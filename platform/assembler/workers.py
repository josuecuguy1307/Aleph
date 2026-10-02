#!/usr/bin/env python3
"""
workers.py — OLA 4 · §2 · WORKERS EFÍMEROS + AUTO-ROUTING ECONÓMICO.

El Núcleo (el agente grande, con identidad) descompone los TRAMOS PESADOS de su
trabajo en *workers* efímeros: una sola tarea, contexto limpio, vida corta, cerebro
asignado por perfil económico. El Núcleo sintetiza; el worker recolecta. Los workers
NO son sub-agentes con identidad (delegation.py) ni piezas del diorama (§1 anti-fractal):
son EJECUCIÓN desechable. Este módulo es el gemelo económico de delegation.run_children,
con tres diferencias duras:

  1. PODERES SOLO-LECTURA — el worker corre pura-cognición por default (belt vacío):
     el Núcleo le CURA el contexto (el slice relevante viaja en la sub-tarea), el worker
     lee/extrae/valida y devuelve un hallazgo. Write-world y dinero NO EXISTEN para él
     (no bloqueados: ausentes). Si se le monta un belt, `readonly_schema` filtra toda
     tool de escritura/dinero/envío ANTES de que el cerebro del worker la vea, y un
     ChildCeilingGate (deny send/money) es defensa-en-profundidad. approve=None sella el
     piso money/send del gate base.
  2. AUTO-ROUTING LEGIBLE — cada sub-tarea se clasifica con REGLAS que se leen (verbos),
     no un router-ML: leer/extraer/validar/repetir → cerebro ECONÓMICO; sintetizar/decidir/
     juzgar → cerebro PRINCIPAL (y el juicio JAMÁS se subdivide: eso lo hace el Núcleo).
  3. PRESUPUESTO DURO + HONESTIDAD — cap de tokens y turnos por worker; model_final REAL
     por worker (superficiado del record del hijo); escalación narrada (worker inválido/
     timeout → 1 reintento en el PRINCIPAL; dos fallos → al reporte). Provider local
     saturado → serialización narrada.

Los eventos viajan por el MISMO riel `sub_agent_*` con campos aditivos (ephemeral:true,
worker_kind, worker_id, routed, model_final, ...): el emisor real es el motor
(recipe_assembler), acá sólo se calculan los datos. NADA de EVENT_TYPES nuevo.

stdlib-only salvo el `runner` (assemble_and_run) que se INYECTA (evita el ciclo de import
con recipe_assembler), igual que delegation.
"""

from __future__ import annotations

import concurrent.futures
import copy
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from delegation import (  # gemelos: reusamos los primitivos de paralelismo/presupuesto
    _HARD_PARALLEL_CEILING,
    _sub_workdir,
    tier_max_parallel,
)

# ── nombre de la tool de descomposición que el cerebro del Núcleo invoca ──────────
WORKER_TOOL_NAME = "repartir_en_workers"

# ── presupuesto duro por worker (defaults conservadores; el tier igual acota) ─────
_WORKER_TOKEN_CAP = 700      # max_tokens de la cognición del worker (recolector, corto)
_WORKER_TURN_CAP = 2         # un worker es casi one-shot; 2 turnos deja margen a 1 tool
_SUBTASK_CHAR_CAP = 1200     # curaduría: la sub-tarea (contexto curado) se acota
_WORKER_ANSWER_CAP = 1200    # lo que del hallazgo del worker vuelve al Núcleo (bounded)
_WORKER_CONCURRENCY_DEFAULT = 3   # cap conservador de workers en paralelo (non-prod)


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE FLAGS (§0.5 · desde el día uno; se construye DETRÁS del flag)
# ══════════════════════════════════════════════════════════════════════════════

def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "on", "yes")


def workers_enabled() -> bool:
    """§2 · workers.enabled. Default OFF hasta que el A/B de §5 lo gane. Con OFF, la tool
    de descomposición NO se ofrece al cerebro y `decompose` se ignora → el paso corre como
    hoy (retro-compat byte-idéntica: la regresión B2 pasa sin cambios)."""
    return _flag("PUPPET_WORKERS_ENABLED")


def guion_enabled() -> bool:
    """§2b · guion.enabled. Default OFF SIEMPRE en esta ola. El worker-guión (código en el
    sandbox) sólo se enciende si el A/B lo justifica con números."""
    return _flag("PUPPET_GUION_ENABLED")


def effective_kind(kind: str) -> str:
    """El kind EFECTIVO: 'guion' sólo si guion.enabled está ON; si no, degrada a 'lectores'
    (pura-cognición). Así un pedido de guión con el flag OFF corre como un worker normal —
    retro-seguro, jamás un camino apagado que igual se ejecuta."""
    return "guion" if (kind == "guion" and guion_enabled()) else "lectores"


# ══════════════════════════════════════════════════════════════════════════════
#  AUTO-ROUTING (§2.4) · reglas LEGIBLES, cero ML
# ══════════════════════════════════════════════════════════════════════════════

