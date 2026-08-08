package service

import (
	"errors"
	"regexp"
	"unicode"
)

var (
	// ErrWeakPassword is returned when a password fails strength validation.
	ErrWeakPassword = errors.New("password must be at least 8 characters and contain at least one uppercase letter, one lowercase letter, and one digit")

	// ErrEmailRequired is returned when email is empty.
	ErrEmailRequired = errors.New("email is required")

	// ErrPasswordRequired is returned when password is empty.
	ErrPasswordRequired = errors.New("password is required")

	// ErrInvalidEmail is returned when email format is invalid.
	ErrInvalidEmail = errors.New("invalid email format")
)

// emailRe is a simple email format validator.
var emailRe = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)

// ValidatePassword checks password strength: >=8 chars, at least one upper,
// one lower, one digit.
func ValidatePassword(password string) error {
	if len(password) < 8 {
		return ErrWeakPassword
	}
	var hasUpper, hasLower, hasDigit bool
	for _, r := range password {
		switch {
		case unicode.IsUpper(r):
			hasUpper = true
		case unicode.IsLower(r):
			hasLower = true
		case unicode.IsDigit(r):
			hasDigit = true
		}
	}
	if !hasUpper || !hasLower || !hasDigit {
		return ErrWeakPassword
	}
	return nil
}

// ValidateEmail checks that email is non-empty and matches a basic format.
func ValidateEmail(email string) error {
	if email == "" {
		return ErrEmailRequired
	}
	if !emailRe.MatchString(email) {
		return ErrInvalidEmail
	}
	return nil
}
