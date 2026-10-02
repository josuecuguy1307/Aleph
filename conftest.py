"""conftest.py — LA COLECCIÓN DE PYTEST NO SE MUERE POR UN SCRIPT STANDALONE.

══ [H8 · 2026-08-08] EL AGUJERO, MEDIDO ══════════════════════════════════════════════
`.venv/bin/python -m pytest --collect-only -q` desde la raíz terminaba así:

    INTERNALERROR> File "platform/assembler/test_anti_exfil_in_path.py", line 129
    INTERNALERROR>   sys.exit(0 if _f == 0 else 1)
    INTERNALERROR> SystemExit: 0
    15 tests collected

**15 tests colectados y la sesión muerta.** Deuda de jun/jul: hay scripts que se llaman
`test_*.py` pero NO son tests de pytest — son varas standalone que corren sus checks al
importarse y cierran con `sys.exit()`. pytest los importa para colectarlos, el `sys.exit`
se ejecuta durante el import y **mata la corrida entera**: los tests de verdad, los que sí
están escritos para pytest, nunca llegan a correr.

No es uno: el barrido encontró **DIEZ** con el mismo patrón. Y uno más,
`test_method_brain.py`, que no muere pero pide un fixture `monkey` que no existe — su
`monkey` es una función local dentro de su propio `main()`, no un fixture.

  ══ POR QUÉ UNA LISTA A MANO Y NO UNA HEURÍSTICA ═══════════════════════════════════
  Se podría detectar «tiene sys.exit a nivel de módulo» y excluirlos solos. No se hace:
  una heurística que decide sola qué NO se corre es exactamente la forma de que un test
  real desaparezca de la suite sin que nadie se entere. La lista es explícita, cada
  entrada dice por qué, y `qa/verify_higiene.py` se pone ROJA si aparece un standalone
  nuevo que no esté acá. El costo de agregar una línea es el punto.

  Cada uno de estos SIGUE siendo ejecutable a mano — es su forma de uso real:
      product/backend/.venv/bin/python platform/assembler/test_anti_exfil_in_path.py
"""
from pathlib import Path

_AQUI = Path(__file__).resolve().parent

#: Scripts standalone bajo nombre `test_*.py`. NO son tests de pytest. Motivo por línea.
STANDALONE = {
    # `sys.exit()` a nivel de módulo: matan la colección entera si pytest los importa.
    "platform/gates/test_exfil_guard.py": "vara del guard de exfiltración",
    "platform/assembler/test_brain_shim.py": "vara del shim del cerebro",
    "platform/assembler/test_degraded_fallback.py": "vara del fallback degradado",
    "platform/assembler/test_anti_exfil_in_path.py": "vara anti-exfil in-path (el caso índice)",
    "platform/assembler/test_distill_tagging.py": "vara del tagging de destilación",
    "platform/assembler/test_models.py": "vara del catálogo de modelos",
    "platform/inspection/loop/test_armed_executor.py": "vara del ejecutor armado",
    "product/backend/app/phase1/test_account_proposal.py": "vara de la propuesta de cuenta",
    "product/backend/app/phase1/test_memory_inheritance.py": "vara de la herencia de memoria",
    "product/backend/app/phase1/test_memory_recall.py": "vara del recall de memoria",
    # No muere, pero sus `test_*(monkey)` piden un fixture que no existe: `monkey` es una
    # función local de su propio `main()`. Colectarlo da errores que no son bugs.
    "product/backend/app/phase1/test_method_brain.py": "vara del cerebro de Método",
    # ══ [Gate 3 · obra 6] LOS TRES QUE EL PRIMER DETECTOR NO VIO ═══════════════════
    # Su `raise SystemExit(1)` está **dentro de un `if`** a nivel de módulo, no suelto, y
    # el detector de la Fase 1 sólo miraba `ast.parse(...).body` directo. Peor: la rama
    # sólo se toma **cuando el test falla**, así que matan la colección de forma NO
    # DETERMINISTA. Medido el 2026-08-08: main colectaba 1252 tests por la mañana y
    # 116 + INTERNALERROR por la tarde, sin que nadie tocara nada — el E2E de visión
    # empezó a fallar y se llevó puesta la suite entera.
    "platform/assembler/test_vision_route_e2e.py": "E2E de visión con modelo real (red)",
    "qa/pulso_tablero/test_metric_integration.py": "integración del pulso del tablero",
    "qa/pulso_tablero/test_metric_event.py": "evento de métrica del pulso",
}

collect_ignore = [str(_AQUI / rel) for rel in STANDALONE]

# ══ [Gate 4 · Fase 6] LOS RUNTIMES PRODUCIDOS DE LA SALA ═══════════════════════════════
#
# Los dos modos de la Sala cuelgan sus dependencias de un directorio al lado del launcher,
# porque su launcher se las pasa por `PYTHONPATH` (`platform/sala/*/arranque.sh`). No son
# código de la casa: son wheels de terceros, gitignoreados, producidos por `deploy/fase6/`.
#
# ⚠️ **Y TRAEN SUS PROPIAS SUITES.** Medido sobre `platform/sala/research/lib`: **3.963
# `test_*.py` y 42 `conftest.py`** —de spacy, torch, transformers y compañía—. Sin esta
# línea, `pytest --collect-only` desde la raíz baja a los 1,9 GiB e intenta colectarlos
# todos: `qa/verify_higiene.py` pasó de 114 s a **colgarse pasados los 300 s**, y con ella
# cualquier corrida de la regresión. No es un test lento: es la suite de otro proyecto
# metiéndose en la nuestra.
#
# Se declaran los DOS aunque hoy sólo uno esté producido en este árbol: el de búsqueda
# aparece en cuanto alguien corra `producir_busqueda.sh`, y descubrirlo entonces —con la
# regresión colgada y sin saber por qué— costaría exactamente lo que costó éste.
_RUNTIMES_PRODUCIDOS = (
    "platform/sala/research/lib",        # 279 wheels del motor de Deep Research (§6.f)
    "platform/sala/research/runtime",    # el intérprete relocatable, compartido
    "platform/sala/busqueda/searxng",    # el venv de SearXNG, proceso vecino (§6.a.bis)
)
collect_ignore += [str(_AQUI / rel) for rel in _RUNTIMES_PRODUCIDOS]
