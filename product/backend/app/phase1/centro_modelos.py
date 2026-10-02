"""centro_modelos.py — EL CENTRO DE MODELOS (FIX-P8 · el punto 35).

LA SEPARACIÓN QUE ORDENA LA PANTALLA:
    modelos  = lo que PIENSA   (esta pantalla)
    conectores = lo que HACE   (el Catálogo · Conectar.dc.html)

Un MCP NO vive acá. El banner de un conector metido entre modelos fue el caso índice
del bug (Globalfishingwatch): dos cosas distintas compitiendo por la misma pantalla.
Este módulo no conoce belts, ni servidores MCP, ni cards del catálogo — por construcción.

QUÉ RESUELVE (lo que el diseño sellado pedía y nunca se construyó):

  · LOS 3 MODOS  — CLI por suscripción · API con tu llave · LOCAL descargado (el nuevo).
    (+ «Incluido», que existe en el producto: esconderlo sería mentir sobre el default.)
  · LAS 5 CATEGORÍAS — visión · razonamiento alto · código · rápido/liviano · embeddings.
  · HUGGING FACE EN VIVO — el catálogo de modelos locales sale de la API pública por
    categoría (sort=trendingScore + filtro de formato). CERO nombres horneados: los
    nombres expiran, los filtros no. Sin red → fallo VISIBLE y lo YA descargado igual.
  · VEREDICTO CONTRA TU MÁQUINA — peso vs disco libre + RAM pedida vs disponible.
  · DESCARGA GUIADA — progreso real (MB/s/restante), CANCELABLE y que LIMPIA, y al
    terminar una PRUEBA AUTOMÁTICA que corre el modelo de verdad (imagen mínima si es
    de visión) → 🟢 con evidencia+timestamp o 🔴 con causa. La salida de éxito RIGE.
  · CAPABILITY GATING — cada pieza declara el tier mínimo que necesita. Si el modelo
    elegido no alcanza: aviso honesto + recomendación + [Descargar este]/[Conectar API].
    JAMÁS corre mudo. El rol Guía es frontier-only (misma vara que cuarto_guide).

VOCABULARIO — el CERRADO del Motor de Verdad, EXTENDIDO con lo que sólo pasa acá:

  estado ∈ {probado, detectado, roto, no_configurado, premium}      (los 5 del semáforo)
  causa  ∈ motor_verdad.CAUSAS ∪ CAUSAS_MODELO                      (ver CAUSAS_MODELO)

CAUSAS_MODELO existe porque un modelo local tiene modos de fallo que un CLI o una key no
tienen (no hay runtime que lo corra; no entra en el disco; la descarga la cancelaste vos).
Mapearlas a las viejas sería mentir con vocabulario prestado — «CLI no instalado» para un
paquete de Python es exactamente el rótulo que miente. Se agregan acá, declaradas.

NADA se marca verde sin evidencia: el estado de un modelo local sale de HABERLO CORRIDO.
"""
from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.phase1 import motor_verdad as MV
from app.phase1 import modelos_discovery as _disc

try:
    import aleph_paths as _ap
except ImportError:  # el módulo se importa suelto en tests
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap


# ══════════════════════════════════════════════════════════════════════════════════
# §0 · VOCABULARIO
# ══════════════════════════════════════════════════════════════════════════════════
PROBADO = MV.PROBADO
DETECTADO = MV.DETECTADO
ROTO = MV.ROTO
NO_CONFIGURADO = MV.NO_CONFIGURADO
PREMIUM = MV.PREMIUM

#: Causas propias de un modelo. EXTENSIÓN DECLARADA del vocabulario cerrado del motor.
#: Cada una tiene su camino en el front (modelos.semaforo.js) — ninguna queda muda.
SIN_RUNTIME = "sin_runtime"                # está descargado pero no hay con qué correrlo
SIN_ESPACIO = "sin_espacio"                # no entra en el disco de esta máquina
DESCARGA_CANCELADA = "descarga_cancelada"  # la cortaste vos (no es un fallo del sistema)
FORMATO_NO_SOPORTADO = "formato_no_soportado"

CAUSAS_MODELO = frozenset({SIN_RUNTIME, SIN_ESPACIO, DESCARGA_CANCELADA, FORMATO_NO_SOPORTADO})
CAUSAS = frozenset(MV.CAUSAS) | CAUSAS_MODELO

# ── familias (los MODOS) ──────────────────────────────────────────────────────────
INCLUIDO = "incluido"
CLI = "cli"
API = "api"
LOCAL = "local"
FAMILIAS = frozenset({INCLUIDO, CLI, API, LOCAL})

#: LOS GRUPOS DE LA PANTALLA — orden, título y lede. Vive acá (no en el front) por la
#: misma razón que en el Centro de Conexiones: es la MISMA verdad que decide en qué
#: familia cae cada fila, y dos tablas se desincronizan.
GRUPOS = [
    (INCLUIDO, "Incluido", "Viene con Aleph. No tienes que traer nada."),
    (CLI, "CLI · tu suscripción", "Tu Claude Code / Codex piensan por tu plan, sin API."),
    (API, "API con tu llave", "Traes tu propia llave; pagas tu consumo directo al proveedor."),
    (LOCAL, "Local · descargado", "Corre en tu máquina. Sin llave, sin nube, sin costo por token."),
]

RECOMENDADO = {INCLUIDO: "cognicion", CLI: "claude_cli", API: "groq"}


# ══════════════════════════════════════════════════════════════════════════════════
# §1 · LAS 5 CATEGORÍAS  ·  y cómo se le preguntan a Hugging Face
# ══════════════════════════════════════════════════════════════════════════════════
# `hf` = los parámetros de la API pública. NO hay nombres de modelo acá: los nombres
# expiran (un top-10 de hoy es una lista muerta en tres meses); los filtros no.
VISION = "vision"
RAZONAMIENTO = "razonamiento"
CODIGO = "codigo"
RAPIDO = "rapido"
EMBEDDINGS = "embeddings"

CATEGORIAS = [
    {
        "id": VISION, "es": "Visión", "en": "Vision",
        "lede_es": "Mira imágenes: capturas, fotos, diagramas, PDFs escaneados.",
        "lede_en": "Looks at images: screenshots, photos, diagrams, scanned PDFs.",
        "hf": {"pipeline_tag": "image-text-to-text"},
        "prueba": "vision",
    },
    {
        "id": RAZONAMIENTO, "es": "Razonamiento alto", "en": "High reasoning",
        "lede_es": "Piensa antes de contestar: problemas largos, varios pasos, planes.",
        "lede_en": "Thinks before answering: long problems, multiple steps, plans.",
        "hf": {"pipeline_tag": "text-generation", "filter": ["reasoning"]},
        "prueba": "texto",
    },
    {
        "id": CODIGO, "es": "Código", "en": "Code",
        "lede_es": "Escribe y lee código, entiende repos, arregla errores.",
        "lede_en": "Writes and reads code, understands repos, fixes errors.",
        "hf": {"filter": ["code"], "pipeline_tag": "text-generation"},
        "prueba": "texto",
    },
    {
        "id": RAPIDO, "es": "Rápido / liviano", "en": "Fast / lightweight",
        "lede_es": "Contesta al toque y entra en cualquier máquina. Para tareas simples.",
        "lede_en": "Answers instantly and fits anywhere. For simple tasks.",
        "hf": {"pipeline_tag": "text-generation"},
        "prueba": "texto",
        "max_gb": 3.0,          # el filtro de esta categoría ES el tamaño
    },
    {
        "id": EMBEDDINGS, "es": "Embeddings", "en": "Embeddings",
        "lede_es": "Convierte texto en vectores: buscar por significado, memoria, RAG.",
        "lede_en": "Turns text into vectors: semantic search, memory, RAG.",
        "hf": {"pipeline_tag": "feature-extraction"},
        "prueba": "embedding",
    },
]
CATEGORIAS_POR_ID = {c["id"]: c for c in CATEGORIAS}


# ══════════════════════════════════════════════════════════════════════════════════
# §2 · TIERS  ·  la escalera de capacidad y quién la exige
# ══════════════════════════════════════════════════════════════════════════════════
# Un tier NO es una opinión: es una cota. Se estima del tamaño (parámetros/peso) para los
# locales y se declara para los hosteados, porque de esos sí sabemos qué son.
TIERS = ["chico", "medio", "grande", "frontier"]
TIER_IDX = {t: i for i, t in enumerate(TIERS)}

TIER_ES = {"chico": "chico", "medio": "medio", "grande": "grande", "frontier": "frontier"}

#: Aliases hosteados que SON frontier. Misma vara que cuarto_guide._es_frontier_guia y
#: que el selector del Cuarto: la familia Opus-4.8 (lane incluida), tu propia API grande,
#: o tu CLI por suscripción. FAIL-CLOSED: lo que no sabemos clasificar NO es frontier.
def _cli_specs_or_empty():
    try:
        import sys as _sys
        _ad = str(Path(__file__).resolve().parents[4] / "platform" / "assembler")
        if _ad not in _sys.path:
            _sys.path.insert(0, _ad)
        from cli_brain.registry import specs as _specs
        return _specs()
    except Exception:
        return ()


def _cli_frontier_slugs() -> tuple[str, ...]:
    specs = _cli_specs_or_empty()
    if specs:
        return tuple("cli." + s.provider_id for s in specs)
    return ("cli.claude_cli", "cli.codex_cli")  # E1-FALLBACK


FRONTIER_SLUGS = frozenset({
    "incluido.cognicion",
    *_cli_frontier_slugs(),
    "api.anthropic", "api.openai", "api.openrouter",
})

#: Configuración ejecutable que acompaña a las filas del selector compartido. No es una
#: tabla del cliente: el sidecar entrega el modelo/base URL exactos sólo para modelos que
#: ya están conectados (más el Default, aunque esté caído). HF no aparece como API: en V2
#: Hugging Face sigue siendo exclusivamente descarga local.
def _picker_cli() -> dict:
    out = {}
    specs = _cli_specs_or_empty()
    if not specs:
        specs = ()  # las filas históricas se reponen abajo
    for s in specs:
        out["cli." + s.provider_id] = {
            "picker_id": s.provider_id,
            "model": s.response_model_id,
            "base_url": "http://127.0.0.1:8926/v1",
            "brain_provider": s.provider_id,
            "model_use_capabilities": list(s.capabilities),
        }
    if not out:
        out = {  # E1-FALLBACK
            "cli.claude_cli": {
                "picker_id": "claude_cli", "model": "claude-code-cli",
                "base_url": "http://127.0.0.1:8926/v1", "brain_provider": "claude_cli",
                # ESPEJO de `registry.SPECS[claude_cli].capabilities`, `vision` incluida:
                # el puente la transporta (`claude_cli.build_stdin`). Si las dos listas se
                # separan, este respaldo miente justo cuando el registry no se pudo leer.
                "model_use_capabilities": ["text", "streaming", "tool_calling", "vision",
                                           "reasoning", "code"],
            },
            "cli.codex_cli": {
                "picker_id": "codex_cli", "model": "codex-cli",
                "base_url": "http://127.0.0.1:8926/v1", "brain_provider": "codex_cli",
                "model_use_capabilities": ["text", "streaming", "tool_calling", "reasoning", "code"],
            },
        }
    return out


_PICKER_HOSTEADO = {
    "incluido.cognicion": {
        "picker_id": "opus", "model": "anthropic/claude-opus-4.8",
        "base_url": "https://openrouter.ai/api/v1", "alias": "brain",
        # Capacidad técnica de la RUTA gestionada, comprobada por el loop actual. No se
        # deduce de «frontier»: es la matriz que model-use/v1 usa para admitir llamadas.
        "model_use_capabilities": ["text", "streaming", "tool_calling", "vision", "reasoning"],
    },
    **_picker_cli(),
    # ── EL PISO DEL ENDPOINT, NO LA FICHA DEL MODELO ────────────────────────────────────
    # Las ocho vías de API sacan su matriz REAL del catálogo VIVO del proveedor, por modelo
    # elegido (ver `_map_caps` más abajo). Pero `_modelo_de_api` dice, y con razón, que
    # «descubrir es una mejora, no una dependencia»: sin red, con el proveedor caído o con
    # uno que no publica catálogo, devuelve el id declarado y la fila sigue CONECTADA. En ese
    # estado la fila quedaba sin matriz alguna y model-use/v1 la rechazaba entera.
    #
    # Esto es el PISO: lo que es cierto de la ruta pase lo que pase, para cualquier modelo de
    # chat que el endpoint OpenAI-compatible pueda resolver. `text` y `streaming` lo son de
    # los ocho. `tool_calling`, `vision` y `reasoning` NO entran acá a propósito: varían por
    # modelo, y declararlos por marca es la mentira que ya cometía el respaldo por rasgos.
    # Que los conceda el catálogo, que sabe cuál modelo es; si no llegó, la llamada que los
    # exija falla cerrada y con causa.
    "api.anthropic": {
        "picker_id": "api:anthropic", "model": "claude-opus-4-8",
        "base_url": "https://api.anthropic.com/v1", "byok_ref": "keys:anthropic",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.openai": {
        "picker_id": "api:openai", "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1", "byok_ref": "keys:openai",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.openrouter": {
        "picker_id": "api:openrouter", "model": "openai/gpt-4o",
        "base_url": "https://openrouter.ai/api/v1", "byok_ref": "keys:openrouter",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.groq": {
        "picker_id": "api:groq", "model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1", "byok_ref": "keys:groq",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.deepseek": {
        "picker_id": "api:deepseek", "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1", "byok_ref": "keys:deepseek",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.mistral": {
        "picker_id": "api:mistral", "model": "mistral-large-latest",
        "base_url": "https://api.mistral.ai/v1", "byok_ref": "keys:mistral",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.together": {
        "picker_id": "api:together", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "base_url": "https://api.together.xyz/v1", "byok_ref": "keys:together",
        "model_use_capabilities": ["text", "streaming"],
    },
    "api.gemini": {
        "picker_id": "api:gemini", "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "byok_ref": "keys:gemini",
        "model_use_capabilities": ["text", "streaming"],
    },
}

#: CAPABILITY GATING — cada pieza declara el tier MÍNIMO que necesita y, si aplica, la
#: capacidad. Es la tabla que hace que nada corra mudo: si el modelo elegido no llega, la
#: pieza lo dice ANTES de correr, con recomendación y camino.
#:
#: `capacidad` mapea a una de las 5 categorías: la pieza no pide "un modelo bueno", pide
#: EXACTAMENTE lo que necesita (mirar una imagen ≠ razonar largo).
PIEZAS = {
    "guia": {
        "es": "El Guía", "en": "The Guide", "min_tier": "frontier", "capacidad": None,
        "porque_es": "copilota el armado entero: si se pierde a mitad de camino te deja peor que solo",
        "porque_en": "it copilots the whole build: losing the thread midway leaves you worse off than alone",
    },
    "vision": {
        "es": "Mirar una imagen", "en": "Look at an image", "min_tier": "chico", "capacidad": VISION,
        "porque_es": "sin un modelo que vea, la respuesta sería adivinada sobre algo que nadie miró",
        "porque_en": "without a model that sees, the answer would be guessed about something nobody looked at",
    },
    "memoria": {
        "es": "Memoria / RAG", "en": "Memory / RAG", "min_tier": "chico", "capacidad": EMBEDDINGS,
        "porque_es": "buscar por significado necesita vectores, y eso lo hace un modelo de embeddings",
        "porque_en": "semantic search needs vectors, and that's what an embeddings model produces",
    },
    "agentes": {
        "es": "Correr tus agentes", "en": "Run your agents", "min_tier": "medio", "capacidad": None,
        "porque_es": "un agente encadena herramientas: un modelo chico se pierde en la segunda",
        "porque_en": "an agent chains tools: a small model gets lost on the second one",
    },
    "codigo": {
        "es": "Escribir código", "en": "Write code", "min_tier": "medio", "capacidad": CODIGO,
        "porque_es": "código que no compila cuesta más caro que no tenerlo",
        "porque_en": "code that doesn't compile costs more than no code at all",
    },
    "chat": {
        "es": "Conversar", "en": "Chat", "min_tier": "chico", "capacidad": None,
        "porque_es": "cualquier modelo sirve para conversar",
        "porque_en": "any model can hold a conversation",
    },
}


def tier_alcanza(tier: Optional[str], minimo: str) -> bool:
    """¿`tier` llega al mínimo? Un tier desconocido NO alcanza (fail-closed)."""
    if tier not in TIER_IDX or minimo not in TIER_IDX:
        return False
    return TIER_IDX[tier] >= TIER_IDX[minimo]


def tier_por_peso(gb: float, params_b: Optional[float] = None) -> str:
    """Tier estimado de un modelo LOCAL. Heurística DECLARADA (no una medición):
    los parámetros mandan si los sabemos; si no, el peso del archivo es la proxy."""
    if params_b:
        if params_b < 4:
            return "chico"
        if params_b < 15:
            return "medio"
        return "grande"          # un local nunca se declara frontier: sería una promesa
    if gb < 2.5:
        return "chico"
    if gb < 9:
        return "medio"
    return "grande"


# ══════════════════════════════════════════════════════════════════════════════════
# §3 · TU MÁQUINA  ·  disco, RAM y qué runtimes hay de verdad
# ══════════════════════════════════════════════════════════════════════════════════
GB = 1024.0 ** 3

#: Overhead sobre el peso del archivo: contexto + KV cache + el propio runtime.
#: Heurística DECLARADA, calibrada contra modelos GGUF cuantizados corriendo en ollama.
RAM_FACTOR = 1.15
RAM_BASE_GB = 0.7

_OLLAMA_URL = os.environ.get("PUPPET_OLLAMA_URL", "http://127.0.0.1:11434")
_OLLAMA_BINS = ("ollama", "/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/usr/bin/ollama")


def modelos_dir() -> Path:
    """Donde viven las descargas. Área ESCRIBIBLE del runtime (jamás `_MEIPASS`)."""
    d = _ap.data_root() / "modelos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifiesto_path() -> Path:
    return modelos_dir() / "manifiesto.json"


def _manifiesto() -> dict:
    try:
        return json.loads(_manifiesto_path().read_text("utf-8"))
    except Exception:
        return {}


def _guardar_manifiesto(m: dict) -> None:
    tmp = _manifiesto_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(_manifiesto_path())


def _ram_total_gb() -> Optional[float]:
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / GB
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=4)
            return int(out.stdout.strip()) / GB
    except Exception:
        pass
    return None


