#!/usr/bin/env python3
"""Vara única Gate 3 · Obra A: REPAIR CUBRE LAS DOS CAUSAS SELLADAS.

    python3 platform/assembler/verify_costura_obraA.py

El rojo que cierra: `motor_verdad.CAUSAS` había crecido con las dos causas de la costura de
tools (`argumentos_invalidos`, `gate_bloqueado`, gate3 · D7) y `repair_clasificar` no las
cubría, así que `test_repair_clasificar` estaba ROJO EN MAIN. Repair las habría mandado a la
escalada sin haberlas pensado — un fallo silencioso disfrazado de comportamiento razonable.

── LO QUE ESTA OBRA DECIDIÓ, Y CON QUÉ EVIDENCIA ───────────────────────────────────
Ninguna de las dos se clasificó por parecido con un fallo de conector. Cada una sale de lo
que su PROPIA vara ya dejó sellado (`verify_costura_obra2.py:202-208`), que es la única
fuente con autor sobre estas dos:

  argumentos_invalidos   origen=modelo · reintentable=TRUE   → TEMPORAL · UNA_VUELTA
  gate_bloqueado         origen=aleph  · reintentable=FALSE  → PERMANENTE · SIN_ALARMA

`gate_bloqueado` NO ES UN FALLO — acta de persona usuaria (2026-08-06), la misma que ordena la obra 5:
*el gate es PROTECCIÓN, no fallo.* Es la SEGUNDA causa que usa `SIN_ALARMA`, y ensanchar esa
lista blanca es la decisión que el propio diccionario pedía que fuera explícita.

── DE DÓNDE SALE CADA MEDICIÓN ─────────────────────────────────────────────────────
VA1 y las dos primeras mitades de VA2 se afirman contra los módulos REALES, importados.
VA2 (la mitad de la cara) y VA3 los mide `arnes_costura_obraA.mjs` en WebKit REAL contra LA
SALA DE ESTE ÁRBOL: el copy se pide RESUELTO a `caraDeCausa` (no leído del literal, porque
una entrada puede existir y salir muda igual) y el color se lee COMPUTADO del DOM, que es la
única forma de probar «ni el verde del éxito ni el rojo del error».

VA4 es la regresión. **`verify_costura_obra4` NO entra, y es una regla nueva declarada:**
tarda ~9 min —vive por encima del tope de 120 s de la suite— y esta obra no toca nada de su
territorio (`cli_brain`, sesiones, slots). Tenerla en el camino crítico del merge fue lo que
abrió dos ventanas de carrera en el cierre de la obra 5, con main moviéndose cinco veces.
Sigue corriendo en la saneada, que es su lugar.

CERO RED, cero backend, cero puertos fijos. NO SPAWNEA OTRAS VARAS (regla sellada).
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
INSPECTION = ROOT / "platform" / "inspection"
for path in (HERE, ROOT / "platform", INSPECTION, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import repair_clasificar as RC  # noqa: E402
from app.phase1 import motor_verdad as MV  # noqa: E402

ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_obraA.mjs"

#: Los colores COMPUTADOS que la obra 5 ya midió y selló en su vara (`verify_costura_obra5`).
#: Se repiten acá como VALOR, no se importan: si la obra 5 los mueve, esta vara se entera.
AMBAR_DEL_CUARTO = "rgb(255, 180, 84)"   # 0xffb454 · el aura `held` del Cuarto
GRIS_DEL_NOCORRIO = "rgb(160, 160, 166)"
ROJO_DEL_FALLO = "rgb(229, 138, 138)"

#: EL COPY SELLADO POR PERSONA USUARIA (2026-08-07). Literal, para que un cambio de copy tenga que
#: pasar por acá: «ninguna causa llega a una superficie sin copy, jamás muda» — y ninguna se
#: queda con el provisional cuando el definitivo existe.
COPY_SELLADO = {
    "gate_bloqueado": "Esperando tu OK — ¿La hago, o la dejo?",
    "argumentos_invalidos": "La herramienta no corrió: el pedido llegó mal armado",
}

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


def _pytest(objetivo: str) -> tuple[bool, str]:
    """Corre UN archivo de test y devuelve (verde, última línea). Es regresión, no anidar
    varas: `qa/correr_varas.py` no se toca desde acá."""
    r = subprocess.run([sys.executable, "-m", "pytest", objetivo, "-q"],
                       cwd=ROOT, text=True, capture_output=True)
    ultima = [l for l in (r.stdout or "").strip().splitlines() if l.strip()]
    return r.returncode == 0, (ultima[-1] if ultima else (r.stderr or "")[-200:])


def main() -> int:
    # ══ VA1 · EL ROJO CERRADO ══════════════════════════════════════════════════════
    verde, resumen = _pytest("platform/inspection/test_repair_clasificar.py")
    check("VA1 test_repair_clasificar VERDE", verde, resumen)

    faltan = sorted(set(MV.CAUSAS) - RC.CAUSAS_CUBIERTAS)
    check("VA1b cero causas del motor sin clasificar en repair", not faltan, faltan)

    # Y que estén cubiertas COMO SE DECIDIÓ, no de cualquier forma: una entrada que las
    # mandara a la escalada también cerraría el rojo, y sería el fallo silencioso de vuelta.
    v_arg = RC.clasificar("argumentos_invalidos")
    check("VA1c argumentos_invalidos → TEMPORAL/UNA_VUELTA, sin botón (origen=modelo, "
          "reintentable=True)",
          v_arg.clase == RC.TEMPORAL and v_arg.accion == RC.UNA_VUELTA
          and v_arg.boton is None and bool(v_arg.razon), v_arg.como_dict())
    v_gate = RC.clasificar("gate_bloqueado")
    check("VA1d gate_bloqueado → PERMANENTE/SIN_ALARMA, sin botón (el gate es PROTECCIÓN)",
          v_gate.clase == RC.PERMANENTE and v_gate.accion == RC.SIN_ALARMA
          and v_gate.boton is None and bool(v_gate.razon), v_gate.como_dict())
    # El contrapositivo de VA1d: NINGUNA de las acciones que reintentan puede tocar el gate.
    # Reintentar una acción que el usuario todavía no autorizó no es gastar: es EJECUTAR lo
    # que el gate frenó.
    check("VA1e el gate JAMÁS cae en una acción que reintente",
          v_gate.accion not in (RC.BACKOFF, RC.UNA_VUELTA), v_gate.accion)

    # ══ EL FRENTE (VA2 · VA3) ══════════════════════════════════════════════════════
    corrida = subprocess.run(["node", str(ARNES)], cwd=ROOT, text=True, capture_output=True)
    if corrida.returncode != 0:
        check("arnés del frente corre", False, (corrida.stderr or corrida.stdout)[-400:])
        print(f"=== {PASSED} passed, {FAILED} failed ===")
        return 1
    front = json.loads(corrida.stdout)
    check("arnés del frente sin errores de página", not front["errores_de_pagina"],
          front["errores_de_pagina"])

    dic = front["diccionario"]
    for causa, esperado in COPY_SELLADO.items():
        d = dic["causas"][causa]
        # VA2 · RESOLUBLE, no sólo presente. `caraDeCausa` es la función real de las tres
        # superficies; si no la alcanza, sale `desconocida` y el copy queda mudo.
        check(f"VA2 [{causa}] el copy sale RESUELTO del diccionario único, no mudo",
              bool(d["titulo"]) and not d["desconocida"], d)
        check(f"VA2b [{causa}] y es EL COPY SELLADO por persona usuaria, no el provisional",
              d["titulo"] == esperado and d["entrada_es"] == esperado,
              {"salió": d["titulo"], "sellado": esperado})
        check(f"VA2c [{causa}] tiene copy en inglés (el diccionario es bilingüe)",
              bool(d["entrada_en"]), d["entrada_en"])

    # VA3 · LA PINTURA. El acta pide identidad propia para la protección: ni verde ni rojo.
    p_gate = front["pintura"]["gate_bloqueado"]
    p_arg = front["pintura"]["argumentos_invalidos"]

    check("VA3 gate_bloqueado se pinta ÁMBAR (held), el mismo del Cuarto — ni verde ni rojo",
          "held" in p_gate["clases"] and p_gate["color"] == AMBAR_DEL_CUARTO
          and "fail" not in p_gate["clases"] and "done" not in p_gate["clases"], p_gate)
    check("VA3b …y con la pregunta explícita: seguir o no",
          bool(p_gate["pregunta"]) and "?" in p_gate["pregunta"], p_gate["pregunta"])
    check("VA3c argumentos_invalidos se pinta GRIS (no corrió) — no es un fallo de la tool",
          "nocorrio" in p_arg["clases"] and p_arg["color"] == GRIS_DEL_NOCORRIO
          and "fail" not in p_arg["clases"] and "done" not in p_arg["clases"], p_arg)
    check("VA3d NINGUNA de las dos cae en el rojo del fallo",
          p_gate["color"] != ROJO_DEL_FALLO and p_arg["color"] != ROJO_DEL_FALLO,
          {"gate": p_gate["color"], "args": p_arg["color"]})
    # EL DISCRIMINANTE de esta obra: las dos son «no salió bien», y si se pintaran igual la
    # persona no podría distinguir «el sistema te está preguntando» de «el modelo se
    # equivocó». Que cada una pase por separado no alcanza (la lección de F4d).
    check("VA3e las dos son DOS caras distintas, no dos grados del mismo rojo",
          p_gate["color"] != p_arg["color"]
          and sorted(p_gate["clases"]) != sorted(p_arg["clases"]),
          {"gate": p_gate["color"], "args": p_arg["color"]})

    # LAS DOS MITADES DE LA MISMA VERDAD. La Sala deriva del EVENTO (`estadoDeCostura`) y las
    # otras superficies derivan de la CAUSA (`SIN_ALARMA`). Si sólo se arreglara una, el gate
    # seguiría siendo un fallo para la mitad del producto — que es el bug que había.
    check("VA3f el gate entró a SIN_ALARMA del diccionario (la otra mitad de la verdad)",
          "gate_bloqueado" in dic["sin_alarma"]
          and dic["causas"]["gate_bloqueado"]["es_alarma"] is False, dic["sin_alarma"])
    check("VA3g y `turno_detenido` sigue ahí: la lista creció, no se reemplazó",
          "turno_detenido" in dic["sin_alarma"], dic["sin_alarma"])
    check("VA3h argumentos_invalidos SÍ es alarma: no corrió, pero algo salió mal",
          dic["causas"]["argumentos_invalidos"]["es_alarma"] is True, dic["causas"])

    # ══ VA4 · LA REGRESIÓN — NO VA ACÁ, Y ES A PROPÓSITO ═══════════════════════════
    # ⚠️ ESTA VARA NO SPAWNEA OTRAS VARAS. Es la regla sellada («prohibido anidar varas:
    # durante la obra sólo la propia, antes del merge una corrida de `qa/correr_varas.py`») y
    # es la misma decisión que tomó `verify_costura_obra5.py`. Meter obras 1·2·3·5 acá adentro
    # convertiría una vara hermética de 3 s en una que levanta cuatro intérpretes, toca los
    # recursos de los otros carriles y puede dar un rojo que no es de nadie.
    #
    # VA4 se corre APARTE y se reporta aparte (ver el reporte de la obra): obras 1·2·3·5,
    # `verify_f4a` con el venv, `test_executor` y `test_instrumentation`. Queda afuera
    # `verify_costura_obra4` (~9 min, territorio `cli_brain` que esta obra no toca) — regla
    # nueva, declarada: tenerla en el camino crítico del merge fue lo que abrió dos ventanas
    # de carrera en el cierre de la obra 5. Sigue corriendo en la saneada, que es su lugar.

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
