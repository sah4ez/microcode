// Package service implements the todo business logic behind the generated
// transport. It validates input, applies PATCH merge semantics, and delegates
// persistence to storage.Repository. It contains no HTTP or SQL code.
package service

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/loki/todoservice/contracts/dto"
	"github.com/loki/todoservice/internal/storage"
)

// ErrEmptyTitle is returned when Create/Update is given a blank title. The HTTP
// layer maps it to 422.
var ErrEmptyTitle = errors.New("title is required")

// APIError is a JSON-serializable application error carrying an HTTP status.
// The generated transport sets the response status via Code() and encodes the
// body — the exported Message field renders as {"error": "..."} and the
// unexported code never leaks to the client.
type APIError struct {
	Message string `json:"error"`
	code    int
}

// Error implements error.
func (e *APIError) Error() string { return e.Message }

// Code lets the generated transport pick the HTTP status (see withErrorCode).
func (e *APIError) Code() int { return e.code }

// NewAPIError wraps a message and HTTP status into an APIError.
func NewAPIError(message string, code int) *APIError {
	return &APIError{Message: message, code: code}
}

// HTTPError maps a domain error into an *APIError so the generated transport
// can set the HTTP status and emit {"error": "..."}. Known domain errors map to
// their semantic codes; anything else collapses to an opaque 500 so internal
// details (e.g. SQL text) never reach the client. Wire it via
// `srv.TodoService().WithErrorHandler(service.HTTPError)`.
func HTTPError(err error) error {
	switch {
	case errors.Is(err, storage.ErrNotFound):
		return NewAPIError("todo not found", http.StatusNotFound)
	case errors.Is(err, ErrEmptyTitle):
		return NewAPIError("title is required", http.StatusUnprocessableEntity)
	default:
		return NewAPIError("internal server error", http.StatusInternalServerError)
	}
}

// Service implements contracts.TodoService over a storage.Repository.
type Service struct {
	repo storage.Repository
	now  func() time.Time
}

// Option configures a Service.
type Option func(*Service)

// WithClock overrides the clock used for created_at (useful in tests).
func WithClock(fn func() time.Time) Option {
	return func(s *Service) { s.now = fn }
}

// New returns a Service backed by repo.
func New(repo storage.Repository, opts ...Option) *Service {
	s := &Service{repo: repo, now: time.Now}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Create validates and stores a new todo. It returns ErrEmptyTitle (→422) when
// the title is blank; the repository assigns the id and the service stamps
// created_at as an RFC3339 UTC string.
func (s *Service) Create(_ context.Context, title string, description string) (dto.Todo, error) {
	title = strings.TrimSpace(title)
	if title == "" {
		return dto.Todo{}, ErrEmptyTitle
	}
	t := dto.Todo{
		Title:       title,
		Description: description,
		Completed:   false,
		CreatedAt:   s.now().UTC().Format(time.RFC3339),
	}
	return s.repo.Create(context.Background(), t)
}

// List returns every stored todo.
func (s *Service) List(_ context.Context) ([]dto.Todo, error) {
	return s.repo.List(context.Background())
}

// Get returns a single todo by id (storage.ErrNotFound → 404).
func (s *Service) Get(_ context.Context, id int64) (dto.Todo, error) {
	return s.repo.Get(context.Background(), id)
}

// Update applies PATCH-style partial updates: nil pointers keep the existing
// value; a non-nil but blank title is rejected with ErrEmptyTitle (→422).
func (s *Service) Update(_ context.Context, id int64, title *string, description *string, completed *bool) (dto.Todo, error) {
	t, err := s.repo.Get(context.Background(), id)
	if err != nil {
		return dto.Todo{}, err
	}
	if title != nil {
		nt := strings.TrimSpace(*title)
		if nt == "" {
			return dto.Todo{}, ErrEmptyTitle
		}
		t.Title = nt
	}
	if description != nil {
		t.Description = *description
	}
	if completed != nil {
		t.Completed = *completed
	}
	return s.repo.Update(context.Background(), t)
}

// Delete removes a todo by id (storage.ErrNotFound → 404 on miss).
func (s *Service) Delete(_ context.Context, id int64) error {
	return s.repo.Delete(context.Background(), id)
}

// Toggle flips the completed flag of a todo and returns the updated item.
func (s *Service) Toggle(_ context.Context, id int64) (dto.Todo, error) {
	t, err := s.repo.Get(context.Background(), id)
	if err != nil {
		return dto.Todo{}, err
	}
	t.Completed = !t.Completed
	return s.repo.Update(context.Background(), t)
}
