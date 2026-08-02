// Package storage defines the persistence boundary for todos.
// SQL lives only in internal/storage/sqlite; the service depends on this
// interface, never on database/sql.
package storage

import (
	"context"
	"errors"

	"github.com/loki/todoservice/contracts/dto"
)

// ErrNotFound is returned when no todo exists for the requested id. The
// repository maps sql.ErrNoRows to this sentinel; the HTTP layer maps it to 404.
var ErrNotFound = errors.New("todo not found")

// Repository is the storage contract the todo service depends on.
type Repository interface {
	// Create persists a new todo (ignoring any incoming ID) and returns it
	// with the server-assigned ID.
	Create(ctx context.Context, t dto.Todo) (dto.Todo, error)
	// List returns every stored todo ordered by id.
	List(ctx context.Context) ([]dto.Todo, error)
	// Get returns a single todo by id, or ErrNotFound.
	Get(ctx context.Context, id int64) (dto.Todo, error)
	// Update overwrites the stored fields of the todo identified by t.ID.
	// It returns ErrNotFound when the id does not exist.
	Update(ctx context.Context, t dto.Todo) (dto.Todo, error)
	// Delete removes a todo by id. Missing id returns ErrNotFound.
	Delete(ctx context.Context, id int64) error
}
