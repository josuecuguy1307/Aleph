"""motor_verdad.py — EL MOTOR DE VERDAD (CUARTO HONESTO · T1 · §2).

Fuente ÚNICA del estado VERIFICADO de todo lo tocable del Cuarto. No dice "existe";
dice "lo probé, esto respondió, hace N segundos" — o "está roto, por ESTA causa, andá
acá a arreglarlo". Es el backend de la ley §0.2 (ESTADO VISIBLE + CAMINO VISIBLE): la UI
(T2) pinta el semáforo con lo que este motor mide; el Guía (T5) lee estos estados y ofrece
el arreglo. Jamás verde sin evidencia.

CONTRATO (spec `reports/step5/CUARTO-HONESTO.md` §1/§2) — resultado TIPADO:

    {tipo, ref, estado, causa, evidencia, ts, cacheado?}

  estado ∈ {probado, detectado, roto, no_configurado, premium}          (los 5 de §1)
  causa  ∈ {falta_key, sin_red, cli_no_instalado, sin_sesion,           (SÓLO si roto)
            timeout, error_upstream} | None
  evidencia = la PRUEBA cruda (model_final, tools listadas, versión, latencia, http…).
  ts = epoch del chequeo (la UI formatea "probado hace 2 min").

CUATRO PRUEBAS POR TIPO (§2), cada una EXTENDIENDO lo que ya existe (cero duplicación):
  cerebro → resolve registry-only (anti-SSRF, patrón cuarto_guide) + ping /chat/completions
            con prompt mínimo, leyendo model_final HONESTO (patrón anti-grift de La Sala).
  cli     → platform/assembler/cli_brain.detect (spawn + version + auth status, TTL propio).
  mcp     → inspection.byo_mcp.probe_mcp: handshake initialize + tools/list REALES.
  key     → descifra la BYOK del user (repo.get_key) + validación mínima contra el proveedor.

role=client + SQLite: la prueba de `key` lee la tabla `keys` del SQLite del usuario vía
get_conn; el resto no toca disco. Todo lazy-import de platform/ → arranca en el sidecar
FROZEN sin depender de que el moat (FORGE) viaje (byo_mcp/liveness son zona RESOLVE, viajan).

Cache TTL corto EN MEMORIA (no una tabla): un estado verificado no necesita sobrevivir un
reinicio del sidecar — si reinicia, re-probar es barato y MÁS honesto (verdad fresca).
`re-probar siempre disponible`: force=True saltea la cache. `Al conectar algo, se prueba
solo`: al_conectar() fuerza una prueba y la cachea (lo llama el seam de connectors_router).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from app.phase1 import diagnostico_conectores as DC

# ── El contrato de estados/causas/tipos (§1) — vocabulario CERRADO ────────────────
PROBADO = "probado"
DETECTADO = "detectado"
ROTO = "roto"
NO_CONFIGURADO = "no_configurado"
PREMIUM = "premium"
ESTADOS = frozenset({PROBADO, DETECTADO, ROTO, NO_CONFIGURADO, PREMIUM})

FALTA_KEY = "falta_key"
SIN_RED = "sin_red"
CLI_NO_INSTALADO = "cli_no_instalado"
SIN_SESION = "sin_sesion"
TIMEOUT = "timeout"
ERROR_UPSTREAM = "error_upstream"
# ── [SALA VIVA] el vocabulario se AMPLÍA, no se duplica ───────────────────────────
# La Sala necesitaba nombrar fallos que el motor ya distinguía en la evidencia pero no
# tipaba. Sin un nombre propio, todos caían en `error_upstream` y la UI sólo podía decir
# "algo falló" — que es exactamente el fallo mudo que estamos matando. Alias explícitos
# donde el concepto ya existía (`cli_no_logueado` == SIN_SESION, `key_ausente` == FALTA_KEY)
# para que ningún caller tenga que inventar un sinónimo.
CLI_VERSION_VIEJA = "cli_version_vieja"        # binario presente, versión por debajo del mínimo
CLI_NO_LOGUEADO = SIN_SESION                   # alias del contrato de la Sala
CLI_INTERACTIVO_COLGADO = "cli_interactivo_colgado"  # esperó un prompt que nadie puede contestar
CLI_SIN_PERMISOS = "cli_sin_permisos"          # cwd no escribible / permiso denegado
PLAN_INSUFICIENTE = "plan_insuficiente"        # la suscripción no cubre el modelo pedido
KEY_AUSENTE = FALTA_KEY                        # alias del contrato de la Sala
KEY_INVALIDA = "key_invalida"                  # 401 — la key no sirve
OAUTH_REVOCADO = "oauth_revocado"              # grant OAuth revocado en el proveedor
SIN_CREDITO = "sin_credito"                    # 402 — la key sirve, no hay saldo
RATE_LIMIT = "rate_limit"                      # 429 — hay que esperar
MODELO_NO_DISPONIBLE = "modelo_no_disponible"  # la key no alcanza ESE modelo
# [GATE 2 · F8] La vía está configurada —la llave ESTÁ y el proveedor contesta— y aun así no
# hay con qué pensar: nadie eligió modelo y no se pudo elegir uno solo. Vive acá por el mismo
# motivo que `CAUSAS_F1C`: **este módulo no la emite** (el motor mide conexiones, y ésta la
# deriva el selector de un requisito), pero el vocabulario de causas es UNO. Sin la entrada
# acá, el mismo string existiría suelto en el selector y en el diccionario del Cuarto, y
# nada obligaría a que se escriban igual.
MODELO_NO_ELEGIDO = "modelo_no_elegido"        # hay llave, no hay modelo elegido
# ── [FIX-P9 · §8] LA CULPA NUESTRA TIENE NOMBRE PROPIO ────────────────────────────
# Cuando lo que falta es un archivo DE ALEPH (un módulo que debía viajar en el .app, un
# belt que el bundle no empaquetó), la causa no es del proveedor ni de la persona: es
# nuestra. Sin esta causa, ese fallo se disfrazaba de `error_upstream` y la UI le pedía a
# la persona que revisara SU configuración por un bug de nuestro build. Es la única causa
# cuyo camino no es un arreglo del usuario, sino [Copiar el reporte].
FALLA_DE_ALEPH = "falla_de_aleph"
PROVEEDOR_CAIDO = "proveedor_caido"            # 5xx/timeout CON internet verificado OK
SERVIDOR_INCOMPATIBLE = DC.SERVIDOR_INCOMPATIBLE
NO_ES_MCP = DC.NO_ES_MCP
FALLO_DESCONOCIDO = DC.FALLO_DESCONOCIDO
# ── [GATE 2 · F1c] LAS SEIS CAUSAS SELLADAS ───────────────────────────────────────
# Cada una de estas seis venía siendo un HUECO DECLARADO: una fase midió el fallo, no
# encontró un nombre que lo dijera sin mentir, usó la aproximación más honesta que había y
# escribió el hueco en su propio código para que no se perdiera. Están todas citadas:
#
#   `contexto_excedido`     F1  · errores_modelo.py (§Ollama, y `ContextWindowExceededError`)
#   `politica_de_contenido` F1  · errores_modelo.py (`ContentPolicyViolationError`)
#   `cli_ocupado`           F2b · cli_brain/slots.py:29-32
#   `turno_detenido`        F2d · cli_brain/base.py:221-228
#   `sesion_perdida`        F2e · cli_brain/sesiones.py:435-438
#   `runtime_ocupado`       F5  · errores_modelo.py:952-955  ·  qa/verify_via_local.py
#
# EL CRITERIO PARA ADMITIRLAS (el mismo de la Sala Viva, arriba): una causa entra cuando
# **el camino del usuario es distinto** del de la causa con la que se la venía fundiendo. No
# entra por precisión de vocabulario: entra porque el consejo cambia.
#
#   · `contexto_excedido` vs `error_upstream`: «revisá el pedido» → «acortá el pedido». Y
#     además NO es reintentable: el mismo texto no va a entrar la próxima vez.
#   · `politica_de_contenido` vs `error_upstream`: «revisá el pedido» → «reformulá». No es
#     un error del pedido: es una negativa, y repetirla igual no la cambia.
#   · `cli_ocupado` vs `rate_limit`: «se agotó tu ventana» (que asusta y no es cierto) →
#     «tu CLI está atendiendo otro turno» (segundos, no horas).
#   · `turno_detenido` vs *nada*: F2d salía SIN causa a propósito, porque inventar una que
#     mintiera era peor. **Un turno que alguien paró no es un fallo** y no lleva alarma.
#   · `sesion_perdida` vs `falla_de_aleph`: `falla_de_aleph` es «copiá el reporte», y esto
#     se arregla solo (el server rehace el turno con contexto completo).
#   · `runtime_ocupado` vs `timeout`: «se colgó, reiniciá» → «hay cola, esperá».
CONTEXTO_EXCEDIDO = "contexto_excedido"        # el pedido no entra en la ventana · acortar
POLITICA_DE_CONTENIDO = "politica_de_contenido"  # el proveedor se negó · reformular
CLI_OCUPADO = "cli_ocupado"                    # tu CLI atiende otro turno · esperar
TURNO_DETENIDO = "turno_detenido"              # lo paraste vos · SIN alarma
SESION_PERDIDA = "sesion_perdida"              # se rehace sola · reintento en curso
RUNTIME_OCUPADO = "runtime_ocupado"            # hay cola local · esperar, no colgado
# GATE 3 · D7 · causas selladas de la costura de tools. Nombran decisiones del
# runtime/modelo que antes se agrupaban en el cajón honesto ``fallo_desconocido``.
GATE_BLOQUEADO = "gate_bloqueado"
ARGUMENTOS_INVALIDOS = "argumentos_invalidos"
# GATE 3 · obra B · ACTA 2 de persona usuaria: SUSTITUIR SÍ, EN SILENCIO NO. El modelo elegido no
# produjo nada y entró el de respaldo: el turno SALIÓ, así que no es un fallo — pero el
# usuario tiene derecho a saber que no corrió con lo que eligió. Vive acá, en el
# vocabulario CERRADO de la UI, porque una causa sin entrada acá no tiene copy.
MODELO_SUSTITUIDO = "modelo_sustituido"
CAUSAS = frozenset({
    FALTA_KEY, SIN_RED, CLI_NO_INSTALADO, SIN_SESION, TIMEOUT, ERROR_UPSTREAM,
    CLI_VERSION_VIEJA, CLI_INTERACTIVO_COLGADO, CLI_SIN_PERMISOS, PLAN_INSUFICIENTE,
    KEY_INVALIDA, OAUTH_REVOCADO, SIN_CREDITO, RATE_LIMIT, MODELO_NO_DISPONIBLE,
    FALLA_DE_ALEPH, PROVEEDOR_CAIDO,
    SERVIDOR_INCOMPATIBLE, NO_ES_MCP, FALLO_DESCONOCIDO,
    CONTEXTO_EXCEDIDO, POLITICA_DE_CONTENIDO, CLI_OCUPADO, TURNO_DETENIDO,
    SESION_PERDIDA, RUNTIME_OCUPADO,
    GATE_BLOQUEADO, ARGUMENTOS_INVALIDOS,
    MODELO_NO_ELEGIDO,
    MODELO_SUSTITUIDO,
})

#: ══ ¿ESTA CAUSA PIDE REINTENTO? ═══════════════════════════════════════════════════════
#: [TANDA 2 · obra A] EL SELLO QUE FALTABA. La distinción existía —está escrita en prosa
#: arriba, causa por causa— pero como CÓDIGO vivía en **una tupla suelta, duplicada** en
#: `centro_conexiones.py:1585` y `:1592`
#: (`causa in (MV.SIN_CREDITO, MV.RATE_LIMIT, MV.SIN_RED, MV.TIMEOUT)`), y ningún otro
#: camino la consultaba. Dos copias de un criterio es cómo la misma falla termina
#: reintentándose en una pantalla y no en la de al lado.
#:
#: EL CRITERIO, y no es «error transitorio»: **¿el mundo puede haber cambiado solo desde la
#: última medición?**
#:
#:   · SÍ  — `sin_red` (te reconectaste) · `timeout` (el server estaba lento) ·
#:           `rate_limit` (pasó la ventana) · `sin_credito` (cargaste saldo) ·
#:           `proveedor_caido` (se levantó) · `cli_ocupado` / `runtime_ocupado` (se
#:           liberó) · `sesion_perdida` (se rehace sola).
#:   · NO  — `key_invalida` · `oauth_revocado` · `falta_key` · `cli_no_instalado` ·
#:           `no_es_mcp` · `servidor_incompatible` · `plan_insuficiente`. Éstas no cambian
#:           **por el paso del tiempo**: cambian porque el usuario hace algo, y ESE algo ya
#:           tiene su gatillo — `medicionRancia` (`conectores/widget.js:89`), que compara la
#:           fecha del veredicto contra la de sus insumos. Reintentarlas por reloj es gastar
#:           un spawn para volver a leer el mismo `401`.
#:
#: `key_invalida` NO es `sin_red`, y ésta es la línea donde eso deja de ser una opinión.
REINTENTABLE = frozenset({
    SIN_RED, TIMEOUT, RATE_LIMIT, SIN_CREDITO, PROVEEDOR_CAIDO,
    CLI_OCUPADO, RUNTIME_OCUPADO, SESION_PERDIDA,
})


def es_reintentable(causa: Optional[str]) -> bool:
    """¿Vale volver a preguntar por el paso del tiempo, sin que nadie haya tocado nada?

    `None` es **False** a propósito: sin causa no hay fallo que reintentar, y devolver
    `True` convertiría «no sé» en «probá de nuevo», que es rellenar un `null` con una
    decisión. Una causa desconocida también es `False`: el default seguro es no gastar."""
    return bool(causa) and causa in REINTENTABLE


#: LAS SEIS DE F1c, aparte. **Ninguna prueba de ESTE módulo las emite** y eso es a propósito:
#: el motor mide CONEXIONES (¿tu cerebro contesta? ¿tu MCP saluda?) y estas seis son de
#: INFERENCIA (¿este turno salió bien?), que es lo que traduce `errores_modelo`. Acá viven
#: sólo para que el vocabulario sea UNO — el semáforo del Cuarto sigue pintando exactamente
#: las mismas causas que antes de F1c, byte por byte, y la vara lo exige.
CAUSAS_F1C = frozenset({
    CONTEXTO_EXCEDIDO, POLITICA_DE_CONTENIDO, CLI_OCUPADO, TURNO_DETENIDO,
    SESION_PERDIDA, RUNTIME_OCUPADO,
})

CEREBRO = "cerebro"
MCP = "mcp"
KEY = "key"
CLI = "cli"
TIPOS = frozenset({CEREBRO, MCP, KEY, CLI})

# TTL de la cache en memoria. Corto a propósito: la verdad envejece.
TTL = float(os.environ.get("PUPPET_MOTOR_TTL", "30"))
_PING_TIMEOUT = float(os.environ.get("PUPPET_MOTOR_PING_TIMEOUT", "20"))
_MCP_TIMEOUT = float(os.environ.get("PUPPET_MOTOR_MCP_TIMEOUT", "45"))

_REPO = Path(__file__).resolve().parents[4]
_PLATFORM = _REPO / "platform"
_ASM = _PLATFORM / "assembler"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))
from safety import url_guard as _url_guard  # noqa: E402
import role as _role  # noqa: E402


def _urlopen_connector(req: urllib.request.Request, *, timeout: float):
    """El control plane sólo contacta Internet público; el cliente conserva self-hosted.

    En el escritorio, una base loopback/LAN es una capacidad explícita (LiteLLM,
    llama.cpp). En el rol ``control`` la misma URL cruza una frontera de red y debe pasar
    por resolución validada, pinning y revalidación de redirects.
    """
    if _role.is_control():
        return _url_guard.open_public_url(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


# ── resultado tipado ──────────────────────────────────────────────────────────────
def _resultado(tipo: str, ref: str, estado: str, *, causa: Optional[str] = None,
               evidencia: Optional[dict] = None, ts: Optional[float] = None,
               destino: Optional[str] = None, camino: Optional[dict] = None) -> dict:
    """Arma el dict del contrato. `causa` SÓLO tiene sentido con estado=roto (se ignora
    en cualquier otro; el front no debería pintar causa sin rojo)."""
    if estado not in ESTADOS:
        raise ValueError(f"estado inválido: {estado!r}")
    if causa is not None and causa not in CAUSAS:
        raise ValueError(f"causa inválida: {causa!r}")
    base = {
        "tipo": tipo,
        "ref": ref,
        "estado": estado,
        "causa": causa if estado == ROTO else None,
        "evidencia": evidencia or {},
        "ts": time.time() if ts is None else ts,
    }
    return DC.aplicar(base, destino=destino or ref, camino=camino)


# ══ [FIX-P11 · §3] EL ESTADO PROBADO PERSISTE ══════════════════════════════════════
# EL BUG MEDIDO (caminata 2026-07-27): «una pieza queda verde y a los segundos vuelve a
# "sin probar"». No era un bug sutil: era el diseño. La cache vivía SÓLO en memoria con
# TTL=30 s, así que a los 30 segundos —o al recargar, o al reabrir la app— la verdad
# verificada desaparecía y el semáforo volvía a 🟡. La persona probaba, veía verde, y el
# producto se olvidaba delante de sus ojos.
#
# El comentario original defendía eso: «un estado verificado no necesita sobrevivir un
# reinicio; re-probar es barato y MÁS honesto». Es falso en los dos tramos. Re-probar NO es
# barato (un MCP stdio spawnea un proceso y tarda segundos; una key pega contra el
# proveedor), y olvidar no es honestidad: es amnesia. Lo honesto es recordar QUÉ pasó y
# CUÁNDO, y decir las dos cosas juntas — «probado a las 13:41» envejece a la vista.
#
# LO QUE INVALIDA UN ESTADO (§3: «sólo por causa real»):
#   · la CONFIG cambió  → `huella`: si la receta/el belt/la llave que se probó ya no es la
#                          misma, el resultado viejo no habla de lo que hay ahora.
#   · la prueba FALLÓ   → el nuevo resultado pisa al viejo (eso es una causa real).
#   · el humano re-prueba (force) → idem.
# El paso del tiempo NO invalida: un verde de hace una hora sigue siendo un verde de hace
# una hora, y así se muestra. Lo que el TTL sigue gobernando es cuándo el motor se permite
# RE-PROBAR solo, no cuándo se le permite RECORDAR.
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
#: Si el disco no está disponible (sandbox, permisos), la persistencia se apaga sola y el
#: motor sigue funcionando en memoria. Degradar nunca puede romper el arranque.
_PERSISTE = os.environ.get("PUPPET_MOTOR_PERSISTE", "1").strip() not in ("0", "false", "no")
_ESTADO_FILE: Optional[Path] = None
_CARGADO = False


def _estado_path() -> Optional[Path]:
    global _ESTADO_FILE
    if _ESTADO_FILE is not None:
        return _ESTADO_FILE
    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
        _ESTADO_FILE = _ap.data_root() / "motor_estado.json"
    except Exception:
        return None
    return _ESTADO_FILE


def _cargar_del_disco() -> None:
    """Una vez por proceso, al primer uso. Un archivo corrupto se ignora entero: un estado
    perdido es un [Probar ahora] de más; un parseo a medias sería basura pintada de verde."""
    global _CARGADO
    if _CARGADO:
        return
    _CARGADO = True
    if not _PERSISTE:
        return
    p = _estado_path()
    if not p or not p.is_file():
        return
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            return
        with _CACHE_LOCK:
            for k, v in (datos.get("estados") or {}).items():
                if isinstance(v, dict) and v.get("estado") in ESTADOS:
                    _CACHE[k] = v
    except Exception:
        pass


def _guardar_al_disco() -> None:
    """Escritura ATÓMICA (tmp + replace): un corte a mitad no deja el archivo mordido."""
    if not _PERSISTE:
        return
    p = _estado_path()
    if not p:
        return
    try:
        with _CACHE_LOCK:
            copia = {k: v for k, v in _CACHE.items()}
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"v": 1, "estados": copia}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _cache_key(tipo: str, ref: str, owner: Optional[str]) -> str:
    # el owner particiona: la key de A jamás puede leer el estado probado de la de B.
    return f"{tipo}\x1f{ref}\x1f{owner or ''}"


def huella_de(tipo: str, ref: str, **kw) -> str:
    """La FIRMA de la configuración que se probó. Si cambia, el resultado viejo caduca —
    aunque sea de hace un segundo. Es la única invalidación por-causa-real que el motor
    puede calcular solo: nadie tiene que acordarse de llamar a `invalidar`."""
    partes = [tipo, ref]
    for k in ("belt_ref", "backed_by", "cli_model"):
        if kw.get(k):
            partes.append(f"{k}={kw[k]}")
    spec = kw.get("spec")
    if spec:
        try:
            partes.append("spec=" + json.dumps(spec, sort_keys=True, ensure_ascii=False))
        except Exception:
            partes.append("spec=?")
    if tipo in (MCP,):
        # el belt es un archivo: su mtime+tamaño es la firma barata de «la receta cambió».
        try:
            b = Path(str(kw.get("belt_ref") or ref))
            if not b.is_absolute():
                b = _REPO / b
            if b.is_file():
                st = b.stat()
                partes.append(f"belt={int(st.st_mtime)}:{st.st_size}")
        except Exception:
            pass
    import hashlib
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()[:16]


def _cache_get(k: str, ttl: float, huella: Optional[str] = None) -> Optional[dict]:
    _cargar_del_disco()
    with _CACHE_LOCK:
        hit = _CACHE.get(k)
    if not hit:
        return None
    # CAUSA REAL nº1 · la config cambió → el veredicto viejo no habla de lo que hay ahora.
    if huella and hit.get("huella") and hit["huella"] != huella:
        with _CACHE_LOCK:
            _CACHE.pop(k, None)
        _guardar_al_disco()
        return None
    if ttl is None:
        return hit                                    # lectura del semáforo: la edad se MUESTRA
    if (time.time() - hit.get("ts", 0.0)) < ttl:
        return hit
    return None


def _cache_put(k: str, result: dict, huella: Optional[str] = None) -> None:
    if huella:
        result = {**result, "huella": huella}
    with _CACHE_LOCK:
        _CACHE[k] = result
    _guardar_al_disco()


def invalidar_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
    # [F7] la auditoría de discriminancia también se olvida: es una medición como
    # cualquier otra, y una vara que la deja pegada mide el proveedor de la prueba anterior.
    with _DISCRIMINA_LOCK:
        _DISCRIMINA.clear()
    _guardar_al_disco()


# ── Pieza Método · estado DERIVADO, persistido con el patrón P11 ────────────────
# No entra a TIPOS porque no tiene un botón «probar»: su prueba ES recalcular
# requires×belt. Guardarlo acá evita otro store/otra ley de semáforo.
METODO = "metodo"


def guardar_estado_metodo(puppet_id: str, method_id: str, *, owner: str,
                          estado_metodo: dict, huella: str) -> dict:
    ref = f"{puppet_id}:{method_id}"
    completo = estado_metodo.get("estado") == "completo"
    result = _resultado(
        METODO, ref, PROBADO if completo else DETECTADO,
        evidencia={
            "detail": estado_metodo.get("detail"),
            "cubiertas": list(estado_metodo.get("cubiertas") or []),
            "faltantes": list(estado_metodo.get("faltantes") or []),
            "resoluciones": list(estado_metodo.get("resoluciones") or []),
        },
    )
    _cache_put(_cache_key(METODO, ref, owner), result, huella)
    return result


def olvidar_por_credencial(provider: str, *, owner: str) -> int:
    """Olvida los veredictos que dependían de ESA credencial. Devuelve cuántos borró.

    Existe para no usar `invalidar_cache()` cuando el disparador afecta a UNA credencial.
    `invalidar_cache` hace `_CACHE.clear()`: borra TODO y lo persiste, así que borrar la
    llave de un servicio dejaba sin evidencia a las otras cuarenta y siete piezas, que no
    tenían nada que ver. Recuperar eso cuesta volver a probarlas a mano, una por una.

    Qué cuenta como «dependía de esa credencial», con el formato de clave
    `tipo\\x1fref\\x1fowner` (`:228`):

        api/cuenta   la ref ES el provider          («api\\x1fgroq\\x1f…»)
        mcp          la ref TERMINA en `#provider`  («mcp\\x1fb.mcp.json#exa\\x1f…»)

    Scoped por owner, como todo lo demás: la llave de un usuario no puede tocar el
    veredicto de otro.
    """
    _cargar_del_disco()
    prov = (provider or "").strip().lower()
    if not prov:
        return 0
    suffix = f"\x1f{owner or ''}"
    n = 0
    with _CACHE_LOCK:
        for key in list(_CACHE):
            if not key.endswith(suffix):
                continue
            partes = key.split("\x1f")
            if len(partes) != 3:
                continue
            ref = partes[1].lower()
            if ref == prov or ref.endswith(f"#{prov}"):
                _CACHE.pop(key, None)
                n += 1
    if n:
        _guardar_al_disco()
    return n


def olvidar_estados_metodo(puppet_id: str, *, owner: str,
                           conservar: Optional[set[str]] = None) -> None:
    """Sin método equipado = opt-in ausente, cero rastro persistido."""
    _cargar_del_disco()
    prefix = f"{METODO}\x1f{puppet_id}:"
    suffix = f"\x1f{owner}"
    changed = False
    with _CACHE_LOCK:
        for key in list(_CACHE):
            if not key.startswith(prefix) or not key.endswith(suffix):
                continue
            method_id = key[len(prefix):-len(suffix)]
            if conservar is not None and method_id in conservar:
                continue
            _CACHE.pop(key, None)
            changed = True
    if changed:
        _guardar_al_disco()


# ── carga dataclass-safe de models.py (bug real: spec sintético rompe @dataclass) ──
_models_mod = None


def _models():
    """`import models` (NO spec_from_file_location) — comparte el módulo ya registrado en
    sys.modules. Cargarlo con un nombre sintético ausente rompe dataclasses._is_type de
    models.py (ResolvedModel). Mismo patrón probado en cuarto_guide/recipe_assembler."""
    global _models_mod
    if _models_mod is None:
        if str(_ASM) not in sys.path:
            sys.path.insert(0, str(_ASM))
        import models as m  # noqa: E402
        _models_mod = m
    return _models_mod


def _cognition_key() -> str:
    """Fallback de key de cognición (infra/.env), la misma que usa un run real. Best-effort."""
    try:
        if str(_ASM) not in sys.path:
            sys.path.insert(0, str(_ASM))
        import recipe_assembler as a  # noqa: E402
        return a._resolve_cognition_key(_REPO) or ""
    except Exception:
        return ""


def _provider_de_key_env(key_env: str, alias: str = "") -> str:
    """`GROQ_API_KEY` → `groq`. El nombre con el que la BYOK del usuario está guardada en el
    vault (misma convención que `_KEY_VALIDATORS` y que el Centro)."""
    p = (key_env or "").strip().upper()
    for suf in ("_API_KEY", "_KEY", "_TOKEN"):
        if p.endswith(suf):
            p = p[: -len(suf)]
            break
    return (p or alias or "").lower()


def _key_del_vault(provider: str, owner: Optional[str],
                   get_conn: Optional[Callable[[], Any]]) -> Optional[str]:
    """(§6a) EL PRIMER PELDAÑO. Lee la BYOK descifrada del usuario ANTES de llamar a nadie.
    Best-effort: si no hay sesión, ni vault, ni fila, devuelve None y el llamador decide —
    lo que NO puede pasar es salir a la red con las manos vacías y volver con un error de
    transporte disfrazado de problema de configuración."""
    if not provider or not owner or get_conn is None:
        return None
    try:
        from app.phase1 import repo
        conn = get_conn()
        try:
            return repo.get_key(conn, owner, provider) or None
        finally:
            conn.close()
    except Exception:
        return None


# ── ping OpenAI-compat compartido (cerebro + key) — REAL, testeable contra un peer local ──
def _ping_chat(base_url: str, model: str, key: Optional[str], *,
               timeout: float = _PING_TIMEOUT) -> dict:
    """UN /chat/completions con prompt mínimo. Devuelve la verdad cruda:
      {ok, http_status, model_final, err_kind, latencia_ms, snippet}
    err_kind ∈ {net, timeout, http} cuando ok=False. model_final = lo que el server REPORTÓ
    (data['model']), no lo pedido — ése es el patrón anti-grift: la UI ve el modelo REAL."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1, "temperature": 0,
    }).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "puppet-motor-verdad/1.0"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=body, method="POST", headers=headers)
    t0 = time.perf_counter()
    try:
        with _urlopen_connector(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        dt = int((time.perf_counter() - t0) * 1000)
        try:
            data = json.loads(raw)
        except Exception:
            return {"ok": False, "http_status": 200, "err_kind": "http",
                    "latencia_ms": dt, "snippet": raw[:200]}
        choice = ((data.get("choices") or [{}])[0]) or {}
        msg = choice.get("message") or {}
        return {"ok": True, "http_status": 200, "model_final": data.get("model") or model,
                "latencia_ms": dt, "snippet": (msg.get("content") or "")[:120]}
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "http_status": e.code, "err_kind": "http",
                "latencia_ms": dt, "snippet": detail or (e.reason or "")}
    except _url_guard.UrlBlocked as e:
        return {"ok": False, "http_status": None, "err_kind": "blocked",
                "latencia_ms": int((time.perf_counter() - t0) * 1000),
                "snippet": e.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        dt = int((time.perf_counter() - t0) * 1000)
        reason = getattr(e, "reason", None) or e
        kind = "timeout" if _looks_timeout(reason) else "net"
        return {"ok": False, "http_status": None, "err_kind": kind,
                "latencia_ms": dt, "snippet": str(reason)[:200]}


def poner_credencial(url: str, key: Optional[str], *, header: str = "bearer",
                     extra: Optional[dict] = None) -> tuple[str, dict]:
    """(url, headers) con la credencial puesta según la FORMA DECLARADA del proveedor.

    ⚠️ [F8 · obra 1] ESTE ES EL ÚNICO LUGAR QUE SABE CÓMO SE AUTENTICA CADA PROVEEDOR, y
    la forma la declara `_KEY_VALIDATORS`. Existe porque el descubrimiento de catálogos
    (`modelos_discovery`) necesitaba exactamente esta lógica y la alternativa era copiarla:
    dos copias del «cómo se manda la llave» se desincronizan en cuanto un proveedor cambia,
    y el síntoma sería un 401 que parece «tu llave no sirve».

    Tres formas, y **son tres porque los proveedores son así**, no por gusto:
      · `bearer`     — `Authorization: Bearer …` (el dialecto OpenAI, la mayoría)
      · `x-api-key`  — Anthropic, que además exige su `anthropic-version` (va en `extra`)
      · `query`      — Google, que toma la credencial como parámetro `?key=` de la URL

    Agregar un proveedor es UNA FILA en `_KEY_VALIDATORS`. Si hiciera falta una cuarta
    forma, va acá con su nombre — jamás un `if provider == …` en el llamador.
    """
    headers = {"User-Agent": "puppet-motor-verdad/1.0"}
    if key and header == "bearer":
        headers["Authorization"] = "Bearer " + key
    elif key and header == "x-api-key":
        headers["x-api-key"] = key
    elif key and header == "query":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={urllib.parse.quote(key, safe='')}"
    if extra:
        headers.update(extra)
    return url, headers


def _ping_models(base_url: str, key: Optional[str], *, header: str = "bearer",
                 extra_headers: Optional[dict] = None, timeout: float = _PING_TIMEOUT) -> dict:
    """GET {base_url}/models — la validación mínima estándar de una key OpenAI-compat.
    Devuelve {ok, http_status, err_kind, latencia_ms, snippet}."""
    url, headers = poner_credencial(base_url.rstrip("/") + "/models", key,
                                    header=header, extra=extra_headers)
    req = urllib.request.Request(url, method="GET", headers=headers)
    t0 = time.perf_counter()
    try:
        with _urlopen_connector(req, timeout=timeout) as resp:
            resp.read()
        return {"ok": True, "http_status": 200,
                "latencia_ms": int((time.perf_counter() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "http_status": e.code, "err_kind": "http",
                "latencia_ms": dt, "snippet": detail or (e.reason or "")}
    except _url_guard.UrlBlocked as e:
        return {"ok": False, "http_status": None, "err_kind": "blocked",
                "latencia_ms": int((time.perf_counter() - t0) * 1000),
                "snippet": e.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        dt = int((time.perf_counter() - t0) * 1000)
        reason = getattr(e, "reason", None) or e
        kind = "timeout" if _looks_timeout(reason) else "net"
        return {"ok": False, "http_status": None, "err_kind": kind,
                "latencia_ms": dt, "snippet": str(reason)[:200]}


def _looks_timeout(reason: Any) -> bool:
    s = str(reason).lower()
    return "timed out" in s or "timeout" in s or isinstance(reason, TimeoutError)


# ══════════════════════════════════════════════════════════════════════════════════
# [FIX-P9 · §6] LA ESCALERA — diagnóstico interno primero, conclusión con camino después
# ══════════════════════════════════════════════════════════════════════════════════
# Barato → caro. Cada peldaño que resuelve el caso CORTA: no se paga el siguiente.
#   (a) ¿está la llave en el vault?    → sin llave NO se llama a nadie. Nunca un error de red
#                                         por una credencial que jamás pusimos.
#   (b) ¿arranca el server local?      → binario ausente = [Instalarlo]; archivo NUESTRO
#                                         ausente = falla de Aleph (§8), no del usuario.
#   (c) SONDA DE INTERNET (red.py)     → nadie escribe `sin_red` sin que la sonda diga NO.
#   (d) hubo respuesta → la RESPUESTA  → 401/403 · 402 · 429 · 5xx · "model not supported".
#                        decide

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0", "[::1]")


def _es_local(destino: Optional[str]) -> bool:
    """¿El destino que falló vive en ESTA máquina? Un stdio o un 127.0.0.1 que no responde
    JAMÁS es «sin internet»: el paquete nunca salió de la placa de red. Confundirlos era
    mandar a la persona a mirar su WiFi por un server que no arrancó."""
    d = (destino or "").strip().lower()
    if not d:
        return False
    if not d.startswith(("http://", "https://", "ws://", "wss://")):
        return True          # un comando stdio: por definición, local
    host = d.split("//", 1)[-1].split("/", 1)[0].split("@")[-1]
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in _LOOPBACK or host.endswith(".local")


def _causa_de_transporte(err_kind: str, destino: Optional[str], ev: dict) -> str:
    """(§6c) EL FIX DE LA MENTIRA. Un fallo de transporte NO es, por sí solo, «sin internet»:
    es «ese destino no contestó». Para culpar a la red hace falta una SEGUNDA medición,
    independiente del destino que falló — la sonda de `red.py`.

    Deja la evidencia de lo que se consultó (`red`), así el desenlace puede mostrar por qué
    decimos lo que decimos en vez de pedir que se nos crea."""
    if _es_local(destino):
        ev["red"] = {"consultada": False, "motivo": "destino local — la red no interviene"}
        return TIMEOUT if err_kind == "timeout" else ERROR_UPSTREAM
    try:
        from app.phase1 import red as _red
        s = _red.sonda()
    except Exception as e:  # noqa: BLE001
        ev["red"] = {"consultada": False, "motivo": f"la sonda no pudo correr: {e}"}
        return TIMEOUT if err_kind == "timeout" else PROVEEDOR_CAIDO
    ev["red"] = {"consultada": True, "online": s.get("online"), "via": s.get("via"),
                 "cacheado": s.get("cacheado")}
    if s.get("online") is False:
        return SIN_RED                      # ← el ÚNICO camino a `sin_red`. Con evidencia.
    if s.get("online") is True:
        # Hay internet y ESTE destino no contesta → el proveedor está caído. Esa es la
        # distinción que la persona necesita: no es su WiFi, no es su llave, es de ellos.
        return TIMEOUT if err_kind == "timeout" else PROVEEDOR_CAIDO
    # DESCONOCIDO: la sonda no pudo decidir. Un desconocido NO se convierte en `sin_red`
    # (sería inventar la conclusión más cara). Se reporta lo que sí sabemos.
    return TIMEOUT if err_kind == "timeout" else ERROR_UPSTREAM


#: Frases con las que los proveedores dicen «ese modelo no es para vos». No hay status HTTP
#: propio para esto: OpenAI manda 404, Anthropic 403, Groq 400 — el dato está en el cuerpo.
_RE_MODELO = ("model_not_found", "model not found", "does not exist", "no such model",
              "model not supported", "unsupported model", "unknown model",
              "invalid model", "modelo no")
_RE_PLAN = ("not have access", "no access", "insufficient_quota", "not entitled",
            "upgrade", "your plan", "tier", "subscription", "permission to use",
            "not allowed to use", "billing")


def _infra_403(txt: str) -> Optional[str]:
    """¿403 de un WAF y no del proveedor juzgando la llave? Lo decide el TRADUCTOR.

    Devuelve `"bloqueo"` (WAF nos rechazó · culpa nuestra), `"ritmo"` (WAF nos frenó · hay
    que esperar) o `None` (el 403 habla de otra cosa y sigue el camino de siempre).

    Import BLANDO como el resto: sin traductor en el árbol devuelve `None`. Fallar hacia el
    comportamiento viejo es peor que fallar hacia uno nuevo sin dueño."""
    try:
        import aleph_paths as _ap                  # noqa: PLC0415 — igual que `_estado_path`
        _asm = str(_ap.resource_root() / "platform" / "assembler")
        if _asm not in sys.path:
            sys.path.insert(0, _asm)
        import errores_modelo as _em                # type: ignore
        if _em.bloqueo_de_infra(txt):
            return "bloqueo"
        if _em.ritmo_de_infra(txt):
            return "ritmo"
        return None
    except Exception:                              # noqa: BLE001
        return None


def _causa_de_http(status: Optional[int], cuerpo: str = "", *,
                   tenia_key: Optional[bool] = None) -> str:
    """(§6d) La RESPUESTA decide. El status manda; el cuerpo desempata cuando el proveedor
    metió dos significados distintos en el mismo número.

      401/403/407 → la llave. `key_invalida` si HABÍA una (la mandamos y la rechazaron);
                    `falta_key` sólo si fuimos sin credencial.
      402         → sin saldo. La llave sirve — es la cuenta la que está vacía.
      429         → te frenaron. No está roto: hay que esperar.
      404/400     → si el cuerpo habla de un modelo, es el modelo; si no, el endpoint.
      5xx         → proveedor caído.
    """
    txt = (cuerpo or "").lower()
    if status in (401, 403, 407):
        # ⚠️ LEY SELLADA (persona usuaria, 2026-08-07): UN 403 NO ES AUTOMÁTICAMENTE LA CREDENCIAL.
        # MEDIDO: sin `User-Agent`, groq contesta 403 «error code: 1010» —el WAF de
        # Cloudflare bloqueando por NUESTRA firma de cliente— y esta función lo leía como
        # `key_invalida`. O sea: mandaba a rotar una llave perfecta, que es de los peores
        # errores posibles (la persona borra algo que funciona y sigue sin andar).
        #
        # El detector vive en el TRADUCTOR, que es el dueño del vocabulario de causas; acá
        # se IMPORTA, no se copia. Dos listas de firmas se separan, y separarse acá
        # significa que el motor acusa a la llave y el chat dice otra cosa.
        if status == 403 and _infra_403(txt) == "bloqueo":
            return FALLA_DE_ALEPH
        if status == 403 and _infra_403(txt) == "ritmo":
            return RATE_LIMIT
        # 403 + "no tenés acceso a ese modelo" es plan, no llave: la llave es válida y el
        # proveedor la reconoció lo bastante como para saber qué NO te toca.
        if status == 403 and any(w in txt for w in _RE_PLAN) and not any(
                w in txt for w in ("invalid", "expired", "revoked", "authentication")):
            return PLAN_INSUFICIENTE
        return KEY_INVALIDA if tenia_key else FALTA_KEY
    if status == 402:
        return SIN_CREDITO
    if status == 429:
        # Un 429 con lenguaje de cuota agotada (no de ritmo) es saldo, no ritmo.
        return SIN_CREDITO if "insufficient_quota" in txt else RATE_LIMIT
    if any(w in txt for w in _RE_MODELO):
        return MODELO_NO_DISPONIBLE
    if any(w in txt for w in _RE_PLAN):
        return PLAN_INSUFICIENTE
    if status is not None and 500 <= status < 600:
        return PROVEEDOR_CAIDO
    if status == 404:
        return MODELO_NO_DISPONIBLE
    return ERROR_UPSTREAM


# ══════════════════════════════════════════════════════════════════════════════════
# PRUEBA 1 · CLI  (spawn + version + auth status) — EXTIENDE cli_brain.detect
# ══════════════════════════════════════════════════════════════════════════════════
def prueba_cli(provider_id: str) -> dict:
    """El estado REAL de un cerebro-por-suscripción (Mi Claude Code / Mi Codex). Reusa el
    detector D2 (spawn del binario + `auth status`, cache TTL propia). JAMÁS lee tokens."""
    try:
        if str(_ASM) not in sys.path:
            sys.path.insert(0, str(_ASM))
        from cli_brain import detect  # noqa: E402  (paquete cli_brain desde el dir del assembler)
        from cli_brain.base import STATE_READY, STATE_NO_AUTH, STATE_NOT_INSTALLED  # noqa: E402
    except Exception as e:
        return _resultado(CLI, provider_id, ROTO, causa=ERROR_UPSTREAM,
                          evidencia={"detail": f"no pude cargar el detector CLI: {e}"})
    st = detect.detect_one(provider_id)
    if st is None:
        return _resultado(CLI, provider_id, NO_CONFIGURADO,
                          evidencia={"detail": f"provider CLI desconocido: {provider_id!r} "
                                               f"(esperaba {' | '.join(detect.PROVIDERS)})"})
    d = st.to_dict(public=True)   # sin path del binario (anti-fingerprint)
    ev = {"detail": d.get("detail", ""), "installed": d.get("installed", False),
          "extra": d.get("extra", {}), "checked_at": d.get("checked_at")}
    if st.state == STATE_READY:
        return _resultado(CLI, provider_id, PROBADO, evidencia=ev, ts=st.checked_at or None)
    if st.state == STATE_NO_AUTH:
        # instalado sin login → arreglo = login del CLI. (Si el detector marcó un timeout del
        # chequeo, la causa honesta es timeout, no sesión.)
        causa = TIMEOUT if "no respondió" in (st.detail or "").lower() else SIN_SESION
        return _resultado(CLI, provider_id, ROTO, causa=causa, evidencia=ev, ts=st.checked_at or None)
    if st.state == STATE_NOT_INSTALLED:
        return _resultado(CLI, provider_id, ROTO, causa=CLI_NO_INSTALADO, evidencia=ev,
                          ts=st.checked_at or None)
    return _resultado(CLI, provider_id, ROTO, causa=ERROR_UPSTREAM, evidencia=ev)


# ══════════════════════════════════════════════════════════════════════════════════
# PRUEBA 2 · CEREBRO  (ping real, model_final honesto) — patrón anti-grift + anti-SSRF
# ══════════════════════════════════════════════════════════════════════════════════
def prueba_cerebro(alias: str, *, cli_model: Optional[str] = None,
                   owner: Optional[str] = None,
                   get_conn: Optional[Callable[[], Any]] = None) -> dict:
    """Prueba un cerebro del catálogo: resuelve SÓLO por alias del registro confiable
    (models.ALIASES → base_url/key vetados; jamás un endpoint crudo del cliente: anti-SSRF/
    exfil, igual que cuarto_guide), pingea con prompt mínimo y lee el model_final HONESTO.

    El estado del cerebro del Guía y del selector SALE DE ACÁ, no de "el binario existe"."""
    M = _models()
    alias = (alias or "").strip()
    if not alias or alias not in M.ALIASES:
        return _resultado(CEREBRO, alias, NO_CONFIGURADO,
                          evidencia={"detail": "elige un cerebro del catálogo (alias conocido); "
                                               "no se aceptan endpoints arbitrarios",
                                     "aliases": sorted(M.ALIASES.keys())})

    # Cerebro CLI: la disponibilidad la MANDA el detector D2 (no el server :8926). Si el CLI
    # no está listo, decilo con SU causa (cli_no_instalado / sin_sesion), no un upstream opaco.
    if alias in M.CLI_BRAIN_PROVIDERS:
        cli = prueba_cli(alias)
        if cli["estado"] != PROBADO:
            ev = dict(cli["evidencia"]); ev["via"] = "cli_brain.detect"
            return _resultado(CEREBRO, alias, cli["estado"], causa=cli["causa"], evidencia=ev)

    target = M.DEFAULT_BRAIN if (alias == "brain" and M.DEFAULT_BRAIN != "brain") else alias
    rm = M.resolve(target)
    base_url = (rm.base_url or "").rstrip("/")
    model = rm.model or ""
    key_env = rm.key_env
    if not base_url or not model:
        return _resultado(CEREBRO, alias, NO_CONFIGURADO,
                          evidencia={"detail": f"no pude resolver el cerebro {alias!r}"})

    # ── (§6a) PELDAÑO 1 · ¿está la llave? — ANTES de llamar a nadie ────────────────
    # Orden: el vault del usuario (su BYOK) gana, después el entorno del proceso. Sin
    # ninguna de las dos NO se sale a la red: se dice «falta tu llave». Antes, un alias con
    # key_env vacío igual pingueaba sin Authorization y volvía con un 401 que la UI pintaba
    # como problema del proveedor — la respuesta correcta al síntoma equivocado.
    key: Optional[str] = None
    provider = _provider_de_key_env(key_env, alias) if key_env else ""
    if key_env:
        key = _key_del_vault(provider, owner, get_conn) or os.environ.get(key_env, "") or _cognition_key()
        if not key:
            return _resultado(CEREBRO, alias, ROTO, causa=FALTA_KEY,
                              evidencia={"detail": f"falta tu llave de {provider or alias} para este "
                                                   f"cerebro; ponla o elige tu CLI local",
                                         "key_env": key_env, "provider": provider,
                                         "escalon": "vault", "consultado_vault": bool(owner)})

    ping = _ping_chat(base_url, model, key)
    if ping["ok"]:
        model_final = ping.get("model_final") or model
        ev = {"requested": model, "model_final": model_final,
              "coincide": model_final == model, "degradado": model_final != model,
              "latencia_ms": ping.get("latencia_ms"), "alias": alias,
              "snippet": ping.get("snippet", "")}
        # model_final != requested NO es roto: el free-tier degrada POR DISEÑO. Se REPORTA
        # honesto (degradado=True) para que la UI/Guía lo muestren; sigue PROBADO (respondió).
        return _resultado(CEREBRO, alias, PROBADO, evidencia=ev)

    ev = {"requested": model, "latencia_ms": ping.get("latencia_ms"),
          "http_status": ping.get("http_status"), "detail": ping.get("snippet", ""),
          "provider": provider or alias}
    kind = ping["err_kind"]
    if kind in ("net", "timeout"):
        # (§6c) NO se escribe `sin_red` acá: lo decide la sonda, mirando el destino real.
        return _resultado(CEREBRO, alias, ROTO,
                          causa=_causa_de_transporte(kind, base_url, ev), evidencia=ev)
    # (§6d) hubo respuesta → la respuesta decide. `tenia_key` separa «no la pusiste» de
    # «la pusiste y la rechazaron»: son dos botones distintos ([Poner] vs [Cambiar]).
    causa = _causa_de_http(ping.get("http_status"), ping.get("snippet", ""), tenia_key=bool(key))
    if alias in M.CLI_BRAIN_PROVIDERS and ping.get("http_status") in (401, 403):
        causa = SIN_SESION
    return _resultado(CEREBRO, alias, ROTO, causa=causa, evidencia=ev)


# ══════════════════════════════════════════════════════════════════════════════════
# PRUEBA 3 · MCP  (handshake initialize + tools/list) — EXTIENDE inspection.byo_mcp
# ══════════════════════════════════════════════════════════════════════════════════
def prueba_mcp(*, spec: Optional[dict] = None, belt_ref: Optional[str] = None,
               backed_by: Optional[str] = None, secret: Optional[str] = None,
               owner: Optional[str] = None,
               get_conn: Optional[Callable[[], Any]] = None) -> dict:
    """Conecta al MCP y lista sus tools REALES (cero theater). `spec` directo
    {transport, url|command, args, env, headers, connector} o (belt_ref+backed_by) para
    leerlo del belt. Si el server pide auth y hay owner+connector, inyecta la BYOK del user;
    si la necesita y no la tenemos → FALTA_KEY sin siquiera conectar (honesto)."""
    ref = belt_ref and f"{belt_ref}#{backed_by}" or (spec or {}).get("url") \
        or (spec or {}).get("command") or "mcp"
    if spec is None:
        try:
            spec = _spec_de_belt(belt_ref, backed_by)
        except HTTPException as e:
            return _resultado(MCP, ref, NO_CONFIGURADO,
                              evidencia={"detail": getattr(e, "detail", str(e))})
    if not spec:
        return _resultado(MCP, ref, NO_CONFIGURADO,
                          evidencia={"detail": "falta el spec del MCP (spec o belt_ref+backed_by)"})

    def _reparacion_local(ev: dict) -> Optional[dict]:
        """Un fallo local posterior al arranque también debe terminar en una mano simple."""
        try:
            from app.phase1 import remedios_conectores as _rem
            catalog_id = (belt_ref and backed_by and f"{belt_ref}#{backed_by}") \
                or str(spec.get("catalog_id") or spec.get("connector")
                       or spec.get("command") or ref)
            remedio = _rem.resolver(
                spec, catalog_id=catalog_id, fuente=spec.get("fuente"), buscar_ia=False
            )
            ev["remedio"] = remedio
            return _rem.camino_de(remedio)
        except Exception:
            return None

    transport = (spec.get("transport") or ("http" if spec.get("url") else "stdio")).lower()
    connector = spec.get("connector")
    needs_auth = bool(spec.get("header_name") or spec.get("package_env_var")
                      or spec.get("needs_auth"))

    # Resolver secreto: explícito > BYOK del user (por connector).
    if secret is None and needs_auth and owner and connector and get_conn is not None:
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                secret = repo.get_key(conn, owner, connector)
            finally:
                conn.close()
        except Exception:
            secret = None
    if needs_auth and not secret:
        return _resultado(MCP, ref, ROTO, causa=FALTA_KEY,
                          evidencia={"detail": f"este MCP necesita tu credencial de "
                                               f"{connector or 'el proveedor'} para conectar",
                                     "connector": connector, "transport": transport,
                                     "destino": spec.get("url") or spec.get("command")},
                          destino=spec.get("url") or spec.get("command"))

    # ── (§6b) PELDAÑO 2 · ¿arranca el server local? — ANTES del spawn caro ──────────
    if transport != "http":
        falta = dependencia_local(spec)
        if falta:
            ev = {k: v for k, v in falta.items() if k != "causa"}
            ev.update({"transport": transport, "escalon": "dependencia",
                       "command": spec.get("command"),
                       "destino": spec.get("command"),
                       "red": {"consultada": False,
                               "motivo": "destino local — la red no interviene"}})
            camino = None
            if falta["causa"] == CLI_NO_INSTALADO:
                try:
                    from app.phase1 import remedios_conectores as _rem
                    catalog_id = (belt_ref and backed_by and f"{belt_ref}#{backed_by}") \
                        or str(spec.get("catalog_id") or spec.get("command") or ref)
                    remedio = _rem.resolver(
                        spec, catalog_id=catalog_id, fuente=spec.get("fuente"), buscar_ia=True
                    )
                    ev["remedio"] = remedio
                    camino = _rem.camino_de(remedio)
                except Exception as exc:  # la cascada no puede tapar el diagnóstico primario
                    ev["remedio"] = {
                        "estado": "no_encontre",
                        "mensaje": "No encontré cómo instalarlo.",
                        "detail": str(exc)[:240],
                    }
            return _resultado(MCP, ref, ROTO, causa=falta["causa"], evidencia=ev,
                              destino=spec.get("command"), camino=camino)

    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        from inspection import byo_mcp  # noqa: E402  (zona RESOLVE → viaja al cliente frozen)
    except Exception as e:
        # El probe MCP es NUESTRO. Si no carga, el bundle está incompleto — §8: se dice que
        # es un defecto de Aleph, jamás «error del proveedor» por un módulo que no viajó.
        return _resultado(MCP, ref, ROTO, causa=FALLA_DE_ALEPH,
                          evidencia={"detail": f"no pude cargar el probe MCP de Aleph: {e}",
                                     "modulo": "inspection.byo_mcp"})

    kw: dict = {"transport": transport, "timeout": _MCP_TIMEOUT}
    # Sólo se ejercita la credencial si HAY credencial. Un MCP keyless no tiene nada que
    # probar y el requisito no le aplica — no puede bloquearle el verde.
    if secret and isinstance(spec.get("prueba_credencial"), dict):
        kw["prueba_credencial"] = spec["prueba_credencial"]
    if transport == "http":
        kw["url"] = spec.get("url")
        headers = dict(spec.get("headers") or {})
        if secret and spec.get("header_name"):
            tmpl = spec.get("header_template") or "{}"
            headers[spec["header_name"]] = tmpl.replace("{}", secret) if "{}" in tmpl else \
                tmpl.replace("{secret}", secret) if "{secret}" in tmpl else secret
        kw["headers"] = headers
    else:
        # Se spawnea con las variables YA EXPANDIDAS y con las del entorno de un run real
        # (PUPPET_BELTS/WORKDIR/REPO). Antes iban crudas: el server recibía literalmente
        # `${PUPPET_WORKDIR}/datos.db` y creaba un directorio con ESE nombre al lado del
        # proceso. Y peor para lo que nos ocupa: el diagnóstico (que sí expande) y la
        # ejecución (que no) hablaban de rutas distintas — dos verdades sobre la misma pieza.
        entorno = _entorno_de_belts()
        kw["command"] = _expandir(spec.get("command") or "", entorno)
        kw["args"] = [_expandir(str(a), entorno) for a in (spec.get("args") or [])]
        # El entorno viaja COMPLETO (os.environ + las PUPPET_*), no sólo el del belt. El
        # spawn de abajo REEMPLAZA el ambiente del hijo cuando se le pasa un dict: mandarle
        # sólo las tres variables del belt le sacaba el PATH, y entonces `uvx` o `npx`
        # dejaban de existir para el server. Ese era un agujero PREEXISTENTE —cualquier belt
        # con `env` propio spawneaba sin PATH— que sólo se veía como «el server no arrancó».
        env = dict(entorno)
        # ⚠️ EL `${VAR}` DEL BELT SE RESUELVE CONTRA EL LLAVERO, no sólo contra las PUPPET_*.
        #
        # Los belts declaran su credencial así: `env: {"EXA_API_KEY": "${EXA_API_KEY}"}`. Sin
        # esto, `_expandir` sólo conocía PUPPET_BELTS/WORKDIR/REPO, así que el placeholder
        # llegaba literal al hijo y el server arrancaba SIN la llave del usuario. Nadie lo
        # notó nunca porque listar tools funciona igual sin credencial — el agujero recién
        # se ve cuando algo LLAMA una tool, que es exactamente lo que hace el 4º requisito.
        #
        # Se usa el MISMO resolver que un run real (`credential_broker.make_user_resolver`)
        # a propósito: si la prueba resolviera las credenciales por su cuenta, la prueba y la
        # ejecución podrían discrepar sobre la misma pieza — dos verdades, que es el fallo
        # que este árbol viene evitando en todos lados.
        llavero: dict = {}
        if owner and get_conn is not None:
            try:
                from app.phase1.credential_broker import make_user_resolver
                resolver = make_user_resolver(owner, get_conn=get_conn)
                for _k, _v in (spec.get("env") or {}).items():
                    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(_v).strip())
                    if not m:
                        continue
                    # el ref del llavero es el CONNECTOR de la pieza, no el nombre de la var
                    val = resolver(connector) if connector else ""
                    if val:
                        llavero[m.group(1)] = val
            except Exception:                    # noqa: BLE001 — sin llavero se sigue igual
                llavero = {}
        entorno_expansion = {**entorno, **llavero}
        env.update({k: _expandir(str(v), entorno_expansion)
                    for k, v in (spec.get("env") or {}).items()})
        if secret and spec.get("package_env_var"):
            env[spec["package_env_var"]] = secret
        kw["env"] = env

    # El destino real de la prueba: la URL si es HTTP, el comando si es stdio. Es lo que la
    # sonda necesita para no confundir «este server no arrancó» con «no hay internet».
    destino = kw.get("url") if transport == "http" else (kw.get("command") or "stdio")
    t0 = time.perf_counter()
    try:
        probe = byo_mcp.probe_mcp(**kw)
    except byo_mcp.BYOValidationError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        msg = str(e)
        capturada = dict(getattr(e, "evidencia", None) or {})
        # La sonda conserva el motivo concreto del arranque (initialize sin respuesta,
        # rechazo JSON-RPC, excepción del spawn). No lo tapes con el envoltorio genérico
        # de BYOValidationError: ése fue el origen de los diagnósticos “No sé qué pasó”.
        detalle_capturado = str(capturada.get("detail") or "").strip()
        ev = {
            **capturada,
            "detail": detalle_capturado or msg,
            "probe_error": msg,
            "latencia_ms": dt,
            "transport": transport,
            "destino": destino,
        }
        if transport != "http":
            ev["red"] = {"consultada": False,
                         "motivo": "destino local — la red no interviene"}
        camino = _reparacion_local(ev) if transport != "http" else None
        return _resultado(MCP, ref, ROTO,
                          causa=_causa_mcp_error(DC.crudo_de(ev), destino, ev),
                          evidencia=ev, destino=destino, camino=camino)
    except Exception as e:  # transporte/URL rechazada por el guard SSRF interno, etc.
        dt = int((time.perf_counter() - t0) * 1000)
        ev = {"detail": str(e), "latencia_ms": dt, "transport": transport,
              "destino": destino}
        if transport != "http":
            ev["red"] = {"consultada": False,
                         "motivo": "destino local — la red no interviene"}
        camino = _reparacion_local(ev) if transport != "http" else None
        return _resultado(MCP, ref, ROTO,
                          causa=_causa_mcp_error(str(e), destino, ev), evidencia=ev,
                          destino=destino, camino=camino)
    dt = int((time.perf_counter() - t0) * 1000)
    tools = probe.get("tools") or []
    ev = {"server_info": probe.get("server_info") or {},
          "tool_count": len(tools), "tools": [t.get("name") for t in tools][:40],
          "latencia_ms": dt, "transport": transport, "destino": destino}
    if transport != "http":
        ev["red"] = {"consultada": False, "motivo": "destino local — la red no interviene"}

    # ── § CLASE 2 · EL VERDE TIENE QUE HABER MEDIDO LA CREDENCIAL ────────────────────
    # Hasta acá lo único probado es que el proceso arranca, saluda y lista tools. Eso NO
    # dice nada de la llave: el server publica su catálogo igual con una credencial basura,
    # porque la llave recién viaja cuando se LLAMA una tool. Medido: con
    # `clave-falsa-de-prueba-0000`, siete conectores quedaban verdes con tools completas y
    # el fallo aparecía en medio de una tarea del usuario.
    #
    # Las tres ramas, y la del medio es la que hace que el verde signifique algo:
    #
    #   hay llave + tool declarada   se corrió  → PROBADO, o ROTO con su causa
    #   hay llave + SIN declarar     no se midió → DETECTADO (ámbar). NUNCA verde.
    #   sin llave                    no aplica   → PROBADO como siempre
    #
    # DETECTADO y no ROTO a propósito: no medimos, y "no lo sé" no es "está mal". El
    # registro público no tiene curación y cae entero en esa rama — y eso está bien: es la
    # verdad, y es exactamente el valor del piso curado, que sí puede prometer verde.
    cred = probe.get("credencial") if isinstance(probe, dict) else None
    # ⚠️ «TIENE CREDENCIAL» SE DERIVA DEL `env`, NO DE `needs_auth`.
    #
    # `needs_auth` sale de `_meta.cards[].auth`, que muchos belts no declaran: medido,
    # `context7`, `github` y `gmail` dan `needs_auth=False` y `connector=None` mientras su
    # env pide `${CONTEXT7_API_KEY}`, `${GITHUB_PERSONAL_ACCESS_TOKEN}` y `${GMAIL_TOKEN}`.
    # Con esos tres, la regla del cuarto requisito no se aplicaba y seguían pintando VERDE
    # con una llave basura — el bug original, sobreviviendo en los que la metadata olvidó.
    #
    # El `${VAR}` del env es la declaración que no puede mentir: es lo que el server
    # realmente necesita al spawnear, y es lo mismo que usa un run de verdad. Un
    # `${PUPPET_BELTS}` no cuenta: ésos los resuelve el entorno del belt, no el llavero.
    declara_credencial = bool(secret) or any(
        re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(v).strip())
        and re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(v).strip()).group(1) not in entorno
        for v in (spec.get("env") or {}).values()
    ) if transport != "http" else bool(secret)
    if cred is not None:
        ev["credencial"] = cred
        if not cred.get("ok"):
            causa = KEY_INVALIDA if cred.get("rechazada") else ERROR_UPSTREAM
            ev["detail"] = cred.get("detalle") or "la credencial no pasó la prueba"
            return _resultado(MCP, ref, ROTO, causa=causa, evidencia=ev, destino=destino)
    elif declara_credencial:
        ev["credencial"] = {
            "probada": False,
            "detalle": "este conector no declara con qué tool probar su credencial: "
                       "se confirma en el primer uso real",
        }
        return _resultado(MCP, ref, DETECTADO, evidencia=ev, destino=destino)
    return _resultado(MCP, ref, PROBADO, evidencia=ev, destino=destino)


_traductor_mod = None


def _traductor():
    """`traductor_errores` — la taxonomía del transporte → NUESTRAS causas tipadas.

    Se carga perezoso y se cachea, con el mismo patrón que `_models()`: `platform/inspection`
    puede no estar en `sys.path` cuando este módulo se importa suelto, y compartir la
    instancia de `sys.modules` evita dos copias del traductor con dos criterios."""
    global _traductor_mod
    if _traductor_mod is None:
        _insp = str(_PLATFORM / "inspection")
        if _insp not in sys.path:
            sys.path.insert(0, _insp)
        import traductor_errores as _t                      # noqa: E402
        _traductor_mod = _t
    return _traductor_mod


def _causa_mcp_error(msg: str, destino: Optional[str] = None,
                     ev: Optional[dict] = None) -> str:
    """Igual que antes, PERO sin la mentira: «connection refused» ya no se traduce solo a
    `sin_red`. Un stdio que no arranca y un 127.0.0.1 que no escucha nunca tocaron la red;
    y para un host remoto la palabra la tiene la sonda, no el texto de la excepción."""
    m = (msg or "").lower()
    ev = ev if ev is not None else {}
    # (sesión 2 · recableo) EL CÓDIGO ANTES QUE EL TEXTO. Cuando el transporte tipa el
    # error —el SDK lo hace— no hace falta adivinar por palabras: `-32001` es vencimiento y
    # `-32000` es canal caído, sin ambigüedad. Con el cliente viejo no hay código y se cae a
    # las mismas reglas de texto de siempre, así que un registro escrito por él se sigue
    # leyendo igual. La causa que devuelve `_causa_de_transporte` es la misma en los dos
    # caminos: lo que cambia es la FUENTE de la señal, no el veredicto.
    _codigo = _traductor().codigo_de(msg)
    if _codigo == _traductor().TIMEOUT:
        return _causa_de_transporte("timeout", destino, ev)
    if _codigo == _traductor().CONEXION_MUERTA:
        return _causa_de_transporte("net", destino, ev)
    if any(w in m for w in ("timed out", "timeout")):
        return _causa_de_transporte("timeout", destino, ev)
    if any(w in m for w in ("refused", "connection", "unreachable", "no arrancó", "no route",
                            "name or service", "getaddrinfo", "no se pudo", "network", "ssl")):
        return _causa_de_transporte("net", destino, ev)
    if any(w in m for w in ("url", "insegura", "rechaz", "guard", "http(s)")):
        return ERROR_UPSTREAM
    # conectó pero no lista tools usables, o protocolo raro → problema del server, no de red.
    return ERROR_UPSTREAM


# ══════════════════════════════════════════════════════════════════════════════════
# (§6b) ¿ARRANCA EL SERVER LOCAL? — el peldaño que separa TU máquina de NUESTRO bug
# ══════════════════════════════════════════════════════════════════════════════════
#: Cómo se instala cada programa que un server MCP local puede necesitar. Sin esto, el
#: camino honesto («[Instalarlo]») no tendría qué decir después de la palabra "instalalo",
#: y volveríamos al workflow-consejo que este trabajo viene a matar.
INSTALACION: dict[str, dict] = {
    "npx":     {"programa": "Node.js", "como": "brew install node",
                "url": "https://nodejs.org/es/download"},
    "node":    {"programa": "Node.js", "como": "brew install node",
                "url": "https://nodejs.org/es/download"},
    "uvx":     {"programa": "uv", "como": "brew install uv",
                "url": "https://docs.astral.sh/uv/getting-started/installation/"},
    "uv":      {"programa": "uv", "como": "brew install uv",
                "url": "https://docs.astral.sh/uv/getting-started/installation/"},
    "docker":  {"programa": "Docker Desktop", "como": "brew install --cask docker",
                "url": "https://www.docker.com/products/docker-desktop/"},
    "python3": {"programa": "Python 3", "como": "brew install python",
                "url": "https://www.python.org/downloads/"},
    "deno":    {"programa": "Deno", "como": "brew install deno", "url": "https://deno.com/"},
    "bun":     {"programa": "Bun", "como": "brew install oven-sh/bun/bun", "url": "https://bun.sh/"},
    "freecad": {"programa": "FreeCAD", "como": "brew install --cask freecad",
                "url": "https://www.freecad.org/downloads.php"},
    "FreeCAD": {"programa": "FreeCAD", "como": "brew install --cask freecad",
                "url": "https://www.freecad.org/downloads.php"},
    # [FIX-P11 · §5] las apps EXTERNAS que los belts asumen instaladas. Sin fila acá, el
    # workflow terminaba en «no tengo la instrucción exacta para X» — el consejo vacío que
    # la ley §4 prohíbe. Caso índice de la caminata: KiCad.
    "kicad":   {"programa": "KiCad", "como": "brew install --cask kicad",
                "url": "https://www.kicad.org/download/"},
    "KiCad":   {"programa": "KiCad", "como": "brew install --cask kicad",
                "url": "https://www.kicad.org/download/"},
    "kicad-cli": {"programa": "KiCad", "como": "brew install --cask kicad",
                  "url": "https://www.kicad.org/download/"},
    "openfoam": {"programa": "OpenFOAM", "como": "brew install --cask docker",
                 "url": "https://www.openfoam.com/download/"},
    "slicer":  {"programa": "3D Slicer", "como": "brew install --cask slicer",
                "url": "https://download.slicer.org/"},
}

#: [FIX-P11 · §5] LA DEPENDENCIA DE SEGUNDO NIVEL. Hay programas que estar instalados no
#: alcanza: tienen que estar CORRIENDO. Docker es el caso índice (OpenFOAM/materialsproject
#: se sirven por contenedor): `which docker` dice que sí, el servidor igual no arranca, y el
#: diagnóstico se lo comía como «error del proveedor» — mandando a la persona a revisar su
#: WiFi por un demonio apagado. «Docker no está corriendo» y «Docker no está instalado» son
#: dos frases distintas porque son dos arreglos distintos: abrir la app vs instalarla.
_SEGUNDO_NIVEL: dict[str, dict] = {
    "docker": {"programa": "Docker", "sonda": ["docker", "info", "--format", "{{.ServerVersion}}"],
               "como_arrancar": "open -a Docker",
               "detail": "Docker está instalado pero no está corriendo. Abre Docker Desktop "
                         "y espera a que la ballena deje de moverse; después prueba de nuevo.",
               "url": "https://www.docker.com/products/docker-desktop/"},
}


def _segundo_nivel(binario: str, encontrado: str) -> Optional[dict]:
    """El chequeo barato de «está, pero no está listo». Devuelve None si todo bien o si no
    conocemos un segundo nivel para este programa. Nunca levanta: una sonda de diagnóstico
    que rompe el diagnóstico sería peor que no tenerla."""
    clave = Path(binario).name.lower()
    reg = _SEGUNDO_NIVEL.get(clave)
    if not reg:
        return None
    import subprocess
    cmd = [encontrado] + list(reg["sonda"][1:])
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=8, text=True)
    except Exception as e:
        return {"causa": CLI_NO_INSTALADO, "programa": reg["programa"], "binario": binario,
                "nivel": "servicio_caido", "como": reg.get("como_arrancar"),
                "url": reg.get("url"),
                "detail": f"{reg['programa']} está instalado pero no pude preguntarle si "
                          f"está corriendo ({e})."}
    if p.returncode == 0 and (p.stdout or "").strip():
        return None                                   # instalado Y corriendo: nada que decir
    return {"causa": CLI_NO_INSTALADO, "programa": reg["programa"], "binario": binario,
            "nivel": "servicio_caido", "instalado": True,
            "como": reg.get("como_arrancar"), "url": reg.get("url"),
            "detail": reg["detail"],
            "salida": ((p.stderr or p.stdout or "").strip()[:240] or None)}

