// Package sqlite implements storage.Store over a pure-Go SQLite driver
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

// Repo is a SQLite-backed storage.Store (todos + personal cabinets).
type Repo struct {
	db *sql.DB
}

// New returns a repository backed by db. Call Migrate once (idempotent) before
// first use to ensure the schema exists.
func New(db *sql.DB) *Repo {
	return &Repo{db: db}
}

// Migrate brings the schema up to the ЛК-aware layout. Idempotent across
// restarts.
//
// "Все старые данные удалить и создать с нуля": todos from the pre-cabinet
// schema (a todos table WITHOUT the lk_id column) are incompatible with the new
// cabinet-scoped model, so an old todos table is dropped and rebuilt from
// scratch. An already-migrated table (lk_id present) is left untouched, so data
// still survives a restart. personal_profiles is created if absent.
func (r *Repo) Migrate(ctx context.Context) error {
	if _, err := r.db.ExecContext(ctx, createUsersSQL); err != nil {
		return fmt.Errorf("create users table: %w", err)
	}
	if _, err := r.db.ExecContext(ctx, createProfilesSQL); err != nil {
		return fmt.Errorf("create personal_profiles table: %w", err)
	}
	todosExists, err := r.tableExists(ctx, "todos")
	if err != nil {
		return fmt.Errorf("check todos table: %w", err)
	}
	if todosExists {
		hasLkID, err := r.columnExists(ctx, "todos", "lk_id")
		if err != nil {
			return fmt.Errorf("check todos.lk_id: %w", err)
		}
		if !hasLkID { // legacy pre-cabinet schema → rebuild from scratch
			if _, err := r.db.ExecContext(ctx, `DROP TABLE todos`); err != nil {
				return fmt.Errorf("drop legacy todos table: %w", err)
			}
			todosExists = false
		}
	}
	if !todosExists {
		if _, err := r.db.ExecContext(ctx, createTodosSQL); err != nil {
			return fmt.Errorf("create todos table: %w", err)
		}
	}
	return nil
}

const (
	createUsersSQL = `CREATE TABLE IF NOT EXISTS users (
		id            INTEGER PRIMARY KEY AUTOINCREMENT,
		email         TEXT    NOT NULL UNIQUE,
		password_hash TEXT    NOT NULL,
		created_at    TEXT    NOT NULL,
		deleted_at    TEXT
	);`

	createProfilesSQL = `CREATE TABLE IF NOT EXISTS personal_profiles (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		name        TEXT    NOT NULL,
		created_at  TEXT    NOT NULL
	);`
	createTodosSQL = `CREATE TABLE IF NOT EXISTS todos (
		id          INTEGER PRIMARY KEY AUTOINCREMENT,
		lk_id       INTEGER NOT NULL,
		title       TEXT    NOT NULL,
		description TEXT    NOT NULL DEFAULT '',
		completed   INTEGER NOT NULL DEFAULT 0,
		created_at  TEXT    NOT NULL
	);`

	insertTodoSQL = `INSERT INTO todos (lk_id, title, description, completed, created_at) VALUES (?, ?, ?, ?, ?)`
	listTodoSQL   = `SELECT id, lk_id, title, description, completed, created_at FROM todos WHERE lk_id = ? ORDER BY id`
	getTodoSQL     = `SELECT id, lk_id, title, description, completed, created_at FROM todos WHERE id = ? AND lk_id = ?`
	getTodoByIDSQL = `SELECT id, lk_id, title, description, completed, created_at FROM todos WHERE id = ?`
	updateTodoSQL = `UPDATE todos SET title = ?, description = ?, completed = ?, created_at = ? WHERE id = ?`
	deleteTodoSQL = `DELETE FROM todos WHERE id = ?`

	insertProfileSQL = `INSERT INTO personal_profiles (name, created_at) VALUES (?, ?)`
	insertUserSQL    = `INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)`
	getUserByEmailSQL = `SELECT id, email, password_hash, created_at, deleted_at FROM users WHERE email = ? AND deleted_at IS NULL`
	getUserByIDSQL   = `SELECT id, email, password_hash, created_at, deleted_at FROM users WHERE id = ?`
	listProfileSQL   = `SELECT id, name, created_at FROM personal_profiles ORDER BY id`
	getProfileSQL    = `SELECT id, name, created_at FROM personal_profiles WHERE id = ?`
	updateProfileSQL = `UPDATE personal_profiles SET name = ?, created_at = ? WHERE id = ?`
	deleteProfileSQL = `DELETE FROM personal_profiles WHERE id = ?`
)

