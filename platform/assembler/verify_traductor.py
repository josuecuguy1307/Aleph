#!/usr/bin/env python3
"""verify_traductor.py — LA VARA DE F1 (Gate 2 · el traductor de errores).

Lo que esta vara exige que quede verde:

    el vocabulario es un SUBCONJUNTO REAL del de motor_verdad (no una copia que derivó) ·
    la tabla de equivalencias de las 4 fuentes × cada caso MEDIDO en los reportes 1-3 ·
    la red NUNCA se confunde con el servidor (la regla de oro, en las tres fuentes que
    pueden confundirla) · el reset_hint '02:59' del CLI se vuelve segundos correctos ·
    ninguna key falsa sobrevive en NINGÚN campo de la salida · y para CUALQUIER entrada
    —None, bytes, basura, objetos que explotan al imprimirse— el traductor devuelve una
    CausaModelo válida y jamás levanta.

Cero red, cero disco, cero mocks del transporte: se construyen las excepciones REALES
(`urllib.error.HTTPError` con sus cabeceras) y, para LiteLLM, clases con el nombre y los
atributos que la auditoría 1 midió — que es exactamente lo que el traductor lee, porque
no importa litellm.

    product/backend/.venv/bin/python platform/assembler/verify_traductor.py
"""
from __future__ import annotations

import io
import sys
import time
import urllib.error
from email.message import Message
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))

import errores_modelo as E  # noqa: E402

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


# ══ helpers para construir las entradas REALES ═════════════════════════════════════
def http_error(status: int, *, cabeceras: dict | None = None, cuerpo: str = "",
               url: str = "https://api.groq.com/openai/v1/chat/completions"):
    m = Message()
    for k, v in (cabeceras or {}).items():
        m[k] = v
    return urllib.error.HTTPError(url, status, "err", m, io.BytesIO(cuerpo.encode()))


def url_error(errno_: int | None, mensaje: str):
    return urllib.error.URLError(OSError(errno_, mensaje) if errno_ is not None else mensaje)


def excepcion_litellm(clase: str, *, status=None, headers=None, mensaje="fallo",
                      contexto=None, llm_provider=None):
    """Una excepción con el NOMBRE de clase y los atributos que el traductor lee.

    El traductor clasifica por nombre + atributos justamente para no depender de litellm;
    esto es la misma superficie que vería con la librería instalada."""
    tipo = type(clase, (Exception,), {})
    e = tipo(mensaje)
    if status is not None:
        e.status_code = status
    if headers is not None:
        e.litellm_response_headers = headers
    if llm_provider is not None:
        e.llm_provider = llm_provider
    if contexto is not None:
        e.__context__ = contexto
    return e


AHORA = 1_785_000_000.0        # reloj fijo: la vara no depende de la hora real

print("=" * 80)
print("VARA F1 · TRADUCTOR DE ERRORES DE INFERENCIA")
print("=" * 80)

# ══ 1 · EL VOCABULARIO ES DE MOTOR_VERDAD, NO UNA COPIA QUE DERIVÓ ═════════════════
seccion("1 · VOCABULARIO CERRADO (subconjunto real, sin deriva)")
try:
    sys.path.insert(0, str(_RAIZ / "product" / "backend"))
    from app.phase1 import motor_verdad as MV          # noqa: E402
    from app.phase1 import centro_modelos as CM        # noqa: E402

    vocabulario = set(MV.CAUSAS) | set(CM.CAUSAS_MODELO)
    sobrantes = E.CAUSAS - vocabulario
    ok(not sobrantes,
       f"las {len(E.CAUSAS)} causas del traductor están TODAS en motor_verdad ∪ CAUSAS_MODELO",
       f"fuera del vocabulario: {sorted(sobrantes)}")
    ok(E.ROTO == MV.ROTO, "el estado 'roto' es el mismo literal que el del motor", E.ROTO)
    for nombre in ("SIN_RED", "KEY_INVALIDA", "SIN_CREDITO", "RATE_LIMIT", "PROVEEDOR_CAIDO",
                   "PLAN_INSUFICIENTE", "TIMEOUT", "ERROR_UPSTREAM", "SIN_SESION",
                   "CLI_NO_INSTALADO", "CLI_SIN_PERMISOS", "FALLA_DE_ALEPH"):
        ok(getattr(E, nombre) == getattr(MV, nombre),
           f"{nombre} idéntico al del motor", f"{getattr(E, nombre)!r} vs {getattr(MV, nombre)!r}")
    ok(E.SIN_RUNTIME == CM.SIN_RUNTIME,
       "SIN_RUNTIME idéntico al de centro_modelos (no se duplicó)", E.SIN_RUNTIME)
    ok(E.FALLO_DESCONOCIDO == MV.FALLO_DESCONOCIDO,
       "el cajón honesto usa FALLO_DESCONOCIDO del motor (no se inventó 'no_clasificado')")
except Exception as exc:                                # noqa: BLE001
    ok(False, "se pudo importar motor_verdad + centro_modelos para comparar",
       f"{type(exc).__name__}: {exc}")

# ══ 2 · TABLA DE EQUIVALENCIAS ═════════════════════════════════════════════════════
# fila = (nombre, callable→CausaModelo, causa esperada, reintentable esperado)
seccion("2A · urllib — los 4 casos medidos en el reporte 2 §P1.b")
REMOTA = "https://api.groq.com/openai/v1/chat/completions"