def _ram_libre_gb() -> Optional[float]:
    """RAM realmente disponible. En macOS «free» miente (el SO usa todo lo que puede):
    lo honesto es free + inactive + speculative, que es lo que el SO puede ceder."""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=4).stdout
            page = 4096
            m = re.search(r"page size of (\d+) bytes", out)
            if m:
                page = int(m.group(1))
            vals = dict(re.findall(r"^(.+?):\s+(\d+)\.", out, re.M))
            libres = sum(int(vals.get(k, 0)) for k in
                         ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
            return (libres * page) / GB
        except Exception:
            return None
    try:
        txt = Path("/proc/meminfo").read_text()
        m = re.search(r"^MemAvailable:\s+(\d+) kB", txt, re.M)
        if m:
            return int(m.group(1)) * 1024 / GB
    except Exception:
        pass
    return None


def _ollama_bin() -> Optional[str]:
    for b in _OLLAMA_BINS:
        p = shutil.which(b) if "/" not in b else (b if os.path.exists(b) else None)
        if p:
            return p
    return None


# ══ EL TRADUCTOR Y LA COLA (Gate 2 · F5) ══════════════════════════════════════════
# Imports PEREZOSOS y a prueba de ausencia: este archivo tiene que poder importarse en un
# test que no arrastre `platform/assembler`. Si el traductor no está, cada camino cae al
# comportamiento de antes de F5 — nunca a una excepción.
def _traductor():
    try:
        import errores_modelo as _e                        # type: ignore
        return _e
    except ImportError:
        asm = Path(__file__).resolve().parents[4] / "platform" / "assembler"
        if str(asm) not in sys.path:
            sys.path.insert(0, str(asm))
        try:
            import errores_modelo as _e                    # type: ignore
            return _e
        except ImportError:
            return None


def _cola():
    try:
        import cola_local as _c                            # type: ignore
        return _c
    except ImportError:
        asm = Path(__file__).resolve().parents[4] / "platform" / "assembler"
        if str(asm) not in sys.path:
            sys.path.insert(0, str(asm))
        try:
            import cola_local as _c                        # type: ignore
            return _c
        except ImportError:
            return None


class _ColaLlena(RuntimeError):
    """Espejo local de `cola_local.SinTurnoLocal`, para poder hacer `except` sin importar
    el módulo en el cuerpo de la función."""


def _causa_ollama(obj: Any, *, consultar_vivo: bool = False) -> Optional[dict]:
    """Fallo del runtime → `CausaModelo` serializada, vía el traductor de F1/F1b/F5.

    `consultar_vivo=True` (sólo para timeouts) pregunta `/api/version` ANTES de clasificar:
    es lo que separa «Ollama está apagado» de «Ollama está ocupado». Se consulta, no se
    supone, y por eso cuesta hasta 3 s — que al lado de un timeout de 120-180 s no es nada.
    """
    tr = _traductor()
    if tr is None:
        return None
    vivo = None
    if consultar_vivo:
        try:
            vivo, _ = _ollama_vivo()
        except Exception:                                  # noqa: BLE001
            vivo = None
    try:
        return tr.desde_ollama(obj, url=_OLLAMA_URL, runtime_vivo=vivo).como_dict()
    except Exception:                                      # noqa: BLE001 — jamás rompe la prueba
        return None


def _causa_cola(e: Exception) -> Optional[dict]:
    c = _cola()
    if c is None:
        return None
    try:
        return c.causa_de(e)
    except Exception:                                      # noqa: BLE001
        return None


def _turno_local():
    """Context manager del turno contra el runtime. Sin el módulo (o con la perilla en 0)
    es un no-op: el pedido sale directo, como antes de F5."""
    c = _cola()
    if c is None:
        class _Nada:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False
        return _Nada()
    cola, llena = c.COLA, c.SinTurnoLocal

    class _T:
        def __enter__(self_inner):
            try:
                cola.pedir()
            except llena as ex:
                # Se re-levanta como el espejo local para que `probar_local` pueda
                # atraparlo sin importar el módulo en su cuerpo.
                nueva = _ColaLlena(str(ex))
                nueva.motivo, nueva.activos = ex.motivo, ex.activos
                nueva.limite, nueva.esperado_s = ex.limite, ex.esperado_s
                raise nueva from ex
            return self_inner

        def __exit__(self_inner, *exc):
            cola.soltar()
            return False

    return _T()


# ══ VERSIÓN MÍNIMA DE OLLAMA (Gate 2 · F5 · obra 3) ═══════════════════════════════
# EL CRITERIO, escrito, porque un número sin criterio se vuelve folclore:
#
#   Aleph le pide a Ollama exactamente cuatro cosas, y las cuatro se usan en este archivo:
#     · `GET /api/version`          — saber si está vivo (y cuál es)
#     · `GET /api/tags`             — qué modelos hay instalados
#     · `POST /api/embed` con `input` — el camino de embeddings de `probar_local`
#     · `POST /v1/chat/completions` — el sobre OpenAI-compat, para chat y visión
#
#   `/api/embed` (plural `embeddings` en la respuesta, campo `input`) es el que fija el
#   piso: reemplazó a `/api/embeddings` (singular, campo `prompt`) en **0.3.4**. Con una
#   versión anterior, `probar_local` de un modelo de embedding falla con 404 y el usuario
#   ve «no tengo ese modelo» cuando lo que falta es el endpoint. El sobre OpenAI-compat
#   existe desde 0.1.24, así que no manda.
#
# 0.3.4 es un PISO, no una recomendación: la instalada acá es 0.24.0 y la auditoría 4
# midió que está 210 commits detrás de HEAD **con un cambio de motor en el medio** (Ollama
# dejó de tener runner propio de GGUF y ahora lanza `llama-server`). Eso NO se convierte en
# un mínimo más alto: sería inventar un requisito que no medimos contra una versión que no
# probamos. Se recomienda actualizar; no se bloquea.
OLLAMA_MINIMA = os.environ.get("PUPPET_OLLAMA_MINIMA", "0.3.4")
OLLAMA_MINIMA_PORQUE = ("`/api/embed` (campo `input`) existe desde 0.3.4; antes era "
                        "`/api/embeddings` con `prompt` y la prueba de un modelo de "
                        "embedding falla con 404")


def _version_tupla(v: str) -> Optional[tuple]:
    """'0.24.0' → (0, 24, 0). `None` si no parsea — y `None` NO significa vieja.

    Ollama puede devolver `0.0.0` en builds de desarrollo o un string con sufijo (`-rc1`).
    Se leen sólo los dígitos iniciales; lo que no parsea se declara desconocido y **no se
    trata como incumplimiento**: bloquear por no entender un número es peor que no chequear.
    """
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v or ""))
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def ollama_version_ok(version: str, minima: str = "") -> dict:
    """¿La versión instalada llega al piso? `{"ok", "version", "minima", "sabido", "mano"}`.

    `sabido=False` cuando no se pudo parsear: ahí `ok` es True (no se bloquea por no saber)
    pero queda dicho, que es la diferencia entre «cumple» y «no pude verificar».
    """
    minima = minima or OLLAMA_MINIMA
    hay, piso = _version_tupla(version), _version_tupla(minima)
    if hay is None or piso is None:
        return {"ok": True, "sabido": False, "version": str(version or ""), "minima": minima,
                "detalle": f"no pude interpretar la versión de Ollama ({version!r})"}
    if hay >= piso:
        return {"ok": True, "sabido": True, "version": str(version), "minima": minima,
                "detalle": f"Ollama v{str(version).lstrip('v')} (mínima {minima})"}
    return {
        "ok": False, "sabido": True, "version": str(version), "minima": minima,
        # ACCIONABLE, no un error mudo: qué pasa, por qué, y el comando exacto.
        "detalle": (f"tu Ollama es v{str(version).lstrip('v')} y Aleph necesita {minima} o superior — "
                    f"actualízalo y vuelve a probar"),
        "por_que": OLLAMA_MINIMA_PORQUE,
        "mano": {"comando": "brew upgrade ollama  # o: curl -fsSL https://ollama.com/install.sh | sh",
                 "doc": "https://ollama.com/download",
                 "por_que": OLLAMA_MINIMA_PORQUE},
    }


def _ollama_vivo() -> tuple[bool, str]:
    """¿El servidor de ollama contesta? Sin él no hay ejecución local por GGUF.

    El timeout de 3 s es corto A PROPÓSITO y ahora carga más peso que antes: F5 lo usa
    como el chequeo de liveness que distingue **apagado** de **ocupado**. Sirve para eso
    porque `/api/version` no pasa por el semáforo del runner (`llm/llama_server.go:922`):
    contesta al instante aunque haya un modelo generando hace veinte segundos.
    """
    try:
        with urllib.request.urlopen(_OLLAMA_URL + "/api/version", timeout=3) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return True, str(d.get("version") or "")
    except Exception as e:
        return False, str(e)


def _mlx_disponible() -> tuple[bool, str]:
    """¿Está el runtime MLX (el nativo de Apple Silicon)? Se mide buscando el módulo.

    ⚠️ ACÁ VIVÍA EL CUELGUE QUE DEJABA LA PANTALLA DE MODELOS VACÍA. La versión anterior
    hacía `subprocess.run([sys.executable, "-c", "import mlx_lm..."], timeout=20)`. En el
    artefacto CONGELADO `sys.executable` NO es un intérprete de Python: es el propio
    `aleph_sidecar`. O sea que ese probe nunca midió MLX — arrancaba un SEGUNDO Aleph
    entero, esperaba los 20 s del timeout y devolvía "no importable". Y como `maquina()`
    se llama varias veces por request, /v1/modelos tardaba 40 s (dos probes) y
    /v1/modelos/maquina hasta 400 s. El front aborta a los 30 s ⇒ pantalla vacía.

    (Es el mismo gotcha que qa/lib/frozen_guard.mjs documenta del otro lado: el bootloader
    de PyInstaller forkea, así que matar al hijo por timeout no cierra sus pipes.)

    `find_spec` responde en microsegundos, no arranca nada y mide exactamente lo mismo:
    si el módulo se puede resolver, el runtime está.
    """
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False, "MLX sólo corre en Apple Silicon"
    try:
        import importlib.util
        if importlib.util.find_spec("mlx_lm") is None:
            return False, "mlx_lm no está instalado"
        if importlib.util.find_spec("mlx") is None:
            return False, "falta mlx (el core)"
        return True, "mlx_lm importable"
    except Exception as e:
        return False, str(e)


