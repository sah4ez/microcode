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

	got, err := repo.Create(context.Background(), dto.Todo{Title: "buy milk", Description: "2L", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if got.ID == 0 {
		t.Fatal("expected server-assigned id")
	}
	if got.Completed {
		t.Errorf("new todo should be incomplete, got completed=true")
	}

	got2, err := repo.Get(context.Background(), got.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got2.Title != "buy milk" || got2.Description != "2L" || got2.CreatedAt != ts {
		t.Errorf("round-trip mismatch: %+v", got2)
	}
}

func TestRepo_GetMissing_returnsErrNotFound(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	_, err := repo.Get(context.Background(), 999)
	if !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestRepo_List_emptyAndOrdered(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	all, err := repo.List(context.Background())
	if err != nil {
		t.Fatalf("list empty: %v", err)
	}
	if len(all) != 0 {
		t.Errorf("want empty slice, got %d", len(all))
	}

	for _, title := range []string{"a", "b", "c"} {
		if _, err := repo.Create(context.Background(), dto.Todo{Title: title, CreatedAt: ts}); err != nil {
			t.Fatalf("create %q: %v", title, err)
		}
	}
	all, err = repo.List(context.Background())
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("want 3, got %d", len(all))
	}
	if all[0].Title != "a" || all[2].Title != "c" {
		t.Errorf("not ordered by id: %v %v", all[0].Title, all[2].Title)
	}
}

func TestRepo_Update(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	created, err := repo.Create(context.Background(), dto.Todo{Title: "old", Description: "od", CreatedAt: ts})
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
	got, _ := repo.Get(context.Background(), created.ID)
	if got.Title != "new" || !got.Completed {
		t.Errorf("update not persisted: %+v", got)
	}

	if _, err := repo.Update(context.Background(), dto.Todo{ID: 999, Title: "x", CreatedAt: ts}); !errors.Is(err, storage.ErrNotFound) {
		t.Fatalf("update missing: want ErrNotFound, got %v", err)
	}
}

func TestRepo_Delete(t *testing.T) {
	db, repo := openDB(t, filepath.Join(t.TempDir(), "t.db"))
	defer db.Close()

	created, err := repo.Create(context.Background(), dto.Todo{Title: "bye", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := repo.Delete(context.Background(), created.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if _, err := repo.Get(context.Background(), created.ID); !errors.Is(err, storage.ErrNotFound) {
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

	// session 1: create
	db1, repo1 := openDB(t, dbPath)
	created, err := repo1.Create(context.Background(), dto.Todo{Title: "persist me", Description: "across restart", CreatedAt: ts})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := db1.Close(); err != nil {
		t.Fatalf("close session 1: %v", err)
	}

	// session 2: reopen the SAME file; Migrate is idempotent
	db2, repo2 := openDB(t, dbPath)
	defer db2.Close()

	got, err := repo2.Get(context.Background(), created.ID)
	if err != nil {
		t.Fatalf("reopen get: %v", err)
	}
	if got.Title != "persist me" || got.Description != "across restart" {
		t.Fatalf("data did not survive reopen: %+v", got)
	}
}