TABLA_URLLIB = [
    ("401 con cabeceras → key_invalida, NO reintentable",
     lambda: E.desde_urllib(http_error(401, cabeceras={"x-request-id": "req_STUB_401",
                                                       "content-type": "application/json"},
                                       cuerpo='{"error":{"message":"Invalid API Key"}}'),
                            url=REMOTA, ahora=AHORA),
     E.KEY_INVALIDA, False),
    # ⚠️ [F7·A] LA DISTINCIÓN QUE FALTABA. Medido el 2026-08-06: un turno con llave basura
    # y un turno SIN NINGUNA llave daban la MISMA causa. Con el vault vacío, «el proveedor
    # rechazó la credencial» es literalmente falso —no había credencial— y manda al botón
    # equivocado: [Cambiar la llave] en vez de [Poner la llave].
    ("★ 401 SIN haber mandado credencial → falta_key, NO key_invalida",
     lambda: E.desde_urllib(http_error(401, cabeceras={"x-request-id": "req_STUB_401_SINKEY"}),
                            url=REMOTA, ahora=AHORA, tenia_key=False),
     E.FALTA_KEY, False),
    ("★ …y CON credencial mandada sigue siendo key_invalida (el default no cambió)",
     lambda: E.desde_urllib(http_error(401), url=REMOTA, ahora=AHORA, tenia_key=True),
     E.KEY_INVALIDA, False),
    ("402 → sin_credito, NO reintentable",
     lambda: E.desde_urllib(http_error(402), url=REMOTA, ahora=AHORA), E.SIN_CREDITO, False),
    ("403 → plan_insuficiente, NO reintentable",
     lambda: E.desde_urllib(http_error(403), url=REMOTA, ahora=AHORA), E.PLAN_INSUFICIENTE, False),
    # ══ [F9] LEY SELLADA: UN 403 NO ES AUTOMÁTICAMENTE LA CREDENCIAL ═══════════════
    # MEDIDO el 2026-08-07: sin `User-Agent`, groq contesta 403 «error code: 1010» — el WAF
    # de Cloudflare rechazando por NUESTRA firma de cliente. El motor lo leía `key_invalida`,
    # o sea que mandaba a ROTAR UNA LLAVE PERFECTA: la persona borra algo que funciona, lo
    # vuelve a pegar, y sigue sin andar. Es de los peores errores posibles.
    ("★★ 403 + «error code: 1010» (WAF nos bloquea) → falla_de_aleph, JAMÁS key_invalida",
     lambda: E.desde_urllib(http_error(403, cuerpo="error code: 1010"), url=REMOTA, ahora=AHORA),
     E.FALLA_DE_ALEPH, False),
    # Y el ritmo del WAF tampoco es la llave — pero se resuelve esperando, no reportando.
    ("★ 403 + «error code: 1015» (WAF nos frena) → rate_limit",
     lambda: E.desde_urllib(http_error(403, cuerpo="error code: 1015"), url=REMOTA, ahora=AHORA),
     E.RATE_LIMIT, True),
    # ⚠️ Y EL 403 QUE NO ES DE INFRA NO CAMBIÓ: el traductor lo sigue mandando a
    # `plan_insuficiente`. **OJO, DIVERGENCIA ANOTADA, NO ARREGLADA ACÁ**: el MOTOR sí
    # afina («invalid/expired/revoked» + 403 → `key_invalida`, `motor_verdad:695`) y el
    # traductor no. Tocarlo sería cambiar, de refilón, el diagnóstico de todos los 403 —
    # que no es lo que esta ley pidió. Queda como deuda con nombre.
    ("403 + «invalid api key» → el traductor sigue diciendo plan (divergencia con el motor)",
     lambda: E.desde_urllib(http_error(403, cuerpo="invalid api key"), url=REMOTA, ahora=AHORA),
     E.PLAN_INSUFICIENTE, False),
    ("404 → modelo_no_disponible, NO reintentable",
     lambda: E.desde_urllib(http_error(404), url=REMOTA, ahora=AHORA), E.MODELO_NO_DISPONIBLE, False),
    ("429 con retry-after → rate_limit, SÍ reintentable",
     lambda: E.desde_urllib(http_error(429, cabeceras={"retry-after": "42"}),
                            url=REMOTA, ahora=AHORA), E.RATE_LIMIT, True),
    ("500 → proveedor_caido, SÍ reintentable",
     lambda: E.desde_urllib(http_error(500), url=REMOTA, ahora=AHORA), E.PROVEEDOR_CAIDO, True),
    ("400 → error_upstream, NO reintentable",
     lambda: E.desde_urllib(http_error(400), url=REMOTA, ahora=AHORA), E.ERROR_UPSTREAM, False),
    ("Errno 8 (DNS caído, host remoto) → sin_red, SÍ reintentable",
     lambda: E.desde_urllib(url_error(8, "nodename nor servname provided, or not known"),
                            url=REMOTA, ahora=AHORA), E.SIN_RED, True),
    ("Errno 61 (refused, host REMOTO) → sin_red — jamás proveedor_caido",
     lambda: E.desde_urllib(url_error(61, "Connection refused"), url=REMOTA, ahora=AHORA),
     E.SIN_RED, True),
    ("Errno 61 (refused en 127.0.0.1:11434) → sin_runtime, no sin_red",
     lambda: E.desde_urllib(url_error(61, "Connection refused"),
                            url="http://127.0.0.1:11434/v1/chat/completions", ahora=AHORA),
     E.SIN_RUNTIME, True),
    ("Errno 61 (refused en 127.0.0.1:8926, servicio NUESTRO) → falla_de_aleph",
     lambda: E.desde_urllib(url_error(61, "Connection refused"),
                            url="http://127.0.0.1:8926/v1/chat/completions", ahora=AHORA),
     E.FALLA_DE_ALEPH, False),
    ("TimeoutError → timeout, SÍ reintentable",
     lambda: E.desde_urllib(TimeoutError("timed out"), url=REMOTA, ahora=AHORA), E.TIMEOUT, True),
    ("timeout contra 127.0.0.1:8923 → falla_de_aleph (local, no timeout de red)",
     lambda: E.desde_urllib(TimeoutError("timed out"), url="http://127.0.0.1:8923/v1", ahora=AHORA),
     E.FALLA_DE_ALEPH, False),
]

seccion("2A · urllib")
for nombre, fn, causa_esp, retry_esp in TABLA_URLLIB:
    r = fn()
    ok(r.causa == causa_esp and r.estado == E.ROTO and r.reintentable == retry_esp
       and r.fuente == E.FUENTE_URLLIB,
       nombre, f"dio causa={r.causa} estado={r.estado} reintentable={r.reintentable}")

r429 = E.desde_urllib(http_error(429, cabeceras={"retry-after": "42"}), url=REMOTA, ahora=AHORA)
ok(r429.retry_after_s == 42.0, "el retry-after de la cabecera llega como 42.0 s", str(r429.retry_after_s))
ok(r429.evidencia.get("retry-after") == "42", "y queda en la evidencia forense", str(r429.evidencia))
r401 = E.desde_urllib(http_error(401, cabeceras={"x-request-id": "req_STUB_401"}),
                      url=REMOTA, ahora=AHORA)
ok(r401.evidencia.get("x-request-id") == "req_STUB_401",
   "el request-id del proveedor SÍ viaja (es forense, no secreto)", str(r401.evidencia))
ok(r401.evidencia.get("http_status") == 401, "y el status también", str(r401.evidencia))
ok(r401.retry_after_s is None, "un 401 no trae retry_after (None, jamás 0)", str(r401.retry_after_s))

