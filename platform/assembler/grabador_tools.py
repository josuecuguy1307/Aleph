#!/usr/bin/env python3
"""grabador_tools.py — QUÉ CATÁLOGO CRUZA, de verdad, por superficie.

Existe para no reconstruir seis registries distintos y creerles: graba el `tools` REAL
que cada superficie manda, en el punto donde cruza. Se enciende con
`ALEPH_GRABAR_TOOLS=<ruta.jsonl>` y no hace nada sin la variable.

Dos tomas, porque son dos caminos:
  · los SEIS workspaces cruzan por `/v1/workspaces/brain/openai/chat/completions`
  · La Sala NO cruza por ahí: arma sus tools en `recipe_assembler`

Cada línea es un PASO (una llamada al cerebro), así que contar líneas por turno da el
**K real** —cuántas vueltas hizo— sin inferirlo de nada.
"""
from __future__ import annotations

import json
import os
import threading
import time

_LOCK = threading.Lock()


def _destino() -> str:
    return (os.environ.get("ALEPH_GRABAR_TOOLS") or "").strip()


def grabar(superficie: str, tools, *, paso: str = "", extra: dict | None = None) -> None:
    """Anota un paso. Nunca levanta: un grabador que rompe el turno no sirve de nada."""
    ruta = _destino()
    if not ruta:
        return
    try:
        tools = list(tools or [])
        fila = {
            "ts": time.time(),
            "superficie": superficie or "?",
            "paso": paso,
            "n_tools": len(tools),
            "nombres": [(t.get("function", t) or {}).get("name") for t in tools],
            "tools": tools,
        }
        if extra:
            fila.update(extra)
        with _LOCK, open(ruta, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
