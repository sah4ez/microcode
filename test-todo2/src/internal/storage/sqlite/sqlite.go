// Package sqlite implements storage.Repository over a pure-Go SQLite driver
// (modernc.org/sqlite, no CGO). It owns all SQL in the project.
package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/loki/todoservice/contracts/dto"
	"github.com/loki/todoservice/internal/storage"
)

// Repo is a SQLite-backed storage.Repository.
type Repo struct {
	db *sql.DB
}

// New returns a repository backed by db. Call Migrate once (idempotent) before
// first use to ensure the schema exists.
func New(db *sql.DB) *Repo {
	return &Repo{db: db}
}

// Migrate creates the todos table if it does not already exist. Safe to call on
// every startup, including across restarts against an existing DB file.
func (r *Repo) Migrate(ctx context.Context) error {
	const q = `CREATE TABLE IF NOT EXISTS todos (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		title       TEXT    NOT NULL,
		description TEXT    NOT NULL DEFAULT '',
		completed   INTEGER NOT NULL DEFAULT 0,
		created_at  TEXT    NOT NULL
	);`
	if _, err := r.db.ExecContext(ctx, q); err != nil {
		return fmt.Errorf("create todos table: %w", err)
	}
	return nil
}

const (
	insertSQL = `INSERT INTO todos (title, description, completed, created_at) VALUES (?, ?, ?, ?)`
	listSQL   = `SELECT id, title, description, completed, created_at FROM todos ORDER BY id`
	getSQL    = `SELECT id, title, description, completed, created_at FROM todos WHERE id = ?`
	updateSQL = `UPDATE todos SET title = ?, description = ?, completed = ?, created_at = ? WHERE id = ?`
	deleteSQL = `DELETE FROM todos WHERE id = ?`
)

// Create persists t and returns it with the server-assigned ID. Parameters are
// bound (never interpolated), so untrusted title/description are safe.
func (r *Repo) Create(ctx context.Context, t dto.Todo) (dto.Todo, error) {
	res, err := r.db.ExecContext(ctx, insertSQL, t.Title, t.Description, boolToInt(t.Completed), t.CreatedAt)
	if err != nil {
		return dto.Todo{}, fmt.Errorf("insert todo: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return dto.Todo{}, fmt.Errorf("insert todo id: %w", err)
	}
	t.ID = id
	return t, nil
}

// List returns every stored todo ordered by id (empty slice, not nil, when none).
func (r *Repo) List(ctx context.Context) ([]dto.Todo, error) {
	rows, err := r.db.QueryContext(ctx, listSQL)
	if err != nil {
		return nil, fmt.Errorf("query todos: %w", err)
	}
	defer rows.Close()

	out := make([]dto.Todo, 0)
	for rows.Next() {
		t, err := scanTodo(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate todos: %w", err)
	}
	return out, nil
}

// Get returns a single todo by id; sql.ErrNoRows is mapped to storage.ErrNotFound.
func (r *Repo) Get(ctx context.Context, id int64) (dto.Todo, error) {
	t, err := scanTodo(r.db.QueryRowContext(ctx, getSQL, id))
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return dto.Todo{}, storage.ErrNotFound
		}
		return dto.Todo{}, fmt.Errorf("query todo %d: %w", id, err)
	}
	return t, nil
}

// Update overwrites the stored todo; a missing id yields storage.ErrNotFound.
func (r *Repo) Update(ctx context.Context, t dto.Todo) (dto.Todo, error) {
	res, err := r.db.ExecContext(ctx, updateSQL, t.Title, t.Description, boolToInt(t.Completed), t.CreatedAt, t.ID)
	if err != nil {
		return dto.Todo{}, fmt.Errorf("update todo %d: %w", t.ID, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return dto.Todo{}, fmt.Errorf("update todo %d rows: %w", t.ID, err)
	}
	if n == 0 {
		return dto.Todo{}, storage.ErrNotFound
	}
	return t, nil
}

// Delete removes a todo by id; a missing id yields storage.ErrNotFound.
func (r *Repo) Delete(ctx context.Context, id int64) error {
	res, err := r.db.ExecContext(ctx, deleteSQL, id)
	if err != nil {
		return fmt.Errorf("delete todo %d: %w", id, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("delete todo %d rows: %w", id, err)
	}
	if n == 0 {
		return storage.ErrNotFound
	}
	return nil
}

// scanner is satisfied by both *sql.Row and *sql.Rows.
type scanner interface {
	Scan(dest ...any) error
}

func scanTodo(s scanner) (dto.Todo, error) {
	var t dto.Todo
	var completed int
	if err := s.Scan(&t.ID, &t.Title, &t.Description, &completed, &t.CreatedAt); err != nil {
		return dto.Todo{}, err
	}
	t.Completed = completed != 0
	return t, nil
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
