package service

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"net/http"
	"os"
	"sync"
	"time"
)

var (
	// ErrInvalidCSRF is returned when the CSRF token doesn't match.
	ErrInvalidCSRF = errors.New("invalid CSRF token")

	// csrfSecret is the HMAC key for CSRF token generation.
	csrfSecret []byte
)

func init() {
	csrfSecret = []byte(os.Getenv("AUTH_CSRF_SECRET"))
	if len(csrfSecret) == 0 {
		csrfSecret = make([]byte, 32)
		if _, err := rand.Read(csrfSecret); err != nil {
			panic("generate CSRF secret: " + err.Error())
		}
	}
}

// csrfStore tracks issued CSRF tokens in-memory.
var csrfStore sync.Map

// GenerateCSRFToken creates a new CSRF token and stores it with an expiry.
func GenerateCSRFToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic("generate CSRF token: " + err.Error())
	}
	token := hex.EncodeToString(b)
	csrfStore.Store(token, time.Now().Add(1*time.Hour))
	return token
}

// ValidateCSRFToken checks if the token exists in the store and hasn't expired.
// If valid, it is consumed (one-time use).
func ValidateCSRFToken(token string) bool {
	if token == "" {
		return false
	}
	val, ok := csrfStore.LoadAndDelete(token)
	if !ok {
		return false
	}
	exp, ok := val.(time.Time)
	if !ok {
		return false
	}
	return time.Now().Before(exp)
}

// _ = http.StatusForbidden (keeps import used)
var _ = http.StatusForbidden
