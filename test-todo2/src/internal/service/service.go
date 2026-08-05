// Package service implements the todo + personal-cabinet business logic behind
// the generated transport. It validates input, applies PATCH merge semantics,
// and delegates persistence to storage.Store. It contains no HTTP or SQL code.
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

// ErrEmptyName is returned when a cabinet is created/updated with a blank name.
// The HTTP layer maps it to 422.
var ErrEmptyName = errors.New("name is required")

// ErrMissingCabinet is returned when a todo create/list/get request carries no
// (or an invalid) x-lk-id cabinet id. The HTTP layer maps it to 400. The
// x-lk-id header is the access key that scopes a request to a single cabinet.
var ErrMissingCabinet = errors.New("x-lk-id header is required")

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
// `srv.TodoService().WithErrorHandler(service.HTTPError)` and
// `srv.PersonalProfileService().WithErrorHandler(service.HTTPError)`.
func HTTPError(err error) error {
	switch {
	case errors.Is(err, storage.ErrNotFound):
		return NewAPIError("todo not found", http.StatusNotFound)
	case errors.Is(err, storage.ErrProfileNotFound):
		return NewAPIError("personal profile not found", http.StatusNotFound)
	case errors.Is(err, ErrEmptyTitle):
		return NewAPIError("title is required", http.StatusUnprocessableEntity)
	case errors.Is(err, ErrEmptyName):
		return NewAPIError("name is required", http.StatusUnprocessableEntity)
	case errors.Is(err, ErrMissingCabinet):
		return NewAPIError("x-lk-id header is required", http.StatusBadRequest)
	default:
		return NewAPIError("internal server error", http.StatusInternalServerError)
	}
}

// Service implements contracts.TodoService AND contracts.PersonalProfileService
// over a storage.Store (todos are cabinet-scoped; cabinets are managed via the
// same store).
type Service struct {
	store storage.Store
	now   func() time.Time
}

// Option configures a Service.
type Option func(*Service)

// WithClock overrides the clock used for created_at (useful in tests).
func WithClock(fn func() time.Time) Option {
	return func(s *Service) { s.now = fn }
}

// New returns a Service backed by store.
func New(store storage.Store, opts ...Option) *Service {
	s := &Service{store: store, now: time.Now}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Create validates and stores a new todo in the cabinet identified by lkId (from
// the x-lk-id header). It returns ErrMissingCabinet (→400) when lkId is absent
// and ErrEmptyTitle (→422) when the title is blank; the repository assigns the
// id and the service stamps created_at as an RFC3339 UTC string.
func (s *Service) Create(_ context.Context, lkId int64, title string, description string) (dto.Todo, error) {
	if lkId <= 0 {
		return dto.Todo{}, ErrMissingCabinet
	}
	title = strings.TrimSpace(title)
	if title == "" {
		return dto.Todo{}, ErrEmptyTitle
	}
	t := dto.Todo{
		LkID:        lkId,
		Title:       title,
		Description: description,
		Completed:   false,
		CreatedAt:   s.now().UTC().Format(time.RFC3339),
	}
	return s.store.Create(context.Background(), t)
}

// List returns every todo that belongs to the cabinet lkId (ErrMissingCabinet
// →400 when the header is absent).
func (s *Service) List(_ context.Context, lkId int64) ([]dto.Todo, error) {
	if lkId <= 0 {
		return nil, ErrMissingCabinet
	}
	return s.store.List(context.Background(), lkId)
}

// Get returns a single todo by id, but only if it belongs to lkId
// (storage.ErrNotFound → 404, including when it belongs to another cabinet).
func (s *Service) Get(_ context.Context, lkId int64, id int64) (dto.Todo, error) {
	if lkId <= 0 {
		return dto.Todo{}, ErrMissingCabinet
	}
	return s.store.Get(context.Background(), lkId, id)
}

// Update applies PATCH-style partial updates: nil pointers keep the existing
// value; a non-nil but blank title is rejected with ErrEmptyTitle (→422).
// Update operates by the global todo id (todos are globally unique); it is not
// cabinet-scoped (only Create/List/Get require x-lk-id).
func (s *Service) Update(_ context.Context, id int64, title *string, description *string, completed *bool) (dto.Todo, error) {
	t, err := s.store.GetByID(context.Background(), id)
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
	return s.store.Update(context.Background(), t)
}

// Delete removes a todo by id (storage.ErrNotFound → 404 on miss).
func (s *Service) Delete(_ context.Context, id int64) error {
	return s.store.Delete(context.Background(), id)
}

// Toggle flips the completed flag of a todo and returns the updated item.
func (s *Service) Toggle(_ context.Context, id int64) (dto.Todo, error) {
	t, err := s.store.GetByID(context.Background(), id)
	if err != nil {
		return dto.Todo{}, err
	}
	t.Completed = !t.Completed
	return s.store.Update(context.Background(), t)
}

// --- personal cabinets (ЛК) ---

// ProfileService implements contracts.PersonalProfileService over the same
// storage.Store. It is a distinct type from Service because both contracts
// define methods named Create/List/Get/Update/Delete with incompatible
// signatures, so one Go type cannot satisfy both.
type ProfileService struct {
	store storage.Store
	now   func() time.Time
}

// ProfileOption configures a ProfileService.
type ProfileOption func(*ProfileService)

// WithProfileClock overrides the clock used for created_at (useful in tests).
func WithProfileClock(fn func() time.Time) ProfileOption {
	return func(s *ProfileService) { s.now = fn }
}

// NewProfile returns a ProfileService backed by store.
func NewProfile(store storage.Store, opts ...ProfileOption) *ProfileService {
	p := &ProfileService{store: store, now: time.Now}
	for _, opt := range opts {
		opt(p)
	}
	return p
}

// Create validates and stores a new cabinet; returns ErrEmptyName (→422) when
// the name is blank.
func (s *ProfileService) Create(_ context.Context, name string) (dto.PersonalProfile, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return dto.PersonalProfile{}, ErrEmptyName
	}
	p := dto.PersonalProfile{
		Name:      name,
		CreatedAt: s.now().UTC().Format(time.RFC3339),
	}
	return s.store.CreateProfile(context.Background(), p)
}

// List returns every cabinet.
func (s *ProfileService) List(_ context.Context) ([]dto.PersonalProfile, error) {
	return s.store.ListProfiles(context.Background())
}

// Get returns a single cabinet by id (storage.ErrProfileNotFound → 404).
func (s *ProfileService) Get(_ context.Context, id int64) (dto.PersonalProfile, error) {
	return s.store.GetProfile(context.Background(), id)
}

// Update applies a PATCH-style rename; nil name keeps the existing value while
// a non-nil blank name is rejected with ErrEmptyName (→422).
func (s *ProfileService) Update(_ context.Context, id int64, name *string) (dto.PersonalProfile, error) {
	p, err := s.store.GetProfile(context.Background(), id)
	if err != nil {
		return dto.PersonalProfile{}, err
	}
	if name != nil {
		nn := strings.TrimSpace(*name)
		if nn == "" {
			return dto.PersonalProfile{}, ErrEmptyName
		}
		p.Name = nn
	}
	return s.store.UpdateProfile(context.Background(), p)
}

// Delete removes a cabinet by id (storage.ErrProfileNotFound → 404).
func (s *ProfileService) Delete(_ context.Context, id int64) error {
	return s.store.DeleteProfile(context.Background(), id)
}
