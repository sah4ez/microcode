package dto

// User is a registered user. The password hash is never included in
// responses; only ID, email, and timestamps are exposed.
//
// @tg desc=`A registered user (password never exposed)`
type User struct {
	// ID is the unique, server-assigned identifier.
	// @tg desc=`Unique user identifier`
	ID int64 `json:"id"`

	// Email is the unique login email.
	// @tg desc=`User email address (unique)`
	Email string `json:"email"`

	// CreatedAt is the RFC3339 (UTC) creation timestamp.
	// @tg desc=`Registration timestamp (RFC3339, UTC)`
	CreatedAt string `json:"created_at"`
}

// TokenPair holds an access + refresh JWT pair returned by login/refresh.
//
// @tg desc=`JWT token pair (access + refresh)`
type TokenPair struct {
	// AccessToken is the short-lived JWT used in Authorization: Bearer headers.
	// @tg desc=`Short-lived access JWT`
	AccessToken string `json:"access_token"`

	// RefreshToken is the longer-lived JWT used to obtain new token pairs.
	// @tg desc=`Long-lived refresh JWT`
	RefreshToken string `json:"refresh_token"`
}

// RegisterResponse is returned by POST /auth/register: the created user
// (without password) plus the initial token pair.
//
// @tg desc=`Registration response: user + tokens`
type RegisterResponse struct {
	// @tg desc=`Created user`
	User User `json:"user"`
	// @tg desc=`Initial token pair`
	Tokens TokenPair `json:"tokens"`
}

// CsrfResponse is returned by GET /auth/csrf.
//
// @tg desc=`CSRF token response`
type CsrfResponse struct {
	// @tg desc=`CSRF token for double-submit`
	CsrfToken string `json:"csrf_token"`
}
