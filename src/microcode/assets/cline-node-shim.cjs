#!/usr/bin/env node
/**
 * cline node-shim — runs cline's agent loop via the pure-JS @cline/core SDK
 * under node (NO Bun). Exposed to loki via CLINE_BIN_PATH.
 *
 * Why: cline's native binary is Bun-compiled and crashes on arm64 microsandbox
 * VMs (bus error) and under qemu (segfault). @cline/core is pure JS.
 *
 * Usage mirrors `cline "<prompt>"` (loki invokes the cline provider CLI with a
 * prompt as the trailing argument and reads the assistant's final text from
 * stdout). Provider (z.ai/GLM) is the cline built-in `zai-coding-plan` OAuth
 * provider (configured via ZAI_OAUTH_* env), model glm-4.6.
 *
 * Env:
 *   CLINE_CWD         working directory (default $PWD)
 *   CLINE_API_KEY     api key (passed through to core config.apiKey)
 *   CLINE_MODEL       model id (default glm-4.6)
 *   CLINE_PROVIDER_ID provider id (default zai-coding-plan)
 *   CLINE_CORE_PATH   override path to @cline/core dist/index.js
 *   ZAI_BUSINESS_BASE_URL / ZAI_OAUTH_CLIENT_ID / ZAI_OAUTH_ORIGIN  (z.ai OAuth)
 */
"use strict";
const path = require("path");
const os = require("os");
const fs = require("fs");

function findCore() {
  const candidates = [
    process.env.CLINE_CORE_PATH,
    "/usr/local/lib/node_modules/cline/node_modules/@cline/core/dist/index.js",
    "/opt/npm-global/lib/node_modules/cline/node_modules/@cline/core/dist/index.js",
    path.join(os.homedir(), ".npm-global/lib/node_modules/cline/node_modules/@cline/core/dist/index.js"),
  ].filter(Boolean);
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  throw new Error("@cline/core not found; install cline globally first");
}

async function main() {
  const prompt = process.argv[process.argv.length - 1];
  if (!prompt || prompt.startsWith("-")) {
    console.error("cline-shim: no prompt provided");
    process.exit(1);
  }
  const cwd = process.env.CLINE_CWD || process.cwd();
  const apiKey = process.env.CLINE_API_KEY || process.env.GLM_API_KEY || process.env.ANTHROPIC_API_KEY || "";
  const modelId = process.env.CLINE_MODEL || "glm-4.6";
  const providerId = process.env.CLINE_PROVIDER_ID || "zai-coding-plan";

  const core = await import(findCore());
  const cline = await core.ClineCore.create({ clientName: "microcode-cline-shim" });

  const r = await cline.start({
    config: {
      providerId,
      modelId,
      apiKey,
      // @cline/core startResolvedSession maps these (camelCase) to the zod-
      // validated snake_case session fields: enable_tools<-enableTools,
      // enable_spawn<-enableSpawnAgent, enable_teams<-enableAgentTeams.
      enableTools: true,
      enableSpawnAgent: false,
      enableAgentTeams: false,
      systemPrompt:
        "You are Cline, a coding agent. Use the available tools to accomplish the task in the workspace, then reply with a concise summary.",
    },
    prompt,
    interactive: false,
    localRuntime: { workspaceRoot: cwd, cwd },
  });
  // start() with a prompt runs the full agent loop synchronously and returns
  // {sessionId, manifest, result}. The assistant text is in result.text.
  const result = r.result || r;

  if (result && typeof result.text === "string" && result.text.length) {
    process.stdout.write(result.text + "\n");
  } else {
    process.stderr.write(
      "cline-shim: no text returned (finishReason=" +
        (result && result.finishReason) + ")\n"
    );
  }
  await cline.dispose();
}

main().catch((e) => {
  console.error("cline-shim error:", (e && e.stack) || e);
  process.exit(1);
});
