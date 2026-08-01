### security-checks.md
**When:** DEVELOPMENT phase, before QA transition

Run a security scan on changed files before leaving DEVELOPMENT:
- Run `semgrep --config=auto --json $(git diff --name-only HEAD~1)` if semgrep
  is available; otherwise fall back to:
  `grep -rnE "(password|secret|api[_-]?key|token)\s*[:=]" src/`
- Block the phase transition if HIGH/CRITICAL findings exist.
- Log results to `.loki/proofs/<run_id>/security.json` as
  `{"scanner": "...", "findings": [...], "verdict": "pass|block"}`.
- Never commit real credentials. If a secret appears, rotate it and use an env
  var instead (microcode forwards secrets via `msb --secret`, never inline).
