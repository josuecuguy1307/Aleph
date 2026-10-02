/* B.1 Educación — la obra se mide en DEV, no contra una .app anterior.
 *
 * Levanta el sidecar de esta rama con el rodeo F3 exclusivamente en fuente,
 * entra el pack Educación, comprueba el catálogo que materializó y cruza un
 * turno HTTP real por el borde. El proveedor es determinista: no simula la
 * casa; sólo hace reproducible el extremo externo del circuito completo.
 */
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ROOT = process.cwd();
const PY = process.env.PYBIN || join(ROOT, "product/backend/.venv/bin/python");
const PORT = Number(process.env.PUERTO || 8965);
const PROVIDER_PORT = PORT + 1;
const BASE = `http://127.0.0.1:${PORT}`;
const DATA = mkdtempSync(join(tmpdir(), "educacion-b-"));
const RODEO = mkdtempSync(join(tmpdir(), "educacion-dueno-"));
const SPACE = `educacion-b-${Date.now().toString(36)}`;
let backend = null;
let provider = null;

const fail = (message) => { throw new Error(message); };
const json = async (response) => response.json().catch(() => null);
const waitFor = async (url, ms = 60_000) => {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try { if ((await fetch(url, { signal: AbortSignal.timeout(2_000) })).ok) return true; } catch (_) {}
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
};
const stop = () => {
  if (backend?.pid) { try { process.kill(-backend.pid, "SIGTERM"); } catch (_) {} }
  try { provider?.close(); } catch (_) {}
  rmSync(DATA, { recursive: true, force: true });
  rmSync(RODEO, { recursive: true, force: true });
};

