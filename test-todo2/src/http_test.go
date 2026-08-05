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

// bootApp stands up the full generated transport (todo + personal-profile
// services) on a SQLite file at dbPath and returns the fiber app plus a closer
// that shuts the server + DB down.
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
	profileSvc := service.NewProfile(repo)
	log := slog.New(slog.NewTextHandler(io.Discard, nil)) // quiet tests
	srv := transport.New(log, transport.TodoService(svc), transport.PersonalProfileService(profileSvc))
	srv.TodoService().WithErrorHandler(service.HTTPError)
	srv.PersonalProfileService().WithErrorHandler(service.HTTPError)
	return srv.Fiber(), func() {
		_ = srv.Shutdown()
		_ = db.Close()
	}
}

// request fires one HTTP request at the in-process fiber app and returns the
// status code and the decoded JSON body (nil for empty/non-JSON bodies).
func request(t *testing.T, app *fiber.App, method, target, body string) (int, map[string]any) {
	return requestH(t, app, method, target, body, nil)
}

// requestH is request with extra request headers (e.g. x-lk-id).
func requestH(t *testing.T, app *fiber.App, method, target, body string, headers map[string]string) (int, map[string]any) {
	t.Helper()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, target, r)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
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

// makeProfile creates a cabinet via the HTTP API and returns its id as a string.
func makeProfile(t *testing.T, app *fiber.App, name string) string {
	t.Helper()
	code, body := request(t, app, fiber.MethodPost, "/personal-profile", `{"name":"`+name+`"}`)
	if code != 201 {
		t.Fatalf("makeProfile: want 201, got %d %v", code, body)
	}
	return idStr(body["id"])
}

