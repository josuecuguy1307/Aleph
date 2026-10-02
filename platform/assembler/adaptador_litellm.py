#!/usr/bin/env python3
"""adaptador_litellm.py — LA FRONTERA CON LiteLLM (Gate 2 · F3).

Pieza NUEVA y AISLADA. Nadie la usa todavía: el cableo a los consumidores es F4. Patrón
D1/F1 — existe, se prueba, no sostiene nada.

QUÉ ES: la única puerta por la que LiteLLM puede entrar al producto. Todo lo que la
auditoría 1 midió como deshonesto queda del lado de afuera de esta puerta:

  · un 500 que en realidad es «no hay red» (§P1.d)   → acá sale `sin_red`
  · un `Usage(0,0,0)` presentado como medición (§P3.a) → acá sale `tokens_medidos=False`
  · un estimado de tiktoken vestido de dato real (§P3.b) → idem, y se detecta MIRANDO si
    algún chunk trajo `usage`, no adivinando
  · `_hidden_params["litellm_model_name"]`, que tras un fallback MIENTE (§P2.b) → se ignora
  · una conexión saliente en el `import` y la lectura del `.env` del CWD (§P4.a/b) → selladas
  · fallbacks: los maneja `_route_chat` río arriba. Acá van APAGADOS.

EL PIN — `litellm==1.91.4`, exacto y no `>=`. Medido el 2026-08-03:

    v1.91.4 → `litellm-1.91.4-py3-none-any.whl`   universal, CERO .so, sin toolchain
    v1.92.0 → wheels por plataforma, y NINGUNO de macOS: en Mac cae al sdist y compila
              una extensión Rust con maturin (~3,5 min, y sólo si hay cargo instalado)

El criterio es el bundle: un CI de macOS que tenga que instalar Rust para empaquetar la
`.app` es una dependencia de build que no queremos. Costo del pin, medido contra `v1.94.0`:
1.154 commits (456 fix, 167 feat) y exactamente DOS directorios de provider nuevos —
`gdc` y `tencent`— ninguno de los que usamos. `rust_bridge` viaja igual en la 1.91.4 pero
sin la extensión: `native_bridge_available()` devuelve False y degrada solo (verificado).
Peso: 168 MB netos sobre un venv limpio, 49 paquetes.

PURO SALVO EL BORDE: este módulo no importa `litellm` al importarse. `init_litellm()` es
lo que sella el entorno y recién ahí importa. Así el árbol sigue arrancando sin la
dependencia instalada, y la vara puede probar el sellado ANTES del primer import.

CONTRA EL DISEÑO DE REPAIR: `DISEÑO-REPAIR-v1.md` §2.1 (DECISIÓN 2.A) declara que
«temporal» de repair ≡ `reintentable` de `errores_modelo`, y §2.3 que un `retry_after_s`
manda sobre su curva de backoff. Este adaptador emite exactamente esos dos campos, vía
`errores_modelo.desde_litellm`, sin taxonomía propia.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

import errores_modelo as _tr           # noqa: E402  (F1: la taxonomía cerrada)
import models as _models               # noqa: E402  (el registro de alias; se lee, no se toca)

# ── EL ENTORNO SELLADO ─────────────────────────────────────────────────────────────
# Estas dos van ANTES del primer import de litellm porque el módulo las lee en su
# `__init__`. Después ya no sirven.
#   LITELLM_LOCAL_MODEL_COST_MAP=True  → mata el GET a raw.githubusercontent.com que
#       `litellm/__init__.py` hace en el import (medido en la auditoría 1 §P4.a).
#   LITELLM_MODE=PRODUCTION            → mata el `load_dotenv()` del import. En un bundle
#       PyInstaller (`sys.frozen`) ese dotenv lee el `.env` del CWD y lo mete en
#       os.environ (§P4.b) — o sea, cualquier `.env` que el usuario tenga al lado.
_ENV_SELLADO = {
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "LITELLM_MODE": "PRODUCTION",
}

#: El mismo techo que `assembler._chat` (PUPPET_HTTP_TIMEOUT, default 60). LiteLLM trae
#: 6000 s por defecto — cien minutos, que para una app de escritorio es «sin timeout».
TIMEOUT_S = float(os.environ.get("PUPPET_HTTP_TIMEOUT", "60"))

_litellm = None          # el módulo, una vez sellado e importado
_motivo_no = ""


def sellar_entorno() -> dict:
    """Fija las env vars del sellado. Devuelve lo que quedó puesto (para la vara).

    Idempotente y explícito: si alguien ya las puso distintas a propósito, se respeta —
    pero se reporta, porque un `LITELLM_LOCAL_MODEL_COST_MAP=False` heredado del ambiente
    volvería a abrir la conexión del import sin que nadie lo note.
    """
    puesto = {}
    for k, v in _ENV_SELLADO.items():
        anterior = os.environ.get(k)
        if anterior is None:
            os.environ[k] = v
        puesto[k] = os.environ[k]
    return puesto


def init_litellm(*, timeout: Optional[float] = None):
    """Sella el entorno, importa litellm y le apaga todo lo que sale de la máquina.

    Idempotente. Devuelve el módulo, o levanta `RuntimeError` si no está instalado — la
    ausencia de la dependencia es un fallo honesto, no un import silencioso a medias.
    """
    global _litellm, _motivo_no
    if _litellm is not None:
        return _litellm
    sellar_entorno()
    try:
        import litellm as _l                       # noqa: PLC0415 — a propósito: DESPUÉS del sellado
    except ImportError as e:                       # pragma: no cover
        _motivo_no = f"litellm no está instalado: {e}"
        raise RuntimeError(_motivo_no) from e

    # Todo lo que sigue apaga comportamientos que la auditoría 1 midió como activos por
    # defecto. Ninguno es opinión: cada línea cierra un hallazgo con número.
    _l.suppress_debug_info = True                  # §P4.h — prints ANSI a stdout por cada error
    _l.disable_hf_tokenizer_download = True        # §P4.g — descarga de tokenizers desde HF
    _l.telemetry = False                           # bandera muerta en el SDK, pero cuesta cero
    _l.request_timeout = timeout if timeout is not None else TIMEOUT_S   # §2 — 6000 s por defecto
    # FALLBACKS APAGADOS. El cascade es de `_route_chat` río arriba, que además lo SURFACEA
    # (`degraded` + cost-event). Si litellm también cascadeara tendríamos dos capas de
    # sustitución y una sola de narración.
    _l.fallbacks = None
    _l.model_fallbacks = None
    _l.context_window_fallbacks = None
    _l.content_policy_fallbacks = None
    _l.num_retries = None                          # los reintentos los decide repair (§3)
    _l.cache = None
    _litellm = _l
    return _l


def disponible() -> tuple[bool, str]:
    """(hay_litellm, motivo). Para que un caller pueda decidir sin capturar excepciones."""
    if _litellm is not None:
        return True, f"litellm {getattr(_litellm, '__version__', '?')}"
    try:
        init_litellm()
        return True, "litellm listo"
    except RuntimeError as e:
        return False, str(e)


def _reset_para_varas() -> None:
    """Sólo para varas: olvida el módulo cacheado."""
    global _litellm, _motivo_no
    _litellm, _motivo_no = None, ""


# ══ EL RESULTADO ═══════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class RespuestaModelo:
    """Lo que sale de esta frontera. Mismo contrato de honestidad que F2c."""

    ok: bool
    texto: str = ""
    #: El modelo que el PROVEEDOR dijo haber usado (`response.model`). Jamás el pedido.
    model_final: Optional[str] = None
    #: {'prompt_tokens': int|None, 'completion_tokens': int|None}. None = no hay dato.
    tokens: dict = field(default_factory=lambda: {"prompt_tokens": None,
                                                  "completion_tokens": None})
    #: ¿Los tokens los reportó el PROVEEDOR? False = no medible (jamás «cero medido»).
    tokens_medidos: bool = False
    #: Costo sólo si se pudo calcular sobre tokens medidos. None jamás 0.0.
    usd: Optional[float] = None
    #: `CausaModelo` serializada del traductor F1 cuando ok=False.
    causa: Optional[dict] = None
    #: Las tool-calls que el modelo pidió, en la forma OpenAI
    #: (`[{id, type:"function", function:{name, arguments}}]`). `[]` = no pidió ninguna.
    #:
    #: F4a · AGREGADO AL CABLEAR, y por una razón que sólo se ve cableando: el loop del
    #: assembler es un tool-use loop, así que una respuesta que sólo lleva `texto` **pierde
    #: en silencio** todo lo que el modelo quiso ejecutar. F3 no lo necesitaba (no
    #: sostenía nada); el primer consumidor sí. Sin esto, prender la perilla habría
    #: convertido cada tool-call del tier oss-direct en una respuesta vacía.
    tool_calls: list = field(default_factory=list)
    #: `finish_reason` del proveedor tal cual. El loop lo mira para decidir si sigue.
    finish_reason: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {"ok": self.ok, "texto": self.texto, "model_final": self.model_final,
                "tokens": dict(self.tokens), "tokens_medidos": self.tokens_medidos,
                "usd": self.usd, "causa": self.causa,
                "tool_calls": list(self.tool_calls), "finish_reason": self.finish_reason,
                "meta": dict(self.meta)}


def _entero_o_none(v: Any) -> Optional[int]:
    """Guarda de tipo: un entero es un entero; lo demás es AUSENCIA, no cero.

    Es la MISMA regla que `cli_brain/base.tokens_o_none` (F2c) y está repetida a
    propósito: `cli_brain` es un consumidor, y una pieza nueva de la frontera no puede
    depender de él sin invertir las capas. Ocho líneas duplicadas cuestan menos que ese
    acoplamiento. Si algún día hay una tercera copia, el lugar de la única es
    `errores_modelo`, que las dos capas ya importan.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float) and v.is_integer():
        return int(v) if v >= 0 else None
    return None


