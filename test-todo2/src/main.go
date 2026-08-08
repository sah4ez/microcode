// Command todoservice is a minimal todo-list REST API persisted to SQLite.
//
// The HTTP transport is GENERATED from the @tg contract in contracts/ by
// `tg server -o internal/transport` (github.com/seniorGolang/tg/v3 + go-fiber).
// This file only wires the generated transport to the hand-written service and
// SQLite repository, then serves on 0.0.0.0:8000 with graceful shutdown.
package main

import (
	"context"
	"database/sql"
	"embed"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "modernc.org/sqlite" // pure-Go SQLite driver (no CGO), registers "sqlite"

	"github.com/loki/todoservice/internal/service"
	"github.com/loki/todoservice/internal/storage/sqlite"
	"github.com/loki/todoservice/internal/transport"
	"github.com/loki/todoservice/internal/web"
)

// staticFS embeds the web UI (static/index.html, app.js, styles.css) into the
// binary so the service ships as a single self-contained artifact. web.Register
// serves these three files from this embed.FS on the same fiber app as the API.
//
//go:embed static/*
var staticFS embed.FS

const (
	dataDir = "./data"
	dbPath  = "./data/todos.db"
	addr    = "0.0.0.0:8000"
)

func main() {
	log := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	if err := run(log); err != nil {
		log.Error("server failed", slog.Any("error", err))
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	// Local persistence: auto-create the data dir and SQLite file.
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return errors.Join(errors.New("create data dir"), err)
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return errors.Join(errors.New("open sqlite"), err)
	}
	defer func() {
		_ = db.Close()
	}()

	// WAL + busy_timeout improve durability and concurrent-write behavior.
	for _, pragma := range []string{
		"PRAGMA journal_mode=WAL",
		"PRAGMA busy_timeout=5000",
		"PRAGMA foreign_keys=ON",
	} {
		if _, err := db.Exec(pragma); err != nil {
			return errors.Join(errors.New("apply pragma "+pragma), err)
		}
	}

	repo := sqlite.New(db)
	migCtx, migCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer migCancel()
	if err := repo.Migrate(migCtx); err != nil {
		return errors.Join(errors.New("migrate database"), err)
	}

	svc := service.New(repo)
	profileSvc := service.NewProfile(repo)
	authSvc := service.NewAuth(repo)

	srv := transport.New(log, transport.UserService(authSvc), transport.TodoService(svc), transport.PersonalProfileService(profileSvc))
	// Map domain errors to HTTP status codes with a sanitized body (no internals).
	srv.UserService().WithErrorHandler(service.HTTPError)
	srv.TodoService().WithErrorHandler(service.HTTPError)
	srv.PersonalProfileService().WithErrorHandler(service.HTTPError)

	// Auth middleware: protects /todos and /personal-profile (returns 401).
	// /auth/* routes are public (login, register, refresh, me, csrf).
	srv.Fiber().Use(service.AuthMiddleware())

	// Web UI: serve the vanilla-JS single page from the SAME fiber app that owns
	// the generated transport (no second server). Registered AFTER the @tg
	// contract routes so /todos... always wins and the three asset paths fall
	// through to the static files.
	web.Register(srv.Fiber(), staticFS)

	// Serve until interrupted. Listen blocks, so run it in a goroutine and
	// surface a startup failure via errCh.
	errCh := make(chan error, 1)
	go func() {
		log.Info("todo service listening", slog.String("addr", "http://"+addr))
		if err := srv.Fiber().Listen(addr); err != nil {
			errCh <- err
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	select {
	case err := <-errCh:
		return errors.Join(errors.New("listen"), err)
	case <-stop:
		log.Info("shutdown signal received, draining...")
	}

	// Graceful shutdown: stop accepting connections and finish in-flight
	// requests (the generated transport caps this at 30s), then the deferred
	// db.Close() runs as run() returns.
	if err := srv.Shutdown(); err != nil {
		return errors.Join(errors.New("shutdown"), err)
	}
	return nil
}
