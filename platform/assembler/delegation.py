#!/usr/bin/env python3
"""
delegation.py — el BRANCH REAL de delegación de sub-agentes (agente anidado) y los
5 RIELES de seguridad, llevados del SPIKE (platform/spike_delegation/, cerebro STUB)
al MOTOR VIVO (recipe_assembler.assemble_and_run, cerebro real).

Este módulo NO corre el loop: lo orquesta. El punto de ejecución de tool del motor
(recipe_assembler.py, `if EXECUTE: raw = registry.call(fn_name, fn_args)`) ramifica
acá cuando el `fn_name` invocado por el cerebro del padre corresponde a un agent_ref
(de `belt.agent_refs[]`, resueltos por el paso 1 vía belt_resolver.resolve_agent_refs).
En ese punto, en vez de `registry.call`, se DELEGA: se corre el sub-agente con SU PROPIO
loop (`assemble_and_run` de la receta hija) y el padre consume su resultado como el
retorno de esa "tool".

LOS 5 RIELES (REALES sobre el motor vivo) — cada uno marcado con `# RIEL #n`:
  1. GATE POR HIJO       — cada sub-run construye build_enforced_gate sobre la receta DEL
                           HIJO; el `approve` del padre NUNCA se reenvía (approve=None).
  2. DEPTH + CICLO       — corte por MAX_DEPTH; huella de ciclo por PATH CANÓNICO de la
                           receta (mejora sobre el spike, que colapsaba por nombre+belt).
  3. DEADLINE PROPAGADO  — el deadline ABSOLUTO del padre se pasa igual al hijo (no se
                           recalcula 180s por nivel).
  4. WORKDIR AISLADO     — cada sub-run en parent/sub-<turn>-<i>-<slug>/ (nunca el compartido).
  5. PUENTE / FRONTERA   — sólo el RESULTADO del hijo (string) cruza al cerebro del padre;
                           sus pasos internos quedan en sub_runs (log), no en su contexto.

LAS 4 DECISIONES DE DISEÑO (de persona usuaria):
  6. MODELO DEL HIJO     — default HEREDA el del padre; con flag (belt.agent_policy.child_model
                           == "own") y si la hija declara model propio, usa el suyo.
  7. BYOK HÍBRIDO        — el hijo recibe SOLO las keys de los servicios que SU receta declara
                           (scoped_byok_resolver); jamás una key del padre que no declaró.
  8. GUARDRAILS DEL PADRE— techo, no llave: el padre puede RESTRINGIR clases de acción del hijo
                           (ChildCeilingGate baja EXECUTE→BLOCKED), pero NUNCA pre-autoriza
                           una acción gated del hijo (el gate del hijo sigue mandando).
  9. PARALELO            — si el padre delega en VARIOS hijos en un mismo turno, corren en
                           PARALELO; cada uno su workdir/gate/deadline-restante; sin estado
                           mutable compartido (cada hilo devuelve su tupla; el padre splicea
                           single-thread tras el join).

stdlib-only salvo el `runner` (assemble_and_run) que se INYECTA para evitar el ciclo de
import recipe_assembler<->delegation.
"""

from __future__ import annotations

import concurrent.futures
import copy
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from belt_resolver import AgentResolutionError, ResolvedAgent, resolve_agent_refs


# ── RIEL #2 · parámetro del límite de profundidad ───────────────────────────────
MAX_DEPTH = 3

# tope de hilos para la delegación en paralelo (decisión 9). No queremos un fan-out
# ilimitado de sub-procesos MCP; un padre que delega en docenas se serializa por lotes.
# Es el fallback NON-PROD (CLI/tests sin _caps_ceiling); el cap POR TIER (Step 2·B1) es el
# min() más ajustado en prod.
_MAX_PARALLEL = 8

# Techo ABSOLUTO de hilos (defensa contra un tier mal-configurado): ni el tier más alto abre
# más de esto. tecnico=10 cabe holgado; un max_parallel corrupto (1000) igual se clampa acá.
_HARD_PARALLEL_CEILING = 16