def formatos_preferidos() -> list[str]:
    """Mac (Apple Silicon) → MLX primero, GGUF después. Cualquier otra → GGUF.

    Es la preferencia por PLATAFORMA (qué formato es nativo), no por lo que hay instalado:
    ver `formato_por_defecto()`, que es la otra mitad."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return ["mlx", "gguf"]
    return ["gguf"]


def runtime_de(formato: str, maq: Optional[dict] = None) -> dict:
    """El runtime que corre ESE formato, con su estado real."""
    maq = maq or maquina()
    return maq["runtimes"]["mlx" if formato == "mlx" else "ollama"]


def formato_por_defecto(maq: Optional[dict] = None) -> str:
    """EL FORMATO EN EL QUE ARRANCA LA PANTALLA.

    «MLX primero» es cierto y se respeta: MLX encabeza la lista y se ofrece. Pero arrancar
    en un formato cuyo runtime NO está instalado manda a alguien a bajar un modelo que no
    va a poder correr — el mismo pecado que «no entra», con otra cara. Así que el DEFAULT
    es el primer formato preferido que además tenga con qué correrse; si ninguno lo tiene,
    vuelve al primero preferido y la pantalla dice, arriba de todo, qué falta instalar."""
    maq = maq or maquina()
    for f in maq["formatos"]:
        if runtime_de(f, maq)["vivo"]:
            return f
    return (maq["formatos"] or ["gguf"])[0]


#: `maquina()` mide disco, RAM, ollama y MLX — cuatro cosas que cambian en minutos, no en
#: milisegundos, y que UNA sola pantalla pedía varias veces por request. Snapshot con TTL
#: corto: barato de repetir, y sigue siendo una medición, no una declaración.
_MAQ_TTL_S = 15.0
_maq_cache: tuple[float, dict] | None = None


def maquina(*, fresco: bool = False) -> dict:
    global _maq_cache
    if not fresco and _maq_cache is not None and (time.time() - _maq_cache[0]) < _MAQ_TTL_S:
        return _maq_cache[1]
    m = _maquina_medida()
    _maq_cache = (time.time(), m)
    return m


def _maquina_medida() -> dict:
    """EL VEREDICTO NECESITA UNA MÁQUINA. Todo medido, nada declarado."""
    d = modelos_dir()
    try:
        du = shutil.disk_usage(str(d))
        disco_libre, disco_total = du.free / GB, du.total / GB
    except Exception:
        disco_libre = disco_total = None
    ovivo, over = _ollama_vivo()
    obin = _ollama_bin()
    mlx_ok, mlx_det = _mlx_disponible()
    return {
        "plataforma": sys.platform,
        "arquitectura": platform.machine(),
        "disco_libre_gb": round(disco_libre, 2) if disco_libre is not None else None,
        "disco_total_gb": round(disco_total, 2) if disco_total is not None else None,
        "ram_total_gb": (lambda x: round(x, 2) if x else None)(_ram_total_gb()),
        "ram_libre_gb": (lambda x: round(x, 2) if x else None)(_ram_libre_gb()),
        "formatos": formatos_preferidos(),
        "runtimes": {
            # F5 · obra 3: la card ya no dice sólo «vivo». Si la versión está por debajo del
            # piso lo DICE, con el comando para arreglarlo — un runtime viejo que falla
            # después con un 404 críptico es exactamente el fallo mudo que el contrato del
            # repo prohíbe. `version_ok` va sólo cuando está vivo: preguntarle la versión a
            # algo que no contesta no tiene sentido.
            "ollama": {"presente": bool(obin), "vivo": ovivo,
                       "detalle": over if not ovivo else ("v" + over),
                       "bin": obin, "formatos": ["gguf"],
                       "version": over if ovivo else None,
                       "version_ok": (ollama_version_ok(over) if ovivo else None),
                       "mano": {"comando": "brew install ollama && ollama serve",
                                "doc": "https://ollama.com/download",
                                "por_que": "es el runtime que corre modelos GGUF en tu máquina"}},
            "mlx": {"presente": mlx_ok, "vivo": mlx_ok, "detalle": mlx_det, "formatos": ["mlx"],
                    "mano": {"comando": f"{Path(sys.executable).name} -m pip install mlx-lm",
                             "doc": "https://github.com/ml-explore/mlx-lm",
                             "por_que": "MLX es el runtime nativo de Apple Silicon; sin él, un modelo MLX se descarga pero no corre"}},
        },
        "carpeta": str(d),
        "ts": time.time(),
    }


def _con_default(maq: dict) -> dict:
    """maquina() + el formato en el que arranca la pantalla (se calcula aparte porque
    `formato_por_defecto` necesita la máquina ya medida)."""
    maq["formato_default"] = formato_por_defecto(maq)
    maq["formatos_corribles"] = [f for f in maq["formatos"] if runtime_de(f, maq)["vivo"]]
    return maq


def veredicto(peso_gb: Optional[float], maq: Optional[dict] = None) -> dict:
    """¿ENTRA EN ESTA MÁQUINA? Tres respuestas, ninguna vaga, y el faltante EXACTO.

      cómodo  — entra en disco y la RAM le sobra
      justo   — entra, pero la RAM queda al filo: va a andar lento
      no_entra— falta disco o falta RAM, y se dice CUÁNTO falta
    """
    maq = maq or maquina()
    if not peso_gb or peso_gb <= 0:
        return {"veredicto": "desconocido", "es": "No sé cuánto pesa", "en": "Unknown size",
                "falta_gb": None, "ram_pedida_gb": None}
    ram_ped = round(peso_gb * RAM_FACTOR + RAM_BASE_GB, 2)
    disco = maq.get("disco_libre_gb")
    ram = maq.get("ram_libre_gb") or maq.get("ram_total_gb")

    if disco is not None and peso_gb > disco:
        falta = round(peso_gb - disco, 2)
        return {"veredicto": "no_entra", "razon": "disco", "falta_gb": falta,
                "ram_pedida_gb": ram_ped,
                "es": f"No entra: te faltan {falta} GB de disco",
                "en": f"Doesn't fit: you're {falta} GB short on disk"}
    if ram is not None and ram_ped > ram:
        falta = round(ram_ped - ram, 2)
        return {"veredicto": "no_entra", "razon": "ram", "falta_gb": falta,
                "ram_pedida_gb": ram_ped,
                "es": f"No entra: te faltan {falta} GB de RAM · pide {ram_ped}, tienes {round(ram, 2)}",
                "en": f"Doesn't fit: {falta} GB RAM short · needs {ram_ped}, you have {round(ram, 2)}"}
    if ram is not None and ram_ped > ram * 0.6:
        return {"veredicto": "justo", "razon": "ram", "falta_gb": 0.0, "ram_pedida_gb": ram_ped,
                "es": "Entra justo — va a andar lento",
                "en": "Fits, barely — it's going to be slow"}
    return {"veredicto": "comodo", "razon": None, "falta_gb": 0.0, "ram_pedida_gb": ram_ped,
            "es": "Entra cómodo", "en": "Fits comfortably"}


# ══════════════════════════════════════════════════════════════════════════════════
# §4 · HUGGING FACE EN VIVO
# ══════════════════════════════════════════════════════════════════════════════════
_HF_API = os.environ.get("PUPPET_HF_API", "https://huggingface.co")
_HF_TIMEOUT = float(os.environ.get("PUPPET_HF_TIMEOUT", "18"))
_HF_LIMIT = int(os.environ.get("PUPPET_HF_LIMIT", "30"))
_HF_TTL = float(os.environ.get("PUPPET_HF_TTL", "600"))
_hf_cache: dict[str, tuple[float, Any]] = {}

#: Higiene del listado, NO censura de catálogo: lo que se le OFRECE a alguien que entra a
#: elegir su primer modelo no puede ser el top de fine-tunes «uncensored/abliterated» que
#: hoy domina el trending de GGUF. Son marcadores de la variante, no nombres de modelo
#: (por eso no expiran como expiraría una lista horneada). Se declara en el informe.
_RUIDO = re.compile(
    r"(uncensored|abliterat|heretic|nsfw|erp\b|roleplay|waifu|horny|smut|degenerate)",
    re.I)


def _hf_get(path: str, params: list[tuple[str, str]]) -> Any:
    """GET a la API pública de HF. Sin token: es pública y así queda claro que no
    mandamos nada del usuario. Sin red → excepción, que el caller convierte en FALLO
    VISIBLE (jamás una lista vacía fingida)."""
    qs = urllib.parse.urlencode(params, doseq=True)
    url = f"{_HF_API}{path}?{qs}" if qs else f"{_HF_API}{path}"
    hit = _hf_cache.get(url)
    if hit and time.time() - hit[0] < _HF_TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Aleph/1.0 (+centro-de-modelos)",
    })
    with urllib.request.urlopen(req, timeout=_HF_TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8", "replace") or "null")
    _hf_cache[url] = (time.time(), d)
    return d


_PARAMS_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[bB](?![\w])")
_QUANT_RE = re.compile(r"(Q\d+_[A-Z0-9_]+|IQ\d+_[A-Z]+|\d+bit|f16|bf16|q8_0)", re.I)


def _params_b(model_id: str, info: Optional[dict] = None) -> Optional[float]:
    """Parámetros en miles de millones. Del metadato si está; del nombre si no."""
    if info:
        st = info.get("safetensors") or {}
        tot = st.get("total")
        if isinstance(tot, (int, float)) and tot > 0:
            return round(tot / 1e9, 2)
    m = _PARAMS_RE.search(model_id.split("/")[-1])
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


#: Lo que NO se baja nunca: no lo necesita ningún runtime y son los archivos donde un
#: repo puede esconder cualquier cosa. Bajar sólo lo que hace falta también es higiene.
_NO_BAJAR = re.compile(r"(^|/)(\.gitattributes|README\.md|LICENSE|\.md$|\.png$|\.jpg$|\.gif$)", re.I)


def _archivos_de(siblings: list[dict], formato: str) -> list[dict]:
    """LOS ARCHIVOS QUE HAY QUE BAJAR — en plural, porque MLX no es un archivo.

    GGUF: UN archivo (el cuantizado que mejor cambia tamaño por calidad — Q4 si está).
    MLX:  EL REPO. Un `.safetensors` suelto no corre: sin `config.json` ni el tokenizer,
          mlx_lm no puede ni cargarlo. Bajar «el archivo más grande» habría dejado 3 GB
          en el disco que no sirven para nada — la peor forma de fallar, porque parece que
          funcionó."""
    utiles = [s for s in siblings if s.get("rfilename") and not _NO_BAJAR.search(str(s["rfilename"]))]
    if formato == "gguf":
        ggufs = [s for s in utiles
                 if str(s["rfilename"]).lower().endswith(".gguf")
                 and "-of-" not in str(s["rfilename"])]      # sin splits: otro cuento
        if not ggufs:
            return []
        con_tam = [s for s in ggufs if isinstance(s.get("size"), int) and s["size"] > 0]
        pool = con_tam or ggufs
        q4 = [s for s in pool if re.search(r"q4", str(s["rfilename"]), re.I)]
        return [min(q4 or pool, key=lambda s: s.get("size") or float("inf"))]
    # MLX: pesos + config + tokenizer. Si no hay safetensors no hay modelo.
    if not any(str(s["rfilename"]).endswith(".safetensors") for s in utiles):
        return []
    return [s for s in utiles if "/" not in str(s["rfilename"])]      # sólo la raíz del repo


def _elegir_archivo(siblings: list[dict], formato: str) -> Optional[dict]:
    """El archivo ANCLA (el que da nombre y peso). Para GGUF es el único; para MLX, el
    safetensors mayor."""
    arch = _archivos_de(siblings, formato)
    if not arch:
        return None
    if formato == "gguf":
        return arch[0]
    sts = [s for s in arch if str(s["rfilename"]).endswith(".safetensors")]
    return max(sts or arch, key=lambda s: s.get("size") or 0)


def _peso_gb(info: dict, formato: str, archivo: Optional[dict]) -> Optional[float]:
    """Cuánto ocupa DE VERDAD. GGUF = ese archivo. MLX = la suma de los pesos."""
    sib = info.get("siblings") or []
    if formato == "gguf":
        if archivo and isinstance(archivo.get("size"), int):
            return round(archivo["size"] / GB, 2)
        return None
    total = sum(s.get("size") or 0 for s in sib
                if str(s.get("rfilename", "")).endswith(".safetensors"))
    if total:
        return round(total / GB, 2)
    us = info.get("usedStorage")
    return round(us / GB, 2) if isinstance(us, (int, float)) and us else None


def catalogo_hf(categoria: str, formato: Optional[str] = None, limite: int = 8) -> dict:
    """EL CATÁLOGO VIVO. Consulta la API pública por categoría y devuelve candidatos con
    peso REAL y veredicto contra ESTA máquina.

    Contrato de honestidad: si no hay red, esto LEVANTA (`red: False` + causa) — nunca
    devuelve [] como si el mundo estuviera vacío. Lo YA descargado lo sirve otro endpoint,
    que no depende de la red, y por eso la pantalla nunca queda muda.
    """
    cat = CATEGORIAS_POR_ID.get(categoria)
    if not cat:
        raise HTTPException(status_code=400, detail=f"categoría desconocida: {categoria!r}")
    maq = maquina()
    formato = formato or (maq["formatos"][0] if maq["formatos"] else "gguf")
    if formato not in ("gguf", "mlx"):
        raise HTTPException(status_code=400, detail=f"formato desconocido: {formato!r}")

    params: list[tuple[str, str]] = [
        ("sort", "trendingScore"), ("direction", "-1"), ("limit", str(_HF_LIMIT)),
    ]
    filtros = list(cat["hf"].get("filter") or [])
    filtros.append(formato)              # el FORMATO es un tag de HF (gguf · mlx)
    for f in filtros:
        params.append(("filter", f))
    if cat["hf"].get("pipeline_tag"):
        params.append(("pipeline_tag", cat["hf"]["pipeline_tag"]))

    t0 = time.perf_counter()
    try:
        crudo = _hf_get("/api/models", params)
    except Exception as e:
        return {"red": False, "categoria": categoria, "formato": formato,
                "causa": MV.SIN_RED if isinstance(e, (urllib.error.URLError, OSError)) else MV.ERROR_UPSTREAM,
                "detalle": f"no pude consultar el catálogo de Hugging Face: {e}",
                "modelos": [], "maquina": maq, "ts": time.time()}
    ms = int((time.perf_counter() - t0) * 1000)

    fuera_ruido = 0
    out: list[dict] = []
    for m in (crudo or []):
        mid = str(m.get("id") or m.get("modelId") or "")
        if not mid or m.get("private") or m.get("gated"):
            continue
        if _RUIDO.search(mid):
            fuera_ruido += 1
            continue
        out.append({"id": mid, "trending": m.get("trendingScore"),
                    "descargas": m.get("downloads"), "likes": m.get("likes"),
                    "tags": m.get("tags") or []})
        if len(out) >= max(limite * 3, limite):
            break

    # El peso REAL exige el detalle del repo (un GET por modelo). Se pide sólo para los
    # que van a salir en pantalla — pedir 30 detalles para mostrar 6 es tirar la red.
    detallados: list[dict] = []
    for cand in out:
        if len(detallados) >= limite:
            break
        try:
            info = _hf_get(f"/api/models/{cand['id']}", [("blobs", "true")])
        except Exception:
            continue
        sib = info.get("siblings") or []
        archivos = _archivos_de(sib, formato)
        arch = _elegir_archivo(sib, formato)
        if not archivos or not arch:
            continue                            # sin archivos que bajar, no se ofrece
        peso = _peso_gb(info, formato, arch)
        maxgb = cat.get("max_gb")
        if maxgb and peso and peso > maxgb:
            continue
        pb = _params_b(cand["id"], info)
        ver = veredicto(peso, maq)
        detallados.append({
            "id": cand["id"],
            "org": cand["id"].split("/")[0],
            "nombre": cand["id"].split("/")[-1],
            "formato": formato,
            "archivo": (arch or {}).get("rfilename"),
            "archivos": [s["rfilename"] for s in archivos],
            "cuantizacion": (lambda m: m.group(0) if m else None)(
                _QUANT_RE.search(str((arch or {}).get("rfilename") or ""))),
            "peso_gb": peso,
            "params_b": pb,
            "tier": tier_por_peso(peso or 0, pb),
            "categoria": categoria,
            "trending": cand["trending"], "descargas": cand["descargas"], "likes": cand["likes"],
            "licencia": next((t.split(":", 1)[1] for t in (info.get("tags") or [])
                              if str(t).startswith("license:")), None),
            "veredicto": ver,
            "url": f"https://huggingface.co/{cand['id']}",
        })

    detallados.sort(key=lambda d: (d["veredicto"]["veredicto"] == "no_entra",
                                   -(d.get("trending") or 0)))
    return {"red": True, "categoria": categoria, "formato": formato, "ms": ms,
            "modelos": detallados, "fuera_por_ruido": fuera_ruido,
            "maquina": maq, "ts": time.time()}


# ══════════════════════════════════════════════════════════════════════════════════
# §5 · LO QUE YA TENÉS  ·  inventario local (nunca depende de la red)
# ══════════════════════════════════════════════════════════════════════════════════
def _ollama_tags() -> list[dict]:
    try:
        with urllib.request.urlopen(_OLLAMA_URL + "/api/tags", timeout=4) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return list(d.get("models") or [])
    except Exception:
        return []


def _tag_norm(t: Optional[str]) -> str:
    """`aleph-x` y `aleph-x:latest` son EL MISMO modelo. ollama devuelve siempre la forma
    con tag explícito; nosotros guardamos la corta. Sin normalizar, el inventario listaba
    el modelo dos veces —una como nuestro y otra como «preexistente»— que es la clase de
    duplicado que hace dudar de toda la pantalla."""
    t = str(t or "")
    return t[:-7] if t.endswith(":latest") else t


def _avatar_cacheado(hf_id: Optional[str]) -> bool:
    """¿Tenemos la cara de esa organización en el cache? El front lo necesita para NO
    pedir un `<img>` que va a dar 404: un 404 por diseño sigue siendo ruido en la consola,
    y el ruido tapa señal. Sin cache se dibuja `serviceFace` directamente."""
    org = str(hf_id or "").split("/")[0]
    if not org:
        return False
    return (modelos_dir() / "avatares" / f"{org}.png").exists()


def instalados() -> dict:
    """Inventario REAL de lo local. Se arma de dos fuentes que viven en tu máquina:
    el manifiesto de lo que bajamos nosotros y lo que ollama tiene registrado. Cero red
    externa → esta lista existe SIEMPRE, aunque el mundo se caiga (calibración #1)."""
    man = _manifiesto()
    tags = {_tag_norm(m.get("name")): m for m in _ollama_tags()}
    filas = []
    for slug, e in sorted(man.items()):
        ruta = e.get("ruta")
        en_disco = bool(ruta and Path(ruta).exists())
        tag = _tag_norm(e.get("ollama_tag"))
        filas.append({
            "slug": slug, "hf_id": e.get("hf_id"), "formato": e.get("formato"),
            "archivo": e.get("archivo"), "peso_gb": e.get("peso_gb"), "tier": e.get("tier"),
            "categoria": e.get("categoria"), "ollama_tag": tag or None,
            "en_ollama": bool(tag and tag in tags),
            "en_disco": en_disco, "ruta": ruta if en_disco else None,
            "avatar": _avatar_cacheado(e.get("hf_id")),
            "estado": e.get("estado") or DETECTADO, "causa": e.get("causa"),
            "prueba": e.get("prueba"), "ts": e.get("ts"),
        })
    # Modelos que ya estaban en ollama antes de Aleph: son tuyos igual, se listan.
    conocidos = {f.get("ollama_tag") for f in filas}
    for name, m in sorted(tags.items()):
        if name in conocidos:
            continue
        gb = round((m.get("size") or 0) / GB, 2)
        det = m.get("details") or {}
        ps = str(det.get("parameter_size") or "")
        pb = None
        mm = _PARAMS_RE.search(ps)
        if mm:
            try:
                pb = float(mm.group(1))
            except ValueError:
                pb = None
        filas.append({
            "slug": "ollama:" + name, "hf_id": None, "formato": det.get("format") or "gguf",
            "archivo": None, "peso_gb": gb, "tier": tier_por_peso(gb, pb),
            "categoria": None, "ollama_tag": name, "en_ollama": True, "en_disco": True,
            "ruta": None, "estado": DETECTADO, "causa": None, "prueba": None,
            "ts": None, "preexistente": True, "avatar": False,
        })
    return {"modelos": filas, "maquina": maquina(), "ts": time.time()}


# ══════════════════════════════════════════════════════════════════════════════════
# §6 · LA DESCARGA GUIADA  ·  progreso real, cancelable, y que LIMPIA
# ══════════════════════════════════════════════════════════════════════════════════
_CHUNK = 1024 * 512
_DL_TIMEOUT = float(os.environ.get("PUPPET_DL_TIMEOUT", "60"))


class Descarga:
    """UN trabajo de descarga. Vive en memoria del sidecar; su archivo, en disco.

    Cancelar NO es «dejar de mirar»: corta el stream, borra el `.part` y deja el disco
    como estaba. Un cancel que deja 400 MB tirados es el bug que estamos matando."""

    def __init__(self, slug: str, hf_id: str, archivo: str, formato: str,
                 categoria: Optional[str], peso_gb: Optional[float], tier: Optional[str],
                 archivos: Optional[list[str]] = None):
        self.slug = slug
        self.hf_id = hf_id
        self.archivo = archivo
        self.archivos = list(archivos or [archivo])
        self.formato = formato
        self.categoria = categoria
        self.peso_gb = peso_gb
        self.tier = tier
        self.cancelar = threading.Event()
        self.bytes = 0
        self.total = 0
        self.estado = "pendiente"
        self.causa: Optional[str] = None
        self.detalle = ""
        self.t0 = time.time()
        self.latido = time.time()
        self.destino: Optional[Path] = None
        self.carpeta: Optional[Path] = None
        self.parcial: Optional[Path] = None
        self.descarga_completa = False

    # "descargado" NO es terminal: todavía faltan instalar y probar de verdad.
    TERMINALES = frozenset({"cancelado", ROTO, PROBADO, DETECTADO})

    @property
    def viva(self) -> bool:
        """¿Este trabajo sigue de verdad en vuelo? Un trabajo cuyo consumidor se fue (el
        browser cortó el cable) queda SUSPENDIDO en su `yield` y su estado nunca avanza:
        preguntar sólo por `estado == "descargando"` lo deja «vivo» para siempre y bloquea
        el próximo intento con un 409 que nadie pidió. Se mide también el LATIDO."""
        if self.estado in Descarga.TERMINALES:
            return False
        return (time.time() - self.latido) < 15.0

    def instantanea(self) -> dict:
        self.latido = time.time()
        return self._foto()

    def _foto(self) -> dict:
        dt = max(0.001, time.time() - self.t0)
        vel = self.bytes / dt
        resta = (self.total - self.bytes) if self.total else 0
        return {
            "slug": self.slug, "hf_id": self.hf_id, "archivo": self.archivo,
            "estado": self.estado, "causa": self.causa, "detalle": self.detalle,
            "bytes": self.bytes, "total": self.total,
            "mb": round(self.bytes / 1024 / 1024, 1),
            "mb_total": round(self.total / 1024 / 1024, 1) if self.total else None,
            "pct": round(100.0 * self.bytes / self.total, 1) if self.total else None,
            "mbps": round(vel / 1024 / 1024, 2),
            "restante_s": int(resta / vel) if (vel > 0 and resta > 0) else None,
            "ts": time.time(),
        }


_trabajos: dict[str, Descarga] = {}
_lock = threading.Lock()


def slug_de(hf_id: str, archivo: Optional[str] = None) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", f"{hf_id}").strip("-").lower()
    return base[:80]


def _url_hf(hf_id: str, archivo: str) -> str:
    return f"{_HF_API}/{hf_id}/resolve/main/{urllib.parse.quote(archivo)}?download=true"


def descargar(job: Descarga) -> Iterator[dict]:
    """Envoltorio con TERMINACIÓN GARANTIZADA — ver `_descargar` para el trabajo real.

    Si el browser corta el cable a mitad, este generador queda suspendido en su `yield` y
    nunca vuelve: sin este `finally`, el trabajo se quedaba en «descargando» PARA SIEMPRE y
    el próximo intento chocaba contra un 409 fantasma. Lo cazó la vara colgada 7 minutos
    esperando un desenlace que ya no iba a llegar."""
    try:
        yield from _descargar(job)
    except GeneratorExit:
        job.cancelar.set()
        if job.estado not in Descarga.TERMINALES:
            job.estado = "cancelado"
            job.causa = DESCARGA_CANCELADA
            job.detalle = "el cable se cortó del lado del cliente"
        raise
    finally:
        if job.estado not in Descarga.TERMINALES:
            job.estado = "cancelado"
            job.causa = DESCARGA_CANCELADA
            job.detalle = job.detalle or "la descarga terminó sin desenlace"
        # GeneratorExit puede entrar justo en un `yield progreso`, por fuera del
        # except _Cancelado de `_descargar`. La limpieza vive también en este borde.
        if not job.descarga_completa and job.carpeta is not None:
            _limpiar(job.parcial, job.carpeta)


def _descargar(job: Descarga) -> Iterator[dict]:
    """Baja el modelo y VA CONTANDO. Generador: cada yield es un evento para el SSE.

    DOS precondiciones DURAS, las dos ANTES de bajar un solo byte:
      1. que entre en el disco — bajar 380 MB para morir sin espacio a los 9/10 es la peor
         forma de decir «no entra»;
      2. que HAYA con qué correrlo — bajar un modelo MLX en una máquina sin mlx_lm deja
         3 GB en el disco que no sirven para nada, y lo descubrís al final. Es el mismo
         pecado con otra cara, y lo cazó la vara: la primera corrida se colgó justo ahí.
    """
    maq = maquina()
    ver = veredicto(job.peso_gb, maq)
    yield {"tipo": "veredicto", "veredicto": ver}
    if ver["veredicto"] == "no_entra":
        job.estado = ROTO
        job.causa = SIN_ESPACIO
        job.detalle = ver["es"]
        yield {"tipo": "fin", **job.instantanea()}
        return

    rt = runtime_de(job.formato, maq)
    if not rt["vivo"]:
        job.estado = ROTO
        job.causa = SIN_RUNTIME
        job.detalle = (f"no hay con qué correr un modelo {job.formato.upper()} en esta máquina: "
                       + (rt["detalle"] or "el runtime no responde")
                       + ". No lo bajo para dejarlo muerto en tu disco.")
        yield {"tipo": "sin_runtime", "formato": job.formato, "mano": rt["mano"], "detalle": job.detalle}
        yield {"tipo": "fin", **job.instantanea(), "mano": rt["mano"]}
        return

    carpeta = modelos_dir() / job.slug
    carpeta.mkdir(parents=True, exist_ok=True)
    job.carpeta = carpeta
    destino = carpeta / Path(job.archivo).name
    job.destino = destino

    if destino.exists() and destino.stat().st_size > 0 and len(job.archivos) == 1:
        job.bytes = job.total = destino.stat().st_size
        job.descarga_completa = True
        job.estado = "descargado"
        yield {"tipo": "progreso", **job.instantanea(), "ya_estaba": True}
        # Ya bajado no significa conectado. Continúa por la MISMA instalación + prueba
        # automática; nunca termina amarillo ni verde prestado.
        yield from _instalar_y_probar(job)
        return

    # Peso total ANTES de empezar: sin él la barra saltaría al terminar cada archivo.
    job.total = 0
    cabezas = []
    for nombre in job.archivos:
        try:
            req = urllib.request.Request(_url_hf(job.hf_id, nombre), method="HEAD",
                                         headers={"User-Agent": "Aleph/1.0 (+centro-de-modelos)"})
            with urllib.request.urlopen(req, timeout=_DL_TIMEOUT) as r:
                n = int(r.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        cabezas.append((nombre, n))
        job.total += n

    job.estado = "descargando"
    job.t0 = time.time()
    yield {"tipo": "arranque", **job.instantanea(), "archivos": len(job.archivos)}
    parcial = None
    try:
        ultimo = 0.0
        for idx, (nombre, _n) in enumerate(cabezas):
            fin_arch = carpeta / Path(nombre).name
            if fin_arch.exists() and fin_arch.stat().st_size > 0:
                job.bytes += fin_arch.stat().st_size
                continue
            parcial = fin_arch.with_suffix(fin_arch.suffix + ".part")
            job.parcial = parcial
            req = urllib.request.Request(_url_hf(job.hf_id, nombre),
                                         headers={"User-Agent": "Aleph/1.0 (+centro-de-modelos)"})
            with urllib.request.urlopen(req, timeout=_DL_TIMEOUT) as r:
                with open(parcial, "wb") as fh:
                    while True:
                        if job.cancelar.is_set():
                            raise _Cancelado()
                        trozo = r.read(_CHUNK)
                        if not trozo:
                            break
                        fh.write(trozo)
                        job.bytes += len(trozo)
                        ahora = time.time()
                        if ahora - ultimo >= 0.4:
                            ultimo = ahora
                            yield {"tipo": "progreso", **job.instantanea(),
                                   "archivo_actual": Path(nombre).name,
                                   "de": idx + 1, "archivos": len(cabezas)}
            parcial.replace(fin_arch)
            parcial = None
            job.parcial = None
        job.descarga_completa = True
        job.estado = "descargado"
        yield {"tipo": "progreso", **job.instantanea()}
    except _Cancelado:
        job.estado = "cancelado"
        job.causa = DESCARGA_CANCELADA
        job.detalle = "lo cortaste tú"
        _limpiar(parcial, carpeta)
        job.parcial = None
        yield {"tipo": "fin", **job.instantanea(), "limpio": True}
        return
    except Exception as e:
        job.estado = ROTO
        job.causa = MV.SIN_RED if isinstance(e, (urllib.error.URLError, OSError)) else MV.ERROR_UPSTREAM
        job.detalle = f"la descarga se cortó: {e}"
        _limpiar(parcial, carpeta)
        job.parcial = None
        yield {"tipo": "fin", **job.instantanea(), "limpio": True}
        return

    yield from _instalar_y_probar(job)


def _instalar_y_probar(job: Descarga) -> Iterator[dict]:
    """Segunda mitad común: archivo nuevo o reutilizado terminan en la misma prueba."""
    # ── INSTALAR: un archivo bajado todavía no es un modelo que corre ──────────────
    yield {"tipo": "instalando", **job.instantanea()}
    inst = instalar(job)
    yield {"tipo": "instalado", **inst}
    if inst.get("estado") == ROTO:
        job.estado = ROTO
        job.causa = inst.get("causa")
        job.detalle = inst.get("detalle") or ""
        _anotar(job, inst, None)
        yield {"tipo": "fin", **job.instantanea()}
        return

    # ── LA PRUEBA AUTOMÁTICA MANDA: la salida de éxito es 🟢, no «descargado» ──────
    yield {"tipo": "probando", **job.instantanea()}
    _anotar(job, inst, None)          # el manifiesto ANTES de probar: probar_local lo lee
    pr = probar_local(job.slug, tag=inst.get("ollama_tag"), categoria=job.categoria)
    job.estado = pr["estado"]
    job.causa = pr.get("causa")
    job.detalle = pr.get("detalle") or ""
    _anotar(job, inst, pr)
    yield {"tipo": "prueba", **pr}
    yield {"tipo": "fin", **job.instantanea(), "prueba": pr}


class _Cancelado(Exception):
    pass


def _limpiar(parcial: Optional[Path], carpeta: Path) -> None:
    """CANCELAR LIMPIA — de verdad, y también cuando el modelo son varios archivos.

    Borra el `.part` en vuelo Y los archivos ya completos de una descarga que nunca
    terminó: un repo MLX a medio bajar (pesos sí, tokenizer no) es basura que ocupa disco
    y encima parece un modelo. Si la carpeta queda vacía, se va la carpeta."""
    try:
        if parcial is not None and parcial.exists():
            parcial.unlink()
    except Exception:
        pass
    try:
        if carpeta.exists() and carpeta.is_relative_to(modelos_dir()):
            for hijo in list(carpeta.iterdir()):
                try:
                    if hijo.is_file():
                        hijo.unlink()
                except Exception:
                    pass
            if not any(carpeta.iterdir()):
                carpeta.rmdir()
    except Exception:
        pass


def _anotar(job: Descarga, inst: dict, pr: Optional[dict]) -> None:
    m = _manifiesto()
    m[job.slug] = {
        "hf_id": job.hf_id, "archivo": job.archivo, "formato": job.formato,
        "categoria": job.categoria, "peso_gb": job.peso_gb, "tier": job.tier,
        "ruta": str(job.destino) if job.destino else None,
        "ollama_tag": inst.get("ollama_tag"), "mlx_dir": inst.get("mlx_dir"),
        "estado": (pr or {}).get("estado") or job.estado,
        "causa": (pr or {}).get("causa") or job.causa,
        "prueba": pr, "ts": time.time(),
    }
    _guardar_manifiesto(m)


# ══════════════════════════════════════════════════════════════════════════════════
# §7 · INSTALAR Y PROBAR  ·  un modelo sólo está 🟢 si CORRIÓ
# ══════════════════════════════════════════════════════════════════════════════════
def instalar(job: Descarga) -> dict:
    """Registra el archivo bajado en un runtime que exista de verdad.

    GGUF → ollama (`ollama create`). MLX → mlx_lm. Sin runtime NO se inventa uno: se
    devuelve `sin_runtime` con EL COMANDO exacto. Un modelo en disco que no puede correr
    es un estado real y merece su rótulo, no un verde prestado."""
    maq = maquina()
    if job.formato == "gguf":
        rt = maq["runtimes"]["ollama"]
        if not rt["presente"] or not rt["vivo"]:
            return {"estado": ROTO, "causa": SIN_RUNTIME, "ollama_tag": None,
                    "detalle": "el archivo está en tu disco, pero no hay runtime que lo corra: "
                               + ("ollama no está instalado" if not rt["presente"] else "ollama no está corriendo"),
                    "mano": rt["mano"]}
        tag = "aleph-" + job.slug[:40]
        modelfile = (job.destino.parent / "Modelfile")
        modelfile.write_text(f'FROM "{job.destino}"\n', "utf-8")
        try:
            out = subprocess.run([rt["bin"], "create", tag, "-f", str(modelfile)],
                                 capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return {"estado": ROTO, "causa": MV.TIMEOUT, "ollama_tag": None,
                    "detalle": "ollama tardó más de 10 minutos en registrar el modelo"}
        if out.returncode != 0:
            return {"estado": ROTO, "causa": MV.ERROR_UPSTREAM, "ollama_tag": None,
                    "detalle": (out.stderr or out.stdout or "").strip()[:400]}
        return {"estado": DETECTADO, "ollama_tag": tag, "causa": None,
                "detalle": f"registrado en ollama como {tag}",
                "evidencia": {"stdout": (out.stdout or "").strip()[:200]}}

    if job.formato == "mlx":
        rt = maq["runtimes"]["mlx"]
        if not rt["presente"]:
            return {"estado": ROTO, "causa": SIN_RUNTIME, "ollama_tag": None,
                    "detalle": "el modelo está en tu disco, pero falta el runtime MLX para correrlo",
                    "mano": rt["mano"]}
        # MLX no «registra»: corre el repo desde su carpeta. Lo que sí se comprueba es que
        # la carpeta esté COMPLETA — un repo sin config.json no carga, y decirlo acá es
        # mucho mejor que un traceback de mlx_lm dentro de la prueba.
        carpeta = job.destino.parent if job.destino else None
        faltan = [n for n in ("config.json",) if carpeta and not (carpeta / n).exists()]
        if faltan:
            return {"estado": ROTO, "causa": FORMATO_NO_SOPORTADO, "ollama_tag": None,
                    "detalle": f"el repo bajó incompleto: falta {', '.join(faltan)}"}
        return {"estado": DETECTADO, "ollama_tag": None, "causa": None,
                "mlx_dir": str(carpeta) if carpeta else None,
                "detalle": "MLX corre el repo desde su carpeta (sin registro previo)"}

    return {"estado": ROTO, "causa": FORMATO_NO_SOPORTADO, "ollama_tag": None,
            "detalle": f"no sé correr el formato {job.formato!r}"}


def _png_minimo(rgb: tuple[int, int, int] = (220, 20, 20), lado: int = 24) -> bytes:
    """Un PNG REAL de un color plano, construido a mano (stdlib pura: zlib + CRC).

    La prueba de un modelo de visión tiene que darle una imagen DE VERDAD. Traer Pillow
    para esto sería una dependencia nueva en el artefacto por 30 líneas de zlib."""
    fila = bytes([0]) + bytes(rgb) * lado
    crudo = fila * lado
    def _chunk(tipo: bytes, datos: bytes) -> bytes:
        c = tipo + datos
        return (len(datos).to_bytes(4, "big") + c + zlib.crc32(c).to_bytes(4, "big"))
    ihdr = lado.to_bytes(4, "big") + lado.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(crudo, 9)) + _chunk(b"IEND", b""))


# F5 · obra 2: EL TURNO SE TOMA ACÁ, no más arriba. Estos dos son los únicos puntos donde
# este archivo le habla al runtime, y el turno tiene que durar EXACTAMENTE lo que dura el
# request en vuelo: tomarlo antes (mientras se arma el payload) o soltarlo después (mientras
# se parsea el JSON) sería tener el runtime reservado sin estar usándolo.
def _ollama_chat(tag: str, mensajes: list[dict], timeout: float = 180.0) -> dict:
    body = json.dumps({"model": tag, "messages": mensajes, "stream": False,
                       "options": {"temperature": 0, "num_predict": 64}}).encode()
    req = urllib.request.Request(_OLLAMA_URL + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with _turno_local():
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")


def _ollama_embed(tag: str, texto: str, timeout: float = 120.0) -> dict:
    body = json.dumps({"model": tag, "input": texto}).encode()
    req = urllib.request.Request(_OLLAMA_URL + "/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    with _turno_local():
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")


_COLOR_OK = re.compile(r"\b(rojo|roja|red|crimson|scarlet|carmes)", re.I)


def probar_local(slug: str, *, tag: Optional[str] = None,
                 categoria: Optional[str] = None) -> dict:
    """LA PRUEBA AUTOMÁTICA. Corre el modelo de verdad y devuelve evidencia + timestamp.

    Por categoría:
      visión      → se le manda una IMAGEN mínima (roja) y se le pregunta el color.
      embeddings  → se le pide un vector y se comprueba que salga numérico y no vacío.
      resto       → una pregunta con UNA respuesta correcta (2+2) y se lee la respuesta.

    Tres desenlaces, ninguno mudo: 🟢 probado (con lo que contestó), 🟡 detectado
    (contestó pero no acertó — corre, pero no puedo firmar que sirva para eso), 🔴 roto.
    """
    man = _manifiesto()
    e = man.get(slug) or {}
    tag = tag or e.get("ollama_tag")
    categoria = categoria or e.get("categoria")
    cat = CATEGORIAS_POR_ID.get(categoria or "") or {}
    clase = cat.get("prueba", "texto")
    t0 = time.perf_counter()

    # ── MLX: no hay servidor; se corre el repo desde su carpeta con mlx_lm ────────
    if (e.get("formato") == "mlx") or (not tag and e.get("mlx_dir")):
        d = e.get("mlx_dir") or (str(Path(e["ruta"]).parent) if e.get("ruta") else None)
        rt = maquina()["runtimes"]["mlx"]
        if not rt["presente"]:
            return _res(slug, ROTO, causa=SIN_RUNTIME,
                        detalle="falta el runtime MLX para correrlo: " + rt["mano"]["comando"])
        if not d or not Path(d).exists():
            return _res(slug, ROTO, causa=SIN_RUNTIME, detalle="no encuentro la carpeta del modelo")
        try:
            out = subprocess.run(
                [sys.executable, "-m", "mlx_lm", "generate", "--model", d,
                 "--prompt", "¿Cuánto es 2+2? Contesta sólo el número.", "--max-tokens", "16"],
                capture_output=True, text=True, timeout=300)
            ms = int((time.perf_counter() - t0) * 1000)
            txt = (out.stdout or "").strip()
            if out.returncode != 0:
                return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM, ms=ms,
                            detalle=(out.stderr or "").strip().splitlines()[-1][:200] if out.stderr else "mlx_lm falló")
            if re.search(r"\b4\b|cuatro|four", txt, re.I):
                return _res(slug, PROBADO, ms=ms, detalle=f"corrió con MLX y contestó bien",
                            evidencia={"respuesta": txt[:300], "runtime": "mlx_lm", "carpeta": d})
            return _res(slug, DETECTADO, ms=ms, detalle="corrió con MLX pero no acertó la respuesta",
                        evidencia={"respuesta": txt[:300], "runtime": "mlx_lm"})
        except subprocess.TimeoutExpired:
            return _res(slug, ROTO, causa=MV.TIMEOUT, detalle="mlx_lm tardó más de 5 minutos")
        except Exception as ex:
            return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM, detalle=f"la prueba MLX falló: {ex}")

    if not tag:
        return _res(slug, ROTO, causa=SIN_RUNTIME,
                    detalle="no hay runtime donde correrlo (no quedó registrado en ollama)")
    vivo, ver = _ollama_vivo()
    if not vivo:
        return _res(slug, ROTO, causa=SIN_RUNTIME,
                    detalle=f"ollama no responde en {_OLLAMA_URL}: {ver}")

    try:
        if clase == "embedding":
            d = _ollama_embed(tag, "la prueba automática del Centro de Modelos")
            vec = (d.get("embeddings") or [[]])[0]
            ms = int((time.perf_counter() - t0) * 1000)
            if isinstance(vec, list) and len(vec) > 8 and all(isinstance(x, (int, float)) for x in vec[:8]):
                return _res(slug, PROBADO, ms=ms,
                            detalle=f"devolvió un vector de {len(vec)} dimensiones",
                            evidencia={"dimensiones": len(vec), "muestra": [round(float(x), 4) for x in vec[:4]],
                                       "modelo": tag})
            return _res(slug, DETECTADO, ms=ms, detalle="respondió, pero no devolvió un vector usable",
                        evidencia={"crudo": str(d)[:220]})

        if clase == "vision":
            import base64
            png = base64.b64encode(_png_minimo()).decode()
            d = _ollama_chat(tag, [{"role": "user", "content": [
                {"type": "text", "text": "¿De qué color es esta imagen? Contesta con UNA palabra."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}},
            ]}])
            txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            ms = int((time.perf_counter() - t0) * 1000)
            if _COLOR_OK.search(txt):
                return _res(slug, PROBADO, ms=ms, detalle=f"miró la imagen y dijo: «{txt[:60]}»",
                            evidencia={"respuesta": txt[:300], "prueba": "PNG 24×24 rojo", "modelo": tag})
            if txt:
                return _res(slug, DETECTADO, ms=ms,
                            detalle=f"aceptó la imagen y contestó «{txt[:40]}», pero no acertó el color",
                            evidencia={"respuesta": txt[:300], "esperado": "rojo", "modelo": tag})
            return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM, ms=ms,
                        detalle="aceptó la imagen pero devolvió una respuesta vacía")

        d = _ollama_chat(tag, [{"role": "user", "content": "¿Cuánto es 2+2? Contesta sólo el número."}])
        txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        ms = int((time.perf_counter() - t0) * 1000)
        if re.search(r"\b4\b|cuatro|four", txt, re.I):
            return _res(slug, PROBADO, ms=ms, detalle=f"corrió y contestó bien: «{txt[:60]}»",
                        evidencia={"pregunta": "2+2", "respuesta": txt[:300], "modelo": tag})
        if txt:
            return _res(slug, DETECTADO, ms=ms,
                        detalle=f"corrió y contestó «{txt[:40]}», que no es la respuesta",
                        evidencia={"pregunta": "2+2", "respuesta": txt[:300], "modelo": tag})
        return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM, ms=ms, detalle="contestó vacío")
    except urllib.error.HTTPError as ex:
        # El status Y EL CUERPO. `str(HTTPError)` es sólo «HTTP Error 400: Bad Request»: el
        # texto que distingue «contexto excedido» de un 400 cualquiera viaja en el cuerpo,
        # y el traductor lo necesita. Se le pasa la forma de dict, que es la que `desde_ollama`
        # sabe leer entera (nativa y OpenAI-compat).
        cuerpo = ""
        try:
            cuerpo = ex.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        payload: Any = {"status": ex.code, "error": cuerpo or str(ex)}
        try:
            payload = {"status": ex.code, **json.loads(cuerpo)} if cuerpo.strip().startswith("{") \
                else payload
        except (json.JSONDecodeError, ValueError):
            pass
        c = _causa_ollama(payload)
        if c is None:
            return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM,
                        detalle=f"el runtime devolvió HTTP {ex.code}: {cuerpo[:200]}")
        return _res(slug, ROTO, causa=c["causa"], detalle=c["detalle"],
                    evidencia={"causa_tipada": c})
    except _ColaLlena as ex:
        # F5 · obra 2: hay otro pedido corriendo contra el runtime. NO se espera mudo ni se
        # cuelga: se contesta con la causa tipada y su motivo.
        c = _causa_cola(ex) or {}
        return _res(slug, ROTO, causa=c.get("causa") or MV.TIMEOUT,
                    detalle=c.get("detalle") or "el runtime local está atendiendo otro pedido",
                    evidencia={"causa_tipada": c})
    except Exception as ex:
        # ── F5 · obra 1: LA CAUSA LA DA EL TRADUCTOR, NO ESTE ARCHIVO ────────────
        # Antes acá había dos líneas que se armaban la causa a mano —`MV.TIMEOUT` si era
        # TimeoutError, `MV.ERROR_UPSTREAM` para todo lo demás— y por eso la pantalla que
        # el usuario mira para elegir modelos no tenía NADA de F1b: ni el 404 que distingue
        # «no tenés ese modelo» de «no hay runtime», ni el contexto excedido, ni el OOM.
        # Ahora consume `desde_ollama`, que ya sabe leer los siete casos medidos.
        #
        # Y la distinción que motivó la fase: `runtime_vivo` se CONSULTA (no se supone).
        # `/api/version` contesta en 3 s aunque el modelo esté ocupado, así que un timeout
        # con el runtime vivo sale `timeout · runtime_ocupado` y JAMÁS `sin_runtime`.
        c = _causa_ollama(ex, consultar_vivo=isinstance(ex, TimeoutError))
        if c is None:                                       # traductor no disponible
            causa = MV.TIMEOUT if isinstance(ex, TimeoutError) else MV.ERROR_UPSTREAM
            return _res(slug, ROTO, causa=causa, detalle=f"la prueba falló: {ex}")
        return _res(slug, ROTO, causa=c["causa"], detalle=c["detalle"],
                    evidencia={"causa_tipada": c})