_INTERPRETES = ("python", "python3", "node", "deno", "bun", "ruby", "sh", "bash")

# ── ${PUPPET_BELTS} y compañía — EXPANDIR ANTES DE DIAGNOSTICAR ────────────────────
# Los belts declaran sus servers con variables: `python3 ${PUPPET_BELTS}/cowork/drive_server.py`.
# Diagnosticar sobre el texto SIN expandir daba un veredicto falso y encima del tipo peor:
# «drive_server.py no está instalado» — culpando a la máquina de la persona por una variable
# que nosotros no resolvimos. Y como la ruta expandida cae DENTRO de nuestro árbol, el
# veredicto correcto cuando de verdad falta es `falla_de_aleph`, no `cli_no_instalado`.
_VAR_RE = re.compile(r"\$(\w+)|\$\{([^}]*)\}")


def _entorno_de_belts() -> dict:
    """Las mismas variables que el assembler define para un run real (mismo belts-root
    único: <root>/product/belts). Un entorno ya exportado gana: si alguien corre con su
    propio PUPPET_BELTS, el diagnóstico tiene que mirar ESE, no el que suponemos."""
    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
        root = _ap.resource_root().resolve()
    except Exception:
        root = _REPO
    # This map is also used as the verifier's MCP expansion source. Keep only
    # non-secret runtime coordinates; ambient provider credentials belong to
    # the per-user credential broker, never to the sidecar process.
    runtime_names = ("PUPPET_BELTS", "PUPPET_REPO", "PUPPET_WORKDIR",
                     "PUPPET_LANG", "PUPPET_PKG", "PUPPET_SHARED_MEMORY")
    env = {name: os.environ[name] for name in runtime_names if name in os.environ}
    env.setdefault("PUPPET_BELTS", str(root / "product" / "belts"))
    env.setdefault("PUPPET_REPO", str(root))
    # PUPPET_WORKDIR: sin un default, un belt que declara `${PUPPET_WORKDIR}/datos.db` hacía
    # que el server creara un directorio LLAMADO «${PUPPET_WORKDIR}» donde estuviera parado
    # el proceso (apareció uno dentro de product/backend/ midiendo esto). Una prueba no
    # escribe en el repo: se le da un workdir propio y descartable.
    if not env.get("PUPPET_WORKDIR"):
        d = Path(tempfile.gettempdir()) / "aleph-probe-workdir"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        env["PUPPET_WORKDIR"] = str(d)
    # PUPPET_LANG: MISMO motivo que PUPPET_WORKDIR, y faltaba. `assemble_and_run` la mete en
    # el child_env de todo run real (`recipe_assembler.py:2182`, default "es"), así que un
    # belt que declara `${PUPPET_LANG}` expande bien EN EL RUN pero recibía el literal
    # «${PUPPET_LANG}» en la PRUEBA — y este env es además el que mira `_pide_llave`, que
    # lee un `${VAR}` sin resolver como declaración de credencial: una perilla de idioma
    # pasaba a contarse como llave. Esta función promete «las mismas variables que el
    # assembler define para un run real»; ésta es una de ellas.
    env.setdefault("PUPPET_LANG", "es")
    return env


