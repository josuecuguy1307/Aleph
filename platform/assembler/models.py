#!/usr/bin/env python3
"""
models.py — LA ABSTRACCIÓN DE MODELOS de Aleph (T5 · dueño del assembler + gateway).

UN solo lugar decide qué modelo corre, por qué endpoint, con qué key y a qué precio.
La receta referencia un ALIAS PORTABLE (model.alias) en vez de hornear el id + base_url
del proveedor. Así "cambiar de modelo = 1 línea" se cumple de verdad — y se cumple en
TRES niveles de configuración:

  1) env  PUPPET_BRAIN=<alias>   → cambia el cerebro en desarrollo; en cliente,
     una elección explícita de la persona tiene prioridad.
  2) DEFAULT_BRAIN (esta línea)  → a qué apunta el alias 'brain' por defecto.
  3) ALIASES['<alias>']          → redefine modelo/endpoint/fallback de un alias puntual.

Cada cambio de ruta queda declarado en la identidad del run.

BACK-COMPAT (no rompe nada): una receta con model.primary + model.base_url explícitos
sigue corriendo idéntica. El alias es ADITIVO; si la receta no trae alias ni hay
PUPPET_BRAIN, se usa lo que la receta declare, como siempre.

CEREBRO E2E (brief §3): el cerebro premium por defecto es Opus 4.8. Dos caminos a Opus
REAL, elegidos por env (C6):
  - PROD (default, contrato congelado v1): OpenRouter (anthropic/claude-opus-4.8) con
    crédito.
  - DEV  (PUPPET_BRAIN_SHIM=1): un shim OpenAI-compat local en :8923 (brain_shim.py, o el
    proxy de Claude Code) sirve Opus real SIN crédito de OpenRouter. Ver §DEV SHIM SEAM.
Si el brain no responde (OpenRouter 402 sin crédito / shim caído), el cascade del assembler
(primary → fallback → oss-direct) cae al OSS de Groq y el run COMPLETA igual — PERO esa
caída YA NO es silenciosa: se SURFACEA como `record["degraded"]` + un cost-event/aviso
"degradado a fallback" (recipe_assembler._emit_model_cost_event). Nunca más un qwen
haciéndose pasar por el cerebro. "Opus por defecto", visible cuando no lo es.

PRECIO: lo MEDIDO es el token (viene del campo `usage` del response del proveedor); el
PRECIO es una CONSTANTE DOCUMENTADA por modelo. Si un modelo no tiene tarifa documentada,
el usd queda None — NO se inventa (mismo principio que instrumentation.py). Agregar una
tarifa = una entrada en PRICES con su fuente.

Stdlib only. Pura: sin red, sin side-effects (salvo leer os.environ para overrides/endpoints).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# ── ENDPOINTS (OpenAI-compatible /chat/completions) ─────────────────────────────
GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# Gemini OpenAI-compat: configurable por infra/.env (GEMINI_API_BASE); default público.
GEMINI_BASE = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai"
)
# OSS-directo local (la red de seguridad del assembler). Mismo default que recipe_assembler.
OLLAMA_BASE = os.environ.get("PUPPET_OSS_DIRECT_BASE_URL", "http://127.0.0.1:11434/v1")


# ── DEV SHIM SEAM (C6) — Opus 4.8 real en dev sin crédito de OpenRouter ──────────
# El cerebro del producto es Opus 4.8 real. En PROD el camino es OpenRouter con crédito
# (contrato congelado v1: ver test_models 1.1–1.4 + CONTRACT-RECIPE §3). En DEV no hay
# crédito (OpenRouter → 402), así que el camino a Opus REAL es un SHIM local OpenAI-compat
# en :8923 (brain_shim.py en este repo, o el proxy de Claude Code ya levantado). Encendés
# el shim para el brain con PUPPET_BRAIN_SHIM=1; o pisás base_url/model/key punto-a-punto.
# SIN ninguna env → EXACTAMENTE el contrato congelado (OpenRouter Opus, tests verdes, prod
# intacto). El cascade OSS sigue DEBAJO en ambos caminos, y su disparo se SURFACEA (no
# silencioso). Pivot de 1 línea, aditivo, reversible.
BRAIN_SHIM_BASE = os.environ.get("PUPPET_BRAIN_SHIM_BASE_URL", "http://127.0.0.1:8923/v1")
BRAIN_SHIM_MODEL = os.environ.get("PUPPET_BRAIN_SHIM_MODEL", "claude-opus-4.8")
_BRAIN_SHIM_ON = os.environ.get("PUPPET_BRAIN_SHIM", "") not in ("", "0", "false", "False", "no")

# Campos efectivos del alias 'brain' (computados una vez, leídos por ALIASES más abajo).
# Default (shim OFF) = el contrato congelado v1, byte por byte. Overrides finos por env.
_BRAIN_BASE = os.environ.get("PUPPET_BRAIN_BASE_URL") or (BRAIN_SHIM_BASE if _BRAIN_SHIM_ON else OPENROUTER_BASE)
_BRAIN_MODEL = os.environ.get("PUPPET_BRAIN_MODEL") or (BRAIN_SHIM_MODEL if _BRAIN_SHIM_ON else "anthropic/claude-opus-4.8")
# El shim local no necesita auth (localhost); OpenRouter sí. Override: PUPPET_BRAIN_KEY_ENV.
_BRAIN_KEY_ENV = os.environ.get("PUPPET_BRAIN_KEY_ENV") or (None if _BRAIN_SHIM_ON else "OPENROUTER_API_KEY")


# ── BYO-CLI SEAM (D1/D3) — el CLI del USUARIO como cerebro por suscripción ───────
# El usuario elige "Mi Claude Code" o "Mi Codex" en el Cuarto (recipe.model.brain_provider)
# y su CLI local YA AUTENTICADO piensa por su suscripción — cero API metered. El server
# local cli_brain (:8926, platform/assembler/cli_brain/server.py) envuelve ambos CLIs con
# las tools OFF (pura cognición) y reporta el model_final REAL. Aleph jamás ve/guarda
# tokens de la suscripción (la única interacción con el auth es `auth status`/`login
# status`). Aditivo: sin brain_provider en la receta → comportamiento byte-idéntico.
CLI_BRAIN_BASE = os.environ.get("PUPPET_CLI_BRAIN_BASE_URL", "http://127.0.0.1:8926/v1")


# Sidecar sin paquete: mismos dos ids que el registro declara. No es una tercera lista
# de producto — se usa SOLO si `cli_brain.registry` no importó.
_CLI_IDS_FALLBACK = tuple(p + "_cli" for p in ("claude", "codex"))  # E1-FALLBACK


def _cli_specs():
    """Lee el registro único. Fallback idéntico al histórico si el paquete no viajó."""
    try:
        from cli_brain.registry import specs as _specs
        return _specs()
    except Exception:
        return ()


class _CliIds:
    """Vista viva de registry.provider_ids. `in` / iter siguen funcionando."""

    def __iter__(self):
        ids = tuple(s.provider_id for s in _cli_specs())
        return iter(ids or _CLI_IDS_FALLBACK)  # E1-FALLBACK

    def __contains__(self, item):
        ids = tuple(s.provider_id for s in _cli_specs())
        return item in (ids or _CLI_IDS_FALLBACK)  # E1-FALLBACK

    def __eq__(self, other):
        return tuple(self) == tuple(other)

    def __bool__(self):
        return True


CLI_BRAIN_PROVIDERS = _CliIds()


# ── EL CEREBRO POR DEFECTO — cambiar el modelo del fleet e2e = ESTA línea ───────
DEFAULT_BRAIN = "brain"


# ── REGISTRO DE ALIASES ─────────────────────────────────────────────────────────
# alias -> {model, base_url, key_env, fallback}
#   model    : id que el endpoint espera en payload["model"].
#   base_url : endpoint OpenAI-compat (sin /chat/completions; el _chat lo agrega).
#   key_env  : nombre de la env var con la bearer key (None = endpoint sin auth, p.ej. ollama).
#   fallback : alias o id al que escalar si este FALLA por transporte/gateway (no por tarea).
ALIASES: dict[str, dict] = {
    # CEREBRO PREMIUM e2e — Opus 4.8 REAL, con red OSS de Groq por debajo.
    # Camino resuelto por env (ver §DEV SHIM SEAM): default OpenRouter (prod, contrato v1);
    # con PUPPET_BRAIN_SHIM=1 → shim local :8923 (dev, Opus real sin crédito). 1-línea para
    # apuntarlo a otro modelo: PUPPET_BRAIN_MODEL/_BASE_URL, o cambiá 'model' acá.
    "brain": {
        "model": _BRAIN_MODEL,
        "base_url": _BRAIN_BASE,
        "key_env": _BRAIN_KEY_ENV,
        "fallback": "oss",            # si el brain no responde → OSS Groq → (assembler) ollama
    },
    # PREMIUM OSS — Leads/Reviewers/Supervisor del workforce (Groq llama-70b).
    "premium": {
        "model": "llama-3.3-70b-versatile",
        "base_url": GROQ_BASE,
        "key_env": "GROQ_API_KEY",
        "fallback": None,
    },
    # OSS-FIRST canónico del path (el músculo barato que SÍ completa e2e con tarifa real).
    "oss": {
        "model": "openai/gpt-oss-120b",
        "base_url": GROQ_BASE,
        "key_env": "GROQ_API_KEY",
        "fallback": "premium",
    },
    # OSS DÉBIL (8b) — synth chico que alucina más; lo usa el gate del loop de inspección
    # para EJERCITAR el candado §5 en vivo (un modelo que sí propone endpoints inexistentes).
    "oss-weak": {
        "model": "llama-3.1-8b-instant",
        "base_url": GROQ_BASE,
        "key_env": "GROQ_API_KEY",
        "fallback": "premium",
    },
    # Constructor (código directo, sin tokens de reasoning).
    "constructor-code": {
        "model": "openai/gpt-oss-120b",
        "base_url": GROQ_BASE,
        "key_env": "GROQ_API_KEY",
        "fallback": "premium",
    },
    # Explorer (razonamiento <think> para tareas abiertas).
    "explorer-reason": {
        "model": "qwen/qwen3-32b",
        "base_url": GROQ_BASE,
        "key_env": "GROQ_API_KEY",
        "fallback": "premium",
    },
    # Multimodal (visión). El vision_router ya lo usa por endpoint; acá como alias nombrable.
    "vision": {
        "model": "gemini-2.5-flash",
        "base_url": GEMINI_BASE,
        "key_env": "GEMINI_API_KEY",
        "fallback": None,
    },
    # OSS-DIRECTO LOCAL — la red de seguridad última (ollama, $0, sin auth).
    "oss-direct": {
        "model": os.environ.get("PUPPET_OSS_DIRECT_MODEL", "qwen3:8b"),
        "base_url": OLLAMA_BASE,
        "key_env": None,
        "fallback": None,
    },
}


# ── TARIFAS PUBLICADAS (constantes documentadas, NO estimadas) ──────────────────
# usd por 1M tokens (input, output). Solo modelos con tarifa que podemos sostener con
# fuente. Lo que no está acá → usd None (honesto: medimos el token, no inventamos precio).
# Para agregar una tarifa nueva: una línea {model_id: (in, out, "fuente")}.
PRICES: dict[str, tuple[float, float, str]] = {
    # Groq gpt-oss-120b — la tarifa canónica ya usada en instrumentation.py.
    "openai/gpt-oss-120b": (0.15, 0.60, "groq.com/pricing (gpt-oss-120b $0.15/$0.60 per 1M)"),
    # Modelos LOCALES (ollama) = $0 marginal por definición (corren en la máquina del host).
    "qwen3:8b": (0.0, 0.0, "ollama local (sin costo marginal de inferencia)"),
}


def _apply_cli_registry() -> None:
    """ALIASES y PRICES de CLI salen del registro único. Sin spec, el histórico."""
    filled = False
    try:
        from cli_brain.registry import aliases as _cli_aliases, prices as _cli_prices
        ALIASES.update(_cli_aliases(CLI_BRAIN_BASE))
        PRICES.update(_cli_prices())
        filled = True
    except Exception:
        filled = False
    if not filled:
        # Fallback idéntico al que había horneado acá (sidecar sin paquete).
        for pid, mid in (("claude_cli", "claude-code-cli"), ("codex_cli", "codex-cli")):  # E1-FALLBACK
            ALIASES[pid] = {"model": mid, "base_url": CLI_BRAIN_BASE,
                            "key_env": None, "fallback": None}
            PRICES[mid] = (0.0, 0.0, "BYO-CLI: suscripción del usuario (sin costo API metered)")


_apply_cli_registry()
# Modelos cuya tarifa NO está documentada acá (Opus vía OpenRouter, llama-70b, qwen3-32b,
# gemini, …) devuelven usd None. NO se inventa el precio. El token igual se mide y se emite.


@dataclass
class ResolvedModel:
    """El modelo efectivo a correr, ya resuelto desde alias o id directo."""
    model: str
    base_url: str
    key_env: Optional[str]
    fallback: Optional[str]
    alias: Optional[str] = None   # alias de origen, o None si vino como id directo


# ── EL TECHO DE PEDIDO POR PROVEEDOR (Gate 4 · Fase 5 · obra 5.1) ───────────────
#
# POR QUÉ VIVE ACÁ. Este archivo ya es el que sabe lo que Aleph sabe de cada proveedor
# —su endpoint, su env de llave, a quién escala—. El tamaño máximo de pedido es otra
# cosa que sabemos de un proveedor, y tenerla en un cuarto lugar sería el quinto sitio
# donde alguien tiene que acordarse de mirar.
#
# ⚠️ **MEDIDO EN VIVO CONTRA GROQ EL 2026-08-09**, con la llave del dueño y en una sola
# sesión de sonda. La primera versión de esta tabla puso 24 KiB «del lado conservador» y
# estaba **en la unidad equivocada**: el 413 de Groq no es un tamaño de pedido.
#
# LA ESCALERA, tal como salió (payload = mensajes mínimos + N schemas de tool):
#
#     n=95   52.849 B  → 200 OK, usage.prompt_tokens 7.984
#     n=100  55.624 B  → 413 «Request too large … on tokens per minute (TPM)»
#     n=110/120/128    → 413, el mismo mensaje
#     n=400            → 400 «'tools' : maximum number of items is 128»
#
# LO QUE ESO DICE, con las palabras del proveedor:
#
#  1. **El 413 es la VENTANA POR MINUTO, no el tamaño del cuerpo.** El límite viaja en
#     CADA respuesta: `x-ratelimit-limit-tokens: 8000` en este tier (`on_demand`), y es
#     exactamente el 8000 que ya aparecía en la evidencia del 2026-08-08 sin que nadie lo
#     leyera como lo que era. Un pedido que solo ya excede la ventana **nunca** entra:
#     esperar no lo arregla, y por eso `contexto_excedido` no es reintentable y el copy no
#     dice «esperá».
#  2. **El techo depende del TIER**, así que un número fijo acá siempre va a ser una
#     aproximación para alguien. El default es el tier medido; el repliegue es la red para
#     todos los demás.
#  3. **Hay un SEGUNDO techo, y no es de tamaño: 128 tools como máximo, y devuelve 400,
#     no 413.** No lo conocía nadie —no está en ninguna auditoría previa— y con 9
#     workspaces más motores es perfectamente alcanzable. Un `invalid_request_error` no lo
#     salva ningún repliegue por bytes: hay que no pasarse de 128, y punto.
#
# DE LOS TOKENS A LOS BYTES, medido en la misma sonda (no es una regla de dedo):
#     52.849 B / 7.984 tok = 6,62 B/tok   ·   5.674 B / 929 tok = 6,11 B/tok
# Se toma **6 B/tok**, el extremo conservador de lo medido.
#
#     8.000 tok (ventana)  −  1.400 tok (el `max_tokens` típico de una receta, que también
#                             cuenta contra la ventana)  =  6.600 tok de prompt
#     6.600 tok × 6 B/tok  ≈  39.600 B   →  se declara 40.960 (40 KiB)
#
# Un host que no está acá **no tiene techo** y NO se recorta (`tool_budget` decisión 2:
# `None` es «no sé», jamás «infinito»). Agregar una fila es una decisión con evidencia.
LIMITES_POR_HOST: dict[str, dict] = {
    "api.groq.com": {
        "max_payload_bytes": 40_960,      # ventana TPM 8.000 − completion, a 6 B/tok
        "max_tools": 128,                 # techo DURO y aparte: 400, no 413
        "fuente": "medido:groq-2026-08-09-tpm8000",
    },
}

#: Margen para lo que el cuerpo lleva y `tool_budget.medir` no ve (model, max_tokens,
#: temperature, tool_choice, y el `cli_model`/`effort` del anexo BYO-CLI). Se declara en
#: vez de adivinarse dentro del medidor.
RESERVA_DE_CUERPO_BYTES = 2_048


def _host_de(base_url: str) -> str:
    u = (base_url or "").strip().lower()
    for prefijo in ("https://", "http://"):
        if u.startswith(prefijo):
            u = u[len(prefijo):]
            break
    return u.split("/", 1)[0].split("?", 1)[0]


def limite_de(base_url: str) -> dict:
    """`{max_payload_bytes, fuente}` del proveedor de ese endpoint.

    `max_payload_bytes = None` = **no sé** → el llamante no recorta (cero regresión para
    todo proveedor que no esté en la tabla).

    La perilla `ALEPH_TOOL_BUDGET_BYTES` pisa la tabla para TODOS los hosts. Existe para
    una sola cosa y está declarada como tal: **una vara necesita poner un techo minúsculo
    y comprobar que el mecanismo recorta de verdad**, sin depender del número de
    producción ni de la cuota de nadie. `0` la apaga explícitamente (útil para medir la
    regresión: con `0` el camino es byte-idéntico al de antes de esta obra).
    """
    crudo = (os.environ.get("ALEPH_TOOL_BUDGET_BYTES") or "").strip()
    if crudo:
        try:
            n = int(crudo)
        except ValueError:
            n = -1
        if n > 0:
            return {"max_payload_bytes": n, "max_tools": None,
                    "fuente": "perilla:ALEPH_TOOL_BUDGET_BYTES"}
        if n == 0:
            return {"max_payload_bytes": None, "max_tools": None,
                    "fuente": "perilla:apagada"}
    fila = LIMITES_POR_HOST.get(_host_de(base_url))
    if not fila:
        return {"max_payload_bytes": None, "max_tools": None, "fuente": "desconocido"}
    out = {"max_payload_bytes": None, "max_tools": None}
    out.update(fila)
    return out


def key_env_for_base_url(base_url: str) -> Optional[str]:
    """Infiere la env var de la key a partir del endpoint (para el back-compat de ids directos)."""
    u = (base_url or "").lower()
    if "groq.com" in u:
        return "GROQ_API_KEY"
    if "openrouter.ai" in u:
        return "OPENROUTER_API_KEY"
    if "generativelanguage.googleapis.com" in u:
        return "GEMINI_API_KEY"
    if "127.0.0.1" in u or "localhost" in u or "11434" in u:
        return None  # ollama local: sin auth
    return None


def resolve(name: str, *, base_url_hint: str = "", fallback_hint: Optional[str] = None) -> ResolvedModel:
    """Resuelve un alias O un id directo a un ResolvedModel.

    - Si `name` es un alias conocido → su entrada del registro.
    - Si no → se trata como id de modelo DIRECTO (back-compat) en base_url_hint, con la
      key inferida del endpoint. fallback_hint preserva el fallback declarado por la receta.
    """
    if name in ALIASES:
        a = ALIASES[name]
        return ResolvedModel(
            model=a["model"], base_url=a["base_url"],
            key_env=a.get("key_env"), fallback=a.get("fallback"), alias=name,
        )
    return ResolvedModel(
        model=name, base_url=base_url_hint,
        key_env=key_env_for_base_url(base_url_hint),
        fallback=fallback_hint, alias=None,
    )


def resolve_fallback(fallback: Optional[str], *, base_url_hint: str = "") -> Optional[str]:
    """El fallback puede ser un alias (lo resolvemos a su id concreto) o un id directo.
    El cascade del assembler corre primary y fallback en el MISMO base_url, así que solo
    necesitamos el id del modelo de fallback (no su endpoint)."""
    if not fallback:
        return None
    if fallback in ALIASES:
        return ALIASES[fallback]["model"]
    return fallback


def resolve_recipe_model(model_cfg: dict) -> dict:
    """Resuelve el modelo efectivo sin pisar una elección explícita en producción.

    En desarrollo, PUPPET_BRAIN puede sustituir la receta y el cambio queda
    declarado en el resultado. En cliente productivo, una elección explícita gana.

    Devuelve {primary, base_url, fallback, key_env, alias}. Es lo que el assembler usa
    para rutear. NO toca claves de la receta; es puro cálculo.

    - Si hay alias (por env o por receta): primary/base_url/key_env salen del registro;
      el fallback efectivo es el del alias salvo que la receta declare uno propio (gana
      la receta para no perder una intención explícita del autor del agente).
    - Si NO hay alias: se respeta lo que la receta horneó (comportamiento histórico).
    """
    model_cfg = model_cfg or {}
    explicit_primary = model_cfg.get("primary", "")
    explicit_base = model_cfg.get("base_url", "")
    explicit_fallback = model_cfg.get("fallback")

    # BYO-CLI (aditivo): model.brain_provider ∈ registry.provider_ids() ∪ {byok, managed}.
    # Los CLI son aliases del registro (van al server cli_brain); byok/managed son
    # declarativos (el ruteo sigue por byok_ref/alias como siempre).
    # La palanca PUPPET_BRAIN sigue disponible para desarrollo/operación, pero
    # no sustituye una selección explícita del usuario en el cliente productivo.
    brain_provider = str(model_cfg.get("brain_provider") or "").strip() or None
    _cli_alias = brain_provider if brain_provider in CLI_BRAIN_PROVIDERS else None

    env_brain = (os.environ.get("PUPPET_BRAIN") or "").strip()
    requested_alias = _cli_alias or model_cfg.get("alias")
    requested_choice = requested_alias or explicit_primary
    production = os.environ.get("ALEPH_ROLE", "client").strip().lower() == "client"
    override_blocked = bool(production and env_brain and requested_choice
                            and env_brain != requested_choice)
    applied_env = "" if override_blocked else env_brain
    chosen_alias = applied_env or requested_alias
    override_used = bool(applied_env and applied_env != requested_choice)

    # ATRIBUCIÓN HONESTA (review MED #7/#16): si se declaró un cerebro CLI pero PUPPET_BRAIN
    # (palanca de ops / setup de demo) lo PISÓ, el run NO corre por el CLI del usuario — corre
    # en la infra del dev (shim/OpenRouter). En ese caso NO reportamos brain_provider CLI, para
    # que el badge de la Sala no atribuya falsamente "verificado por tu CLI". El badge cae
    # entonces al chequeo de familia sobre el model_final REAL que respondió (correcto).
    _cli_overridden = bool(_cli_alias and override_used)
    reported_bp = None if _cli_overridden else brain_provider

    if chosen_alias:
        # 'brain' es indirección: apunta a lo que diga DEFAULT_BRAIN (que normalmente es
        # otra entrada del registro). Resolvemos esa indirección una vez.
        target = DEFAULT_BRAIN if chosen_alias == "brain" and DEFAULT_BRAIN != "brain" else chosen_alias
        rm = resolve(target, base_url_hint=explicit_base, fallback_hint=explicit_fallback)
        # fallback: gana el de la receta si lo declaró; si no, el del alias.
        fb_raw = explicit_fallback if explicit_fallback is not None else rm.fallback
        return {
            "primary": rm.model,
            "base_url": rm.base_url or explicit_base,
            "fallback": resolve_fallback(fb_raw, base_url_hint=rm.base_url or explicit_base),
            "key_env": rm.key_env,
            "alias": chosen_alias,
            "brain_provider": reported_bp,
            "brain_provider_overridden": _cli_overridden,
            "requested_provider": brain_provider,
            "requested_model": str(model_cfg.get("cli_model") or "").strip() if _cli_alias else (requested_alias or explicit_primary),
            "override_used": override_used,
            "override_source": "PUPPET_BRAIN" if override_used else "",
            "override_blocked": override_blocked,
        }

    # Sin alias → exactamente lo histórico (id directo horneado en la receta).
    return {
        "primary": explicit_primary,
        "base_url": explicit_base,
        "fallback": resolve_fallback(explicit_fallback, base_url_hint=explicit_base),
        "key_env": key_env_for_base_url(explicit_base),
        "alias": None,
        "brain_provider": reported_bp,
        "brain_provider_overridden": _cli_overridden,
        "requested_provider": brain_provider,
        "requested_model": str(model_cfg.get("cli_model") or "").strip() if _cli_alias else (requested_alias or explicit_primary),
        "override_used": override_used,
        "override_source": "PUPPET_BRAIN" if override_used else "",
        "override_blocked": override_blocked,
    }


def price(model_id: Optional[str], prompt_tokens: int, completion_tokens: int) -> Optional[dict]:
    """USD de una llamada, a tarifa DOCUMENTADA. Devuelve None si no hay tarifa para ese
    modelo (no se inventa). Si hay, devuelve {usd, usd_input, usd_output, price_model, source}.
    El token es lo medido; el precio es la constante. Redondeo a microcentavos (8 decimales)."""
    if not model_id or model_id not in PRICES:
        return None
    pin, pout, src = PRICES[model_id]
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    usd_in = round(pt / 1_000_000.0 * pin, 8)
    usd_out = round(ct / 1_000_000.0 * pout, 8)
    return {
        "usd": round(usd_in + usd_out, 8),
        "usd_input": usd_in,
        "usd_output": usd_out,
        "price_model": model_id,
        "source": src,
    }


__all__ = [
    "ALIASES", "PRICES", "DEFAULT_BRAIN", "ResolvedModel",
    "resolve", "resolve_recipe_model", "resolve_fallback",
    "key_env_for_base_url", "price",
    "GROQ_BASE", "OPENROUTER_BASE", "GEMINI_BASE", "OLLAMA_BASE",
    "CLI_BRAIN_BASE", "CLI_BRAIN_PROVIDERS",
]


# ── CLI smoke ──────────────────────────────────────────────────────────────────
def _main() -> None:
    import json
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "resolve":
        cfg = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"alias": "brain"}
        print(json.dumps(resolve_recipe_model(cfg), ensure_ascii=False, indent=2))
        return
    print(json.dumps({
        "default_brain": DEFAULT_BRAIN,
        "aliases": {k: v["model"] for k, v in ALIASES.items()},
        "priced": list(PRICES.keys()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
