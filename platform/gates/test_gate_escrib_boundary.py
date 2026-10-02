#!/usr/bin/env python3
"""
test_gate_escrib_boundary.py — REGRESIÓN del falso positivo `describe_table`
(hallazgo FIX-P4 §8.1, cerrado en la integración de la tanda P).

Bug: la raíz castellana de escritura `"escrib"` vivía como SUBSTRING PELADO en las
tres listas de nombres del gate. Y `escrib` ∈ `d-escrib-e`: `sqlite.describe_table`
—una LECTURA— caía a `write-world` por el PISO 3 de `classify_action` y pedía permiso
en cada uso. El daño era doble: un candado fantasma sobre una lectura (ruido que
entrena a la persona a aprobar sin leer) y una capacidad del kit base que había que
dejar fuera del subset para esquivarlo.

Cura: `"escrib"` sale de las tuplas de substring y entra por `_ESCRIB_RE`
(`(?<!d)escrib`) — la raíz NO precedida de 'd'. La única familia que produce la
colisión es `describ-` (describe / describir / redescribir), toda ella de lectura;
`escribir`, `sobrescribir` y `reescribir` siguen cayendo del lado de la escritura.

Este test corre contra el factory de PROD (`build_enforced_gate`) — el mismo path que
usa el assembler — y no sólo contra el clasificador puro: un piso que se arregla en la
función y no en el gate no arregla nada.

Run: python3 test_gate_escrib_boundary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
# `build_enforced_gate` importa `aleph_paths`, que vive un nivel arriba. Sin esto la
# vara muere con ModuleNotFoundError sin medir nada — el mismo modo de fallo mudo que
# tienen hoy sus hermanas cuando se las corre sueltas desde este directorio.
sys.path.insert(0, str(_THIS.parent))

import approval_gate as ag  # noqa: E402
import recipe_enforcer as enf  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _recipe():
    """Peor caso: la receta intenta apagar los gates. Los pisos igual mandan."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Escrib Boundary", "nicho": "datos"},
        "model": {"primary": "x", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 64, "max_turns": 2},
        "belt": {"belt_ref": "x", "tool_filters": {}},
        "framing": {"inline": "t"}, "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "off", "send": "off"},
    }


# ⚠ `build_enforced_gate` NO usa el módulo `approval_gate` que importa este archivo:
# carga el MISMO ARCHIVO bajo el nombre `puppet_approval_gate`. Misma fuente, otro
# objeto de módulo. Medir/parchear el import de arriba mide un gate que no es el de
# producción — lo cazó la calibración del bloque 5 al no ponerse roja.
def _gate_prod():
    return enf.build_enforced_gate(_recipe())


def _ns_prod(gate=None):
    """El NAMESPACE del módulo que realmente construyó el gate. `puppet_approval_gate`
    se carga por spec y NO queda registrado en sys.modules, así que se llega a él por
    los globals de un método de la clase — que ES el dict del módulo."""
    return type(gate or _gate_prod()).classify_action.__globals__


# ── 1 · LA LECTURA NO GATEA ─────────────────────────────────────────────────────
# El caso exacto del hallazgo, más su familia inglesa. Todos son lecturas: el gate
# tiene que dejarlos auto-ejecutar bajo la perilla DEFAULT ('balanceado').
def test_describe_no_gatea():
    gate = _gate_prod()
    lecturas = ["describe_table", "describe", "describeTable", "sqlite_describe",
                "db.describe_schema"]
    for tool in lecturas:
        cls = gate.classify_action("sqlite", tool, {})
        check(f"1.x '{tool}' clasifica READ (no write-world)",
              cls == "read", f"{tool} → {cls}")
        d = gate.evaluate("sqlite", tool, {})
        check(f"1.x '{tool}' auto-ejecuta (cero candado fantasma)",
              d.action == "execute", f"{tool} → {d.action}/{d.level}")


# ── 2 · LA ESCRITURA SÍ GATEA ───────────────────────────────────────────────────
# Contra-prueba obligatoria: si el fix hubiera aflojado la raíz, este bloque queda
# verde por error. Las variantes con prefijo (sobre-/re-) son las que un `\b` ingenuo
# habría perdido — por eso están acá y no en el comentario.
def test_escritura_si_gatea():
    gate = _gate_prod()
    escrituras = ["escribir_archivo", "escribe_fila", "db_escribir",
                  "sobrescribir_tabla", "reescribir_config", "escribirRegistro"]
    for tool in escrituras:
        cls = gate.classify_action("sqlite", tool, {})
        check(f"2.x '{tool}' clasifica WRITE-WORLD (piso 3)",
              cls == "write-world", f"{tool} → {cls}")
        d = gate.evaluate("sqlite", tool, {})
        check(f"2.x '{tool}' RETENIDA bajo balanceado",
              d.action == "needs_ok", f"{tool} → {d.action}")