seccion("2B · CLI — reporte 2 §P1.e (lo que classify_error hoy funde) + contrato §0.3")
TABLA_CLI = [
    ('{"loggedIn": false} → sin_sesion (hoy: no_auth)',
     lambda: E.desde_cli('{"loggedIn": false}', 1, ahora=AHORA), E.SIN_SESION, False),
    ("'usage limit reached|<epoch>' → rate_limit CON retry_after",
     lambda: E.desde_cli("usage limit reached|1785000900", 1, ahora=AHORA), E.RATE_LIMIT, True),
    ("529/overloaded → proveedor_caido, SÍ reintentable",
     lambda: E.desde_cli("Error: overloaded_error 529", 1, ahora=AHORA), E.PROVEEDOR_CAIDO, True),
    ("getaddrinfo ENOTFOUND → SIN_RED  ← hoy cae en model_error (el arreglo)",
     lambda: E.desde_cli("getaddrinfo ENOTFOUND api.anthropic.com", 1, ahora=AHORA),
     E.SIN_RED, True),
    ("fallo desconocido → fallo_desconocido  ← hoy cae en model_error (el arreglo)",
     lambda: E.desde_cli("some totally unknown failure", 7, ahora=AHORA),
     E.FALLO_DESCONOCIDO, False),
    ("command not found → cli_no_instalado",
     lambda: E.desde_cli("claude: command not found", 127, ahora=AHORA), E.CLI_NO_INSTALADO, False),
    ("Permission denied → cli_sin_permisos",
     lambda: E.desde_cli("Permission denied", 126, ahora=AHORA), E.CLI_SIN_PERMISOS, False),
    ("'does not have access' → plan_insuficiente",
     lambda: E.desde_cli("Your account does not have access to this model", 1, ahora=AHORA),
     E.PLAN_INSUFICIENTE, False),
    ("'model not found' → modelo_no_disponible",
     lambda: E.desde_cli("model not found: claude-inexistente", 1, ahora=AHORA),
     E.MODELO_NO_DISPONIBLE, False),
    ("stderr vacío y sin result event → fallo_desconocido (jamás una causa que mienta)",
     lambda: E.desde_cli("", 1, ahora=AHORA), E.FALLO_DESCONOCIDO, False),
    ("result event con api_error_status=401 → sin_sesion (la credencial del CLI es la sesión)",
     lambda: E.desde_cli("", 1, {"is_error": True, "api_error_status": 401,
                                 "terminal_reason": "api_error", "subtype": "success"},
                         ahora=AHORA), E.SIN_SESION, False),
    ("result event con api_error_status=429 → rate_limit",
     lambda: E.desde_cli("", 1, {"is_error": True, "api_error_status": 429,
                                 "terminal_reason": "api_error"}, ahora=AHORA), E.RATE_LIMIT, True),
    ("result event con api_error_status=500 → proveedor_caido",
     lambda: E.desde_cli("", 1, {"is_error": True, "api_error_status": 500,
                                 "terminal_reason": "api_error"}, ahora=AHORA),
     E.PROVEEDOR_CAIDO, True),
    ("result event manda sobre el texto: status 429 gana a un stderr que dice 'not logged in'",
     lambda: E.desde_cli("not logged in", 1, {"is_error": True, "api_error_status": 429},
                         ahora=AHORA), E.RATE_LIMIT, True),
    ("terminal_reason=timeout sin status → timeout",
     lambda: E.desde_cli("", 1, {"is_error": True, "terminal_reason": "timeout"}, ahora=AHORA),
     E.TIMEOUT, True),
]
for nombre, fn, causa_esp, retry_esp in TABLA_CLI:
    r = fn()
    ok(r.causa == causa_esp and r.estado == E.ROTO and r.reintentable == retry_esp
       and r.fuente == E.FUENTE_CLI,
       nombre, f"dio causa={r.causa} estado={r.estado} reintentable={r.reintentable}")

seccion("2C · LiteLLM — reporte 1 §P1 (sin importar litellm)")
ctx_dns = OSError(8, "nodename nor servname provided, or not known")
ctx_refused = ConnectionRefusedError(61, "Connection refused")