def _expandir(s: str, env: Optional[dict] = None) -> str:
    """`${VAR}`/`$VAR` → su valor. Una variable DESCONOCIDA queda literal (misma semántica
    que os.path.expandvars): inventarle un valor vacío convertiría `${X}/srv.py` en
    `/srv.py`, que es una ruta real de otra cosa — un diagnóstico peor que no diagnosticar."""
    env = env if env is not None else _entorno_de_belts()

    def _sub(m):
        nombre = m.group(1) or m.group(2) or ""
        return env.get(nombre, m.group(0))
    return _VAR_RE.sub(_sub, str(s or ""))


def _instalacion_de(cmd: str, exe: Path) -> dict:
    """[FIX-P11 · §5] CÓMO SE INSTALA ESTO — con las tres formas de acertarle al nombre.

    El caso índice de la caminata: el server de KiCad se declara como
        <mcp-install>/mcp-kicad-sch-api/.venv/bin/python
    Buscar esa cadena entera en `INSTALACION` no da nada, y `exe.name` es «python» —
    tampoco. Resultado: `como` y `url` en None, y el workflow terminaba en «no tengo la
    instrucción exacta», que es el consejo vacío. Pero el nombre del programa SÍ está: en
    el medio de la ruta (`mcp-kicad-sch-api`). Se busca, en orden:
      1. el comando tal cual  (`npx`, `docker`, `/usr/local/bin/docker`)
      2. el nombre del ejecutable  (`docker`, `python3`)
      3. cualquier SEGMENTO de la ruta que nombre un programa conocido (`…/mcp-kicad-…`)
    Y si nada de eso pega, se devuelve al menos el nombre del paquete —lo que la persona
    puede buscar— en vez de la ruta cruda."""
    inst = INSTALACION.get(cmd) or INSTALACION.get(exe.name)
    if inst:
        return dict(inst)
    partes = [s for s in re.split(r"[/\\]", str(cmd)) if s]
    # `<mcp-install>` no nombra la app de escritorio: nombra el root donde vive UN PAQUETE
    # MCP. Antes el fuzzy match veía «kicad» dentro de `mcp-kicad-sch-api` y ofrecía
    # reinstalar KiCad aunque KiCad.app ya estuviera presente. El paquete es lo que falta;
    # si el catálogo no declara cómo instalarlo, el remedio correcto es «no encontré».
    if "<mcp-install>" in partes:
        i = partes.index("<mcp-install>")
        paquete = partes[i + 1] if i + 1 < len(partes) else None
        if paquete:
            return {"programa": paquete, "paquete": paquete}
    for seg in reversed(partes):
        s = seg.lower()
        for clave, fila in INSTALACION.items():
            k = clave.lower()
            if k == s or (len(k) > 3 and k in s):
                return dict(fila)
    # sin fila conocida: el mejor nombre disponible es el del paquete/carpeta, no la ruta.
    paquete = None
    for seg in reversed(partes):
        if seg in (".venv", "bin", "python", "python3", "node", "lib"):
            continue
        paquete = seg
        break
    return {"programa": paquete or exe.name or cmd, "paquete": paquete}


