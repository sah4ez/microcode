package service

import (
	"context"
	"strings"

	"github.com/gofiber/fiber/v2"
)

// AuthMiddleware returns a fiber middleware that validates the Bearer token
// on protected routes (/todos/*, /personal-profile/*). All other routes are public.
func AuthMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		path := c.Path()

		// Always set client IP in context (for login rate limiting on /auth/login).
		ctx := SetClientIP(c.UserContext(), c.IP())
		c.SetUserContext(ctx)

		// Only protect todo and profile routes.
		if !isProtectedRoute(path) {
			return c.Next()
		}

		authHeader := string(c.Request().Header.Peek("Authorization"))
		tokenStr, err := ExtractBearerToken(authHeader)
		if err != nil {
			c.Status(fiber.StatusUnauthorized)
			return c.JSON(fiber.Map{"error": "authorization required"})
		}

		claims, err := ParseAndValidateToken(tokenStr)
		if err != nil {
			c.Status(fiber.StatusUnauthorized)
			return c.JSON(fiber.Map{"error": "invalid or expired token"})
		}

		ctx = SetUserID(c.UserContext(), claims.UserID)
		c.SetUserContext(ctx)

		return c.Next()
	}
}

func isProtectedRoute(path string) bool {
	if strings.HasPrefix(path, "/todos") || strings.HasPrefix(path, "/personal-profile") {
		return true
	}
	// /auth/me requires a valid access token to identify the caller.
	if path == "/auth/me" {
		return true
	}
	return false
}

// CSRFMiddleware validates the CSRF token from X-CSRF-Token header against
// the server-side store (one-time use, consumed on validation).
func CSRFMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		token := string(c.Request().Header.Peek("X-CSRF-Token"))
		if token == "" {
			c.Status(fiber.StatusForbidden)
			return c.JSON(fiber.Map{"error": "CSRF token required"})
		}
		if !ValidateCSRFToken(token) {
			c.Status(fiber.StatusForbidden)
			return c.JSON(fiber.Map{"error": "invalid CSRF token"})
		}
		return c.Next()
	}
}

// SetUserID stores the authenticated user's ID in the context.
func SetUserID(ctx context.Context, userID int64) context.Context {
	return context.WithValue(ctx, contextKeyUserID, userID)
}

// GetUserID extracts the authenticated user's ID from the context.
func GetUserID(ctx context.Context) int64 {
	if v, ok := ctx.Value(contextKeyUserID).(int64); ok {
		return v
	}
	return 0
}

// SetClientIP stores the client IP in the context.
func SetClientIP(ctx context.Context, ip string) context.Context {
	return context.WithValue(ctx, contextKeyIP, ip)
}

// GetClientIP extracts the client IP from the context.
func GetClientIP(ctx context.Context) string {
	if v, ok := ctx.Value(contextKeyIP).(string); ok {
		return v
	}
	return ""
}
