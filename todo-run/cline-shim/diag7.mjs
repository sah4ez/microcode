const core = await import("/usr/local/lib/node_modules/cline/node_modules/@cline/core/dist/index.js");
const cline = await core.ClineCore.create({ clientName: "diag" });
const unsub = cline.host.subscribe((ev) => {
  const t = ev.type || ev.subtype || "?";
  if (/agent_event|ended/.test(t)) console.log(">>>", t, JSON.stringify(ev).slice(0,300));
});
// zai-coding-plan uses OAuth (ZAI_OAUTH_* env), not raw apiKey
const r = await cline.start({
  config: { providerId: "zai-coding-plan", modelId: "glm-4.6", apiKey: process.env.CLINE_API_KEY, systemPrompt: "Reply concisely." },
  prompt: "say OK", interactive: false, localRuntime: { workspaceRoot: "/tmp", cwd: "/tmp" },
});
const res = await cline.send({ sessionId: r.sessionId, prompt: "say OK" });
console.log("RESULT:", JSON.stringify(res?.text||"").slice(0,150), "finish=", res?.finishReason);
unsub(); await cline.dispose();
