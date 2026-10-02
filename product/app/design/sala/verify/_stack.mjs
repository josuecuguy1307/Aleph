/* _stack.mjs — preflight del stack vivo. NO spawnea nada: verifica y FALLA HONESTO
 * por pieza, con el comando exacto para levantar la que falte. */
import { FRONT, BACK, SHIM } from "./_env.mjs";

async function ping(url, label, hint) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return { label, ok: true };
  } catch (e) {
    return { label, ok: false, err: String(e && e.message || e), hint };
  }
}

/* Devuelve {ok, pieces[]}. Si requireShim=false, el shim caído no bloquea (casos stub). */
export async function preflight({ requireShim = true } = {}) {
  const pieces = await Promise.all([
    ping(BACK + "/health", "backend :8080",
      "cd product/backend && PUPPET_HTTP_TIMEOUT=240 PUPPET_BRAIN_SHIM=1 PUPPET_BRAIN_SHIM_MODEL=claude-code-opus-4.8 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080   (el timeout largo es OBLIGATORIO: una completion de Opus vía shim tarda 60-100s; con el default 60s el run muere con BrokenPipe y ok=false)"),
    ping(FRONT + "/sala/sala.html", "front :8091",
      "python3 product/app/serve.py   (desde el worktree cuyo frontend querés servir)"),
    ping(SHIM + "/health", "brain shim :8923",
      "python3 eval/shim_claude_code.py   (cuenta Max vía claude -p, sin API key)"),
  ]);
  let ok = true;
  for (const p of pieces) {
    if (p.ok) { console.log("  ✓ " + p.label); continue; }
    const blocking = requireShim || !p.label.includes("shim");
    console.log((blocking ? "  ✗ " : "  ~ ") + p.label + " — " + p.err);
    if (blocking) { console.log("     levantar con: " + p.hint); ok = false; }
  }
  return { ok, pieces };
}
