const core = await import("/usr/local/lib/node_modules/cline/node_modules/@cline/core/dist/index.js");
const cline = await core.ClineCore.create({ clientName: "diag" });
const unsub = cline.host.subscribe((ev) => {
  const t = ev.type || ev.subtype || "?";
  if (/agent_event|ended/.test(t)) console.log(">>>", t, JSON.stringify(ev).slice(0,400));
});
for (const pid of ["zai-coding-plan","zai","glm","anthropic"]) {
  for (const mid of ["glm-4.6","glm-5-2","glm-4-flash"]) {
    try {
      const r = await cline.start({
        config: { providerId: pid, modelId: mid, apiKey: process.env.CLINE_API_KEY, baseUrl: "https://api.z.ai/api/anthropic", systemPrompt: "Reply concisely." },
        prompt: "say OK", interactive: false, localRuntime: { workspaceRoot: "/tmp", cwd: "/tmp" },
      });
      const res = await cline.send({ sessionId: r.sessionId, prompt: "say OK" });
      console.log(`${pid}/${mid}: "${(res?.text||"").slice(0,60)}" finish=${res?.finishReason}`);
      await cline.stop(r.sessionId).catch(()=>{});
    } catch(e) { console.log(`${pid}/${mid}: ERR ${e.message.slice(0,80)}`); }
  }
}
unsub(); await cline.dispose();
