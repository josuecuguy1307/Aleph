"""
contracts.py — los CONTRATOS del motor de inspección (spec canónico v1).

SOLO interfaces, tipos y firmas. CERO comportamiento de motor: ninguna capa
observa, sintetiza, valida ni forja acá. Las stages son ABCs/Protocols que las
implementaciones reales (session/, observe/, synth, validate, emit) cumplen;
este archivo únicamente CLAVA la forma que deben respetar.

DOS contratos de SEGURIDAD sí ejecutan de verdad — son el candado que el gate
verifica contra disco real y no se pueden declarar sin enforcement o pierden su
garantía:
  • toda credencial pasa por Fernet (cifra-al-guardar / descifra-al-leer; el
    valor en claro nunca toca disco) — cierra el quiebre CASO D donde el Bearer
    del BYO-HTTP se persistía EN CLARO en manifest.json;
  • el namespace anónimo NO colisiona entre dos usuarios anónimos distintos — el
    viejo `registry.belt_dir_for` colapsaba todo anónimo a `anon/<slug>`.
Ambos reusan el vault Fernet del org (platform/gates/vault.py vía crypto.py) —
no inventamos cripto nueva.

Mapa al doc «Motor de Inspección — Arquitectura Completa» (v1):
  Capa 0  → SSRFGuard               (Trampa 3 · corre ANTES de tocar el target)
  Capa 1  → SessionProvider/Session (§2 · las 4 formas, una ABC)
  Capa 2  → Observer                (§1)
  Capa 3  → Synthesizer + WorkingSet(§3)
  Capa 4  → Validator               (§4 · el candado)
  Capa 5  → Emitter                 (§1 · VERIFIED → MCP + belt cards)
  §5      → FailureClass            (dos niveles: REFINE_TOOL / SWITCH_STRATEGY)
  §4      → Strategy                (4 niveles: descubrimiento/auth/forma/navegación)
  §7      → ToolKind READ/WRITE     (split read/write)
"""
from __future__ import annotations

import abc
import hashlib
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

# raíz DURABLE y por-usuario de los belts/credenciales sintetizados.
# Espeja registry.SYNTH_BELTS_DIR sin importar registry (que arrastra el motor).
_REPO_ROOT = Path(__file__).resolve().parents[2]
def _dir_datos(nombre: str) -> Path:
    """`<data_root>/<nombre>` — el dir de datos del USUARIO, no el árbol.
    ⚠️ EL BUNDLE ES SÓLO LECTURA (CLAUDE.md · clase ya pagada en synth_belts, el pin
    del sello y la caché del resolver). Bajo PyInstaller `_REPO_ROOT` cae dentro de
    `_MEIPASS`, el temp que se borra al cerrar: lo que se escriba ahí NO existe en el
    arranque siguiente. Todo lo que se ESCRIBE va al dir de datos del usuario.
    Cae al árbol sólo si `aleph_paths` no se puede importar (dev suelto): en frozen siempre
    resuelve, porque `aleph_paths` viaja en el bundle.
    """
    try:
        import aleph_paths
        return aleph_paths.data_root() / nombre
    except Exception:                    # noqa: BLE001
        return _REPO_ROOT / "product" / "backend" / "data" / nombre

SYNTH_BELTS_DIR = _dir_datos("synth_belts")


