"""hilo_workspace.py — EL TURNO DE UN WORKSPACE, EN EL HILO DE LA CASA.

[convergencia · superficie 1]

EL AGUJERO QUE TAPA, MEDIDO EN `aleph.db` ANTES DE ESCRIBIRLO. La pantalla de cada
workspace ya crea un hilo de la casa, lo bautiza con el nombre del workspace y lo recuerda
por `(dueño, workspace)` — los seis están en la tabla `chats`. Lo que faltaba era que el
turno LLEGARA a ese hilo. Se proyectaba en UN solo lugar, `POST /v1/workspaces/brain/close`,
y a `close` lo llaman los PLUGINS. Sólo tres stacks declaran plugin, así que los otros tres
tenían un hilo que nacía, se bautizaba y quedaba vacío para siempre:

    Ciencia 8 user / 4 agent · Oficina 4/0 · Legal 0/1 · Finanzas 1/0 · Diseño 0/0 · Educación 0/0

POR QUÉ ESTE MÓDULO EXISTE Y NO ES UN CLOSURE MÁS DE `router.py`. Porque tiene que poder
MEDIRSE. Un closure adentro de `build_phase1_router` sólo se alcanza levantando el endpoint
entero —o sea con sesión, catálogo de modelos, llave y proveedor vivo—, y una vara que
necesita todo eso no se corre nunca. Acá adentro no hay HTTP: entra un cuerpo de mensajes y
una conexión, sale una fila. Es el mismo criterio que el seam `window.__salaV2`: la vara
mide PRODUCCIÓN, no un arnés paralelo.

LO QUE ESTE MÓDULO **NO** HACE: decidir quién es el dueño del hilo. Eso es autorización y
vive en el borde, río arriba, antes de llamar acá.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

_log = logging.getLogger("aleph.hilo_workspace")


def texto_de_mensaje(m: Any) -> str:
    """El texto de un mensaje OpenAI, que puede venir string o en partes.

    Un `content` puede ser `"hola"` o `[{"type":"text","text":"hola"}, …]` (el formato
    multimodal). Quedarse con el primero, o hacerle `str()` a la lista, deja el prompt en
    algo como `[{'type': 'text', …}]` del lado del hilo — que es la misma forma del
    `[object Object]` que ya nos mordió una vez en la Sala.
    """
    c = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
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


def _rol(m: Any) -> Any:
    return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)


# ── EL ANDAMIAJE NO ES UN TURNO ──────────────────────────────────────────────────────
#
# EL DEFECTO, MEDIDO EN LA DB REAL. `turno_de` nació suponiendo que **todas las llamadas de
# un turno comparten el último `user`** — cierto para un loop `modelo → tool → modelo`, y
# FALSO en cuanto el harness hace llamadas auxiliares. Medido el 2026-08-23 en Diseño, con
# la identidad ya recuperada: **3 turnos humanos dejaron 23 filas**. Ninguna era el turno:
#
#     «## Current prompt … Return JSON now.»          ← el extractor de preferencias
#     «Summarize this design prompt as a short title» ← el bautizador del diseño
#     «## Existing Workspace MEMORY.md …»             ← el escritor de memoria
#     «## Existing Brief …»                           ← el escritor del brief
#     «<function=skill>{"name":"responsive-layout"}»  ← un marcador crudo del CLI
#
# LA CAUSA ES GENERAL —el borde anota TODA llamada como si fuera un turno— así que el
# arreglo va en dos capas, y ninguna de las dos puede dejar mudo a un stack que hoy habla:
#
#   1 · EL FILTRO GENERAL · el turno es el LOOP DEL AGENTE, y el loop es el que lleva el
#       catálogo del stack. Una llamada sin catálogo es el harness pidiéndole un favor al
#       modelo, no el agente trabajando. Medido en Diseño: el loop manda 13 tools en cada
#       paso; las cinco auxiliares mandan 0.
#       ⚠️ FAIL-OPEN, y por eso hay estado: el filtro sólo se aplica **en los chats donde
#       ya se vio un catálogo**. Un stack que nunca manda tools —no puedo correr Educación
#       en este árbol para saberlo— se sigue anotando como hoy, byte por byte. Un filtro
#       que apagara un hilo por una suposición sería peor que el ruido que viene a sacar.
#
#   2 · LA MARCA DECLARADA · el filtro deja UNA llamada por turno, pero su `user` sigue
#       siendo la plantilla del harness con el pedido humano adentro. Dónde vive el pedido
#       dentro de esa plantilla es dato DEL STACK, así que **lo declara el registro** y el
#       código no lo adivina — es la regla de la casa («el guard no inventa; el catálogo
#       declara»). Sin declaración, el texto va entero, como hoy.
#
#: Los chats en los que ALGÚN paso ya mostró el catálogo del stack. Es lo que vuelve al
#: filtro fail-open: sin esta prueba no se filtra nada.
_CON_CATALOGO: set = set()


def marcar_catalogo(chat_id: Optional[str], tools: Any) -> None:
    """Anota que este chat ya mostró el catálogo de su stack. Idempotente y barato."""
    if chat_id and tools:
        _CON_CATALOGO.add(str(chat_id))


def es_el_loop_del_agente(chat_id: Optional[str], tools: Any) -> bool:
    """¿Este paso es el agente trabajando, o el harness pidiendo un favor?

    Sólo dice que NO cuando hay con qué compararlo: en un chat que ya mostró catálogo, un
    paso sin catálogo es andamiaje. En un chat que nunca lo mostró, todo cuenta —que es
    exactamente lo que pasa hoy.
    """
    if tools:
        return True
    return str(chat_id or "") not in _CON_CATALOGO


def lleva_la_marca(texto: str, decl: Optional[dict]) -> bool:
    """¿Este `user` es el que trae el pedido humano, según lo que el registro declara?

    Sin declaración no se puede distinguir y **todos pasan**: es la conducta de hoy.
    """
    desde = (decl or {}).get("desde")
    return True if not desde else (desde in (texto or ""))


def pedido_humano(texto: str, decl: Optional[dict]) -> str:
    """El pedido humano, sacado de la plantilla del harness POR LO QUE EL REGISTRO DICE.

    `desde` y `hasta` son literales declarados en la fila del stack, no una heurística: el
    día que el harness cambie su plantilla, esto deja de recortar y el texto va entero —
    degrada a lo de hoy, nunca a un recorte inventado. `hasta` es opcional; sin él se toma
    hasta el final.
    """
    txt = texto or ""
    desde = (decl or {}).get("desde")
    if not desde:
        return txt.strip()
    i = txt.find(desde)
    if i < 0:
        return txt.strip()
    cuerpo = txt[i + len(desde):]
    hasta = (decl or {}).get("hasta")
    if hasta:
        j = cuerpo.find(hasta)
        if j >= 0:
            cuerpo = cuerpo[:j]
    # Un recorte que se come el pedido entero NO se entrega: vale más la plantilla completa
    # que una fila vacía, que en la pantalla se lee como «el usuario no dijo nada».
    return cuerpo.strip() or txt.strip()


#: `chat → el último turno con pedido humano`. Los pasos que siguen —los que traen el
#: resultado de una tool y no un pedido nuevo— cuelgan su RESPUESTA de este turno.
_ABIERTO: dict = {}


def turno_del_paso(chat_id: Optional[str], messages: Any, *,
                   decl: Optional[dict] = None) -> tuple[Optional[tuple[str, str]], bool]:
    """`(turno, trae_pedido)` — a qué turno pertenece ESTE paso.

    LA MITAD QUE FALTABA Y QUE UN FILTRO SOLO SE LLEVA PUESTA. Con la marca declarada, los
    pasos posteriores del loop no la traen —el harness de Diseño mete el resultado de una
    tool como `user` («Attached image(s) from tool result:»)— y filtrarlos a secas dejaría
    el hilo con la pregunta y **sin la respuesta final**, que es peor que el ruido.

    Así que se separan las dos cosas: el PEDIDO se anota una sola vez, cuando llega el
    `user` marcado; la RESPUESTA de los pasos siguientes se actualiza en sitio sobre ese
    mismo turno, que es lo que el módulo ya prometía («hasta que gana la última»).
    """
    t = turno_de(messages, decl=decl)
    clave = str(chat_id or "")
    if t is not None:
        _ABIERTO[clave] = t
        return t, True
    return _ABIERTO.get(clave), False


def turno_de(messages: Any, *, decl: Optional[dict] = None) -> Optional[tuple[str, str]]:
    """`(turno_id, prompt)` del turno humano que este pedido atiende, o `None`.

    EL TURNO SE DERIVA DEL ÚLTIMO `user`, y hay que decir por qué en vez de dejarlo
    implícito: un harness llama al borde N veces por turno (modelo → tool → modelo), y
    ninguno de los tres stacks sin plugin manda `X-Aleph-Turn` ni `X-Aleph-Turno-Id`. Acá
    no hay señal de «empezó un turno nuevo». Lo que sí cambia entre un turno y el siguiente
    es el último mensaje `user` del historial.

    Con eso alcanza porque `chats_repo.append_message` ya es idempotente por
    `(chat, client_turn_id, rol)`: los N pedidos del MISMO turno traen el mismo último
    `user`, así que colapsan en una fila, y la respuesta del agente se **actualiza en
    sitio** hasta que gana la última — que es la final del turno.

    LA DEGRADACIÓN, DICHA: el id lleva también CUÁNTOS mensajes `user` hay, así que repetir
    literalmente el mismo prompt más adelante en la conversación da otro id. Lo único que
    sigue colapsando es repetir el mismo prompt con el MISMO historial — que es
    indistinguible de un reintento, y para un reintento colapsar es lo correcto. Un stack
    que no mandara historial degrada a «prompts iguales colapsan», nunca a anotar de más.
    """
    try:
        usuarios = [m for m in (messages or []) if _rol(m) == "user"]
    except Exception:                                # noqa: BLE001 — cuerpo ajeno
        return None
    if not usuarios:
        return None
    crudo = texto_de_mensaje(usuarios[-1]).strip()
    if not crudo:
        return None
    # LA MARCA, ANTES QUE NADA: un `user` que no la trae no es el turno de este stack.
    if not lleva_la_marca(crudo, decl):
        return None
    prompt = pedido_humano(crudo, decl)
    if not prompt:
        return None
    # ⚠️ LA SEMILLA VA CON EL PROMPT YA RECORTADO. Con el crudo, dos pasos del MISMO turno
    # cuya plantilla cambió una línea (el `Design Context Pack` cambia entre pasos) darían
    # ids distintos y el turno se anotaría dos veces. Lo estable es lo que el humano dijo.
    semilla = "%d\x1f%s" % (len(usuarios), prompt)
    return ("borde-" + hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:24], prompt)


def le_toca_al_borde(meta: Optional[dict]) -> bool:
    """¿A este workspace hay que anotarle el turno en el borde?

    Sí exactamente cuando NO tiene plugin. Y la guarda es el REGISTRO, no una lista de
    nombres escrita a mano: el día que un stack gane plugin deja de pasar por acá solo, sin
    que nadie se acuerde de venir a borrarlo de una lista.

    Por qué no se anota para los que SÍ tienen plugin: el plugin corre adentro del harness y
    ve el turno de verdad — sabe cuál fue el prompt y cuál la respuesta FINAL, después del
    último paso de tools. Acá eso hay que derivarlo. Cambiar un dato medido por uno inferido
    sería empeorar tres hilos para arreglar tres.
    """
    return bool(meta) and not meta.get("plugin")


def anotar_pedido(conn, *, chat_id: str, turno: tuple[str, str],
                  space_id: Optional[str] = None) -> None:
    """El pedido humano, ANTES de correr.

    Antes y no después, por la misma razón que `_chat_gate` de la Sala: si el turno se rompe
    a mitad, lo que el usuario dijo no se pierde. Nunca tumba el turno — el hilo es
    proyección, jamás camino crítico.
    """
    from app.phase1 import chats_repo
    try:
        chats_repo.append_message(conn, chat_id=chat_id, role="user", kind="obra",
                                  content=turno[1], space_id=space_id,
                                  client_turn_id=turno[0])
    except Exception as exc:                         # noqa: BLE001
        _log.error("hilo_ws_pedido_falló chat=%s turno=%s error=%s",
                   chat_id, turno[0], exc)


def anotar_respuesta(conn, *, chat_id: str, turno: tuple[str, str], texto: str,
                     space_id: Optional[str] = None) -> None:
    """La respuesta. Vacía = no se anota — y eso NO es un descuido.

    Un paso intermedio del harness devuelve `tool_calls` y texto vacío. Escribir esa fila
    pondría un turno en blanco en el hilo; no escribirla deja el `user` solo hasta que
    llegue el paso que sí trae texto, que se actualiza en sitio sobre el mismo
    `client_turn_id`. El estado intermedio queda siendo «pedido sin respuesta todavía»,
    que es verdad, en vez de «el agente contestó nada», que es mentira.
    """
    if not (texto or "").strip():
        return
    from app.phase1 import chats_repo
    try:
        chats_repo.append_message(conn, chat_id=chat_id, role="agent", kind="obra",
                                  content=texto, space_id=space_id,
                                  client_turn_id=turno[0])
    except Exception as exc:                         # noqa: BLE001
        _log.error("hilo_ws_respuesta_falló chat=%s turno=%s error=%s",
                   chat_id, turno[0], exc)


__all__ = ["texto_de_mensaje", "turno_de", "le_toca_al_borde",
           "anotar_pedido", "anotar_respuesta"]
