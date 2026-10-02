"""perfil.py — LAS PERILLAS DE browser-use, DERIVADAS DEL CEREBRO ELEGIDO.
[Gate 4 · Fase 6 · §6.a · «cambiar de cerebro es cambiar el modelo, no tocar código»]

EL PROBLEMA QUE RESUELVE
------------------------
La corrida del 2026-08-18 dejó tres perillas puestas A MANO para que el turno pasara:

    use_vision=False                      porque el borde devolvió 409 missing:['vision']
    dont_force_structured_output=True     porque el borde descarta `response_format`
    add_schema_to_system_prompt=True      idem
    (y el timeout de 75 s por llamada mató las 6 llamadas de qwen3:8b)

Si esas cuatro quedan como constantes, el día que alguien ponga su llave de API y elija un
modelo con visión, browser use **sigue navegando a ciegas** y nadie se entera. Este módulo
las DERIVA de lo que el cerebro declara, para que ese día no haya que editar nada.

DE DÓNDE SALEN LAS CAPACIDADES — el mecanismo YA EXISTE y no se duplica
-----------------------------------------------------------------------
`product/backend/app/phase1/model_use_resolver.py` ya tiene `declara_matriz(row)` y
`normalized_capabilities(row)`, y su docstring trae la lección cara que este módulo hereda
entera: **jamás caer al vocabulario de `capacidades`**, que son RASGOS DE UI. Medido allá el
2026-08-12 sobre las 13 filas reales, ese respaldo mentía en las dos direcciones — seis
filas de API quedaban sin `text` ni `tool_calling` (Claude rechazándose a sí mismo para un
chat), y el rasgo `vision` de la MARCA se heredaba a modelos que no ven.

Acá se aplica lo mismo: **sin matriz declarada no se prende nada.** `vision` ausente es
`use_vision=False`, y `vision` presente es `True` — pero la ausencia se distingue de la
declaración vacía, porque «no medí» ≠ «medí y dio cero».

⚠️ Y HAY UN DATO MEDIDO QUE ESTE MÓDULO NO PUEDE ADIVINAR: el `:8926` **no transporta
imágenes**. Probado el 2026-08-18 con un secreto irrepetible dentro de un PNG: el modelo
contestó `NO-VEO-IMAGEN`, la frase de escape, en vez de inventar un código. La causa está en
`cli_brain/prompt_bridge.py:204` — `f"[Usuario]: {content}"` con `content` lista vuelve el
base64 **texto literal**. Por eso `centro_modelos.py:197` NO declara `vision` para
`cli.claude_cli`, y esa declaración **es correcta**: no es conservadora, es un hecho del
puente. Cuando el puente aprenda a mandar imágenes, se agrega `vision` a esa fila y este
módulo prende la captura solo.
"""
from __future__ import annotations

import os
from typing import Any, Optional

#: Techo por llamada, por defecto. browser-use usa 75 s (`agent/service.py:274`) y con eso
#: qwen3:8b murió 6 de 6 veces — gasta ~400 tokens de razonamiento antes de la primera letra
#: útil. No se hardcodea otro número: se declara el default de la casa y se deja pisar.
TIMEOUT_DEFAULT_S = 75
TIMEOUT_ENV = "ALEPH_BROWSER_LLM_TIMEOUT_S"

#: ¿El borde honra `response_format`? HOY NO —lo descarta en silencio, medido contra
#: `WorkspaceBrainOpenAIRequest`— y por eso el schema viaja en el prompt. El día que el
#: borde lo declare, esta variable pasa a "1" y el schema estricto vuelve **sin reescribir
#: el arranque**. Es una perilla y no una constante justamente por eso.
SCHEMA_ENV = "ALEPH_BORDE_HONRA_RESPONSE_FORMAT"


def _caps(fila: Optional[dict]) -> set[str]:
    """Las capacidades declaradas del cerebro, normalizadas. Reusa el lector de la casa;
    si no está en el path (dev suelto), cae a una normalización equivalente y NADA MÁS —
    jamás al vocabulario de rasgos."""
    if not fila:
        return set()
    try:
        from app.phase1.model_use_resolver import declara_matriz, normalized_capabilities
        return normalized_capabilities(fila) if declara_matriz(fila) else set()
    except Exception:                                    # noqa: BLE001
        crudas = fila.get("model_use_capabilities")
        if crudas is None:                               # ausente ≠ vacía
            return set()
        return {str(c).strip().casefold() for c in crudas if str(c).strip()}


def perillas(fila_del_cerebro: Optional[dict], *, timeout_s: Optional[int] = None) -> dict[str, Any]:
    """Las perillas de browser-use para ESTE cerebro. Nada acá está escrito a mano.

    Devuelve lo que consumen `Agent(...)` y `ChatOpenAI(...)`:
      · `use_vision`  — `True` sólo si el cerebro DECLARA `vision`.
      · `llm_timeout` — el techo por llamada (env, argumento, o el default de la casa).
      · `dont_force_structured_output` / `add_schema_to_system_prompt` — invertidos el día
        que el borde honre `response_format`.
    """
    caps = _caps(fila_del_cerebro)
    honra = str(os.environ.get(SCHEMA_ENV, "")).strip().lower() in ("1", "true", "si", "sí")
    try:
        techo = int(timeout_s if timeout_s is not None
                    else os.environ.get(TIMEOUT_ENV) or TIMEOUT_DEFAULT_S)
    except (TypeError, ValueError):
        techo = TIMEOUT_DEFAULT_S
    return {
        "use_vision": "vision" in caps,
        "llm_timeout": max(1, techo),
        # Las dos válvulas son la MISMA decisión mirada de los dos lados: mientras el borde
        # no honre el campo, no se le exige y el schema va en el prompt.
        "dont_force_structured_output": not honra,
        "add_schema_to_system_prompt": not honra,
        "_caps_declaradas": sorted(caps),
    }


#: Copy de los dos estados que el usuario tiene que poder leer ANTES de que falle. Ninguna
#: causa llega a una superficie sin copy — la misma regla que el borde ya cumple.
COPY = {
    "sin_vision": (
        "Este cerebro no ve imágenes, así que voy a navegar leyendo la estructura de la "
        "página. En páginas con mapas, gráficos o botones sin texto puedo no encontrar lo "
        "que buscas. Con un modelo que vea, uso capturas."),
    "cerebro_lento": (
        "Este cerebro tarda más de lo que un navegador aguanta por paso. Para manejar el "
        "navegador conviene un cerebro de CLI o de API."),
}


def aviso(fila_del_cerebro: Optional[dict]) -> Optional[dict]:
    """Lo que la pantalla dice ANTES de arrancar, o `None` si no hay nada que avisar."""
    p = perillas(fila_del_cerebro)
    if not p["use_vision"]:
        return {"causa": "browser_sin_vision", "copy": COPY["sin_vision"],
                "detalle": f"capacidades declaradas: {', '.join(p['_caps_declaradas']) or '(ninguna)'}"}
    return None


__all__ = ["perillas", "aviso", "COPY", "TIMEOUT_DEFAULT_S", "TIMEOUT_ENV", "SCHEMA_ENV"]
