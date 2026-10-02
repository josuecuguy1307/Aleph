#!/usr/bin/env python3
"""
verify_2e_evidencia.py — DONE-BAR del TERCER CARRIL (evidencia técnica cruda por evento),
DESDE LA UI del Cuarto, con Playwright, en puertos propios (NO :8091), 0 errores de consola.

Corre UNA forja REAL (TMDB + Groq) por el camino 1-A `window.__startForgeInspection` (coreografía
SOLA, sin equipar → el modelo no se toca), con una sonda 404 REAL para ejercitar `tool.descartada`.
El overlay de evidencia (cuarto.evidence.js) está cableado al MISMO `onEvent`, así que captura el
payload crudo de cada evento. Sobre ese run, prueba:

  (a) modo dev OFF  → coreografía corrió (run ok, propuesta/validada/descartada reales) PERO el
                      cajón está oculto y NO hay ni una tarjeta de evidencia renderizada (regresión).
  (b) modo dev ON   → al tocar el toggle, cada evento del stream tiene su tarjeta y el payload crudo
                      mostrado es EL EVENTO LITERAL (deep-equal con window.__ev) — cero fabricación.
  (c) tool.validada → el request (del validando apareado) y la respuesta (status 200 + payload real)
                      mostrados COINCIDEN con lo que el motor disparó de verdad (no inventados).
  (d) modelo del Cuarto byte-idéntico antes/después (el overlay es de lectura, no muta nada).

Gate de verificación (lo prende la importación de verify_integra_ola1):
  PUPPET_FORGE_ALLOW_SEED_PROBES=1  → la sonda 404 REAL pasa por el candado y cae como descartada.

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_2e_evidencia.py
"""
from __future__ import annotations

import json
import os
import sys
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

# importar verify_integra_ola1 prende PUPPET_FORGE_ALLOW_SEED_PROBES=1 + sube PUPPET_HTTP_TIMEOUT,
# y nos da _boot_frontend; el resto de helpers salen del selftest del despachador.
from inspection.dispatch.verify_integra_ola1 import _boot_frontend  # noqa: E402
from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _recover_tmdb_from_vault)

PUPPET = "cuarto-2e-evidencia"
CUARTO_PATH = f"/cuarto/cuarto.pixi.html?puppet={PUPPET}"
SHOTDIR = _APP / "design" / "cuarto" / "screenshots"

URL_TARGET = "https://api.themoviedb.org/3"

# ── JS: arranca la forja 1-A (coreografía sola, NO equipa) y captura los eventos crudos ──
_FORGE_JS = """
(p) => {
  window.__ev = []; window.__done = false; window.__res = null;
  window.__startForgeInspection({
    url: p.url, cred: p.cred, seedProbes: p.seeds,
    onEvent: (e) => window.__ev.push(e),
  }).then((r) => { window.__res = r; window.__done = true; })
    .catch((e) => { window.__res = { ok: false, error: String(e) }; window.__done = true; });
  return true;
}
"""

# ── JS: snapshot del modelo (byte-idéntico antes/después = overlay no muta) ──
_SNAP_JS = """
() => ({
  model: JSON.stringify(window.__cuarto.relationModel()),
  pieces: JSON.stringify(window.__cuarto.pieces()),
  relations: JSON.stringify(window.__cuarto.relations()),
  placed: JSON.stringify(window.__cuarto.placedTiles()),
})
"""

# ── JS: estado con dev OFF (cajón oculto, cero tarjetas) ──
_PHASE_OFF_JS = """
() => {
  const ev = window.__ev || [];
  const drawer = document.getElementById('evDrawer');
  const counts = ev.reduce((a, e) => { a[e.type] = (a[e.type] || 0) + 1; return a; }, {});
  return {
    evLen: ev.length,
    isOpen: window.__evidence.isOpen(),
    evCount: window.__evidence.count(),
    drawerDisplay: drawer ? getComputedStyle(drawer).display : 'MISSING',
    cardCount: document.querySelectorAll('#evBody .ev-card').length,
    toggleExists: !!document.getElementById('evToggle'),
    resOk: !!(window.__res && window.__res.ok),
    resErr: (window.__res && window.__res.error) || null,
    types: [...new Set(ev.map(e => e.type))],
    counts,
  };
}
"""

