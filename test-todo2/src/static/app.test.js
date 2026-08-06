// Frontend unit tests for app.js — extract functions and test them in isolation.
// Run: node static/app.test.js  (or open static/app.test.html in a browser)
//
// Since the real app.js attaches to DOM elements, we mock a minimal DOM for
// unit testing the pure logic functions (escapeHtml, lkHeaders, asJSON).

// --- Minimal DOM mock for Node.js ---
if (typeof document === "undefined") {
  const elements = {};
  globalThis.document = {
    getElementById: (id) => elements[id] || null,
    createElement: (tag) => ({
      className: "", dataset: {}, textContent: "", value: "", innerHTML: "",
      type: "text", required: false, append: (...args) => {}, appendChild: () => {},
      addEventListener: () => {}, style: {}, setAttribute: () => {},
    }),
    createTextNode: (t) => t,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.localStorage = {
    getItem: () => null, setItem: () => {}, removeItem: () => {},
  };
  globalThis.window = globalThis;
  globalThis.confirm = () => true;
}

// --- Extract the esc (escapeHtml) function for testing ---
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

// --- Extract lkHeaders ---
function lkHeaders(extra) {
  const headers = Object.assign({}, extra || {});
  if (activeLkId) {
    headers["x-lk-id"] = String(activeLkId);
  }
  return headers;
}

// --- Extract asJSON ---
function asJSON(method, data, withLk) {
  const headers = { "Content-Type": "application/json" };
  return {
    method,
    headers: withLk ? lkHeaders(headers) : headers,
    body: JSON.stringify(data),
  };
}

// --- Test runner ---
let passed = 0;
let failed = 0;
const errors = [];

function assert(condition, message) {
  if (condition) {
    passed++;
  } else {
    failed++;
    errors.push(message);
  }
}

function assertEqual(actual, expected, message) {
  if (actual === expected) {
    passed++;
  } else {
    failed++;
    errors.push(`${message}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

// --- Tests ---

// Test: esc() escapes HTML entities
assertEqual(esc("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;", "esc escapes < and >");
assertEqual(esc("hello & world"), "hello &amp; world", "esc escapes &");
assertEqual(esc('a"b'), "a&quot;b", "esc escapes double quotes");
assertEqual(esc("a'b"), "a&#39;b", "esc escapes single quotes");
assertEqual(esc("plain text"), "plain text", "esc leaves plain text unchanged");
assertEqual(esc(""), "", "esc handles empty string");
assertEqual(esc(null), "", "esc handles null");
assertEqual(esc(undefined), "", "esc handles undefined");

// Test: lkHeaders with activeLkId
var activeLkId = "42";
const hdrs = lkHeaders();
assertEqual(hdrs["x-lk-id"], "42", "lkHeaders includes x-lk-id when activeLkId is set");

const hdrs2 = lkHeaders({ "Content-Type": "text/plain" });
assertEqual(hdrs2["Content-Type"], "text/plain", "lkHeaders merges extra headers");
assertEqual(hdrs2["x-lk-id"], "42", "lkHeaders includes x-lk-id with extra headers");

// Test: lkHeaders without activeLkId
activeLkId = "";
const hdrs3 = lkHeaders();
assertEqual(hdrs3["x-lk-id"], undefined, "lkHeaders omits x-lk-id when activeLkId is empty");

// Test: asJSON
activeLkId = "5";
const req = asJSON("POST", { title: "test" }, true);
assertEqual(req.method, "POST", "asJSON sets method");
assertEqual(req.body, '{"title":"test"}', "asJSON serializes body");
assertEqual(req.headers["Content-Type"], "application/json", "asJSON sets content-type");
assertEqual(req.headers["x-lk-id"], "5", "asJSON with withLk includes x-lk-id");

const req2 = asJSON("GET", null, false);
assertEqual(req2.headers["x-lk-id"], undefined, "asJSON without withLk omits x-lk-id");
assertEqual(req2.body, "null", "asJSON serializes null body");

// Test: asJSON with PATCH (data may have null fields)
const req3 = asJSON("PATCH", { name: "new" }, false);
assertEqual(req3.method, "PATCH", "asJSON sets PATCH method");
assertEqual(req3.body, '{"name":"new"}', "asJSON serializes PATCH body");

// --- Report ---
console.log(`\nFrontend tests: ${passed} passed, ${failed} failed`);
if (errors.length) {
  console.log("Failures:");
  errors.forEach((e) => console.log("  - " + e));
}
process.exit(failed > 0 ? 1 : 0);