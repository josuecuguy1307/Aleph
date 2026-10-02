"""
router.py — endpoints FASE 1 sobre la DB de Fase 0 (montables en main.py).

Expone, bajo prefijo /v1, las cinco piezas del microtask backend:
  (a) endpoints sobre puppet_ai: auth, catálogo de puppets del usuario, workshop/config,
      storage (runs/keys), BYOK.
  (b) el Workshop VALIDA params contra el SCHEMA de la receta (recipe_validator, anidado
      A+A+C) y RECHAZA lo que rompe el contrato: POST /v1/recipes/validate y la validación
      embebida en POST /v1/puppets (guardar = validar primero).
  (c) event stream SSE: GET /v1/spaces/{space_id}/stream — pinta los eventos del loop
      (events.jsonl), soporta Last-Event-ID (replay exacto). Token-cost CERO.
  (d) instrumentación: POST /v1/runs/{run_id}/instrument liga los 5 campos por run_id.
  (e) BYOK falla a media tarea → 424 + señal TIPADA (handler de BYOKFailure → screen 11).

Inyección por callables (mismo patrón que espacios/conexiones en main.py): el router
resuelve `get_conn` y `events_dir` en tiempo de request, así los tests inyectan stubs.

Diseño defensivo: si psycopg2/DB no está disponible, los endpoints de DB devuelven 503
tipado (no un crash de import) — el stream SSE y la validación de receta NO dependen de DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel


class CliExecutableChoice(BaseModel):
    provider_id: str
    mode: str
    path: str = ""

from app.phase1 import recipe_validator as rv
from app.launch_cap import current as _current_launch_cap
from app.phase1 import event_stream as es
from app.phase1 import agent_catalog  # D3 · export + identidad visible; file I/O FUERA de repo.py
from app.phase1 import kit_base as _kit  # FIX-P4 · el KIT BASE de fábrica (normalizador de receta)
from app.phase1.byok import BYOKFailure, BYOK_HTTP_STATUS
# EL TAP DE ETAPAS (`ALEPH_ETAPAS=1`). Con guarda: un módulo de medición que rompe el
# import del router deja la app sin arrancar, que es el peor resultado posible para algo
# cuyo único trabajo es mirar. Sin él, `marca` es un no-op y el turno no se entera.
try:
    from app.infra import observability as _obs
except Exception:                                        # noqa: BLE001
    class _obs:                                          # type: ignore[no-redef]
        @staticmethod
        def marca(*_a, **_k): pass

import hashlib as _hashlib
import hmac as _hmac
import json as _json
import logging as _logging
import os
import re as _re
import sqlite3 as _sqlite3
import time as _time
import uuid as _uuid
import urllib.parse as _urlparse

_log = _logging.getLogger(__name__)


class _SobreModelo:
    """El aviso de que el modelo pedido no atendió, del resolver al sobre de la respuesta.

    Es un `ContextVar` por el mismo motivo que `sobre_turno`: el dato nace en el preflight y
    se necesita al armar la respuesta, con `workspace_brain.complete()` en el medio, y
    cambiarle la aridad a `_preflight_paso` le rompería el merge a las sesiones que lo están
    tocando. Se toma con `poner` y se VACÍA con `sacar`: un aviso que sobrevive a su pedido
    le contaría al turno siguiente una sustitución que no fue suya.
    """

    def __init__(self):
        from contextvars import ContextVar
        self._v = ContextVar("aleph_sobre_modelo", default=None)

    def poner(self, snapshot) -> None:
        cadena = list(getattr(snapshot, "fallback_chain", None) or [])
        self._v.set({"pedido": cadena[0], "atendio": getattr(snapshot, "selection_ref", ""),
                     "modelo": getattr(snapshot, "resolved_model", "")} if cadena else None)

    def sacar(self):
        v = self._v.get()
        self._v.set(None)
        return v


_sobre_modelo = _SobreModelo()


def _turno_de(valor: Optional[str]) -> int:
    """El número de turno que mandó un harness ajeno por cabecera, saneado.

    Una cabecera es texto y viene de otro proceso: puede llegar vacía, con espacios o
    con cualquier cosa. Un turno ilegible no es motivo para tumbar el paso —es un dato
    informativo que va al evento del espacio—, así que degrada a 1 en vez de reventar."""
    try:
        n = int(str(valor or "1").strip())
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1

try:
    import aleph_paths as _ap
except ImportError:
    import sys as _bootstrap_sys
    _bootstrap_sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

# ── EL SOBRE DEL TURNO (id + deadline), del borde al spawn ────────────────────
# Se carga como módulo PLANO desde el directorio del assembler, igual que `cli_brain`:
# `assembler.py` viaja como módulo plano en PyInstaller e importar `assembler.sobre_turno`
# colisionaría con él ("assembler is not a package").
# Fallback MUDO a propósito: sin el módulo, el borde sigue atendiendo turnos exactamente
# como antes de esta obra —lo único que se pierde es el reenvío del sobre, que mejora el
# corte pero no habilita el turno.
try:
    import sys as _sys_sobre
    _ad_sobre = str(_ap.resource_root() / "platform" / "assembler")
    if _ad_sobre not in _sys_sobre.path:
        _sys_sobre.path.insert(0, _ad_sobre)
    import sobre_turno as _sobre_turno            # type: ignore
except Exception:                                 # noqa: BLE001 — jamás rompe el borde
    class _SinSobre:
        @staticmethod
        def poner(*_a, **_k): return None
        @staticmethod
        def sacar(_t): pass
    _sobre_turno = _SinSobre()                    # type: ignore

# enforcer (clasificación money/send) cargado por ruta — para la política de aprobación
_RESOURCE_ROOT = _ap.resource_root()
_GATES_DIR = _RESOURCE_ROOT / "platform" / "gates"
_enf_mod = None
def _load_enforcer_mod():
    global _enf_mod
    if _enf_mod is None:
        _enf_mod = _ap.load_module_by_path(
            "puppet_recipe_enforcer_router", _GATES_DIR / "recipe_enforcer.py")
    return _enf_mod

# verbo humano para la bitácora de la sala (la sala muestra verb_human)
_VERB_HUMAN = {
    "create_workbook": "Creó la planilla", "write_data_to_excel": "Escribió datos en la planilla",
    "read_data_from_excel": "Leyó datos de la planilla", "apply_formula": "Aplicó una fórmula",
    "get_cik_by_ticker": "Buscó la empresa", "get_recent_filings": "Buscó reportes recientes",
    "get_financials": "Leyó los números", "lookup_price": "Consultó el precio",
    # belt default (inline-rich) + heroes: el timeline vivo de la sala narra por paso
    "run_python": "Calculó con Python", "write_xlsx": "Escribió la planilla",
    "write_csv": "Escribió el CSV",
    "add": "Sumó", "sub": "Restó", "mul": "Multiplicó", "div": "Dividió",
    "pow": "Elevó a potencia", "mod": "Calculó el módulo",
    "run_fem_analysis": "Corrió el análisis FEM", "backtest_portfolio": "Corrió el backtest",
    "ac_sweep": "Simuló el circuito", "worldbank_series": "Consultó el Banco Mundial",
    "search_works": "Buscó papers",
    # acciones sensibles que el gate retiene (money-touch / send): el verbo es la
    # INTENCIÓN ("quiere…"), porque cuando aparecen gateadas la acción NO se ejecutó.
    "place_order": "Quiere mover tu dinero", "send_message": "Quiere mandar un mensaje",
}
def _verb_human(tool_raw):
    return _VERB_HUMAN.get(tool_raw, "Usó una herramienta")


# ── borrado de cuenta (ticket 2): resolución de un login sobre cuenta borrada ───

def _resolve_deleted_login(conn, repo, user: dict, password_given) -> str:
    """Qué hacer cuando un login EXITOSO cae sobre una cuenta en soft-delete:
      - 'purged'            ventana vencida → purga lazy YA + cuenta inexistente.
      - 'password_required' puerta legacy sin contraseña sobre cuenta CON contraseña
                            → jamás reactiva (la reactivación exige la misma fuerza
                            de auth que la cuenta tiene).
      - 'reactivated'       dentro de la ventana → deleted_at a NULL, cuenta intacta."""
    from datetime import datetime, timezone

    state = repo.user_deleted_state(conn, user["id"]) or {}
    purge_after = state.get("purge_after")
    try:
        expired = bool(purge_after) and \
            datetime.fromisoformat(purge_after) <= datetime.now(timezone.utc)
    except ValueError:
        expired = False
    if expired:
        from app.phase1 import account_deletion
        account_deletion.purge_user(conn, user["id"])
        return "purged"
    if not password_given:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash IS NOT NULL FROM users WHERE id = %s",
                        (user["id"],))
            row = cur.fetchone()
        if row and row[0]:
            return "password_required"
    repo.reactivate_user(conn, user["id"])
    return "reactivated"


# ── modelos de request/response ───────────────────────────────────────────────

class RecipeValidateRequest(BaseModel):
    recipe: dict[str, Any]


class RecipeValidateResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str] = []
    effective_gates: dict[str, str] = {}  # §3.5: lo que Security HARÁ CUMPLIR (mandatorios siempre)


class ForgeRequest(BaseModel):
    """La FORJA: una intención (+ canvas actual opcional) → PROPONE 1 pieza (PROPONE, no commitea)."""
    intent: str
    current_canvas: Optional[dict[str, Any]] = None


class AuthRequest(BaseModel):
    email: str
    display_name: Optional[str] = None
    password: Optional[str] = None   # register/login real; ausente = legacy get-or-create (dev/interno)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MergeLocalRequest(BaseModel):
    """LOGIN SUAVE · fusión: el token de la sesión LOCAL (device user) cuyo trabajo
    se liga a la cuenta autenticada del header Authorization."""
    local_token: str


class PuppetCreateRequest(BaseModel):
    owner_id: str
    name: str
    nicho: str
    config: dict[str, Any]  # la receta v1 anidada
    # model-use/v1: el Cuarto nuevo manda sólo el id canónico y las perillas dentro de
    # config.model; el backend materializa primary/base_url/refs antes de validar.
    model_selection_ref: Optional[str] = None
    # TICKET 27 · HERENCIA AL NACER (opcional): {puppet_id, policy}. El hijo nace con el estante del
    # source COPIADO con provenance. policy = 'skill_only' (default) | {'projects':[...]} | {'entries':[...]}.
    inherit_from: Optional[dict[str, Any]] = None


class PuppetUpdateRequest(BaseModel):
    config: dict[str, Any]
    model_selection_ref: Optional[str] = None


class KeyUpsertRequest(BaseModel):
    user_id: str
    provider: str
    secret: str


class RunCreateRequest(BaseModel):
    puppet_id: Optional[str] = None
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    intent: Optional[str] = None


class InstrumentRequest(BaseModel):
    intent: Optional[str] = None
    belt: dict[str, Any]
    trayectoria: Optional[list[dict[str, Any]]] = None
    events: Optional[list[dict[str, Any]]] = None  # alternativa: armar trayectoria de eventos
    senal: Optional[dict[str, Any]] = None
    costo: Optional[dict[str, Any]] = None


class RunPuppetRequest(BaseModel):
    """Corre un puppet END-TO-END: receta anidada + prompt → loop con el ENFORCER
    en el path → run + instrumentation_logs persistidos por run_id en Postgres.
    `recipe` puede venir inline, o se carga de `puppet_id` (puppets.config)."""
    recipe: Optional[dict[str, Any]] = None
    puppet_id: Optional[str] = None
    # [LEY 15 · MODO RAW] `model` es el picker_id del selector de la casa. No es un
    # provider/base_url y jamás permite que el cliente saltee al model router.
    model: Optional[str] = None
    # Estado explícito del sobre. `None` es el camino raw válido; un agente persistido
    # sigue viajando por `puppet_id` y su receta owner-gated.
    agent: Optional[str] = None
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    prompt: str
    deadline_s: float = 180.0
    images: Optional[list[str]] = None   # data-URLs (visión): el run las manda al modelo multimodal
    lang: str = "es"   # [i18n-bi] idioma del usuario (aleph-lang) → PUPPET_LANG del run
    chat_id: Optional[str] = None   # [UX·A1] conversación persistente: el turno se registra
                                    # y el cerebro recibe el historial real del hilo
    client_turn_id: Optional[str] = None  # id estable del submit/retry: transcript idempotente
    autonomy: Optional[str] = None  # [UX·B1] override de la perilla para ESTE turno (el
                                    # selector de la Sala): se foldea en la receta antes de
                                    # validar; los pisos del gate no se relajan jamás
    method_id: Optional[str] = None      # PIEZA MÉTODO · este run corre dirigido por el método
    method_adjust: Optional[str] = None  # PIEZA MÉTODO · ajuste del dueño SOLO para este run
    turn_text: Optional[str] = None      # [ticket 22] texto CRUDO del turno del usuario para el
                                         # registro del hilo (prompt puede venir envuelto en un
                                         # edit-prompt); el transcript guarda lo que el humano dijo
    # [FIX-P9 · deuda #1 de FIX-P7] TOOLS DEL CLIENTE — schemas OpenAI-function que declara la
    # SUPERFICIE y ejecuta la SUPERFICIE (pintar las opciones del turno). Se le declaran al
    # modelo junto al belt; cuando las pide, la call vuelve al cliente (`client_calls` en la
    # respuesta y evento `client_call` en el SSE) y el motor NO ejecuta nada.
    #
    # POR QUÉ ESTO NO ABRE UNA PUERTA: una tool de cliente no llega jamás al registry ni al
    # gate — es un mensaje de vuelta a la interfaz, no una capacidad. Y si su nombre choca
    # con una del belt, gana el belt y la del cliente se descarta (assembler): sin esa regla,
    # un `send_email` declarado desde afuera podría TAPAR al real y el gate no vería la
    # diferencia. Un techo duro además, porque el schema viaja al prompt y se paga en tokens.
    client_tools: Optional[list[dict[str, Any]]] = None


class ApproveHeldRequest(BaseModel):
    """APPROVE-BY-HTTP: el dueño aprueba (ok=True → se EJECUTA) o rechaza (ok=False) una
    acción de alta consecuencia (send/money) que el gate retuvo durante el run."""
    approval_id: str
    ok: bool


class WorkspaceBrainRequest(BaseModel):
    """[Gate 4 · Fase 3 · 3.2 · ley 2] UN paso del harness de un workspace heredado.

    El stack importado conserva su loop y ejecuta SUS tools; lo único que le cortamos
    es la línea que le preguntaba al modelo. Acá entra el estado de ese loop (mensajes
    en protocolo OpenAI + los schemas de sus funciones) y sale la jugada del modelo.

    LO QUE NO ESTÁ EN ESTE BODY, Y ES EL PUNTO: `provider`. El cerebro lo elige Aleph, no
    el harness. Un harness que pudiera pedir su proveedor no estaría re-cableado: seguiría
    enchufado, con otro cable.

    [LEY 15 · MODO RAW] `model` SÍ está, y no contradice lo anterior: **no es un proveedor,
    es el `picker_id` de una fila del SELECTOR DE LA CASA** — o sea la elección que el
    usuario ya hizo en su propia superficie, no una que el harness inventa. Se ignora si
    viene un agente (con agente manda la receta, ley 15.d: el agente es aditivo), y sin él
    es lo que hace posible hablar con un modelo en seco. Ausente, se usa lo que el usuario
    tenga elegido."""
    recipe: Optional[dict[str, Any]] = None
    puppet_id: Optional[str] = None
    model: Optional[str] = None      # picker_id del selector — JAMÁS un base_url del harness
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    chat_id: Optional[str] = None
    workspace: str = ""              # quién pide (informativo: va al evento del espacio)
    turn: int = 1
    messages: list[Any]
    tools: Optional[list[Any]] = None
    # [B0-2] El `tool_choice` del harness, que el motor pisaba con `"auto"`. Acá SÍ se
    # honra —a diferencia de `provider`— porque no elige cerebro: dice si ESTE paso de SU
    # loop admite una respuesta de texto. Eso es del dueño del loop, y el dueño es él.
    tool_choice: Optional[Any] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    lang: Optional[str] = None  # existing aleph-lang UI fallback; message/request wins


class WorkspaceBrainOpenAIRequest(BaseModel):
    """[Gate 4 · F3-ciencia] EL CUERPO DE UN HARNESS QUE HABLA OpenAI.

    Un stack heredado con capa de proveedores propia no sabe pedir por la puerta de la
    casa: sabe pedir `/v1/chat/completions`. Éste es ese cuerpo, y el borde de dialecto
    lo traduce al MISMO paso que `brain/complete` — no a otro camino.

    **`model` ENTRA Y SE IGNORA, y ése es el punto.** La ley de la casa (una casa, un
    agente) dice que el harness no elige cerebro: el modelo sale de la receta, por
    `resolve_recipe_model`. Se acepta el campo porque el cliente lo manda siempre y
    rechazarlo sería romper su cliente por nada; lo que vuelve en la respuesta es el
    `model_final` honesto, o sea el que reportó el proveedor. Un harness que pudiera
    elegir su modelo acá no estaría re-cableado: seguiría enchufado, con otro cable.

    Lo que NO viene en el cuerpo —receta, dueño, espacio, turno— viaja en cabeceras
    `X-Aleph-*`, porque el cliente ajeno no tiene dónde ponerlo en un body de OpenAI y
    su config SÍ le permite mandar cabeceras sin tocarle una línea de código."""
    model: Optional[str] = None      # se ignora a propósito (ver arriba)
    messages: list[Any]
    tools: Optional[list[Any]] = None
    tool_choice: Optional[Any] = None   # [B0-2] se honra — ver el cuerpo de la casa
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    lang: Optional[str] = None


class WorkspaceBrainOpenAIEmbeddingsRequest(BaseModel):
    """EL CUERPO DE `/v1/embeddings` DE OpenAI, para el mismo borde de dialecto.

    Hermano del de arriba y con la misma regla: **`model` entra y se ignora**. El motor de
    embeddings lo elige la casa (`rag_index.pick_embed_provider`), igual que el cerebro lo
    elige la receta; lo que vuelve en la respuesta es el modelo REAL con el que se embebió,
    porque un corpus indexado queda sellado a ese modelo y mentirlo acá es drift silencioso
    en la recuperación de mañana.

    `dimensions` y `encoding_format` SÍ se honran o se rechazan con causa, nunca se ignoran:
    devolver vectores de otro largo, o en otro formato, del que el cliente pidió es
    exactamente la clase de divergencia muda que este borde existe para no tener."""
    input: Any                              # str | list[str]
    model: Optional[str] = None             # se ignora a propósito (ver arriba)
    encoding_format: Optional[str] = "float"
    dimensions: Optional[int] = None
    user: Optional[str] = None


#: [Gate 4 · Fase 3 · 3.7 · ley 6 enmendada] EL REGISTRO DE WORKSPACES DE LA CASA.
#:
#: Una fila por stack heredado que viaja con esta instalación. `dist` es la ruta —relativa
#: al `resource_root()`, así que funciona igual en dev y en el congelado— donde vive su
#: frontend construido: que exista su `index.html` ES `installed`, y `installed` es lo que
#: decide si el workspace APARECE. `url_env`/`url_default` son de dónde atiende su proceso,
#: y que atienda es `running` — otro hecho, que decide qué se ve al ENTRAR.
#:
#: [Gate 4 · F3-ciencia] **EL PRIMER INQUILINO DE VERDAD.** La cosecha dejó el registro
#: vacío y esperando; lo estrena Ciencia (OpenScience, `third_party/openscience/`). Se
#: llena la fila y nada más: elegibilidad, tipos, censo de fuentes y la puerta al cerebro
#: ya estaban cableados y data-driven — era exactamente el punto de dejarlos así.
#:
#: `dist` apunta al build de su frontend (`vite build` en `frontend/workspace`), que es lo
#: que su propio `backend/cli/script/build.ts` embebe en el binario. **No se commitea**: el
#: `.gitignore` del proyecto de origen ignora `dist`, igual que pasaba con el stack
#: anterior. Es artefacto de build y viaja por el spec del sidecar, no por git — o sea que
#: `installed` es falso en un checkout limpio y verdadero en la `.app`, que es justo lo que
#: ese campo quiere decir.
_WORKSPACE_STACKS: dict[str, dict] = {
    "legal": {
        "label": "Legal",
        "icon": "§",
        "stack": "Aleph Legal",
        "dist": "third_party/dochaus/apps/web/dist",
        "url_env": "ALEPH_WORKSPACE_LEGAL_URL",
        "url_default": "http://127.0.0.1:0",
        # La SEÑAL DE SALUD, y por qué NO es `/`. Este pack son TRES procesos —motor,
        # ingest y web— y en su puerto público **ninguna ruta discrimina**: el server de la
        # piel es catch-all de SPA y devuelve el `index.html` con 200 a todo. Medido el
        # 2026-08-11 con el stack sano: `/`, `/health`, `/global/health` y `/api/health`
        # devolvieron las cuatro 200 con HTML.
        #
        # `/` NO mentía en el ARRANQUE —`start.sh:169-189` no levanta el web hasta que el
        # motor pasó `/global/health`, la config pasó `/global/config` y el ingest contestó
        # `/matters`— pero era CIEGO a la degradación posterior. Medido congelando el motor
        # con SIGSTOP (vivo, sin atender: el supervisor de `start.sh:204-227` no lo mata
        # porque no está muerto):
        #   GET /                       → 200 en 0,0 s   ⇒ `running: true`  (mentira)
        #   GET /opencode/global/health → 000, timeout   ⇒ `running: false` (la verdad)
        #
        # Y no hace falta escribirle nada al stack: su propio server web ya PROXEA
        # `/opencode/*` al motor y `/ingest/*` al servicio de documentos
        # (`third_party/dochaus/apps/web/script/serve-dist.ts:27-34`), así que la puerta
        # honesta ya existía y sólo había que declararla. Por eso acá NO se usa el patrón
        # del `/.aleph/health` que publica nuestro lanzador de Diseño: ese patrón es para el
        # stack que no expone ninguna, y éste sí expone.
        "health": "/opencode/global/health",
        "bin": ["third_party/dochaus/start.sh"],
        "serve_args": [],
        "config_env": "DOCHAUS_CONFIG_DIR",
        "data_env": "WORKSPACE_ROOT",
        # ── [F1-CONECTORES] LA CREDENCIAL DEL USUARIO, AL LUGAR DONDE ESTE STACK YA LEE ──
        # `$WORKSPACE_ROOT/.preferences/preferences.json`, releído por LLAMADA
        # (`dochaus/lib/research.ts:78-84`), así que una escritura del `enter` aplica en el
        # turno siguiente sin reiniciar el motor. Es el destino más barato de los seis: JSON
        # plano, sin cifrado, sin caché y sin esquema que aborte.
        #
        # Y de paso se le arregla el modo: su propio escritor lo deja en 0644
        # (`services/ingest/src/preferences.ts:66`, `writeFileSync` sin `mode`) con la key de
        # Exa adentro. El escritor de la casa usa `_escribir_json_0600`.
        "cred_format": "preferences_json",
        # `exa` es el slug del vault y `EXA_API_KEY` su canónica; las dos las declara
        # `catalog/connectors/env-alias.json`, no esta fila.
        "cred_map": [{"vault": "exa", "campo": "searchApiKey"}],
        # EL ALMACÉN DEL MOTOR, ADENTRO DE LA INSTALACIÓN. Su motor resuelve dirs con
        # `xdg-basedir` (`packages/core/src/global.ts:10-13`), y sin estas tres variables
        # cae en el home del usuario: medido, las sesiones de Legal terminaban en
        # `~/.local/share/opencode/opencode-local.db` **compartiendo store con Oficina**
        # (32 sesiones suyas en el `opencode.db` de al lado) y el catálogo de models.dev en
        # `~/.cache/opencode/`. Eso no es por workspace ni por instalación: un
        # `ALEPH_DATA_DIR` nuevo heredaba lo de antes, y nada de eso se borra al desinstalar.
        # Medido que aísla del todo: con los `XDG_*` puestos, el motor escribe su
        # `opencode-local.db` bajo el dir declarado y no toca el del home.
        "env": {
            "XDG_DATA_HOME": "{raiz}/motor/data",
            "XDG_CACHE_HOME": "{raiz}/motor/cache",
            "XDG_STATE_HOME": "{raiz}/motor/state",
        },
        "env_dirs": ["XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"],
        "config_file": "opencode.json",
        # [LEY 12] EL MOTOR QUE CORRE ADENTRO, declarado. No es cosmética: es lo que
        # habilita `pack.exclusividad_del_cerebro`, que pregunta por una ruta de opencode
        # (`/opencode/config/providers`) y por lo tanto sólo vale donde hay un opencode.
        # Legal lo tiene detrás de su propio web, que ya proxea `/opencode/*` —la misma
        # costura que su `health` usa desde F6— así que no hace falta escribirle nada.
        # MEDIDO 2026-08-14 con el pack vivo: 200, `connected=['aleph']`, sin cabecera.
        "engine": "opencode",
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # [LEY 12] «un modelo: Cerebro de Aleph», hecho imposible de violar y no comprobado
        # después. Con la lista negra que traía el stack (`disabled_providers: ["opencode"]`)
        # el motor seguía ofreciendo 185 proveedores y 6.273 modelos bajados de models.dev.
        # Ver `pack._exclusividad_del_cerebro` para la medición y para lo que NO cierra.
        # Ciencia y Oficina pueden adoptarlo con esta misma línea; no se las prende acá
        # porque su cierre medido es de ellas, no de esta tanda.
        "brain_exclusivo": True,
        "plugin": "platform/workspaces/plugins/dochaus.js",
        # LA CAPA DE OFICIO DEL STACK, ENLAZADA DONDE SU MOTOR LA BUSCA.
        # `nombre en el dir de datos → ruta en los recursos`. El motor suma a su lista de
        # dirs de config cada `.opencode` que encuentra SUBIENDO desde el directorio del
        # turno (`config/paths.ts:26-31`), y los matters viven en `<data>/<matter>`: un
        # `.opencode` en `<data>` cae exactamente un nivel arriba de todos ellos.
        # Sin esto `<recursos>/third_party/dochaus/dochaus` no está en ninguna lista, y el
        # motor arranca con 14 tools genéricas y CERO agentes.
        #
        # SE ENLAZAN LAS CUATRO CARPETAS DE CONTENIDO, NO EL DIRECTORIO: `.opencode` tiene
        # que ser NUESTRO porque el motor escribe adentro de sus config dirs (`.gitignore`,
        # `npm install`, y una reescritura del `opencode.json`). Medido en esta obra; el
        # porqué completo está en `pack.preparar_config_del_motor`.
        # `plugin/` no va: el pack ya lo declara por ruta absoluta. `opencode.json` tampoco:
        # su contenido lo escribe `script/aleph-legal-config.ts` sobre la config del pack.
        "engine_config_links": {
            ".opencode/agent": "third_party/dochaus/dochaus/agent",
            ".opencode/skill": "third_party/dochaus/dochaus/skill",
            ".opencode/command": "third_party/dochaus/dochaus/command",
            ".opencode/tool": "third_party/dochaus/dochaus/tool",
        },
    },
    "educacion": {
        "label": "Educación",
        "icon": "✎",
        "stack": "Aleph Educación",
        # El standalone de Next se construye desde el stack importado. Que exista es el
        # hecho de instalación; que su grupo atienda lo decide `running`.
        "dist": "third_party/deeptutor/web/.next/standalone",
        "install_marker": "server.js",
        "url_env": "ALEPH_WORKSPACE_EDUCACION_URL",
        "url_default": "http://127.0.0.1:0",
        # La SEÑAL DE SALUD, y por qué NO puede ser `/`. Este pack son DOS procesos —el
        # Next y el API de Python— y `/` lo contesta el Next, que liga su puerto ANTES de
        # que el API termine de arrancar. Medido el 2026-08-11 sobre la `.app` instalada,
        # con el API muriéndose en el import (`ModuleNotFoundError: pydantic_settings`):
        #   t+3 s   GET /  200   → el registro decía running: true
        #   t+6 s   GET /  000   → el grupo entero ya estaba muerto
        # O sea: `/enter` devolvía 200 en 0,75 s y el usuario entraba a un workspace que
        # moría cuatro segundos después, sin un solo aviso. `/api/health` SÍ discrimina —el
        # proxy de Next lo reenvía al API— y en esa misma corrida devolvía **500** con el
        # API caído. Es la misma lección que la fila de Ciencia dejó escrita más abajo: la
        # señal tiene que tocar el órgano que hace el trabajo, no la piel que lo envuelve.
        #
        # El entry point reducido de Aleph no publica `/api/health`: esa ruta era una
        # suposición heredada y Next la reenviaba correctamente a un 404. El resultado
        # medido en la .app fue dos esperas completas de 25 s y el grupo terminado aunque
        # Uvicorn ya hubiera montado sus 25 routers. `system/status` es una ruta real del
        # API, usada por la propia UI, y por el proxy obliga a que estén vivos Next + Python.
        "health": "/api/v1/system/status",
        # Un único launcher (API Python + Next) corre como grupo del dueño. `exit` mata
        # el grupo entero, incluidas sus hijas, por la misma lápida F4 de los demás packs.
        "bin": ["platform/workspaces/launchers/deeptutor"],
        "serve_args": [],
        "port_arg": False,
        "config_env": "DEEPTUTOR_HOME",
        "data_env": "DEEPTUTOR_DATA_DIR",
        "config_file": "model_catalog.json",
        "config_format": "deeptutor",
        # ── [F1-CONECTORES] EL DESTINO MÁS PARECIDO AL VAULT DE LOS SEIS ────────────────
        # `<runtime>/data/system/user-secrets/<owner>/private/mcp/<server>.json`
        # (`multi_user/paths.py:220-238` + `services/mcp/secrets.py:38-64`): ya está indexado
        # POR DUEÑO, ya es 0600 con su dir 0700, y su lector resuelve `${secret:<s>/<f>}`
        # desde disco EN CADA referencia (`secrets.py:113`) — no hay caché que invalidar.
        # No es `model_catalog.json`: ése es la superficie de MODELOS, otra cosa.
        #
        # ⚠️ EL DUEÑO ES DEL ESPACIO DE IDS DE EDUCACIÓN, NO EL `user_id` DE ALEPH
        # (`LOCAL_ADMIN_ID = "local-admin"`, `multi_user/models.py:82`). Pasarle el nuestro
        # escribiría en un dir que su lector no mira. Queda declarado acá y medido en el
        # primer `enter` real: hasta entonces es la suposición honesta, no un hecho.
        "cred_owner": "local-admin",
        "cred_format": "mcp_secrets",
        # Los nombres de campo salen de su catálogo curado de fábrica
        # (`services/mcp/catalog/vendor/curated.json`, 45 entradas, 21 con campo de secreto).
        # Van tres, no las 21: el mapa completo es decisión del escritorio y viaja con la
        # reclasificación de los 99, que no es de esta obra.
        "cred_map": [
            {"vault": "exa", "server": "exa", "campo": "api_key"},
            {"vault": "github", "server": "github", "campo": "token"},
            {"vault": "huggingface", "server": "huggingface", "campo": "token"},
        ],
        "backend_port_offset": 1,
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
    },
    "ciencia": {
        "label": "Ciencia",
        "icon": "⌬",          # el hexágono del anillo: oficio, no marca ajena
        "stack": "OpenScience",
        "dist": "third_party/openscience/frontend/workspace/dist",
        "url_env": "ALEPH_WORKSPACE_CIENCIA_URL",
        "url_default": "http://127.0.0.1:4096",
        # La SEÑAL DE SALUD del stack, y por qué no alcanza con pedirle `/` — ver el
        # comentario de `running` en `workspaces_list()`. Medido en este stack:
        #   corriendo de verdad → GET /  404   ·  GET /global/health  200 {"healthy":true}
        #   sólo su dist servido → GET /  200  ·  GET /global/health  404
        # O sea que `/` contesta al revés en las dos direcciones. Cada stack declara la
        # suya; si un stack no declara ninguna, se cae a `/` y `running` vale lo que valía.
        "health": "/global/health",

        # ── [Gate 4 · Fase 4 · O1] LO QUE EL PACK NECESITA PARA LEVANTARLO SOLO ────────
        # `bin` son las rutas candidatas del binario compilado, EN ORDEN: la del `.app`
        # primero, la del árbol de desarrollo después. Se declaran las dos para que la
        # misma línea sirva congelada y en dev (`platform/workspaces/pack.py:binario_de`).
        #
        # El binario se produce con `bun run build` en `backend/cli` y **embebe su propia
        # UI y sus 294 skills** — medido el 2026-08-09 sobre el compilado: corriendo solo,
        # sin `dist` al lado y con su config aislada, `/` devuelve 200 text/html y `/skill`
        # 174.818 b de JSON. Por eso el `dist` deja de ser necesario el día que el binario
        # viaje: son 29,1 MiB de la misma UI, dos veces.
        "bin": [
            "third_party/openscience/bin/openscience",
            "third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience",
        ],
        "serve_args": ["serve"],

        # ── EL KERNEL DE PYTHON SE DECLARA, NO SE HEREDA ────────────────────────────────
        # Su notebook arranca el intérprete por PATH
        # (`backend/cli/src/tool/notebook.ts:202`: candidatos `python3`, `python`), y una
        # `.app` lanzada desde el Finder NO hereda el PATH del shell: ahí `python3` es
        # `/usr/bin/python3`, sin matplotlib. El tiro parabólico no producía su PNG por eso.
        # `pack.py:preparar_interprete` deja un shim en el dir que ya se antepone al PATH
        # del pack — cero líneas del motor del stack.
        "python_kernel": True,
        "stack_dir": "third_party/openscience",
        # Sus dos overrides de entorno, que el propio stack respeta sin tocarle una línea
        # (`backend/cli/src/global/index.ts:53,59`). Con esto sus datos dejan de vivir en
        # `~/.openscience/` y pasan al dir de datos del usuario que Aleph ya administra.
        "config_env": "OPENSCIENCE_CONFIG_DIR",
        "data_env": "OPENSCIENCE_DATA_DIR",
        "config_file": "openscience.json",
        # ── [F1-CONECTORES] EL ÚNICO DE LOS SEIS QUE NO RECIBE UN ARCHIVO ────────────────
        # Su store va cifrado con AES-256-GCM y la llave (`credentials.key`, 32 bytes) es
        # local a la máquina y al dir de datos; `SecretFile.key` se niega a reemplazar una
        # existente. La casa no tiene esa llave, así que no le escribe el store: se lo PIDE
        # por `PUT /settings/credentials/:id` y el stack cifra. Medido contra el binario que
        # ship-ea: el PUT acepta un curl pelado → 200, el valor NO queda en claro en disco
        # (0 coincidencias), `applyCredentialEnv()` corre en el save y en el delete EN VIVO,
        # y el store sobrevive al reinicio y hasta a un cambio de binario.
        #
        # ⚠️ UN SERVICIO POR LLAMADA (la ruta es `/:id`; varios CAMPOS en un PUT sí), y el
        # nombre de campo tiene que ser EXACTO: uno que su spec no conozca devuelve 200 y se
        # descarta en silencio (`credentials.ts:512`). Los 12 ids y sus campos los declara su
        # propio `CATALOG` (`credentials.ts:61-166`).
        #
        # `env_del_stack` es lo que su `mapServiceEnv` DERIVA del id (`credentials.ts:239-273`)
        # — es su tabla, no la del catálogo de Aleph. Se declara para poder CRUZARLA con
        # `env-alias.json`: la verificación por sonda sólo afirma sobre un nombre que está en
        # las dos, y lo que aparece en una sola va a `sin_verificar`.
        "cred_format": "http_credentials",
        "cred_map": [
            {"vault": "github", "servicio": "github", "campo": "token",
             "env_del_stack": ["GITHUB_TOKEN", "GH_TOKEN"]},
            {"vault": "huggingface", "servicio": "huggingface", "campo": "api_key",
             "env_del_stack": ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"]},
        ],
        # Dónde le enchufa Aleph su cerebro. Se declara acá y no en el código del pack
        # porque es lo único de esta fila que depende del DIALECTO del stack, no del stack.
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # ── EL CEREBRO ES ÚNICO, TAMBIÉN ACÁ (Ley 12) ─────────────────────────────────
        # Faltaba, y el costo se vio en pantalla. Sin esta clave el pack escribe el
        # proveedor `aleph` pero NO la lista blanca, así que el motor sigue ofreciendo los
        # suyos: medido contra el stack vivo, `GET /config/providers` devolvía
        # `['huggingface', 'github-copilot', 'github-copilot-enterprise', 'aleph']` — y el
        # picker de la sesión del dueño tenía elegido **«Claude Code»**, no «Cerebro de
        # Aleph». Un turno así NO CRUZA el borde de la casa: no lo mide el ledger, no le
        # aplica el presupuesto, no pasa por el streaming, y la pantalla no tiene por qué
        # parecer distinta después de arreglar el borde. Ésa fue exactamente la confusión
        # que costó media tanda: el borde streameaba y el turno iba por otro lado.
        #
        # `_exclusividad_del_cerebro` inyecta `enabled_providers` en el cuerpo que se
        # escribe en `config/openscience.json` (`pack.py:1895`) — el archivo que el motor
        # ABRE, no el muerto que le costó el efecto a Diseño.
        "brain_exclusivo": True,
        # [O2] EL PLUGIN DE LA CASA para este stack. Vive en NUESTRO árbol y el stack lo
        # carga por `file://` desde su propia config: es el que le pone `X-Aleph-Space` a
        # cada paso del harness y el que cruza al puente lo que el workspace produjo.
        "plugin": "platform/workspaces/plugins/openscience.js",
    },
    # [Gate 4 · F6-diseño] Open CoDesign es un workspace Electron, no un servidor web.
    # Su lanzador propio abre la ventana nativa y publica sólo una señal loopback para que
    # el ciclo F4 mida vida y sea dueño del proceso; el oficio sigue siendo su UI nativa.
    "diseno": {
        "label": "Diseño",
        "icon": "✦",
        "stack": "Open CoDesign",
        "dist": "third_party/codesign/apps/desktop/out/renderer",
        "url_env": "ALEPH_WORKSPACE_DISENO_URL",
        "url_default": "http://127.0.0.1:4097",
        "health": "/.aleph/health",
        "bin": ["third_party/codesign/bin/aleph-codesign"],
        "serve_args": [],
        "config_env": "XDG_CONFIG_HOME",
        "data_env": "ALEPH_CODESIGN_DATA_DIR",
        # ── [F2 · D] LA MITAD DE DATOS DEL CERCO, QUE FALTABA ────────────────────────────
        # `config_env` ya cerca la mitad de CONFIG (`XDG_CONFIG_HOME` → el dir de config del
        # pack, que es de donde `bin/aleph-codesign` lee para escribir su `config.toml`). La
        # de DATOS no estaba cercada, y por ahí entra lo de otro inquilino: el importador de
        # opencode resuelve su dir con la convención de `xdg-basedir` —
        # `xdgData = XDG_DATA_HOME || ~/.local/share` — y termina leyendo
        # `~/.local/share/opencode/auth.json`, que es GLOBAL A LA MÁQUINA y sobrevive a un
        # `ALEPH_DATA_DIR` nuevo.
        #
        # ⚠️ EL ENCUADRE, MEDIDO EN FASE 0 Y CONFIRMADO ACÁ: Diseño no GUARDA ahí, IMPORTA de
        # ahí. Se traga lo que otro inquilino dejó en el home. Y lo que se tragaría son
        # credenciales de MODELO (los cuatro importadores son de CLIs de modelo, F1), así que
        # el daño primario es de LEY 12 y está anotado en `DEUDAS-REVISION.md`. Cercar el dir
        # no arregla esa deuda: le saca la materia prima.
        #
        # QUE ESTA LÍNEA ALCANCE NO ES SUPOSICIÓN: el lector honra la variable explícitamente
        # (`imports/opencode-config.ts:136-137`, `const xdgData = env['XDG_DATA_HOME']; if
        # (…) return join(xdgData, 'opencode')`). Es la misma forma que la fila de Legal ya
        # usa para sus tres XDG.
        #
        # Hoy `~/.local/share/opencode/auth.json` NO existe en esta máquina: la puerta está
        # abierta y no hay nada sobre la mesa. Se cierra ahora, antes de que aparezca.
        "env": {"XDG_DATA_HOME": "{raiz}/motor/data"},
        # [Diseño · obra 1] LA CONFIG DE ESTE PACK LA ESCRIBE SU LANZADOR, NO `pack.py`.
        # El motor lee `$XDG_CONFIG_HOME/open-codesign/config.toml` (TOML `version = 3`) y
        # lo produce `bin/aleph-codesign` antes de levantar Electron, porque depende de lo
        # que sólo el lanzador sabe. Antes esta fila declaraba `config_file: "config.toml"`
        # y `pack.escribir_config` dejaba al lado un JSON en dialecto de opencode que
        # NADIE ABRE — medido por `atime` contra un `enter` limpio: `atime == mtime`, o sea
        # que su única lectura en toda su vida fue la escritura. Ver el comentario de
        # `config_format == "launcher"` en `pack.py` para lo que eso rompía.
        "config_format": "launcher",
        # El launcher Electron lee el puntero genérico `ALEPH_PACK_CONFIG` para
        # conocer la sesión y el proyecto, aunque Diseño no cargue un plugin Aleph.
        # DESDE LA OBRA 1 ES ADEMÁS EL ÚNICO CANAL de la casa hacia su motor: lo que este
        # registro quiera declararle a Diseño viaja por el puntero y lo traduce el
        # lanzador. `cerebro_label` es la primera declaración que cruza, y es la que deja
        # el canal probado de punta a punta.
        "pack_config": True,
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # ── [F1-CONECTORES] LA CREDENCIAL VIAJA POR EL PUNTERO, NO POR UN ARCHIVO NUESTRO ─
        # Por lo mismo que su config: el `config.toml` lo produce `bin/aleph-codesign` y dos
        # escritores para un archivo es una carrera con ganador fijo. El puntero
        # `aleph-pack.json` ya es 0600 y ya es el único canal de la casa a este motor.
        #
        # ⚠️ EL VALOR VA CON PREFIJO `plain:`. `decryptSecret` acepta tres formas y sólo tres
        # (`apps/desktop/src/main/keychain.ts:29-41`): `safe:<base64>`, `plain:<texto>`, o
        # crudo — y el crudo cae en la rama legacy de safeStorage y LEVANTA. `safe:` lo
        # produce el Keychain del usuario, del otro lado de Electron, así que la casa no
        # puede fabricarlo. El prefijo es parte del contrato del stack, no un downgrade.
        "cred_format": "puntero_launcher",
        # ── SU PROCESO ES UNO SOLO POR MÁQUINA ──────────────────────────────────────────
        # Diseño es una app Electron con candado de instancia única: la segunda le pasa el
        # trabajo a la primera y se va con `exit 0`. Sin esta declaración, `pack._clave`
        # mete el `user_id` en la clave, elige OTRO puerto, y el dueño presta un proceso
        # nuevo que no puede vivir. MEDIDO contra la .app INSTALADA: misma clave → 200 en
        # 16-29 ms; otra clave → 503 «murió al arrancar (exit 0)» con el pack VIVO.
        # Y el aislamiento por usuario que la clave prometía era ilusorio: su config vive
        # en `<ws>/config/aleph-pack.json`, que es por workspace.
        "proceso_unico_por_maquina": True,
        # ── DÓNDE VIVE EL PEDIDO HUMANO DENTRO DE LA PLANTILLA DE SU HARNESS ────────────
        # [convergencia · superficie 1] El loop de Diseño no le manda al modelo lo que el
        # usuario escribió: le manda una plantilla con el pedido adentro. Sin esta
        # declaración el hilo de la casa guardaba los 1.434 caracteres de
        # «Workspace context: - Current design title… <untrusted_scanned_content>…» en vez
        # de «Hacé un banner de anuncio con un botón».
        #
        # SE DECLARA, NO SE ADIVINA — es la regla de la casa. Son dos literales de SU
        # plantilla; el día que cambie, el recorte no encuentra la marca y el texto va
        # entero (degrada a lo de hoy, nunca a un recorte inventado). Y `desde` hace de
        # segunda llave: sus cinco llamadas auxiliares —el extractor de preferencias, el
        # bautizador, el escritor de memoria, el del brief— **no la traen**, así que no se
        # anotan aunque el filtro por catálogo todavía no tenga con qué comparar.
        "hilo_pedido": {"desde": "User request:",
                        "hasta": "Use the following local context"},
        # ── [F1 · CIERRE DE DISEÑO, CON DATO] SUS SEIS CANALES SON TODOS DE MODELO ───────
        # El censo le cuenta 4 importadores + 1 con API key + 1 OAuth. Medidos los seis en
        # este árbol, uno por uno, y ninguno es de conector:
        #
        #   · los 4 importadores  = configs de CLIs de MODELO: `imports/claude-code-config.ts`,
        #     `codex-config.ts`, `gemini-cli-config.ts`, `opencode-config.ts`. Devuelven
        #     `{provider, apiKey}` — un proveedor de LLM y su llave.
        #   · el OAuth            = `packages/providers/src/codex/oauth.ts:4-5`,
        #     `AUTH_BASE = https://auth.openai.com` con CLIENT_ID horneado: el sign-in de
        #     ChatGPT. Proveedor de modelo.
        #   · la API key          = la de esos mismos proveedores. `BUILTIN_PROVIDERS`
        #     (`packages/shared/src/config.ts:235`) tiene TRES y los tres son de modelo:
        #     anthropic, openai, openrouter.
        #
        # Cero conectores de tercero: `figma` aparece UNA vez en todo el árbol y es una
        # etiqueta de origen de un design token (`packages/shared/src/design-token.ts:17`),
        # no un servicio con API ni con credencial. Así que LEY 12 cubre el 100 % de la
        # superficie de credenciales de Diseño y no hay nada que traer del vault.
        #
        # LOS 4 IMPORTADORES PIDEN UN CLICK, NO UNA LLAVE: son
        # `ipcMain.handle("config:v1:import-*-config")` (`onboarding/register.ts:213-266`),
        # expuestos al renderer por el preload (`preload/index.ts:608-614`). No corren solos
        # y no piden pegar nada — leen lo que el usuario ya tiene en su máquina.
        #
        # ⚠️ Y AHÍ HAY UN HALLAZGO QUE NO ES DE ESTA OBRA Y QUEDA ANOTADO: esos cuatro
        # ESCRIBEN. `onboarding/external-imports.ts` llama a `writeConfig` y pone
        # `activeProvider: imported.provider.id` (`:167`, `:210`), o sea que un click mueve el
        # cerebro al proveedor importado. Y esta fila no declara `engine` ni `brain_exclusivo`
        # ni `brain_lectura`, así que **ninguna de las dos exclusividades corre sobre Diseño**
        # (`exclusividad_del_cerebro` pide `engine == "opencode"`;
        # `exclusividad_por_terna` pide `brain_lectura == "settings_llm"`). Es deuda de LEY 12,
        # no de conectores, y su arreglo va por el puntero —no por `brain_exclusivo`, que
        # escribiría en el `config.toml` que este pack no usa—. Queda `[no medible]` sin
        # correr Electron si la pantalla llega a mostrar esos botones bajo el pack.
        #
        # ⚠️ EL MAPA VA VACÍO, Y NO ES UN OLVIDO: HOY NO HAY DESTINO. Medido en este árbol —
        # el único almacén de credenciales de codesign es `config.secrets[<providerId>]`
        # (`apps/desktop/src/main/auth-bridge.ts:91`), y para que se lea, ese id tiene que
        # existir como bloque `[providers.<id>]`, que en codesign son proveedores de LLM
        # (`provider-settings.ts:72,78,186,239`). Su `main/` no tiene ninguna superficie MCP
        # ni de conector de tercero (grep = 0).
        #
        # O sea que meter acá la llave de un conector haría una de dos cosas, las dos malas:
        # nada (si no hay bloque de provider que la referencie) o un SEGUNDO CEREBRO — que es
        # exactamente lo que `exclusividad_del_cerebro` apaga por LEY 12. La rama de formato
        # queda escrita y probada por la vara con una fila sintética, para el día que Diseño
        # tenga una superficie de conectores; el mapa se llena ese día, no antes.
        "cred_map": [],
    },
    # [Gate 4 · F6-FINANZAS] **EL SEGUNDO INQUILINO.** Vibe-Trading (HKUDS, MIT), importado
    # entero en `third_party/vibetrading/`. Decisión del dueño: **Opción B** — los 8
    # conectores con orden real entran VIVOS con la máquina de mandato del stack intacta
    # (LEY 0: ese órgano es del oficio y para su dominio es mejor que Ó11). Ó11 sigue
    # gobernando el resto de la casa.
    "finanzas": {
        "label": "Finanzas",
        "icon": "◪",          # el bloque partido: cartera y contraparte, no marca ajena
        "stack": "Vibe-Trading",
        "dist": "third_party/vibetrading/frontend/dist",
        "url_env": "ALEPH_WORKSPACE_FINANZAS_URL",
        "url_default": "http://127.0.0.1:8907",
        # La SEÑAL DE SALUD, medida en este stack (2026-08-09, sobre el árbol operado):
        #   corriendo desde el árbol (con dist) → GET /  200 text/html · GET /health  200
        #   corriendo desde el wheel (sin dist) → GET /  404          · GET /health  200
        # O sea que `/` depende de si el dist está al lado y `/health` no: es la única
        # señal que dice «el server atiende» en las dos formas de correrlo.
        "health": "/health",

        # ── LO QUE EL PACK NECESITA PARA LEVANTARLO SOLO ──────────────────────────────
        # No es un binario compilado como el de Ciencia: es un backend Python. El `bin` es
        # un LANZADOR que vive en el árbol de Aleph y que exporta `PYTHONPATH` al árbol
        # importado antes de exec-utar el console script del venv del stack — sin eso,
        # `api_server.py:332` busca el `frontend/dist` dentro de site-packages y no lo
        # encuentra (medido: `GET /` 404). El venv se provisiona en la instalación y está
        # en el `.gitignore`, igual que el `dist`: por eso `installed` es falso en un
        # checkout limpio y verdadero en la `.app`, que es lo que ese campo quiere decir.
        "bin": [
            "platform/workspaces/launchers/finanzas-serve",
        ],
        "serve_args": ["serve"],
        # Este stack tiene UNA sola raíz de runtime para config y datos
        # (`agent/src/config/paths.py:11`), así que las dos claves declaran la MISMA
        # variable a propósito: el `env` del spec colapsa a una y el `.env` se escribe en
        # el dir de datos (ver `pack._escribir_config_dotenv`).
        "config_env": "VIBE_TRADING_HOME",
        "data_env": "VIBE_TRADING_HOME",
        "config_file": ".env",
        # [F6] El dialecto de config de este stack no es el JSON de Ciencia: son cuatro
        # variables de entorno en un `.env`. El ciclo del pack NO cambia; sólo el escritor.
        "config_format": "dotenv",
        # ── [F1-CONECTORES] EL PRECEDENTE DE ESTA OBRA, AHORA TAMBIÉN PARA CREDENCIALES ───
        # Las líneas se AGREGAN al `.env` que `_escribir_config_dotenv` acaba de escribir —
        # ese escritor reemplaza el archivo entero en cada `enter`, así que el orden importa
        # y está declarado en `pack.py`: primero el cerebro, después las credenciales.
        #
        # ⚠️ Y CADA CLAVE VA AL `case` DE `platform/workspaces/launchers/finanzas-serve` EN
        # EL MISMO COMMIT. El porqué está medido y escrito en UN solo lugar —la nota de
        # `_escribir_config_dotenv` en `pack.py`, que la sesión de Finanzas dejó el
        # 2026-08-17— y no se repite acá: su `case` es lista cerrada, así que una clave nueva
        # nace con la sombra puesta y sin señal.
        "cred_format": "dotenv_extra",
        "cred_map": [{"vault": "alphavantage", "clave": "ALPHA_VANTAGE_API_KEY"}],
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # [LEY 12] EXCLUSIVIDAD, EN LA FORMA QUE ESTE STACK TIENE. No hay lista de
        # proveedores que blanquear como en los dos motores opencode: hay UNA configuración
        # de LLM y una pantalla de ajustes que la reescribe entera (`PUT /settings/llm`).
        # Acá «otro cerebro» no es un proveedor de más — son los MISMOS tres campos
        # apuntando a otro lado, así que lo que se compara es la TERNA COMPLETA.
        # ⚠️ Medido: el desvío mantuvo `provider = openai` y cambió `model_name` y
        # `base_url`. Comparar sólo el id del proveedor habría dado verde.
        "brain_exclusivo": True,
        "brain_lectura": "settings_llm",
        # Sin plugin: este stack no tiene el punto de extensión `config.plugin` que tiene
        # el de Ciencia.
        #
        # ⚠️ ACÁ DECÍA «lo que el workspace produce cruza al puente por
        # `POST /v1/workspaces/artifact`», Y ERA FALSO: la ruta no existe con ese nombre
        # —es `/v1/workspaces/artifacts`—, y ningún proceso la llamaba. Los tres llamantes
        # del árbol son los tres plugins (`openscience.js:178` · `openwork.js:247` ·
        # `dochaus.js:24`), o sea exactamente los stacks que NO son éste. Las dos filas del
        # puente que la Fase 6 midió para Finanzas eran, desde el día uno, código
        # inalcanzable: este workspace no producía un solo artefacto de la casa.
        #
        # Ahora sí lo hace, y por donde este stack ya pasa: `_cosechar_artefactos_del_borde`
        # lee los `role:"tool"` del historial en cada paso del cerebro y cruza los que
        # `artefactos_del_borde.KINDS_POR_WORKSPACE` declara. El plugin sigue siendo la
        # deuda —ve el turno de verdad, el borde lo deriva—, pero deja de ser la diferencia
        # entre tener artefactos y no tener ninguno.
    },

    #: [Gate 4 · F6-oficina] EL SEGUNDO INQUILINO — y el primero que se configura por HTTP.
    #: OpenWork (`third_party/openwork/`, sólo su árbol MIT `apps/` + `packages/`; `/ee` es
    #: FSL y no viajó). Estrena tres cosas que Ciencia no necesitaba y que por eso el pack
    #: no tenía: entorno declarado por la fila, config con forma propia, y el cerebro
    #: enchufado por PATCH después de la salud (ver `pack.enchufar_cerebro`).
    "oficina": {
        "label": "Oficina",
        "icon": "▤",          # la hoja del oficio, no la marca del proyecto
        "stack": "OpenWork",
        # `dist` es la UI construida (`pnpm run build` en `apps/app`). No se commitea —es
        # artefacto de build, igual que la de Ciencia— y viaja por el spec del sidecar.
        "dist": "third_party/openwork/apps/app/dist",
        "url_env": "ALEPH_WORKSPACE_OFICINA_URL",
        "url_default": "http://127.0.0.1:4288",
        # Medido sobre el binario compilado el 2026-08-10: `/health` devuelve
        # `{"ok":true,"version":"0.18.18",…}`. `/` devuelve 200 tanto sirviendo la UI como
        # sin ella, así que `/` NO discrimina y no se declara.
        "health": "/health",
        "bin": [
            "third_party/openwork/bin/openwork-server",
            "third_party/openwork/apps/server/dist/bin/openwork-server",
        ],
        # Su CLI toma banderas directas, sin subcomando: el `--port` se lo agrega el pack.
        "serve_args": [],
        # ── LA CONFIG ────────────────────────────────────────────────────────────────
        # Su `server.json` es el VEHÍCULO DE LOS SECRETOS: su CLI acepta `--token`, pero
        # `ps` muestra `argv`, así que los tokens van por archivo 0600 —que además es su
        # costura oficial (`apps/server/src/config.ts:251`). El server NO persiste este
        # archivo por su cuenta (medido: el dir queda vacío), así que lo escribe Aleph.
        "config_shape": "openwork_server",
        "config_file": "server.json",
        # ── EL ENTORNO ───────────────────────────────────────────────────────────────
        # Las cuatro son seams del propio repo (`packages/paths/index.mjs`), cero parche.
        # `OPENWORK_SERVER_CONFIG` apunta a un ARCHIVO, no a un dir: por eso la fila
        # declara plantillas en vez del par `config_env`/`data_env` que le alcanza a Ciencia.
        "env": {
            "OPENWORK_SERVER_CONFIG": "{config}/server.json",
            # ── [F1-CONECTORES] EL QUINTO SEAM, QUE FALTABA ──────────────────────────
            # Esta fila declaraba cuatro variables de `packages/paths/index.mjs` y presumía
            # de que eran «las cuatro seams del propio repo, cero parche». Faltaba ésta, que
            # vive en el MISMO archivo: `openworkEnvStorePath` (`paths/index.mjs:73-79`)
            # honra SÓLO `OPENWORK_ENV_STORE` — no `OPENWORK_SERVER_CONFIG`— así que el
            # `env.json` con las credenciales del usuario aterrizaba en
            # `~/.config/openwork/`, global a la máquina y afuera del pack. Medido en Fase 0:
            # ese dir existe en la máquina y `<pack>/config/` no tenía `env.json`.
            "OPENWORK_ENV_STORE": "{config}/env.json",
            "OPENWORK_DATA_DIR": "{data}",
            "OPENCODE_CONFIG_DIR": "{config}/opencode",
            # Con esto el MISMO proceso sirve la API y la UI, y le inyecta a su `index.html`
            # el token de cliente (`static-ui.ts:129`). Es lo que hace que el workspace no
            # tenga pantalla de login: la UI ya viene autenticada de fábrica.
            "OPENWORK_WEB_ROOT": "{recursos}/third_party/openwork/apps/app/dist",
            # ── EL MOTOR ─────────────────────────────────────────────────────────
            # El harness de OpenWork es el binario `opencode`, y sin él el cuerpo sirve
            # la UI pero no corre un turno: el PATCH del cerebro devuelve
            # `opencode_unconfigured` porque no hay motor al que recargarle nada. Lo
            # levanta el propio server —es SU costura (`apps/server/src/cli.ts:45`)— y
            # sólo si se le pide con esta bandera.
            "OPENWORK_MANAGE_OPENCODE": "1",
            # Nuestro binario pinneado y verificado, jamás uno del PATH: lo que corra
            # tiene que ser lo que `third_party/opencode/IMPORT.md` describe.
            "OPENWORK_OPENCODE_BIN": "{recursos}/third_party/opencode/bin/opencode-darwin-arm64",
            # Y no se actualiza solo. Es su costura oficial, la misma clase que
            # `OFFICECLI_SKIP_UPDATE=1`: un motor que se auto-actualiza deja de ser el del
            # manifiesto y su SHA pasa a mentir.
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
        },
        # Cuáles de esas rutas son DIRECTORIOS que tienen que existir antes del arranque.
        # `OPENWORK_SERVER_CONFIG` no está acá a propósito: es un archivo, y su carpeta
        # (`{config}`) ya la crea el pack. `OPENCODE_CONFIG_DIR` sí: el motor escribe un
        # `.gitignore` adentro al construir su instancia y, si falta, muere con ENOENT que
        # la superficie ve como un 500 `UnknownError` mudo.
        "env_dirs": ["OPENCODE_CONFIG_DIR"],
        # ── [F1-CONECTORES] EL JSON CON ESQUEMA QUE SU SHELL INYECTA A CADA HIJO ─────────
        # Forma exacta: `{schemaVersion, updatedAt, variables:[{key,value,updatedAt}]}`
        # (`apps/server/src/env-file.ts:36-40`), en claro y 0600. La casa escribe ANTES del
        # spawn porque su `EnvService` CACHEA y no reinvalida (`env-file.ts:167-180`): la
        # carga es perezosa, así que llegar antes del primer `list()` es la condición.
        #
        # ⚠️ NO SE LE PONE UNA KEY DE LLM ACÁ. Su `readForInjection` saca todo `OPENWORK_*`
        # y `OPENCODE_*` (`env-file.ts:235`), y además una credencial de proveedor por esta
        # vía sería un segundo cerebro entrando por la puerta de al lado — justo lo que
        # `exclusividad_del_cerebro` apaga. Van credenciales de SERVICIO, que es para lo que
        # su propio código dice que existe el store («for service credentials, not
        # OpenWork/OpenCode runtime knobs», `env-file.ts:16-18`).
        "cred_format": "env_json",
        "cred_map": [
            {"vault": "github", "clave": "GITHUB_TOKEN"},
            {"vault": "exa", "clave": "EXA_API_KEY"},
        ],
        # [O2 · obra C] EL PLUGIN DE LA CASA para este stack. Vive en NUESTRO árbol y el
        # MOTOR lo carga por `file://`. A diferencia de Ciencia —donde el plugin se declara
        # en el mismo archivo de config del stack— acá va en un `opencode.json` aparte,
        # dentro del dir de config del motor: es él quien lo carga, no el server.
        "plugin": "platform/workspaces/plugins/openwork.js",
        "engine_config_dir_env": "OPENCODE_CONFIG_DIR",

        # ── LAS MANOS ─────────────────────────────────────────────────────────────
        # Nombre con el que las skills las llaman → dónde viaja el binario. El pack arma
        # un dir de enlaces y lo pone delante del PATH del motor. Sin esto el agente no
        # encuentra la mano, y la puerta de Ó11 —que casa contra la ORDEN— tampoco
        # reconocería un `…/gws-macos-arm64 gmail send` como un envío.
        "hands": {
            "gws": "third_party/gws/bin/gws-macos-arm64",
            "officecli": "third_party/officecli/bin/officecli-macos-arm64",
        },

        # ── Ó11 · LA PUERTA DE LAS MANOS CLOUD ────────────────────────────────────
        # Las formas son las reales del CLI de gws (`gws <servicio> <recurso> <método>`,
        # leídas de sus SKILL.md), no inventadas. El orden importa poco porque la regla
        # ancha va al final y el motor resuelve por especificidad — MEDIDO en
        # `qa/verify_f6_oficina.py`, no supuesto.
        #
        # Fail-closed de verdad: además de los verbos que el mandato nombra (enviar,
        # borrar, evento), cae en `ask` TODO lo que no sea una lectura obvia. Es la misma
        # regla que `platform/gates/approval_gate.py` ya sella para tools desconocidas:
        # ante la duda, se pregunta. Lo único que pasa solo son los verbos de lectura.
        # MEDIDO, y por eso es tan corto: el matcher del motor **no resolvió** patrones con
        # varios comodines. Con `gws * * send*` declarado, su propio log dijo
        # `action.pattern=*  action.action=allow` — o sea que la regla ancha ganaba y el
        # envío pasaba solo. Se dejan las formas que el motor SÍ resuelve.
        #
        # Y el resultado es más fail-closed que la versión larga, no menos: **toda** orden
        # de las manos cloud se pregunta. Es la misma regla que `approval_gate.py` sella
        # para tools desconocidas —ante la duda, se pregunta— aplicada a una mano que toca
        # el correo real de una persona. Una lista blanca de lecturas queda anotada como
        # deuda: primero hay que medir cómo desempata el motor entre dos reglas que casan.
        # EL ORDEN ES LA REGLA, y se midió: **gana la ÚLTIMA que casa**, no la más
        # específica. Con `{"gws *": "ask", "*": "allow"}` el propio log del motor decía
        # `action.pattern=*  action.action=allow` y el envío pasaba solo. Por eso el
        # comodín va PRIMERO y las manos cloud después: lo último que casa es lo que manda.
        # (Ésa es también la razón por la que las formas con varios comodines se cayeron:
        # no hacía falta afinarlas, hacía falta ordenarlas.)
        "engine_permissions": {
            "bash": {
                # lo que no es una mano cloud sigue como estaba: esta puerta es de gws
                "*": "allow",
                # …y toda orden de las manos cloud se pregunta. Fail-closed por defecto,
                # igual que `approval_gate.py` con una tool desconocida.
                "gws *": "ask",
            },
        },
        # ── EL CEREBRO ───────────────────────────────────────────────────────────────
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # Por HTTP, no por archivo: su motor vive detrás del server y sólo se entera de un
        # proveedor nuevo si alguien le pide que recargue. El orden lo garantiza el pack.
        "brain_wiring": "patch_providers",
        "brain_patch_path": "/runtime-config/providers",
        "brain_provider_id": "aleph",
        # [LEY 12] Ver la fila de Legal: lo mismo, y acá además hay con qué REPARAR
        # (`_apagar_catalogo_ajeno` habla la ruta del server de OpenWork).
        "engine": "opencode",
        # [LEY 12] El motor trae EMBEBIDO su catálogo gratuito (`opencode/big-pickle` y
        # compañía). Medido: `OPENCODE_DISABLE_MODELS_FETCH=1` no lo saca — viene horneado
        # en el binario, no se baja. Se apaga por la costura del server
        # (`POST /workspace/:id/runtime-config/disabled-providers`) para que el selector
        # del workspace muestre UN cerebro y no una tienda de modelos.
        "brain_disable_providers": ["opencode"],
    },

    # ── [Gate 4 · Fase 6 · §6.a] BROWSER USE — capacidad de la Sala, no un vertical ───
    #
    # Igual que Búsqueda y Deep Research: `oculto`, así que no aparece en el menú ni como
    # destino de un artefacto. Lo que lo distingue de los seis es que NO tiene cara — su
    # `dist` es su propio directorio y lo único que sirve es un puerto de loopback con
    # NDJSON. La cara es la Sala.
    #
    # `bin` es el launcher de la casa, que resuelve el runtime COMPARTIDO
    # (`platform/sala/research/runtime`, plano y jamás un venv) y el chromium que ya viaja.
    "sala_browser": {
        "label": "Navegador",
        "icon": "▣",
        "stack": "browser-use",
        "oculto": True,
        "dist": "platform/browser",
        "install_marker": "servidor.py",
        "url_env": "ALEPH_SALA_BROWSER_URL",
        "url_default": "http://127.0.0.1:0",
        # La señal de salud toca el órgano que hace el trabajo, no una piel: `/health` lo
        # contesta el mismo handler que corre el loop.
        "health": "/health",
        "bin": ["platform/browser/arranque.sh"],
        "serve_args": [],
        "config_env": "ALEPH_BROWSER_CONFIG_DIR",
        "data_env": "ALEPH_BROWSER_PROFILE_DIR",
        "config_file": "browser.json",
        # El cerebro entra por el borde, como todos. La costura la arma
        # `platform/browser/cerebro.py` leyendo ESTE mismo archivo de config.
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
    },

    # ── [Gate 4 · Fase 6 · §6.f] EL PRIMER INQUILINO QUE NO ES UN VERTICAL ────────────
    #
    # Deep Research **no es un workspace**: es una CAPACIDAD DE LA SALA. El plan lo sella
    # dos veces —«deep research NO es vertical (es característica de la Sala, 6.f)» y «a
    # los verticales: jamás por default»— y esta fila es el lugar donde eso deja de ser
    # prosa y pasa a ser código: `oculto: True` (ver `workspaces_list`).
    #
    # Está acá, en el registro de packs, porque lo que necesita es EXACTAMENTE lo que el
    # pack sabe hacer: levantar un proceso al entrar, matarlo al salir, elegirle un puerto
    # libre, escribirle la config del cerebro y pasarle la sesión. No hacía falta una
    # máquina nueva; hacía falta no dibujarlo en el menú.
    #
    # QUÉ LEVANTA. No su servidor MCP: ése es **stdio** (`third_party/ldr/src/
    # local_deep_research/mcp/server.py:1053`) y **ciego al progreso** —su propio docstring
    # avisa «synchronous operation that typically takes 1-5 minutes» (`:367-368`)—, y §6.f
    # pide justo el progreso: «planificando → buscando → leyendo 4/20 → sintetizando». Lo
    # que levanta es la cáscara de LA CASA (`platform/sala/research/`), que importa el motor
    # como librería y rinde sus etapas en NDJSON. El MCP queda igual, censado, disponible
    # como tool para un agente — pero no es la puerta de la Sala.
    "sala_research": {
        "label": "Deep Research",
        "icon": "◈",
        "stack": "Local Deep Research",
        # ⟵ LA LÍNEA QUE HACE CUMPLIR LA REGLA SELLADA. Sin esto, el sidebar lo pinta como
        # vertical con `href="../workspaces/sala_research.html"` —que no existe— y, peor,
        # `/v1/workspaces/destino` lo ofrece como destino de artefactos: o sea que deep
        # research llegaría a los verticales por la puerta de atrás, que es exactamente lo
        # que el plan prohíbe. Se filtra en UN solo lugar porque el aplicador de destinos
        # se alimenta de la misma lista (`_filas_workspaces` → `workspaces_list`).
        "oculto": True,
        # No tiene `dist` porque no tiene cara: `installed` sale de que su launcher esté en
        # disco, que es el otro hecho que esa línea ya acepta. Se declara el directorio del
        # pack para no dejar el campo vacío y que la ruta diga dónde vive.
        "dist": "platform/sala/research",
        "url_env": "ALEPH_SALA_RESEARCH_URL",
        # `:0` a propósito, igual que Legal: que un puerto horneado no se pueda colar.
        "url_default": "http://127.0.0.1:0",
        "health": "/health",
        "bin": ["platform/sala/research/arranque.sh"],
        "serve_args": [],
        # `LDR_DATA_DIR` es la env var que **el motor ya respeta** (`third_party/ldr/src/
        # local_deep_research/config/paths.py:28`), no una inventada por nosotros: con ella
        # sus datos dejan de vivir donde él quiera y pasan al dir que Aleph administra.
        # `ALEPH_RESEARCH_CONFIG_DIR` sí es de la casa, y tiene que serlo: quien lee esa
        # config no es el motor, es nuestra cáscara.
        "config_env": "ALEPH_RESEARCH_CONFIG_DIR",
        "data_env": "LDR_DATA_DIR",
        "config_file": "aleph-cerebro.json",
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # Sin `plugin`: el plugin por `file://` es la costura de los stacks OpenCode para
        # anotar sus pasos. Acá el que anota es nuestro propio servidor, que ya pone
        # `X-Aleph-Space` en cada llamada al borde (`platform/sala/research/cerebro.py`).
    },

    # ── [Gate 4 · Fase 6 · §6.a.bis] LA BÚSQUEDA WEB BASE — tampoco es un vertical ────
    #
    # Misma naturaleza que `sala_research` y la misma línea que lo hace cumplir: `oculto`.
    # El plan lo sella igual de fuerte: «a los VERTICALES no llega por default — sus
    # stacks traen buscadores propios con protocolos EXACTOS del oficio que NO se tocan;
    # genérico jamás pisa específico».
    #
    # DOS PROCESOS, y el segundo es el interesante. El launcher levanta **SearXNG aparte**
    # y después Vane. SearXNG es **AGPL-3.0** y `third_party/README.md` lo prohíbe como
    # código adentro — pero no hubo que inventar nada: upstream YA lo corre por el camino
    # Descarga (lo clona en build, venv y usuario propios, y le habla sólo por HTTP JSON).
    # Del árbol importado de Vane, lo único de SearXNG son tres archivos de configuración.
    "sala_busqueda": {
        "label": "Búsqueda",
        "icon": "◎",
        "stack": "Vane",
        "oculto": True,
        "dist": "platform/sala/busqueda",
        "url_env": "ALEPH_SALA_BUSQUEDA_URL",
        "url_default": "http://127.0.0.1:0",
        # NO `/`. La lección de Ciencia (ver el comentario de `running` más arriba) es que
        # `/` contesta lo que no corresponde: acá la raíz murió con la cara, así que
        # devolvería 404 aunque el motor esté perfecto.
        #
        # [§6.a.bis · servidor] Era `/api/providers`, que es de Vane. Ahora el puerto del
        # pack lo atiende `platform/sala/busqueda/servidor.py` —el motor quedó en un
        # puerto interno— así que la señal es la SUYA. No se pierde lo que probaba la
        # anterior: el launcher no levanta el servidor hasta que `/api/providers` del
        # motor contesta, o sea que un `/health` en verde sigue implicando que el motor
        # atiende y que su capa de config cargó.
        "health": "/health",
        "bin": ["platform/sala/busqueda/arranque.sh"],
        "serve_args": [],
        # `DATA_DIR` es la env var que **el propio Vane ya respeta** para su config y su
        # SQLite (`third_party/vane/src/lib/config/index.ts:8-11`). El dir de config sí es
        # de la casa: quien lee ese archivo es nuestro traductor, no el motor.
        "config_env": "ALEPH_BUSQUEDA_CONFIG_DIR",
        "data_env": "DATA_DIR",
        "config_file": "aleph-cerebro.json",
        "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph",
        # Sin `plugin`, por lo mismo que `sala_research`.
    },
}

#: [Gate 4 · Fase 4 · O1] LAS CAUSAS DEL PACK, CON SU COPY (regla sellada: ninguna causa
#: llega a una superficie sin copy; si aparece una nueva se deriva provisional y se marca,
#: jamás muda). Mismo patrón que `bridge.CAUSES`.
_COPY_PACK = {
    "pack_no_instalado": "Este workspace no viajó completo con esta instalación.",
    "pack_no_arranco": "El workspace no llegó a levantarse.",
}

#: [LEY 12 · ley 9] LO QUE EL `enter` TIENE QUE PODER DECIR CUANDO REPARA SOLO.
#:
#: La decisión de producto es «reparar y anunciar», no «cerrar la puerta»: un `PackError`
#: acá dejaría al usuario afuera de su trabajo por algo que apretó él, y encima sin poder
#: entrar a deshacerlo. Pero reparar en silencio sería la misma clase de defecto que la
#: obra viene a matar —la auditoría de Oficina midió tres fallos mudos en un solo turno—,
#: así que la causa viaja con su copy, como manda la regla sellada: ninguna causa llega a
#: una superficie sin copy.
_COPY_EXCLUSIVIDAD = {
    "cerebro_ajeno_apagado":
        "Habías conectado otro proveedor de modelos en este espacio. Lo apagamos: "
        "aquí el modelo lo pone Aleph.",
    "cerebro_ajeno_presente":
        "Hay otro proveedor de modelos conectado en este espacio y Aleph no pudo "
        "apagarlo. Lo que pase por él no queda registrado.",
}

#: [F1-CONECTORES] LAS CAUSAS DE CREDENCIAL, CADA UNA CON SU COPY.
#: Regla sellada: ninguna causa llega a una superficie sin copy. Van acá al lado de las de
#: exclusividad y viajan en el MISMO sobre (`salida["aviso"]`) a propósito — la pantalla ya
#: sabe leer ese campo, y que adentro cambie el mecanismo no es motivo para que aprenda un
#: vocabulario nuevo.
_COPY_CREDENCIALES = {
    # LA SOMBRA. Se DICE y no se toca: la variable la exportó el usuario en su shell y la
    # casa no sabe si es un descuido o una decisión. Lo que sí sabe es que el stack va a
    # preferirla por encima de la llave del vault, y eso en silencio sería el peor de los
    # dos mundos: la pantalla diría «conectado» sobre una llave que no se está usando.
    "credencial_sombreada":
        "Tienes una credencial exportada en tu terminal con el mismo nombre que la que "
        "guardaste en Aleph. Este espacio va a usar la de tu terminal, no la de Aleph. "
        "No la tocamos: si quieres que gane la de Aleph, quítala de tu terminal.",
    # La escritura no se pudo verificar releyendo. No se afirma que falló: se afirma que no
    # se pudo probar, que es distinto y es lo único honesto que la casa sabe.
    "credencial_sin_verificar":
        "Guardamos tu credencial en este espacio pero no pudimos comprobar que llegó. "
        "Si el conector no funciona, vuelve a entrar al espacio.",
    "credencial_no_coincide":
        "Tu credencial no quedó como la guardamos en Aleph. El conector puede fallar; "
        "vuelve a entrar al espacio para que la escribamos de nuevo.",
}


class WorkspaceArtifactRequest(BaseModel):
    """[Gate 4 · Fase 3 · 3.5] LO QUE UN STACK HEREDADO PRODUJO, cruzando el puente.

    El stack manda su artefacto CRUDO —su `kind`, su `data`— y Aleph lo traduce a un
    tipo canónico con `platform/artifacts/bridge.py`. Es a propósito que el stack NO
    mande `type`: si pudiera elegir el tipo del vocabulario, habría dos vocabularios
    otra vez (los cuatro que 2.3 mató) y cada stack nuevo agregaría el suyo.

    Las REFERENCIAS de procedencia viajan como en cualquier create; los HECHOS los
    resuelve el servidor leyendo el events.jsonl (contrato §3.2)."""
    sid: str                              # la sesión de obras (la de la Sala del usuario)
    workspace: str                        # quién produjo (el id de `_WORKSPACE_STACKS`)
    kind: str                             # el vocabulario DEL STACK (snapshot_card, …)
    data: Any = None                      # el resultado crudo de su tool
    name: Optional[str] = None            # la tool que lo produjo (informativo)
    title: Optional[str] = None           # si el stack tiene un título mejor que el derivado
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    run_id: Optional[str] = None
    chat_id: Optional[str] = None
    agent_id: Optional[str] = None
    intent: Optional[str] = None
    # [Convergencia · superficie 7] EL PASAPORTE DEL STACK, COMO REFERENCIA.
    #
    # Un stack heredado puede traer su PROPIA procedencia —OpenScience trae un
    # `ProvenanceEnvelope` con el sha256 de los bytes, el commit del código y el id de
    # su corrida— y hasta acá se tiraba entero: el plugin que cruza copiaba cuatro
    # campos de presentación y dejaba `contentHash` y el sobre atrás. Un archivo que el
    # stack SÍ ejecutó y SÍ hasheó llegaba sin ninguna forma de volver.
    #
    # Estas tres NO cambian el grado. `capture_quality` se sigue topando en `declared`
    # para todo lo que produce un workspace (`provenance._cap_workspace`), porque Aleph
    # midió el modelo y no ejecutó el kernel, y esa regla no se toca. Lo que cambia es
    # que la afirmación queda COMPROBABLE, que es lo contrario de creerle.
    source_sha256: Optional[str] = None    # hash de los bytes, del propio almacén del stack
    source_run_ref: Optional[str] = None   # el id de corrida dentro de SU sobre
    source_commit: Optional[str] = None    # la revisión de código que su sobre fijó


class WorkspaceBrainCloseRequest(BaseModel):
    """[Gate 4 · Fase 3 · 3.2] Cierra en el espacio el turno que el harness terminó:
    `final` + `closed`, que es lo que `provenance` necesita para resolver `model_final`.

    `model_final` NO viene en el body a propósito: el borde lo re-deriva de los
    `workspace_step` que ÉL MISMO escribió en el espacio. Si el harness pudiera
    declararlo, fabricaría el hecho central del anti-grift (contrato §3.2)."""
    space_id: str
    workspace: str = ""
    answer: str = ""
    ok: bool = True
    turns: int = 0
    error: Optional[str] = None
    run_id: Optional[str] = None
    user_id: Optional[str] = None
    # [Gate 4 · Fase 3 · 3.6 · modelo de hilos] El hilo DEL WORKSPACE. Es un chat más del
    # MISMO agente: identidad, instrucciones y cinturón se comparten con la Sala porque
    # cuelgan del puppet; el HISTORIAL no, porque es otro `chat_id`. El turno se registra
    # acá, al cerrar — el `complete` no toca el hilo: el estado del loop es del harness.
    chat_id: Optional[str] = None
    prompt: Optional[str] = None
    client_turn_id: Optional[str] = None


class WorkspaceEnterRequest(BaseModel):
    """[Gate 4 · Fase 4 · O1] «Estoy entrando a este workspace»: levantá su pack.

    `user_id` no es decorativo: el pack corre **por dueño** (la clave del dueño es
    `(user_id, entity_id, huella)`), su config lleva la sesión de ESE usuario y sus datos
    van a su dir. Sin dueño no se levanta nada — el mismo fail-closed que la fuga entre
    cuentas dejó sellado.

    `puppet_id` es de qué receta sale el cerebro; si no viene, el borde resuelve la de por
    defecto igual que hoy.

    [O2] `chat_id` y `sid` son el HILO y la BIBLIOTECA de este workspace, y los manda la
    pantalla porque son suyos: el `sid` es la MISMA clave que usa La Sala
    (`sala-v2/artefactos.js:artSid`). Usar otra partiría la Biblioteca en dos mitades
    invisibles entre sí — la vieja y la del workspace verían obras distintas del mismo
    agente."""
    user_id: Optional[str] = None
    puppet_id: Optional[str] = None
    chat_id: Optional[str] = None
    sid: Optional[str] = None
    # El espacio es el archivo de hechos del turno del stack. Si el launcher no lo
    # entrega separado, `sid` sigue siendo la identidad estable de la Biblioteca.
    space_id: Optional[str] = None


class WorkspacePreferenciaRequest(BaseModel):
    """[4.5] «Para este tipo de trabajo, siempre este workspace». `workspace` vacío la borra.

    La preferencia es POR TIPO y no global a propósito: «los informes ábrelos en Ciencia» es
    una decisión que el usuario puede tomar sin perder la casa; «todo en Ciencia» se la quita."""
    user_id: str
    tipo: str
    workspace: Optional[str] = None


class WorkspaceMemoriaRequest(BaseModel):
    """[O5] Cómo quedó un workspace, por dueño. `deltas` es abierto a propósito: lo que una
    pantalla quiera recordar de lo suyo entra sin migración, y el día que un campo se gane su
    lugar se le pone nombre (hoy lo tienen `chat_id` y `sid`, los dos que la casa verifica)."""
    user_id: str
    chat_id: Optional[str] = None
    sid: Optional[str] = None
    deltas: Optional[dict] = None


class WorkspaceLeaveRequest(BaseModel):
    """«Me fui del workspace». `gracia_s` sólo lo manda una vara que quiera medir el
    apagado literal (0 = apagá en el acto, sin ventana para el F5 del usuario)."""
    user_id: Optional[str] = None
    gracia_s: Optional[float] = None


class MemoryWriteRequest(BaseModel):
    """Step 2 · A3 — el usuario escribe/edita una memoria del agente desde el panel.
    [op 3 · reclasificar] `kind` opcional en el PATCH: mover skill↔episodica con un toque
    (sin tocar el contenido). El POST sigue exigiendo content (422 si falta)."""
    content: Optional[str] = None
    kind: Optional[str] = None


_SEED_MAX_IDS = 500   # cota dura de ids por request de seed (anti auto-DoS; el bus igual se capa por tier)

# [FIX-P9] TOOLS DEL CLIENTE — techo duro y forma exigida.
# El techo existe porque cada schema viaja al system del modelo: sin cota, un cliente
# infla el prompt de cada turno con lo que quiera y lo paga la cuenta de Aleph (la línea
# roja #1 del negocio). 12 alcanza y sobra: la capa de opciones declara 5.
_CLIENT_TOOLS_MAX = 12


def _validar_client_tools(raw):
    """Devuelve la lista saneada, o levanta 422 con la causa EXACTA.

    Rechaza en vez de sanear en silencio (§4h: fallo visible, jamás mudo). Un schema mal
    formado es un bug del cliente, y descartarlo callado deja al modelo sin una tool que la
    superficie cree haber declarado — la interfaz esperaría opciones que nunca van a llegar.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail={
            "error": "client_tools_invalid", "detail": "`client_tools` tiene que ser una lista"})
    if len(raw) > _CLIENT_TOOLS_MAX:
        raise HTTPException(status_code=422, detail={
            "error": "client_tools_too_many",
            "detail": f"máximo {_CLIENT_TOOLS_MAX} tools de cliente por run (llegaron {len(raw)})"})
    out, vistos = [], set()
    for i, t in enumerate(raw):
        fn = (t or {}).get("function") if isinstance(t, dict) else None
        nombre = (fn or {}).get("name") if isinstance(fn, dict) else None
        if not isinstance(fn, dict) or not isinstance(nombre, str) or not nombre.strip():
            raise HTTPException(status_code=422, detail={
                "error": "client_tools_invalid",
                "detail": f"client_tools[{i}] no tiene la forma {{type:'function', function:{{name,…}}}}"})
        if nombre in vistos:
            raise HTTPException(status_code=422, detail={
                "error": "client_tools_duplicated", "detail": f"«{nombre}» viene dos veces"})
        vistos.add(nombre)
        out.append({"type": "function", "function": fn})
    return out or None


class BusSeedRequest(BaseModel):
    """ORDEN 4 · composición — el usuario elige memorias de sus agentes para sembrar el bus de un
    Cuarto (préstamo con procedencia, sin tocar el origen). `memory_ids` = ids de agent_memories."""
    memory_ids: list[str]


def _rag_ext_for_mime(mime: Optional[str]) -> str:
    """mime → extensión (markitdown elige el conversor por extensión). Fallback .bin (deja que
    markitdown sniffee)."""
    return {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/csv": ".csv", "text/html": ".html", "application/json": ".json",
    }.get((mime or "").split(";")[0].strip().lower(), ".bin")


class RagDocRequest(BaseModel):
    """DOC-RAG: subir un documento a la memoria de un agente. Texto → `content`. Binario
    (PDF/Excel/Word/imagen) → `content_b64` + `mime`: el backend lo convierte a markdown con
    markitdown (ticket 32) antes de indexarlo. `content` es opcional cuando viene content_b64."""
    name: str
    content: Optional[str] = None
    content_b64: Optional[str] = None
    mime: Optional[str] = None


class KnowledgeUploadRequest(BaseModel):
    """C1 · RAG (átomo Conocimiento): subir un documento al corpus de una COMPOSICIÓN
    (Cuarto guardado). El contenido llega como `text` (txt/md ya-texto) o `content_b64`
    (binario pdf/docx, base64) — sin python-multipart. `mime` ayuda a elegir el extractor.
    Server-side: se trocea, se embebe con la llave BYOK del DUEÑO (nunca la de Aleph, nunca
    a logs/respuesta) y se indexa (coseno en Python puro)."""
    name: str
    mime: Optional[str] = None
    text: Optional[str] = None
    content_b64: Optional[str] = None


class TranscribeRequest(BaseModel):
    """🎙️ voz → texto: audio en base64 → Groq Whisper → texto al input."""
    audio_b64: str
    mime: Optional[str] = "audio/webm"
    filename: Optional[str] = "audio.webm"
    user_id: Optional[str] = None


class TurnClassifyRequest(BaseModel):
    """Ruteo charla/obra por DECLARACIÓN de la cognición (no por forma del output)."""
    prompt: str
    user_id: Optional[str] = None


class ObraCaptionRequest(BaseModel):
    """Línea natural (voz del modelo) que acompaña a una obra en el chat — generada, no fija."""
    task: str
    excerpt: str = ""
    editing: bool = False
    user_id: Optional[str] = None


class DetenerTurnoRequest(BaseModel):
    """[F4b · obra 2] Parar UN turno del BYO-CLI en vuelo. El `turno_id` sale del canal
    `turno` del stream (`stream_chat` lo lee del annex que F2d puso en el primer chunk)."""
    turno_id: str
    user_id: Optional[str] = None


class ArtifactCreateRequest(BaseModel):
    """F4 · crear un artifact nuevo en la sesión (acción declarada 'new').

    [Gate 4 · Fase 2] La superficie manda REFERENCIAS (space_id/run_id/…), jamás
    afirmaciones: `model_final`/`tool_calls`/`degraded` los resuelve el SERVIDOR
    leyendo el events.jsonl del espacio (contrato §3.2 — si la superficie pudiera
    declarar el modelo, fabricaría capacidad)."""
    title: str
    type: str = "informe"
    content: str = ""
    user_id: Optional[str] = None
    # referencias de procedencia (opcionales, saneadas server-side):
    space_id: Optional[str] = None
    run_id: Optional[str] = None
    chat_id: Optional[str] = None
    agent_id: Optional[str] = None
    method_id: Optional[str] = None
    method_run_id: Optional[str] = None
    produced_by: Optional[str] = None   # run | stream | manual | workspace
    intent: Optional[str] = None        # el pedido que la originó (informativo, [:200])
    workspace: Optional[str] = None     # [F3 · 3.4] el stack heredado que lo produjo


class ArtifactEditRequest(BaseModel):
    """F4 · editar un artifact (snapshot a versions[] + update). Acción declarada 'edit'.
    [Gate 4 · Fase 2] El turno que edita trae SUS referencias: cada versión lleva
    su propia identidad (contrato §4)."""
    content: str
    title: Optional[str] = None
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    run_id: Optional[str] = None
    chat_id: Optional[str] = None
    agent_id: Optional[str] = None
    method_id: Optional[str] = None
    method_run_id: Optional[str] = None
    produced_by: Optional[str] = None
    intent: Optional[str] = None
    workspace: Optional[str] = None     # [F3 · 3.4]


class ArtifactClassifyRequest(BaseModel):
    """F4 · la cognición DECLARA new|edit (+ id) — no se infiere por forma."""
    prompt: str
    artifacts: list[dict[str, Any]] = []
    user_id: Optional[str] = None


def build_phase1_router(
    *,
    get_conn: Callable[[], Any],
    events_dir: Callable[[], Path],
) -> APIRouter:
    """
    get_conn():   devuelve una conexión psycopg2 fresca a puppet_ai (el caller la cierra).
    events_dir(): devuelve el dir donde viven los events.jsonl por space_id.
    """
    router = APIRouter(prefix="/v1", tags=["phase1"])
    # `repo_root` se conserva únicamente para el puente histórico que exporta agentes
    # en el árbol durante dev. Toda LECTURA empaquetada usa resource_root; toda escritura
    # de outputs usa data_root, nunca `_MEIPASS`.
    repo_root = Path(__file__).resolve().parents[4]
    resource_root = _RESOURCE_ROOT

    def _export_agent_bridge(puppet: Optional[dict]) -> bool:
        """D3 · exporta el puppet como receta hija (catalog/agents/agent-<uuid>.config.json) para que
        un padre lo referencie por agent_ref. Best-effort: nunca tumba el request (el row YA está en DB;
        re-exportamos en create Y update, idempotente por UUID). El file I/O vive en agent_catalog,
        no en repo.py (la capa DB queda pura).

        FIX F (§9·F) · devuelve True si el archivo se escribió, False si el export falló (deploy
        read-only / FS lleno). En False el caller expone `bridge_pending` en la respuesta: sin eso el
        agente colocado queda PERMANENTEMENTE no-delegable en silencio (delegation omite el ref que no
        resuelve, sin ruido) y sólo se auto-cura en un re-save. No-fatal: el puppet igual devuelve 201."""
        if not puppet or not puppet.get("id"):
            return False
        try:
            agent_catalog.export_agent(puppet, repo_root)
            return True
        except Exception:
            _log.warning("agent_catalog.export_agent falló para puppet %s", puppet.get("id"), exc_info=True)
            return False

    def _conn():
        try:
            return get_conn()
        except Exception as exc:  # psycopg2 ausente o DB caída
            raise HTTPException(
                status_code=503,
                detail={"error": "db_unavailable", "detail": str(exc)},
            )

    # ── AUTHZ (anti-IDOR): autoriza por SESIÓN, no por el id que manda el cliente ──
    # El token de sesión (Bearer) cifra el user_id dueño. Cada endpoint con identidad
    # de usuario verifica session.owner == el id reclamado. Sin token → 401; token de
    # otro → 403. Cierra el IDOR donde un user leía data (y creds BYOK) de otro.
    def _bearer(authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None
        a = authorization.strip()
        return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)

    def _inbox_chat_gate(sid: str, authorization: Optional[str]) -> str:
        """El dueño de la sesión, y SÓLO si ese chat existe y es suyo.

        EL HUECO QUE CIERRA, medido contra la .app instalada: el inbox devolvía **201 para
        un chat que no existe**. No era una fuga —la carpeta cuelga del hash del dueño, así
        que nadie lee lo de otro— pero dejaba crear directorios para cualquier `sid`
        inventado, y encima le mentía al cliente: le decía «guardado» sobre una conversación
        que el run después iba a rechazar con `chat_not_found`. Dos superficies con dos
        respuestas distintas sobre el mismo id es cómo se pierde un archivo sin que nadie
        sepa dónde quedó.

        Mismo criterio y mismo repo que `_chat_gate` del run: un chat ajeno es 404, no 403
        — no se confirma que exista si no es tuyo.
        """
        from app.phase1 import chats_repo, repo as _r
        owner = _r.session_owner(_bearer(authorization))
        if not owner:
            raise HTTPException(status_code=401, detail={
                "error": "no_session", "detail": "Adjuntar necesita tu sesión."})
        conn = _conn()
        try:
            if chats_repo.get_chat_owned(conn, str(sid), str(owner)) is None:
                raise HTTPException(status_code=404, detail={
                    "error": "chat_not_found", "detail": "Ese chat no existe."})
        finally:
            conn.close()
        return str(owner)

    def _inbox_dir_de(body, authorization) -> Optional[str]:
        """La carpeta de adjuntos de (dueño de la sesión, chat). `None` si falta alguno.

        El dueño sale de la SESIÓN, jamás de `body.user_id`: si dependiera del campo, mandar
        el id de otro leería los adjuntos de otro. Mismo criterio que el cap de billing y
        que el guard de RAG.

        ⚠️ VIVE ACÁ ADENTRO, Y NO A NIVEL DE MÓDULO, POR UN BUG QUE ESTO YA CAUSÓ. `_bearer`
        es un CLOSURE de este builder. Con el helper afuera, la llamada tiraba `NameError`,
        el `except` la convertía en `None` y el adjunto nunca llegaba al workdir — un
        turno que respondía «no veo ningún archivo» sin una sola línea en el log.
        Medido contra la .app instalada (2aa64a13): el inbox tenía el PDF, el belt levantaba
        los 8 servers, y `adjuntos/` no existía en el run_outputs.
        """
        from app.phase1 import repo as _r, inbox_store as _ib
        try:
            owner = _r.session_owner(_bearer(authorization))
            chat = getattr(body, "chat_id", None)
            if not owner or not chat:
                return None
            return str(_ib.dir_de(str(owner), str(chat)))
        except Exception as e:                          # noqa: BLE001 — no tumba el run…
            # …PERO SE VE. La versión muda de esto es la que escondió el NameError de arriba:
            # un adjunto que no llega es una promesa rota, y el usuario no tiene cómo saberlo.
            _log.warning("no pude resolver el inbox del chat: %s: %s", type(e).__name__, e)
            return None

    def _authorize(claimed_user_id: str, authorization: Optional[str]) -> str:
        from app.phase1 import repo
        owner = repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para continuar."})
        if str(owner) != str(claimed_user_id):
            raise HTTPException(status_code=403,
                detail={"error": "forbidden", "detail": "Esa cuenta no es la tuya."})
        return owner

    def _dueno_obligatorio(reclamado: Optional[str], authorization: Optional[str]) -> str:
        """El dueño de una ruta operativa, SIEMPRE derivado de la sesión.

        ⚠️ [B0-4] La diferencia con llamar a `_authorize` sólo cuando el body trae `user_id`
        es la que separa una garantía de una costumbre: si el campo es opcional, omitirlo
        esquivaba el chequeo entero, y con él el preflight de presupuesto, el resolver BYOK
        y la atribución del costo. La seguridad tiene que estar en el endpoint, no en la
        buena conducta del cliente — el pack propio mandaba el token, pero eso no lo vuelve
        obligatorio.

        Un `user_id` de body o de cabecera sólo se CONTRASTA; jamás crea autoridad.
        """
        from app.phase1 import repo
        owner = repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401, detail={
                "error": "no_session",
                "detail": "Esta acción necesita tu sesión."})
        if reclamado is not None and str(reclamado).strip() and str(owner) != str(reclamado):
            raise HTTPException(status_code=403, detail={
                "error": "forbidden", "detail": "Esa cuenta no es la tuya."})
        return str(owner)

    #: CUÁNTO VALE EL SONDEO DE LOS CLI **EN EL CAMINO DEL TURNO**. La cara sigue con el
    #: de siempre (20 s): ahí el estado se MUESTRA y uno viejo es una mentira que se lee.
    #: Acá no se muestra nada — se resuelve cuál cerebro atiende— y sondear cuesta 2.172 ms
    #: medidos. Con 20 s, cualquiera que tarde más de eso en escribir el mensaje siguiente
    #: lo paga entero antes de que el modelo arranque.
    _TTL_CLI_EN_TURNO = float(os.environ.get("ALEPH_TTL_CLI_TURNO", "300") or "300")

    def _model_use_catalog(owner_id: str, necesita: Optional[str] = None) -> dict[str, Any]:
        """Catálogo ejecutable privado; jamás se devuelve al navegador.

        EL POOL PRIMERO, Y ES UNA DIFERENCIA DE SEGUNDOS. `todos=True` es el catálogo de
        CONFIGURACIÓN —el del Cuarto—: trae también lo que todavía no está configurado, y
        para cada vía API sale a la red a pedirle `/v1/models` al proveedor. Medido con
        cProfile sobre este mismo camino: **8 `urlopen` HTTPS, 2.276 ms**, en el turno,
        antes de que el modelo arranque, y para un turno que corre por un CLI local.

        El pool (`todos=False`) es «conectados + Default» — literalmente lo que la Sala
        ofrece para USAR ahora, que es lo único que un turno necesita resolver. Medido en
        la misma corrida: **2.785 ms → 14 ms**, con `default_id` IDÉNTICO (`codex_cli`).

        ⚠️ Y SI LA SELECCIÓN NO ESTÁ EN EL POOL, SE ENSANCHA. Una vía API configurada
        podría no entrar al pool por su propia regla; antes que resolverla mal, se paga el
        catálogo completo. Así el camino rápido es el común y el raro sigue siendo correcto
        — nunca al revés.
        """
        from app.phase1 import centro_modelos
        pool = centro_modelos.selector_modelos(
            owner=owner_id, get_conn=_conn, contexto=None, todos=False,
            ttl_cli=_TTL_CLI_EN_TURNO,
        )
        if necesita:
            _ids = {str((m or {}).get("id") or "") for m in (pool.get("modelos") or [])}
            _pedido = str(necesita)
            if _pedido not in _ids and f"cli.{_pedido}" not in _ids and _pedido.replace("cli.", "", 1) not in {i.replace("cli.", "", 1) for i in _ids}:
                _obs.marca("run.catalogo_ensanchado", pedido=_pedido)
                return centro_modelos.selector_modelos(
                    owner=owner_id, get_conn=_conn, contexto=None, todos=True,
                    ttl_cli=_TTL_CLI_EN_TURNO,
                )
        return pool

    def _route_model_use(
        *,
        workspace_id: str,
        call_class: str,
        authorization: Optional[str],
        recipe: Optional[dict[str, Any]],
        selection_ref: Optional[str],
        agent_id: Optional[str],
        session_id: Optional[str],
        task_id: Optional[str],
        entity_id: Optional[str],
        messages: Optional[list[dict[str, Any]]] = None,
        attachments: Optional[list[dict[str, Any]]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        required_capabilities: Optional[list[str]] = None,
        stream: bool = True,
        call_id: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[Any]]:
        """Aplica ``legacy | shadow | aleph_v2`` en la frontera de ejecución.

        Devuelve ``(recipe, raw_model_cfg, snapshot)``. En legacy y shadow la receta
        permanece byte-idéntica; en aleph_v2 el routing del cliente se reemplaza por la
        fila owner-gated del catálogo. No ejecuta modelos ni tools.
        """
        from app.phase1 import repo as _repo
        from app.phase1.model_route_flags import RouteMode, route_mode
        from app.phase1.model_use_adapters import adapt_recipe_v1, adapt_workspace_raw
        from app.phase1.model_use_execution import (
            materialize_model_config, materialize_recipe, selection_ref_for_recipe,
        )
        from app.phase1.model_use_migration import admit_for_mode
        from app.phase1.model_use_resolver import ResolutionFailure
        from pydantic import ValidationError

        mode = route_mode(workspace_id, call_class)
        if mode is RouteMode.LEGACY:
            return recipe, None, None

        owner_id = _repo.session_owner(_bearer(authorization))
        cid = str(call_id or task_id or entity_id or _uuid.uuid4().hex)
        catalog: Optional[dict[str, Any]] = None

        def read_catalog(owner: str) -> dict[str, Any]:
            nonlocal catalog
            if catalog is None:
                catalog = _model_use_catalog(owner, selection_ref)
            return catalog

        try:
            if recipe is not None:
                catalog = read_catalog(str(owner_id or "")) if owner_id else None
                inferred = selection_ref_for_recipe(recipe, catalog or {})
                if not inferred:
                    # [default por proveedor] La receta no mapea a nada del catálogo. Antes
                    # el turno moría acá; ahora cae al Default del dueño —que es una
                    # elección suya— y sigue. No hay proveedor que preferir: la receta no
                    # nombró ninguno resoluble, así que el Default es lo único honesto.
                    #
                    # Si tampoco hay Default, se levanta la causa de siempre con su copy:
                    # el fallback no puede inventar un modelo donde el dueño no eligió uno.
                    inferred = str((catalog or {}).get("default_id") or "").strip()
                    if inferred:
                        _log.warning(
                            "model-use: la receta no mapea a ninguna selección canónica; "
                            "el turno lo atiende el Default del dueño (`%s`)", inferred)
                    else:
                        raise ResolutionFailure(
                            "selection_unmapped",
                            "La receta todavía no tiene una selección canónica resoluble.",
                            409,
                        )
                request = adapt_recipe_v1(
                    recipe=recipe,
                    # Las recetas inline no tienen identidad durable. El id call-local
                    # evita fabricar un puppet y mantiene explícito que la política sólo
                    # vive durante esta llamada.
                    agent_id=str(agent_id or f"inline:{cid}"),
                    selection_ref=inferred,
                    call_id=cid,
                    idempotency_key=cid,
                    workspace_id=workspace_id,
                    call_class=call_class,
                    session_id=session_id,
                    task_id=task_id,
                    entity_id=entity_id,
                    messages=messages,
                    attachments=attachments,
                    tools=tools,
                    required_capabilities=required_capabilities,
                    stream=stream,
                )
            else:
                request = adapt_workspace_raw(
                    call_id=cid,
                    idempotency_key=cid,
                    workspace_id=workspace_id,
                    call_class=call_class,
                    selection_ref=selection_ref,
                    selection_scope=(
                        "session" if session_id else ("task" if task_id else "default")
                    ),
                    session_id=session_id,
                    task_id=task_id,
                    entity_id=entity_id,
                    messages=messages,
                    attachments=attachments,
                    tools=tools,
                    required_capabilities=required_capabilities,
                    stream=stream,
                )

            decision = admit_for_mode(
                request, mode=mode, owner_id=owner_id, read_catalog=read_catalog
            )
        except ResolutionFailure as exc:
            if mode is RouteMode.SHADOW:
                _log.info(
                    "model-use shadow rejected workspace=%s class=%s error=%s",
                    workspace_id, call_class, exc.code,
                )
                return recipe, None, None
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc
        except (ValidationError, ValueError) as exc:
            if mode is RouteMode.SHADOW:
                _log.info(
                    "model-use shadow invalid workspace=%s class=%s error=%s",
                    workspace_id, call_class, type(exc).__name__,
                )
                return recipe, None, None
            raise HTTPException(status_code=422, detail={
                "error": "model_use_invalid", "detail": str(exc),
            }) from exc

        if mode is RouteMode.SHADOW:
            _log.info(
                "model-use shadow workspace=%s class=%s admitted=%s selection=%s error=%s",
                workspace_id, call_class, bool(decision.snapshot),
                decision.snapshot.selection_ref if decision.snapshot else None,
                (decision.shadow_error or {}).get("error"),
            )
            return recipe, None, decision.snapshot

        snapshot = decision.snapshot
        if snapshot is None or catalog is None:  # defensa; ALEPH_V2 nunca debería llegar así
            raise HTTPException(status_code=500, detail={
                "error": "model_route_incomplete",
                "detail": "La admisión no produjo una ruta ejecutable.",
            })
        if recipe is not None:
            return materialize_recipe(recipe, snapshot, catalog), None, snapshot
        return None, materialize_model_config(snapshot, catalog), snapshot

    def _canonicalize_saved_config(
        config: dict[str, Any], *, selection_ref: Optional[str], owner_id: str, agent_id: str
    ) -> dict[str, Any]:
        """Materializa el payload secretless del Cuarto para los ejecutores legacy.

        Clientes anteriores que no mandan ``model_selection_ref`` conservan exactamente
        su camino. El nuevo contrato falla fuerte si el id no existe, no está conectado o
        no soporta las capacidades del agente.
        """
        if not str(selection_ref or "").strip():
            return config
        from app.phase1.model_use_execution import canonicalize_recipe_selection
        from app.phase1.model_use_resolver import ResolutionFailure
        from pydantic import ValidationError
        try:
            return canonicalize_recipe_selection(
                config,
                selection_ref=str(selection_ref).strip(),
                owner_id=str(owner_id),
                agent_id=str(agent_id),
                # Con QUÉ se necesita: si la selección no está en el pool, `_model_use_catalog`
                # se ensancha sola. Pasar la función pelada la dejaría sin ese dato.
                read_catalog=lambda _o: _model_use_catalog(_o, selection_ref),
            )
        except ResolutionFailure as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={
                "error": "model_use_invalid", "detail": str(exc),
            }) from exc

    def _authorize_resource(expected_owner: Optional[str],
                            authorization: Optional[str],
                            query_token: Optional[str] = None) -> Optional[str]:
        """REGLA owner-gated-CUANDO-hay-dueño (§4.5, T6): si el recurso TIENE dueño, la
        sesión debe ser ese dueño (401 sin sesión · 403 si es de otro). Si el recurso es
        ANÓNIMO (`expected_owner is None`: inspect/demo/run sin user), la lectura es ABIERTA
        — un recurso sin dueño no es data privada de nadie (no rompe el recon ni la demo).
        Difiere de `_authorize` (identidad OBLIGATORIA, None⇒deny) a propósito.
        Acepta el token por header (Bearer) o por `?token=` (SÓLO streaming: el EventSource
        del browser no puede mandar headers). La lógica pura vive en app.phase1.authz."""
        from app.phase1 import authz
        token = authz.pick_token(authorization, query_token)
        verdict, owner = authz.decide(expected_owner, token)
        if verdict == "no_session":
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para ver esto."})
        if verdict == "forbidden":
            raise HTTPException(status_code=403,
                detail={"error": "forbidden", "detail": "Eso no es de tu cuenta."})
        return owner

    def _authorize_space(space_id: str, authorization: Optional[str],
                         query_token: Optional[str] = None) -> Path:
        """Claim inmutable primero; sólo owners legacy no-nulos como fallback."""
        from inspection.space_access import (SpaceAccessError, read_claim,
                                             space_dir, validate_space_id)
        from app.phase1 import repo as _repo
        try:
            sid = validate_space_id(space_id)
            root = events_dir()
            claim = read_claim(root, sid)
            directory = space_dir(root, sid)
        except SpaceAccessError as exc:
            raise HTTPException(status_code=404,
                                detail={"error": "space_not_found"}) from exc
        if claim is not None:
            if not claim["public"]:
                _authorize_resource(claim["owner_id"], authorization, query_token)
            return directory
        conn0 = _conn()
        try:
            legacy_owner = _repo.space_owner(conn0, sid)
        finally:
            conn0.close()
        if legacy_owner is None:
            raise HTTPException(status_code=404, detail={"error": "space_not_found"})
        _authorize_resource(legacy_owner, authorization, query_token)
        return directory

    def _chat_gate(body: "RunPuppetRequest", authorization: Optional[str]) -> Optional[dict]:
        """[UX·A1] Si el turno trae chat_id, valida y prepara la conversación persistente:
        exige sesión (un chat SIEMPRE tiene dueño), el chat debe ser del owner de la
        SESIÓN (anti-IDOR: ajeno == 404), y si tanto el body como el chat traen puppet_id
        deben coincidir (un hilo no cambia de composición a mitad). Devuelve
        {chat, history_text} — history_text es el bloque de turnos PREVIOS (registro
        real, artifacts-por-handle: solo texto) para anteponer al prompt del cerebro.
        El turno del usuario se persiste ACÁ (antes de correr: si el run falla a mitad,
        lo que el usuario dijo no se pierde); el del agente lo persiste el caller al
        tener la respuesta."""
        if not body.chat_id:
            return None
        from app.phase1 import chats_repo, repo as _repo
        owner = _repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para usar chats."})
        conn = _conn()
        try:
            chat = chats_repo.get_chat_owned(conn, body.chat_id, str(owner))
            if chat is None:
                raise HTTPException(status_code=404,
                    detail={"error": "chat_not_found", "detail": "Ese chat no existe."})
            if body.puppet_id and chat.get("puppet_id") and \
                    str(chat["puppet_id"]) != str(body.puppet_id):
                raise HTTPException(status_code=409,
                    detail={"error": "chat_mismatch",
                            "detail": "Ese chat pertenece a otra composición."})
            turn_id = (str(body.client_turn_id).strip()[:128]
                       if body.client_turn_id else None)
            history = chats_repo.build_history_block(
                conn, body.chat_id, exclude_client_turn_id=turn_id)
            message = chats_repo.append_message(
                conn, chat_id=body.chat_id, role="user",
                kind=("obra" if body.space_id else "chat"),
                content=(body.turn_text or body.prompt), space_id=body.space_id,
                client_turn_id=turn_id,
            )
            replayed = bool(
                turn_id and not message.get("_idempotent_inserted", True)
            )
            prior_answer = (
                chats_repo.get_turn_message(
                    conn, chat_id=body.chat_id,
                    client_turn_id=turn_id, role="agent",
                )
                if replayed else None
            )
            return {"chat": chat, "history_text": history or None,
                    "client_turn_id": turn_id, "replayed": replayed,
                    "prior_answer": prior_answer}
        except HTTPException:
            raise
        except _sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            _log.error(
                "chat_gate database_locked chat=%s turn=%s",
                body.chat_id, body.client_turn_id,
            )
            raise HTTPException(status_code=503, detail={
                "error": "database_locked",
                "detail": (
                    "La base local estuvo ocupada durante 30 s. "
                    "El turno no se ejecutó; vuelve a intentarlo."
                ),
            }) from exc
        finally:
            conn.close()

    def _chat_record_user(chat_id: str, prompt: str, *, kind: str,
                          space_id: Optional[str] = None,
                          client_turn_id: Optional[str] = None) -> None:
        """[Gate 4 · Fase 3 · 3.6] El pedido del humano, en el hilo del workspace.

        Gemelo de `_chat_record_answer`: proyección, jamás camino crítico. La
        idempotencia por `client_turn_id` es la del propio `append_message` (un retry no
        duplica el mensaje humano)."""
        if not (chat_id and (prompt or "").strip()):
            return
        try:
            from app.phase1 import chats_repo
            conn = _conn()
            try:
                chats_repo.append_message(conn, chat_id=chat_id, role="user",
                                          kind=kind, content=prompt,
                                          space_id=space_id,
                                          client_turn_id=client_turn_id)
            finally:
                conn.close()
        except Exception as exc:                     # noqa: BLE001
            _log.error("chat_record_user_failed chat=%s error=%s", chat_id, exc)

    def _chat_owner(chat_id: str) -> Optional[str]:
        """El dueño de un hilo, para el guard del borde (ajeno == 404 río arriba)."""
        try:
            from app.phase1 import chats_repo
            conn = _conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM chats WHERE id = %s", (chat_id,))
                    row = cur.fetchone()
                    return str(row[0]) if row else None
            finally:
                conn.close()
        except Exception:                            # noqa: BLE001
            return None

    def _chat_replay_answer(chat_gate: Optional[dict]) -> Optional[dict]:
        """Un replay nunca corre dos veces: devuelve lo ya cerrado o dice que sigue vivo."""
        if not chat_gate or not chat_gate.get("replayed"):
            return None
        prior = chat_gate.get("prior_answer") or {}
        answer = str(prior.get("content") or "").strip()
        if answer:
            return {
                "ok": True, "answer": answer,
                "run_id": prior.get("run_id"),
                "idempotent_replay": True,
            }
        raise HTTPException(status_code=409, detail={
            "error": "turn_in_progress",
            "detail": "Ese turno ya fue aceptado y sigue en curso; no lo ejecuté dos veces.",
        })

    def _chat_record_answer(chat_id: str, answer: str, *, kind: str,
                            space_id: Optional[str] = None,
                            run_id: Optional[str] = None,
                            client_turn_id: Optional[str] = None) -> None:
        """[UX·A1] Persiste la respuesta del agente en el hilo. NUNCA tumba el run:
        el registro es proyección, no camino crítico."""
        if not (chat_id and (answer or "").strip()):
            return
        try:
            from app.phase1 import chats_repo
            conn = _conn()
            try:
                chats_repo.append_message(conn, chat_id=chat_id, role="agent",
                                          kind=kind, content=answer,
                                          space_id=space_id, run_id=run_id,
                                          client_turn_id=client_turn_id)
            finally:
                conn.close()
        except Exception as exc:
            _log.error(
                "chat_record_answer_failed chat=%s turn=%s error=%s",
                chat_id, client_turn_id, exc,
            )

    # ── EL HILO DEL WORKSPACE PARA LOS STACKS SIN PLUGIN ─────────────────────────────
    # [convergencia · superficie 1] La derivación del turno y la escritura viven en
    # `app.phase1.hilo_workspace` — que es donde se pueden MEDIR sin levantar el endpoint
    # entero. Acá quedan las dos cosas que sí son del borde: la autorización del hilo y
    # abrir/cerrar la conexión. Todo el porqué está en el docstring de ese módulo.
    def _anotar_pedido_del_borde(ws: str, chat_id: Optional[str], space_id: Optional[str],
                                 messages, authorization: Optional[str], tools=None):
        """Anota el pedido humano ANTES de correr. Devuelve `(turno_id, prompt)` o `None`.

        El dueño del hilo se verifica ACÁ y no adentro del módulo: un `chat_id` ajeno tiene
        que morir río arriba con su 404, no aparecer en el hilo de otro. Es la misma guarda
        que ya usa `close` (`_authorize_resource(_chat_owner(...))`).

        ⚠️ **NO TODA LLAMADA ES UN TURNO**, y suponer que sí llenaba el hilo de andamiaje:
        medido en Diseño, 3 turnos humanos dejaron 23 filas, ninguna el turno. Las dos
        capas que lo separan viven en `hilo_workspace` y las dos son fail-open. Acá se las
        llama en orden y se le pasa el `tools` que el STACK declaró —no el que el borde le
        vaya a mandar al modelo, que con code execution es otro—."""
        from app.phase1 import hilo_workspace as _hw
        if not chat_id:
            return None
        meta = _WORKSPACE_STACKS.get((ws or "").strip().lower())
        if not _hw.le_toca_al_borde(meta):
            return None
        _hw.marcar_catalogo(chat_id, tools)
        if not _hw.es_el_loop_del_agente(chat_id, tools):
            return None                     # el harness pidiendo un favor, no el agente
        turno, trae_pedido = _hw.turno_del_paso(
            chat_id, messages, decl=(meta or {}).get("hilo_pedido"))
        if not turno:
            return None
        if not trae_pedido:
            # Un paso del MISMO turno: su respuesta se actualiza en sitio, pero el pedido
            # ya está anotado y volver a escribirlo sería duplicarlo con otro texto.
            return turno
        _authorize_resource(_chat_owner(chat_id), authorization)
        conn = _conn()
        try:
            _hw.anotar_pedido(conn, chat_id=chat_id, turno=turno, space_id=space_id)
        finally:
            conn.close()
        return turno

    def _anotar_respuesta_del_borde(chat_id: Optional[str], turno, texto: str,
                                    space_id: Optional[str]) -> None:
        """Anota la respuesta del turno. Sin turno no hay nada que anotar."""
        if not (chat_id and turno):
            return
        from app.phase1 import hilo_workspace as _hw
        conn = _conn()
        try:
            _hw.anotar_respuesta(conn, chat_id=chat_id, turno=turno, texto=texto,
                                 space_id=space_id)
        finally:
            conn.close()

    # ── EL PUENTE + EL ALMACÉN, EN UN SOLO LUGAR ─────────────────────────────────────
    # POR QUÉ SE EXTRAE. Hasta acá esta secuencia —cruzar, decidir si el contenido es
    # texto o JSON, reclamar dueño, construir procedencia, escribir— vivía ENTERA adentro
    # de `POST /workspaces/artifacts`, que era su único llamante. Al aparecer el segundo
    # (la cosecha del borde, para los stacks sin plugin) copiarla habría fabricado la
    # quinta lista divergente de este repo: dos lugares que escriben artefactos de
    # workspace y que empiezan a disentir en la primera corrección que sólo uno reciba.
    # Un mecanismo, un dueño.
    def _cruzar_al_almacen(*, workspace: str, kind: str, name, data, sid: str,
                           titulo, refs) -> dict:
        """El artefacto de un stack heredado, hecho ciudadano. Levanta `BridgeError`.

        El rechazo del puente **sube tal cual**: quién lo traduce a una respuesta depende
        del llamante —el endpoint le debe un 422 tipado a quien lo llamó; la cosecha del
        borde no le debe nada a nadie y lo anota—. Decidir eso acá adentro obligaría a
        elegir por los dos.
        """
        from app.phase1 import artifact_store
        from artifacts import bridge
        obra = bridge.cross(workspace, {"kind": kind, "name": name, "data": data})
        # El contenido rico viaja como JSON en `content` — la misma convención que la
        # Sala vieja usa para planilla/convergence/cad (el renderer lo parsea). Lo que ya
        # ES texto se guarda tal cual.
        #
        # [Convergencia · superficie 7] LA REGLA MIRA LA FORMA, NO EL TIPO. Decía
        # `if obra["type"] == "informe"`, y eso alcanzaba mientras el puente sólo producía
        # `informe` y formas ricas. Al empezar a producir `web` y `documento` —que también
        # traen texto plano— el `else` los envolvía en JSON, y BAJARLOS DEVOLVÍA EL SOBRE:
        # medido levantando la app, un export de Diseño se bajaba como `.html` de 198 b que
        # empezaba en `{"` en vez de `<`. La forma es el criterio correcto porque no hay que
        # acordarse de venir a agregar cada tipo nuevo acá: una obra con `content` de texto
        # y nada más es texto, tenga el tipo que tenga.
        _rico = any(k not in ("type", "title", "content") for k in obra)
        contenido = (
            obra["content"]
            if isinstance(obra.get("content"), str) and not _rico
            else _json.dumps(obra, ensure_ascii=False, default=str)
        )
        _artifact_store_call(artifact_store.claim_owner, sid, refs.user_id)
        prov = _build_artifact_provenance(refs)
        art = _artifact_store_call(
            artifact_store.create_artifact, sid,
            titulo or obra.get("title") or kind, obra["type"], contenido, prov)
        # `claimed` le dice a la superficie si el propio workspace reclama este tipo o
        # si la obra cae a la base (ley 4: lo no reclamado NO es un estado roto).
        return {"artifact": art, "workspace_kind": kind,
                "claimed": bridge.claims(workspace, obra["type"])}

    # ── LA COSECHA DEL BORDE, PARA LOS STACKS SIN PLUGIN ─────────────────────────────
    # [Finanzas · los artefactos] Gemela exacta de `_anotar_pedido_del_borde`, y por el
    # mismo motivo: los tres stacks que declaran plugin cruzan sus artefactos DESDE
    # adentro del harness (`plugins/openscience.js:178` · `openwork.js:247` ·
    # `dochaus.js:24`), y los tres que no, no los cruzaban NUNCA. La fila de Finanzas
    # decía en un comentario que sí —«cruza al puente por POST /v1/workspaces/artifact»—
    # y no había un solo llamante en el árbol: sus dos filas del puente
    # (`bridge.TABLE["finanzas"]`) eran código inalcanzable.
    #
    # La derivación vive en `app.phase1.artefactos_del_borde`, que es donde se puede
    # MEDIR sin levantar el endpoint entero. Acá quedan las dos cosas que sí son del
    # borde: la autorización del `sid` y la escritura.
    def _cosechar_artefactos_del_borde(ws: str, chat_id, space_id, user_id,
                                       messages, authorization) -> None:
        """Cruza lo que este paso trae del paso anterior. NUNCA tumba el turno.

        Es proyección, igual que el hilo: un artefacto que no se pudo guardar no puede
        costarle al usuario la respuesta que estaba esperando. Por eso todo lo de acá
        adentro se anota y sigue — pero se ANOTA, que es la mitad que un `except: pass`
        se lleva puesta.
        """
        from app.phase1 import hilo_workspace as _hw
        from app.phase1 import artefactos_del_borde as _ab
        _wsl = (ws or "").strip().lower()
        meta = _WORKSPACE_STACKS.get(_wsl)
        if not _hw.le_toca_al_borde(meta):
            return                      # tiene plugin: lo cruza él, que ve el turno de verdad
        cosecha = _ab.cosechar(messages, workspace=_wsl)
        # ── [Educación · cortes 3 y 4] LA SEGUNDA FUENTE: EL ALMACÉN DEL PROPIO PACK ──
        # Un stack sin plugin puede hablar de DOS formas, y hay que leerlas las dos:
        #   · Finanzas devuelve JSON adentro del `role:"tool"` → lo abre `cosechar`.
        #   · Educación pone PROSA ahí (`tool_dispatch.py:637-645`) y lo estructurado se
        #     queda del otro lado. Sus entregables —los archivos que el turno generó y el
        #     `response` de cada capacidad— viven en el store que el stack YA escribe,
        #     `chat_history.db`. Eso lo lee `obras_del_pack`.
        # Las dos devuelven la MISMA forma, así que de acá para abajo hay un solo camino
        # de escritura: mismo `sid`, misma procedencia, misma huella, mismo rechazo con
        # causa. Dos lectores, un escritor.
        from app.phase1 import obras_del_pack as _op
        try:
            cosecha = list(cosecha) + _op.leer(_wsl)
        except Exception as exc:                     # noqa: BLE001 — store ajeno
            _logging.getLogger(__name__).warning(
                "obras_del_pack_falló ws=%s error=%s", _wsl, exc)
        if not cosecha:
            return
        # El `sid` agrupa los artefactos de una conversación en el almacén. El hilo del
        # workspace es la agrupación que el usuario reconoce —es el mismo `chat_id` con el
        # que la superficie 1 anota el turno—, así que la obra aparece donde está la
        # charla que la pidió. Sin hilo se cae al espacio, y sin espacio al workspace: un
        # artefacto sin lugar preferido es mejor que un artefacto perdido.
        sid = str(chat_id or space_id or ("ws-" + _wsl))
        from app.phase1 import artifact_store as _store
        _authorize_resource(_store.get_owner(sid), authorization)

        class _Refs:
            pass
        _Refs.space_id, _Refs.run_id = space_id, None
        _Refs.chat_id, _Refs.agent_id = chat_id, None
        _Refs.user_id = user_id
        _Refs.method_id = _Refs.method_run_id = None
        # `workspace` y no `model`: Aleph midió el MODELO del turno, no la función del
        # stack que produjo esto. Es el mismo grado que se lleva el camino del plugin
        # (3.4), y bajarlo o subirlo acá sería mentir sobre qué fue lo que vimos.
        _Refs.produced_by = "workspace"
        _Refs.intent = None
        _Refs.workspace = _wsl
        # El pasaporte del stack va VACÍO y eso es honesto: por el borde no llega ningún
        # sha256 ni referencia de corrida que el stack haya firmado. Inventarle una sería
        # exactamente lo que `never_filled` prohíbe.
        _Refs.source_sha256 = _Refs.source_run_ref = _Refs.source_commit = None

        from artifacts import bridge as _bridge
        for pieza in cosecha:
            if not _ab.es_nueva(chat_id, pieza["huella"]):
                continue                 # el mismo resultado, repetido en el historial
            try:
                _cruzar_al_almacen(
                    workspace=_wsl, kind=pieza["kind"], name=pieza["name"],
                    data=pieza["data"], sid=sid, titulo=pieza["name"], refs=_Refs)
            except _bridge.BridgeError as exc:
                # El puente rechazando NO es un error del borde: es el puente haciendo su
                # trabajo (entregar exigía inventar dato). Se anota con su causa y su copy
                # para que quede en el expediente, y el turno sigue.
                _logging.getLogger(__name__).info(
                    "cosecha_borde: %s/%s no cruzó — %s (%s)", _wsl, pieza["kind"],
                    exc.code, _bridge.CAUSES.get(exc.code, ""))
            except Exception as exc:                 # noqa: BLE001
                _logging.getLogger(__name__).warning(
                    "cosecha_borde_falló ws=%s kind=%s error=%s", _wsl, pieza["kind"], exc)

    def _make_space_emitter(space_id: str):
        """LA COSTURA A LA SALA: devuelve un on_event que persiste cada paso del run
        como evento del espacio (events.jsonl[space_id]) vía EventLog (persist-before-emit,
        id monotónico). La sala consume esos eventos (SSE /spaces/{id}/stream o snapshot
        /spaces/{id}/events). Un fallo emitiendo NUNCA tumba el run."""
        from inspection.space_access import space_dir
        path = space_dir(events_dir(), space_id, create=True) / "events.jsonl"
        log = es._events_replay().EventLog(path)
        def emit(evt: dict) -> None:
            e = dict(evt)
            e["space_id"] = space_id
            if e.get("kind") == "tool_call":
                e.setdefault("verb_human", _verb_human(e.get("tool_raw") or e.get("tool")))
            try:
                log.append(e)
            except Exception:
                # ⚠️ ANTES ERA `pass`, Y ESO ES LO QUE HIZO INVISIBLE EL DEFECTO.
                # `EventLog.append` RECHAZA todo `type` que no esté en `EVENT_TYPES`, y
                # este `except` se comía el rechazo: el evento no llegaba al disco y
                # nadie se enteraba. Un emisor que se traga sus propios fallos convierte
                # cualquier señal nueva en un cero silencioso — el mismo modo de fallo
                # que ya nos costó un tap que grababa cero por un NameError.
                # Sigue sin tumbar el run (esa parte estaba bien): ahora lo DICE.
                _logging.getLogger(__name__).warning(
                    "space_emitter: evento DESCARTADO type=%r space=%s — no llegó al "
                    "disco y la superficie no lo va a ver", e.get("type"), space_id,
                    exc_info=True)
        return emit

    # ── (b) Workshop valida la receta contra el SCHEMA ────────────────────────
    @router.post("/recipes/validate", response_model=RecipeValidateResponse)
    def validate_recipe(body: RecipeValidateRequest):
        """
        Valida una receta v1 ANIDADA contra el contrato taller↔assembler. Devuelve
        también effective_gates (§3.5): los gates que Security HARÁ CUMPLIR — los
        mandatorios SIEMPRE, aunque la receta los omita o los ponga 'off'. El taller
        muestra esto para que el usuario no crea que apagó un gate que en realidad sigue.
        """
        eff = rv.effective_gates(body.recipe)
        try:
            warnings = rv.validate_recipe(body.recipe, repo_root=resource_root)
            return RecipeValidateResponse(
                valid=True, errors=[], warnings=warnings, effective_gates=eff
            )
        except rv.RecipeValidationError as exc:
            return RecipeValidateResponse(
                valid=False, errors=exc.errors, warnings=exc.warnings, effective_gates=eff
            )

    # ── LA FORJA (v0) — intención → PROPONE 1 pieza (PROPONE, no commitea) ──────
    @router.post("/forge", status_code=200)
    def forge(body: ForgeRequest, authorization: Optional[str] = Header(default=None)):
        """La forja propone UNA pieza (card real keyless) + su zona + narración para la
        intención. No toca DB ni credenciales: solo propone (el front acepta/rechaza).

        ⚠️ LA SESIÓN ENTRÓ EN A1. Este endpoint no la pedía, y `collect_atoms` caminaba el
        `synth_belts` de TODAS las cuentas: la forja podía proponerle a alguien una pieza
        que había traído otra persona de la misma máquina. Sin sesión sigue funcionando —
        propone del catálogo de la caja, que es público."""
        from app.phase1 import forge as _forge
        from app.phase1.atoms_router import _owner_from_session
        if not (body.intent or "").strip():
            raise HTTPException(status_code=422, detail={"error": "missing_intent"})
        return _forge.propose(body.intent, body.current_canvas,
                              owner=_owner_from_session(authorization))

    # ── (a) auth mínima ───────────────────────────────────────────────────────
    #
    # [CONTRACT-AUTH-v2] ⛔ CERRADO POR DEFAULT EN PRODUCCIÓN.
    #
    # Este endpoint crea cuentas con un email que NADIE VERIFICA. Mientras estuvo
    # abierto en el servidor público, cualquiera en internet podía registrar la
    # dirección de otra persona — verificado en vivo: POST a Render devolvía 201.
    # Ese es el vector de pre-hijacking: el atacante pre-registra victima@gmail.com y,
    # cuando la víctima entra por Google, su identidad queda ligada a esa cuenta.
    #
    # Sacar el botón del front fue COSMÉTICO: la API seguía aceptando registros. La
    # superficie no se cierra en la UI, se cierra en el servidor.
    #
    # Sigue vivo para DEV/CI y el CLI local, que lo necesitan para crear cuentas de
    # prueba sin depender de un OAuth con browser. Se enciende con
    # `PUPPET_ALLOW_PASSWORD_AUTH=1`. El default es el seguro — misma doctrina que P7:
    # una capa de seguridad cuyo default depende de que alguien recuerde una variable
    # no es una capa de seguridad.
    _PASSWORD_AUTH_ENV = "PUPPET_ALLOW_PASSWORD_AUTH"

    def _password_auth_habilitado() -> bool:
        # import local: este módulo NO importa `os` a nivel de módulo (sólo un
        # `import os as _os` dentro de otra función). Usarlo sin importarlo acá daría
        # NameError en el primer request — un 500 en vez del 404 limpio, y encima
        # invisible al importar la app.
        import os as _osmod
        return str(_osmod.environ.get(_PASSWORD_AUTH_ENV, "")).strip().lower() in (
            "1", "true", "yes", "on")

    def _exigir_password_auth():
        if _password_auth_habilitado():
            return
        # 404 y no 403: para quien sondea desde afuera, este endpoint sencillamente
        # NO EXISTE en producción. No se le confirma que hay una puerta cerrada.
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/auth/register", status_code=201)
    def auth_register(body: AuthRequest):
        """Crear cuenta: email + contraseña → hash scrypt en Postgres → sesión.
        409 si el email ya tiene cuenta; 400 si email/contraseña inválidos.
        404 si el registro por contraseña está deshabilitado (default en producción)."""
        _exigir_password_auth()
        from app.phase1 import repo
        if not body.password:
            raise HTTPException(status_code=400,
                detail={"error": "password_required", "detail": "Pon una contraseña."})
        conn = _conn()
        try:
            try:
                user = repo.register_user(conn, body.email, body.password, body.display_name)
            except ValueError as e:
                code = str(e)
                msg = {"email_taken": "Ese correo ya tiene una cuenta. Prueba ingresar.",
                       "password_too_short": "La contraseña necesita al menos 6 caracteres.",
                       "bad_email": "Ese correo no parece válido."}.get(code, "No pude crear la cuenta.")
                raise HTTPException(status_code=(409 if code == "email_taken" else 400),
                                    detail={"error": code, "detail": msg})
            user = dict(user)
            user["session_token"] = repo.mint_session(user["id"], conn=conn)
            return user
        finally:
            conn.close()

    @router.post("/auth/login", status_code=200)
    def auth_login(body: AuthRequest):
        """Login real con email + contraseña (verifica el hash). 401 si no coincide.

        ⛔ [CONTRACT-AUTH-v2] Cerrado por default en producción, igual que /auth/register
        y por una razón MÁS fuerte: su modo legacy sin contraseña hace get-or-create por
        email, o sea que este endpoint también CREA CUENTAS — con sólo mandar una
        dirección. Abierto en el servidor público era una segunda puerta al mismo vector
        de pre-hijacking, y más silenciosa que la primera.
        Sin contraseña → legacy get-or-create por email (solo dev/herramientas internas).

        BORRADO DE CUENTA (ticket 2): un login exitoso sobre una cuenta en soft-delete
        DENTRO de la ventana la REACTIVA intacta (deleted_at→NULL) y responde
        reactivated:true (las conexiones OAuth NO vuelven — se revocaron al pedir el
        borrado). Pasada la ventana, purga lazy + respuesta honesta account_purged.
        La reactivación exige la MISMA fuerza de auth que la cuenta tiene: una cuenta
        CON contraseña jamás se reactiva por la puerta legacy sin contraseña."""
        _exigir_password_auth()
        from app.phase1 import repo
        conn = _conn()
        try:
            reactivated = False
            if body.password:
                user = repo.login_user(conn, body.email, body.password)
                if user is None:
                    raise HTTPException(status_code=401,
                        detail={"error": "bad_credentials", "detail": "Correo o contraseña incorrectos."})
            else:
                # login-suave: el email centinela del device user (device::<nonce>) es
                # INALCANZABLE por esta puerta → get_or_create_user tira ValueError y acá se
                # traduce a 400 honesto (nunca se crea/loguea una cuenta con ese correo).
                try:
                    user = repo.get_or_create_user(conn, body.email, body.display_name)
                except ValueError as e:
                    raise HTTPException(status_code=400,
                        detail={"error": str(e), "detail": "Ese correo no sirve para ingresar."})
            # BORRADO DE CUENTA (step5, ticket 2): un login sobre una cuenta en soft-delete
            # dentro de la ventana la reactiva; pasada la ventana, purga lazy + 401 honesto.
            if user.get("deleted_at"):
                outcome = _resolve_deleted_login(conn, repo, user, body.password)
                if outcome == "purged":
                    raise HTTPException(status_code=401,
                        detail={"error": "account_purged",
                                "detail": "Esta cuenta fue borrada definitivamente."})
                if outcome == "password_required":
                    raise HTTPException(status_code=401,
                        detail={"error": "bad_credentials",
                                "detail": "Correo o contraseña incorrectos."})
                user = repo.get_user(conn, user["id"])
                reactivated = True
            user = dict(user)
            user["session_token"] = repo.mint_session(user["id"], conn=conn)  # liga la sesión al owner
            if reactivated:
                user["reactivated"] = True
            return user
        finally:
            conn.close()

    # ── LOGIN SUAVE: la app funciona 100% local SIN cuenta ────────────────────
    def _es_control_plane() -> bool:
        """El 'usuario de equipo' existe SOLO donde la máquina es del usuario (la .app
        / el stack local). En el control plane multi-tenant (ALEPH_ROLE=control) una
        identidad anónima compartida sería una mezcla de datos → estos endpoints NO
        existen ahí (404, misma frontera de rol que Casa 2; default=client)."""
        import os
        return os.environ.get("ALEPH_ROLE", "client").strip().lower() == "control"

    def _require_local_session_boundary(request: Request,
                                        launch_cap: Optional[str]) -> None:
        """Frontera browser→sidecar para las dos rutas que crean/mueven identidad.

        Host/Origin derrotan DNS rebinding. La capability aleatoria une la webview
        lanzada por Tauri con SU sidecar y no se persiste. Sin capability de launch,
        estas rutas fallan cerradas: un navegador cualquiera no puede acuñar identidad.
        """
        def loopback_authority(raw: str) -> tuple[Optional[str], Optional[int]]:
            try:
                parsed = _urlparse.urlsplit(raw if "://" in raw else "http://" + raw)
                host = (parsed.hostname or "").lower().rstrip(".")
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
            except (TypeError, ValueError):
                return None, None
            if host not in ("127.0.0.1", "localhost", "::1"):
                return None, None
            return host, port

        host_name, host_port = loopback_authority(request.headers.get("host") or "")
        if host_name is None:
            raise HTTPException(status_code=403, detail={"error": "local_origin_required"})
        origin = (request.headers.get("origin") or "").strip()
        if origin:
            origin_name, origin_port = loopback_authority(origin)
            if origin_name is None or origin_port != host_port:
                raise HTTPException(status_code=403, detail={"error": "local_origin_required"})

        expected = _current_launch_cap()
        if not expected:
            raise HTTPException(status_code=503, detail={"error": "local_auth_unavailable"})
        expected_port = int(os.environ.get("ALEPH_SIDECAR_PORT") or 0)
        if not expected_port or host_port != expected_port:
            raise HTTPException(status_code=403, detail={"error": "sidecar_origin_mismatch"})
        supplied = (launch_cap or "").strip()
        if not supplied or not _hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail={"error": "launch_cap_required"})

    @router.post("/auth/local", status_code=200)
    def auth_local(request: Request,
                   authorization: Optional[str] = Header(default=None),
                   launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
        """Sesión LOCAL anónima (device user): la puerta de la app jamás exige login.
        Idempotente y auto-reparadora: si el caller ya trae una sesión device válida
        cuya fila sigue existiendo, la reusa; si no (primer arranque, o el device user
        se fusionó a una cuenta), entrega la identidad de este equipo — creándola si
        hace falta. Sin red externa: todo pasa contra la DB local."""
        from app.phase1 import repo
        if _es_control_plane():
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        _require_local_session_boundary(request, launch_cap)
        conn = _conn()
        try:
            user = None
            prev = repo.session_owner(_bearer(authorization))
            if prev:
                try:
                    u = repo.get_user(conn, prev)
                except Exception:
                    u = None  # id no-uuid u otra rareza del token → identidad fresca
                if u and repo.is_device_user(u):
                    user = u
            if user is None:
                user = repo.get_or_create_device_user(conn)
            user = dict(user)
            user["session_token"] = repo.mint_session(user["id"], conn=conn)
            user["anon"] = True   # el front lo usa para OFRECER (no exigir) el login
            return user
        finally:
            conn.close()

    @router.post("/auth/merge-local", status_code=200)
    def auth_merge_local(body: MergeLocalRequest,
                         request: Request,
                         authorization: Optional[str] = Header(default=None),
                         launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
        """FUSIÓN post-login: lo creado bajo el device user local se liga a la cuenta
        (el trabajo previo no se pierde). Capability-based: hay que TENER ambos tokens
        — el de la cuenta (Authorization) y el de la sesión local (body) — así que no
        hay IDOR posible; y solo fusiona device→cuenta (repo valida ambos extremos)."""
        from app.phase1 import repo
        if _es_control_plane():
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        _require_local_session_boundary(request, launch_cap)
        acc = repo.session_owner(_bearer(authorization))
        if acc is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para ligar tu trabajo local."})
        dev = repo.session_owner((body.local_token or "").strip())
        if dev is None:
            raise HTTPException(status_code=400,
                detail={"error": "bad_local_token", "detail": "La sesión local no es válida."})
        if str(dev) == str(acc):
            return {"ok": True, "merged": False, "reason": "same_user"}
        conn = _conn()
        try:
            try:
                moved = repo.merge_local_into_account(conn, dev, acc)
            except ValueError as e:
                code = str(e)
                msg = {"no_device_user": "Esa sesión local ya no existe (quizá ya se fusionó).",
                       "not_a_device_user": "Solo se fusiona el trabajo local de este equipo.",
                       "no_account": "No encontré la cuenta destino.",
                       "account_is_device": "El destino tiene que ser una cuenta real."
                       }.get(code, "No pude fusionar el trabajo local.")
                raise HTTPException(status_code=400, detail={"error": code, "detail": msg})
            # lo que vive en disco (no en la DB) se re-liga best-effort DESPUÉS del commit:
            # un tropiezo acá no deshace la fusión — se reporta, no se esconde.
            fs: dict[str, Any] = {}
            try:
                from app.phase1 import rag_store
                fs["rag_docs"] = rag_store.reown(dev, acc)
            except Exception as exc:  # noqa: BLE001
                fs["rag_error"] = f"{type(exc).__name__}: {exc}"
            try:
                from app.phase1 import artifact_store
                fs["artifact_sessions"] = artifact_store.reown(dev, acc)
            except Exception as exc:  # noqa: BLE001
                fs["artifact_error"] = f"{type(exc).__name__}: {exc}"
            return {"ok": True, "merged": True, "moved": moved, "fs": fs}
        finally:
            conn.close()

    @router.post("/users/{user_id}/password", status_code=200)
    def change_password(user_id: str, body: ChangePasswordRequest,
                        authorization: Optional[str] = Header(default=None)):
        """Cambiar contraseña de la PROPIA cuenta (owner-gated). Verifica la actual contra
        el hash y setea la nueva. 401 sin sesión · 403 si no es tu cuenta · 400 si la actual
        no coincide / la nueva es muy corta / la cuenta no tenía contraseña."""
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            try:
                repo.change_password(conn, user_id, body.current_password, body.new_password)
            except ValueError as e:
                code = str(e)
                msg = {"bad_current": "La contraseña actual no es correcta.",
                       "password_too_short": "La contraseña nueva necesita al menos 6 caracteres.",
                       "no_password_set": "Esta cuenta no tiene contraseña para cambiar.",
                       "no_user": "No encontré la cuenta."}.get(code, "No pude cambiar la contraseña.")
                raise HTTPException(status_code=(404 if code == "no_user" else 400),
                                    detail={"error": code, "detail": msg})
            return {"ok": True, "session_token": repo.mint_session(user_id, conn=conn)}
        finally:
            conn.close()

    @router.post("/auth/logout", status_code=204)
    def auth_logout(authorization: Optional[str] = Header(default=None)):
        """Revoca la generación Fernet activa. JWT logout pertenece a Supabase."""
        from app.phase1 import authz, repo
        token = authz.parse_bearer(authorization)
        if token:
            repo.revoke_legacy_session(token)
        return None

    @router.get("/users/{user_id}/export")
    def export_user_data(user_id: str, authorization: Optional[str] = Header(default=None)):
        """Exportá TODOS tus datos (owner-gated): perfil + tus Aleph + sesiones + obra +
        conexiones (solo provider+last4, NUNCA la llave). JSON descargable, datos REALES de
        la DB — cero relleno. Sin sesión → 401; de otro → 403."""
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            return {
                "export_version": "1",
                "user": repo.get_user(conn, user_id),                 # ya sin password_hash
                "puppets": repo.list_puppets(conn, user_id),
                "runs": repo.list_runs(conn, user_id, limit=1000),
                "outputs": repo.list_outputs(conn, user_id, limit=1000),
                # STEP 2·A3 · el export lista CONECTORES del usuario, no el plumbing OAuth: filtramos
                # las filas companion "<name>__oauth" / "__oauth_partial" (no son servicios propios).
                "connections": [k for k in repo.list_keys(conn, user_id)
                                if not repo.is_companion_provider(k.get("provider", ""))],
            }
        finally:
            conn.close()

    # ── Fase 4 · Historial (runs) + Biblioteca (outputs) del usuario ───────────
    @router.get("/users/{user_id}/runs")
    def list_user_runs(user_id: str, limit: int = Query(default=50),
                       authorization: Optional[str] = Header(default=None)):
        """Historial de sesiones del usuario + costo real por run."""
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            return {"runs": repo.list_runs(conn, user_id, limit=limit)}
        finally:
            conn.close()

    @router.get("/users/{user_id}/outputs")
    def list_user_outputs(user_id: str, limit: int = Query(default=50),
                          authorization: Optional[str] = Header(default=None)):
        """Biblioteca: la obra del usuario (outputs de sus runs)."""
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            return {"outputs": repo.list_outputs(conn, user_id, limit=limit)}
        finally:
            conn.close()

    # ── Biblioteca: DESCARGAR la obra (archivo) de un output ───────────────────
    _RUN_OUTPUTS_ROOT = (_ap.data_root() / "run_outputs").resolve()

    @router.get("/outputs/{output_id}/download")
    def download_output(output_id: str,
                        authorization: Optional[str] = Header(default=None)):
        """
        Descarga el archivo de un output kind=file (la obra de Biblioteca). Devuelve los
        bytes REALES con su mime y un filename para el browser.

        Seguridad:
          - AUTHZ por dueño: el output debe pertenecer a un run del usuario de la sesión
            (mismo candado anti-IDOR que el resto). Sin sesión → 401; de otro → 403.
          - GUARD anti path-traversal / lectura de archivo arbitrario: solo se sirve si la
            ruta resuelta cae DENTRO de data/run_outputs. Un uri que apunte a /etc/passwd
            o fuera del área → 403, jamás se abre.
        """
        from app.phase1 import repo
        conn = _conn()
        try:
            row = repo.get_output_owned(conn, output_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "output_not_found"})
        # authz por dueño (user_id None ⇒ run anónimo ⇒ no descargable autenticado)
        _authorize(row.get("user_id"), authorization)
        uri = row.get("uri")
        if not uri:
            raise HTTPException(status_code=409,
                detail={"error": "no_file", "detail": "este output no tiene archivo (p.ej. es texto)"})
        path = Path(uri).resolve()
        # guard: la ruta DEBE estar bajo el área de outputs del run
        if _RUN_OUTPUTS_ROOT != path and _RUN_OUTPUTS_ROOT not in path.parents:
            raise HTTPException(status_code=403,
                detail={"error": "path_forbidden", "detail": "ruta fuera del área de outputs"})
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=410,
                detail={"error": "file_gone", "detail": "el archivo ya no está disponible"})
        return FileResponse(
            str(path),
            media_type=row.get("mime") or "application/octet-stream",
            filename=path.name,
        )

    # ── (a) catálogo de puppets del usuario ───────────────────────────────────
    @router.get("/users/{user_id}/puppets")
    def list_user_puppets(user_id: str, nicho: Optional[str] = Query(default=None),
                          status: Optional[str] = Query(default=None),
                          authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            # [rediseño · fase 2 · 2.2] EL PASADO, ANTES DE LISTAR. `marcar_usado` promueve
            # de acá en adelante (en `create_run`, el choke point); esto promueve lo que ya
            # tenía huella. Va en el MISMO lugar y por el MISMO motivo que el `ensure_kit`
            # de abajo: es el borde de CARGA, así que alcanza a todo agente existente sin
            # migrar la DB. Un solo UPDATE acotado al dueño, idempotente — la segunda
            # llamada escribe 0 filas. Best-effort: si la DB está read-only, la lista igual
            # sale (con los estados viejos, que es peor que bien pero mucho mejor que un 500).
            try:
                repo.backfill_usados(conn, user_id)
            except Exception:  # noqa: BLE001
                _log.warning("backfill de estado: falló para %s", user_id, exc_info=True)
            puppets = repo.list_puppets(conn, user_id, nicho=nicho, status=status)
            # FIX-P4 · KIT BASE · el borde de CARGA. Éste es el GET con el que el Cuarto
            # rehidrata "Mis agentes" y con el que la Sala abre un agente guardado (ambos
            # filtran esta lista por id): completar acá alcanza a TODO agente EXISTENTE sin
            # tener que migrar la DB. Silencioso e idempotente — ensure_kit sólo devuelve
            # cambió=True la PRIMERA vez, así que la segunda carga no reescribe nada ni
            # duplica. La persistencia es best-effort: si la DB está read-only el agente
            # igual SALE con el kit en la respuesta (lo que se carga es lo que corre).
            for i, p in enumerate(puppets):
                cfg, cambio = _kit.ensure_kit(p.get("config"))
                if cambio:
                    p["config"] = cfg
                    try:
                        repo.backfill_config(conn, p["id"], cfg)
                        _export_agent_bridge(p)   # el puente de delegación sigue a la receta
                    except Exception:
                        _log.warning("kit base: backfill falló para puppet %s", p.get("id"),
                                     exc_info=True)
                # NOMBRES HUMANOS · el ID sigue siendo la clave de DB/exportación, pero nunca una
                # etiqueta. La migración es idempotente y además deja config.meta.name alineado
                # para que el siguiente round-trip del Cuarto no reintroduzca el valor técnico.
                try:
                    p = repo.backfill_human_name(conn, p)
                except Exception:
                    # Lectura fail-soft: aunque una DB read-only no admita el backfill, la
                    # respuesta conserva el fallback y la UI jamás cae al UUID.
                    p["name"] = agent_catalog.display_name(p.get("name"), p.get("config"))
                    p["config"] = agent_catalog.config_with_display_name(p.get("config"), p["name"])
                    _log.warning("backfill de nombre humano falló para puppet %s", p.get("id"),
                                 exc_info=True)
                puppets[i] = p
            return {"puppets": puppets}
        finally:
            conn.close()

    # ── (a)+(b) workshop: guardar = VALIDAR primero, luego persistir ──────────
    @router.post("/puppets", status_code=201)
    def create_puppet(body: PuppetCreateRequest,
                      authorization: Optional[str] = Header(default=None)):
        """
        Guarda un puppet: VALIDA la receta contra el schema (rechaza lo que rompe el
        contrato) y RECIÉN si pasa la escribe en puppets.config. Una receta inválida
        nunca toca la DB (422 con los errores tipados). Solo podés crear puppets a tu
        propio nombre (owner == sesión).
        """
        _authorize(body.owner_id, authorization)
        requested_name = agent_catalog.clean_human_name(body.name)
        if not requested_name:
            raise HTTPException(status_code=422, detail={
                "error": "agent_name_required",
                "detail": "Dale al agente un nombre legible; los identificadores técnicos no se usan como nombre.",
            })
        body.name = requested_name
        body.config = _canonicalize_saved_config(
            body.config,
            selection_ref=body.model_selection_ref,
            owner_id=body.owner_id,
            agent_id="draft",
        )
        body.config = agent_catalog.config_with_display_name(body.config, body.name)
        # FIX-P4 · KIT BASE · el borde de NACIMIENTO. Antes de validar y de persistir: el
        # agente NACE con los 5 brazos en su cinturón, sin trámite y sin que nadie los
        # arrastre. Va antes del validador a propósito — lo que se guarda es lo que se
        # validó (jamás persistir algo que el validador no vio).
        body.config, _ = _kit.ensure_kit(body.config)
        try:
            rv.validate_recipe(body.config, repo_root=resource_root)
        except rv.RecipeValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings},
            )
        from app.phase1 import repo
        conn = _conn()
        try:
            # TICKET 27 · HERENCIA AL NACER · resolver el source ANTES de crear (para inyectar el framing
            # base del padre en la config del hijo). ANTI-IDOR: el source DEBE ser del mismo dueño — jamás
            # se hereda de otro usuario (source ajeno/inexistente → 403/404, sin oráculo).
            _inh = body.inherit_from if isinstance(body.inherit_from, dict) else None
            _src = None
            if _inh and _inh.get("puppet_id"):
                _src = str(_inh.get("puppet_id"))
                _src_owner = repo.puppet_owner(conn, _src)
                if _src_owner is None:
                    raise HTTPException(status_code=404, detail="source de herencia no encontrado")
                if str(_src_owner) != str(body.owner_id):
                    raise HTTPException(status_code=403, detail="no puedes heredar el estante de otro usuario")
                # RAZONAMIENTO HEREDADO (pieza 2): la identidad/framing del padre → BASE editable del hijo
                # (framing.inherited_base). El assembler la antepone a la especialización propia del hijo.
                _sfr = (((repo.get_puppet(conn, _src) or {}).get("config") or {}).get("framing") or {})
                _base = "\n\n".join([x for x in ((_sfr.get("inherited_base") or "").strip(),
                                                 (_sfr.get("inline") or "").strip()) if x])
                if _base:
                    if not isinstance(body.config.get("framing"), dict):
                        body.config["framing"] = {}
                    body.config["framing"]["inherited_base"] = _base
            puppet = repo.create_puppet(
                conn, owner_id=body.owner_id, name=body.name,
                nicho=body.nicho, config=body.config, commit=False,
            )
            if _src:
                # copia del estante con provenance, MISMA txn que el create (atómico)
                puppet["inherited_count"] = repo.inherit_memories(
                    conn, source_puppet_id=_src, dest_puppet_id=puppet["id"],
                    policy=_inh.get("policy", "skill_only"), commit=False)
            conn.commit()
            # D3 · el PUENTE de identidad: exportar la receta a catalog/agents/agent-<uuid>.config.json
            # ahora que el row tiene el UUID server-minted. Side-effect best-effort (el puppet YA está en
            # DB): un fallo de FS NO tumba el guardar — el próximo update re-exporta (idempotente por UUID).
            # FIX F · si el export falló (FS read-only), señalamos bridge_pending para que la UI sepa que el
            # agente todavía NO es delegable (no-fatal: 201 igual).
            if not _export_agent_bridge(puppet):
                puppet["bridge_pending"] = True
            return puppet
        finally:
            conn.close()

    @router.put("/puppets/{puppet_id}/config")
    def update_puppet_config(puppet_id: str, body: PuppetUpdateRequest,
                             authorization: Optional[str] = Header(default=None)):
        """El taller edita la receta: VALIDA y sube version. Inválida ⇒ 422, no se guarda.
        AUTHZ (§4.5, T6): sólo el DUEÑO del puppet edita su receta. Sin esto, cualquiera
        reescribía la receta de otro (modelo/belt/gates/rag.dir) — IDOR de escritura."""
        from app.phase1 import repo
        conn = _conn()
        try:
            # PIEZA MÉTODO · serializa con equipar/desequipar métodos (que hacen
            # read-modify-write del MISMO config): sin el lock compartido, un PUT ciego
            # del taller y un equip concurrente se pisan (update_config reemplaza el
            # config entero, last-write-wins). Mismo key que methods_router.
            # [Casa 2 · 2.4] En el cliente `pg_advisory_xact_lock` no existe y el except lo
            # TRAGABA en silencio → el PUT quedaba SIN serializar (el clobber que el lock
            # existe para evitar). SQLite no tiene advisory locks: BEGIN IMMEDIATE toma el
            # write lock hasta el commit y da la misma serialización (mismo patrón que
            # methods_router._lock_config). El path de control queda byte-idéntico.
            if repo._dbmod().es_cliente():
                conn.raw.execute("BEGIN IMMEDIATE")
            else:
                try:
                    with conn.cursor() as _cur:
                        _cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                                     (f"mrefs:{puppet_id}",))
                except Exception:
                    pass
            owner = repo.puppet_owner(conn, puppet_id)
            if owner is None:
                raise HTTPException(status_code=404, detail=f"puppet '{puppet_id}' no encontrado")
            _authorize(owner, authorization)
            existing_puppet = repo.get_puppet(conn, puppet_id)
            body.config = _canonicalize_saved_config(
                body.config,
                selection_ref=body.model_selection_ref,
                owner_id=str(owner),
                agent_id=puppet_id,
            )
            # Una edición histórica puede llegar con meta.name vacío o técnico. Al guardar,
            # deja persistido el fallback humano y update_config sincroniza la columna name.
            requested_name = agent_catalog.clean_human_name(
                ((body.config.get("meta") or {}).get("name") if isinstance(body.config.get("meta"), dict) else None)
            )
            body.config = agent_catalog.config_with_display_name(
                body.config,
                requested_name or agent_catalog.display_name(
                    (existing_puppet or {}).get("name"), (existing_puppet or {}).get("config"),
                ),
            )
            # FIX-P4 · KIT BASE · el borde de EDICIÓN. El Cuarto reconstruye la receta desde
            # las piezas COLOCADAS, y el kit no es una pieza del diorama: sin esta línea, el
            # primer "Guardar" del taller le arrancaba los brazos al agente. Idempotente.
            body.config, _ = _kit.ensure_kit(body.config)
            try:
                rv.validate_recipe(body.config, repo_root=resource_root)
            except rv.RecipeValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings},
                )
            puppet = repo.update_config(conn, puppet_id, body.config)
            if puppet is None:
                raise HTTPException(status_code=404, detail=f"puppet '{puppet_id}' no encontrado")
            # MÉTODO × CONECTORES: el veredicto pertenece al belt ACTUAL. No se estampa
            # al equipar; cada mutación de receta lo recalcula y lo guarda con P11.
            from app.phase1 import method_match as _method_match
            _states = _method_match.recalculate(
                conn, puppet, owner=str(owner), repo_root=resource_root)
            if _states:
                puppet["method_states"] = _states
            # D3 · re-exportar el puente (idempotente por UUID): el archivo hijo sigue el config editado.
            # FIX F · export fallido (FS read-only) → bridge_pending honesto en la respuesta (no-fatal).
            if not _export_agent_bridge(puppet):
                puppet["bridge_pending"] = True
            return puppet
        finally:
            conn.close()

    @router.delete("/puppets/{puppet_id}")
    def delete_puppet(puppet_id: str,
                      authorization: Optional[str] = Header(default=None)):
        """Delete an agent from the same persisted catalog used by local and synced users.

        The DB row is canonical. Its UUID-keyed catalog export is a derived delegation
        bridge, so remove that first; if the DB mutation then fails, restore the bridge
        from the still-persisted row before returning a readable error.
        """
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = repo.puppet_owner(conn, puppet_id)
            if owner is None:
                raise HTTPException(status_code=404, detail="Agente no encontrado.")
            _authorize(owner, authorization)
            puppet = repo.get_puppet(conn, puppet_id)
            if puppet is None:
                raise HTTPException(status_code=404, detail="Agente no encontrado.")
            try:
                if not agent_catalog.delete_agent_export(puppet_id, repo_root):
                    raise OSError("agent export still exists")
            except Exception:
                _log.warning("No se pudo retirar el export del agente %s", puppet_id,
                             exc_info=True)
                raise HTTPException(status_code=503, detail={
                    "error": "agent_delete_failed",
                    "detail": "No se pudo eliminar el agente. Inténtalo de nuevo.",
                })
            try:
                deleted = repo.delete_puppet(conn, puppet_id, owner_id=str(owner))
            except Exception:
                try:
                    agent_catalog.export_agent(puppet, repo_root)
                except Exception:
                    _log.error("No se pudo restaurar el export tras fallar el borrado %s",
                               puppet_id, exc_info=True)
                _log.warning("No se pudo borrar el agente persistido %s", puppet_id,
                             exc_info=True)
                raise HTTPException(status_code=503, detail={
                    "error": "agent_delete_failed",
                    "detail": "No se pudo eliminar el agente. Inténtalo de nuevo.",
                })
            if not deleted:
                # Otra solicitud pudo borrar la fila mientras esta request retiraba el
                # export; no lo restaures aquí o reaparecería un puente huérfano.
                raise HTTPException(status_code=404, detail="Agente no encontrado.")
            return {"deleted": True, "id": puppet_id}
        finally:
            conn.close()

    # ── Step 2 · A3 · MEMORIA DEL AGENTE · panel CRUD (ver/agregar/editar/borrar/limpiar) ──
    # Lo que se ve = lo que hay (cero memoria oculta). AUTHZ anti-IDOR: sólo el DUEÑO del
    # agente toca su memoria (puppet_owner + _authorize). La FRONTERA (entradas/bytes por
    # tier) la impone el runtime en el write-path — la receta no la sube.
    def _memory_caps(conn, owner_id: Optional[str]) -> dict:
        try:
            import sys as _sys
            _pd = str(resource_root / "platform")
            if _pd not in _sys.path:
                _sys.path.insert(0, _pd)
            from gates.recipe_enforcer import memory_caps_for_tier
            from app.phase1 import repo as _r
            tier = (_r.get_user(conn, owner_id) or {}).get("tier") if owner_id else None
            return memory_caps_for_tier(tier)
        except Exception:
            return {"max_entries": 20, "max_bytes": 8192}   # free (fail-closed hacia el piso)

    def _rag_caps(conn, owner_id: Optional[str]) -> Optional[dict]:
        """Techo de CONOCIMIENTO (docs/bytes) del corpus según el MODO de almacenamiento —
        no según free/premium:
          · self_hosted (DEFAULT = hoy; el corpus vive en el Postgres LOCAL del usuario, su
            propio disco) → None = SIN cap. RAG funcional en free, como la memoria A3.
          · hosted (LATENTE: Aleph corre la DB → Aleph paga storage) → cap por tier de la
            CUENTA del dueño (repo.get_user().tier), NO recipe.tier (display/editable).
        Resuelto server-side vía el mismo shim de sys.path que _memory_caps. Ante cualquier
        fallo devolvemos None = semántica self_hosted (el path de prod local-first)."""
        try:
            import sys as _sys
            _pd = str(resource_root / "platform")
            if _pd not in _sys.path:
                _sys.path.insert(0, _pd)
            from gates.recipe_enforcer import rag_caps_for_tier
            from app.phase1 import repo as _r
            tier = (_r.get_user(conn, owner_id) or {}).get("tier") if owner_id else None
            return rag_caps_for_tier(tier)
        except Exception:
            return None   # self_hosted (sin cap) — el path real hoy

    def _truncate_bytes(s: str, n: int) -> str:
        """Trunca `s` a lo sumo `n` BYTES UTF-8 (no caracteres) en frontera válida. El cap del
        tier es en BYTES; cortar por caracteres dejaría una entrada multibyte por ENCIMA del
        techo, que enforce_memory_caps desalojaría al instante (la memoria recién escrita se
        auto-borraría en silencio)."""
        b = s.encode("utf-8")
        if len(b) <= n:
            return s
        return b[:n].decode("utf-8", "ignore")

    # ── BYO-CLI (D2) · DETECCIÓN HONESTA DE CEREBROS POR SUSCRIPCIÓN ────────────────
    @router.get("/brains/status")
    def brains_status(refresh_claude: bool = False) -> dict:
        """Los providers BYO-CLI del registro único, cada uno con su estado REAL e
        independiente (ready | no_auth | not_installed) + razón honesta. No expone
        nada sensible — jamás tokens: la única interacción con el auth de cada CLI es su
        comando de estado, con cache TTL corto en el detector. El Cuarto pinta la opción
        viva/apagada con esta verdad. `catalog` es la lista de ids/copy para la UI."""
        def _included_status() -> dict:
            try:
                asm = _ap.load_module_by_path(
                    "puppet_recipe_assembler_brain_status",
                    resource_root / "platform" / "assembler" / "recipe_assembler.py",
                )
                if getattr(asm, "_resolve_cognition_key")(resource_root):
                    return {
                        "provider": "included",
                        "state": "ready",
                        "detail": "lane incluida configurada",
                    }
                return {
                    "provider": "included",
                    "state": "not_configured",
                    "detail": "no hay llave de cognición configurada para la lane incluida",
                }
            except Exception as exc:
                return {
                    "provider": "included",
                    "state": "unknown",
                    "detail": f"no pude verificar la lane incluida: {exc.__class__.__name__}",
                }

        try:
            import sys as _sys
            # `assembler.py` también viaja como módulo plano en PyInstaller; importar
            # `assembler.cli_brain` colisiona con ese módulo ("assembler is not a package").
            # Caso 3 ya usa el paquete `cli_brain` desde el directorio del assembler.
            _ad = str(resource_root / "platform" / "assembler")
            if _ad not in _sys.path:
                _sys.path.insert(0, _ad)
            from cli_brain.detect import detect_all, detect_one
            from cli_brain.lifecycle import service_status
            if refresh_claude:
                # El botón Recheck salta la cache sin invocar un turno de Claude.
                detect_one("claude_cli", force_refresh=True)
            # public=True: SIN el path del binario (fingerprinting del host, review LOW #2/#23)
            providers = detect_all(public=True)
            providers["included"] = _included_status()
            from cli_brain.registry import public_catalog
            # Slice C: detectar un CLI autenticado NO basta para decir que la ruta puede
            # ejecutar. La señal compartida incluye la salud REAL del listener local :8926.
            service = service_status()
            for entry in providers.values():
                if entry.get("provider") == "included":
                    continue
                entry["service_state"] = service.get("state", "unknown")
                entry["provider_ready"] = (entry.get("state") == "ready"
                                           and service.get("state") == "ready")
                entry["execution_verified"] = entry.get("last_test_state") == "passed"
            return {"providers": providers, "service": service,
                    "catalog": public_catalog()}
        except Exception as e:
            # fail honesto: sin detección la UI dice "no pude verificar" — jamás finge ready
            return {
                "providers": {"included": _included_status()},
                "service": {
                    "state": "unavailable", "mode": "failed", "managed": False,
                    "detail": f"no pude verificar el servicio CLI: {e.__class__.__name__}",
                },
                "error": f"deteccion no disponible: {e.__class__.__name__}",
            }

    def _cli_configuration_module():
        import sys as _sys
        assembler_dir = str(_ap.resource_root() / "platform" / "assembler")
        if assembler_dir not in _sys.path:
            _sys.path.insert(0, assembler_dir)
        from cli_brain import config as cli_config
        return cli_config

    @router.get("/brains/executables")
    def cli_executables(request: Request,
                        launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
        """Private device settings. Unlike public /brains/status, this reveals local paths."""
        if _es_control_plane():
            raise HTTPException(status_code=404, detail="not found")
        _require_local_session_boundary(request, launch_cap)
        cli_config = _cli_configuration_module()
        from cli_brain.registry import provider_ids
        try:
            from cli_brain.detect import PROVIDERS
            choices = {}
            for pid in provider_ids():
                entry = cli_config.get(pid)
                provider = PROVIDERS[pid]
                resolved, source, error = provider._resolve_binary()
                choices[pid] = {**entry, "resolved_path": resolved or "",
                                "resolution_source": source,
                                "configuration_error": error}
            return {"providers": choices}
        except cli_config.ConfigError as exc:
            raise HTTPException(status_code=409, detail={"error": "config_invalid",
                                                         "detail": str(exc)}) from exc

    @router.put("/brains/executables")
    def save_cli_executable(body: CliExecutableChoice, request: Request,
                            launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
        if _es_control_plane():
            raise HTTPException(status_code=404, detail="not found")
        _require_local_session_boundary(request, launch_cap)
        cli_config = _cli_configuration_module()
        try:
            saved = cli_config.save(body.provider_id, body.mode, body.path)
        except cli_config.ConfigError as exc:
            raise HTTPException(status_code=422, detail={"error": "config_invalid",
                                                         "detail": str(exc)}) from exc
        from cli_brain.detect import invalidate_cache
        invalidate_cache()
        return {"provider_id": body.provider_id, **saved}

    @router.post("/brains/executables/verify")
    def verify_cli_executable(body: CliExecutableChoice, request: Request,
                              launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
        if _es_control_plane():
            raise HTTPException(status_code=404, detail="not found")
        _require_local_session_boundary(request, launch_cap)
        cli_config = _cli_configuration_module()
        try:
            return cli_config.verify_executable(body.provider_id, body.path)
        except cli_config.ConfigError as exc:
            raise HTTPException(status_code=422, detail={"error": "config_invalid",
                                                         "detail": str(exc)}) from exc

    def _mem_gate(conn, puppet_id: str, authorization: Optional[str]) -> str:
        """Owner del agente o 404/401/403. Devuelve el owner_id autorizado."""
        from app.phase1 import repo
        owner = repo.puppet_owner(conn, puppet_id)
        if owner is None:
            raise HTTPException(status_code=404, detail=f"puppet '{puppet_id}' no encontrado")
        _authorize(owner, authorization)
        return owner

    @router.get("/users/{user_id}/memories")
    def list_owner_memories_ep(user_id: str, limit: int = Query(default=500, le=2000),
                               authorization: Optional[str] = Header(default=None)):
        """LO QUE ALEPH SE ACUERDA DE VOS, junto: memoria de agente de TODOS tus agentes.

        EL AGUJERO QUE CIERRA. La memoria funciona desde hace rato —el executor la inyecta
        en el system prompt de CADA turno, en tres sitios (cuenta, agente, compartida)— y
        `executor.py:811` ya le dice al usuario «(+N recuerdo(s) más en tu panel de
        memoria)». Ese panel no existía. Aleph se acordaba de cosas del usuario y el usuario
        no tenía cómo verlas ni cómo sacarlas: memoria invisible y no removible, que es lo
        contrario del control sobre lo propio.

        Casi todo estaba: `GET`/`DELETE` por agente, el gate anti-IDOR, el repo. Lo único
        que faltaba era la vista POR DUEÑO — sin ella el panel serían 190 pedidos, uno por
        agente. Ver `repo.list_owner_memories` para por qué el join es obligatorio.

        NO SE INVENTA UN DELETE NUEVO: cada fila viaja con su `puppet_id` y el panel borra
        por el endpoint que ya existe (`DELETE /v1/puppets/{pid}/memories/{mid}`), que ya
        tiene su `_mem_gate`. Una segunda vía de borrar es una segunda vía de equivocarse.

        AUTHZ: `_authorize(user_id, …)` — el mismo de `/users/{id}/puppets` y `/keys`. La
        memoria de otro no se lista ni se cuenta.
        """
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            mems = repo.list_owner_memories(conn, user_id, limit=limit)
            # La de CUENTA viaja al lado pero MARCADA: es de otro alcance (la leen todos tus
            # agentes) y su DELETE es otro endpoint. Mezclarlas sin distinguir haría creer
            # que borrar una fila del panel las saca de todos lados.
            try:
                cuenta = repo.list_account_memories(conn, user_id, pinned_only=True)
            except Exception:                                    # noqa: BLE001
                cuenta = []
            return {"total": len(mems), "memories": mems,
                    "account": {"total": len(cuenta), "memories": cuenta}}
        finally:
            conn.close()

    @router.get("/puppets/{puppet_id}/memories")
    def list_puppet_memories(puppet_id: str,
                             authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, puppet_id, authorization)
            mems = repo.list_memories(conn, puppet_id)
            # TICKET 26 · verificación de la cita AL LEER (Copilot): cada memoria marca si su run
            # de origen existe de verdad → el panel muestra fuente auditable (✓) o cita colgada (⚠).
            from app.phase1.memory_recall import cite_run_ids, annotate_cite_verification
            annotate_cite_verification(mems, repo.runs_exist(conn, cite_run_ids(mems)))
            usage = repo.memory_usage(conn, puppet_id)
            caps = _memory_caps(conn, owner)
            return {"puppet_id": puppet_id, "total": len(mems),
                    "usage": usage, "caps": caps, "memories": mems}
        finally:
            conn.close()

    @router.get("/puppets/{puppet_id}/shelf")
    def puppet_memory_shelf(puppet_id: str,
                            authorization: Optional[str] = Header(default=None)):
        """ORDEN 4 · el ESTANTE del agente agrupado para el SELECTOR de herencia/composición:
        pericia / proyectos (episódica por run) / sueltas. Excluye lo confidencial (no elegible).
        SÓLO memoria de AGENTE (A3): la de cuenta jamás es elegible acá. AUTHZ anti-IDOR: _mem_gate."""
        from app.phase1 import repo
        from app.phase1.memory_recall import group_shelf
        conn = _conn()
        try:
            _mem_gate(conn, puppet_id, authorization)
            grouped = group_shelf(repo.list_memories(conn, puppet_id))
            return {"puppet_id": puppet_id,
                    "skill": grouped["skill"], "projects": grouped["projects"],
                    "loose": grouped["loose"]}
        finally:
            conn.close()

    @router.post("/puppets/{puppet_id}/memories", status_code=201)
    def add_puppet_memory(puppet_id: str, body: MemoryWriteRequest,
                          authorization: Optional[str] = Header(default=None)):
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(status_code=422,
                detail={"error": "empty_content", "detail": "La memoria no puede estar vacía."})
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, puppet_id, authorization)
            caps = _memory_caps(conn, owner)
            content = _truncate_bytes(content, int(caps["max_bytes"]))   # entrada ≤ techo (bytes)
            mem = repo.add_memory(conn, puppet_id=puppet_id, content=content,
                                  source="user", pinned=True)
            repo.enforce_memory_caps(conn, puppet_id,
                max_entries=int(caps["max_entries"]), max_bytes=int(caps["max_bytes"]))
            return mem
        finally:
            conn.close()

    @router.patch("/puppets/{puppet_id}/memories/{memory_id}")
    def update_puppet_memory(puppet_id: str, memory_id: str, body: MemoryWriteRequest,
                             authorization: Optional[str] = Header(default=None)):
        """Edita el contenido y/o RECLASIFICA (op 3: meta.kind skill↔episodica). Acepta
        content, kind, o ambos; sin ninguno → 422. AUTHZ anti-IDOR: _mem_gate (401 sin
        sesión · 403 ajeno · 404 memoria de otro puppet == inexistente, sin oráculo)."""
        content = (body.content or "").strip()
        kind = (body.kind or "").strip().lower() or None
        if kind is not None and kind not in ("skill", "episodica"):
            raise HTTPException(status_code=422,
                detail={"error": "invalid_kind", "detail": "kind debe ser 'skill' o 'episodica'."})
        if not content and kind is None:
            raise HTTPException(status_code=422,
                detail={"error": "empty_content", "detail": "La memoria no puede estar vacía."})
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, puppet_id, authorization)
            m = repo.get_memory(conn, memory_id)
            if not m or str(m.get("puppet_id")) != str(puppet_id):
                raise HTTPException(status_code=404, detail="memoria no encontrada")
            mem = m
            if content:
                caps = _memory_caps(conn, owner)
                mem = repo.update_memory(conn, memory_id, content=_truncate_bytes(content, int(caps["max_bytes"])))
                repo.enforce_memory_caps(conn, puppet_id,
                    max_entries=int(caps["max_entries"]), max_bytes=int(caps["max_bytes"]))
            if kind is not None:
                mem = repo.reclassify_memory(conn, memory_id, kind)
            return mem
        finally:
            conn.close()

    @router.delete("/puppets/{puppet_id}/memories/{memory_id}")
    def delete_puppet_memory(puppet_id: str, memory_id: str,
                             authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            _mem_gate(conn, puppet_id, authorization)
            m = repo.get_memory(conn, memory_id)
            if not m or str(m.get("puppet_id")) != str(puppet_id):
                raise HTTPException(status_code=404, detail="memoria no encontrada")
            return {"deleted": repo.delete_memory(conn, memory_id)}
        finally:
            conn.close()

    @router.delete("/puppets/{puppet_id}/memories")
    def clear_puppet_memories(puppet_id: str,
                              authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            _mem_gate(conn, puppet_id, authorization)
            return {"cleared": repo.clear_memories(conn, puppet_id)}
        finally:
            conn.close()

    # ── Step 2 · B2 · MEMORIA COMPARTIDA del Cuarto · panel CRUD por COMPOSICIÓN ──
    # La composición = el Cuarto GUARDADO = un puppet top-level (composition_id = puppets.id) →
    # el owner y los caps se resuelven IGUAL que A3 (_mem_gate = puppet_owner, _memory_caps). Cada
    # entrada muestra su AUTOR (author_label). AUTHZ anti-IDOR: sólo el dueño del Cuarto ve/edita
    # su memoria compartida; una entrada de OTRA composición no matchea (chequeo composition_id).
    # La escritura del panel es del USUARIO (source='user', autor='Vos'); la de los agentes entra
    # server-side por el executor (destilado), nunca por acá.
    @router.get("/compositions/{composition_id}/memories")
    def list_composition_memories(composition_id: str,
                                  authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)
            mems = repo.list_shared_memories(conn, composition_id)
            usage = repo.shared_memory_usage(conn, composition_id)
            caps = _memory_caps(conn, owner)
            return {"composition_id": composition_id, "total": len(mems),
                    "usage": usage, "caps": caps, "memories": mems}
        finally:
            conn.close()

    @router.post("/compositions/{composition_id}/memories", status_code=201)
    def add_composition_memory(composition_id: str, body: MemoryWriteRequest,
                               authorization: Optional[str] = Header(default=None)):
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(status_code=422,
                detail={"error": "empty_content", "detail": "La nota compartida no puede estar vacía."})
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)
            caps = _memory_caps(conn, owner)
            content = _truncate_bytes(content, int(caps["max_bytes"]))   # entrada ≤ techo (bytes)
            mem = repo.add_shared_memory(conn, composition_id=composition_id, content=content,
                                         author_agent_id=owner, author_label="Tú",
                                         source="user", pinned=True)
            repo.enforce_shared_memory_caps(conn, composition_id,
                max_entries=int(caps["max_entries"]), max_bytes=int(caps["max_bytes"]))
            return mem
        finally:
            conn.close()

    @router.patch("/compositions/{composition_id}/memories/{memory_id}")
    def update_composition_memory(composition_id: str, memory_id: str, body: MemoryWriteRequest,
                                  authorization: Optional[str] = Header(default=None)):
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(status_code=422,
                detail={"error": "empty_content", "detail": "La nota compartida no puede estar vacía."})
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)
            m = repo.get_shared_memory(conn, memory_id)
            if not m or str(m.get("composition_id")) != str(composition_id):
                raise HTTPException(status_code=404, detail="nota compartida no encontrada")
            caps = _memory_caps(conn, owner)
            mem = repo.update_shared_memory(conn, memory_id,
                content=_truncate_bytes(content, int(caps["max_bytes"])))
            repo.enforce_shared_memory_caps(conn, composition_id,
                max_entries=int(caps["max_entries"]), max_bytes=int(caps["max_bytes"]))
            return mem
        finally:
            conn.close()

    @router.delete("/compositions/{composition_id}/memories/{memory_id}")
    def delete_composition_memory(composition_id: str, memory_id: str,
                                  authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            _mem_gate(conn, composition_id, authorization)
            m = repo.get_shared_memory(conn, memory_id)
            if not m or str(m.get("composition_id")) != str(composition_id):
                raise HTTPException(status_code=404, detail="nota compartida no encontrada")
            return {"deleted": repo.delete_shared_memory(conn, memory_id)}
        finally:
            conn.close()

    @router.delete("/compositions/{composition_id}/memories")
    def clear_composition_memories(composition_id: str,
                                   authorization: Optional[str] = Header(default=None)):
        from app.phase1 import repo
        conn = _conn()
        try:
            _mem_gate(conn, composition_id, authorization)
            return {"cleared": repo.clear_shared_memories(conn, composition_id)}
        finally:
            conn.close()

    @router.post("/compositions/{composition_id}/seed", status_code=200)
    def seed_composition_bus(composition_id: str, body: BusSeedRequest,
                             authorization: Optional[str] = Header(default=None)):
        """ORDEN 4 · COMPOSICIÓN — sembrar el bus del Cuarto con memorias ELEGIDAS de agentes del
        dueño (préstamo con procedencia, sin tocar el origen). El servicio valida dueño (anti-IDOR),
        excluye confidencial, y RECHAZA estructuralmente cualquier id que no sea de agent_memories
        (una id de cuenta cae en 'not_found' → la memoria de cuenta jamás se siembra a un bus).
        AUTHZ anti-IDOR: _mem_gate(composition_id) resuelve el DUEÑO del Cuarto = owner autorizado."""
        ids = list(body.memory_ids or [])
        if len(ids) > _SEED_MAX_IDS:   # cota anti auto-DoS (una request no dispara trabajo ilimitado)
            raise HTTPException(status_code=422, detail={
                "error": "too_many_ids",
                "detail": f"Máximo {_SEED_MAX_IDS} memorias por seed; recibí {len(ids)}."})
        from app.phase1 import repo
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)
            caps = _memory_caps(conn, owner)
            result = repo.seed_shared_bus(
                conn, composition_id=composition_id, owner_id=owner, memory_ids=ids,
                max_entries=int(caps["max_entries"]), max_bytes=int(caps["max_bytes"]))
            return {"composition_id": composition_id,
                    "seeded_count": len(result["seeded"]),
                    "seeded": result["seeded"], "skipped": result["skipped"],
                    # honestidad del cap: lo recién sembrado que el techo desalojó + total desalojado
                    "evicted_seeded": result.get("evicted_seeded", []),
                    "evicted_total": result.get("evicted_total", 0)}
        finally:
            conn.close()

    # ── Step 2 · C1 · CONOCIMIENTO (RAG) del Cuarto · corpus por COMPOSICIÓN ──────
    # El átomo Conocimiento: subís documentos (txt/md/pdf/docx) → se trocean, se embeben con
    # TU llave BYOK (nunca la de Aleph) y se indexan con coseno en Python puro ($0, sin pgvector).
    # AUTHZ anti-IDOR: _mem_gate (=puppet_owner del Cuarto) en CADA endpoint; un doc de OTRA
    # composición nunca matchea (cross-check doc.composition_id). La FRONTERA (docs/bytes) sólo
    # existe en modo `hosted` (Aleph corre la DB); en self_hosted (hoy, disco del usuario) NO hay
    # cap. La llave BYOK se resuelve SERVER-SIDE y JAMÁS aparece en una respuesta ni en un log.
    @router.get("/compositions/{composition_id}/knowledge")
    def list_knowledge(composition_id: str,
                       authorization: Optional[str] = Header(default=None)):
        from app.phase1 import knowledge_store
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)   # anti-IDOR FIRST
            # el backend (sqlite-file self_hosted / Postgres hosted) lo elige get_store
            store = knowledge_store.get_store(conn=conn, composition_id=composition_id)
            docs = store.list_docs()                                 # panel: sin embeddings/cuerpo
            usage = store.usage()
            caps = _rag_caps(conn, owner)   # None en self_hosted (sin cap)
            return {"composition_id": composition_id, "total": len(docs),
                    "usage": usage, "caps": caps, "docs": docs}
        finally:
            conn.close()

    @router.post("/compositions/{composition_id}/knowledge", status_code=201)
    def upload_knowledge(composition_id: str, body: KnowledgeUploadRequest,
                         authorization: Optional[str] = Header(default=None)):
        from app.phase1 import knowledge_store, rag_index
        conn = _conn()
        try:
            owner = _mem_gate(conn, composition_id, authorization)   # anti-IDOR FIRST
            # backend elegido server-side (sqlite-file self_hosted / Postgres hosted)
            store = knowledge_store.get_store(conn=conn, composition_id=composition_id)

            # --- validar/decodificar el payload (recién DESPUÉS de autorizar) -----------
            name = (body.name or "").strip()
            if not name:
                raise HTTPException(status_code=422,
                    detail={"error": "empty_name", "detail": "El documento necesita un nombre."})
            raw: Any = None
            if body.content_b64:
                import base64 as _b64
                try:
                    raw = _b64.b64decode(body.content_b64, validate=False)
                except Exception:
                    raise HTTPException(status_code=422,
                        detail={"error": "bad_base64", "detail": "El contenido base64 no es válido."})
            elif body.text is not None:
                raw = body.text
            if raw is None or len(raw) == 0:
                raise HTTPException(status_code=422,
                    detail={"error": "empty_content", "detail": "El documento está vacío."})
            new_bytes = len(raw) if isinstance(raw, (bytes, bytearray)) else len(raw.encode("utf-8"))

            # --- FRONTERA (sólo hosted; self_hosted → caps None → sin chequeo) -----------
            caps = _rag_caps(conn, owner)
            if caps is not None:
                usage = store.usage()
                over_docs = (usage["doc_count"] + 1) > int(caps["max_docs"])
                over_bytes = (usage["total_bytes"] + new_bytes) > int(caps["max_bytes"])
                if over_docs or over_bytes:
                    msg = (f"El corpus de conocimiento de tu plan llegó al tope "
                           f"({caps['max_docs']} documentos / {caps['max_bytes'] // 1_000_000} MB). "
                           f"Para indexar más documentos necesitas mejorar tu plan.")
                    return JSONResponse(status_code=413, content={
                        "error": msg,
                        "upsell": {"feature": "rag_capacity", "min_tier": "basico"},
                        "usage": usage, "caps": caps,
                    })

            # --- write-path server-side: rollback en CUALQUIER excepción (no zombifica) --
            doc_id = None
            try:
                doc_id = store.add_doc(
                    doc_name=name, mime=body.mime, bytes=new_bytes, sha256=None, meta={})

                # 1) extraer texto (txt/md/pdf/docx) — doc malo → status='error' honesto
                try:
                    text = rag_index.extract_text(name, body.mime, raw)
                except rag_index.RagIngestError as exc:
                    reason = f"ingest: {exc}"
                    store.set_status(doc_id, "error", error=reason)
                    return JSONResponse(status_code=422, content={
                        "doc_id": doc_id, "status": "error", "error": reason,
                        "message": "No pudimos extraer texto real de ese documento.",
                        "docs": store.list_docs()})
                sha = rag_index.sha256_text(text)
                chunks = rag_index.chunk_text(text)

                # 2) llave BYOK del DUEÑO (server-side; NUNCA a la respuesta ni al log)
                provider = rag_index.pick_embed_provider(owner)
                key = rag_index.resolve_embed_key(owner, provider) if provider else None
                if not key:
                    honest = ("Para indexar este documento conecta tu propia llave de embeddings "
                              "(OpenAI o Gemini) en Conexiones. Aleph no usa su llave para tu corpus.")
                    store.set_status(doc_id, "error_no_key", error=honest)
                    return JSONResponse(status_code=424, content={
                        "doc_id": doc_id, "status": "error_no_key", "error": honest,
                        "message": honest,
                        "docs": store.list_docs()})

                # 3) embeber (el provider fija model/dim/base_url) — fallo de proveedor = honesto
                defs = rag_index.embed_defaults_for(provider)
                try:
                    vectors = rag_index.embed_texts(
                        [c for _, c, _ in chunks], provider=provider,
                        model=defs["model"], api_key=key, base_url=defs["base_url"])
                except rag_index.RagEmbedError as exc:
                    reason = str(exc)
                    if reason.startswith("no_api_key") or reason.startswith("no_base_url"):
                        honest = ("Para indexar este documento conecta tu propia llave de embeddings "
                                  "(OpenAI o Gemini) en Conexiones. Aleph no usa su llave para tu corpus.")
                        store.set_status(doc_id, "error_no_key", error=honest)
                        return JSONResponse(status_code=424, content={
                            "doc_id": doc_id, "status": "error_no_key", "error": honest,
                            "message": honest,
                            "docs": store.list_docs()})
                    store.set_status(doc_id, "error", error=f"embed: {reason}")
                    return JSONResponse(status_code=502, content={
                        "doc_id": doc_id, "status": "error", "error": f"embed: {reason}",
                        "message": "El proveedor de embeddings falló. Vuelve a intentar.",
                        "docs": store.list_docs()})

                # 4) persistir chunks (embedding 1:1) + sellar 'indexed' con la guarda de drift
                n = 0
                for (ix, content, char_start), vec in zip(chunks, vectors):
                    store.add_chunk(
                        doc_id=doc_id, chunk_ix=ix, content=content,
                        bytes=len(content.encode("utf-8")), embedding=vec,
                        meta={"doc_name": name, "chunk_ix": ix,
                              "char_start": char_start, "sha256": sha})
                    n += 1
                store.set_status(doc_id, "indexed", error=None,
                    embed_provider=provider, embed_model=defs["model"],
                    embed_dim=int(defs["dim"]), n_chunks=n)

                # 5) frontera hosted: desalojo por prefijo (self_hosted → no-op → skip)
                if caps is not None:
                    store.enforce_caps(int(caps["max_docs"]), int(caps["max_bytes"]))

                return {"doc_id": doc_id, "status": "indexed", "n_chunks": n,
                        "provider": provider, "dim": int(defs["dim"]),
                        "docs": store.list_docs()}
            except HTTPException:
                raise
            except Exception as exc:
                conn.rollback()   # LOAD-BEARING: transacción abierta → conn zombie si no
                raise HTTPException(status_code=500,
                    detail={"error": "index_failed", "detail": str(exc)})
        finally:
            conn.close()

    @router.delete("/compositions/{composition_id}/knowledge/{doc_id}")
    def delete_knowledge(composition_id: str, doc_id: str,
                         authorization: Optional[str] = Header(default=None)):
        from app.phase1 import knowledge_store
        conn = _conn()
        try:
            _mem_gate(conn, composition_id, authorization)   # anti-IDOR FIRST
            store = knowledge_store.get_store(conn=conn, composition_id=composition_id)
            doc = store.get_doc(doc_id)   # self_hosted inyecta composition_id → cross-check uniforme
            if not doc or str(doc.get("composition_id")) != str(composition_id):
                raise HTTPException(status_code=404, detail="documento no encontrado")
            return {"deleted": store.delete_doc(doc_id)}   # CASCADE → chunks
        finally:
            conn.close()

    # ── (a) BYOK storage (cifrada; nunca devuelve el secreto) ─────────────────
    @router.post("/keys", status_code=200)
    def upsert_key(body: KeyUpsertRequest,
                   authorization: Optional[str] = Header(default=None)):
        """[F7·A] LA PUERTA QUE SALTEABA LA VALIDACIÓN — ahora delega en `agregar_key`.

        LO QUE ESTABA MAL, medido el 2026-08-06 contra la app instalada:

            POST /v1/keys {"provider":"groq","secret":"basura-total-que-no-es-una-llave"}
              → HTTP 200 · guardada

        Escribía directo con `repo.upsert_key`: sin guard de forma, sin validador, sin
        prueba dura, sin sembrar el motor y sin espejar el registro. Y ES LA PUERTA QUE
        USAN DOS SUPERFICIES —**Ajustes** (`Settings.dc.html:407`) y **brain-setup**
        (`brain-setup.html:117`)—, así que una llave inventada entraba al vault, aparecía
        en Modelos con `hay_llave:true`, el selector la OFRECÍA como cerebro en el Cuarto y
        en la Sala, y el llavero la marcaba `verified:true`. Cuatro superficies mintiendo
        por una puerta.

        Ahora es la MISMA función que usan Modelos y Conectores (`centro_conexiones.
        agregar_key`): valida contra el proveedor con el validador discriminante de F7,
        guarda sólo si corresponde, siembra el veredicto en el motor y espeja el registro.

        ⚠️ **EL CONTRATO HTTP CAMBIA A PROPÓSITO, y es lo que arregla las dos pantallas sin
        tocarlas**: una llave rechazada devuelve **422**, no 200. Las dos ya hacen
        `if (!r.ok) { …no se pudo guardar… }`; con 200 «exitoso» sobre una llave rechazada
        seguirían mostrando éxito. El cuerpo del 422 lleva la causa TIPADA para quien la
        quiera pintar.

        Lo que NO cambia: el 200 devuelve el mismo dict de `repo.upsert_key`
        (`id/user_id/provider/last4/enc_scheme/created_at`) — los consumidores que sólo
        miran `r.ok` o `last4` siguen igual.
        """
        _authorize(body.user_id, authorization)
        from app.phase1 import repo
        from app.phase1.centro_conexiones import agregar_key

        res = agregar_key(body.provider, body.secret, owner=body.user_id,
                          get_conn=_conn, guardar_igual=False)
        if not res.get("guardada"):
            raise HTTPException(status_code=422, detail={
                "error": "key_rechazada",
                "causa": res.get("causa"),
                "estado": res.get("estado"),
                "detail": res.get("mensaje"),
                "provider": body.provider,
                "puede_guardar_igual": bool(res.get("puede_guardar_igual")),
            })
        # Se devuelve la fila REAL del vault (no un eco del body): es el contrato que ya
        # tenían los consumidores, y de paso confirma que lo guardado existe.
        conn = _conn()
        try:
            for k in repo.list_keys(conn, body.user_id):
                if (k.get("provider") or "").lower() == body.provider.strip().lower():
                    return {**k, "estado": res.get("estado"), "prueba": res.get("prueba")}
        finally:
            conn.close()
        return {"provider": body.provider, "last4": res.get("last4"),
                "estado": res.get("estado"), "prueba": res.get("prueba")}

    @router.get("/users/{user_id}/keys")
    def list_keys(user_id: str, authorization: Optional[str] = Header(default=None)):
        """Metadatos de las keys (provider + last4 + verified). JAMÁS el secreto.

        `verified`: ¿la llave se validó DURO al conectar? GENÉRICO — derivado de
        `validate.soft` del objeto del conector: soft=true (no se puede validar la key,
        ej. Alpha Vantage) → verified:false → el badge va ámbar. Sin objeto o sin soft
        → verified:true → verde (los 13 conectores existentes quedan IGUAL). Cero
        hardcode por-conector: misma lógica que `connected_unverified` en el motor."""
        _authorize(user_id, authorization)
        import json as _j
        from app.phase1 import repo
        onb = resource_root / "catalog" / "connectors" / "onboarding"

        def _verified(provider: str) -> bool:
            try:
                p = onb / f"{provider}.json"
                if not p.exists():
                    return True
                obj = _j.loads(p.read_text(encoding="utf-8"))
                return not bool((obj.get("validate") or {}).get("soft"))
            except Exception:
                return True

        # [F7·A] `verified` SALE DEL MOTOR, no de la existencia de la fila.
        #
        # LO QUE ESTABA MAL, medido: una llave basura guardada por esta misma API salía
        # `verified: True` en el llavero de Ajustes. `_verified` de arriba no mira NINGUNA
        # medición: mira si la ficha del conector declara `validate.soft`, o sea si el
        # conector es validable EN PRINCIPIO. Eso responde «¿se podría validar?», no «¿se
        # validó?» — y el llavero pintaba la segunda con la respuesta de la primera.
        #
        # Ahora manda el veredicto del motor de verdad (el mismo que pinta Modelos y
        # Conectores) y `_verified` queda como TECHO: un conector declarado `soft` no puede
        # ponerse verde ni aunque alguien le siembre un veredicto. Verde con evidencia o
        # nada — y ahora la fila además dice CUÁL evidencia y de CUÁNDO.
        from app.phase1 import motor_verdad as _MV
        conn = _conn()
        try:
            keys = repo.list_keys(conn, user_id)
            for k in keys:
                prov = (k.get("provider") or "").lower()
                try:
                    res = _MV.estado(_MV.KEY, prov, owner=user_id)
                except Exception:                       # noqa: BLE001 — leer no tumba el llavero
                    res = {}
                medido = bool(res.get("cacheado")) and not (
                    res.get("evidencia") or {}).get("nunca_probado")
                k["estado"] = res.get("estado") or "detectado"
                k["causa"] = res.get("causa")
                k["medido_en"] = res.get("ts") if medido else None
                k["verified"] = bool(
                    medido and res.get("estado") == _MV.PROBADO and _verified(prov))
            return {"keys": keys}
        finally:
            conn.close()

    @router.delete("/users/{user_id}/keys/{provider}", status_code=200)
    def delete_key(user_id: str, provider: str,
                   authorization: Optional[str] = Header(default=None)):
        """Quita una key BYOK del usuario. Devuelve {deleted: bool}."""
        _authorize(user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            return {"deleted": repo.delete_key(conn, user_id, provider)}
        finally:
            conn.close()

    # ── DOC-RAG v0: memoria del agente (docs .md/.txt → rag_dir → _load_rag) ────
    # La carpeta es por (user_id de la SESIÓN, agent_key). Aislamiento estricto: authz
    # por dueño + nombres sanitizados en rag_store (anti-traversal). El toggle de memoria
    # y el rag.dir los arma el taller; acá solo guardamos/listamos/borramos los archivos.
    @router.get("/users/{user_id}/rag/{agent_key}")
    def list_rag(user_id: str, agent_key: str,
                 authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import rag_store
        return {"docs": rag_store.list_docs(user_id, agent_key),
                "rag_dir": rag_store.rel_dir(user_id, agent_key)}

    @router.post("/users/{user_id}/rag/{agent_key}", status_code=201)
    def upload_rag(user_id: str, agent_key: str, body: RagDocRequest,
                   authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import rag_store
        _name = body.name
        _content = body.content
        # TICKET 32 · INGESTA RICA (markitdown): un binario (PDF/Excel/Word/…) llega en content_b64;
        # lo convertimos a MARKDOWN antes de indexar (el RAG es texto). El nombre pasa a .md. Si
        # markitdown no está o falla, error HONESTO (jamás guarda basura binaria como si fuera texto).
        if body.content_b64 and not _content:
            import base64 as _b64, tempfile as _tmp, os as _os
            try:
                _raw = _b64.b64decode(body.content_b64)
            except Exception:
                raise HTTPException(status_code=400, detail={"error": "bad_base64"})
            try:
                from markitdown import MarkItDown
            except Exception:
                raise HTTPException(status_code=501, detail={
                    "error": "markitdown_unavailable",
                    "detail": "conversión de PDF/Excel/Word no disponible en este server (markitdown)."})
            _ext = _os.path.splitext(_name)[1] or _rag_ext_for_mime(body.mime)
            _fd, _path = _tmp.mkstemp(suffix=_ext)
            try:
                with _os.fdopen(_fd, "wb") as _f:
                    _f.write(_raw)
                _md = MarkItDown().convert(_path).text_content or ""
            except Exception as exc:
                raise HTTPException(status_code=422, detail={
                    "error": "convert_failed",
                    "detail": f"no pude convertir «{_name}» a markdown: {type(exc).__name__}"})
            finally:
                try: _os.unlink(_path)
                except Exception: pass
            if not _md.strip():
                raise HTTPException(status_code=422, detail={
                    "error": "empty_after_convert",
                    "detail": f"«{_name}» no produjo texto (¿escaneado/imagen sin OCR?)."})
            _content = _md
            _base, _e = _os.path.splitext(_name)
            _name = _base + ".md"          # se indexa como markdown
        if not _content:
            raise HTTPException(status_code=400, detail={"error": "empty_doc"})
        doc = rag_store.save_doc(user_id, agent_key, _name, _content)
        return {"doc": doc, "docs": rag_store.list_docs(user_id, agent_key),
                "rag_dir": rag_store.rel_dir(user_id, agent_key), "converted": bool(body.content_b64)}

    @router.get("/users/{user_id}/rag/{agent_key}/{name}")
    def read_rag(user_id: str, agent_key: str, name: str,
                 authorization: Optional[str] = Header(default=None)):
        """Contenido de UN doc del agente (para enganchar @doc al contexto del run).
        Authz por dueño; anti-traversal en rag_store."""
        _authorize(user_id, authorization)
        from app.phase1 import rag_store
        content = rag_store.read_doc(user_id, agent_key, name)
        if content is None:
            raise HTTPException(status_code=404, detail={"error": "doc_not_found", "detail": name})
        return {"name": name, "content": content}

    @router.delete("/users/{user_id}/rag/{agent_key}/{name}", status_code=200)
    def delete_rag(user_id: str, agent_key: str, name: str,
                   authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import rag_store
        return {"deleted": rag_store.delete_doc(user_id, agent_key, name),
                "docs": rag_store.list_docs(user_id, agent_key)}

    # ── (a) runs (storage de ejecuciones) ─────────────────────────────────────
    @router.post("/runs", status_code=201)
    def create_run(body: RunCreateRequest,
                   authorization: Optional[str] = Header(default=None)):
        """AUTHZ (§4.5, T6): si el run se atribuye a un user, debe ser el de la sesión —
        nadie forja runs (ni costo) a nombre de otro. Run anónimo (sin user_id) se permite."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import repo
        conn = _conn()
        try:
            return repo.create_run(
                conn, puppet_id=body.puppet_id, user_id=body.user_id,
                space_id=body.space_id, intent=body.intent,
            )
        finally:
            conn.close()

    # ── [FIX-P10 §1] ¿quedó un turno en vuelo… o cortado? ─────────────────────
    @router.get("/runs/estado", status_code=200)
    def estado_de_turnos(authorization: Optional[str] = Header(default=None)):
        """EVIDENCIA, NO PERMISO. Le dice al front tres cosas del dueño de la sesión:

          · `vivo`      — un run que ESTE proceso está corriendo ahora mismo (late).
          · `huerfanos` — filas 'running' sin motor detrás: el registro mintiendo.
          · `cortado`   — el último turno que quedó a medias, para el aviso honesto.

        La ley del composer (FIX-P10 §1b) es que NADA de esto bloquea el envío: un run
        viejo no puede volver a dejar mudo al chat. Por eso el endpoint no devuelve un
        booleano de permiso — devuelve hechos.
        """
        from app.phase1 import authz
        user_id = authz.require_actor(authorization)
        if user_id is None:
            raise HTTPException(status_code=401, detail={
                "error": "no_session",
                "detail": "Inicia sesión para continuar.",
            })
        from app.phase1 import run_lifecycle as _rl
        conn = _conn()
        try:
            return _rl.estado_del_turno(conn, user_id)
        finally:
            conn.close()

    # ── (d) instrumentación: liga los 5 campos por run_id ─────────────────────
    @router.post("/runs/{run_id}/instrument", status_code=201)
    def instrument_run(run_id: str, body: InstrumentRequest,
                       authorization: Optional[str] = Header(default=None)):
        """
        Escribe LA fila del moat: liga por run_id intent+belt+trayectoria+senal+costo.
        La trayectoria llega armada, o se reconstruye de `events` (los del loop).
        AUTHZ (§4.5, T6): si el run TIENE dueño, sólo él escribe su instrumentación/costo
        (nadie contamina el moat ni el ledger de costo de otro). Run anónimo → abierto.
        """
        from app.phase1 import instrumentation as instr, repo as _repo
        conn0 = _conn()
        try:
            _owner = _repo.run_owner(conn0, run_id)
        finally:
            conn0.close()
        _authorize_resource(_owner, authorization)
        trayectoria = body.trayectoria
        if trayectoria is None and body.events is not None:
            trayectoria = instr.build_trayectoria(body.events)
        if trayectoria is None:
            trayectoria = []
        conn = _conn()
        try:
            log_id = instr.persist_run(
                conn, run_id=run_id, intent=body.intent, belt=body.belt,
                trayectoria=trayectoria, senal=body.senal, costo=body.costo,
            )
            return {"instrumentation_log_id": log_id, "run_id": run_id,
                    "steps": len(trayectoria)}
        finally:
            conn.close()

    # ── RUN-EXECUTOR: corre un puppet E2E por el path de PROD ─────────────────
    @router.post("/puppets/run", status_code=201)
    def run_puppet(body: RunPuppetRequest,
                   authorization: Optional[str] = Header(default=None)):
        """
        Corre UN puppet end-to-end: receta (anidada, validada) → assembler resuelve
        belt_ref → build_enforced_gate(recipe) EN EL PATH → modelo OSS opera el belt
        → persiste el run + instrumentation_logs (5 campos ligados por run_id) en
        Postgres. Devuelve el run_id, el id de la fila del moat, y el RUN RECORD
        completo (evidencia: belt resuelto, tools cableadas, gate_decisions, ruta de
        modelo). El gate SIEMPRE está en el camino; money/send caen a needs_ok aunque
        la receta los apague (§3.5). MONEY-TOUCH OFF: sin callback approve, una tool
        needs_ok NO se ejecuta — se registra la decisión del gate y el run sigue.
        """
        _obs.marca("run.entra")
        if body.user_id:  # si el run se atribuye a un user, debe ser el de la sesión
            _authorize(body.user_id, authorization)
        from app.phase1 import executor, repo as _repo

        # [UX·A1] chat persistente: valida dueño, registra el turno del usuario y trae
        # el historial real del hilo (se antepone al prompt DEL CEREBRO; intent queda crudo)
        _chat = _chat_gate(body, authorization)
        _obs.marca("run.chat_gate")
        _replay = _chat_replay_answer(_chat)
        if _replay is not None:
            return _replay

        recipe = body.recipe
        # [LEY 15] Mismo discriminante que run/stream (`router.py`, `raw_mode`): sin agente
        # guardado y sin receta inline, este turno es EL PISO DE LA SALA. Se calcula ANTES
        # de tocar `recipe` porque abajo el borde raw la rellena con la proyección efímera.
        raw_mode = not body.puppet_id and recipe is None
        _obs.marca("run.pre_receta", raw=raw_mode)
        # Un run con identidad de agente SIEMPRE valida el dueño, incluso cuando La Sala
        # manda una copia de la receta con overrides de sesión. Así conserva memoria/chat
        # por puppet_id sin convertir la receta inline en un bypass de ownership.
        if body.puppet_id:
            # [audit superficie · H3] Cargar una receta GUARDADA (por puppet_id) EXIGE ser
            # su dueño. Antes get_puppet no filtraba owner y `run` sólo autorizaba
            # `if body.user_id`: quien conociera un puppet_id ajeno lo corría SIN sesión,
            # gastando cognición/tools a costa de Aleph (la línea roja #1 del negocio).
            # Una `recipe` INLINE anónima es tu propia receta ad-hoc y sigue permitida (no
            # toca datos de nadie; los tests y el e2e dependen de ese camino). La frontera:
            # inline = tuya · puppet_id = de alguien, y ese alguien tenés que ser vos.
            _runner = _repo.session_owner(_bearer(authorization))
            if not _runner:
                raise HTTPException(status_code=401, detail={
                    "error": "no_session",
                    "detail": "Correr un agente guardado necesita tu sesión."})
            conn = _conn()
            try:
                puppet = _repo.get_puppet(conn, body.puppet_id)
            finally:
                conn.close()
            # Ajeno == 404, indistinguible de inexistente (anti-IDOR: no se confirma que
            # el puppet existe si no es tuyo).
            if puppet is None or str(puppet.get("owner_id")) != str(_runner):
                raise HTTPException(status_code=404, detail=f"puppet '{body.puppet_id}' no encontrado")
            if recipe is None:
                # FIX-P4 · KIT BASE · borde de CORRIDA por puppet_id. La Sala normalmente manda
                # su copia de la receta (que YA salió del GET normalizado), pero un run que sólo
                # trae puppet_id lee el config crudo de la DB: un agente viejo que nunca pasó por
                # el GET correría sin brazos. Acá NO se persiste (el GET es el dueño del backfill):
                # esto es completar en memoria lo que va a correr. Idempotente.
                recipe, _ = _kit.ensure_kit(puppet["config"])
        elif recipe is None:
            # [LEY 15 · MODO RAW · borde de OBRA] EL PISO DE LA SALA, CON MANOS.
            #
            # El gemelo de `chat.raw` (run/stream), y por el mismo motivo: sin agente el
            # turno entra por el MISMO selector canónico, con `agent_id=None`. Lo que
            # agrega este borde es el CINTURÓN — hasta acá el piso era el único estado
            # del producto sin brazos, y de eso colgaban por dependencia la ejecución de
            # código, leer un adjunto, que naciera una obra y las tools del cliente.
            #
            # LA LEY SE RESPETA ENTERA, y conviene decir POR QUÉ cada mitad:
            #   · NO SE FABRICA RECETA v1. `recipe` acá es la MISMA proyección efímera que
            #     usa el stream (`{"model": …}`), más un `belt` vacío para que `ensure_kit`
            #     tenga dónde escribir. No pasa por `validate_recipe` (ver el `raw_mode`
            #     de abajo) porque no es una receta: es la configuración de ESTE turno.
            #     Medido: el motor no la valida — `executor.py:469` lee `recipe.get("belt")
            #     or {}` con guardas y no llama al validador. La validación es puerta del
            #     ROUTER, no requisito del ejecutor.
            #   · NO SE ESCRIBE UN PUPPET. Ni fila, ni implícito, ni por-defecto: acá no
            #     hay un solo `insert`. Mil turnos raw dejan mil espacios y CERO agentes
            #     (`qa/verify_piso_sin_puppets.py` lo mide, y se probó cayendo).
            #   · EL CINTURÓN NO ES UN AGENTE. Es el kit base de la casa —los mismos 6
            #     servers keyless que `ensure_kit` ya equipa en los otros tres bordes—,
            #     idéntico en todo turno del piso. No se elige, no se guarda, no aparece
            #     en el Cuarto. Es de LA SALA, no del usuario.
            #   · EL CONSENTIMIENTO NO SE DUPLICA. Este borde no inventa gate: cae en el
            #     MISMO camino de `/puppets/run` que ya existe, con `approval_gate` y sus
            #     pisos intactos más abajo. Por eso la obra va acá y NO en run/stream, que
            #     es toolless por diseño — meterle tools ahí sí habría sido una segunda
            #     opinión sobre el consentimiento.
            _raw_owner = _repo.session_owner(_bearer(authorization)) or body.user_id
            _, _v2_raw_cfg, _v2_snapshot = _route_model_use(
                workspace_id="sala",
                call_class="run.raw",
                authorization=authorization,
                recipe=None,
                selection_ref=body.model,
                agent_id=None,
                session_id=body.chat_id,
                task_id=body.space_id,
                entity_id=body.space_id,
                messages=[{"role": "user", "content": body.prompt}],
                attachments=[
                    {"type": "image", "index": i} for i, _ in enumerate(body.images or [])
                ],
                tools=body.client_tools,
                required_capabilities=[
                    "text", "tool_calling", *(["vision"] if body.images else [])
                ],
                stream=False,
                call_id=body.client_turn_id,
            )
            _selected = _v2_snapshot.selection_ref if _v2_snapshot else body.model
            _raw_cfg = _v2_raw_cfg or _modelo_crudo(_selected, _raw_owner)
            if not _raw_cfg:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "missing_recipe",
                            "detail": "elige un modelo en el selector, o pasa `recipe` inline o `puppet_id`"},
                )
            # `belt: {}` es la única llave que `ensure_kit` necesita para no ser
            # conservadora (es explícitamente pura y no toca un config sin `belt` dict).
            recipe, _kit_puesto = _kit.ensure_kit({"model": _raw_cfg, "belt": {}})
            if not _kit_puesto:
                # `PUPPET_KIT_BASE=0` (la palanca de calibración en rojo) apaga el kit.
                # El piso entonces corre SIN manos, y eso se dice en vez de fingirlo.
                recipe = {"model": _raw_cfg, "belt": {}}

        # [UX·B1] OVERRIDE DE AUTONOMÍA por-turno (el selector de sesión de la Sala): se
        # foldea en la receta ANTES de validate_recipe (set cerrado manual/balanceado/
        # autonomo → basura rebota 422) y el gate la lee de recipe.autonomy como siempre.
        # Los PISOS no se relajan: money cortocircuita a needs_ok bajo TODA perilla y las
        # tools con nombre de escritura-externa mantienen su piso (approval_gate 2a + pisos
        # 1-3). Aplica SOLO a este run (turnos siguientes) — las held pendientes quedan
        # selladas con SU receta (execute_held_tool): cambiar la perilla no retro-aprueba.
        _obs.marca("run.receta_lista")
        if body.autonomy:
            recipe = {**(recipe or {}), "autonomy": body.autonomy}

        # [LEY 15] El piso ya resolvió su modelo arriba, en su propio borde (`run.raw`).
        # Volver a rutear acá lo contaría DOS VECES en el ledger y pisaría la proyección
        # efímera con una segunda decisión. Mismo guard que `run/stream`.
        if not raw_mode:
            recipe, _, _ = _route_model_use(
                workspace_id="sala",
                call_class="agent.run",
                authorization=authorization,
                recipe=recipe,
                selection_ref=None,
                agent_id=body.puppet_id,
                session_id=body.chat_id,
                task_id=body.space_id,
                entity_id=body.space_id,
                messages=[{"role": "user", "content": body.prompt}],
                attachments=[
                    {"type": "image", "index": i} for i, _ in enumerate(body.images or [])
                ],
                tools=body.client_tools,
                required_capabilities=[
                    "text", "tool_calling", *(["vision"] if body.images else [])
                ],
                stream=False,
                call_id=body.client_turn_id,
            )

        # GUARD DE AISLAMIENTO DOC-RAG: la receta trae rag.dir del cliente. Si apunta al área
        # de RAG, DEBE ser la carpeta del user de la sesión — nunca la de otro. Si no pertenece,
        # cortamos la memoria (enabled:false) en vez de leer docs ajenos. Cero re-arquitectura:
        # es saneo en el router (mismo rol que el authz), no toca el motor ni _load_rag.
        _obs.marca("run.pre_rag_store")
        from app.phase1 import rag_store
        _rag = (recipe or {}).get("rag") if isinstance(recipe, dict) else None
        if isinstance(_rag, dict) and _rag.get("enabled") and _rag.get("dir"):
            if not rag_store.is_owned_rag_dir(_rag.get("dir"), body.user_id):
                recipe = {**recipe, "rag": {**_rag, "enabled": False, "dir": None,
                                            "_blocked": "rag.dir no pertenece a tu cuenta"}}

        # Validar la receta contra el SCHEMA antes de correr (no se levanta un puppet
        # con receta que rompe el contrato — el validador es parte del path de prod).
        #
        # [LEY 15] El piso NO pasa por acá, y es la mitad que hace cumplir la ley: validar
        # exigiría que la proyección efímera fuera una receta v1 (`meta.name`, `meta.nicho`,
        # `schema_version`…) — o sea, FABRICAR el agente que la ley prohíbe, sólo para
        # poder correr sin él. Mismo salteo y mismo motivo que `run/stream`. Lo que el piso
        # sí atraviesa entero, dos pasos más abajo, es el GATE: el consentimiento no
        # depende del validador y no se relaja acá.
        if not raw_mode:
            try:
                rv.validate_recipe(recipe, repo_root=resource_root)
            except rv.RecipeValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings},
                )

        # A2 · HOLD-AND-DEFER (gemelo de infra/run_handler.py). La perilla de Autonomía
        # (recipe.autonomy) vive DENTRO del gate: el gate YA decidió auto/hold por clase
        # de acción. Todo lo que llega acá como needs_ok REQUIERE OK humano — no se
        # auto-concede (cierra el bug de write-world genérico rubber-stampeado). El OK
        # real llega por HTTP (POST /v1/runs/{id}/approve). Piso money nunca baja.
        def _approve(server, tool, payload):
            return False
        # costura a la sala: si hay space_id, cada paso del run se persiste como evento
        _obs.marca("run.pre_emisor")
        on_event = _make_space_emitter(body.space_id) if body.space_id else None
        _obs.marca("run.post_emisor")

        # CREDENTIAL-BROKER POR END-USER (Tier A, F4-B4): el resolver queda LIGADO al
        # user_id de ESTE run. Resuelve keys.<prov>.byok_ref → la credencial CIFRADA de
        # ESE usuario (tabla `keys`, descifrada solo en memoria) y la cablea al child_env
        # del belt. Aislamiento: un run de A jamás resuelve la credencial de B. Sin
        # user_id no se resuelve nada (un run anónimo no toca credenciales de nadie).
        from app.phase1 import credential_broker
        byok_resolver = (
            credential_broker.make_user_resolver(body.user_id, get_conn=get_conn)
            if body.user_id else None
        )

        _obs.marca("run.pre_conn")
        conn = _conn()
        _obs.marca("run.post_conn")
        try:
            # ── T7-billing · CORTE por presupuesto ANTES de gastar cognición ──────
            # Si el usuario ya excedió su cap → 402 y el run NO arranca (no funde la
            # cuenta).
            #
            # [Step 5 · P12 · T-S5-02] A QUIÉN SE MIDE SALE DE LA SESIÓN, no del body.
            # Antes era `if body.user_id:` — y como ese campo lo manda el CLIENTE, un
            # usuario logueado esquivaba su propio cap con sólo OMITIRLO: el run seguía
            # (su sesión es válida), pero no había a quién medir. Barato de descubrir y
            # caro de pagar: es gasto de cognición sin techo, la línea roja #1 del
            # negocio. Ahora la sesión decide, y omitir el campo no cambia nada.
            #
            # Anónimo de verdad (sin sesión) sigue pasando: no hay cuenta que medir ni
            # cap que aplicar. Los tests y el e2e dependen de ese camino. Su techo es
            # otro problema (rate-limit del borde), no el de esta capa.
            from app.phase1 import billing
            _medido = _repo.session_owner(_bearer(authorization))
            if _medido:
                _pf = billing.preflight(conn, _medido)
                if not _pf["allowed"]:
                    raise HTTPException(status_code=402,
                        detail={"error": "over_budget", **_pf})

            # [ticket 22 · contrato de ruteo] turno CONVERSACIONAL (hilo con chat_id y SIN
            # espacio de obra): el cerebro responde como chat — prosa breve, estructura chica
            # inline; el documento con cuerpo pertenece a la obra. La instrucción viaja por el
            # MISMO canal que el history (prompt del cerebro), jamás al registro del turno.
            _hist_text = (_chat or {}).get("history_text")
            if body.chat_id and not body.space_id:
                _style = ("[Modo conversación] Estás charlando en un hilo de chat: responde en "
                          "prosa breve y natural (negritas o bullets chicos si ayudan; una "
                          "mini-tabla solo si el dato lo pide). NO produzcas un documento ni un "
                          "informe con secciones — si el pedido requiere un entregable con "
                          "cuerpo, dilo y ofrece armarlo como obra. Usa tus herramientas "
                          "cuando haga falta para responder con datos reales.")
                _hist_text = ((_hist_text + "\n\n") if _hist_text else "") + _style
            # ── EL SOBRE, TAMBIÉN EN EL CAMINO DE OBRA ──────────────────────────────
            # MEDIDO el 2026-08-26 con la perilla del broker PRENDIDA: el primer turno de
            # La Sala daba
            #     [broker] codex_cli → cae al camino de hoy · motivo=sin_clave_de_conversacion
            # y el contador cerraba en `atendidos=0`. La causa: `sobre_turno.poner()` se
            # llamaba en DOS lugares y los dos viven adentro de
            # `POST /v1/workspaces/brain/openai/chat/completions`. La Sala no pasa por ahí
            # —va por `/v1/puppets/run` → `executor.run_puppet_e2e`— así que `actual()`
            # devolvía `(None, None, None)`, `campos_del_cuerpo()` devolvía `{}`, y el
            # borde de CLIs recibía el turno SIN `sesion`.
            #
            # Consecuencia: **el broker no podía entrar desde La Sala, ni prendido**, y el
            # `--resume` de claude tampoco. Un A/B del broker medido en La Sala comparaba
            # dos ramas idénticas — que es exactamente por qué «perdía».
            #
            # La clave usa el MISMO formato del otro camino (`_clave_de_conversacion`):
            # `"<ws>:<user>:<peldaño>:<valor>"`, que es lo que `dueno_de_clave()` parsea
            # fail-closed. El peldaño es `chat` porque el `space_id` cambia en CADA turno
            # (medido: space-mtakl56n-0 y space-mtas6pzf-0 en dos turnos del mismo hilo) y
            # una clave que cambia por turno no comparte NADA: sería un proceso nuevo cada
            # vez, o sea el camino de hoy con un pool al lado.
            # Sin chat no hay clave y no se inventa una: se sigue como hasta ahora.
            _clave_obra = ("%s:%s:chat:%s" % ("sala", (body.user_id or "-"), body.chat_id)
                           if getattr(body, "chat_id", None) else None)
            _tok_obra = _sobre_turno.poner(None, None, _clave_obra) if _clave_obra else None
            try:
                _obs.marca("run.al_executor")
                out = executor.run_puppet_e2e(
                recipe, body.prompt,
                puppet_id=body.puppet_id, user_id=body.user_id, space_id=body.space_id,
                chat_id=getattr(body, "chat_id", None),
                conn=conn, deadline_s=body.deadline_s,
                byok_resolver=byok_resolver,
                approve=_approve, on_event=on_event,
                images=body.images,
                lang=body.lang,
                history_text=_hist_text,
                method_id=body.method_id,          # PIEZA MÉTODO (None = byte-idéntico)
                method_adjust=body.method_adjust,
                client_tools=_validar_client_tools(body.client_tools),   # [FIX-P9]
                # [T2.5c] EL INBOX DE ESTA CONVERSACIÓN. La carpeta se deriva de
                # (dueño, chat) y NO se recibe del cliente: una ruta que viene del body es
                # una ruta que el cliente elige, y ahí el aislamiento deja de ser
                # estructural. Sin dueño o sin chat no hay inbox — y no se inventa uno
                # compartido, que sería el balde donde se cruzan dos usuarios.
                inbox_dir=_inbox_dir_de(body, authorization),
                )
            finally:
                # El `finally` cubre también el fallo: un sobre que queda puesto se
                # filtraría al turno siguiente de ESTE worker y le prestaría la
                # conversación de otro. Es la misma disciplina del `poner/sacar` del otro
                # camino (`router.py:5788`).
                if _tok_obra is not None:
                    _sobre_turno.sacar(_tok_obra)

            # [UX·A1] registra la respuesta del agente en el hilo (proyección, no camino
            # crítico: un fallo acá jamás tumba el run)
            if _chat:
                _chat_record_answer(body.chat_id, out.get("answer") or "",
                                    kind=("obra" if body.space_id else "chat"),
                                    space_id=body.space_id, run_id=out.get("run_id"),
                                    client_turn_id=(_chat or {}).get("client_turn_id"))

            # ── T7-billing · INGESTA el costo del run (COST-EVENT §4.6 → ledger) ──
            # Idempotente por run_id. NUNCA tumba el run: si billing falla, el run igual
            # responde (el cost-event queda re-ingestable). Anónimo → no factura a nadie.
            try:
                out["billing"] = billing.record_run_cost(
                    conn, run_id=out.get("run_id"), user_id=body.user_id,
                    cost_events=out.get("cost_events", []),
                )
            except Exception as _bexc:  # noqa: BLE001
                out["billing"] = {"ingested": 0, "error": f"{type(_bexc).__name__}"}
            return out
        finally:
            conn.close()

    # ── APPROVE-BY-HTTP (deuda #1): el OK del dueño EJECUTA la acción retenida ──
    @router.post("/runs/{run_id}/approve", status_code=200)
    def approve_held(run_id: str, body: ApproveHeldRequest,
                     authorization: Optional[str] = Header(default=None)):
        """El dueño APRUEBA (ok=true → la acción se EJECUTA de verdad) o RECHAZA (ok=false →
        se descarta) una acción de alta consecuencia (ej. send_email) que el gate retuvo
        durante el run. El correo/pago NO salió en el run; este OK explícito es el ÚNICO camino
        a ejecutarlo (invariante §3.5 intacta). Aislamiento anti-IDOR: la sesión debe ser dueña
        de la acción."""
        from app.phase1 import executor, repo as _repo
        conn = _conn()
        try:
            ha = _repo.get_held_action(conn, body.approval_id)
        finally:
            conn.close()
        if ha is None:
            raise HTTPException(status_code=404,
                detail={"error": "held_not_found", "detail": "No existe esa acción para aprobar."})
        if str(ha.get("run_id")) != str(run_id):
            raise HTTPException(status_code=404,
                detail={"error": "run_mismatch", "detail": "La acción no pertenece a ese run."})
        # AUTHZ: la sesión DEBE ser dueña de la acción (toca envío real → anti-IDOR estricto).
        _authorize(ha.get("user_id"), authorization)
        return executor.approve_held_action(body.approval_id, ok=body.ok, user_id=ha.get("user_id"))

    # ── snapshot de eventos del espacio (lo que la sala lee de un run real) ────
    @router.get("/spaces/{space_id}/events")
    def space_events(space_id: str,
                     authorization: Optional[str] = Header(default=None),
                     token: Optional[str] = Query(default=None)):
        """Devuelve los eventos persistidos de un espacio (snapshot JSON). La sala lo
        consume con ?space=<id> para pintar un RUN REAL en vez del fixture demo.
        AUTHZ (§4.5, T6): si el space pertenece a un run con dueño, sólo el dueño lo lee
        (los eventos llevan args/resultados/answer del trabajo real). Space anónimo
        (inspect/demo) → abierto. Token por header o ?token= (paridad con el stream)."""
        path = _authorize_space(space_id, authorization, token) / "events.jsonl"
        evts: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    evts.append(_json.loads(line))
                except Exception:
                    pass
        return {"space_id": space_id, "events": evts}

    # ── (c) event stream SSE (token-cost CERO) ────────────────────────────────
    @router.get("/spaces/{space_id}/stream")
    async def stream_space(space_id: str, request: Request,
                           last_event_id: int = Query(default=0, alias="last_event_id"),
                           authorization: Optional[str] = Header(default=None),
                           token: Optional[str] = Query(default=None)):
        """
        SSE de los eventos del espacio. Pinta lo que el loop YA persistió en
        events.jsonl. Soporta Last-Event-ID (header o query) → replay exacto.
        El modelo NO ve este stream (token-cost cero).
        AUTHZ (§4.5, T6): si el space pertenece a un run con dueño, sólo el dueño puede
        abrir el stream. Space anónimo (inspect/demo) → abierto. Como el EventSource del
        browser NO puede mandar headers, la sesión viaja por `?token=<session_token>`.
        """
        directory = _authorize_space(space_id, authorization, token)
        # Last-Event-ID estándar del browser (header) tiene prioridad sobre el query.
        hdr = request.headers.get("last-event-id")
        if hdr:
            try:
                last_event_id = int(hdr)
            except ValueError:
                pass

        events_path = directory / "events.jsonl"
        if not events_path.exists():
            raise HTTPException(status_code=404, detail=f"espacio '{space_id}' sin stream")

        # IDLE-TIMEOUT DEL STREAM DE RUN (Gap #3): un run agéntico real (cerebro Opus ~55s)
        # puede pasar >30s entre eventos en un turno lento; el default 30s cerraría el stream
        # MID-RUN y el cliente perdería el progreso. Lo elevamos a la duración del run (env
        # PUPPET_STREAM_IDLE_S, default 180s = deadline_s). Igual cierra LIMPIO antes por el
        # evento `closed` que emite el executor al terminar — el idle es solo el backstop.
        import os as _os
        _idle_s = float(_os.environ.get("PUPPET_STREAM_IDLE_S", "180") or "180")

        async def _agen():
            # is_disconnected sync-bridge: chequeamos el flag del request entre polls.
            import anyio
            gen = es.iter_sse_events(events_path, last_event_id=last_event_id,
                                     idle_timeout_s=_idle_s)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    frame = await anyio.to_thread.run_sync(lambda: next(gen, None))
                    if frame is None:
                        break
                    yield frame
            finally:
                gen.close()

        return StreamingResponse(
            _agen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── RUTEO charla/obra (ADITIVO): la COGNICIÓN declara el turno ─────────────
    @router.post("/classify-turn")
    def classify_turn_ep(body: TurnClassifyRequest,
                         authorization: Optional[str] = Header(default=None)):
        """La cognición decide si el turno es 'chat' (conversación) u 'obra' (deliverable).
        La Sala rutea por esto en vez de adivinar por la forma del output. ADITIVO: no toca
        el motor (es una clasificación corta y separada)."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import stream_chat
        try:
            turn = stream_chat.classify_turn(body.prompt or "")
        except Exception:
            turn = ""
        return {"turn": turn or None}

    # ── Caption de obra (ADITIVO): la voz del modelo presenta la obra ──────────
    @router.post("/obra-caption")
    def obra_caption_ep(body: ObraCaptionRequest,
                        authorization: Optional[str] = Header(default=None)):
        """Genera la línea natural (voz del modelo) que acompaña a la obra en el chat. Devuelve
        {message, model, usage} → output REAL del modelo, no una cadena fija. ADITIVO."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import stream_chat
        try:
            return stream_chat.obra_caption(body.task or "", body.excerpt or "", bool(body.editing))
        except Exception as exc:
            return {"message": "", "model": None, "usage": None, "error": str(exc)}

    # ── ⏹ PARAR EL TURNO (Gate 2 · F4b · obra 2) ──────────────────────────────
    @router.post("/turnos/detener")
    def detener_turno(body: DetenerTurnoRequest,
                      authorization: Optional[str] = Header(default=None)):
        """Para un turno del BYO-CLI en vuelo. **El puente que faltaba.**

        F2d construyó `stop_turn` entero —secuencia de CLITrigger, deadline propio que
        resuelve SIEMPRE, el slot liberado por el `finally`— y lo expuso en el server
        `:8926`. Y **nadie lo llamó nunca**, porque la Sala habla con este backend, no con
        `:8926`, y no había endpoint que cruzara. Una obra terminada que no se podía
        alcanzar es una obra que, para el usuario, no existe.

        Los dos resultados son los del vocabulario cerrado de F2d y los DOS son 200:
        `turno_detenido` (el proceso murió) y `no_habia_turno` — que **no es un error**,
        es lo normal cuando alguien aprieta parar justo cuando la respuesta llegaba.
        Devolver 4xx ahí convertiría un final feliz en un cartel rojo.
        """
        if body.user_id:
            _authorize(body.user_id, authorization)
        import json as _j
        import os as _os
        import urllib.error as _ue
        import urllib.request as _ur

        # [F6-cierre · obra C] PRIMERO EL REGISTRO HTTP LOCAL. Las vías Ollama/API no
        # tienen proceso hijo que matar: tienen un socket, y pararlas es cerrarlo. Se
        # busca acá antes de salir a la red porque preguntarle al `:8926` por un turno
        # que nunca fue suyo devolvería `no_habia_turno` — un «no había nada» falso
        # sobre un turno que sí estaba corriendo, que es la peor respuesta posible.
        from app.phase1 import turnos_http as _th
        _local = _th.detener(body.turno_id) if body.turno_id else None
        if _local and _local.get("resultado") == _th.TURNO_DETENIDO:
            return _local

        # ── [Gate 4 · F5 · 5.2] Y DESPUÉS, LAS OBRAS ──────────────────────────────
        # Tercer consultado de la misma cascada, con el MISMO par de resultados. Una obra
        # no tiene un socket que cerrar (tiene N llamadas al modelo y M tool-calls), así
        # que pararla es marcarla: el motor mira la marca antes de cada turno y antes de
        # cada tool, y el socket del modelo que esté abierto en ese momento se cierra.
        #
        # La llave es el `space_id` que eligió el cliente, o el `run_id` — el registro los
        # trata como el mismo acto. Los tres espacios de nombres son disjuntos
        # (`http-…` · `sala-…` · el turno del CLI), así que preguntar en cascada no puede
        # parar el turno de otro.
        from app.phase1 import executor as _ex
        _obra = _ex._turnos_obra.detener(body.turno_id) if body.turno_id else None
        if _obra and _obra.get("resultado") == _ex._turnos_obra.TURNO_DETENIDO:
            return _obra

        base = _os.environ.get("PUPPET_CLI_BRAIN_BASE_URL", "http://127.0.0.1:8926/v1").rstrip("/")
        req = _ur.Request(base + "/turnos/detener",
                          data=_j.dumps({"turno_id": body.turno_id}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _ur.urlopen(req, timeout=15) as r:
                return _j.loads(r.read().decode("utf-8", "replace"))
        except _ue.HTTPError as e:
            # El server ya contesta tipado; se reenvía tal cual en vez de re-inventarlo.
            try:
                return _j.loads(e.read().decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return {"resultado": "no_habia_turno", "detalle": f"HTTP {e.code}"}
        except Exception as exc:  # noqa: BLE001 — el server local caído no tumba la Sala
            # Sin cerebro CLI arriba no hay turno que parar, y eso NO es un fallo del
            # botón: es que no había nada corriendo por esa vía.
            # El detalle es el TIPO de la excepción, jamás su texto: el mensaje de un
            # error de red puede traer la URL con credenciales adentro.
            return {"resultado": "no_habia_turno", "detalle": type(exc).__name__}

    # ── 🗂 LO QUE EL CLI ESCRIBE EN TU DISCO (Gate 2 · F4b · obra 4) ───────────
    @router.get("/cli/transcripts")
    def cli_transcripts(authorization: Optional[str] = Header(default=None)):
        """Dónde viven los transcripts del BYO-CLI, cuántos son y cuántos son TUYOS.

        F2e dejó las conversaciones en `~/.claude/projects/` en texto plano y midió que no
        hay dónde moverlas. La respuesta no puede ser esconderlas: es decirlo. `tuyos` va
        en el payload a propósito — es la prueba, en el mismo dato, de que sabemos separar
        lo de Aleph de lo que abriste vos en tu terminal.
        """
        from app.phase1 import transcripts_cli as _t
        return _t.donde()

    @router.post("/cli/transcripts/borrar")
    def cli_transcripts_borrar(confirmar: bool = Query(default=False),
                               authorization: Optional[str] = Header(default=None)):
        """Borra los transcripts que Aleph generó. **Sólo los suyos.**

        SIN `confirmar=true` NO BORRA: devuelve el dry-run, o sea exactamente qué se
        llevaría por delante. No es burocracia — es que del otro lado del mismo directorio
        están las conversaciones del usuario (medido en esta máquina: 1.128 carpetas
        suyas), y un borrado que no se puede previsualizar es un borrado que no se puede
        auditar antes de que sea tarde.
        """
        from app.phase1 import transcripts_cli as _t
        if not confirmar:
            return dict(_t.limpiar(dry_run=True), confirmacion_requerida=True)
        return _t.limpiar()

    # ── 🎙️ TRANSCRIPCIÓN (ADITIVO): audio → texto vía Groq Whisper ────────────
    @router.post("/transcribe")
    def transcribe_audio(body: TranscribeRequest,
                         authorization: Optional[str] = Header(default=None)):
        """Audio (base64) → texto. Reusa la cognición (Whisper en Groq). Si el run se
        atribuye a un user, debe ser el de la sesión. ADITIVO: no toca el motor."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        import base64
        from app.phase1 import transcribe as _tx
        try:
            audio = base64.b64decode(body.audio_b64 or "", validate=False)
        except Exception:
            raise HTTPException(status_code=422, detail={"error": "bad_audio", "detail": "base64 inválido"})
        if not audio:
            raise HTTPException(status_code=422, detail={"error": "empty_audio"})
        if len(audio) > 25_000_000:  # ~25MB, tope de Whisper
            raise HTTPException(status_code=413, detail={"error": "audio_too_large"})
        try:
            text = _tx.transcribe(audio, filename=body.filename or "audio.webm", mime=body.mime or "audio/webm")
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": "transcribe_failed", "detail": str(exc)})
        return {"text": text}

    # ── STREAMING token-por-token (ADITIVO): la "sesión en vivo" letra-a-letra ──
    @router.post("/puppets/run/stream")
    def run_puppet_stream(body: RunPuppetRequest,
                          authorization: Optional[str] = Header(default=None)):
        """
        STREAMING de la respuesta del modelo token-por-token (SSE) para que la Sala
        dibuje la obra MIENTRAS se genera (render-on-change en vivo). Chat DIRECTO de
        texto (sin tools/gate): solo produce una obra de TEXTO, no ejecuta acciones —
        las obras con tools/acciones siguen yendo por /puppets/run (con su gate, §3.5).
        Reusa la MISMA carga de receta + guard de aislamiento DOC-RAG + validación que
        el run completo. ADITIVO: no toca el run path ni el motor.
        Eventos SSE: {type:'token',text} por delta · {type:'done',answer} al cerrar ·
        {type:'error',detail,answer} si falla a mitad.
        """
        if body.user_id:  # si el run se atribuye a un user, debe ser el de la sesión
            _authorize(body.user_id, authorization)
        from app.phase1 import repo as _repo, rag_store, stream_chat

        # [UX·A1] chat persistente: registra el turno del usuario y rehidrata el hilo
        _chat = _chat_gate(body, authorization)
        _replay = _chat_replay_answer(_chat)
        if _replay is not None:
            async def _replay_stream():
                yield "data: " + _json.dumps({
                    "type": "done", "answer": _replay["answer"],
                    "idempotent_replay": True,
                }) + "\n\n"
            return StreamingResponse(
                _replay_stream(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        recipe = body.recipe
        raw_mode = not body.puppet_id and recipe is None
        # Igual que el run completo: una receta con overrides de sesión puede viajar
        # junto a puppet_id, pero la identidad guardada sigue siendo owner-gated.
        if body.puppet_id:
            # [audit superficie · H3] Cargar una receta GUARDADA (por puppet_id) EXIGE ser
            # su dueño. Antes get_puppet no filtraba owner y `run` sólo autorizaba
            # `if body.user_id`: quien conociera un puppet_id ajeno lo corría SIN sesión,
            # gastando cognición/tools a costa de Aleph (la línea roja #1 del negocio).
            # Una `recipe` INLINE anónima es tu propia receta ad-hoc y sigue permitida (no
            # toca datos de nadie; los tests y el e2e dependen de ese camino). La frontera:
            # inline = tuya · puppet_id = de alguien, y ese alguien tenés que ser vos.
            _runner = _repo.session_owner(_bearer(authorization))
            if not _runner:
                raise HTTPException(status_code=401, detail={
                    "error": "no_session",
                    "detail": "Correr un agente guardado necesita tu sesión."})
            conn = _conn()
            try:
                puppet = _repo.get_puppet(conn, body.puppet_id)
            finally:
                conn.close()
            # Ajeno == 404, indistinguible de inexistente (anti-IDOR: no se confirma que
            # el puppet existe si no es tuyo).
            if puppet is None or str(puppet.get("owner_id")) != str(_runner):
                raise HTTPException(status_code=404, detail=f"puppet '{body.puppet_id}' no encontrado")
            if recipe is None:
                # FIX-P4 · KIT BASE · borde de CORRIDA por puppet_id. La Sala normalmente manda
                # su copia de la receta (que YA salió del GET normalizado), pero un run que sólo
                # trae puppet_id lee el config crudo de la DB: un agente viejo que nunca pasó por
                # el GET correría sin brazos. Acá NO se persiste (el GET es el dueño del backfill):
                # esto es completar en memoria lo que va a correr. Idempotente.
                recipe, _ = _kit.ensure_kit(puppet["config"])
        elif recipe is None:
            # [LEY 15] La charla sin agente entra por el MISMO selector/configuración
            # canónica que el borde de workspaces. No se fabrica una receta v1 ni se
            # escribe un puppet: `recipe` acá es una proyección efímera de `model_cfg`
            # para que el stream certificado pueda reutilizar sus building blocks.
            _raw_owner = _repo.session_owner(_bearer(authorization)) or body.user_id
            _, _v2_raw_cfg, _v2_snapshot = _route_model_use(
                workspace_id="sala",
                call_class="chat.raw",
                authorization=authorization,
                recipe=None,
                selection_ref=body.model,
                agent_id=None,
                session_id=body.chat_id,
                task_id=None,
                entity_id=body.space_id,
                messages=[{"role": "user", "content": body.prompt}],
                attachments=[
                    {"type": "image", "index": i} for i, _ in enumerate(body.images or [])
                ],
                required_capabilities=[
                    "text", "streaming", *(["vision"] if body.images else [])
                ],
                stream=True,
                call_id=body.client_turn_id,
            )
            _selected = _v2_snapshot.selection_ref if _v2_snapshot else body.model
            _raw_cfg = _v2_raw_cfg or _modelo_crudo(_selected, _raw_owner)
            if not _raw_cfg:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "missing_recipe",
                            "detail": "elige un modelo en el selector, o pasa `recipe` inline o `puppet_id`"},
                )
            recipe = {"model": _raw_cfg}

        # Un `agent` reclamado sin la identidad owner-gated no es una variante raw: es un
        # request inconsistente y se corta antes de gastar cognición.
        if body.agent and not body.puppet_id:
            raise HTTPException(status_code=422, detail={
                "error": "agent_requires_puppet",
                "detail": "un agente necesita `puppet_id`; el modo raw usa `agent:null`"})

        # [UX·B1] mismo fold de autonomía que el run completo (el stream no ejecuta tools,
        # pero la receta viaja consistente y la validación rechaza valores basura igual).
        if body.autonomy:
            recipe = {**(recipe or {}), "autonomy": body.autonomy}

        if not raw_mode:
            recipe, _, _ = _route_model_use(
                workspace_id="sala",
                call_class="chat.agent",
                authorization=authorization,
                recipe=recipe,
                selection_ref=None,
                agent_id=body.puppet_id,
                session_id=body.chat_id,
                task_id=None,
                entity_id=body.space_id,
                messages=[{"role": "user", "content": body.prompt}],
                attachments=[
                    {"type": "image", "index": i} for i, _ in enumerate(body.images or [])
                ],
                required_capabilities=[
                    "text", "streaming", *(["vision"] if body.images else [])
                ],
                stream=True,
                call_id=body.client_turn_id,
            )

        # MISMO guard de aislamiento DOC-RAG que el run completo (saneo en el router).
        _rag = (recipe or {}).get("rag") if isinstance(recipe, dict) else None
        if isinstance(_rag, dict) and _rag.get("enabled") and _rag.get("dir"):
            if not rag_store.is_owned_rag_dir(_rag.get("dir"), body.user_id):
                recipe = {**recipe, "rag": {**_rag, "enabled": False, "dir": None,
                                            "_blocked": "rag.dir no pertenece a tu cuenta"}}

        if not raw_mode:
            try:
                rv.validate_recipe(recipe, repo_root=resource_root)
            except rv.RecipeValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings},
                )

        _recipe = recipe

        # El raw también deja un espacio auditable. Si la Sala moderna no mandó uno,
        # la casa genera una referencia opaca sólo para eventos/procedencia; nunca es un
        # agente, una sesión de workspace ni un puerto.
        _raw_space_id = (body.space_id or ("raw-" + _uuid.uuid4().hex)) if raw_mode else None
        _raw_on_event = _make_space_emitter(_raw_space_id) if _raw_space_id else None
        if _raw_on_event:
            _raw_on_event({
                "type": "turn_started", "kind": "turn", "workspace": "sala",
                "run_id": _raw_space_id, "agent": None, "model_requested": body.model,
            })

        # ── T7-billing · CORTE por presupuesto antes de streamear cognición ──────
        # Mismo cap que el run completo: un usuario sin presupuesto no arranca el chat.
        # [Step 5 · P12 · T-S5-02] Y a quién se mide sale de la SESIÓN, igual que en
        # /puppets/run: si dependiera de `body.user_id`, omitir el campo esquivaría el
        # cap por este otro camino y el arreglo del otro endpoint no serviría de nada.
        _medido_s = _repo.session_owner(_bearer(authorization))
        if _medido_s:
            from app.phase1 import billing
            _bconn = _conn()
            try:
                _pf = billing.preflight(_bconn, _medido_s)
            finally:
                _bconn.close()
            if not _pf["allowed"]:
                raise HTTPException(status_code=402,
                    detail={"error": "over_budget", **_pf})

        # BYOK-LLM (⚡ "Tu API"): resolver ligado al user → si model.byok_ref nombra un
        # provider del usuario, el LLM corre con SU key (su API), no la cognición incluida.
        from app.phase1 import credential_broker
        _byok = credential_broker.make_user_resolver(body.user_id, get_conn=get_conn) if body.user_id else None

        # [UX·A1] el cerebro recibe la conversación previa del hilo (registro real);
        # el prompt crudo ya quedó registrado como turno del usuario en _chat_gate.
        _hist = (_chat or {}).get("history_text")
        _brain_prompt = (_hist + "\n\n" + body.prompt) if _hist else body.prompt

        # [UX·B5] las instrucciones persistentes rigen también la charla pura. El scope
        # es SIEMPRE el usuario de la sesión (build_block filtra por user_id en SQL:
        # un puppet ajeno devuelve vacío por construcción). Fail-safe: sin bloque.
        _instr = None
        if body.user_id:
            try:
                from app.phase1 import instructions_repo as _irepo
                _iconn = _conn()
                try:
                    _instr = _irepo.build_block(_iconn, body.user_id, body.puppet_id) or None
                finally:
                    _iconn.close()
            except Exception:
                _instr = None

        def _gen():
            full: list[str] = []
            _hubo_uso = {"si": False}
            _uso_final = None
            _modelo_final = None
            _degradado = False

            def _cerrar_raw(answer: str, ok: bool, error: Optional[str] = None) -> None:
                """Cierra el raw con las mismas señales que S8/provenance consumen.

                El chat sigue siendo el transcript humano; el espacio es la evidencia
                durable del turno y de su `model_final`. No se crea ningún registro de
                agente, y un fallo al escribir telemetría jamás cambia la respuesta.
                """
                if not _raw_on_event:
                    return
                try:
                    uso = _uso_final if isinstance(_uso_final, dict) else {}
                    pt, ct = uso.get("prompt_tokens"), uso.get("completion_tokens")
                    measured = pt is not None or ct is not None
                    try:
                        pti, cti = int(pt or 0), int(ct or 0)
                    except (TypeError, ValueError):
                        pti, cti, measured = 0, 0, False
                    priced = {}
                    if _modelo_final and measured:
                        try:
                            priced = stream_chat._asm()._models.price(_modelo_final, pti, cti) or {}
                        except Exception:
                            priced = {}
                    cost = {
                        "type": "cost", "kind": "model", "user_id": body.user_id,
                        "run_id": _raw_space_id, "model": _modelo_final,
                        "tier": "fallback" if _degradado else "primary",
                        "degraded": bool(_degradado),
                        "tokens": {"prompt": pti, "completion": cti, "total": pti + cti},
                        "tokens_measured": measured,
                        "usd": priced.get("usd"), "price_source": priced.get("source"),
                    }
                    _raw_on_event(cost)
                    try:
                        from app.phase1 import billing as _billing
                        _bconn = _conn()
                        try:
                            _billing.record_run_cost(
                                _bconn, run_id=_raw_space_id, user_id=body.user_id,
                                cost_events=[cost])
                        finally:
                            _bconn.close()
                    except Exception:
                        pass
                    _raw_on_event({
                        "type": "final", "kind": "final", "answer": (answer or "")[:20000],
                        "model_final": _modelo_final, "ok": bool(ok),
                        "run_id": _raw_space_id, "agent": None,
                    })
                    _raw_on_event({
                        "type": "closed", "kind": "closed", "answer": (answer or "")[:20000],
                        "model_final": _modelo_final, "ok": bool(ok),
                        "run_id": _raw_space_id, "agent": None, "error": error,
                    })
                except Exception:
                    pass
            try:
                # [UX·A4] stream_answer entrega (kind, s): 'token' = respuesta (se acumula
                # y persiste) · 'thinking' = razonamiento REAL del modelo (frame aparte,
                # efímero — solo existe si el modelo lo emite; jamás se fabrica).
                for kind, tok in stream_chat.stream_answer(_recipe, _brain_prompt, byok_resolver=_byok,
                                                           extra_system=_instr,
                                                           method_active=bool(body.method_id), lang=body.lang):
                    if kind == "thinking":
                        yield "data: " + _json.dumps({"type": "thinking", "text": tok}) + "\n\n"
                        continue
                    # [F4b · obra 2] el id del turno en vuelo → la Sala ya puede pararlo.
                    if kind == "turno":
                        yield "data: " + _json.dumps({"type": "turno", "turno_id": tok}) + "\n\n"
                        continue
                    # [GATE 3 · obra B · ACTA 2] LA SUSTITUCIÓN SE ANUNCIA. Canal propio,
                    # igual que `thinking`, `turno` y `usage`: es un dato DEL TURNO, no texto
                    # de la respuesta, y dejarlo caer al acumulador metería un JSON crudo
                    # adentro de lo que el usuario lee. El payload ya viene armado y
                    # redactado por `stream_chat` (pedido · usado · causa_origen tipada).
                    # [GATE 3 · obra 6] LA MEMORIA PERDIDA LLEGA A LA PANTALLA. Mismo
                    # molde que `modelo_sustituido` (obra B) y por la misma razón: es un
                    # dato del turno, no texto de la respuesta. El turno NO falló —la
                    # sesión es una optimización y perderla cuesta un turno más caro, no
                    # un turno roto (`cli_brain/server.py:498-520`)— así que esto no entra
                    # por el camino de error: entra por su canal, y la Sala lo pinta como
                    # aviso de estado, no como rojo.
                    if kind == "sesion_perdida":
                        try:
                            _sp = _json.loads(tok)
                        except Exception:          # noqa: BLE001 — avisar jamás rompe el turno
                            _sp = None
                        if _sp:
                            yield "data: " + _json.dumps({"type": "sesion_perdida", **_sp}) + "\n\n"
                        continue
                    if kind == "modelo_sustituido":
                        try:
                            _sus = _json.loads(tok)
                        except Exception:          # noqa: BLE001 — avisar jamás rompe el turno
                            _sus = None
                        if _sus:
                            _degradado = True
                            yield "data: " + _json.dumps({"type": "modelo_sustituido", **_sus}) + "\n\n"
                        continue
                    if kind == "model_final":
                        _modelo_final = str(tok or "").strip() or _modelo_final
                        yield "data: " + _json.dumps({
                            "type": "model_final", "model_final": _modelo_final,
                        }) + "\n\n"
                        continue
                    # [F6-cierre · obra B] EL USO DEL TURNO. Canal propio, igual que
                    # `thinking` y `turno`. Va ANTES del `full.append` a propósito: es un
                    # dato del turno, no texto de la respuesta, y dejarlo caer al acumulador
                    # metería un JSON crudo adentro de lo que el usuario lee.
                    if kind == "usage":
                        try:
                            _uso = _json.loads(tok)
                        except Exception:          # noqa: BLE001 — un uso ilegible no corta el turno
                            _uso = None
                        if _uso:
                            _hubo_uso["si"] = True
                            _uso_final = _uso
                            yield "data: " + _json.dumps({"type": "usage", **_uso}) + "\n\n"
                        continue
                    full.append(tok)
                    yield "data: " + _json.dumps({"type": "token", "text": tok}) + "\n\n"
                answer = "".join(full)
                # [F6-cierre · obra B] NO-MEDIBLE DECLARADO. Si el proveedor no mandó uso ni
                # siquiera pidiéndoselo, se dice — no se calla. El silencio es ambiguo: la
                # card no puede distinguir «no llegó» de «todavía no llegó», y termina
                # mostrando un hueco que parece un bug. Un `tokens_medidos:false` explícito
                # es la única forma de que la superficie diga «no se pudo medir» en vez de
                # inventar un cero, que es lo que la regla prohíbe.
                if not _hubo_uso["si"]:
                    yield "data: " + _json.dumps({
                        "type": "usage", "prompt_tokens": None, "completion_tokens": None,
                        "total_tokens": None, "tokens_medidos": False, "usd": None,
                    }) + "\n\n"
                if _chat:  # registra la respuesta en el hilo (jamás corta el stream)
                    _chat_record_answer(
                        body.chat_id, answer, kind="chat",
                        client_turn_id=(_chat or {}).get("client_turn_id"))
                _cerrar_raw(answer, True)
                yield "data: " + _json.dumps({
                    "type": "done", "answer": answer,
                    "model_final": _modelo_final, "space_id": _raw_space_id,
                    "agent": None if raw_mode else body.agent,
                }) + "\n\n"
            except Exception as exc:  # el streaming no tumba el server: reporta por el canal
                if _chat and full:  # lo que alcanzó a decir queda registrado (honesto)
                    _chat_record_answer(
                        body.chat_id, "".join(full), kind="chat",
                        client_turn_id=(_chat or {}).get("client_turn_id"))
                _cerrar_raw("".join(full), False, str(exc)[:400])
                # F4b · obra 1 · LA CAUSA VIAJA AL LADO DEL STRING, no en su lugar.
                # `detail` NO se toca (hay consumidores que lo leen y varas que lo fijan);
                # lo que se agrega es `causa`, que es lo ÚNICO de acá que se le puede
                # mostrar a una persona: `detail` puede llevar el cuerpo crudo del
                # proveedor, y la causa sale del traductor ya redactada y con su acción.
                _err = {"type": "error", "detail": str(exc), "answer": "".join(full)}
                _c = getattr(exc, "causa", None)
                if _c is not None and hasattr(_c, "como_dict"):
                    _err["causa"] = _c.como_dict()
                _err["model_final"] = _modelo_final
                _err["space_id"] = _raw_space_id
                yield "data: " + _json.dumps(_err) + "\n\n"

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── F4 · MODELO MULTI-ARTIFACT (un chat ↔ muchos artifacts) ────────────────
    @router.post("/artifacts/classify-action")
    def artifact_classify_action(body: ArtifactClassifyRequest,
                                 authorization: Optional[str] = Header(default=None)):
        """La cognición DECLARA la acción: {'action':'new'} | {'action':'edit','artifact_id':..}.
        Se decide mirando el mensaje + las obras existentes, NO por la forma del output."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import stream_chat
        try:
            return stream_chat.classify_artifact_action(body.prompt or "", body.artifacts or [])
        except Exception:
            return {"action": "new"}

    # ── EL INBOX DE LA CONVERSACIÓN [T2.5c] ─────────────────────────────────────────
    # El adjunto se SUBE y queda; el agente lo lee por ruta. Ver `inbox_store` para el
    # porqué de la ruta, el hash del dueño y el aislamiento estructural.
    #
    # EL CUERPO VA CRUDO — ni multipart ni base64, y las dos exclusiones tienen motivo:
    #   · multipart necesitaría `python-multipart`, que NO está instalado y del que este
    #     endpoint sería el PRIMER usuario del backend (medido). Una dependencia nueva en
    #     una app empaquetada con PyInstaller no es `pip install`: es bundle, spec, hidden
    #     imports y una licencia más que declarar — todo para parsear un sobre.
    #   · base64 infla 33 % y obliga a sostener el archivo DOS veces en memoria (el string
    #     y los bytes). El tope de 25 MB del store se volvería 33 MB de body por nada.
    # El nombre viaja por query, que es el único dato que el sobre traía.

    @router.post("/sessions/{sid}/inbox", status_code=201)
    async def inbox_subir(sid: str, request: Request,
                          nombre: str = Query(default="adjunto"),
                          authorization: Optional[str] = Header(default=None)):
        """Sube UN adjunto a la conversación. Devuelve su ficha (nombre, ruta, mime, sha256)."""
        from app.phase1 import inbox_store as _ib
        owner = _inbox_chat_gate(sid, authorization)
        datos = await request.body()
        try:
            return _ib.guardar(str(owner), str(sid), nombre, datos)
        except _ib.InboxError as e:
            # 413 para lo que es cuestión de TAMAÑO, 422 para el resto: el cliente puede
            # decidir distinto (sacar un archivo vs elegir otro) y un 400 genérico no
            # le dice cuál de las dos cosas pasó.
            codigo = 413 if e.code in ("muy_grande", "sesion_llena") else 422
            raise HTTPException(status_code=codigo,
                                detail={"error": e.code, "detail": e.detail})

    @router.get("/sessions/{sid}/inbox")
    def inbox_listar(sid: str, authorization: Optional[str] = Header(default=None)):
        """Lo adjunto de esta conversación. Sólo lo que SIGUE en disco."""
        from app.phase1 import inbox_store as _ib
        owner = _inbox_chat_gate(sid, authorization)
        return {"archivos": _ib.listar(str(owner), str(sid))}

    @router.delete("/sessions/{sid}/inbox/{nombre}")
    def inbox_quitar(sid: str, nombre: str,
                     authorization: Optional[str] = Header(default=None)):
        """Saca un adjunto. El nombre se sanea en el store: jamás se usa como ruta."""
        from app.phase1 import inbox_store as _ib
        owner = _inbox_chat_gate(sid, authorization)
        if not _ib.quitar(str(owner), str(sid), str(nombre)):
            raise HTTPException(status_code=404, detail={
                "error": "no_esta", "detail": "Ese adjunto ya no está."})
        return {"ok": True, "nombre": nombre}

    @router.get("/sessions/{sid}/artifacts")
    def artifacts_list(sid: str,
                       authorization: Optional[str] = Header(default=None),
                       token: Optional[str] = Query(default=None)):
        """Lista ORDENADA de artifacts de la sesión (para la Biblioteca = file-browser).
        Lee del estado REAL; lo que no está, no se lista (anti-theater).
        AUTHZ (§4.5, T6): si la sesión tiene dueño, sólo él lista su obra. Sesión anónima
        (legacy, sin dueño ligado) → abierta (no rompe sesiones viejas)."""
        from app.phase1 import artifact_store
        _authorize_resource(artifact_store.get_owner(sid), authorization, token)
        return {"session_id": sid, "artifacts": artifact_store.list_artifacts(sid)}

    @router.get("/sessions/{sid}/artifacts/{aid}")
    def artifact_get(sid: str, aid: str,
                     authorization: Optional[str] = Header(default=None),
                     token: Optional[str] = Query(default=None)):
        from app.phase1 import artifact_store
        _authorize_resource(artifact_store.get_owner(sid), authorization, token)
        a = artifact_store.get_artifact(sid, aid)
        if a is None:
            raise HTTPException(status_code=404, detail={"error": "artifact_not_found", "detail": aid})
        return {"artifact": a}

    @router.get("/sessions/{sid}/artifacts/{aid}/download")
    def artifact_download(sid: str, aid: str, fmt: Optional[str] = Query(default=None),
                          authorization: Optional[str] = Header(default=None),
                          token: Optional[str] = Query(default=None)):
        """DESCARGA POR TIPO: sirve el ARCHIVO REAL de la obra en su formato (no el HTML del
        render ni un markdown disfrazado). Se genera del CONTENIDO y se CACHEA por contenido →
        bajar dos veces NO regenera; editar la obra regenera una vez. Ver `artifact_export`.
        AUTHZ (§4.5, T6): sólo el dueño de la sesión baja el archivo real de su obra. El
        token puede ir por header o `?token=` (la descarga suele ser navegación directa)."""
        from app.phase1 import artifact_store, artifact_export
        _authorize_resource(artifact_store.get_owner(sid), authorization, token)
        a = artifact_store.get_artifact(sid, aid)
        if a is None:
            raise HTTPException(status_code=404, detail={"error": "artifact_not_found", "detail": aid})
        try:
            info = artifact_export.export(a, fmt, sid)
        except Exception as exc:
            raise HTTPException(status_code=500,
                detail={"error": "export_failed", "detail": str(exc)[:200]})
        path = Path(info["path"]).resolve()
        # guard anti path-traversal: la ruta DEBE caer bajo el área de descargas de artifacts.
        dl_root = artifact_export.dl_root().resolve()
        if dl_root != path and dl_root not in path.parents:
            raise HTTPException(status_code=403, detail={"error": "path_forbidden"})
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=410, detail={"error": "file_gone"})
        return FileResponse(str(path), media_type=info["mime"], filename=info["filename"])

    def _build_artifact_provenance(body) -> dict:
        """[Gate 4 · Fase 2 · §3] El bloque de identidad, resuelto SERVER-SIDE.
        El cliente sólo referenció; los hechos salen del events.jsonl del espacio
        (el mismo path que usa el spine, arriba). space_id se sanea ANTES de
        componer path alguno; una ref malformada se descarta, jamás se path-joinea."""
        from artifacts import provenance as _prov   # platform/ en sys.path (main.py:512)
        refs = {
            "space_id": body.space_id, "run_id": body.run_id,
            "chat_id": body.chat_id, "agent_id": body.agent_id,
            "user_id": body.user_id,
            "method_id": body.method_id, "method_run_id": body.method_run_id,
            "produced_by": body.produced_by, "intent": body.intent,
            # [Gate 4 · Fase 3 · 3.4] qué stack heredado lo produjo. Con
            # `produced_by="workspace"` la calidad se topa en `declared`: Aleph midió
            # el modelo del turno, no la función que escribió el contenido.
            "workspace": getattr(body, "workspace", None),
            # [Convergencia · superficie 7] El pasaporte del stack. Con `getattr` porque
            # este constructor lo comparten create, edit y el puente, y sólo el puente
            # los trae: un `body` sin ellos tiene que seguir funcionando igual.
            # Son INERTES — `_cap_workspace` no los mira. Guardarlos es lo que hace que
            # la afirmación del stack se pueda re-derivar en vez de tener que creerla.
            "source_sha256": getattr(body, "source_sha256", None),
            "source_run_ref": getattr(body, "source_run_ref", None),
            "source_commit": getattr(body, "source_commit", None),
        }
        safe_space = _prov.safe_ref(body.space_id)
        events_path = (events_dir() / safe_space / "events.jsonl") if safe_space else None
        return _prov.build(refs, events_path)

    def _artifact_store_call(fn, *args, **kw):
        """Mapea StoreError (borde de escritura tipado) → HTTP visible."""
        from app.phase1.artifact_store import StoreError
        try:
            return fn(*args, **kw)
        except StoreError as exc:
            raise HTTPException(status_code=exc.http_status,
                                detail={"error": exc.code, **exc.detail})

    @router.post("/sessions/{sid}/artifacts", status_code=201)
    def artifact_create(sid: str, body: ArtifactCreateRequest,
                        authorization: Optional[str] = Header(default=None)):
        """AUTHZ (§4.5, T6): el user_id reclamado debe ser el de la sesión; y la sesión, si
        YA tiene dueño, debe ser tuya (no podés escribir en la sesión de otro). La primera
        creación con user_id LIGA el dueño de la sesión (claim-on-first-create).
        [Gate 4 · Fase 2] El artefacto nace con su identidad adentro (provenance
        resuelta de events.jsonl) y su tipo validado contra EL vocabulario."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import artifact_store
        _authorize_resource(artifact_store.get_owner(sid), authorization)
        _artifact_store_call(artifact_store.claim_owner, sid, body.user_id)
        prov = _build_artifact_provenance(body)
        art = _artifact_store_call(artifact_store.create_artifact,
                                   sid, body.title, body.type, body.content, prov)
        return {"artifact": art}

    @router.put("/sessions/{sid}/artifacts/{aid}")
    def artifact_edit(sid: str, aid: str, body: ArtifactEditRequest,
                      authorization: Optional[str] = Header(default=None)):
        """EDIT: snapshot del content previo a versions[] + update (cambio quirúrgico ya aplicado).
        AUTHZ (§4.5, T6): si la sesión tiene dueño, sólo él edita su obra.
        [Gate 4 · Fase 2] El turno que edita re-resuelve la procedencia del contenido
        nuevo; la del previo viaja a versions[] con su contenido (contrato §4)."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import artifact_store
        _authorize_resource(artifact_store.get_owner(sid), authorization)
        # Un edit SIN referencias (sync mecánico de contenido, callers legacy) CONSERVA la
        # identidad existente en vez de pisarla con un bloque vacío; un edit que declara su
        # origen (turno nuevo) la re-resuelve. El snapshot de versión ocurre igual.
        _declared = (body.space_id, body.run_id, body.chat_id, body.agent_id,
                     body.method_id, body.method_run_id, body.produced_by, body.intent,
                     body.workspace)
        prov = _build_artifact_provenance(body) if any(f is not None for f in _declared) else None
        a = _artifact_store_call(artifact_store.edit_artifact,
                                 sid, aid, body.content, body.title, provenance=prov)
        if a is None:
            raise HTTPException(status_code=404, detail={"error": "artifact_not_found", "detail": aid})
        return {"artifact": a}

    @router.post("/sessions/{sid}/artifacts/{aid}/revert")
    def artifact_revert(sid: str, aid: str,
                        authorization: Optional[str] = Header(default=None)):
        """Restaura la ÚLTIMA versión previa (revertir el último edit).
        AUTHZ (§4.5, T6): si la sesión tiene dueño, sólo él revierte su obra."""
        from app.phase1 import artifact_store
        _authorize_resource(artifact_store.get_owner(sid), authorization)
        a = _artifact_store_call(artifact_store.revert_artifact, sid, aid)
        if a is None:
            raise HTTPException(status_code=409,
                detail={"error": "no_version", "detail": "no hay versión previa para revertir"})
        return {"artifact": a}

    # ══ EL BORDE DEL CEREBRO PARA WORKSPACES HEREDADOS ═══════════════════════════
    # [Gate 4 · Fase 3 · obra 3.2 · ley 2] La tercera puerta al cerebro, y la más chica:
    # un PASO. Ver la cabecera de `workspace_brain.py` para el porqué de cada regla.
    #
    # Paridad-mano (Ó8 · ley técnica 5): misma sesión que el humano, misma receta,
    # misma validación, mismo `_route_chat`, mismos eventos del espacio — y MENOS
    # poder: no ejecuta tools, no toca el mundo, no abre el gate.

    def _modelo_crudo(elegido: Optional[str], owner: Optional[str]) -> Optional[dict]:
        """EL MODELO DEL SELECTOR, SIN AGENTE. [Gate 4 · Fase 4 · O6 · LEY 15 · modo raw]

        Devuelve el `model_cfg` que el motor ya sabe consumir —el mismo que
        `models.resolve_recipe_model` recibe— o `None` si no hay ninguno usable.

        **No inventa un puente nuevo.** El mapa `picker_id → {model, base_url, alias |
        byok_ref | brain_provider}` ya existe del lado del servidor y es el que sirve el
        selector (`centro_modelos._PICKER_HOSTEADO`, leído por `selector_modelos`). Un
        segundo mapa acá sería el tercer espacio de ids de modelo, que es un error que esta
        casa ya pagó.

        Sin `elegido`, se usa **lo que el usuario tiene elegido** para el contexto: la ley 15
        dice «el usuario elige modelo del selector y habla», y el selector ya persiste esa
        elección. Así el harness no tiene que acordarse de nada.
        """
        from app.phase1 import centro_modelos as cm
        try:
            # `todos=True` A PROPÓSITO, y lo destapó la vara: el selector en modo pool
            # devuelve sólo «conectados + Default», así que en una instalación SIN LLAVES la
            # lista sale vacía, la fila no se encuentra y el borde contestaba
            # `422 missing_recipe` — o sea «no elegiste modelo» cuando el usuario SÍ había
            # elegido uno y lo que faltaba era la llave. Con el catálogo completo la fila
            # aparece y el fallo se dice por su nombre (`modelo_no_conectado`).
            sel = cm.selector_modelos(owner=owner, get_conn=_conn, contexto="sala", todos=True)
        except Exception:                            # noqa: BLE001 — sin catálogo no hay raw
            return None
        filas = list(sel.get("modelos") or [])
        pedido = str(elegido or "").strip() or str(sel.get("seleccion_id") or "").strip()
        fila = next((f for f in filas if str(f.get("picker_id") or "") == pedido), None)
        if fila is None:
            return None
        if fila.get("conectado") is not True:
            # Causa tipada, no un 500 ni un turno que muere en el proveedor: elegir un
            # modelo sin llave es un estado normal y la pantalla tiene que poder decirlo.
            raise HTTPException(status_code=424, detail={
                "error": "modelo_no_conectado",
                "detail": f"«{fila.get('label') or pedido}» todavía no tiene su llave puesta.",
                "picker_id": pedido})
        cfg = {"primary": fila.get("model") or "", "base_url": fila.get("base_url") or ""}
        for clave in ("alias", "byok_ref", "brain_provider"):
            if fila.get(clave):
                cfg[clave] = fila[clave]
        return cfg if cfg["primary"] else None

    def _brain_recipe(body, authorization: Optional[str]) -> dict:
        """La receta de este paso, por la MISMA puerta que las otras dos vías.

        `puppet_id` es owner-gated (anti-IDOR: ajeno == 404, indistinguible de
        inexistente) y una `recipe` inline es la receta ad-hoc del que llama, igual que
        en `/puppets/run`. Se valida contra el schema antes de gastar un token.

        [LEY 15 · MODO RAW] Y hay un TERCER camino, que es el mínimo suficiente: **sin
        agente y sin receta, con el modelo que el usuario eligió**. No pasa por
        `validate_recipe` —y no es un descuido— porque **lo que viaja no es una receta**:
        es un `model_cfg`. Medido contra el validador: una receta v1 exige `meta.name`,
        `meta.nicho`, `belt.belt_ref` y `belt.tool_filters` NO vacío, así que meter un turno
        raw por ahí obligaría a inventarle a cada mensaje un nombre, un nicho y un cinturón
        — que es exactamente la «receta implícita» vetada por el dueño, y encima contra un
        contrato congelado.

        Que esto sea barato no es casualidad: `workspace_brain.complete()` ya usa **sólo**
        `recipe["model"]` (su única lectura de la receta). El borde ya era raw por dentro;
        lo único que faltaba era dejarlo entrar."""
        recipe = body.recipe
        if body.puppet_id:
            from app.phase1 import repo as _repo
            _runner = _repo.session_owner(_bearer(authorization))
            if not _runner:
                raise HTTPException(status_code=401, detail={
                    "error": "no_session",
                    "detail": "Correr un agente guardado necesita tu sesión."})
            conn = _conn()
            try:
                puppet = _repo.get_puppet(conn, body.puppet_id)
            finally:
                conn.close()
            if puppet is None or str(puppet.get("owner_id")) != str(_runner):
                raise HTTPException(status_code=404,
                                    detail=f"puppet '{body.puppet_id}' no encontrado")
            if recipe is None:
                recipe, _ = _kit.ensure_kit(puppet["config"])
        elif recipe is None:
            # ── EL CAMINO RAW (ley 15) ────────────────────────────────────────────────
            # Devuelve TEMPRANO, sin validar: no es una receta. El turno queda con
            # `agent: null`, que es un estado válido del camino — el circuito entero sigue
            # igual (model_final honesto, ledger, provenance, S8), porque las garantías
            # nunca dependieron del agente.
            from app.phase1 import repo as _repo
            # [B0-4] SIN respaldo a `body.user_id`: un id del cuerpo no crea autoridad. El
            # endpoint ya exigió sesión, así que acá siempre hay dueño; si algún día se
            # llamara desde otro lado sin ella, el `None` hace fallar la selección en vez
            # de resolverla contra el catálogo de un dueño que nadie autenticó.
            dueno = _repo.session_owner(_bearer(authorization))
            cfg = _modelo_crudo(getattr(body, "model", None), dueno)
            if cfg:
                return {"model": cfg}
            raise HTTPException(status_code=422, detail={
                "error": "missing_recipe",
                "detail": "elige un modelo en el selector, o pasa `recipe` inline o `puppet_id`"})
        try:
            rv.validate_recipe(recipe, repo_root=resource_root)
        except rv.RecipeValidationError as exc:
            raise HTTPException(status_code=422, detail={
                "error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings})
        return recipe

    def _brain_measured_model(space_id: str) -> Optional[str]:
        """El ÚLTIMO modelo que Aleph midió en este espacio, leído de lo que Aleph
        mismo escribió (`workspace_step.model`).

        Es el eslabón que hace que `close` no tenga que creerle al harness: el hecho
        central del artefacto (`model_final`) sale del registro firmado, no del body
        de quien pide cerrar."""
        from artifacts import provenance as _prov   # platform/ en sys.path (main.py:512)
        try:
            path = events_dir() / (_prov.safe_ref(space_id) or "") / "events.jsonl"
            raw = path.read_text(encoding="utf-8")
        except Exception:                            # noqa: BLE001 — sin espacio, sin hecho
            return None
        model = None
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = _json.loads(line)
            except Exception:                        # noqa: BLE001
                continue
            if not isinstance(ev, dict):
                continue
            payload = ev.get("payload")
            data = {**ev, **payload} if isinstance(payload, dict) else ev
            if data.get("type") == "workspace_step" and data.get("model"):
                model = str(data["model"])
        return model

    def _preflight_paso(body, authorization):
        """Todo lo que hay que resolver ANTES de gastar cognición en un paso de workspace.

        [B0-3 · fase D] Sale de adentro de `workspace_brain_complete` para que la vía
        BLOQUEANTE y la que STREAMEA hagan exactamente los mismos controles: el dueño, la
        admisión de model-use, el saneo, el presupuesto y el resolver BYOK. Si esto se
        duplicara, la vía nueva podría quedarse sin alguno de ellos —y son justo los que
        B0-1 y B0-4 acaban de cerrar—.

        Devuelve `(recipe, messages, tools, byok_resolver, on_event, dueno, wb)`.
        """
        # [B0-4] EL DUEÑO, ANTES QUE NADA Y SIN CONDICIÓN. Esto era
        # `if body.user_id: _authorize(...)`, así que omitir un campo opcional saltaba el
        # gate entero. Ahora sale de la sesión siempre; `body.user_id` sólo se contrasta.
        _dueno = _dueno_obligatorio(body.user_id, authorization)
        from app.phase1 import credential_broker, workspace_brain as wb
        if not body.lang:
            from workspaces import memoria as ws_memoria
            body.lang = ws_memoria.ajustes(_dueno).get("idioma", "es")
        _raw_model_use = not body.puppet_id and body.recipe is None
        _workspace_id = body.workspace if body.workspace in _WORKSPACE_STACKS else "workspace"

        def _route_workspace(candidate: Optional[dict[str, Any]]):
            return _route_model_use(
                workspace_id=_workspace_id,
                call_class="workspace.step",
                authorization=authorization,
                recipe=candidate,
                selection_ref=body.model if candidate is None else None,
                agent_id=body.puppet_id,
                session_id=body.chat_id,
                task_id=body.space_id,
                entity_id=body.space_id,
                messages=[m for m in body.messages if isinstance(m, dict)],
                tools=[t for t in (body.tools or []) if isinstance(t, dict)],
                required_capabilities=[
                    "text",
                    *(["tool_calling"] if body.tools else []),
                    # [B0-1] La FORMA de la carga es un requisito, no un detalle: si el
                    # paso trae una imagen, un audio o un archivo, el modelo tiene que
                    # declararlo. Antes esto no se miraba porque el saneo aplanaba las
                    # partes a texto y para cuando llegaba al proveedor ya no había imagen
                    # que soportar — la llamada «funcionaba» y el modelo contestaba a
                    # ciegas. Ahora se exige acá y se falla antes del primer token.
                    *sorted(wb.modalidades_de(body.messages)),
                ],
                stream=False,
                call_id=(f"{body.space_id}:{body.turn}" if body.space_id else None),
            )

        # [default por proveedor] EL SNAPSHOT SE MIRA, NO SE TIRA. Trae `fallback_chain`,
        # que es como el resolver dice que el modelo pedido no atendió y que puso otro. El
        # campo existía en el contrato desde el principio y **nadie lo llenaba ni lo leía**;
        # sin este par de líneas el reemplazo sería silencioso, que es justo lo que la casa
        # no acepta. Se guarda en el `_sobre_modelo` de este pedido, que el borde vacía al
        # armar la respuesta.
        _snap = None
        if _raw_model_use:
            # V2 admite y materializa ANTES de la traducción heredada. En legacy/shadow
            # `raw_cfg_v2` queda vacío y recién entonces se usa el camino anterior.
            _, raw_cfg_v2, _snap = _route_workspace(None)
            recipe = ({"model": raw_cfg_v2} if raw_cfg_v2 is not None
                      else _brain_recipe(body, authorization))
        else:
            # Agentes/recetas mantienen primero su owner gate y validación histórica;
            # el gateway sustituye exclusivamente su infraestructura de modelo.
            recipe = _brain_recipe(body, authorization)
            recipe_v2, _, _snap = _route_workspace(recipe)
            if recipe_v2 is not None:
                recipe = recipe_v2
        try:
            messages = wb.sanitize_messages(body.messages)
            tools = wb.sanitize_tools(body.tools)
        except wb.BrainError as exc:
            raise HTTPException(status_code=exc.status,
                                detail={"error": exc.error, "detail": exc.detail})

        # Presupuesto ANTES de gastar cognición, con la MISMA regla que el run: a quién
        # se mide sale de la SESIÓN, no del body (omitir el campo no esquiva el cap).
        from app.phase1 import billing
        conn = _conn()
        try:
            # [B0-4] El cap ya no es condicional: el dueño existe siempre, así que no hay
            # forma de esquivar el presupuesto omitiendo un campo.
            _pf = billing.preflight(conn, _dueno)
            if not _pf["allowed"]:
                raise HTTPException(status_code=402,
                                    detail={"error": "over_budget", **_pf})
        finally:
            conn.close()

        # [B0-4] EL DUEÑO DE LA SESIÓN, NO EL DEL CUERPO. Con `body.user_id` opcional, un
        # paso sin ese campo se quedaba sin resolver BYOK —las llaves del usuario no
        # entraban— y el costo no quedaba atribuido a nadie. Las dos cosas ahora cuelgan
        # del dueño que el endpoint ya exigió.
        byok_resolver = credential_broker.make_user_resolver(_dueno, get_conn=get_conn)
        on_event = _make_space_emitter(body.space_id) if body.space_id else None
        # El aviso del reemplazo, si lo hubo. Va por el sobre y no por la tupla de retorno
        # para no cambiarle la aridad a algo que otras sesiones están tocando.
        _sobre_modelo.poner(_snap)
        return recipe, messages, tools, byok_resolver, on_event, _dueno, wb

    @router.post("/workspaces/brain/complete")
    def workspace_brain_complete(body: WorkspaceBrainRequest,
                                 authorization: Optional[str] = Header(default=None)):
        """UN paso del harness de un workspace heredado (ley 2 · obra 3.2).

        Entran los mensajes y los schemas de SUS funciones; sale la jugada del modelo
        (texto o `tool_calls`). Aleph no ejecuta nada del harness — las tools del stack
        las corre el stack. El evento que queda en el espacio es `workspace_step`
        (informativo), JAMÁS `tool_call_finished`: escribir la señal de «corrió» por lo
        que otro proceso declara es fabricar el hecho que el anti-grift juzga."""
        (recipe, messages, tools, byok_resolver, on_event, _dueno,
         wb) = _preflight_paso(body, authorization)

        # ══ [Obra 1.b · EXPERIMENTO] CODE EXECUTION EN EL BORDE ═══════════════════════
        # PERILLA POR STACK (`ALEPH_CODE_EXECUTION_WS=ciencia`). Apagada, esto es
        # byte-idéntico al camino de siempre: `paso()` devuelve `None` y no se ejecuta.
        #
        # Lo que cambia cuando está encendida: el modelo recibe UNA tool en vez del
        # catálogo y escribe un script; el script se SUSPENDE cada vez que llama a una
        # tool del stack, y esa llamada se le devuelve al stack **en su formato de
        # siempre, con su id**. El stack la ejecuta —él, no Aleph— y vuelve con el
        # resultado, que despierta al script. **El stack no se entera de nada.**
        #
        # El ahorro son LAS CRUCES: los pasos intermedios no llaman al modelo, así que
        # el catálogo deja de viajar en cada uno.
        _cm_out = None
        try:
            from app.phase1 import codemode_borde as _cmb
            if _cmb.encendido_para(body.workspace or ""):
                # ══ [obra 2] LA COMPOSICIÓN: LAS DOS JUNTAS, NO UNA U OTRA ═══════
                # Hasta acá las dos técnicas se EXCLUÍAN, y era de cableado: el bloque
                # del plegado vivía bajo `if _cm_out is None`, así que cuando code
                # execution resolvía el paso el plegado **no se intentaba nunca**.
                # Medido: en Oficina eso hacía que las salidas siguieran siendo el
                # 72,5 % del prompt con code execution puesto.
                #
                # Se levanta porque las dos firmas de `llamar_modelo` son LA MISMA
                # —`(messages, tools) -> out`—, así que el plegado se mete ADENTRO del
                # closure con el que code execution llama al modelo. Cada una sigue
                # mandando en su terreno y ninguna sabe de la otra:
                #   · code execution manda EL BUCLE (cuántas veces se cruza)
                #   · el plegado manda LA CARGA (qué lleva cada cruce)
                # No se toca una línea de ninguno de los dos módulos.
                def _crudo(_msgs, _tools):
                    return wb.complete(
                        recipe, _msgs, _tools,
                        byok_resolver=byok_resolver, on_event=on_event,
                        user_id=_dueno, workspace=(body.workspace or "")[:40],
                        turn=int(body.turn or 1), lang=body.lang,
                        max_tokens=body.max_tokens, temperature=body.temperature,
                        tool_choice=None,
                    )

                def _llamar_modelo(_msgs, _tools):
                    # `tool_choice` NO se reenvía en estas llamadas: el stack lo eligió
                    # para SU catálogo, y acá el catálogo es otro. Exigir por nombre una
                    # tool que ya no está declarada haría fallar el paso; exigir "alguna"
                    # con una sola declarada no agrega nada. Queda anotado, no silencioso.
                    # el plegado, si su perilla nombra a este stack. `paso` devuelve
                    # `None` cuando no hay nada plegado: ahí se llama crudo y el camino
                    # queda byte-idéntico al de code execution solo.
                    try:
                        from app.phase1 import salidas_diferidas as _sd2
                        if _sd2.encendido_para(body.workspace or ""):
                            _r = _sd2.paso(
                                clave="ce:%s:%s" % ((body.workspace or "ws"),
                                                    (body.chat_id or "sin-chat")),
                                workspace=(body.workspace or ""), messages=_msgs,
                                tools=_tools, llamar_modelo=_crudo, on_event=on_event)
                            if _r is not None:
                                return _r
                    except Exception:           # noqa: BLE001 — nunca tumba el turno
                        _logging.getLogger(__name__).warning(
                            "composición plegado+code execution: caí al crudo",
                            exc_info=True)
                    return _crudo(_msgs, _tools)
                _cm_out = _cmb.paso(
                    # La clave tiene que ser ESTABLE entre los pasos de un turno y propia
                    # de cada workspace. El `chat_id` lo es: el loop del stack lo mantiene.
                    clave="%s:%s" % ((body.workspace or "ws"), (body.chat_id or "sin-chat")),
                    workspace=(body.workspace or ""), messages=messages, tools=tools,
                    llamar_modelo=_llamar_modelo, on_event=on_event)
        except Exception:                       # noqa: BLE001 — el experimento NO puede
            # tumbar el turno: si algo se rompe acá, se cae al camino de siempre y se dice.
            _logging.getLogger(__name__).warning(
                "codemode_borde: caí al camino normal", exc_info=True)
            _cm_out = None

        # ══ [Obra A] LAS SALIDAS DE TOOLS, DIFERIDAS ═════════════════════════════════
        # PERILLA POR STACK (`ALEPH_SALIDAS_DIFERIDAS_WS=oficina`). Apagada, esto es
        # byte-idéntico al camino de siempre: `paso()` devuelve `None`.
        #
        # QUÉ ARREGLA, con el número que lo justifica: los seis workspaces cruzan con
        # `sesion=None`, así que `server._armar_prompt` re-manda el historial ENTERO en
        # cada paso. Medido el 2026-08-22 en Oficina, 3 turnos reales desde la pantalla:
        # el `read` de un CSV de 12,7 KB pesa 7.358 tokens y cruzó 7 VECES — 51.506
        # tokens pagados, el 73 % del prompt de toda la conversación.
        #
        # Lo que se difiere es la REPETICIÓN, nunca la primera lectura: la salida más
        # nueva jamás se pliega, y todo lo que se recorta se declara con su tamaño y con
        # la llamada exacta para recuperarlo. El stack no se entera: manda y recibe lo
        # de siempre, y la tool del lector no le llega nunca.
        #
        # Este bloque es el plegado SOLO — cuando code execution no corrió. Si corrió,
        # el plegado ya actuó ADENTRO de su closure (ver la composición, más arriba), y
        # volver a plegar acá sería plegar dos veces.
        if _cm_out is None:
            try:
                from app.phase1 import salidas_diferidas as _sd
                if _sd.encendido_para(body.workspace or ""):
                    def _llamar_modelo_sd(_msgs, _tools):
                        return wb.complete(
                            recipe, _msgs, _tools,
                            byok_resolver=byok_resolver, on_event=on_event,
                            user_id=_dueno, workspace=(body.workspace or "")[:40],
                            turn=int(body.turn or 1), lang=body.lang,
                            max_tokens=body.max_tokens, temperature=body.temperature,
                            tool_choice=body.tool_choice,
                        )
                    _cm_out = _sd.paso(
                        clave="%s:%s" % ((body.workspace or "ws"),
                                         (body.chat_id or "sin-chat")),
                        workspace=(body.workspace or ""), messages=messages, tools=tools,
                        llamar_modelo=_llamar_modelo_sd, on_event=on_event)
            except Exception:               # noqa: BLE001 — no puede tumbar el turno
                _logging.getLogger(__name__).warning(
                    "salidas_diferidas: caí al camino normal", exc_info=True)
                _cm_out = None

        # ══ [Obra B] EL MISMO PEDIDO, DOS VECES ══════════════════════════════════════
        # PERILLA POR STACK (`ALEPH_ECO_AUXILIAR_WS=ciencia`). Apagada, no hace nada.
        #
        # Medido en Ciencia: el agente auxiliar (`You are a title generator`) recibe el
        # MISMO prompt byte por byte DOS VECES POR TURNO, con 6-8 s de diferencia
        # (hashes `fb44103853c56565` y `cb63c57faad3d662`, dos cruces cada uno). Y no es
        # un reintento nuestro: el tap que los grabó corre una vez por pedido HTTP.
        #
        # ⚠️ CORRIGE LA PREMISA DEL BRIEF: ese agente **no recibe 25 tools**, recibe CERO.
        # Podar tools no ahorraba nada ahí. Lo que se paga es la llamada repetida.
        #
        # Sólo aplica a llamadas SIN tools —una transformación de texto pura, sin
        # efectos— y contesta como mucho UNA repetición por clave. El paso se emite
        # igual; lo que no se emite es cost-event, porque no hubo llamada al modelo.
        _eco_out = None
        if os.environ.get("ALEPH_ECO_DIAG"):
            print("[eco·diag] ws=%r tools=%d cm_out=%s msgs=%d" % (
                body.workspace, len(tools or []), _cm_out is not None,
                len(messages or [])), flush=True)
        if _cm_out is None and not tools:
            try:
                from app.phase1 import llamada_repetida as _lr
                _eco_out = _lr.paso(
                    clave="%s:%s" % ((body.workspace or "ws"),
                                     (body.chat_id or "sin-chat")),
                    workspace=(body.workspace or ""), messages=messages, tools=tools,
                    max_tokens=body.max_tokens, temperature=body.temperature,
                    on_event=on_event,
                    llamar_modelo=lambda: wb.complete(
                        recipe, messages, tools,
                        byok_resolver=byok_resolver, on_event=on_event,
                        user_id=_dueno, workspace=(body.workspace or "")[:40],
                        turn=int(body.turn or 1), lang=body.lang,
                        max_tokens=body.max_tokens, temperature=body.temperature,
                        tool_choice=body.tool_choice,
                    ))
            except Exception:               # noqa: BLE001 — no puede tumbar el turno
                _logging.getLogger(__name__).warning(
                    "llamada_repetida: caí al camino normal", exc_info=True)
                _eco_out = None
        if _eco_out is not None:
            _cm_out = _eco_out

        try:
            out = _cm_out if _cm_out is not None else wb.complete(
                recipe, messages, tools,
                byok_resolver=byok_resolver, on_event=on_event,
                user_id=_dueno, workspace=(body.workspace or "")[:40],
                turn=int(body.turn or 1), lang=body.lang,
                max_tokens=body.max_tokens, temperature=body.temperature,
                tool_choice=body.tool_choice,
            )
        except HTTPException:
            raise
        except Exception as exc:                     # noqa: BLE001
            # FALLO VISIBLE: la causa tipada del traductor viaja al harness para que su
            # propia consola diga QUÉ pasó, en vez de «the model request failed».
            causa = None
            try:
                from app.phase1 import stream_chat as _sc
                _c = _sc._causa_de_error(exc)
                causa = _c if isinstance(_c, str) else None
            except Exception:                        # noqa: BLE001
                pass
            # ── [Gate 4 · F5 · 5.1] UN 413 NO ES «EL CEREBRO NO ESTÁ» ────────────────
            # `brain_unavailable` con un 502 le dice al harness —y a su consola, que es
            # lo que el usuario lee— que Aleph se cayó. Con un pedido demasiado grande eso
            # es literalmente falso: el cerebro contestó, y contestó que no le entra.
            # La diferencia no es cosmética: ante «no está» se espera y se reintenta igual;
            # ante «no entra» hay que mandar menos. Se conserva la causa sellada en `causa`
            # (el mismo campo de siempre) y se devuelve el status que el proveedor usó.
            if causa == "contexto_excedido":
                raise HTTPException(status_code=413, detail={
                    "error": "request_too_large", "causa": causa,
                    "detail": str(exc)[:400]})
            raise HTTPException(status_code=502, detail={
                "error": "brain_unavailable", "causa": causa, "detail": str(exc)[:400]})

        # Ingesta del costo (idempotente por evento; jamás tumba el paso). Un workspace
        # heredado gasta cognición de la casa: si no entra al ledger, es un agujero.
        try:
            conn = _conn()
            try:
                billing.record_run_cost(conn, run_id=None, user_id=body.user_id,
                                        cost_events=out.get("cost_events") or [])
            finally:
                conn.close()
        except Exception:                            # noqa: BLE001
            pass
        out.pop("cost_events", None)
        return out

    # ── EL BORDE DE DIALECTO ───────────────────────────────────────────────────────
    # [Gate 4 · F3-ciencia · ley 0 costura (1)]
    #
    # POR QUÉ EXISTE. El circuito certificado en Gate 2/2.5 es un **cliente** de
    # OpenAI-compatible: `assembler.py` arma `base_url + "/chat/completions"` y sale a
    # pedir. Un stack heredado con capa de proveedores propia también es un cliente de
    # lo mismo. Dos clientes, ningún servidor: por eso un stack así no podía enchufarse
    # a la casa sin que alguien tradujera el dialecto.
    #
    # LO QUE **NO** ES: no es un camino alternativo al cerebro. Este borde no resuelve
    # modelos, no rutea, no habla con ningún proveedor y no escribe eventos. Traduce la
    # FORMA y llama a `workspace_brain_complete` — el mismo paso, con su preflight de
    # presupuesto, su receta validada, su BYOK, su emisor de espacio y su ledger. Si
    # mañana cambia el circuito, este borde no se entera, que es exactamente lo que se
    # busca: la puerta nueva no puede divergir de la vieja porque **es** la vieja.
    #
    # Es la misma regla que gobierna el puente de artefactos: se adapta la forma, jamás
    # el dato. Acá el único dato que este borde deriva es `finish_reason` cuando el
    # proveedor no lo mandó, y se deriva de la forma del propio payload (hay tool_calls
    # o no hay), no de una suposición sobre qué quiso decir el modelo.

    def _aviso_degradado(degraded: Optional[dict]) -> str:
        """[obra 3] EL ANUNCIO QUE CORTA. Vacío si el turno lo contestó quien correspondía.

        POR QUÉ EN EL TEXTO, que es una decisión fea y deliberada. Cuando la red de
        seguridad dispara, el turno lo contesta un modelo que el usuario NO eligió. Eso ya
        se anunciaba —`aleph.degraded` en el sobre, `notice` en el espacio— y está MEDIDO
        que no lo ve nadie: son campos JSON que cada harness ajeno decide si mirar, y
        ninguno de los seis los mira. Un aviso que la persona no puede ver no es un aviso.

        El texto es el ÚNICO canal que atraviesa seis harnesses distintos sin pedirles que
        cambien una línea (LEY 0). Cuesta ensuciar la respuesta; se paga a cambio de que
        «te contestó otro modelo» deje de ser un secreto. La alternativa medida era el
        silencio.

        NO reemplaza al sobre: `aleph.degraded` sigue viajando entero para la máquina. Esto
        es para los ojos.
        """
        if not isinstance(degraded, dict):
            return ""
        real = degraded.get("actual_model") or "otro modelo"
        querido = degraded.get("intended_model") or "el cerebro que elegiste"
        return (f"⚠️ **{querido} no está disponible ahora, así que este turno lo contestó "
                f"`{real}`** — un modelo local de respaldo, no el que elegiste. "
                f"La respuesta puede ser peor.\n\n")

    def _openai_message(out: dict) -> dict:
        """La jugada de la casa, en la forma que un cliente OpenAI sabe leer."""
        _aviso = _aviso_degradado(out.get("degraded"))
        _cont = out.get("content")
        msg: dict = {"role": "assistant",
                     "content": ((_aviso + _cont) if (_aviso and _cont) else (_aviso or _cont))}
        calls = out.get("tool_calls") or []
        if calls:
            msg["tool_calls"] = [{
                "id": c.get("id") or "call",
                "type": "function",
                # `arguments` viaja crudo (string JSON) desde `workspace_brain`, que es
                # lo que el contrato de OpenAI pide. No se re-serializa ni se valida acá.
                "function": {"name": c.get("name"), "arguments": c.get("arguments") or "{}"},
            } for c in calls]
        return msg

    #: Los estados que el SDK de OpenAI REINTENTA solo. Es su contrato, no una opinión
    #: nuestra: `408, 409, 429, >=500`, con `maxRetries: 2` — o sea 3 intentos.
    _REINTENTA_EL_SDK = frozenset({408, 409, 429})

    #: Y las causas que NO pueden mejorar con un reintento: el modelo elegido no declara
    #: la capacidad que el turno necesita, y va a seguir sin declararla en el intento 2 y
    #: en el 3. Se bajan a 400, que el SDK entrega SIN reintentar.
    #
    # LA LISTA COMPLETA, sacada con un parseo AST de cada `ResolutionFailure` del árbol —
    # y hubo que rehacerla, porque el primer barrido fue con un regex y el regex mintió:
    # leía el status sólo si estaba en su propia línea, así que dio «409 por default» para
    # `no_session`, que declara **401** en la misma línea del mensaje. Un instrumento que
    # lee de menos no da rojo: da un dato equivocado con cara de dato.
    #
    #   409 · capability_unavailable · capability_unknown · model_unresolved
    #   409 · selection_missing (no declara status: se lleva el 409 por default)
    #   409 · selection_unmapped        (router.py:1648)
    #   409 · selection_not_found       (model_use_execution.py:99)  ← el resolver la tira
    #                                    404, pero la ejecución la tira 409. Dos sitios,
    #                                    dos status, la misma causa.
    #   ── y las que NUNCA entran acá porque su status no se reintenta ──
    #   401 · no_session          424 · model_not_connected    404 · selection_not_found
    #
    # `no_session` se queda igual en el conjunto: la pertenencia es de la CAUSA («un
    # reintento no la arregla»), no del status, y el `if` de abajo ya exige las dos cosas.
    _NO_SE_ARREGLA_REINTENTANDO = frozenset({
        "capability_unavailable", "capability_unknown", "selection_unmapped",
        "model_unresolved", "no_session", "selection_missing", "selection_not_found",
    })

    def _error_openai(status: int, det: dict):
        """El error, EN EL SOBRE QUE UN CLIENTE OPENAI SABE ABRIR.

        DOS DEFECTOS MEDIDOS, y los dos se ven en el mismo renglón del log del pack:

            `409 status code (no body)`   ×3 por cada imagen

        1 · **EL CUERPO NO ESTABA VACÍO: ESTABA ANIDADO.** Se armaba el objeto `error`
            correcto y después se lo metía adentro de un `HTTPException`, que FastAPI
            serializa como `{"detail": …}`. Un cliente OpenAI lee `body.error`; acá vivía
            en `body.detail.error`, así que no encontraba nada y reportaba «no body».
            La causa viajaba entera y **no la leía nadie**. Ahora va donde su contrato dice.

        2 · **LOS TRES INTENTOS SON EL STATUS, NO EL CUERPO.** El SDK de OpenAI reintenta
            solo en `408/409/429/5xx` con `maxRetries: 2`: 1 + 2 = los **3 intentos**
            exactos que se midieron (12 cruces de 43 en una conversación de Diseño, el
            28 %). Un `capability_unavailable` no mejora reintentando —el modelo va a
            seguir sin declarar `vision`—, así que baja a **400**, que el SDK entrega sin
            reintentar. Lo que se reintenta sigue reintentándose: esto no toca 429 ni 5xx.

        ⚠️ NO ARREGLA LA VISIÓN NI CAMBIA EL CEREBRO. El gate sigue negándose, y hace
        bien. Lo único que cambia es que ahora el stack **puede enterarse de por qué**.
        """
        causa = str(det.get("error") or "brain_error")
        if status in _REINTENTA_EL_SDK and causa in _NO_SE_ARREGLA_REINTENTANDO:
            status = 400
        return JSONResponse(status_code=status, content={"error": {
            "message": str(det.get("detail") or det.get("error") or "brain error"),
            "type": causa,
            # El `code` del contrato: la causa tipada de la casa, que es lo accionable.
            # Antes iba `det.get("causa")`, que para estos fallos es `None` — un campo
            # nulo donde había un dato.
            "code": det.get("causa") or causa,
            "aleph": det,
        }})

    def _openai_finish(out: dict) -> str:
        """El `finish_reason` que exige el sobre de OpenAI.

        Se usa el del proveedor si vino. Si no vino, se deriva de la FORMA del payload:
        un turno que pidió herramientas es `tool_calls`, uno que no, `stop`. Es
        derivación de forma, no invención de dato: la información ya está en el mismo
        objeto, sólo que en otro campo."""
        fr = out.get("finish_reason")
        if isinstance(fr, str) and fr:
            return fr
        return "tool_calls" if (out.get("tool_calls") or []) else "stop"

    @router.post("/workspaces/brain/openai/chat/completions")
    def workspace_brain_openai(body: WorkspaceBrainOpenAIRequest,
                               request: Request,
                               authorization: Optional[str] = Header(default=None),
                               x_aleph_puppet: Optional[str] = Header(default=None),
                               x_aleph_workspace: Optional[str] = Header(default=None),
                               x_aleph_space: Optional[str] = Header(default=None),
                               x_aleph_user: Optional[str] = Header(default=None),
                               x_aleph_chat: Optional[str] = Header(default=None),
                               x_aleph_turn: Optional[str] = Header(default=None),
                               x_aleph_model: Optional[str] = Header(default=None),
                               x_aleph_turno_id: Optional[str] = Header(default=None),
                               x_aleph_deadline_epoch: Optional[str] = Header(default=None),
                               x_aleph_sesion: Optional[str] = Header(default=None),
                               x_aleph_lang: Optional[str] = Header(default=None)):
        """UN paso del harness de un workspace heredado, **en dialecto OpenAI**.

        Mismo paso que `POST /v1/workspaces/brain/complete`: este endpoint arma el cuerpo
        de la casa y lo llama. Lo que cambia es sólo el sobre de entrada y el de salida.

        LO QUE ENTRA: el cuerpo de `/v1/chat/completions` que manda cualquier cliente
        OpenAI. Lo que ese cuerpo no puede llevar viaja en cabeceras — la config de un
        stack heredado permite mandar cabeceras sin tocarle una línea de código, así que
        la cirugía del lado del stack sigue siendo **config pura**:

            Authorization: Bearer <sesión de Aleph>   quién es (el mismo `_authorize`)
            X-Aleph-Puppet:    <puppet_id>            de qué receta sale el cerebro
            X-Aleph-Workspace: ciencia                quién pide (va al `workspace_step`)
            X-Aleph-Space:     <space_id>             dónde se anota el paso
            X-Aleph-User:      <user_id>              a quién se le mide el presupuesto
            X-Aleph-Chat:      <chat_id>              el hilo, si lo hay
            X-Aleph-Turn:      <n>                    el turno del loop ajeno
            X-Aleph-Turno-Id:       <id>              el MISMO id para el pedido y sus reintentos
            X-Aleph-Deadline-Epoch: <epoch>           el MISMO corte para todos ellos
            X-Aleph-Sesion:         <id>              la CONVERSACIÓN (no el intento)

        `X-Aleph-Sesion` se **espacia por workspace** antes de bajarla: la clave la elige el
        stack y dos stacks distintos podrían elegir la misma. Prefijar con el workspace hace
        que una clave ajena no pueda alcanzar la conversación de otro.

        **EL SOBRE DEL TURNO SE REENVÍA, NO SE FABRICA.** Las dos últimas son el sobre que
        el stack le pone a su intento, y este borde las TIRABA: medido 2026-08-15, el mismo
        sobre entregado directo al `:8926` llegaba entero (`remaining_s = 24,98`) y por acá
        llegaba inventado (`180,0`). Consecuencia medida en el turno Apple: sus 5
        ejecuciones del CLI recibieron 180 s CADA UNA, así que el techo real de un turno no
        era 180 s sino 180 s por ejecución. Ahora se dejan puestas en el contexto y
        `assembler._preparar_pedido` las baja al `:8926` — sólo cuando el destino es ese
        server, nunca hacia un proveedor remoto.

        **`model` del cuerpo se ignora.** El cerebro lo elige la receta; el `model` que
        vuelve en la respuesta es el `model_final` honesto (el que reportó el proveedor),
        que es justamente el dato que la tarjeta y el anti-grift leen.

        `usage` se **omite** cuando no hubo medición, igual que en el resto de la casa: un
        dict de ceros contaría como llamada medida y rompería el único contador de
        honestidad que tenemos."""
        # ══ QUIÉN PIDE, CUANDO NO LO DICE ═════════════════════════════════════════════
        # La cabecera manda. Cuando NO viene —Diseño no la manda, medido contra la pantalla
        # el 2026-08-22: 5 pasos, los 5 con `X-Aleph-Workspace` ausente— la identidad se
        # RECUERDA en vez de perderse: el `chat_id` que llega en `X-Aleph-Chat` es, byte por
        # byte, el que esta casa le repartió al pack en su `enter`.
        #
        # NO ES UN RESPALDO COSMÉTICO. Con `workspace=""` el turno cae en un stack que no
        # existe, y de ahí cuelgan dos cosas medidas: ninguna perilla por stack lo alcanza
        # (`encendido_para("")` es siempre False) y su hilo de la casa se queda vacío
        # (`le_toca_al_borde(_WORKSPACE_STACKS.get(""))` es False — el hilo de Diseño tenía
        # 0 mensajes con ciencia/legal/oficina en 24/5/18).
        #
        # LO QUE **NO** SE HACE ACÁ: adivinar. Si la casa no repartió nada que reconocer, el
        # workspace queda vacío igual que antes y el turno corre exactamente como hoy. Ver
        # `pack.workspace_de` para las tres llaves que se midieron y por qué dos no sirven.
        _ws_pedido = (x_aleph_workspace or "").strip()
        _ws_recordado = ""
        if not _ws_pedido:
            try:
                from workspaces import pack as _ws_pack
                _ws_recordado = _ws_pack.workspace_de(chat_id=x_aleph_chat,
                                                      space_id=x_aleph_space)
            except Exception:                                # noqa: BLE001
                # La identidad es una MEJORA del turno, jamás su camino crítico.
                _log.warning("identidad del borde: no se pudo consultar el registro",
                             exc_info=True)
        _ws = _ws_pedido or _ws_recordado
        # ══ LAS MARCAS DEL CAMINO DEL WORKSPACE (`ALEPH_ETAPAS=1`) ═══════════════════
        # El tap existía desde `ebd0f379` y medía UN camino: el de la Sala (`run.*`,
        # `exec.*`, `asm.*`). El de los workspaces —el que recorren los seis stacks— no
        # tenía una sola marca, así que la tanda de latencia que bajó la Sala de 13 a 4,6 s
        # no se pudo repetir acá: no había con qué ver dónde se va el tiempo.
        #
        # Mismo prefijo por familia que ya usan las otras (`ws.*`), misma regla: UNA línea
        # en el BORDE de cada etapa, los deltas se calculan después y fuera del turno.
        # Apagadas cuestan una comparación.
        _obs.marca("ws.entra", ws=_ws or "", stream=bool(body.stream),
                   n_messages=len(body.messages or []), n_tools=len(body.tools or []))

        def _perilla_stream() -> str:
            """Sólo para el instrumento: qué contesta una perilla POR STACK con este `_ws`.
            Función pura del entorno; no decide nada del turno."""
            try:
                from app.phase1 import model_route_flags as _f
                return _f.modo_stream(_ws).value
            except Exception:                                # noqa: BLE001
                return "?"

        # [medición · identidad de Diseño] QUÉ LLEGA DE VERDAD AL BORDE, cabecera por
        # cabecera, más el puerto de origen del socket. Apagado sin `ALEPH_GRABAR_CABECERAS`.
        # Es el único instrumento que puede decir si la identidad se perdió y con qué
        # material se puede recuperar; nunca levanta.
        try:
            _rc = (os.environ.get("ALEPH_GRABAR_CABECERAS") or "").strip()
            if _rc:
                _cli = getattr(request, "client", None)
                with open(_rc, "a", encoding="utf-8") as _fh:
                    _fh.write(_json.dumps({
                        "ts": _time.time(),
                        "cabeceras": {k: v for k, v in request.headers.items()
                                      if k.lower().startswith("x-aleph")
                                      or k.lower() in ("authorization", "user-agent", "host")},
                        "cliente": [getattr(_cli, "host", None), getattr(_cli, "port", None)],
                        "n_tools": len(body.tools or []),
                        "n_messages": len(body.messages or []),
                        "ws_visto": (x_aleph_workspace or "?"),
                        "ws_recordado": _ws_recordado,
                        "ws_usado": _ws or "",
                        # LA PERILLA POR STACK, RESUELTA CON LO QUE EL BORDE VA A USAR.
                        # Es el hecho que la deuda pedía ver: con `workspace=""` ninguna
                        # perilla por stack podía alcanzar a Diseño, porque su clave de
                        # entorno se arma con el nombre del workspace.
                        "perilla_stream": _perilla_stream(),
                    }, ensure_ascii=False, default=str) + "\n")
        except Exception:                                    # noqa: BLE001
            pass
        # [medición · tanda de tokens] QUÉ CATÁLOGO CRUZA DE VERDAD, por workspace.
        # Apagado sin `ALEPH_GRABAR_TOOLS`. Una línea por PASO → contar líneas da el K real.
        #
        # ⚠️ LA SUPERFICIE ES `_ws`, NO LA CABECERA. Con la cabecera cruda, los 5 pasos de
        # Diseño se anotaban como `'?'` y el K real del stack quedaba sin dueño: el
        # grabador medía «alguien cruzó 5 veces» sin poder decir quién. Ahora anota lo
        # MISMO que el borde va a usar, que es la única forma de que la tabla de cruces y
        # la perilla hablen del mismo workspace.
        try:
            from grabador_tools import grabar as _grabar_tools
            _grabar_tools(_ws or "?", body.tools, paso="brain_openai",
                          extra={"n_messages": len(body.messages or []),
                                 "ws_cabecera": (x_aleph_workspace or ""),
                                 "ws_recordado": _ws_recordado})
        except Exception:
            pass
        # [medición · obra A · salidas de tools] DE QUÉ ESTÁ HECHO lo que cruza, con
        # el workspace puesto. Acá los `messages` son los que manda EL STACK, antes de
        # que Aleph le agregue nada — la otra mitad la toma `server._armar_prompt`.
        # Apagado sin `ALEPH_GRABAR_PROMPT`. Graba crudo: tokeniza `analizar_prompt.py`.
        try:
            from grabador_prompt import grabar_cruce as _grabar_prompt
            # ⚠️ LA SUPERFICIE ES `_ws`, NO LA CABECERA — el mismo arreglo que ya se le
            # hizo al grabador de tools. Diseño no manda `X-Aleph-Workspace`, así que con
            # la cabecera cruda sus 43 cruces se anotaban como `'?'` y el reparto quedaba
            # sin dueño: imposible separar lo suyo de un pack ajeno vivo en el mismo tap.
            _grabar_prompt("borde", _ws or "?",
                           [m.model_dump() if hasattr(m, "model_dump") else m
                            for m in (body.messages or [])],
                           body.tools, body.tool_choice, paso="brain_openai",
                           extra={"chat": x_aleph_chat or "", "turn": x_aleph_turn or "",
                                  "space": x_aleph_space or ""})
        except Exception:
            pass
        equiv = WorkspaceBrainRequest(
            lang=body.lang or x_aleph_lang,
            puppet_id=(x_aleph_puppet or None),
            # [LEY 15] `X-Aleph-Model` es el picker_id del SELECTOR DE LA CASA, no el
            # `model` del body: ése se sigue ignorando a propósito (el harness no elige
            # cerebro). Sin agente y sin esta cabecera, se usa lo que el usuario tenga
            # elegido.
            model=(x_aleph_model or None),
            user_id=(x_aleph_user or None),
            space_id=(x_aleph_space or None),
            chat_id=(x_aleph_chat or None),
            workspace=_ws,
            turn=_turno_de(x_aleph_turn),
            messages=body.messages,
            tools=body.tools,
            tool_choice=body.tool_choice,   # [B0-2] el harness OpenAI ya lo manda; se honra
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        )
        # LA CONVERSACIÓN, ESPACIADA POR WORKSPACE. La clave la elige el stack (para
        # Finanzas es su `session_id`), y dos stacks distintos podrían elegir la misma sin
        # saberlo. Prefijarla con el workspace hace imposible que una clave alcance la
        # conversación de otro — y cuesta una línea, contra un modo de fallo que sería
        # «contestar con el contexto de otro», que es justo lo que el server dice evitar.
        # ══════════════════════════════════════════════════════════════════════════════
        # INTEGRACIÓN · LAS DOS COSTURAS DE SESIÓN ERAN UNA SOLA. QUEDÓ LA ESCALERA.
        #
        # `b8c3fff2` (Legal/Ciencia/Oficina) y `88d9c406` (Diseño) escribían LA MISMA
        # LÍNEA, cada una sin saber de la otra. Dos implementaciones de lo mismo es
        # exactamente lo que esta casa demolió con 4.592 líneas, así que queda UNA.
        #
        # GANA LA ESCALERA, y no por ser más nueva: la otra tiene DOS peldaños
        # (`sesion` → `chat`) y **Legal no manda ninguno de los dos** — su config sólo
        # lleva `X-Aleph-Workspace`. Con dos peldaños la clave de Legal sale `None`, no
        # hay sesión, y su 66 % de prompt cacheado no existe. La escalera además trae
        # tres arreglos que la otra nunca vio, los tres medidos:
        #   · la visita se matchea en base36 — el plugin de Ciencia no usa `%x`, y con
        #     `[0-9a-f]` el peldaño estaba MUERTO en Ciencia sin una sola señal;
        #   · el hilo hashea sólo la parte humana — el harness regenera su andamiaje en
        #     cada turno, y con él adentro la sesión se reabría siempre (21 % vs 66 %);
        #   · el `#hilo` va en TODOS los peldaños que Aleph infiere — en Legal el agente
        #     `router` y el de Q&A comparten `X-Aleph-Chat` y caían en la misma sesión.
        #
        # NO SE PIERDE NADA DE LA OTRA. Sus dos piezas siguen enteras y son las que hacen
        # que esto pueda estar PRENDIDO por default:
        #   · `sesiones.prefijo_vivo` — la cola sólo sale si el principio no cambió, así
        #     que una clave demasiado gruesa cuesta un render completo de más, JAMÁS una
        #     cola pegada sobre otra charla;
        #   · `sesiones.RESUME_PROBADO` — y sólo con un CLI que sepa continuar. Con Grok
        #     la entrega se rompía (timeout 176 s + exit 1); ahí la clave se ignora en el
        #     server, que es quien sabe qué CLI atiende. Sin esa lista esto no podría
        #     estar prendido.
        # Y su PERILLA sobrevive entera, abajo: `ALEPH_SESION_POR_CHAT=0` apaga los tres
        # peldaños que Aleph infiere y deja sólo el que el stack eligió.
        #
        # LO MEDIDO POR CADA UNA, que es lo que se está cobrando acá:
        #     Legal 66 % · Ciencia 42 % · Oficina 62 % de prompt cacheado   (la escalera)
        #     Diseño −65 % y −71 % de tokens por cruce, 0 % → 67 % y 73 %
        #       de cruces incrementales, las tres entregas renderizadas    (la perilla ON)
        #
        # LA SUPERFICIE ES `_ws`, NO LA CABECERA CRUDA. `56e750f8` lo dejó escrito:
        # «hasta que el recupero llegue a main, la superficie es la cabecera cruda».
        # `a74dd218` acaba de llegar en este mismo merge, así que ya no hace falta —
        # y con Diseño, que NO manda `X-Aleph-Workspace`, la diferencia es real.
        # ══════════════════════════════════════════════════════════════════════════════
        _por_chat = (os.environ.get("ALEPH_SESION_POR_CHAT") or "1").strip() != "0"
        # ══ [obra 1 · el caché] LA CLAVE DE CONVERSACIÓN, CON ESCALERA ═══════════════
        # ANTES: sólo `X-Aleph-Sesion`. Y de los seis stacks **la manda uno solo**
        # (Finanzas, `vibetrading/.../llm.py:1163`), porque es el único con el plugin que
        # sabe fabricarla por turno. Para los otros cinco la clave salía `None`, y de ahí
        # en cascada: sin clave no hay sesión → `claude_cli.py:194` arma el argv con
        # `--no-session-persistence` → no queda prefijo en disco → **`cache_read = 0`**.
        # Medido: 0 de 28 llamadas leyeron caché, y los 28 cruces salieron `·completa`.
        #
        # ⚠️ EL RESTO DEL CABLE YA ESTABA. Lo verifiqué hop por hop antes de escribir una
        # línea: `sobre_turno.campos_del_cuerpo()` mete `{"sesion": …}` en el payload,
        # `assembler.py:792` la llama, y `server.py:419` lee `req["sesion"]`. No faltaba
        # el mecanismo: faltaba **la entrada**. Nadie le daba una clave a los cinco sin
        # plugin.
        #
        # LA ESCALERA, de más específico a menos, y cada peldaño DICE qué granularidad da:
        #   1. `X-Aleph-Sesion` — la eligió el stack. Es la conversación de verdad.
        #   2. `X-Aleph-Chat`   — el hilo de la casa. Medido estable en Ciencia y Oficina
        #      a lo largo de los 3 turnos, así que da conversación completa.
        #   3. `X-Aleph-Space`  — la visita. Legal no manda ni sesión ni chat (su config
        #      sólo lleva `X-Aleph-Workspace`), y su espacio es estable DENTRO de un turno
        #      y cambia entre turnos: da reuso intra-turno, no entre turnos. Es parcial y
        #      se declara parcial; el arreglo entero para Legal es agregarle
        #      `X-Aleph-Chat` a `pack._cabeceras_aleph`, que es otra obra.
        #
        # EL USUARIO ENTRA EN LA CLAVE, y no es cosmético: una sesión reusada por la clave
        # equivocada le contesta a alguien con el contexto de otro. Ver la fuga de cuentas
        # de `collect_atoms`. Con el dueño adentro, dos cuentas no pueden colisionar.
        def _visita_de(space: str):
            """El id de VISITA que hay adentro del id de espacio, o `None`.

            `pack._espacio_de_visita` fabrica `space-ws-<sid>-<hex>` y el plugin de
            Ciencia le agrega `-<n>` por turno. El `<sid>` es lo ESTABLE de la visita —
            lo mintea Aleph, no el stack— y es lo único que sobrevive de un turno al
            siguiente cuando no hay ni `X-Aleph-Sesion` ni `X-Aleph-Chat`.
            Si el formato no calza, devuelve `None` y la escalera cae al espacio entero:
            un cambio de formato degrada a reuso intra-turno, no rompe nada.
            """
            # ⚠️ el sello de tiempo NO es hexadecimal: `_espacio_de_visita` usa
            # `%x` pero el plugin de Ciencia fabrica el suyo en base36 (`mt63bqeu`).
            # Con `[0-9a-f]` esto no matcheaba NUNCA en Ciencia — medido, `visita=None`
            # en los seis cruces— y el peldaño quedaba muerto sin una señal.
            m = _re.match(r"^space-ws-(.+?)-[0-9a-z]{6,}(?:-\d+)?$", (space or "").strip())
            return m.group(1) if m else None

        def _hilo_de(msgs):
            """La huella del PRIMER mensaje de usuario: identifica la conversación.

            Hace falta porque la visita sola NO alcanza: dos chats distintos abiertos en
            la misma visita compartirían clave, y con render incremental eso le mandaría
            los mensajes nuevos de uno a la sesión del otro — contestarle a alguien con
            el contexto de otra conversación. El primer mensaje del usuario no cambia
            mientras la conversación viva, y es distinto entre conversaciones.
            """
            # ⚠️ LA MISMA NORMALIZACIÓN QUE USA EL PREFIJO, Y NO ES CASUALIDAD. El
            # mensaje humano llega en bloques (`[{"type":"text",…}]`) el turno que se
            # escribe y en cadena pelada cuando el historial se replica; hasheando la
            # forma cruda, el `#hilo` cambiaba de un turno al otro y la sesión se abría
            # de nuevo cada vez. Se importa `sesiones` en vez de copiar la función: las
            # DOS puertas de la sesión —esta clave y `sesiones.prefijo_vivo`— tienen que
            # normalizar IDÉNTICO o una deja pasar lo que la otra rechaza, que es
            # exactamente el estado del que salimos. Sin `try`: si esto no se puede
            # importar, la sesión no funciona, y prefiero un 500 con traceback antes que
            # volver en silencio al hash inestable.
            from cli_brain.sesiones import texto_de_contenido as _texto_contenido
            for m in (msgs or []):
                m = m if isinstance(m, dict) else (m.model_dump()
                                                   if hasattr(m, "model_dump") else {})
                if (m.get("role") or "") == "user":
                    # ⚠️ SÓLO LA PARTE HUMANA, Y EL BARRIDO YA NO VIVE ACÁ. El harness le
                    # pega andamiaje al mensaje —`<system-reminder>`, `<env>`— y lo REGENERA
                    # (o lo descarta al replicar el historial). Eso lo barre ahora
                    # `texto_de_contenido`, junto con la normalización de forma, porque las
                    # DOS puertas de la sesión tienen que ver lo mismo: cuando el barrido
                    # estaba sólo acá, la CLAVE quedaba estable y `prefijo_vivo` seguía
                    # rechazando —medido— y el turno salía `·completa` igual.
                    c = _texto_contenido(m.get("content")).strip()
                    if not c:
                        continue
                    return _hashlib.sha1(c.encode("utf-8", "replace")).hexdigest()[:12]
            return None

        def _clave_de_conversacion():
            _visita = _visita_de(x_aleph_space or "")
            _hilo = _hilo_de(body.messages)
            # ⚠️ EL `#hilo` VA EN TODOS LOS PELDAÑOS QUE ALEPH INFIERE, no sólo en la
            # visita. Lo cazó la medición del 2026-08-23 en Legal: su agente `router`
            # (el del prompt `<candidates>`) y su agente de Q&A **comparten el mismo
            # `X-Aleph-Chat`**, así que con la clave por chat pelado caían en la MISMA
            # sesión. Cada llamada del router llegaba con un historial que no era el de
            # la conversación, `_armar_prompt` veía que no calzaba y **renovaba el id** —
            # o sea que el agente principal perdía su sesión una vez por turno y el
            # reuso entre turnos no ocurría nunca. Con la huella del primer mensaje de
            # usuario al lado, los dos agentes quedan separados y cada uno conserva la
            # suya.
            #
            # LA EXCEPCIÓN, y es una regla: al peldaño `sesion` NO se le agrega nada.
            # Ahí el stack DIJO cuál es la conversación, y donde el stack dice, se le
            # obedece; el `#hilo` sólo desambigua donde ALEPH está adivinando.
            _suf = ("#%s" % _hilo) if _hilo else ""
            # LA PERILLA DE DISEÑO, ADENTRO DE LA ESCALERA. `ALEPH_SESION_POR_CHAT=0`
            # deja SÓLO el peldaño que el stack eligió — o sea el comportamiento exacto
            # de main. Va acá y no envolviendo la llamada porque lo que la perilla apaga
            # es «que la casa adivine la conversación», y adivinar es precisamente lo que
            # hacen los tres peldaños de abajo; el primero no adivina nada.
            _inf = _por_chat
            for peldano, v in (("sesion", (x_aleph_sesion or "").strip()),
                               ("chat", (("%s%s" % (x_aleph_chat.strip(), _suf))
                                         if (_inf and (x_aleph_chat or "").strip()) else "")),
                               ("visita", ("%s%s" % (_visita, _suf))
                                          if (_inf and _visita and _hilo) else ""),
                               ("space", (("%s%s" % (x_aleph_space.strip(), _suf))
                                          if (_inf and (x_aleph_space or "").strip()) else ""))):
                if v:
                    return "%s:%s:%s:%s" % (_ws or "ws",
                                            (x_aleph_user or "-"), peldano, v)
            return None
        _sesion_espaciada = _clave_de_conversacion()
        # [convergencia · superficie 1] EL PEDIDO HUMANO, EN EL HILO DE LA CASA. Va ACÁ —
        # antes de las dos ramas y antes de correr— porque las dos ramas lo necesitan y
        # porque un turno que se rompe a mitad no puede llevarse lo que el usuario dijo.
        # Devuelve `None` para los tres stacks que tienen plugin: a ésos los anota `close`,
        # que ve el turno de verdad. Ver `_anotar_pedido_del_borde`.
        _obs.marca("ws.pre_hilo")
        _turno_hilo = _anotar_pedido_del_borde(
            _ws, x_aleph_chat, x_aleph_space, body.messages,
            authorization, tools=body.tools)
        _obs.marca("ws.post_hilo")
        # [Finanzas · los artefactos] LO QUE EL PASO ANTERIOR PRODUJO, CRUZADO ACÁ.
        # Va junto al hilo y por la misma razón: el harness manda el historial COMPLETO en
        # cada paso, así que los `role:"tool"` que llegan con ESTE pedido son el resultado
        # del paso anterior — y para un stack sin plugin, el borde es el único lugar de la
        # casa por donde esos resultados pasan. Devuelve sin hacer nada para los tres que
        # SÍ tienen plugin, y para todo workspace sin filas declaradas.
        _cosechar_artefactos_del_borde(
            _ws, x_aleph_chat, x_aleph_space, (x_aleph_user or None),
            body.messages, authorization)
        _obs.marca("ws.post_cosecha")
        # ══ [B0-3 · fase D] EL STREAMING DE VERDAD, DETRÁS DE BANDERA ═══════════════
        # Con `emulado` (el DEFAULT) el camino es exactamente el de siempre: se espera la
        # respuesta entera y recién ahí se fabrican los chunks. Medido 3 veces, ese camino
        # entrega el primer chunk EN EL MISMO INSTANTE que el último —14,61/14,61 ·
        # 7,31/7,31 · 7,52/7,52—, o sea que el workspace se queda mudo hasta el final.
        #
        # Con `real` se retransmite conforme llega. La bandera es POR WORKSPACE para poder
        # encender uno y mirarlo antes de mover el resto.
        import asyncio as _asyncio

        from app.phase1 import model_route_flags as _flags
        # ⚠️ LA SUPERFICIE ES `_ws` (identidad de Diseño) Y EL PREFLIGHT VA IZADO
        # (la Sala). Las dos cosas, no una: la rama de la Sala escribió
        # `x_aleph_workspace` sólo porque `_ws` no existía en main, y ya existe.
        if body.stream and _flags.modo_stream(_ws) is _flags.ModoStream.REAL:
            # El preflight tiene que ocurrir mientras el endpoint todavía puede devolver
            # un error HTTP. Dentro del generador, Starlette ya entregó 200 y el
            # proveedor real queda oculto detrás del stream emulado; además el último
            # evento de usage (incluidos los tokens de cache) no llega al harness.
            # Se calcula una sola vez y el generador sólo consume ese paso preparado.
            _obs.marca("ws.pre_preflight", modo="real")
            (recipe, messages, tools, byok_resolver, on_event, _dueno,
             wb) = _preflight_paso(equiv, authorization)
            _obs.marca("ws.post_preflight", modo="real")
            _id = "chatcmpl-" + _uuid.uuid4().hex[:24]
            _cr = int(_time.time())

            # EL MODELO HONESTO, EN CUANTO EL PROVEEDOR LO DICE. Arranca en lo que el
            # pedido traía —que para los seis stacks es NADA: ninguno manda `X-Aleph-Model`
            # y el `model` del body se ignora a propósito, así que medido daba `""` en
            # TODOS los chunks— y lo pisa el primer evento `model_final` del stream. Los
            # chunks anteriores a ese evento salen como salían; del evento en adelante,
            # y en el `finish` y el `usage`, va el que corrió de verdad.
            _modelo_vivo = [x_aleph_model or equiv.model or ""]

            def _chunk_real(delta: dict, finish=None, extra=None) -> str:
                cuerpo = {"id": _id, "object": "chat.completion.chunk", "created": _cr,
                          "model": _modelo_vivo[0],
                          "choices": ([] if extra else
                                      [{"index": 0, "delta": delta, "finish_reason": finish}])}
                if extra:
                    cuerpo["aleph"] = extra
                return "data: " + _json.dumps(cuerpo) + "\n\n"

            async def _generar():
                from starlette.concurrency import iterate_in_threadpool

                from app.phase1 import executor as _ex
                _obras = _ex._turnos_obra

                paso = None
                _fallo = None      # lo que rompió el turno, si rompió: cierra el sobre
                _dicho: list = []  # el texto del turno, para el hilo de la casa
                _hubo_texto = False  # sólo para la marca del PRIMER token
                _idx_tools: dict = {}  # id de tool_call → índice estable en el stream

                # ── EL `turno_id` VIAJA EN EL PRIMER CHUNK ────────────────────────────
                # Sin esto, un workspace NO PUEDE parar su turno: no tiene qué mandarle a
                # `POST /v1/turnos/detener`. Y no es hipotético — MEDIDO en Oficina el
                # 2026-08-13, con el botón «Stop» apretado en dos momentos distintos de
                # dos turnos:
                #
                #     corrida 1 · CLI vivió 45,4 s      corrida 2 · CLI vivió 45,1 s
                #
                # La misma vida las dos veces, y 45 s es exactamente el watchdog de
                # inactividad del `:8926`. Si el botón lo matara, la vida habría variado
                # con el momento del click. **El botón no corta**: su abort va al motor
                # del stack (`POST /opencode/session/{id}/abort`) y nunca llega acá, así
                # que la cadena que sí funciona cuando el cliente se va —la de la fuga de
                # cuota— nunca se dispara. La UI pinta «Aborted» mientras el CLI sigue
                # quemando la cuota del usuario.
                #
                # Se emite por el MISMO canal que ya usa la Sala (`stream_chat` cede
                # `("turno", _tid)`), en la extensión `aleph` del primer chunk: un cliente
                # que no lo mire sigue viendo un stream OpenAI válido, byte a byte.
                #
                # ⚠️ ESTO ES LA MITAD DEL PUENTE. La otra mitad es que cada stack lo
                # guarde y lo mande al abortar. Sin esa mitad el botón sigue sin cortar —
                # lo único que cambia es que ahora TIENE con qué.
                _handle = _obras.abrir("sala-" + _id)
                yield _chunk_real({}, extra={"turno_id": _handle})
                yield _chunk_real({"role": "assistant", "content": ""})

                # ── EL TURNO SE REGISTRA PARA PODER MATARLO DESDE AFUERA ───────────────
                # `iterate_in_threadpool` corre el generador sync en un HILO, y ese hilo se
                # queda bloqueado en el `read()` del socket del proveedor. Cuando el cliente
                # cierra la Sala, Starlette cancela esta corrutina —MEDIDO, la cancelación
                # llega en el acto— pero el hilo no se entera de nada: no hay forma de
                # interrumpir un `read()` bloqueado desde otro hilo, y cerrar el generador
                # tampoco (`gen.close()` sobre un generador en ejecución tira
                # `ValueError: generator already executing`; medido acá el 2026-08-13).
                #
                # Lo único que despierta a ese hilo es cerrarle el socket por abajo, y eso
                # ya existe y está probado: `turnos_obra` hace `shutdown(SHUT_RDWR)` antes
                # del `close()`, justamente porque `close()` solo NO despierta al lector.
                # Es el mismo mecanismo del botón «parar turno» — parar porque te fuiste y
                # parar porque apretaste son el mismo acto para el proveedor, que en los dos
                # casos sigue generando y cobrando si nadie le corta.
                #
                # SIN ESTO: 25,1 segundos de CLI generando después del corte, medidos.
                _fuente = wb.complete_stream(
                        recipe, messages, tools,
                        byok_resolver=byok_resolver, on_event=on_event,
                        user_id=_dueno, workspace=(equiv.workspace or "")[:40],
                        turn=int(equiv.turn or 1), lang=equiv.lang,
                        max_tokens=equiv.max_tokens, temperature=equiv.temperature,
                        tool_choice=equiv.tool_choice, handle=_handle)
                # ── LA DESCONEXIÓN SE VIGILA EN PARALELO, NO ENTRE ITEMS ──────────────
                # Esperar el `CancelledError` de Starlette NO alcanza, y está medido:
                # `iterate_in_threadpool` corre el generador sync en un hilo NO cancelable,
                # así que la cancelación no se entrega hasta que el `next()` en curso
                # vuelve — o sea cuando el CLI ya terminó, que es justo lo que queríamos
                # evitar. Con el CLI callado 25 s, el aviso llegaba 25 s tarde.
                #
                # Por eso hay un reloj propio, que corre CONTRA el próximo item. Pregunta
                # por la referencia que el guardián más externo de `app/main.py` dejó en
                # `request.state`: `request.is_disconnected` acá adentro está envuelto por
                # los BaseHTTPMiddleware y contesta False para siempre (Starlette #2094).
                # El respaldo es para montar este router SIN la app —un FastAPI pelado en
                # un test no tiene guardián, y ahí el `request` directo sí funciona.
                _chequeo = getattr(request.state, "is_disconnected", None) \
                    or request.is_disconnected
                _it = iterate_in_threadpool(_fuente).__aiter__()

                async def _se_fue():
                    while not await _chequeo():
                        await _asyncio.sleep(0.5)
                    return True

                _reloj = _asyncio.ensure_future(_se_fue())
                try:
                    while True:
                        _prox = _asyncio.ensure_future(_it.__anext__())
                        _listos, _ = await _asyncio.wait(
                            {_prox, _reloj}, return_when=_asyncio.FIRST_COMPLETED)
                        if _reloj in _listos:
                            # Gana el reloj: se corta el socket del proveedor. NO se espera
                            # al hilo —sigue bloqueado en su `read()`— pero el `shutdown`
                            # lo despierta y su `finally` cierra todo. Eso es lo que hace
                            # que el `:8926` vea el pipe roto y pare el CLI.
                            _obras.detener(_handle)
                            _prox.cancel()
                            return
                        try:
                            clase, carga = _prox.result()
                        except StopAsyncIteration:
                            break
                        if clase == "texto":
                            # LA MARCA QUE DA SENTIDO A TODA LA FAMILIA `ws.*`: el instante
                            # del PRIMER token que sale hacia el stack. El total de un turno
                            # no distingue «tardó 8 s» de «tardó 8 s y no se vio nada hasta
                            # el final»; el delta contra `ws.entra` sí. Una sola vez por
                            # turno: marcar cada trozo llenaría el log y mediría lo mismo.
                            if not _hubo_texto:
                                _hubo_texto = True
                                _obs.marca("ws.1er_texto", ws=_ws or "")
                            # [convergencia · superficie 1] El hilo necesita el texto
                            # ENTERO, y acá el texto son trozos. Se acumula mientras se
                            # retransmite: la anotación no puede costarle un byte de
                            # latencia al que está leyendo.
                            _dicho.append(carga)
                            yield _chunk_real({"content": carga})
                        elif clase == "tool_delta":
                            # ── EL `index` ES OBLIGATORIO, Y NO LO MANDÁBAMOS ──────
                            # ESTO MATABA EL TURNO ENTERO, y con un error que el usuario
                            # veía en crudo en la pantalla. Capturado del chat del dueño:
                            #
                            #   AI_TypeValidationError: Type validation failed:
                            #   {"model":"claude-opus-5","choices":[{"delta":{"tool_calls":
                            #   [{"id":"call_257d…","type":"function","function":
                            #   {"name":"write","arguments":"{…}"}}]}}]}
                            #
                            # El `model: claude-opus-5` dice que ese chunk salió de acá. Y
                            # el esquema con el que el stack valida CADA chunk del stream
                            # (`@ai-sdk/openai-compatible@1.0.30`) es:
                            #
                            #   tool_calls: z.array(z.object({
                            #     index: z.number(),            ← REQUERIDO
                            #     id: z.string().nullish(),
                            #     function: z.object({ name: …nullish, arguments: …nullish })
                            #   })).nullish()
                            #
                            # `index` es el ÚNICO campo obligatorio de los cuatro, y es
                            # justo el que faltaba: el turno moría con la respuesta a
                            # medias y la pantalla mostraba el JSON del error.
                            #
                            # POR QUÉ FALTABA. `assembler.py` lo agrega a mano en la vía
                            # NO-stream —su comentario lo dice: «el sobre no-stream no lo
                            # trae»— y la vía de stream reenvía el `tool_call` tal cual
                            # llega. Cuando el de arriba no lo trae, acá salía sin él.
                            #
                            # SE COMPLETA, NO SE INVENTA: si el trozo trae su `index` se
                            # respeta (es el que dice a cuál de varias tools pertenece); si
                            # no lo trae, se le asigna uno estable POR `id` de tool_call, de
                            # modo que los pedazos de una misma llamada caigan siempre en el
                            # mismo índice y dos llamadas distintas nunca se pisen.
                            if isinstance(carga, dict) and carga.get("index") is None:
                                _tid_tc = carga.get("id") or ""
                                if _tid_tc not in _idx_tools:
                                    _idx_tools[_tid_tc] = len(_idx_tools)
                                carga = {**carga, "index": _idx_tools[_tid_tc]}
                            yield _chunk_real({"tool_calls": [carga]})
                        elif clase == "razonamiento":
                            # ── EL RAZONAMIENTO TAMBIÉN CRUZA ────────────────────────
                            # ESTE ERA EL AGUJERO QUE SE VEÍA EN PANTALLA. `complete_stream`
                            # cede `("razonamiento", …)` desde siempre, y esta rama NO lo
                            # contemplaba: caía por el `elif` y se tiraba. Mientras el modelo
                            # piensa —que es literalmente lo que el stack rotula «Recopilando
                            # pensamientos»— por el cable NO VIAJABA NADA.
                            #
                            # De ahí las dos cosas que reportó el dueño y que parecían
                            # contradecirse: «se demora y no carga» y «streamea a veces». Es
                            # lo mismo visto dos veces. Cuando el modelo piensa poco, el texto
                            # arranca enseguida y parece que streamea; cuando piensa 12-20 s
                            # —medido en su pantalla: «Recopilando pensamientos · 12s» y
                            # después «· 20s», con el área de respuesta VACÍA— la pantalla se
                            # queda muerta y parece colgada. El transporte estaba bien: lo
                            # que faltaba era mandar lo único que existe durante esa espera.
                            #
                            # EL CAMPO NO SE ADIVINA. Leído del SDK que el stack usa de
                            # verdad (`@ai-sdk/openai-compatible@1.0.30`, `index.mjs:559`):
                            #     const reasoningContent = delta.reasoning_content ?? delta.reasoning
                            # Se manda `reasoning_content`, que es el que mira primero. Un
                            # cliente que no lo conozca ve un `delta` sin `content` y sigue
                            # andando: no rompe a nadie que no lo espere.
                            yield _chunk_real({"reasoning_content": carga})
                        elif clase == "model_final":
                            # No se emite un chunk por esto: no hay nada que pintar. Sólo
                            # cambia con qué se sella lo que venga después.
                            if carga:
                                _modelo_vivo[0] = carga
                        elif clase == "paso":
                            paso = carga
                except (_asyncio.CancelledError, GeneratorExit):
                    # El cliente se fue. No hay a quién contarle nada: lo único que
                    # corresponde es cortar y dejar que la cancelación siga su camino.
                    # `detener` es idempotente.
                    _obras.detener(_handle)
                    raise
                except BaseException as _exc:      # noqa: BLE001 — se cierra el sobre
                    # ⚠️ EL SOBRE SE CIERRA CON CAUSA, SIEMPRE. Acá se hacía `raise`, y con
                    # las cabeceras YA enviadas eso no es un error: es una conexión que se
                    # corta. MEDIDO en Ciencia (binario `363d7ceb…`): el cliente recibía 2
                    # chunks, sin `finish_reason`, sin `usage` y sin `[DONE]`; el stack lo
                    # leía como «No output generated» y el turno volvía VACÍO; y la
                    # telemetría lo anotaba **`status=200`**. Tres de cada cuatro turnos.
                    #
                    # Es exactamente el «FALLO VISIBLE, JAMÁS MUDO» del contrato del repo,
                    # en la única capa que puede cumplirlo: quien abrió el sobre es el
                    # único que puede cerrarlo. Aguas abajo ya no hay HTTP que devolver.
                    _obras.detener(_handle)
                    _fallo = _exc
                finally:
                    _reloj.cancel()
                    # El registro se limpia SIEMPRE: uno que crece es una fuga de memoria
                    # con forma de tabla, y un id reusado pararía el turno de otro.
                    _obras.cerrar(_handle)
                if _fallo is not None:
                    # La causa TIPADA si el traductor la sabe leer, y el string pelado si
                    # no: lo que no puede pasar es que no viaje nada.
                    _causa = None
                    try:
                        from errores_modelo import causa_de_excepcion as _cde
                        _c = _cde(_fallo)
                        _causa = _c.como_dict() if _c is not None else None
                    except Exception:              # noqa: BLE001 — el bundle recortado
                        _causa = None
                    # OpenAI-compatible clients inspect top-level `error`. Keeping it
                    # only under `aleph.error` made a failed Codex turn look empty.
                    # `error` is not a standard finish_reason, either.
                    yield "data: " + _json.dumps({"error": {
                        "message": str(_fallo) or _fallo.__class__.__name__,
                        "type": (_causa or {}).get("causa") or "brain_error",
                        "causa": _causa,
                    }}) + "\n\n"
                    # Y el `[DONE]`, que es lo que le dice al cliente que el stream terminó
                    # a propósito y no que se le cayó la conexión.
                    yield "data: [DONE]\n\n"
                    return
                # [obra 3] EL ANUNCIO, EN EL TEXTO. Acá va AL FINAL y no al principio, y no
                # es preferencia: en la rama que streamea de verdad el `degraded` recién
                # llega con el `paso`, o sea después del último token. Anunciarlo antes
                # exigiría que el cascade avisara al cambiar de tier, que es otra obra. Al
                # final se ve; callado no.
                _avi = _aviso_degradado((paso or {}).get("degraded"))
                if _avi:
                    _dicho.append("\n\n" + _avi.strip())
                    yield _chunk_real({"content": "\n\n" + _avi.strip()})
                # [convergencia · superficie 1] LA RESPUESTA, TAMBIÉN POR ACÁ. Esta rama
                # está dormida hoy (`ModoStream` default = `emulado`), y por eso mismo va
                # cableada: una bandera que se prende y apaga superficies en silencio es
                # justo cómo el streaming real se quedó dormido un mes sin que nadie lo
                # notara. Un paso con sólo `tool_calls` deja `_dicho` vacío y no escribe.
                _anotar_respuesta_del_borde(x_aleph_chat, _turno_hilo,
                                            "".join(_dicho), x_aleph_space)
                yield _chunk_real({}, (paso or {}).get("finish_reason") or "stop")
                _ex = {k: (paso or {}).get(k) for k in ("repliegue", "degraded")
                       if (paso or {}).get(k)}
                if _ex:
                    yield _chunk_real({}, None, extra=_ex)
                if isinstance((paso or {}).get("usage"), dict):
                    yield "data: " + _json.dumps({
                        "id": _id, "object": "chat.completion.chunk", "created": _cr,
                        "model": paso.get("model") or "", "choices": [],
                        "usage": paso["usage"]}) + "\n\n"
                _obs.marca("ws.fin", ws=_ws or "", modo="real", hubo_texto=_hubo_texto)
                yield "data: [DONE]\n\n"

            async def _generar_con_sobre():
                """El sobre puesto DURANTE todo el stream, y sacado al terminarlo.

                Envolver en vez de indentar `_generar` no es cosmético: el handler ya
                volvió cuando el generador corre, así que un `poner/sacar` en el cuerpo del
                endpoint estaría sacado antes del primer chunk. Acá el `set` ocurre en la
                MISMA task que consume el generador, y `iterate_in_threadpool` copia ese
                contexto al hilo donde vive el `urllib` que sale al `:8926`. El `finally`
                corre también si el cliente se va a mitad de stream."""
                _tok = _sobre_turno.poner(x_aleph_turno_id, x_aleph_deadline_epoch, _sesion_espaciada)
                try:
                    async for _trozo in _generar():
                        yield _trozo
                finally:
                    _sobre_turno.sacar(_tok)

            return StreamingResponse(_generar_con_sobre(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache",
                                              "X-Accel-Buffering": "no"})

        _tok_sobre = _sobre_turno.poner(x_aleph_turno_id, x_aleph_deadline_epoch, _sesion_espaciada)
        # ⚠️ ESTA MARCA Y LA SIGUIENTE ENCIERRAN AL ACUMULADOR. `workspace_brain_complete`
        # devuelve el paso ENTERO, así que con `emulado` el endpoint no puede contestar
        # —ni las cabeceras— hasta que el turno terminó. Medido contra la instalada
        # `8774cd82` con los cinco stacks: `t_cabeceras = t_1er_texto = t_fin`, Δ 0,00 s.
        _obs.marca("ws.al_cerebro", modo="emulado")
        try:
            out = workspace_brain_complete(equiv, authorization)
        except HTTPException as exc:
            # FALLO VISIBLE, en el sobre que el harness ajeno sabe abrir. El detalle
            # tipado de la casa (con su `causa`) viaja ADENTRO: traducir el sobre no
            # puede costar la causa, que es lo único que hace accionable el error.
            det = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
            return _error_openai(exc.status_code, det)
        finally:
            # El sobre no puede sobrevivir al pedido: el hilo del threadpool se reusa, y un
            # sobre viejo le pondría el id y el deadline de un turno ajeno al siguiente.
            _sobre_turno.sacar(_tok_sobre)
            _obs.marca("ws.del_cerebro", modo="emulado")

        modelo = out.get("model") or ""
        mensaje = _openai_message(out)
        fin = _openai_finish(out)
        # [convergencia · superficie 1] LA RESPUESTA, EN EL MISMO HILO. Este es el camino
        # de los tres stacks sin plugin hoy: `emulado` es el default de `ModoStream`, y
        # `emulado` pasa por acá igual que el no-stream. Un paso con `tool_calls` trae
        # `content` vacío y no escribe — el que sí trae texto actualiza en sitio sobre el
        # mismo `client_turn_id`, así que gana el último, que es el final del turno.
        _anotar_respuesta_del_borde(x_aleph_chat, _turno_hilo,
                                    mensaje.get("content") or "", x_aleph_space)
        uso = out.get("usage") if isinstance(out.get("usage"), dict) else None
        ident = "chatcmpl-" + _uuid.uuid4().hex[:24]
        creado = int(_time.time())

        # [B0-2] LO QUE EL HARNESS TIENE QUE SABER PARA NO DECIDIR A CIEGAS.
        # `complete()` ya calculaba el repliegue y lo devolvía —su propio comentario dice
        # «para que el borde de dialecto lo pueda contar en su sobre»— pero este sobre lo
        # tiraba. El endpoint de la casa lo devuelve entero (`return out`); el dialecto no.
        #
        # Importa porque un repliegue NO conserva comportamiento: el modelo elige su jugada
        # en función del conjunto de tools VISIBLE en ese paso, así que quitar `redline`,
        # `compute`, `order` o `search` puede producir otra tool, o texto en vez de tool. Que
        # la tool demorada reaparezca en el paso siguiente no deshace la decisión de éste.
        #
        # Aleph no puede conservar el comportamiento —la alternativa al repliegue es que no
        # haya paso, porque el proveedor ya devolvió 413— pero sí puede dejar de ser el único
        # que lo sabe. Va bajo `aleph`, la misma extensión que ya usa el sobre de error, así
        # que un cliente OpenAI que no la mire sigue funcionando igual.
        _aleph_extra: dict = {}
        if out.get("repliegue"):
            _aleph_extra["repliegue"] = out["repliegue"]
        if out.get("degraded"):
            _aleph_extra["degraded"] = out["degraded"]
        # [timeout en segundos] SI ALEPH LE TOCÓ LOS ARGUMENTOS AL HARNESS, SE LO DICE.
        # `_normalizar_timeouts` corrige un `timeout` que el modelo mandó en segundos sobre
        # una tool que lo declara en ms (el caso medido en Oficina: 120 → 120.000). El stack
        # tiene derecho a saber que sus argumentos no son los que el modelo escribió: si la
        # corrección viajara muda, el harness no podría explicar por qué su comando duró más
        # de lo que pidió, y nosotros habríamos cambiado un fallo mudo por un acierto mudo.
        if out.get("timeouts_normalizados"):
            _aleph_extra["timeouts_normalizados"] = out["timeouts_normalizados"]
        # [default por proveedor] Y SI EL MODELO PEDIDO NO ATENDIÓ, EL TURNO LO DICE.
        # El `model` del sobre ya es el que corrió de verdad; esto agrega lo que ese campo
        # no puede: que hubo una sustitución y QUÉ se había pedido. Sin esto el reemplazo
        # sería invisible desde afuera y la mejora se volvería un parche silencioso.
        _sust = _sobre_modelo.sacar()
        if _sust:
            _aleph_extra["modelo_sustituido"] = _sust

        if not body.stream:
            respuesta: dict = {
                "id": ident, "object": "chat.completion", "created": creado,
                "model": modelo,
                "choices": [{"index": 0, "message": mensaje, "finish_reason": fin}],
            }
            if uso:
                respuesta["usage"] = uso
            if _aleph_extra:
                respuesta["aleph"] = _aleph_extra
            return respuesta

        # SSE. `workspace_brain.complete()` no streamea —devuelve el paso entero—, así que
        # el borde emite ese paso como un chunk y cierra. Es SSE válido y es lo que un
        # cliente OpenAI consume sin distinguirlo: lo que NO se hace es fingir que hubo
        # generación token a token cuando no la hubo.
        def _chunk(delta: dict, finish: Optional[str] = None) -> str:
            return "data: " + _json.dumps({
                "id": ident, "object": "chat.completion.chunk", "created": creado,
                "model": modelo,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }) + "\n\n"

        async def _stream():
            yield _chunk({"role": "assistant", "content": ""})
            if mensaje.get("content"):
                yield _chunk({"content": mensaje["content"]})
            for i, tc in enumerate(mensaje.get("tool_calls") or []):
                yield _chunk({"tool_calls": [{"index": i, **tc}]})
            yield _chunk({}, fin)
            if _aleph_extra:
                # [B0-2] Mismo aviso que en el sobre no-stream: un cliente que lea el
                # stream tiene el mismo derecho a saber que su conjunto de tools cambió.
                yield "data: " + _json.dumps({
                    "id": ident, "object": "chat.completion.chunk", "created": creado,
                    "model": modelo, "choices": [], "aleph": _aleph_extra,
                }) + "\n\n"
            if uso:
                yield "data: " + _json.dumps({
                    "id": ident, "object": "chat.completion.chunk", "created": creado,
                    "model": modelo, "choices": [], "usage": uso,
                }) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/workspaces/brain/openai/embeddings")
    def workspace_brain_openai_embeddings(
            body: WorkspaceBrainOpenAIEmbeddingsRequest,
            authorization: Optional[str] = Header(default=None),
            x_aleph_workspace: Optional[str] = Header(default=None),
            x_aleph_user: Optional[str] = Header(default=None)):
        """EMBEDDINGS del workspace, **en dialecto OpenAI** — la otra mitad del borde.

        Existe por lo mismo que el de chat: un stack heredado sabe pedir `/v1/embeddings` y
        no sabe pedir por la puerta de la casa. Sin esta ruta, un workspace con RAG queda
        muerto aunque el chat ande — medido en Educación, donde `llamaindex` (el pipeline
        local, el único que no pide paquete ni API key ajena) fallaba su preflight por un
        solo check, «Active embedding model», mientras esta ruta devolvía 404.

        **NO ES UN CAMINO NUEVO, y eso es lo único que lo hace admisible.** Traduce sobre el
        MISMO circuito con el que la casa indexa sus propios documentos —
        `rag_index.pick_embed_provider` · `resolve_embed_key` · `embed_texts`, los tres que
        ya usa `POST /v1/rag/docs`—, con el mismo broker de credenciales, el mismo
        aislamiento cross-user y el mismo dueño obligatorio derivado de la sesión que el
        borde de chat. Si mañana cambia el circuito, cambia para los dos: acá no hay copia.

        Consecuencia honesta de eso: los embeddings de la casa son **BYOK**. Si el dueño no
        tiene llave de embeddings, esto NO inventa un proveedor ni cae a uno local que nadie
        eligió — dice qué falta y por qué, con la misma copy que ya usa el indexador."""
        from app.phase1 import rag_index

        # El mismo gate que el borde de chat, sin condición: el dueño sale de la sesión.
        dueno = _dueno_obligatorio(x_aleph_user, authorization)

        crudo = body.input
        if isinstance(crudo, str):
            textos = [crudo]
        elif isinstance(crudo, list):
            textos = [t if isinstance(t, str) else str(t) for t in crudo]
        else:
            textos = []
        if not textos:
            raise HTTPException(status_code=422, detail={"error": {
                "message": "`input` tiene que ser un texto o una lista de textos.",
                "type": "invalid_request_error", "code": "input_vacio"}})

        formato = (body.encoding_format or "float").strip().lower()
        if formato not in ("float", "base64"):
            raise HTTPException(status_code=422, detail={"error": {
                "message": f"`encoding_format` no soportado: {formato}.",
                "type": "invalid_request_error", "code": "encoding_format_no_soportado"}})

        proveedor = rag_index.pick_embed_provider(dueno)
        if not proveedor:
            # Misma causa y misma copy que el indexador de la casa. FALLO VISIBLE: el stack
            # muestra este mensaje tal cual en su preflight de RAG.
            raise HTTPException(status_code=424, detail={"error": {
                "message": ("Para usar la búsqueda por significado conecta tu propia llave "
                            "de embeddings en Modelos."),
                "type": "no_embed_key", "code": "sin_llave_embeddings"}})
        llave = rag_index.resolve_embed_key(dueno, proveedor)
        if not llave:
            raise HTTPException(status_code=424, detail={"error": {
                "message": ("Para usar la búsqueda por significado conecta tu propia llave "
                            "de embeddings en Modelos."),
                "type": "no_embed_key", "code": "sin_llave_embeddings"}})

        defs = rag_index.embed_defaults_for(proveedor)
        # `dimensions` NO se ignora: un corpus indexado queda sellado al largo del vector, y
        # entregar otro largo del pedido rompe la recuperación mucho después, en silencio.
        if body.dimensions and int(body.dimensions) != int(defs.get("dim") or 0):
            raise HTTPException(status_code=422, detail={"error": {
                "message": (f"El motor de embeddings de Aleph entrega vectores de "
                            f"{defs.get('dim')} dimensiones y se pidieron {body.dimensions}."),
                "type": "invalid_request_error", "code": "dimensiones_no_disponibles"}})

        try:
            vectores = rag_index.embed_texts(
                textos, provider=proveedor, model=defs["model"],
                api_key=llave, base_url=defs["base_url"])
        except Exception as exc:
            # Mismo criterio que el sobre de error del borde de chat: el sobre es de OpenAI,
            # la causa de la casa viaja adentro y no se pierde al traducir.
            raise HTTPException(status_code=502, detail={"error": {
                "message": "El motor de embeddings de Aleph no pudo responder.",
                "type": "embed_error", "code": "embed_fallo",
                "aleph": {"detail": str(exc), "provider": proveedor}}}) from exc

        def _empaquetar(vec: list) -> Any:
            if formato != "base64":
                return vec
            import base64 as _b64
            import struct as _struct
            return _b64.b64encode(
                _struct.pack(f"<{len(vec)}f", *[float(x) for x in vec])).decode("ascii")

        return {
            "object": "list",
            # El modelo REAL con el que se embebió, no el que pidió el cliente.
            "model": defs["model"],
            "data": [{"object": "embedding", "index": i, "embedding": _empaquetar(v)}
                     for i, v in enumerate(vectores)],
            # `usage` se OMITE: la casa no mide tokens en este circuito, y un dict de ceros
            # contaría como llamada medida. Misma regla que el borde de chat.
        }

    @router.post("/workspaces/artifacts", status_code=201)
    def workspace_artifact(body: WorkspaceArtifactRequest,
                           authorization: Optional[str] = Header(default=None)):
        """EL PUENTE (3.5): el artefacto de un stack heredado se vuelve ciudadano.

        `kind` del stack → tipo canónico + forma, por `platform/artifacts/bridge.py`.
        Se adapta la FORMA, jamás el DATO: si entregar exigiera rellenar lo que falta,
        el puente RECHAZA con causa visible (422 tipado) en vez de guardar una obra
        vacía que el renderer pintaría como si tal cosa.

        La procedencia nace `produced_by="workspace"`, que topa `capture_quality` en
        `declared` (3.4): Aleph midió el modelo del turno, no la función del stack que
        escribió esto."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import artifact_store
        from artifacts import bridge
        _authorize_resource(artifact_store.get_owner(body.sid), authorization)

        class _Refs:  # el mismo constructor de procedencia que usan create/edit
            space_id, run_id = body.space_id, body.run_id
            chat_id, agent_id = body.chat_id, body.agent_id
            user_id = body.user_id
            method_id = method_run_id = None
            produced_by = "workspace"
            intent = body.intent
            workspace = body.workspace
            # El pasaporte del stack, inerte: `safe_ref` lo sanea y `_cap_workspace` no
            # lo mira. Queda para que la afirmación se pueda re-derivar, no para creerla.
            source_sha256 = body.source_sha256
            source_run_ref = body.source_run_ref
            source_commit = body.source_commit
        try:
            # El cuerpo de esto vive en `_cruzar_al_almacen`, compartido con la cosecha
            # del borde: dos escritores de artefactos de workspace que divergen es la
            # quinta lista de este repo, y ya sabemos cómo termina.
            return _cruzar_al_almacen(
                workspace=body.workspace, kind=body.kind, name=body.name,
                data=body.data, sid=body.sid, titulo=body.title, refs=_Refs)
        except bridge.BridgeError as exc:
            raise HTTPException(status_code=422, detail={
                "error": exc.code, "detail": exc.detail, "kind": exc.kind,
                "copy": bridge.CAUSES.get(exc.code)})

    @router.get("/workspaces")
    def workspaces_list(authorization: Optional[str] = Header(default=None)):
        """LOS WORKSPACES DE LA CASA y su elegibilidad. [Gate 4 · Fase 3 · 3.7 · ley 6]

        **La elegibilidad es por STACK, no por cinturón** (enmienda 2026-08-08): con la
        ley 0, un vertical vale entero sin un solo conector de Aleph, así que
        condicionar su existencia al cinturón sería esconder algo que funciona. El
        cinturón SUGIERE; el stack decide si el workspace existe.

        Se reportan dos hechos distintos y no se confunden:
          · `installed` — el stack viajó con esta instalación (su frontend construido
            está donde el binario lo sirve). Es lo que decide si el workspace APARECE.
          · `running`   — además su proceso está atendiendo AHORA. Es lo que decide qué
            se ve al entrar; que no corra no lo borra del menú, lo hace decir por qué.

        **`running` SE MIDE CONTRA LA SEÑAL DE SALUD DEL STACK, NO CONTRA `/`**
        [Gate 4 · F3-ciencia]. La primera versión pedía `/` y daba por vivo cualquier 200.
        Lo destapó una CAPTURA de la inmersión: la barra de Aleph decía «en vivo» dos
        centímetros arriba de un lienzo que decía «Local workspace unavailable» — la
        pantalla contradiciéndose a sí misma, con la vara entera en verde.

        Medido sobre el stack de Ciencia, y el resultado es peor que «la sonda es débil»:
        **está invertida en las dos direcciones.**

            corriendo de verdad  →  GET /  404   ·  GET /global/health  200
            sólo su dist servido →  GET /  200   ·  GET /global/health  404

        Un 200 en `/` prueba que algo atiende ese puerto, no que el workspace sirva: un
        server estático, o uno que todavía está arrancando y ya publica su UI, contestan
        200 con su API muerta. Y al revés, un stack que sirve su API pero todavía no sus
        assets contesta 404 en `/` estando perfectamente vivo. La barra afirmaba un hecho
        que nunca había medido.

        Cada fila declara su `health`; sin `health`, se cae a `/` y `running` vale lo que
        valía — un stack que no declare señal no queda peor que antes.
        Los no elegibles NO aparecen: ni grises, ni con candado (ley de producto 6).

        **HOY EL REGISTRO ESTÁ VACÍO, y ése es un estado sano** (cosecha de la Fase 3): la
        fase estrenó esta puerta con un stack heredado y la cosecha lo sacó entero. Cero
        elegibles ⇒ `{"workspaces": []}` ⇒ el menú **no dibuja la sección**. No hay
        pantalla rota, ni fila gris, ni error: no hay workspaces porque todavía no entró
        ninguno. El día que entre uno se agrega su fila a `_WORKSPACE_STACKS` y todo el
        resto de la puerta —elegibilidad, tipos, censo de fuentes— ya está cableado."""
        from artifacts import bridge
        from workspaces import sources as ws_sources
        from workspaces import pack as ws_pack
        import urllib.request as _url
        salida = []
        for ws, meta in _WORKSPACE_STACKS.items():
            # [Gate 4 · Fase 6 · §6.f] LO OCULTO NO SE OFRECE. Una fila con `oculto` es una
            # capacidad de LA SALA que usa la máquina del pack, no un workspace: no se
            # dibuja en el menú y —lo que de verdad importa— **no se ofrece como destino de
            # artefactos**, porque el aplicador se alimenta de esta misma lista
            # (`_filas_workspaces`). Es la regla «jamás a los verticales por default»
            # escrita en código en vez de confiada a la prosa. Entrar y salir siguen
            # andando por su id: `_meta_ws` lee el registro, no esta lista.
            if meta.get("oculto"):
                continue
            raiz = resource_root / meta["dist"]
            binario = ws_pack.binario_de(meta)
            # [Gate 4 · F4 · O1] INSTALADO = «el workspace viajó con esta instalación», y
            # desde que el pack existe hay DOS formas de que haya viajado: su `dist` (lo
            # que empaquetaba Fase 3) o su binario (que embebe esa misma UI adentro). Se
            # aceptan las dos a propósito: el día que el binario reemplace al `dist` —son
            # 29,1 MiB de la misma UI dos veces— esta línea no cambia y nada se cae.
            marcador = meta.get("install_marker")
            instalado = ((raiz / marcador).is_file() if marcador else (raiz / "index.html").exists()) \
                or (bool(binario) and not marcador)
            # AUTOARRANCA es otro hecho, y por eso es otro campo: si no hay binario, Aleph
            # no puede levantarlo y lo único honesto que puede decir la pantalla es que hay
            # que levantarlo por fuera. Confundirlo con `installed` sería prometer un botón
            # que no existe.
            # [Gate 4 · F4 · cierre] EL PACK ES DEL DUEÑO, ASÍ QUE LA PREGUNTA TAMBIÉN.
            # `pack.vivo()` busca por `(user_id, workspace)` —el pack corre por dueño— y sin
            # dueño no encontraba el proceso que ESA sesión acababa de levantar: el registro
            # decía `running: false` sobre su propio pack vivo. En dev no se veía porque la
            # vara entraba sin sesión; lo destapó la corrida contra la `.app` INSTALADA,
            # donde escribir en `/v1` exige sesión. Y de paso es lo correcto: una cuenta no
            # tiene por qué ver el pack de otra.
            from app.phase1 import repo as _repo_ws
            _dueno_ws = _repo_ws.session_owner(_bearer(authorization))
            vivo = ws_pack.vivo(ws, meta, user_id=_dueno_ws)
            declarada = os.environ.get(meta["url_env"])
            if vivo:
                base, corriendo = vivo["url"], vivo["atiende"]
            elif binario and not declarada:
                # ⚠️ SIN PACK VIVO **NO SE SONDEA UN PUERTO POR DEFECTO**, y esto lo destapó
                # la vara de esta obra: `url_default` era `127.0.0.1:4096`, y en la máquina
                # había un `bun` HUÉRFANO (PPID 1) de una sesión anterior escuchando justo
                # ahí. El registro decía `running: true` sobre un proceso que no era suyo
                # —de otro árbol, de otra sesión— y la pantalla habría metido en el lienzo
                # un stack que Aleph no gobierna.
                #
                # Es el mismo defecto que F3 arregló en el eje del PROTOCOLO (pedirle `/` a
                # un server de archivos estáticos decía «vivo»), ahora en el eje de la
                # IDENTIDAD: un 200 en un puerto no prueba que ese puerto sea el nuestro.
                # Cuando el workspace se autoarranca, el único que sabe si corre es su pack.
                base, corriendo = "", False
            else:
                # Camino declarado: un stack sin binario (todavía no empaquetado) o un
                # desarrollador que apunta a su propio server con `url_env`. Ahí sí se
                # sondea, porque alguien lo DECLARÓ — no se adivina un puerto.
                base = declarada or meta["url_default"]
                corriendo = False
                try:
                    with _url.urlopen(base + meta.get("health", "/"), timeout=1.5) as r:
                        corriendo = r.status == 200
                except Exception:                   # noqa: BLE001 — no correr no es un error
                    corriendo = False
            salida.append({
                "id": ws, "label": meta["label"], "icon": meta.get("icon", "▚"),
                "stack": {"name": meta["stack"], "installed": instalado,
                          "running": corriendo, "url": base,
                          "autoarranca": bool(binario)},
                "accepts": list(bridge.accepts(ws)),
                "kinds": list(bridge.kinds(ws)),
                # [ley 2.ter · jamás registro doble] Las fuentes que el stack YA TRAE.
                # El Cuarto y Conectores las muestran como «📦 fuente del stack — ya
                # incluida», jamás como un conector nuestro a armar, y el agente
                # recomienda con esto a la vista en vez de a ciegas.
                "sources": ws_sources.sources(ws),
            })
        return {"workspaces": [w for w in salida if w["stack"]["installed"]]}

    def _meta_ws(ws: str) -> dict:
        meta = _WORKSPACE_STACKS.get((ws or "").strip().lower())
        if not meta:
            raise HTTPException(status_code=404, detail={
                "error": "workspace_desconocido",
                "detail": f"«{ws}» no es un workspace de esta instalación"})
        return meta

    @router.post("/workspaces/{ws}/enter")
    def workspace_enter(ws: str, body: WorkspaceEnterRequest, request: Request,
                        authorization: Optional[str] = Header(default=None)):
        """ENTRAR AL WORKSPACE: el pack levanta su proceso. [Gate 4 · Fase 4 · O1]

        Es la mitad que faltaba del morph. Hasta hoy «entrar» era navegar a una pantalla y
        rezar para que alguien hubiera levantado el server a mano — y el modo de fallo no
        era teórico: el proceso de F3 quedó **con PPID 1** escuchando su puerto después de
        que su sesión murió.

        **Idempotente.** Entrar dos veces no levanta dos packs: el dueño comparte por
        huella. Y entrar dentro de la ventana de gracia de un `leave` la cancela y reusa el
        proceso caliente, que es lo que hace que un F5 no mate un kernel.

        **De dónde sale el `baseURL` del cerebro:** de ESTE pedido. El sidecar recibe su
        puerto del shell en cada arranque (`aleph-shell/src-tauri/src/lib.rs:48-62`), así
        que la única fuente que no miente es la URL por la que el navegador nos está
        hablando ahora mismo. Hornearlo —que es lo que había— dejaba al workspace
        apuntando al puerto de la sesión anterior."""
        meta = _meta_ws(ws)
        ws = ws.strip().lower()
        if body.user_id:
            _authorize(body.user_id, authorization)
        from workspaces import pack as ws_pack
        base = str(request.base_url).rstrip("/")
        token = (authorization or "").removeprefix("Bearer ").strip() or None
        # [F1-CONECTORES] EL RESOLVER DEL VAULT, CONSTRUIDO ACÁ Y PASADO ADENTRO. `platform/`
        # no puede importar `product/backend/` sin invertir las capas, así que el broker se
        # arma del lado que ya lo tiene y viaja como parámetro — el mismo patrón con el que
        # este archivo le pasa `byok_resolver` al assembler (`router.py:3762`, `:4347`).
        #
        # SIN `user_id` NO HAY RESOLVER, y eso es fail-closed a propósito: una credencial del
        # vault es de un dueño, y `make_user_resolver(None)` sólo resuelve refs
        # auto-contenidos (`credential_broker.py:229-231`). Un `enter` anónimo entra sin
        # credenciales y la salida lo dice; lo que no pasa es que reciba las de otro.
        _cred_resolver = None
        if body.user_id:
            from app.phase1 import credential_broker
            _cred_resolver = credential_broker.make_user_resolver(
                body.user_id, get_conn=get_conn)
        try:
            vivo = ws_pack.levantar(
                ws, meta, base_aleph=base, user_id=body.user_id, token=token,
                puppet_id=body.puppet_id, chat_id=body.chat_id, sid=body.sid,
                space_id=body.space_id, cred_resolver=_cred_resolver)
        except ws_pack.PackError as exc:
            # FALLO VISIBLE, con causa tipada y su copy — la pantalla tiene que poder decir
            # QUÉ pasó, no «no se pudo».
            raise HTTPException(status_code=503, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": _COPY_PACK.get(exc.causa, exc.causa)})
        salida = {"workspace": ws, "url": vivo["url"], "pids": vivo["pids"],
                  "entity_id": vivo["entity_id"]}
        # [LEY 12] EL AVISO SÓLO EXISTE SI HUBO ALGO QUE AVISAR. Un `enter` sano devuelve
        # exactamente lo que devolvía antes; el campo aparece únicamente cuando la casa
        # deshizo algo del usuario o encontró algo que no pudo deshacer. Es la diferencia
        # entre anunciar y hacer ruido.
        excl = vivo.get("exclusividad") or {}
        if excl.get("apagados") or excl.get("sin_apagar"):
            causa = ("cerebro_ajeno_presente" if excl.get("sin_apagar")
                     else "cerebro_ajeno_apagado")
            salida["aviso"] = {
                "error": causa,
                "detail": ("proveedores ajenos en el motor: "
                           + ", ".join(excl.get("intrusos") or [])),
                "copy": _COPY_EXCLUSIVIDAD[causa],
                "apagados": excl.get("apagados") or [],
                "sin_apagar": excl.get("sin_apagar") or [],
            }
        # LA OTRA FORMA DEL MISMO AVISO: el stack cuyo cerebro no es una LISTA sino una
        # TERNA. Mismo campo `aviso`, mismas dos causas y el MISMO copy ya probado en
        # Oficina — la pantalla no tiene que aprender un vocabulario nuevo porque adentro
        # cambie el mecanismo. El detalle sí dice qué se encontró, que es lo accionable.
        elif excl.get("desviada"):
            causa = ("cerebro_ajeno_apagado" if excl.get("reparada")
                     else "cerebro_ajeno_presente")
            _prev = excl.get("previa") or {}
            salida["aviso"] = {
                "error": causa,
                "detail": ("el stack apuntaba a %s / %s"
                           % (_prev.get("model_name") or "?",
                              _prev.get("base_url") or "?")),
                "copy": _COPY_EXCLUSIVIDAD[causa],
                "apagados": [_prev.get("model_name")] if excl.get("reparada") else [],
                "sin_apagar": [] if excl.get("reparada") else [_prev.get("model_name")],
            }
        # ── [F1-CONECTORES] LO QUE PASÓ CON LAS CREDENCIALES DEL USUARIO ────────────────
        # El DATO va en su propio campo, como `exclusividad`: quien quiera auditar el `enter`
        # lo lee entero (qué se escribió, qué se verificó, de dónde salió la tabla de
        # canónicas) sin que nada de eso tenga que caber en un copy.
        cred = vivo.get("credenciales") or {}
        if cred:
            salida["credenciales"] = cred
        # Y EL AVISO, EN EL SOBRE QUE YA EXISTE. La CAUSA la elige `pack.causa_de_credenciales`
        # —está allá para que la vara pueda llamarla— y acá se le pone el copy, que es donde
        # viven todos los copys de este archivo.
        #
        # ⚠️ NO PISA UN AVISO DE CEREBRO. `aviso` es un campo, no una lista, y el contrato de
        # LEY 12 ya lo usa: sobrescribirlo cambiaría el significado de una respuesta que la
        # pantalla ya sabe leer. Si los dos tienen algo que decir, gana el cerebro (que es el
        # que ya estaba) y lo de credenciales queda completo en `salida["credenciales"]`. La
        # deuda de un `enter` con DOS avisos queda anotada, no resuelta acá.
        if cred and "aviso" not in salida:
            _causa, _detalle = ws_pack.causa_de_credenciales(cred)
            if _causa:
                salida["aviso"] = {"error": _causa, "detail": _detalle,
                                   "copy": _COPY_CREDENCIALES[_causa]}
        return salida

    @router.get("/workspaces/oficina/aprobaciones")
    def oficina_aprobaciones(authorization: Optional[str] = Header(default=None)):
        owner = _dueno_obligatorio(None, authorization)
        from workspaces import pack as ws_pack
        try:
            return ws_pack.aprobaciones_oficina(_meta_ws("oficina"), user_id=owner)
        except ws_pack.PackError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/workspaces/oficina/aprobaciones/{solicitud}")
    def oficina_decidir_aprobacion(solicitud: str, permitir: bool = Query(...),
                                   authorization: Optional[str] = Header(default=None)):
        owner = _dueno_obligatorio(None, authorization)
        from workspaces import pack as ws_pack
        try:
            return ws_pack.aprobaciones_oficina(_meta_ws("oficina"), user_id=owner,
                                               solicitud=solicitud, permitir=permitir)
        except ws_pack.PackError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/workspaces/{ws}/leave")
    def workspace_leave(ws: str, body: WorkspaceLeaveRequest,
                        authorization: Optional[str] = Header(default=None)):
        """SALIR DEL WORKSPACE: se suelta el pack y se arma su gracia.

        No apaga en el instante, y el porqué está medido en el propio producto: adentro del
        lienzo puede haber un kernel de Python corriendo (`workspaces/ciencia.html:113-115`
        ya lo advierte para el `src` del iframe), y un F5 emite `pagehide` + `pageshow` en
        menos de un segundo. La ventana es corta y declarada (`ALEPH_PACK_GRACIA_S`); con
        0 el apagado es literal, que es como lo mide la vara."""
        meta = _meta_ws(ws)
        ws = ws.strip().lower()
        if body.user_id:
            _authorize(body.user_id, authorization)
        from workspaces import pack as ws_pack
        parte = ws_pack.salir(ws, user_id=body.user_id, gracia_s=body.gracia_s)
        return {"workspace": ws, **parte,
                "vivo": bool(ws_pack.vivo(ws, meta, user_id=body.user_id))}

    def _filas_workspaces(authorization: Optional[str] = None) -> list:
        """Las filas del registro, YA filtradas por instalado. Es lo que `workspaces_list`
        devuelve, y se comparte para que el aplicador y el menú no midan elegibilidad con
        dos varas distintas."""
        return list(workspaces_list(authorization).get("workspaces") or [])

    @router.get("/workspaces/destino")
    def workspace_destino(tipo: Optional[str] = Query(default=None),
                          user_id: Optional[str] = Query(default=None),
                          authorization: Optional[str] = Header(default=None)):
        """A DÓNDE VA ESTE TRABAJO. [Gate 4 · Fase 4 · O5 · obras 4.4 y 4.5 · ley 6]

        **El aplicador único de las tres señales**, que es lo que la vara de esta fase pide:
        stack disponible (filtra) · preferencia grabada (manda) · artefacto (reclama), con el
        cinturón ordenando y jamás filtrando.

        La decisión la toma `platform/workspaces/destino.py` con los hechos ya medidos. Este
        endpoint sólo los junta — y ése es el punto: una sola respuesta para el selector, la
        tarjeta y el agente, en vez de tres pantallas opinando por separado."""
        if user_id:
            _authorize(user_id, authorization)
        from workspaces import destino as ws_destino
        from workspaces import memoria as ws_memoria
        from workspaces import sources as ws_sources
        filas = _filas_workspaces(authorization)
        # LA SEÑAL DEL CINTURÓN. Hoy se deriva del censo 2.ter: un workspace se sugiere si
        # alguna de SUS fuentes es de las que Aleph también alcanza desde el cinturón
        # (`also_in_belt`). Es una señal de AFINIDAD del workspace, no del cinturón que este
        # usuario tiene equipado — refinarla a lo equipado es una obra propia, y hasta que
        # exista decirlo así evita prometer una personalización que no hay.
        sugeridos = [w["id"] for w in filas
                     if any(f.get("also_in_belt") for f in ws_sources.sources(w["id"]))]
        return ws_destino.decidir(
            disponibles=filas, tipo=(tipo or None),
            preferencias=ws_memoria.preferencias(user_id), sugerencias=sugeridos)

    @router.put("/workspaces/preferencia")
    def workspace_preferencia(body: WorkspacePreferenciaRequest,
                              authorization: Optional[str] = Header(default=None)):
        """«Para esto, siempre acá». [4.5] Un `workspace` vacío borra la preferencia."""
        _authorize(body.user_id, authorization)
        from workspaces import memoria as ws_memoria
        # [Gate 4 · Fase 6] GUARDAR UNA PREFERENCIA QUE NUNCA VA A CUMPLIRSE ES UN FALLO
        # MUDO. `preferir()` sólo valida la FORMA del string, así que hasta acá se podía
        # grabar «para los informes, siempre <lo que sea>» y el aplicador la descartaba
        # después en silencio —`destino.decidir` exige que la preferencia esté entre los
        # workspaces elegibles (`platform/workspaces/destino.py`)— devolviendo
        # `motivo: "artefacto"`, como si el usuario nunca la hubiera expresado.
        #
        # Con los modos de la Sala eso dejó de ser teórico: `sala_research` y
        # `sala_busqueda` son ids REALES del registro y ocultos a propósito, así que
        # pasaban la validación de forma y morían mudos. Se rechaza en el borde de
        # escritura (ley técnica 3: validar al escribir, no al leer), con causa y copy.
        destino_pedido = (body.workspace or "").strip().lower()
        if destino_pedido:
            meta_pedida = _WORKSPACE_STACKS.get(destino_pedido)
            if meta_pedida is None or meta_pedida.get("oculto"):
                raise HTTPException(status_code=422, detail={
                    "error": "workspace_no_elegible",
                    "detail": f"«{body.workspace}» no es un workspace al que se pueda mandar trabajo",
                    "copy": "Ese destino no existe para tu trabajo."})
        try:
            prefs = ws_memoria.preferir(body.user_id, body.tipo, body.workspace)
        except ws_memoria.MemoriaError as exc:
            raise HTTPException(status_code=422, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": ws_memoria.CAUSAS.get(exc.causa, exc.causa)})
        return {"preferencias": prefs}

    @router.get("/workspaces/{ws}/memoria")
    def workspace_memoria_leer(ws: str, user_id: Optional[str] = Query(default=None),
                               authorization: Optional[str] = Header(default=None)):
        """CÓMO QUEDÓ este workspace para este dueño. [O5 · ley 5 · ley técnica 4]

        La clave es `(dueño, workspace)` — dominio, no UI. Lo que había era
        `localStorage["aleph_ws_chat_ciencia"]`: una clave de INSTALACIÓN, o sea que dos
        cuentas en la misma máquina compartían el hilo. Eso es la deuda **D1**, y muere acá."""
        _meta_ws(ws)
        _authorize(user_id, authorization)
        from workspaces import memoria as ws_memoria
        try:
            return {"workspace": ws.strip().lower(),
                    "memoria": ws_memoria.como_quedo(user_id, ws.strip().lower())}
        except ws_memoria.MemoriaError as exc:
            raise HTTPException(status_code=422, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": ws_memoria.CAUSAS.get(exc.causa, exc.causa)})

    @router.put("/workspaces/{ws}/memoria")
    def workspace_memoria_guardar(ws: str, body: WorkspaceMemoriaRequest,
                                  authorization: Optional[str] = Header(default=None)):
        """Guarda cómo quedó. Es un MERGE: una pantalla que sólo sabe el hilo no puede
        borrarle la sesión de obras a otra que sólo sabe eso."""
        _meta_ws(ws)
        _authorize(body.user_id, authorization)
        from workspaces import memoria as ws_memoria
        try:
            return {"workspace": ws.strip().lower(),
                    "memoria": ws_memoria.recordar(body.user_id, ws.strip().lower(),
                                                   chat_id=body.chat_id, sid=body.sid,
                                                   deltas=body.deltas)}
        except ws_memoria.MemoriaError as exc:
            raise HTTPException(status_code=422, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": ws_memoria.CAUSAS.get(exc.causa, exc.causa)})

    @router.get("/workspaces/bridge")
    def workspace_bridge(workspace: Optional[str] = Query(default=None)):
        """La tabla del puente, legible. La lee el reporte, la lee una vara, y la va a
        leer la extracción del traductor universal de Fase 6."""
        from artifacts import bridge
        data = bridge.as_json()
        if workspace:
            ws = workspace.strip().lower()
            data["workspaces"] = {k: v for k, v in data["workspaces"].items() if k == ws}
        return data

    @router.post("/workspaces/brain/close")
    def workspace_brain_close(body: WorkspaceBrainCloseRequest,
                              authorization: Optional[str] = Header(default=None)):
        """Cierra el turno del harness en el espacio: `final` + `closed`.

        Sin esto, todo artefacto del workspace saldría `partial` con la referencia
        colgando (`provenance` busca un terminal). `model_final` NO se toma del body:
        se re-deriva de los `workspace_step` que este mismo borde escribió."""
        if body.user_id:
            _authorize(body.user_id, authorization)
        from app.phase1 import workspace_brain as wb
        from artifacts import provenance as _prov
        space_id = _prov.safe_ref(body.space_id)
        if not space_id:
            raise HTTPException(status_code=422, detail={
                "error": "space_id_invalid", "detail": "space_id ausente o malformado"})
        model_final = _brain_measured_model(space_id)
        out = wb.close(
            _make_space_emitter(space_id),
            answer=body.answer or "", ok=bool(body.ok), model_final=model_final,
            run_id=body.run_id, workspace=(body.workspace or "")[:40],
            turns=int(body.turns or 0), error=body.error,
        )
        # [3.6] EL HILO DEL WORKSPACE. El turno entero (pedido + respuesta) queda en SU
        # hilo, no en el de la Sala: dos lugares de conversación, un solo agente. La
        # proyección no es camino crítico — un fallo acá jamás rompe un turno terminado.
        if body.chat_id:
            _authorize_resource(_chat_owner(body.chat_id), authorization)
            if (body.prompt or "").strip():
                _chat_record_user(body.chat_id, body.prompt, kind="obra",
                                  space_id=space_id, client_turn_id=body.client_turn_id)
            _chat_record_answer(body.chat_id, body.answer or "", kind="obra",
                                space_id=space_id, run_id=body.run_id,
                                client_turn_id=body.client_turn_id)
            out["chat_id"] = body.chat_id
        return out

    return router


def install_byok_handler(app) -> None:
    """
    (e) Registra el handler que convierte una BYOKFailure (excepción de dominio) en un
    424 + señal TIPADA → screen 11. NO un 500 mudo. Llamar una vez sobre la app.
    """
    @app.exception_handler(BYOKFailure)
    async def _byok_handler(request, exc: BYOKFailure):  # noqa: ANN001
        return JSONResponse(status_code=BYOK_HTTP_STATUS, content=exc.to_signal())


__all__ = ["build_phase1_router", "install_byok_handler"]
