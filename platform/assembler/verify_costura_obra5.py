#!/usr/bin/env python3
"""Vara única Gate 3 · Obra 5: LA PLATAFORMA DICE LA VERDAD.

    python3 platform/assembler/verify_costura_obra5.py

Mide los tres agujeros de la auditoría 4 y el acta que los ordena:

  O1 · G-1  el ✓ mentiroso del log de la Sala          → V1 V2 V3 V4 V5
  O2 · G-3  el auto-retry que nunca dispara            → V6
  O3 · G-2  el gate invisible en el moat               → V7

── DE DÓNDE SALE CADA MEDICIÓN ─────────────────────────────────────────────────────
V1-V5 NO se afirman leyendo código: los mide `arnes_costura_obra5.mjs` en WebKit REAL
(el motor de WKWebView, el mismo de la .app) contra LA SALA DE ESTE ÁRBOL, entrando por
los DOS caminos de producción que pintan la línea —el VIVO (`narrateEvent`) y el del
RECORD (`lineaDelRecord`, el del stream cortado, que es el de G-1)— y leyendo el DOM:
la clase, el copy y el COLOR COMPUTADO de cada entrada.

El acta pide «ni el verde del éxito ni el rojo del error», y eso sólo se prueba mirando
el píxel. Por eso V4 exige el ámbar exacto del Cuarto y V5b exige que los CUATRO colores
sean CUATRO — si dos estados colapsan en el mismo color, la vara cae aunque cada caso
pase por separado. Ese es el discriminante que le faltaba a la vara de F4d.

V6 cotejo el mapa de auto-retry de la Sala, clave por clave, contra el vocabulario SELLADO
del backend, importado de verdad (`errores_modelo`), no transcripto.

V7 corre los DOS constructores de trayectoria de verdad.

── LO QUE ESTA VARA NO HACE, A PROPÓSITO ───────────────────────────────────────────
NO SPAWNEA OTRAS VARAS. Es la regla sellada («prohibido anidar varas: durante la obra sólo
la propia, antes del merge una corrida de qa/correr_varas.py»), y hoy pesa doble: hay una
tanda de varas VIVA de otro carril (F7) sobre el mismo store del CLI. La regresión de obras
1-4 se corre aparte y se reporta aparte.

Cero red, cero backend, cero puertos fijos: el arnés levanta un estático en puerto EFÍMERO
que le da el SO y contesta todo `/v1/**` con `{}`. JAMÁS :8377 ni :25374.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for path in (HERE, ROOT / "platform", BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import errores_modelo as em  # noqa: E402
from app.phase1 import instrumentation as instr  # noqa: E402
from app.phase1 import executor  # noqa: E402

ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_obra5.mjs"
AMBAR_DEL_CUARTO = "rgb(255, 180, 84)"   # 0xffb454 · cuarto.render.js:2154 (aura `held`)
PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: Any = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL {name} — {detail}")


def main() -> int:
    # ══ EL FRENTE (V1-V5) ══════════════════════════════════════════════════════════
    corrida = subprocess.run([_node(), str(ARNES)], cwd=ROOT, text=True, capture_output=True)
    if corrida.returncode != 0:
        check("arnés del frente corre", False, (corrida.stderr or corrida.stdout)[-400:])
        print(f"=== {PASSED} passed, {FAILED} failed ===")
        return 1
    front = json.loads(corrida.stdout)
    check("arnés del frente sin errores de página", not front["errores_de_pagina"],
          front["errores_de_pagina"])

    for camino in ("vivo", "record"):
        d = front[camino]
        v1, v2, v3, v4 = d["v1_ok"], d["v2_fallo"], d["v3_nocorrio"], d["v4_held"]

        check(f"V1 [{camino}] tool ejecutada OK → ✓ verde, con lo que devolvió",
              "done" in v1["clases"] and v1["estado"].startswith("listo")
              and "3" in v1["estado"] and not v1["pregunta"], v1)

        check(f"V2 [{camino}] tool que CORRIÓ y falló → estado de error, JAMÁS ✓",
              "fail" in v2["clases"] and "done" not in v2["clases"], v2)
        # la causa legible sale del diccionario único (Sem.caraDeCausa), no de un string crudo
        check(f"V2b [{camino}] la causa se lee, y es la del vocabulario sellado",
              "El proveedor está caído" in v2["sub"] and "502" not in v2["estado"], v2["sub"])

        check(f"V3 [{camino}] tool que NO se ejecutó (executed:false) → estado propio",
              "nocorrio" in v3["clases"] and "fail" not in v3["clases"]
              and "done" not in v3["clases"], v3)
        check(f"V3b [{camino}] «no corrió» ≠ «no salió»: distinto copy y distinto color",
              v3["estado"] != v2["estado"] and v3["color"] != v2["color"], (v3, v2))

        check(f"V4 [{camino}] acción RETENIDA → identidad de PROTECCIÓN (ni verde ni rojo)",
              "held" in v4["clases"] and "fail" not in v4["clases"]
              and "done" not in v4["clases"] and v4["color"] == AMBAR_DEL_CUARTO, v4)
        check(f"V4b [{camino}] …y la pregunta explícita al usuario: seguir o no",
              bool(v4["pregunta"]) and "?" in v4["pregunta"], v4["pregunta"])

        # EL DISCRIMINANTE: cuatro estados ⇒ cuatro caras. Sin esto, cada caso puede pasar
        # y la pantalla seguir fundiendo dos cosas distintas en la misma pintura.
        colores = {v1["color"], v2["color"], v3["color"], v4["color"]}
        clases = {tuple(sorted(x["clases"])) for x in (v1, v2, v3, v4)}
        check(f"V5b [{camino}] los cuatro estados son CUATRO caras distintas",
              len(colores) == 4 and len(clases) == 4, {"colores": sorted(colores)})

    # V5 · la ruta de G-1 (stream cortado) mantiene los veredictos del camino vivo.
    check("V5 el STREAM CORTADO da los MISMOS veredictos que el camino vivo",
          all(front["record"][k]["clases"] == front["vivo"][k]["clases"]
              for k in ("v1_ok", "v2_fallo", "v3_nocorrio", "v4_held"))
          and front["record"]["entradas"] == 4,
          {k: front["record"][k]["clases"] for k in front["record"] if k != "entradas"})

    est = front["estados"]
    check("V5c un `status` desconocido, un evento nulo → NUNCA ✓",
          est["desconocido"] == "fail" and est["nulo"] == "fail", est)
    check("V5d una entrada sin señal de fallo sigue cerrando ✓ (cero ✗ inventados)",
          est["record_pelado"] == "done", est)

    # ══ V6 · EL MAPA DE RETRY CONTRA EL VOCABULARIO SELLADO ════════════════════════
    mapa = set(front["retry"]["mapa"])
    huerfanas = sorted(mapa - set(em.CAUSAS))
    check("V6 cada clave del mapa existe en el vocabulario sellado (cero huérfanas)",
          not huerfanas, huerfanas)
    check("V6b el mapa es el espejo EXACTO de errores_modelo._REINTENTABLES",
          mapa == set(em._REINTENTABLES),
          {"sobran": sorted(mapa - set(em._REINTENTABLES)),
           "faltan": sorted(set(em._REINTENTABLES) - mapa)})
    check("V6c las dos claves muertas ya no existen ni matchean",
          "servidor_caido" not in mapa and "stream_cortado" not in mapa
          and front["retry"]["muerta_vieja"] is False
          and front["retry"]["muerta_vieja2"] is False, sorted(mapa))
    check("V6d `proveedor_caido` (el nombre REAL) sí dispara el reintento",
          "proveedor_caido" in mapa and front["retry"]["espejo_si"] is True)
    # lo que prueba que decide el BOOLEANO y no el nombre: en `tipada_si` la causa del run
    # (`contexto_excedido`) NO está en el mapa y reintenta igual; en `tipada_no` la causa
    # (`timeout`) SÍ está en el mapa y no reintenta. El nombre pierde, el sello gana.
    check("V6e el retry lo decide `reintentable`, no la lista de nombres",
          front["retry"]["tipada_si"] is True and front["retry"]["tipada_no"] is False)
    check("V6f sin causa tipada, el espejo del sello decide (y no reintenta lo permanente)",
          front["retry"]["espejo_no"] is False)

    # ══ V7 · EL GATE EN LAS DOS TRAYECTORIAS ═══════════════════════════════════════
    eventos = [
        {"id": 1, "type": "turn_started", "payload": {"turn": 1}},
        {"id": 2, "type": "gate_waiting", "tool": "send_email", "gate_decision": "needs_ok",
         "gate_action": "needs_ok", "executed": False, "causa": "gate_bloqueado",
         "origen": "aleph", "reintentable": False},
        {"id": 3, "type": "tool_call_finished", "tool": "units_check", "wall_s": 0.2,
         "gate_decision": "execute", "result": "[tool error] DimensionalityError"},
        {"id": 4, "type": "tool_call_finished", "tool": "sumar", "wall_s": 0.1,
         "gate_decision": "blocked", "result": "[gate: acción BLOQUEADA]"},
    ]
    ev_traj = instr.build_trayectoria(eventos)
    gated = [s for s in ev_traj if s.get("retenida")]
    check("V7 gate_waiting AHORA es un paso de la trayectoria por eventos",
          any(s["name"] == "send_email" for s in ev_traj), [s.get("name") for s in ev_traj])
    check("V7b una acción retenida se registra como PROTECCIÓN, no como error",
          len(gated) == 2 and all(s["error"] is None for s in gated),
          [{k: s[k] for k in ("name", "error", "retenida")} for s in gated])
    check("V7c el vocabulario muerto («NO»/«denied»/«rejected») ya no decide nada",
          instr.GATE_RETIENE == frozenset({"needs_ok", "blocked"})
          and instr.build_trayectoria(
              [{"type": "tool_call_finished", "tool": "x", "gate_decision": "NO",
                "result": "ok"}])[0]["retenida"] is False, sorted(instr.GATE_RETIENE))
    check("V7d lo que SÍ falló sigue siendo error",
          next(s for s in ev_traj if s["name"] == "units_check")["error"] is not None)

    record = {"model_route": [{"model": "m", "ok": True, "tier": "primary"}], "tool_calls": [
        {"tool": "units_check", "gate_action": "execute", "wall_s": 0.2,
         "result": "[tool error] DimensionalityError"},
        {"tool": "create_workbook", "gate_action": "needs_ok", "result": "[gate: requiere tu OK]"},
        {"tool": "wire_money", "gate_decision": "blocked", "result": "[gate: BLOQUEADA]"},
    ]}
    rec_traj = executor.build_trajectory_from_record(record)
    ret_rec = [s for s in rec_traj if s.get("retenida")]
    check("V7e la trayectoria del MOAT usa el MISMO criterio (un solo criterio, G-7)",
          len(ret_rec) == 2 and all(s["error"] is None for s in ret_rec)
          and next(s for s in rec_traj if s["name"] == "units_check")["error"] is not None,
          [{k: s.get(k) for k in ("name", "error", "retenida")} for s in rec_traj])
    check("V7f ninguna de las dos trayectorias escribe ya `gate:` en `error`",
          not any(str(s.get("error") or "").startswith("gate:")
                  for s in list(ev_traj) + list(rec_traj)))

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


def _node() -> str:
    return "node"


if __name__ == "__main__":
    raise SystemExit(main())