#: EL ESTADO DEL DETECTOR DE CLIs → el vocabulario sellado del motor. No se inventa ninguna
#: causa: las cuatro ya existen y son las que el resto de la casa usa para lo mismo.
_CAUSA_DE_CLI = {
    "not_installed": MV.CLI_NO_INSTALADO,
    "no_auth": MV.SIN_SESION,
    "auth_expired": MV.SIN_SESION,
}


def _probar_cli(slug: str, ref: str) -> dict:
    """¿Este CLI puede correr AHORA? Por el MISMO detector que sirve `/v1/brains/status`.

    ⚠️ SE USA EL DETECTOR, NO `_checklist_cli`. Los dos existen y los dos son honestos, pero
    dentro del sidecar el checklist muere con `module 'models' has no attribute 'ALIASES'`
    —una colisión de módulos planos del empaquetado, de la misma familia que la que ya está
    documentada en `brains_status`— mientras el detector responde perfecto en ese mismo
    proceso. Se consume lo que funciona donde tiene que funcionar. La colisión queda
    reportada aparte: es un bug del empaquetado, no de esta puerta.

    Un CLI no se «corre» para probarlo: tener sesión y un servicio vivo ES la prueba. Correr
    un turno de verdad gastaría los créditos del usuario para contestar una pregunta que su
    propio estado ya contesta.
    """
    t0 = time.time()
    try:
        import sys as _sys
        _ad = str(_ap.resource_root() / "platform" / "assembler")
        if _ad not in _sys.path:
            _sys.path.insert(0, _ad)
        from cli_brain.detect import detect_all
        from cli_brain.lifecycle import service_status
        provs = detect_all(public=True) or {}
        svc = service_status() or {}
    except Exception as ex:  # noqa: BLE001 — sin detector se dice, jamás se finge verde
        logging.getLogger(__name__).warning("probar_cli sin detector para %s: %r", slug, ex)
        return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM,
                    detalle="no pude verificar el CLI en este momento",
                    evidencia={"excepcion": f"{type(ex).__name__}: {ex}"[:300]})

    st = provs.get(ref) or {}
    estado_cli = str(st.get("state") or "")
    detalle = str(st.get("detail") or "")
    ms = int((time.time() - t0) * 1000)
    if estado_cli != "ready":
        return _res(slug, ROTO, causa=_CAUSA_DE_CLI.get(estado_cli, MV.ERROR_UPSTREAM),
                    ms=ms, detalle=detalle, evidencia={"detector": estado_cli})
    # LA SESIÓN NO ALCANZA: el listener local es el que ejecuta. Un CLI logueado con el
    # servicio caído no puede correr nada, y decir «listo» ahí sería el falso verde de
    # siempre (misma lección que el Slice C de la Sala).
    if str(svc.get("state") or "") != "ready":
        return _res(slug, ROTO, causa=MV.CLI_INTERACTIVO_COLGADO, ms=ms,
                    detalle=str(svc.get("detail") or ""),
                    evidencia={"detector": estado_cli, "servicio": svc.get("state")})
    return _res(slug, PROBADO, ms=ms, detalle=detalle or "sesión activa y servicio vivo",
                evidencia={"detector": estado_cli, "servicio": svc.get("state")})


def _res(slug: str, estado: str, *, causa: Optional[str] = None, detalle: str = "",
         evidencia: Optional[dict] = None, ms: Optional[int] = None) -> dict:
    if causa is not None and causa not in CAUSAS:
        raise ValueError(f"causa fuera del vocabulario: {causa!r}")
    r = {"slug": slug, "estado": estado, "causa": causa if estado == ROTO else None,
         "detalle": detalle, "evidencia": evidencia or {}, "ms": ms, "ts": time.time()}
    man = _manifiesto()
    if slug in man:
        man[slug]["estado"] = estado
        man[slug]["causa"] = r["causa"]
        man[slug]["prueba"] = r
        _guardar_manifiesto(man)
    return r


def borrar_local(slug: str) -> dict:
    """LIBERAR ESPACIO — de verdad: el archivo, la carpeta y el registro del runtime."""
    man = _manifiesto()
    e = man.get(slug)
    if not e:
        raise HTTPException(status_code=404, detail=f"no tengo {slug!r} en el manifiesto")
    liberado = 0
    ruta = e.get("ruta")
    if ruta:
        p = Path(ruta)
        try:
            if p.exists():
                liberado += p.stat().st_size
            carpeta = p.parent
            if carpeta.exists() and carpeta.is_relative_to(modelos_dir()):
                for hijo in carpeta.iterdir():
                    try:
                        liberado += hijo.stat().st_size if hijo.is_file() else 0
                    except Exception:
                        pass
                shutil.rmtree(carpeta, ignore_errors=True)
        except Exception:
            pass
    tag = e.get("ollama_tag")
    quitado_ollama = False
    if tag:
        b = _ollama_bin()
        if b:
            try:
                r = subprocess.run([b, "rm", tag], capture_output=True, text=True, timeout=60)
                quitado_ollama = r.returncode == 0
            except Exception:
                quitado_ollama = False
    man.pop(slug, None)
    _guardar_manifiesto(man)
    return {"borrado": True, "slug": slug, "liberado_gb": round(liberado / GB, 2),
            "ollama": quitado_ollama, "maquina": maquina()}


# ══════════════════════════════════════════════════════════════════════════════════
# §8 · GATING  ·  la pieza declara, el centro contesta
# ══════════════════════════════════════════════════════════════════════════════════
def tier_de_fila(slug: str, tier_local: Optional[str] = None) -> Optional[str]:
    """El tier EFECTIVO de una fila. Los hosteados lo declaran (de esos sí sabemos qué
    son); los locales lo estiman de su peso. Fail-closed: lo desconocido no sube de tier."""
    if slug in FRONTIER_SLUGS:
        return "frontier"
    h = _HOSTEADO_POR_SLUG.get(slug)
    if h:
        return h["tier"]
    return tier_local


def capacidades_de(slug: str, categoria: Optional[str], familia: str) -> list[str]:
    """Qué capacidades tiene ESTA fila.

    Un hosteado las declara en su renglón de HOSTEADOS (la visión NO se deduce de
    «es frontier»: Gemini ve y no guía, y un CLI guía sin ver imágenes por API). Un
    local tiene EXACTAMENTE la de su categoría — la que se probó al descargarlo."""
    if familia in (INCLUIDO, CLI, API):
        h = _HOSTEADO_POR_SLUG.get(slug)
        return list(h["capacidades"]) if h else [RAZONAMIENTO, RAPIDO]
    return [categoria] if categoria else []


#: Qué prueba de categoría acredita qué capacidad técnica. El puente es `prueba`, no el id:
#: `razonamiento`, `codigo` y `rapido` son tres RASGOS distintos que se acreditan con la
#: MISMA prueba (`texto`), y lo que la matriz necesita saber es qué se ejecutó de verdad.
_MATRIZ_POR_PRUEBA = {
    "texto": ["streaming", "text"],
    "vision": ["streaming", "text", "vision"],
    "embedding": ["embeddings"],
}


def matriz_de_local(categoria: Optional[str]) -> Optional[list[str]]:
    """La matriz técnica de un modelo local, derivada de la prueba que YA se le corrió.

    Un local no tiene catálogo de proveedor que consultar, pero tiene algo mejor: se probó
    al descargarlo (`CATEGORIAS[*]["prueba"]`), y esa prueba es un hecho ejecutado, no una
    ficha de marketing. Un modelo de embeddings NO recibe `text` ni `streaming`: no hace
    chat, y admitirlo para una charla sería inventar.

    Devuelve `None` —ausente, no vacío— cuando la fila no tiene categoría: ahí no sabemos, y
    el resolver tiene que poder distinguir «no declara» de «declara que no puede».
    """
    cat = CATEGORIAS_POR_ID.get(str(categoria or "")) or {}
    matriz = _MATRIZ_POR_PRUEBA.get(str(cat.get("prueba") or ""))
    return list(matriz) if matriz else None


def gate(pieza: str, *, slug: str = "", tier: Optional[str] = None,
         categoria: Optional[str] = None, familia: str = LOCAL) -> dict:
    """¿ESTE modelo alcanza para ESTA pieza? La respuesta trae el porqué y el camino.

    Nunca devuelve un simple False: si no alcanza, dice qué falta, qué recomendamos y
    cuáles son las DOS salidas reales ([Descargar este] / [Conectar API])."""
    p = PIEZAS.get(pieza)
    if not p:
        raise HTTPException(status_code=400, detail=f"pieza desconocida: {pieza!r}")
    tier_ef = tier_de_fila(slug, tier)
    caps = capacidades_de(slug, categoria, familia)
    falta_cap = bool(p["capacidad"]) and p["capacidad"] not in caps
    falta_tier = not tier_alcanza(tier_ef, p["min_tier"])
    alcanza = not (falta_cap or falta_tier)

    razon_es = razon_en = ""
    if falta_cap:
        c = CATEGORIAS_POR_ID.get(p["capacidad"], {})
        razon_es = f"este modelo no hace {c.get('es', p['capacidad'])}"
        razon_en = f"this model doesn't do {c.get('en', p['capacidad'])}"
    elif falta_tier:
        razon_es = f"«{p['es']}» necesita un modelo {p['min_tier']}; éste es {tier_ef or 'desconocido'}"
        razon_en = f"“{p['en']}” needs a {p['min_tier']} model; this one is {tier_ef or 'unknown'}"

    return {
        "pieza": pieza, "alcanza": alcanza,
        "min_tier": p["min_tier"], "tier": tier_ef, "capacidad": p["capacidad"],
        "falta_capacidad": falta_cap, "falta_tier": falta_tier,
        "es": razon_es, "en": razon_en,
        "porque_es": p["porque_es"], "porque_en": p["porque_en"],
        "recomendacion": None if alcanza else {
            "categoria": p["capacidad"] or RAZONAMIENTO,
            "min_tier": p["min_tier"],
            "descargar": p["min_tier"] != "frontier",
            "api": True,
        },
        "ts": time.time(),
    }


# ══════════════════════════════════════════════════════════════════════════════════
# §9 · LAS FILAS DE LA PANTALLA
# ══════════════════════════════════════════════════════════════════════════════════
#: Los modelos HOSTEADOS que el producto ya sirve. La verdad de ESTADO la pone el Motor
#: (probando de verdad); esta tabla dice quién existe, con qué marca se pinta, qué tier
#: es y QUÉ SABE HACER.
#:
#: Las capacidades se DECLARAN por fila y no se deducen de «es frontier»: Gemini ve
#: imágenes y no alcanza para guiar, y un CLI por suscripción guía sin exponer visión por
#: esta ruta. Deducirlas habría producido las dos mentiras al mismo tiempo.
def _h(familia, ref, label, marca, alias, sub, tier, caps):
    return {"familia": familia, "ref": ref, "label": label, "marca": marca, "alias": alias,
            "sub": sub, "tier": tier, "capacidades": caps, "slug": f"{familia}.{ref}"}


_TXT = [RAZONAMIENTO, CODIGO, RAPIDO]
def _hosteados_cli() -> list:
    specs = _cli_specs_or_empty()
    if specs:
        return [
            _h(CLI, s.provider_id, s.display_name, s.brand, s.provider_id,
               s.centro_sub, "frontier", _TXT)
            for s in specs
        ]
    return [  # E1-FALLBACK
        _h(CLI, "claude_cli", "Claude Code", "claude_code", "claude_cli",
           "Tu suscripción de Claude Code piensa por ti, sin API.", "frontier", _TXT),
        _h(CLI, "codex_cli", "Codex", "codex", "codex_cli",
           "Tu suscripción de Codex piensa por ti, sin API.", "frontier", _TXT),
    ]


