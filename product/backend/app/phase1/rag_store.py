"""
rag_store.py — DOC-RAG v0: store de documentos por-agente en filesystem.

El usuario sube .md/.txt → se guardan en una carpeta POR (user_id, agent_key) →
ESA carpeta ES el `rag_dir` que la receta pasa al assembler (rag.dir), y que el
motor lee con `_load_rag` (YA existe, intacto). v0: sin embeddings, sin vector store
— solo archivos que el assembler concatena como "Contexto cargado (RAG)".

AISLAMIENTO (no-negociable): la carpeta es `data/rag/<user_id>/<agent_key>/`. El
user_id viene de la SESIÓN autorizada (no del cliente). Nombres y claves se sanitizan
(anti path-traversal): solo [A-Za-z0-9_.-], jamás '/', '..' ni rutas absolutas. Un run
de A nunca puede apuntar su rag.dir a la carpeta de B (el router valida la pertenencia
con `is_owned_rag_dir` antes de correr).

Solo stdlib. No toca DB ni el motor.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# rag_store.py: product/backend/app/phase1 → repo root = parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]

# ⚠️ LOS ÍNDICES VIVEN EN EL DIR DE DATOS DEL USUARIO, NO EN EL ÁRBOL.
# Esto era `_REPO_ROOT/product/backend/data/rag`, y bajo PyInstaller `parents[4]` cae
# DENTRO de `_MEIPASS` — el temp del bundle, que se borra al cerrar la app. Medido: ni
# `rag/` ni `espacios/` existían en Application Support. El usuario subía sus documentos
# y desaparecían al cerrar, rompiendo la ley que este módulo declara arriba: «el usuario
# es dueño de su índice». Un índice que muere al cerrar no es de nadie.
# `aleph_paths.rag_dir()` es la MISMA raíz que usan la base y el llavero.
def _rag_root() -> Path:
    try:
        import aleph_paths
        return aleph_paths.rag_dir()
    except Exception:                    # noqa: BLE001 — dev sin platform en el path
        return _REPO_ROOT / "product" / "backend" / "data" / "rag"


RAG_ROOT = _rag_root()

#: La raíz VIEJA. Sigue nombrada por dos razones: la migración de cortesía la busca al
#: arrancar, y el guard de pertenencia tiene que seguir reconociéndola — una receta
#: guardada antes de este cambio lleva `rag.dir` repo-relativo, y si el guard dejara de
#: verla como «área de RAG» pasaría a tratarla como un dir cualquiera y se saltearía la
#: comprobación cross-user. Degradar un guard en silencio es peor que la ruta rota.
_RAG_ROOT_VIEJA = _REPO_ROOT / "product" / "backend" / "data" / "rag"
_REL_ROOT = "product/backend/data/rag"   # forma repo-relativa histórica (recetas viejas)

_ALLOWED_EXT = (".md", ".txt")
_MAX_BYTES = 400_000   # tope por doc (v0): evita que un archivo gigante reviente el contexto


def _safe_seg(seg: str) -> str:
    """Sanitiza un segmento de ruta: solo [A-Za-z0-9_.-]; nunca '/', '..', vacío."""
    seg = re.sub(r"[^A-Za-z0-9_.-]", "_", (seg or "").strip())
    seg = seg.lstrip(".") or "x"          # nada que empiece con '.' (oculto / '..')
    return seg[:120]


def _safe_name(name: str) -> str:
    """Nombre de archivo seguro y con extensión permitida (.md/.txt). Default .md."""
    base = _safe_seg(Path(name or "doc").name)
    if not base.lower().endswith(_ALLOWED_EXT):
        base = base + ".md"
    return base


def agent_dir(user_id: str, agent_key: str) -> Path:
    return RAG_ROOT / _safe_seg(user_id) / _safe_seg(agent_key)


def rel_dir(user_id: str, agent_key: str) -> str:
    """El rag.dir repo-relativo que va en la receta (lo resuelve el assembler vs repo_root)."""
    # ABSOLUTO a propósito: `_build_rag` del assembler resuelve lo RELATIVO contra
    # `repo_root`, y la raíz ya no vive bajo el repo. Un relativo apuntaría de vuelta al
    # bundle. El assembler ya acepta absolutos (`p.is_absolute()` → se usa tal cual).
    return str(RAG_ROOT / _safe_seg(user_id) / _safe_seg(agent_key))


def save_doc(user_id: str, agent_key: str, name: str, content: str) -> dict[str, Any]:
    """Guarda un doc .md/.txt en la carpeta del agente. Devuelve {name, bytes}."""
    if not isinstance(content, str):
        raise ValueError("content debe ser texto (.md/.txt)")
    content = content[:_MAX_BYTES]
    d = agent_dir(user_id, agent_key)
    d.mkdir(parents=True, exist_ok=True)
    fname = _safe_name(name)
    (d / fname).write_text(content, encoding="utf-8")
    return {"name": fname, "bytes": len((content).encode("utf-8"))}


def list_docs(user_id: str, agent_key: str) -> list[dict[str, Any]]:
    d = agent_dir(user_id, agent_key)
    out: list[dict[str, Any]] = []
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in _ALLOWED_EXT:
            try:
                out.append({"name": p.name, "bytes": p.stat().st_size})
            except OSError:
                pass
    return out


def read_doc(user_id: str, agent_key: str, name: str) -> Optional[str]:
    """Devuelve el TEXTO de un doc del agente (para enganchar @doc al contexto). None si
    no existe / fuera de carpeta. Mismo guard anti-traversal que delete_doc."""
    p = agent_dir(user_id, agent_key) / _safe_name(name)
    try:
        base = agent_dir(user_id, agent_key).resolve()
        rp = p.resolve()
        if base != rp and base not in rp.parents:
            return None
        if rp.exists() and rp.is_file() and rp.suffix.lower() in _ALLOWED_EXT:
            return rp.read_text(encoding="utf-8")[:_MAX_BYTES]
    except OSError:
        return None
    return None


def delete_doc(user_id: str, agent_key: str, name: str) -> bool:
    p = agent_dir(user_id, agent_key) / _safe_name(name)
    # garantía extra: el archivo resuelto DEBE quedar dentro de la carpeta del agente
    try:
        base = agent_dir(user_id, agent_key).resolve()
        rp = p.resolve()
        if base != rp and base not in rp.parents:
            return False
        if rp.exists() and rp.is_file():
            rp.unlink()
            return True
    except OSError:
        pass
    return False


def is_owned_rag_dir(rag_dir: Optional[str], user_id: Optional[str]) -> bool:
    """GUARD DE AISLAMIENTO: ¿ese rag.dir (provisto por el cliente) pertenece a este user?

    True si el rag.dir NO toca el área de RAG (p.ej. un dir de catálogo legítimo) — esos
    no son cross-user. Si SÍ cae bajo data/rag/, exige que el primer segmento sea el
    user_id de la sesión. Así un cliente no puede apuntar a data/rag/<otro_user>/…
    """
    if not rag_dir:
        return True
    try:
        p = Path(rag_dir)
        abs_p = p if p.is_absolute() else (_REPO_ROOT / p)
        abs_p = abs_p.resolve()
        # LAS DOS RAÍCES. Una receta guardada antes de la mudanza lleva el `rag.dir`
        # repo-relativo viejo; si el guard sólo mirara la raíz nueva, esa ruta caería en
        # «no es área de RAG» y se saltearía la comprobación cross-user. El guard tiene
        # que seguir siendo duro con lo viejo, no sólo con lo nuevo.
        raices = []
        for r in (RAG_ROOT, _RAG_ROOT_VIEJA):
            try:
                raices.append(r.resolve())
            except OSError:
                pass
    except Exception:
        return False
    root = next((r for r in raices if r == abs_p or r in abs_p.parents), None)
    if root is None:
        return True   # no es del área de RAG → no es un problema de cross-user
    if not user_id:
        return False  # toca el área de RAG sin user → no autorizado
    try:
        owner_seg = abs_p.relative_to(root).parts[0]
    except (ValueError, IndexError):
        return False
    return owner_seg == _safe_seg(user_id)


def reown(old_user_id: str, new_user_id: str) -> int:
    """FUSIÓN (login suave): mueve data/rag/<device>/* → data/rag/<cuenta>/ conservando
    la estructura por agent_key. Ante colisión de archivo gana el de la cuenta (el doc
    local duplicado queda; no se pisa nada). Devuelve cuántos docs se movieron."""
    src = RAG_ROOT / _safe_seg(str(old_user_id))
    dst = RAG_ROOT / _safe_seg(str(new_user_id))
    if not src.is_dir() or src == dst:
        return 0
    moved = 0
    for agent_d in sorted(p for p in src.iterdir() if p.is_dir()):
        target = dst / agent_d.name
        target.mkdir(parents=True, exist_ok=True)
        for f in sorted(p for p in agent_d.iterdir() if p.is_file()):
            if not (target / f.name).exists():
                f.rename(target / f.name)
                moved += 1
        try:
            agent_d.rmdir()   # solo si quedó vacío
        except OSError:
            pass
    try:
        src.rmdir()
    except OSError:
        pass
    return moved


__all__ = ["RAG_ROOT", "agent_dir", "rel_dir", "save_doc", "list_docs",
           "delete_doc", "is_owned_rag_dir", "reown"]
