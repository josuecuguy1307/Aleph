"""Aleph Educación entry point with no local identity or vendor control plane."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deeptutor.logging import configure_logging
from deeptutor.services.config import ensure_runtime_settings_files, load_system_settings
from deeptutor.services.config.origins import normalize_origins

ensure_runtime_settings_files()
configure_logging()
logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    settings = load_system_settings()
    port = str(settings["frontend_port"])
    origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    for origin in normalize_origins([settings["cors_origin"], settings["cors_origins"]]):
        if origin not in origins:
            origins.append(origin)
    return origins


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start no account, partner, cron, PocketBase or vendor control plane."""
    logger.info("Aleph Educación startup")
    try:
        from deeptutor.events.event_bus import get_event_bus

        await get_event_bus().start()
    except Exception as exc:
        logger.warning("EventBus unavailable: %s", exc)
    yield
    try:
        from deeptutor.events.event_bus import get_event_bus

        await get_event_bus().stop()
    except Exception:
        pass


app = FastAPI(title="Aleph Educación", version="1.0.0", lifespan=lifespan, redirect_slashes=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Aleph-Space"],
)

from deeptutor.api.routers import chat, unified_ws  # noqa: E402

app.include_router(chat.router, prefix="/api/v1", tags=["tutor"])
app.include_router(unified_ws.router, prefix="/api/v1", tags=["tutor-stream"])

# ── LOS ROUTERS QUE EL FRENTE PIDE Y NADIE MONTABA ────────────────────────────────────
# Medido el 2026-08-11 sobre el pack levantado entero (Next + este API): el backend
# publicaba TRES rutas —`/api/v1/chat/sessions`, su detalle y `/`— y el frontend pide
# `/api/v1/settings`, `/api/v1/memory/overview`, `/api/v1/system/status` y dos docenas más.
# Resultado: las 19 pantallas de `/settings/*` mostraban «Could not load settings from the
# backend — HTTP 404» SIEMPRE, y `/settings/memory`, `/memory/l2` y `/memory/l3` caían en
# el error boundary de Next («This page couldn't load»).
#
# No fue una extirpación: `EXTIRPACIONES.md` registra lo que sí se cortó (Partners, OAuth
# Codex, CLI-Anything, multiusuario/PocketBase, PyMuPDF) y ninguno de estos está en esa
# lista — sus módulos siguen enteros en `deeptutor/api/routers/`. Se perdieron al reescribir
# este entry point, que quedó montando sólo el chat.
#
# Se montan UNO POR UNO y no en un bucle sobre el directorio: la lista es explícita para
# que agregar un router sea una decisión escrita, y para que un módulo reintroducido por una
# actualización del stack no entre solo. Cada uno va en su propio try: un router que no
# importe (porque depende de algo extirpado) no puede dejar al tutor sin arrancar, y su
# ausencia se DICE en el log — fallo visible, jamás mudo.
# CADA ROUTER CON SU PREFIJO, Y EL PREFIJO NO SE ADIVINA.
# Salvo `chat` y `unified_ws` —que escriben la ruta completa adentro (`/chat/sessions`)—,
# los routers declaran rutas RELATIVAS: `settings` declara `""` y `/catalog`, `memory`
# declara `/overview`. Montarlos todos bajo `/api/v1` a secas los deja colgando de la raíz
# y el frontend, que pide `/api/v1/settings/catalog` y `/api/v1/memory/overview`, sigue sin
# encontrarlos. Medido: con el prefijo plano, `GET /api/v1/settings` contestaba 200 pero con
# la config del sistema (chat/solve/research) en vez de las preferencias, y la pantalla de
# Ajustes cambiaba su error de «HTTP 404» a «Cannot read properties of undefined (reading
# 'theme')» — un fallo peor, porque parece un dato mal formado y no una ruta ausente.
#
# El mapa sale del `main.py` de HKUDS/DeepTutor@456f9c2, que es la fuente autoritativa:
# ahí está escrito con qué prefijo se monta cada uno. Dos que allí figuran NO están acá:
# `partners` y `space_cli_apps`, cortados por EXTIRPACIONES.md (sus módulos no existen en
# este árbol). `auth` tampoco: acá `routers/auth.py` sólo provee dependencias y no publica
# `APIRouter`, justamente para no reponer `/login`, `/register` ni el callback de Codex.
_ROUTERS_DEL_FRENTE = [
    ("agent_config", "/api/v1/agent-config"),
    ("attachments", "/api/attachments"),
    ("book", "/api/v1/book"),
    ("capabilities_settings", "/api/v1/capabilities"),
    ("co_writer", "/api/v1/co_writer"),
    ("dashboard", "/api/v1/dashboard"),
    ("imports", "/api/v1/imports"),
    ("knowledge", "/api/v1/knowledge"),
    ("mastery_path", "/api/v1/learning"),      # el módulo se llama distinto que su ruta
    ("memory", "/api/v1/memory"),
    ("notebook", "/api/v1/notebook"),
    ("personas", "/api/v1/personas"),
    ("plugins_api", "/api/v1/plugins"),
    ("question", "/api/v1/question"),
    ("question_notebook", "/api/v1/question-notebook"),   # guion, no guion bajo
    ("quiz_judge", "/api/v1"),                 # escribe su ruta completa adentro
    ("sessions", "/api/v1/sessions"),
    ("settings", "/api/v1/settings"),
    ("mcp_settings", "/api/v1/settings/mcp"),  # cuelga DEBAJO de settings
    ("skills", "/api/v1/skills"),
    ("space_mcp", "/api/v1/space/mcp"),
    ("subagents", "/api/v1/subagents"),
    ("system", "/api/v1/system"),
    ("tools", "/api/v1/tools"),
    ("voice", "/api/v1/voice"),
]

