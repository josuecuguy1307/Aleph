"""cerebro.py — LA COSTURA: el cerebro de Aleph enchufado a browser-use.
[Gate 4 · Fase 6 · §6.a · LEY 2 · LEY 12]

QUÉ HACE
--------
Traduce el archivo que el pack escribe (dialecto de la casa) a los kwargs que
`browser_use.llm.ChatOpenAI` consume. Nada más. Es el mismo trabajo que
`platform/sala/busqueda/config.py` hace para Vane — **se leyó ése antes de escribir éste**,
y por eso este archivo hereda su lección más cara (las cabeceras, abajo).

LA DIFERENCIA CON VANE, Y POR QUÉ ESTE ARCHIVO ES MÁS CORTO
------------------------------------------------------------
Vane necesita que le escriban un JSON en disco: su selector queda VACÍO si el `baseURL` no
es el de OpenAI (`config.py:22-26`), así que hay que declararle el modelo a mano. browser-use
**no tiene selector**: recibe el objeto `ChatOpenAI` por constructor
(`browser_use/llm/openai/chat.py`), y ese objeto acepta `base_url` (`:41`), `api_key`
(`:38`) y `default_headers` (`:60`) — los tres pasados al cliente en
`_get_client_params()` (`:48-67`). No hay archivo que escribir: hay kwargs que armar.

⚠️ LAS CABECERAS NO SE TIRAN — la lección de Búsqueda, y acá aplica igual
--------------------------------------------------------------------------
El pack escribe `X-Aleph-Workspace`, `X-Aleph-User` y `X-Aleph-Puppet`
(`platform/workspaces/pack.py:346-352`). La primera versión de la costura de Búsqueda las
descartaba y sus llamadas llegaban al borde **sin identidad y sin `X-Aleph-Space`** — sin
espacio el borde produce el paso pero no tiene dónde archivarlo, y **el anti-grift S8 queda
ciego a todo lo que este modo produce** (`platform/sala/busqueda/config.py:120-127`).
browser-use da decenas de pasos por tarea: ciego acá cuesta más que en ningún otro modo.

LO QUE ESTE MÓDULO NO HACE: no importa `browser_use` (así se prueba sin el paquete
instalado), no abre red, no elige modelo. Devuelve un dict de kwargs. Sólo stdlib.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

#: El modelo que se le declara al borde. El borde lo IGNORA a propósito —el cerebro lo elige
#: la receta (LEY 12)— pero el cliente de OpenAI exige un string no vacío. Es la misma trampa
#: de los dos espacios de id que `config.py:28-32` ya dejó escrita para Vane.
MODELO_DECLARADO = "aleph-brain"

#: Sin sesión, un string coherente: el borde autoriza por cabecera, no por esta clave.
API_KEY_SIN_SESION = "aleph-sin-sesion"


class CosturaError(Exception):
    def __init__(self, causa: str, detalle: str = ""):
        self.causa = causa
        self.detalle = detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


def leer_pack(ruta: Path) -> dict:
    """El archivo del pack: `provider.aleph.options.{baseURL, apiKey, headers}`.

    MISMA FORMA que la de Búsqueda a propósito: un solo escritor (`pack.py`) y dos lectores
    que leen igual. Un segundo formato acá sería la tercera copia del mismo contrato."""
    try:
        cuerpo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        opciones = cuerpo["provider"]["aleph"]["options"]
        base = str(opciones["baseURL"]).rstrip("/")
    except FileNotFoundError:
        raise CosturaError("cerebro_sin_config", f"no está {ruta}") from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CosturaError("cerebro_config_incompleta", f"{ruta}: {type(e).__name__}") from None
    if not base:
        raise CosturaError("cerebro_config_incompleta", "baseURL vacío")
    return {"base_url": base,
            "api_key": str(opciones.get("apiKey") or ""),
            "headers": dict(opciones.get("headers") or {})}


def armar(cerebro: dict, *, space_id: Optional[str] = None,
          modelo: str = MODELO_DECLARADO) -> dict[str, Any]:
    """Los kwargs de `ChatOpenAI`. `space_id` entra como `X-Aleph-Space`: sin él el borde no
    tiene dónde archivar el paso y S8 no puede cruzar nada de lo que este modo produzca."""
    base = str(cerebro.get("base_url") or "").rstrip("/")
    if not base:
        raise CosturaError("cerebro_config_incompleta", "base_url vacío")
    headers = dict(cerebro.get("headers") or {})
    if space_id:
        headers["X-Aleph-Space"] = str(space_id)
    return {
        "model": modelo,
        "base_url": base,
        "api_key": str(cerebro.get("api_key") or "") or API_KEY_SIN_SESION,
        "default_headers": headers or None,
    }


def desde_pack(ruta: Path, *, space_id: Optional[str] = None) -> dict[str, Any]:
    """El camino entero, para el llamador que sólo tiene la ruta del pack."""
    return armar(leer_pack(ruta), space_id=space_id)


__all__ = ["leer_pack", "armar", "desde_pack", "CosturaError",
           "MODELO_DECLARADO", "API_KEY_SIN_SESION"]
