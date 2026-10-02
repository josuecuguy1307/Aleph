#!/usr/bin/env python3
"""Vara única Gate 3 · Fase 3: EL ANTI-GRIFT LEE EL ESTADO HONESTO.

    product/backend/.venv/bin/python platform/assembler/verify_costura_antigrift.py

⚠️ **NO ANIDA VARAS**. Lo único que corre acá adentro es el ARNÉS del frente, que no es
una vara: mide y devuelve JSON.

── POR QUÉ SÓLO ESTE PEDAZO DE LA OBRA 7 ───────────────────────────────────────────
Gate 4 arranca con el contrato de artefactos y su certificación se apoya en el
anti-grift. Si el anti-grift no puede leer el estado REAL de una tool, está midiendo la
DECLARACIÓN y no el HECHO — y eso sí es del átomo que Gate 3 certifica. El resto de la
obra 7 queda al banco, declarado en el reporte.

── O1 · LO QUE SE MIDIÓ ANTES DE TOCAR NADA ────────────────────────────────────────
La auditoría 4 se hizo sobre main `c358c39`. Desde entonces mergearon las obras 5·A·B·C·D,
el cierre de §28, la Fase 1 (higiene) y la Fase 2 (obra 6). Estado real sobre `a60edcf`:

  G-1  el ✓ mentiroso del log          RESUELTO por la obra 5 (`sala.html:3860` lo declara)
  G-2  vocabulario de gate inexistente RESUELTO por la obra 5 (`instrumentation.py:51-61`)
  G-3  claves de auto-retry muertas    RESUELTO por la obra 5 (`sala.html:4932-4946`)
  G-4  `executed` sin consumidor       **VIVO donde importa** → lo cierra O2, acá
  G-5  `origen` invisible              VIVO · al banco (es superficie, no anti-grift)
  G-6  D9 muere en el primer consumidor RESUELTO por la obra 6 (fase 2 de este cierre)
  G-7  dos constructores de trayectoria RESUELTO por la obra 5 → **se MIDE acá** (V3)
  G-8  scrub retenido cuenta como grounding **VIVO** → lo cierra O3, acá
  G-9  `gate_decision` sin consumidores VIVO · SOLO DOCUMENTADO (EVENTS-SCHEMA.md)
  G-10 citas podridas                  (b) corregida acá (era el docstring que se tocaba);
                                       (a) y (c) al banco
  G-11 flywheel/logs sin consumo       VIVO · al banco
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for _p in (str(HERE), str(ROOT / "platform"), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_antigrift.mjs"
SALA = ROOT / "product" / "app" / "design" / "sala" / "sala.html"

# [Convergencia · superficie 7 · paso 6] LA SALA VIEJA SE BORRÓ.
# Esta vara medía, entre otras cosas, texto de `sala/sala.html`. Esa pantalla ya no existe:
# su trabajo se rescató en la v2 y el resto murió con ella. La mitad que medía la Sala se
# SALTEA diciéndolo —no se borra la vara, porque el RESTO de lo que mide sigue vivo— y no
# se finge verde: un checkeo sin objeto es un salteo, jamás un ✓.
SALA_VIVA = SALA.exists()

ESQUEMA = ROOT / "platform" / "flywheel" / "EVENTS-SCHEMA.md"

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


def seccion(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def main() -> int:
    print("=" * 80)
    print("VARA · FASE 3 · EL ANTI-GRIFT LEE EL ESTADO HONESTO")
    print("=" * 80)

    # ══ V3 · LOS DOS CONSTRUCTORES DE TRAYECTORIA (G-7) ══════════════════════════════
    # Va primero porque es puro backend y no necesita navegador.
    seccion("V3 · un mismo hecho → el MISMO veredicto por los dos constructores (G-7)")
    from app.phase1 import executor as EX                       # noqa: E402
    from app.phase1 import instrumentation as INSTR             # noqa: E402

    check("V3 los dos comparten LA MISMA constante `GATE_RETIENE` (el patrón de la obra 5)",
          EX.instr.GATE_RETIENE is INSTR.GATE_RETIENE,
          f"{sorted(INSTR.GATE_RETIENE)}")

    #: El MISMO hecho, en las dos formas en que llega: evento (stream) y record (terminal).
    _CASOS = [
        ("tool que corrió bien",
         {"tool": "buscar", "gate_decision": "execute", "gate_action": "execute",
          "result": "3 resultados", "executed": True},
         "execute", "3 resultados"),
        ("tool RETENIDA por el gate — protección, no fallo",
         {"tool": "pagar", "gate_decision": "needs_ok", "gate_action": "needs_ok",
          "result": "[gate:needs_ok]", "executed": False},
         "needs_ok", "[gate:needs_ok]"),
        ("tool BLOQUEADA por el gate",
         {"tool": "borrar", "gate_decision": "blocked", "gate_action": "blocked",
          "result": "[gate:blocked]", "executed": False},
         "blocked", "[gate:blocked]"),
        ("tool que FALLÓ de verdad",
         {"tool": "cobrar", "gate_decision": "execute", "gate_action": "execute",
          "result": "[error] upstream 502", "executed": True,
          "causa": "error_upstream", "origen": "conector", "reintentable": True},
         "execute", "[error] upstream 502"),
    ]
    for _nombre, _tc, _gd, _res in _CASOS:
        _por_record = EX.build_trajectory_from_record({"model_route": [], "tool_calls": [_tc]})
        _ev = dict(_tc)
        _ev.update({"type": "tool_call_finished"})
        _por_evento = INSTR.build_trayectoria([_ev])
        # se comparan los campos que deciden el veredicto del moat
        _claves = ("kind", "name", "error", "gate_decision", "retenida",
                   "causa", "origen", "reintentable")
        _a = {k: _por_record[0].get(k) for k in _claves}
        _b = {k: _por_evento[0].get(k) for k in _claves}
        check(f"V3 ★ «{_nombre}» → veredicto IDÉNTICO por los dos caminos",
              _a == _b, f"{_a} vs {_b}")

    check("V3 …y una retención NO se registra como error (la obra 5: el gate es protección)",
          all(EX.build_trajectory_from_record(
              {"model_route": [], "tool_calls": [_tc]})[0]["error"] is None
              for _n, _tc, _gd, _r in _CASOS if _tc["gate_decision"] in INSTR.GATE_RETIENE))

    # ══ V4 · model_final SIGUE SIENDO EL REAL ════════════════════════════════════════
    seccion("V4 · `model_final` sigue siendo el real (no se regresa lo del §28)")
    if not SALA_VIVA:
        print("  ~ SALTEADO: la Sala vieja se borró (paso 6) — esta mitad no tiene objeto")
        return
    _sala = SALA.read_text(encoding="utf-8")
    check("V4 el badge exige familia por DECLARACIÓN + coherencia, jamás igualdad literal",
          "FAMILY_RE.test(mf)" in _sala and "cliOk" in _sala)
    check("V4 ★ el eco del wrapper-id del CLI NO cuenta como modelo verificado",
          "CLI_WRAPPER_IDS" in _sala and "'claude-code-cli': 1" in _sala.replace('"', "'")
          or "CLI_WRAPPER_IDS={ 'claude-code-cli':1" in _sala)
    check("V4 …y un run degradado jamás da badge verde",
          "if(n.degraded) return { ok:false" in _sala)

    # ══ O5 · G-9 SOLO DOCUMENTADO ════════════════════════════════════════════════════
    seccion("O5 · G-9 — el plan de migración escrito, y CERO código")
    _esq = ESQUEMA.read_text(encoding="utf-8")
    check("O5 el plan de migración `gate_action` → `gate_decision` está en EVENTS-SCHEMA.md",
          "Migración `gate_action` → `gate_decision`" in _esq)
    check("O5 …y dice QUÉ SE ROMPE en cada paso, que es lo que lo hace un plan y no una lista",
          "qué se rompe si se saltea" in _esq)
    check("O5 ★ …y declara por qué NO se puede borrar hoy: el anti-grift lo usa de respaldo "
          "para los records ya persistidos",
          "el anti-grift deja de poder juzgar los records viejos" in _esq)
    check("O5 el respaldo sigue en el código (no se tocó una línea de la migración)",
          "c.executed===undefined && c.gate_action==='execute'" in _sala)

    # ══ EL FRENTE ════════════════════════════════════════════════════════════════════
    seccion("V1 · V2 — el anti-grift, por su función REAL en WebKit")
    corrida = subprocess.run(["node", str(ARNES)], cwd=ROOT, text=True, capture_output=True,
                             timeout=600, env=dict(os.environ))
    if corrida.returncode != 0:
        check("el arnés del frente corre", False, (corrida.stderr or "")[-400:])
        print(f"\n=== {PASSED} passed, {FAILED} failed ===")
        return 1
    try:
        A = json.loads(corrida.stdout)
    except json.JSONDecodeError:
        check("el arnés devuelve JSON", False, (corrida.stdout or "")[-300:])
        print(f"\n=== {PASSED} passed, {FAILED} failed ===")
        return 1

    check("el arnés no dejó errores de página", not A["errores_de_pagina"],
          str(A["errores_de_pagina"][:2]))
    G = A["grounding"]

    # V1 · O2 — el estado honesto
    check("V1 la tool que corrió bien SÍ cuenta como evidencia", G["ok"] is True)
    check("V1 ★ una tool que el gate DEJÓ correr y que FALLÓ (causa tipada) NO cuenta — "
          "antes `gate_action==='execute'` la daba por buena", G["fallo_con_causa"] is False)
    check("V1 ★ una tool que NUNCA CORRIÓ (`executed:false`) NO cuenta — es el G-4: "
          "`executed` pasa a tener consumidor justo donde cambia el veredicto",
          G["no_corrio"] is False)
    check("V1 una tool retenida por el gate NO cuenta (propuesta, nunca corrida)",
          G["gateada"] is False)
    check("V1 un `null` no cuenta", G["__nulo"] is False)

    # V2 · O3 · G-8 — el scrub
    check("V2 ★★ [G-8] un resultado RETENIDO POR EL SCRUB no cuenta como grounding — "
          "empieza con `[c`, el regex `[(error|gate)` no lo tocaba, y entraba como "
          "evidencia que NADIE PUDO LEER", G["scrub_retenido"] is False)

    # el respaldo para la historia ya persistida
    check("V1 ★ un registro VIEJO sin `executed` sigue juzgándose por `gate_action` — "
          "sin esto el anti-grift no podría juzgar nada de lo ya persistido",
          G["viejo_ok"] is True and G["viejo_gateada"] is False)

    # el badge entero
    B = A["grift"]
    check("V4 ★ con evidencia real el badge es verde", B["con_evidencia_real"]["ok"] is True)
    check("V4 sin evidencia → caveat honesto, no badge falso",
          B["sin_evidencia"]["ok"] is False and "herramientas" in B["sin_evidencia"]["reason"])
    check("V4 degradado → jamás verde", B["degradado"]["ok"] is False)
    check("V4 corrida fallida → jamás verde", B["fallida"]["ok"] is False)

    print("\n     [invocación única del chequeo completo]  "
          "product/backend/.venv/bin/python qa/correr_varas.py")
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