_montados: list[str] = []
_ausentes: list[str] = []
for _nombre, _prefijo in _ROUTERS_DEL_FRENTE:
    try:
        _mod = __import__(f"deeptutor.api.routers.{_nombre}", fromlist=["router"])
        app.include_router(_mod.router, prefix=_prefijo, tags=[_nombre])
        # `settings` publica DOS routers: `router` y `public_router`. En el segundo vive
        # `GET /api/v1/settings/ui`, de donde el shell saca tema e idioma ANTES de que
        # exista sesión. Se monta pegado al primero para que no se olvide al leer la lista.
        _extra = getattr(_mod, "public_router", None)
        if _extra is not None:
            app.include_router(_extra, prefix=_prefijo, tags=[f"{_nombre}-public"])
        _montados.append(_nombre)
    except Exception as _exc:  # noqa: BLE001 — cualquier fallo de import es dato, no crash
        _ausentes.append(f"{_nombre} ({type(_exc).__name__}: {_exc})")

logger.info("routers montados (%d): %s", len(_montados), ", ".join(_montados))
if _ausentes:
    logger.warning("routers NO montados (%d): %s", len(_ausentes), " · ".join(_ausentes))

# EL COMODÍN VA ÚLTIMO. La única ruta de `outputs` es `@router.api_route("/{output_path:path}")`:
# bajo `/api/v1` se tragaba todo lo que no estuviera registrado antes que él —medido: pedir
# `/api/v1/settings/ui` devolvía `404 {"detail":"Output not found"}`, su mensaje, no el de
# settings—. Sirve descargas del workspace y el frontend lo llama en `/api/outputs/…`.
try:
    from deeptutor.api.routers import outputs as _outputs_mod  # noqa: E402

    app.include_router(_outputs_mod.router, prefix="/api/outputs", tags=["outputs"])
    logger.info("montado outputs en /api/outputs (descargas del workspace)")
except Exception as _exc:  # noqa: BLE001
    logger.warning("outputs NO montado (%s: %s)", type(_exc).__name__, _exc)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "aleph-educacion", "surface": "tutor"}