HOSTEADOS = [
    _h(INCLUIDO, "cognicion", "Cognición incluida", "aleph", "brain",
       "La que viene con Aleph. No tienes que traer nada.", "frontier", _TXT + [VISION]),
    *_hosteados_cli(),
    _h(API, "anthropic", "Anthropic", "anthropic", None,
       "Claude con tu propia llave.", "frontier", _TXT + [VISION]),
    _h(API, "openai", "OpenAI", "openai", None,
       "GPT con tu propia llave.", "frontier", _TXT + [VISION, EMBEDDINGS]),
    _h(API, "openrouter", "OpenRouter", "openrouter", None,
       "Un montón de modelos por una sola llave.", "frontier", _TXT + [VISION]),
    _h(API, "groq", "Groq", "groq", None,
       "Modelos abiertos, muy rápidos, con tu llave.", "grande", _TXT),
    _h(API, "deepseek", "DeepSeek", "deepseek", None,
       "Razonamiento barato con tu llave.", "grande", _TXT),
    _h(API, "mistral", "Mistral", "mistral", None,
       "Modelos europeos con tu llave.", "grande", _TXT),
    _h(API, "together", "Together", "together", None,
       "Modelos abiertos hosteados, con tu llave.", "grande", _TXT),
    _h(API, "gemini", "Gemini", "gemini", None,
       "Multimodal de Google con tu llave.", "grande", _TXT + [VISION]),
]
_HOSTEADO_POR_SLUG = {h["slug"]: h for h in HOSTEADOS}


# ══════════════════════════════════════════════════════════════════════════════════
# [F9] LAS TABLAS DE UN PROVEEDOR DE API — cuáles son OBLIGATORIAS y cuáles no
# ══════════════════════════════════════════════════════════════════════════════════
# LEY: los proveedores son DATOS. Dar de alta uno es agregar FILAS, jamás un caso especial
# (`verify` lo guarda con un proveedor ficticio que se rompe primero si alguien mete un if).
#
# Pero «son datos» no alcanza si nadie dice CUÁLES datos: hoy la variación por proveedor vive
# en SIETE tablas de cuatro módulos, y nada obligaba a que un alta las tocara todas. Medido
# el 2026-08-07: `gemini` falta en tres, `mistral` y `together` en una. Un alta incompleta no
# rompe nada ruidosamente — se DEGRADA EN SILENCIO, que es el fallo mudo con otra cara.
#
# Esta declaración es la que hace la diferencia entre «faltó cargarla» y «no hace falta».
# Se midió con el proveedor ficticio: anda SIN las tres opcionales.
TABLAS_DE_PROVEEDOR = {
    # Sin cualquiera de estas cuatro, el proveedor NO funciona como los demás.
    "obligatorias": {
        "motor_verdad._KEY_VALIDATORS": "cómo se autentica · base · sonda de generación",
        "modelos_discovery.RUTAS": "de dónde sale su catálogo y en qué dialecto",
        "centro_modelos._PICKER_HOSTEADO": "modelo semilla · base_url · byok_ref",
        "centro_modelos.HOSTEADOS": "la fila misma: label · marca · tier · capacidades",
    },
    # Estas MEJORAN la experiencia y su ausencia tiene un camino declarado. NO son deuda:
    # el proveedor ficticio corre sin ninguna de las tres y hace todo lo que tiene que hacer.
    "opcionales": {
        "motor_verdad.MODELO_PRUEBA": "semilla del modelo; sin ella manda la elección del "
                                      "usuario o el id de _PICKER_HOSTEADO",
        "centro_conexiones.KEY_SHAPE": "forma de la llave para avisar antes de mandarla; "
                                       "sin ella se valida contra el proveedor y listo",
        "centro_conexiones.NOMBRE_MARCA": "nombre visible; sin él se usa el ref",
    },
}


def _estado_hosteado(h: dict, owner: Optional[str], get_conn) -> dict:
    """El estado de una fila hosteada NO lo inventa esta pantalla: se lo pregunta al Motor
    de Verdad, con la LECTURA barata (`estado`, que no dispara pings caros).

    Por eso los 5 estados del semáforo pueden aparecer de verdad: 🟡 sin probar, ⚪ sin
    configurar (no hay llave guardada), 🔴 con su causa, 🟢 si el motor tiene una prueba
    fresca, 🔒 si el motor dice `premium`. Hornear DETECTADO habría convertido la pantalla
    en una lista decorativa que dice lo mismo pase lo que pase."""
    try:
        if h["familia"] == API:
            res = MV.estado(MV.KEY, h["ref"], owner=owner)
            hay_llave = False
            if owner and get_conn:
                try:
                    from app.phase1 import repo
                    conn = get_conn()
                    try:
                        hay_llave = any((k.get("provider") or "").lower() == h["ref"]
                                        for k in repo.list_keys(conn, owner))
                    finally:
                        conn.close()
                except Exception:
                    hay_llave = False
            estado = res.get("estado") or DETECTADO
            # Sin llave guardada, «sin probar» sería una promesa: no hay NADA que probar.
            if not hay_llave and estado == DETECTADO:
                estado = NO_CONFIGURADO
            return {"estado": estado, "causa": res.get("causa"), "ts": res.get("ts"),
                    "hay_llave": hay_llave, "prueba": _prueba_de(res, estado)}
        if h["alias"]:
            res = MV.estado(MV.CEREBRO, h["alias"])
            estado = res.get("estado") or DETECTADO
            return {"estado": estado, "causa": res.get("causa"),
                    "ts": res.get("ts"), "hay_llave": None,
                    "prueba": _prueba_de(res, estado)}
    except Exception:
        pass
    return {"estado": DETECTADO, "causa": None, "ts": None, "hay_llave": None, "prueba": None}


def _prueba_de(res: dict, estado: str) -> Optional[dict]:
    """[F7 · obra 3] LA EVIDENCIA DE LA FILA, con su fecha.

    El motor ya medía y ya guardaba el porqué; la fila lo tiraba y por eso las 8 filas de
    la vía API llegaban al front SIN campo `prueba` — o sea sin `[?]` posible y sin fecha,
    y «🟢 probado» a secas. Verde sin evidencia no existe (ley de Gate 1): esto es lo que
    le da al verde algo detrás.

    **Sin medición no hay prueba**, y `MV.estado` es explícito al respecto: cuando nunca se
    probó devuelve un placeholder (`cacheado=False`, `evidencia.nunca_probado`) con un `ts`
    FRESCO —el del momento de preguntar—. Emitir eso como evidencia sería lo peor de los dos
    mundos: un [?] que no muestra nada y una fecha que hace pasar por recién medido algo que
    no se midió nunca (y que por lo tanto nunca envejecería para la caducidad).
    """
    if not res or not res.get("ts"):
        return None
    if not res.get("cacheado") or (res.get("evidencia") or {}).get("nunca_probado"):
        return None
    ev = res.get("evidencia") or {}
    return {
        "estado": estado,
        "causa": res.get("causa"),
        "ts": res.get("ts"),
        # `detail` es la frase que el motor ya redacta; `prueba` dice CON QUÉ se juzgó
        # (F7 · obra 1a: catalogo_autenticado · generacion · no_discriminante).
        "detalle": ev.get("detail") or ev.get("auditoria_validador") or "",
        "evidencia": ev,
    }


def filas(owner: Optional[str] = None, get_conn=None) -> dict:
    """La pantalla entera, sin tocar la red externa: filas + grupos + categorías + máquina.

    Los estados salen del Motor de Verdad y se PRUEBAN a pedido (mismo contrato del Centro
    de Conexiones). Nada nace verde."""
    maq = _con_default(maquina())
    inv = instalados()
    out = []
    for h in HOSTEADOS:
        slug = h["slug"]
        st = _estado_hosteado(h, owner, get_conn)
        out.append({
            "slug": slug, "familia": h["familia"], "ref": h["ref"], "label": h["label"],
            "marca": h["marca"], "sub": h["sub"], "alias": h["alias"], "categoria": None,
            "tier": tier_de_fila(slug, None), "formato": None, "peso_gb": None,
            "estado": st["estado"], "causa": st["causa"], "ts": st["ts"],
            "hay_llave": st["hay_llave"], "local": False,
            "prueba": st.get("prueba"),          # [F7] evidencia + fecha, para el [?]
            "frontier": slug in FRONTIER_SLUGS,
            "capacidades": capacidades_de(slug, None, h["familia"]),
        })
    for m in inv["modelos"]:
        out.append({
            "slug": "local." + m["slug"], "familia": LOCAL, "ref": m["slug"],
            "label": (m.get("hf_id") or m.get("ollama_tag") or m["slug"]).split("/")[-1],
            "marca": (m.get("hf_id") or "").split("/")[0] or "huggingface",
            "sub": (f"{m['formato']} · {m['peso_gb']} GB" if m.get("peso_gb") else (m.get("formato") or "")),
            "alias": None, "categoria": m.get("categoria"),
            "tier": m.get("tier"), "formato": m.get("formato"), "peso_gb": m.get("peso_gb"),
            "estado": m.get("estado") or DETECTADO, "causa": m.get("causa"),
            "local": True, "frontier": False, "hf_id": m.get("hf_id"),
            "avatar": bool(m.get("avatar")),
            "ollama_tag": m.get("ollama_tag"), "prueba": m.get("prueba"),
            "preexistente": bool(m.get("preexistente")),
            "capacidades": capacidades_de("local." + m["slug"], m.get("categoria"), LOCAL),
        })
    conteo = {"total": len(out)}
    for f in FAMILIAS:
        conteo[f] = sum(1 for r in out if r["familia"] == f)
    conteo["probados"] = sum(1 for r in out if r["estado"] == PROBADO)
    conteo["rotos"] = sum(1 for r in out if r["estado"] == ROTO)
    return {
        "filas": out,
        "grupos": [{"familia": f, "titulo": t, "lede": l, "recomendado": RECOMENDADO.get(f)}
                   for f, t, l in GRUPOS],
        "categorias": [{k: v for k, v in c.items() if k != "hf"} for c in CATEGORIAS],
        "piezas": {k: {kk: vv for kk, vv in v.items()} for k, v in PIEZAS.items()},
        "conteo": conteo, "maquina": maq, "ts": time.time(),
    }


# ══════════════════════════════════════════════════════════════════════════════════
# §9.b · MODELOS V2 — lote inicial + Default/Conectados + sesión CLI persistente
# ══════════════════════════════════════════════════════════════════════════════════
_PREF_LOCK = threading.RLock()
_CLI_LOCK = threading.Lock()
_VEREDICTOS_UTILES = frozenset({"comodo", "justo", "no_entra"})
_DEFAULT_CAIDO_CAMINOS = (
    {
        "accion": "reconectar",
        "es": "Reconectar",
        "en": "Reconnect",
    },
    {
        "accion": "usar_otro_conectado",
        "es": "Usar otro conectado",
        "en": "Use another connected model",
    },
)


#: El archivo pre-multicuenta. NO se borra: se adopta una vez y se deja quieto, porque
#: «no se borra hasta que una versión lo declare migrado» es parte del contrato de esta
#: migración. Su historia también explica por qué durante meses dos cuentas de la misma
#: Mac compartieron elección de cerebro.
_PREF_LEGADO = "preferencias-v2.json"


def _preferencias_path(owner: Optional[str] = None) -> Path:
    """El archivo de preferencias DE ESTE DUEÑO.

    [Convergencia · superficie 3 · fase 1] Hallazgo A.3, en rojo: este archivo era UNO
    para toda la instalación. Aleph es multicuenta LOCAL —dos personas en la misma Mac—,
    así que la elección de cerebro de una era la de la otra. Es la misma familia que la
    fuga entre cuentas de Gate 2.5, en otra superficie.

    LA CLAVE ES `(dueño, recurso)`, igual que en `workspaces/memoria.py`. El nombre del
    archivo se arma con un id SANEADO, nunca con lo que llegue: un `owner` con `/` o `..`
    escribiría fuera del directorio.

    ADOPCIÓN, UNA VEZ. Si este dueño todavía no tiene archivo y el viejo global existe, se
    COPIA —no se mueve—. Así el primero que entra después de actualizar no pierde su
    Default, y el archivo viejo queda como estaba por si hay que volver atrás.

    SIN DUEÑO devuelve el archivo viejo y el llamador NO persiste (ver
    `_preferencias_normalizadas`): una lectura anónima puede mirar el estado heredado,
    pero no puede escribirlo ni recibir el de una cuenta.
    """
    base = modelos_dir()
    duenio = _slug_de_owner(owner)
    if not duenio:
        return base / _PREF_LEGADO
    d = base / "preferencias"
    d.mkdir(parents=True, exist_ok=True)
    mio = d / f"{duenio}.json"
    if not mio.is_file():
        viejo = base / _PREF_LEGADO
        if viejo.is_file():
            try:
                mio.write_text(viejo.read_text("utf-8"), "utf-8")
            except Exception:                               # noqa: BLE001
                pass                                        # sin adopción, empieza limpio
    return mio


def _slug_de_owner(owner: Optional[str]) -> Optional[str]:
    """Un id opaco o nada. Mismo criterio que `memoria._seguro` y `provenance.safe_ref`:
    lo que no tiene forma de id no se usa para armar una ruta de archivo."""
    s = str(owner or "").strip()
    if not s or len(s) > 120:
        return None
    if not all(c.isalnum() or c in "._:-" for c in s):
        return None
    # Y AL MENOS UN ALFANUMÉRICO. Sin esto, `..` pasa el filtro —el punto está permitido—
    # y el archivo sale `...json`. No escapa del directorio, pero tampoco es un id: dos
    # basuras distintas pueden colisionar en el mismo archivo. Lo encontró la vara.
    if not any(c.isalnum() for c in s):
        return None
    return s


def _cli_sesiones_path() -> Path:
    return modelos_dir() / "sesiones-cli-v2.json"


def modelo_elegido_de(slug: str, *, owner: Optional[str] = None) -> Optional[str]:
    """[F9] EL MODELO QUE ESTA VÍA USA — para que la SONDA pruebe la ruta del usuario.

    Pública porque `motor_verdad.prueba_key` la necesita: la sonda de generación tiene que
    correr con el modelo que la persona eligió, no con uno fijo. Probar `MODELO_PRUEBA` y
    coronar verde certifica una ruta que no es la suya.

    Devuelve la ELECCIÓN PERSISTIDA. `None` = no eligió, y entonces la semilla declarada
    hace su trabajo. Un solo lector del archivo: dos se separan, y separarse acá significa
    que la sonda prueba un modelo y la fila muestra otro.
    """
    with _PREF_LOCK:
        raw = _leer_json(_preferencias_path(owner), {})
    m = (raw.get("modelos") or {}).get(str(slug or ""))
    return str(m) if m else None


def _leer_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default


def _guardar_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def cli_sesiones(*, fresco: bool = False, ttl: Optional[float] = None) -> dict:
    """Estado real y no sensible de las sesiones CLI.

    La autenticación sigue siendo propiedad de Claude Code/Codex; Aleph no copia tokens.
    Persistimos sólo el último diagnóstico público para que una recarga no "olvide" qué
    sesión estaba elegida. Un snapshot viejo jamás se convierte en verde: si la detección
    viva falla se devuelve como `persistida:true`, con `actual:false`.
    """
    previo = _leer_json(_cli_sesiones_path(), {})
    try:
        asm = Path(__file__).resolve().parents[4] / "platform" / "assembler"
        if str(asm) not in sys.path:
            sys.path.insert(0, str(asm))
        from cli_brain.detect import detect_all
        from cli_brain.lifecycle import service_status

        providers = detect_all(ttl=0 if fresco else ttl, public=True)
        service = service_status()
        _cli_ids = set(_cli_frontier_slugs())
        _cli_ids = {s.replace("cli.", "", 1) for s in _cli_ids}
        proveedores_limpios = {
            k: {
                kk: vv for kk, vv in (v or {}).items()
                if kk in {"provider", "state", "installed", "detail", "extra", "checked_at",
                          "auth_state", "last_auth_verified_at", "last_auth_result",
                          "configuration_state", "access_state",
                          "service_state", "last_test_state", "last_test_at",
                          "last_error_kind", "last_actual_model"}
            }
            for k, v in providers.items() if k in _cli_ids
        }
        prev_providers = previo.get("providers") or {}
        caidas = [
            {
                "provider": provider,
                "antes": "ready",
                "ahora": (status or {}).get("state") or "unavailable",
                "causa": (
                    MV.CLI_NO_INSTALADO
                    if (status or {}).get("state") == "not_installed"
                    else MV.SIN_SESION
                    if (status or {}).get("state") in ("no_auth", "auth_expired")
                    else MV.ERROR_UPSTREAM
                ),
                "detalle": (status or {}).get("detail") or "la sesión CLI dejó de estar disponible",
            }
            for provider, status in proveedores_limpios.items()
            if (prev_providers.get(provider) or {}).get("state") == "ready"
            and (status or {}).get("state") != "ready"
        ]
        limpio = {
            "version": 2,
            "providers": proveedores_limpios,
            "service": {
                k: v for k, v in (service or {}).items()
                if k in {"state", "mode", "managed", "detail", "pid", "port", "checked_at"}
            },
            "actual": True, "persistida": False, "caidas": caidas, "ts": time.time(),
        }
        with _CLI_LOCK:
            _guardar_json(_cli_sesiones_path(), limpio)
        return limpio
    except Exception as exc:
        return {
            "providers": previo.get("providers") or {},
            "service": previo.get("service") or {
                "state": "unavailable", "detail": "no pude verificar el servicio CLI",
            },
            "actual": False, "persistida": bool(previo),
            "detalle": f"detección CLI no disponible: {exc.__class__.__name__}",
            "ts": time.time(),
        }


def _anotar_memoria(base: dict, owner: Optional[str], get_conn) -> dict:
    """[F4c] Pega `estuvo_completa` a cada fila, desde el registro de modelos.

    Es el dato que hace posible la regla ANTI-YO-YO: sin él, un modelo cuyo runtime se
    apagó dejaría de ser completo en el próximo arranque y se iría a la aduana; al prender
    Ollama volvería al local. Un yo-yo por cada fallo transitorio.

    **Se DERIVA, no se guarda**: `ultimo_veredicto == 'probado'`, igual que el molde de
    conectores (`centro_conexiones.py:1999`). Y `'probado'` significa que el modelo CORRIÓ,
    no que esté instalado.

    Sin owner o sin DB, `estuvo_completa=False` para todas: es la respuesta honesta —no
    sabemos si anduvo— y deja las piezas en la aduana, que es el lado conservador (mostrar
    un trámite de más es recuperable; esconder uno que hace falta, no).
    """
    filas_ = base.get("filas") or []
    memoria: dict = {}
    if owner and get_conn:
        try:
            from app.phase1 import modelos_repo as _mr
            conn = get_conn()
            try:
                memoria = {f["modelo_id"]: f for f in _mr.listar(conn, user_id=owner)}
            finally:
                conn.close()
        except Exception:                          # noqa: BLE001 — leer la memoria no tumba la pantalla
            memoria = {}
    for f in filas_:
        m = memoria.get(f.get("ref")) or {}
        f["estuvo_completa"] = bool(m.get("estuvo_completa"))
        # La medición viva del registro NO pisa la de la fila (que se acaba de medir);
        # viaja aparte para que el [?] pueda decir «la última vez que anduvo fue…».
        if m:
            f["registro"] = {"ultimo_veredicto": m.get("ultimo_veredicto"),
                             "causa": m.get("causa"),
                             "ultima_verificacion": m.get("ultima_verificacion")}
    return base