try {
  // F3: `dueno.py` adelanta el models equivocado sólo bajo uvicorn desde fuente.
  // Es un rodeo del arnés, no viaja al producto ni al congelado.
  writeFileSync(join(RODEO, "sitecustomize.py"), [
    "import importlib.util as _u, sys as _s",
    `_p = ${JSON.stringify(join(ROOT, "platform/assembler/models.py"))}`,
    "_spec = _u.spec_from_file_location('models', _p)",
    "_m = _u.module_from_spec(_spec)",
    "_s.modules['models'] = _m",
    "_spec.loader.exec_module(_m)",
    "",
  ].join("\n"));

  provider = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      if (req.url?.endsWith("/models")) {
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ object: "list", data: [{ id: "educacion-fixture" }] }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        id: "educacion-b", object: "chat.completion", created: 0,
        model: "educacion-fixture",
        choices: [{ index: 0, message: { role: "assistant", content: "42" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 3, completion_tokens: 1, total_tokens: 4 },
      }));
    });
  });
  await new Promise((resolve) => provider.listen(PROVIDER_PORT, "127.0.0.1", resolve));

  backend = spawn(PY, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PORT)], {
    cwd: join(ROOT, "product/backend"), detached: true, stdio: "ignore",
    env: {
      ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATA,
      ALEPH_DEEPTUTOR_PYTHON: PY,
      PYTHONPATH: [RODEO, process.env.PYTHONPATH].filter(Boolean).join(":"),
    },
  });
  if (!(await waitFor(`${BASE}/health`))) fail("el sidecar dev no levantó");
  const listed = await json(await fetch(`${BASE}/v1/workspaces`));
  if (!listed?.workspaces?.some((row) => row?.id === "educacion" && row?.stack?.installed === true))
    fail("el dist de Educación no volvió installed:true por el hecho server.js");

  const local = await fetch(`${BASE}/v1/auth/local`, { method: "POST" });
  const user = await json(local);
  if (!local.ok || !user?.id || !user?.session_token) fail("el pack no recibió una sesión local");
  const auth = { "Content-Type": "application/json", Authorization: `Bearer ${user.session_token}` };

  const recipe = {
    schema_version: "v1", meta: { name: "educacion-b", nicho: "general", output_type: "informe" },
    model: { alias: "educacion-fixture", primary: "educacion-fixture", base_url: `http://127.0.0.1:${PROVIDER_PORT}/v1`, temperature: 0, max_tokens: 32, max_turns: 1 },
    belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json", tool_filters: { calc: ["add"] } },
    framing: { inline: "" }, rag: { enabled: false }, keys: {}, gates: {},
  };
  const saved = await fetch(`${BASE}/v1/puppets`, { method: "POST", headers: auth,
    body: JSON.stringify({ name: "educacion-b", nicho: "general", owner_id: user.id, config: recipe }) });
  const puppet = await json(saved);
  const puppetId = puppet?.id || puppet?.puppet_id;
  if (!saved.ok || !puppetId) fail(`no se guardó receta de la vara: HTTP ${saved.status}`);

  const entered = await fetch(`${BASE}/v1/workspaces/educacion/enter`, { method: "POST", headers: auth,
    body: JSON.stringify({ user_id: user.id, puppet_id: puppetId, space_id: SPACE }) });
  const pack = await json(entered);
  if (!entered.ok || !pack?.url || !(await waitFor(pack.url))) fail(`Educación no quedó viva: HTTP ${entered.status}`);

  const catalogPath = join(DATA, "workspaces", "educacion", "runtime", "data", "user", "settings", "model_catalog.json");
  const catalog = JSON.parse(readFileSync(catalogPath, "utf8"));
  const profile = catalog?.services?.llm?.profiles?.[0];
  if (profile?.api_key !== user.session_token || profile?.extra_headers?.["X-Aleph-Space"] !== SPACE ||
      profile?.extra_headers?.["X-Aleph-Puppet"] !== puppetId || profile?.extra_headers?.["X-Aleph-User"] !== user.id)
    fail("el catálogo no materializó exactamente la sesión y cabeceras del pack");

  const headers = { ...auth, ...profile.extra_headers, "X-Aleph-Turn": "1" };
  const turn = await fetch(`${BASE}/v1/workspaces/brain/openai/chat/completions`, { method: "POST", headers,
    body: JSON.stringify({ model: "el-harness-no-elige", messages: [{ role: "user", content: "¿Cuánto es 40 + 2?" }], stream: false }) });
  const response = await json(turn);
  if (!turn.ok || !response?.model || response.model === "el-harness-no-elige" || !response?.choices?.[0]?.message)
    fail(`el borde no devolvió model_final honesto: HTTP ${turn.status}`);

  const eventsResponse = await fetch(`${BASE}/v1/spaces/${SPACE}/events`, { headers: auth });
  const eventsBody = await json(eventsResponse);
  const events = Array.isArray(eventsBody) ? eventsBody : (eventsBody?.events || []);
  const step = events.filter((event) => (event?.type || event?.event) === "workspace_step").at(-1);
  if (!eventsResponse.ok || !step || step.workspace !== "educacion" || step.model !== response.model)
    fail("no quedó un workspace_step de Educación con el model_final del borde");

  const left = await fetch(`${BASE}/v1/workspaces/educacion/leave`, { method: "POST", headers: auth,
    body: JSON.stringify({ user_id: user.id, gracia_s: 0 }) });
  if (!left.ok) fail(`exit del pack falló: HTTP ${left.status}`);
  await new Promise((resolve) => setTimeout(resolve, 700));
  let stillLive = false;
  try { stillLive = (await fetch(pack.url, { signal: AbortSignal.timeout(800) })).ok; } catch (_) {}
  if (stillLive) fail("exit dejó vivo el pack Educación");

  // Nunca se imprime el token. La evidencia sólo conserva forma, resultado y hecho archivado.
  console.log(JSON.stringify({
    request: { workspace: "educacion", space: SPACE, headers: ["Authorization", ...Object.keys(profile.extra_headers), "X-Aleph-Turn"], model: "el-harness-no-elige" },
    response: { object: response.object, model_final: response.model, finish_reason: response.choices[0].finish_reason, content: response.choices[0].message.content },
    workspace_step: { type: step.type || step.event, workspace: step.workspace, space: SPACE, turn: step.turn, model: step.model },
    exit: { zero_orphans: true }, rodeo_dueno_dev_only: true,
  }, null, 2));
} catch (error) {
  console.error(`B.1 rojo: ${error?.stack || error}`);
  process.exitCode = 1;
} finally {
  stop();
}
