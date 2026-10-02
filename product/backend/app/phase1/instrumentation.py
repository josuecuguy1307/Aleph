"""
instrumentation.py — el pipeline del MOAT: liga por run_id los 5 campos del loop.

Microtask (d): pipeline de instrumentación que liga los 5 campos por run_id en
instrumentation_logs — NO logs sueltos. Una fila = un loop completo, ligado por run_id:

  (1) intent      — qué pidió el usuario
  (2) belt        — snapshot de la receta usada (puppets.config al correr)
  (3) trayectoria — secuencia model_call + tool_call, cada uno con latency_ms y error
  (4) senal       — explícita (👍/👎) + implícita (saved/edited/abandoned)
  (5) costo       — tokens {prompt, completion, total, by_model}

FUENTE de la trayectoria: el events.jsonl que el loop YA escribe
(platform/assembler/session.py). No re-instrumentamos el loop; LEEMOS lo que ya emitió.
Cada `tool_call_finished` trae `wall_s` (→ latency_ms) y `gate_decision`. Reconstruimos
también los `model_call` a partir de `turn_started` (un turno = una llamada al modelo).

Esto convierte un stream de eventos crudo en LA fila del moat. El costo en tokens lo
provee el caller (el loop no lo emite hoy en los eventos); si no llega, queda {} y se
marca honestamente — no inventamos números.

API:
  build_trayectoria(events) -> list[dict]     # del events.jsonl al campo (3)
  build_signal(...) -> dict                    # explícita + implícita → campo (4)
  persist_run(conn, run_id, ...) -> int        # INSERT en instrumentation_logs (la fila)
  trayectoria_from_file(path) -> list[dict]    # helper: lee un events.jsonl y arma (3)

Stdlib + json (+ psycopg2 vía repo para persist).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import aleph_paths as _ap
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_TOOL_RESULT_PATH = _ap.resource_root() / "platform" / "assembler" / "tool_result.py"
_tool_result_mod = _ap.load_module_by_path("puppet_instrumentation_tool_result", _TOOL_RESULT_PATH)
es_error_de_tool = _tool_result_mod.es_error_de_tool


# ── [GATE 3 · obra 5] EL VOCABULARIO REAL DEL GATE ────────────────────────────────────
# `GateDecision` declara TRES valores y sólo tres (platform/gates/approval_gate.py:220-222):
# `execute` · `needs_ok` · `blocked`. Este módulo venía comparando contra ("NO","denied",
# "rejected"), que no existe en ningún lado del árbol — la rama era inalcanzable.
#
# UNA ACCIÓN RETENIDA NO ES UN ERROR: ES PROTECCIÓN (acta de persona usuaria, 2026-08-06). El gate hizo
# su trabajo. Por eso `error` queda en None y la retención se firma en su propio campo, que es
# aditivo: quien contaba errores deja de contar los frenos del gate como fallas del run, y
# quien quiera los frenos los tiene por nombre en vez de tener que parsear un string "gate:…".
# MISMO CRITERIO, PALABRA POR PALABRA, que `executor.build_trajectory_from_record` (:559) —
# eran los dos constructores vivos con distinta corrección (auditoría 4 §G-7).
GATE_EXECUTE = "execute"
GATE_RETIENE = frozenset({"needs_ok", "blocked"})


def _ms(wall_s: Any) -> Optional[int]:
    """wall_s (segundos, float) → latency_ms (entero). None si no hay dato."""
    if wall_s is None:
        return None
    try:
        return int(round(float(wall_s) * 1000))
    except (TypeError, ValueError):
        return None


def build_trayectoria(events: list[dict]) -> list[dict]:
    """
    Reconstruye el campo (3) trayectoria a partir de los eventos del loop.

    Cada turno (`turn_started`) cuenta como un model_call. Cada `tool_call_finished`
    es un tool_call con su latency_ms (de wall_s) y error (lo deriva del gate y del
    resultado). El resultado es la secuencia ORDENADA de pasos del loop, lista para
    instrumentation_logs.trayectoria.

    Forma de cada paso (alineada con schema.sql §7):
      {seq, kind:'model_call'|'tool_call', name, latency_ms, error}
    Para tool_call agregamos gate_decision y la CausaCostura cuando el evento la trae.
    """
    steps: list[dict] = []
    seq = 0
    for ev in events:
        etype = ev.get("type")
        if etype == "turn_started":
            seq += 1
            steps.append({
                "seq": seq,
                "kind": "model_call",
                "name": "chat.completions",
                "latency_ms": None,   # el evento del modelo no trae latencia hoy (honesto)
                "error": None,
                "turn": ev.get("turn") or (ev.get("payload") or {}).get("turn"),
            })
        elif etype in ("tool_call_finished", "gate_waiting"):
            # [GATE 3 · obra 5] `gate_waiting` TAMBIÉN ES UN PASO. El emisor cambia el TIPO del
            # evento cuando la decisión no es EXECUTE (recipe_assembler.py:3304), y esta función
            # sólo miraba `tool_call_finished`: una acción frenada por el gate NO EXISTÍA en
            # esta trayectoria. Un run llegaba al moat con un paso menos del que de verdad tuvo.
            seq += 1
            # session.py pone los datos "planos" en el evento; events_replay los anida en payload.
            payload = ev.get("payload") or {}
            tool = ev.get("tool") or payload.get("tool")
            wall_s = ev.get("wall_s") if ev.get("wall_s") is not None else payload.get("wall_s")
            # D4 · migración aditiva: el nombre sellado es `gate_decision`; `gate_action` sigue
            # vivo en consumidores y en los eventos viejos, así que se lee como respaldo.
            gate_decision = next(
                (v for v in (ev.get("gate_decision"), payload.get("gate_decision"),
                             ev.get("gate_action"), payload.get("gate_action"))
                 if v is not None), None)
            result = ev.get("result") or payload.get("result") or ""
            retenida = gate_decision in GATE_RETIENE
            # error: SÓLO lo que de verdad falló. Una retención no es un fallo (ver GATE_RETIENE).
            error: Optional[str] = None
            if not retenida and es_error_de_tool(result):
                error = result[:200]
            step = {
                "seq": seq,
                "kind": "tool_call",
                "name": tool,
                "latency_ms": _ms(wall_s),
                "error": error,
                "gate_decision": gate_decision,
                "retenida": retenida,
            }
            for key in ("causa", "origen", "reintentable", "timeout_s",
                        "vencio_el_reloj", "detalle"):
                if key in ev:
                    step[key] = ev[key]
                elif key in payload:
                    step[key] = payload[key]
            steps.append(step)
    return steps


def trayectoria_from_file(events_path: str | Path) -> list[dict]:
    """Lee un events.jsonl (de session.py o de events_replay) y arma la trayectoria."""
    p = Path(events_path)
    events: list[dict] = []
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # una línea rota no tira el pipeline; la saltamos (honesto, no inventamos)
                continue
    return build_trayectoria(events)


def build_signal(
    *,
    explicit: Optional[str] = None,
    saved: bool = False,
    edited: bool = False,
    abandoned: bool = False,
) -> dict[str, Any]:
    """
    Campo (4) señal: explícita (👍/👎) + implícita (guardó/editó/abandonó).
    explicit ∈ {'up','down',None}. Forma alineada con schema.sql §7.
    """
    if explicit not in (None, "up", "down"):
        raise ValueError("explicit debe ser 'up', 'down' o None")
    return {
        "explicit": explicit,
        "implicit": {"saved": bool(saved), "edited": bool(edited), "abandoned": bool(abandoned)},
    }


# ── TARIFA PUBLICADA DEL PROVEEDOR (constante documentada, NO estimada) ─────────
# Lo MEDIDO es el token (viene del campo `usage` del response del proveedor); el
# PRECIO es una constante con fuente. Tarifa de Groq para gpt-oss-120b (el modelo
# canónico OSS-first del path): $0.15 / 1M tokens de entrada, $0.60 / 1M de salida.
# Fuente: groq.com/pricing (registrado en catalog/scoring-v0.md §gpt-oss-120b, 2026-06-15).
# Si el modelo del run no es gpt-oss-120b, el USD queda None (no aplicamos una tarifa
# que no le corresponde — honestidad: medimos el token, no inventamos el precio).
GROQ_GPT_OSS_120B_USD_PER_1M_INPUT = 0.15
GROQ_GPT_OSS_120B_USD_PER_1M_OUTPUT = 0.60
GROQ_GPT_OSS_120B_PRICE_SOURCE = "groq.com/pricing (gpt-oss-120b $0.15/$0.60 per 1M; catalog/scoring-v0.md)"
_PRICED_MODEL = "openai/gpt-oss-120b"


def usd_for_gpt_oss_120b(prompt_tokens: int, completion_tokens: int) -> float:
    """USD del run a la tarifa publicada de Groq para gpt-oss-120b. tokens MEDIDOS ×
    precio CONSTANTE. Devuelve el costo redondeado a 8 decimales (microcentavos)."""
    usd = (
        int(prompt_tokens) / 1_000_000.0 * GROQ_GPT_OSS_120B_USD_PER_1M_INPUT
        + int(completion_tokens) / 1_000_000.0 * GROQ_GPT_OSS_120B_USD_PER_1M_OUTPUT
    )
    return round(usd, 8)


def build_cost(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    by_model: Optional[dict[str, Any]] = None,
    model_final: Optional[str] = None,
) -> dict[str, Any]:
    """Campo (5) costo: tokens MEDIDOS + USD a tarifa publicada. total se deriva.
    by_model opcional (desglose por modelo). model_final selecciona la tarifa: si es
    gpt-oss-120b, computamos usd_total con la constante documentada; si no, usd_total
    queda None (no aplicamos una tarifa que no corresponde)."""
    total = int(prompt_tokens) + int(completion_tokens)
    cost: dict[str, Any] = {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": total,
    }
    if by_model:
        cost["by_model"] = by_model
    # USD: solo si el modelo del run coincide con la tarifa que tenemos documentada.
    if model_final == _PRICED_MODEL and total > 0:
        cost["usd_total"] = usd_for_gpt_oss_120b(prompt_tokens, completion_tokens)
        cost["usd_input"] = round(int(prompt_tokens) / 1_000_000.0 * GROQ_GPT_OSS_120B_USD_PER_1M_INPUT, 8)
        cost["usd_output"] = round(int(completion_tokens) / 1_000_000.0 * GROQ_GPT_OSS_120B_USD_PER_1M_OUTPUT, 8)
        cost["price_model"] = _PRICED_MODEL
        cost["price_source"] = GROQ_GPT_OSS_120B_PRICE_SOURCE
    else:
        cost["usd_total"] = None  # sin tarifa documentada para este modelo → no inventamos
    return cost


def persist_run(
    conn,
    *,
    run_id: str,
    intent: Optional[str],
    belt: dict,
    trayectoria: list[dict],
    senal: Optional[dict] = None,
    costo: Optional[dict] = None,
) -> int:
    """
    Escribe LA fila del moat en instrumentation_logs, ligando por run_id los 5 campos.
    belt y trayectoria son obligatorios (NOT NULL en schema.sql §7). Devuelve el id
    (BIGSERIAL) de la fila. UNA fila por loop completo — no logs sueltos.

    Precondición: run_id debe existir en `runs` (FK). El caller crea el run primero
    (repo.create_run) y luego liga la instrumentación a ese mismo run_id.
    """
    if not run_id:
        raise ValueError("run_id requerido (es EL ligador del moat)")
    if belt is None:
        raise ValueError("belt requerido (campo 2 — snapshot de la receta)")
    if trayectoria is None:
        raise ValueError("trayectoria requerida (campo 3)")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO instrumentation_logs (run_id, intent, belt, trayectoria, senal, costo)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                run_id,
                intent,
                json.dumps(belt),
                json.dumps(trayectoria),
                json.dumps(senal) if senal is not None else None,
                json.dumps(costo) if costo is not None else None,
            ),
        )
        row_id = cur.fetchone()[0]
    conn.commit()
    return int(row_id)


def get_log(conn, run_id: str) -> Optional[dict[str, Any]]:
    """Lee la fila del moat ligada a un run_id (la última si hubiera varias)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, run_id, intent, belt, trayectoria, senal, costo, created_at "
            "FROM instrumentation_logs WHERE run_id = %s ORDER BY id DESC LIMIT 1",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, row))
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v is not None and type(v).__name__ == "UUID":
            out[k] = str(v)
    return out


__all__ = [
    "build_trayectoria",
    "trayectoria_from_file",
    "build_signal",
    "build_cost",
    "usd_for_gpt_oss_120b",
    "persist_run",
    "get_log",
]