# verbos que marcan RECOLECCIÓN → cerebro económico
_ECON_VERBS = (
    "leer", "lee", "leé", "extraer", "extrae", "extraé", "listar", "lista", "listá",
    "buscar", "busca", "buscá", "contar", "cuenta", "contá", "parsear", "parsea",
    "validar", "valida", "validá", "revisar", "revisa", "revisá", "resumir", "resume",
    "resumí", "filtrar", "filtra", "recolectar", "recopilar", "transformar", "convertir",
    "normalizar", "tabular", "clasificar", "etiquetar",
    "read", "extract", "list", "search", "find", "count", "parse", "validate", "collect",
    "scrape", "gather", "fetch", "filter", "summarize", "transform", "normalize", "tabulate",
)

# verbos que marcan JUICIO/SÍNTESIS → cerebro principal, SIEMPRE (nunca se subdivide)
_JUDGE_VERBS = (
    "sintetizar", "sintetiza", "sintetizá", "decidir", "decide", "decidí", "elegir",
    "elige", "elegí", "concluir", "concluye", "recomendar", "recomienda", "recomendá",
    "priorizar", "prioriza", "priorizá", "juzgar", "juzga", "evaluar", "evalúa", "evaluá",
    "diseñar", "diseña", "planear", "planificar", "estrategia",
    "synthesize", "decide", "judge", "recommend", "prioritize", "conclude", "choose",
    "evaluate", "design", "plan", "strategize",
)


def _has_verb(text: str, verbs: tuple) -> Optional[str]:
    t = (text or "").strip().lower()
    for v in verbs:
        # límite de palabra por la izquierda; permite conjugaciones/acentos por la derecha
        if re.search(r"(^|[^\wáéíóúñ])" + re.escape(v), t):
            return v
    return None


def classify_subtask(text: str) -> tuple[str, str]:
    """(routed, reason). Juicio gana si hay verbo de juicio explícito; si no, recolección;
    default económico (un worker es, por definición, un recolector)."""
    jv = _has_verb(text, _JUDGE_VERBS)
    if jv:
        return "principal", f"'{jv}' → juicio/síntesis"
    ev = _has_verb(text, _ECON_VERBS)
    if ev:
        return "economico", f"'{ev}' → lectura/extracción"
    return "economico", "default → económico (recolector)"


def route_subtask(text: str, perfil: str = "auto") -> tuple[str, str]:
    """`perfil` de decompose overridea la heurística. auto → classify_subtask."""
    p = (perfil or "auto").strip().lower()
    if p == "principal":
        return "principal", "perfil declarado: principal"
    if p in ("economico", "económico", "economic"):
        return "economico", "perfil declarado: económico"
    return classify_subtask(text)


# ══════════════════════════════════════════════════════════════════════════════
#  PODERES SOLO-LECTURA (§2.3) · write-world/dinero AUSENTES para el worker
# ══════════════════════════════════════════════════════════════════════════════

_SEND_HINTS = ("send", "email", "mail", "post", "publish", "tweet", "message", "notify",
               "sms", "whatsapp", "telegram", "slack", "broadcast", "reply", "comment")
_MONEY_HINTS = ("pay", "payment", "charge", "transfer", "order", "buy", "sell", "trade",
                "invoice", "refund", "payout", "wire", "withdraw", "deposit", "checkout")
# escritura genérica sobre el mundo (mutación externa) más allá de send/money
_WRITE_HINTS = ("write", "create", "update", "delete", "remove", "insert", "upsert", "put",
                "patch", "upload", "commit", "push", "merge", "drop", "set_", "edit", "modify",
                "rename", "move", "execute", "run_", "exec", "install", "deploy", "provision",
                "revoke", "grant", "approve", "close_", "open_pr", "issue")


def worker_action_class(tool_name: str) -> Optional[str]:
    """Clase de acción de una tool por su nombre (mismos hints que el enforcer/ChildCeilingGate,
    + escritura genérica). None = lectura (solo-lectura, permitida al worker)."""
    t = (tool_name or "").lower()
    if any(h in t for h in _SEND_HINTS):
        return "send"
    if any(h in t for h in _MONEY_HINTS):
        return "money_touch"
    if any(h in t for h in _WRITE_HINTS):
        return "write_world"
    return None


def is_readonly_tool(tool_name: str) -> bool:
    return worker_action_class(tool_name) is None


def readonly_schema(schema: list) -> list:
    """Filtra un schema de tools (formato OpenAI) dejando SÓLO las de lectura. Las de
    escritura/dinero/envío quedan AUSENTES (no bloqueadas: el cerebro del worker no las ve).
    Esta es la garantía primaria del §2.3."""
    out = []
    for t in schema or []:
        try:
            name = (t.get("function") or {}).get("name") or t.get("name") or ""
        except AttributeError:
            name = ""
        if is_readonly_tool(name):
            out.append(t)
    return out


def worker_deny_ceiling() -> dict:
    """Techo (ChildCeilingGate) para el worker: defensa-en-profundidad sobre el filtro de
    schema. Deny de las clases que el gate base clasifica (send/money). La escritura genérica
    ya queda AUSENTE por readonly_schema; approve=None sella el piso money/send del gate."""
    return {"deny_classes": ["send", "money_touch"]}


