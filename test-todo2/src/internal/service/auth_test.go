package service

import (
	"database/sql"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/loki/todoservice/internal/storage"
	"github.com/loki/todoservice/internal/storage/sqlite"

	_ "modernc.org/sqlite"
)

// newAuthSvc wires the auth service over a fresh temp SQLite file with a fixed clock.
func newAuthSvc(t *testing.T) (*AuthService, func()) {
	t.Helper()
	db, err := sql.Open("sqlite", filepath.Join(t.TempDir(), "auth.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	repo := sqlite.New(db)
	if err := repo.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	fixed := time.Date(2026, 8, 8, 12, 0, 0, 0, time.UTC)
	return NewAuth(repo, WithAuthClock(func() time.Time { return fixed })), func() { _ = db.Close() }
}

func TestAuthService_Register_and_Login(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	resp, err := svc.Register(ctx, "user@example.com", "Password1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	if resp.User.ID == 0 {
		t.Error("expected server-assigned user id")
	}
	if resp.User.Email != "user@example.com" {
		t.Errorf("email = %q, want user@example.com", resp.User.Email)
	}
	if resp.Tokens.AccessToken == "" || resp.Tokens.RefreshToken == "" {
		t.Error("expected tokens")
	}

	// Duplicate email
	_, err = svc.Register(ctx, "user@example.com", "Password1")
	if !errors.Is(err, storage.ErrDuplicateEmail) {
		t.Errorf("duplicate: want ErrDuplicateEmail, got %v", err)
	}

	// Login correct
	tokens, err := svc.Login(ctx, "user@example.com", "Password1")
	if err != nil || tokens.AccessToken == "" {
		t.Fatalf("login: %v", err)
	}

	// Login wrong password
	_, err = svc.Login(ctx, "user@example.com", "WrongPass1")
	if !errors.Is(err, storage.ErrUserNotFound) {
		t.Errorf("wrong pw: want ErrUserNotFound, got %v", err)
	}

	// Login nonexistent
	_, err = svc.Login(ctx, "noone@example.com", "Password1")
	if !errors.Is(err, storage.ErrUserNotFound) {
		t.Errorf("no user: want ErrUserNotFound, got %v", err)
	}
}

func TestAuthService_Refresh(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	resp, err := svc.Register(ctx, "user@example.com", "Password1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}

	newTokens, err := svc.Refresh(ctx, resp.Tokens.RefreshToken)
	if err != nil {
		t.Fatalf("refresh: %v", err)
	}
	if newTokens.AccessToken == "" || newTokens.RefreshToken == "" {
		t.Error("refresh: expected tokens")
	}

	// Old token revoked
	_, err = svc.Refresh(ctx, resp.Tokens.RefreshToken)
	if !errors.Is(err, ErrInvalidRefreshToken) {
		t.Errorf("revoked: want ErrInvalidRefreshToken, got %v", err)
	}

	// Invalid token
	_, err = svc.Refresh(ctx, "bad-token")
	if !errors.Is(err, ErrInvalidRefreshToken) {
		t.Errorf("invalid: want ErrInvalidRefreshToken, got %v", err)
	}
}

func TestAuthService_Me(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	resp, err := svc.Register(ctx, "user@example.com", "Password1")
	if err != nil {
		t.Fatalf("register: %v", err)
	}

	authCtx := SetUserID(ctx, resp.User.ID)
	user, err := svc.Me(authCtx)
	if err != nil || user.Email != "user@example.com" {
		t.Fatalf("me: %v %+v", err, user)
	}

	// No user_id in context
	_, err = svc.Me(ctx)
	if !errors.Is(err, ErrUnauthorized) {
		t.Errorf("no ctx: want ErrUnauthorized, got %v", err)
	}
}

func TestAuthService_PasswordValidation(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	tests := []struct{ pw string; want bool }{
		{"Password1", true},
		{"Short1", false},
		{"password1", false},
		{"PASSWORD1", false},
		{"Passwordx", false},
		{"Pass1", false},
	}
	for _, tt := range tests {
		_, err := svc.Register(ctx, "pw@example.com", tt.pw)
		got := err == nil
		if got != tt.want {
			t.Errorf("ValidatePassword(%q): got=%v want=%v err=%v", tt.pw, got, tt.want, err)
		}
	}
}

func TestAuthService_EmailValidation(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	_, err := svc.Register(ctx, "", "Password1")
	if !errors.Is(err, ErrEmailRequired) {
		t.Errorf("empty email: want ErrEmailRequired, got %v", err)
	}

	_, err = svc.Register(ctx, "not-an-email", "Password1")
	if !errors.Is(err, ErrInvalidEmail) {
		t.Errorf("bad email: want ErrInvalidEmail, got %v", err)
	}
}

func TestAuthService_Csrf(t *testing.T) {
	svc, cleanup := newAuthSvc(t)
	defer cleanup()

	resp, err := svc.Csrf(ctx)
	if err != nil || resp.CsrfToken == "" {
		t.Fatalf("csrf: %v", err)
	}
	if !ValidateCSRFToken(resp.CsrfToken) {
		t.Error("token should be valid")
	}
	if ValidateCSRFToken(resp.CsrfToken) {
		t.Error("token should be consumed after first use")
	}
}

func TestValidatePassword(t *testing.T) {
	for _, tt := range []struct{ pw string; want bool }{
		{"Password1", true}, {"Short1", false}, {"password1", false},
		{"PASSWORD1", false}, {"Passwordx", false}, {"", false},
	} {
		got := ValidatePassword(tt.pw) == nil
		if got != tt.want {
			t.Errorf("ValidatePassword(%q) = %v, want %v", tt.pw, got, tt.want)
		}
	}
}

func TestAuthHTTPError_mapsStatusCodes(t *testing.T) {
	for _, c := range []struct {
		name string; in error; code int; msg string
	}{
		{"invalid token", ErrInvalidToken, 401, "invalid or expired token"},
		{"unauthorized", ErrUnauthorized, 401, "authorization required"},
		{"weak password", ErrWeakPassword, 422, "password must be at least 8 characters and contain at least one uppercase letter, one lowercase letter, and one digit"},
		{"email required", ErrEmailRequired, 422, "email is required"},
		{"duplicate email", storage.ErrDuplicateEmail, 409, "email already registered"},
		{"user not found", storage.ErrUserNotFound, 401, "invalid email or password"},
		{"rate limit", ErrTooManyLoginAttempts, 429, "too many login attempts"},
		{"invalid refresh", ErrInvalidRefreshToken, 401, "invalid or revoked refresh token"},
		{"invalid csrf", ErrInvalidCSRF, 403, "invalid CSRF token"},
	} {
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