def _tokens_de(usage: Any) -> tuple[dict, bool]:
    """`usage` de litellm → (dict, se_midio). La regla de F2c, aplicada acá.

    EL CASO QUE ESTO ATRAPA (§P3.a): un provider que no manda `usage` hace que litellm
    devuelva `Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)` — ceros con
    aspecto de medición. Un turno de inferencia con CERO tokens de prompt no existe: si
    los dos son 0, no hubo dato.
    """
    if usage is None:
        return {"prompt_tokens": None, "completion_tokens": None}, False
    leer = (usage.get if isinstance(usage, dict) else (lambda k: getattr(usage, k, None)))
    pt = _entero_o_none(leer("prompt_tokens"))
    ct = _entero_o_none(leer("completion_tokens"))
    if (pt or 0) == 0 and (ct or 0) == 0:
        return {"prompt_tokens": None, "completion_tokens": None}, False
    return {"prompt_tokens": pt, "completion_tokens": ct}, (pt is not None or ct is not None)


def _usd_de(respuesta: Any, medidos: bool) -> Optional[float]:
    """El costo, sólo si hay sobre qué calcularlo.

    `_hidden_params['response_cost']` vale `0.0` tanto cuando el modelo es gratis como
    cuando litellm no supo tarifarlo (medido: §P3.a devolvió 0.0 sobre un usage inventado).
    Como no se pueden distinguir, un 0.0 se reporta como None — el mismo principio que
    `models.PRICES`: sin tarifa que podamos sostener, `usd` es None, no cero.
    """
    if not medidos:
        return None
    hp = getattr(respuesta, "_hidden_params", None) or {}
    v = hp.get("response_cost") if isinstance(hp, dict) else None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _model_final_de(respuesta: Any) -> Optional[str]:
    """`response.model` — lo que el PROVEEDOR reportó.

    NO se mira `_hidden_params['litellm_model_name']`: tras un fallback ese campo conserva
    el modelo PEDIDO, no el que respondió (medido en la auditoría 1 §P2.b). Es el campo
    que miente, y por eso está nombrado acá sólo para decir que no se usa.
    """
    m = getattr(respuesta, "model", None)
    if m is None and isinstance(respuesta, dict):
        m = respuesta.get("model")
    m = str(m or "").strip()
    return m or None