# ── 3 · EL RESTO DEL SUBSET DEL KIT NO SE MOVIÓ ─────────────────────────────────
# El fix es quirúrgico: sólo la raíz castellana. Los verbos ingleses del kit base
# tienen que seguir exactamente donde estaban (FIX-P4 §5).
def test_kit_sqlite_sin_cambios():
    gate = _gate_prod()
    for tool in ["read_query", "list_tables"]:
        check(f"3.x '{tool}' sigue READ", gate.classify_action("sqlite", tool, {}) == "read")
    for tool in ["write_query", "create_table"]:
        check(f"3.x '{tool}' sigue WRITE-WORLD",
              gate.classify_action("sqlite", tool, {}) == "write-world")


# ── 3.bis · EL RESIDUO, MEDIDO Y DECLARADO ──────────────────────────────────────
# `describir_tabla` / `redescribir_vista` siguen RETENIDAS — pero YA NO por el hint
# `escrib` (bloque 4 lo prueba: la raíz no matchea). Caen por el FAIL-CLOSED del paso
# 6: `describir` no es token de `_READ_ONLY_HINTS` (que tiene el inglés `describe` y
# los castellanos leer/buscar/consultar/ver/mostrar/listar/obtener, pero no éste).
# Cerrarlo es AGRANDAR el allowlist de lectura — otro cambio, otro review, y no es lo
# que pidió esta integración. Se mide acá para que el residuo no sea invisible: si
# alguien agrega `describir` a los read-hints, esta aserción se pone roja y avisa.
def test_residuo_describir_castellano():
    gate = _gate_prod()
    for tool in ["describir_tabla", "redescribir_vista"]:
        cls = gate.classify_action("sqlite", tool, {})
        check(f"3bis '{tool}' sigue write-world POR FAIL-CLOSED (no por 'escrib')",
              cls == "write-world", f"{tool} → {cls}")
    check("3bis y la razón es el allowlist de lectura, no la raíz de escritura",
          "describir" not in ag._READ_ONLY_HINTS and not ag._suggests_escritura("describir_tabla"))


# ── 4 · LOS DOS ESPEJOS COINCIDEN ───────────────────────────────────────────────
# approval_gate y recipe_enforcer duplican las listas a propósito (defensa en
# profundidad). Duplicado que se desincroniza es peor que no duplicar: si uno de los
# dos se arregla y el otro no, la receta emite una regla 'auto-ejecuta' engañosa
# sobre algo que el gate va a retener.
def test_espejos_en_sync():
    casos = {
        "describe_table": False, "describir_tabla": False, "sqlite_describe": False,
        "redescribir_vista": False,
        "escribir_archivo": True, "sobrescribir_tabla": True, "reescribir_config": True,
        "db_escribir": True,
    }
    for tool, esperado in casos.items():
        a = _ns_prod()['_suggests_escritura'](tool)
        b = enf.ESCRIB_RE.search(tool.lower()) is not None
        check(f"4.x espejo coincide en '{tool}' (esperado {esperado})",
              a == b == esperado, f"gate={a} enforcer={b}")
    # y el enforcer completo, que es lo que decide si emite la regla
    check("4.y suggests_external_write('describe_table') == False",
          not enf.suggests_external_write("describe_table"))
    check("4.z suggests_external_write('escribir_archivo') == True",
          enf.suggests_external_write("escribir_archivo"))


# ── 5 · CALIBRACIÓN EN ROJO ─────────────────────────────────────────────────────
# Una vara que no se puede poner roja no prueba nada. Se restaura el bug a propósito
# (la raíz vuelve a ser substring pelado) y se exige que el bloque 1 CAIGA.
def test_calibracion_en_rojo():
    import re
    g = _gate_prod()
    ns = _ns_prod(g)
    original = ns["_ESCRIB_RE"]
    try:
        ns["_ESCRIB_RE"] = re.compile(r"escrib")       # ← el bug, restaurado
        cls = g.classify_action("sqlite", "describe_table", {})
        check("5.1 CALIBRACIÓN: con el bug restaurado, describe_table SÍ gatea",
              cls == "write-world", f"describe_table → {cls} (si dice 'read', la vara es ciega)")
        d = g.evaluate("sqlite", "describe_table", {})
        check("5.2 CALIBRACIÓN: y con el bug pedía permiso en cada uso",
              d.action == "needs_ok", f"describe_table → {d.action}")
    finally:
        ns["_ESCRIB_RE"] = original
    check("5.3 restaurado el fix, describe_table vuelve a READ",
          _gate_prod().classify_action("sqlite", "describe_table", {}) == "read")


def main():
    print("=== regresión: 'escrib' ∈ 'd-escrib-e' — describe_table NO gatea, write sí ===\n")
    test_describe_no_gatea()
    test_escritura_si_gatea()
    test_kit_sqlite_sin_cambios()
    test_residuo_describir_castellano()
    test_espejos_en_sync()
    test_calibracion_en_rojo()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