// tableExists reports whether a table named by name is present.
func (r *Repo) tableExists(ctx context.Context, name string) (bool, error) {
	var n int64
	err := r.db.QueryRowContext(ctx,
		`SELECT count(1) FROM sqlite_master WHERE type = 'table' AND name = ?`, name,
	).Scan(&n)
	if err != nil {
		return false, err
	}
	return n > 0, nil
}

// columnExists reports whether column is present on table.
func (r *Repo) columnExists(ctx context.Context, table, column string) (bool, error) {
	rows, err := r.db.QueryContext(ctx, fmt.Sprintf(`PRAGMA table_info(%s)`, table))
	if err != nil {
		return false, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid int64
		var cname, ctype string
		var notnull, pk int64
		var dflt sql.NullString
		if err := rows.Scan(&cid, &cname, &ctype, &notnull, &dflt, &pk); err != nil {
			return false, err
		}
		if cname == column {
			return true, nil
		}
	}
	return false, rows.Err()
}

// Create persists t in its cabinet (t.LkID) and returns it with the
// server-assigned ID. Parameters are bound (never interpolated), so untrusted
// title/description are safe.
func (r *Repo) Create(ctx context.Context, t dto.Todo) (dto.Todo, error) {
	res, err := r.db.ExecContext(ctx, insertTodoSQL, t.LkID, t.Title, t.Description, boolToInt(t.Completed), t.CreatedAt)
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

// List returns every todo that belongs to cabinet lkID, ordered by id (empty
// slice, not nil, when none).
func (r *Repo) List(ctx context.Context, lkID int64) ([]dto.Todo, error) {
	rows, err := r.db.QueryContext(ctx, listTodoSQL, lkID)
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

// Get returns a single todo by id, but only if it belongs to lkID; otherwise
// storage.ErrNotFound. Scoping by lkID is the access-control boundary: a todo
// in another cabinet looks the same as a missing todo (404, no leakage).
func (r *Repo) Get(ctx context.Context, lkID int64, id int64) (dto.Todo, error) {
	t, err := scanTodo(r.db.QueryRowContext(ctx, getTodoSQL, id, lkID))
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return dto.Todo{}, storage.ErrNotFound
		}
		return dto.Todo{}, fmt.Errorf("query todo %d: %w", id, err)
	}
	return t, nil
}