def _texto_de(respuesta: Any) -> str:
    try:
        ch = respuesta.choices[0] if not isinstance(respuesta, dict) else respuesta["choices"][0]
        msg = getattr(ch, "message", None) or (ch.get("message") if isinstance(ch, dict) else None)
        if msg is None:
            return ""
        c = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        return c or ""
    except Exception:                                   # noqa: BLE001
        return ""


def _mensaje_de(respuesta: Any) -> Any:
    """El `message` del choice 0, sea objeto o dict. `None` si no hay."""
    try:
        ch = respuesta.choices[0] if not isinstance(respuesta, dict) else respuesta["choices"][0]
    except Exception:                                   # noqa: BLE001
        return None
    return getattr(ch, "message", None) or (ch.get("message") if isinstance(ch, dict) else None)


def _tool_calls_de(respuesta: Any) -> list:
    """`message.tool_calls` → la forma OpenAI en dicts planos, o `[]`.

    Se serializa a mano y no con `.model_dump()` a propósito: el loop del assembler lee
    EXACTAMENTE tres cosas (`id`, `function.name`, `function.arguments`) y `arguments` le
    llega SIEMPRE como string JSON por el camino urllib. Un dump del objeto de litellm
    traería campos extra y, peor, podría entregar `arguments` ya deserializado según la
    versión — y `json.loads` sobre un dict revienta. Se normaliza acá, una vez.
    """
    msg = _mensaje_de(respuesta)
    if msg is None:
        return []
    crudas = getattr(msg, "tool_calls", None)
    if crudas is None and isinstance(msg, dict):
        crudas = msg.get("tool_calls")
    if not crudas:
        return []
    salida = []
    for tc in crudas:
        try:
            leer = (tc.get if isinstance(tc, dict) else (lambda k: getattr(tc, k, None)))
            fn = leer("function")
            leer_fn = (fn.get if isinstance(fn, dict) else (lambda k: getattr(fn, k, None)))
            args = leer_fn("arguments")
            if not isinstance(args, str):
                # Un dict/None se vuelve el string JSON que el loop espera. `json` entra
                # acá y no arriba porque es el único lugar del módulo que lo necesita.
                import json as _json
                args = _json.dumps(args or {})
            salida.append({
                "id": str(leer("id") or ""),
                "type": str(leer("type") or "function"),
                "function": {"name": str(leer_fn("name") or ""), "arguments": args},
            })
        except Exception:                               # noqa: BLE001 — una tool-call rara no tumba el turno
            continue
    return salida


