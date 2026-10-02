/* F · Educación contra la .app instalada, en una sola serie y sin navegador. */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const APP = "/Applications/Aleph.app";
const SIDECAR = `${APP}/Contents/MacOS/aleph_sidecar`;
const PORT = Number(process.env.PUERTO || 8985);
const PROVIDER_PORT = PORT + 1;
const BASE = `http://127.0.0.1:${PORT}`;
const DATA = mkdtempSync(join(tmpdir(), "educacion-f-"));
const SPACE = `educacion-f-${Date.now().toString(36)}`;
let sidecar, provider, providerBodies = [], sidecarLog = "";

const fail = (m) => { throw new Error(m); };
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const json = async (r) => r.json().catch(() => null);
async function waitFor(url, ms = 90_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if ((await fetch(url, { signal: AbortSignal.timeout(2_000) })).ok) return true; } catch (_) {}
    await pause(350);
  }
  return false;
}
function makePdf(text) {
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(`BT /F1 18 Tf 72 720 Td (${text}) Tj ET`)} >>\nstream\nBT /F1 18 Tf 72 720 Td (${text}) Tj ET\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n", offsets = [0];
  objs.forEach((o, i) => { offsets.push(Buffer.byteLength(body)); body += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const start = Buffer.byteLength(body);
  body += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= objs.length; i++) body += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  return Buffer.from(`${body}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`);
}
function tutorPdfTurn(url, profile) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url.replace(/^http/, "ws") + "/api/v1/ws");
    const timer = setTimeout(() => { ws.close(); reject(new Error("timeout del tutor directo")); }, 60_000);
    ws.onerror = () => { clearTimeout(timer); reject(new Error("websocket del tutor directo falló")); };
    ws.onopen = () => ws.send(JSON.stringify({
      type: "start_turn", capability: "chat", language: "es", content: "Lee el PDF adjunto.",
      session_id: "f-pdf-session", tools: [], knowledge_bases: [], config: {},
      llm_selection: { profile_id: profile.id, model_id: "educacion-fixture" },
      attachments: [{ type: "document", filename: "lectura.pdf", mime_type: "application/pdf", id: "pdf-f6", base64: makePdf("PDFIUM F6 TEXTO").toString("base64") }],
    }));
    ws.onmessage = (event) => {
      const msg = JSON.parse(String(event.data));
      if (msg.type === "error") { clearTimeout(timer); ws.close(); reject(new Error(`tutor: ${msg.content || msg.message}`)); }
      if (msg.type === "done") { clearTimeout(timer); ws.close(); resolve(msg); }
    };
  });
}
function stop() {
  try { if (sidecar?.pid) process.kill(-sidecar.pid, "SIGTERM"); } catch (_) {}
  try { provider?.close(); } catch (_) {}
  if (!process.env.KEEP_F_DATA) rmSync(DATA, { recursive: true, force: true });
}