# ── JS: estado con dev ON (cada evento → tarjeta; payload crudo == evento literal) ──
_PHASE_ON_JS = """
() => {
  const ev = window.__ev || [];
  const drawer = document.getElementById('evDrawer');
  const cards = [...document.querySelectorAll('#evBody .ev-card')];
  const parse = (s) => { try { return JSON.parse(s); } catch (e) { return null; } };
  const norm = (o) => JSON.stringify(o);
  const rawOf = (c) => { const pre = c.querySelector('.ev-raw'); return pre ? pre.textContent : null; };

  // (b) TODA tarjeta muestra su evento LITERAL (deep-equal) — cero fabricación
  let allRawMatch = cards.length === ev.length && cards.length > 0;
  const mismatch = [];
  cards.forEach((c) => {
    const i = Number(c.dataset.idx);
    const parsed = parse(rawOf(c));
    if (!parsed || norm(parsed) !== norm(ev[i])) { allRawMatch = false; mismatch.push(i); }
  });

  // (c) una tool.validada con respuesta dura (status 200 + payload real = snippet de texto del
  // body) + su validando apareado. payload del contrato es STRING (res.text[:240]), no objeto.
  const vIdx = ev.findIndex((e) => e.type === 'tool.validada' && e.status === 200
                 && typeof e.payload === 'string' && e.payload.length > 0);
  let validada = null;
  if (vIdx >= 0) {
    const evV = ev[vIdx];
    const card = cards.find((c) => Number(c.dataset.idx) === vIdx);
    const cardParsed = card ? parse(rawOf(card)) : null;
    let vdIdx = -1;
    for (let k = vIdx - 1; k >= 0; k--) {
      if (ev[k].type === 'tool.validando' && ev[k].nombre === evV.nombre) { vdIdx = k; break; }
    }
    const vdEv = vdIdx >= 0 ? ev[vdIdx] : null;
    const vdCard = vdIdx >= 0 ? cards.find((c) => Number(c.dataset.idx) === vdIdx) : null;
    const vdParsed = vdCard ? parse(rawOf(vdCard)) : null;
    const payloadSlice = evV.payload.slice(0, 40);
    validada = {
      nombre: evV.nombre, status: evV.status, payloadLen: evV.payload.length,
      payloadHead: evV.payload.slice(0, 80),
      // la RESPUESTA mostrada == el evento real (deep-equal del payload crudo = cero fabricación)
      respCardMatchesEvent: cardParsed ? norm(cardParsed) === norm(evV) : false,
      respCardShowsStatus: card ? /(^|[^0-9])200([^0-9]|$)/.test(card.textContent) : false,
      respCardShowsPayload: card ? card.textContent.includes(payloadSlice) : false,
      // el REQUEST mostrado == el que el motor disparó (request del validando == _request_of del engine)
      validandoIdx: vdIdx,
      reqEndpoint: vdEv && vdEv.request ? vdEv.request.endpoint : null,
      reqMethod: vdEv && vdEv.request ? vdEv.request.method : null,
      reqCardMatchesEvent: vdParsed ? norm(vdParsed) === norm(vdEv) : false,
      reqCardShowsEndpoint: (vdCard && vdEv && vdEv.request)
        ? vdCard.textContent.includes(vdEv.request.endpoint) : false,
    };
  }

  // bonus: descartada muestra el error EXACTO (no "falló")
  const dIdx = ev.findIndex((e) => e.type === 'tool.descartada');
  let descartada = null;
  if (dIdx >= 0) {
    const card = cards.find((c) => Number(c.dataset.idx) === dIdx);
    const motivo = ev[dIdx].motivo;
    descartada = {
      nombre: ev[dIdx].nombre, motivo, symptom: ev[dIdx].symptom,
      cardShowsMotivo: card && motivo ? card.textContent.includes(String(motivo).slice(0, 24)) : false,
    };
  }

  return {
    isOpen: window.__evidence.isOpen(),
    drawerDisplay: getComputedStyle(drawer).display,
    cardCount: cards.length, evLen: ev.length,
    allRawMatch, mismatch, vIdx, validada, dIdx, descartada,
  };
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    SHOTDIR.mkdir(parents=True, exist_ok=True)
    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    have_forge = bool(tmdb_key) and bool(os.environ.get("GROQ_API_KEY"))

    back_port, front_port = _free_port(), _free_port()
    print("═" * 72)
    print(f"  VERIFY 2e-EVIDENCIA (Cuarto) · backend :{back_port} · front :{front_port}")
    print(f"  forja-en-vivo (a·b·c·d): {'SÍ (TMDB+Groq)' if have_forge else 'OMITIDA (falta key)'}")
    print("═" * 72)
    if not have_forge:
        print("  ❌ sin GROQ_API_KEY o TMDB key → no se puede probar evidencia REAL. Abortando.")
        return 2

    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)

    probe404 = {"name": "pelicula_fantasma", "endpoint": "/movie/{movie_id}", "method": "GET",
                "path_params": {"movie_id": "0"}, "kind": "read"}

    console_errors: list[str] = []
    R: dict[str, bool] = {}
    base = f"http://127.0.0.1:{front_port}"
    cuarto_url = base + CUARTO_PATH
    info: dict = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1320, "height": 880}, device_scale_factor=2)
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            page.goto(cuarto_url, wait_until="load")
            page.wait_for_function(
                "() => window.__cuarto && window.__cuarto.forge && window.__startForgeInspection "
                "&& window.__evidence", timeout=15000)
            page.wait_for_timeout(500)

            before = page.evaluate(_SNAP_JS)

            # ── FORJA REAL (única) — coreografía 1-A + evidencia, sin equipar ──
            print("  · forjando TMDB en vivo (Motor B + Groq, sonda 404 real)… ~30-150s")
            page.evaluate(_FORGE_JS, {"url": URL_TARGET, "cred": tmdb_key, "seeds": [probe404]})
            t0 = time.time()
            while time.time() - t0 < 210:
                if page.evaluate("() => window.__done"):
                    break
                page.wait_for_timeout(200)
            done = page.evaluate("() => window.__done")
            page.wait_for_timeout(300)

            after = page.evaluate(_SNAP_JS)

            # ════ (a) modo dev OFF · cajón oculto + cero tarjetas, pero la coreografía corrió ════
            off = page.evaluate(_PHASE_OFF_JS)
            info["off"] = off
            page.screenshot(path=str(SHOTDIR / "2e-00-dev-off-clean.png"))
            assert_a = (
                done is True and off["resOk"] is True
                and off["toggleExists"] is True
                and off["isOpen"] is False
                and off["drawerDisplay"] == "none"
                and off["cardCount"] == 0
                and off["counts"].get("tool.propuesta", 0) >= 1
                and off["counts"].get("tool.validada", 0) >= 1
                and off["counts"].get("tool.descartada", 0) >= 1
                and off["evCount"] == off["evLen"]      # capturó en memoria, pero NO pintó nada
            )
            R["(a) dev OFF · coreografía limpia, sin evidencia visible"] = assert_a
            print(f"    (a) run_ok={off['resOk']} cajón={off['drawerDisplay']} tarjetas={off['cardCount']} "
                  f"capturados={off['evCount']} · counts(prop/val/desc)="
                  f"{off['counts'].get('tool.propuesta',0)}/{off['counts'].get('tool.validada',0)}/"
                  f"{off['counts'].get('tool.descartada',0)} → {'✅' if assert_a else '❌'}")

            # ── tocar el TOGGLE (modo dev) — clic REAL del botón ──
            page.click("#evToggle")
            page.wait_for_timeout(300)
            on = page.evaluate(_PHASE_ON_JS)
            info["on"] = on
            page.screenshot(path=str(SHOTDIR / "2e-01-dev-on-evidence.png"))

            # ════ (b) modo dev ON · cada evento → tarjeta, payload crudo == evento literal ════
            assert_b = (
                on["isOpen"] is True
                and on["drawerDisplay"] == "flex"
                and on["evLen"] >= 6
                and on["cardCount"] == on["evLen"]
                and on["allRawMatch"] is True
            )
            R["(b) dev ON · evidencia cruda real por evento (cero fabricación)"] = assert_b
            print(f"    (b) cajón={on['drawerDisplay']} tarjetas={on['cardCount']}/{on['evLen']} "
                  f"raw==evento(todas)={on['allRawMatch']} mismatch={on['mismatch']} "
                  f"→ {'✅' if assert_b else '❌'}")

            # ════ (c) tool.validada · request+response mostrados == lo que el motor disparó ════
            v = on.get("validada") or {}
            assert_c = bool(
                on.get("vIdx", -1) >= 0 and v
                and v.get("status") == 200 and (v.get("payloadLen") or 0) > 0
                and v.get("respCardMatchesEvent") is True
                and v.get("respCardShowsStatus") is True
                and v.get("respCardShowsPayload") is True
                and v.get("validandoIdx", -1) >= 0
                and v.get("reqCardMatchesEvent") is True
                and v.get("reqCardShowsEndpoint") is True
            )
            R["(c) tool.validada · request+response REALES (no inventados)"] = assert_c
            print(f"    (c) tool={v.get('nombre')} status={v.get('status')} "
                  f"payloadLen={v.get('payloadLen')} resp:match={v.get('respCardMatchesEvent')} "
                  f"status_visible={v.get('respCardShowsStatus')} payload_visible={v.get('respCardShowsPayload')} "
                  f"· req {v.get('reqMethod')} {v.get('reqEndpoint')} match={v.get('reqCardMatchesEvent')} "
                  f"endpoint_visible={v.get('reqCardShowsEndpoint')} → {'✅' if assert_c else '❌'}")
            print(f"        payload (real, head): {str(v.get('payloadHead'))!r}")
            d = on.get("descartada") or {}
            print(f"        descartada bonus: {d.get('nombre')} motivo_visible={d.get('cardShowsMotivo')} "
                  f"motivo={str(d.get('motivo'))[:60]!r}")

            # ════ (d) modelo del Cuarto byte-idéntico antes/después (overlay = lectura) ════
            assert_d = (before["model"] == after["model"] and before["pieces"] == after["pieces"]
                        and before["relations"] == after["relations"] and before["placed"] == after["placed"])
            R["(d) modelo del Cuarto sin mutar (overlay de lectura)"] = assert_d
            print(f"    (d) modelo idéntico={before['model']==after['model']} piezas={before['pieces']==after['pieces']} "
                  f"relaciones={before['relations']==after['relations']} placed={before['placed']==after['placed']} "
                  f"→ {'✅' if assert_d else '❌'}")

            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.3)

    print("\n" + "─" * 72)
    print(f"  errores de consola: {len(console_errors)}")
    for e in console_errors:
        print(f"    ✗ {e}")
    R["consola · 0 errores"] = not console_errors

    print("═" * 72)
    for k, val in R.items():
        print(f"  {k:54s}: {'✅ VERDE' if val else '❌ ROJO'}")
    allok = all(R.values())
    print("═" * 72)
    print(f"  capturas: {SHOTDIR / '2e-00-dev-off-clean.png'}")
    print(f"            {SHOTDIR / '2e-01-dev-on-evidence.png'}")
    print(f"  TOTAL: {'✅ TODO VERDE — tercer carril (evidencia) cerrado' if allok else '❌ HAY ROJO'}")
    # dump para diagnóstico si algo falla
    if not allok:
        print("\nINFO_JSON_START"); print(json.dumps(info, indent=2)[:4000]); print("INFO_JSON_END")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
