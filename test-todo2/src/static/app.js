// Minimal vanilla-JS todo UI. Talks to the REST API at /todos (same origin).
// No build step, no external dependencies. Field names match the Go model:
// title, description, completed, created_at.

const listEl = document.getElementById("todo-list");
const formEl = document.getElementById("create-form");
const errorEl = document.getElementById("error");

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

function asJSON(data) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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

async function refresh() {
  try {
    const data = await fetchJSON("/todos");
    renderList(Array.isArray(data.todos) ? data.todos : []);
    showError("");
  } catch (err) {
    showError(err.message);
  }
}

async function createTodo(title, description) {
  await fetchJSON("/todos", asJSON({ title, description }));
  await refresh();
}

async function toggleTodo(id) {
  await fetchJSON(`/todos/${id}/toggle`, { method: "POST" });
  await refresh();
}

async function deleteTodo(id) {
  await fetchJSON(`/todos/${id}`, { method: "DELETE" });
  await refresh();
}

async function patchTodo(id, title, description) {
  await fetchJSON(`/todos/${id}`, asJSON({ title, description }));
  await refresh();
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

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = document.getElementById("title").value;
  const description = document.getElementById("description").value;
  try {
    await createTodo(title, description);
    formEl.reset();
    showError("");
  } catch (err) {
    showError(err.message);
  }
});

refresh();