try {
  provider = createServer((req, res) => {
    let raw = ""; req.on("data", (c) => { raw += c; }); req.on("end", () => {
      providerBodies.push(raw);
      if (req.url?.endsWith("/models")) return res.end(JSON.stringify({ object: "list", data: [{ id: "educacion-fixture" }] }));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ id: "f", object: "chat.completion", created: 0, model: "educacion-fixture", choices: [{ index: 0, message: { role: "assistant", content: "Respuesta del tutor" }, finish_reason: "stop" }] }));
    });
  });
  await new Promise((ok) => provider.listen(PROVIDER_PORT, "127.0.0.1", ok));
  sidecar = spawn(SIDECAR, ["--port", String(PORT)], { detached: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA } });
  sidecar.stdout.on("data", (chunk) => { sidecarLog += String(chunk); });
  sidecar.stderr.on("data", (chunk) => { sidecarLog += String(chunk); });
  if (!(await waitFor(`${BASE}/health`))) fail("frío: el sidecar instalado no levantó");
  const local = await fetch(`${BASE}/v1/auth/local`, { method: "POST" }); const user = await json(local);
  if (!local.ok || !user?.session_token) fail("la sesión local no fue emitida por el pack");
  const auth = { "Content-Type": "application/json", Authorization: `Bearer ${user.session_token}` };
  const recipe = { schema_version: "v1", meta: { name: "f-educacion", nicho: "general", output_type: "informe" }, model: { alias: "educacion-fixture", primary: "educacion-fixture", base_url: `http://127.0.0.1:${PROVIDER_PORT}/v1`, temperature: 0, max_tokens: 32, max_turns: 1 }, belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json", tool_filters: { calc: ["add"] } }, framing: { inline: "" }, rag: { enabled: false }, keys: {}, gates: {} };
  const saved = await fetch(`${BASE}/v1/puppets`, { method: "POST", headers: auth, body: JSON.stringify({ name: "f-educacion", nicho: "general", owner_id: user.id, config: recipe }) }); const puppet = await json(saved); const puppetId = puppet?.id || puppet?.puppet_id;
  if (!saved.ok || !puppetId) fail("no se pudo guardar la receta de F");
  const entered = await fetch(`${BASE}/v1/workspaces/educacion/enter`, { method: "POST", headers: auth, body: JSON.stringify({ user_id: user.id, puppet_id: puppetId, space_id: SPACE }) }); const pack = await json(entered);
  if (!entered.ok || !(await waitFor(pack?.url))) fail(`tocar Educación no levantó el tutor congelado: HTTP ${entered.status} ${JSON.stringify(pack)} log=${sidecarLog.slice(-1200)}`);
  const profile = JSON.parse(readFileSync(join(DATA, "workspaces/educacion/runtime/data/user/settings/model_catalog.json"), "utf8")).services.llm.profiles[0];
  const edge = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST", headers: { ...auth, ...profile.extra_headers, "X-Aleph-Turn": "1" }, body: JSON.stringify({ model: "no-final-del-harness", messages: [{ role: "user", content: "¿Cuánto es 40 + 2?" }], stream: false }) }); const answer = await json(edge);
  if (!edge.ok || answer?.model !== "educacion-fixture") fail("el borde no reportó model_final honesto");
  await tutorPdfTurn(pack.url, profile);
  if (!providerBodies.some((body) => body.includes("PDFIUM F6 TEXTO"))) fail("el PDF no llegó extraído desde el tutor; pypdfium2 no quedó probado");
  const close = await fetch(`${BASE}/v1/workspaces/brain/close`, { method: "POST", headers: auth, body: JSON.stringify({ space_id: SPACE, workspace: "educacion", answer: answer.choices[0].message.content, turns: 1, user_id: user.id }) });
  if (!close.ok) fail("no cerró el turno antes del pasaporte");
  const artifact = await fetch(`${BASE}/v1/workspaces/artifacts`, { method: "POST", headers: auth, body: JSON.stringify({ sid: "f-educacion-artifact", workspace: "educacion", kind: "report", data: { content: "# Síntesis\nRespuesta del tutor" }, title: "Síntesis F", user_id: user.id, space_id: SPACE, intent: "estudio" }) }); const art = await json(artifact);
  if (!artifact.ok || !art?.artifact?.provenance?.model_final) fail("el informe no recibió pasaporte con model_final");
  const leave = await fetch(`${BASE}/v1/workspaces/educacion/leave`, { method: "POST", headers: auth, body: JSON.stringify({ user_id: user.id, gracia_s: 0 }) }); if (!leave.ok) fail("cerrar Educación falló");
  await pause(700);
  const reopened = await fetch(`${BASE}/v1/workspaces/educacion/enter`, { method: "POST", headers: auth, body: JSON.stringify({ user_id: user.id, puppet_id: puppetId, space_id: SPACE }) }); const pack2 = await json(reopened);
  if (!reopened.ok || !(await waitFor(`${pack2.url}/api/v1/chat/sessions/f-pdf-session`))) fail("reabrir no restauró la sesión del tutor");
  await fetch(`${BASE}/v1/workspaces/educacion/leave`, { method: "POST", headers: auth, body: JSON.stringify({ user_id: user.id, gracia_s: 0 }) });
  console.log(JSON.stringify({ installed: true, tutor_direct: true, model_final: answer.model, pdf: "pypdfium2 text observed by provider", artifact_passport: art.artifact.provenance.model_final, restored: true, zero_orphans: true }, null, 2));
} catch (error) { console.error(`F rojo: ${error?.stack || error}`); process.exitCode = 1; } finally { stop(); }