def _nuestro(p: Path) -> bool:
    """¿Este archivo es DE ALEPH? (vive bajo el repo o bajo el bundle congelado). Si falta
    uno de estos, no hay nada que la persona pueda instalar: es NUESTRO build el que se
    olvidó de empaquetarlo. Caso índice: `assembler.py` fuera del .app."""
    try:
        raices = [_REPO.resolve()]
        try:
            if str(_PLATFORM) not in sys.path:
                sys.path.insert(0, str(_PLATFORM))
            import aleph_paths as _ap  # noqa: E402
            raices.append(_ap.resource_root().resolve())
        except Exception:
            pass
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            raices.append(Path(mei).resolve())
        p = p.resolve()
        return any(r == p or r in p.parents for r in raices)
    except Exception:
        return False


def dependencia_local(spec: dict) -> Optional[dict]:
    """(§6b) Chequeo de dependencia ANTES de spawnear. Devuelve None si todo está en su
    lugar, o el diagnóstico de qué falta:

      · binario ausente y NO es nuestro   → `cli_no_instalado` + cómo instalarlo ([Instalarlo])
      · archivo NUESTRO ausente           → `falla_de_aleph`  (§8: no se disfraza de proveedor)

    Es barato (dos stat) y corta el caso más frecuente sin pagar un spawn de 45 s que iba a
    terminar en «connection refused» → «sin internet», que era la cadena de mentiras."""
    env = _entorno_de_belts()
    cmd = _expandir((spec.get("command") or "").strip(), env)
    if not cmd:
        return None
    exe = Path(cmd)
    # 1 · ¿existe el ejecutable? (ruta absoluta → stat; nombre suelto → PATH)
    encontrado = str(exe) if exe.is_absolute() and exe.exists() else shutil.which(cmd)
    if not encontrado:
        if exe.is_absolute() and _nuestro(exe):
            return {"causa": FALLA_DE_ALEPH, "archivo": str(exe),
                    "detail": f"falta un archivo de Aleph: {exe.name}. Esto es un defecto "
                              f"nuestro, no de tu configuración."}
        inst = _instalacion_de(cmd, exe)
        prog = inst.get("programa") or exe.name or cmd
        # [FIX-P11 · §5 + §7·3] cuando el binario es una ruta LARGA (el venv de un MCP
        # externo), la ruta NO es el mensaje: el mensaje es qué programa falta. La ruta se
        # va a `buscado`, que el wizard pinta PLEGADO — arriba queda la causa en humano.
        return {"causa": CLI_NO_INSTALADO, "programa": prog, "binario": cmd,
                "buscado": cmd if cmd != prog else None,
                "como": inst.get("como"), "url": inst.get("url"),
                "paquete": inst.get("paquete"),
                "detail": f"{prog} no está instalado en esta máquina."}
    # 1-bis · [FIX-P11 · §5] EL BINARIO ESTÁ… ¿pero el servicio corre? Es el peldaño que
    #         faltaba entre «no está instalado» y «no arrancó»: Docker apagado.
    seg = _segundo_nivel(cmd, encontrado)
    if seg:
        return seg
    # 2 · si es un intérprete, el SCRIPT que va a correr también tiene que existir. Acá es
    #     donde se caza el caso índice: python3 <ruta-nuestra-que-el-bundle-no-empaquetó>.
    if Path(encontrado).name.split(".")[0].lower() in _INTERPRETES:
        for crudo in (spec.get("args") or []):
            a = _expandir(str(crudo), env)
            if a.startswith("-") or "/" not in a:
                continue
            objetivo = Path(a)
            if objetivo.exists():
                continue
            if _nuestro(objetivo):
                return {"causa": FALLA_DE_ALEPH, "archivo": str(objetivo),
                        "declarado": str(crudo),
                        "detail": f"falta un archivo de Aleph: {objetivo.name}. Esto es un "
                                  f"defecto nuestro, no de tu configuración."}
            return {"causa": CLI_NO_INSTALADO, "programa": objetivo.name, "binario": a,
                    "detail": f"no encontré «{objetivo.name}» en esta máquina."}
    return None


