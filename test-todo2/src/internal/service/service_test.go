package service

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/loki/todoservice/internal/storage"
	"github.com/loki/todoservice/internal/storage/sqlite"

	_ "modernc.org/sqlite"
)

var ctx = context.Background()

// newSvc wires the service over a fresh temp SQLite file with a fixed clock so
// created_at is deterministic. Uses the real repository (no mocks).
func newSvc(t *testing.T) (*Service, func()) {
	t.Helper()
	db, err := sql.Open("sqlite", filepath.Join(t.TempDir(), "svc.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	repo := sqlite.New(db)
	if err := repo.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	fixed := time.Date(2026, 8, 2, 5, 24, 0, 0, time.UTC)
	return New(repo, WithClock(func() time.Time { return fixed })), func() { _ = db.Close() }
}

func TestService_Create_rejectsBlankTitle(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	if _, err := svc.Create(ctx, 1, "   ", "d"); !errors.Is(err, ErrEmptyTitle) {
		t.Fatalf("blank title: want ErrEmptyTitle, got %v", err)
	}
}

func TestService_Create_requiresCabinet(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	// x-lk-id missing (lkId <= 0) → ErrMissingCabinet before title is checked.
	if _, err := svc.Create(ctx, 0, "ok", "d"); !errors.Is(err, ErrMissingCabinet) {
		t.Fatalf("missing cabinet: want ErrMissingCabinet, got %v", err)
	}
	if _, err := svc.List(ctx, 0); !errors.Is(err, ErrMissingCabinet) {
		t.Fatalf("list missing cabinet: want ErrMissingCabinet, got %v", err)
	}
}

func TestService_Create_stampsFields(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	got, err := svc.Create(ctx, 1, "  trimmed  ", "desc")
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if got.LkID != 1 {
		t.Errorf("lk_id = %d, want 1", got.LkID)
	}
	if got.Title != "trimmed" {
		t.Errorf("title not trimmed: %q", got.Title)
	}
	if got.Completed {
		t.Error("new todo must be incomplete")
	}
	if got.CreatedAt != "2026-08-02T05:24:00Z" {
		t.Errorf("created_at = %q, want RFC3339 fixed stamp", got.CreatedAt)
	}
	if got.ID == 0 {
		t.Error("id not assigned")
	}
}

func TestService_Update_patchMerge(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	base, err := svc.Create(ctx, 1, "title", "desc")
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	completed := true
	updated, err := svc.Update(ctx, base.ID, nil, nil, &completed)
	if err != nil {
		t.Fatalf("update completed: %v", err)
	}
	if !updated.Completed || updated.Title != "title" || updated.Description != "desc" {
		t.Errorf("PATCH should only touch completed: %+v", updated)
	}

	newDesc := "changed"
	updated, err = svc.Update(ctx, base.ID, nil, &newDesc, nil)
	if err != nil {
		t.Fatalf("update desc: %v", err)
	}
	if updated.Description != "changed" || !updated.Completed {
		t.Errorf("merge lost state: %+v", updated)
	}

	blank := "   "
	if _, err := svc.Update(ctx, base.ID, &blank, nil, nil); !errors.Is(err, ErrEmptyTitle) {
		t.Errorf("blank title patch: want ErrEmptyTitle, got %v", err)
	}

	title := "x"
	if _, err := svc.Update(ctx, 999, &title, nil, nil); !errors.Is(err, storage.ErrNotFound) {
		t.Errorf("update missing: want ErrNotFound, got %v", err)
	}
}

func TestService_Toggle_flipsState(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	base, err := svc.Create(ctx, 1, "toggle me", "")
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	on, err := svc.Toggle(ctx, base.ID)
	if err != nil {
		t.Fatalf("toggle 1: %v", err)
	}
	if !on.Completed {
		t.Error("first toggle should complete")
	}
	off, err := svc.Toggle(ctx, base.ID)
	if err != nil {
		t.Fatalf("toggle 2: %v", err)
	}
	if off.Completed {
		t.Error("second toggle should un-complete")
	}
	if _, err := svc.Toggle(ctx, 999); !errors.Is(err, storage.ErrNotFound) {
		t.Errorf("toggle missing: want ErrNotFound, got %v", err)
	}
}

func TestService_GetAndDelete_propagateNotFound(t *testing.T) {
	svc, cleanup := newSvc(t)
	defer cleanup()

	if _, err := svc.Get(ctx, 1, 1); !errors.Is(err, storage.ErrNotFound) {
		t.Errorf("get missing: want ErrNotFound, got %v", err)
	}
	if err := svc.Delete(ctx, 1); !errors.Is(err, storage.ErrNotFound) {
		t.Errorf("delete missing: want ErrNotFound, got %v", err)
	}
}

func TestHTTPError_mapsStatusCodes(t *testing.T) {
	cases := []struct {
		name string
		in   error
		code int
		msg  string
	}{
		{"not found", storage.ErrNotFound, 404, "todo not found"},
		{"profile not found", storage.ErrProfileNotFound, 404, "personal profile not found"},
		{"empty title", ErrEmptyTitle, 422, "title is required"},
		{"empty name", ErrEmptyName, 422, "name is required"},
		{"missing cabinet", ErrMissingCabinet, 400, "x-lk-id header is required"},
		{"unknown", errors.New("database is locked"), 500, "internal server error"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			api, ok := HTTPError(c.in).(*APIError)
			if !ok {
				t.Fatalf("HTTPError did not return *APIError")
			}
			if api.Code() != c.code {
				t.Errorf("code = %d, want %d", api.Code(), c.code)
			}
			if api.Message != c.msg {
				t.Errorf("message = %q, want %q", api.Message, c.msg)
			}
		})
	}
}

// --- personal cabinet (ЛК) service tests ---

// newProfileSvc wires the profile service over a fresh temp SQLite file with a
// fixed clock so created_at is deterministic. Shares the same store as the todo
// service would.
func newProfileSvc(t *testing.T) (*ProfileService, func()) {
	t.Helper()
	db, err := sql.Open("sqlite", filepath.Join(t.TempDir(), "svc.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	repo := sqlite.New(db)
	if err := repo.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	fixed := time.Date(2026, 8, 2, 5, 24, 0, 0, time.UTC)
	return NewProfile(repo, WithProfileClock(func() time.Time { return fixed })), func() { _ = db.Close() }
}

func TestService_ProfileCRUD(t *testing.T) {
	psvc, cleanup := newProfileSvc(t)
	defer cleanup()

	p, err := psvc.Create(ctx, "  работа  ")
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if p.Name != "работа" {
		t.Errorf("name not trimmed: %q", p.Name)
	}
	if p.ID == 0 || p.CreatedAt != "2026-08-02T05:24:00Z" {
		t.Errorf("unexpected profile: %+v", p)
	}

	_, _ = psvc.Create(ctx, "дом")
	all, err := psvc.List(ctx)
	if err != nil || len(all) != 2 {
		t.Fatalf("list: %v len=%d", err, len(all))
	}

	got, err := psvc.Get(ctx, p.ID)
	if err != nil || got.Name != "работа" {
		t.Fatalf("get: %v %+v", err, got)
	}

	rename := "office"
	updated, err := psvc.Update(ctx, p.ID, &rename)
	if err != nil || updated.Name != "office" {
		t.Fatalf("update: %v %+v", err, updated)
	}
	blank := "   "
	if _, err := psvc.Update(ctx, p.ID, &blank); !errors.Is(err, ErrEmptyName) {
		t.Errorf("blank name update: want ErrEmptyName, got %v", err)
	}
	if _, err := psvc.Update(ctx, 999, &rename); !errors.Is(err, storage.ErrProfileNotFound) {
		t.Errorf("update missing: want ErrProfileNotFound, got %v", err)
	}

	if _, err := psvc.Create(ctx, "   "); !errors.Is(err, ErrEmptyName) {
		t.Errorf("blank name create: want ErrEmptyName, got %v", err)
	}
	if _, err := psvc.Get(ctx, 999); !errors.Is(err, storage.ErrProfileNotFound) {
		t.Errorf("get missing: want ErrProfileNotFound, got %v", err)
	}
	if err := psvc.Delete(ctx, p.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if err := psvc.Delete(ctx, p.ID); !errors.Is(err, storage.ErrProfileNotFound) {
		t.Errorf("delete missing: want ErrProfileNotFound, got %v", err)
	}
}
