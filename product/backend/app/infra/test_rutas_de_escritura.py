"""test_rutas_de_escritura.py — EL BUNDLE ES SÓLO LECTURA.

Guard de CLASE, no de caso. La regla: todo lo que se ESCRIBE va al dir de datos del
usuario; el bundle sólo se lee. Se rompió tres veces antes (synth_belts, el pin del sello,
la caché del resolver) y dos más acá (RAG y espacios) — cada vez con el mismo síntoma:
bajo PyInstaller la ruta cae en `_MEIPASS`, el temp que se borra al cerrar la app, y lo
que el usuario guardó desaparece.

Este test recorre TODOS los resolvedores de escritura de una sola vez: si alguien agrega
un `_REPO_ROOT / "product" / "backend" / "data" / …` nuevo, esto se pone rojo con su nombre
en vez de descubrirse el día que un usuario pierda sus documentos.

Correr: pytest product/backend/app/infra/test_rutas_de_escritura.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

import aleph_paths  # noqa: E402


def _resolvedores():
    """(nombre, ruta) de cada punto de ESCRITURA del árbol. Se importan perezoso para que
    un módulo pesado no tumbe la colección."""
    import bridge, contracts, mcp_registry, registry            # noqa: E401
    from app import espacios
    from app.phase1 import account_deletion, inspect_router, knowledge_store
    from app.phase1 import rag_store, resolve_router
    return [
        ("rag_store.RAG_ROOT", rag_store.RAG_ROOT),
        ("knowledge_store.rag_dir_root", Path(knowledge_store.rag_dir_root())),
        ("espacios.DEFAULT_ESPACIOS_DIR", espacios.DEFAULT_ESPACIOS_DIR),
        ("bridge._DEFAULT_ESPACIOS", bridge._DEFAULT_ESPACIOS),
        ("inspect_router._ESPACIOS", inspect_router._ESPACIOS),
        ("resolve_router._ESPACIOS", resolve_router._ESPACIOS),
        ("contracts.SYNTH_BELTS_DIR", contracts.SYNTH_BELTS_DIR),
        ("registry.SYNTH_BELTS_DIR", registry.SYNTH_BELTS_DIR),
        ("mcp_registry._CACHE_DIR", mcp_registry._CACHE_DIR),
        ("account_deletion._OUTBOX", account_deletion._OUTBOX),
    ]


def test_ninguna_escritura_cae_en_el_arbol():
    """El bundle es de lectura. Una ruta bajo el repo funciona en dev y MIENTE en la .app:
    ahí es `_MEIPASS` y se borra al cerrar."""
    raiz = str(aleph_paths.data_root())
    malas = [(n, str(p)) for n, p in _resolvedores() if not str(p).startswith(raiz)]
    assert not malas, "escriben fuera del dir de datos del usuario:\n  " + "\n  ".join(
        f"{n} -> {p}" for n, p in malas)


def test_ninguna_escritura_cae_en_MEIPASS():
    """El síntoma directo, por si `data_root()` cambiara: nada que se escriba puede vivir
    en el temp del bundle."""
    malas = [n for n, p in _resolvedores() if "_MEI" in str(p)]
    assert not malas, f"escriben en el temp del bundle: {malas}"


def test_los_que_comparten_destino_lo_comparten_de_verdad():
    """FUENTE ÚNICA. El split-brain de espacios era EL MISMO event-log en dos lugares
    según quién lo abriera; el de RAG, dos módulos calculando la misma raíz por su cuenta.
    Si divergen otra vez, esto lo dice acá y no en producción."""
    r = dict(_resolvedores())
    espacios = {r["espacios.DEFAULT_ESPACIOS_DIR"], r["bridge._DEFAULT_ESPACIOS"],
                r["inspect_router._ESPACIOS"], r["resolve_router._ESPACIOS"]}
    assert len({str(x) for x in espacios}) == 1, f"espacios divergen: {espacios}"

    rag = {str(r["rag_store.RAG_ROOT"]), str(r["knowledge_store.rag_dir_root"])}
    assert len(rag) == 1, f"las dos raíces de RAG divergen: {rag}"

    belts = {str(r["contracts.SYNTH_BELTS_DIR"]), str(r["registry.SYNTH_BELTS_DIR"])}
    assert len(belts) == 1, f"synth_belts diverge: {belts}"


def test_el_guard_de_pertenencia_sigue_duro_en_LAS_DOS_raices():
    """La mudanza no puede ablandar el aislamiento. Una receta vieja lleva el `rag.dir`
    repo-relativo; si el guard dejara de reconocer esa raíz, la trataría como «dir
    cualquiera» y se saltearía la comprobación cross-user."""
    from app.phase1 import rag_store
    yo, otro = "user-a", "user-b"
    assert rag_store.is_owned_rag_dir(rag_store.rel_dir(yo, "ag"), yo) is True
    assert rag_store.is_owned_rag_dir(rag_store.rel_dir(otro, "ag"), yo) is False
    assert rag_store.is_owned_rag_dir(f"product/backend/data/rag/{otro}/ag", yo) is False
    assert rag_store.is_owned_rag_dir("catalog/templates/algo", yo) is True
