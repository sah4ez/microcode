package service

import (
	"errors"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"
)

// ErrTooManyLoginAttempts is returned when the per-IP rate limit is exceeded.
var ErrTooManyLoginAttempts = errors.New("too many login attempts")

// loginRateLimit is the max login attempts per IP per window.
var loginRateLimit int

func init() {
	loginRateLimit = 10
	if v := os.Getenv("AUTH_LOGIN_RATE"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			loginRateLimit = n
		}
	}
}

// loginRateWindow is the time window for rate limiting.
const loginRateWindow = 15 * time.Minute

// rateLimiter tracks per-IP request counts in a sliding window.
type rateLimiter struct {
	mu    sync.Mutex
	counts map[string]*rateEntry
}

type rateEntry struct {
	count int
	exp   time.Time
}

// globalLoginLimiter is the per-IP rate limiter for login attempts.
var globalLoginLimiter = &rateLimiter{counts: make(map[string]*rateEntry)}

// Allow checks if the given IP is within the rate limit. If not, returns
// ErrTooManyLoginAttempts.
func (rl *rateLimiter) Allow(ip string) error {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	entry, ok := rl.counts[ip]
	if !ok || now.After(entry.exp) {
		rl.counts[ip] = &rateEntry{count: 1, exp: now.Add(loginRateWindow)}
		return nil
	}
	if entry.count >= loginRateLimit {
		return ErrTooManyLoginAttempts
	}
	entry.count++
	return nil
}

// RateLimitStatus returns the remaining attempts for an IP, or -1 if limited.
func (rl *rateLimiter) RateLimitStatus(ip string) (remaining int, resetIn time.Duration) {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	entry, ok := rl.counts[ip]
	if !ok || now.After(entry.exp) {
		return loginRateLimit, 0
	}
	remaining = loginRateLimit - entry.count
	if remaining < 0 {
		remaining = 0
	}
	resetIn = time.Until(entry.exp)
	if resetIn < 0 {
		resetIn = 0
	}
	return
}

// _ = http.StatusOK (keeps net/http import used)
var _ = http.StatusOK
