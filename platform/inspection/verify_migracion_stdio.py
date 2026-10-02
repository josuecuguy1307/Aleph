#!/usr/bin/env python3
"""verify_migracion_stdio.py — LA MIGRACIÓN STDIO, LADO A LADO (OBRA 3 · sesión 2).

No prueba el puente: prueba que **el veredicto no cambió**. Corre `verificar_uno` —la MISMA
función del producto, la que llena el registro— dos veces sobre cada entidad de la muestra,
una con `ALEPH_TRANSPORTE=viejo` y otra con `=sdk`, y compara lo que quedó en la fila.

    REGLA MADRE: el 89% no cambia de lógica, cambia de FUENTE. Si un veredicto cambia de
    valor para el mismo servidor, es un bug del recableo — no una mejora. Se reporta y se
    PARA, no se acepta.

DRY-RUN: nunca se pasa `--aplicar`, así que el registro no se toca. Lo único que se hace es
levantar los servidores de verdad, preguntarles, y apagarlos.

LA MUESTRA cubre los cinco estados que el registro produce, con las entidades reales que
los tienen hoy (42 conexiones · v5):

    viva + verde       zotero · context7 · exa · github   ← los 4 verdes de la vara
    viva + no_aplica   fetch · sqlite
    sin_sondear        pysandbox
    rota (arranque)    time (pin de uvx) · dicom (binario ausente)

Correr (con el venv del producto, que es el que tiene el pin):
    product/backend/.venv/bin/python platform/inspection/verify_migracion_stdio.py
    …  --rapido   saltea las entidades con credencial (doble spawn, las más lentas)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

#: entidad → qué estado viene a cubrir. El orden es el del reporte.
MUESTRA = [
    ("zotero", "viva + verde · con llave real"),
    ("context7", "viva + verde · con llave real"),
    ("exa", "viva + verde · con llave real"),
    ("github", "viva + verde · con llave real"),
    ("fetch", "viva + no_aplica · sonda declarada"),
    ("sqlite", "viva + no_aplica"),
    ("pysandbox", "sin_sondear · ninguna tool llamable a ciegas"),
    ("time", "rota · arranque (pin de uvx)"),
    ("dicom", "rota · arranque (binario ausente)"),
]
CON_LLAVE = {"zotero", "context7", "exa", "github"}

_fallos = 0
_divergencias: list = []


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"    ✓ {nombre}")
    else:
        _fallos += 1
        print(f"    ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def _limpiar_modulos():
    """El selector se resuelve al importar/llamar, y los módulos cachean la clase elegida.
    Entre las dos corridas hay que soltar TODO lo que la sostiene, o la segunda mediría con
    el transporte de la primera y este verificador daría verde por no medir nada."""
    for nombre in list(sys.modules):
        if nombre.split(".")[0] in {"transporte", "transporte_sdk", "byo_mcp",
                                    "traductor_errores"} or \
           nombre.startswith("app.phase1.conexiones_verificador") or \
           nombre.startswith("app.phase1.motor_verdad"):
            sys.modules.pop(nombre, None)


def _medir(entidad: str, belt: str, server: str, transporte: str, owner, get_conn) -> dict:
    os.environ["ALEPH_TRANSPORTE"] = transporte
    _limpiar_modulos()
    from app.phase1 import conexiones_verificador as V   # noqa: E402 — re-import a propósito
    import transporte as TP                              # noqa: E402
    elegido = TP.elegido()["transporte"]
    t0 = time.perf_counter()
    fila = V.verificar_uno(belt, server, owner=owner, get_conn=get_conn)
    fila["_ms"] = int((time.perf_counter() - t0) * 1000)
    fila["_transporte"] = elegido
    return fila


def _resumen(fila: dict) -> dict:
    """Lo que TIENE que coincidir. La evidencia (texto libre, timestamps, latencias) no
    entra: dos corridas contra un servidor real nunca dan el mismo byte, y exigirlo haría
    que este verificador fuera rojo siempre por el motivo equivocado."""
    cx = fila.get("conexion") or {}
    cr = fila.get("credencial") or {}
    return {
        "conexion": cx.get("estado"),
        "causa": cx.get("causa"),
        "credencial": cr.get("estado"),
        "arranca": bool(fila.get("arranca")),
        "tools_probadas": sorted(fila.get("tools_probadas") or []),
    }


def main() -> int:
    rapido = "--rapido" in sys.argv
    from app.phase1 import repo                            # noqa: E402
    conn = repo.get_conn()
    owner = None
    try:
        with conn.cursor() as cur:
            # EL DUEÑO DEL REGISTRO ES EL QUE TIENE CONEXIONES, no el que tiene una
            # llave cualquiera. `SELECT user_id FROM keys LIMIT 1` aguantó mientras hubo un
            # solo usuario; hoy las varas y la suite crean usuarios de PRUEBA con llave
            # propia (broker-test-a/b, zotero-inject-a, cowork-approve-test), así que un
            # `LIMIT 1` sin ORDER BY devuelve cualquiera — y con un usuario de prueba esto
            # mide el catálogo entero contra un registro VACÍO. Determinista y no vacío.
            cur.execute("SELECT user_id FROM conexiones GROUP BY user_id "
                        "ORDER BY COUNT(*) DESC, user_id LIMIT 1")
            r = cur.fetchone()
            if r is None:                      # sin conexiones no hay registro que mirar;
                cur.execute("SELECT user_id FROM keys LIMIT 1")   # una cuenta suelta sirve
                r = cur.fetchone()
            owner = r[0] if r else None
    finally:
        conn.close()
    if not owner:
        print("✗ no hay owner en `keys`: sin llavero, los verdes no se pueden medir.")
        return 1

    from app.phase1 import conexiones_verificador as V0    # noqa: E402
    entradas = {srv: belt for belt, srv in V0._entradas()}

    print(f"MIGRACIÓN STDIO · cliente viejo vs puente · owner={owner[:8]}…")
    print(f"transporte por default hoy: ALEPH_TRANSPORTE no seteado → auto\n")

    for entidad, cubre in MUESTRA:
        if rapido and entidad in CON_LLAVE:
            continue
        belt = entradas.get(entidad)
        print(f"── {entidad}  ({cubre})")
        if not belt:
            ok(False, "está en el catálogo", "no lo encontré en `_entradas()`")
            continue
        viejo = _medir(entidad, belt, entidad, "viejo", owner, repo.get_conn)
        nuevo = _medir(entidad, belt, entidad, "sdk", owner, repo.get_conn)
        rv, rn = _resumen(viejo), _resumen(nuevo)
        ok(viejo["_transporte"] == "legacy" and nuevo["_transporte"] == "sdk",
           "cada corrida usó el transporte que se le pidió",
           f"viejo={viejo['_transporte']} nuevo={nuevo['_transporte']}")
        print(f"      viejo  ({viejo['_ms']:>5} ms)  {json.dumps(rv, ensure_ascii=False)}")
        print(f"      puente ({nuevo['_ms']:>5} ms)  {json.dumps(rn, ensure_ascii=False)}")
        igual = rv == rn
        ok(igual, "MISMO veredicto, MISMAS tools, MISMA credencial")
        if not igual:
            _divergencias.append((entidad, rv, rn))

    # ── EL DUEÑO SOSTIENE (D2): lo que quedó vivo se cierra ACÁ ────────────────────
    # Con `ALEPH_DUENO=on` y la ociosidad en 600 s, las conexiones NO mueren al soltar el
    # préstamo — ése es todo el punto de D2. Una vara que las dejara colgadas reportaría
    # «cero huérfanos» mintiendo: no son huérfanos, son sostenidas, pero al terminar de
    # medir no las quiere nadie. Se apagan como lo hará el lifespan, y se cuenta.
    try:
        import transporte  # noqa: F401  (asegura sys.path de platform/inspection)
        import dueno as _DU
        if _DU.encendido():
            vivas = len(_DU.actual().estado()["vivas"])
            cerradas = _DU.actual().apagar_todo(motivo="fin de la vara")
            print(f"\n[dueño] sostenía {vivas} conexión(es) al terminar; "
                  f"apagadas {cerradas}.")
            ok(_DU.actual().estado()["vivas"] == [],
               "y el dueño no quedó sosteniendo nada")
    except Exception as e:                                 # noqa: BLE001
        print(f"\n[dueño] no se pudo cerrar al final: {type(e).__name__}: {e}")

    print()
    if _divergencias:
        print("═══ DIVERGENCIAS — SE PARA ═══")
        for entidad, rv, rn in _divergencias:
            print(f"  {entidad}")
            for k in sorted(set(rv) | set(rn)):
                if rv.get(k) != rn.get(k):
                    print(f"    {k}: viejo={rv.get(k)!r}  puente={rn.get(k)!r}")
    print(f"{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
    return 0 if _fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
