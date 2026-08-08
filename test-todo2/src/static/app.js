// Minimal vanilla-JS todo UI. Talks to the REST API at /todos (same origin).
// No build step, no external dependencies. Field names match the Go model:
// title, description, completed, created_at.
//
// Cabinet (ЛК) support: a dropdown lists all personal-profile cabinets; the
// active cabinet's id is sent as the `x-lk-id` header on every todo request.
// Switching cabinets reloads the todo list for the newly selected cabinet.
//
// Auth support: access token in localStorage. All API requests include
// Authorization: Bearer header. 401 redirects to /login.

// --- Auth helpers ---
function getToken() {
  return localStorage.getItem("access_token") || "";
}
function getRefreshToken() {
  return localStorage.getItem("refresh_token") || "";
}
function setTokens(access, refresh) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}
function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("activeLkId");
}

// authHeaders builds headers with Bearer token.
function authHeaders(extra) {
  const headers = Object.assign({}, extra || {});
  const token = getToken();
  if (token) {
    headers["Authorization"] = "Bearer " + token;
  }
  return headers;
}

// checkAuth redirects to /login if no token is present.
function checkAuth() {
  if (!getToken() && window.location.pathname !== "/login") {
    window.location.href = "/login";
    return false;
  }
  return true;
}

// refreshAccessToken tries to get a new access token using the refresh token.
async function refreshAccessToken() {
  const rt = getRefreshToken();
  if (!rt) return false;
  try {
    const res = await fetch("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

// logout clears tokens and redirects to /login.
function logout() {
  clearTokens();
  window.location.href = "/login";
}

const listEl = document.getElementById("todo-list");
const formEl = document.getElementById("create-form");
const errorEl = document.getElementById("error");
const lkSelectEl = document.getElementById("lk-select");
const lkCreateFormEl = document.getElementById("lk-create-form");
const cabinetMgmtListEl = document.getElementById("cabinet-mgmt-list");

// activeLkId holds the currently selected cabinet id (sent as x-lk-id).
// Persisted in localStorage so a page reload keeps the same cabinet.
let activeLkId = localStorage.getItem("activeLkId") || "";

function showError(message) {
  if (!message) {
    errorEl.hidden = true;
    errorEl.textContent = "";
    return;
  }
  errorEl.hidden = false;
  errorEl.textContent = message;
}

// fetchJSON wraps fetch with JSON parsing, auth headers, and error normalization.
// On 401, attempts token refresh and retries once.
async function fetchJSON(url, options = {}) {
  // Inject auth headers if not already set.
  if (!options.headers || !options.headers["Authorization"]) {
    options.headers = authHeaders(options.headers || {});
  }
  const res = await fetch(url, options);
  const ct = res.headers.get("content-type") || "";
  let body = null;
  if (ct.includes("application/json")) {
    body = await res.json();
  } else {
    body = await res.text();
  }
  // On 401, try refresh and retry once.
  if (res.status === 401 && window.location.pathname !== "/login") {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      options.headers = authHeaders(options.headers || {});
      const retry = await fetch(url, options);
      if (retry.ok) {
        const ct2 = retry.headers.get("content-type") || "";
        return ct2.includes("application/json") ? await retry.json() : await retry.text();
      }
    }
    logout();
    throw new Error("session expired");
  }
  if (!res.ok) {
    const msg = (body && body.error) ? body.error : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}

// lkHeaders builds the headers for a todo request, injecting the active
// cabinet's id as x-lk-id (string per the API contract).
function lkHeaders(extra) {
  const headers = Object.assign({}, extra || {});
  if (activeLkId) {
    headers["x-lk-id"] = String(activeLkId);
  }
  return headers;
}

// asJSON builds a JSON-body request, optionally carrying x-lk-id and auth.
function asJSON(method, data, withLk) {
  const headers = { "Content-Type": "application/json" };
  return {
    method,
    headers: withLk ? authHeaders(lkHeaders(headers)) : authHeaders(headers),
    body: JSON.stringify(data),
  };
}

// escapeHtml prevents stored title/description from injecting markup.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function renderTodo(t) {
  const li = document.createElement("li");
  li.className = "todo" + (t.completed ? " completed" : "");
  li.dataset.id = String(t.id);

  const head = document.createElement("div");
  head.className = "todo-head";

  const toggle = document.createElement("input");
  toggle.type = "checkbox";
  toggle.checked = !!t.completed;
  toggle.addEventListener("change", () => toggleTodo(t.id));

  const label = document.createElement("label");
  label.textContent = t.title;
  label.addEventListener("click", () => toggleTodo(t.id));

  head.append(toggle, label);
  li.append(head);

  if (t.description) {
    const desc = document.createElement("p");
    desc.className = "todo-desc";
    desc.textContent = t.description;
    li.append(desc);
  }

  const meta = document.createElement("div");
  meta.className = "todo-meta";
  meta.textContent = `created ${t.created_at}`;
  li.append(meta);

  const actions = document.createElement("div");
  actions.className = "todo-actions";

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "secondary";
  editBtn.textContent = "Edit";
  editBtn.addEventListener("click", () => startEdit(li, t));

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "danger";
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", () => deleteTodo(t.id));

  actions.append(editBtn, delBtn);
  li.append(actions);

  return li;
}

function renderList(todos) {
  listEl.innerHTML = "";
  if (!todos || !todos.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No todos yet. Add one above.";
    listEl.append(empty);
    return;
  }
  for (const t of todos) {
    listEl.append(renderTodo(t));
  }
}

// renderCabinets rebuilds the dropdown from the profile list and restores the
// active selection (falling back to the first cabinet if none was selected).
function renderCabinets(profiles) {
  lkSelectEl.innerHTML = "";
  if (!profiles || !profiles.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No cabinets — create one";
    lkSelectEl.append(opt);
    activeLkId = "";
    localStorage.removeItem("activeLkId");
    return;
  }
  for (const p of profiles) {
    const opt = document.createElement("option");
    opt.value = String(p.id);
    opt.textContent = p.name;
    lkSelectEl.append(opt);
  }
  // Keep the previous selection if it still exists, otherwise pick the first.
  const stillExists = profiles.some((p) => String(p.id) === String(activeLkId));
  activeLkId = stillExists ? activeLkId : String(profiles[0].id);
  lkSelectEl.value = String(activeLkId);
  localStorage.setItem("activeLkId", String(activeLkId));
}

async function refreshCabinets() {
  try {
    const data = await fetchJSON("/personal-profile");
    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    renderCabinets(profiles);
    renderCabinetManagement(profiles);
    return profiles;
  } catch (err) {
    showError(err.message);
    return [];
  }
}

async function refresh() {
  // No active cabinet → clear the list; the API requires x-lk-id.
  if (!activeLkId) {
    renderList([]);
    showError("");
    return;
  }
  try {
    const data = await fetchJSON("/todos", { headers: lkHeaders() });
    renderList(Array.isArray(data.todos) ? data.todos : []);
    showError("");
  } catch (err) {
    showError(err.message);
  }
}

async function createTodo(title, description) {
  await fetchJSON("/todos", asJSON("POST", { title, description }, true));
  await refresh();
}

async function toggleTodo(id) {
  await fetchJSON(`/todos/${id}/toggle`, { method: "POST", headers: lkHeaders() });
  await refresh();
}

async function deleteTodo(id) {
  await fetchJSON(`/todos/${id}`, { method: "DELETE", headers: lkHeaders() });
  await refresh();
}

async function patchTodo(id, title, description) {
  await fetchJSON(`/todos/${id}`, asJSON("PATCH", { title, description }, true));
  await refresh();
}

// renderCabinetManagement rebuilds the management list (rename/delete) from the
// profile list. This is the separate interface for working with ЛК.
function renderCabinetManagement(profiles) {
  cabinetMgmtListEl.innerHTML = "";
  if (!profiles || !profiles.length) {
    const empty = document.createElement("li");
    empty.className = "cabinet-management-empty";
    empty.textContent = "No cabinets yet.";
    cabinetMgmtListEl.append(empty);
    return;
  }
  for (const p of profiles) {
    const li = document.createElement("li");
    li.dataset.id = String(p.id);

    const info = document.createElement("div");
    info.className = "cabinet-info";
    info.innerHTML =
      '<span class="cabinet-name">' + esc(p.name) + '</span>' +
      '<span class="cabinet-id"> id=' + esc(String(p.id)) + '</span>';
    li.append(info);

    const actions = document.createElement("div");
    actions.className = "cabinet-actions";

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "secondary";
    renameBtn.textContent = "Rename";
    renameBtn.addEventListener("click", () => startRenameCabinet(li, p));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "danger";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => deleteCabinet(p.id));

    actions.append(renameBtn, deleteBtn);
    li.append(actions);
    cabinetMgmtListEl.append(li);
  }
}

// startRenameCabinet swaps the cabinet info into an inline rename form.
function startRenameCabinet(li, p) {
  li.innerHTML = "";
  const form = document.createElement("form");
  form.className = "lk-create";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "rename-input";
  input.value = p.name;
  input.required = true;

  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "Save";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "secondary";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => {
    refreshCabinets();
  });

  form.append(input, save, cancel);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await renameCabinet(p.id, input.value.trim());
      showError("");
    } catch (err) {
      showError(err.message);
    }
  });
  li.append(form);
  input.focus();
}

