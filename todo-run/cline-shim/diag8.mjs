const core = await import("/usr/local/lib/node_modules/cline/node_modules/@cline/core/dist/index.js");
const cline = await core.ClineCore.create({ clientName: "diag" });
let textParts = [];
const unsub = cline.host.subscribe((ev) => {
  const p = ev.payload;
  if (p && p.event) {
    const e = p.event;
    if (e.type === "text") textParts.push(e.text || "");
    if (e.type === "content" && e.contentType === "text") textParts.push(e.text||e.content||"");
    if (e.type === "done" || e.type === "tool_call" || e.type === "tool_use") console.log("EVT:", e.type, JSON.stringify(e).slice(0,150));
  }
});
const r = await cline.start({
  config: { providerId: "zai-coding-plan", modelId: "glm-4.6", apiKey: process.env.CLINE_API_KEY, systemPrompt: "Reply concisely." },
  prompt: "Reply with exactly: SHIM_OK", interactive: false, localRuntime: { workspaceRoot: "/tmp", cwd: "/tmp" },
});
const res = await cline.send({ sessionId: r.sessionId, prompt: "Reply with exactly: SHIM_OK" });
console.log("=== FINAL ===");
console.log("text:", JSON.stringify(res?.text).slice(0,200));
console.log("finishReason:", res?.finishReason);
console.log("toolCalls:", res?.toolCalls?.length);
console.log("collected text parts:", textParts.join("").slice(0,200));
unsub(); await cline.dispose();