TABLA_LITELLM = [
    ("AuthenticationError(401) → key_invalida",
     lambda: E.desde_litellm(excepcion_litellm("AuthenticationError", status=401,
                                               llm_provider="anthropic"), ahora=AHORA),
     E.KEY_INVALIDA, False),
    # ⚠️ [F7·A·bis] LAS DOS FILAS ESPEJO DE `TABLA_URLLIB`. F7·A cableó `tenia_key` de UN
    # SOLO LADO: urllib pasó a decir `falta_key` y litellm siguió diciendo `key_invalida`
    # ante el MISMO 401. La vara que lo cazó no fue ésta —fue `verify_f4a` §4c, que compara
    # las dos vías lado a lado— y por eso van acá: una tabla que sólo mide una vía no puede
    # ver una divergencia entre vías. La clase que manda litellm es `AuthenticationError`,
    # correcta para el status: lo que cambia es que NO mandamos credencial.
    ("★ AuthenticationError(401) SIN haber mandado credencial → falta_key, NO key_invalida",
     lambda: E.desde_litellm(excepcion_litellm("AuthenticationError", status=401,
                                               llm_provider="anthropic"),
                             ahora=AHORA, tenia_key=False),
     E.FALTA_KEY, False),
    ("★ …y CON credencial mandada sigue siendo key_invalida (el default no cambió)",
     lambda: E.desde_litellm(excepcion_litellm("AuthenticationError", status=401,
                                               llm_provider="anthropic"),
                             ahora=AHORA, tenia_key=True),
     E.KEY_INVALIDA, False),
    ("RateLimitError(429) con retry-after en litellm_response_headers → rate_limit",
     lambda: E.desde_litellm(excepcion_litellm("RateLimitError", status=429,
                                               headers={"retry-after": "37",
                                                        "x-request-id": "req_STUB_429"}),
                             ahora=AHORA), E.RATE_LIMIT, True),
    ("InternalServerError(500) con __context__ de DNS → SIN_RED  ← el hallazgo §P1.d",
     lambda: E.desde_litellm(excepcion_litellm("InternalServerError", status=500,
                                               mensaje="OpenAIException - Connection error.",
                                               contexto=ctx_dns), ahora=AHORA),
     E.SIN_RED, True),
    ("InternalServerError(500) con __context__ de refused REMOTO → SIN_RED",
     lambda: E.desde_litellm(excepcion_litellm("InternalServerError", status=500,
                                               contexto=ctx_refused), url=REMOTA, ahora=AHORA),
     E.SIN_RED, True),
    ("InternalServerError(500) SIN contexto de red → proveedor_caido (el 500 de verdad)",
     lambda: E.desde_litellm(excepcion_litellm("InternalServerError", status=500,
                                               mensaje="upstream is down"), ahora=AHORA),
     E.PROVEEDOR_CAIDO, True),
    # ── F1c · LAS DOS FILAS QUE F1 DEJÓ ESPERANDO ────────────────────────────────
    # ERAN `error_upstream` con el hueco escrito al lado. Ahora cada una dice lo suyo, y
    # las dos siguen NO reintentables — que es el punto: como `error_upstream` eran
    # temporales-una-vuelta en repair, o sea que se gastaba una llamada entera para
    # recibir exactamente la misma negativa.
    ("ContextWindowExceededError → contexto_excedido (F1c: era error_upstream)",
     lambda: E.desde_litellm(excepcion_litellm("ContextWindowExceededError", status=400),
                             ahora=AHORA), E.CONTEXTO_EXCEDIDO, False),
    ("ContentPolicyViolationError → politica_de_contenido (F1c: era error_upstream)",
     lambda: E.desde_litellm(excepcion_litellm("ContentPolicyViolationError", status=400),
                             ahora=AHORA), E.POLITICA_DE_CONTENIDO, False),
    # Y la que NO se movió, para que la línea quede amarrada: `RejectedRequestError` es de
    # los guardrails de litellm, no de la política del proveedor.
    ("RejectedRequestError → SIGUE error_upstream: no es el proveedor el que se negó",
     lambda: E.desde_litellm(excepcion_litellm("RejectedRequestError", status=400),
                             ahora=AHORA), E.ERROR_UPSTREAM, False),
    ("APIConnectionError → sin_red",
     lambda: E.desde_litellm(excepcion_litellm("APIConnectionError",
                                               mensaje="Connection error."), url=REMOTA,
                             ahora=AHORA), E.SIN_RED, True),
    ("Timeout → timeout",
     lambda: E.desde_litellm(excepcion_litellm("Timeout", mensaje="Request timed out"),
                             ahora=AHORA), E.TIMEOUT, True),
    ("NotFoundError(404) → modelo_no_disponible",
     lambda: E.desde_litellm(excepcion_litellm("NotFoundError", status=404), ahora=AHORA),
     E.MODELO_NO_DISPONIBLE, False),
    ("BudgetExceededError → sin_credito",
     lambda: E.desde_litellm(excepcion_litellm("BudgetExceededError"), ahora=AHORA),
     E.SIN_CREDITO, False),
    ("clase que no conocemos y sin status → fallo_desconocido",
     lambda: E.desde_litellm(excepcion_litellm("AlgoQueNoExiste", mensaje="???"), ahora=AHORA),
     E.FALLO_DESCONOCIDO, False),
    # ── LA PRECEDENCIA (medida en F3 sobre litellm 1.93.0) ───────────────────────────
    # `BadRequestError` con `status_code=401`: la clase y el status se CONTRADICEN. Con la
    # clase mandando salía `error_upstream` («revisá tu pedido») cuando lo que pasa es que
    # la key no sirve. En los cinco códigos accionables gana el STATUS.
    ("BadRequestError(401) — clase y status se CONTRADICEN → manda el STATUS: key_invalida",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=401,
                                               mensaje="Invalid API key"), ahora=AHORA),
     E.KEY_INVALIDA, False),
    ("BadRequestError(402) → sin_credito (el status manda)",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=402), ahora=AHORA),
     E.SIN_CREDITO, False),
    ("BadRequestError(403) → plan_insuficiente (el status manda)",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=403), ahora=AHORA),
     E.PLAN_INSUFICIENTE, False),
    ("BadRequestError(404) → modelo_no_disponible (el status manda)",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=404), ahora=AHORA),
     E.MODELO_NO_DISPONIBLE, False),
    ("BadRequestError(429) → rate_limit, y SÍ reintentable (el status manda)",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=429), ahora=AHORA),
     E.RATE_LIMIT, True),
    # …y la precedencia está ACOTADA a esos cinco: fuera de ellos la clase sigue mandando.
    ("BadRequestError(500) → error_upstream: el 500 NO está en los cinco, gana la clase",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=500,
                                               mensaje="upstream is down"), ahora=AHORA),
     E.ERROR_UPSTREAM, False),
    ("ContextWindowExceededError(400) → contexto_excedido: el 400 tampoco está en los "
     "cinco, gana la clase (y desde F1c la clase dice algo más útil)",
     lambda: E.desde_litellm(excepcion_litellm("ContextWindowExceededError", status=400),
                             ahora=AHORA), E.CONTEXTO_EXCEDIDO, False),
    # …y el TRANSPORTE le sigue ganando a los dos (la regla de oro no se movió).
    ("BadRequestError(401) con __context__ de DNS → SIN_RED: el transporte gana al status",
     lambda: E.desde_litellm(excepcion_litellm("BadRequestError", status=401,
                                               contexto=ctx_dns), url=REMOTA, ahora=AHORA),
     E.SIN_RED, True),
]
for nombre, fn, causa_esp, retry_esp in TABLA_LITELLM:
    r = fn()
    ok(r.causa == causa_esp and r.estado == E.ROTO and r.reintentable == retry_esp
       and r.fuente == E.FUENTE_LITELLM,
       nombre, f"dio causa={r.causa} estado={r.estado} reintentable={r.reintentable}")

rl = E.desde_litellm(excepcion_litellm("RateLimitError", status=429,
                                       headers={"retry-after": "37"}), ahora=AHORA)
ok(rl.retry_after_s == 37.0,
   "el retry-after sale de litellm_response_headers (donde LiteLLM lo esconde)", str(rl.retry_after_s))