def _anotar_conectados(base: dict, sesiones: dict) -> dict:
    """Añade origen/conectado sin sustituir el estado real de cada fila."""
    service_ok = (sesiones.get("service") or {}).get("state") == "ready"
    providers = sesiones.get("providers") or {}
    for f in base.get("filas") or []:
        f["origen"] = "hf_local" if f.get("local") else f.get("familia")
        conectado = False
        if f["familia"] == CLI:
            sesion = providers.get(f["ref"]) or {}
            vivo = sesiones.get("actual") and service_ok and sesion.get("state") == "ready"
            # ⚠️ [F9] `conectado` NO SE DECIDE ACÁ. Se deriva de `estado` más abajo, con la
            # MISMA regla que las otras vías.
            #
            # EL BUG MEDIDO EN LA APP (2026-08-07, payload de `/v1/modelos/v2`): la fila de
            # Claude Code llegaba con `estado:"probado"` —con su prueba, su detalle («sesión
            # activa (max)») y su fecha— y `conectado:false` AL MISMO TIEMPO. La pantalla
            # sacaba el TEXTO de `estado` y la LUZ de `conectado`: «probado hace 0s» con luz
            # gris, al lado de OpenRouter con el mismo texto en verde.
            #
            # La causa: sólo esta vía tenía un SENSOR PROPIO para `conectado` (la sonda de
            # sesión VIVA). Cuando `sesiones["actual"]` es False —el snapshot persistido, no
            # una sonda de ahora— ninguna de las dos ramas de abajo toca `estado`, así que
            # queda el veredicto del motor (correcto, con evidencia) y `conectado` cae a
            # False por AUSENCIA DE SONDA. Es la regla sellada otra vez: ausencia de
            # registro no es dato negativo.
            #
            # Cuál mentía: LA LUZ. `estado` es una medición con evidencia y fecha; `conectado`
            # la re-derivaba de un sensor que puede no haber corrido. Ahora hay una sola
            # regla y no pueden discrepar por construcción.
            f["sesion_cli"] = sesion
            f["servicio_cli"] = sesiones.get("service") or {}
            # Detección + sesión + listener vivos son evidencia suficiente para la fila.
            if vivo:
                f["estado"] = PROBADO
                f["causa"] = None
                f["prueba"] = {
                    "estado": PROBADO, "ts": sesiones.get("ts"),
                    "detalle": ("sesión CLI activa y servicio local listo; "
                                + ("ejecución verificada" if sesion.get("last_test_state") == "passed"
                                   else "acceso y ejecución aún sin verificar")),
                    "evidencia": {"sesion_cli": True, "servicio_local": True,
                                  "acceso_proveedor": sesion.get("access_state", "unknown"),
                                  "ejecucion_verificada": sesion.get("last_test_state") == "passed"},
                }
            elif sesiones.get("actual"):
                estado_sesion = sesion.get("state")
                f["estado"] = ROTO
                f["causa"] = (
                    MV.CLI_NO_INSTALADO
                    if estado_sesion == "not_installed"
                    else MV.SIN_SESION
                    if estado_sesion == "no_auth"
                    else MV.ERROR_UPSTREAM
                )
                f["prueba"] = {
                    "estado": ROTO,
                    "causa": f["causa"],
                    "ts": sesiones.get("ts"),
                    "detalle": (
                        (sesiones.get("service") or {}).get("detail")
                        if not service_ok
                        else sesion.get("detail")
                    ) or "la sesión CLI no está disponible",
                    "evidencia": {
                        "sesion_cli": estado_sesion,
                        "servicio_local": (sesiones.get("service") or {}).get("state"),
                    },
                }
        elif f["familia"] == API:
            # ⚠️ [F7·A] CONECTADO EXIGE VEREDICTO, NO «hay una fila en el vault».
            #
            # EL BUG MEDIDO (2026-08-06): esto era `bool(f.get("hay_llave"))`. Como
            # `selector_modelos` filtra por `conectado`, una llave que NADIE probó —incluso
            # una guardada por la puerta sin validación de `/v1/keys`— se OFRECÍA como
            # cerebro del agente en el Cuarto y en la Sala. El usuario elegía un modelo que
            # nunca contestó, y el fallo aparecía recién a mitad del turno.
            #
            # La llave sigue siendo condición NECESARIA (sin ella no hay nada que probar),
            # pero ya no es suficiente: hace falta que el motor haya dicho PROBADO. Un
            # `detectado` —«la guardé, no la pude validar»— NO alcanza: es exactamente el
            # estado que la ley de Gate 1 prohíbe pintar de verde.
            #
            # Lo que NO cambia: `hay_llave` sigue viajando tal cual, y la ADUANA de F4c
            # deriva de ÉL (`credencial_ok`), no de esto. Por eso un modelo con llave y sin
            # veredicto queda en «Tus modelos» 🟡 «sin probar» —que es la verdad— y no se
            # va a la aduana a pedir una llave que ya está.
            conectado = bool(f.get("hay_llave")) and f.get("estado") == PROBADO
        elif f["familia"] == INCLUIDO:
            conectado = f.get("estado") == PROBADO
        elif f.get("local"):
            conectado = f.get("estado") == PROBADO and bool(f.get("ollama_tag"))
        # [F9] LA REGLA ÚNICA para las vías sin requisito extra: si el estado dice PROBADO,
        # la pieza está conectada — venga de donde venga ese veredicto. La vía API mantiene
        # su requisito adicional (`hay_llave`, ley de F7·A: conectado exige veredicto Y
        # credencial) y la local el suyo (`ollama_tag`); ésos son requisitos REALES de la
        # vía, no un segundo sensor del mismo hecho.
        if f["familia"] == CLI:
            conectado = f.get("estado") == PROBADO
        f["conectado"] = conectado
    return base


def _fila_hf(m: dict) -> dict:
    """Candidato HF como la misma fila comparable del buscador (nunca como API)."""
    mid = str(m.get("id") or "")
    cats = list(dict.fromkeys(m.get("categorias") or [m.get("categoria")]))
    cats = [c for c in cats if c]
    return {
        "slug": "hf." + slug_de(mid), "familia": LOCAL, "origen": "hf_local",
        "ref": mid, "hf_id": mid, "hf": True, "local": True, "instalado": False,
        "label": m.get("nombre") or mid.split("/")[-1], "marca": m.get("org") or "huggingface",
        "sub": "Hugging Face · descarga local", "tier": m.get("tier"),
        "categorias": cats, "categoria": cats[0] if cats else None,
        "capacidades": cats, "frontier": False, "conectado": False,
        "estado": NO_CONFIGURADO, "causa": None, "recomendado": bool(m.get("recomendado")),
        "destino": "descarga_local", "inference_api": False,
        "formato": m.get("formato"), "archivo": m.get("archivo"),
        "archivos": m.get("archivos") or [], "peso_gb": m.get("peso_gb"),
        "cuantizacion": m.get("cuantizacion"), "veredicto": m.get("veredicto"),
        "url": m.get("url"), "descargas": m.get("descargas"), "likes": m.get("likes"),
    }


def _default_meta(default: Optional[str], por_slug: dict[str, dict]) -> dict:
    fila = por_slug.get(default) or {}
    caido = bool(default) and not bool(fila.get("conectado"))
    return {
        "slug": default,
        "conectado": bool(fila.get("conectado")),
        "caido": caido,
        "estado": fila.get("estado"),
        "causa": fila.get("causa"),
        # El guard se muestra AL USARLO, no al cargar ni al cambiar de filtro.
        "popup": "al_usarlo" if caido else None,
        "caminos": [dict(c) for c in _DEFAULT_CAIDO_CAMINOS] if caido else [],
    }


def _preferencias_normalizadas(filas_: list[dict], *, owner: Optional[str] = None,
                               persistir_default: bool = True) -> dict:
    por_slug = {f.get("slug"): f for f in filas_ if f.get("slug")}
    conectados = [f["slug"] for f in filas_ if f.get("conectado")]
    # SIN DUEÑO NO SE ESCRIBE. Una lectura anónima puede mirar lo heredado; persistir el
    # default derivado en el archivo global le cambiaría la elección a la cuenta que
    # todavía no lo adoptó.
    persistir_default = persistir_default and bool(_slug_de_owner(owner))
    with _PREF_LOCK:
        raw = _leer_json(_preferencias_path(owner), {})
        default = raw.get("default")
        # Un Default caído se conserva: sólo así el popup puede aparecer AL USARLO. Se
        # reemplaza automáticamente únicamente si ya no existe en el catálogo.
        if default not in por_slug:
            prioridad = [INCLUIDO, CLI, API, LOCAL]
            default = next((f["slug"] for fam in prioridad for f in filas_
                            if f.get("familia") == fam and f.get("conectado")), None)
            # Default es vocabulario singular, no opcional. Si nada está conectado, la
            # fila incluida queda como Default CAÍDO (sin falsearla verde) y el guard
            # ofrece Reconectar / Usar otro conectado recién cuando intentan usarla.
            if default is None:
                default = (
                    "incluido.cognicion"
                    if "incluido.cognicion" in por_slug
                    else next(iter(por_slug), None)
                )
        contextos = {
            str(k): str(v) for k, v in (raw.get("contextos") or {}).items()
            if v in por_slug
        }
        # ── [F8 · obra 2] LA ELECCIÓN DEL USUARIO, POR PROVEEDOR ──────────────────────
        # `{slug_de_la_vía: model_id}`. Vive acá y no en una tabla nueva porque es LA MISMA
        # clase de dato que `default` y `contextos` —una preferencia de modelo del dueño de
        # esta máquina— y partirla en dos casas es cómo se llega a que dos lugares se
        # contradigan sobre qué modelo se está usando.
        #
        # ⚠️ NO SE FILTRA CONTRA `por_slug`, a diferencia de `contextos`, y es a propósito.
        # Esta función normaliza con las filas que le pasen, y una lista PARCIAL borraría del
        # disco una elección que el usuario hizo una vez y no volvió a tocar. La validación
        # de «ese modelo existe» pasa donde tiene sentido pagarla: al ESCRIBIR
        # (`guardar_preferencias`, contra el catálogo vivo) y al LEER (`elegir()` re-elige
        # solo si el preferido murió — regla sellada en F6). Una preferencia muerta se
        # reemplaza; jamás se borra en silencio por el efecto colateral de otra pantalla.
        modelos = {
            str(k): str(v) for k, v in (raw.get("modelos") or {}).items() if k and v
        }
        persistido = {
            "version": 2, "default": default, "conectados": conectados,
            "contextos": contextos,
            # ⚠️ SI ESTA CLAVE NO ESTÁ ACÁ, LA ELECCIÓN SE PIERDE EN LA PRÓXIMA PINTADA.
            # `persistido` se REARMA de cero en cada normalización y es lo que se escribe a
            # disco: una clave que no esté en este dict no sobrevive a la primera lectura.
            "modelos": modelos,
            "actualizado_en": raw.get("actualizado_en") or time.time(),
        }
        if persistir_default and any(raw.get(k) != persistido.get(k) for k in persistido):
            _guardar_json(_preferencias_path(owner), persistido)
        return {
            **persistido,
            "default_estado": _default_meta(default, por_slug),
            "default_caido": bool(default and not (por_slug.get(default) or {}).get("conectado")),
            "ts": time.time(),
        }


def guardar_preferencias(cuerpo: dict, filas_: list[dict],
                         llaves: Optional[dict] = None, *,
                         owner: Optional[str] = None) -> dict:
    """Muta sólo Default, una elección de contexto o EL MODELO DE UN PROVEEDOR; Conectados
    siempre es derivado.

    [F8 · obra 2] `{"slug": "api.groq", "modelo": "llama-3.3-70b-versatile"}` persiste la
    elección del usuario para ESA vía. `modelo: ""` (o `null`) la BORRA — que no es lo mismo
    que elegir: es devolverle la decisión a Aleph, y sin esa salida el usuario que probó un
    modelo queda casado con él para siempre.

    Es GENERAL para los 8 proveedores y no tiene una sola rama por proveedor: qué se puede
    elegir sale del catálogo vivo de `modelos_discovery`, cuya tabla (`RUTAS`/`FORMAS`) es la
    que se extiende cuando aparece uno nuevo.
    """
    por_slug = {f.get("slug"): f for f in filas_ if f.get("slug")}
    with _PREF_LOCK:
        actual = _preferencias_normalizadas(filas_, owner=owner)
        if "modelo" in cuerpo:
            slug = str(cuerpo.get("slug") or "")
            f = por_slug.get(slug)
            if not f:
                raise HTTPException(status_code=404, detail="esa vía no existe")
            if str(f.get("familia") or "") != API:
                # Sólo la vía API tiene catálogo de proveedor. Un CLI usa el modelo de su
                # suscripción y un local usa el que está bajado: ofrecer «elegí modelo» ahí
                # sería un menú sobre algo que no se elige.
                raise HTTPException(status_code=409,
                                    detail="sólo una vía de API tiene modelos para elegir")
            modelo = str(cuerpo.get("modelo") or "").strip()
            elegidos = dict(actual.get("modelos") or {})
            if not modelo:
                elegidos.pop(slug, None)               # volver a «que elija Aleph»
            else:
                ref = slug.split(".", 1)[-1]
                cat = _disc.descubrir(ref, key=(llaves or {}).get(ref))
                # ⚠️ LA SEMILLA SIRVE PARA RECHAZAR, JAMÁS PARA DECLARAR MUERTO. Y la
                # distinción no es teórica: la MIDIÓ este mismo guard.
                #
                # Sembrar `cat` entero arreglaba una asimetría y creaba una peor. La que
                # arreglaba: el picker pinta la lista sembrada y DESHABILITA lo que no
                # sirve, pero este guard mira el catálogo VIVO —vacío sin llave—, así que
                # `fila_cat` salía None, el chequeo de `servible` no corría, y el backend
                # ACEPTABA lo que la pantalla ya había marcado como inservible. Eso es
                # justo lo que F9 prohíbe.
                #
                # La que creaba: `verificar_vigente` declara «sin catálogo NO HAY
                # VEREDICTO». Con la semilla adentro pasaba a haberlo — y la semilla son
                # LOS PRINCIPALES, NO TODOS. MEDIDO: `claude-opus-5` (está en la tabla) →
                # 200, y un id cualquiera de Anthropic que no esté en nuestras 5 filas →
                # 409 «ya no está en el catálogo de anthropic». Le habríamos cerrado la
                # puerta a un modelo legítimo con una tabla corta de 31 filas como única
                # prueba. Nadie puede perder acceso por lo que nosotros no escribimos.
                #
                # Por eso son DOS listas y no una: la vigencia se juzga con lo que el
                # PROVEEDOR publicó, y la semilla sólo alcanza para lo que ella misma
                # conoce.
                from app.phase1 import modelos_semilla as _semilla
                cat_sembrado = _semilla.sembrar(cat, slug)
                # ⚠️ EL VEREDICTO LO DA `verificar_vigente`, NO UN `in` ESCRITO ACÁ. Esa
                # función ya declara la regla que importa: **sin catálogo no hay veredicto**
                # (red caída o proveedor sin `/models` ⇒ se acepta, no se acusa). Reescribir
                # la comparación acá sería tener dos opiniones sobre si un id está vivo.
                muerto = _disc.verificar_vigente(ref, modelo, cat)
                if muerto:
                    raise HTTPException(status_code=409, detail=muerto.get("detalle")
                                        or "ese modelo no está en el catálogo del proveedor")
                # ⚠️ [F9] EXISTIR NO ES SERVIR, y el guard de F8 sólo preguntaba lo primero.
                # MEDIDO el 2026-08-07 contra el catálogo real de groq: de sus 15 modelos, 4
                # no sirven de cerebro (`whisper-*` transcriben, `orpheus-*` hablan), y esta
                # puerta los ACEPTABA. El usuario elegía Whisper y se enteraba a mitad del
                # primer turno — el fallo más lejos posible de la decisión que lo causó.
                #
                # La regla NO se copia acá: la responde `_disc.servible`, la misma que usa
                # `elegir()`. Dos copias de «qué modelo sirve» se separan, y separarse acá
                # significa que la pantalla ofrece lo que el backend rechaza.
                # Acá SÍ el sembrado: si la semilla conoce la fila, su veredicto de
                # `servible` vale tanto como el del catálogo vivo — lo da la misma función.
                # Y si no la conoce, `fila_cat` es None y no se rechaza nada, igual que
                # antes: no saber nunca es motivo para decir que no.
                fila_cat = next((m for m in (cat_sembrado.get("modelos") or [])
                                 if m.get("model_id") == modelo), None)
                if fila_cat is not None and not _disc.servible(fila_cat):
                    # ⚠️ EL MOTIVO NO SE REDACTA ACÁ. Lo da `motivo_no_servible`, que lo
                    # deriva de lo que el catálogo declara — y por eso un modelo que SÍ
                    # genera texto (pero además imagen) no recibe un «no genera texto» que
                    # cualquiera puede desmentir abriendo el catálogo del proveedor.
                    #
                    # Va como DETALLE del 409 y NO como causa tipada nueva (regla de persona usuaria,
                    # 2026-08-07): las causas tipadas son para lo que le pasa a algo
                    # CONECTADO; esto es una validación de entrada en el momento de elegir.
                    # Inflar el vocabulario de causas con motivos de rechazo sería mezclar
                    # dos cosas que se leen y se resuelven distinto.
                    raise HTTPException(
                        status_code=409,
                        detail=f"«{modelo}» no sirve como cerebro. "
                               + _disc.motivo_no_servible(fila_cat))
                elegidos[slug] = modelo
            actual["modelos"] = elegidos
        if "default" in cuerpo:
            slug = str(cuerpo.get("default") or "")
            if slug not in por_slug or not por_slug[slug].get("conectado"):
                raise HTTPException(status_code=409, detail="el Default tiene que estar conectado")
            actual["default"] = slug
        contexto = str(cuerpo.get("contexto") or "").strip().casefold()
        if contexto in {"guía", "guide"}:
            contexto = "guia"
        if contexto:
            if not re.match(r"^[\w.:-]{1,80}$", contexto):
                raise HTTPException(status_code=400, detail="contexto inválido")
            slug = str(cuerpo.get("seleccion") or actual.get("default") or "")
            f = por_slug.get(slug)
            if not f or not f.get("conectado"):
                raise HTTPException(status_code=409, detail="sólo se puede elegir un modelo conectado")
            if contexto == "guia" and not f.get("frontier"):
                raise HTTPException(status_code=409, detail="el Guía sólo acepta modelos frontier conectados")
            actual.setdefault("contextos", {})[contexto] = slug
        persistido = {
            "version": 2,
            "default": actual.get("default"),
            "conectados": [f["slug"] for f in filas_ if f.get("conectado")],
            "contextos": actual.get("contextos") or {},
            "modelos": actual.get("modelos") or {},      # [F8·obra 2] mismo motivo que arriba
            "actualizado_en": time.time(),
        }
        _guardar_json(_preferencias_path(owner), persistido)
    return {
        **persistido,
        "default_estado": _default_meta(persistido["default"], por_slug),
        "default_caido": not bool((por_slug.get(persistido["default"]) or {}).get("conectado")),
        "ts": time.time(),
    }


def catalogo_hf_lote(*, categorias: Optional[list[str]] = None,
                     formato: Optional[str] = None, limite: int = 2,
                     maq: Optional[dict] = None) -> dict:
    """Contrato batch de HF para el sidecar.

    Una llamada HTTP al sidecar reúne todas las categorías pedidas y pega a cada modelo
    su peso y veredicto antes de responder. El navegador jamás hace una request por
    modelo. Internamente las consultas públicas a HF corren concurrentes y se deduplican
    por ``id``; HF Inference API queda explícitamente fuera de V2.

    Sólo salen filas comparables: peso positivo y veredicto ∈
    {``comodo``, ``justo``, ``no_entra``}. Un candidato sin tamaño real se rechaza con
    fallo visible en vez de aparecer como una fila muda que obliga a abrirla.
    """
    solicitadas = list(dict.fromkeys(
        categorias if categorias is not None else [c["id"] for c in CATEGORIAS]))
    desconocidas = [c for c in solicitadas if c not in CATEGORIAS_POR_ID]
    if desconocidas:
        raise HTTPException(
            status_code=400,
            detail=f"categorías desconocidas: {', '.join(desconocidas)}",
        )
    if not solicitadas:
        raise HTTPException(status_code=400, detail="el lote necesita al menos una categoría")
    if limite < 1 or limite > 6:
        raise HTTPException(status_code=400, detail="limite fuera de rango (1..6)")

    hf_por_id: dict[str, dict] = {}
    fallos: list[dict] = []
    rechazados: list[dict] = []
    max_workers = min(5, len(solicitadas))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="modelos-hf") as pool:
        jobs = {
            pool.submit(catalogo_hf, categoria, formato, limite): categoria
            for categoria in solicitadas
        }
        for job in as_completed(jobs):
            categoria = jobs[job]
            try:
                dato = job.result()
            except Exception as exc:
                dato = {
                    "red": False,
                    "categoria": categoria,
                    "causa": MV.ERROR_UPSTREAM,
                    "detalle": str(exc),
                    "modelos": [],
                }
            if dato.get("red") is False:
                fallos.append({
                    k: dato.get(k)
                    for k in ("categoria", "causa", "detalle")
                })
            for modelo in dato.get("modelos") or []:
                mid = str(modelo.get("id") or "")
                if not mid:
                    rechazados.append({
                        "categoria": categoria,
                        "causa": MV.ERROR_UPSTREAM,
                        "detalle": "Hugging Face devolvió un candidato sin id",
                    })
                    continue
                peso = modelo.get("peso_gb")
                try:
                    peso_util = isinstance(peso, (int, float)) and float(peso) > 0
                except (TypeError, ValueError):
                    peso_util = False
                if not peso_util:
                    rechazados.append({
                        "id": mid,
                        "categoria": categoria,
                        "causa": MV.ERROR_UPSTREAM,
                        "detalle": "candidato omitido: Hugging Face no informó un peso comparable",
                    })
                    continue
                ver = modelo.get("veredicto")
                if not isinstance(ver, dict) or ver.get("veredicto") not in _VEREDICTOS_UTILES:
                    # Si el peso está, el sidecar puede reparar el veredicto contra el
                    # snapshot de la máquina. "desconocido" nunca cuenta como cumplimiento.
                    ver = veredicto(float(peso), maq)
                    modelo = {**modelo, "veredicto": ver}
                if ver.get("veredicto") not in _VEREDICTOS_UTILES:
                    rechazados.append({
                        "id": mid,
                        "categoria": categoria,
                        "causa": MV.ERROR_UPSTREAM,
                        "detalle": "candidato omitido: no pude calcular disco/RAM",
                    })
                    continue
                if mid in hf_por_id:
                    cats = hf_por_id[mid].setdefault("categorias", [])
                    if categoria not in cats:
                        cats.append(categoria)
                else:
                    copia = dict(modelo)
                    copia["categorias"] = [categoria]
                    hf_por_id[mid] = copia

    modelos = list(hf_por_id.values())
    modelos.sort(key=lambda m: (
        (m.get("veredicto") or {}).get("veredicto") == "no_entra",
        str(m.get("nombre") or m.get("id") or ""),
    ))
    return {
        "version": 2,
        "modelos": modelos,
        "fallos": fallos,
        "rechazados": rechazados,
        # La UI ya sabe conservar Conectados cuando esto es false. Un candidato no
        # comparable es una degradación visible igual que una categoría que no respondió.
        "red": not fallos and not rechazados,
        "hf": {
            "modo": "descarga_local",
            "inference_api": False,
        },
        "contrato": {
            "lote": True,
            "requests_listado": 1,
            "requests_sidecar": 1,
            "categorias": len(solicitadas),
            "hf_modelos": len(modelos),
            "veredictos_en_fila": not rechazados and all(
                isinstance(m.get("peso_gb"), (int, float))
                and float(m["peso_gb"]) > 0
                and isinstance(m.get("veredicto"), dict)
                and m["veredicto"].get("veredicto") in _VEREDICTOS_UTILES
                for m in modelos
            ),
            "veredictos_utiles": sorted(_VEREDICTOS_UTILES),
            "candidatos_rechazados": len(rechazados),
        },
        "ts": time.time(),
    }


