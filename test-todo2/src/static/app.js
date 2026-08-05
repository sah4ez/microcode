// Minimal vanilla-JS todo UI. Talks to the REST API at /todos (same origin).
// No build step, no external dependencies. Field names match the Go model:
// title, description, completed, created_at.
//
// Cabinet (ЛК) support: a dropdown lists all personal-profile cabinets; the
// active cabinet's id is sent as the `x-lk-id` header on every todo request.
// Switching cabinets reloads the todo list for the newly selected cabinet.

const listEl = document.getElementById("todo-list");
const formEl = document.getElementById("create-form");
const errorEl = document.getElementById("error");
const lkSelectEl = document.getElementById("lk-select");
const lkCreateFormEl = document.getElementById("lk-create-form");

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

// fetchJSON wraps fetch with JSON parsing and error normalization.
async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  const ct = res.headers.get("content-type") || "";
  let body = null;
  if (ct.includes("application/json")) {
    body = await res.json();
  } else {
    body = await res.text();
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

// asJSON builds a JSON-body request, optionally carrying x-lk-id.
function asJSON(method, data, withLk) {
  const headers = { "Content-Type": "application/json" };
  return {
    method,
    headers: withLk ? lkHeaders(headers) : headers,
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

// Boot: load cabinets first, then todos for the active cabinet.
(async () => {
  await refreshCabinets();
  await refresh();
})();
