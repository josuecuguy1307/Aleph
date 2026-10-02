"""arranque.py — LA SONDA DE ARRANQUE (FIX-P1B · §8). Silenciosa si está todo.

EL CASO ÍNDICE: `assembler.py` quedó FUERA del .app. Adentro, el código que lo carga por
ruta falló; el fallo subió por la cadena y salió en pantalla como **«Error del proveedor»**.
La persona leyó eso y fue a revisar su llave de Groq — que estaba perfecta. El defecto era
NUESTRO, del build, y la UI se lo cobró a un tercero.

Eso es lo que este módulo impide, con tres capas:

  1. ESTA SONDA (runtime) — al arrancar el sidecar mira si el bundle está completo: los
     directorios de datos que servimos, los módulos planos que cargamos por ruta, y los
     servers que decimos traer incluidos. Si está todo, NO DICE NADA (una sonda que grita
     cuando todo anda bien se vuelve ruido y se ignora). Si falta algo, deja el veredicto
     listo para que `/v1/motor/arranque` lo entregue.
  2. EL GATE DE BUILD (`qa/gate_bundle_aleph.py`) — corre la MISMA lista contra el .app
     recién construido. Ahí es donde se caza un `assembler.py` que no viajó, antes de que
     salga por la puerta.
  3. LA CAUSA `falla_de_aleph` (motor_verdad) — si igual se escapa una, el motor la nombra
     como lo que es. La 1ª línea dice «esto es un defecto nuestro» y el camino es
     [Copiar el reporte], no [Poner la llave].

REGLA: esta sonda mide, NO arregla y NO adivina. Un módulo que no importa se reporta con su
excepción textual — es lo que un humano necesita para pegarlo en un issue.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO / "platform"

#: Directorios de datos que el sidecar SIRVE. Espejo de `_DATA_DIRS` en aleph_sidecar.spec:
#: si acá y allá se desincronizan, el gate de build lo grita (comparten esta constante).
DATA_DIRS = ("catalog", "product/belts", "product/app/design", "docs/guia")

#: Módulos PLANOS que cargamos por RUTA (aleph_paths.load_module_by_path). Un `import`
#: normal no los cazaría, y por eso PyInstaller los pierde CALLADO: no hay ImportError en
#: el build, sólo un archivo que no viajó y un crash a las tres pantallas de distancia.
#:
#: Se verifican por RUTA, no por nombre importable, justamente porque así los carga el
#: producto: `load_module_by_path("puppet_assembler_base", _THIS_DIR/"assembler.py")`. Un
#: chequeo por `import` daría verde con el archivo ausente si el nombre existiera en otro
#: lado — que es exactamente la clase de falso verde que este trabajo persigue.
#:
#: `assembler.py` va primero: es EL que se escapó del .app y el motivo de este archivo.
#:
#: CADA ENTRADA DECLARA CÓMO SE CARGA, y ése es el chequeo que se le aplica. La distinción
#: no es burocracia — sin ella la sonda miente en los dos sentidos:
#:   · `ruta`  → el producto lo abre con `load_module_by_path`. SÓLO vale que el ARCHIVO
#:               esté. Un `import` del mismo nombre desde otro lado daría verde con el
#:               archivo ausente: el falso verde exacto que dejó pasar a `assembler.py`.
#:   · `import`→ viaja adentro del PYZ (hiddenimport). No hay archivo suelto que buscar;
#:               exigirlo sería un falso ROJO, que envenena el gate hasta que se lo ignora.
RUTA, IMPORT = "ruta", "import"
MODULOS_PLANOS = (
    ("assembler",           "platform/assembler/assembler.py",           RUTA),
    ("recipe_assembler",    "platform/assembler/recipe_assembler.py",    RUTA),
    # MULTIAGENTE F1 (docs/multiagente.md): el contrato CADENA. Va como RUTA porque el
    # ARCHIVO tiene que estar (viaja en `_TARGET_DIRS` del spec) — el router lo importa tras
    # meter ese dir en sys.path, así que un `import` que resolviera desde otro lado sería
    # justo el falso verde que esta sonda existe para no dar.
    ("multiagente",         "platform/assembler/multiagente.py",         RUTA),
    ("session",             "platform/assembler/session.py",             RUTA),
    ("connect_engine",      "platform/connectors/connect_engine.py",     RUTA),
    ("oauth_flow",          "platform/connectors/oauth_flow.py",         RUTA),
    ("connections",         "platform/connectors/smithery/connections.py", RUTA),
    ("approval_gate",       "platform/gates/approval_gate.py",           RUTA),
    ("recipe_enforcer",     "platform/gates/recipe_enforcer.py",         RUTA),
    ("vault",               "platform/gates/vault.py",                   RUTA),
    ("tier_gate",           "platform/gates/tier_gate.py",               RUTA),
    ("scrubber",            "platform/gates/scrubber.py",                RUTA),
    ("runtime_integration", "platform/gates/runtime_integration.py",     RUTA),
    ("db",                  "platform/db/db.py",                         RUTA),
    ("events_replay",       "platform/flywheel/events_replay.py",        RUTA),
    ("sanitizer",           "platform/sanitizer/runtime_overlay.py",     RUTA),
    ("build_id",            "platform/build_id.py",                      IMPORT),
    ("aleph_paths",         "platform/aleph_paths.py",                   IMPORT),
)

#: Lo que decimos traer INCLUIDO. Si no arranca, el producto miente en su propia vitrina.
#: Acá el IMPORT es la prueba: son paquetes reales y lo que importa no es dónde están sino
#: que el intérprete congelado pueda cargarlos.
SERVERS_INCLUIDOS = (
    ("cli_brain.detect",   "detección de tu Claude Code / Codex"),
    ("inspection.byo_mcp", "el probe que conecta con los servidores de las piezas"),
)

_VEREDICTO: Optional[dict] = None


def _resource_root() -> Path:
    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
        return _ap.resource_root().resolve()
    except Exception:
        return _REPO


def _build_horneado() -> str:
    """La identidad HORNEADA en el bundle gana sobre el entorno (mismo criterio que
    build_id.is_founder): un artefacto tiene que saber qué es sin depender de quién lo
    lanzó. Sin esto, todo reporte de un .app decía «dev» y el dato era inútil."""
    try:
        import aleph_build_id  # type: ignore
        return str(getattr(aleph_build_id, "ALEPH_BUILD", "") or "").strip() or "dev"
    except Exception:
        return (os.environ.get("ALEPH_BUILD") or "dev").strip()


def _falta_archivo(rel: str) -> Optional[str]:
    """None si el archivo viajó; si no, DÓNDE se lo buscó (lo que un dev necesita leer)."""
    root = _resource_root()
    if (root / rel).exists():
        return None
    # El onefile de PyInstaller también puede haberlo dejado suelto al lado del repo.
    if (_REPO / rel).exists():
        return None
    return f"no está en el bundle (busqué {root / rel})"


def _falta_import(nombre: str) -> Optional[str]:
    """None si el módulo importa DE VERDAD; si no, la primera línea de la excepción.
    Prepara el sys.path como lo hace el sidecar: si no, mediríamos nuestro PYTHONPATH en
    vez del bundle, que es el falso-negativo clásico de este tipo de sonda."""
    root = _resource_root()
    for d in ("platform", "platform/assembler", "platform/db", "platform/gates",
              "platform/connectors", "platform/flywheel", "platform/sanitizer"):
        p = str(root / d)
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        __import__(nombre)
        return None
    except Exception as e:  # noqa: BLE001
        return str(e).split("\n")[0][:200] or nombre


def medir(force: bool = False) -> dict:
    """Corre la sonda. → {ok, fallas:[{que, cual, detalle}], reporte, ts, entorno}

    `ok=True` ⇒ NADA que mostrar (la sonda es silenciosa por contrato)."""
    global _VEREDICTO
    if _VEREDICTO is not None and not force:
        return _VEREDICTO

    t0 = time.perf_counter()
    root = _resource_root()
    fallas: list[dict] = []

    for d in DATA_DIRS:
        p = root / d
        if not p.is_dir():
            fallas.append({"que": "datos", "cual": d,
                           "detalle": f"el bundle no trae {d}/ (busqué en {p})"})

    for nombre, rel, modo in MODULOS_PLANOS:
        por_que = _falta_archivo(rel) if modo == RUTA else _falta_import(nombre)
        if por_que:
            fallas.append({"que": "modulo", "cual": nombre, "ruta": rel, "modo": modo,
                           "detalle": por_que})

    for nombre, para_que in SERVERS_INCLUIDOS:
        por_que = _falta_import(nombre)
        if por_que:
            fallas.append({"que": "server_incluido", "cual": nombre,
                           "detalle": f"{para_que}: {por_que}"})

    entorno = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "resource_root": str(root),
        "python": sys.version.split()[0],
        "plataforma": f"{platform.system()} {platform.release()}",
        "aleph_build": _build_horneado(),
        "ms": int((time.perf_counter() - t0) * 1000),
    }
    _VEREDICTO = {"ok": not fallas, "fallas": fallas, "ts": time.time(), "entorno": entorno,
                  "reporte": _reporte(fallas, entorno) if fallas else ""}
    return _VEREDICTO


def _reporte(fallas: list[dict], entorno: dict) -> str:
    """EL TEXTO DE [Copiar el reporte]. Pensado para pegarse tal cual en un issue: qué falta,
    dónde se buscó, y en qué build pasó. Sin JSON crudo de la excepción como cuerpo."""
    L = ["Aleph — defecto de empaquetado (sonda de arranque)", ""]
    L.append(f"build     : {entorno.get('aleph_build')}"
             f"{' · frozen' if entorno.get('frozen') else ' · desde el repo'}")
    L.append(f"plataforma: {entorno.get('plataforma')} · Python {entorno.get('python')}")
    L.append(f"recursos  : {entorno.get('resource_root')}")
    L.append("")
    L.append(f"falta{'n' if len(fallas) != 1 else ''} {len(fallas)} pieza"
             f"{'s' if len(fallas) != 1 else ''} nuestra"
             f"{'s' if len(fallas) != 1 else ''}:")
    for f in fallas:
        L.append(f"  · [{f['que']}] {f['cual']} — {f['detalle']}")
    L.append("")
    L.append("Esto es un defecto de Aleph: no hay nada que configurar de tu lado.")
    return "\n".join(L)


def sonda_de_arranque() -> dict:
    """Se llama UNA vez al montar el router. Silenciosa si está todo; si falta algo, lo
    imprime en el log del sidecar (donde un dev lo ve) y lo deja para el endpoint."""
    v = medir()
    if not v["ok"]:
        try:
            print("\n" + v["reporte"] + "\n", file=sys.stderr, flush=True)
        except Exception:
            pass
    return v


def main(argv: Optional[list[str]] = None) -> int:
    """CLI del gate de build: `python -m app.phase1.arranque [--json]` → exit 1 si falta algo."""
    argv = list(sys.argv[1:] if argv is None else argv)
    v = medir(force=True)
    if "--json" in argv:
        print(json.dumps(v, indent=2, ensure_ascii=False))
    elif v["ok"]:
        print("sonda de arranque: OK — el bundle está completo "
              f"({len(MODULOS_PLANOS)} módulos · {len(DATA_DIRS)} dirs de datos · "
              f"{len(SERVERS_INCLUIDOS)} servers incluidos)")
    else:
        print(v["reporte"])
    return 0 if v["ok"] else 1


__all__ = ["medir", "sonda_de_arranque", "DATA_DIRS", "MODULOS_PLANOS", "SERVERS_INCLUIDOS", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