def tier_max_parallel(caps_ceiling: Optional[dict]) -> int:
    """Step 2·B1 · FRONTERA de paralelismo por tier. `caps_ceiling['max_parallel']` viene de
    recipe_enforcer.TIER_RUNTIME_CAPS (free=1 / basico=3 / tecnico=10), server-side, NO editable
    por receta. Sin ceiling (CLI/tests non-prod) → el tope absoluto _MAX_PARALLEL (back-compat)."""
    mp = (caps_ceiling or {}).get("max_parallel")
    return mp if isinstance(mp, int) and mp >= 1 else _MAX_PARALLEL


def bounded_child_caps(caps_ceiling: Optional[dict]) -> Optional[dict]:
    """Step 2·B1 · PRESUPUESTO ANIDADO ACOTADO. El hijo hereda un techo ESTRICTAMENTE MENOR
    que el del padre: max_turns/max_tool_calls del hijo = la MITAD de los del padre (mínimo 1).
    Así un hijo en loop se corta por SU techo mucho antes de agotar el presupuesto del árbol y
    el padre sigue vivo (A1 hace el corte real en el choke point). El deadline ABSOLUTO ya lo
    comparte todo el árbol (RIEL #3) y max_parallel es del ÁRBOL (no se divide por nivel) → se
    conservan tal cual. caps_ceiling=None (CLI/tests non-prod) → None (sin frontera, back-compat
    byte-idéntico: el hijo corre como hoy)."""
    if not caps_ceiling:
        return caps_ceiling
    out = dict(caps_ceiling)
    for k in ("max_turns", "max_tool_calls"):
        v = caps_ceiling.get(k)
        if isinstance(v, int) and v > 1:
            out[k] = max(1, v // 2)
    return out


# ── síntesis de la "tool" que representa al sub-agente ante el cerebro del padre ──

def _safe_fn_name(raw: str, fallback: str) -> str:
    """Nombre de función válido para tool-calling (OpenAI: ^[a-zA-Z0-9_-]+$).
    Deriva del meta.name de la hija; si queda vacío, usa el slug del agent_ref."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (raw or "").strip().lower()).strip("_")
    return s or re.sub(r"[^a-zA-Z0-9_-]+", "_", (fallback or "agent")).strip("_") or "agent"


def build_agent_tools(recipe: dict, repo_root: Path) -> tuple[list, dict]:
    """Resuelve `belt.agent_refs[]` (slugs string, contrato del paso 1) y devuelve:
      - una lista de schemas de "tool" (formato OpenAI) que el cerebro del padre puede
        INVOCAR — su nombre/descr salen de la META de la receta hija (no del slug);
      - un mapa { fn_name -> ResolvedAgent } para que el ejecutor sepa a quién delegar.

    Receta SIN agent_refs → ([], {}) → el padre corre EXACTAMENTE como hoy (regresión).
    Un agent_ref que no resuelve NO tumba el run: se omite (best-effort; el padre sigue
    con sus tools reales). La resolución profunda/validación ya la hizo el paso 1.
    """
    belt = recipe.get("belt", {}) or {}
    refs = belt.get("agent_refs")
    if not isinstance(refs, list) or not refs:
        return [], {}

    try:
        resolved = resolve_agent_refs(refs, repo_root)
    except AgentResolutionError:
        # un ref roto no debe tumbar al padre; el paso 1 ya validó la forma en el taller.
        resolved = []
        for r in refs:
            try:
                resolved.extend(resolve_agent_refs([r], repo_root))
            except AgentResolutionError:
                continue

    tools: list = []
    agent_map: dict = {}
    seen: set = set()
    for ra in resolved:
        meta = (ra.recipe.get("meta") or {}) if isinstance(ra.recipe, dict) else {}
        fn_name = _safe_fn_name(meta.get("name", ""), ra.slug)
        # de-dup: dos refs que colapsan al mismo nombre → sufijo por slug
        if fn_name in seen:
            fn_name = _safe_fn_name(fn_name + "_" + ra.slug, ra.slug)
        seen.add(fn_name)
        agent_map[fn_name] = ra
        desc = (meta.get("descripcion") or meta.get("description")
                or f"Sub-agente '{meta.get('name', ra.slug)}'.")
        nicho = meta.get("nicho")
        full_desc = (
            f"DELEGA una sub-tarea a un sub-agente especializado"
            + (f" (nicho: {nicho})" if nicho else "")
            + f". {desc} Pásale la tarea concreta en `task`; corre con SU propio "
            f"cinturón y su propio candado de seguridad y te devuelve sólo el resultado."
        )
        tools.append({
            "type": "function",
            "function": {
                "name": fn_name,
                "description": full_desc[:1024],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "La sub-tarea concreta a delegar a este sub-agente.",
                        },
                    },
                    "required": ["task"],
                },
            },
        })
    return tools, agent_map


# ── RIEL #2 · huella de ciclo por PATH CANÓNICO (mejora sobre el spike) ──────────

def canonical_fingerprint(resolved: ResolvedAgent) -> str:
    """Huella de la receta hija = su PATH CANÓNICO resuelto. Dos refs al MISMO archivo
    colapsan (ciclo real A→A / A→B→A); dos agentes DISTINTOS con el mismo meta.name NO
    colapsan (el bug del spike, que usaba nombre+belt). recipe_path ya viene de
    `cand.resolve()` en el resolver → absoluto y canónico."""
    try:
        return str(Path(resolved.recipe_path).resolve())
    except Exception:
        return str(resolved.recipe_path)


# ── RIEL #5 · la FRONTERA: sólo el resultado cruza, jamás el contexto del hijo ───

def bridge_child_result(child_record: dict) -> str:
    """De vuelta del sub-run, el cerebro del PADRE consume SÓLO esto (un string), igual
    que `registry.call` devuelve un string. NO ve los tool_calls del hijo, ni sus
    mensajes, ni su workdir — sólo el resultado final + si salió ok. Compartimentado."""
    import json
    return json.dumps({
        "sub_agente": child_record.get("meta_name") or child_record.get("_meta_name"),
        "ok": bool(child_record.get("ok")),
        "resultado": child_record.get("answer", "") or "",
        "truncado": bool(child_record.get("truncated")),
        "error": child_record.get("error"),
    }, ensure_ascii=False)


def child_log_view(child_record: dict, agent_fn: str, child_path: str) -> dict:
    """Vista TRIMEADA del sub-run para record['sub_runs'] (instrumentación/log). NO se le
    pasa al cerebro del padre (eso es el bridge). Suficiente para evidencia/auditoría."""
    return {
        "agent_fn": agent_fn,
        "recipe_path": child_path,
        "meta_name": child_record.get("meta_name") or child_record.get("_meta_name"),
        "depth": child_record.get("depth"),
        "ok": bool(child_record.get("ok")),
        "answer": (child_record.get("answer") or "")[:600],
        "truncated": bool(child_record.get("truncated")),
        "error": child_record.get("error"),
        "gate_enforced": bool(child_record.get("gate_enforced")),
        "n_tool_calls": len(child_record.get("tool_calls", []) or []),
        "n_gate_decisions": len(child_record.get("gate_decisions", []) or []),
        "workdir": child_record.get("workdir"),
        "model_final": child_record.get("model_final"),
    }


# ── DECISIÓN 7 · BYOK HÍBRIDO: el hijo sólo ve las keys que SU receta declara ─────

def scoped_byok_resolver(
    parent_resolver: Optional[Callable[[str], str]],
    child_recipe: dict,
) -> tuple[Optional[Callable[[str], str]], set]:
    """Devuelve un resolver que SÓLO resuelve los byok_ref que la receta del HIJO declara
    en su bloque `keys`. Aunque el resolver del padre (ligado al user_id, vault compartido)
    PUDIERA resolver más, este wrapper NIEGA todo ref no declarado por la hija → el hijo
    nunca recibe una key del padre que no pidió. Devuelve (resolver, allow_set).

    Si la hija no declara keys → resolver que niega todo (set vacío). Si no hay resolver
    del padre → (None, set()) (no hay credenciales que pasar)."""
    keys = (child_recipe.get("keys") or {}) if isinstance(child_recipe, dict) else {}
    allow: set = set()
    for _provider, spec in keys.items():
        ref = (spec or {}).get("byok_ref")
        if ref:
            allow.add(ref)
    if parent_resolver is None:
        return None, allow

    def _scoped(ref: str) -> str:
        # RIEL/decisión 7: ref fuera del allow-set declarado por la hija → negado.
        if ref not in allow:
            return ""
        return parent_resolver(ref)

    return _scoped, allow


# ── DECISIÓN 6 · MODELO DEL HIJO: hereda el del padre (default) o usa el suyo ─────

def child_model_policy(parent_recipe: dict) -> str:
    """'inherit' (default) | 'own'. Flag: belt.agent_policy.child_model, o el override
    de entorno PUPPET_CHILD_MODEL. El default conservador = el hijo HEREDA el modelo del
    padre (un sub-agente caro no se dispara solo)."""
    env = (os.environ.get("PUPPET_CHILD_MODEL") or "").strip().lower()
    if env in ("own", "inherit"):
        return env
    pol = (((parent_recipe.get("belt") or {}).get("agent_policy") or {})
           .get("child_model"))
    pol = (pol or "").strip().lower()
    return pol if pol in ("own", "inherit") else "inherit"


def resolve_child_model_cfg(
    parent_model_cfg: dict,
    child_recipe: dict,
    policy: str,
    *,
    child_slug: Optional[str] = None,
    child_models: Optional[dict] = None,
) -> Optional[dict]:
    """El model_cfg EFECTIVO que el hijo usará. ORDEN DE PRECEDENCIA (de mayor a menor):

      1. OVERRIDE POR-HIJO (decisión 6-bis): si el padre declara
         `belt.agent_policy.child_models[<slug>]` — dict PLANO con la misma forma que
         `recipe.model` (primary/base_url/..., la que produce compileModel del Cuarto) —
         ESE cfg gana y se devuelve (deepcopy). El <slug> es EXACTAMENTE el que produce
         belt_resolver._slug_from_agent_ref(agent_ref) para ese hijo.
      2. POLÍTICA own/inherit (decisión 6, byte-idéntica a hoy): `policy` ya viene
         resuelta por child_model_policy, donde el env PUPPET_CHILD_MODEL manda sobre el
         flag `belt.agent_policy.child_model` de la receta — esa precedencia del ENV se
         mantiene EXACTAMENTE como hoy, pero sólo decide ESTE paso (own vs inherit); no
         pisa un override por-hijo del paso 1.
           'own' y la hija declara `model` propio → None (el hijo usa SU receta.model).
      3. HEREDA (default conservador): el model_cfg del PADRE (deepcopy).

    Devuelve None para "usá tu propio model"; un dict para "usá éste"."""
    # 1 · override por-hijo (6-bis): primero SIEMPRE.
    if isinstance(child_models, dict) and child_slug:
        per_child = child_models.get(child_slug)
        if isinstance(per_child, dict) and per_child:
            return copy.deepcopy(per_child)
    # 2 y 3 · lógica existente byte-idéntica (own → el suyo; si no, hereda el del padre).
    if policy == "own" and isinstance(child_recipe.get("model"), dict) and child_recipe["model"]:
        return None
    return copy.deepcopy(parent_model_cfg) if isinstance(parent_model_cfg, dict) else None


# ── DECISIÓN 8 · GUARDRAILS DEL PADRE: un TECHO sobre el gate del hijo ───────────

class ChildCeilingGate:
    """Envuelve el gate REAL del hijo con un TECHO declarado por el padre. SÓLO PUEDE
    RESTRINGIR: si una tool del hijo cae en una clase de acción que el padre PROHIBIÓ,
    fuerza la decisión a BLOCKED — aunque el gate del hijo la habilitara. NUNCA afloja:
    una acción que el gate del hijo deja en NEEDS_OK/BLOCKED se respeta tal cual (el techo
    no puede subir un EXECUTE prohibido a permitido, ni un needs_ok a execute).

    El padre RESTRINGE; jamás DESBLOQUEA. Y como `approve` NO se reenvía al hijo (RIEL #1),
    el padre tampoco puede pre-autorizar las acciones gated del hijo. Las dos vías por las
    que el padre podría 'abrir' al hijo quedan cerradas.

    Forma del techo (parent_ceiling):
      { "deny_classes": ["send", "money_touch"],   # por clasificación de nombre de tool
        "deny_servers": ["github"],                 # por server
        "deny_tools":   ["delete_repo"] }           # por nombre exacto de tool
    """

    # clasificadores de clase (mismos hints que el enforcer de Security)
    _SEND = ("send", "email", "mail", "post", "publish", "tweet", "message", "notify",
             "sms", "whatsapp", "telegram", "slack", "broadcast")
    _MONEY = ("pay", "payment", "charge", "transfer", "order", "buy", "sell", "trade",
              "invoice", "refund", "payout", "wire", "withdraw", "deposit", "checkout")

    def __init__(self, inner_gate, parent_ceiling: dict):
        self._inner = inner_gate
        c = parent_ceiling or {}
        self._deny_classes = {str(x).lower() for x in (c.get("deny_classes") or [])}
        self._deny_servers = {str(x).lower() for x in (c.get("deny_servers") or [])}
        self._deny_tools = {str(x).lower() for x in (c.get("deny_tools") or [])}

    def _class_of(self, tool: str) -> set:
        t = (tool or "").lower()
        cls = set()
        if any(h in t for h in self._SEND):
            cls.add("send")
        if any(h in t for h in self._MONEY):
            cls.add("money_touch")
        return cls

    def _denied_by_ceiling(self, server: str, tool: str) -> Optional[str]:
        if (server or "").lower() in self._deny_servers:
            return f"el padre prohibió el server '{server}' a este sub-agente"
        if (tool or "").lower() in self._deny_tools:
            return f"el padre prohibió la tool '{tool}' a este sub-agente"
        denied_classes = self._class_of(tool) & self._deny_classes
        if denied_classes:
            return (f"el padre prohibió la clase de acción "
                    f"{sorted(denied_classes)} a este sub-agente")
        return None

    def evaluate(self, server: str, tool: str, args: dict):
        decision = self._inner.evaluate(server, tool, args)
        reason = self._denied_by_ceiling(server, tool)
        if reason is None:
            return decision  # el techo no aplica → el gate del hijo manda intacto
        # TECHO: bajar a BLOCKED. Sólo restringe (nunca un BLOCKED→EXECUTE).
        return _CeilingBlocked(decision, reason)

    def grant_ok(self, server: str, tool: str):
        # se delega, pero como el hijo corre con approve=None, en la práctica no se llama.
        return self._inner.grant_ok(server, tool)

    def __getattr__(self, name):
        # cualquier otro atributo/método del gate real pasa de largo.
        return getattr(self._inner, name)


def merge_ceilings(inherited: Optional[dict], own: Optional[dict]) -> Optional[dict]:
    """Une dos techos en uno MÁS estricto (decisión 8, TRANSITIVA). El techo es monótono
    HACIA ABAJO en la cadena: un nieto no puede hacer lo que el ABUELO prohibió, aunque el
    padre intermedio no lo repita (si no, bastaría meter una capa benigna para evadir el
    techo del abuelo). La unión nunca afloja: sólo agrega prohibiciones."""
    if not inherited and not own:
        return None
    a, b = inherited or {}, own or {}
    out: dict = {}
    for k in ("deny_classes", "deny_servers", "deny_tools"):
        merged = list(dict.fromkeys(list(a.get(k) or []) + list(b.get(k) or [])))
        if merged:
            out[k] = merged
    return out or None


class _CeilingBlocked:
    """Decisión BLOCKED sintética del techo del padre, con la MISMA interfaz que la
    decisión real del gate (action/level/payload + constantes EXECUTE/NEEDS_OK/BLOCKED)."""

    def __init__(self, inner_decision, reason: str):
        # heredar las constantes del objeto real (no asumimos sus valores literales)
        self.EXECUTE = getattr(inner_decision, "EXECUTE", "execute")
        self.NEEDS_OK = getattr(inner_decision, "NEEDS_OK", "needs_ok")
        self.BLOCKED = getattr(inner_decision, "BLOCKED", "blocked")
        self.action = self.BLOCKED
        self.level = getattr(inner_decision, "level", "prohibido")
        base_payload = dict(getattr(inner_decision, "payload", {}) or {})
        base_payload["motivo"] = reason
        base_payload.setdefault("leyenda", reason)
        self.payload = base_payload


# ── EL BRANCH: correr los sub-agentes (en paralelo si son varios) ────────────────

def _sub_workdir(parent_workdir: Optional[str], turn: int, idx: int, slug: str) -> Optional[str]:
    """RIEL #4 · workdir aislado del hijo: parent/sub-<turn>-<idx>-<slug>/. Único dentro
    del run (turn+idx desambiguan dos delegaciones al mismo agente en el mismo turno o en
    turnos distintos). Si el padre no tiene workdir, el hijo cae al temporal por defecto."""
    if not parent_workdir:
        return None
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug or "agent").strip("-") or "agent"
    sub = Path(parent_workdir) / f"sub-{turn}-{idx}-{safe}"
    try:
        sub.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return str(sub)


def _run_one_child(
    *,
    runner: Callable,
    resolved: ResolvedAgent,
    task: str,
    depth: int,
    deadline_abs: float,
    agent_stack: tuple,
    parent_workdir: Optional[str],
    turn: int,
    idx: int,
    repo_root: Path,
    byok_resolver: Optional[Callable[[str], str]],
    user_id: Optional[str],
    run_id: Optional[str],
    parent_model_cfg: dict,
    policy: str,
    child_ceiling: Optional[dict],
    child_models: Optional[dict] = None,
    shared_memory: Optional[dict] = None,
    caps_ceiling: Optional[dict] = None,
    account_tier: Optional[str] = None,
    shared_pinned: Optional[str] = None,
    shared_members: Optional[list] = None,
    account_sensitive: Optional[list] = None,
) -> dict:
    """Corre UN sub-agente con su loop propio. Aplica RIELES 1-5 + decisiones 6-8 (+6-bis
    override de modelo por-hijo, + memoria compartida explícita — jamás via os.environ
    global: runs concurrentes no deben cruzarse el path). Devuelve un record (igual que
    assemble_and_run); enriquecido con meta_name/depth para el bridge.

    Step 2·B2 · MEMORIA COMPARTIDA por composición: el hijo hereda el bloque compartido
    (shared_pinned) y la membresía (shared_members) del padre, pero aporta/lee con SU PROPIA
    identidad (shared_self = su slug). Así un hijo CONECTADO (su slug ∈ members) lee el bus y
    deja su aporte atribuido; un hijo NO conectado no lo ve."""
    fp = canonical_fingerprint(resolved)
    meta_name = ((resolved.recipe.get("meta") or {}).get("name")
                 if isinstance(resolved.recipe, dict) else None) or resolved.slug

    # ── RIEL #2 · DEPTH + CICLO (por path canónico) — ANTES de correr nada ─────────
    if fp in agent_stack:
        return {"ok": False, "error": f"cycle_detected (path canónico ya en la cadena: {fp})",
                "answer": "", "depth": depth + 1, "meta_name": meta_name, "truncated": False,
                "tool_calls": [], "gate_decisions": [], "gate_enforced": False, "_meta_name": meta_name}
    if depth + 1 > MAX_DEPTH:
        return {"ok": False, "error": f"depth_limit_exceeded (>{MAX_DEPTH})",
                "answer": "", "depth": depth + 1, "meta_name": meta_name, "truncated": False,
                "tool_calls": [], "gate_decisions": [], "gate_enforced": False, "_meta_name": meta_name}

    # ── RIEL #3 · DEADLINE PROPAGADO: si ya pasó, ni arrancamos el hijo ───────────
    remaining = deadline_abs - time.monotonic()
    if remaining <= 0:
        return {"ok": False, "error": "deadline_exceeded_before_start", "answer": "",
                "depth": depth + 1, "meta_name": meta_name, "truncated": True,
                "tool_calls": [], "gate_decisions": [], "gate_enforced": False, "_meta_name": meta_name}

    child_recipe = resolved.recipe
    # ── DECISIÓN 6 (+6-bis) · MODELO: override por-hijo → own → hereda ────────────
    child_model_cfg = resolve_child_model_cfg(
        parent_model_cfg, child_recipe, policy,
        child_slug=resolved.slug, child_models=child_models,
    )
    # ── DECISIÓN 7 · BYOK HÍBRIDO: resolver scopeado a las keys que la hija declara ─
    scoped_resolver, _allow = scoped_byok_resolver(byok_resolver, child_recipe)
    # ── RIEL #4 · WORKDIR AISLADO ────────────────────────────────────────────────
    sub_wd = _sub_workdir(parent_workdir, turn, idx, resolved.slug)

    # ── correr el sub-agente con SU PROPIO loop (cerebro REAL) ────────────────────
    rec = runner(
        child_recipe, str(task),
        repo_root=repo_root,
        byok_resolver=scoped_resolver,      # DECISIÓN 7
        base_matrix=None,                   # el belt del hijo autocarga su base (RIEL #1)
        approve=None,                       # RIEL #1 · el hijo NO hereda el OK del padre
        on_event=None,                      # RIEL #5 · los eventos del hijo NO van al stream del padre
        workdir=sub_wd,                     # RIEL #4
        user_id=user_id,
        run_id=run_id,
        # plumbing interno de la recursión (additivo; el caller público no lo pasa):
        _depth=depth + 1,                   # RIEL #2
        _deadline_abs=deadline_abs,         # RIEL #3 · MISMO deadline absoluto
        _agent_stack=agent_stack + (fp,),   # RIEL #2 · cadena de paths canónicos
        _parent_ceiling=child_ceiling,      # DECISIÓN 8 · techo sobre el gate del hijo
        _caps_ceiling=bounded_child_caps(caps_ceiling),  # STEP 2·A1 FRONTERA + B1 PRESUPUESTO
                                            # ANIDADO · el hijo hereda el techo de tier ACOTADO
                                            # (max_turns/tool_calls a la mitad, mín 1; max_parallel
                                            # se conserva). Una receta hija con child_model 'own'
                                            # NO lo evade; un hijo en loop se corta por SU techo.
        account_tier=account_tier,          # MURALLA PREMIUM · el hijo hereda el tier de la CUENTA
                                            # (server-side) → su gate es autoritativo igual que el padre;
                                            # un blocked premium del hijo NO lo abre recipe.tier editada.
        _child_model_cfg=child_model_cfg,   # DECISIÓN 6 (+6-bis por-hijo)
        _shared_memory=shared_memory,       # MEMORIA COMPARTIDA (germen efímero) · mismo path
                                            # que el padre, explícito por parámetro (NUNCA os.environ)
        # ── Step 2·B2 · MEMORIA COMPARTIDA por composición (durable) ──
        shared_pinned=shared_pinned,        # bloque compartido del Cuarto (lo armó el executor)
        shared_members=shared_members,      # membresía teal (identidades conectadas al cilindro)
        account_sensitive=account_sensitive,  # ticket 4 · ANTI-EXFIL · el hijo HEREDA la lista de
                                            # hechos a vigilar (NO la data): un padre envenenado que
                                            # mete un dato de cuenta en el task del hijo → el escaneo
                                            # de los tool-calls del hijo lo atrapa igual.
        shared_self=resolved.slug,          # identidad de ESTE hijo (autor de su aporte)
        shared_author_label=meta_name,      # nombre del hijo para el panel
        distill_shared=bool(shared_members),  # el _is_member del assembler decide si realmente destila
    )
    if isinstance(rec, dict):
        rec.setdefault("depth", depth + 1)
        rec["meta_name"] = meta_name
        rec["_meta_name"] = meta_name
    return rec


def run_children(
    agent_calls: list,
    agent_map: dict,
    *,
    runner: Callable,
    depth: int,
    deadline_abs: float,
    agent_stack: tuple,
    parent_workdir: Optional[str],
    turn: int,
    repo_root: Path,
    byok_resolver: Optional[Callable[[str], str]],
    user_id: Optional[str],
    run_id: Optional[str],
    parent_model_cfg: dict,
    policy: str,
    child_ceiling: Optional[dict],
    child_models: Optional[dict] = None,
    shared_memory: Optional[dict] = None,
    caps_ceiling: Optional[dict] = None,
    account_tier: Optional[str] = None,
    shared_pinned: Optional[str] = None,
    shared_members: Optional[list] = None,
    account_sensitive: Optional[list] = None,
) -> list:
    """DECISIÓN 9 · PARALELO. `agent_calls` = [(fn_name, args, tool_call_id)] del MISMO turno.
    Si hay >1, corren CONCURRENTES (un hilo por hijo); si hay 1, inline. Cada hijo tiene su
    propio workdir/gate/deadline-restante. NO se comparte estado mutable: cada tarea devuelve
    su tupla (call, record) y el caller (el loop del motor) splicea single-thread tras el join.

    Devuelve [ (call_tuple, child_record) ] en el MISMO orden que agent_calls."""
    tasks = []
    for idx, (fn_name, fn_args, tc_id) in enumerate(agent_calls):
        resolved = agent_map.get(fn_name)
        task_text = ""
        if isinstance(fn_args, dict):
            task_text = fn_args.get("task") or fn_args.get("tarea") or fn_args.get("prompt") or ""
        tasks.append((idx, (fn_name, fn_args, tc_id), resolved, str(task_text)))

    def _do(idx, call, resolved, task_text):
        # FAIL-SAFE: un sub-run que EXPLOTE (excepción no-RuntimeError, belt roto, etc.) NUNCA
        # debe tumbar al PADRE. Se captura y se devuelve un record de error que el padre consume
        # como cualquier otro resultado (vía el bridge). Vale para el camino serial y el paralelo.
        try:
            if resolved is None:
                return call, {"ok": False, "error": f"agent_ref '{call[0]}' no resoluble en delegación",
                              "answer": "", "depth": depth + 1, "meta_name": call[0], "truncated": False,
                              "tool_calls": [], "gate_decisions": [], "gate_enforced": False, "sub_runs": []}
            rec = _run_one_child(
                runner=runner, resolved=resolved, task=task_text, depth=depth,
                deadline_abs=deadline_abs, agent_stack=agent_stack, parent_workdir=parent_workdir,
                turn=turn, idx=idx, repo_root=repo_root, byok_resolver=byok_resolver,
                user_id=user_id, run_id=run_id, parent_model_cfg=parent_model_cfg,
                policy=policy, child_ceiling=child_ceiling,
                child_models=child_models, shared_memory=shared_memory,
                caps_ceiling=caps_ceiling, account_tier=account_tier,
                shared_pinned=shared_pinned, shared_members=shared_members,
                account_sensitive=account_sensitive,
            )
            return call, rec
        except Exception as exc:  # noqa: BLE001
            return call, {"ok": False, "error": f"sub-run falló: {exc}", "answer": "",
                          "depth": depth + 1, "meta_name": call[0], "truncated": False,
                          "tool_calls": [], "gate_decisions": [], "gate_enforced": False, "sub_runs": []}

    if len(tasks) <= 1:
        return [_do(*t) for t in tasks]

    # ── PARALELO real: un hilo por hijo (cada uno bootea sus propios MCP servers) ──
    # Step 2·B1 · FRONTERA de paralelismo por tier: el nº de hijos CONCURRENTES se clampa al
    # cap del tier (free=1 / basico=3 / tecnico=10), server-side vía _caps_ceiling; una receta
    # editada NO lo sube. Con max_parallel=1 (free) el pool de 1 worker serializa los hijos
    # respetando el orden (results se splicean por posición). Non-prod (caps_ceiling=None) →
    # _MAX_PARALLEL (back-compat). El techo absoluto _HARD_PARALLEL_CEILING acota cualquier tier.
    results: list = [None] * len(tasks)
    max_workers = min(_HARD_PARALLEL_CEILING, tier_max_parallel(caps_ceiling), len(tasks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_to_pos = {ex.submit(_do, idx, call, resolved, task_text): idx
                      for (idx, call, resolved, task_text) in tasks}
        # límite duro por si un hijo se cuelga dentro de una sola call (defensa en
        # profundidad sobre el chequeo de deadline entre turnos del loop hijo).
        overall_timeout = max(1.0, (deadline_abs - time.monotonic()) + 30.0)
        try:
            for fut in concurrent.futures.as_completed(fut_to_pos, timeout=overall_timeout):
                pos = fut_to_pos[fut]
                try:
                    results[pos] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    call = tasks[pos][1]
                    results[pos] = (call, {"ok": False, "error": f"sub-run falló: {exc}",
                                           "answer": "", "depth": depth + 1, "meta_name": call[0],
                                           "truncated": False, "tool_calls": [], "gate_decisions": [],
                                           "gate_enforced": False})
        except concurrent.futures.TimeoutError:
            for fut, pos in fut_to_pos.items():
                if results[pos] is None:
                    call = tasks[pos][1]
                    results[pos] = (call, {"ok": False, "error": "sub-run truncado por deadline (timeout duro)",
                                           "answer": "", "depth": depth + 1, "meta_name": call[0],
                                           "truncated": True, "tool_calls": [], "gate_decisions": [],
                                           "gate_enforced": False})
    return results
