"""
mudanza_datos.py — trae al dir del usuario lo que quedó escrito en el árbol/bundle.

Los índices RAG y los event-logs de espacios se escribían con rutas derivadas de
`parents[N]`, que bajo PyInstaller caen dentro de `_MEIPASS` — el temp del bundle, que se
borra al cerrar. Eso ya está arreglado en origen (`aleph_paths.rag_dir()` /
`espacios_dir()`); esto es la cortesía: lo que un usuario alcanzó a escribir en el lugar
viejo se trae al nuevo en el próximo arranque.

⚠️ NUNCA SE BORRA NADA DEL USUARIO. RAG se MUEVE archivo por archivo y ante colisión
GANA EL DESTINO —lo que ya estaba en el dir del usuario es más nuevo por construcción—;
el de origen se deja donde está. Los eventos se FUSIONAN por timestamp sin duplicar.
Si algo sale mal, el original sigue ahí y el arranque no se cae: una mudanza no puede
costarte los datos que vino a rescatar.

Es idempotente: al terminar deja una marca en el destino y no vuelve a mirar.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

#: Marca de mudanza hecha. Se escribe en el DESTINO: si el usuario borra su dir de datos,
#: la mudanza vuelve a correr, que es lo correcto — el origen puede seguir teniendo algo.
_MARCA = ".mudado-desde-el-arbol"


def _ya_mudado(destino: Path) -> bool:
    return (destino / _MARCA).exists()


def _marcar(destino: Path) -> None:
    try:
        destino.mkdir(parents=True, exist_ok=True)
        (destino / _MARCA).write_text("", encoding="utf-8")
    except OSError:
        pass


def mudar_rag(viejo: Path, nuevo: Path) -> dict:
    """Mueve los índices del árbol al dir del usuario. Colisión → gana el destino."""
    res = {"movidos": 0, "conservados": 0, "origen": str(viejo), "destino": str(nuevo)}
    if _ya_mudado(nuevo) or not viejo.exists() or viejo.resolve() == nuevo.resolve():
        res["omitido"] = "nada que mudar"
        _marcar(nuevo)
        return res
    for src in viejo.rglob("*"):
        if not src.is_file() or src.name == _MARCA:
            continue
        dst = nuevo / src.relative_to(viejo)
        try:
            if dst.exists():
                # El del destino es más nuevo por construcción: se conserva y el de origen
                # NO se toca. Perder un documento del usuario por una mudanza sería peor
                # que la ruta rota que vinimos a arreglar.
                res["conservados"] += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            res["movidos"] += 1
        except OSError:
            pass
    _marcar(nuevo)
    return res


def _leer_eventos(p: Path) -> list:
    out = []
    try:
        for linea in p.read_text(encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                out.append(json.loads(linea))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _clave(e: dict) -> tuple:
    """Identidad de un evento para no duplicar al fusionar. `id` cuando está; si no, la
    terna que lo hace único en la práctica."""
    return (e.get("id"), e.get("ts"), e.get("type") or e.get("tipo"), e.get("space_id"))


def reconciliar_espacios(viejo: Path, nuevo: Path) -> dict:
    """Fusiona los `events.jsonl` huérfanos al canónico, por timestamp y sin duplicar."""
    res = {"espacios": 0, "eventos_sumados": 0, "origen": str(viejo), "destino": str(nuevo)}
    if _ya_mudado(nuevo) or not viejo.exists() or viejo.resolve() == nuevo.resolve():
        res["omitido"] = "nada que reconciliar"
        _marcar(nuevo)
        return res
    for src in sorted(viejo.glob("*/events.jsonl")):
        space_id = src.parent.name
        dst = nuevo / space_id / "events.jsonl"
        huerfanos = _leer_eventos(src)
        if not huerfanos:
            continue
        actuales = _leer_eventos(dst) if dst.exists() else []
        vistos = {_clave(e) for e in actuales}
        nuevos = [e for e in huerfanos if _clave(e) not in vistos]
        if not nuevos:
            continue
        # APPEND POR TIMESTAMP: se reescribe el archivo con las dos historias ordenadas.
        # Concatenar sin ordenar dejaría el log con el tiempo yendo hacia atrás a la mitad,
        # y cualquiera que lo lea en orden sacaría la secuencia equivocada.
        juntos = sorted(actuales + nuevos, key=lambda e: (e.get("ts") or 0, e.get("id") or 0))
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open("w", encoding="utf-8") as fh:
                for e in juntos:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            res["espacios"] += 1
            res["eventos_sumados"] += len(nuevos)
        except OSError:
            pass
    _marcar(nuevo)
    return res


def mudar_todo() -> dict:
    """Corre las dos mudanzas. Nunca levanta: el arranque no se cae por esto."""
    salida: dict[str, Any] = {}
    try:
        import aleph_paths
        from app.phase1 import rag_store
        from app import espacios as _esp
        salida["rag"] = mudar_rag(rag_store._RAG_ROOT_VIEJA, aleph_paths.rag_dir())
        salida["espacios"] = reconciliar_espacios(_esp._ESPACIOS_DIR_VIEJA,
                                                  aleph_paths.espacios_dir())
    except Exception as e:                   # noqa: BLE001 — frontera del arranque
        salida["error"] = f"{type(e).__name__}: {e}"
    return salida


__all__ = ["mudar_todo", "mudar_rag", "reconciliar_espacios"]
