"""
run_handler.py — handler del job kind='puppet_run'.

NO reescribe la lógica de ejecución: arma las MISMAS costuras que el endpoint
síncrono /v1/puppets/run (router.run_puppet es la referencia canónica) y llama al
executor.run_puppet_e2e EXISTENTE. Lo único que cambia respecto del endpoint es
DÓNDE corre: en un thread del worker pool, no en el thread del request.

Reparto de responsabilidades:
  - VALIDACIÓN / AUTHZ / RAG-guard / carga de receta  → en el ENQUEUE (síncrono, rápido,
    devuelve 422 al toque si la receta rompe el contrato). Acá la receta ya viene lista.
  - EJECUCIÓN pesada (assemble_and_run + loop OSS + gate en el path + moat) → acá.

El executor crea el run en Postgres (paso 1), persiste instrumentation_logs y cierra
el run. El run_id producido se liga al job (mark_done).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _make_space_emitter(space_id: str, events_root: Optional[str]):
    """Costura a la Sala: reusa el EventLog de event_stream (persist-before-emit, id
    monotónico) — el MISMO que consume el SSE /spaces/{id}/stream. Un fallo emitiendo
    nunca tumba el run."""
    from app.phase1 import event_stream as es
    if events_root:
        root = Path(events_root)
    else:
        from app.espacios import DEFAULT_ESPACIOS_DIR
        root = DEFAULT_ESPACIOS_DIR
    from inspection.space_access import space_dir
    path = space_dir(root, space_id, create=True) / "events.jsonl"
    log = es._events_replay().EventLog(path)

    def emit(evt: dict) -> None:
        e = dict(evt)
        e["space_id"] = space_id
        try:
            log.append(e)
        except Exception:
            pass
    return emit


def handle(job: dict) -> dict:
    """Ejecuta un puppet run encolado. `job['payload']` trae receta+prompt+contexto.
    Devuelve el `out` del executor (incluye run_id, ok, answer, record…)."""
    payload = job.get("payload") or {}
    recipe = payload.get("recipe")
    prompt = payload.get("prompt") or ""
    user_id = payload.get("user_id") or job.get("user_id")
    space_id = payload.get("space_id")
    puppet_id = payload.get("puppet_id")
    deadline_s = float(payload.get("deadline_s") or 180.0)
    images = payload.get("images")
    lang = payload.get("lang") or "es"
    events_root = payload.get("events_root")

    if recipe is None:
        raise ValueError("payload sin `recipe` — el enqueue debe resolverla antes de encolar")

    from app.phase1 import executor, credential_broker

    # byok ligado a ESTE user (aislamiento por usuario; default get_conn = repo.get_conn)
    byok_resolver = credential_broker.make_user_resolver(user_id) if user_id else None

    # A2 · HOLD-AND-DEFER. La perilla de Autonomía (recipe.autonomy) vive DENTRO del gate
    # (candado runtime): el gate YA decidió auto/hold por clase de acción antes de llegar
    # acá. Todo lo que el gate marcó needs_ok REQUIERE OK humano — no se auto-concede.
    # El OK real llega por HTTP (POST /v1/runs/{id}/approve → approve_held_action).
    # Esto cierra el bug HEADLINE: un write-world genérico (create_pr, create_issue) que
    # el gate retuvo YA NO se rubber-stampea; y la perilla se respeta (relaja en el gate,
    # no acá). El piso money nunca baja (gate + assert_invariant).
    def _approve(_server, _tool, _payload):
        return False

    on_event = _make_space_emitter(space_id, events_root) if space_id else None

    out = executor.run_puppet_e2e(
        recipe, prompt,
        puppet_id=puppet_id, user_id=user_id, space_id=space_id,
        conn=None,  # el executor abre/cierra su propia conexión corta
        deadline_s=deadline_s,
        byok_resolver=byok_resolver,
        approve=_approve, on_event=on_event,
        images=images,
        lang=lang,
    )
    return out