seccion("2D · Ollama — local, jamás sin_red · la tabla MEDIDA en la auditoría 4 §3.2")
# LAS TRES FILAS QUE NO SE MUEVEN son las de transporte: refused y timeout contra el
# runtime local siguen siendo `sin_runtime`, y el 5xx también. Esa es la regla de oro.
#
# LAS DOS QUE SÍ CAMBIAN, declaradas: el modelo ausente (404 o su texto) pasa de
# `sin_runtime` a `modelo_no_disponible`. Justificación medida: la sonda S2 midió que ese
# caso llega como **HTTP 404 con el runtime vivo y contestando**; decir «no hay runtime»
# manda al usuario a prender algo que ya está prendido. El detalle («bajá el modelo») ya
# era el correcto desde F1 — lo que estaba mal era el rótulo.
TABLA_OLLAMA = [
    # ── lo que NO se movió ────────────────────────────────────────────────────────
    ("refused en :11434 → sin_runtime (NO sin_red: es local) — LA REGLA DE ORO",
     lambda: E.desde_ollama(url_error(61, "Connection refused"),
                            url="http://127.0.0.1:11434/api/chat", ahora=AHORA),
     E.SIN_RUNTIME, True),
    ("timeout contra ollama → sin_runtime, no timeout de red",
     lambda: E.desde_ollama(TimeoutError("timed out"),
                            url="http://127.0.0.1:11434/api/chat", ahora=AHORA),
     E.SIN_RUNTIME, True),
    ("500 «otro» de ollama → sin_runtime (es el runtime local, no un proveedor)",
     lambda: E.desde_ollama({"status": 500, "error": "llama runner terminated"}, ahora=AHORA),
     E.SIN_RUNTIME, True),
    # ── lo que CAMBIÓ (declarado arriba) ──────────────────────────────────────────
    ("modelo ausente (texto de ollama) → modelo_no_disponible  ← CAMBIÓ desde F1",
     lambda: E.desde_ollama({"error": 'model "qwen3:8b" not found, try pulling it first'},
                            ahora=AHORA), E.MODELO_NO_DISPONIBLE, False),
    ("404 de la API de ollama → modelo_no_disponible  ← CAMBIÓ desde F1",
     lambda: E.desde_ollama({"status": 404, "error": "model not found"}, ahora=AHORA),
     E.MODELO_NO_DISPONIBLE, False),
    # ── lo NUEVO: los casos que antes se fundían en sin_runtime ────────────────────
    ("404 por /v1 (sobre OpenAI anidado) → modelo_no_disponible, igual que el nativo",
     lambda: E.desde_ollama({"status": 404,
                             "error": {"message": "model 'x' not found",
                                       "type": "not_found_error",
                                       "param": None, "code": None}}, ahora=AHORA),
     E.MODELO_NO_DISPONIBLE, False),
    ("400 + «the input length exceeds the context length» → contexto_excedido "
     "(F1c: era error_upstream + `motivo` en la evidencia)",
     lambda: E.desde_ollama({"status": 400,
                             "error": "the input length exceeds the context length"},
                            ahora=AHORA), E.CONTEXTO_EXCEDIDO, False),
    ("400 «unexpected EOF» (JSON roto) → error_upstream, NO sin_runtime",
     lambda: E.desde_ollama({"status": 400, "error": "unexpected EOF"}, ahora=AHORA),
     E.ERROR_UPSTREAM, False),
    ("400 «[] is too short - 'messages'» (campos faltantes) → error_upstream",
     lambda: E.desde_ollama({"status": 400,
                             "error": {"message": "[] is too short - 'messages'",
                                       "type": "invalid_request_error"}}, ahora=AHORA),
     E.ERROR_UPSTREAM, False),
    ("503 + «server busy … maximum pending requests» → rate_limit, SÍ reintentable",
     lambda: E.desde_ollama({"status": 503,
                             "error": "server busy, maximum pending requests exceeded"},
                            ahora=AHORA), E.RATE_LIMIT, True),
    ("500 + substring de OOM (llm/status.go) → sin_runtime «no hay con qué correrlo»",
     lambda: E.desde_ollama({"status": 500,
                             "error": "cudaMalloc failed: out of memory"}, ahora=AHORA),
     E.SIN_RUNTIME, True),
    ("500 + «failed to allocate» (otra de la lista de status.go) → sin_runtime",
     lambda: E.desde_ollama({"status": 500,
                             "error": "ggml_backend_alloc: failed to allocate buffer"},
                            ahora=AHORA), E.SIN_RUNTIME, True),
    ("418 (fuera de las familias medidas, pero 4xx) → error_upstream: el runtime "
     "contestó y rechazó",
     lambda: E.desde_ollama({"status": 418, "error": "soy una tetera"}, ahora=AHORA),
     E.ERROR_UPSTREAM, False),
    ("error SIN status y sin patrón conocido → fallo_desconocido, jamás un rótulo "
     "inventado (el cajón honesto sigue existiendo)",
     lambda: E.desde_ollama({"error": "algo rarísimo pasó acá adentro"}, ahora=AHORA),
     E.FALLO_DESCONOCIDO, False),
    # ── F5 · APAGADO NO ES OCUPADO ───────────────────────────────────────────────
    # La auditoría 4 §3.1 midió que Ollama ENCOLA: 3 simultáneos → 3× HTTP 200 (7,9/15/23 s),
    # cero errores. El timeout que veíamos era nuestro cliente rindiéndose con el runtime
    # vivo. Con la liveness confirmada, ese timeout deja de ser `sin_runtime`.
    # F1c · el hueco #6, cerrado: era `timeout` (un GRIS de repair, que se desempata por
    # `murio`) y acá no hay ningún gris — se MIDIÓ que el runtime está vivo y encolando.
    ("timeout con runtime_vivo=True → runtime_ocupado, NO sin_runtime  ← F5 · F1c",
     lambda: E.desde_ollama(TimeoutError("timed out"),
                            url="http://127.0.0.1:11434/api/chat",
                            runtime_vivo=True, ahora=AHORA), E.RUNTIME_OCUPADO, True),
    ("timeout con runtime_vivo=False → sin_runtime, ahora CONFIRMADO",
     lambda: E.desde_ollama(TimeoutError("timed out"),
                            url="http://127.0.0.1:11434/api/chat",
                            runtime_vivo=False, ahora=AHORA), E.SIN_RUNTIME, True),
    ("timeout SIN saber (None) → sin_runtime: el comportamiento de F1b, byte por byte",
     lambda: E.desde_ollama(TimeoutError("timed out"),
                            url="http://127.0.0.1:11434/api/chat", ahora=AHORA),
     E.SIN_RUNTIME, True),
    ("refused con runtime_vivo=True → SIGUE sin_runtime: contesta y no contesta es una "
     "contradicción, y manda lo que se midió en ESTE intento",
     lambda: E.desde_ollama(url_error(61, "Connection refused"),
                            url="http://127.0.0.1:11434/api/chat",
                            runtime_vivo=True, ahora=AHORA), E.SIN_RUNTIME, True),
    ("404 con runtime_vivo=True → modelo_no_disponible: la liveness NO pisa los status",
     lambda: E.desde_ollama({"status": 404, "error": "model not found"},
                            runtime_vivo=True, ahora=AHORA), E.MODELO_NO_DISPONIBLE, False),
]
for nombre, fn, causa_esp, retry_esp in TABLA_OLLAMA:
    r = fn()
    ok(r.causa == causa_esp and r.estado == E.ROTO and r.reintentable == retry_esp
       and r.fuente == E.FUENTE_OLLAMA,
       nombre, f"dio causa={r.causa} estado={r.estado} reintentable={r.reintentable}")

# ── la EVIDENCIA, que es lo que hace utilizable la separación ─────────────────────
ctx_plano = E.desde_ollama({"status": 400,
                            "error": "the input length exceeds the context length"}, ahora=AHORA)
ok(ctx_plano.evidencia.get("motivo") == "contexto_excedido",
   "el `motivo` distingue contexto_excedido de una petición inválida cualquiera",
   str(ctx_plano.evidencia))
