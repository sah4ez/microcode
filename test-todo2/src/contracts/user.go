// Package contracts declares the user service (auth) API as a @tg-annotated Go
// interface. The HTTP (fiber) transport is GENERATED from this contract by
// `tg server -o internal/transport`; business logic lives in internal/service.
package contracts

import (
	"context"

	"github.com/loki/todoservice/contracts/dto"
)

// @tg title=`User Service`
// @tg version=`1.0.0`
// @tg desc=`User authentication: registration, login, refresh, and profile.`
// @tg http-server
type UserService interface {
	// Register creates a new user account with the given email and password.
	// Password is validated (8+ chars, upper/lower/digit) and stored as bcrypt hash.
	// Returns the user (without password) and an initial JWT token pair.
	//
	// @tg http-method=POST
	// @tg http-path=`/auth/register`
	// @tg http-success=201
	// @tg enableInlineSingle
	// @tg summary=`Register a new user`
	// @tg email.required
	// @tg email.desc=`User email (unique)`
	// @tg password.required
	// @tg password.desc=`Password (min 8 chars, upper+lower+digit)`
	Register(ctx context.Context, email string, password string) (resp dto.RegisterResponse, err error)

	// Login authenticates a user by email and password. On success, returns a
	// JWT token pair (access + refresh). Subject to per-IP rate limiting.
	//
	// @tg http-method=POST
	// @tg http-path=`/auth/login`
	// @tg http-success=200
	// @tg enableInlineSingle
	// @tg summary=`Authenticate and get tokens`
	// @tg email.required
	// @tg email.desc=`User email`
	// @tg password.required
	// @tg password.desc=`User password`
	Login(ctx context.Context, email string, password string) (tokens dto.TokenPair, err error)

	// Refresh exchanges a valid refresh token for a new token pair (access +
	// refresh rotation). The old refresh token is invalidated.
	//
	// @tg http-method=POST
	// @tg http-path=`/auth/refresh`
	// @tg http-success=200
	// @tg enableInlineSingle
	// @tg summary=`Refresh token pair`
	// @tg refreshToken.required
	// @tg refreshToken.desc=`Refresh JWT`
	Refresh(ctx context.Context, refreshToken string) (tokens dto.TokenPair, err error)

	// Me returns the authenticated user's profile (id, email, created_at).
	// The user identity is extracted from the JWT in the Authorization header
	// (set by the auth middleware into the request context).
	//
	// @tg http-method=GET
	// @tg http-path=`/auth/me`
	// @tg http-success=200
	// @tg enableInlineSingle
	// @tg summary=`Get current user profile`
	Me(ctx context.Context) (user dto.User, err error)

	// Csrf returns a CSRF token for the double-submit cookie pattern.
	// The token is also set as a non-HttpOnly cookie so the browser sends it
	// back. POST /auth/register requires the same token in the X-CSRF-Token header.
	//
	// @tg http-method=GET
	// @tg http-path=`/auth/csrf`
	// @tg http-success=200
	// @tg enableInlineSingle
	// @tg summary=`Get CSRF token`
	Csrf(ctx context.Context) (resp dto.CsrfResponse, err error)
}