def _spec_de_belt(belt_ref: Optional[str], backed_by: Optional[str]) -> Optional[dict]:
    """Resuelve el belt portable y normaliza `backed_by` a un spec de probe."""
    if not belt_ref or not backed_by:
        return None
    try:
        import aleph_paths as _ap  # type: ignore
    except ImportError:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
    root = _ap.resource_root().resolve()
    if str(_ASM) not in sys.path:
        sys.path.insert(0, str(_ASM))
    from belt_resolver import (  # type: ignore
        BeltRefInvalid, BeltResolutionError, resolve_belt_ref,
    )
    try:
        p = resolve_belt_ref(belt_ref, root, portable_only=True).mcp_json_path
    except BeltRefInvalid:
        raise HTTPException(status_code=400, detail="belt_ref fuera de rango")
    except BeltResolutionError:
        raise HTTPException(status_code=404, detail=f"belt no encontrado: {belt_ref}")
    belt = json.loads(p.read_text(encoding="utf-8"))
    entry = (belt.get("mcpServers") or {}).get(backed_by)
    if not entry:
        raise HTTPException(status_code=404, detail=f"server {backed_by!r} no está en el belt")
    # conector declarado por la card que respalda este server (para resolver la BYOK).
    connector = None
    for c in (belt.get("_meta") or {}).get("cards") or []:
        if c.get("backed_by") == backed_by:
            connector = c.get("credential_provider") or c.get("connector"); break
    spec: dict = {"connector": connector}
    if entry.get("url"):
        spec.update(transport="http", url=entry["url"], headers=entry.get("headers") or {})
    else:
        spec.update(transport="stdio", command=entry.get("command"),
                    args=entry.get("args") or [], env=entry.get("env") or {})
    # Contrato aditivo del diagnosticador: la ingesta 5a podrá poblar estos campos en
    # origen; el motor sólo los consume. No se normaliza ni modifica la ingesta acá.
    for key in ("como", "url_instalacion", "package", "paquete", "fuente"):
        if entry.get(key) is not None:
            spec[key] = entry.get(key)
    if isinstance(entry.get("instalacion"), dict):
        spec["instalacion"] = dict(entry["instalacion"])
    if isinstance(entry.get("reparacion"), dict):
        spec["reparacion"] = dict(entry["reparacion"])
    # LA TOOL QUE PRUEBA LA CREDENCIAL (§ clase 2). La elige el CATÁLOGO, no el código:
    # tiene que ser de LECTURA, barata y determinista sin argumentos raros, y eso lo sabe
    # quien curó el conector. Sin este campo, el veredicto no puede ser verde — ver
    # `prueba_mcp`.
    if isinstance(entry.get("prueba_credencial"), dict):
        spec["prueba_credencial"] = dict(entry["prueba_credencial"])
    # LA SONDA DECLARADA (CLAUDE.md · «el guard no inventa; el catálogo declara»). Para
    # servidores sanos cuyas tools TODAS piden un argumento que no se puede adivinar.
    if entry.get("tool_sonda"):
        spec["tool_sonda"] = entry["tool_sonda"]
        if isinstance(entry.get("args_sonda"), dict):
            spec["args_sonda"] = dict(entry["args_sonda"])
    # ¿necesita auth? si la card tiene connector con auth != keyless, o el entry declara env/header.
    spec["needs_auth"] = bool(connector) and any(
        c.get("backed_by") == backed_by and c.get("auth", "keyless") != "keyless"
        for c in (belt.get("_meta") or {}).get("cards") or [])
    return spec


def _medir_precondicion(pre: dict) -> dict:
    """Mide una precondición declarativa sin ejecutar nada.

    Sólo hay dos sondas admitidas: existencia de una ruta y escucha TCP local. Una
    precondición humana puede delegar su verificación a una de ellas. La lista cerrada
    evita convertir datos de catálogo en una puerta para ejecutar comandos arbitrarios.
    """
    out = dict(pre)
    sonda = pre.get("verificacion") if pre.get("tipo") == "humana" else pre
    if not isinstance(sonda, dict):
        out.update(comprobada=False, cumplida=False,
                   evidencia="No hay una verificación declarada para este paso.")
        return out
    tipo = str(sonda.get("tipo") or "")
    if tipo == "ruta":
        cruda = str(sonda.get("ruta") or "")
        ruta = Path(_expandir(os.path.expanduser(cruda)))
        ok = bool(cruda) and ruta.exists()
        out.update(
            comprobada=True,
            cumplida=ok,
            evidencia=(f"Encontré {ruta}." if ok else f"No encontré {ruta}."),
        )
        return out
    if tipo == "tcp":
        import socket
        host = str(sonda.get("host") or "127.0.0.1")
        try:
            port = int(sonda.get("port"))
        except (TypeError, ValueError):
            out.update(comprobada=False, cumplida=False,
                       evidencia="La verificación TCP no declara un puerto válido.")
            return out
        # Esta sonda es local por contrato: no se acepta que un belt haga al diagnosticador
        # tocar hosts arbitrarios al abrir una card.
        if host not in {"127.0.0.1", "localhost", "::1"}:
            out.update(comprobada=False, cumplida=False,
                       evidencia="La verificación TCP sólo admite servicios locales.")
            return out
        try:
            with socket.create_connection((host, port), timeout=0.25):
                pass
            ok = True
        except OSError:
            ok = False
        out.update(
            comprobada=True,
            cumplida=ok,
            evidencia=(f"El servicio local responde en {host}:{port}."
                       if ok else f"El servicio local no responde en {host}:{port}."),
        )
        return out
    out.update(comprobada=False, cumplida=False,
               evidencia=f"No conozco la sonda «{tipo or 'sin tipo'}».")
    return out


def _precondiciones_de(spec: dict) -> list[dict]:
    reparacion = spec.get("reparacion") or {}
    # La mayoría de los servicios remotos no declara precondiciones locales. En JSON la
    # ausencia y un `null` explícito son equivalentes para este contrato: cero filas.
    # Iterar el None hacía que /v1/motor/receta devolviera 500 y el checklist de FRED
    # perdiera las recetas de sus dos procesos.
    filas = (reparacion.get("precondiciones") or []) if isinstance(reparacion, dict) else []
    return [_medir_precondicion(p) for p in filas if isinstance(p, dict)]


# ══════════════════════════════════════════════════════════════════════════════════
# PRUEBA 4 · API KEY  (validación mínima contra el proveedor) — EXTIENDE repo/byok
# ══════════════════════════════════════════════════════════════════════════════════
#: Validadores mínimos por proveedor. OpenAI-compat estándar = GET /models. Sólo los que
#: sé validar de verdad; para el resto → DETECTADO (existe, sin verificar): jamás verde
#: sin evidencia. Extensible: sumar un proveedor = una fila acá.
#
# ⚠️ [F9] `sonda` — CÓMO SE PRUEBA QUE LA LLAVE SIRVE PARA **GENERAR**, SIN GENERAR.
#
# Un `GET /models` que contesta 200 dice que la llave abre EL CATÁLOGO. Eso no es lo que el
# usuario va a hacer con ella. La sonda manda un `POST /chat/completions` con un parámetro
# deliberadamente inválido: si el proveedor contesta **400 por ese parámetro**, la credencial
# cruzó la puerta de auth de la ruta de GENERACIÓN y llegó a validar el cuerpo. Cero tokens.
#
# MEDIDO el 2026-08-07 contra los dos proveedores con llave, con la vara dura de F7 —no
# «con llave vs sin llave», que lo pasa cualquiera, sino **llave buena vs llave FALSA bien
# formada**:
#
#     proveedor    buena   falsa                    ninguna   latencia   tokens
#     groq          400    401 «Invalid API Key»      401      159 ms      0
#     openrouter    400    401 «User not found.»      401       52 ms      0
#
# Y es MÁS RÁPIDA que el camino que reemplaza (groq 340 ms · openrouter 186 ms de `/models`).
#
#   param            — qué parámetro se rompe. Su NOMBRE tiene que aparecer en el cuerpo del
#                      400, y eso es el guard: un 400 genérico no corona (ver `_sonda_generacion`).
#   confirma_modelo  — MEDIDO, no supuesto. Con parámetro basura Y modelo inexistente:
#                      openrouter contesta por el MODELO (lo valida primero) ⇒ la sonda
#                      confirma el id; groq contesta por el PARÁMETRO ⇒ NO lo confirma.
#                      Ausente = False: no se afirma lo que no se midió.
#
# Un proveedor SIN `sonda` declarada no se asume: cae al camino anterior. Declarar, no adivinar.
_KEY_VALIDATORS: dict[str, dict] = {
    "groq":       {"base": "https://api.groq.com/openai/v1", "header": "bearer",
                   "sonda": {"param": "temperature", "confirma_modelo": False}},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "header": "bearer",
                   "sonda": {"param": "temperature", "confirma_modelo": True}},
    "openai":     {"base": "https://api.openai.com/v1", "header": "bearer"},
    "deepseek":   {"base": "https://api.deepseek.com", "header": "bearer"},
    "mistral":    {"base": "https://api.mistral.ai/v1", "header": "bearer"},
    "together":   {"base": "https://api.together.xyz/v1", "header": "bearer"},
    "anthropic":  {"base": "https://api.anthropic.com/v1", "header": "x-api-key",
                   "extra": {"anthropic-version": "2023-06-01"}},
    # [F8 · obra 1] Google no manda la credencial por cabecera: va como `?key=` en la URL.
    # Es la tercera forma de `poner_credencial`, declarada acá como las otras dos.
    "gemini":     {"base": "https://generativelanguage.googleapis.com/v1beta",
                   "header": "query"},
}

#: El modelo con el que se hace la PRUEBA DURA de cada proveedor. **Una sola tabla en todo
#: el producto**: `centro_conexiones.MODELO_DEFECTO` es un alias de ésta. Dos tablas se
#: desincronizan, y entonces el checklist prueba un modelo y el motor otro.
MODELO_PRUEBA: dict[str, str] = {
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-4o",
    "anthropic": "claude-opus-4-8",
    "openrouter": "openai/gpt-4o",
    "deepseek": "deepseek-chat",
    "mistral": "mistral-small-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
}