ok("n_ctx" not in ctx_plano.evidencia and "n_prompt_tokens" not in ctx_plano.evidencia,
   "y SIN números inventados: Ollama aplana el error rico (llama_server.go:2369-2381), "
   "así que por esta vía no hay cuánto te pasaste — y ese vacío ES el dato",
   str(ctx_plano.evidencia))

ctx_rico = E.desde_ollama(
    {"status": 400,
     "error": "input (20000 tokens) is larger than the max context size (2048 tokens)"},
    ahora=AHORA)
ok(ctx_rico.evidencia.get("n_prompt_tokens") == 20000 and ctx_rico.evidencia.get("n_ctx") == 2048,
   "pero si los números SÍ llegan (llama-server directo), se leen y viajan",
   str(ctx_rico.evidencia))
ctx_campos = E.desde_ollama({"status": 400, "error": {"message": "exceeds context size"},
                             "n_prompt_tokens": 9000, "n_ctx": 4096}, ahora=AHORA)
ok(ctx_campos.evidencia.get("n_ctx") == 4096,
   "y también si vienen como campos del cuerpo, no en el texto", str(ctx_campos.evidencia))

oom = E.desde_ollama({"status": 500, "error": "cudaMalloc failed: out of memory"}, ahora=AHORA)
ok(oom.evidencia.get("fuente") == "heuristica",
   "el OOM se marca como HEURÍSTICA: es grep sobre código interno de Ollama, no su API",
   str(oom.evidencia))
ok("status.go" in str(oom.evidencia.get("origen_heuristica", "")),
   "diciendo de dónde sale, para que el día que Ollama la cambie se sepa dónde mirar",
   str(oom.evidencia.get("origen_heuristica")))
ok(oom.evidencia.get("motivo") == "memoria_insuficiente",
   "y el `motivo` dice memoria_insuficiente, que es el hueco del vocabulario",
   str(oom.evidencia))
quinientos = E.desde_ollama({"status": 500, "error": "llama runner terminated"}, ahora=AHORA)
ok(quinientos.evidencia.get("motivo") == "fallo_del_runtime"
   and "fuente" not in quinientos.evidencia,
   "un 500 SIN señal de OOM no se marca como heurística: no se adivinó nada",
   str(quinientos.evidencia))

sat = E.desde_ollama({"status": 503, "error": "server busy, maximum pending requests exceeded"},
                     ahora=AHORA)
ok(sat.evidencia.get("origen") == "runtime",
   "el saturado dice `origen: runtime` — ni la ventana de un proveedor ni nuestro techo",
   str(sat.evidencia))

ocupado = E.desde_ollama(TimeoutError("timed out"), url="http://127.0.0.1:11434/api/chat",
                         runtime_vivo=True, ahora=AHORA)
ok(ocupado.evidencia.get("motivo") == "runtime_ocupado"
   and ocupado.evidencia.get("origen") == "runtime",
   "el ocupado dice `motivo: runtime_ocupado` + `origen: runtime` (hueco #6 propuesto)",
   str(ocupado.evidencia))
ok(ocupado.evidencia.get("runtime_vivo") is True,
   "y deja anotado que la liveness se CONFIRMÓ, no se supuso", str(ocupado.evidencia))
ok("ocup" in ocupado.detalle and "corriendo" in ocupado.detalle,
   "y el detalle manda a ESPERAR, no a prender lo que ya está prendido", ocupado.detalle)
apagado = E.desde_ollama(TimeoutError("timed out"), url="http://127.0.0.1:11434/api/chat",
                         runtime_vivo=False, ahora=AHORA)
ok(apagado.evidencia.get("runtime_vivo") is False,
   "y el apagado confirmado también queda anotado", str(apagado.evidencia))

v1 = E.desde_ollama({"status": 404, "error": {"message": "model 'x' not found",
                                              "type": "not_found_error"}}, ahora=AHORA)
ok(v1.evidencia.get("tipo_openai") == "not_found_error",
   "de los TRES tipos que Ollama emite, el que vino queda en la evidencia",
   str(v1.evidencia))

# ── la regla de oro, en la vía de ollama: ningún caso puede salir `sin_red` ───────
_TODOS_OLLAMA = [fn() for _, fn, _, _ in TABLA_OLLAMA] + [ctx_rico, oom, sat, v1, quinientos]
ok(all(c.causa != E.SIN_RED for c in _TODOS_OLLAMA),
   f"NINGUNO de los {len(_TODOS_OLLAMA)} casos de ollama sale `sin_red` — es local, y "
   f"la regla de oro no se movió con las filas nuevas",
   str([c.causa for c in _TODOS_OLLAMA if c.causa == E.SIN_RED]))
ok(all(c.fuente == E.FUENTE_OLLAMA for c in _TODOS_OLLAMA),
   "y todos declaran fuente `ollama`")

# ══ 3 · LA REGLA DE ORO, EXPLÍCITA ═════════════════════════════════════════════════
seccion("3 · LA REGLA DE ORO: la red no es el servidor")
sin_status = [
    ("urllib DNS", E.desde_urllib(url_error(8, "getaddrinfo failed"), url=REMOTA, ahora=AHORA)),
    ("urllib refused remoto", E.desde_urllib(url_error(61, "Connection refused"), url=REMOTA, ahora=AHORA)),
    ("urllib unreachable", E.desde_urllib(url_error(51, "Network is unreachable"), url=REMOTA, ahora=AHORA)),
    ("cli DNS", E.desde_cli("getaddrinfo ENOTFOUND api.anthropic.com", 1, ahora=AHORA)),
    ("litellm 500-con-red-abajo", E.desde_litellm(
        excepcion_litellm("InternalServerError", status=500, contexto=ctx_dns), ahora=AHORA)),
]
for nombre, r in sin_status:
    ok(r.causa != E.PROVEEDOR_CAIDO,
       f"{nombre}: un transporte sin status NUNCA es proveedor_caido", r.causa)
ok(E.desde_urllib(http_error(500), url=REMOTA, ahora=AHORA).causa == E.PROVEEDOR_CAIDO,
   "y un 5xx CON status sí es proveedor_caido (la otra mitad de la regla)")

locales = [
    ("ollama :11434", E.desde_urllib(url_error(61, "Connection refused"),
                                     url="http://127.0.0.1:11434/v1", ahora=AHORA), E.SIN_RUNTIME),
    ("cli_brain :8926", E.desde_urllib(url_error(61, "Connection refused"),
                                       url="http://127.0.0.1:8926/v1", ahora=AHORA), E.FALLA_DE_ALEPH),
    ("shim :8923", E.desde_urllib(url_error(61, "Connection refused"),
                                  url="http://localhost:8923/v1", ahora=AHORA), E.FALLA_DE_ALEPH),
]
for nombre, r, esperada in locales:
    ok(r.causa == esperada and r.causa != E.SIN_RED,
       f"{nombre}: un fallo LOCAL nunca es sin_red", r.causa)

