"""cerebro.py — LA COSTURA: el cerebro de Aleph enchufado a Local Deep Research.
[Gate 4 · Fase 6 · §6.f · LEY 12 · LEY 2]

LA COSTURA ES UN PARÁMETRO, Y ES DE ELLOS
------------------------------------------
LDR no se toca. Su API pública recibe el modelo **por parámetro**:

    quick_summary(query, llms={"aleph": <BaseChatModel>}, provider="aleph", ...)

`third_party/ldr/src/local_deep_research/api/research_functions.py:44` declara el
parámetro; `:90-95` lo registra con `register_llm()`; `:102` construye con `get_llm(...)` y
`:141` lo **inyecta** en `AdvancedSearchSystem(llm=llm, ...)`. El núcleo agéntico no va a
buscar el modelo a ningún lado — lo recibe. Cero corte de código en el camino del modelo.

POR QUÉ EL REGISTRO Y NO `openai_endpoint`
-------------------------------------------
LDR tiene un PEP de egreso delante de su fábrica de modelos
(`third_party/ldr/src/local_deep_research/config/llm_config.py:140-215`) que **falla
cerrado**. Ahí mismo, en `:167-171`, ellos declaran la excepción:

    # User-registered in-process LLMs are exempt here for the same
    # reason evaluate_llm_endpoint allows them: no endpoint to
    # classify, operator-injected, audit-hook backstopped.

O sea: el camino del registro es **la puerta que el repo dejó abierta para este caso
exacto** (ley 9.6: se toca únicamente por la costura que el propio repo dejó). La
alternativa `provider="openai_endpoint"` + una URL `127.0.0.1` también pasaría, pero
dependería de que su clasificador de egreso siga tratando el loopback como privado — una
apuesta sobre código ajeno que no hace falta hacer.

DE DÓNDE SALE LA CONFIGURACIÓN
-------------------------------
No se inventa nada acá: la escribe el pack de la casa, en cada `enter`,
`platform/workspaces/pack.py:329-389`, con este cuerpo:

    {"provider": {"aleph": {"options": {"baseURL": <base>+brain_path,
                                        "apiKey": <sesión>,
                                        "headers": {"X-Aleph-Workspace": …}}}},
     "model": "aleph/cerebro"}

Es dialecto de OpenCode (el que hablan Ciencia y Legal), pero como **portador** de
(baseURL, apiKey, headers) sirve igual para un stack de Python. Por eso este pack **no
necesita tocar `pack.py`**: lee el mismo archivo y lo traduce acá.

EL `model` QUE VIAJA NO GOBIERNA
---------------------------------
El borde **ignora el campo `model`** del cuerpo a propósito (`router.py:3355-3466`; el
cerebro lo elige la receta, no el cliente). Se manda igual porque el SDK de OpenAI exige el
campo. El `model_final` honesto vuelve en la respuesta y es el que vale.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

#: Prefijo del nombre con el que el cerebro queda registrado adentro de LDR.
#:
#: **NO es constante, y ésa es la corrección importante.** El registro de LDR es GLOBAL al
#: proceso y está keyeado por nombre
#: (`third_party/ldr/src/local_deep_research/llm/llm_registry.py:32-37`, que incluso avisa
#: `"Overwriting existing LLM"` al pisar). Nuestro servidor es multihilo y arma **un
#: cliente por obra** —porque `X-Aleph-Space` se fija en las cabeceras al construir—, así
#: que con un nombre fijo dos obras simultáneas se pisan: la obra A resolvería el cliente
#: de B y **todos sus turnos quedarían anotados en el espacio de B**. Eso es exactamente la
#: procedencia que el anti-grift S8 lee: no es un detalle de concurrencia, es contaminar la
#: evidencia de un turno con la de otro.
PREFIJO = "aleph"


#: La clave con la que el PACK escribe el proveedor en su archivo de config
#: (`platform/workspaces/pack.py:346-352`, `cuerpo["provider"]["aleph"]`). Es el mismo
#: string que el prefijo, pero **no es el mismo concepto**: éste es un contrato con el
#: pack, aquél es una clave de un registro ajeno. Se separan para que cambiar uno no
#: arrastre al otro por accidente.
CLAVE_PACK = "aleph"


def nombre_de(obra_id: str) -> str:
    """El nombre de registro de ESTA obra. Único por obra, estable dentro de ella."""
    return f"{PREFIJO}-{obra_id}"

#: El id de modelo que viaja en el cuerpo. El borde lo ignora (ver arriba); se manda porque
#: el SDK lo exige. Se deja explícito y con nombre de la casa para que, si algún día
#: aparece en un log ajeno, se lea «Aleph» y no un modelo de un proveedor que no usamos.
MODELO = "aleph/cerebro"


class CosturaError(Exception):
    """No se pudo armar el cerebro, con causa legible para la superficie.

    Regla sellada: ninguna causa llega a una superficie sin copy. Las causas de acá se
    traducen en `servidor.py` (`_COPY`).
    """

    def __init__(self, causa: str, detalle: str = ""):
        self.causa = causa
        self.detalle = detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


def leer_config(ruta: Path) -> dict:
    """Lee el archivo que el pack escribió y devuelve `{base_url, api_key, headers}`.

    Falla con causa tipada; jamás devuelve una config a medias.
    """
    try:
        cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CosturaError("cerebro_sin_config", f"no está {ruta}") from None
    except (OSError, ValueError) as e:
        raise CosturaError("cerebro_config_ilegible", f"{type(e).__name__}: {e}") from None

    try:
        opciones = cuerpo["provider"][CLAVE_PACK]["options"]
        base_url = str(opciones["baseURL"]).rstrip("/")
    except (KeyError, TypeError, AttributeError):
        raise CosturaError(
            "cerebro_config_incompleta",
            f"{ruta} no declara provider.{CLAVE_PACK}.options.baseURL",
        ) from None

    if not base_url:
        raise CosturaError("cerebro_config_incompleta", "baseURL vacío")

    return {
        "base_url": base_url,
        # El apiKey es la SESIÓN de Aleph y puede venir vacía en dev (el borde exige
        # sesión sólo cuando viaja `X-Aleph-User`). No se rellena con un placebo.
        "api_key": str(opciones.get("apiKey") or ""),
        "headers": dict(opciones.get("headers") or {}),
    }


def construir(config: dict, *, space_id: Optional[str] = None,
              turno: Optional[int] = None, temperatura: float = 0.7) -> Any:
    """Devuelve un `BaseChatModel` de LangChain apuntado al borde de dialecto.

    `space_id` va como `X-Aleph-Space`: es **dónde se anotan los eventos** del turno. Sin
    él el borde produce el paso pero no tiene dónde archivarlo, y el anti-grift S8 queda
    ciego a todo lo que produce este modo — el mismo defecto que el plugin de Ciencia
    documenta en `platform/workspaces/plugins/openscience.js:9-12`. Por eso se arma **un
    cliente por obra**: las cabeceras de LangChain se fijan al construir.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:                       # noqa: BLE001 — causa honesta, no crash
        raise CosturaError(
            "cerebro_sin_sdk",
            f"falta langchain_openai en este intérprete ({e})",
        ) from None

    cabeceras = dict(config.get("headers") or {})
    if space_id:
        cabeceras["X-Aleph-Space"] = space_id
    if turno is not None:
        cabeceras["X-Aleph-Turn"] = str(turno)

    return ChatOpenAI(
        model=MODELO,
        base_url=config["base_url"],
        # El SDK de OpenAI rechaza una api_key vacía antes de mandar nada. En dev, cuando
        # el borde no exige sesión, se manda un valor inerte y VISIBLE: si aparece en un
        # log, se lee lo que es. Nunca una llave real, nunca un `sk-` fabricado.
        api_key=config.get("api_key") or "aleph-sin-sesion",
        default_headers=cabeceras,
        temperature=temperatura,
        # Sin reintentos del SDK: el borde ya tiene su propia política y un reintento acá
        # duplicaría turnos en el ledger de la casa.
        max_retries=0,
        timeout=float(os.environ.get("ALEPH_RESEARCH_TIMEOUT_S", "180")),
    )
