/**
 * Fixture determinista de la vara de Sala. Sirve el frontend del worktree en :8304
 * y simula un cerebro con tres pasos encadenados por turno, sin red externa.
 *
 * Sólo es un banco local: la reina contra el sidecar instalado queda descrita en
 * reports/step5/SALA-E2E.md y la repite Integración D sin instalar.
 */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DESIGN = join(ROOT, "product/app/design");
const PORT = Number(process.env.SALA_PORT || 8304);
if (PORT === 25374) throw new Error("25374 está prohibido para la vara");

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".png": "image/png",
  ".svg": "image/svg+xml", ".webp": "image/webp", ".woff2": "font/woff2",
  ".md": "text/markdown", ".ico": "image/x-icon",
};
let mode = "ready";
let seq = 0;
let seen = [];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function chainedModelCalls(turn) {
  turn.model_calls = [];
  for (let step = 1; step <= 3; step += 1) {
    const started_at = Date.now();
    await wait(18);
    turn.model_calls.push({ step, started_at, finished_at: Date.now() });
  }
}

const json = (res, status, body) => {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
};
const bodyOf = async (req) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString();
  try { return raw ? JSON.parse(raw) : {}; } catch { return {}; }
};

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const url = new URL(req.url, "http://fixture");
  const path = url.pathname;

  if (path === "/__qa/state") return json(res, 200, { mode, seen });
  if (path === "/__qa/reset") {
    const body = await bodyOf(req);
    mode = body.mode || "ready"; seen = []; seq = 0;
    return json(res, 200, { ok: true, mode });
  }
  if (path === "/health") return json(res, 200, { status: "ok", fixture: "sala-e2e" });

  if (path.startsWith("/v1/")) {
    const body = await bodyOf(req);
    if (path === "/v1/auth/local" && req.method === "POST") {
      return json(res, 200, {
        id: "user-sala-e2e", email: "device::sala-e2e",
        session_token: "fixture-session", anon: true,
      });
    }
    if (path === "/v1/brains/status") {
      if (mode === "no-model") return json(res, 200, {
        providers: {
          claude_cli: { provider: "claude_cli", state: "not_installed",
            detail: "No hay un modelo utilizable.", installed: false },
        },
        service: { state: "ready", mode: "shared" },
      });
      return json(res, 200, {
        providers: {
          claude_cli: { provider: "claude_cli", state: "ready",
            detail: "sesión activa", installed: true },
        },
        service: { state: "ready", mode: "shared" },
      });
    }
    if (path === "/v1/motor/estado") return json(res, 200, {
      tipo: "cerebro", ref: "claude_cli",
      estado: mode === "no-model" ? "roto" : "probado",
      causa: mode === "no-model" ? "cli_no_instalado" : null,
      evidencia: { fixture: true }, ts: Date.now() / 1000,
    });
    if (path === "/v1/icons") return json(res, 200, { known: [] });
    if (path === "/v1/chats" && req.method === "POST") {
      return json(res, 200, { id: "chat-sala-e2e" });
    }
    if (path.startsWith("/v1/chats/")) {
      return json(res, 200, { id: "chat-sala-e2e", messages: [] });
    }
    if (path === "/v1/classify-turn") return json(res, 200, { turn: "chat" });
    if (path === "/v1/runs/estado") return json(res, 200, {
      vivo: null, huerfanos: [], cortado: null,
    });
    if (path === "/v1/puppets/run/stream") {
      const turn = {
        seq: ++seq,
        prompt: body.prompt || "",
        client_turn_id: body.client_turn_id || null,
        received_at: Date.now(),
      };
      seen.push(turn);
      if (mode === "fail-next") {
        mode = "ready";
        return json(res, 401, { detail: { error: "model_rejected",
          detail: "La key de la fixture fue rechazada." } });
      }
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Aleph-Accepted-At": String(Date.now()),
      });
      res.flushHeaders();
      turn.accepted_at = Date.now();
      await chainedModelCalls(turn);
      const answer = `Cierre ${turn.seq}: tres pasos completos.`;
      if (mode === "empty-next") {
        mode = "ready";
        res.write(`data: ${JSON.stringify({ type: "done", answer: "" })}\n\n`);
        res.end();
        return;
      }
      const frames = [
        { type: "thinking", text: "paso 1\n" },
        { type: "thinking", text: "paso 2\n" },
        { type: "thinking", text: "paso 3\n" },
        { type: "token", text: answer },
        { type: "done", answer },
      ];
      let ix = 0;
      const timer = setInterval(() => {
        if (ix >= frames.length) { clearInterval(timer); res.end(); return; }
        res.write(`data: ${JSON.stringify(frames[ix++])}\n\n`);
      }, 18);
      return;
    }
    return json(res, 200, {});
  }

  try {
    const rel = normalize(decodeURIComponent(path).replace(/^\/+/, ""));
    const file = join(DESIGN, rel || "sala/sala.html");
    if (!file.startsWith(DESIGN)) throw new Error("outside design root");
    const data = await readFile(file);
    res.writeHead(200, { "Content-Type": MIME[extname(file)] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("not found");
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`SALA_E2E_FIXTURE_READY http://127.0.0.1:${PORT}/sala/sala.html`);
});
