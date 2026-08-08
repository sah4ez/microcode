package service

import (
	"context"
	"strings"
	"time"

	"github.com/loki/todoservice/contracts/dto"
	"github.com/loki/todoservice/internal/storage"
	"golang.org/x/crypto/bcrypt"
)

// AuthService implements contracts.UserService (register, login, refresh, me, csrf).
type AuthService struct {
	store storage.Store
	now   func() time.Time
}

// AuthOption configures an AuthService.
type AuthOption func(*AuthService)

// WithAuthClock overrides the clock used for created_at (useful in tests).
func WithAuthClock(fn func() time.Time) AuthOption {
	return func(s *AuthService) { s.now = fn }
}

// NewAuth returns an AuthService backed by store.
func NewAuth(store storage.Store, opts ...AuthOption) *AuthService {
	s := &AuthService{store: store, now: time.Now}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Register creates a new user account. Returns the user (without password) and
// an initial JWT token pair.
func (s *AuthService) Register(_ context.Context, email, password string) (dto.RegisterResponse, error) {
	email = strings.TrimSpace(strings.ToLower(email))
	if err := ValidateEmail(email); err != nil {
		return dto.RegisterResponse{}, err
	}
	if err := ValidatePassword(password); err != nil {
		return dto.RegisterResponse{}, err
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return dto.RegisterResponse{}, err
	}

	user := storage.UserRecord{
		Email:        email,
		PasswordHash: string(hash),
		CreatedAt:    s.now().UTC().Format(time.RFC3339),
	}
	created, err := s.store.CreateUser(context.Background(), user)
	if err != nil {
		// Check for UNIQUE constraint violation (duplicate email).
		if strings.Contains(err.Error(), "UNIQUE constraint") {
			return dto.RegisterResponse{}, storage.ErrDuplicateEmail
		}
		return dto.RegisterResponse{}, err
	}

	tokens, err := GenerateTokenPair(created.ID)
	if err != nil {
		return dto.RegisterResponse{}, err
	}

	return dto.RegisterResponse{
		User: dto.User{
			ID:        created.ID,
			Email:     created.Email,
			CreatedAt: created.CreatedAt,
		},
		Tokens: tokens,
	}, nil
}

// Login authenticates a user by email + password. Subject to per-IP rate limiting.
func (s *AuthService) Login(ctx context.Context, email, password string) (dto.TokenPair, error) {
	email = strings.TrimSpace(strings.ToLower(email))

	// Rate limit check (IP from context).
	ip, _ := ctx.Value(contextKeyIP).(string)
	if ip != "" {
		if err := globalLoginLimiter.Allow(ip); err != nil {
			return dto.TokenPair{}, err
		}
	}

	if err := ValidateEmail(email); err != nil {
		return dto.TokenPair{}, err
	}

	user, err := s.store.GetUserByEmail(context.Background(), email)
	if err != nil {
		return dto.TokenPair{}, storage.ErrUserNotFound
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		return dto.TokenPair{}, storage.ErrUserNotFound
	}

	return GenerateTokenPair(user.ID)
}

// Refresh exchanges a valid refresh token for a new token pair (rotation).
func (s *AuthService) Refresh(_ context.Context, refreshToken string) (dto.TokenPair, error) {
	claims, err := ParseAndValidateRefreshToken(refreshToken)
	if err != nil {
		return dto.TokenPair{}, ErrInvalidRefreshToken
	}

	// Verify user still exists and is not deleted.
	user, err := s.store.GetUserByID(context.Background(), claims.UserID)
	if err != nil {
		return dto.TokenPair{}, ErrInvalidRefreshToken
	}
	if user.DeletedAt != nil {
		return dto.TokenPair{}, storage.ErrUserDeleted
	}

	// Revoke old refresh token (rotation).
	RevokeRefreshToken(claims.ID)

	return GenerateTokenPair(claims.UserID)
}

// Me returns the authenticated user's profile. The user ID is extracted from
// the context (set by the auth middleware).
func (s *AuthService) Me(ctx context.Context) (dto.User, error) {
	userID, ok := ctx.Value(contextKeyUserID).(int64)
	if !ok || userID == 0 {
		return dto.User{}, ErrUnauthorized
	}

	user, err := s.store.GetUserByID(context.Background(), userID)
	if err != nil {
		return dto.User{}, err
	}
	if user.DeletedAt != nil {
		return dto.User{}, storage.ErrUserDeleted
	}

	return dto.User{
		ID:        user.ID,
		Email:     user.Email,
		CreatedAt: user.CreatedAt,
	}, nil
}

// Csrf returns a new CSRF token.
func (s *AuthService) Csrf(_ context.Context) (dto.CsrfResponse, error) {
	return dto.CsrfResponse{CsrfToken: GenerateCSRFToken()}, nil
}

// Context keys for auth data.
type contextKey string

const (
	contextKeyUserID contextKey = "user_id"
	contextKeyIP     contextKey = "client_ip"
)
