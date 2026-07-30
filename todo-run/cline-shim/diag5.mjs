const core = await import("/usr/local/lib/node_modules/cline/node_modules/@cline/core/dist/index.js");
const cline = await core.ClineCore.create({ clientName: "diag" });
const unsub = cline.host.subscribe((ev) => {
  const t = ev.type || ev.subtype || "?";
  if (/agent_event|ended|message|text|tool/.test(t)) console.log(">>>", t, JSON.stringify(ev).slice(0,400));
});
const r = await cline.start({
  config: { providerId: "anthropic-compatible", modelId: "glm-4.6", apiKey: process.env.CLINE_API_KEY, baseUrl: "https://api.z.ai/api/anthropic", systemPrompt: "Reply concisely." },
  prompt: "Reply with exactly: SHIM_OK", interactive: false,
  localRuntime: { workspaceRoot: "/tmp", cwd: "/tmp" },
});
const res = await cline.send({ sessionId: r.sessionId, prompt: "Reply with exactly: SHIM_OK" });
console.log("=== result text:", JSON.stringify(res?.text || res?.finishReason).slice(0,200));
unsub(); await cline.dispose();