# ══════════════════════════════════════════════════════════════════════════════
#  MODELO DEL WORKER (§2.4/§2.6) · slot `model.workers` o hereda el del Núcleo
# ══════════════════════════════════════════════════════════════════════════════

def resolve_workers_model(model_cfg: dict) -> Optional[dict]:
    """El cerebro ECONÓMICO de los workers = `model.workers` (dict plano con la forma de
    recipe.model) si la receta lo declara; si no, None → HEREDA el model del agente (§2 herencia).
    NO se cablea un provider hardcodeado (mission)."""
    w = (model_cfg or {}).get("workers")
    return copy.deepcopy(w) if isinstance(w, dict) and w else None


def _is_local_provider(model_cfg: dict) -> bool:
    """Provider local (ollama/localhost/specialist) → no paraleliza; se serializa (§2.6)."""
    if not isinstance(model_cfg, dict):
        return False
    hay = " ".join(str(model_cfg.get(k) or "") for k in ("base_url", "primary", "alias")).lower()
    return any(h in hay for h in ("localhost", "127.0.0.1", "11434", "ollama", "specialist", ":8000/v1"))


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA DE LA TOOL DE DESCOMPOSICIÓN (lo invoca el cerebro del Núcleo)
# ══════════════════════════════════════════════════════════════════════════════

def build_worker_tool() -> list:
    """La única tool que el Núcleo invoca para EJECUTAR un paso ya declarado con `decompose`.
    Una llamada → N workers efímeros. Sólo se ofrece al Núcleo (depth 0), nunca a un worker
    ni a un sub-agente (los workers no engendran workers)."""
    return [{
        "type": "function",
        "function": {
            "name": WORKER_TOOL_NAME,
            "description": (
                "Repartí un paso de trabajo PESADO y REPETITIVO (lectura/extracción/validación "
                "sobre varias fuentes o ítems) en WORKERS efímeros que corren en paralelo con "
                "contexto limpio y cerebro económico. Úsalo SÓLO para sub-tareas de RECOLECCIÓN; "
                "la síntesis/el juicio/la decisión NO se reparten: eso lo haces tú con lo que "
                "los workers te devuelven. Cada string de `subtareas` es UNA tarea concreta y "
                "autocontenida (incluye en el propio texto el dato/contexto que el worker necesita: "
                "el worker NO ve tu conversación)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_n": {
                        "type": "integer",
                        "description": "El nº del paso de tu plan que declaraste con `decompose` (para ligarlo en la Mente).",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["lectores", "guion"],
                        "description": "lectores = workers de lectura/extracción (default). guion = un guión de plomería de datos (avanzado).",
                    },
                    "subtareas": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Las sub-tareas concretas, una por worker. Cada una autocontenida.",
                    },
                },
                "required": ["subtareas"],
            },
        },
    }]


def parse_worker_call(fn_args: Any) -> dict:
    """Normaliza los args de una llamada a repartir_en_workers. Tolerante: subtareas puede
    venir como lista o string único."""
    a = fn_args if isinstance(fn_args, dict) else {}
    subs = a.get("subtareas") or a.get("subtasks") or a.get("tasks") or []
    if isinstance(subs, str):
        subs = [subs]
    subs = [str(s).strip() for s in subs if isinstance(s, (str, int, float)) and str(s).strip()]
    kind = str(a.get("kind") or "lectores").strip().lower()
    if kind not in ("lectores", "guion"):
        kind = "lectores"
    step_n = a.get("step_n")
    try:
        step_n = int(step_n) if step_n is not None else None
    except (TypeError, ValueError):
        step_n = None
    return {"subtareas": subs, "kind": kind, "step_n": step_n}


def worker_id_for(turn: int, step_n: Optional[int], idx: int) -> str:
    """ID único por instancia de worker (resuelve el gotcha 'sólo hay slug': N workers de un
    paso colisionarían por slug). Fórmula ÚNICA usada por el emisor (started) y run_workers."""
    return f"w{turn}-{step_n if step_n is not None else 0}-{idx}"


def perfil_for_step(plan: Any, step_n: Optional[int]) -> tuple[str, bool]:
    """Del plan declarado (B2 + `decompose`), devuelve (perfil, declared) para un step_n:
    el `perfil` de la descomposición y si el paso REALMENTE la declaró (para la honestidad
    'jamás invisible' + el ligado en la Mente). Sin match → ('auto', False)."""
    if not isinstance(plan, list) or step_n is None:
        return "auto", False
    for s in plan:
        if isinstance(s, dict) and s.get("n") == step_n:
            dec = s.get("decompose")
            if isinstance(dec, dict):
                return (str(dec.get("perfil") or "auto"), True)
            return "auto", False
    return "auto", False


# ══════════════════════════════════════════════════════════════════════════════
#  RECETA EFÍMERA DEL WORKER (pura-cognición por default; belt vacío = solo-lectura fuerte)
# ══════════════════════════════════════════════════════════════════════════════

