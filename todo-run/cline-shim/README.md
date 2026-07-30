# cline node-shim via @cline/core (WIP)

`cline` ships a Bun-compiled native binary that crashes on arm64 microsandbox
VMs (bus error) and under qemu (segfault). This shim runs cline's agent loop
through the pure-JS `@cline/core` SDK under node, exposed via `CLINE_BIN_PATH`.

## What works (verified on host)
- `@cline/core` loads under node (no Bun).
- `ClineCore.create()` → `cline.start({config, prompt, localRuntime})` works.
- The agent LLM tool-use loop **starts** after `cline.send({sessionId, prompt})`:
  emits `agent_event` → `iteration_start`.
- z.ai Anthropic-compatible streaming endpoint works directly (curl confirms
  `message_start`/`content_block_start`/... SSE flow for model glm-4.6).

## Blocking issue (not yet resolved)
- The loop completes in ~1.3s with
  `done: reason=error, "No output generated. The model stream ended without a
  finish chunk."` (inputTokens:0). Core receives the z.ai stream but does not
  parse a finish chunk — a subtle incompatibility between z.ai's Anthropic-
  compat SSE format and cline-core's stream parser (core is minified, hard to
  debug). claude-code CLI parses the same z.ai endpoint fine, so the gap is
  specifically in core's stream handling.

## Config used
```js
config: {
  providerId: "anthropic", modelId: "glm-4.6",
  apiKey: process.env.CLINE_API_KEY,
  baseUrl: "https://api.z.ai/api/anthropic",
  systemPrompt: "Reply concisely.",
  reasoningEffort: "none",
}
```

See `cline-node-shim.cjs` for the wiring sketch.