def _finish_de(respuesta: Any) -> Optional[str]:
    try:
        ch = respuesta.choices[0] if not isinstance(respuesta, dict) else respuesta["choices"][0]
    except Exception:                                   # noqa: BLE001
        return None
    fr = getattr(ch, "finish_reason", None)
    if fr is None and isinstance(ch, dict):
        fr = ch.get("finish_reason")
    return str(fr) if fr else None


def _falla(exc: Any, *, url: str = "", tenia_key: bool = True) -> RespuestaModelo:
    """Cualquier excepción de litellm → `RespuestaModelo` con la causa de F1.

    Éste es el primer uso real de `desde_litellm`. La fila que importa es la P1.d: un
    `InternalServerError` con `status_code=500` cuyo `__context__` es un ConnectError sale
    de acá como `sin_red`, no como `proveedor_caido`.

    Y la segunda, que ESTA vía descubrió midiendo: un 401 llega como `BadRequestError` con
    `status_code=401`. Desde F2d el traductor le da precedencia al status en los cinco
    códigos accionables, así que de acá sale `key_invalida` — el adaptador no interviene,
    sigue sin taxonomía propia.

    [F7·A·bis] Y `tenia_key` viaja igual que por urllib: F7·A lo cableó de un solo lado y
    las dos vías empezaron a dar veredictos distintos ante el MISMO 401 (`verify_f4a` §4c
    lo cazó). El adaptador sigue sin taxonomía: sólo pasa el dato que ya tenía.

    ⚠️ EL DATO LO PONE EL LLAMANTE, NO SE INFIERE DE `kw["api_key"]`. Es tentador mirar el
    centinela `sin-auth` de `_kwargs_de`, pero ese centinela CONFUNDE dos cosas: «este
    endpoint no lleva auth» (ollama, el shim, cli_brain) y «lleva auth y no teníamos
    llave». Sólo el llamante sabe cuál de las dos es — y es el MISMO criterio que usa la
    vía urllib (`_tipado(..., tenia_key=bool(api_key))`), que es lo que hace que las dos
    contesten igual. Default `True` = el comportamiento de siempre para quien no lo sepa.
    """
    causa = _tr.desde_litellm(exc, url=url, tenia_key=tenia_key).como_dict()
    return RespuestaModelo(ok=False, causa=causa,
                           meta={"excepcion": type(exc).__name__})


