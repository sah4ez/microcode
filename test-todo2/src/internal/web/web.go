// Package web serves the vanilla-JS todo UI from embedded static assets on the
// same fiber app that owns the generated API transport. The three asset routes
// (/ , /styles.css, /app.js) are registered AFTER the @tg contract routes by
// the caller, so the API (/todos...) always wins.
//
// The caller supplies the embed.FS that contains the static/ tree (embedded at
// the project root, next to the static/ directory, so go:embed resolves it).
// There is no user-controlled path parameter on any of these handlers, so
// there is no path-traversal surface; each route returns one fixed file with a
// correct, browser-friendly Content-Type.
package web

import (
	"embed"
	"path/filepath"

	"github.com/gofiber/fiber/v2"
)

// asset reads one embedded file and writes it with the right Content-Type.
// key is a fixed path into the embedded tree (e.g. "static/index.html"); never
// user input.
func asset(c *fiber.Ctx, staticFS embed.FS, key, contentType string) error {
	data, err := staticFS.ReadFile(key)
	if err != nil {
		return c.SendStatus(fiber.StatusNotFound)
	}
	c.Set("Content-Type", contentType)
	c.Set("Cache-Control", "no-cache")
	return c.Send(data)
}

// Register wires the UI asset routes onto app, reading from the embedded
// static/ tree in staticFS. It MUST be called after the generated @tg contract
// routes so /, /styles.css and /app.js fall through behind every /todos... API
// route.
func Register(app *fiber.App, staticFS embed.FS) {
	app.Get("/login", func(c *fiber.Ctx) error {
		return asset(c, staticFS, filepath.Join("static", "login.html"), "text/html; charset=utf-8")
	})
	app.Get("/", func(c *fiber.Ctx) error {
		return asset(c, staticFS, filepath.Join("static", "index.html"), "text/html; charset=utf-8")
	})
	app.Get("/styles.css", func(c *fiber.Ctx) error {
		return asset(c, staticFS, filepath.Join("static", "styles.css"), "text/css; charset=utf-8")
	})
	app.Get("/app.js", func(c *fiber.Ctx) error {
		return asset(c, staticFS, filepath.Join("static", "app.js"), "text/javascript; charset=utf-8")
	})
}


