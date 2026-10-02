"""artefactos_del_borde.py — LO QUE UN WORKSPACE SIN PLUGIN PRODUCE, CRUZADO POR EL BORDE.

[Finanzas · los artefactos]

EL AGUJERO QUE TAPA, Y CÓMO SE MIDIÓ (grep y lectura, no una intuición)
──────────────────────────────────────────────────────────────────────
La fila de Finanzas del registro declara, en un comentario, cómo llegan sus artefactos a
la casa (`router.py`, entrada `"finanzas"`):

    «Sin plugin: este stack no tiene el punto de extensión `config.plugin` que tiene el
     de Ciencia. Lo que el workspace produce cruza al puente por
     POST /v1/workspaces/artifact»

**Eso es una declaración, no un estado.** Medido sobre el árbol:

  · el endpoint existe (`router.py` · `@router.post("/workspaces/artifacts")`) y es el
    ÚNICO llamante de `bridge.cross()` en producción;
  · `grep -rn "workspaces/artifacts"` sobre el árbol entero devuelve tres llamantes, y
    **los tres son plugins**: `plugins/openscience.js:178` · `plugins/openwork.js:247` ·
    `plugins/dochaus.js:24`. Ninguno es de Finanzas, que no tiene plugin;
  · por lo tanto `bridge.TABLE["finanzas"]` —`market_ohlcv` y `alpha_zoo`, las dos filas
    que la Fase 6 midió contra el stack vivo y dejó escritas con su caso— es **código
    inalcanzable**, y Finanzas no produce UN SOLO artefacto de la casa.

Hasta el nombre de la ruta del comentario estaba mal (`/artifact`, sin la `s`): nadie la
llamó nunca, así que nadie se enteró. Es la misma forma de defecto que este repo ya tiene
nombrada —el mecanismo construido y sin llamador— y por eso el arreglo no inventa un
puente nuevo: le pone el llamador al que ya existe.

POR QUÉ EL BORDE Y NO UN PLUGIN
───────────────────────────────
Porque este stack no tiene dónde enchufar uno, y construírselo sería tocarle el oficio.
El borde, en cambio, ya ve el turno: el harness manda el historial COMPLETO en cada paso
(`POST /v1/workspaces/brain/openai/chat/completions`), así que los `role:"tool"` del paso
anterior pasan por acá sin pedirle nada al stack. Es exactamente el precedente que
`hilo_workspace.py` ya sentó para el HILO —«los que no tienen plugin, los anota el
borde»— y de ahí se hereda todo: el mismo `le_toca_al_borde(meta)` como guarda, el mismo
«es proyección, jamás camino crítico», y el mismo módulo puro para que se pueda MEDIR sin
levantar el endpoint entero.

LO QUE ESTE MÓDULO **NO** HACE
──────────────────────────────
  · No traduce. La traducción es del puente (`platform/artifacts/bridge.py`) y sigue
    siendo suya: acá se decide QUÉ resultado es un artefacto, y el puente decide si se
    puede entregar sin inventar dato. Si el puente rechaza, acá no se guarda nada — un
    `BridgeError` es la respuesta correcta, no un problema a esquivar.
  · No autoriza. El dueño del `sid` se verifica río arriba, en el borde, igual que el hilo.
  · No adivina qué tool produce qué. **Lo declara la tabla de abajo**, workspace por
    workspace, y un workspace que no está tiene mapa VACÍO: cero regresión para los otros
    cinco. Es la misma disciplina que `tool_budget.PISO_POR_WORKSPACE` («se declara por
    workspace y no se infiere»).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

_log = logging.getLogger("aleph.artefactos_del_borde")

#: `workspace → {nombre de la tool del stack: kind del puente}`.
#:
#: LAS DOS FILAS DE FINANZAS, Y POR QUÉ SON ESTAS DOS Y NO MÁS. El puente sólo sabe
#: recibir de Finanzas lo que la Fase 6 midió contra el stack corriendo: `market_ohlcv` y
#: `alpha_zoo` (`bridge.TABLE["finanzas"]`, cada una con su caso ejecutado escrito al
#: lado). Declarar acá una tercera obligaría a inventarle una fila al puente, que es
#: justamente lo que el puente existe para que no pase. Cuando el puente gane una fila
#: nueva, gana su tool acá **en el mismo commit** — y `verify_artefactos_del_borde.py`
#: falla si las dos tablas se desincronizan.
#:
#: LOS NOMBRES SALEN DEL CÓDIGO DEL STACK, no de su documentación:
#:   · `get_market_data`  `third_party/vibetrading/agent/src/tools/market_data_tool.py:14`
#:     devuelve `json.dumps(fetch_market_data(...))`, y `fetch_market_data` arma
#:     `results[symbol] = records` (`agent/src/market_data.py:198-204`) — o sea
#:     `{símbolo: [barras]}`, que es EXACTAMENTE la forma que `_ohlcv_a_planilla` aplana.
#:   · `alpha_zoo`        `agent/src/tools/alpha_zoo_tool.py:152` devuelve
#:     `json.dumps({"status": "ok", "result": {... "items": [...]}})` (`:47`, `:85`), que
#:     es la forma que `_resultado_anidado_a_planilla` desenvuelve.
#: Las dos filas del puente se escribieron midiendo esas salidas; esta tabla sólo dice qué
#: tool las emite.
#: ⚠️ EDUCACIÓN NO ESTÁ ACÁ, Y NO ES UN OLVIDO. [Educación · los artefactos · 2026-08-27]
#: Es de la misma familia —stack sin plugin— y aun así esta puerta no le sirve, por la
#: FORMA del resultado y no por el mapa:
#:
#:   · Finanzas cumple el contrato de este módulo: `market_data.py:228` hace `json.dumps`,
#:     así que el `role:"tool"` lleva JSON y `cosechar` lo puede abrir.
#:   · Educación no puede: su harness arma el mensaje con `"content": result_text`
#:     (`third_party/deeptutor/deeptutor/core/agentic/tool_dispatch.py:637-645`), que es
#:     PROSA para el modelo; lo estructurado queda en `metadata` / `tool_metadata_by_id`,
#:     que no cruzan el protocolo OpenAI. Barridas las **19** clases de tool de
#:     `deeptutor/tools/builtin/__init__.py`: **ninguna** pone `json.dumps` adentro de
#:     `ToolResult(content=…)`. El `json.loads` de abajo excluye 19 de 19 — hoy y para
#:     cualquier fila que se le agregue.
#:
#: Declararle filas sin resolver eso daría un mapa verde sobre un mecanismo mudo, que es
#: justo el defecto que este archivo vino a cerrar. `qa/verify_cosecha_educacion.py` lo
#: mide corriendo este módulo: con la forma de Finanzas cosecha 1, con la de Educación
#: cosecha 0 **incluso con la fila puesta a mano**.
#:
#: Y hay un corte más de fondo que una fila no arregla: los entregables de Educación
#: —ejercicio, informe, visualización, ruta de estudio, solución— son resultados de
#: CAPACIDAD, no de tool, y nunca aparecen como `role:"tool"`. Para ésos falta un canal.
KINDS_POR_WORKSPACE: dict[str, dict[str, str]] = {
    "finanzas": {
        "get_market_data": "market_ohlcv",
        "alpha_zoo": "alpha_zoo",
    },
}


def kinds_de_workspace(workspace: Any) -> dict:
    """El mapa tool→kind de ese workspace. Desconocido → vacío (o sea: no pasa nada).

    Tolera `None`, `""` y mayúsculas: el borde recibe el nombre por cabecera HTTP, y un
    mapa que se pierde por un rótulo con otra caja sería el fallo mudo que esto evita.
    """
    if not isinstance(workspace, str):
        return {}
    return KINDS_POR_WORKSPACE.get(workspace.strip().casefold(), {})


def _nombre(x: Any, *k: str) -> Any:
    """Un campo, venga el mensaje como dict o como modelo pydantic. El cuerpo es AJENO."""
    cur = x
    for clave in k:
        if isinstance(cur, dict):
            cur = cur.get(clave)
        else:
            cur = getattr(cur, clave, None)
        if cur is None:
            return None
    return cur


def _texto_del_resultado(m: Any) -> str:
    """El `content` de un mensaje `role:"tool"`, que puede venir string o en partes.

    Misma razón que `hilo_workspace.texto_de_mensaje`: hacerle `str()` a la lista deja un
    `[{'type': 'text', …}]` metido adentro del artefacto — la misma forma del
    `[object Object]` que ya nos mordió una vez en la Sala.
    """
    c = _nombre(m, "content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        partes = []
        for p in c:
            if isinstance(p, str):
                partes.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                partes.append(p["text"])
        return "\n".join(partes)
    return ""


def _mapa_de_llamadas(messages: Any) -> dict:
    """`tool_call_id → nombre de la tool`, leído de los `assistant` del historial.

    POR QUÉ POR ID Y NO POR EL CAMPO `name` DEL PROPIO MENSAJE `tool`: porque `name` es
    OPCIONAL en el protocolo OpenAI y varios harness no lo mandan. El `tool_call_id` sí es
    obligatorio para poder aparear la respuesta con su llamada, así que es la única
    referencia que no depende de la buena voluntad del stack. Si igual viene `name`, se
    usa como respaldo — no se descarta un dato que está.
    """
    out: dict = {}
    for m in (messages or []):
        for tc in (_nombre(m, "tool_calls") or []):
            _id = _nombre(tc, "id")
            _fn = _nombre(tc, "function", "name")
            if _id and _fn:
                out[str(_id)] = str(_fn)
    return out


def cosechar(messages: Any, *, workspace: Any) -> list:
    """Los resultados de tool de ESTE historial que son artefactos declarados.

    Devuelve `[{"kind", "tool", "name", "data", "huella"}]`, en el orden en que aparecen.

    LA `huella` ES LO QUE HACE QUE UN TURNO NO DEJE NUEVE COPIAS. El harness manda el
    historial COMPLETO en cada paso: un turno de nueve pasos hace pasar el mismo resultado
    de `get_market_data` nueve veces por acá. Sin huella, la Biblioteca terminaría con
    nueve planillas idénticas de un solo pedido. Es sha256 del `(kind, contenido crudo)`,
    o sea del DATO — no del id de la llamada, que cambia entre reintentos del mismo
    resultado.

    NUNCA LEVANTA. El cuerpo es de un proceso ajeno: un `content` que no es JSON, una
    lista donde se esperaba un objeto o un mensaje con una forma que nadie previó salen
    por el mismo lado —no cosechados— y el turno sigue. Un artefacto perdido es malo; un
    turno tumbado por intentar cosecharlo es peor.
    """
    mapa = kinds_de_workspace(workspace)
    if not mapa:
        return []
    try:
        por_id = _mapa_de_llamadas(messages)
        out, vistas = [], set()
        for m in (messages or []):
            if _nombre(m, "role") != "tool":
                continue
            tool = por_id.get(str(_nombre(m, "tool_call_id") or "")) or _nombre(m, "name")
            kind = mapa.get(str(tool or ""))
            if not kind:
                continue
            crudo = _texto_del_resultado(m)
            if not crudo.strip():
                continue
            try:
                data = json.loads(crudo)
            except (ValueError, TypeError):
                # NO se guarda el texto crudo como si fuera el dato. Una tool que declara
                # devolver JSON y devuelve otra cosa es una anomalía del stack, y
                # convertirla en un artefacto sería exactamente el «panel en blanco» que
                # el puente rechaza: una forma vacía pintada como si tal cosa.
                _log.info("cosecha: %s devolvió algo que no es JSON — no cruza", tool)
                continue
            if not isinstance(data, (dict, list)) or not data:
                continue
            huella = hashlib.sha256(
                ("%s\x1f%s" % (kind, crudo)).encode("utf-8")).hexdigest()
            if huella in vistas:
                continue                       # el mismo resultado repetido en el historial
            vistas.add(huella)
            out.append({"kind": kind, "tool": str(tool), "data": data,
                        "huella": huella,
                        "name": "%s · %s" % (workspace, tool)})
        return out
    except Exception as exc:                             # noqa: BLE001 — cuerpo ajeno
        _log.warning("cosecha_falló ws=%s error=%s", workspace, exc)
        return []


#: `chat → huellas ya cruzadas`. En proceso y a propósito: es una guarda contra el
#: historial repetido DENTRO de una conversación viva, no un registro de verdad. El
#: registro de verdad es el almacén de artefactos, y si el proceso se reinicia lo peor que
#: pasa es que un resultado que sigue en el historial se guarde una segunda vez —barato— en
#: vez de que un artefacto nuevo se pierda —caro—. Mismo criterio y misma forma que
#: `hilo_workspace._CON_CATALOGO`.
_YA_CRUZADO: dict = {}


def es_nueva(chat_id: Optional[str], huella: str) -> bool:
    """¿Esta huella todavía no se cruzó en este chat? Marca al preguntar (idempotente)."""
    clave = str(chat_id or "-")
    vistas = _YA_CRUZADO.setdefault(clave, set())
    if huella in vistas:
        return False
    vistas.add(huella)
    return True


def olvidar(chat_id: Optional[str]) -> None:
    """Suelta las huellas de un chat. Existe para las varas: sin esto, dos casos seguidos
    del mismo chat se pisan y el segundo mide el memo en vez del código."""
    _YA_CRUZADO.pop(str(chat_id or "-"), None)


__all__ = ["KINDS_POR_WORKSPACE", "kinds_de_workspace", "cosechar", "es_nueva", "olvidar"]