# ══ LA SUPERFICIE ══════════════════════════════════════════════════════════════════
def _kwargs_de(alias: str, mensajes: list, *, base_url_hint: str = "",
               max_tokens: Optional[int] = None, temperature: Optional[float] = None,
               timeout: Optional[float] = None, extra: Optional[dict] = None) -> dict:
    """Resuelve el alias contra `models.py` y arma el kwargs de litellm.

    `models.resolve` es la fuente: mismo registro que usa el assembler, para que un alias
    signifique lo mismo por las dos vías. La key sale de su `key_env`; si el endpoint no
    lleva auth (ollama), va vacía.
    """
    r = _models.resolve(alias, base_url_hint=base_url_hint)
    kw: dict = {
        "model": r.model,
        # EL PROVIDER SE DECLARA, NO SE INFIERE. `models.ALIASES` guarda ids PELADOS
        # (`qwen3:8b`, `openai/gpt-oss-120b`, `anthropic/claude-opus-4.8`) porque
        # `assembler._chat` los postea tal cual contra el `base_url` de la entrada: quien
        # decide el provider es la URL, no el nombre. Si dejáramos que litellm infiriera,
        # un `qwen3:8b` sin prefijo conocido termina en un BadRequest 400 antes de salir
        # de la máquina (medido al escribir esto). `custom_llm_provider="openai"` le dice
        # «hablá OpenAI-compat contra ese api_base», que es EXACTAMENTE lo que hace `_chat`
        # — y todos nuestros endpoints (Groq · OpenRouter · Gemini-compat · ollama/v1 ·
        # el shim · cli_brain) lo son.
        "custom_llm_provider": "openai",
        "messages": list(mensajes or []),
        "api_base": r.base_url or None,
        "timeout": timeout if timeout is not None else TIMEOUT_S,
        # FALLBACKS APAGADOS también por llamada, no sólo global.
        "num_retries": 0,
    }
    # LA KEY. `_chat` simplemente no manda cabecera `Authorization` cuando no hay key, pero
    # el cliente `AsyncOpenAI` que litellm usa por debajo EXIGE una string no vacía y
    # revienta en el constructor si falta — antes de tocar la red, y envuelto como un
    # `InternalServerError` 500 que parece del proveedor (medido al escribir esto: un
    # endpoint local sin `key_env` daba `proveedor_caido` sin haber salido de la máquina).
    # Para los endpoints sin auth (ollama, el shim, cli_brain) va un centinela explícito:
    # viaja como `Bearer sin-auth`, que esos servicios ignoran, y así el fallo que se ve es
    # el del proveedor y no el nuestro.
    kw["api_key"] = (os.environ.get(r.key_env) or "") if r.key_env else ""
    if not kw["api_key"]:
        kw["api_key"] = "sin-auth"
    if max_tokens is not None:
        kw["max_tokens"] = int(max_tokens)
    if temperature is not None:
        kw["temperature"] = float(temperature)
    if extra:
        kw.update(extra)
    return kw


async def acompletar(alias: str, mensajes: list, *, base_url_hint: str = "",
                     max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                     timeout: Optional[float] = None, tenia_key: bool = True,
                     extra: Optional[dict] = None) -> RespuestaModelo:
    """UN completion, sin streaming. Async nativo (`acompletion`), jamás el sync.

    `tenia_key` sólo se usa si algo falla: separa `falta_key` de `key_invalida` en un 401.
    Lo pone el llamante — ver `_falla` para por qué NO se infiere del kwargs."""
    l = init_litellm()
    kw = _kwargs_de(alias, mensajes, base_url_hint=base_url_hint, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout, extra=extra)
    url = kw.get("api_base") or ""
    try:
        resp = await l.acompletion(**kw)
    except Exception as exc:                            # noqa: BLE001 — se traduce, no se propaga
        return _falla(exc, url=url, tenia_key=tenia_key)
    tokens, medidos = _tokens_de(getattr(resp, "usage", None))
    return RespuestaModelo(
        ok=True, texto=_texto_de(resp), model_final=_model_final_de(resp),
        tokens=tokens, tokens_medidos=medidos, usd=_usd_de(resp, medidos),
        tool_calls=_tool_calls_de(resp), finish_reason=_finish_de(resp),
        meta={"alias": alias, "stream": False},
    )