# belt VACÍO shippeado: cero MCP servers → cero tools de mundo (la forma más fuerte del §2.3).
# El motor exige un belt_ref resoluble; belt:{} da error de carga. Este ref resuelve a un
# .mcp.json con mcpServers:{} → registry vacío → tools=[] para el worker (pura-cognición).
_EMPTY_BELT_REF = "platform/assembler/belt-empty-worker.mcp.json"

WORKER_FRAMING = (
    "Eres un WORKER efímero del Núcleo: UNA sola sub-tarea, contexto limpio, vida corta. "
    "Haz EXACTAMENTE la sub-tarea que se te da y NADA más. Devuelve un hallazgo estructurado "
    "y CONCISO: lo que leíste/extrajiste/validaste, sin preámbulo. No decidas ni sintetices "
    "por encima de tu tarea — eso lo hace el Núcleo con lo que le devuelves. Tienes poderes de "
    "SOLO LECTURA: no puedes escribir en el mundo ni mover dinero (esas herramientas no existen "
    "para ti)."
)


def build_worker_recipe(subtask: str, kind: str, *, model_cfg: dict,
                        token_cap: int, turn_cap: int) -> dict:
    """Receta efímera de UN worker. belt VACÍO (pura-cognición: el contexto curado viaja en
    la sub-tarea). model = el cfg ya ruteado (económico o principal), con presupuesto DURO."""
    model = copy.deepcopy(model_cfg) if isinstance(model_cfg, dict) else {}
    # presupuesto duro: nunca por encima del cap (aunque el cfg heredado pida más)
    _mt = model.get("max_tokens")
    model["max_tokens"] = min(int(_mt), token_cap) if isinstance(_mt, int) and _mt else token_cap
    _tt = model.get("max_turns")
    model["max_turns"] = min(int(_tt), turn_cap) if isinstance(_tt, int) and _tt else turn_cap
    model.pop("reporter", None)   # el worker no tiene 2ª etapa de reporte
    model.pop("workers", None)    # el worker no engendra workers
    return {
        "meta": {"name": f"worker-{kind}"},
        "model": model,
        "belt": {"belt_ref": _EMPTY_BELT_REF},   # pura-cognición · cero tools de mundo (§2.3)
        "framing": {"inline": WORKER_FRAMING},
    }


# ══════════════════════════════════════════════════════════════════════════════
#  BRIDGE · lo que del trabajo de los workers vuelve al cerebro del Núcleo
# ══════════════════════════════════════════════════════════════════════════════

def _bound(s: Any, n: int) -> str:
    t = "" if s is None else str(s)
    return t if len(t) <= n else t[:n] + "…"