def _slug(s: str) -> str:
    """Slug estable y seguro-para-path. Pura forma; no decide nada del motor."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s or "").strip("-").lower()
    return s or "x"


# ══════════════════════════════════════════════════════════════════════════════
# CAPA 0 · SSRFGuard (Trampa 3) — corre ANTES de tocar el target
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class GuardVerdict:
    """allow/deny + razón. La razón viaja para poder loguear POR QUÉ se bloqueó.
    `bool(verdict)` == allowed, para usarlo directo en un `if`."""
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


class SSRFGuard(abc.ABC):
    """Capa 0 · Trampa 3 · interfaz que corre ANTES de tocar el target.

    El motor apunta a URLs arbitrarias del usuario → agujero SSRF de manual.
    Obligatorio, no opcional: ninguna capa toca una URL que este guard no
    aprobó primero. Fail-closed: ante la duda, deny.
    """

    @abc.abstractmethod
    def check(self, url: str) -> GuardVerdict:
        """Recibe una URL → devuelve allow/deny + razón. NO hace la request;
        solo dictamina si tocarla es seguro."""
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# CAPA 1 · SessionProvider (§2) — las 4 formas, UNA interfaz
# ══════════════════════════════════════════════════════════════════════════════
class AuthForm(str, Enum):
    """Las 4 formas de sesión (§2). El identificador (Capa 0) elige cuál; el
    resto del pipeline es idéntico para las cuatro."""
    OPEN = "open"                      # abierto · sin login
    TOKEN = "token"                    # Forma 1 · key/token en header/query/cookie
    LOGIN_API = "login_api"            # Forma 2 · endpoint de login define la sesión
    HUMAN_SESSION = "human_session"    # Forma 3 · humano se loguea, motor captura la cookie


class SessionError(Exception):
    """La sesión no se pudo conseguir o no vale. (La sesión vale o no vale: la
    puerta no miente — §1.)"""


@dataclass(frozen=True)
class Session:
    """Una sesión autenticada UNIFORME — lo que las 4 formas devuelven IGUAL.
    El observador (Capa 2) la consume sin saber de qué forma vino.

    Inmutable: una sesión es un substrate fijo que el loop usa, no muta."""
    form: AuthForm
    base_url: str
    headers: Mapping[str, str] = field(default_factory=dict)   # auth ya inyectada (redactada en logs)
    cookies: Mapping[str, str] = field(default_factory=dict)
    storage_state: Optional[Mapping[str, Any]] = None          # Forma 3: cookie/localStorage capturado
    meta: Mapping[str, Any] = field(default_factory=dict)


class SessionProvider(abc.ABC):
    """Capa 1 · ABC. UNA implementación por forma de auth (§2). Las 4 devuelven
    LO MISMO: una `Session` lista para observar. La puerta, no el motor.

    NO se instancia directo (es abstracta): el identificador (Capa 0) decide qué
    subclase instanciar según la forma detectada.

    LÍNEA ROJA (Trampa 1): en Forma 3 el motor CAPTURA la sesión que el humano
    dejó abierta — NUNCA resuelve 2FA/captcha. Una implementación que asuma "el
    motor pasa el 2FA" viola este contrato.
    """

    #: qué forma de auth implementa esta puerta (cada subclase la fija)
    form: ClassVar[AuthForm]

    @abc.abstractmethod
    def acquire(self) -> Session:
        """Devuelve una sesión autenticada uniforme, lista para el Observador
        (Capa 2). Levanta SessionError si la sesión no vale."""
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# §7 · read/write split  +  CAPA 3 · el WORKING SET (§3)
# ══════════════════════════════════════════════════════════════════════════════
class ToolKind(str, Enum):
    """§7 · un READ se valida llamándolo (seguro, alimenta la frontera); un
    WRITE NO se ejecuta (se verifica por schema/OPTIONS/dry-run, no expande
    frontera). No es opcional: o creás/borrás cosas reales "probando", o nunca
    validás los writes."""
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class Capability:
    """CONFIRMED — algo que EXISTE de verdad en el target (un endpoint que
    respondió, un campo presente). Hecho observado, no propuesta."""
    endpoint: str
    method: str
    evidence: str                       # qué observación lo confirma (status, snippet de schema…)
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateTool:
    """CANDIDATES — una tool PROPUESTA por el sintetizador, SIN validar. Puede
    estar alucinada; el validador (Capa 4) decide."""
    name: str
    kind: ToolKind
    endpoint: str
    method: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""
    derived_from: tuple[str, ...] = ()  # qué CONFIRMED/obs la originaron


@dataclass(frozen=True)
class VerifiedTool:
    """VERIFIED — una candidata que PASÓ el candado contra el software vivo.
    Es lo ÚNICO que entra al belt (Capa 5)."""
    candidate: CandidateTool
    verified_by: str                    # "200-OK+schema-match" | "OPTIONS" | "dry-run"
    sample_response: Optional[str] = None   # reads: snippet minado (alimenta FRONTIER)


@dataclass(frozen=True)
class FailedTool:
    """FAILED{tool, razón} — el COMBUSTIBLE del loop. NO se descarta: la razón
    (FailureClass) decide el próximo move y se alimenta al sintetizador para no
    repetir el error."""
    candidate: CandidateTool
    failure: "FailureClass"
    detail: str = ""


@dataclass(frozen=True)
class FrontierLead:
    """FRONTIER — una pista SIN explorar que un read minado destapó: un ID en
    una respuesta, un link, paginación, un sub-recurso."""
    hint: str
    kind: str = "unknown"               # id|link|pagination|subresource
    source_tool: Optional[str] = None


@dataclass(frozen=True)
class WorkingSet:
    """El estado del loop interno (§3) en una vuelta. INMUTABLE: cada vuelta
    produce un WorkingSet NUEVO (las transiciones devuelven copias, no mutan).

        CONFIRMED  = lo que existe de verdad
        CANDIDATES = tools propuestas, sin validar
        VERIFIED   = las que pasaron el candado → van al belt
        FAILED     = {tool, razón} ← el combustible del loop
        FRONTIER   = pistas sin explorar
    """
    confirmed: tuple[Capability, ...] = ()
    candidates: tuple[CandidateTool, ...] = ()
    verified: tuple[VerifiedTool, ...] = ()
    failed: tuple[FailedTool, ...] = ()
    frontier: tuple[FrontierLead, ...] = ()

    def with_(self, **changes: Any) -> "WorkingSet":
        """Azúcar sobre dataclasses.replace: devuelve un WorkingSet NUEVO con
        campos reemplazados, sin mutar el actual. Forma, no política: QUÉ se
        agrega cada vuelta lo decide el loop, no este tipo."""
        return replace(self, **changes)


# ══════════════════════════════════════════════════════════════════════════════
# CAPAS 2·3·4 · contratos de etapa (Observador → Sintetizador → Validador)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Observation:
    """Salida cruda del Observador (Capa 2): el mapa de capacidades + las
    Capability CONFIRMED que se desprenden. "Puede ver parcial" — por eso el
    loop vuelve a observar la frontera que se abre."""
    capability_map: Mapping[str, Any]   # endpoints/schema/HAR/DOM crudos
    confirmed: tuple[Capability, ...] = ()
    passive: bool = True                # 1ra vuelta pasiva; luego activa


@dataclass(frozen=True)
class Validation:
    """El veredicto del Validador (Capa 4 · el candado) sobre un lote de
    candidatas. "No miente — es el árbitro." Los reads que pasaron MINAN
    frontera; los writes verificados NO (no se ejecutaron)."""
    verified: tuple[VerifiedTool, ...] = ()
    failed: tuple[FailedTool, ...] = ()
    frontier: tuple[FrontierLead, ...] = ()


@runtime_checkable
class Observer(Protocol):
    """Capa 2 · contrato de etapa. Con la sesión adentro, mira QUÉ es el
    software a partir de las pistas de FRONTIER → mapa de capacidades crudo +
    CONFIRMED. Entrada/salida respetan el working set."""

    def observe(self, session: Session, frontier: Sequence[FrontierLead]) -> Observation:
        ...


@runtime_checkable
class Synthesizer(Protocol):
    """Capa 3 · contrato de etapa. Opus propone: "vi estos endpoints/campos →
    estas tools tienen sentido" → CANDIDATES. CLAVE: recibe los FAILED para no
    repetir el error. Puede alucinar tools — el validador las atrapa."""

    def synthesize(
        self,
        confirmed: Sequence[Capability],
        observation: Observation,
        failed: Sequence[FailedTool],
    ) -> tuple[CandidateTool, ...]:
        ...


@runtime_checkable
class Validator(Protocol):
    """Capa 4 · contrato de etapa · EL CANDADO. Llama CADA candidata contra el
    software vivo y separa VERIFIED de FAILED, minando FRONTIER de los reads que
    pasan. Respeta el split read/write (§7): READ se llaman; WRITE NO se
    ejecutan (schema/OPTIONS/dry-run)."""

    def validate(self, session: Session, candidates: Sequence[CandidateTool]) -> Validation:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# §5 · Tabla de fallas de dos niveles (el cerebro de los loops)
# ══════════════════════════════════════════════════════════════════════════════
class FailureLevel(str, Enum):
    """El nivel decide QUÉ loop reacciona ante una falla."""
    REFINE_TOOL = "refine_tool"          # interno · el loop interno arregla ESTA tool
    SWITCH_STRATEGY = "switch_strategy"  # externo · el loop externo cambia de estrategia


class FailureClass(Enum):
    """§5 · cada síntoma → (nivel, move). Lo que hace al motor inteligente en
    vez de girar al pedo. `escalates`=True marca el caso 401/403: arranca
    interno (fuera-de-scope), pero si es SISTÉMICO escala a externo (¿sesión
    mal?).

        síntoma           nivel             move
        ─────────────────────────────────────────────────────────────────
        404               REFINE_TOOL       drop tool / re-observar
        400               REFINE_TOOL       re-sintetizar el SHAPE
        401/403           REFINE_TOOL*      marcar fuera-de-scope (*escala)
        200 + schema≠     REFINE_TOOL       re-sintetizar la DESC
        todos 404+openapi SWITCH_STRATEGY   switchear al peldaño A (autodescriptivo)
        timeout / 5xx     SWITCH_STRATEGY   cambiar superficie / abortar rama
    """
    #                  (symptom,            level,                         move,                         escalates)
    NOT_FOUND        = ("404",              FailureLevel.REFINE_TOOL,     "drop_tool_or_reobserve",      False)
    BAD_SHAPE        = ("400",              FailureLevel.REFINE_TOOL,     "resynth_shape",               False)
    FORBIDDEN        = ("401_403",          FailureLevel.REFINE_TOOL,     "mark_out_of_scope",           True)
    SCHEMA_MISMATCH  = ("200_schema",       FailureLevel.REFINE_TOOL,     "resynth_description",         False)
    ALL_404_OPENAPI  = ("all404_openapi",   FailureLevel.SWITCH_STRATEGY, "switch_to_self_describing",   False)
    TIMEOUT          = ("timeout_5xx",      FailureLevel.SWITCH_STRATEGY, "change_surface_or_abort",     False)

    def __init__(self, symptom: str, level: FailureLevel, move: str, escalates: bool):
        self.symptom = symptom
        self.level = level
        self.move = move
        self.escalates = escalates

    @classmethod
    def from_symptom(cls, symptom: str) -> "FailureClass":
        """Mapeo (estático) síntoma→clase. Lookup puro de la tabla §5; no decide
        nada del motor más allá de leer la fila."""
        for member in cls:
            if member.symptom == symptom:
                return member
        raise KeyError(f"síntoma sin fila en la tabla §5: {symptom!r}")


# ══════════════════════════════════════════════════════════════════════════════
# §4 · Strategy — una hipótesis de crackeo en 4 niveles (el loop externo)
# ══════════════════════════════════════════════════════════════════════════════
class Discovery(str, Enum):
    """Nivel 1 · ¿cómo averiguo qué expone?"""
    OPENAPI = "openapi"                       # sniff /openapi.json /swagger
    GRAPHQL_INTROSPECT = "graphql_introspection"
    REST_PATTERN = "rest_pattern"             # /api/v1, convención REST
    PASSIVE_HAR = "passive_har_dom"           # observación pasiva HAR/DOM
    FINGERPRINT = "fingerprint"               # huella de familia (Odoo/Supabase/…)


class AuthChannel(str, Enum):
    """Nivel 2 · ¿cómo consigo/uso la sesión?"""
    HEADER = "header"
    QUERY = "query"
    COOKIE = "cookie"
    LOGIN_ENDPOINT = "login_endpoint"


class ToolForm(str, Enum):
    """Nivel 3 · ¿cómo llamo el endpoint?"""
    QUERY_PARAMS = "query"
    BODY = "body"
    PATH = "path"
    PAGE_OFFSET = "pagination_offset"
    PAGE_CURSOR = "pagination_cursor"
    PAGE_NUMBER = "pagination_page"


class Navigation(str, Enum):
    """Nivel 4 · ¿cómo recorro?"""
    FOLLOW_LINKS = "follow_links"
    ENUMERATE_IDS = "enumerate_ids"
    SEARCH = "search"


@dataclass(frozen=True)
class Strategy:
    """§4 · una hipótesis de cómo crackear ESTE software, en 4 niveles. El loop
    externo es un torneo: las estrategias compiten, el validador arbitra, gana
    una y se captura (indexada por huella → el moat §8).

    Inmutable: una estrategia es una combinación fija que compite tal cual."""
    discovery: Discovery
    auth: AuthChannel
    tool_form: ToolForm
    navigation: Navigation
    fingerprint: Optional[str] = None         # familia detectada (peldaño B), si la hay


# ══════════════════════════════════════════════════════════════════════════════
# CAPA 5 · Emisor — tools VERIFIED → MCP + belt cards
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class BeltCard:
    """La pieza equipable en El Cuarto (una card por tool, misma forma que el
    catálogo). Forma, no contenido — el Emisor real la llena."""
    id: str
    label: str
    tool: str
    zone: str                           # fuentes|mesa|entrega
    backed_by: str                      # server_name del MCP forjado


@dataclass(frozen=True)
class ForgedMCP:
    """El MCP forjado + sus belt cards: la salida del Emisor (Capa 5),
    equipable en El Cuarto."""
    server_name: str
    belt_ref: str                       # ref RELATIVA al repo (portable, scopeada al user)
    tools: tuple[str, ...]
    cards: tuple[BeltCard, ...]


@runtime_checkable
class Emitter(Protocol):
    """Capa 5 · contrato. Entrada = tools VERIFIED (SOLO verificadas, jamás
    candidatas — lo fuerza el tipo `VerifiedTool`). Salida = MCP forjado + belt
    cards. No valida (eso ya pasó); empaqueta lo que el candado dejó pasar."""

    def emit(self, verified: Sequence[VerifiedTool]) -> ForgedMCP:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# CAPA 5 (camino AGENTE) · el segundo tipo de capacidad — un SUB-AGENTE equipable
# ──────────────────────────────────────────────────────────────────────────────
# PARALELO al camino de tools (Candidate→Verified→Forged + Emitter), NO lo
# reemplaza. La forja hoy equipa SOLO tools (ForgedMCP{tools}); el amendment
# `belt.agent_refs[]` (paso 1) abrió un segundo tipo de capacidad: el sub-agente
# (una OTRA RECETA con su propio Núcleo). Estos tipos son el lado «forja» de ese
# amendment: VerifiedAgent(receta) → ForgedAgent{recipe_ref}.
#
# REGLA LOAD-BEARING (paso 1/5): un agente equipado viaja SIEMPRE por la vía del
# agente (`belt.agent_refs[]` / `agentServers{}`), JAMÁS por la de la tool
# (`belt.belt_refs[]` / `mcpServers{}`). El tipo separado es lo que mantiene esa
# separación imposible de cruzar por accidente. NO se toca `ForgedMCP.tools`.
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CandidateAgent:
    """CANDIDATE-AGENT — un sub-agente PROPUESTO para equipar: una ref a OTRA
    receta, SIN confirmar todavía que esa receta existe ni que es v1. Paralelo de
    CandidateTool (el validador decide). Lleva sólo identidad portable, no la
    receta (eso lo trae el VerifiedAgent)."""
    agent_ref: str                      # slug/path a la receta hija (portable, sin path absoluto)
    name: str = ""                      # identidad legible (meta.name del hijo), si se conoce
    description: str = ""


@dataclass(frozen=True)
class VerifiedAgent:
    """VERIFIED-AGENT — un sub-agente cuya receta EXISTE y pasó el check
    estructural v1 (schema_version=='v1' + meta + belt). Es lo ÚNICO que se equipa
    como agent_ref (Capa 5, camino agente). Paralelo de VerifiedTool — el agente NO
    es una tool: viaja por su propia vía y nunca por el belt de tools.

    `source_ref`: ref RELATIVA al repo si la receta YA vive en disco bajo el repo
    (p.ej. `catalog/agents/research-sub.config.json`) → el emisor la referencia
    tal cual, sin duplicar. None → la receta vino inline y el emisor la PERSISTE."""
    candidate: CandidateAgent
    recipe: Mapping[str, Any]           # la receta hija cargada (v1: schema_version+meta+belt)
    source_ref: Optional[str] = None    # ref relativa si ya está en disco bajo el repo; None = inline
    verified_by: str = "v1-shape"       # cómo se confirmó (check estructural v1 / validate_recipe)


@dataclass(frozen=True)
class ForgedAgent:
    """El AGENTE forjado/equipable: la salida del Emisor de agentes (Capa 5),
    PARALELO a ForgedMCP. NO trae `tools` (un agente DELEGA, no inlinea tools);
    trae `recipe_ref` = la ref RELATIVA a la receta hija que aterriza en
    `belt.agent_refs[]` (NUNCA `belt_refs[]` — regla load-bearing paso 1/5).

    `manifest_ref`: ref al belt-agent manifest (`agentServers{}`, el descriptor
    paralelo a `mcpServers{}`) si se escribió; '' si no."""
    agent_name: str                     # identidad del agente equipado (paralelo a server_name)
    recipe_ref: str                     # ref RELATIVA al repo → belt.agent_refs[] (paralelo a belt_ref)
    agent_ref: str                      # el ref original tal cual el caller lo pidió
    manifest_ref: str = ""              # ref al manifest con agentServers{} (descriptor), si se escribió


@runtime_checkable
class AgentEmitter(Protocol):
    """Capa 5 · contrato PARALELO a Emitter, para el camino del AGENTE. Entrada =
    sub-agentes VERIFIED (recetas hijas existentes, SOLO verificadas — lo fuerza el
    tipo `VerifiedAgent`). Salida = un ForgedAgent por agente. NO forja un MCP (no
    hay tools que cablear): referencia/persiste la receta hija y deja el
    `recipe_ref` listo para `belt.agent_refs[]`. No valida (eso ya pasó)."""

    def emit_agent(self, verified: Sequence[VerifiedAgent]) -> tuple[ForgedAgent, ...]:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Persistencia de credenciales — TODA credencial pasa por Fernet (+ fix namespace)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Principal:
    """Quién POSEE una credencial/belt.

      • Autenticado  → `user_id` estable.
      • Anónimo      → un `anon_id` OPACO y ÚNICO por principal (un token de
                       sesión, no el literal "anon").

    El bug viejo (`registry.belt_dir_for`) colapsaba todo anónimo a la carpeta
    `anon/<slug>`: dos anónimos distintos con el mismo slug COMPARTÍAN carpeta y
    una credencial de uno la leía el otro (CASO D). Acá cada anónimo trae su
    propio `anon_id` → namespaces disjuntos.
    """
    user_id: Optional[str] = None
    anon_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not (self.user_id or self.anon_id):
            raise ValueError(
                "Principal necesita user_id (autenticado) o anon_id (anónimo único); "
                "el literal 'anon' compartido está PROHIBIDO — colisiona (CASO D)."
            )


def credential_namespace(principal: Principal) -> str:
    """Segmento de path AISLADO por principal.

      • autenticado → `u/<slug(user_id)>`
      • anónimo     → `anon/<sha256(anon_id)[:16]>`  ← el hash del id ÚNICO,
                      NUNCA el literal `anon`.

    Garantía: dos anónimos distintos con el mismo slug de belt NO comparten
    carpeta (sus anon_id difieren → el hash difiere → el namespace difiere)."""
    if principal.user_id:
        return f"u/{_slug(principal.user_id)}"
    digest = hashlib.sha256((principal.anon_id or "").encode("utf-8")).hexdigest()[:16]
    return f"anon/{digest}"


def credential_dir(principal: Principal, slug: str, *, root: Path = SYNTH_BELTS_DIR) -> Path:
    """La carpeta AISLADA y por-principal donde viven el belt + las credenciales
    de este slug. Reemplaza `registry.belt_dir_for(user_id, slug)` (que
    colisionaba): el namespace ahora sale del Principal, no del literal `anon`."""
    return root / credential_namespace(principal) / slug


class CredentialStore(abc.ABC):
    """Contrato de persistencia de credenciales.

    INVARIANTE: toda credencial pasa por Fernet — se CIFRA al guardar, se
    DESCIFRA al leer, y el valor en claro NUNCA toca disco. Cierra el quiebre
    CASO D (el Bearer del BYO-HTTP se persistía en claro en manifest.json).
    """

    @abc.abstractmethod
    def put(self, name: str, value: str) -> None:
        """Cifra `value` con Fernet y lo persiste. El plaintext no toca disco."""
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, name: str) -> Optional[str]:
        """Descifra y devuelve el valor, o None si no está guardado."""
        raise NotImplementedError

    @abc.abstractmethod
    def has(self, name: str) -> bool:
        raise NotImplementedError


class FernetCredentialStore(CredentialStore):
    """Implementación de REFERENCIA del contrato (no es lógica de motor): reusa
    el vault Fernet del org (platform/gates/vault.py · PBKDF2→Fernet, vía
    crypto.py). NO inventa cripto. Aislada por-principal vía `credential_dir` →
    el namespace anónimo no colisiona."""

    def __init__(
        self,
        principal: Principal,
        slug: str,
        *,
        master_secret: Optional[str] = None,
        root: Path = SYNTH_BELTS_DIR,
    ):
        # carga perezosa del vault del org por ruta (mismo patrón que crypto.py)
        from inspection import crypto  # local: evita costo de import si no se usa el store

        store_path = credential_dir(principal, slug, root=root) / "credentials.enc"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        vault_mod = crypto._load_vault_module()
        self._vault = vault_mod.CredentialVault(
            str(store_path),
            master_secret=master_secret or crypto.runtime_master_secret(),
        )

    def put(self, name: str, value: str) -> None:
        self._vault.put(name, value)

    def get(self, name: str) -> Optional[str]:
        if not self._vault.has(name):
            return None
        # inject_env es el único getter de valor del vault (camino auditado).
        return self._vault.inject_env({}, [name]).get(name)

    def has(self, name: str) -> bool:
        return self._vault.has(name)


__all__ = [
    # Capa 0
    "GuardVerdict", "SSRFGuard",
    # Capa 1
    "AuthForm", "SessionError", "Session", "SessionProvider",
    # §7 + working set (Capa 3)
    "ToolKind", "Capability", "CandidateTool", "VerifiedTool", "FailedTool",
    "FrontierLead", "WorkingSet",
    # etapas (Capas 2·3·4)
    "Observation", "Validation", "Observer", "Synthesizer", "Validator",
    # §5 fallas
    "FailureLevel", "FailureClass",
    # §4 estrategia
    "Discovery", "AuthChannel", "ToolForm", "Navigation", "Strategy",
    # Capa 5 (tools)
    "BeltCard", "ForgedMCP", "Emitter",
    # Capa 5 (camino agente · paralelo, aditivo)
    "CandidateAgent", "VerifiedAgent", "ForgedAgent", "AgentEmitter",
    # credenciales + namespace
    "Principal", "credential_namespace", "credential_dir",
    "CredentialStore", "FernetCredentialStore", "SYNTH_BELTS_DIR",
]