def filas_v2(owner: Optional[str] = None, get_conn=None, *,
             limite_hf: int = 2, formato: Optional[str] = None) -> dict:
    """UN lote inicial: Incluido + CLI + API + instalados + candidatos HF con veredicto.

    El navegador hace una sola request aunque salgan N candidatos HF. El sidecar resuelve
    catálogo/peso/RAM y devuelve cada `veredicto` ya pegado a su fila. Las categorías se
    consultan concurrentemente para que el lote no sume cinco latencias seriales.
    """
    base = _anotar_memoria(
        _anotar_conectados(filas(owner=owner, get_conn=get_conn), cli_sesiones()),
        owner, get_conn)
    lote = catalogo_hf_lote(
        formato=formato,
        limite=limite_hf,
        maq=base.get("maquina"),
    )
    instalados_hf = {
        str(f.get("hf_id")) for f in base.get("filas") or [] if f.get("hf_id")
    }
    hf = [_fila_hf(m) for m in lote.get("modelos") or []
          if str(m.get("id") or "") not in instalados_hf]
    todas = list(base.get("filas") or []) + hf
    # [F4c] Las candidatas de HF se suman DESPUÉS del anotador, así que se anota de nuevo
    # sobre el lote completo. Sin esto, una fila del catálogo público llegaría al front sin
    # `estuvo_completa` y `pertenencia()` la trataría como nunca-completa por ausencia del
    # campo en vez de por decisión — que es la clase de default silencioso que esta obra
    # existe para no tener. (Es idempotente: re-anotar una fila ya anotada da lo mismo.)
    _anotar_memoria({"filas": todas}, owner, get_conn)
    pref = _preferencias_normalizadas(todas, owner=owner)
    for f in todas:
        f["default"] = f.get("slug") == pref.get("default")
        if f.get("default"):
            f["recomendado"] = True
    conteo = {
        "total": len(todas), "hf": len(hf),
        "conectados": len(pref.get("conectados") or []),
        "probados": sum(1 for f in todas if f.get("estado") == PROBADO),
        "rotos": sum(1 for f in todas if f.get("estado") == ROTO),
    }
    return {
        "version": 2, "filas": todas, "categorias": base.get("categorias") or [],
        "maquina": base.get("maquina"), "preferencias": pref, "conteo": conteo,
        "hf": {
            "red": lote.get("red"),
            "fallos": lote.get("fallos") or [],
            "rechazados": lote.get("rechazados") or [],
            "modo": "descarga_local",
            "inference_api": False,
        },
        "contrato": {
            **(lote.get("contrato") or {}),
            "hf_modelos": len(hf),
            "veredictos_en_fila": not (lote.get("rechazados") or []) and all(
                isinstance(f.get("peso_gb"), (int, float))
                and float(f["peso_gb"]) > 0
                and isinstance(f.get("veredicto"), dict)
                and f["veredicto"].get("veredicto") in _VEREDICTOS_UTILES
                for f in hf
            ),
        },
        "ts": time.time(),
    }


def _modelo_de_api(slug: str, declarado: Optional[str], key: Optional[str] = None,
                   eleccion: Optional[str] = None
                   ) -> tuple[Optional[str], Optional[dict], str]:
    """[Gate 2 · F6-cierre · obra A] El modelo de una vía API, del CATÁLOGO VIVO.

    **Calca lo que la vía local ya hace acá abajo**: el
    modelo de un Ollama no está escrito en el código, sale de `/api/tags`. Acá sale de
    `/v1/models` del proveedor.

    ⚠️ EL ID DECLARADO PASA A SER UNA PREFERENCIA, NO UN DECRETO. Si sigue vivo se usa —el
    comportamiento no cambia y nadie se despierta con otro modelo— y sólo si MURIÓ el
    discovery elige un reemplazo. Es la diferencia entre un catálogo que envejece y uno que
    se muere: F6-bis midió los dos ids que teníamos escritos (`qwen/qwen3.6-plus:free` y
    `openai/gpt-oss-120b:free`) y **ninguno de los dos existía ya**.

    Sin red, con el proveedor caído o con un proveedor que no publica catálogo, esto
    devuelve el declarado y sigue como antes: descubrir es una mejora, no una dependencia.

    ⚠️ [F8 · obra 1] `key` NO ES OPCIONAL EN LA PRÁCTICA. Esto llamaba a `descubrir(ref)` a
    secas, sin credencial, y MEDIDO el 2026-08-07 eso dejaba **7 de 8 proveedores con cero
    modelos**: el único que traía catálogo era OpenRouter, porque su `/models` es público.
    Con la llave del vault, groq pasó de 0 a 15 en la misma corrida.

    ⚠️ [F8 · obra 2] AHORA HAY DOS PREFERENCIAS, Y NO EMPATAN. `eleccion` es lo que el
    usuario eligió y persistió; `declarado` es el id escrito en `_PICKER_HOSTEADO`. El del
    usuario gana **siempre** que siga vivo: una heurística nuestra no le pisa una decisión
    suya. El escrito baja de rango a lo que siempre debió ser — una semilla para el primer
    arranque, no un decreto.

    Devuelve `(model_id, catalogo, origen)` con `origen` ∈ `usuario · catalogo · declarado ·
    ninguno`. El origen VIAJA porque la card tiene que poder decir la verdad: «usando X»
    cuando lo elegiste vos y «usando X» cuando lo elegimos nosotros no son la misma frase, y
    sin este campo la superficie tendría que adivinarlo comparando strings.

    `ninguno` no es un hueco: es el caso honesto en que NO hay modelo que usar —el catálogo
    llegó y no trajo nada servible— y es lo que enciende la causa `modelo_no_elegido` en vez
    de servir a ciegas un id que nadie verificó.
    """
    ref = str(slug or "").split(".", 1)[-1]

    # ── LA SEMILLA ENTRA COMO `declarado`, EL RANGO MÁS BAJO ──────────────────────────
    # No es un cuarto competidor: OCUPA el lugar del id escrito en `_PICKER_HOSTEADO`,
    # que es exactamente lo que este docstring ya dice que ese id debería ser — «una
    # semilla para el primer arranque, no un decreto».
    #
    # POR QUÉ. Sin llave, la tarjeta pinta la lista de la tabla y decía «usando X» con un
    # X que no estaba en esa lista. MEDIDO el 2026-08-13 sobre las seis vías sembradas:
    # **3 de 6** afirmaban usar un modelo ausente de la lista que ellas mismas mostraban
    # —`api.openai` decía `gpt-4o`, `api.mistral` decía `mistral-large-latest`—. Abrir una
    # lista de cinco Claudes mientras la card jura estar usando un sexto que no está es la
    # clase de contradicción que no se puede explicar mirando la pantalla.
    #
    # SÓLO CUANDO EL PROVEEDOR NO HABLÓ. Con catálogo vivo la semilla no se toca: el que
    # sabe qué modelos existen es él, y ahí el `declarado` original sigue de pista como
    # siempre (camino byte-idéntico). Y la elección del USUARIO le gana a las dos, incluso
    # si eligió algo que la tabla no conoce — la tabla son los principales, no todos, y no
    # saber nunca es motivo para pisarle una decisión suya.
    from app.phase1 import modelos_semilla as _semilla
    _sem = [f for f in _semilla.filas_de(slug) if _disc.servible(f)]
    _decl = _sem[0]["model_id"] if _sem else declarado
    _por = "semilla" if _sem else "declarado"

    if ref not in _disc.RUTAS:
        return _decl, None, _por
    try:
        #: `fresco=False` a propósito: el caché con la caducidad de F4c es el que decide si
        #: hay que salir a la red. Preguntar el catálogo entero en cada pintada del selector
        #: sería pagar red por un dato que cambia en días.
        cat = _disc.descubrir(ref, key=key)
    except Exception:                              # noqa: BLE001 — descubrir jamás rompe la pantalla
        return (eleccion or _decl), None, ("usuario" if eleccion else _por)
    if not cat.get("modelos"):
        # SIN CATÁLOGO NO HAY VEREDICTO (misma ley que `verificar_vigente`): no se puede
        # afirmar que la elección del usuario murió porque se cayó la red. Se sigue con lo
        # que había — descubrir es una mejora, no una dependencia (ley de F6).
        return (eleccion or _decl), cat, ("usuario" if eleccion else _por)
    elegido = _disc.elegir(cat, preferido=(eleccion or declarado))
    if not elegido:
        return None, cat, "ninguno"
    if eleccion and elegido == eleccion:
        return elegido, cat, "usuario"
    # Llegar acá con una `eleccion` puesta significa que `elegir()` NO la respetó, y sólo
    # hace eso cuando el id ya no está en el catálogo vivo. O sea: la elección del usuario
    # murió y se re-eligió sola. Sale como `catalogo`, no como `usuario` — decir «lo elegiste
    # vos» sobre un reemplazo automático es exactamente la mentira que este campo evita.
    if not eleccion and elegido == declarado:
        return elegido, cat, "declarado"
    return elegido, cat, "catalogo"


def _sondas_de(fila: dict, owner: Optional[str], get_conn) -> dict:
    """[F9] LAS SONDAS REALES DEL CHECKLIST — para que «Prueba de inferencia» PRUEBE.

    ⚠️ EL VERBO MENTÍA, y era la clase de mentira que este proyecto persigue. `correr()`
    acepta sondas desde F4c y su ÚNICO llamador las omitía, así que el verbo se resolvía con
    `fila.estado == "probado"`: leía el veredicto del PROVEEDOR y decía «Prueba de
    inferencia ✓». Prometía una generación y entregaba una lectura de un flag.

    Ahora corre la SONDA de F9 —`POST /chat/completions` con un parámetro inválido—: mide la
    ruta de GENERACIÓN de verdad, sin gastar un token y en ~160 ms.

    ⚠️ Y SE PERSISTE. Va por `MV.probar`, no por `veredicto_key` a secas: `probar` escribe el
    veredicto en el store con su EVIDENCIA y su FECHA. Sin eso el resultado viviría sólo en
    el SSE y la fila volvería a «sin probar» al recargar — o sea, el checklist diría que
    probó y la pantalla lo desmentiría treinta segundos después.

    Sólo la vía API tiene sonda. Las otras siguen resolviéndose con lo que la fila declara,
    que fue medido río arriba: un checklist que re-mide todo desde cero es más lento y no
    más honesto.
    """
    if str(fila.get("familia") or "") != API or not owner:
        return {}

    def _probar_inferencia():
        res = MV.probar(MV.KEY, str(fila.get("ref") or ""), owner=owner, force=True,
                        motivo="checklist_modelos", get_conn=get_conn)
        ev = res.get("evidencia") or {}
        if res.get("estado") == PROBADO:
            return True, None, ev.get("detail") or "la ruta de generación aceptó tu llave"
        return False, res.get("causa") or "fallo_desconocido", ev.get("detail") or ""

    return {"prueba": _probar_inferencia}


def _llaves_de_api(owner: Optional[str], get_conn) -> dict:
    """`{provider: secreto}` para los proveedores de API que tengan llave guardada.

    ⚠️ SE LEE UNA VEZ POR PINTADA, no una por fila: son ~8 filas de API y abrir la DB por
    cada una es pagar ocho veces lo mismo. Y el secreto NO entra en ninguna fila: sólo
    viaja hasta el header de `descubrir` y muere ahí.
    """
    if not owner or get_conn is None:
        return {}
    try:
        from app.phase1 import repo as _repo
        conn = get_conn()
        try:
            return {p: k for p in _disc.RUTAS
                    for k in [(_repo.get_key(conn, owner, p) or None)] if k}
        finally:
            conn.close()
    except Exception:                              # noqa: BLE001 — sin vault se descubre sin llave
        return {}


def _selector_de(v2: dict, contexto: Optional[str] = None,
                 todos: bool = False, llaves: Optional[dict] = None) -> dict:
    """`todos=True` [F7·B] = el CATÁLOGO COMPLETO del picker, no sólo el pool.

    El pool (default) es la ley del selector: conectados + Default, y nada más — es lo que
    la Sala ofrece para USAR ahora. Pero un picker de CONFIGURACIÓN (el del Cuarto) tiene
    que mostrar también lo que todavía no está configurado, con su estado real y su trámite;
    si no, el usuario no tiene dónde poner la llave y la pantalla termina inventando su
    propia lista — que es exactamente lo que hacía el Cuarto con 12 modelos hardcodeados.

    Las filas salen IGUAL en los dos modos: mismo `picker_id`, mismo `model`/`base_url`/
    `byok_ref` de `_PICKER_HOSTEADO`, mismo `estado`/`causa`/`hay_llave`/`prueba`. Lo único
    que cambia es a cuáles se les deja pasar.
    """
    pref = v2.get("preferencias") or {}
    default = pref.get("default")
    contexto = str(contexto or "").strip().casefold() or None
    if contexto in {"guía", "guide"}:
        contexto = "guia"
    filas_ = [
        f for f in v2.get("filas") or []
        if not f.get("hf") and (todos or f.get("conectado") or f.get("slug") == default)
    ]
    if contexto == "guia":
        filas_ = [f for f in filas_ if f.get("frontier")]
    out = []
    for f in filas_:
        row = dict(f)
        row.update(_PICKER_HOSTEADO.get(f.get("slug")) or {})
        # [F6-cierre · obra A] La vía API elige del catálogo VIVO, igual que la local de
        # abajo. El id de `_PICKER_HOSTEADO` entra como preferencia; si murió, se reemplaza.
        if str(f.get("familia") or "") == "api" and row.get("model"):
            _ref = str(f.get("slug") or "").split(".", 1)[-1]
            _eleccion = (pref.get("modelos") or {}).get(str(f.get("slug") or "")) or None
            _m, _cat, _origen = _modelo_de_api(str(f.get("slug") or ""), row.get("model"),
                                               key=(llaves or {}).get(_ref),
                                               eleccion=_eleccion)
            if _m:
                row["model"] = _m
            # ── [F8 · obra 2] QUÉ MODELO SE USA Y QUIÉN LO ELIGIÓ, EXPLÍCITO ──────────
            # `modelo_elegido: null` NO ES «no lo mandé»: es «lo busqué y no hay». La
            # distinción es la misma que `_toolsDeServidor` ya defiende («no medí» ≠ «medí y
            # dio cero»), y acá decide una causa: sin el null explícito, la superficie no
            # puede saber si esta fila no tiene modelo o si está mirando una fila vieja.
            row["modelo_elegido"] = _m or None
            row["modelo_elegido_por"] = _origen
            if not _m:
                # LA LLAVE ESTÁ Y AUN ASÍ NO HAY CON QUÉ PENSAR. Ni `falta_key` (la llave
                # está: mandar a ponerla otra vez es el trámite que ya hizo) ni un id
                # hardcodeado servido a ciegas. Se dice lo que pasa y se ofrece lo único que
                # lo resuelve: elegir uno. Causa SIN CULPA — no se equivocó nadie.
                row["estado"] = ROTO
                row["causa"] = MV.MODELO_NO_ELEGIDO     # del vocabulario, jamás un literal
                # NO se saca del pool: se queda visible y NO seleccionable, igual que el
                # Default caído. Esconderla haría desaparecer una vía que el usuario
                # configuró, sin decirle nunca por qué.
                row["conectado"] = False
            if _cat:
                # La fecha viaja a la superficie: una pantalla puede decir «catálogo de
                # hace 2 días» en vez de afirmar que es de ahora.
                row["catalogo"] = {"descubierto_en": _cat.get("descubierto_en"),
                                   "rancio": bool(_cat.get("rancio")),
                                   "fuente": _cat.get("fuente"),
                                   "modelos": len(_cat.get("modelos") or [])}
                # Matriz técnica del MODELO ELEGIDO, no de la marca. El catálogo ya
                # normaliza `texto/tools/vision/razonamiento`; acá sólo traducimos ese
                # vocabulario al contrato común. Si el proveedor no lo declara, no se
                # inventa soporte y una llamada que lo requiera falla antes de ejecutar.
                _elegido = next((m for m in (_cat.get("modelos") or [])
                                 if str(m.get("model_id") or "") == str(_m or "")), None)
                if _elegido:
                    _map_caps = {
                        "texto": "text", "tools": "tool_calling",
                        "vision": "vision", "razonamiento": "reasoning",
                    }
                    _caps = {
                        _map_caps[c] for c in (_elegido.get("capacidades") or [])
                        if c in _map_caps
                    }
                    # `streaming` NO ESTÁ EN EL CATÁLOGO y no es del modelo: es del
                    # TRANSPORTE. Ningún proveedor lo publica en su ficha porque el SSE lo
                    # da el endpoint, no los pesos. Sin esto, la matriz del catálogo —la
                    # buena, la que sabe qué modelo es— salía SIN streaming y quedaba por
                    # debajo del piso declarado arriba: descubrir el catálogo empeoraba la
                    # fila en vez de mejorarla. Se concede junto con `text`, que es donde
                    # el chat existe; a un modelo de embeddings no le corresponde.
                    if "text" in _caps:
                        _caps.add("streaming")
                    row["model_use_capabilities"] = sorted(_caps)
                    row["context_window"] = _elegido.get("context")
                    row["cost"] = {"free": _elegido.get("free")}
        if f.get("local"):
            row.update({
                "picker_id": "local:" + str(f.get("ref") or ""),
                "model": f.get("ollama_tag"),
                "base_url": "http://127.0.0.1:11434/v1",
                "alias": "oss-direct",
            })
            # La matriz sale de la prueba que se le corrió al descargarlo. Sin categoría no
            # se escribe nada: la fila queda SIN declarar y el resolver dice `capability_
            # unknown`, que es la verdad. Escribir `[]` diría «no puede nada», y no es lo
            # mismo que «no sabemos».
            _matriz_local = matriz_de_local(f.get("categoria"))
            if _matriz_local is not None:
                row["model_use_capabilities"] = _matriz_local
        out.append(row)
    seleccion_slug = (pref.get("contextos") or {}).get(contexto or "") or default
    if not any(f.get("slug") == seleccion_slug for f in out):
        # Una selección persistida puede haberse caído. No se cuela al pool: se usa el
        # Default sólo si el rol lo permite, y si no el primer conectado permitido.
        seleccion_slug = (
            default
            if any(f.get("slug") == default for f in out)
            else next((f.get("slug") for f in out if f.get("conectado")), None)
        )
    seleccion = next((f.get("picker_id") for f in out if f.get("slug") == seleccion_slug), None)
    return {
        "version": 2, "modelos": out, "default": default,
        "default_id": next((f.get("picker_id") for f in out if f.get("slug") == default), None),
        "default_estado": pref.get("default_estado"),
        "default_caido": pref.get("default_caido"),
        "seleccion": seleccion_slug, "seleccion_id": seleccion,
        "contexto": contexto, "contextos": pref.get("contextos") or {},
        "regla": "conectados+default" + (" ∩ frontier" if contexto == "guia" else ""),
        "ts": time.time(),
    }


def selector_modelos(owner: Optional[str] = None, get_conn=None,
                     contexto: Optional[str] = None, todos: bool = False,
                     ttl_cli: Optional[float] = None) -> dict:
    """Selector liviano: no consulta HF; sólo inventario/conexiones y el Default.

    `ttl_cli` — CUÁNTO VALE EL ÚLTIMO SONDEO DE LOS CLI. `None` = el de siempre
    (`DETECT_TTL`, 20 s): es lo que usa LA CARA, y tiene que seguir así porque el picker
    muestra estado y un estado viejo ahí es una mentira que el usuario lee.

    EL CAMINO DEL TURNO pasa uno largo, y la razón es medida: sondear los tres CLI cuesta
    **2.172 ms**, y con 20 s de TTL cualquier persona que tarde más de eso en escribir el
    mensaje siguiente lo paga ENTERO, en el peor lugar — antes de que el modelo arranque.
    Medido en la .app instalada: 3.451 ms de los 6.200 pre-CLI eran esto.

    Y no se pierde ninguna verdad: el turno NO necesita saber si el CLI está vivo, necesita
    resolver CUÁL es. Si resulta que está caído, quien lo descubre es el turno mismo, y esa
    causa ya llega con copy propia a la pantalla (lo vimos: «Falló: Grok · rate-limited»,
    con el botón para usar el otro). Preguntarlo antes no lo evita: lo cobra dos veces.
    """
    # ⚠️ SIN `ttl_cli` LA LLAMADA QUEDA BYTE-IDÉNTICA A LA DE ANTES. No es cosmético: las
    # varas sustituyen `cli_sesiones` por un doble sin kwargs, y pasarle uno que no espera
    # las rompe — dos rojas, medidas. Un parámetro nuevo no puede cambiarle la firma a los
    # llamadores que no lo usan.
    _ses = cli_sesiones() if ttl_cli is None else cli_sesiones(ttl=ttl_cli)
    base = _anotar_memoria(
        _anotar_conectados(filas(owner=owner, get_conn=get_conn), _ses),
        owner, get_conn)
    pref = _preferencias_normalizadas(base.get("filas") or [], owner=owner)
    for f in base.get("filas") or []:
        f["default"] = f.get("slug") == pref.get("default")
    return _selector_de({"filas": base.get("filas") or [], "preferencias": pref},
                        contexto, todos, llaves=_llaves_de_api(owner, get_conn))