def bridge_worker_results(results: list) -> str:
    """El Núcleo consume SÓLO esto (un string), como el retorno de cualquier tool. Trae los
    hallazgos ACOTADOS de cada worker + un resumen — NO los datos crudos completos (§2b: los
    datos viajan por el código/contexto curado, no inflan el contexto del cerebro)."""
    import json
    ok = sum(1 for r in results if r.get("ok"))
    esc = sum(1 for r in results if (r.get("escalated") or {}).get("retried"))
    workers = [{
        "worker_id": r.get("worker_id"),
        "subtarea": _bound(r.get("subtask"), 200),
        "routed": r.get("routed"),
        "ok": bool(r.get("ok")),
        "hallazgo": _bound(r.get("answer"), _WORKER_ANSWER_CAP),
        "model_final": r.get("model_final"),
        "error": r.get("error"),
    } for r in results]
    return json.dumps({
        "resumen": f"{ok}/{len(results)} workers OK" + (f", {esc} escalado(s) al principal" if esc else ""),
        "workers": workers,
        "nota": "Sintetiza tú estos hallazgos; la decisión no se subdivide.",
    }, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
#  RUN_WORKERS · el fan-out efímero (gemelo económico de run_children)
# ══════════════════════════════════════════════════════════════════════════════

def _est_tokens(s: str) -> int:
    return max(1, len(s or "") // 4)


# ══════════════════════════════════════════════════════════════════════════════
#  §2b · WORKER-GUIÓN — el cerebro ESCRIBE plomería, el sandbox la CORRE, sólo el
#  RESUMEN vuelve. Los datos viajan por el CÓDIGO, jamás por el contexto del cerebro.
#  Es UN tipo más de worker (hereda §2). Contención (defensa en profundidad, NO un jail seccomp;
#  `python3 -I` NO aísla red ni filesystem por sí solo — review §5 HIGH):
#    (1) GUARD DE ADMISIÓN estático (_guard_guion_code): RECHAZA antes de correr toda firma de red
#        (socket/urllib/http/smtp/ftp), subprocess/os.system, fork/setsid/exec y lectura de
#        credenciales/entorno (os.environ, .env, .ssh, vault). Primera línea contra exfiltración.
#    (2) env MÍNIMO (sin credenciales del run) · (3) cwd EFÍMERO · (4) grupo de proceso propio
#        (start_new_session → el timeout mata al GRUPO, sin nietos huérfanos) · (5) output cap.
#  Honesto: es aislamiento-de-proceso + admisión estática, no un sandbox con syscall-filter.
# ══════════════════════════════════════════════════════════════════════════════
_GUION_OUT_CAP = 4000          # recorte del stdout/stderr del guión (sólo el resumen vuelve)
_GUION_TIMEOUT_S = 20          # presupuesto DURO de tiempo del guión (runaway → matado y narrado)

GUION_FRAMING = (
    "Eres un WORKER-GUIÓN del Núcleo: escribe UN script de Python (SÓLO stdlib, sin pip) que haga "
    "la PLOMERÍA DE DATOS de tu sub-tarea y que imprima con print() SÓLO un RESUMEN corto y "
    "estructurado del resultado (qué hiciste, cuántos, errores) — JAMÁS vuelques los datos crudos: "
    "los datos viajan por tu código, no por tu respuesta. Los archivos de entrada están en tu "
    "directorio actual (cwd); trabaja SÓLO ahí. Tu guión corre con un GUARD de admisión que RECHAZA "
    "antes de correr cualquier red (socket/urllib/http), subprocess, fork/exec o lectura de "
    "credenciales/entorno (os.environ, .env): no los uses — sólo cómputo local sobre tus archivos. "
    "Devuelve el script en UN bloque ```python ... ```."
)

_CODE_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.DOTALL)

# ── GUARD DE ADMISIÓN (§2b · review §5 HIGH) — firmas que el guión NO puede usar. El objetivo NO es
#    ser un jail perfecto (imposible sin seccomp), sino cerrar los vectores de exfiltración conocidos
#    ANTES de ejecutar: red (cualquier egress), subprocess/fork/exec (escape del grupo), y lectura de
#    credenciales/entorno (env del run + archivos de secretos en disco). Un guión legítimo es cómputo
#    local sobre su cwd: no necesita nada de esto. Fail-closed: si duda, rechaza.
_GUION_FORBIDDEN = [
    r"\bsocket\b", r"\bssl\b", r"\burllib\b", r"\bhttp\.client\b", r"\bhttplib\b", r"\brequests\b",
    r"\bhttpx\b", r"\baiohttp\b", r"\bsmtplib\b", r"\bftplib\b", r"\btelnetlib\b", r"\bxmlrpc\b",
    r"\bsocketserver\b", r"\basyncio\b", r"\bwebbrowser\b",
    r"\bsubprocess\b", r"os\.system", r"os\.popen", r"\bpopen\b", r"os\.exec", r"os\.spawn",
    r"os\.fork", r"\bsetsid\b", r"\bpty\b", r"\bctypes\b", r"\bcffi\b", r"\bmultiprocessing\b",
    r"os\.environ", r"os\.getenv", r"os\.putenv",
    r"\.ssh", r"id_rsa", r"id_ed25519", r"vault\.enc", r"vault\.salt", r"credentials",
    r"(^|[^\w.])\.env\b", r"/\.env\b", r"['\"][^'\"]*\.env['\"]",   # archivos de secretos (no os.environ)
    r"Path\.home", r"pathlib\.Path\.home", r"os\.path\.expanduser",
    r"__import__\s*\(", r"\bimportlib\b", r"\beval\s*\(", r"\bexec\s*\(", r"\bcompile\s*\(",
    # primitivas de reflexión/evasión: un guión de plomería legítimo no las necesita, y son la vía
    # para eludir el escaneo por nombre (getattr(os,'sy'+'stem'), __builtins__, globals()['open']).
    r"\bgetattr\s*\(", r"__builtins__", r"\bglobals\s*\(", r"\bvars\s*\(", r"\blocals\s*\(",
    r"\bsetattr\s*\(", r"\bmemoryview\b",
]
_GUION_FORBIDDEN_RE = [re.compile(p, re.IGNORECASE) for p in _GUION_FORBIDDEN]


def _guard_guion_code(code: str) -> Optional[str]:
    """Escaneo de admisión ANTES de correr el guión. Devuelve la firma prohibida (str) si el código
    intenta red/subprocess/fork/exec/credenciales, o None si pasa. Es la 1ª línea de §2.3 para el
    carril guión (los lectores ya son puros por belt-vacío; el guión ejecuta código, así que necesita
    este filtro explícito). Complementa —no reemplaza— al env-limpio y al cwd efímero."""
    txt = code or ""
    for rx in _GUION_FORBIDDEN_RE:
        if rx.search(txt):
            return rx.pattern
    return None


def _extract_script(text: str) -> str:
    """El código del guión = el primer bloque ```python```; si no hay cerca, el texto crudo."""
    m = _CODE_RE.search(text or "")
    return (m.group(1).strip() if m else (text or "").strip())


def _killpg(proc) -> None:
    """Mata TODO el grupo de proceso del guión (nietos incluidos), no sólo el hijo directo — cierra
    el bypass de doble-fork y el hang por pipe heredado. Fallback a proc.kill() si killpg no aplica."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_guion_code(code: str, workdir: Optional[str], timeout_s: int = _GUION_TIMEOUT_S) -> dict:
    """Corre el guión con contención en profundidad (NO un jail seccomp — ver cabecera §2b):
    (0) GUARD de admisión estático (rechaza red/subprocess/fork/credenciales ANTES de correr);
    (1) `python3 -I` (sin site-packages ni env de import); (2) env MÍNIMO (sin credenciales del run);
    (3) cwd efímero acotado; (4) grupo de proceso propio → el timeout mata al GRUPO; (5) output cap.
    Devuelve {ok,returncode,stdout,stderr,timed_out,cwd[,blocked]}."""
    violation = _guard_guion_code(code)
    if violation:
        return {"ok": False, "returncode": None, "stdout": "", "blocked": True,
                "stderr": f"[guión bloqueado por la caja de seguridad: firma prohibida ({violation}) — "
                          f"el worker-guión no puede usar red, subprocess ni leer credenciales/entorno]",
                "timed_out": False}
    try:
        import sys as _sys
        from pathlib import Path as _Path
        guest_path = str(_Path(__file__).resolve().parents[2] / "product/belts/generalistas")
        if guest_path not in _sys.path:
            _sys.path.insert(0, guest_path)
        from guest_execution import execute_python
        result = execute_python(code, timeout_s)
        stderr = (f"[guión matado: presupuesto de tiempo agotado ({timeout_s}s)]"
                  if result["timed_out"] else result["stderr"])
        return {**result, "stdout": result["stdout"][:_GUION_OUT_CAP],
                "stderr": stderr[:_GUION_OUT_CAP]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "returncode": None, "stdout": "",
                "stderr": f"isolated_guest_unavailable: {type(exc).__name__}",
                "timed_out": False, "blocked": True}


def run_guion_worker(subtask: str, *, worker_id, step_n, routed, reason, econ_model_cfg,
                     principal_model_cfg, runner, repo_root, byok_resolver, user_id, run_id,
                     depth, deadline_abs, agent_stack, parent_workdir, turn, idx, caps_ceiling,
                     token_cap, turn_cap, subtask_char_cap, account_sensitive=None) -> dict:
    """UN worker-guión: (1) el cerebro ECONÓMICO escribe un script de plomería; (2) el script
    corre en el sandbox; (3) SÓLO el resumen (stdout acotado) vuelve — los datos crudos jamás
    entran al contexto del cerebro. model_final = el cerebro que ESCRIBIÓ el guión. El código es
    INSPECCIONABLE (view-only) en el record. Presupuesto duro de tiempo/salida en el sandbox."""
    curated = _bound(subtask, subtask_char_cap)
    input_tokens_est = _est_tokens(curated) + _est_tokens(GUION_FRAMING)
    model_cfg = econ_model_cfg if routed == "economico" else principal_model_cfg
    wd = _sub_workdir(parent_workdir, turn, idx, "guion")
    recipe = build_worker_recipe(curated, "guion", model_cfg=model_cfg, token_cap=token_cap, turn_cap=turn_cap)
    recipe["framing"] = {"inline": GUION_FRAMING}
    t0 = time.monotonic()
    try:
        rec = runner(recipe, curated, repo_root=repo_root, byok_resolver=byok_resolver, base_matrix=None,
                     approve=None, on_event=None, workdir=wd, user_id=user_id, run_id=run_id,
                     _depth=depth + 1, _deadline_abs=deadline_abs, _agent_stack=agent_stack,
                     _parent_ceiling=worker_deny_ceiling(), _child_model_cfg=None,
                     _caps_ceiling=caps_ceiling, _worker_readonly=True,
                     account_sensitive=account_sensitive)   # ticket 4 (review F3/F7): hereda la vigilancia anti-exfil
    except Exception as exc:  # noqa: BLE001
        rec = {"ok": False, "error": f"el cerebro del guión falló: {exc}", "answer": "", "model_final": None}
    script = _extract_script(rec.get("answer", "") if isinstance(rec, dict) else "")
    model_final = rec.get("model_final") if isinstance(rec, dict) else None
    # (2) el guión CORRE — los datos por el CÓDIGO, sólo el resumen vuelve
    sb = _run_guion_code(script, wd) if script.strip() else {
        "ok": False, "stdout": "", "stderr": "[el cerebro no produjo un guión]",
        "timed_out": False, "returncode": None, "cwd": wd}
    summary = _bound(sb.get("stdout", ""), _WORKER_ANSWER_CAP)   # SÓLO el resumen (acotado)
    ok = bool(sb.get("ok")) and bool(summary.strip())
    return {
        "worker_id": worker_id, "subtask": curated, "worker_kind": "guion", "step_n": step_n,
        "routed": routed, "route_reason": reason, "ok": ok,
        "answer": summary,                                     # el resumen estructurado (no los datos)
        "error": None if ok else (sb.get("stderr") or "guión sin salida útil"),
        "model_final": model_final,                            # el cerebro que ESCRIBIÓ el guión
        "held": 0,
        "script": script,                                      # INSPECCIONABLE (view-only) en la Mente
        "sandbox": {"returncode": sb.get("returncode"), "timed_out": bool(sb.get("timed_out")),
                    "stderr": _bound(sb.get("stderr"), 400)},
        "budget": {"tokens_cap": token_cap, "time_cap_s": _GUION_TIMEOUT_S},
        "spent": {"input_tokens_est": input_tokens_est, "wall_s": round(time.monotonic() - t0, 3),
                  "stdout_chars": len(sb.get("stdout", ""))},
        "escalated": None,
    }


def _run_one_worker(*, runner, subtask, kind, routed, reason, worker_id, step_n,
                    econ_model_cfg, principal_model_cfg, repo_root, byok_resolver,
                    user_id, run_id, depth, deadline_abs, agent_stack, parent_workdir,
                    turn, idx, caps_ceiling, token_cap, turn_cap, subtask_char_cap,
                    account_sensitive=None) -> dict:
    """Corre UN worker (pura-cognición, solo-lectura) + escalación de 1 reintento en el
    principal. Devuelve un dict con model_final REAL, budget consumido y estado."""
    curated = _bound(subtask, subtask_char_cap)   # CURADURÍA: la sub-tarea se acota (no volcar)
    input_tokens_est = _est_tokens(curated) + _est_tokens(WORKER_FRAMING)
    model_cfg = econ_model_cfg if routed == "economico" else principal_model_cfg

    def _spawn(mcfg, tag) -> dict:
        recipe = build_worker_recipe(curated, kind, model_cfg=mcfg, token_cap=token_cap, turn_cap=turn_cap)
        wd = _sub_workdir(parent_workdir, turn, idx, f"{kind}-{tag}")
        t0 = time.monotonic()
        rec = runner(
            recipe, curated,
            repo_root=repo_root,
            byok_resolver=byok_resolver,        # scoped por la propia receta (belt vacío → nada)
            base_matrix=None,
            approve=None,                        # el worker NO ejecuta gated (piso money/send)
            on_event=None,                       # los pasos internos del worker NO cruzan (RIEL#5)
            workdir=wd,
            user_id=user_id, run_id=run_id,
            _depth=depth + 1,
            _deadline_abs=deadline_abs,
            _agent_stack=agent_stack,
            _parent_ceiling=worker_deny_ceiling(),   # defensa-en-profundidad (send/money)
            _child_model_cfg=None,               # el model va en la receta efímera
            _caps_ceiling=caps_ceiling,
            _worker_readonly=True,               # §2.3 · write-world AUSENTE del schema del worker
            account_sensitive=account_sensitive,  # ticket 4 (review F3/F7): hereda la vigilancia anti-exfil
        )
        wall = time.monotonic() - t0
        if isinstance(rec, dict):
            rec["_wall_s"] = round(wall, 3)
        return rec if isinstance(rec, dict) else {"ok": False, "error": "worker sin record"}

    def _valid(rec) -> bool:
        return bool(rec.get("ok")) and bool((rec.get("answer") or "").strip()) and not rec.get("truncated")

    escalated = None
    try:
        rec = _spawn(model_cfg, "a")
    except Exception as exc:  # noqa: BLE001 — un worker que explota jamás tumba al Núcleo
        rec = {"ok": False, "error": f"worker falló: {exc}", "answer": "", "_wall_s": 0.0}

    # ── ESCALACIÓN NARRADA (§2.5): inválido/timeout → 1 reintento en el PRINCIPAL ──
    if not _valid(rec):
        try:
            rec2 = _spawn(principal_model_cfg, "esc")
        except Exception as exc:  # noqa: BLE001
            rec2 = {"ok": False, "error": f"worker (reintento) falló: {exc}", "answer": "", "_wall_s": 0.0}
        escalated = {
            "retried": True,
            "from": (rec.get("model_final") or (model_cfg or {}).get("primary")),
            "to": (rec2.get("model_final") or (principal_model_cfg or {}).get("primary")),
            "reason": rec.get("error") or ("timeout/truncado" if rec.get("truncated") else "hallazgo inválido/vacío"),
        }
        rec = rec2   # el segundo intento manda (dos fallos → estado honesto abajo)

    return {
        "worker_id": worker_id,
        "subtask": curated,
        "worker_kind": kind,
        "step_n": step_n,
        "routed": routed,
        "route_reason": reason,
        "ok": bool(rec.get("ok")) and bool((rec.get("answer") or "").strip()),
        "answer": rec.get("answer") or "",
        "error": rec.get("error"),
        "model_final": rec.get("model_final"),        # §2.5 · la verdad, una capa más adentro
        "held": len(rec.get("held_actions") or []),   # workers read-only → esperado 0
        "budget": {"tokens_cap": token_cap, "time_cap_s": None},
        "spent": {"input_tokens_est": input_tokens_est, "wall_s": rec.get("_wall_s", 0.0)},
        "escalated": escalated,
    }


def run_workers(subtasks: list, *, kind: str, perfil: str, step_n: Optional[int],
                runner: Callable, parent_model_cfg: dict, workers_model_cfg: Optional[dict],
                repo_root: Path, byok_resolver: Optional[Callable[[str], str]],
                user_id: Optional[str], run_id: Optional[str], depth: int,
                deadline_abs: float, agent_stack: tuple, parent_workdir: Optional[str],
                turn: int, caps_ceiling: Optional[dict] = None,
                token_cap: int = _WORKER_TOKEN_CAP, turn_cap: int = _WORKER_TURN_CAP,
                subtask_char_cap: int = _SUBTASK_CHAR_CAP,
                account_sensitive: Optional[list] = None) -> dict:
    """Fan-out efímero de una llamada a repartir_en_workers. Devuelve
    {results:[...], serialized:{cause,requested,max}|None}. `results` en el MISMO orden que
    subtasks. El cerebro ECONÓMICO = workers_model_cfg o (None → hereda) el del Núcleo; el
    PRINCIPAL (para juicio y escalación) = siempre el del Núcleo."""
    econ_model_cfg = workers_model_cfg if isinstance(workers_model_cfg, dict) and workers_model_cfg else parent_model_cfg
    principal_model_cfg = parent_model_cfg
    eff_kind = effective_kind(kind)   # 'guion' sólo con guion.enabled ON; si no, 'lectores'

    tasks = []
    for idx, sub in enumerate(subtasks):
        routed, reason = route_subtask(sub, perfil)
        worker_id = worker_id_for(turn, step_n, idx)
        tasks.append((idx, sub, routed, reason, worker_id))

    # ── CONCURRENCIA (§2.6): cap conservador + tier; provider local → serializa (narrado) ──
    serialized = None
    local_econ = _is_local_provider(econ_model_cfg)
    tier_cap = tier_max_parallel(caps_ceiling)
    if local_econ and len(tasks) > 1:
        max_workers = 1
        serialized = {"cause": "provider_saturated", "requested": len(tasks), "max_parallel": 1,
                      "leyenda": "El cerebro económico corre local (una cosa a la vez); los workers van en fila."}
    else:
        max_workers = max(1, min(_HARD_PARALLEL_CEILING, tier_cap, _WORKER_CONCURRENCY_DEFAULT, len(tasks)))
        if len(tasks) > tier_cap:
            serialized = {"cause": "tier_cap", "requested": len(tasks), "max_parallel": tier_cap,
                          "leyenda": f"Tu plan permite {tier_cap} worker(s) a la vez; los {len(tasks)} van en fila."}

    def _do(idx, sub, routed, reason, worker_id):
        try:
            _common = dict(
                worker_id=worker_id, step_n=step_n, routed=routed, reason=reason,
                econ_model_cfg=econ_model_cfg, principal_model_cfg=principal_model_cfg,
                runner=runner, repo_root=repo_root, byok_resolver=byok_resolver,
                user_id=user_id, run_id=run_id, depth=depth, deadline_abs=deadline_abs,
                agent_stack=agent_stack, parent_workdir=parent_workdir, turn=turn, idx=idx,
                caps_ceiling=caps_ceiling, token_cap=token_cap, turn_cap=turn_cap,
                subtask_char_cap=subtask_char_cap, account_sensitive=account_sensitive,
            )
            if eff_kind == "guion":
                return run_guion_worker(sub, **_common)          # §2b · plomería en el sandbox
            return _run_one_worker(subtask=sub, kind=eff_kind, **_common)   # lectores (pura-cognición)
        except Exception as exc:  # noqa: BLE001
            return {"worker_id": worker_id, "subtask": _bound(sub, subtask_char_cap),
                    "worker_kind": eff_kind, "step_n": step_n, "routed": routed, "route_reason": reason,
                    "ok": False, "answer": "", "error": f"worker falló: {exc}",
                    "model_final": None, "held": 0,
                    "budget": {"tokens_cap": token_cap, "time_cap_s": None},
                    "spent": {"input_tokens_est": 0, "wall_s": 0.0}, "escalated": None}

    results: list = [None] * len(tasks)
    if len(tasks) <= 1 or max_workers <= 1:
        for t in tasks:
            results[t[0]] = _do(*t)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_pos = {ex.submit(_do, *t): t[0] for t in tasks}
            overall_timeout = max(1.0, (deadline_abs - time.monotonic()) + 30.0)
            try:
                for fut in concurrent.futures.as_completed(fut_pos, timeout=overall_timeout):
                    pos = fut_pos[fut]
                    try:
                        results[pos] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        results[pos] = {"worker_id": worker_id_for(turn, step_n, pos), "ok": False,
                                        "answer": "", "error": f"worker falló: {exc}", "subtask": "",
                                        "worker_kind": kind, "step_n": step_n, "routed": "economico",
                                        "route_reason": "", "model_final": None, "held": 0,
                                        "budget": {"tokens_cap": token_cap, "time_cap_s": None},
                                        "spent": {"input_tokens_est": 0, "wall_s": 0.0}, "escalated": None}
            except concurrent.futures.TimeoutError:
                for fut, pos in fut_pos.items():
                    if results[pos] is None:
                        results[pos] = {"worker_id": worker_id_for(turn, step_n, pos), "ok": False,
                                        "answer": "", "error": "worker truncado por deadline",
                                        "subtask": "", "worker_kind": kind, "step_n": step_n,
                                        "routed": "economico", "route_reason": "", "model_final": None,
                                        "held": 0, "budget": {"tokens_cap": token_cap, "time_cap_s": None},
                                        "spent": {"input_tokens_est": 0, "wall_s": 0.0}, "escalated": None}
    return {"results": results, "serialized": serialized}
