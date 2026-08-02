package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"log/slog"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/gofiber/fiber/v2"
	"github.com/loki/todoservice/internal/service"
	"github.com/loki/todoservice/internal/storage/sqlite"
	"github.com/loki/todoservice/internal/transport"

	_ "modernc.org/sqlite"
)

// bootApp stands up the full generated transport on a SQLite file at dbPath and
// returns the fiber app plus a closer that shuts the server + DB down.
func bootApp(t *testing.T, dbPath string) (*fiber.App, func()) {
	t.Helper()
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		t.Fatalf("pragma: %v", err)
	}
	repo := sqlite.New(db)
	if err := repo.Migrate(context.Background()); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	svc := service.New(repo)
	log := slog.New(slog.NewTextHandler(io.Discard, nil)) // quiet tests
	srv := transport.New(log, transport.TodoService(svc))
	srv.TodoService().WithErrorHandler(service.HTTPError)
	return srv.Fiber(), func() {
		_ = srv.Shutdown()
		_ = db.Close()
	}
}

// request fires one HTTP request at the in-process fiber app and returns the
// status code and the decoded JSON body (nil for empty/non-JSON bodies).
func request(t *testing.T, app *fiber.App, method, target, body string) (int, map[string]any) {
	t.Helper()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, target, r)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := app.Test(req, -1)
	if err != nil {
		t.Fatalf("app.Test %s %s: %v", method, target, err)
	}
	raw, _ := io.ReadAll(resp.Body)
	var out map[string]any
	if len(raw) > 0 && strings.Contains(resp.Header.Get("Content-Type"), "json") {
		_ = json.Unmarshal(raw, &out)
	}
	return resp.StatusCode, out
}

// idStr renders a JSON-decoded numeric id (float64) as a path-safe string.
func idStr(v any) string {
	if f, ok := v.(float64); ok {
		return strconv.FormatInt(int64(f), 10)
	}
	return ""
}

func TestHTTP_Create_List_Get(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	code, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"Buy milk","description":"2 liters"}`)
	if code != 201 {
		t.Fatalf("create: want 201, got %d %v", code, body)
	}
	if body["title"] != "Buy milk" {
		t.Errorf("title = %v, want Buy milk", body["title"])
	}
	if body["completed"] != false {
		t.Errorf("completed = %v, want false", body["completed"])
	}
	if body["id"] == nil || body["created_at"] == nil {
		t.Fatalf("missing id/created_at: %v", body)
	}
	id := idStr(body["id"])

	if code, body = request(t, app, fiber.MethodGet, "/todos", ""); code != 200 {
		t.Fatalf("list: want 200, got %d %v", code, body)
	}
	if arr, _ := body["todos"].([]any); len(arr) != 1 {
		t.Fatalf("list: want todos[1], got %v", body)
	}

	if code, body = request(t, app, fiber.MethodGet, "/todos/"+id, ""); code != 200 {
		t.Fatalf("get: want 200, got %d %v", code, body)
	}
	if body["id"] == nil {
		t.Errorf("get missing id: %v", body)
	}
}

func TestHTTP_Create_blankTitle_is422(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()
	code, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"   "}`)
	if code != 422 {
		t.Fatalf("want 422 for blank title, got %d %v", code, body)
	}
	if body["error"] != "title is required" {
		t.Errorf("error = %v, want 'title is required'", body["error"])
	}
}

func TestHTTP_Get_unknown_is404(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()
	code, body := request(t, app, fiber.MethodGet, "/todos/777", "")
	if code != 404 {
		t.Fatalf("want 404, got %d %v", code, body)
	}
	if body["error"] != "todo not found" {
		t.Errorf("error = %v, want 'todo not found'", body["error"])
	}
}

func TestHTTP_Update_patch(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	_, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"old","description":"od"}`)
	id := idStr(body["id"])

	code, body := request(t, app, fiber.MethodPatch, "/todos/"+id, `{"completed":true,"title":"new"}`)
	if code != 200 {
		t.Fatalf("patch: want 200, got %d %v", code, body)
	}
	if body["completed"] != true || body["title"] != "new" || body["description"] != "od" {
		t.Errorf("patch result = %v", body)
	}
	if code, _ := request(t, app, fiber.MethodPatch, "/todos/"+id, `{"title":""}`); code != 422 {
		t.Errorf("blank title patch: want 422, got %d", code)
	}
	if code, _ := request(t, app, fiber.MethodPatch, "/todos/999", `{"completed":true}`); code != 404 {
		t.Errorf("patch missing: want 404, got %d", code)
	}
}

func TestHTTP_Toggle(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	_, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"t"}`)
	id := idStr(body["id"])

	if code, body := request(t, app, fiber.MethodPost, "/todos/"+id+"/toggle", ""); code != 200 || body["completed"] != true {
		t.Fatalf("toggle 1: code=%d body=%v", code, body)
	}
	if code, body := request(t, app, fiber.MethodPost, "/todos/"+id+"/toggle", ""); code != 200 || body["completed"] != false {
		t.Fatalf("toggle 2: code=%d body=%v", code, body)
	}
	if code, _ := request(t, app, fiber.MethodPost, "/todos/999/toggle", ""); code != 404 {
		t.Errorf("toggle missing: want 404, got %d", code)
	}
}

func TestHTTP_Delete(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	_, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"bye"}`)
	id := idStr(body["id"])

	if code, _ := request(t, app, fiber.MethodDelete, "/todos/"+id, ""); code != 204 {
		t.Fatalf("delete: want 204, got %d", code)
	}
	if code, _ := request(t, app, fiber.MethodGet, "/todos/"+id, ""); code != 404 {
		t.Errorf("get after delete: want 404, got %d", code)
	}
	if code, _ := request(t, app, fiber.MethodDelete, "/todos/"+id, ""); code != 404 {
		t.Errorf("delete again: want 404, got %d", code)
	}
}

// TestHTTP_persistsAcrossRestart is the Definition-of-Done persistence test at
// the HTTP layer: create a todo in one server instance, stop it (closing the
// SQLite handle), start a fresh instance on the SAME db file, confirm present.
func TestHTTP_persistsAcrossRestart(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "todos.db")

	app1, close1 := bootApp(t, dbPath)
	_, body := request(t, app1, fiber.MethodPost, "/todos", `{"title":"survive restart"}`)
	id := idStr(body["id"])
	close1() // simulate a clean process restart

	app2, close2 := bootApp(t, dbPath)
	defer close2()

	code, body := request(t, app2, fiber.MethodGet, "/todos/"+id, "")
	if code != 200 {
		t.Fatalf("after restart: want 200, got %d %v", code, body)
	}
	if body["title"] != "survive restart" {
		t.Fatalf("data lost across restart: %v", body)
	}
}