# ══════════════════════════════════════════════════════════════════════════════════
# [F7 · obra 1a] EL VALIDADOR DISCRIMINANTE — una prueba que pasa sin credencial
#                NO ES UNA PRUEBA
# ══════════════════════════════════════════════════════════════════════════════════
# EL BUG MEDIDO (auditoría 2026-08-06, `~/Desktop/AUDITORIA-MODELOS.md` §1·A1):
# `GET https://openrouter.ai/api/v1/models` contesta **200 sin `Authorization`**. Como el
# veredicto salía de ese 200, CUALQUIER llave con forma `sk-or-…` —inventada— salía
# `probado` y se guardaba. La prueba medía «internet anda», no «tu llave anda».
#
# LA REGLA: antes de coronar verde con un validador, se comprueba que el validador
# DISCRIMINE — se lo corre **sin llave** y las dos respuestas tienen que diferir. Si no
# difieren, ese 200 no prueba nada sobre la credencial y hay que pagar la PRUEBA DURA:
# un POST de generación real, que ningún proveedor sirve sin autenticar.
#
# Y si la prueba dura no se puede correr (no hay modelo declarado, se cayó la red), el
# techo es 🟡 DETECTADO. Nunca verde: «no pude probarlo» y «anda» son cosas distintas.

#: ¿El GET /models de este proveedor distingue con-llave de sin-llave? Se mide UNA vez por
#: proceso y por base: no depende del usuario ni de su llave, sólo del proveedor. El TTL es
#: largo a propósito — que un proveedor abra o cierre su catálogo es noticia rara.
_DISCRIMINA: dict[str, dict] = {}
_DISCRIMINA_TTL = float(os.environ.get("PUPPET_DISCRIMINA_TTL", "3600"))
_DISCRIMINA_LOCK = threading.Lock()


def discriminante(base: str, *, header: str = "bearer",
                  extra_headers: Optional[dict] = None) -> dict:
    """¿`GET {base}/models` sirve para juzgar una credencial?

    Devuelve `{discrimina: bool, sin_llave: {...}, motivo: str}`. `discrimina=False`
    significa que el endpoint contesta lo mismo con y sin credencial: su 200 es
    información sobre el proveedor, no sobre la llave.

    Ante la duda —red caída, timeout— devuelve `discrimina=False`: fail-closed. Un
    validador que no se pudo auditar no corona verde.
    """
    base = (base or "").rstrip("/")
    if not base:
        return {"discrimina": False, "motivo": "sin dirección que auditar", "sin_llave": {}}
    with _DISCRIMINA_LOCK:
        cacheado = _DISCRIMINA.get(base)
        if cacheado and (time.time() - cacheado["ts"]) < _DISCRIMINA_TTL:
            return {k: v for k, v in cacheado.items() if k != "ts"}
    r = _ping_models(base, None, header=header, extra_headers=extra_headers)
    if r.get("ok"):
        out = {"discrimina": False, "sin_llave": {"http_status": 200},
               "motivo": f"{base}/models contesta 200 SIN credencial: su 200 no dice nada "
                         f"sobre tu llave"}
    elif r.get("err_kind") == "http":
        out = {"discrimina": True,
               "sin_llave": {"http_status": r.get("http_status")},
               "motivo": f"sin credencial contesta {r.get('http_status')}: el endpoint "
                         f"distingue"}
    else:
        # Red o tiempo: no se pudo auditar. NO se asume que discrimina.
        out = {"discrimina": False,
               "sin_llave": {"err_kind": r.get("err_kind")},
               "motivo": "no pude auditar el validador (no llegué al proveedor sin llave)"}
    with _DISCRIMINA_LOCK:
        _DISCRIMINA[base] = {**out, "ts": time.time()}
    return out