async function renameCabinet(id, name) {
  if (!name) return;
  await fetchJSON(`/personal-profile/${id}`, asJSON("PATCH", { name }, false));
  await refreshCabinets();
}

async function deleteCabinet(id) {
  if (!confirm("Delete this cabinet and all its todos?")) return;
  await fetchJSON(`/personal-profile/${id}`, { method: "DELETE" });
  // If the deleted cabinet was active, switch to another or clear.
  if (String(activeLkId) === String(id)) {
    activeLkId = "";
    localStorage.removeItem("activeLkId");
  }
  const profiles = await refreshCabinets();
  if (profiles.length && !activeLkId) {
    activeLkId = String(profiles[0].id);
    lkSelectEl.value = String(activeLkId);
    localStorage.setItem("activeLkId", String(activeLkId));
  }
  await refresh();
}

async function createCabinet(name) {
  await fetchJSON("/personal-profile", asJSON("POST", { name }, false));
  const profiles = await refreshCabinets();
  // Select the newly created cabinet (ids are monotonic, so it is the last).
  if (profiles.length) {
    activeLkId = String(profiles[profiles.length - 1].id);
    lkSelectEl.value = String(activeLkId);
    localStorage.setItem("activeLkId", String(activeLkId));
    await refresh();
  }
}

