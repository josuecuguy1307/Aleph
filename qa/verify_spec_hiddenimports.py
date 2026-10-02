#!/usr/bin/env python3
"""verify_spec_hiddenimports.py — TODO `hiddenimport` DEL SPEC TIENE QUE RESOLVER.

[TANDA 2 · obra B]

EL BUG QUE LA PIDIÓ
-------------------
El build cantaba `ERROR: Hidden import 'connections' not found` desde `5761a165`, en cada
corrida, sin romper nada (exit 0). Eso es lo peor que le puede pasar a un warning: aparece
siempre y nunca importa, así que enseña a saltearlos. Es la misma regla que esta casa ya
selló para las varas — una roja permanente enseña a ignorar las rojas.

LA CAUSA, medida: `_TARGET_MODULES` declara `"connections"` porque `arranque.py:72` lo
carga por ruta desde `platform/connectors/smithery/connections.py`, pero `_PATHS` tenía
`platform/connectors` y **no** su subdirectorio. El nombre plano no resolvía.

QUÉ MIDE ESTA VARA
------------------
Reconstruye el `pathex` EXACTO del spec —mismo orden de inserción, que importa— y le pide
a `importlib` que resuelva cada nombre de `_TARGET_MODULES`. Es lo mismo que hace
`Analysis`, sin pagar un build de 25 minutos.

⚠️ LO QUE **NO** MIDE, y hay que decirlo: que el nombre resuelva **al archivo que
`arranque.py` declara**. Medido el 2026-08-22, `session` resuelve a
`platform/inspection/session/__init__.py` y no a `platform/assembler/session.py` — porque
`platform/inspection` se inserta último y queda primero. Hoy no rompe (el archivo viaja
igual como dato y quien lo carga lo hace por ruta), así que queda REPORTADO y no
convertido en rojo: un rojo que nadie pidió arreglar es la misma enfermedad que esta vara
viene a curar. Se imprime como aviso con su nombre.

CORRE: `python3 qa/verify_spec_hiddenimports.py`
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SPEC = RAIZ / "deploy" / "fase4" / "aleph_sidecar.spec"
ARRANQUE = RAIZ / "product" / "backend" / "app" / "phase1" / "arranque.py"

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


def _lista_literal(fuente: str, nombre: str) -> list[str]:
    """La lista tal como el spec la escribe. Se parsea el AST, no se importa el spec:
    importarlo ejecutaría PyInstaller entero."""
    arbol = ast.parse(fuente)
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and t.id == nombre:
                    return [e.value for e in nodo.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def main() -> int:
    fuente = SPEC.read_text(encoding="utf-8")
    paths = _lista_literal(fuente, "_PATHS")
    modulos = _lista_literal(fuente, "_TARGET_MODULES")
    ok(bool(paths), "`_PATHS` se pudo leer del spec", f"{len(paths)}")
    ok(bool(modulos), "`_TARGET_MODULES` se pudo leer del spec", f"{len(modulos)}")
    if not paths or not modulos:
        return 1

    # EL MISMO ORDEN QUE EL SPEC: `for _p in pathex: sys.path.insert(0, _p)`, o sea que el
    # ÚLTIMO de `_PATHS` termina PRIMERO en `sys.path`. Reproducirlo mal haría que la vara
    # resolviera módulos que el build no resuelve, o al revés.
    guardado = list(sys.path)
    try:
        for p in [str(RAIZ / x) for x in paths]:
            sys.path.insert(0, p)
        importlib.invalidate_caches()
        resueltos: dict[str, str] = {}
        no_resueltos: list[str] = []
        for m in modulos:
            try:
                spec = importlib.util.find_spec(m)
            except Exception:  # noqa: BLE001 — irresoluble también es no resuelto
                spec = None
            if spec is None:
                no_resueltos.append(m)
            else:
                resueltos[m] = str(spec.origin or "")
    finally:
        sys.path[:] = guardado
        importlib.invalidate_caches()

    ok(not no_resueltos,
       "todo nombre de `_TARGET_MODULES` resuelve contra el pathex del spec",
       "irresolubles: " + ", ".join(no_resueltos))

    # El caso índice, nombrado: que no vuelva por descuido.
    ok("connections" in resueltos,
       "`connections` resuelve (el warning permanente del build)",
       "sigue irresoluble")
    ok("platform/connectors/smithery" in paths,
       "`platform/connectors/smithery` está en `_PATHS`")

    # ── AVISO, NO ROJO: el nombre resuelve, pero ¿al archivo que `arranque.py` declara? ──
    declarado: dict[str, str] = {}
    for nodo in ast.walk(ast.parse(ARRANQUE.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Tuple) and len(nodo.elts) == 3:
            a, b = nodo.elts[0], nodo.elts[1]
            if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and isinstance(b, ast.Constant) and isinstance(b.value, str)
                    and b.value.endswith(".py")):
                declarado[a.value] = b.value
    discrepan = [
        (m, declarado[m], os.path.relpath(resueltos[m], RAIZ))
        for m in sorted(resueltos)
        if m in declarado and resueltos[m]
        and os.path.relpath(resueltos[m], RAIZ) != declarado[m]
    ]
    if discrepan:
        print("  · aviso — el nombre resuelve a OTRO archivo que el que `arranque.py` "
              "declara (no rompe hoy: se carga por ruta y el .py viaja como dato):")
        for m, decl, real in discrepan:
            print(f"      {m}: declara {decl} · resuelve {real}")

    print("\n✗ %d fallo(s)" % len(FALLOS) if FALLOS
          else "\n✓ hiddenimports del spec: todo verde")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