async def acompletar_stream(alias: str, mensajes: list, *, base_url_hint: str = "",
                            max_tokens: Optional[int] = None,
                            temperature: Optional[float] = None,
                            timeout: Optional[float] = None, tenia_key: bool = True,
                            extra: Optional[dict] = None) -> AsyncIterator:
    """Streaming. Rinde `('texto', str)` por delta y `('final', RespuestaModelo)` al cerrar.

    CIERRE GARANTIZADO. `CustomStreamWrapper` de litellm NO tiene `close()` síncrono
    (auditoría 1 §P6.a: tras `break`+`del`+`gc` el servidor entregó los 300 chunks). Sólo
    tiene `aclose()`, y hay que llamarlo. El `try/finally` de acá lo hace pase lo que pase,
    incluida la cancelación de la Task — que es el camino por el que el usuario aprieta
    «parar».

    USAGE HONESTO EN STREAMING. LiteLLM, si el provider no manda `usage`, lo ESTIMA con
    tiktoken y lo entrega en el mismo campo que un dato real (§P3.b). Acá no se adivina:
    se MIRA si algún chunk trajo `usage` del provider. Si ninguno lo trajo, el usage final
    es una estimación de litellm y sale `tokens_medidos=False`, aunque tenga números.
    """
    l = init_litellm()
    kw = _kwargs_de(alias, mensajes, base_url_hint=base_url_hint, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout, extra=extra)
    kw["stream"] = True
    # Pedirle al provider que mande el usage al final. Si lo manda, es MEDIDO; si no lo
    # manda, ningún chunk lo va a traer y eso es justo lo que queremos detectar.
    kw.setdefault("stream_options", {"include_usage": True})
    url = kw.get("api_base") or ""

    try:
        stream = await l.acompletion(**kw)
    except Exception as exc:                            # noqa: BLE001
        yield "final", _falla(exc, url=url, tenia_key=tenia_key)
        return

    partes: list[str] = []
    usage_del_provider = None
    modelo = None
    n_chunks = 0
    try:
        async for chunk in stream:
            n_chunks += 1
            if modelo is None:
                modelo = _model_final_de(chunk)
            u = getattr(chunk, "usage", None)
            if u is not None:
                # ¡El provider lo mandó! Esto es lo único que cuenta como medido.
                usage_del_provider = u
            try:
                d = chunk.choices[0].delta
                txt = getattr(d, "content", None)
            except Exception:                           # noqa: BLE001
                txt = None
            if txt:
                partes.append(txt)
                yield "texto", txt
    except Exception as exc:                            # noqa: BLE001
        yield "final", _falla(exc, url=url, tenia_key=tenia_key)
        return
    finally:
        # EL CIERRE. Sin esto el provider sigue generando y facturando después del corte.
        try:
            cerrar = getattr(stream, "aclose", None)
            if cerrar is not None:
                await cerrar()
        except Exception:                               # noqa: BLE001 — cerrar nunca rompe
            pass

    texto = "".join(partes)
    tokens, medidos = _tokens_de(usage_del_provider)

    # ── LA DETECCIÓN DE LA ESTIMACIÓN ──────────────────────────────────────────────
    # MEDIDO al escribir esto, y NO es lo que suponíamos: litellm no se limita a dejar el
    # usage vacío cuando el provider no lo manda — INYECTA un chunk con un `usage` que él
    # mismo calculó con tiktoken. O sea que «¿algún chunk trajo usage?» devuelve True
    # igual, y no sirve para distinguir.
    # Lo que SÍ distingue es comparar contra el contador local: si los DOS números
    # coinciden EXACTAMENTE con `token_counter`, no es una medición del proveedor, es la
    # cuenta que litellm acaba de hacer. Se exigen los dos para que una coincidencia
    # casual en uno solo no descarte una medición real.
    estimado = False
    if medidos:
        try:
            ct_local = l.token_counter(model=kw["model"], text=texto)
            pt_local = l.token_counter(model=kw["model"], messages=kw["messages"])
            estimado = (tokens.get("completion_tokens") == ct_local
                        and tokens.get("prompt_tokens") == pt_local)
        except Exception:                               # noqa: BLE001 — contar nunca rompe el turno
            estimado = False
    if estimado:
        tokens, medidos = {"prompt_tokens": None, "completion_tokens": None}, False

    # ── EL MODELO, EN STREAMING ────────────────────────────────────────────────────
    # MEDIDO: los chunks que entrega litellm llevan en `.model` el id PEDIDO, no el que
    # el proveedor declaró — aunque el proveedor mande otro en su propio chunk. Así que
    # en streaming NO hay `model_final` honesto que sacar de acá, y no se inventa uno:
    # queda None y la meta dice por qué. El `model_final` autoritativo de esta vía sale
    # del camino no-streaming, o del anti-grift de `_route_chat` río arriba.
    model_final = None if (modelo or "") == kw["model"] else modelo

    yield "final", RespuestaModelo(
        ok=True, texto=texto, model_final=model_final,
        tokens=tokens, tokens_medidos=medidos,
        # En streaming no hay `_hidden_params.response_cost` confiable: el costo se calcula
        # arriba con `models.price` sobre tokens MEDIDOS, o no se calcula.
        usd=None,
        meta={"alias": alias, "stream": True, "chunks": n_chunks,
              "usage_estimado_por_litellm": estimado,
              "model_final_ecoado": model_final is None and bool(modelo)},
    )