# ══ 4 · RETRY_AFTER ════════════════════════════════════════════════════════════════
seccion("4 · retry_after_s — el reset del CLI en segundos, y None jamás 0")
hint = E.desde_cli("usage limit reached. resets 02:59", 1, ahora=AHORA)
esperado = None
_l = time.localtime(AHORA)
_medianoche = AHORA - (_l.tm_hour * 3600 + _l.tm_min * 60 + _l.tm_sec)
_obj = _medianoche + 2 * 3600 + 59 * 60
if _obj <= AHORA:
    _obj += 86400
esperado = _obj - AHORA
ok(hint.causa == E.RATE_LIMIT, "el hint '02:59' se clasifica como rate_limit", hint.causa)
ok(hint.retry_after_s is not None and abs(hint.retry_after_s - esperado) < 1.0,
   f"'02:59' → {esperado:.0f} s (próxima ocurrencia de esa hora local)",
   str(hint.retry_after_s))
ok(0 < (hint.retry_after_s or 0) <= 86400, "y cae dentro de las próximas 24 h", str(hint.retry_after_s))

epoch = E.desde_cli("usage limit reached|1785000900", 1, ahora=AHORA)
ok(epoch.retry_after_s == 900.0, "el epoch del CLI → 900 s exactos", str(epoch.retry_after_s))

en_horas = E.desde_cli("usage limit reached, resets in 2h", 1, ahora=AHORA)
ok(en_horas.retry_after_s == 7200.0, "'resets in 2h' → 7200 s", str(en_horas.retry_after_s))

pasado = E.desde_urllib(http_error(429, cabeceras={"retry-after": "0"}), url=REMOTA, ahora=AHORA)
ok(pasado.retry_after_s is None, "un retry-after de 0 se reporta como None, JAMÁS 0",
   str(pasado.retry_after_s))
negativo = E.desde_cli("usage limit reached|1000000000", 1, ahora=AHORA)
ok(negativo.retry_after_s is None, "un reset ya vencido tampoco inventa un 0",
   str(negativo.retry_after_s))
sin_ra = E.desde_urllib(http_error(429), url=REMOTA, ahora=AHORA)
ok(sin_ra.causa == E.RATE_LIMIT and sin_ra.retry_after_s is None,
   "un 429 sin cabecera es rate_limit con retry_after None", str(sin_ra.retry_after_s))

# ══ 5 · REDACCIÓN ══════════════════════════════════════════════════════════════════
seccion("5 · REDACCIÓN — ninguna key sobrevive en NINGÚN campo")
KEY = "sk-ant-api03-VERYSECRETKEYVALUE1234567890abcdefGHIJKL"
CUERPO = ('{"error":{"message":"Incorrect API key provided: ' + KEY +
          '. You can find your API key at https://console.anthropic.com/keys",'
          '"type":"invalid_request_error"}}')


def todo_el_texto(c: E.CausaModelo) -> str:
    d = c.como_dict()
    return " ".join([str(d["causa"]), str(d["detalle"]), str(d["fuente"]),
                     " ".join(f"{k}={v}" for k, v in d["evidencia"].items())])


casos_secreto = [
    ("urllib 401 con la key en el cuerpo",
     E.desde_urllib(http_error(401, cabeceras={"authorization": "Bearer " + KEY,
                                               "x-request-id": "req_ok"},
                               cuerpo=CUERPO), url=REMOTA, ahora=AHORA)),
    ("cli con la key en stderr", E.desde_cli(f"authentication_error: bad key {KEY}", 1, ahora=AHORA)),
    ("litellm con la key en el mensaje",
     E.desde_litellm(excepcion_litellm("AuthenticationError", status=401, mensaje=CUERPO),
                     ahora=AHORA)),
    ("ollama con la key en el error", E.desde_ollama({"error": f"failed with {KEY}"}, ahora=AHORA)),
    ("fallo desconocido con la key adentro", E.desde_cli(f"weird failure {KEY}", 9, ahora=AHORA)),
]
for nombre, r in casos_secreto:
    texto = todo_el_texto(r)
    ok(KEY not in texto, f"{nombre}: la key NO aparece en causa/detalle/evidencia",
       texto[:120])
    ok("Bearer " + KEY not in texto, f"{nombre}: tampoco el header Authorization completo")

r_auth = E.desde_urllib(http_error(401, cabeceras={"authorization": "Bearer " + KEY,
                                                   "x-request-id": "req_ok"}),
                        url=REMOTA, ahora=AHORA)
ok("authorization" not in {k.lower() for k in r_auth.evidencia},
   "la cabecera Authorization ni siquiera entra a la evidencia (lista blanca)",
   str(sorted(r_auth.evidencia)))
ok(r_auth.evidencia.get("x-request-id") == "req_ok",
   "pero las forenses de la lista blanca sí entran")
r_cuerpo = E.desde_urllib(http_error(400, cuerpo=CUERPO), url=REMOTA, ahora=AHORA)
ok("console.anthropic.com" not in todo_el_texto(r_cuerpo),
   "el cuerpo del proveedor no se copia a la salida (ni su texto inocente)",
   todo_el_texto(r_cuerpo)[:120])

# ══ 6 · PROPIEDAD: para TODA entrada, CausaModelo válida y cero excepciones ═════════
seccion("6 · PROPIEDAD — jamás levanta, jamás sale del vocabulario")


class Explosiva:
    """Un objeto cuyo __str__ y cuyos atributos explotan. El peor caso realista."""

    def __str__(self):
        raise RuntimeError("bum")

    def __getattr__(self, n):
        raise RuntimeError("bum " + n)


BASURA = [
    None, "", 0, -1, 3.5, True, False, b"", b"\xff\xfe\x00binario",
    "  ", "\n\n\n", "%s %d {no_existe}", "{" * 500, "\x00\x01\x02",
    "sk-" + "A" * 5000, "á" * 1000, "🙂" * 100,
    [], {}, (), set(), object(), Explosiva(),
    {"error": None}, {"status": "no soy un int"}, {"status": 99999},
    {"is_error": True}, {"api_error_status": "429"}, {"api_error_status": -5},
    # F1b · las formas que las ramas nuevas de ollama tocan, deformadas a propósito:
    # sobres anidados con tipos imposibles, y números de contexto que no son números.
    {"error": {"message": None, "type": 7}}, {"error": {"message": {"a": 1}}},
    {"error": []}, {"error": {"message": "exceeds context size", "n_ctx": "muchos"}},
    {"status": True, "error": "out of memory"},
    {"status": 500, "error": {"message": b"\xff out of memory"}},
    {"n_ctx": -1, "n_prompt_tokens": None, "error": "exceeds context size"},
    Exception(), Exception(None), OSError(), OSError(999999, "raro"),
    urllib.error.URLError(""), TimeoutError(),
    ValueError("x" * 100000),
]