// GetByID returns a single todo by its global id (no cabinet filter); used by
// Update/Toggle which are not cabinet-scoped. Missing id → storage.ErrNotFound.
func (r *Repo) GetByID(ctx context.Context, id int64) (dto.Todo, error) {
	t, err := scanTodo(r.db.QueryRowContext(ctx, getTodoByIDSQL, id))
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
	res, err := r.db.ExecContext(ctx, updateTodoSQL, t.Title, t.Description, boolToInt(t.Completed), t.CreatedAt, t.ID)
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
	res, err := r.db.ExecContext(ctx, deleteTodoSQL, id)
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

// --- personal cabinets (ЛК) ---

// CreateProfile persists p and returns it with the server-assigned ID.
func (r *Repo) CreateProfile(ctx context.Context, p dto.PersonalProfile) (dto.PersonalProfile, error) {
	res, err := r.db.ExecContext(ctx, insertProfileSQL, p.Name, p.CreatedAt)
	if err != nil {
		return dto.PersonalProfile{}, fmt.Errorf("insert profile: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return dto.PersonalProfile{}, fmt.Errorf("insert profile id: %w", err)
	}
	p.ID = id
	return p, nil
}

// ListProfiles returns every cabinet ordered by id (empty slice, not nil).
func (r *Repo) ListProfiles(ctx context.Context) ([]dto.PersonalProfile, error) {
	rows, err := r.db.QueryContext(ctx, listProfileSQL)
	if err != nil {
		return nil, fmt.Errorf("query profiles: %w", err)
	}
	defer rows.Close()

	out := make([]dto.PersonalProfile, 0)
	for rows.Next() {
		p, err := scanProfile(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate profiles: %w", err)
	}
	return out, nil
}

// GetProfile returns a single cabinet by id; sql.ErrNoRows → ErrProfileNotFound.
func (r *Repo) GetProfile(ctx context.Context, id int64) (dto.PersonalProfile, error) {
	p, err := scanProfile(r.db.QueryRowContext(ctx, getProfileSQL, id))
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return dto.PersonalProfile{}, storage.ErrProfileNotFound
		}
		return dto.PersonalProfile{}, fmt.Errorf("query profile %d: %w", id, err)
	}
	return p, nil
}

// UpdateProfile overwrites the stored name; a missing id yields ErrProfileNotFound.
func (r *Repo) UpdateProfile(ctx context.Context, p dto.PersonalProfile) (dto.PersonalProfile, error) {
	res, err := r.db.ExecContext(ctx, updateProfileSQL, p.Name, p.CreatedAt, p.ID)
	if err != nil {
		return dto.PersonalProfile{}, fmt.Errorf("update profile %d: %w", p.ID, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return dto.PersonalProfile{}, fmt.Errorf("update profile %d rows: %w", p.ID, err)
	}
	if n == 0 {
		return dto.PersonalProfile{}, storage.ErrProfileNotFound
	}
	return p, nil
}

// DeleteProfile removes a cabinet by id; a missing id yields ErrProfileNotFound.
func (r *Repo) DeleteProfile(ctx context.Context, id int64) error {
	res, err := r.db.ExecContext(ctx, deleteProfileSQL, id)
	if err != nil {
		return fmt.Errorf("delete profile %d: %w", id, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("delete profile %d rows: %w", id, err)
	}
	if n == 0 {
		return storage.ErrProfileNotFound
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
	if err := s.Scan(&t.ID, &t.LkID, &t.Title, &t.Description, &completed, &t.CreatedAt); err != nil {
		return dto.Todo{}, err
	}
	t.Completed = completed != 0
	return t, nil
}

func scanProfile(s scanner) (dto.PersonalProfile, error) {
	var p dto.PersonalProfile
	if err := s.Scan(&p.ID, &p.Name, &p.CreatedAt); err != nil {
		return dto.PersonalProfile{}, err
	}
	return p, nil
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// --- users ---

// CreateUser persists u and returns it with the server-assigned ID.
func (r *Repo) CreateUser(ctx context.Context, u storage.UserRecord) (storage.UserRecord, error) {
	res, err := r.db.ExecContext(ctx, insertUserSQL, u.Email, u.PasswordHash, u.CreatedAt)
	if err != nil {
		return storage.UserRecord{}, fmt.Errorf("insert user: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return storage.UserRecord{}, fmt.Errorf("insert user id: %w", err)
	}
	u.ID = id
	return u, nil
}

// GetUserByEmail returns a non-deleted user by email; sql.ErrNoRows → ErrUserNotFound.
func (r *Repo) GetUserByEmail(ctx context.Context, email string) (storage.UserRecord, error) {
	u, err := scanUser(r.db.QueryRowContext(ctx, getUserByEmailSQL, email))
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return storage.UserRecord{}, storage.ErrUserNotFound
		}
		return storage.UserRecord{}, fmt.Errorf("query user by email %s: %w", email, err)
	}
	return u, nil
}

// GetUserByID returns a user by id (including deleted ones); sql.ErrNoRows → ErrUserNotFound.
func (r *Repo) GetUserByID(ctx context.Context, id int64) (storage.UserRecord, error) {
	u, err := scanUser(r.db.QueryRowContext(ctx, getUserByIDSQL, id))
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return storage.UserRecord{}, storage.ErrUserNotFound
		}
		return storage.UserRecord{}, fmt.Errorf("query user %d: %w", id, err)
	}
	return u, nil
}

func scanUser(s scanner) (storage.UserRecord, error) {
	var u storage.UserRecord
	if err := s.Scan(&u.ID, &u.Email, &u.PasswordHash, &u.CreatedAt, &u.DeletedAt); err != nil {
		return storage.UserRecord{}, err
	}
	return u, nil
}
