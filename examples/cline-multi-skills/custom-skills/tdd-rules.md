### tdd-rules.md
**When:** Implementing any feature/bugfix, BEFORE writing implementation code

Hard rules (overlay on top of loki's built-in testing.md):
- RED-GREEN-REFACTOR, always. Write the test first, watch it FAIL, then implement.
- If you didn't watch the test fail, you don't know if it tests the right thing.
- Never delete or weaken a failing test. Fix the code, not the test.
- No mocks where real behavior is cheap to exercise (in-memory SQLite, real
  function calls). Reserve mocks for external services/network only.
- One behavior per test. Name tests as `test_<unit>_<condition>_<expected>`.
- Tests live next to the code: `foo.py` → `test_foo.py` in the same package.

Verify gate (this module feeds loki's VERIFY phase):
- Every new public function/class must have at least one test.
- The suite must be green before advancing to QA.