def _post_generacion(base: str, key: str, *, header: str = "bearer",
                     extra_headers: Optional[dict] = None, modelo: str,
                     timeout: float = _PING_TIMEOUT) -> dict:
    """LA PRUEBA DURA: `POST {base}/chat/completions` con `stream:true` y `max_tokens:1`.

    Es la misma que corre el paso `streaming` del checklist de Gate 1
    (`centro_conexiones._checklist_api`), y es la única que ningún proveedor sirve sin
    autenticar. Se lee sólo el primer pedazo: alcanza para saber que arrancó y no gasta
    presupuesto del usuario.
    """
    cuerpo = json.dumps({"model": modelo, "stream": True, "max_tokens": 1,
                         "messages": [{"role": "user", "content": "ping"}]}).encode()
    headers = {"User-Agent": "puppet-motor-verdad/1.0", "Content-Type": "application/json"}
    if header == "bearer":
        headers["Authorization"] = "Bearer " + key
    elif header == "x-api-key":
        headers["x-api-key"] = key
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=cuerpo,
                                 method="POST", headers=headers)
    t0 = time.perf_counter()
    try:
        with _urlopen_connector(req, timeout=timeout) as resp:
            chunk = resp.read(400).decode("utf-8", "replace")
        return {"ok": True, "http_status": resp.status if hasattr(resp, "status") else 200,
                "chunk": chunk, "latencia_ms": int((time.perf_counter() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "http_status": e.code, "err_kind": "http",
                "latencia_ms": dt, "snippet": detail or (e.reason or "")}
    except _url_guard.UrlBlocked as e:
        return {"ok": False, "http_status": None, "err_kind": "blocked",
                "latencia_ms": int((time.perf_counter() - t0) * 1000),
                "snippet": e.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        dt = int((time.perf_counter() - t0) * 1000)
        reason = getattr(e, "reason", None) or e
        return {"ok": False, "http_status": None,
                "err_kind": "timeout" if _looks_timeout(reason) else "net",
                "latencia_ms": dt, "snippet": str(reason)[:200]}


def _sonda_generacion(base: str, key: str, *, header: str, extra_headers: Optional[dict],
                      modelo: str, sonda: dict, timeout: float = _PING_TIMEOUT) -> dict:
    """[F9] ¿La llave sirve para GENERAR? — sin generar, sin gastar un token.

    Manda un `POST /chat/completions` con `{param}` deliberadamente inválido. Las tres
    respuestas posibles dicen cosas distintas y ninguna cuesta tokens:

      · **400 nombrando el parámetro roto** → la credencial cruzó la puerta de auth de la
        ruta de generación y llegó a validar el cuerpo. **Es el verde.**
      · **401 / 403**                        → la llave no sirve para generar (aunque abra
        el catálogo, que es exactamente el caso que esto viene a separar).
      · **cualquier otra cosa**              → no se sabe. No corona.

    ⚠️ EL GUARD DEL CUERPO, y es condición sellada: un 400 sólo cuenta si el cuerpo
    **nombra el parámetro que rompimos**. Un 400 genérico podría ser cualquier otra cosa —
    y de hecho uno de los 400 que medimos NO es nuestro parámetro: con un modelo inválido,
    OpenRouter contesta 400 «no-existe-9000 is not a valid model ID». Ese 400 no es un
    verde: es que el modelo elegido no sirve, y coronarlo sería el fallo mudo de siempre.

    ⚠️ EL `User-Agent` NO ES DECORACIÓN. Medido el 2026-08-07: sin él, groq contesta **403
    «error code: 1010»** — un bloqueo de Cloudflare por firma de cliente, que NO es un
    problema de credencial. Se manda el mismo que el resto del motor.
    """
    param = str(sonda.get("param") or "temperature")
    cuerpo = json.dumps({"model": modelo, param: "no-soy-un-numero",
                         "messages": [{"role": "user", "content": "x"}]}).encode()
    url, headers = poner_credencial(base.rstrip("/") + "/chat/completions", key,
                                    header=header, extra=extra_headers)
    headers.update({"Content-Type": "application/json",
                    "User-Agent": "puppet-motor-verdad/1.0"})
    req = urllib.request.Request(url, data=cuerpo, method="POST", headers=headers)
    t0 = time.perf_counter()
    try:
        with _urlopen_connector(req, timeout=timeout) as resp:
            # Un 2xx acá sería que el proveedor ACEPTÓ un parámetro basura: no prueba nada
            # sobre la puerta de auth, y encima puede haber generado. No corona.
            return {"veredicto": "inesperado", "http_status": getattr(resp, "status", 200),
                    "latencia_ms": int((time.perf_counter() - t0) * 1000),
                    "snippet": resp.read(200).decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:                          # noqa: BLE001
            body = ""
        if e.code in (401, 403):
            return {"veredicto": "rechazada", "http_status": e.code,
                    "latencia_ms": dt, "snippet": body}
        if e.code == 400 and param.lower() in body.lower():
            return {"veredicto": "auth_ok", "http_status": 400,
                    "latencia_ms": dt, "snippet": body}
        return {"veredicto": "ambiguo", "http_status": e.code,
                "latencia_ms": dt, "snippet": body}
    except _url_guard.UrlBlocked as e:
        return {"veredicto": "transporte", "http_status": None,
                "err_kind": "blocked",
                "latencia_ms": int((time.perf_counter() - t0) * 1000),
                "snippet": e.reason}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        dt = int((time.perf_counter() - t0) * 1000)
        reason = getattr(e, "reason", None) or e
        return {"veredicto": "transporte", "http_status": None,
                "err_kind": "timeout" if _looks_timeout(reason) else "net",
                "latencia_ms": dt, "snippet": str(reason)[:200]}


def veredicto_key(provider: str, secret: str, *, base: str, header: str = "bearer",
                  extra_headers: Optional[dict] = None,
                  modelo: Optional[str] = None) -> dict:
    """EL NÚCLEO de «¿esta llave sirve?». **Un solo lugar para los dos llamadores**:
    `prueba_key` (llave que ya está en el vault) y `centro_conexiones.agregar_key`
    (llave candidata, todavía sin guardar).

    Devuelve `{estado, causa, evidencia, http_status, latencia_ms}` — el contrato de
    siempre, con la evidencia AMPLIADA: `prueba` dice con qué se juzgó
    (`catalogo_autenticado` · `generacion` · `no_discriminante`) para que ninguna
    superficie tenga que adivinar de dónde salió el verde.
    """
    provider = (provider or "").strip().lower()
    base = (base or "").rstrip("/")
    modelo = modelo or MODELO_PRUEBA.get(provider) or ""

    r = _ping_models(base, secret, header=header, extra_headers=extra_headers)
    ev: dict = {"provider": provider, "http_status": r.get("http_status"),
                "latencia_ms": r.get("latencia_ms"), "validador": base + "/models"}

    # ── el proveedor rechazó: eso SÍ es información dura sobre la llave ──────────────
    if not r.get("ok"):
        ev["detail"] = r.get("snippet", "")
        kind = r.get("err_kind")
        if kind in ("net", "timeout"):
            return _resultado(KEY, provider, ROTO,
                              causa=_causa_de_transporte(kind, base, ev), evidencia=ev)
        if kind == "blocked":
            return _resultado(KEY, provider, ROTO, causa=ERROR_UPSTREAM, evidencia=ev)
        return _resultado(KEY, provider, ROTO,
                          causa=_causa_de_http(r.get("http_status"), r.get("snippet", ""),
                                               tenia_key=True), evidencia=ev)

    # ── contestó 200. ¿ESE 200 dice algo sobre la llave? ─────────────────────────────
    # ══ [F9] LA SONDA DE GENERACIÓN — REEMPLAZA a `catalogo_autenticado` ══════════════
    #
    # El catálogo baja a PRIMER PELDAÑO: dice que el proveedor existe y contesta. El verde
    # ya no sale de ahí, porque «tu llave abre el catálogo» no es lo que el usuario va a
    # hacer con ella — y para OpenRouter ese 200 ni siquiera pedía credencial (F7 · A).
    #
    # No es un complemento con trade-off: la sonda gana en las tres dimensiones. Prueba lo
    # correcto (la puerta de GENERACIÓN), discrimina contra llave falsa bien formada, cuesta
    # 0 tokens y es MÁS RÁPIDA que el `/models` que ya pagábamos.
    sonda = _KEY_VALIDATORS.get(provider, {}).get("sonda")
    if sonda and modelo:
        g = _sonda_generacion(base, secret, header=header, extra_headers=extra_headers,
                              modelo=modelo, sonda=sonda)
        ev["sonda"] = {k: g.get(k) for k in ("veredicto", "http_status", "latencia_ms")}
        ev["latencia_ms"] = g.get("latencia_ms")
        ev["modelo_sondeado"] = modelo
        # `confirma_modelo` es MEDIDO por proveedor: openrouter valida el modelo antes que
        # el parámetro (⇒ el 400 del parámetro prueba que el id existe), groq al revés.
        # Ausente = False: el verde no afirma sobre el modelo lo que no se midió.
        ev["confirma_modelo"] = bool(sonda.get("confirma_modelo"))
        if g["veredicto"] == "auth_ok":
            ev["prueba"] = "auth_generacion"
            ev["http_status"] = 400
            ev["detail"] = (
                f"{provider} aceptó tu llave en la ruta de generación: rechazó el pedido por "
                f"el parámetro, no por la credencial ({g.get('latencia_ms')} ms, sin gastar "
                f"tokens)." + (f" El modelo «{modelo}» también pasó."
                               if sonda.get("confirma_modelo") else ""))
            return _resultado(KEY, provider, PROBADO, evidencia=ev)
        if g["veredicto"] == "rechazada":
            ev["detail"] = g.get("snippet", "")
            return _resultado(KEY, provider, ROTO,
                              causa=_causa_de_http(g.get("http_status"), g.get("snippet", ""),
                                                   tenia_key=True), evidencia=ev)
        if g["veredicto"] == "transporte":
            ev["prueba"] = "sonda_no_corrio"
            ev["detail"] = (f"El catálogo contestó, pero la sonda de generación no llegó a "
                            f"correr ({g.get('err_kind')}): no puedo afirmar que tu llave "
                            f"sirva para generar.")
            return _resultado(KEY, provider, DETECTADO, evidencia=ev)
        # `ambiguo` / `inesperado`: hubo respuesta y NO se entiende. Jamás verde por defecto.
        ev["prueba"] = "sonda_ambigua"
        ev["detail"] = (f"La sonda de generación devolvió {g.get('http_status')} y no puedo "
                        f"leerlo como «la llave sirve»: {str(g.get('snippet', ''))[:160]}")
        return _resultado(KEY, provider, DETECTADO, evidencia=ev)

    audit = discriminante(base, header=header, extra_headers=extra_headers)
    ev["discriminante"] = audit["discrimina"]
    ev["auditoria_validador"] = audit["motivo"]
    if audit["discrimina"]:
        ev["prueba"] = "catalogo_autenticado"
        ev["detail"] = (f"{provider} aceptó tu llave: su catálogo pide credencial "
                        f"({audit['sin_llave'].get('http_status')} sin llave, 200 con la tuya)")
        return _resultado(KEY, provider, PROBADO, evidencia=ev)

    # ── NO discrimina → hay que pagar la prueba dura ────────────────────────────────
    if not modelo:
        ev["prueba"] = "no_discriminante"
        ev["detail"] = (f"{audit['motivo']}. Y no tengo un modelo declarado para "
                        f"{provider} con el que hacer la prueba dura: no puedo afirmar "
                        f"que tu llave sirva.")
        return _resultado(KEY, provider, DETECTADO, evidencia=ev)

    g = _post_generacion(base, secret, header=header, extra_headers=extra_headers,
                         modelo=modelo, timeout=_PING_TIMEOUT)
    ev["prueba"] = "generacion"
    ev["modelo_probado"] = modelo
    ev["http_status"] = g.get("http_status")
    ev["latencia_ms"] = g.get("latencia_ms")
    if g.get("ok"):
        ev["primer_chunk"] = (g.get("chunk") or "")[:120]
        ev["detail"] = (f"{provider} generó con tu llave ({modelo}, primer pedazo en "
                        f"{g.get('latencia_ms')} ms). Su catálogo es público, así que el "
                        f"verde sale de la generación, no del catálogo.")
        return _resultado(KEY, provider, PROBADO, evidencia=ev)

    ev["detail"] = g.get("snippet", "")
    kind = g.get("err_kind")
    if kind in ("net", "timeout"):
        # No se pudo probar. NO es rojo sobre la llave —no la rechazaron— y NO es verde.
        ev["prueba"] = "no_discriminante"
        ev["detail"] = (f"{audit['motivo']}. Y la prueba dura no llegó a correr "
                        f"({kind}): no puedo afirmar que tu llave sirva.")
        return _resultado(KEY, provider, DETECTADO, evidencia=ev)
    return _resultado(KEY, provider, ROTO,
                      causa=_causa_de_http(g.get("http_status"), g.get("snippet", ""),
                                           tenia_key=True), evidencia=ev)


# ══ [FIX-P11 · §1] LA SEGUNDA TABLA DE VALIDADORES — la que YA existía y nadie miraba ══
# EL BUG MEDIDO (caminata 2026-07-27, caso índice Zotero): probar Zotero devolvía
# `{"validador":"none","motivo":"workflow"}` y la UI decía «No pudo conectar». Mentira doble:
# no se probó nada, y Zotero SÍ es validable.
#
# La causa es que había DOS tablas de validadores que no se hablaban:
#   1. `catalog/connectors/onboarding/*.json` → cada conector declara su `validate`
#      ({path, method, soft, require…}). 20 de los 28 traen un endpoint REAL y funcionando;
#      es lo que corre el wizard de conexión (POST /v1/connectors/{n}/connect).
#   2. `_KEY_VALIDATORS` (acá arriba) → SIETE proveedores de LLM, y nada más.
# `prueba_key` sólo miraba la 2. Entonces github, notion, zotero, huggingface, asana, osf,
# hubspot, onshape, zenodo, canvas, linear, fred, moodle, openbom, alphavantage, jupyter,
# exa, coingecko, context7 y massive —TODOS con validador declarado— caían en «sin validador»
# y de ahí a «No pudo conectar».
#
# Esto no agrega una tabla nueva: LEE la que ya es fuente de verdad del catálogo. Sumar un
# conector sigue siendo un JSON, y ahora ese JSON sirve a las dos superficies.
_CATALOGO_CACHE: dict[str, Optional[dict]] = {}


def _onboarding_dir() -> Optional[Path]:
    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
        d = _ap.resource_root() / "catalog" / "connectors" / "onboarding"
        return d if d.is_dir() else None
    except Exception:
        d = _REPO / "catalog" / "connectors" / "onboarding"
        return d if d.is_dir() else None


def conector_del_catalogo(nombre: str) -> Optional[dict]:
    """El objeto de onboarding de un conector, o None. Cacheado por proceso (es un JSON
    del bundle: no cambia en caliente). Nombre saneado — jamás un path traversal."""
    n = re.sub(r"[^a-z0-9_.-]", "", (nombre or "").strip().lower())
    if not n or n.startswith(".") or "/" in n:
        return None
    if n in _CATALOGO_CACHE:
        return _CATALOGO_CACHE[n]
    obj = None
    d = _onboarding_dir()
    if d:
        p = d / f"{n}.json"
        try:
            if p.is_file() and p.resolve().parent == d.resolve():
                obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            obj = None
    _CATALOGO_CACHE[n] = obj
    return obj


def validador_de(provider: str) -> dict:
    """CENSO, en una función: ¿qué sé hacer para probar la credencial de `provider`?

        {"clase": "directo"|"catalogo"|"oauth"|"keyless"|"ninguno",
         "fuente": …, "detalle": …}

    `directo`   → `_KEY_VALIDATORS` (los proveedores de cognición: GET /models).
    `catalogo`  → el conector declara `validate.path` → prueba REAL contra su endpoint.
    `oauth`     → la cuenta se prueba autorizándola; la credencial no es una llave pegable.
    `keyless`   → no hay credencial que validar (el servicio es abierto).
    `ninguno`   → no tengo forma directa. Se dice, y se ofrece la prueba del MCP.
    Público a propósito: la vara del censo lo imprime sin duplicar la lógica."""
    p = (provider or "").strip().lower()
    if p in _KEY_VALIDATORS:
        return {"clase": "directo", "fuente": "_KEY_VALIDATORS",
                "detalle": _KEY_VALIDATORS[p]["base"]}
    obj = conector_del_catalogo(p)
    if obj:
        am = str(obj.get("auth_method") or "").lower()
        if am == "keyless":
            return {"clase": "keyless", "fuente": f"catalog/{p}.json", "detalle": "sin credencial"}
        if am in ("oauth", "admin_oauth"):
            return {"clase": "oauth", "fuente": f"catalog/{p}.json",
                    "detalle": obj.get("provider") or p}
        ruta = str((obj.get("validate") or {}).get("path") or "").strip()
        if ruta:
            return {"clase": "catalogo", "fuente": f"catalog/{p}.json",
                    "detalle": (obj.get("api_base") or "").rstrip("/") + ruta,
                    "soft": bool((obj.get("validate") or {}).get("soft"))}
        return {"clase": "ninguno", "fuente": f"catalog/{p}.json",
                "detalle": "el conector no declara validate.path"}
    return {"clase": "ninguno", "fuente": None, "detalle": "no está en el catálogo"}


def _prueba_key_por_catalogo(provider: str, secret: str, obj: dict) -> dict:
    """Corre el MISMO `connect_engine` que el wizard, con la llave YA guardada. Una sola
    implementación del validador por conector: si el wizard la acepta, el semáforo la pinta
    verde, y al revés. Dos validadores para la misma llave serían dos verdades."""
    campos = [f.get("id") for f in (obj.get("credential_fields") or []) if f.get("id")]
    creds = {(campos[0] if campos else "key"): secret}
    try:
        if str(_PLATFORM) not in sys.path:
            sys.path.insert(0, str(_PLATFORM))
        import aleph_paths as _ap  # noqa: E402
        eng = _ap.load_module_by_path(
            "puppet_connect_engine",
            _ap.resource_root() / "platform" / "connectors" / "connect_engine.py")
    except Exception as e:
        # El motor de conexión es NUESTRO: si no carga, es un defecto de empaquetado (§8),
        # jamás «tu llave no sirve».
        return _resultado(KEY, provider, ROTO, causa=FALLA_DE_ALEPH,
                          evidencia={"detail": f"no pude cargar el motor de conexión: {e}",
                                     "modulo": "connectors.connect_engine"})
    t0 = time.perf_counter()
    try:
        r = eng.connect(obj, creds, api_base=obj.get("api_base") or "")
    except Exception as e:
        return _resultado(KEY, provider, ROTO, causa=ERROR_UPSTREAM,
                          evidencia={"detail": str(e)[:300], "provider": provider,
                                     "validador": "catalogo"})
    dt = int((time.perf_counter() - t0) * 1000)
    estado_conn = str(r.get("state") or "")
    ev = {"provider": provider, "latencia_ms": dt, "validador": "catalogo",
          "endpoint": (obj.get("api_base") or "").rstrip("/")
                      + str((obj.get("validate") or {}).get("path") or ""),
          "detail": r.get("message") or ""}
    if r.get("identity"):
        ev["identidad"] = r["identity"]
    if estado_conn in ("connected", "connected_empty"):
        return _resultado(KEY, provider, PROBADO, evidencia=ev)
    if estado_conn == "invalid":
        return _resultado(KEY, provider, ROTO, causa=KEY_INVALIDA, evidencia=ev)
    if estado_conn == "network":
        return _resultado(KEY, provider, ROTO,
                          causa=_causa_de_transporte("net", ev["endpoint"], ev), evidencia=ev)
    # connected_unverified / oauth_pending / gate → la llave está y NO fue refutada. Es
    # DETECTADO por definición del contrato (§1): existe, sin verde falso.
    ev["validador"] = "catalogo_blando"
    return _resultado(KEY, provider, DETECTADO, evidencia=ev)


def _prueba_oauth_por_catalogo(provider: str, token: str, obj: dict) -> dict:
    """Valida un bearer OAuth con el endpoint de lectura declarado por el catálogo."""
    endpoint = ((obj.get("api_base") or "").rstrip("/")
                + str((obj.get("validate") or {}).get("path") or ""))
    req = urllib.request.Request(
        endpoint, method=str((obj.get("validate") or {}).get("method") or "GET"),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json",
                 "User-Agent": "aleph-oauth-diagnostic/1"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=_PING_TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
        ev = {"http_status": response.status,
              "latencia_ms": int((time.perf_counter() - t0) * 1000),
              "provider": provider, "endpoint": endpoint, "auth": "oauth"}
        identity_field = str((obj.get("validate") or {}).get("identity_field") or "")
        if identity_field and isinstance(body, dict) and body.get(identity_field):
            ev["identidad"] = body[identity_field]
        return _resultado(KEY, provider, PROBADO, evidencia=ev)
    except urllib.error.HTTPError as exc:
        ev = {"http_status": exc.code,
              "latencia_ms": int((time.perf_counter() - t0) * 1000),
              "provider": provider, "endpoint": endpoint, "auth": "oauth"}
        # OAuth nunca se etiqueta "llave mala": la reparación es reconectar el grant.
        cause = OAUTH_REVOCADO if exc.code in (401, 403) else _causa_de_http(exc.code)
        return _resultado(KEY, provider, ROTO, causa=cause, evidencia=ev)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        ev = {"http_status": None,
              "latencia_ms": int((time.perf_counter() - t0) * 1000),
              "provider": provider, "endpoint": endpoint, "auth": "oauth"}
        kind = "timeout" if _looks_timeout(getattr(exc, "reason", exc)) else "net"
        return _resultado(KEY, provider, ROTO,
                          causa=_causa_de_transporte(kind, endpoint, ev), evidencia=ev)


def prueba_key(provider: str, *, owner: Optional[str],
               get_conn: Optional[Callable[[], Any]] = None,
               _validator_base_override: Optional[str] = None) -> dict:
    """Descifra la BYOK del user (repo.get_key, SQLite del cliente) y la valida mínimamente
    contra el proveedor. Sin key → NO_CONFIGURADO. Con key + validador conocido → prueba real
    → PROBADO / ROTO(causa). Con key + sin validador → DETECTADO (te manda a probar el MCP)."""
    provider = (provider or "").strip()
    if not provider:
        return _resultado(KEY, provider, NO_CONFIGURADO, evidencia={"detail": "falta el provider"})
    if not owner:
        return _resultado(KEY, provider, NO_CONFIGURADO,
                          evidencia={"detail": "no hay sesión para leer tus credenciales"})
    if get_conn is None:
        return _resultado(KEY, provider, ROTO, causa=ERROR_UPSTREAM,
                          evidencia={"detail": "sin acceso al almacén de credenciales"})
    cat = conector_del_catalogo(provider)
    oauth_meta: dict = {}
    try:
        from app.phase1 import repo
        conn = get_conn()
        try:
            secret = repo.get_key(conn, owner, provider)
            if cat and str(cat.get("auth_method") or "").lower() in ("oauth", "admin_oauth"):
                # Mismo knob que el runtime: un token vencido dispara refresh antes de
                # validar. invalid_grant marca el companion como oauth_revoked.
                if secret:
                    try:
                        from app.phase1 import credential_broker
                        secret = credential_broker._maybe_refresh_oauth(
                            conn, owner, provider, secret)
                    except Exception:
                        pass
                try:
                    oauth_meta = json.loads(
                        repo.get_key(conn, owner, f"{provider}__oauth") or "{}")
                except (TypeError, json.JSONDecodeError):
                    oauth_meta = {}
        finally:
            conn.close()
    except Exception as e:
        return _resultado(KEY, provider, ROTO, causa=ERROR_UPSTREAM,
                          evidencia={"detail": f"no pude leer la credencial: {e}"})
    if oauth_meta.get("state") == "oauth_revoked":
        # El nombre sale del provider, JAMÁS hardcodeado: esto es el motor de todos los
        # conectores OAuth y el que redacta el mensaje de usuario es el diagnosticador,
        # que lo arma con `evidencia["provider"]`.
        _nombre = str((cat.get("provider") or cat.get("display_name") or provider)
                      if cat else provider)
        return _resultado(
            KEY, provider, ROTO, causa=OAUTH_REVOCADO,
            evidencia={"provider": provider, "auth": "oauth",
                       "detail": f"Revocaste el acceso desde {_nombre}."},
        )
    if not secret:
        return _resultado(KEY, provider, NO_CONFIGURADO,
                          evidencia={"detail": f"conecta tu credencial de {provider}"})
    if cat and str(cat.get("auth_method") or "").lower() in ("oauth", "admin_oauth"):
        return _prueba_oauth_por_catalogo(provider, secret, cat)

    v = None
    if _validator_base_override:
        v = {"base": _validator_base_override, "header": "bearer"}
    else:
        v = _KEY_VALIDATORS.get(provider.lower())
    if not v:
        # [FIX-P11 · §1] ANTES de rendirse: el CATÁLOGO. 20 de los 28 conectores declaran un
        # endpoint de validación real que este camino no miraba (ver `validador_de`).
        if cat and str((cat.get("validate") or {}).get("path") or "").strip():
            return _prueba_key_por_catalogo(provider, secret, cat)
        # Sin validador de verdad: se dice ASÍ. La regla nueva de §1 —«jamás "no pudo
        # conectar" cuando no se probó»— vive en estos tres campos, que la UI lee sin tener
        # que interpretar prosa:
        #   validador:"none"  → no corrió ninguna prueba
        #   probable_por      → cómo SÍ se puede verificar (el MCP, de punta a punta)
        #   detail            → la frase honesta, ya escrita, para pintar tal cual
        info = validador_de(provider)
        if info["clase"] == "keyless":
            detalle = (f"{provider} no pide credencial: no hay llave que validar. "
                       "Se prueba usándolo.")
        elif info["clase"] == "oauth":
            detalle = (f"{provider} se conecta autorizando tu cuenta, no pegando una llave — "
                       "la prueba es la autorización misma.")
        else:
            detalle = (f"No tengo forma directa de probar {provider} — "
                       "lo verifico con el MCP de punta a punta.")
        return _resultado(KEY, provider, DETECTADO,
                          evidencia={"detail": detalle, "validador": "none",
                                     "validador_clase": info["clase"],
                                     "probable_por": "mcp", "provider": provider})
    # [F7 · obra 1a] EL VEREDICTO SALE DE `veredicto_key`, no de un 200 pelado. Un
    # `GET /models` que contesta lo mismo con y sin credencial no puede coronar verde:
    # ahí se paga la prueba dura (POST de generación). Acá SIEMPRE hubo llave (se leyó del
    # vault más arriba), así que un 401 es `key_invalida`, no `falta_key` — la distinción
    # es el botón: [Cambiar la llave], no [Poner la llave]. Eso lo decide `_causa_de_http`
    # adentro del núcleo, con `tenia_key=True`.
    # ⚠️ [F9] LA SONDA USA EL MODELO ELEGIDO POR EL USUARIO, no uno fijo. `MODELO_PRUEBA`
    # baja a SEMILLA —el mismo movimiento que F8 le hizo a `_PICKER_HOSTEADO`—: se usa
    # cuando todavía no hay elección, no como decreto. Probar con un modelo que el usuario
    # no eligió certifica una ruta que no es la suya.
    #
    # Import LAZY: el dueño del archivo de preferencias es `centro_modelos`, y el motor no
    # depende de él. Blando a propósito — sin elección, la semilla; el veredicto no se cae
    # porque falte una preferencia.
    _elegido = None
    try:
        from app.phase1 import centro_modelos as _CM
        _elegido = _CM.modelo_elegido_de(f"api.{provider}", owner=owner)
    except Exception:                              # noqa: BLE001 — sin preferencia, semilla
        _elegido = None
    res = veredicto_key(provider, secret, base=v["base"],
                        header=v.get("header", "bearer"), extra_headers=v.get("extra"),
                        modelo=_elegido or None)
    if res["estado"] == ROTO and res.get("causa") not in (SIN_RED, TIMEOUT):
        try:
            from app.phase1 import byok
            res["evidencia"]["motivo"] = str(byok.classify_provider_error(
                f"{res['evidencia'].get('http_status')} "
                f"{res['evidencia'].get('detail', '')}"))
        except Exception:
            pass
    return res


# ══════════════════════════════════════════════════════════════════════════════════
# DISPATCHER + cache + "se prueba solo"
# ══════════════════════════════════════════════════════════════════════════════════
def probar(tipo: str, ref: str, *, owner: Optional[str] = None, force: bool = False,
           motivo: Optional[str] = None, get_conn: Optional[Callable[[], Any]] = None,
           **kw) -> dict:
    """Prueba UNA cosa por tipo. Cachea con TTL corto; `force` re-prueba siempre. `motivo`
    ('conexion'|'manual'|…) queda en la evidencia para telemetría/diagnóstico."""
    if tipo not in TIPOS:
        raise HTTPException(status_code=422, detail=f"tipo inválido: {tipo!r} (esperaba {sorted(TIPOS)})")
    k = _cache_key(tipo, ref, owner)
    h = huella_de(tipo, ref, **kw)
    if not force:
        hit = _cache_get(k, TTL, h)
        if hit is not None:
            return {**hit, "cacheado": True}

    if tipo == CLI:
        res = prueba_cli(ref)
    elif tipo == CEREBRO:
        # owner/get_conn viajan para que el peldaño (a) pueda mirar el VAULT del usuario y
        # no sólo el entorno del proceso — su BYOK es una llave tan real como la de infra.
        res = prueba_cerebro(ref, cli_model=kw.get("cli_model"), owner=owner, get_conn=get_conn)
    elif tipo == MCP:
        res = prueba_mcp(spec=kw.get("spec"), belt_ref=kw.get("belt_ref") or ref,
                         backed_by=kw.get("backed_by"), secret=kw.get("secret"),
                         owner=owner, get_conn=get_conn)
    elif tipo == KEY:
        # [F9] `base_url` VIAJA. El checklist puede estar probando contra una dirección
        # propia del usuario (o contra un peer, en las varas): si `probar` fuera siempre al
        # endpoint declarado, verificaría una cosa y el resto del checklist otra — y en las
        # varas mandaría tráfico al proveedor real con una llave de mentira.
        res = prueba_key(ref, owner=owner, get_conn=get_conn,
                         _validator_base_override=kw.get("base_url"))
    else:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"tipo no soportado: {tipo!r}")

    if motivo:
        res["evidencia"] = {**res.get("evidencia", {}), "motivo": motivo}
        # `motivo` también es evidencia: el veredicto persistido debe contener exactamente
        # lo mismo que los campos legacy, no una foto anterior a la mutación.
        res = DC.aplicar(
            res,
            destino=(res.get("evidencia") or {}).get("destino") or ref,
            camino=(res.get("veredicto") or {}).get("camino"),
        )
    # [FIX-P11 · §3] `probado_ts` = cuándo CORRIÓ una prueba de verdad. `ts` puede refrescarse;
    # esto no. Es lo que la UI muestra como «probado a las 13:41» sin poder inventarlo.
    res["probado_ts"] = res.get("ts")
    _cache_put(k, res, h)
    return {**res, "cacheado": False}


def al_conectar(tipo: str, ref: str, *, owner: Optional[str] = None,
                get_conn: Optional[Callable[[], Any]] = None, **kw) -> dict:
    """`Al conectar algo, se prueba solo` (§2). Fuerza una prueba fresca y la cachea. Best-
    effort por diseño: lo llama el seam del connect — jamás debe romper el connect si falla."""
    return probar(tipo, ref, owner=owner, force=True, motivo="conexion",
                  get_conn=get_conn, **kw)


def estado(tipo: str, ref: str, *, owner: Optional[str] = None, **kw) -> dict:
    """Lectura NO bloqueante para el semáforo: devuelve lo RECORDADO (sin importar su edad,
    que se muestra) o DETECTADO ('sin probar aún' → [Probar ahora]). Nunca verde sin evidencia.

    [FIX-P11 · §3] Antes esto pasaba `TTL`: a los 30 s de haber probado, la misma pieza
    volvía a 🟡 «sin probar» — la amnesia que la caminata reportó. Ahora la lectura no
    caduca por reloj (`ttl=None`); caduca por CAUSA (huella distinta) o porque una prueba
    nueva la pisó. `fresco` sigue diciendo si el dato es más joven que el TTL, para quien
    quiera re-probar solo."""
    if tipo not in TIPOS:
        raise HTTPException(status_code=422, detail=f"tipo inválido: {tipo!r}")
    hit = _cache_get(_cache_key(tipo, ref, owner), None, huella_de(tipo, ref, **kw))
    if hit is not None:
        edad = time.time() - float(hit.get("ts") or 0)
        return {**hit, "cacheado": True, "fresco": edad < TTL, "edad_s": int(max(0, edad))}
    return {**_resultado(tipo, ref, DETECTADO,
                         evidencia={"detail": "sin probar aún — toca [Probar ahora]",
                                    "nunca_probado": True}),
            "cacheado": False, "fresco": False}


# ── owner desde la sesión (anti-IDOR: la key de A jamás se prueba con la sesión de B) ──
def _owner_from_session(authorization: Optional[str]) -> Optional[str]:
    tok = (authorization or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    if not tok:
        return None
    try:
        from app.phase1 import repo
        return repo.session_owner(tok)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════════
def build_motor_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/motor", tags=["motor-verdad"])

    @router.post("/probar")
    def http_probar(body: dict = Body(...), authorization: Optional[str] = Header(default=None)):
        """Prueba UNA cosa AHORA (fuerza salvo que force=false). Body:
          {tipo, ref, force?, motivo?, cli_model?, belt_ref?, backed_by?, spec?}
        El owner (para key/mcp) SIEMPRE sale de la sesión (anti-IDOR), nunca del body."""
        tipo = (body.get("tipo") or "").strip()
        ref = str(body.get("ref") or body.get("belt_ref") or "")
        owner = _owner_from_session(authorization)
        force = bool(body.get("force", True))  # POST /probar = acción explícita → fresco por default
        return probar(tipo, ref, owner=owner, force=force, motivo=body.get("motivo") or "manual",
                      get_conn=get_conn, cli_model=body.get("cli_model"),
                      belt_ref=body.get("belt_ref"), backed_by=body.get("backed_by"),
                      spec=body.get("spec"))

    @router.get("/estado")
    def http_estado(tipo: str = Query(...), ref: str = Query(...),
                    belt_ref: Optional[str] = Query(default=None),
                    backed_by: Optional[str] = Query(default=None),
                    cli_model: Optional[str] = Query(default=None),
                    authorization: Optional[str] = Header(default=None)):
        """Lectura barata del semáforo (recordado o DETECTADO). No dispara pruebas caras.
        [FIX-P11 · §3] `belt_ref`/`backed_by`/`cli_model` viajan para que la HUELLA calculada
        acá sea la MISMA que la del POST /probar — con huellas distintas, lo probado nunca se
        volvería a encontrar y el estado parecería no haberse guardado nunca."""
        owner = _owner_from_session(authorization)
        return estado(tipo, ref, owner=owner, belt_ref=belt_ref,
                      backed_by=backed_by, cli_model=cli_model)

    # ── [FIX-P11 · §1] EL CENSO, expuesto ───────────────────────────────────────────
    @router.get("/validadores")
    def http_validadores():
        """Qué sé probar y qué no, por servicio. Es la tabla que la UI necesita para NO
        decir «no pudo conectar» sobre algo que nunca probó, y la que la vara imprime."""
        filas = []
        vistos = set()
        for p in sorted(_KEY_VALIDATORS):
            filas.append({"servicio": p, **validador_de(p)})
            vistos.add(p)
        d = _onboarding_dir()
        if d:
            for f in sorted(d.glob("*.json")):
                if f.stem in vistos:
                    continue
                filas.append({"servicio": f.stem, **validador_de(f.stem)})
        resumen: dict[str, int] = {}
        for fila in filas:
            resumen[fila["clase"]] = resumen.get(fila["clase"], 0) + 1
        return {"total": len(filas), "resumen": resumen, "validadores": filas}

    # ── (§9) EL ENDPOINT QUE P1A DEJÓ DECLARADO ─────────────────────────────────────
    @router.get("/receta")
    def http_receta(belt_ref: str = Query(...), backed_by: str = Query(...)):
        """GET /v1/motor/receta?belt_ref=…&backed_by=… → el comando REAL del server MCP.

        `manoDe()` en el front tenía este agujero escrito en un comentario: «no inventa el
        comando del server —el cliente no lo tiene, y no hay endpoint que lo entregue—».
        Este es ese endpoint. Con él, [Probar el server a mano] deja de ser «el curl de MI
        endpoint» y pasa a ser el comando exacto que la persona puede correr en su terminal
        para ver el server fallar con sus propios ojos.

        FRONTERA DE SECRETOS — el belt puede tener llaves literales en `env`/`headers`. Acá
        viajan sólo los NOMBRES, más si están o no seteados. Un endpoint de diagnóstico que
        filtra credenciales es un endpoint de exfiltración con buenos modales."""
        spec = _spec_de_belt(belt_ref, backed_by)   # anti-traversal: el mismo guard del probe
        if not spec:
            raise HTTPException(status_code=404,
                                detail={"error": "sin_receta",
                                        "detail": f"no encontré {backed_by!r} en {belt_ref}"})
        transport = (spec.get("transport") or ("http" if spec.get("url") else "stdio")).lower()
        env = dict(spec.get("env") or {})
        headers = dict(spec.get("headers") or {})
        out: dict = {
            "belt_ref": belt_ref, "backed_by": backed_by, "transport": transport,
            "connector": spec.get("connector"), "needs_auth": bool(spec.get("needs_auth")),
            # NOMBRES, jamás valores.
            "env_names": sorted(env.keys()),
            "env_seteadas": sorted([k for k, v in env.items() if str(v or "").strip()]),
            "header_names": sorted(headers.keys()),
        }
        # Las precondiciones se miden al abrir la card. No se propone instalar/activar algo
        # por intuición: cada fila llega con `comprobada`, `cumplida` y evidencia.
        out["precondiciones"] = _precondiciones_de(spec)
        if transport == "http":
            out["url"] = spec.get("url")
            cabeceras = " ".join(f"-H '{k}: ***'" for k in sorted(headers))
            out["shell"] = (f"curl -sS -X POST {spec.get('url')} {cabeceras} "
                            "-H 'content-type: application/json' "
                            "-d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'").strip()
        else:
            cmd = spec.get("command") or ""
            args = [str(a) for a in (spec.get("args") or [])]
            out["command"] = cmd
            out["args"] = args
            # `shell` va EXPANDIDO: el punto de este endpoint es que la persona pueda pegar
            # el comando en su terminal y verlo fallar. Un `${PUPPET_BELTS}` sin resolver no
            # corre en ninguna shell — sería entregar un comando que no es el comando.
            entorno = _entorno_de_belts()
            prefijo = " ".join(f"{k}=***" for k in sorted(out["env_seteadas"]))
            partes = [p for p in ([prefijo] if prefijo else [])
                      + [_expandir(cmd, entorno)] + [_expandir(a, entorno) for a in args] if p]
            out["shell"] = " ".join(partes)
            out["shell_declarado"] = " ".join([p for p in [cmd] + args if p])
            # El diagnóstico §6b va PEGADO a la receta: si falta el programa, la persona ve
            # por qué el comando no le va a andar antes de pegarlo en su terminal.
            out["dependencia"] = dependencia_local(spec)
            dep = out["dependencia"]
            if dep and dep.get("causa") == CLI_NO_INSTALADO:
                from app.phase1 import remedios_conectores as _rem
                catalog_id = f"{belt_ref}#{backed_by}"
                remedio = _rem.resolver(
                    spec, catalog_id=catalog_id, fuente=spec.get("fuente"),
                    # Abrir una card no gasta cerebro. Si la derivación no alcanza, queda
                    # [Buscar de nuevo], que sí dispara el peldaño IA de forma explícita.
                    buscar_ia=False,
                )
                out["remedio"] = remedio
                out["dependencia"] = {**dep, "remedio": remedio}
        # Dónde vive el belt (para que [Abrir el belt] tenga qué abrir «en su lugar»).
        out["belt_path"] = belt_ref
        return out

    # ── [FIX-P11 · §5] [INSTALARLO] QUE INSTALA DE VERDAD ───────────────────────────
    @router.post("/instalar")
    def http_instalar(body: dict = Body(...)):
        """Corre el comando de instalación/arranque de UN programa conocido.

        EL GATE, y por qué es éste: instalar software es alta consecuencia, así que la
        pregunta no es «¿confío en quien aprieta?» sino «¿qué puede llegar a correrse?».
        La respuesta acá es una LISTA CERRADA: el servidor ignora por completo el texto que
        manda el cliente y corre EXCLUSIVAMENTE el comando que la tabla `INSTALACION` /
        `_SEGUNDO_NIVEL` tiene escrito para ese programa. Un cliente comprometido no puede
        pedir `rm -rf`: no hay forma de expresarlo — no hay campo que lo transporte.
        Y por eso mismo se corre SIN shell (lista de argumentos), que cierra la inyección
        por metacaracteres aunque alguien meta una fila con `;` en la tabla.

        El OK humano es el tap: la UI muestra el comando EXACTO antes de ofrecer el botón
        (§5 «lo da y lo ejecuta»), así nadie instala nada que no haya leído."""
        prog = str(body.get("programa") or "").strip()
        remedio_id = str(body.get("remedio_id") or "").strip()
        accion = str(body.get("accion") or "instalar").strip().lower()
        if not prog and not remedio_id:
            raise HTTPException(status_code=422, detail={"error": "falta_programa"})
        # ── EL OK EXPLÍCITO ────────────────────────────────────────────────────────────
        # Medido mientras probaba este endpoint: un POST con sólo `{"programa":"Node.js"}`
        # CORRIÓ `brew install node` en la máquina (sin daño —ya estaba— pero podía no
        # estarlo). La lista cerrada impide correr comandos ARBITRARIOS; no impedía correr
        # los nuestros por accidente. Instalar software es alta consecuencia: exige el OK,
        # y el OK tiene que ser un acto separado de nombrar el programa. La UI lo manda
        # después de mostrar el comando exacto — que es lo que hace al consentimiento
        # informado. Un cliente que no leyó el comando no puede haber puesto este campo.
        if body.get("confirmado") is not True:
            raise HTTPException(status_code=428, detail={
                "error": "falta_confirmacion",
                "detail": "Muéstrale el comando exacto a la persona y reenvía con "
                          "confirmado:true. No instalo nada sin OK."})
        # Resolución del comando: SIEMPRE de nuestras tablas, jamás del body.
        comando: Optional[str] = None
        if remedio_id:
            from app.phase1 import remedios_conectores as _rem
            remedio = _rem.obtener(remedio_id)
            if not remedio or not remedio.get("ejecutable") or not remedio.get("como"):
                raise HTTPException(status_code=404, detail={
                    "error": "remedio_no_encontrado",
                    "detail": "La propuesta ya no está disponible. Búscala de nuevo antes "
                              "de instalar.",
                })
            comando = str(remedio["como"])
            prog = prog or str(remedio.get("paquete") or remedio.get("catalog_id") or "el programa")
        for clave, fila in INSTALACION.items():
            if comando is None and (
                clave.lower() == prog.lower()
                or str(fila.get("programa", "")).lower() == prog.lower()
            ):
                comando = fila.get("como")
                break
        if accion == "arrancar":
            for _, fila in _SEGUNDO_NIVEL.items():
                if str(fila.get("programa", "")).lower() == prog.lower():
                    comando = fila.get("como_arrancar")
                    break
        if not comando:
            raise HTTPException(status_code=404, detail={
                "error": "sin_comando",
                "detail": f"No tengo un comando de instalación para «{prog}» en esta máquina."})
        import shlex
        import subprocess
        argv = shlex.split(comando)
        if not argv or not shutil.which(argv[0]):
            raise HTTPException(status_code=409, detail={
                "error": "sin_gestor", "comando": comando,
                "detail": f"«{argv[0] if argv else '?'}» no está en esta máquina, así que no "
                          f"puedo correr el comando por ti. Cópialo y ejecútalo en tu terminal."})
        t0 = time.perf_counter()
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return {"ok": False, "comando": comando, "causa": "timeout",
                    "detail": "la instalación tardó más de 15 minutos — ejecútalo en tu terminal "
                              "para verla avanzar."}
        except Exception as e:
            return {"ok": False, "comando": comando, "causa": "error_upstream",
                    "detail": str(e)[:300]}
        dt = int((time.perf_counter() - t0) * 1000)
        salida = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        if remedio_id:
            # La confirmación fue explícita y el comando ejecutado es exactamente el que
            # estaba registrado/mostrado. Recién ahora el hallazgo IA queda como write-back.
            try:
                from app.phase1 import remedios_conectores as _rem
                _rem.confirmar(remedio_id)
            except Exception:
                pass
        return {"ok": p.returncode == 0, "comando": comando, "codigo": p.returncode,
                "latencia_ms": dt, "salida": salida[-4000:],
                "detail": "Listo." if p.returncode == 0
                          else "El comando terminó con error. El detalle crudo está abajo."}

    @router.post("/remedio/buscar")
    def http_buscar_remedio(body: dict = Body(...)):
        """Peldaño IA explícito: sólo se alcanza cuando catálogo+derivación dejaron hueco."""
        belt_ref = str(body.get("belt_ref") or "").strip()
        backed_by = str(body.get("backed_by") or "").strip()
        if not belt_ref or not backed_by:
            raise HTTPException(status_code=422, detail={"error": "falta_receta"})
        spec = _spec_de_belt(belt_ref, backed_by)
        if not spec:
            raise HTTPException(status_code=404, detail={"error": "sin_receta"})
        from app.phase1 import remedios_conectores as _rem
        return _rem.resolver(
            spec,
            catalog_id=f"{belt_ref}#{backed_by}",
            fuente=spec.get("fuente"),
            buscar_ia=True,
            forzar_busqueda=True,
        )

    # ── (§6c) LA SONDA DE INTERNET, expuesta ────────────────────────────────────────
    @router.get("/red")
    def http_red(force: bool = Query(default=False)):
        """El estado de la red medido por LA sonda (una, compartida, cache ~30 s). La UI la
        usa para el «[Reintentar] auto al volver» y las varas para probar que ningún
        `sin_red` se escribió sin que esto dijera que no."""
        from app.phase1 import red as _red
        return _red.sonda(force=force)

    # ── (§8) LA SONDA DE ARRANQUE ───────────────────────────────────────────────────
    @router.get("/arranque")
    def http_arranque(force: bool = Query(default=False)):
        """{ok:true} y nada más cuando el bundle está completo — silenciosa por contrato.
        Con fallas, entrega el reporte listo para [Copiar el reporte]."""
        from app.phase1 import arranque as _arr
        return _arr.medir(force=force)

    # Se corre AL MONTAR: si el bundle vino incompleto, queda dicho antes de que alguien
    # se coma un «error del proveedor» que en realidad era nuestro.
    try:
        from app.phase1 import arranque as _arr
        _arr.sonda_de_arranque()
    except Exception:   # noqa: BLE001 — una sonda jamás puede impedir el arranque
        pass

    return router


__all__ = [
    # contrato
    "PROBADO", "DETECTADO", "ROTO", "NO_CONFIGURADO", "PREMIUM", "ESTADOS",
    "FALTA_KEY", "SIN_RED", "CLI_NO_INSTALADO", "SIN_SESION", "TIMEOUT", "ERROR_UPSTREAM", "CAUSAS",
    "CLI_VERSION_VIEJA", "CLI_NO_LOGUEADO", "CLI_INTERACTIVO_COLGADO", "CLI_SIN_PERMISOS",
    "PLAN_INSUFICIENTE", "KEY_AUSENTE", "KEY_INVALIDA", "OAUTH_REVOCADO",
    "SIN_CREDITO", "RATE_LIMIT",
    "MODELO_NO_DISPONIBLE", "FALLA_DE_ALEPH", "PROVEEDOR_CAIDO", "GATE_BLOQUEADO",
    "ARGUMENTOS_INVALIDOS",
    "CEREBRO", "MCP", "KEY", "CLI", "TIPOS",
    # la escalera (§6) — pública para que el Centro y Modelos clasifiquen IGUAL
    "dependencia_local", "INSTALACION",
    # [FIX-P11] el censo de validadores (§1) + la huella que invalida por causa (§3)
    "validador_de", "conector_del_catalogo", "huella_de",
    # probers + orquestación
    "prueba_cli", "prueba_cerebro", "prueba_mcp", "prueba_key",
    "probar", "al_conectar", "estado", "invalidar_cache",
    # router
    "build_motor_router",
]


# ══════════════════════════════════════════════════════════════════════════════════
# [F9] TRES REGLAS DEL PROYECTO, medidas y selladas — para que no nos muerdan de nuevo
# ══════════════════════════════════════════════════════════════════════════════════
#
# 1 · **UN `max_tokens` CHICO CONTRA UN RAZONADOR DEVUELVE VACÍO Y COBRA IGUAL.**
#     Ninguna prueba puede coronar verde con eso. Es la SEGUNDA vez que muerde (F6 y F9).
#     Medido el 2026-08-07 contra `openai/gpt-oss-120b` —el default de groq, que declara
#     `razonamiento`— con `messages:[{"user":"ping"}]`:
#
#         max_tokens |  1     2     4     8    16    32
#         contenido  |  VACÍO en TODOS   (finish_reason: length)
#         costo      |  73 tokens la más barata (72 de prompt + 1)
#
#     El razonamiento se come el presupuesto antes de emitir un solo carácter. Una prueba
#     que lee «hubo respuesta 200» y corona verde está certificando un string vacío.
#
# 2 · **`max_tokens: 0` NO ES «UN TOKEN MENOS»: OpenRouter lo lee como SIN LÍMITE.**
#     Jamás usarlo de sonda. Medido: contesta **402** «This request requires more credits,
#     or fewer max_tokens. You requested up to 65536 tokens, but can only afford 15436».
#     O sea que una llave perfectamente válida sale rechazada por un motivo inventado por
#     la sonda. La sonda rompe un PARÁMETRO DE TIPO (`temperature`), que ningún proveedor
#     puede interpretar como una intención.
#
# 3 · **UN 403 NO SIEMPRE HABLA DE LA CREDENCIAL.** Medido: sin `User-Agent`, groq contesta
#     **403 «error code: 1010»** — un bloqueo de Cloudflare por firma de cliente. Leerlo
#     como `key_invalida` sería mandar a rotar una llave que está perfecta. Por eso toda
#     salida a un proveedor manda el `User-Agent` del motor.