// startEdit swaps the todo card into an inline edit form (title + description).
function startEdit(li, t) {
  li.innerHTML = "";

  const form = document.createElement("form");
  form.className = "edit-form";

  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.value = t.title;
  titleInput.required = true;

  const descInput = document.createElement("input");
  descInput.type = "text";
  descInput.value = t.description || "";

  const save = document.createElement("button");
  save.type = "submit";
  save.textContent = "Save";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "secondary";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", refresh);

  form.append(titleInput, descInput, save, cancel);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await patchTodo(t.id, titleInput.value, descInput.value);
      showError("");
    } catch (err) {
      showError(err.message);
    }
  });

  li.append(form);
  titleInput.focus();
}

// Switching cabinets reloads todos for the newly selected cabinet (Non-functional
// requirement: "при переключении между лк должны перезагружаться все доступные
// записи").
lkSelectEl.addEventListener("change", async () => {
  activeLkId = lkSelectEl.value;
  localStorage.setItem("activeLkId", String(activeLkId));
  await refresh();
});

lkCreateFormEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("lk-name").value.trim();
  if (!name) return;
  try {
    await createCabinet(name);
    lkCreateFormEl.reset();
    showError("");
  } catch (err) {
    showError(err.message);
  }
});

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = document.getElementById("title").value;
  const description = document.getElementById("description").value;
  if (!activeLkId) {
    showError("Select or create a cabinet first.");
    return;
  }
  try {
    await createTodo(title, description);
    formEl.reset();
    showError("");
  } catch (err) {
    showError(err.message);
  }
});

// Boot: check auth, then load cabinets and todos. On /login page, set up forms.
(async () => {
  if (window.location.pathname === "/login") {
    setupLoginPage();
    return;
  }
  if (!checkAuth()) return;
  setupLogoutButton();
  await refreshCabinets();
  await refresh();
})();

function setupLoginPage() {
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const authToggle = document.getElementById("auth-toggle");
  const authError = document.getElementById("auth-error");

  // Toggle between login and register
  authToggle.innerHTML = '<a href="#" id="toggle-link">Need an account? Register</a>';
  document.getElementById("toggle-link").addEventListener("click", (e) => {
    e.preventDefault();
    if (loginForm.hidden) {
      loginForm.hidden = false;
      registerForm.hidden = true;
      document.getElementById("toggle-link").textContent = "Need an account? Register";
    } else {
      loginForm.hidden = true;
      registerForm.hidden = false;
      document.getElementById("toggle-link").textContent = "Already have an account? Sign in";
    }
    authError.hidden = true;
  });

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;
    if (!email || !password) { authError.textContent = "Email and password are required"; authError.hidden = false; return; }
    try {
      authError.hidden = true;
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Login failed");
      setTokens(data.access_token, data.refresh_token);
      window.location.href = "/";
    } catch (err) {
      authError.textContent = err.message;
      authError.hidden = false;
    }
  });

  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("reg-email").value.trim();
    const password = document.getElementById("reg-password").value;
    const confirm = document.getElementById("reg-confirm").value;
    if (!email || !password) { authError.textContent = "Email and password are required"; authError.hidden = false; return; }
    if (password !== confirm) { authError.textContent = "Passwords do not match"; authError.hidden = false; return; }
    if (password.length < 8 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password)) {
      authError.textContent = "Password must be 8+ chars with uppercase, lowercase, and digit";
      authError.hidden = false; return;
    }
    try {
      authError.hidden = true;
      const res = await fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Registration failed");
      setTokens(data.tokens.access_token, data.tokens.refresh_token);
      window.location.href = "/";
    } catch (err) {
      authError.textContent = err.message;
      authError.hidden = false;
    }
  });
}

function setupLogoutButton() {
  const btn = document.getElementById("logout-btn");
  if (btn) {
    btn.addEventListener("click", () => {
      clearTokens();
      window.location.href = "/login";
    });
  }
}