levantadas = 0
fuera_vocab = 0
malos_estado = 0
total = 0
for entrada in BASURA:
    for fn, kw in ((E.desde_urllib, {}), (E.desde_cli, {}),
                   (E.desde_litellm, {}), (E.desde_ollama, {})):
        total += 1
        try:
            r = fn(entrada, **kw)
        except Exception as exc:                        # noqa: BLE001
            levantadas += 1
            print(f"      LEVANTÓ {fn.__name__}({entrada!r:.40}) → {type(exc).__name__}: {exc}")
            continue
        if not isinstance(r, E.CausaModelo):
            fuera_vocab += 1
            continue
        if r.causa not in E.CAUSAS:
            fuera_vocab += 1
        if r.estado != E.ROTO or r.fuente not in E.FUENTES:
            malos_estado += 1
        if r.retry_after_s is not None and not (isinstance(r.retry_after_s, float)
                                                and r.retry_after_s > 0):
            malos_estado += 1

# desde_cli con firmas raras (rc y result_event basura)
for rc in (None, 0, 1, -9, "x", 3.3, object()):
    for ev in (None, {}, [], "no soy un dict", {"api_error_status": object()}):
        total += 1
        try:
            r = E.desde_cli("algo raro", rc, ev)
            if r.causa not in E.CAUSAS or r.estado != E.ROTO:
                fuera_vocab += 1
        except Exception as exc:                        # noqa: BLE001
            levantadas += 1
            print(f"      LEVANTÓ desde_cli(rc={rc!r}, ev={ev!r}) → {type(exc).__name__}: {exc}")

ok(levantadas == 0, f"ninguna de las {total} entradas basura hizo levantar al traductor",
   f"{levantadas} levantaron")
ok(fuera_vocab == 0, "ninguna salida quedó fuera del vocabulario", f"{fuera_vocab} fuera")
ok(malos_estado == 0, "ninguna salida tuvo estado/fuente/retry_after inválidos",
   f"{malos_estado} malos")

ok(all(E.desde_cli(x).causa == E.FALLO_DESCONOCIDO for x in ("", None, "   ")),
   "una entrada vacía cae en fallo_desconocido, no en una causa que mienta")

# la dataclass se defiende sola
try:
    E.CausaModelo(causa="inventada", estado=E.ROTO, detalle="x", fuente=E.FUENTE_CLI)
    ok(False, "CausaModelo rechaza una causa fuera del vocabulario")
except ValueError:
    ok(True, "CausaModelo rechaza una causa fuera del vocabulario")
try:
    E.CausaModelo(causa=E.SIN_RED, estado="probado", detalle="x", fuente=E.FUENTE_CLI)
    ok(False, "CausaModelo rechaza un estado que no sea 'roto'")
except ValueError:
    ok(True, "CausaModelo rechaza un estado que no sea 'roto' (contrato de _resultado)")
try:
    r = E.desde_urllib(http_error(401), url=REMOTA, ahora=AHORA)
    r.causa = "otra"                                    # type: ignore[misc]
    ok(False, "CausaModelo es inmutable")
except Exception:                                       # noqa: BLE001
    ok(True, "CausaModelo es inmutable (frozen)")

# ══ 7 · SUPERA A classify_error, medido lado a lado ════════════════════════════════
seccion("7 · absorbe y SUPERA a cli_brain.classify_error")
try:
    sys.path.insert(0, str(_RAIZ / "platform" / "assembler"))
    from cli_brain.claude_cli import ClaudeCliProvider   # noqa: E402
    prov = ClaudeCliProvider()
    comparaciones = [
        ("getaddrinfo ENOTFOUND api.anthropic.com", 1, E.SIN_RED, "model_error"),
        ("some totally unknown failure", 7, E.FALLO_DESCONOCIDO, "model_error"),
        ("claude: command not found", 127, E.CLI_NO_INSTALADO, "model_error"),
        ("Permission denied", 126, E.CLI_SIN_PERMISOS, "model_error"),
    ]
    for blob, rc, esperada, hoy in comparaciones:
        viejo, _ = prov.classify_error(blob, rc)
        nuevo = E.desde_cli(blob, rc, ahora=AHORA).causa
        ok(viejo == hoy and nuevo == esperada,
           f"'{blob[:34]}…': hoy '{viejo}' → traductor '{nuevo}'",
           f"esperado hoy={hoy} nuevo={esperada}")
    # lo que ya hacía bien lo sigue haciendo bien
    for blob, rc, esperada in (('{"loggedIn": false}', 1, E.SIN_SESION),
                               ("usage limit reached|1785000900", 1, E.RATE_LIMIT)):
        ok(E.desde_cli(blob, rc, ahora=AHORA).causa == esperada,
           f"lo que classify_error ya acertaba sigue igual: '{blob[:30]}…' → {esperada}")
except Exception as exc:                                # noqa: BLE001
    ok(False, "se pudo importar cli_brain para comparar lado a lado",
       f"{type(exc).__name__}: {exc}")

# ══ 8 · PUREZA ═════════════════════════════════════════════════════════════════════
seccion("8 · pureza — stdlib, sin red, sin disco, determinista")
fuente_mod = (_AQUI / "errores_modelo.py").read_text("utf-8")
for prohibido in ("import requests", "import httpx", "urlopen(", "socket.socket",
                  "open(", "subprocess", "import litellm"):
    ok(prohibido not in fuente_mod, f"el módulo no contiene «{prohibido}»")
importados = [l.strip() for l in fuente_mod.splitlines()
              if l.startswith("import ") or l.startswith("from ")]
ok(all(any(l.startswith(p) for p in ("import re", "import time", "from dataclasses",
                                     "from typing", "from urllib.parse", "from __future__"))
       for l in importados),
   "todos los imports de nivel superior son stdlib", "; ".join(importados))
a = E.desde_urllib(http_error(429, cabeceras={"retry-after": "42"}), url=REMOTA, ahora=AHORA)
b = E.desde_urllib(http_error(429, cabeceras={"retry-after": "42"}), url=REMOTA, ahora=AHORA)
ok(a.como_dict() == b.como_dict(), "dos traducciones de la misma entrada son idénticas")
ok(E.desde_cli("usage limit reached. resets 02:59", 1, ahora=AHORA).retry_after_s
   == E.desde_cli("usage limit reached. resets 02:59", 1, ahora=AHORA).retry_after_s,
   "con `ahora` inyectado el resultado no depende del reloj")

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
