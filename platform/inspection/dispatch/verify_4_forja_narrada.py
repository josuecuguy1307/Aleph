#!/usr/bin/env python3
"""
verify_4_forja_narrada.py — done-bar de la rama 4-forja-narrada (sprint Cuarto launch).

Prueba las 3 piezas de la ola contra el stack VIVO (cero mocks del motor):

  (1) BRAIN DEFAULT — el forge de PRODUCTO sintetiza con el cerebro real SIN que el caller
      pase synthAlias (el default del cliente pasó de "oss" a "brain"): forja viva PokéAPI
      vía window.__inspectAndEquip → forge.iniciado.cerebro=="alias:brain" · ≥1 `sintetizando`
      · tool.propuesta.model ~ claude · mcp.forjado real → pieza equipada.
      (+ regresión TMDB token si la key del vault está.)
  (2) LATIDO — con PUPPET_FORGE_HEARTBEAT_S=1 el stream NARRA la espera del cerebro:
      ≥1 `forge.latido{elapsed_s,stage}` en el run (antes: silencio total ~90s).
  (3) 422 → DRAWER — un rechazo pre-stream (Pydantic 422) llega al carril de evidencia con
      su payload REAL y el drawer se AUTO-ABRE en fallo: window.__evidence.isOpen() · card
      error{stage:"despacho",status:422} · HUD legible (no un JSON crudo).
  (4) DEGRADED VISIBLE — backend en subproceso con el shim MUERTO
      (PUPPET_BRAIN_SHIM_BASE_URL→puerto sin listener): la UI muestra el corte honesto
      (reason "cerebro …degradada"), el drawer se abre con error{stage:"sintesis",
      degraded:true} y NO hay mcp.forjado (cero falso verde). Sin fallback silencioso a oss.

Correr:  product/backend/.venv/bin/python platform/inspection/dispatch/verify_4_forja_narrada.py
         (shim Opus vivo en :8923 = eval/shim_claude_code.py; GROQ_API_KEY se limpia acá)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── CEREBRO OPUS (shim), NO Groq — fijado ANTES de cualquier import del motor/modelos ──
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ.setdefault("PUPPET_BRAIN_SHIM_MODEL", "claude-code-opus-4.8")
os.environ.pop("GROQ_API_KEY", None)          # línea roja: el default nuevo NO debe caer a Groq
os.environ["PUPPET_FORGE_HEARTBEAT_S"] = "1"  # latidos densos → el assert (2) es determinístico
os.environ.setdefault("PUPPET_WORKERS", "0")

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for _p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _recover_tmdb_from_vault)
from inspection.dispatch.verify_integra_ola1 import _boot_frontend  # noqa: E402

SHIM = "http://127.0.0.1:8923/v1"
POKE = "https://pokeapi.co/api/v2"
TMDB = "https://api.themoviedb.org/3"
_POKE_HINT = ("PokéAPI REST read-only (sin login). GET /pokemon/{id} → un pokémon (sample id=1); "
              "GET /type/{id} → un tipo (sample id=1). Proponé esas lecturas con su sample id.")
_TMDB_HINT = ("TMDB v3 (api_key en query). GET /movie/{movie_id} → detalles (sample movie_id=550); "
              "GET /configuration → config. Proponé esas lecturas.")

CONTRACT_STAGES = {"forge.iniciado", "forge.latido", "sesion.ok", "observando", "sintetizando",
                   "tool.propuesta", "tool.validando", "tool.validada", "tool.descartada",
                   "mcp.forjado", "cerrado", "error"}

CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    CHECKS.append((label, bool(ok), extra))
    print(f"  {'✓' if ok else '✗'} {label}" + (f"  · {extra}" if extra else ""))


# el digest que la página devuelve por corrida (res + frames que los asserts leen)
_FORGE_JS = """
async (p) => {
  // [identidad visual 6/6] la revisión antes de equipar ya no cuelga de un modo: aparece
  // SIEMPRE y espera un toque. `autoSeal` da ESE toque (sin destildar nada) para que un
  // verificador headless recorra el MISMO panel real que ve una persona, sin colgarse.
  window.__manual && window.__manual.configure({ autoSeal: true });
  const res = await window.__inspectAndEquip(p.args);
  const evs = res.events || [];
  const by = {};
  for (const e of evs) by[e.type] = (by[e.type] || 0) + 1;
  const ini = evs.find(e => e.type === "forge.iniciado") || {};
  return {
    ok: res.ok === true, path: res.path, reason: res.reason || null, error: res.error || null,
    piece: res.piece ? { id: res.piece.id, label: res.piece.label } : null,
    server: res.server || null, tools: res.tools || [],
    counts: by, cerebro: ini.cerebro || null,
    propuestaModels: evs.filter(e => e.type === "tool.propuesta").map(e => String(e.model || "")),
    latidos: evs.filter(e => e.type === "forge.latido").map(e => ({ s: e.elapsed_s, stage: e.stage })),
    sintetizando: evs.filter(e => e.type === "sintetizando").map(e => ({ round: e.round, cerebro: e.cerebro })),
    errores: evs.filter(e => e.type === "error"),
    evOpen: !!(window.__evidence && window.__evidence.isOpen()),
    evCount: (window.__evidence && window.__evidence.count()) || 0,
  };
}
"""


def _shim_alive() -> bool:
    try:
        with urllib.request.urlopen(SHIM.replace("/v1", "") + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_health(port: int, tries: int = 150) -> bool:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> int:
    if not _shim_alive():
        print("✗ PRECONDICIÓN: el shim Opus :8923 no responde (python3 eval/shim_claude_code.py)")
        return 1
    print("✓ shim :8923 vivo")

    back = _free_port()
    front = _free_port()
    _boot_server(back)
    _boot_frontend(front, back)
    print(f"✓ backend :{back} + frontend :{front} (worktree 4-forja-narrada)")

    from playwright.sync_api import sync_playwright

    tmdb_key = ""
    try:
        tmdb_key = _recover_tmdb_from_vault() or ""
    except Exception:
        pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        console_errors: list[str] = []
        # mismo filtro que reel_capture/verify_icons: el navegador loguea "Failed to load resource"
        # para CUALQUIER respuesta 4xx — acá el 422 de la fase (3) es intencional, no un error JS.
        _NOISE = ("Failed to load resource", "favicon", "net::ERR")
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" and not any(n in m.text for n in _NOISE) else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.goto(f"http://127.0.0.1:{front}/cuarto/cuarto.pixi.html?puppet=cuarto-4-forja")
        page.wait_for_function("() => window.__cuarto && window.__inspectAndEquip && window.__evidence",
                               timeout=20000)

        # ── (1)+(2) BRAIN DEFAULT + LATIDO · PokéAPI abierto, SIN synthAlias ──────────────
        print("\n(1)+(2) forja viva PokéAPI con el DEFAULT del cliente (sin synthAlias)… ~1-3 min")
        a = page.evaluate(_FORGE_JS, {"args": {
            "service": POKE, "url": POKE, "forma": "open", "cred": None, "validatePath": "/",
            "apiShapeHint": _POKE_HINT, "maxRounds": 1, "seedCandidates": []}})
        check("(1a) cerebro del stream = alias:brain (default nuevo, sin pasar synthAlias)",
              a.get("cerebro") == "alias:brain", str(a.get("cerebro")))
        models = a.get("propuestaModels") or []
        check("(1b) tool.propuesta.model ~ claude (sintetizó el cerebro real, no Groq)",
              bool(models) and all(("claude" in m.lower() or "opus" in m.lower()) for m in models),
              f"models={sorted(set(models))}")
        check("(1c) mcp.forjado real → pieza equipada (ok:true, path:forged)",
              a.get("ok") is True and a.get("path") == "forged" and bool(a.get("piece"))
              and (a.get("counts", {}).get("mcp.forjado", 0) >= 1),
              f"server={a.get('server')} tools={len(a.get('tools') or [])}")
        sint = a.get("sintetizando") or []
        check("(1d) ≥1 `sintetizando` narró la Capa 3 (round + cerebro reales)",
              len(sint) >= 1 and all(s.get("cerebro") == "alias:brain" for s in sint),
              f"n={len(sint)}")
        lat = a.get("latidos") or []
        check("(2a) ≥1 `forge.latido` durante la espera (elapsed_s real ≥1)",
              len(lat) >= 1 and any((l.get("s") or 0) >= 1 for l in lat), f"n={len(lat)}")
        check("(2b) latido.stage ∈ vocabulario del contrato",
              all((l.get("stage") in CONTRACT_STAGES) for l in lat),
              f"stages={sorted({str(l.get('stage')) for l in lat})}")
        page.screenshot(path=str(_HERE / "4fn-1-forge-brain.png"))

        # ── (1e) regresión TMDB token con brain (si la key del vault está) ────────────────
        if tmdb_key:
            print("\n(1e) regresión TMDB (token) con brain… ~1-3 min")
            c = page.evaluate(_FORGE_JS, {"args": {
                "service": TMDB, "url": TMDB, "forma": "token", "cred": tmdb_key,
                "authIn": "query", "authParam": "api_key", "validatePath": "/configuration",
                "apiShapeHint": _TMDB_HINT, "maxRounds": 1, "seedCandidates": []}})
            check("(1e) TMDB token forja con brain (regresión Forma 1)",
                  c.get("ok") is True and c.get("cerebro") == "alias:brain",
                  f"path={c.get('path')} tools={len(c.get('tools') or [])}")
        else:
            print("  (1e) SKIP — sin TMDB key en el vault (no bloquea: PokéAPI ya probó el default)")

        # ── (3) 422 pre-stream → drawer auto-abierto con el detalle real ──────────────────
        print("\n(3) 422 pre-stream (max_rounds no-numérico)…")
        b = page.evaluate(_FORGE_JS, {"args": {
            "service": TMDB, "url": TMDB, "forma": "token", "cred": "x",
            "maxRounds": "no-numero", "seedCandidates": []}})
        err422 = next((e for e in (b.get("errores") or [])
                       if e.get("stage") == "despacho" and e.get("status") == 422), None)
        check("(3a) 422 → ok:false + evento error{stage:despacho,status:422} en el carril",
              b.get("ok") is False and err422 is not None, str(err422)[:90])
        check("(3b) drawer de evidencia AUTO-ABIERTO en fallo (con ≥1 card)",
              b.get("evOpen") is True and (b.get("evCount") or 0) >= 1,
              f"open={b.get('evOpen')} count={b.get('evCount')}")
        check("(3c) HUD legible: el error nombra el campo, no es un JSON crudo",
              bool(b.get("error")) and "max_rounds" in str(b.get("error"))
              and not str(b.get("error")).startswith("[{"), str(b.get("error"))[:80])
        page.screenshot(path=str(_HERE / "4fn-3-drawer-422.png"))

        check("(x) 0 errores JS de página en (1)-(3)", not console_errors,
              "; ".join(console_errors[:3]))
        browser.close()

    # ── (4) DEGRADED VISIBLE · backend+frontend en SUBPROCESO con shim MUERTO ────────────
    print("\n(4) shim muerto → corte honesto visible (subproceso)…")
    dead_back, dead_front = _free_port(), _free_port()
    env = dict(os.environ)
    env["PUPPET_BRAIN_SHIM"] = "1"
    env["PUPPET_BRAIN_SHIM_BASE_URL"] = f"http://127.0.0.1:{_free_port()}/v1"  # sin listener
    env["PUPPET_WORKERS"] = "0"
    env.pop("GROQ_API_KEY", None)
    pb = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir",
                           str(_BACKEND), "--host", "127.0.0.1", "--port", str(dead_back),
                           "--log-level", "warning"], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fenv = dict(env)
    fenv["ALEPH_FRONT_PORT"] = str(dead_front)
    fenv["ALEPH_BACKEND"] = f"http://127.0.0.1:{dead_back}"
    pf = subprocess.Popen([sys.executable, str(_APP / "serve.py")], env=fenv,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        check("(4-pre) backend con shim muerto levantó", _wait_health(dead_back))
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errs4: list[str] = []
            page.on("pageerror", lambda e: errs4.append(str(e)))
            page.goto(f"http://127.0.0.1:{dead_front}/cuarto/cuarto.pixi.html?puppet=cuarto-4fn-dead")
            page.wait_for_function("() => window.__cuarto && window.__inspectAndEquip && window.__evidence",
                                   timeout=20000)
            d = page.evaluate(_FORGE_JS, {"args": {
                "service": POKE, "url": POKE, "forma": "open", "cred": None, "validatePath": "/",
                "apiShapeHint": _POKE_HINT, "maxRounds": 1, "seedCandidates": []}})
            degr = next((e for e in (d.get("errores") or [])
                         if e.get("stage") == "sintesis" and e.get("degraded")), None)
            check("(4a) error{stage:sintesis,degraded:true} en el stream (corte honesto)",
                  degr is not None, str(degr)[:90])
            check("(4b) SIN mcp.forjado ni pieza (cero falso verde, cero fallback a oss)",
                  d.get("ok") is False and not d.get("piece")
                  and d.get("counts", {}).get("mcp.forjado", 0) == 0,
                  f"reason={str(d.get('reason'))[:60]}")
            check("(4c) reason visible nombra al cerebro degradado",
                  "cerebro" in str(d.get("reason") or "") and "degrad" in str(d.get("reason") or ""),
                  str(d.get("reason"))[:80])
            check("(4d) drawer auto-abierto con la evidencia del degradado",
                  d.get("evOpen") is True and (d.get("evCount") or 0) >= 1,
                  f"open={d.get('evOpen')} count={d.get('evCount')}")
            check("(4e) `sintetizando` narró ANTES del corte (la espera fue real)",
                  len(d.get("sintetizando") or []) >= 1, f"n={len(d.get('sintetizando') or [])}")
            page.screenshot(path=str(_HERE / "4fn-4-degraded.png"))
            check("(4x) 0 pageerrors en (4)", not errs4, "; ".join(errs4[:2]))
            browser.close()
    finally:
        pb.terminate()
        pf.terminate()

    (_HERE / "4fn-results.json").write_text(json.dumps(
        [{"check": c, "ok": o, "extra": x} for c, o, x in CHECKS], indent=2, ensure_ascii=False))
    bad = [c for c, o, _ in CHECKS if not o]
    print()
    if bad:
        print(f"RESULTADO: ROJO ({len(bad)}): " + " · ".join(bad))
        return 1
    print(f"RESULTADO: VERDE — forja narrada con brain ({len(CHECKS)} checks: default brain · "
          "latido · sintetizando · 422→drawer · degraded visible sin falso verde)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