# ══════════════════════════════════════════════════════════════════════════════════
# §10 · EL ROUTER
# ══════════════════════════════════════════════════════════════════════════════════
def _sse(gen: Iterator[dict]) -> StreamingResponse:
    def cuerpo():
        try:
            for ev in gen:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:      # jamás una espera muda: si el generador muere, se dice
            yield f"data: {json.dumps({'tipo': 'fin', 'estado': ROTO, 'causa': MV.ERROR_UPSTREAM, 'detalle': str(e)})}\n\n"
        yield "data: {\"tipo\": \"cerrado\"}\n\n"
    return StreamingResponse(cuerpo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def build_modelos_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    r = APIRouter(prefix="/v1/modelos", tags=["modelos"])

    def _owner(authorization: Optional[str]) -> Optional[str]:
        """El dueño de la sesión, si hay Bearer — MISMO resolvedor que el Centro de
        Conexiones. Sin sesión NO se rompe: la pantalla se pinta igual y las filas dicen
        la verdad («sin configurar»), que es exactamente lo que pasa."""
        try:
            return MV._owner_from_session(authorization)
        except Exception:
            return None

    @r.get("")
    def _filas(authorization: Optional[str] = Header(default=None)):
        """La pantalla: filas + grupos + las 5 categorías + el veredicto de tu máquina."""
        return filas(owner=_owner(authorization), get_conn=get_conn)

    @r.post("/checklist")
    def _checklist(cuerpo: dict = Body(default={}),
                   authorization: Optional[str] = Header(default=None)):
        """[F4c · obra 4] EL CHECKLIST VIVO: los verbos completándose por SSE.

        Mismos nombres de evento que `POST /v1/conexiones/checklist` (Gate 1) — así el
        cliente SSE de `conectores/fuentes.js::checklistEnVivo` sirve tal cual y no hay un
        segundo dialecto que mantener.

        El spinner mudo era el problema: se apretaba [Probar] y no pasaba nada visible
        hasta que la fila cambiaba (o no). Ahora se ve QUÉ está corriendo y, si falla, EN
        QUÉ VERBO — que es el dato que convierte «no anduvo» en algo accionable.
        """
        from fastapi.responses import StreamingResponse
        from app.phase1 import modelos_checklist as _CK
        refs = [str(x) for x in (cuerpo.get("refs") or cuerpo.get("slugs") or []) if x]
        _own = _owner(authorization)
        base = filas(owner=_own, get_conn=get_conn)
        porref = {f.get("ref"): f for f in (base.get("filas") or [])}

        def _gen():
            for ref in refs:
                fila = porref.get(ref)
                if fila is None:
                    # NO se inventa una fila. Si el modelo no está en el catálogo de este
                    # usuario, se dice — con su nombre — en vez de correr un checklist
                    # sobre la nada y cerrarlo en verde.
                    yield ("data: {\"tipo\": \"fila.cerrada\", \"ref\": "
                           + __import__("json").dumps(ref)
                           + ", \"ok\": false, \"causa\": \"modelo_no_disponible\"}\n\n")
                    continue
                yield from _CK.sse(_CK.correr(fila, sondas=_sondas_de(fila, _own, get_conn)))

        return StreamingResponse(_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @r.get("/v2")
    def _filas_v2(authorization: Optional[str] = Header(default=None),
                  limite_hf: int = Query(2, ge=1, le=6),
                  formato: Optional[str] = None):
        """Lote V2 único: TODAS las filas; cada HF ya trae peso/RAM/veredicto."""
        return filas_v2(owner=_owner(authorization), get_conn=get_conn,
                        limite_hf=limite_hf, formato=formato)

    @r.get("/catalogo/lote")
    def _catalogo_lote(categorias: Optional[str] = None,
                       limite: int = Query(2, ge=1, le=6),
                       formato: Optional[str] = None):
        """Batch HF explícito: N filas con peso/RAM/veredicto en UNA request al sidecar.

        `categorias` acepta ids separados por coma. HF se usa sólo como catálogo y
        descarga local; este endpoint jamás ofrece ni valida Inference API.
        """
        cats = (
            [c.strip() for c in categorias.split(",") if c.strip()]
            if categorias is not None
            else None
        )
        return catalogo_hf_lote(categorias=cats, formato=formato, limite=limite)

    @r.get("/selector")
    def _selector(contexto: Optional[str] = None, todos: int = 0,
                  authorization: Optional[str] = Header(default=None)):
        """Pool compartido: sólo Conectados + Default; Guía además exige frontier.

        `todos=1` [F7·B] devuelve el CATÁLOGO COMPLETO con la misma forma — para un picker
        de CONFIGURACIÓN, que necesita mostrar lo no configurado con su trámite. El pool
        sigue siendo el default: nadie que pida el pool recibe de más."""
        return selector_modelos(owner=_owner(authorization), get_conn=get_conn,
                                contexto=contexto, todos=bool(todos))

    @r.get("/preferencias")
    def _preferencias(authorization: Optional[str] = Header(default=None)):
        base = _anotar_conectados(
            filas(owner=_owner(authorization), get_conn=get_conn), cli_sesiones())
        return _preferencias_normalizadas(base.get("filas") or [], owner=_owner(authorization))

    @r.put("/preferencias")
    def _guardar_preferencias(cuerpo: dict = Body(...),
                              authorization: Optional[str] = Header(default=None)):
        _own = _owner(authorization)
        base = _anotar_conectados(filas(owner=_own, get_conn=get_conn), cli_sesiones())
        # [F8·obra 2] Las llaves viajan porque validar «ese modelo existe» exige el catálogo
        # del proveedor, y 7 de los 8 no publican catálogo sin credencial (medido en obra 1).
        return guardar_preferencias(cuerpo, base.get("filas") or [],
                                    llaves=_llaves_de_api(_own, get_conn), owner=_own)

    @r.get("/proveedor/{slug}/catalogo")
    def _catalogo_proveedor(slug: str, fresco: int = 0,
                            authorization: Optional[str] = Header(default=None)):
        """[F8 · obra 2] EL CATÁLOGO DE UN PROVEEDOR, para que el usuario pueda elegir.

        Persistir una elección que no se puede hacer es media función: éste es el otro lado
        del `PUT /preferencias {slug, modelo}`. Devuelve la forma de §11 tal como la dejó
        `modelos_discovery` —`model_id · label · context · capacidades · free`— más quién
        está elegido hoy y por quién, que es lo que el picker necesita para marcar la fila.

        No hay una rama por proveedor: el slug entra a la MISMA tabla declarada (`RUTAS`).
        Un slug que no sea de la vía API sale 409 con su motivo, jamás una lista vacía que
        se lea como «este proveedor no tiene modelos».
        """
        _own = _owner(authorization)
        base = _anotar_conectados(filas(owner=_own, get_conn=get_conn), cli_sesiones())
        _filas = base.get("filas") or []
        f = next((x for x in _filas if x.get("slug") == slug), None)
        if f is None:
            raise HTTPException(status_code=404, detail="esa vía no existe")
        if str(f.get("familia") or "") != API:
            raise HTTPException(status_code=409,
                                detail="sólo una vía de API tiene modelos para elegir")
        ref = str(slug).split(".", 1)[-1]
        pref = _preferencias_normalizadas(_filas, owner=_own)
        eleccion = (pref.get("modelos") or {}).get(slug) or None
        # UNA sola lectura del vault por request — la misma regla que `_llaves_de_api`
        # declara para la pintada: abrir la DB una vez por uso es pagar N veces lo mismo.
        key = _llaves_de_api(_own, get_conn).get(ref)
        cat = _disc.descubrir(ref, key=key, fresco=bool(fresco))
        # LA SEMILLA, y SÓLO si el proveedor no dijo nada. Sin llave estas vías devuelven
        # cero filas y la tarjeta quedaba muda — y una lista vacía no distingue «este
        # proveedor no tiene modelos» de «no se pudo traer». La semilla nunca le gana al
        # vivo ni se mezcla con él: o están las medidas, o está ella, marcada fila por
        # fila. La `causa` se conserva: mostrar la lista no cura la llave que falta.
        from app.phase1 import modelos_semilla as _semilla
        # EL DETECTOR DE VEJEZ, ANTES DE SEMBRAR y sólo si el proveedor habló. Acá es el
        # único lugar donde la tabla y el catálogo vivo están sobre la mesa al mismo
        # tiempo, así que contrastarlos no cuesta una sola request: el dato ya vino por
        # otro motivo. No salimos a preguntarle a nadie — la tabla se audita sola el día
        # que el usuario conecta su llave.
        _contraste = _semilla.contrastar(cat, slug)
        _semilla.registrar(_contraste)
        cat = _semilla.sembrar(cat, slug)
        # El origen se calcula con la MISMA función que pinta la fila. Dos resolvedores del
        # «qué modelo se usa» es cómo se llega a que el picker marque uno y la card diga otro.
        usando, _c, origen = _modelo_de_api(slug, (_PICKER_HOSTEADO.get(slug) or {}).get("model"),
                                            key=key, eleccion=eleccion)
        return {
            "slug": slug, "ref": ref, "label": f.get("label"),
            # [F9] `servible` VIAJA CON CADA FILA. El picker no puede ofrecer lo que esta
            # misma request va a rechazar en el PUT: sería mandar a la persona a un error
            # que la pantalla ya sabía. No se OCULTAN —el catálogo del proveedor es lo que
            # es, y esconder filas haría que la lista no coincida con la del proveedor—: se
            # marcan, con el mismo criterio que decide el rechazo (`_disc.servible`).
            # `motivo` viaja SÓLO para lo que no sirve, y sale de la MISMA función que
            # redacta el rechazo: la pantalla dice exactamente lo que diría el 409 si se
            # apretara. Dos redacciones del mismo «no» es cómo se llega a que la UI prometa
            # una cosa y el backend conteste otra.
            "modelos": [{**m, "servible": _disc.servible(m),
                         **({} if _disc.servible(m)
                            else {"motivo": _disc.motivo_no_servible(m)})}
                        for m in (cat.get("modelos") or [])],
            "usando": usando, "elegido_por": origen, "eleccion_del_usuario": eleccion,
            # La fecha y la fuente viajan para que el picker pueda decir «catálogo de hace 2
            # días» en vez de afirmar que es de ahora — misma regla que la fila.
            "descubierto_en": cat.get("descubierto_en"), "fuente": cat.get("fuente"),
            "rancio": bool(cat.get("rancio")), "causa": cat.get("causa"),
            # El contraste viaja SÓLO cuando encontró algo: mandar `al_dia: true` en cada
            # respuesta le daría a la pantalla un cartel verde que nadie pidió. Lo que la
            # superficie tiene que poder decir es cuándo la tabla FALLÓ.
            **({"semilla_contraste": _contraste}
               if _contraste and not _contraste.get("al_dia") else {}),
        }

    @r.get("/cli/sesiones")
    def _cli_sesiones():
        """Detección viva + último snapshot público; nunca tokens ni paths de binario."""
        return cli_sesiones(fresco=True)

    @r.get("/maquina")
    def _maquina():
        """Disco, RAM y qué runtimes existen DE VERDAD en esta máquina."""
        return _con_default(maquina())

    @r.get("/semilla/contrastes")
    def _semilla_contrastes():
        """Qué le erró la tabla curada, la última vez que cada proveedor habló.

        ⚠️ EXISTE PARA QUE EL REGISTRO NO SEA DE ESCRITURA SOLA. `registrar()` deja el
        veredicto en disco por vía; sin esta puerta ese archivo sería un log que nadie
        abre, que es la misma nada que no escribirlo — con el costo extra de parecer que
        alguien vigila.

        Lo que se ve en la tarjeta es el contraste de ESE proveedor y sólo mientras se
        mira. Esto es la foto de todos juntos, que es la pregunta del que mantiene la
        tabla: «¿qué hay que arreglar?». Público como el resto del catálogo: no dice nada
        del usuario, dice de nuestro archivo.

        Una vía que nunca se contrastó NO aparece — no tener veredicto no es estar al día,
        y listarla en cero la haría pasar por verificada.
        """
        from app.phase1 import modelos_semilla as _semilla
        partes = _semilla.contrastes()
        return {
            "contrastes": partes,
            "vias_contrastadas": len(partes),
            "vias_con_hallazgos": sum(1 for p in partes if not p.get("al_dia")),
            "muertos": sum(len(p.get("muertos") or []) for p in partes),
            "distintos": sum(len(p.get("distintos") or []) for p in partes),
        }

    @r.get("/catalogo")
    def _catalogo(categoria: str = Query(...), formato: Optional[str] = None,
                  limite: int = Query(8, ge=1, le=24)):
        """El catálogo VIVO de Hugging Face por categoría. Sin red → `red:false` + causa."""
        return catalogo_hf(categoria, formato, limite)

    @r.get("/instalados")
    def _instalados():
        """Lo que YA está en tu máquina. No toca la red: existe aunque el mundo se caiga."""
        return instalados()

    @r.post("/descargar")
    def _descargar(cuerpo: dict = Body(...)):
        """Descarga guiada por SSE: veredicto → progreso → instalar → PRUEBA → fin."""
        hf_id = str(cuerpo.get("hf_id") or "").strip()
        archivo = str(cuerpo.get("archivo") or "").strip()
        if not hf_id or not archivo:
            raise HTTPException(status_code=400, detail="faltan hf_id y archivo")
        if not re.match(r"^[\w.\-]+/[\w.\-]+$", hf_id):
            raise HTTPException(status_code=400, detail="hf_id con forma inválida")
        if ".." in archivo or archivo.startswith("/"):
            raise HTTPException(status_code=400, detail="archivo con forma inválida")
        archivos = [str(x) for x in (cuerpo.get("archivos") or [archivo])
                    if x and ".." not in str(x) and not str(x).startswith("/")]
        job = Descarga(
            slug=slug_de(hf_id), hf_id=hf_id, archivo=archivo, archivos=archivos,
            formato=str(cuerpo.get("formato") or "gguf"),
            categoria=cuerpo.get("categoria"),
            peso_gb=(float(cuerpo["peso_gb"]) if cuerpo.get("peso_gb") else None),
            tier=cuerpo.get("tier"))
        with _lock:
            viejo = _trabajos.get(job.slug)
            # Apretar «Descargar» otra vez es una orden, no un error. Si quedó un trabajo
            # VIVO se lo cancela y se toma el relevo (el `.part` lo limpia su propio
            # camino); si el de antes ya estaba muerto, no bloquea nada. Devolver 409 acá
            # convertía un cable cortado en una pantalla que no se recupera nunca.
            if viejo and viejo.viva:
                viejo.cancelar.set()
            _trabajos[job.slug] = job
        return _sse(descargar(job))

    @r.post("/cancelar")
    def _cancelar(cuerpo: dict = Body(...)):
        """Cortar la descarga Y limpiar. El `.part` no sobrevive a un cancel."""
        slug = str(cuerpo.get("slug") or "")
        job = _trabajos.get(slug)
        if not job:
            raise HTTPException(status_code=404, detail="no hay descarga con ese slug")
        job.cancelar.set()
        return {"cancelado": True, "slug": slug, "estado": job.estado}

    @r.get("/descarga/{slug}")
    def _estado_descarga(slug: str):
        job = _trabajos.get(slug)
        if not job:
            raise HTTPException(status_code=404, detail="no hay descarga con ese slug")
        return job.instantanea()

    @r.post("/probar")
    def _probar(cuerpo: dict = Body(...),
                authorization: Optional[str] = Header(default=None)):
        """La prueba automática, a pedido. Corre el modelo; jamás declara.

        ⚠️ ESTO LLAMABA A `probar_local` PARA TODO SLUG, y era un rojo falso para cualquier
        vía que no fuera local. `probar_local` sin `tag` de ollama sale por `SIN_RUNTIME`
        con «no quedó registrado en ollama» — una causa que para una API o un CLI no
        significa NADA. Medido sobre la app instalada, las cuatro daban lo mismo:

            api.groq · api.openrouter · api.anthropic · cli.codex_cli
              → roto · sin_runtime · «no quedó registrado en ollama»

        …y dos de ellas (openrouter, codex_cli) figuran `probado` y `conectado` en el pool,
        porque ese estado lo escribe OTRO camino. O sea: la única puerta que la UI ofrece
        para «probar ahora» contradecía al propio catálogo.

        LA CONSECUENCIA NO ERA COSMÉTICA. Una vía de API con llave guardada queda en
        `detectado` («la tengo, no la probé») y **nunca podía pasar a `probado`**, porque su
        única puerta la mandaba a ollama. Por eso `api.groq` tenía llave en el vault y seguía
        fuera de `conectados`, y `preferencias.default` apuntaba a una vía que no podía
        verificar jamás.

        EL ARREGLO NO INVENTA NADA: despacha por familia con `correr_checklist`, que ya
        existe y ya sabe de `incluido`/`cli`/`api`, y colapsa con `_estado_fila`, que ya
        habla los 5 estados del motor. **El diccionario no se toca**: `sin_runtime` deja de
        aplicarse donde no corresponde y cada vía usa la causa que ya tenía —`key_invalida`,
        `sin_credito`, `rate_limit`— que son las que distinguen un problema de la CUENTA del
        usuario de un defecto nuestro.
        """
        slug = str(cuerpo.get("slug") or "")
        if not slug:
            raise HTTPException(status_code=400, detail="falta slug")
        familia, _, ref = slug.partition(".")
        # Un slug sin familia (o `local.*`) sigue por donde iba: correr el modelo de verdad.
        if not ref or familia == LOCAL:
            return probar_local(slug, tag=cuerpo.get("tag"), categoria=cuerpo.get("categoria"))
        if familia == CLI:
            return _probar_cli(slug, ref)
        from app.phase1 import centro_conexiones as CX
        t0 = time.time()
        try:
            reqs = list(CX.correr_checklist(familia, ref, owner=_owner(authorization),
                                            get_conn=get_conn, profundo=True))
        except HTTPException:
            raise
        except Exception as ex:  # noqa: BLE001 — la prueba no puede tumbar el Centro
            # LA TRAZA VA A LA EVIDENCIA, NUNCA AL DETALLE. El detalle lo lee un humano en
            # la pantalla, y un `AttributeError` de Python ahí es la causa técnica cruda que
            # esta casa tiene prohibido mostrar.
            logging.getLogger(__name__).warning(
                "modelos.probar falló para %s: %r", slug, ex)
            return _res(slug, ROTO, causa=MV.ERROR_UPSTREAM,
                        detalle="no pude comprobar esta vía en este momento",
                        evidencia={"excepcion": f"{type(ex).__name__}: {ex}"[:300]})
        estado, causa = CX._estado_fila(reqs)
        # EL DETALLE SALE DEL REQUISITO QUE FALLÓ, no de una frase escrita acá: es el mismo
        # texto que el checklist ya le muestra al usuario, y así las dos superficies no
        # pueden decir cosas distintas del mismo hecho.
        roto = next((q for q in reqs if q.get("estado") == CX.ROTO), None)
        detalle = str((roto or {}).get("detalle") or (roto or {}).get("titulo") or "")
        if not detalle and estado == PROBADO:
            hechos = sum(1 for q in reqs if q.get("estado") == CX.HECHO)
            detalle = f"la vía respondió: {hechos} de {len(reqs)} requisitos comprobados"
        return _res(slug, estado, causa=causa, ms=int((time.time() - t0) * 1000),
                    detalle=detalle,
                    evidencia={"requisitos": [
                        {"id": q.get("id"), "estado": q.get("estado"), "causa": q.get("causa")}
                        for q in reqs]})

    @r.delete("/local/{slug}")
    def _borrar(slug: str):
        """Liberar espacio: borra el archivo, la carpeta y el registro del runtime."""
        return borrar_local(slug)

    @r.get("/gate")
    def _gate(pieza: str = Query(...), slug: str = "", tier: Optional[str] = None,
              categoria: Optional[str] = None, familia: str = LOCAL):
        """¿Este modelo alcanza para esta pieza? Con porqué, recomendación y camino."""
        return gate(pieza, slug=slug, tier=tier, categoria=categoria, familia=familia)

    @r.get("/avatar/{org}")
    def _avatar(org: str):
        """La cara de una organización de HF, SIEMPRE del cache.

        Se puebla AL DESCARGAR (`?refrescar=1`), nunca en caliente: una lista de 8
        modelos no puede disparar 8 fetch a un tercero mientras alguien mira la pantalla.
        Sin cache → 404 y el front dibuja `serviceFace` (iniciales + color determinista)."""
        if not re.match(r"^[\w.\-]{1,64}$", org):
            raise HTTPException(status_code=400, detail="org inválida")
        p = modelos_dir() / "avatares" / f"{org}.png"
        if p.exists():
            return Response(p.read_bytes(), media_type="image/png",
                            headers={"X-Aleph-Icon-Source": "cache",
                                     "Cache-Control": "public, max-age=86400"})
        return JSONResponse(status_code=404, content={"cara": False, "org": org,
                                                      "detalle": "sin avatar cacheado — usa serviceFace"})

    @r.post("/avatar/{org}")
    def _cachear_avatar(org: str):
        """Cachea el avatar de una org. Se llama AL DESCARGAR, no al listar."""
        if not re.match(r"^[\w.\-]{1,64}$", org):
            raise HTTPException(status_code=400, detail="org inválida")
        destino = modelos_dir() / "avatares"
        destino.mkdir(parents=True, exist_ok=True)
        p = destino / f"{org}.png"
        if p.exists():
            return {"cacheado": True, "ya_estaba": True, "org": org}
        try:
            info = _hf_get(f"/api/organizations/{org}/overview", [])
            url = (info or {}).get("avatarUrl") or ""
            if not url:
                return {"cacheado": False, "org": org, "detalle": "la org no publica avatar"}
            if url.startswith("/"):
                url = _HF_API + url
            req = urllib.request.Request(url, headers={"User-Agent": "Aleph/1.0"})
            with urllib.request.urlopen(req, timeout=10) as rr:
                datos = rr.read(400_000)
            p.write_bytes(datos)
            return {"cacheado": True, "org": org, "bytes": len(datos)}
        except Exception as e:
            return {"cacheado": False, "org": org, "detalle": str(e)}

    return r


__all__ = [
    "build_modelos_router", "maquina", "veredicto", "catalogo_hf", "instalados",
    "descargar", "instalar", "probar_local", "borrar_local", "gate", "filas",
    "filas_v2", "catalogo_hf_lote", "selector_modelos", "cli_sesiones",
    "guardar_preferencias",
    "CATEGORIAS", "GRUPOS", "PIEZAS", "TIERS", "CAUSAS", "CAUSAS_MODELO",
    "FRONTIER_SLUGS", "tier_alcanza", "tier_por_peso", "formatos_preferidos",
    "Descarga", "slug_de", "modelos_dir",
]
