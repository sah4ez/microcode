// Package storage defines the persistence boundary for todos and personal
// cabinets (ЛК). SQL lives only in internal/storage/sqlite; the service depends
// on these interfaces, never on database/sql.
package storage

import (
	"context"
	"errors"

	"github.com/loki/todoservice/contracts/dto"
)

// ErrNotFound is returned when no todo exists for the requested id (or when a
// todo exists but belongs to a different cabinet). The repository maps
// sql.ErrNoRows to this sentinel; the HTTP layer maps it to 404.
var ErrNotFound = errors.New("todo not found")

// ErrProfileNotFound is returned when no personal cabinet exists for the
// requested id. The HTTP layer maps it to 404.
var ErrProfileNotFound = errors.New("personal profile not found")

// Repository is the storage contract for todos. Todos are partitioned by
// cabinet (LkID): Create/List/Get are scoped to a cabinet so a request only
// ever touches its own cabinet's records.
type Repository interface {
	// Create persists a new todo in the cabinet t.LkID and returns it with the
	// server-assigned ID. The caller must set t.LkID (validated upstream).
	Create(ctx context.Context, t dto.Todo) (dto.Todo, error)
	// List returns every todo that belongs to cabinet lkID, ordered by id.
	List(ctx context.Context, lkID int64) ([]dto.Todo, error)
	// Get returns a single todo by id, but only if it belongs to lkID; otherwise
	// ErrNotFound. This is what makes x-lk-id an access-control key: a request
	// for another cabinet's todo looks the same as a missing todo (404).
	Get(ctx context.Context, lkID int64, id int64) (dto.Todo, error)
	// Update overwrites the stored fields of the todo identified by t.ID.
	// It returns ErrNotFound when the id does not exist.
	Update(ctx context.Context, t dto.Todo) (dto.Todo, error)
	// Delete removes a todo by id. Missing id returns ErrNotFound.
	Delete(ctx context.Context, id int64) error
	// GetByID returns a single todo by its global id, regardless of cabinet.
	// Used by Update/Toggle which operate by global id (todos are globally
	// unique) and therefore are not cabinet-scoped. Cabinet scoping applies to
	// Create/List/Get only, per the x-lk-id contract.
	GetByID(ctx context.Context, id int64) (dto.Todo, error)
}

// ProfileRepository is the storage contract for personal cabinets (ЛК).
type ProfileRepository interface {
	// CreateProfile persists a new cabinet and returns it with the
	// server-assigned ID.
	CreateProfile(ctx context.Context, p dto.PersonalProfile) (dto.PersonalProfile, error)
	// ListProfiles returns every cabinet ordered by id.
	ListProfiles(ctx context.Context) ([]dto.PersonalProfile, error)
	// GetProfile returns a single cabinet by id, or ErrProfileNotFound.
	GetProfile(ctx context.Context, id int64) (dto.PersonalProfile, error)
	// UpdateProfile overwrites the stored name of the cabinet identified by p.ID.
	// It returns ErrProfileNotFound when the id does not exist.
	UpdateProfile(ctx context.Context, p dto.PersonalProfile) (dto.PersonalProfile, error)
	// DeleteProfile removes a cabinet by id. Missing id returns ErrProfileNotFound.
	DeleteProfile(ctx context.Context, id int64) error
}

// ErrUserNotFound is returned when no user exists for the requested id or email.
// The HTTP layer maps it to 404.
var ErrUserNotFound = errors.New("user not found")

// ErrUserDeleted is returned when a user exists but has been soft-deleted.
// The HTTP layer maps it to 403.
var ErrUserDeleted = errors.New("user account is deleted")

// ErrDuplicateEmail is returned when a registration attempts to use an email
// already taken by an active (non-deleted) user. The HTTP layer maps it to 409.
var ErrDuplicateEmail = errors.New("email already registered")

// UserRepository is the storage contract for users.
type UserRepository interface {
	// CreateUser persists a new user and returns it with the server-assigned ID.
	CreateUser(ctx context.Context, u UserRecord) (UserRecord, error)
	// GetUserByID returns a user by id, or ErrUserNotFound.
	GetUserByID(ctx context.Context, id int64) (UserRecord, error)
	// GetUserByEmail returns a non-deleted user by email, or ErrUserNotFound.
	GetUserByEmail(ctx context.Context, email string) (UserRecord, error)
}

// UserRecord is the full database row for a user (includes password hash).
// It is never exposed to HTTP responses; only dto.User (without hash) is returned.
type UserRecord struct {
	ID        int64
	Email     string
	PasswordHash string
	CreatedAt string
	DeletedAt *string // nil = active, non-nil = soft-deleted
}

// Store is the combined persistence contract the service depends on: todos,
// cabinets, and users.
type Store interface {
	Repository
	ProfileRepository
	UserRepository
}
