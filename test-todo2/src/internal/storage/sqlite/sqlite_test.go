package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"testing"

	"github.com/loki/todoservice/contracts/dto"
	"github.com/loki/todoservice/internal/storage"

	_ "modernc.org/sqlite"
)

const ts = "2026-08-02T05:24:00Z"

// openDB opens a SQLite file at path and returns a migrated repository. The
// caller owns closing the returned *sql.DB.
func openDB(t *testing.T, path string) (*sql.DB, *Repo) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		t.Fatalf("pragma: %v", err)
	}
	repo := New(db)
	if err := repo.Migrate(context.Background()); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return db, repo
}

func TestRepo_CreateAndGet(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	got, err := repo.Create(context.Background(), dto.Todo{LkID: 1, Title: "buy milk", Description: "2L", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if got.ID == 0 {
		t.Fatal("expected server-assigned id")
	}
	if got.LkID != 1 {
		t.Errorf("lk_id = %d, want 1", got.LkID)
	}
	if got.Completed {
		t.Errorf("new todo should be incomplete, got completed=true")
	}

	got2, err := repo.Get(context.Background(), 1, got.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got2.Title != "buy milk" || got2.Description != "2L" || got2.LkID != 1 || got2.CreatedAt != ts {
		t.Errorf("round-trip mismatch: %+v", got2)
	}
}

func TestRepo_GetMissing_returnsErrNotFound(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	if _, err := repo.Get(context.Background(), 1, 999); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

// TestRepo_Get_isCabinetScoped proves x-lk-id is an access-control key: a todo
// in cabinet 1 is invisible (ErrNotFound) when queried under cabinet 2.
func TestRepo_Get_isCabinetScoped(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	created, err := repo.Create(context.Background(), dto.Todo{LkID: 1, Title: "secret", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if _, err := repo.Get(context.Background(), 2, created.ID); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("cross-cabinet get must be ErrNotFound, got %v", err)
	}
	// GetByID (used by Update/Toggle) is NOT cabinet-scoped and must still find it.
	got, err := repo.GetByID(context.Background(), created.ID)
	if err != nil || got.LkID != 1 {
		t.Fatalf("GetByID should find it regardless of cabinet: %v %+v", err, got)
	}
}

func TestRepo_List_emptyAndOrdered(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	all, err := repo.List(context.Background(), 1)
	if err != nil {
		t.Fatalf("list empty: %v", err)
	}
	if len(all) != 0 {
		t.Errorf("want empty slice, got %d", len(all))
	}

	for _, title := range []string{"a", "b", "c"} {
		if _, err := repo.Create(context.Background(), dto.Todo{LkID: 1, Title: title, CreatedAt: ts}); err != nil {
			t.Fatalf("create %q: %v", title, err)
		}
	}
	// a todo in a different cabinet must NOT appear in cabinet 1's list
	if _, err := repo.Create(context.Background(), dto.Todo{LkID: 2, Title: "other", CreatedAt: ts}); err != nil {
		t.Fatalf("create other: %v", err)
	}
	all, err = repo.List(context.Background(), 1)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("want 3 (cabinet-scoped), got %d", len(all))
	}
	if all[0].Title != "a" || all[2].Title != "c" {
		t.Errorf("not ordered by id: %v %v", all[0].Title, all[2].Title)
	}
}

func TestRepo_Update(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	created, err := repo.Create(context.Background(), dto.Todo{LkID: 1, Title: "old", Description: "od", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	created.Title = "new"
	created.Description = "nd"
	created.Completed = true
	updated, err := repo.Update(context.Background(), created)
	if err != nil {
		t.Fatalf("update: %v", err)
	}
	if !updated.Completed || updated.Title != "new" {
		t.Errorf("update result mismatch: %+v", updated)
	}
	got, _ := repo.Get(context.Background(), 1, created.ID)
	if got.Title != "new" || !got.Completed {
		t.Errorf("update not persisted: %+v", got)
	}

	if _, err := repo.Update(context.Background(), dto.Todo{ID: 999, LkID: 1, Title: "x", CreatedAt: ts}); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("update missing: want ErrNotFound, got %v", err)
	}
}

func TestRepo_Delete(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	created, err := repo.Create(context.Background(), dto.Todo{LkID: 1, Title: "bye", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := repo.Delete(context.Background(), created.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if _, err := repo.Get(context.Background(), 1, created.ID); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("get after delete: want ErrNotFound, got %v", err)
	}
	if err := repo.Delete(context.Background(), created.ID); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("delete missing: want ErrNotFound, got %v", err)
	}
}

// TestRepo_persistsAcrossReopen is the load-bearing non-functional test: data
// written in one DB session must survive closing the file and reopening it.
func TestRepo_persistsAcrossReopen(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "todos.db")

	// session 1: create a cabinet + a todo in it
	db1, repo1 := openDB(t, dbPath)
	prof, err := repo1.CreateProfile(context.Background(), dto.PersonalProfile{Name: "работа", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create profile: %v", err)
	}
	created, err := repo1.Create(context.Background(), dto.Todo{LkID: prof.ID, Title: "persist me", Description: "across restart", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := db1.Close(); err != nil {
		t.Fatalf("close session 1: %v", err)
	}

	// session 2: reopen the SAME file; Migrate is idempotent
	db2, repo2 := openDB(t, dbPath)
	defer db2.Close()

	got, err := repo2.Get(context.Background(), prof.ID, created.ID)
	if err != nil {
		t.Fatalf("reopen get: %v", err)
	}
	if got.Title != "persist me" || got.Description != "across restart" || got.LkID != prof.ID {
		t.Fatalf("data did not survive reopen: %+v", got)
	}
}

// TestRepo_profiles exercises the ЛК CRUD against the separate personal_profiles
// table.
func TestRepo_profiles(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "p.db"))
	defer db.Close()

	p1, err := repo.CreateProfile(context.Background(), dto.PersonalProfile{Name: "работа", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create p1: %v", err)
	}
	if p1.ID == 0 {
		t.Fatal("expected server-assigned profile id")
	}
	p2, err := repo.CreateProfile(context.Background(), dto.PersonalProfile{Name: "дом", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create p2: %v", err)
	}

	all, err := repo.ListProfiles(context.Background())
	if err != nil {
		t.Fatalf("list profiles: %v", err)
	}
	if len(all) != 2 || all[0].Name != "работа" || all[1].Name != "дом" {
		t.Errorf("profile list mismatch: %+v", all)
	}

	got, err := repo.GetProfile(context.Background(), p1.ID)
	if err != nil || got.Name != "работа" {
		t.Fatalf("get profile: %v %+v", err, got)
	}

	newName := "office"
	updated, err := repo.UpdateProfile(context.Background(), dto.PersonalProfile{ID: p1.ID, Name: newName, CreatedAt: ts})
	if err != nil || updated.Name != newName {
		t.Fatalf("update profile: %v %+v", err, updated)
	}

	if _, err := repo.GetProfile(context.Background(), 999); !errors.Is(err, storage.ErrProfileNotFound) {
		t.Errorf("missing profile: want ErrProfileNotFound, got %v", err)
	}
	if err := repo.DeleteProfile(context.Background(), p2.ID); err != nil {
		t.Fatalf("delete profile: %v", err)
	}
	if err := repo.DeleteProfile(context.Background(), p2.ID); !errors.Is(err, storage.ErrProfileNotFound) {
		t.Errorf("delete missing profile: want ErrProfileNotFound, got %v", err)
	}
}

// TestRepo_Migrate_dropsLegacyTodos proves "все старые данные удалить и создать с
// нуля": a pre-cabinet todos table (no lk_id) is dropped and rebuilt, so the
// old data is gone and the new lk_id column is present.
func TestRepo_Migrate_dropsLegacyTodos(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "legacy.db")
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	// simulate the OLD schema (no lk_id) with some data
	if _, err := db.Exec(`CREATE TABLE todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, completed INTEGER, created_at TEXT);`); err != nil {
		t.Fatalf("seed legacy table: %v", err)
	}
	if _, err := db.Exec(`INSERT INTO todos (title, description, completed, created_at) VALUES ('legacy', 'old', 0, '2020');`); err != nil {
		t.Fatalf("seed legacy row: %v", err)
	}
	db.Close()

	// reopen through the repo: Migrate must detect the missing lk_id, drop, rebuild
	db2, repo := openDB(t, dbPath)
	defer db2.Close()

	var cnt int64
	if err := db2.QueryRow(`SELECT count(1) FROM todos`).Scan(&cnt); err != nil {
		t.Fatalf("count after migrate: %v", err)
	}
	if cnt != 0 {
		t.Errorf("legacy data should be wiped on migrate, got %d rows", cnt)
	}
	// new schema must accept lk_id
	if _, err := repo.Create(context.Background(), dto.Todo{LkID: 7, Title: "new", CreatedAt: ts}); err != nil {
		t.Fatalf("create on migrated schema: %v", err)
	}
}
