#!/usr/bin/env python3
"""
verify_integra_ola1.py — DONE-BAR de la integración Ola 1 (1a+1b+1c) DESDE LA UI del CUARTO,
con Playwright, en puertos propios (NO :8091), 0 errores de consola.

Prueba la VERTICAL COMPLETA por el botón "Inspeccionar" UNIFICADO de cuarto.pixi.html
(window.__inspectAndEquip → UN consumidor SSE, UN fetch, UN run de forja):

  (1) target real + token (TMDB) → el resolver da MISS → se dispara el Motor B (UN run).
  (2) coreografía 1-A: fantasmas (propuesta) → pulso (validando) → sólidas (validada) /
      desvanecidas (descartada), 1:1 con eventos REALES del MISMO stream (cero-teatro).
  (3) mcp.forjado → 1-B materializa la pieza REAL (server≠null, belt_ref, puppet_id), del
      MISMO run, NO hueca, NO una forja paralela (un solo mcp.forjado / forge.iniciado).
  (4) equipar → un RUN real la invoca con éxito (get_movie_details(550)→200 o equivalente).
  (5) target que SÍ está en el registry (stripe) → el resolver lo TRAE sin forjar; impostor
      DNS → RECHAZADO (sin equipar).

Gates de verificación (env, mismo patrón que los selftests):
  PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES=1  → el matcher REAL arbitra found/impostor (5).
  PUPPET_FORGE_ALLOW_SEED_PROBES=1         → una sonda 404 REAL fuerza una `tool.descartada` (2).

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_integra_ola1.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

# el gate de seed-probes tiene que estar ANTES de que el backend atienda el primer request.
os.environ["PUPPET_FORGE_ALLOW_SEED_PROBES"] = "1"
# el cerebro LOCAL del RUN (qwen3:8b por ollama) puede tardar en carga fría / razonamiento → damos
# margen al timeout de la llamada al modelo (default 60s) para que el primer turno complete.
os.environ.setdefault("PUPPET_HTTP_TIMEOUT", "150")

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _fake_spec, _cand, _recover_tmdb_from_vault)

PUPPET = "cuarto-integra-ola1"
CUARTO_PATH = f"/cuarto/cuarto.pixi.html?puppet={PUPPET}"


def _boot_frontend(front_port: int, back_port: int):
    """serve.py en un thread, sirviendo MI worktree design/ + proxy SSE al backend de este run."""
    os.environ["ALEPH_FRONT_PORT"] = str(front_port)
    os.environ["ALEPH_BACKEND"] = f"http://127.0.0.1:{back_port}"
    import importlib
    serve = importlib.import_module("serve")          # product/app/serve.py
    importlib.reload(serve)                            # re-lee PORT/BACK del env
    srv = serve.ThreadingHTTP(("", front_port), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import urllib.request
    for _ in range(100):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{front_port}/cuarto/cuarto.pixi.html", timeout=1) as r:
                if r.status == 200:
                    return srv
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("serve.py no sirvió cuarto.pixi.html a tiempo")


# ── JS: un clic en el botón unificado · devuelve un RESUMEN serializable (no el payload crudo) ──
_INSPECT_JS = """
async (p) => {
  // [identidad visual 6/6] la revisión antes de equipar ya no cuelga de un modo: aparece
  // SIEMPRE y espera un toque. `autoSeal` da ESE toque (sin destildar nada) para que un
  // verificador headless recorra el MISMO panel real que ve una persona, sin colgarse.
  window.__manual && window.__manual.configure({ autoSeal: true });
  const res = await window.__inspectAndEquip(p.args);
  const placed = window.__cuarto.placedTiles();
  const forgedPiece = placed.find(t => t.forged) || null;
  const resolvedPiece = placed.find(t => t.resolved) || null;
  const slim = (t) => t ? { id:t.id, server:t.server, belt_ref:t.belt_ref, puppet_id:t.puppet_id,
                            forged:!!t.forged, resolved:!!t.resolved, tools:t.tools, gated:!!t.gated } : null;
  const counts = {};
  for (const e of (res.events||[])) counts[e.type] = (counts[e.type]||0) + 1;
  return {
    ok: !!res.ok, path: res.path||null, origin: res.origin||null,
    server: res.server||null, belt_ref: res.belt_ref||null, tools: res.tools||[],
    rejected_impostor: !!res.rejected_impostor, reason: res.reason||null,
    choreo: res.choreo||null, eventCounts: counts,
    forgedPiece: slim(forgedPiece), resolvedPiece: slim(resolvedPiece),
  };
}
"""

# ── JS: RUN real síncrono que invoca la pieza forjada (mismo handoff que el botón ▶ RUN) ──
_RUN_JS = """
async (p) => {
  const c = window.__cuarto;
  // El RUN usa el cerebro LOCAL (ollama qwen3:8b, id "qwen-local" → alias oss-direct): tool-use real,
  // sin TPM (Groq recién quemó su ventana en la forja, y su turno >60s aborta el run). La forja SÍ
  // necesita Groq (el shim Opus rehúsa forjar); el RUN no — la red de seguridad local lo completa.
  c.nucleoData().model = (p.model || "qwen-local");
  window.__sync();
  const recipe = window.__lastRecipe;
  const tools = p.tools || [];
  const pick = (re) => tools.find(t => re.test(t));
  let aTool, hint;
  const noArg = pick(/popular|genre_list|trending|now_playing|top_rated|upcoming|discover/i);
  if (pick(/get_movie_details/)) { aTool="get_movie_details"; hint="con movie_id=550 (Fight Club)"; }
  else if (pick(/movie_release_dates/)) { aTool=pick(/movie_release_dates/); hint="con movie_id=550"; }
  else if (pick(/person_details/)) { aTool=pick(/person_details/); hint="con person_id=287 (Brad Pitt)"; }
  else if (pick(/tv_details|tv_aggregate/)) { aTool=pick(/tv_details|tv_aggregate/); hint="con tv_id=1399"; }
  else if (noArg) { aTool=noArg; hint="(no necesita argumentos)"; }
  else { aTool=tools[0]; hint="con movie_id=550 si pide un id"; }
  const prompt = `Tenés equipada la herramienta TMDB \\`${aTool}\\`. Llamala AHORA MISMO ${hint}. ` +
    `No pidas aclaraciones ni inventes datos: ejecutá la herramienta con ese valor real y, con lo que ` +
    `devuelva, decime en una sola frase un dato concreto del resultado. /no_think`;
  const r = await fetch("/v1/puppets/run", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ recipe, prompt, space_id:"verify-ola1-"+Date.now(), deadline_s:240 }),
  });
  const body = await r.json().catch(()=>null);
  const rec = (body && body.record) || {};
  const forged = new Set(tools);
  return {
    status: r.status, ok: !!(body && body.ok),
    cabled: (rec.tools_cabled||[]).filter(t => forged.has(t.tool||t.name||t)).map(t=>t.tool||t.name||t),
    called: (rec.tool_calls||[]).filter(tc => forged.has(tc.tool||tc.name)).map(tc=>tc.tool||tc.name),
    model_final: rec.model_final, degraded: !!rec.degraded,
    error: (body&&body.error)||rec.error||null, steps: (body&&body.trajectory_steps)||rec.steps||null,
    answer: (body&&body.answer)||"",
    recipe_model: recipe && recipe.model, recmodel_alias: recipe && recipe.model && recipe.model.alias,
    rec_keys: Object.keys(rec), all_tool_calls: rec.tool_calls||[],
    body_dump: JSON.stringify(body).slice(0, 1800),
  };
}
"""


def _prewarm_ollama(model: str = "qwen3:8b") -> None:
    """Carga el modelo local en memoria de ollama (la 1ra inferencia en frío tarda ~80s). Best-effort."""
    import json as _json
    import urllib.request
    try:
        data = _json.dumps({"model": model, "prompt": "ok", "stream": False,
                            "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=data,
                                     headers={"content-type": "application/json"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=180) as r:
            r.read()
        print(f"  · ollama {model} precalentado en {time.time()-t0:.0f}s")
    except Exception as e:
        print(f"  ⚠ no pude precalentar ollama ({e}) — el RUN puede tardar en carga fría")


def main() -> int:
    from playwright.sync_api import sync_playwright

    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    have_forge = bool(tmdb_key) and bool(os.environ.get("GROQ_API_KEY"))

    back_port, front_port = _free_port(), _free_port()
    print("═" * 72)
    print(f"  VERIFY INTEGRA-OLA1 (Cuarto) · backend :{back_port} · front :{front_port}")
    print(f"  forja-en-vivo (1·2·3·4): {'SÍ (TMDB+Groq)' if have_forge else 'OMITIDA (falta key)'}")
    print("═" * 72)

    server, _ = _boot_server(back_port)            # setea PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES=1
    _front = _boot_frontend(front_port, back_port)
    if have_forge:
        _prewarm_ollama()                          # carga qwen3:8b en memoria antes del RUN (4)
    tmp = Path(tempfile.mkdtemp(prefix="ola1-ui-"))

    # fixtures de (5): candidato verificado (DNS) + spec del MCP local real + impostor (github fork)
    fake = _fake_spec(tmp, tools=["get_account", "list_charges"], server_name="stripe-local")
    verified = _cand("com.stripe/mcp", "com.stripe", "stripe", "dns", "Stripe",
                     "Stripe payments MCP", "https://mcp.stripe.com")
    impostor = _cand("io.github.evil/stripe-mcp", "io.github.evil", "evil", "github_org",
                     "Stripe (unofficial)", "stripe-like community fork", "https://evil.example/mcp")
    # sonda 404 REAL → fuerza una tool.descartada (la coreografía de "desvanecidas")
    probe404 = {"name": "pelicula_fantasma", "endpoint": "/movie/{movie_id}", "method": "GET",
                "path_params": {"movie_id": "0"}, "kind": "read"}

    console_errors: list[str] = []
    R = {}
    base = f"http://127.0.0.1:{front_port}"
    cuarto_url = base + CUARTO_PATH
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1320, "height": 880})
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            def open_cuarto():
                page.goto(cuarto_url, wait_until="load")
                page.wait_for_function("() => window.__cuarto && window.__inspectAndEquip", timeout=15000)

            # ── (1)(2)(3)(4) TMDB: miss → forja → pieza real → RUN ───────────────────────
            forged_tools = []
            if have_forge:
                open_cuarto()
                print("  · forjando TMDB en vivo (dispatch → Motor B + Groq)… ~30-120s")
                f = page.evaluate(_INSPECT_JS, {"args": {
                    "service": "https://api.themoviedb.org/3",
                    "url": "https://api.themoviedb.org/3", "cred": tmdb_key,
                    "maxRounds": 2, "seedCandidates": [], "seedProbes": [probe404],
                    "synthAlias": "oss"}})
                ec = f.get("eventCounts") or {}
                ch = f.get("choreo") or {}
                fp = f.get("forgedPiece") or {}
                forged_tools = f.get("tools") or []

                # (1) resolver MISS → Motor B, UN run (un solo forge.iniciado / mcp.forjado)
                p1 = (ec.get("resolver.miss", 0) >= 1 and ec.get("dispatch.forjando", 0) >= 1
                      and ec.get("forge.iniciado", 0) == 1 and ec.get("mcp.forjado", 0) == 1
                      and f.get("path") == "forged")
                R["(1) resolver miss → Motor B · UN run"] = p1
                print(f"    (1) miss={ec.get('resolver.miss',0)} forjando={ec.get('dispatch.forjando',0)} "
                      f"forge.iniciado={ec.get('forge.iniciado',0)} mcp.forjado={ec.get('mcp.forjado',0)} "
                      f"→ {'✅' if p1 else '❌'}")

                # (2) coreografía 1:1 con eventos reales (fantasmas/pulso/sólidas/desvanecidas)
                p2 = (ec.get("tool.propuesta", 0) >= 1 and ec.get("tool.validando", 0) >= 1
                      and ec.get("tool.validada", 0) >= 1 and ec.get("tool.descartada", 0) >= 1
                      and ch.get("connected") is True and ch.get("forged") is True)
                R["(2) coreografía 1:1 (cero-teatro)"] = p2
                print(f"    (2) propuesta={ec.get('tool.propuesta',0)} validando={ec.get('tool.validando',0)} "
                      f"validada={ec.get('tool.validada',0)} descartada={ec.get('tool.descartada',0)} "
                      f"· choreo conectado={ch.get('connected')} forjado={ch.get('forged')} "
                      f"validadas={ch.get('validated')} → {'✅' if p2 else '❌'}")

                # (3) pieza REAL del MISMO run (server≠null, belt_ref, puppet_id), no hueca
                p3 = (f.get("ok") is True and f.get("path") == "forged"
                      and bool(fp.get("server")) and str(fp.get("server")).startswith("forge")
                      and bool(fp.get("belt_ref")) and bool(fp.get("puppet_id"))
                      and bool(fp.get("forged")) and len(fp.get("tools") or []) >= 1)
                R["(3) mcp.forjado → pieza REAL (no hueca)"] = p3
                print(f"    (3) ok={f.get('ok')} server={fp.get('server')} "
                      f"belt_ref={'✓' if fp.get('belt_ref') else '∅'} puppet_id={fp.get('puppet_id')} "
                      f"tools={len(fp.get('tools') or [])} → {'✅' if p3 else '❌'}")

                # (4) RUN real invoca la pieza forjada (handoff belt_ref → runtime). El forge acaba de
                # consumir TPM de Groq → opcional dejar respirar la ventana antes del run (env).
                delay_s = int(os.environ.get("OLA1_RUN_DELAY_S", "0") or "0")
                if delay_s > 0:
                    print(f"    · esperando {delay_s}s para que respire el TPM de Groq antes del RUN…")
                    page.wait_for_timeout(delay_s * 1000)
                run = page.evaluate(_RUN_JS, {"tools": forged_tools})
                p4 = (run.get("ok") is True and len(run.get("cabled") or []) >= 1
                      and len(run.get("called") or []) >= 1)
                R["(4) RUN real la invoca (get_movie_details→200)"] = p4
                print(f"    (4) run ok={run.get('ok')} cableadas={len(run.get('cabled') or [])} "
                      f"llamadas={run.get('called')} model_final={run.get('model_final')} "
                      f"degraded={run.get('degraded')} → {'✅' if p4 else '❌'}")
                if not p4:
                    print(f"        error={str(run.get('error'))[:200]!r} steps={run.get('steps')} "
                          f"answer={str(run.get('answer'))[:140]!r}")
                    print(f"        recipe_model={run.get('recipe_model')}")
                    print(f"        rec_keys={run.get('rec_keys')}")
                    print(f"        all_tool_calls={str(run.get('all_tool_calls'))[:300]}")
                    print(f"        body_dump={run.get('body_dump')}")
            else:
                print("  ⚠ (1)/(2)/(3)/(4) OMITIDOS: falta GROQ_API_KEY o TMDB key.")

            # ── (5a) stripe FOUND en registry → traído sin forjar ────────────────────────
            open_cuarto()
            a = page.evaluate(_INSPECT_JS, {"args": {
                "service": "stripe", "url": None, "cred": None,
                "seedCandidates": [verified], "seedSpec": fake}})
            eca = a.get("eventCounts") or {}
            rp = a.get("resolvedPiece") or {}
            no_forge = not any(eca.get(t, 0) for t in
                               ("forge.iniciado", "dispatch.forjando", "mcp.forjado", "observando"))
            p5a = (a.get("ok") is True and a.get("path") == "registry" and a.get("origin") == "registry"
                   and eca.get("resolver.encontrado", 0) >= 1 and eca.get("mcp.equipado", 0) >= 1
                   and no_forge and bool(rp.get("server")) and bool(rp.get("belt_ref"))
                   and len(rp.get("tools") or []) >= 1 and bool(rp.get("resolved")))
            R["(5a) stripe found → traído sin forjar"] = p5a
            print(f"  (5a) path={a.get('path')} encontrado={eca.get('resolver.encontrado',0)} "
                  f"equipado={eca.get('mcp.equipado',0)} forge_corrió={not no_forge} "
                  f"server={rp.get('server')} tools={len(rp.get('tools') or [])} → {'✅' if p5a else '❌'}")

            # ── (5b) impostor DNS → rechazado, sin equipar ───────────────────────────────
            open_cuarto()
            c = page.evaluate(_INSPECT_JS, {"args": {
                "service": "stripe", "url": None, "cred": None, "seedCandidates": [impostor]}})
            ecc = c.get("eventCounts") or {}
            p5b = (c.get("rejected_impostor") is True and ecc.get("resolver.miss", 0) >= 1
                   and ecc.get("mcp.equipado", 0) == 0 and ecc.get("resolver.encontrado", 0) == 0
                   and ecc.get("mcp.forjado", 0) == 0 and c.get("resolvedPiece") is None
                   and c.get("forgedPiece") is None)
            R["(5b) impostor → rechazado, sin equipar"] = p5b
            print(f"  (5b) rejected={c.get('rejected_impostor')} miss={ecc.get('resolver.miss',0)} "
                  f"equipado={ecc.get('mcp.equipado',0)} encontrado={ecc.get('resolver.encontrado',0)} "
                  f"piezas=∅:{c.get('resolvedPiece') is None and c.get('forgedPiece') is None} "
                  f"→ {'✅' if p5b else '❌'}")

            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.3)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "─" * 72)
    print(f"  errores de consola: {len(console_errors)}")
    for e in console_errors:
        print(f"    ✗ {e}")
    R["consola 0 errores"] = not console_errors

    print("═" * 72)
    for k, v in R.items():
        print(f"  {k:46s}: {'✅ VERDE' if v else '❌ ROJO'}")
    if not have_forge:
        print("  (1)/(2)/(3)/(4) no evaluados (forja en vivo omitida — falta key)")
    allok = all(R.values()) and have_forge
    print("═" * 72)
    print(f"  TOTAL: {'✅ TODO VERDE — vertical Ola 1 integrada' if allok else '❌ HAY ROJO o forja omitida'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