# ══ EL PUENTE SYNC ═════════════════════════════════════════════════════════════════
# MISMO patrón que `platform/inspection/transporte_sdk.py:317` (`anyio.from_thread.
# start_blocking_portal`), por las mismas tres razones que ese módulo documenta: los
# cancel scopes de anyio son POR TAREA y el `__aexit__` del stream tiene que correr en la
# misma tarea que el `__aenter__`; anyio ya es dependencia nuestra; y un portal por
# llamada conserva el aislamiento. NO se importa aquél: su portal vive dentro de la clase
# del transporte MCP, atado a su ciclo de vida. Extraer un helper común tocaría
# `platform/inspection/`, que esta fase sólo puede leer — queda anotado para después.

def completar(alias: str, mensajes: list, **kw) -> RespuestaModelo:
    """Interfaz sync. Un portal por llamada; el async de adentro es el único camino real."""
    import functools

    from anyio.from_thread import start_blocking_portal
    with start_blocking_portal(backend="asyncio") as portal:
        return portal.call(functools.partial(acompletar, alias, mensajes, **kw))


def completar_stream(alias: str, mensajes: list, **kw) -> Iterator:
    """Interfaz sync del streaming. El generador async se sostiene DENTRO del portal, así
    que su `aclose()` corre en la misma tarea que lo abrió — que es exactamente el motivo
    por el que `transporte_sdk` eligió portal y no un loop a mano."""
    from anyio.from_thread import start_blocking_portal
    with start_blocking_portal(backend="asyncio") as portal:
        agen = acompletar_stream(alias, mensajes, **kw)
        with portal.wrap_async_context_manager(_sostener(agen)) as it:
            while True:
                try:
                    yield portal.call(it.__anext__)
                except StopAsyncIteration:
                    return


class _sostener:
    """Context manager async que sostiene un generador async y garantiza su `aclose()`."""

    def __init__(self, agen):
        self._agen = agen

    async def __aenter__(self):
        return self._agen

    async def __aexit__(self, *exc):
        try:
            await self._agen.aclose()
        except Exception:                               # noqa: BLE001
            pass
        return False


__all__ = ["init_litellm", "sellar_entorno", "disponible", "TIMEOUT_S",
           "RespuestaModelo", "acompletar", "acompletar_stream",
           "completar", "completar_stream"]
