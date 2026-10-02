"""
stream_chat.py — STREAMING token-por-token para la Sala (ADITIVO, no toca el run path).

La "sesión en vivo" letra-a-letra: para obras de TEXTO (informe/documento) la Sala
puede pedir la respuesta del modelo en STREAMING y dibujarla mientras llega (render-on-change).

Es un chat DIRECTO (sin tools, sin enforcer): solo genera texto, no ejecuta acciones —
por eso no necesita gate (no toca plata/datos; las obras con tools/acciones siguen yendo
por el run completo `/v1/puppets/run`, con su gate). REUSA los building-blocks del
assembler (framing + RAG + key de cognición); cero re-arquitectura del motor.

BYOK-LLM (⚡ "Tu API"): si la receta trae `model.byok_ref` (ej. "keys:openai") y hay un
resolver del usuario, el LLM corre con la key del USUARIO (su propia API) en vez de la
cognición incluida. Soporta OpenAI-compatible (Bearer + /chat/completions) Y Anthropic
(/v1/messages + x-api-key), porque Claude NO es OpenAI-compatible.

Solo stdlib (urllib). Cognición real (Groq/OpenAI-compat con stream=true).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterator, Optional

log = logging.getLogger(__name__)

try:
    import aleph_paths as _ap
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_REPO = _ap.resource_root()
_ASM_DIR = _REPO / "platform" / "assembler"

# ── EL TRADUCTOR (Gate 2 · F1) ─────────────────────────────────────────────────────
# Import BLANDO, igual que en `assembler.py` y `recipe_assembler.py`: con `_tr is None`
# este módulo se comporta EXACTAMENTE como antes de F4b y la excepción cruda sube como
# siempre. Esa rama está probada en la vara.
try:
    if str(_ASM_DIR) not in sys.path:
        sys.path.insert(0, str(_ASM_DIR))
    import errores_modelo as _tr                   # type: ignore
except ImportError:                                # pragma: no cover
    _tr = None                                     # type: ignore

_asm_mod = None
def _asm():
    global _asm_mod
    if _asm_mod is None:
        if str(_ASM_DIR) not in sys.path:
            sys.path.insert(0, str(_ASM_DIR))
        _asm_mod = _ap.load_module_by_path(
            "puppet_assembler_stream", _ASM_DIR / "recipe_assembler.py")
    return _asm_mod


def _system_content(recipe: dict, lang: Optional[str] = None) -> str:
    """framing + RAG, REUSANDO los helpers del assembler (mismos que el run completo)."""
    a = _asm()
    return (a._build_framing(recipe, _REPO) + a._build_idioma_block(lang)
            + a._build_rag(recipe, _REPO))


def _is_anthropic(base_url: str) -> bool:
    return "anthropic.com" in (base_url or "")


def _resolve_llm_key(recipe: dict, byok_resolver: Optional[Callable[[str], str]]) -> tuple[str, bool]:
    """Devuelve (api_key, es_byok). BYOK-LLM: si model.byok_ref resuelve a la key del
    usuario, se usa ESA (su propia API). Si no, la cognición incluida."""
    model = recipe.get("model", {}) or {}
    ref = model.get("byok_ref")
    if ref and byok_resolver:
        try:
            k = byok_resolver(ref)
        except Exception:
            k = ""
        if k:
            return k, True
    return _asm()._resolve_cognition_key(_REPO), False


def _is_cli_brain_endpoint(base_url: str) -> bool:
    url = (base_url or "").rstrip("/").lower()
    cli_url = os.environ.get(
        "PUPPET_CLI_BRAIN_BASE_URL", "http://127.0.0.1:8926/v1"
    ).rstrip("/").lower()
    return url == cli_url or ":8926/" in (url + "/")


# ══ LA CAUSA TIPADA EN EL CAMINO DE STREAMING (Gate 2 · F4b · obra 1) ══════════════
# EL AGUJERO QUE CIERRA, y es un agujero que F4a NO tapó: F4a tipó `assembler._chat`, y
# **la Sala no pasa por ahí**. El chat en vivo va por `_stream_openai`/`_stream_anthropic`,
# que hacen `urlopen(...)` SIN un solo `except`, así que la excepción cruda sube por
# `stream_answer` hasta `router.py`, que la vuelca como `{"type":"error","detail":str(exc)}`.
# O sea: el motor ya decía la verdad y la cara seguía mostrando el string del proveedor.
#
# Acá se traduce con las MISMAS piezas de F1/F4a — cero taxonomía nueva — y el mensaje se
# conserva por la misma razón de siempre: hay consumidores que lo leen.

_PUERTO_OLLAMA = 11434

#: [GATE 3 · obra 6] El nombre SELLADO, tomado del vocabulario y no escrito acá. Con el
#: import blando caído queda el literal, que es el mismo string que `errores_modelo.py:93`
#: define — pero la fuente de verdad es el módulo, igual que en todo el resto del archivo.
_SESION_PERDIDA = getattr(_tr, "SESION_PERDIDA", "sesion_perdida") if _tr else "sesion_perdida"

# ── [F6-cierre · obra C] EL REGISTRO DE TURNOS HTTP ────────────────────────────────
from app.phase1 import turnos_http as _turnos      # noqa: E402


def _detenido(turno_id: Optional[str]) -> Exception:
    """El corte que pidió el usuario, TIPADO — y con una causa que YA EXISTE.

    `turno_detenido` está en el vocabulario cerrado de F1 desde F2d (`errores_modelo.CAUSAS`),
    así que ya tiene copy en la superficie. Inventar una causa nueva acá habría roto la
    regla sellada —ninguna causa llega a una pantalla sin copy— para decir exactamente lo
    mismo que el vocabulario ya sabía decir.

    `reintentable=True` a propósito: el turno no falló, lo pararon. Volver a mandarlo es
    una acción perfectamente sensata, y marcarlo como permanente le escondería el botón de
    reintentar a alguien que sólo cambió de opinión.
    """
    if _tr is None:
        return RuntimeError("turno detenido")
    try:
        return _tr.ErrorDeModelo(
            _tr.CausaModelo(
                causa=_tr.TURNO_DETENIDO, estado=_tr.ROTO,
                detalle="Paraste este turno.",
                evidencia={"turno_id": turno_id or ""},
                reintentable=True, fuente=_tr.FUENTE_URLLIB),
            "turno detenido")
    except Exception:                              # noqa: BLE001 — tipar jamás rompe el turno
        return RuntimeError("turno detenido")


def _es_ollama(base_url: str) -> bool:
    """¿Este endpoint es el runtime local? Se mira el PUERTO, no el nombre del modelo."""
    u = (base_url or "").lower()
    return f":{_PUERTO_OLLAMA}" in u


def _runtime_vivo(base_url: str) -> Optional[bool]:
    """¿Ollama CONTESTA, aunque no haya contestado el pedido? `None` = no se pudo saber.

    ESTE ES EL ÍTEM QUE F4a DEJÓ HEREDADO. Un timeout contra `:11434` salía `sin_runtime`
    —«prendé Ollama»— con Ollama corriendo perfectamente, porque `desde_urllib` no tiene
    forma de distinguir «apagado» de «ocupado». F5 ya resolvió la distinción en
    `desde_ollama(runtime_vivo=...)`; lo que faltaba era que alguien MIDIERA la liveness en
    este camino, y por eso la causa seguía mintiendo en la Sala.

    Se puede medir barato y está medido por qué: `/api/version` contesta aunque el modelo
    esté ocupado, porque NO pasa por el semáforo del runner (auditoría 4 §3.1: 3 pedidos
    simultáneos → 3× HTTP 200 con latencia acumulada, cero 503). Timeout corto y jamás
    levanta: una sonda que puede colgar el reporte de un error es peor que no tenerla.
    """
    try:
        raiz = base_url.rstrip("/")
        for sufijo in ("/v1", "/api"):
            if raiz.endswith(sufijo):
                raiz = raiz[: -len(sufijo)]
        with urllib.request.urlopen(raiz + "/api/version", timeout=3.0) as r:
            return 200 <= getattr(r, "status", 200) < 300
    except urllib.error.HTTPError:
        return True          # contestó algo: está vivo, aunque no le guste la ruta
    except Exception:        # noqa: BLE001 — refused/timeout/lo que sea: no se pudo saber que vive
        return False


def _tipar(exc: Exception, base_url: str, cuerpo: str = "",
           tenia_key: bool = True) -> Exception:
    """Excepción cruda del streaming → `ErrorDeModelo` con la causa del vocabulario cerrado.

    Tres caminos, en este orden y cada uno con su motivo:

      1. **el cuerpo del server BYO-CLI manda** — `:8926` clasifica con todo a la vista y
         publica `error.causa`; el status pelado BORRA eso (F4a §2.5). Mismo candado que
         allá: sólo para ESE endpoint y sólo con una causa del vocabulario cerrado.
      2. **Ollama se traduce como Ollama** — `desde_ollama`, con la liveness MEDIDA. Es la
         única forma de que «hay cola» no se lea «prendé el runtime».
      3. **el resto, `desde_urllib`** — el camino de siempre.

    Nunca levanta por su cuenta: si traducir falla, vuelve la excepción original y el
    comportamiento es el de antes de F4b.
    """
    if _tr is None:
        return exc
    try:
        if _is_cli_brain_endpoint(base_url) and cuerpo:
            c = _causa_cli_brain(cuerpo)
            if c is not None:
                return _tr.ErrorDeModelo(c, str(exc))
        if _es_ollama(base_url):
            return _tr.ErrorDeModelo(
                _tr.desde_ollama(exc, url=base_url, runtime_vivo=_runtime_vivo(base_url)),
                str(exc))
        # [F7·A] `tenia_key` decide 401 → `key_invalida` vs `falta_key`. Sin él, un turno
        # con el vault vacío decía «el proveedor rechazó la credencial» sobre una credencial
        # que nunca existió — y mandaba a [Cambiar la llave] en vez de [Poner la llave].
        return _tr.ErrorDeModelo(
            _tr.desde_urllib(exc, url=base_url, tenia_key=tenia_key), str(exc))
    except Exception:                              # noqa: BLE001 — traducir jamás rompe el turno
        return exc


def _causa_cli_brain(cuerpo: str):
    """`error.causa` del cuerpo del `:8926`, si viene y si es del vocabulario cerrado."""
    if _tr is None:
        return None
    try:
        c = ((json.loads(cuerpo) or {}).get("error") or {}).get("causa")
        if not isinstance(c, dict) or c.get("causa") not in _tr.CAUSAS:
            return None
        return _tr.CausaModelo(
            causa=c["causa"], estado=_tr.ROTO, detalle=str(c.get("detalle") or "")[:200],
            evidencia=c.get("evidencia") if isinstance(c.get("evidencia"), dict) else {},
            reintentable=bool(c.get("reintentable")), retry_after_s=c.get("retry_after_s"),
            fuente=c.get("fuente") if c.get("fuente") in _tr.FUENTES else _tr.FUENTE_CLI)
    except Exception:                              # noqa: BLE001
        return None


def _causa_de_error(exc) -> Optional[str]:
    """[GATE 3 · obra B] El NOMBRE de la causa de un error YA TIPADO, o `None`.

    Lo usa el aviso de sustitución para decir POR QUÉ falló el primario. Devuelve el nombre
    del vocabulario cerrado y nada más: **jamás `str(exc)`**, que puede traer el cuerpo
    crudo del proveedor y no va a una pantalla (`errores_modelo.ErrorDeModelo:241`).

    Se apoya en `causa_de_excepcion`, que el traductor declara como «el único lugar donde se
    pregunta ¿esto ya está traducido?» (`errores_modelo.py:259`). Escribir acá un
    `getattr(exc, "causa", …)` propio sería el segundo lugar que decide lo mismo.

    `None` es una respuesta legítima y frecuente, no un borde a tapar: el primario puede
    haber cerrado **sin error alguno** —un razonador que gastó el budget pensando y no
    emitió texto— y ahí no hay causa que dar. Inventarle una sería mentir sobre por qué se
    sustituyó.
    """
    if exc is None or _tr is None:
        return None
    try:
        c = _tr.causa_de_excepcion(exc)
        return c.causa if c is not None else None
    except Exception:                              # noqa: BLE001 — avisar jamás rompe el turno
        return None


def _normalizar_uso(crudo: dict) -> Optional[dict]:
    """El `usage` del proveedor → el contrato de F2c. `None` si no hay NADA que informar.

    ⚠️ LA REGLA, y es la razón entera de que esta función exista: **`None` jamás cero**.
    Un cero se lee como «este turno salió gratis», que es una afirmación; «no lo sé» es
    otra cosa y tiene que verse distinta. El molde ya lo dice donde el CLI arma su annex:
    la señal explícita es `tokens_medidos`, y va AL LADO de `usage`, no adentro — para que
    `usage` siga teniendo forma OpenAI y cualquier consumidor lo entienda.

    Un proveedor que manda `{"total_tokens": 0}` sobre un turno que corrió está mintiendo,
    pero no nos toca a nosotros arreglarlo: se reporta `tokens_medidos: False` y los
    números en `None`. Repetir su cero como si fuera medición sería adoptar su mentira.
    """
    def _ent(v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    pt, ct = _ent(crudo.get("prompt_tokens")), _ent(crudo.get("completion_tokens"))
    tt = _ent(crudo.get("total_tokens"))
    if tt is None and (pt or ct):
        tt = (pt or 0) + (ct or 0)

    # `cost` es de OpenRouter y viene en USD; otros no lo mandan y queda `None`. Cero NO
    # es un costo válido acá por la misma razón: no se distingue de «no vino».
    usd = None
    try:
        c = float(crudo.get("cost"))
        usd = c if c > 0 else None
    except (TypeError, ValueError):
        usd = None

    medidos = tt is not None
    if not medidos and usd is None:
        return None                       # el proveedor no dijo nada: no hay evento que dar
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt,
            "tokens_medidos": medidos, "usd": usd}


def _stream_openai(base_url, model, key, system, prompt, max_tokens, temperature,
                   cli_model=None, effort=None) -> Iterator[tuple[str, str]]:
    body = {
        "model": model, "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }
    # ── [Gate 2 · F6-cierre · obra B] PEDIR EL USO ────────────────────────────────
    # F6-bis lo midió contra OpenRouter: el proveedor manda `usage` en el último chunk
    # del stream —{total_tokens, cost}— CON y SIN esta bandera, y acá se tiraba: el
    # bucle de abajo leía sólo `choices[0].delta`. No era que no se pudiera medir; era
    # un dato que llegaba y se descartaba, y la Sala mostraba el turno sin costo.
    # Se pide explícito igual, porque «lo manda igual» es cierto de OpenRouter HOY y no
    # es contrato de nadie: los que respetan la bandera la necesitan, y los que no, la
    # ignoran. NO se manda al cerebro CLI: ése ya publica su uso en su propio annex
    # (F2c) y su payload no se toca.
    if not _is_cli_brain_endpoint(base_url):
        body["stream_options"] = {"include_usage": True}
    # Slice D: these provider-specific controls only cross the managed CLI boundary.
    # Regular OpenAI-compatible providers keep their historical payload byte-for-byte.
    if cli_model:
        body["cli_model"] = str(cli_model)
    if effort:
        body["effort"] = str(effort)
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                 "User-Agent": "puppet-sala/1.0", "Accept": "text/event-stream"},
    )
    timeout = 120.0
    if _is_cli_brain_endpoint(base_url):
        try:
            timeout = max(timeout, float(os.environ.get("PUPPET_CLI_BRAIN_TIMEOUT", "180")) + 30.0)
        except ValueError:
            timeout = 210.0
    # F4b · obra 1 · el ABRIR se tipa. Se separa del bucle a propósito: acá es donde caen
    # el 401, el 429 y la red muerta —los tres que la Sala mostraba como string crudo— y
    # donde el `HTTPError` todavía tiene su cuerpo sin leer (el del `:8926` trae la causa
    # ya clasificada, y `read()` la consume una sola vez).
    #
    # ── [F6-cierre · obra C] EL TURNO HTTP, REGISTRADO ANTES DE ABRIR EL SOCKET ────
    # Se registra ANTES de `urlopen` porque el usuario puede apretar parar mientras el
    # pedido viaja: si el id naciera después, ese apretón no tendría a quién pararle nada
    # y el turno arrancaría igual. El cerebro CLI NO entra acá — ése publica su propio
    # `turno_id` en el annex (F2d) y tiene su propio `stop_turn`, que mata un proceso.
    _es_cli = _is_cli_brain_endpoint(base_url)
    _tid = None
    if not _es_cli:
        _tid = _turnos.abrir("local" if _es_ollama(base_url) else "api")
        yield ("turno", _tid)
    try:
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise _tipar(e, base_url, e.read().decode("utf-8", "replace"),
                         tenia_key=bool(key)) from None
        except Exception as e:                      # noqa: BLE001 — URLError/timeout/socket
            if _turnos.fue_detenido(_tid):
                raise _detenido(_tid) from None
            raise _tipar(e, base_url, tenia_key=bool(key)) from None
        if _tid:
            _turnos.atar(_tid, r)                   # desde acá, parar cierra ESTE socket
        reported_model = None
        with r:
            it = iter(r)
            while True:
                # El corte se mira ANTES de pedir la línea siguiente: si ya nos pidieron
                # parar, no hay razón para esperar un byte más del proveedor.
                if _turnos.fue_detenido(_tid):
                    raise _detenido(_tid)
                try:
                    raw = next(it)
                except StopIteration:
                    break
                except Exception as e:              # noqa: BLE001 — el socket se cerró
                    # Cerrar el socket despierta al lector con un error de red cualquiera,
                    # indistinguible de un corte real. Quién causó el corte es parte del
                    # corte: si fue el botón, se dice `turno_detenido`, no «se cayó la red».
                    if _turnos.fue_detenido(_tid):
                        raise _detenido(_tid) from None
                    raise _tipar(e, base_url, tenia_key=bool(key)) from None
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    # `model` is the provider's fact, not the request's intention.  Keep
                    # it as a side-channel so the raw Sala can expose the same
                    # `model_final` anti-grift signal as workspace_brain.
                    provider_model = obj.get("model")
                    if provider_model and str(provider_model) != reported_model:
                        reported_model = str(provider_model)
                        yield ("model_final", reported_model)
                    # [F4b · obra 2] EL `turno_id` DEL PRIMER CHUNK, que hasta ahora se
                    # tiraba. F2d lo puso ahí exactamente para esto —«es lo que le permite
                    # al cliente detener este turno»— y del otro lado nadie lo leía: el
                    # endpoint `/v1/turnos/detener` existía y NADIE lo llamaba, porque la
                    # Sala no tenía cómo saber QUÉ turno parar. Canal propio, igual que
                    # `thinking`: quien no lo entienda lo ignora y el chat sigue igual.
                    _ax = obj.get("aleph_cli_brain")
                    if isinstance(_ax, dict) and _ax.get("turno_id"):
                        yield ("turno", str(_ax["turno_id"]))
                    # ══ [GATE 3 · obra 6] LA MEMORIA PERDIDA SE DICE ═══════════════
                    # La obra 4 hizo que el agente recupere su conversación tras un
                    # reinicio. Cuando NO puede —store del CLI rotado, proyecto movido,
                    # archivo borrado— cae a sesión nueva y el `:8926` emite la causa
                    # SELLADA `sesion_perdida` en `annex.sesion.causa`
                    # (`cli_brain/server.py:635-640`). Hasta acá llegaba y **acá moría**:
                    # de todo el annex se leía `turno_id` y nada más.
                    #
                    # El usuario seguía escribiendo creyendo que el agente recuerda lo de
                    # ayer, y estaba en cero. **Perder memoria en silencio es peor que
                    # perderla con aviso.**
                    #
                    # Canal propio, calcando `modelo_sustituido` de la obra B: es un dato
                    # DEL TURNO, no texto de la respuesta, y dejarlo caer al acumulador
                    # metería un JSON crudo adentro de lo que la persona lee.
                    if isinstance(_ax, dict):
                        _ses_ax = _ax.get("sesion")
                        _c_ses = (_ses_ax or {}).get("causa") if isinstance(_ses_ax, dict) else None
                        if isinstance(_c_ses, dict) and _c_ses.get("causa") == _SESION_PERDIDA:
                            yield ("sesion_perdida", json.dumps({
                                "causa": _SESION_PERDIDA,
                                "detalle": str(_c_ses.get("detalle") or "")[:200],
                                # `reintentable` viaja tal como lo selló el vocabulario: la
                                # Sala NO lo deriva del nombre (obra 5, `autoReintentable`).
                                "reintentable": bool(_c_ses.get("reintentable")),
                            }))
                    # [F6-cierre · obra B] EL USO, con el contrato de F2c. Viene en el chunk
                    # FINAL (con `choices` vacío), así que se lee antes de mirar el delta.
                    _u = obj.get("usage")
                    if isinstance(_u, dict):
                        _uso = _normalizar_uso(_u)
                        if _uso is not None:
                            yield ("usage", json.dumps(_uso))
                    _d = (obj.get("choices") or [{}])[0].get("delta", {})
                    delta = _d.get("content")
                    # [UX·A4] THINKING REAL: los razonadores de Groq-directo
                    # (gpt-oss-120b, verificado con sonda viva 2026-07-09) emiten
                    # delta.reasoning — lo entregamos como canal aparte. Si el modelo no
                    # razona, el canal no existe y el panel del front jamás aparece.
                    think = _d.get("reasoning")
                except Exception:
                    delta, think = None, None
                if think:
                    yield ("thinking", think)
                if delta:
                    yield ("token", delta)
    finally:
        # SIEMPRE. Un registro que crece es una fuga con forma de tabla, y un id viejo
        # reusado pararía un turno que no es.
        _turnos.cerrar(_tid)


def _stream_anthropic(base_url, model, key, system, prompt, max_tokens, temperature) -> Iterator[tuple[str, str]]:
    """Adapter para la API de Anthropic (/v1/messages, SSE). Claude NO es OpenAI-compatible:
    system va aparte, headers x-api-key + anthropic-version, deltas content_block_delta."""
    body = {
        "model": model, "max_tokens": max_tokens, "temperature": temperature, "stream": True,
        "system": system, "messages": [{"role": "user", "content": prompt}],
    }
    base = base_url.rstrip("/")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01", "User-Agent": "puppet-sala/1.0",
                 "Accept": "text/event-stream"},
    )
    reported_model = None
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except Exception:
                continue
            if obj.get("type") == "message_start":
                provider_model = ((obj.get("message") or {}).get("model")
                                  if isinstance(obj.get("message"), dict) else None)
                if provider_model and str(provider_model) != reported_model:
                    reported_model = str(provider_model)
                    yield ("model_final", reported_model)
            elif obj.get("type") == "content_block_delta":
                d = obj.get("delta", {})
                if d.get("type") in ("text_delta", "text") and d.get("text"):
                    yield ("token", d["text"])
                # [UX·A4] si Anthropic entrega thinking_delta (BYOK con thinking activo),
                # pasa por el canal aparte. NO lo pedimos en el body (Opus 4.8 rechaza
                # thinking-con-budget): sin dato real → sin panel, jamás fabricado.
                elif d.get("type") == "thinking_delta" and d.get("thinking"):
                    yield ("thinking", d["thinking"])
            elif obj.get("type") == "message_stop":
                break


# [ticket 22 · Caso 3] CHAT ES EL DEFAULT. La conversación vive en burbujas; la obra es la
# excepción (entregable con cuerpo o pedido explícito). El sesgo anterior ("ante la duda,
# obra") invertía la proporción: 47 obras vs 14 chats en una jornada real — hilos inusables.
_CLASSIFY_SYS = (
    "Eres un clasificador de intención para un asistente. El usuario CONVERSA en burbujas de "
    "chat y solo A VECES pide una OBRA (un deliverable). Respondes UNA sola palabra, en "
    "minúscula, sin nada más: 'chat' u 'obra'.\n"
    "- 'obra' SOLO si el pedido PRODUCE un entregable con cuerpo propio que el usuario va a "
    "conservar: un informe, acta, documento, carta, planilla o tabla, checklist, gráfico, "
    "render, archivo o pieza de código — o si lo pide explícito («ármame/genérame/redáctame/"
    "escríbeme <ese entregable>», «haz el acta», «prepara el borrador del mail») — o si pide "
    "MODIFICAR un entregable ya producido («agrégale/súmale/cámbiale/sácale <algo> al acta/"
    "a la planilla/al checklist») — editar una obra es trabajo de obra, no charla.\n"
    "- 'chat' para TODO lo demás: preguntas (AUNQUE haga falta consultar herramientas o datos "
    "para contestarlas — consultar para responder es conversación, no una obra), "
    "confirmaciones, avisos, órdenes de recordar algo, aclaraciones, seguimientos, saludos, "
    "charla, y pedidos sobre la propia conversación («resúmeme el chat», «¿qué decidimos?»).\n"
    "Ante la duda: 'chat'. La obra es la excepción, no el default."
)

def classify_turn(prompt: str) -> str:
    """Cognición decide el TURNO: 'chat' (conversación) u 'obra' (deliverable). UNA palabra.
    Usa un modelo SIN canal de reasoning oculto (llama-3.3-70b) para que no gaste el budget
    en pensar y devuelva la etiqueta directo. Devuelve '' si no pudo (→ el caller cae a fallback)."""
    import json as _json
    a = _asm()
    key = a._resolve_cognition_key(_REPO)
    body = {
        # 8b-instant: clasificación trivial (1 palabra) + cuota por-modelo SEPARADA de llama-3.3
        # (que carga el produce-fallback + caption) → menos contención de rate-limit, más rápido.
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": _CLASSIFY_SYS},
                     {"role": "user", "content": (prompt or "")[:2000]}],
        "max_tokens": 4, "temperature": 0, "stream": False,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=_json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "puppet-sala/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            obj = _json.loads(r.read().decode("utf-8", "replace"))
        txt = (obj.get("choices") or [{}])[0].get("message", {}).get("content", "").strip().lower()
    except Exception:
        return ""
    if "obra" in txt:
        return "obra"
    if "chat" in txt:
        return "chat"
    return ""


_CAPTION_SYS = (
    "Acabas de entregarle una OBRA al usuario (un informe, paper, planilla, etc.). "
    "Escribe UNA sola línea, corta y natural, EN TU VOZ, presentándole lo que hiciste — "
    "como se lo dirías en un chat. Ejemplos de tono: 'aquí tienes el paper que encontré sobre X', "
    "'te armé el informe', 'listo, le sumé la conclusión'. "
    "REGLAS: máximo ~14 palabras · sin comillas · NO digas 'mira el canvas' ni 'a la derecha' "
    "(eso ya lo muestra la interfaz) · sin markdown · una sola oración."
)

# ── EL VOCABULARIO ÚNICO · consumidor 1/4 [Gate 4 · Fase 2 · obra 2.3] ────────
# Acá vivía la LISTA de 7 tipos: la más pobre de las cuatro que el censo §C.3 midió y
# la única que el modelo veía nunca. Un tipo agregado en cualquier otra lista no
# llegaba jamás al clasificador. Murió: el conjunto sale de `producible_by_llm` del
# vocabulario (platform/artifacts/vocabulary.py), que desde 2.3 GOBIERNA.
def _vocab():
    """EL vocabulario de tipos, o None si `platform/artifacts` no está alcanzable
    (dev sin platform/ en el path). `platform/` ya lo puso el rescate de
    aleph_paths de este mismo módulo."""
    try:
        from artifacts import vocabulary
        return vocabulary
    except Exception:                                     # pragma: no cover
        return None


_VOCAB = _vocab()

#: Glosa POR TIPO para el menú del clasificador. NO es una lista de tipos —es prosa
#: opcional—: el menú lo arma el vocabulario y un tipo sin glosa entra igual con su
#: `label_es`. Va en castellano a propósito: es texto que lee un modelo que responde
#: en castellano al usuario (ley 11 = el CÓDIGO en inglés, no el prompt).
_TYPE_GLOSS = {
    "informe":   "análisis, resumen, explicación, texto largo.",
    "documento": "carta, memo, correo, contrato, texto formal.",
    "planilla":  "tabla, hoja de cálculo, datos en filas y columnas, presupuesto.",
    "web":       "página web, landing, sitio, HTML, algo visual/interactivo para ver en el navegador.",
    "dashboard": "gráficos, visualización de datos, métricas/charts como foco principal.",
    "3d":        "escena o modelo 3D, visualización tridimensional, animación (three.js).",
    "imagen":    "una imagen o ilustración.",
    # [Convergencia · superficie 7] Se escribe con encabezados: cada `#` es un slide y lo
    # que sigue son sus viñetas. La glosa lo dice porque el modelo tiene que saber CÓMO se
    # estructura, no sólo que existe — sin esto escribiría prosa corrida y saldría un deck
    # de un solo slide.
    "presentacion": "deck de slides para exponer: se escribe en markdown y cada encabezado "
                    "abre un slide, con viñetas debajo.",
}


def _producible_types() -> tuple:
    if _VOCAB is None:                                    # fallo VISIBLE, jamás mudo
        log.error("stream_chat: EL vocabulario (platform/artifacts) no está disponible — "
                  "el clasificador queda con su default documentado ('informe'). "
                  "No se inventa una lista local: eso sería la 5ª lista.")
        return ("informe",)
    return tuple(_VOCAB.producible_by_llm())


def _gloss(t: str) -> str:
    g = _TYPE_GLOSS.get(t)
    if g:
        return g
    label = ((_VOCAB.TYPES.get(t) or {}).get("label_es") if _VOCAB else "") or t
    return label + "."


def _type_menu(types: tuple) -> str:
    return "\n".join('  · "%s": %s' % (t, _gloss(t)) for t in types)


_ARTIFACT_TYPES = _producible_types()

_ARTIFACT_ACTION_SYS = (
    "Eres un router para un asistente que mantiene MUCHAS obras (artifacts) por sesión. "
    "Te paso el mensaje del usuario y la lista de obras existentes (id · título · tipo). Decides "
    "(a) si el mensaje EDITA una obra existente o crea una NUEVA, y (b) si es nueva, de QUÉ TIPO. "
    "Responde SOLO un JSON, sin nada más:\n"
    "- {\"action\":\"edit\",\"artifact_id\":\"<id>\"} SOLO si el mensaje pide un CAMBIO sobre una obra "
    "YA existente — un verbo de modificación dirigido a ella ('agrégale', 'súmale la sección X', "
    "'cambia', 'sácale', 'corrige', 'revierte'). Elige el id que mejor coincida. "
    "[ticket 22] MENCIONAR una obra NO es editarla: una pregunta sobre la obra, un comentario, o "
    "un pedido de OTRO entregable que la referencia ('ármame una tabla como la del pañol') NO son edit.\n"
    "- {\"action\":\"new\",\"type\":\"<tipo>\"} si pide PRODUCIR un entregable (nuevo o distinto), o si "
    "NO hay obras todavía. Ante la duda edit/new: new (editar por error pisa trabajo; crear no).\n"
    "TIPOS válidos para 'new' (elige el que mejor describe el ENTREGABLE pedido, por su forma final):\n"
    + _type_menu(_ARTIFACT_TYPES) + "\n"
    "Ante la duda del tipo usa \"informe\". Un retoque explícito ('agrégale', 'ajústale') con UNA "
    "sola obra → edit esa; TODO lo demás dudoso → new."
)

def _coerce_type(t) -> str:
    """Normaliza el tipo que DECLARÓ la cognición a uno del vocabulario; default 'informe'.
    Las palabras coloquiales que escribe el modelo (grafico, carta, sitio, excel, foto…)
    viven en `vocabulary.LLM_ALIASES`: acá NO queda tabla. Sin vocabulario (fallo ya
    logueado arriba) cae al default documentado, jamás a una copia local."""
    if _VOCAB is None:
        return "informe"
    return _VOCAB.normalize_from_llm(t) or "informe"


def _norm_task(s) -> str:
    """Normaliza un pedido para comparar 'misma tarea' (minúsculas, sin acentos/puntuación)."""
    import unicodedata as _u
    s = _u.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def classify_artifact_action(prompt: str, artifacts: list) -> dict:
    """La cognición DECLARA la acción sobre artifacts + el TIPO de obra nueva:
    {'action':'new','type':'<tipo>'} | {'action':'edit','artifact_id':..}.
    El TIPO no se infiere por la forma del output; lo declara la cognición mirando QUÉ pide el
    usuario. Fallback: si no hay obras → new/informe; si no pudo → new/informe (no muta a ciegas).
    En edit, el tipo lo conserva la obra existente (el caller lo ignora acá)."""
    import json as _json
    arts = artifacts or []
    a = _asm()
    key = a._resolve_cognition_key(_REPO)
    # NO-STACK guardrail DURO (override del modelo): si el mensaje es ~igual al pedido (intent) que
    # YA produjo una obra → editá ESA, sin consultar al modelo (re-ask exacto = misma obra, no apila).
    _np = _norm_task(prompt)
    if _np:
        for x in arts:
            if _norm_task(x.get("intent") or x.get("title")) == _np:
                return {"action": "edit", "artifact_id": x.get("id")}
    listing = ("\n".join("- id=%s · título=%s · pedido=%s · tipo=%s"
                         % (x.get("id"), (x.get("title") or "")[:50], (x.get("intent") or "")[:70], x.get("type"))
                         for x in arts[:30])) if arts else "(ninguna todavía)"
    user = "Obras existentes:\n" + listing + "\n\nMensaje del usuario:\n" + (prompt or "")[:1500]
    body = {"model": "llama-3.1-8b-instant",   # routing acción+tipo: 8b basta (6/6) y descarga a llama-3.3
            "messages": [{"role": "system", "content": _ARTIFACT_ACTION_SYS}, {"role": "user", "content": user}],
            "max_tokens": 60, "temperature": 0, "stream": False}
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=_json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "puppet-sala/1.0"})
    # retry-on-429: el rate-limit por-minuto de Groq no debe corromper la decisión (un 429 silencioso
    # haría que un EDIT se trate como NEW y que el tipo caiga a 'informe'). Backoff corto, luego default.
    import time as _time
    parsed = {}
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                obj = _json.loads(r.read().decode("utf-8", "replace"))
            txt = (obj.get("choices") or [{}])[0].get("message", {}).get("content", "")
            m = re.search(r"\{.*\}", txt, re.DOTALL)
            parsed = _json.loads(m.group(0)) if m else {}
            break
        except Exception as e:
            if getattr(e, "code", None) == 429 and _attempt < 2:
                _time.sleep(1.5 * (_attempt + 1)); continue
            return {"action": "new", "type": "informe"}
    # EDIT solo si hay obras y el id existe de verdad (anti-alucinación); el tipo lo conserva la obra
    if arts and parsed.get("action") == "edit":
        aid = parsed.get("artifact_id") or parsed.get("target_artifact_id")   # acepta ambos nombres
        if any(x.get("id") == aid for x in arts):
            return {"action": "edit", "artifact_id": aid}
    # cualquier otro caso → NEW con el tipo declarado (normalizado), default informe
    return {"action": "new", "type": _coerce_type(parsed.get("type"))}


def obra_caption(task: str, excerpt: str, editing: bool = False) -> dict:
    """Genera (con el modelo) la línea natural que acompaña a la obra en el chat. Devuelve
    {message, model, usage} para que el caller pueda probar que es output REAL, no hardcode.
    Modelo sin reasoning oculto (llama-3.3-70b) para que devuelva la línea directo."""
    import json as _json
    a = _asm()
    key = a._resolve_cognition_key(_REPO)
    verbo = "Actualizaste" if editing else "Creaste"
    user = (verbo + " esto para el usuario.\nLo que pidió: " + (task or "")[:400] +
            "\nResumen de lo que entregaste:\n" + (excerpt or "")[:700])
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": _CAPTION_SYS}, {"role": "user", "content": user}],
        "max_tokens": 40, "temperature": 0.7, "stream": False,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=_json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "puppet-sala/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            obj = _json.loads(r.read().decode("utf-8", "replace"))
        msg = (obj.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        msg = msg.strip('"').strip().split("\n")[0][:200]
        return {"message": msg, "model": obj.get("model"), "usage": obj.get("usage")}
    except Exception as exc:
        return {"message": "", "model": None, "usage": None, "error": str(exc)}


def stream_answer(recipe: dict, prompt: str,
                  byok_resolver: Optional[Callable[[str], str]] = None,
                  extra_system: Optional[str] = None,
                  method_active: bool = False,
                  lang: Optional[str] = None) -> Iterator[tuple[str, str]]:
    """Yields los deltas de texto del modelo (stream=true). Chat directo, sin tools/gate.
    BYOK-LLM: si model.byok_ref + resolver → corre con la key del usuario (su API).

    RESILIENCIA (obra que SÍ sale): el primario puede 429ear (rate-limit por-minuto de
    Groq) o devolver content VACÍO (gpt-oss-120b es razonador: a veces gasta el budget en
    pensar y no emite texto). En ambos casos el síntoma era "obra vacía → 'reformula'". Si
    el primario falla ANTES de emitir nada, o cierra sin haber emitido contenido, caemos al
    `fallback` (llama-3.3-70b, no-razonador, confiable) sobre la MISMA key/base_url. Solo
    para la cognición incluida: si es BYOK, respetamos la elección del usuario (no cambiamos
    su modelo a la fuerza) y propagamos el error."""
    model = recipe.get("model", {}) or {}
    # El caller ya entrega una configuración ejecutable. La selección raw la materializa
    # el selector canónico (`_modelo_crudo`); conservar aquí esos campos explícitos evita
    # que un `brain_provider`/alias antiguo arrastre controles CLI hacia otro endpoint.
    # Las recetas completas siguen pasando por el resolver único en el executor/brain.
    base_url = (model.get("base_url") or "https://api.groq.com/openai/v1").rstrip("/")
    primary = model.get("primary") or "openai/gpt-oss-120b"
    fallback = model.get("fallback")
    max_tokens = int(model.get("max_tokens", 1400) or 1400)
    temperature = float(model.get("temperature", 0.3) or 0.3)
    is_cli = _is_cli_brain_endpoint(base_url)
    cli_model = (str(model.get("cli_model") or "").strip()) or None
    effort_pref = (str(model.get("effort") or "").strip().lower()) or None
    if effort_pref == "auto":
        effort = "high" if method_active else "low"
    elif effort_pref in {"low", "medium", "high", "max"}:
        effort = effort_pref
    else:
        effort = None
    system = _system_content(recipe, lang)
    # [UX·B5] las instrucciones persistentes del dueño también rigen la CHARLA pura
    # (el router las arma desde la DB, scoped a la sesión; acá solo se componen).
    if extra_system and str(extra_system).strip():
        system = system + "\n" + str(extra_system).strip()
    key, _is_byok = _resolve_llm_key(recipe, byok_resolver)
    if is_cli:
        # EL TERCER CAMINO AL :8926, y el único que se había quedado afuera de la regla.
        # `recipe_assembler.py` y `workspace_brain.py` ya vaciaban la llave de cognición
        # del dev antes de hablarle al puerto local (review HIGH #14); acá seguía viajando.
        # Ahora, además de no mandarla, va la LLAVE DE INSTANCIA — que es lo que el server
        # exige desde que el puerto dejó de estar abierto a cualquier proceso local.
        from cli_brain import credencial as _cred
        key, _is_byok = _cred.leer(), False

    def _stream(m):
        if _is_anthropic(base_url):
            yield from _stream_anthropic(base_url, m, key, system, prompt, max_tokens, temperature)
        else:
            yield from _stream_openai(
                base_url, m, key, system, prompt, max_tokens, temperature,
                cli_model=cli_model if is_cli else None,
                effort=effort if is_cli else None,
            )

    # [UX·A4] el stream entrega TUPLAS (kind, s) con kind ∈ 'token'|'thinking'.
    # `produced` cuenta SOLO texto: un razonador que gastó el budget pensando sin emitir
    # contenido sigue cayendo al fallback (la resiliencia de siempre, intacta).
    produced = False
    primary_error = None
    try:
        for item in _stream(primary):
            if item and item[0] == "token" and item[1]:
                produced = True
            yield item
    except Exception as exc:  # 429 / corte de red / etc. antes (o a mitad) del stream
        primary_error = exc

    if produced:
        return  # el primario emitió contenido (aunque cortara a mitad): la obra ya salió

    # primario VACÍO o caído sin emitir nada → fallback (solo cognición incluida, mismo Groq)
    #
    # ══ [GATE 3 · obra B · ACTA 2] SUSTITUIR SÍ, EN SILENCIO NO ════════════════════════
    # Hasta acá esto cambiaba de modelo a mitad de turno y no emitía NADA: la auditoría 5
    # lo midió como el «corte 2» y este archivo no nombraba `degraded`, `tier` ni
    # `model_final` en ninguna de sus líneas. El usuario elegía un cerebro, corría con otro,
    # y no había forma de enterarse.
    #
    # La sustitución SE MANTIENE —el acta la ratifica: que no se caiga el trabajo— y ahora
    # se ANUNCIA, antes de emitir el primer token del respaldo, con los TRES datos que el
    # acta pide: qué se pidió, qué entró, y por qué falló el primero. La causa del fallo
    # original sale del VOCABULARIO EXISTENTE (el traductor de F4b, el mismo que ya tipa los
    # errores de este archivo), jamás de texto libre: `primary_error` puede traer el cuerpo
    # crudo del proveedor y eso no va a una pantalla.
    #
    # `causa_origen` es None cuando el primario no reventó sino que **cerró sin emitir
    # contenido** (el razonador que gasta el budget pensando). Ese caso NO tiene causa
    # tipada porque no hubo error: se dice así, sin inventarle una.
    # ── [obra B · O8] `not _is_byok` — MEDIDO, Y SE QUEDA ─────────────────────────────
    # La pregunta era si esto es una limitación real o un resto. Es real, y por dos motivos
    # que se midieron:
    #
    #   1 · `_is_byok` no dice «la receta declara BYOK»: dice **que la llave del usuario se
    #       resolvió de verdad** (`_resolve_llm_key:82` devuelve True sólo si `byok_resolver`
    #       entregó una key). O sea que la condición es exactamente «estamos gastando la
    #       llave de esta persona», que es la única sobre la que vale decidir.
    #   2 · una receta BYOK bien compilada sale con `fallback: null`
    #       (`cuarto.models.js:318`), así que en el camino feliz este guard ni siquiera se
    #       ejecuta. Pero **no es redundante**: una receta que lleve `byok_ref` compilada por
    #       la otra rama (`cuarto.models.js:341`) se lleva un `fallback` HORNEADO de Groq
    #       (`:334`, `"openai/gpt-oss-20b"`). Sin este guard, un fallo del modelo del usuario
    #       lo mandaría a correr contra otro proveedor sin preguntarle.
    #
    # LA ASIMETRÍA QUEDA DECLARADA, y ahora es defendible: con la llave del usuario NO se
    # sustituye —se propaga el error, que es visible y tipado desde F4b— y con la cognición
    # incluida SÍ se sustituye y se AVISA. Antes las dos mitades eran mudas y la diferencia
    # parecía arbitraria; ahora cada una dice lo suyo.
    if fallback and fallback != primary and not _is_byok:
        yield ("modelo_sustituido", json.dumps({
            "causa": "modelo_sustituido",
            "pedido": primary,
            "usado": fallback,
            "causa_origen": _causa_de_error(primary_error),
            "origen": "aleph",
            "reintentable": False,
        }))
        yield from _stream(fallback)
        return

    if primary_error is not None:  # sin fallback usable → que el canal SSE reporte el error real
        raise primary_error


__all__ = ["stream_answer"]
