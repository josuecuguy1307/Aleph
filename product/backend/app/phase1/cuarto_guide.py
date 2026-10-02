"""cuarto_guide.py — LA COSTURA CHAT del GUÍA del Cuarto (belt cuarto-ui).

`POST /v1/cuarto/guide` — UNA vuelta del cerebro-guía (STATELESS). El loop de tool-calling
vive en el CLIENTE (cuarto.guide.js): el browser ejecuta cada tool_call llamando el MISMO
handler que el mouse (window.__guideHost) y vuelve a llamar acá con el resultado. Este server
NO ejecuta ninguna tool del Cuarto ni toca el mundo: sólo REENVÍA {messages, tools} al cerebro
elegido (reusando platform/assembler/models.py + la key de infra) y devuelve el turno del
asistente {content, tool_calls, model_final}.

POR QUÉ es "flaco" (§1 del contrato): las `tools` que reenvía son las 16 de cuarto-ui (las
manda el cliente); este endpoint no las conoce ni las corre — pasa el schema al modelo y
devuelve lo que pidió. Ningún efecto de mundo real pasa por acá; la línea de seguridad
(propuesta≠ejecución) la enforcea el host en el browser (las Puertas abren flujos gateados).

DOBLE ROL (§3): el cerebro-guía es la elección de PLATAFORMA del usuario (guide_model), SEPARADA
del cerebro de agentes. A propósito NO aplicamos la palanca de ops PUPPET_BRAIN acá (esa fuerza
el cerebro de los RUNS): si lo hiciéramos, los dos slots (guía vs agentes) colapsarían y el chip
mentiría. Resolvemos por el alias/brain_provider elegido, vía models.resolve (routing + key
correctos, dev/prod por env), sin el override.

ANNEX (sub-modelo BYO-CLI): si el guía usa un cerebro CLI y el cliente mandó `cli_model`, se
reenvía al server :8926 en el campo `cli_model` (que thread-ea el flag -m/--model del CLI).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_REPO = Path(__file__).resolve().parents[4]
_ASM_DIR = _REPO / "platform" / "assembler"

_models_mod = None


def _models():
    """Carga platform/assembler/models.py con `import models` (misma convención que
    assembler/recipe_assembler), COMPARTIENDO el módulo ya registrado en sys.modules.

    OJO (bug real cazado en verificación): cargarlo con spec_from_file_location bajo un
    nombre sintético que NO se registra en sys.modules rompe el @dataclass de models.py —
    `dataclasses._is_type` hace `sys.modules.get(cls.__module__).__dict__` y con el nombre
    sintético ausente eso es None → AttributeError al servir /v1/cuarto/guide en vivo. El
    `import models` normal deja `__module__ == "models"` (registrado) y no duplica la copia."""
    global _models_mod
    if _models_mod is None:
        if str(_ASM_DIR) not in sys.path:
            sys.path.insert(0, str(_ASM_DIR))
        import models as m  # noqa: E402  (comparte el módulo ya registrado; ver docstring)
        _models_mod = m
    return _models_mod


def _cognition_key() -> str:
    """Fallback de key: la de cognición de infra/.env (misma que el run) si la env var no está.
    `import recipe_assembler` (no spec sintético) por el mismo motivo que _models()."""
    try:
        if str(_ASM_DIR) not in sys.path:
            sys.path.insert(0, str(_ASM_DIR))
        import recipe_assembler as a  # noqa: E402
        return a._resolve_cognition_key(_REPO) or ""
    except Exception:
        return ""


# T5 · SABE (CUARTO HONESTO §5–§6): la base de conocimiento del Guía vive en docs/guia/<superficie>.<locale>.md.
_GUIA_SURFACES = ("cuarto", "piezas", "conectar", "cerebros", "sala", "memoria")
_guia_docs_cache: dict[str, str] = {}


def _guia_docs_dir() -> Path:
    """Dónde viven los MD del Guía, en dev Y en el bundle frozen.

    ⚠️ BUG REAL, MEDIDO [Integración #5 · sonda del bundle]. Esto era `_REPO / "docs" / "guia"`
    con `_REPO = Path(__file__).resolve().parents[4]`, y bajo PyInstaller ese cálculo se cae:
    este módulo sale del PYZ, así que `__file__` es `_MEIPASS/app/phase1/cuarto_guide.py` y
    subir 4 niveles aterriza DOS niveles ARRIBA de `_MEIPASS` —
    `/private/var/folders/<user>/<hash>` — donde no hay ningún `docs/`. Medido contra el binario
    Public snapshot: local temporary-path example generalized; behavior unchanged.
    recién construido: los MD SÍ viajan (`_MEIPASS/docs/guia/` tiene los 13 archivos), pero la
    ruta que los buscaba apuntaba afuera. En dev `parents[4]` sí da la raíz del repo, y por eso
    no se veía: el Guía se quedaba sin su base de conocimiento SÓLO en la .app, y en silencio
    (el `except: pass` de abajo se lo tragaba). Es el mismo gotcha PYZ/_MEIPASS que ya había
    mordido a `sqlite_db._ruta_schema()`, y se resuelve igual: `resource_root()` conoce los dos
    mundos (dev = raíz del árbol · frozen = `_MEIPASS`). Se prefiere el vecino local, que en dev
    es byte-idéntico a lo histórico.
    """
    local = _REPO / "docs" / "guia"
    if local.is_dir():
        return local
    try:
        import aleph_paths                                  # noqa: PLC0415 — perezoso, como el resto
    except ImportError:
        plat = str(_REPO / "platform")
        if plat not in sys.path:
            sys.path.insert(0, plat)
        import aleph_paths                                  # noqa: PLC0415
    return aleph_paths.resource_root() / "docs" / "guia"


def _guia_docs(locale: str) -> str:
    """Concatena docs/guia/<superficie>.<locale>.md — el poder SABE del Guía. Fail-soft en el
    CONTENIDO (si falta un archivo devuelve lo que haya y el Guía sigue andando por sus tools),
    pero NO mudo: si la base entera sale vacía se avisa por log, porque un Guía sin SABE contesta
    peor sin que nadie se entere — que es exactamente el fallo callado que la ley §4h prohíbe.
    Cacheado por locale (los MD son estáticos en runtime)."""
    loc = "en" if str(locale or "").lower().startswith("en") else "es"
    if loc in _guia_docs_cache:
        return _guia_docs_cache[loc]
    base = _guia_docs_dir()
    parts = []
    for surf in _GUIA_SURFACES:
        try:
            parts.append((base / f"{surf}.{loc}.md").read_text(encoding="utf-8"))
        except Exception:
            pass
    joined = "\n\n---\n\n".join(parts)
    if not joined:
        print(f"[guia] SABE vacío: no encontré docs/guia/*.{loc}.md en {base} — "
              f"el Guía va a contestar sólo con sus tools", flush=True)
    _guia_docs_cache[loc] = joined
    return joined


# T5 · FRONTIER-ONLY (CUARTO HONESTO §6 · cerebros.es.md): el Guía exige cerebro capaz — familia opus-4.8
# ('brain'/DEFAULT_BRAIN), tu propia API ('byok') o tu CLI por suscripción (CLI_BRAIN_PROVIDERS).
_FRONTIER_GUIDE_ALIASES = frozenset({"brain", "byok"})


def _es_frontier_guia(alias: Optional[str], brain_provider: Optional[str], M) -> bool:
    """True si el cerebro-guía es frontier (misma vara que Inspección). Todo lo demás (modelos chicos)
    → False, y el endpoint lo RECHAZA honesto (jamás corre un modelo chico como Guía; sin degradación silenciosa)."""
    if brain_provider and brain_provider in M.CLI_BRAIN_PROVIDERS:
        return True
    a = str(alias or "")
    if a in _FRONTIER_GUIDE_ALIASES:
        return True
    try:
        if a and a == M.DEFAULT_BRAIN:
            return True
    except Exception:
        pass
    return False


class GuideTurn(BaseModel):
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = []
    guide_model: dict[str, Any] = {}
    cli_model: Optional[str] = None
    locale: str = "es"   # T5 · qué idioma de docs/guia inyectar (SABE)


def _resolve_guide_brain(gm: dict) -> Optional[dict]:
    """Resuelve el cerebro-guía SÓLO desde el registro CONFIABLE de la plataforma (aliases
    conocidos de models.ALIASES — que INCLUYEN los providers CLI, apuntando a CLI_BRAIN_BASE).
    Devuelve None si el alias no es conocido.

    SEGURIDAD (review BLOCKER #1 · RULE 4 "cero mundo real / no toca credenciales"): este endpoint
    NO tiene auth propia y adjunta la key de infra para el cerebro elegido. Confiar en un `base_url`/
    `primary` CRUDO del cliente permitía SSRF + EXFILTRACIÓN de esa credencial — `base_url=
    "https://groq.com.attacker.tld/v1"` pasa el match-por-substring de key_env_for_base_url y se
    lleva la GROQ key real; loopback interno (169.254.169.254) daba SSRF ciego. Por eso resolvemos
    ÚNICAMENTE por alias del registro y JAMÁS pasamos hints del cliente (base_url/primary/fallback)
    a resolve: el base_url y la key SIEMPRE salen de models.ALIASES (hosts hardcodeados y vetados,
    env-aware dev/prod). Sin alias conocido → None (rechazo; no se ancla ninguna key a un host no
    vetado). NO se aplica el override PUPPET_BRAIN (guía ≠ agentes; ver docstring del módulo)."""
    M = _models()
    gm = gm or {}
    bp = (str(gm.get("brain_provider") or "").strip()) or None
    brain_provider = bp if bp in M.CLI_BRAIN_PROVIDERS else None   # provider desconocido → ignorado
    alias = brain_provider or (str(gm.get("alias") or "").strip()) or None
    if not alias or alias not in M.ALIASES:
        return None   # ni base_url ni primary del cliente se usan JAMÁS (anti-SSRF/exfiltración)
    target = M.DEFAULT_BRAIN if (alias == "brain" and M.DEFAULT_BRAIN != "brain") else alias
    rm = M.resolve(target)   # SIN hints del cliente → base_url/key SIEMPRE del registro
    return {"base_url": rm.base_url, "primary": rm.model, "key_env": rm.key_env,
            "brain_provider": brain_provider, "alias": alias}


def build_cuarto_guide_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["cuarto-guide"])

    @router.post("/cuarto/guide")
    def cuarto_guide(turn: GuideTurn):
        M = _models()
        r = _resolve_guide_brain(turn.guide_model or {})
        # r es None cuando el alias NO es del registro confiable → RECHAZO (anti-SSRF/exfil): jamás
        # se acepta un base_url/primary arbitrario del cliente ni se le adjunta la key de infra.
        if not r:
            return JSONResponse(status_code=400, content={"error": {
                "message": "cerebro-guía inválido: elige un modelo del catálogo (alias conocido); "
                           "no se aceptan endpoints arbitrarios",
                "type": "bad_guide_model"}})
        base_url = (r.get("base_url") or "").rstrip("/")
        primary = r.get("primary") or ""
        key_env = r.get("key_env")
        brain_provider = r.get("brain_provider")
        if not base_url or not primary:
            return JSONResponse(status_code=400, content={
                "error": {"message": "no pude resolver el cerebro-guía (guide_model inválido)", "type": "bad_guide_model"}})
        # T5 · FRONTIER-ONLY (§6): defensa en profundidad — aunque el selector del cliente ya bloquea los
        # modelos chicos, el backend NUNCA corre uno como Guía (jamás degradar en silencio). Rechazo honesto.
        if not _es_frontier_guia(r.get("alias"), brain_provider, M):
            return JSONResponse(status_code=400, content={"error": {
                "message": "el Guía necesita un cerebro frontier (Opus 4.8, tu propia API o tu CLI por "
                           "suscripción); elige uno capaz — no corro un modelo chico como Guía",
                "type": "not_frontier"}})

        # T5 · SABE: inyecta la base de conocimiento (docs/guia.<locale>) como 2º system, DESPUÉS del framing
        # del cliente. El cliente manda `locale`; la receta + el estado semáforo llegan por las tools del belt.
        messages = list(turn.messages)
        knowledge = _guia_docs(turn.locale)
        if knowledge:
            es = not str(turn.locale or "").lower().startswith("en")
            head = ("BASE DE CONOCIMIENTO DEL GUÍA (docs/guia — tu poder SABE; cuando pregunten «dónde/qué/cómo», "
                    "responde desde aquí y muestra el lugar real en la UI):\n\n" if es else
                    "GUIDE KNOWLEDGE BASE (docs/guia — your KNOW power; when asked where/what/how, answer from "
                    "here and point at the real place in the UI):\n\n")
            kn = {"role": "system", "content": head + knowledge}
            if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
                messages.insert(1, kn)
            else:
                messages.insert(0, kn)

        body: dict[str, Any] = {"model": primary, "messages": messages,
                                "temperature": 0, "max_tokens": 900}
        if turn.tools:
            body["tools"] = turn.tools
        # annex sub-modelo: SÓLO para cerebros CLI (:8926 lee `cli_model` → flag -m/--model).
        if turn.cli_model and brain_provider in M.CLI_BRAIN_PROVIDERS:
            body["cli_model"] = turn.cli_model

        headers = {"Content-Type": "application/json", "User-Agent": "puppet-cuarto-guide/1.0"}
        if key_env:
            key = os.environ.get(key_env, "") or _cognition_key()
            if not key:
                return JSONResponse(status_code=502, content={"error": {
                    "message": f"falta la key {key_env} para el cerebro-guía elegido; "
                               f"elige Opus (shim), tu CLI local, o configura esa key",
                    "type": "no_key"}})
            headers["Authorization"] = "Bearer " + key

        req = urllib.request.Request(base_url + "/chat/completions",
                                     data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:600]
            except Exception:
                pass
            # 400/error CLASIFICADO por el modelo pedido (annex): si el plan no soporta el
            # cli_model, se narra honesto ("pediste X, respondió …"), nunca falso verde.
            return JSONResponse(status_code=502, content={"error": {
                "message": f"el cerebro-guía respondió {e.code}: {detail or e.reason}",
                "type": "brain_error", "brain_status": e.code,
                "requested_cli_model": turn.cli_model}})
        except Exception as e:
            return JSONResponse(status_code=502, content={"error": {
                "message": f"no pude alcanzar el cerebro-guía: {e}", "type": "brain_unreachable"}})

        choice = ((data.get("choices") or [{}])[0]) or {}
        msg = choice.get("message") or {}
        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            # model_final HONESTO: lo que el cerebro reportó (no lo pedido). El chip lo muestra.
            "model_final": data.get("model") or primary,
            "brain_provider": brain_provider,
            "requested_cli_model": turn.cli_model,
        }

    return router