// lkHeaders builds the x-lk-id header map for the given cabinet id.
func lkHeaders(lkID string) map[string]string {
	return map[string]string{"x-lk-id": lkID}
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

	lk := makeProfile(t, app, "работа")

	code, body := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"Buy milk","description":"2 liters"}`, lkHeaders(lk))
	if code != 201 {
		t.Fatalf("create: want 201, got %d %v", code, body)
	}
	if body["title"] != "Buy milk" {
		t.Errorf("title = %v, want Buy milk", body["title"])
	}
	if body["completed"] != false {
		t.Errorf("completed = %v, want false", body["completed"])
	}
	if body["id"] == nil || body["created_at"] == nil || body["lk_id"] == nil {
		t.Fatalf("missing id/created_at/lk_id: %v", body)
	}
	if idStr(body["lk_id"]) != lk {
		t.Errorf("lk_id = %v, want %s", body["lk_id"], lk)
	}
	id := idStr(body["id"])

	if code, body = requestH(t, app, fiber.MethodGet, "/todos", "", lkHeaders(lk)); code != 200 {
		t.Fatalf("list: want 200, got %d %v", code, body)
	}
	if arr, _ := body["todos"].([]any); len(arr) != 1 {
		t.Fatalf("list: want todos[1], got %v", body)
	}

	if code, body = requestH(t, app, fiber.MethodGet, "/todos/"+id, "", lkHeaders(lk)); code != 200 {
		t.Fatalf("get: want 200, got %d %v", code, body)
	}
	if body["id"] == nil {
		t.Errorf("get missing id: %v", body)
	}
}

// TestHTTP_missingHeader_is400 proves the x-lk-id header is required for todo
// create/list/get (authorization of access).
func TestHTTP_missingHeader_is400(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	code, body := request(t, app, fiber.MethodPost, "/todos", `{"title":"x"}`)
	if code != 400 {
		t.Fatalf("create without x-lk-id: want 400, got %d %v", code, body)
	}
	if code, body = request(t, app, fiber.MethodGet, "/todos", ""); code != 400 {
		t.Fatalf("list without x-lk-id: want 400, got %d %v", code, body)
	}
	if body["error"] != "x-lk-id header is required" {
		t.Errorf("error message = %v, want 'x-lk-id header is required'", body["error"])
	}
}

func TestHTTP_Create_blankTitle_is422(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()
	lk := makeProfile(t, app, "cabinet")
	code, body := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"   "}`, lkHeaders(lk))
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
	lk := makeProfile(t, app, "cabinet")
	code, body := requestH(t, app, fiber.MethodGet, "/todos/777", "", lkHeaders(lk))
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

	lk := makeProfile(t, app, "cabinet")

	_, body := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"old","description":"od"}`, lkHeaders(lk))
	id := idStr(body["id"])

	// PATCH/DELETE/Toggle operate by the global todo id (no x-lk-id needed).
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

	lk := makeProfile(t, app, "cabinet")

	_, body := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"t"}`, lkHeaders(lk))
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

	lk := makeProfile(t, app, "cabinet")

	_, body := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"bye"}`, lkHeaders(lk))
	id := idStr(body["id"])

	if code, _ := request(t, app, fiber.MethodDelete, "/todos/"+id, ""); code != 204 {
		t.Fatalf("delete: want 204, got %d", code)
	}
	if code, _ := requestH(t, app, fiber.MethodGet, "/todos/"+id, "", lkHeaders(lk)); code != 404 {
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
	lk := makeProfile(t, app1, "работа")
	_, body := requestH(t, app1, fiber.MethodPost, "/todos", `{"title":"survive restart"}`, lkHeaders(lk))
	id := idStr(body["id"])
	close1() // simulate a clean process restart

	app2, close2 := bootApp(t, dbPath)
	defer close2()

	code, body := requestH(t, app2, fiber.MethodGet, "/todos/"+id, "", lkHeaders(lk))
	if code != 200 {
		t.Fatalf("after restart: want 200, got %d %v", code, body)
	}
	if body["title"] != "survive restart" {
		t.Fatalf("data lost across restart: %v", body)
	}
}

// TestHTTP_lkId_scoping is the PRD Definition-of-Done test: "curl с заголовками
// x-lk-id возвращает только доступные записи". Two cabinets ("работа", "дом")
// each get their own todos; listing with one cabinet's x-lk-id returns ONLY that
// cabinet's records, and a cross-cabinet GET is 404.
func TestHTTP_lkId_scoping(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	lkWork := makeProfile(t, app, "работа")
	lkHome := makeProfile(t, app, "дом")

	// работа gets two todos, дом gets one todo
	requestH(t, app, fiber.MethodPost, "/todos", `{"title":"w1"}`, lkHeaders(lkWork))
	requestH(t, app, fiber.MethodPost, "/todos", `{"title":"w2"}`, lkHeaders(lkWork))
	_, homeBody := requestH(t, app, fiber.MethodPost, "/todos", `{"title":"h1"}`, lkHeaders(lkHome))
	homeID := idStr(homeBody["id"])

	// list работа → only its 2 todos
	code, body := requestH(t, app, fiber.MethodGet, "/todos", "", lkHeaders(lkWork))
	if code != 200 {
		t.Fatalf("list работа: want 200, got %d %v", code, body)
	}
	workTodos, _ := body["todos"].([]any)
	if len(workTodos) != 2 {
		t.Fatalf("работа list: want 2 todos, got %d %v", len(workTodos), body)
	}

	// list дом → only its 1 todo
	_, body = requestH(t, app, fiber.MethodGet, "/todos", "", lkHeaders(lkHome))
	homeTodos, _ := body["todos"].([]any)
	if len(homeTodos) != 1 {
		t.Fatalf("дом list: want 1 todo, got %d %v", len(homeTodos), body)
	}

	// работа cannot GET дом's todo (404, no leakage)
	if code, _ := requestH(t, app, fiber.MethodGet, "/todos/"+homeID, "", lkHeaders(lkWork)); code != 404 {
		t.Errorf("cross-cabinet get: want 404, got %d", code)
	}
}

// TestHTTP_personalProfile_crud exercises the /personal-profile group end to end.
func TestHTTP_personalProfile_crud(t *testing.T) {
	app, closeFn := bootApp(t, filepath.Join(t.TempDir(), "todos.db"))
	defer closeFn()

	// create two cabinets
	code, body := request(t, app, fiber.MethodPost, "/personal-profile", `{"name":"работа"}`)
	if code != 201 || body["name"] != "работа" || body["id"] == nil {
		t.Fatalf("create profile: code=%d body=%v", code, body)
	}
	id := idStr(body["id"])
	if code, _ = request(t, app, fiber.MethodPost, "/personal-profile", `{"name":"дом"}`); code != 201 {
		t.Fatalf("create profile 2: got %d", code)
	}
	if code, _ = request(t, app, fiber.MethodPost, "/personal-profile", `{"name":"   "}`); code != 422 {
		t.Errorf("blank name: want 422, got %d", code)
	}

	// list
	if code, body = request(t, app, fiber.MethodGet, "/personal-profile", ""); code != 200 {
		t.Fatalf("list profiles: want 200, got %d", code)
	}
	if arr, _ := body["profiles"].([]any); len(arr) != 2 {
		t.Fatalf("list profiles: want 2, got %v", body)
	}

	// get + update
	if code, body = request(t, app, fiber.MethodGet, "/personal-profile/"+id, ""); code != 200 || body["name"] != "работа" {
		t.Fatalf("get profile: code=%d body=%v", code, body)
	}
	if code, body = request(t, app, fiber.MethodPatch, "/personal-profile/"+id, `{"name":"office"}`); code != 200 || body["name"] != "office" {
		t.Fatalf("patch profile: code=%d body=%v", code, body)
	}
	if code, _ = request(t, app, fiber.MethodPatch, "/personal-profile/"+id, `{"name":"   "}`); code != 422 {
		t.Errorf("blank name patch: want 422, got %d", code)
	}
	if code, _ = request(t, app, fiber.MethodGet, "/personal-profile/999", ""); code != 404 {
		t.Errorf("get missing profile: want 404, got %d", code)
	}

	// delete
	if code, _ = request(t, app, fiber.MethodDelete, "/personal-profile/"+id, ""); code != 204 {
		t.Fatalf("delete profile: want 204, got %d", code)
	}
	if code, _ = request(t, app, fiber.MethodDelete, "/personal-profile/"+id, ""); code != 404 {
		t.Errorf("delete missing profile: want 404, got %d", code)
	}
}
