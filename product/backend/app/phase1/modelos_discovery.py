"""modelos_discovery.py — EL CATÁLOGO DE LA VÍA API SALE DEL PROVEEDOR, NO DE UNA CONSTANTE.

Gate 2 · F6-cierre · Obra A.

⚠️ POR QUÉ EXISTE, con el caso que lo pagó.

`_PICKER_HOSTEADO["api.openrouter"]` declaraba `"model": "openai/gpt-4o"`, escrito una vez
y para siempre. F6-bis midió qué pasa con eso: se pidió certificar
`qwen/qwen3.6-plus:free` y **ese id no existe**; `openai/gpt-oss-120b:free`, el fallback,
**tampoco**. Los dos habían sido ciertos en algún momento. El catálogo de un proveedor
cambia sin avisarle a nadie, y un id hardcodeado no envejece: se muere, y el usuario se
entera con un 404 que no dice nada.

La vía local ya resolvió esto y **acá se calca**: `centro_modelos._ollama_tags()` le
pregunta a `/api/tags` qué hay instalado en vez de declararlo. Lo mismo, contra
`GET /api/v1/models` del proveedor.

──────────────────────────────────────────────────────────────────────────────────────
LAS TRES REGLAS

  1. **NORMALIZAR, NO REENVIAR.** El crudo del proveedor es de él y cambia cuando quiere.
     Acá sale la forma de §11 —`provider_id · model_id · context · capacidades · free`— y
     el resto de Aleph no ve el JSON de nadie. Si mañana OpenRouter renombra un campo, se
     arregla en esta función y en ninguna otra.

  2. **CACHÉ CON FECHA VISIBLE, Y LA CADUCIDAD ES LA DE F4c.** Un catálogo guardado no es
     un catálogo cierto: es una medición, y las mediciones envejecen. Se reusa
     `modelos_caducidad.rancia()` —el mismo TTL y el mismo `calendar.timegm` que ya cazó
     un bug de 3 horas— para que «rancio» signifique UNA sola cosa en todo el producto.
     La fecha viaja en la respuesta: una pantalla puede decir «catálogo de hace 2 días».

  3. **UN ID QUE MURIÓ NO ES UN 404.** Entre descubrir y usar puede pasar tiempo. Si el id
     ya no está en el catálogo, esto devuelve la causa TIPADA `modelo_no_disponible` con
     `re_descubrir=True`, que es la acción que resuelve. Dejar salir el 404 crudo sería
     exactamente el string pelado que F4b vino a matar.

FALLO VISIBLE, JAMÁS MUDO: sin red, con llave inválida o con el proveedor caído, esto NO
inventa un catálogo. Devuelve el cacheado marcándolo rancio, o vacío con su causa.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app.phase1 import modelos_caducidad as _cad

# Import BLANDO del motor: de ahí salen la TABLA de autenticación por proveedor
# (`_KEY_VALIDATORS`) y el ÚNICO armador que la aplica (`poner_credencial`). Blando porque
# este módulo tiene que poder importarse en un árbol a medias, igual que el traductor.
try:
    from app.phase1 import motor_verdad as _mv
except Exception:                                  # noqa: BLE001 — pragma: no cover
    _mv = None                                     # type: ignore

try:
    import aleph_paths as _ap
except ImportError:                                # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

# ── EL TRADUCTOR (Gate 2 · F1) ─────────────────────────────────────────────────────
# Import BLANDO, el mismo de `stream_chat.py`: con `_tr is None` esto sigue funcionando y
# la causa sale sin traducir en vez de romper el descubrimiento. El vocabulario de causas
# tiene UN dueño y no se re-declara acá.
_ASM_DIR = _ap.resource_root() / "platform" / "assembler"
try:
    if str(_ASM_DIR) not in sys.path:
        sys.path.insert(0, str(_ASM_DIR))
    import errores_modelo as _tr                   # type: ignore
except ImportError:                                # pragma: no cover
    _tr = None                                     # type: ignore

# ══════════════════════════════════════════════════════════════════════════════════
# [F8 · obra 1] DÓNDE SE DESCUBRE Y CON QUÉ DIALECTO
#
# ⚠️ LA AUTENTICACIÓN NO ESTÁ ACÁ. La declara `motor_verdad._KEY_VALIDATORS` (`header`:
# bearer | x-api-key | query, más su `extra`) y la pone `motor_verdad.poner_credencial`.
# Una segunda tabla de «cómo se manda la llave» se desincroniza en cuanto un proveedor
# cambia, y el síntoma sería un 401 que se lee como «tu llave no sirve».
#
# ⚠️ Y LA URL SE DECLARA ENTERA, no se compone con la `base` del validador: `deepseek`
# valida contra `https://api.deepseek.com` pero lista en `.../v1/models`. Componer daría
# una URL que no existe, y el fallo aparecería como «el proveedor no contesta».
#
# Agregar un proveedor = UNA FILA acá (+ una en `_KEY_VALIDATORS` si no está). Jamás un
# `if provider == …`.
# ══════════════════════════════════════════════════════════════════════════════════
RUTAS = {
    "openrouter": {"url": "https://openrouter.ai/api/v1/models",  "forma": "openai"},
    "openai":     {"url": "https://api.openai.com/v1/models",     "forma": "openai"},
    "groq":       {"url": "https://api.groq.com/openai/v1/models", "forma": "openai"},
    "together":   {"url": "https://api.together.xyz/v1/models",   "forma": "openai"},
    "mistral":    {"url": "https://api.mistral.ai/v1/models",     "forma": "openai"},
    "deepseek":   {"url": "https://api.deepseek.com/v1/models",   "forma": "openai"},
    # ⚠️ LAS DOS NUEVAS, Y SU FORMA ESTÁ DECLARADA-NO-VERIFICADA. No hay llave de estos dos
    # proveedores en esta máquina, así que la respuesta EXITOSA no se pudo medir: lo que se
    # midió (2026-08-07) es que los endpoints existen y piden credencial. Por eso
    # `_leer_lista` es FAIL-VISIBLE — si el dialecto no es el declarado, sale una causa que
    # lo dice, en vez de una lista vacía que parece «este proveedor no tiene modelos».
    "anthropic":  {"url": "https://api.anthropic.com/v1/models",  "forma": "anthropic"},
    "gemini":     {"url": "https://generativelanguage.googleapis.com/v1beta/models",
                   "forma": "google"},
}

#: CÓMO SE LEE CADA DIALECTO. Es una DECLARACIÓN, no código por proveedor: tres proveedores
#: nuevos que hablen `openai` no agregan una línea acá.
#:
#:   lista  — la clave del array en la respuesta
#:   id     — de dónde sale el `model_id`
#:   label  — el nombre lindo (cae al id si no está)
#:   ctx    — la ventana, si el proveedor la declara en el listado
#:   texto  — cómo se sabe que ESTE modelo sirve para chatear. `None` = el listado no lo
#:            dice y todos los que lista son de chat (Anthropic sólo publica modelos Claude).
FORMAS = {
    # ⚠️ `modalidades` y `ctx` son LISTAS DE RUTAS CANDIDATAS, y eso NO es indecisión: el
    # mismo dialecto OpenAI pone los campos en lugares distintos según el proveedor.
    # MEDIDO el 2026-08-07 contra los dos únicos con llave en esta máquina:
    #   · OpenRouter → `architecture.{input,output}_modalities` · `context_length`
    #   · Groq       → `{input,output}_modalities` AL NIVEL DE LA FILA · `context_window`
    # Se lee la primera ruta que exista. Un proveedor nuevo que use cualquiera de las dos
    # anda sin tocar nada; uno que use una tercera agrega la ruta acá, no un `if`.
    "openai":    {"lista": "data", "id": "id", "label": "name",
                  "modalidades": ["architecture", ""],
                  "ctx": ["context_length", "context_window", "top_provider.context_length"],
                  "features": ["supported_parameters", "supported_features"],
                  "texto": "modalidades"},
    "anthropic": {"lista": "data", "id": "id", "label": "display_name",
                  "modalidades": [], "ctx": [], "features": [], "texto": None},
    # `id_prefijo`: Google devuelve `models/gemini-2.5-flash` y el id útil es lo de después.
    # ⚠️ VA DECLARADO POR DIALECTO Y NO SE APLICA A TODOS: los ids de OpenRouter LLEVAN
    # barra de verdad (`x-ai/grok-4.20`, `openai/gpt-4o`) y recortarla los rompe. MEDIDO el
    # 2026-08-07 al escribir esto: con el recorte global, OpenRouter elegía `grok-4.20`
    # —un id que no existe— en vez de `x-ai/grok-4.20`. Es el mismo bug que F6 pagó con
    # ids muertos, ahora fabricado por nosotros.
    "google":    {"lista": "models", "id": "name", "label": "displayName",
                  "modalidades": [], "ctx": ["inputTokenLimit"], "features": [],
                  "texto": "generateContent", "id_prefijo": "models/"},
}

#: EL ÚNICO ID HARDCODEADO QUE QUEDA EN LA VÍA API, y está acá a propósito: es el suelo
#: cuando el discovery no pudo correr. Declarado, con su motivo, en un solo lugar y
#: nombrado como lo que es. Medido el 2026-08-05: existe en el catálogo gratuito de
#: OpenRouter. Si un día también muere, el guard de §3 lo dirá tipado en vez de un 404.
FALLBACK_DECLARADO = "openai/gpt-oss-20b:free"

_TIMEOUT_S = 8.0


def _dir_cache() -> Path:
    from app.phase1.centro_modelos import modelos_dir
    d = modelos_dir() / "catalogo_api"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ahora_iso(t: Optional[float] = None) -> str:
    #: UTC, igual que `modelos_repo._ahora_iso`. `rancia()` desarma con `calendar.timegm`,
    #: y mezclar husos acá reintroduciría el bug de las 3 horas por la puerta de atrás.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t if t is not None else time.time()))


# ══════════════════════════════════════════════════════════════════════════════════
# §11 · LA NORMALIZACIÓN — la forma que ve el resto de Aleph
# ══════════════════════════════════════════════════════════════════════════════════
def _por_ruta(crudo: dict, rutas) -> Optional[object]:
    """El primer valor que exista entre las RUTAS DECLARADAS. `a.b` baja un nivel."""
    for r in (rutas or []):
        cur = crudo
        for parte in str(r).split(".") if r else []:
            cur = (cur or {}).get(parte) if isinstance(cur, dict) else None
        if cur:
            return cur
    return None


def _leer_lista(crudo: dict, forma: str) -> tuple[Optional[list], Optional[dict]]:
    """(filas, causa). FAIL-VISIBLE: si el dialecto no es el declarado, se DICE.

    ⚠️ [F8] Devolver `[]` ante una forma inesperada sería el peor de los dos mundos: la
    pantalla diría «este proveedor no tiene modelos» —una afirmación sobre el proveedor—
    cuando lo que pasó es que NOSOTROS declaramos mal el dialecto. Son diagnósticos
    distintos y llevan a arreglos distintos.
    """
    clave = (FORMAS.get(forma) or {}).get("lista") or "data"
    filas = crudo.get(clave)
    if isinstance(filas, list):
        return filas, None
    return None, {"causa": "forma_inesperada",
                  "detalle": f"el listado no trae «{clave}» — claves recibidas: "
                             f"{sorted(crudo)[:8]}"}


def normalizar(provider_id: str, crudo: dict, forma: str = "openai") -> Optional[dict]:
    """Una entrada del proveedor → la forma de §11. `None` si no es un modelo de texto.

    `free` NO se adivina por el sufijo del nombre: se mira el PRECIO. `:free` es una
    convención de OpenRouter que otros no usan, y un modelo puede ser gratis sin llamarse
    así. Mirar el precio es la única lectura que vale en todos los proveedores.
    """
    F = FORMAS.get(forma) or FORMAS["openai"]
    mid = str(crudo.get(F["id"]) or "").strip()
    _pref = F.get("id_prefijo")
    if _pref and mid.startswith(_pref):
        mid = mid[len(_pref):]
    if not mid:
        return None

    precio = crudo.get("pricing") or {}
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    p_in, p_out = _num(precio.get("prompt")), _num(precio.get("completion"))
    # Sin precios declarados NO se afirma que sea gratis: se dice que no se sabe (`None`).
    # Un `False` inventado haría que el selector esconda modelos que sí son gratis, y un
    # `True` inventado le cobraría al usuario sin avisarle.
    if p_in is None and p_out is None:
        free = None if not mid.endswith(":free") else True
    else:
        free = (p_in or 0.0) == 0.0 and (p_out or 0.0) == 0.0

    # El nodo donde viven las modalidades: `architecture` en OpenRouter, la fila misma en
    # Groq. `""` en la tabla significa «la fila misma».
    arq = crudo
    for _r in (F.get("modalidades") or []):
        _n = crudo.get(_r) if _r else crudo
        if isinstance(_n, dict) and (_n.get("input_modalities") or _n.get("output_modalities")):
            arq = _n
            break
    entradas = (arq.get("input_modalities") if isinstance(arq, dict) else None) or []
    salidas = (arq.get("output_modalities") if isinstance(arq, dict) else None) or []
    params = _por_ruta(crudo, F.get("features")) or []
    caps = []
    # ★ `texto` = ESTE MODELO SIRVE PARA CHATEAR, y hay que mirarlo, no suponerlo. Medido
    # el 2026-08-05 en el catálogo de OpenRouter: `google/lyria-3-clip-preview` declara
    # 1.048.576 de contexto y sale `["text","audio"]` — es un modelo de MÚSICA, y por
    # tamaño ganaba la elección de «el más grande gratis». Un chat que contesta con audio
    # no es un chat: se pide salida de texto y punto.
    # ── ¿ESTE MODELO SIRVE PARA CHATEAR? — por el dialecto DECLARADO, no por proveedor ──
    #   "modalidades"     → el dialecto OpenAI publica modalidades: se miran (ver ★ abajo)
    #   "generateContent" → Google publica los métodos que soporta cada modelo
    #   None              → el listado no lo dice y TODO lo que lista es de chat
    #                       (Anthropic sólo publica modelos Claude en `/v1/models`)
    _tx = F.get("texto")
    if _tx is None:
        caps.append("texto")
    elif _tx == "modalidades":
        if salidas == ["text"] or (not salidas and "text" in entradas):
            caps.append("texto")
    elif _tx in (crudo.get("supportedGenerationMethods") or []):
        caps.append("texto")
    # ★ `router` = no es un modelo, es un despachador (`openrouter/auto`, tokenizer
    # "Router"). Declara 2.000.000 de contexto y ganaba por goleada, pero elegirlo es
    # delegar en la heurística de OTRO qué modelo corre — y entonces `model_id` deja de
    # decir qué corrió, que es lo único que esta pieza existe para saber.
    if str(arq.get("tokenizer") or "").lower() == "router":
        caps.append("router")
    if "image" in entradas:
        caps.append("vision")
    if "tools" in params:
        caps.append("tools")
    if "reasoning" in params:
        caps.append("razonamiento")

    ctx = _por_ruta(crudo, F.get("ctx"))
    try:
        ctx = int(ctx) if ctx else None
    except (TypeError, ValueError):
        ctx = None

    return {
        "provider_id": provider_id,
        "model_id": mid,
        "label": str(crudo.get(F["label"]) or mid),
        "context": ctx,
        "capacidades": caps,
        "free": free,
        # ⚠️ [F9] `salidas` SE SUMA A §11, y la forma estaba congelada («la forma es la de
        # §11 y NADA más», `verify_f6:122`). Se agrega a propósito y con motivo:
        #
        # `capacidades` es una PROYECCIÓN con pérdida. Dos modelos que no sirven de cerebro
        # por razones opuestas —`whisper` transcribe, `orpheus` habla— salen los dos con
        # `capacidades=()`, y desde ahí el rechazo sólo puede ser genérico. La regla sellada
        # por persona usuaria es que cada motivo tenga SU copy, derivado de lo que el catálogo declara;
        # sin las salidas ese copy habría que inventarlo, que es justo lo prohibido.
        #
        # Se guarda lo DECLARADO, ordenado para poder compararlo. Vacío = el proveedor no lo
        # dice (Anthropic no publica modalidades), y eso también es un dato: se distingue
        # «no declara» de «declara algo que no sirve».
        "salidas": salidas,
    }


# ══════════════════════════════════════════════════════════════════════════════════
# §2 · DESCUBRIR — con caché fechado y caducidad de F4c
# ══════════════════════════════════════════════════════════════════════════════════
#: LA VERSIÓN DE LA FORMA NORMALIZADA (§11). Sube cuando `normalizar()` cambia lo que
#: devuelve, y un caché de otra versión se DESCARTA en vez de servirse a medias.
#:
#: ⚠️ LO CAZÓ LA CERTIFICACIÓN DE F9 SOBRE EL BINARIO INSTALADO, y era invisible desde los
#: tests: F9 sumó `salidas` a §11, pero el caché en disco seguía siendo el de la forma
#: VIEJA. Los modelos cacheados llegaban sin `salidas`, y entonces el rechazo perdía su copy
#: sellado —«Genera voz; no genera texto.»— y caía al genérico «El catálogo no declara que
#: devuelva texto». Medido: `openrouter.json` sin `salidas`, `groq.json` con ellas (recién
#: reescrito). El usuario habría visto un copy peor por una razón que no existe.
#:
#: Un caché que sobrevive a un cambio de forma es una versión vieja del producto sirviendo
#: datos a una nueva. La fecha de caducidad de F4c mide OTRA cosa (si el catálogo del
#: proveedor envejeció); esto mide si NOSOTROS cambiamos de idea.
FORMA_V = 2


def _leer_cache(provider_id: str) -> Optional[dict]:
    f = _dir_cache() / f"{provider_id}.json"
    try:
        datos = json.loads(f.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001 — sin caché es un caso normal
        return None
    # Un caché de otra forma NO se repara ni se completa: se tira. Rellenar campos que no
    # se midieron sería inventar el dato que la forma nueva vino a traer.
    if not isinstance(datos, dict) or int(datos.get("forma_v") or 1) != FORMA_V:
        return None
    return datos


def _escribir_cache(provider_id: str, datos: dict) -> None:
    try:
        (_dir_cache() / f"{provider_id}.json").write_text(
            json.dumps({**datos, "forma_v": FORMA_V}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass                                       # no poder cachear no rompe el descubrimiento


def descubrir(provider_id: str, key: Optional[str] = None, *,
              fresco: bool = False, ahora: Optional[float] = None) -> dict:
    """El catálogo VIVO del proveedor, normalizado. Nunca levanta.

    `{provider_id, modelos:[§11], descubierto_en, rancio, fuente, causa}`
      · `fuente`: 'red' | 'cache' | 'ninguna'
      · `rancio`: el caché envejeció (misma regla que las mediciones de modelos)
      · `causa`: tipada, cuando no se pudo descubrir
    """
    cache = _leer_cache(provider_id)
    ts_cache = (cache or {}).get("descubierto_en")
    cache_rancio = _cad.rancia(ts_cache, ahora=ahora)

    # Un caché fresco se reusa: preguntarle el catálogo entero al proveedor en cada
    # pantalla es pagar red por un dato que cambia en días, no en segundos.
    if cache and not cache_rancio and not fresco:
        return {**cache, "rancio": False, "fuente": "cache", "causa": None}

    decl = RUTAS.get(provider_id)
    if not decl:
        # No es un fallo: es un proveedor que no publica catálogo. Se dice así.
        return {"provider_id": provider_id, "modelos": [], "descubierto_en": None,
                "rancio": False, "fuente": "ninguna",
                "causa": {"causa": "sin_descubrimiento",
                          "detalle": f"{provider_id} no publica catálogo de modelos"}}
    ruta, forma = decl["url"], decl.get("forma", "openai")

    # ⚠️ [F8 · obra 1] LA CREDENCIAL VIAJA, Y LA FORMA LA DECLARA EL VALIDADOR.
    #
    # ANTES esto mandaba `Authorization: Bearer` a secas y sólo cuando el llamador pasaba
    # `key` — y el llamador (`centro_modelos._modelo_de_api`) NO la pasaba. MEDIDO el
    # 2026-08-07 sobre la app instalada, descubriendo los 8 proveedores sin credencial:
    #
    #     openrouter  400 modelos   ← su /models es público
    #     openai · mistral · deepseek    0   key_invalida
    #     groq · together                0   plan_insuficiente
    #     anthropic · gemini             0   sin_descubrimiento (ni estaban en la tabla)
    #
    # O sea: 7 de 8 proveedores sin catálogo, y el único que andaba era el que no necesita
    # llave. El «catálogo vivo» era vivo para uno solo.
    _auth = (_mv._KEY_VALIDATORS.get(provider_id) or {}) if _mv else {}
    ruta, cab = (_mv.poner_credencial(ruta, key, header=_auth.get("header", "bearer"),
                                      extra=_auth.get("extra"))
                 if _mv else (ruta, {"Authorization": f"Bearer {key}"} if key else {}))
    req = urllib.request.Request(ruta, headers={"Accept": "application/json", **cab})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
            crudo = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception as exc:                       # noqa: BLE001 — red/llave/proveedor caído
        causa = None
        if _tr is not None:
            try:
                causa = _tr.desde_urllib(exc, url=ruta).como_dict()
            except Exception:                      # noqa: BLE001 — traducir jamás rompe
                causa = None
        # SE DEVUELVE EL CACHÉ VIEJO MARCADO RANCIO, no un catálogo vacío: un catálogo de
        # ayer sirve para elegir; una lista vacía deja al usuario sin opciones por un
        # timeout. Lo que NO se hace es esconder que está viejo.
        if cache:
            return {**cache, "rancio": True, "fuente": "cache", "causa": causa}
        return {"provider_id": provider_id, "modelos": [], "descubierto_en": None,
                "rancio": False, "fuente": "ninguna",
                "causa": causa or {"causa": "sin_red", "detalle": str(exc)[:200]}}

    brutas, mal = _leer_lista(crudo if isinstance(crudo, dict) else {}, forma)
    if mal is not None:
        # El dialecto no era el declarado. Se dice ASÍ —es un problema NUESTRO— en vez de
        # devolver una lista vacía, que se leería como «este proveedor no tiene modelos».
        if cache:
            return {**cache, "rancio": True, "fuente": "cache", "causa": mal}
        return {"provider_id": provider_id, "modelos": [], "descubierto_en": None,
                "rancio": False, "fuente": "ninguna", "causa": mal}
    filas = []
    for m in brutas:
        n = normalizar(provider_id, m if isinstance(m, dict) else {}, forma)
        if n:
            filas.append(n)
    filas.sort(key=lambda f: f["model_id"])

    datos = {"provider_id": provider_id, "modelos": filas,
             "descubierto_en": _ahora_iso(ahora)}
    _escribir_cache(provider_id, datos)
    return {**datos, "rancio": False, "fuente": "red", "causa": None}


# ══════════════════════════════════════════════════════════════════════════════════
# §3 · EL GUARD — un id que murió sale TIPADO, jamás como 404 crudo
# ══════════════════════════════════════════════════════════════════════════════════
def verificar_vigente(provider_id: str, model_id: str, catalogo: dict) -> Optional[dict]:
    """`None` si el id sigue vivo; si no, la causa TIPADA con la acción que la resuelve.

    Se calla sobre un catálogo que no se pudo traer: afirmar «ese modelo no existe» porque
    se cayó la red sería inventar un diagnóstico. Sin catálogo no hay veredicto.
    """
    if not model_id:
        return None
    if catalogo.get("fuente") == "ninguna" or not catalogo.get("modelos"):
        return None
    vivos = {m["model_id"] for m in catalogo["modelos"]}
    if model_id in vivos:
        return None
    return {
        "causa": "modelo_no_disponible",
        "estado": "roto",
        "detalle": f"«{model_id}» ya no está en el catálogo de {provider_id}.",
        "evidencia": {"model_id": model_id, "provider_id": provider_id,
                      "catalogo_de": catalogo.get("descubierto_en"),
                      "rancio": bool(catalogo.get("rancio")), "modelos_vivos": len(vivos)},
        "reintentable": False,
        "re_descubrir": True,          # LA ACCIÓN: no «reintentá», sino «volvé a descubrir»
        "fuente": "api",
    }


# ══════════════════════════════════════════════════════════════════════════════════
# §4 · ELEGIR — del catálogo vivo, con la prioridad declarada
# ══════════════════════════════════════════════════════════════════════════════════
def servible(m: dict) -> bool:
    """¿Este modelo puede ser el CEREBRO de un agente?

    SERVIBLE = emite texto · no es un router · no es de embeddings. Los tres filtros
    salieron de mirar el catálogo real, no de imaginarlo: sin ellos «el más grande» daba un
    modelo de música y «el más grande a secas» daba un despachador.

    ⚠️ [F9] ES UNA FUNCIÓN CON NOMBRE, y antes era un `if` adentro de `elegir()`. El motivo
    lo dio una medición del 2026-08-07: el catálogo real de groq trae **15 modelos, 11
    servibles y 4 que no** —dos de voz (`orpheus`) y dos de transcripción (`whisper`)—, y la
    regla vivía en un solo lugar que sólo corría cuando ELEGÍA Aleph. Todo el resto del
    producto —el guard que valida la elección del usuario, el picker que la ofrece— no tenía
    forma de preguntarla sin copiar el `if`. Copiarlo es cómo se llega a que la pantalla
    ofrezca Whisper de cerebro y el backend lo acepte.
    """
    caps = m.get("capacidades") or []
    return ("texto" in caps and "router" not in caps
            and "embed" not in str(m.get("model_id") or "").lower())


#: Cómo se lee cada modalidad de salida cuando hay que nombrarla. Sale de lo que los
#: catálogos REALES declaran (barrido del 2026-08-07 sobre groq y openrouter, los dos
#: proveedores con llave en esta máquina). Un valor que no esté acá se dice tal como vino:
#: nombrar mal es peor que citar.
_SALIDA_ES = {"image": "imagen", "audio": "audio", "speech": "voz",
              "transcription": "transcripción", "video": "video", "text": "texto"}


def motivo_no_servible(m: dict) -> str:
    """POR QUÉ este modelo no puede ser el cerebro — en las palabras del catálogo.

    ⚠️ COPY SELLADO POR PERSONA USUARIA (2026-08-07) tras barrer los catálogos reales, y las TRES
    familias salieron de la medición, no de imaginarlas:

      1. NO devuelve texto            → transcripción · voz     (groq: 2 + 2)
      2. devuelve texto PERO NO SOLO  → imagen · audio          (openrouter: 9 + 4)
      3. router                       → no es de modalidad      (openrouter: 17)

    ⚠️ LA FAMILIA 2 EXISTE PORQUE MI PRIMERA REDACCIÓN ERA MENTIRA. «No genera texto» es
    falso para 13 de los 30 casos de openrouter: `openai/gpt-audio` declara
    `out=["audio","text"]` y `google/gemini-3.1-flash-image` declara `out=["image","text"]`
    — los dos generan texto. Decirles lo contrario es mentirle a alguien que puede abrir el
    catálogo del proveedor y verificar. Se les reconoce el texto y se dice qué sobra.

    El ROUTER no es una modalidad y su copy no habla de eso: enruta perfectamente y devuelve
    texto. El problema es que no se puede saber QUÉ modelo respondió — que es exactamente lo
    que esta pieza existe para saber.

    Y lo que no encaje en las tres: copy DERIVADO de lo que el catálogo declare. Jamás un
    rechazo mudo, jamás una categoría inventada para un proveedor que todavía no vimos.
    """
    caps = m.get("capacidades") or []
    sal = [s for s in (m.get("salidas") or [])]
    if "router" in caps:
        return "Enruta a otros modelos: no se puede saber cuál respondió."
    if sal == ["transcription"]:
        return "Transcribe audio; no genera texto."
    if sal == ["speech"]:
        return "Genera voz; no genera texto."
    extras = [s for s in sal if s != "text"]
    if "text" in sal and extras:
        if extras == ["image"]:
            return "Devuelve imagen además de texto; el cerebro necesita solo texto."
        if extras == ["audio"]:
            return "Devuelve audio además de texto; el cerebro necesita solo texto."
        nombres = " y ".join(_SALIDA_ES.get(s, s) for s in extras)
        return f"Devuelve {nombres} además de texto; el cerebro necesita solo texto."
    if sal:
        nombres = " y ".join(_SALIDA_ES.get(s, s) for s in sal)
        return f"Devuelve {nombres}; el cerebro necesita solo texto."
    # Sin salidas declaradas no se afirma QUÉ devuelve —eso sería inventar—, pero tampoco
    # se calla: se dice lo único que se sabe y por qué no alcanza.
    return "El catálogo no declara que devuelva texto; el cerebro necesita solo texto."


def elegir(catalogo: dict, *, solo_gratis: bool = False,
           preferido: Optional[str] = None) -> Optional[str]:
    """El id a usar: el más grande SERVIBLE del catálogo vivo.

    «Más grande» se ordena por `context`, que es el único tamaño que el proveedor declara
    de forma comparable — el número de parámetros no viaja en `/models`. `preferido` gana
    si sigue vivo **y sirve**, para que la elección del usuario no se la coma una heurística.
    """
    modelos = catalogo.get("modelos") or []
    # ⚠️ [F9] «SIGUE VIVO» NO ALCANZA: TAMBIÉN TIENE QUE SERVIR. Medido el 2026-08-07:
    # `elegir(preferido="canopylabs/orpheus-arabic-saudi")` devolvía ese id — un modelo de
    # VOZ coronado como cerebro del agente, porque esta rama miraba sólo si existía en el
    # catálogo y se disparaba ANTES del filtro de abajo. La preferencia del usuario sigue
    # ganando; lo que no puede es saltarse la única condición que hace que un modelo sea
    # usable como cerebro.
    if preferido and any(m["model_id"] == preferido and servible(m) for m in modelos):
        return preferido
    cand = [m for m in modelos if servible(m)]
    if solo_gratis:
        cand = [m for m in cand if m.get("free") is True]
    if not cand:
        return FALLBACK_DECLARADO if not modelos else None
    # ⚠️ [F8] EL DESEMPATE, y lo pagó una medición. Con la llave de groq puesta (2026-08-07)
    # quedaron CUATRO modelos empatados en 131.072 de contexto, y el orden de la lista le
    # daba la corona a `groq/compound` — que **no declara `tools`**. Un cerebro que no puede
    # llamar herramientas no sirve de default para un agente: el turno se cae recién cuando
    # la persona ya armó todo.
    #
    # «Mayor capacidad utilizable» (la ley sellada) se ordena así, y en este orden:
    #   1. el contexto, que es el único tamaño comparable que los proveedores declaran;
    #   2. `tools`, sin la cual el agente no puede usar sus piezas;
    #   3. `razonamiento`, que mejora el resultado sin cambiar lo que se puede hacer.
    # La preferencia del usuario ya ganó más arriba: esto sólo decide cuando NO hay elección.
    def _rango(m):
        caps = m.get("capacidades") or []
        return (m.get("context") or 0, 1 if "tools" in caps else 0,
                1 if "razonamiento" in caps else 0)
    cand.sort(key=_rango, reverse=True)
    return cand[0]["model_id"]


__all__ = ["RUTAS", "FORMAS", "FALLBACK_DECLARADO", "normalizar", "descubrir",
           "verificar_vigente", "elegir", "servible", "motivo_no_servible"]
