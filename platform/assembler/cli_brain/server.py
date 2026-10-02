#!/usr/bin/env python3
"""server.py — el server BYO-CLI :8926 (PUPPET_CLI_BRAIN_PORT), OpenAI-compat.

Hermano PRODUCTIZADO del shim :8923: UN server, DOS providers, ruteados por model-id
del request ('claude-code-cli' → Mi Claude Code · 'codex-cli' → Mi Codex). Diferencias
de primera clase vs el shim de eval:

  1. `model` de la respuesta = el modelo REAL que el CLI reportó (model_final honesto),
     no un eco del request. La fuente viaja en `aleph_cli_brain.model_final_source`.
  2. Errores CLASIFICADOS por provider (D4): ventana agotada → HTTP 429 con body
     {"error":{"type":"throttled","brain_provider","provider_name","reset_hint",...}};
     CLI caído/sin login → 503 "cli_unavailable"; timeout → 504; error de modelo/
     entitlement → 502 "model_error". Nunca un false green.
  3. GET /v1/brains/status — la detección D2 servida (cache TTL corto).
  4. POST /v1/turnos/detener {"turno_id"} — F2d: matar UN turno en vuelo, con respuesta
     tipada (turno_detenido | no_habia_turno) y deadline propio, así el endpoint SIEMPRE
     contesta. GET /v1/turnos lista lo que está en vuelo (id, provider, edad, pid).

Correr: `python3 platform/assembler/cli_brain/server.py`
Apuntar el backend: los aliases claude_cli/codex_cli de models.py ya miran
PUPPET_CLI_BRAIN_BASE_URL (default http://127.0.0.1:8926/v1).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import select
import socket
import sys
import threading
import time
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _tiene_kwarg(fn, nombre: str) -> bool:
    try:
        p = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if nombre in p:
        return True
    return any(v.kind is inspect.Parameter.VAR_KEYWORD for v in p.values())


@lru_cache(maxsize=64)
def _acepta_kwarg_por_firma(fn, nombre: str) -> bool:
    return _tiene_kwarg(fn, nombre)


def _acepta_kwarg(fn, nombre: str) -> bool:
    """¿Este `invoke` conoce el kwarg `nombre`? Si no, se lo llama sin él.

    COMPATIBILIDAD HACIA ATRÁS, por firma y no por try/except: un TypeError nacido DENTRO
    de invoke no debe hacernos llamar dos veces al CLI. `on_evento` es de F2a; `turno_id`
    es de F2d. Un provider viejo sigue funcionando: no adelanta y no se puede detener.
    """
    try:
        return _acepta_kwarg_por_firma(fn, nombre)
    except TypeError:               # un callable no hasheable: se resuelve sin caché
        return _tiene_kwarg(fn, nombre)


def _acepta_on_evento(fn) -> bool:
    """¿Este `invoke` conoce el streaming de F2a? Si no, se lo llama como siempre."""
    return _acepta_kwarg(fn, "on_evento")


def _grabar_usage(res, provider, medidos):
    """[medición · obra del «resto»] El usage REAL del CLI, apuntado al lado del cruce.

    Devuelve `cache_write_tokens` tal cual —para no cambiar una coma del annex— y de
    paso anota la fila. Se cuelga acá y no en un lugar propio porque **éste es el único
    punto donde existe `res.usage` con los campos de caché ya normalizados**
    (`base.usage_del_cli`); pedirlo más arriba sería medir otra cosa.

    Contesta la pregunta 4 de la obra —«¿el caché lo cubre?»— con un número en vez de
    una suposición: `cache_read_tokens` > 0 significa que el prefijo se reusó.
    Apagado sin `ALEPH_GRABAR_PROMPT`.
    """
    try:
        from grabador_prompt import grabar_usage as _gu
        _gu(provider.provider_id, res.usage, medidos)
    except Exception:
        pass
    return res.usage.get("cache_write_tokens")


# ══ EL REINTENTO YA NO SALE A CIEGAS ══════════════════════════════════════════════════
#
# EL DEFECTO, medido en Oficina el 2026-08-26. El guard de pureza descarta la generación
# entera cuando el CLI ejecutó algo por su cuenta (`base.py`, `exec_events > 0`). Después
# alguien reintenta —el cascade de `recipe_assembler`, o el propio harness, que ve un 502 y
# lo vuelve a mandar— y el reintento llega **con el mismo prompt, byte por byte**. Del log
# del cerebro, un turno real:
#
#     ✗ codex_cli (65,0 s)  falla_de_aleph: ejecutó 10 acción(es) por su cuenta
#     → codex_cli (7381 chars)      ← EL MISMO PROMPT OTRA VEZ
#     ✓ codex_cli (11,1 s)  final
#
# O sea que el modelo que acaba de romper el contrato **no se entera de que lo rompió**, y
# la segunda vuelta es una moneda al aire. Cuando sale cara, contesta bien; cuando sale
# cruz, racionaliza: «habilitá acceso de escritura y `@oai/artifact-tool`» — dos cosas que
# no existen (grep = 0 en todo el árbol) y que mandan a la persona a arreglar lo que no
# está roto.
#
# POR QUÉ LA MEMORIA VIVE ACÁ Y NO EN EL CASCADE. Porque **hay dos reintentadores y sólo
# uno es nuestro**. El cascade de Aleph podría agregar un mensaje; el harness que reintenta
# por su cuenta, no — es su loop, en su proceso, y tocarlo sería meterse en el oficio del
# stack. Este server es el único punto por el que pasan LOS DOS, así que es el único lugar
# donde la corrección llega siempre.
#
# LA LLAVE ES EL PROMPT MISMO, y por una razón exacta: el reintento es idéntico. No hace
# falta una clave de conversación (que puede no venir), ni el `turno_id` (que cambia entre
# intentos). Si el pedido cambió, no es el reintento de esto y la corrección NO se aplica:
# **fail-open**, porque avisarle a un turno limpio de un pecado que no cometió es peor que
# no avisar.
#
#: Cuánto vive una marca. Un reintento llega en segundos; pasado esto, lo que haya es otra
#: cosa y aplicarle la corrección sería hablarle de un turno que ya nadie recuerda.
_IMPUREZA_TTL_S = 300.0
#: Techo del mapa. Es memoria de proceso y se poda sola; existe para que un pico de turnos
#: descartados no la deje creciendo.
_IMPUREZA_MAX = 256
_IMPUREZA: dict = {}
_IMPUREZA_LOCK = threading.Lock()


def _huella_pedido(provider_id: str, prompt: str) -> str:
    """La identidad de un PEDIDO, no de un turno. Dos intentos del mismo pedido dan la
    misma huella; un pedido distinto da otra y no hereda nada."""
    h = hashlib.sha256()
    h.update((provider_id or "").encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update((prompt or "").encode("utf-8", "replace"))
    return h.hexdigest()


def _marcar_impureza(provider_id: str, prompt: str, acciones: int) -> None:
    """El guard descartó ESTE pedido. Que el próximo intento del mismo pedido lo sepa."""
    ahora = time.time()
    with _IMPUREZA_LOCK:
        # La poda va antes de insertar: así el techo se respeta aunque nadie más entre.
        for k, v in list(_IMPUREZA.items()):
            if ahora - v.get("ts", 0) > _IMPUREZA_TTL_S:
                _IMPUREZA.pop(k, None)
        if len(_IMPUREZA) >= _IMPUREZA_MAX:
            _IMPUREZA.pop(min(_IMPUREZA, key=lambda k: _IMPUREZA[k].get("ts", 0)), None)
        _IMPUREZA[_huella_pedido(provider_id, prompt)] = {"ts": ahora,
                                                          "acciones": int(acciones or 0)}


def _preludio_de_impureza(provider_id: str, prompt: str) -> str:
    """La corrección para el próximo intento de un pedido que el guard ya descartó.

    **Se CONSUME** (`pop`): la corrección es para el intento siguiente, no para todos los
    que vengan. Si ese intento también se descarta, el guard vuelve a marcar y la próxima
    corrección sale de ese descarte — que es el número honesto, no uno acumulado."""
    with _IMPUREZA_LOCK:
        marca = _IMPUREZA.pop(_huella_pedido(provider_id, prompt), None)
    if not marca or time.time() - marca.get("ts", 0) > _IMPUREZA_TTL_S:
        return ""
    n = marca.get("acciones") or 0
    cuantas = f"{n} acción(es)" if n else "acciones"
    return (
        "⚠️ ESTE PEDIDO YA SE INTENTÓ UNA VEZ Y SE PERDIÓ ENTERO.\n"
        f"En el intento anterior ejecutaste {cuantas} por tu cuenta en vez de pedirlas con "
        "el marcador, así que el sistema descartó TODA la respuesta —también lo que "
        "habías razonado bien— y estamos otra vez en el mismo punto.\n"
        "No es un castigo ni un permiso que te falte: es que en este paso tú no ejecutas. "
        "Las herramientas de la lista de abajo las corre EL SISTEMA. Tu trabajo es elegir "
        "UNA y escribirla como `<function=NOMBRE>{...}</function>`.\n"
        "Y no inventes lo que te falta: si algo no está, nómbralo con el nombre exacto de "
        "esa lista.\n"
    )


def _grabado(rendido: tuple, incremental: bool, mensajes, tools, tool_choice) -> tuple:
    """[medición · obra A] La toma `render`: el prompt FINAL y si salió completo.

    Es el ÚNICO lugar donde existe el texto exacto que va al CLI, y el único que sabe
    si el historial se re-mandó entero o se mandó sólo la cola. Devuelve la misma tupla
    que devolvía la línea que reemplaza, más las imágenes: sin la variable de entorno no
    hace nada.

    ⚠️ Lo que se GRABA es el prompt, no las imágenes. La toma es para medir tokens y
    ahorro de contexto; volcar el base64 de una captura de 128 KB al archivo de medición
    sería, otra vez, la imagen viajando como texto — sólo que a otro destino.
    """
    prompt, imagenes = rendido
    try:
        from grabador_prompt import grabar_cruce as _gp
        _gp("render", "_cli_brain", mensajes, tools, tool_choice, paso="armar_prompt",
            prompt=prompt, incremental=incremental)
    except Exception:
        pass
    return prompt, incremental, imagenes


def _armar_prompt(sesion, mensajes: list, tools: list, tool_choice=None) -> tuple:
    """(prompt, ¿es incremental?, imágenes). El único lugar donde se decide qué re-mandar.

    Las imágenes salen DEL MISMO recorrido que el prompt y por eso vuelven de acá: en el
    camino incremental sólo se adjuntan las de la COLA (las viejas ya las tiene el CLI por
    `--resume`), y en el completo, todas. Devolverlas desde otro lado obligaría a repetir
    esa decisión, que es justo la que este módulo existe para tomar una sola vez.

    Incremental sólo si hay sesión viva Y quedó algo nuevo. Si `enviados` quedó adelantado
    respecto de lo que llegó —el cliente recortó su historial, o rebobinó— no hay cola que
    mandar: ahí se manda TODO y se arranca sesión nueva, porque continuar una conversación
    con un historial que ya no coincide es responder sobre algo que el usuario borró.
    """
    if sesion is None or sesion.fresca:
        return _grabado(render_con_imagenes(mensajes, tools, tool_choice), False,
                        mensajes, tools, tool_choice)
    # ── [Gate 3 · D9] EL TURNO DEL REENCUENTRO ────────────────────────────────────
    # La sesión salió del mapa en disco: el CLI TIENE la charla, pero `enviados` era un
    # dato del proceso que murió. Adivinarlo es lo mismo que rebobinar mal —«responder
    # sobre algo que el usuario borró»— así que se manda el historial COMPLETO, que es
    # exactamente lo que cuesta hoy un reinicio. Va por el renderer incremental porque
    # el argv dice `--resume`: «SIGUE LA CONVERSACIÓN» es lo que está pasando, y los
    # `system` viajan igual como `[Instrucción]`, así que no se pierde nada.
    #
    # Y se reporta `incremental=False`, que es la verdad: no se ahorró un solo mensaje.
    # El annex es la auditoría del ahorro; un `True` que no ahorró la vuelve decoración.
    if sesion.restaurada and sesion.enviados == 0:
        return _grabado(render_incremental_con_imagenes(mensajes, tools, tool_choice),
                        False, mensajes, tools, tool_choice)
    # ── LA COLA SE MANDA SÓLO SI EL PRINCIPIO SIGUE SIENDO EL MISMO ──────────────
    # Comparar LARGOS no alcanza, y está medido: en una conversación real de Diseño de 4
    # turnos, de 14 roturas de prefijo la guarda por largo atrapa 5 y **se le escapan 9**.
    # El `context-prune` del stack reescribe mensajes viejos —los cambia por stubs
    # `[tool result dropped …]`— y el historial CRECE igual, así que el largo dice «todo
    # bien» mientras el contenido ya es otro. Mandar la cola ahí es continuar, sobre el
    # historial que el CLI tiene, una conversación que el stack ya reescribió.
    if not _ses.prefijo_vivo(sesion, mensajes):
        sesion.renovar_id()
        return _grabado(render_con_imagenes(mensajes, tools, tool_choice), False,
                        mensajes, tools, tool_choice)
    nuevos = mensajes[sesion.enviados:]
    if not nuevos:
        sesion.renovar_id()
        return _grabado(render_con_imagenes(mensajes, tools, tool_choice), False,
                        mensajes, tools, tool_choice)
    return _grabado(render_incremental_con_imagenes(nuevos, tools, tool_choice), True,
                    nuevos, tools, tool_choice)


def _perder_sesion(sesion, clave: str, causa, detalle: str):
    """[Gate 3 · D9] Un id que el CLI ya NO tiene. Dos efectos, y son distintos a propósito.

    1. **El mapa se limpia SIEMPRE.** El id acaba de morir; si se quedara en el archivo,
       cada arranque lo restauraría y volvería a perderlo — un spawn tirado por reinicio,
       para siempre. Vale para la sesión restaurada y para la que nació en este proceso:
       en las dos, lo que hay escrito en disco quedó viejo en este instante.
    2. **La causa se emite SÓLO si la sesión venía del mapa, y una sola vez.** Perder una
       sesión a mitad de la vida ya tenía su reporte desde F2e (el log y `rehecha` del
       annex) y no es lo que D9 vino a cerrar; lo que no tenía voz es «restauré algo que
       ya no existía», que es esta causa. `sesion_perdida` es del vocabulario SELLADO en
       F1c: acá no nace ninguna causa nueva.
    """
    _ses.SESIONES.olvidar(clave)
    if not sesion.restaurada or sesion.perdida_reportada:
        return causa
    sesion.perdida_reportada = True
    print("[cli_brain] ⟲ causa=sesion_perdida (venía del mapa); la entrada de esa clave "
          "se borró", file=_log, flush=True)
    return _ses.causa_de_resume(sesion.id, detalle) or causa


if __package__ in (None, ""):  # ejecutado como script suelto — misma convención que el
    # backend (executor.py añade platform/assembler a sys.path e importa flat)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from cli_brain.base import (ERR_ACCESS_DENIED, ERR_AUTH_EXPIRED, ERR_AUTH_UNKNOWN,
                                ERR_CONFIG_INVALID, ERR_DETENIDO, ERR_MODEL,
                                ERR_MODEL_UNAVAILABLE, ERR_NO_AUTH, ERR_NOT_INSTALLED,
                                ERR_PROVIDER, ERR_RATE_LIMIT, ERR_SERVICE_UNAVAILABLE,
                                ERR_SESION_PERDIDA, ERR_TIMEOUT)
    from cli_brain import base as _base
    from cli_brain.detect import detect_all as _detect_all, detect_one as _detect_one, detect_statuses as _detect_status, get_provider
    from cli_brain import credencial as _credencial
    from cli_brain.prompt_bridge import (FiltroVivo, extract_tool_calls,
                                         marcador_ilegible, texto_visible,
                                         nombre_exigido, obliga_a_tool, render_prompt,
                                         render_con_imagenes,
                                         render_incremental_con_imagenes,
                                         render_prompt_incremental)
    from cli_brain.tool_inventory_dedup import colapsar_inventario_textual
    from cli_brain import sesiones as _ses
    from cli_brain import slots as _slots
    from cli_brain.registry import public_catalog, response_model_ids, served_label
else:
    from .base import (ERR_ACCESS_DENIED, ERR_AUTH_EXPIRED, ERR_AUTH_UNKNOWN,
                       ERR_CONFIG_INVALID, ERR_DETENIDO, ERR_MODEL,
                       ERR_MODEL_UNAVAILABLE, ERR_NO_AUTH, ERR_NOT_INSTALLED,
                       ERR_PROVIDER, ERR_RATE_LIMIT, ERR_SERVICE_UNAVAILABLE,
                       ERR_SESION_PERDIDA, ERR_TIMEOUT)
    from . import base as _base
    from .detect import detect_all as _detect_all, detect_one as _detect_one, detect_statuses as _detect_status, get_provider
    from . import credencial as _credencial
    from .prompt_bridge import (FiltroVivo, extract_tool_calls, marcador_ilegible,
                                texto_visible, nombre_exigido,
                                obliga_a_tool, render_prompt, render_con_imagenes,
                                render_incremental_con_imagenes,
                                render_prompt_incremental)
    from .tool_inventory_dedup import colapsar_inventario_textual
    from . import sesiones as _ses
    from . import slots as _slots
    from .registry import public_catalog, response_model_ids, served_label

PORT = int(os.environ.get("PUPPET_CLI_BRAIN_PORT", "8926"))

#: Cada cuánto se mira si el consumidor sigue del otro lado. Es la ÚNICA forma de
#: enterarse de que se fue: un turno de CLI no emite nada hasta el final, así que no hay
#: escritura que pueda fallar. El intervalo acota la fuga — lo que se siga generando
#: después del corte no puede pasar de esto más lo que tarde el CLI en morir.
_VIGILIA_S = 1.0

_log = sys.stderr

_HTTP_BY_KIND = {
    ERR_ACCESS_DENIED: (403, "provider_access_denied"),
    ERR_AUTH_EXPIRED: (401, "auth_expired"),
    ERR_AUTH_UNKNOWN: (503, "auth_unknown"),
    ERR_PROVIDER: (502, "provider_error"),
    ERR_SERVICE_UNAVAILABLE: (503, "provider_service_unavailable"),
    ERR_MODEL_UNAVAILABLE: (422, "provider_model_unavailable"),
    ERR_RATE_LIMIT: (429, "throttled"),
    ERR_NO_AUTH: (503, "cli_unavailable"),
    ERR_NOT_INSTALLED: (503, "cli_unavailable"),
    ERR_CONFIG_INVALID: (409, "cli_config_invalid"),
    ERR_TIMEOUT: (504, "cli_timeout"),
    # F2d · el turno lo paró alguien. NO es 502: el modelo no rechazó nada y el proveedor
    # no falló. 409 «conflicto con el estado actual del recurso» es lo más honesto que
    # ofrece HTTP para «esto ya no corre porque se pidió que dejara de correr», y el
    # `type` tipado (`turno_detenido`) es el que de verdad lleva el significado.
    ERR_DETENIDO: (409, "turno_detenido"),
    # F2e · el CLI ya no tiene la conversación. En el camino normal esto NO sale por
    # HTTP: el server rehace el turno con contexto completo y el usuario no se entera.
    # Si llega hasta acá es porque rehacerlo TAMBIÉN falló, y entonces hay que decirlo.
    ERR_SESION_PERDIDA: (409, "sesion_perdida"),
    # ERR_MODEL y cualquier otro → 502 model_error
}


# ── ANTI-CSRF DRIVE-BY (review MED #1) ───────────────────────────────────────────
# El server bindea 127.0.0.1, PERO un navegador en una página maliciosa puede POSTear
# fire-and-forget a http://127.0.0.1:8926/... (simple request, sin preflight) y quemar la
# ventana de la SUSCRIPCIÓN del usuario. Defensa: (1) Host header ∈ {127.0.0.1,localhost}:PORT
# — bloquea DNS-rebinding; (2) RECHAZAR si viene un header Origin (un cliente local legítimo
# —el assembler— NO manda Origin; solo un browser cross-site lo agrega). Clase Ollama/LM-Studio.
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ══ SSE REAL (Gate 2 · F2a) ═══════════════════════════════════════════════════
    # ANTES: el CLI era bloqueante, así que esto FABRICABA un stream — un solo chunk con
    # la respuesta ya completa, con Content-Length, después de 60-100 s de silencio.
    # AHORA: los eventos se reenvían SEGÚN LLEGAN. El formato hacia el consumidor es el
    # MISMO (`chat.completion.chunk` con `delta`, cerrado por `[DONE]`); lo que cambia es
    # CUÁNDO llegan. Sin Content-Length y con flush por chunk, porque ahora sí hay stream.
    #
    # LOS HEADERS SE ESCRIBEN TARDE, a propósito: hasta el primer delta todavía se puede
    # responder un HTTP 429/503/504 como hasta hoy. Si el turno falla ANTES de emitir nada
    # —que es el único fallo que existía— el cliente ve exactamente la misma respuesta de
    # error de siempre. Sólo si ya salió texto se reporta por el canal (caso nuevo, porque
    # hasta ahora era imposible fallar a mitad: no había mitad).

    def _sse_abrir(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")   # ningún proxy nos vuelve a bufferear
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, chunk: dict) -> None:
        self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
        self.wfile.flush()

    @staticmethod
    def _chunk(cid, created, model, delta: dict, *, finish=None, annex=None,
               usage=None) -> dict:
        c = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if annex is not None:
            c["aleph_cli_brain"] = annex
        # EL `usage` TAMBIÉN VIAJA POR EL STREAM. Iba sólo en la respuesta no-streaming, y
        # mientras el stream fue un camino de excepción no se notó; desde que es el DEFAULT
        # (obra 4) la casa se quedó ciega en el camino principal — medido: `prompt` y
        # `completion` en `None` en 6 de 6 turnos por el borde. Va en el chunk de cierre,
        # que es donde lo pone el contrato de OpenAI.
        if usage is not None:
            c["usage"] = usage
        return c

    def _send_stream(self, obj):
        """Cola de compatibilidad: emite un objeto YA COMPLETO como SSE.

        Se conserva para el provider que todavía no streamea (codex) y para el caso en que
        el turno terminó sin haber emitido un solo delta. Idéntico a lo de antes salvo que
        ya no manda Content-Length (el canal es un stream de verdad).
        """
        choice = (obj.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        delta = {"role": "assistant"}
        if message.get("content") is not None:
            delta["content"] = message.get("content")
        if message.get("tool_calls"):
            delta["tool_calls"] = message["tool_calls"]
        self._sse_abrir()
        self._sse(self._chunk(obj.get("id"), obj.get("created"), obj.get("model"), delta,
                              finish=choice.get("finish_reason"),
                              annex=obj.get("aleph_cli_brain"),
                              usage=obj.get("usage")))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _local_only(self) -> bool:
        """True si la request es de un cliente local legítimo (no un drive-by de browser)."""
        host = (self.headers.get("Host") or "").strip().lower()
        # El puerto sale del server real (tests usan efímero; desktop usa 8926). No se
        # confía en Host para escoger destino: solo se valida contra loopback+ese puerto.
        port = int(getattr(self.server, "server_port", PORT))
        allowed_hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}",
                                   f"[::1]:{port}", "127.0.0.1", "localhost"})
        if host and host not in allowed_hosts:
            return False
        # un browser cross-site agrega Origin; el assembler local NO → si hay Origin, es sospechoso
        if self.headers.get("Origin"):
            return False
        return True

    def _autorizado(self) -> bool:
        """La llave de instancia. `_local_only` para al NAVEGADOR; esto para a un PROCESO.

        Las dos hacen falta y ninguna reemplaza a la otra: el guard de arriba se apoya en
        que un browser manda `Origin` y un cliente local no, así que un script del usuario
        —o algo que se coló— pasa por el medio sin tocar nada. `recipe_assembler.py:2904`
        ya nombraba esta amenaza («evita que otro proceso local que bindee el puerto la
        capture»); esto es el otro lado, que el puerto sepa quién le habla.

        Sin llave configurada devuelve True — ver la cabecera de `credencial.py`: falla
        abierta a propósito para no romper los servers sueltos de las varas.
        """
        llave = str(getattr(self.server, "llave_instancia", "") or "")
        return _credencial.coincide(self.headers.get("Authorization"), llave)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/health" or path == "":
            return self._send(200, {"ok": True, "service": "cli_brain", "port": PORT})
        if not self._local_only():
            return self._send(403, {"error": {"message": "solo clientes locales", "type": "forbidden"}})
        if path.endswith("/models"):
            return self._send(200, {"object": "list", "data": [
                {"id": i} for i in response_model_ids()
            ], "catalog": public_catalog()})
        if path.endswith("/brains/status") or path == "/status":
            # público: SIN path del binario (fingerprinting) — solo estado + installed bool
            providers = _detect_all(public=True)
            for provider_id, status in providers.items():
                auth_ready = (status.get("state") == _base.STATE_READY and
                              status.get("auth_state") == "authenticated")
                runtime = _slots.SLOTS.estado_provider(
                    provider_id, authenticated_ready=auth_ready)
                # The in-memory server state is authoritative for an active cooldown.
                # Persisted evidence remains historical and never implies live quota.
                if runtime.get("last_provider_event") is None:
                    runtime["last_provider_event"] = status.get("last_provider_rate_limit")
                if runtime.get("last_execution_state") == "not_verified":
                    runtime["last_execution_state"] = status.get(
                        "last_execution_state", "not_verified")
                status["runtime"] = runtime
                status["quota_availability"] = "unknown"
                status["authenticated_ready"] = auth_ready
            return self._send(200, {"providers": providers,
                "catalog": public_catalog()})
        if path.endswith("/broker"):
            # EL PARTE DEL BROKER: cuántos turnos atendió por CLI y cuántos cayeron al
            # respaldo, con el MOTIVO de cada caída. Sin esto, «¿se está usando?» y «¿por
            # qué se cayó?» sólo se podían contestar leyendo stderr — y cinco de las
            # caídas eran mudas. Local-only como el resto: sin prompts ni argv.
            try:
                from .broker.capa import caidas, encendido as _br_on
                from .broker.pool import POOL as _POOL
                return self._send(200, {"encendido": _br_on(),
                                        "por_cli": caidas(),
                                        "pool": _POOL.estado()})
            except Exception as e:                          # noqa: BLE001
                return self._send(200, {"error": f"{type(e).__name__}: {e}"})
        if path.endswith("/turnos"):
            # F2d · quién está en vuelo AHORA. Sin prompts, sin argv: id, provider, edad y
            # pid. Es lo que hace falta para poder detener algo y para poder auditarlo.
            return self._send(200, {"turnos": [t.como_dict() for t in _base.turnos_vivos()]})
        self._send(404, {"error": "not found"})

    # ══ F2d · DETENER UN TURNO ════════════════════════════════════════════════════
    def _detener(self):
        """`POST /v1/turnos/detener {"turno_id": "..."}` → respuesta TIPADA.

        Los dos resultados son del vocabulario cerrado de `base`: `turno_detenido` (el
        proceso está muerto, o el deadline venció y se dice) y `no_habia_turno` (no es un
        error: es lo normal cuando el usuario aprieta el botón justo cuando la respuesta
        llegaba). Nunca cuelga: `stop_turn` tiene deadline propio.
        """
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            req = json.loads(self.rfile.read(n).decode()) if n else {}
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            return self._send(400, {"error": {"message": f"bad request: {e}"}})
        if not isinstance(req, dict):
            return self._send(400, {"error": {"message": "bad request: se esperaba un objeto"}})
        tid = str(req.get("turno_id") or req.get("id") or "")
        if not tid:
            return self._send(400, {"error": {"message": "falta `turno_id`",
                                              "type": "bad_request"}})
        r = _base.stop_turn(tid)
        print(f"[cli_brain] ⏹ stop {tid} → {r.get('resultado')} "
              f"(señal={r.get('senal')} vivo={r.get('vivo')} {r.get('esperado_s')}s)",
              file=_log, flush=True)
        # 200 en los dos casos: el `stop` HIZO lo que se le pidió. Que no hubiera turno no
        # es un fallo del pedido — es información, y viaja en `resultado`.
        return self._send(200, r)

    def do_POST(self):
        # El reloj nace al entrar por HTTP, antes de auth, parseo, prompt y cola. Si el
        # cliente trae el deadline estable del intento, se respeta el menor entre ése y
        # nuestro techo local: un llamante puede acortar presupuesto, nunca estirarlo.
        _http_enter_mono = time.monotonic()
        _ruta = self.path.split("?", 1)[0].rstrip("/")
        if _ruta.endswith("/turnos/detener"):
            if not self._local_only():
                return self._send(403, {"error": {"message": "solo clientes locales (anti-CSRF)",
                                                  "type": "forbidden"}})
            if not self._autorizado():
                return self._send(401, {"error": {"message": "llave de instancia inválida o ausente",
                                                  "type": "cli_brain_no_autorizado"}})
            return self._detener()
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        if not self._local_only():
            return self._send(403, {"error": {"message": "solo clientes locales (anti-CSRF)",
                                              "type": "forbidden"}})
        if not self._autorizado():
            return self._send(401, {"error": {"message": "llave de instancia inválida o ausente",
                                              "type": "cli_brain_no_autorizado"}})
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n).decode())
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            return self._send(400, {"error": {"message": f"bad request: {e}"}})

        model_id = str(req.get("model") or "")
        provider = get_provider(model_id)
        if provider is None:
            served = " | ".join(response_model_ids())
            return self._send(404, {"error": {"message": f"modelo desconocido: {model_id}. "
                                                         f"Este server sirve {served}"}})
        _provider_resolved_s = round(time.monotonic() - _http_enter_mono, 3)
        def _preinvoke_timing(layer: str) -> dict:
            return {"request_received_s": 0.0,
                    "provider_resolved_s": _provider_resolved_s,
                    "completion_s": round(time.monotonic() - _http_enter_mono, 3),
                    "process_started_s": None, "first_output_s": None,
                    "timeout_layer": layer}

        _deadline_mono = _http_enter_mono + _base.DEFAULT_TIMEOUT
        _deadline_raw = (
            self.headers.get("X-Aleph-Deadline-Epoch")
            or req.get("deadline_epoch")
        )
        if _deadline_raw not in (None, ""):
            try:
                _deadline_epoch = float(_deadline_raw)
                if not math.isfinite(_deadline_epoch):
                    raise ValueError("deadline no finito")
                _desde_upstream = _http_enter_mono + max(
                    0.0, _deadline_epoch - time.time()
                )
                _deadline_mono = min(_deadline_mono, _desde_upstream)
            except (TypeError, ValueError, OverflowError):
                return self._send(400, {"error": {
                    "message": "deadline inválido",
                    "type": "bad_request",
                }})

        # ANNEX · SUB-MODELO POR PROVIDER (BYO-CLI): el sub-modelo DENTRO del provider viaja en
        # `cli_model` (distinto de `model`, que ya se consumió arriba para ELEGIR el provider
        # claude-code-cli | codex-cli). Vacío → default del provider (env). El flag del CLI
        # (`claude -p --model X` / `codex -m X`) ya lo honra downstream (base.invoke→build_argv).
        # "Elegir es un pedido; model_final es el hecho": si el plan no soporta el sub-modelo, el
        # CLI da error CLASIFICADO (no falso verde), y `requested_model` deja la traza honesta.
        cli_model = (str(req.get("cli_model") or "").strip()) or None
        # TICKET 27·3 · DIAL DE ESFUERZO: el effort del turno viaja del assembler → acá → flag REAL del
        # CLI (--effort). Se REPORTA en la respuesta (forense verificable: qué effort corrió cada turno).
        _eff = (str(req.get("effort") or "").strip().lower()) or None
        _eff = _eff if _eff in ("low", "medium", "high", "max") else None
        # ── F2e · LA SESIÓN ───────────────────────────────────────────────────────
        # `sesion` en el body es la CLAVE DE LA CONVERSACIÓN, y la elige quien sabe qué es
        # una conversación: el assembler. Sin clave no hay sesión y todo queda como antes —
        # no se adivina cuál es la charla a partir de los mensajes, porque adivinar mal
        # significa contestar con el contexto de otro.
        _msgs = req.get("messages", []) or []
        _tools = req.get("tools", []) or []
        _dedup_habilitado = os.environ.get(
            "PUPPET_COLLAPSE_TOOL_INVENTORY", "1"
        ) not in ("0", "false", "False", "")
        if _dedup_habilitado:
            _msgs, _inventario_colapsado, _inventario_chars = colapsar_inventario_textual(
                _msgs, _tools
            )
        else:
            _inventario_colapsado, _inventario_chars = False, 0
        if _inventario_colapsado:
            print(
                f"[cli_brain] inventario textual duplicado colapsado "
                f"({_inventario_chars} chars; {len(_tools)} schemas intactos)",
                file=_log,
                flush=True,
            )
        # [B0-2 · CLI] El CLI no tiene `tool_choice` nativo —no hay canal estructurado, las
        # tools viajan como texto en el prompt— así que la obligación se DICE ahí y se
        # COMPRUEBA en la salida, más abajo. Ausente = como siempre.
        _tool_choice = req.get("tool_choice")
        _clave = str(req.get("sesion") or req.get("session") or "").strip()
        # ⚠️ Y LA CLAVE NO ALCANZA: EL CLI TIENE QUE PODER CONTINUAR. La decisión es de
        # ACÁ y no del borde, porque el borde no sabe qué CLI va a atender el turno —
        # lo elige la receta, más abajo. Con un CLI cuyo resume no está probado, honrar la
        # clave no ahorra: hace fallar el turno y lo reintenta con el contexto completo,
        # o sea DOS invocaciones en el mismo pedido. Medido con Grok. Ver `RESUME_PROBADO`.
        # LA CLAVE DE CONVERSACIÓN, ENTERA, ANTES DE GATEARLA. El broker (paso 3) la
        # necesita aunque el `--resume` de este CLI no esté probado: **son dos mecanismos
        # distintos**. `RESUME_PROBADO` habla del flag del CLI, que reabre una charla que
        # vive en el store DEL CLI; la conversación del broker vive DENTRO de un proceso
        # que no se murió, y no pasa por ese flag ni por ese store. Vaciar la clave para
        # los dos era dejar al broker sin identidad de charla y sin dueño — o sea apagado
        # para grok y codex, que son justo los dos que más ganan.
        _clave_conversacion = _clave
        if _clave and not _ses.resume_probado(provider.provider_id):
            print(f"[cli_brain] · {provider.provider_id} no tiene el resume probado; "
                  f"este turno va completo (la clave se ignora)", file=_log, flush=True)
            _clave = ""
        sesion = _ses.SESIONES.obtener(_clave, provider.provider_id) if _clave else None
        # ── D9 · la causa de que una sesión RESTAURADA no sirviera ────────────────
        # Vive en el annex de este turno, una sola vez. `None` en todos los demás.
        _causa_sesion = None
        # Se CAPTURA acá porque la bandera se apaga en cuanto el turno sale bien (y
        # también si hay que rehacer la sesión); el annex tiene que poder decir que ESTE
        # turno fue el del reencuentro, no el estado en que quedó después.
        _restaurada = bool(sesion.restaurada) if sesion is not None else False
        # Antes de resumir: ¿el CLI TODAVÍA tiene esa conversación? Es un `isfile`, y
        # ahorra descubrirlo por un spawn que va a fallar (medido: rc=1, stdout vacío).
        #
        # [Gate 3 · D9] Este mismo `isfile` es ahora el ÚNICO validador de lo que se
        # restauró del mapa en disco. Por eso el arranque no valida nada: acá se decide,
        # con la sesión ya pedida y sin una llamada de más.
        if sesion is not None and not sesion.fresca and not _ses.existe_sesion(
                sesion.id, sesion.workdir):
            print(f"[cli_brain] ⟲ la sesión {sesion.id} ya no está en el store; se rehace",
                  file=_log, flush=True)
            _causa_sesion = _perder_sesion(sesion, _clave, _causa_sesion,
                                           "el mapa restaurado apuntaba a una "
                                           "conversación que el CLI ya no tiene")
            sesion.renovar_id()
        prompt, _incremental, _imagenes = _armar_prompt(sesion, _msgs, _tools, _tool_choice)
        # ── LA CORRECCIÓN DEL INTENTO ANTERIOR, SI LO HUBO ───────────────────────────
        # Va DESPUÉS del render y no adentro, porque la llave del mapa ES el prompt
        # renderizado: hasta acá no existe con qué preguntar. Consecuencia declarada: el
        # grabador de `_grabado` anota el render BASE, sin preludio — es lo correcto, mide
        # el renderizador; el preludio se ve en la línea de abajo y en `annex.preludio`.
        _preludio = _preludio_de_impureza(provider.provider_id, prompt)
        if _preludio:
            prompt = _preludio + "\n" + prompt
        print(f"[cli_brain] → {provider.provider_id} ({len(prompt)} chars"
              + (f" · {len(_imagenes)} imagen(es)" if _imagenes else "") + ")"
              + (" +corrección-de-pureza" if _preludio else "")
              + (f" model={cli_model}" if cli_model else "")
              + (f" effort={_eff}" if _eff else "")
              + (f" sesion={sesion.id[:8]}·t{sesion.turnos}"
                 f"{'·incremental' if _incremental else '·completa'}" if sesion else ""),
              file=_log, flush=True)
        # ── F2a · el reenvío en vivo ──────────────────────────────────────────────
        # Los headers se abren con el PRIMER delta, no antes: mientras no salió nada, el
        # camino de error sigue siendo un HTTP con su status, byte-idéntico al de siempre.
        quiere_stream = bool(req.get("stream"))
        _cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        _turno_pedido = str(
            req.get("turno_id")
            or self.headers.get("X-Aleph-Turno-Id")
            or _cid
        ).strip() or _cid
        _created = int(time.time())
        # Un filtro POR TURNO: guarda la cola ambigua entre pedazo y pedazo, así que
        # compartirlo entre generaciones se llevaría restos de una a la siguiente.
        _filtro_vivo = FiltroVivo()
        _vivo = {"abierto": False, "deltas": 0, "pensados": 0,
                 "modelo": provider.response_model_id, "turno_id": ""}

        def _abrir_una_vez():
            """Abre el SSE y emite el chunk de apertura. Idempotente.

            ⚠️ EXISTE PORQUE F4b LO NECESITÓ Y POR POCO ROMPE F2d. La apertura vivía dentro
            del camino de `texto`, y ahí también viaja el `turno_id` del annex — «lo que le
            permite a quien consume el stream apretar detener». Cuando el `pensando` empezó
            a emitir (obra 5), pasó a poder abrir el stream PRIMERO… y ese primer chunk se
            habría ido sin el `turno_id`, dejando el botón de parar sin nada que parar.
            Con un solo lugar que abre, el annex sale sí o sí, venga el thinking o el texto.
            """
            if _vivo["abierto"]:
                return
            self._sse_abrir()
            # F2d · el `turno_id` viaja en el PRIMER chunk, sea cual sea su canal.
            self._sse(self._chunk(_cid, _created, _vivo["modelo"], {"role": "assistant"},
                                  annex={"turno_id": _vivo["turno_id"]}))
            _vivo["abierto"] = True

        def _abandonar(motivo: str) -> None:
            """El consumidor se fue: se PARA el turno en vez de seguir generando.

            ── POR QUÉ ESTO NO PUEDE SER UN `pass` ──────────────────────────────────────
            Acá abajo ya se detectaba el corte (`BrokenPipeError`) y se lo tragaba con un
            «no debe romper la lectura». Romper la lectura no, pero seguir generando
            tampoco: MEDIDO el 2026-08-12, cortando el cliente a los 44,3 s el `claude`
            siguió vivo hasta los 84,0 s — **40 segundos de la ventana de la suscripción
            gastados en una respuesta que ya nadie iba a leer**. Es exactamente lo que el
            barrido de arranque dice de los huérfanos: «sigue quemando la ventana por una
            respuesta que ya nadie va a recibir».

            Se reusa `stop_turn`, el MISMO freno del botón de parar: no se inventa un
            segundo camino para matar un turno. Una sola vez por turno — el pipe roto se
            vuelve a detectar en cada delta que se intente escribir.
            """
            if _vivo.get("abandonado"):
                return
            _vivo["abandonado"] = True
            try:
                r = _base.stop_turn(_tid)
                print(f"[cli_brain] ⏹ el consumidor se fue ({motivo}); se para el turno "
                      f"{_tid} → {r.get('resultado')}", file=_log, flush=True)
            except Exception:                          # noqa: BLE001 — cerrar jamás rompe
                print(f"[cli_brain] ⏹ el consumidor se fue ({motivo}); no se pudo parar "
                      f"el turno {_tid}", file=_log, flush=True)

        def _on_evento(clase, carga):
            # 'sistema' trae el modelo que el CLI declara al arrancar: sirve para no rotular
            # los chunks con el id del wrapper. El model_final AUTORITATIVO sigue saliendo
            # del `result` (modelUsage) y viaja en el chunk final — el anti-grift no cambia.
            if clase == "sistema" and isinstance(carga, dict):
                # F2b · EL AVISO DE LÍMITE, EN VIVO. El binario emite `rate_limit_event`
                # con `resetsAt` DURANTE el turno (medido en F2a). Si dice que ya no está
                # permitido, la cola deja de lanzar turnos de este provider hasta esa hora
                # — en vez de esperar a que el próximo rebote para enterarse.
                if carga.get("resetsAt") and str(carga.get("status", "")).lower() != "allowed":
                    _reset_at = carga.get("resetsAt")
                    try:
                        _retry_after = max(0.0, float(_reset_at) - time.time())
                    except (TypeError, ValueError):
                        _retry_after = None
                    _reason = str(carga.get("rateLimitType") or "rate_limit")
                    _event = _slots.SLOTS.registrar_rate_limit(
                        provider.provider_id, reset_at=_reset_at,
                        retry_after_s=_retry_after,
                        reset_hint=_slots._legible(_retry_after), motivo=_reason)
                    try:
                        if __package__ in (None, ""):
                            from cli_brain.evidence import record_provider_rate_limit
                        else:
                            from .evidence import record_provider_rate_limit
                        record_provider_rate_limit(
                            provider.provider_id, retry_after_s=_event.get("retry_after_s"),
                            reset_hint=_event.get("reset_hint", ""),
                            reset_at=_event.get("reset_at"), reason=_reason,
                            occurred_at=_event.get("occurred_at"))
                    except Exception as exc:
                        print(f"[cli_brain] no pude guardar el rate-limit de {provider.provider_id}: "
                              f"{type(exc).__name__}", file=_log, flush=True)
                    if _event.get("reset_at"):
                        print(f"[cli_brain] ⏸ {provider.provider_id} en pausa hasta "
                              f"{_event['reset_at']} ({_reason})",
                              file=_log, flush=True)
                if carga.get("model"):
                    _vivo["modelo"] = carga["model"]
                return
            if clase == "pensando":
                _vivo["pensados"] += 1
                # [F4b · obra 5] …Y AHORA SÍ SE EMITE. El comentario de acá decía «este
                # endpoint no tiene canal de thinking hoy», y era cierto cuando se escribió:
                # el canal existía río abajo (`stream_chat._stream_openai` ya lee
                # `delta.reasoning`, y la Sala ya pinta el panel) pero nadie lo llenaba por
                # esta vía. O sea que el razonamiento REAL del CLI —que F2a midió llegando
                # como `thinking_delta`— se contaba y se tiraba.
                #
                # Va como `delta.reasoning`, que es el campo que los razonadores de
                # Groq-directo ya usan: MISMO canal, cero formato nuevo. Un cliente que no
                # lo entienda lo ignora, así que el contrato OpenAI sigue intacto.
                #
                # CERO TEATRO: si el CLI no emite `thinking_delta`, acá no entra nada y el
                # panel del front no aparece. El thinking no se fabrica jamás.
                if quiere_stream and carga:
                    try:
                        _abrir_una_vez()
                        self._sse(self._chunk(_cid, _created, _vivo["modelo"],
                                              {"reasoning": carga}))
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        _abandonar("pipe roto al emitir razonamiento")
                return
            if clase != "texto" or not quiere_stream or not carga:
                return
            # El marcador es protocolo: la llamada ya sale estructurada en `tool_calls`.
            # Si además se emite como texto, la persona lee el andamio mientras se escribe.
            # Retener no es fallar: un pedazo puede no soltar nada todavía.
            visible = _filtro_vivo.empujar(carga)
            if not visible:
                return
            try:
                _abrir_una_vez()
                self._sse(self._chunk(_cid, _created, _vivo["modelo"], {"content": visible}))
                _vivo["deltas"] += 1
            except (BrokenPipeError, ConnectionResetError, OSError):
                # El consumidor cortó. No rompe la lectura —el turno termina ordenado— pero
                # SÍ para al CLI: seguir generando es quemarle la ventana al usuario.
                _abandonar("pipe roto al emitir texto")

        # COMPATIBILIDAD HACIA ATRÁS: `on_evento` es de F2a. Un provider que implemente el
        # contrato ANTERIOR (`invoke(prompt, model, timeout, effort)`) sigue funcionando —
        # simplemente no adelanta nada y el turno se emite entero al final, como hasta ayer.
        # Se decide por firma, no por try/except: un TypeError nacido DENTRO de invoke no
        # debe hacernos llamar dos veces al CLI.
        # ── F2b · EL TURNO SE PIDE ANTES DE SPAWNEAR ──────────────────────────────
        # Techo global + un turno por provider + pausa por ventana agotada. Si no hay,
        # el N+1 NO espera mudo ni revienta: se le contesta con la causa tipada y su
        # status, por el mismo mapa HTTP de siempre. Y jamás nace un segundo `claude -p`.
        #
        # [obra 2] Y ESPERA ANTES DE RECHAZAR. El techo propio se libera solo en segundos
        # —lo que hay del otro lado es OTRA llamada del mismo turno—, así que rebotar en el
        # acto mandaba al cascade a buscarle otro modelo al usuario. La espera es acotada
        # (`ESPERA_TURNO_S`) y no aplica a la pausa por ventana agotada, que no se libera
        # sola. Si el tope se cumple, el rechazo es exactamente el de siempre.
        _cola_t0 = time.monotonic()
        _base.anotar_evento(
            "slot_requested", turno_id=_turno_pedido,
            request_id=_cid, provider=provider.provider_id,
            remaining_s=max(0.0, _deadline_mono - _cola_t0),
        )
        _espera_real = min(
            _slots.ESPERA_TURNO_S,
            max(0.0, _deadline_mono - _cola_t0),
        )
        if _deadline_mono <= time.monotonic():
            _base.anotar_evento(
                "slot_rejected", turno_id=_turno_pedido,
                request_id=_cid, provider=provider.provider_id,
                reason="deadline", queue_s=0.0, remaining_s=0.0,
            )
            return self._send(504, {"error": {
                "message": f"[{provider.display_name}] el deadline llegó agotado",
                "type": "cli_timeout",
                "error_kind": ERR_TIMEOUT,
                "brain_provider": provider.provider_id,
                "provider_name": provider.display_name,
                "turno_id": _turno_pedido,
                "reason": "deadline",
                "queue_s": 0.0,
                "timing": _preinvoke_timing("service_queue_deadline"),
            }})
        # ── EL CARRIL AUXILIAR (paso 5) ──────────────────────────────────────────
        # Un turno SIN catálogo es un auxiliar del stack —título, clasificación, resumen—
        # y no tiene por qué quedarse con el slot del turno de OFICIO. Medido desde la
        # pantalla: en Oficina el TÍTULO pidió primero y el oficio esperó 2,67 s detrás;
        # en Ciencia 5,69-8,14 s; en Diseño 2,73 s. `_tools` es la lista que este mismo
        # pedido va a cruzar, así que la clasificación no adivina nada.
        _es_auxiliar = not _tools
        try:
            _slots.SLOTS.pedir(provider.provider_id, espera_s=_espera_real,
                               auxiliar=_es_auxiliar)
        except _slots.SinSlot as sin:
            _esperado = time.monotonic() - _cola_t0
            _deadline_agotado = time.monotonic() >= _deadline_mono
            _base.anotar_evento(
                "slot_rejected", turno_id=_turno_pedido,
                request_id=_cid, provider=provider.provider_id,
                reason="deadline" if _deadline_agotado else sin.motivo,
                slot_reason=sin.motivo, queue_s=_esperado,
                remaining_s=max(0.0, _deadline_mono - time.monotonic()),
            )
            if _deadline_agotado:
                return self._send(504, {"error": {
                    "message": f"[{provider.display_name}] el deadline se agotó en la cola",
                    "type": "cli_timeout",
                    "error_kind": ERR_TIMEOUT,
                    "brain_provider": provider.provider_id,
                    "provider_name": provider.display_name,
                    "turno_id": _turno_pedido,
                    "reason": "deadline",
                    "queue_s": round(_esperado, 3),
                    "timing": _preinvoke_timing("service_queue_deadline"),
                }})
            causa = _slots.causa_de(sin, nombre_cli=provider.display_name)
            code, etype = _HTTP_BY_KIND.get(ERR_RATE_LIMIT, (429, "throttled"))
            print(f"[cli_brain] ⊘ {provider.provider_id} rechazado: {sin.motivo} "
                  f"({sin.activos}/{sin.limite})", file=_log, flush=True)
            return self._send(code, {"error": {
                "message": f"[{provider.display_name}] {(causa or {}).get('detalle') or sin.motivo}",
                "type": etype,
                "error_kind": ERR_RATE_LIMIT,
                "brain_provider": provider.provider_id,
                "provider_name": provider.display_name,
                "reset_hint": _slots._legible(sin.restante_s) if sin.restante_s else "",
                "causa": causa,
            }})

        _esperado = time.monotonic() - _cola_t0
        _base.anotar_evento(
            "slot_granted", turno_id=_turno_pedido,
            request_id=_cid, provider=provider.provider_id,
            queue_s=_esperado,
            remaining_s=max(0.0, _deadline_mono - time.monotonic()),
        )
        if time.monotonic() >= _deadline_mono:
            # La cola consumió el último milisegundo. No se abre ficha ni se spawnea un
            # proceso condenado; se suelta exactamente el slot que acabamos de obtener.
            _slots.SLOTS.soltar(provider.provider_id, auxiliar=_es_auxiliar)
            return self._send(504, {"error": {
                "message": f"[{provider.display_name}] el deadline se agotó en la cola",
                "type": "cli_timeout",
                "error_kind": ERR_TIMEOUT,
                "brain_provider": provider.provider_id,
                "provider_name": provider.display_name,
                "turno_id": _turno_pedido,
                "reason": "deadline",
                "timing": _preinvoke_timing("service_queue_deadline"),
            }})

        # ── F2d · EL TURNO SE ABRE DESPUÉS DEL SLOT ───────────────────────────────
        # Después, no antes: un turno que fue rechazado por el techo no existe, y abrirle
        # ficha haría que un `stop` contestara `turno_detenido` sobre algo que nunca
        # corrió. El id lo puede elegir el cliente (`turno_id` en el body) — es la única
        # forma de poder detener un pedido NO-streaming, cuyo id de respuesta recién se
        # conoce al final. `abrir_turno` devuelve el id DEFINITIVO (desempata colisiones),
        # y ése es el que se reporta.
        _turno = _base.abrir_turno(_turno_pedido, provider.provider_id)
        _tid = _turno.id
        _vivo["turno_id"] = _tid
        # ── EL CENTINELA: MIRAR EL SOCKET, NO ESCRIBIRLO ──────────────────────────
        # `_abandonar` sólo podía dispararse cuando una escritura FALLABA, y un turno de
        # CLI NO ESCRIBE NADA mientras piensa: el binario entrega la respuesta al final.
        # El consumidor se iba, nadie intentaba escribir, nadie se enteraba, y el CLI
        # seguía quemando la ventana de la suscripción hasta terminar solo.
        #
        # MEDIDO el 2026-08-13 con TODA la cadena del backend ya funcionando —el turno
        # registrado, el socket atado, el `detener` devolviendo `turno_detenido`—: la fuga
        # seguía en 25,4 s. Cerrarle el socket a este server NO para al CLI si de este lado
        # nadie mira. Faltaba mirar.
        #
        # POR QUÉ MIRAR Y NO LATIR. El primer intento fue un comentario SSE periódico, para
        # que la escritura fallara. Dos problemas, los dos medidos: sólo se puede escribir
        # con el stream ABIERTO, y el stream abre con el primer delta — que es justamente
        # lo que no llega. Abrirlo antes tampoco: mientras no salió nada, el camino de
        # error sigue siendo un HTTP con su status, y abrir el SSE lo convertiría en un 200
        # con el error adentro. Se perdería el tipado de fallos entero por una sonda.
        #
        # `select` + `MSG_PEEK` no toca nada: no escribe, no consume bytes, no abre el
        # stream. Cuando el otro lado cierra, el socket queda legible y el peek devuelve
        # vacío — eso es EOF, y EOF es que se fue.
        _centinela_para = threading.Event()

        def _vigilar() -> None:
            _sock = self.connection
            while not _centinela_para.wait(_VIGILIA_S):
                if _vivo.get("abandonado"):
                    return
                try:
                    listos, _, _ = select.select([_sock], [], [], 0)
                    if not listos:
                        continue                      # nada que leer: sigue ahí
                    if _sock.recv(1, socket.MSG_PEEK) == b"":
                        _abandonar("el socket del consumidor dio EOF")
                        return
                except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                    _abandonar("el socket del consumidor ya no existe")
                    return

        _centinela = threading.Thread(target=_vigilar, name=f"centinela-{_tid}", daemon=True)
        _centinela.start()

        t0 = time.time()
        _rehecha = False
        _claude_execution_started = False
        try:
            kw = {"model": cli_model, "effort": _eff}
            if _acepta_kwarg(provider.invoke, "timeout"):
                kw["timeout"] = max(0.0, _deadline_mono - time.monotonic())
            if _acepta_kwarg(provider.invoke, "deadline_mono"):
                kw["deadline_mono"] = _deadline_mono
            if _acepta_kwarg(provider.invoke, "request_received_mono"):
                kw["request_received_mono"] = _http_enter_mono
            if _acepta_on_evento(provider.invoke):
                kw["on_evento"] = _on_evento
            if _acepta_kwarg(provider.invoke, "turno_id"):
                kw["turno_id"] = _tid
            if _acepta_kwarg(provider.invoke, "clave_conversacion"):
                kw["clave_conversacion"] = _clave_conversacion
            _con_sesion = sesion is not None and _acepta_kwarg(provider.invoke, "sesion")
            if _con_sesion:
                kw["sesion"] = sesion
            # Un provider viejo que no conozca el kwarg no se rompe: se lo llama como
            # siempre y sus imágenes quedan en las MARCAS del prompt, no en base64.
            if _imagenes and _acepta_kwarg(provider.invoke, "imagenes"):
                kw["imagenes"] = _imagenes
            _claude_preflight = None
            if provider.provider_id == "claude_cli":
                # La cache normal de 20 s evita un spawn por turno. Si nunca se verificó o
                # ya no está autenticado, este intento exige un sondeo nuevo antes del CLI.
                _claude_preflight = _detect_one("claude_cli")
                if _claude_preflight is None or _claude_preflight.state != _base.STATE_READY:
                    _claude_preflight = _detect_one("claude_cli", force_refresh=True)
            if provider.provider_id == "claude_cli" and (
                    _claude_preflight is None or _claude_preflight.state != _base.STATE_READY):
                _state = _claude_preflight.state if _claude_preflight else _base.STATE_AUTH_UNKNOWN
                _kind = (ERR_AUTH_EXPIRED if _state == _base.STATE_AUTH_EXPIRED else
                         ERR_NO_AUTH if _state == _base.STATE_NO_AUTH else ERR_AUTH_UNKNOWN)
                if _state == _base.STATE_NOT_INSTALLED:
                    _kind = ERR_NOT_INSTALLED
                elif _state == _base.STATE_CONFIG_INVALID:
                    _kind = ERR_CONFIG_INVALID
                _detail = ("La sesión de Claude Code venció. Ejecuta `claude auth login` y vuelve a comprobar."
                           if _kind == ERR_AUTH_EXPIRED else
                           "Claude Code no tiene una sesión activa. Ejecuta `claude auth login` y vuelve a comprobar."
                           if _kind == ERR_NO_AUTH else
                           _claude_preflight.detail if _kind in (ERR_NOT_INSTALLED, ERR_CONFIG_INVALID)
                           and _claude_preflight else
                           "No pude verificar la sesión de Claude Code. Vuelve a comprobar.")
                res = _base.BrainResult(ok=False, error_kind=_kind, error_detail=_detail)
            else:
                if provider.provider_id == "claude_cli":
                    _claude_execution_started = True
                res = provider.invoke(prompt, **kw)
            # ── F2e · LA SESIÓN SE PERDIÓ A MITAD: SE REHACE, NO SE FALLA ─────────
            # El chequeo de `existe_sesion` la caza casi siempre, pero hay una carrera real
            # (el usuario borra su store entre el `isfile` y el spawn) y está el caso del
            # id ya en uso. La sesión es una OPTIMIZACIÓN: perderla tiene que costar un
            # turno más caro, jamás un turno fallado. Se rehace UNA vez —dos sería una
            # espiral— con el contexto completo, que es literalmente el comportamiento de
            # antes de esta fase.
            if _con_sesion and not res.ok and (res.error_kind == ERR_SESION_PERDIDA
                                               or (res.meta or {}).get("sesion_perdida")):
                print(f"[cli_brain] ⟲ resume perdido ({sesion.id}); rehago con contexto "
                      f"completo", file=_log, flush=True)
                # [Gate 3 · D9] La carrera que el `isfile` no caza (el store se borra
                # ENTRE el chequeo y el spawn) llega hasta acá, y el mapa tiene que
                # enterarse igual: si no, el id que acaba de morir sobrevive al reinicio.
                _causa_sesion = _perder_sesion(sesion, _clave, _causa_sesion,
                                               "el CLI rechazó continuar la conversación "
                                               "restaurada del mapa")
                sesion.renovar_id()
                _rehecha = True
                kw["sesion"] = sesion
                _p2, _im2 = render_con_imagenes(_msgs, _tools, _tool_choice)
                if _acepta_kwarg(provider.invoke, "imagenes"):
                    # La sesión se perdió: el CLI NO tiene ninguna imagen de esta charla,
                    # así que el turno rehecho las lleva TODAS. Dejar acá el `_imagenes` de
                    # la cola sería mandar el texto completo con las imágenes de un turno.
                    kw["imagenes"] = _im2
                res = provider.invoke(_p2, **kw)
            if (provider.provider_id == "claude_cli" and _claude_execution_started and not res.ok and
                    res.error_kind in (ERR_MODEL, ERR_NO_AUTH, ERR_ACCESS_DENIED,
                                       ERR_SERVICE_UNAVAILABLE, ERR_PROVIDER)):
                # Siempre se salta la cache tras un fallo ambiguo. El estado fresco manda
                # sobre el 403/502 del wrapper; jamás se reintenta la petición al proveedor.
                _fresh = _detect_one("claude_cli", force_refresh=True)
                if _fresh is None:
                    _fresh = _base.BrainStatus("claude_cli", _base.STATE_AUTH_UNKNOWN)
                res = provider.reconcile_failure(res, _fresh)
            _state_event_at = time.time()
            if res.ok:
                # A real successful completion is newer evidence than any earlier
                # rate-limit event from this provider/account context. Clear its local
                # cooldown before releasing the slot to waiting requests.
                _slots.SLOTS.registrar_ejecucion_exitosa(
                    provider.provider_id, actual_model=res.model_final or "",
                    ahora=_state_event_at)
            elif res.error_kind == ERR_RATE_LIMIT:
                _cause = res.causa if isinstance(res.causa, dict) else {}
                _retry_after = _cause.get("retry_after_s")
                _event = _slots.SLOTS.registrar_rate_limit(
                    provider.provider_id, retry_after_s=_retry_after,
                    reset_hint=res.reset_hint or "",
                    motivo="rate_limit", ahora=_state_event_at)
                _state_event_at = _event.get("occurred_at", _state_event_at)
                try:
                    if __package__ in (None, ""):
                        from cli_brain.evidence import record_provider_rate_limit
                    else:
                        from .evidence import record_provider_rate_limit
                    record_provider_rate_limit(
                        provider.provider_id, retry_after_s=_event.get("retry_after_s"),
                        reset_hint=_event.get("reset_hint", ""),
                        reset_at=_event.get("reset_at"), occurred_at=_event.get("occurred_at"))
                except Exception as exc:
                    print(f"[cli_brain] no pude guardar el rate-limit de {provider.provider_id}: "
                          f"{type(exc).__name__}", file=_log, flush=True)
            try:
                if __package__ in (None, ""):
                    from cli_brain.evidence import record as _record_provider_evidence
                else:
                    from .evidence import record as _record_provider_evidence
                _record_provider_evidence(
                    provider.provider_id, ok=res.ok,
                    error_kind=res.error_kind or "", actual_model=res.model_final or "",
                    retry_after_s=((res.causa or {}).get("retry_after_s")
                                   if isinstance(res.causa, dict) else None),
                    reset_hint=res.reset_hint or "",
                    occurred_at=_state_event_at)
            except Exception as exc:
                print(f"[cli_brain] no pude guardar el estado de prueba de {provider.provider_id}: "
                      f"{type(exc).__name__}", file=_log, flush=True)
        finally:
            # El centinela primero: mira ESTE socket, y dejarlo vivo mientras se cierra el
            # turno lo dejaría vigilando una respuesta que ya terminó.
            _centinela_para.set()
            # El orden importa: primero se cierra el turno (deja de ser detenible y su fila
            # sale del registro persistente), después se suelta el slot. Al revés, el turno
            # siguiente podría entrar y encontrarse el id del anterior todavía en la tabla.
            _base.cerrar_turno(_tid)
            _slots.SLOTS.soltar(provider.provider_id, auxiliar=_es_auxiliar)
        dt = time.time() - t0
        _timing = dict((res.meta or {}).get("timing") or {})
        _timing["provider_resolved_s"] = _provider_resolved_s
        _timing["completion_s"] = round(time.monotonic() - _http_enter_mono, 3)
        if not res.ok and res.error_kind == ERR_TIMEOUT:
            _timing["timeout_layer"] = _timing.get("timeout_layer") or "cli_deadline"
        # El avance de la sesión SÓLO con el turno bueno. Si falló, el CLI no vio esos
        # mensajes y darlos por enviados los perdería para siempre.
        if sesion is not None and res.ok:
            sesion.turnos += 1
            # Contador Y huella, juntos y en una sola pieza medible: un `enviados` sin
            # su huella es el contador que miente que `prefijo_vivo` viene a arreglar.
            _ses.avanzar(sesion, _msgs)
            # [Gate 3 · D9] …y recién acá el mapa. La MISMA regla que `enviados`: si el
            # turno no salió bien, el CLI no escribió transcript y el id no se puede
            # resumir — persistirlo sería dejarle al próximo arranque una promesa vacía.
            _ses.SESIONES.recordar(sesion)
            # Confirmada: el id ya es de este proceso y `turnos` lo cuenta. Desde acá el
            # incremental vuelve solo.
            sesion.restaurada = False

        # ── EL GUARD DE PUREZA DESCARTÓ: QUE EL PRÓXIMO INTENTO LO SEPA ──────────────
        # La marca se pone con el prompt **base**, sin el preludio que ESTE intento pudo
        # haber llevado: si no, un segundo descarte cambiaría la llave y el tercer intento
        # saldría a ciegas otra vez. La llave tiene que ser la del PEDIDO, y el pedido es
        # el mismo las tres veces.
        if not res.ok and (res.exec_events or 0) > 0:
            _marcar_impureza(provider.provider_id,
                             prompt[len(_preludio) + 1:] if _preludio else prompt,
                             res.exec_events)

        if not res.ok:
            code, etype = _HTTP_BY_KIND.get(res.error_kind, (502, "model_error"))
            print(f"[cli_brain] ✗ {provider.provider_id} {res.error_kind} ({dt:.1f}s): "
                  f"{res.error_detail[:160]}", file=_log, flush=True)
            cuerpo = {"error": {
                "message": f"[{provider.display_name}] {res.error_detail}",
                "type": etype,
                "error_kind": res.error_kind,
                "brain_provider": provider.provider_id,
                "provider_name": provider.display_name,
                "reset_hint": res.reset_hint,
                "turno_id": _tid,       # F2d · qué turno fue, aunque haya terminado mal
                "identity": {
                    "requested_provider": provider.provider_id,
                    "requested_model": cli_model,
                    "resolved_provider": provider.provider_id,
                    "resolved_model": res.resolved_model,
                    "actual_provider": None,
                    "actual_model": None,
                    "fallback_used": False,
                    "override_used": False,
                },
                "timing": _timing,
            }}
            # F2a · LA CAUSA TIPADA VIAJA EN EL ERROR (primer consumidor real del traductor
            # de F1). Aditivo: las seis claves de arriba no cambian. Ya viene redactada.
            _cause_payload = None
            if res.causa:
                _cause = dict(res.causa)
                if res.error_kind == ERR_RATE_LIMIT:
                    _evidence = dict(_cause.get("evidencia") or {})
                    _event = {
                        "state": "provider_rate_limited",
                        "origin": "provider",
                        "occurred_at": time.time(),
                        "retry_after_s": _cause.get("retry_after_s"),
                        "reset_hint": res.reset_hint or "",
                    }
                    _evidence.update({
                        "runtime_state": "provider_rate_limited",
                        "quota_availability": "rate_limited_at_event",
                        "provider_event": _event,
                    })
                    _cause["evidencia"] = _evidence
                    _cause["runtime_state"] = "provider_rate_limited"
                    _cause["quota_availability"] = "rate_limited_at_event"
                    _cause["provider_rate_limit_event"] = _event
                cuerpo["error"]["causa"] = _cause
                _cause_payload = _cause
            if not _vivo["abierto"]:
                return self._send(code, cuerpo)     # el camino de siempre
            # Falló A MITAD del stream — imposible hasta esta fase, porque no había mitad.
            # Los headers ya salieron, así que se reporta por el canal y se cierra limpio.
            self._sse(self._chunk(_cid, _created, _vivo["modelo"], {}, finish="error",
                                  annex={"brain_provider": provider.provider_id,
                                         "provider_name": provider.display_name,
                                         "error_kind": res.error_kind,
                                         "reset_hint": res.reset_hint,
                                         "turno_id": _tid,
                                         "causa": _cause_payload}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        tool_calls = extract_tool_calls(res.text)
        has_call = bool(tool_calls)

        # ══ [B0-2 · CLI] LA OBLIGACIÓN SE COMPRUEBA, NO SE SUPONE ══════════════════════
        # Acá está la diferencia entre honrar `tool_choice` y fingir que se honra. En un
        # proveedor de API, `"required"` lo garantiza el servidor del proveedor. Acá no
        # existe esa bandera: lo único que hay es una instrucción en un prompt, y una
        # instrucción se puede desobedecer. Si devolviéramos el texto como si nada, el
        # harness lo leería como respuesta final —que es justo la decisión equivocada que
        # este bloqueo venía a evitar— y encima quedaría indistinguible de un turno en el
        # que nadie exigió nada.
        #
        # Es la misma doctrina que ya tiene este puente para el otro lado («solo se emite
        # tool_calls si el modelo REALMENTE puso un marcador»): lo que no pasó, no se
        # afirma. Falla visible, con su causa, y el llamante decide.
        if obliga_a_tool(_tool_choice) and _tools and not has_call:
            _exigida = nombre_exigido(_tool_choice)
            print(f"[cli_brain] ✗ {provider.provider_id} tool_choice exigía "
                  f"{_exigida or 'una tool'} y el modelo contestó texto", file=_log, flush=True)
            return self._send(422, {"error": {
                "message": (f"[{provider.display_name}] este paso exigía llamar "
                            f"{('`' + _exigida + '`') if _exigida else 'una herramienta'} y el "
                            f"modelo respondió texto. Los cerebros CLI no tienen "
                            f"`tool_choice` nativo: la obligación viaja en el prompt y se "
                            f"verifica en la salida, así que puede no cumplirse."),
                "type": "tool_choice_no_honrado",
                "causa": {"causa": "tool_choice_no_honrado",
                          "exigido": _exigida or "any",
                          "soporte": "prompt",       # no `native` — y la diferencia importa
                          "texto_devuelto": (res.text or "")[:400]},
            }})

        # ══ EL MARCADOR ROTO NO SE SIRVE COMO PROSA ═══════════════════════════════════
        # LO QUE SE VEÍA. `extract_tool_calls` devuelve `[]` tanto cuando el modelo
        # escribió una respuesta final como cuando escribió un marcador cuyo JSON no
        # cerraba. Los dos caían acá abajo en `content: res.text` con
        # `finish_reason: "stop"`, así que la segunda terminaba en la pantalla del usuario
        # como **código crudo servido de respuesta**: `<function=redline>{"documen…`.
        # Un abogado leyendo eso no tiene forma de saber que lo que falló fue una llamada
        # a herramienta y no su pregunta.
        #
        # Es la misma doctrina que el bloque de acá arriba, aplicada al caso que le
        # faltaba: **lo que no pasó, no se afirma**. Ahí era «no llamó y debía»; acá es
        # «quiso llamar y no se entendió». En los dos, devolver el texto como si nada
        # convierte un fallo en una respuesta.
        #
        # POR QUÉ FALLA Y NO LIMPIA EL MARCADOR. Borrarlo dejaría un texto mutilado que
        # parece una respuesta completa —el modelo escribió el marcador EN LUGAR de
        # contestar, no además— y encima escondería que hubo un intento. La causa tipada
        # deja que la cascada reintente sabiendo qué pasó, que es lo único que evita el
        # segundo turno a ciegas.
        if not has_call:
            _rota = marcador_ilegible(res.text, _tools)
            if _rota:
                print(f"[cli_brain] ✗ {provider.provider_id} intentó llamar {_rota} y el "
                      f"marcador no se pudo parsear", file=_log, flush=True)
                return self._send(422, {"error": {
                    "message": (f"[{provider.display_name}] el modelo intentó llamar "
                                f"`{_rota}` y el marcador quedó mal escrito, así que la "
                                f"llamada no se pudo armar. No se devuelve ese texto como "
                                f"respuesta: es una herramienta fallida, no una contestación."),
                    "type": "marcador_ilegible",
                    "causa": {"causa": "marcador_ilegible",
                              "tool": _rota,
                              "soporte": "prompt",   # el marcador es texto, no canal nativo
                              "texto_devuelto": (res.text or "")[:400]},
                }})

        if res.exec_events:
            # el CLI ejecutó algo por su cuenta — se surfacea SIEMPRE (el harness lo caza)
            print(f"[cli_brain] ⚠ {provider.provider_id} exec_events={res.exec_events} "
                  f"(el wrapper debe ser puro in/out)", file=_log, flush=True)
        print(f"[cli_brain] ✓ {provider.provider_id} ({dt:.1f}s) "
              f"{'tool-call' if has_call else 'final'} model={res.model_final} "
              f"out_tok={res.usage.get('completion_tokens')}", file=_log, flush=True)

        # `res.text` es la salida CRUDA del CLI, marcador incluido. Cuando el marcador
        # parseó, la llamada ya viaja en `tool_calls` y repetirla en `content` es mandarle
        # el andamio al usuario — el mismo defecto que `marcador_ilegible` cubre para el
        # caso en que NO parsea. Los dos casos, ahora, con la misma regla.
        message = {"role": "assistant",
                   "content": texto_visible(res.text) if has_call else res.text}
        finish_reason = "stop"
        if has_call:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        # ── F2c · EL CERO NO SE INVENTA ───────────────────────────────────────────
        # Antes: `int(... or 0)` — un CLI que no reportó tokens salía de acá diciendo que
        # gastó cero. Ahora el None se PRESERVA. Río abajo `_accumulate_usage` ya sabe
        # leerlo: un dict con los dos campos en None cae en `calls_no_usage` y
        # `_emit_model_cost_event` deja `tokens_measured: false` y `usd: null` — todo eso
        # SIN tocar `recipe_assembler`, que es justamente el contrato que ya existía y que
        # esta vía venía esquivando.
        pt = res.usage.get("prompt_tokens")
        ct = res.usage.get("completion_tokens")
        _medidos = bool(getattr(res, "tokens_medidos", False)) and (pt is not None or ct is not None)
        _total = (pt or 0) + (ct or 0) if _medidos else None
        response = {
            "id": _cid,
            "object": "chat.completion",
            "created": _created,
            # A CLI-reported model wins. Codex may instead provide an accepted
            # explicit -m selection, marked requested-validated in the annex.
            "model": res.model_final or provider.response_model_id,
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            # COMPAT: las TRES claves de siempre siguen estando. Lo que cambia es que su
            # valor puede ser `null` cuando el CLI no reportó — que es la verdad. Un
            # consumidor que hacía `int(usage["prompt_tokens"] or 0)` sigue funcionando;
            # uno que compara contra None ahora se entera. La señal explícita vive en el
            # annex (`tokens_medidos`), para no meter un campo no-OpenAI dentro de `usage`.
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": _total},
            "aleph_cli_brain": {
                "brain_provider": provider.provider_id,
                "provider_name": provider.display_name,
                "model_final_source": res.model_final_source,
                "exec_events": res.exec_events,
                "requested_model": cli_model,   # annex: el sub-modelo PEDIDO (None = default del plan)
                "resolved_model": res.resolved_model,
                "actual_model": res.model_final,
                "actual_model_source": res.model_final_source or "unknown",
                "timing": _timing,
                "identity": {
                    "requested_provider": provider.provider_id,
                    "requested_model": cli_model,
                    "resolved_provider": provider.provider_id,
                    "resolved_model": res.resolved_model,
                    "actual_provider": provider.provider_id,
                    "actual_model": res.model_final,
                    "actual_model_source": res.model_final_source or "unknown",
                    "fallback_used": False,
                    "override_used": False,
                },
                "effort": _eff,                 # 27·3 · el effort REAL que corrió el CLI este turno
                "stream": res.meta.get("stream"),  # F2a · forense: cuántos deltas, overflow, mudo
                "tokens_medidos": _medidos,     # F2c · ¿los tokens son del CLI, o no hay dato?
                # EL LEDGER DICE «NO SÉ» EN VOZ ALTA. `tokens_medidos` ya es la señal para
                # la máquina, pero un `usage` con `null` adentro se lee igual que un campo
                # que nadie llenó, y ésas son dos cosas distintas: una es «el CLI no lo
                # reportó» y la otra es «se perdió en el camino» — que es exactamente el
                # defecto que esto viene a cerrar. Con el estado escrito, un turno sin
                # tokens es un turno DECLARADO sin tokens, no un agujero.
                "usage_estado": "medido" if _medidos else "no_reportado",
                # EL LEDGER HONESTO. Van en el annex y no dentro de `usage` por la misma
                # razón que `tokens_medidos`: `usage` es el sobre de OpenAI y no se le
                # meten campos que no son suyos. Sin esto la casa no puede distinguir
                # «prompt barato» de «prompt cacheado», que es la única forma de saber si
                # reusar la sesión sirvió. `None` = el CLI no reportó ese campo.
                "cache_write_tokens": _grabar_usage(res, provider, _medidos),
                "cache_read_tokens": res.usage.get("cache_read_tokens"),
                "reasoning_tokens": res.usage.get("reasoning_tokens"),
                "advertised_tools": (res.meta or {}).get("advertised_tools"),
                "tool_calls": (res.meta or {}).get("tool_calls"),
                # Si este turno llevó la corrección de un descarte anterior. Es la prueba
                # forense de que el reintento NO salió a ciegas: sin esto, un turno
                # corregido y uno virgen son indistinguibles desde afuera.
                "preludio_correccion": bool(_preludio),
                "turno_id": _tid,               # F2d · el id con el que se lo podía detener
                # F2e · la sesión, para que el ahorro sea AUDITABLE y no un acto de fe:
                # qué id se usó, qué número de turno fue, si se mandó sólo lo nuevo, y si
                # hubo que rehacerla. `None` cuando la fase está apagada o no hubo clave.
                # [D9] `restaurada` dice si este id salió del mapa en disco, y `causa`
                # lleva la causa SELLADA `sesion_perdida` cuando lo restaurado ya no
                # servía. Las dos son None/False en el turno normal.
                "sesion": ({"id": sesion.id, "turno": sesion.turnos,
                            "incremental": _incremental, "rehecha": _rehecha,
                            "mensajes_enviados": sesion.enviados,
                            "restaurada": _restaurada, "causa": _causa_sesion}
                           if sesion is not None else None),
            },
        }
        if quiere_stream:
            if not _vivo["abierto"]:
                # el turno terminó sin un solo delta (provider sin stream-json, o respuesta
                # que llegó entera en el result): se emite como antes, en un chunk.
                return self._send_stream(response)
            # Ya se emitieron los deltas. Falta SÓLO el cierre: `finish_reason`, el annex,
            # el `usage` y el model_final AUTORITATIVO (el de `modelUsage`, no el del init).
            _final = {"tool_calls": tool_calls} if has_call else {}
            self._sse(self._chunk(_cid, _created, response["model"], _final,
                                  finish=finish_reason, annex=response["aleph_cli_brain"],
                                  usage=response.get("usage")))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self._send(200, response)


class CliBrainHTTPServer(ThreadingHTTPServer):
    """Listener local administrable por el sidecar.

    `daemon_threads` evita que `server_close()` espere indefinidamente a un handler; el
    lifecycle termina primero sus subprocess registrados y luego une el hilo servidor.
    """
    daemon_threads = True
    allow_reuse_address = True


def create_server(port: int | None = None, *, llave: str = "") -> CliBrainHTTPServer:
    """Crea y BINDEA el server; quien llama posee `serve_forever/shutdown/server_close`.

    `llave` va ATADA A ESTE SERVER y NO se lee del disco en cada request, que es como lo
    tenía escrito primero y estaba mal: el archivo es por instalación, así que en cuanto el
    producto creaba su llave, TODO server de esta máquina empezaba a exigirla — incluidos
    los efímeros que levantan las varas, que no tienen cómo saberla. Medido: dos varas en
    rojo. La amenaza es el puerto del producto, no el de una vara; quien enciende el gate
    es quien es dueño del ciclo de vida (`lifecycle.start`), pasando la llave acá.
    """
    # [Gate 3 · D9] EL BOOT DE LAS SESIONES, y es una lectura de archivo. Va acá y no en
    # `main()` porque `main()` no es el único que sirve turnos: las varas bindean por
    # `create_server` y tienen que ver exactamente el mismo arranque que el usuario.
    # Cero llamadas al CLI, cero `stat` del store: lo que no sirva se descubre en su turno.
    try:
        _n = _ses.SESIONES.cargar()
        print(f"[cli_brain] mapa de sesiones: {_n} conversación(es) restaurada(s) de "
              f"{_ses.SESIONES.mapa_ruta}", file=_log, flush=True)
    except Exception as e:                                   # noqa: BLE001
        # `cargar()` ya está escrito para no levantar. Este guard existe igual porque lo
        # que está del otro lado es el arranque de la app: si algún día alguien mete una
        # excepción ahí adentro, se pierden las sesiones, no el sidecar.
        print(f"[cli_brain] el mapa de sesiones no se pudo leer ({type(e).__name__}: {e}); "
              f"arranco sin sesiones restauradas", file=_log, flush=True)
    srv = CliBrainHTTPServer(("127.0.0.1", PORT if port is None else int(port)), Handler)
    srv.llave_instancia = str(llave or "")
    return srv


def main():
    # El server suelto SÍ toma la llave de la instalación: es el mismo puerto que
    # usa el backend de dev, y los dos leen el mismo archivo.
    srv = create_server(llave=_credencial.leer())
    actual_port = int(srv.server_port)
    print(f"[cli_brain] BYO-CLI server en http://127.0.0.1:{actual_port}/v1 — providers: "
          f"{served_label()}; tools de los CLIs OFF",
          file=_log, flush=True)
    try:
        srv.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
