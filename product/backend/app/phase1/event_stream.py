"""
event_stream.py — SSE sobre los eventos que el loop YA emite (token-cost CERO).

Microtask (c): event stream SSE que PINTA los eventos que ya emite el loop
(platform/assembler/session.py + platform/flywheel/events_replay.py). Costo en tokens
= CERO: el modelo NO ve la pantalla; esto solo TRANSPORTA al frontend los eventos que
el motor ya persiste en events.jsonl. Nada de esto entra al prompt del agente.

Cómo funciona:
  - El loop persiste cada evento en events.jsonl ANTES de emitir (persist-before-emit,
    contrato de EVENTS-SCHEMA.md). events_replay.EventLog garantiza id monotónico
    contiguo, lo que hace EXACTO el replay con Last-Event-ID.
  - Este módulo abre ese events.jsonl como EventLog y produce un stream SSE:
      * primero hace catch-up: read_since(Last-Event-ID) → replay exacto de lo perdido;
      * luego hace tail: poll del archivo y emite los eventos nuevos a medida que aparecen;
      * cada frame SSE lleva `id:` = el id del evento (el browser lo manda como
        Last-Event-ID al reconectar → replay exacto sin huecos ni duplicados).
  - Se corta limpio en el evento `closed` (el espacio terminó) o cuando el cliente
    se desconecta (StreamingResponse lo detecta vía request.is_disconnected()).

format_sse / iter_sse_events son SINCRÓNICOS y testeables sin levantar el server
(la evidencia no necesita bindear un puerto). El router envuelve iter_sse_events en
un StreamingResponse async.

Stdlib only (+ events_replay cargado por ruta).
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Iterator, Optional

# event_stream.py: product/backend/app/phase1 -> repo root = parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_EVENTS_REPLAY_PY = _REPO_ROOT / "platform" / "flywheel" / "events_replay.py"


def _load_events_replay():
    import aleph_paths
    return aleph_paths.load_module_by_path("puppet_events_replay", _EVENTS_REPLAY_PY)


_er = None


def _events_replay():
    global _er
    if _er is None:
        _er = _load_events_replay()
    return _er


def format_sse(event: dict[str, Any]) -> str:
    """
    Formatea UN evento como frame SSE (Server-Sent Events):
        id: <id>\n
        event: <type>\n
        data: <json>\n\n
    El `id:` es el id monotónico del EventLog → el browser lo reenvía como
    Last-Event-ID al reconectar, habilitando replay EXACTO. El `event:` es el tipo
    (belt_ready, tool_call_finished, …) para que el front ruteé sin parsear el body.
    """
    lines: list[str] = []
    eid = event.get("id")
    if eid is not None:
        lines.append(f"id: {eid}")
    etype = event.get("type")
    if etype:
        lines.append(f"event: {etype}")
    # data debe ser una sola línea JSON (SSE separa por \n; un \n dentro rompería el frame)
    data = json.dumps(event, ensure_ascii=False)
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def replay_events(events_path: str | Path, last_event_id: int = 0) -> list[dict[str, Any]]:
    """
    Catch-up SIN tailing: devuelve EXACTAMENTE los eventos con id > last_event_id.
    Reconexión con Last-Event-ID=N ⇒ read_since(N) ⇒ {N+1..max}. Testeable directo.
    """
    log = _events_replay().EventLog(events_path)
    return log.read_since(int(last_event_id or 0))


def iter_sse_events(
    events_path: str | Path,
    *,
    last_event_id: int = 0,
    poll_interval: float = 0.25,
    idle_timeout_s: float = 30.0,
    heartbeat_s: float = 15.0,
    stop_on_closed: bool = True,
    is_disconnected: Optional[callable] = None,
) -> Iterator[str]:
    """
    Generador SÍNCRONO de frames SSE para un events.jsonl. Diseño:

      1. CATCH-UP: emite read_since(last_event_id) — replay exacto de lo perdido.
      2. TAIL: poll del archivo cada `poll_interval`; emite los eventos nuevos
         (id creciente) a medida que el loop los appendea.
      3. Heartbeat: si no hay eventos por `heartbeat_s`, emite un comentario SSE
         (`: ping`) para mantener viva la conexión (no es un evento del dominio).
      4. Corte: en el evento `closed` (si stop_on_closed) o si el cliente se
         desconectó (is_disconnected()) o tras `idle_timeout_s` sin novedad.

    is_disconnected: callable opcional que el router pasa (request.is_disconnected,
    adaptado a sync) para cortar cuando el browser cierra la pestaña.

    Token-cost CERO: este generador NO llama al modelo; solo transporta eventos ya
    persistidos. El agente nunca ve este stream.
    """
    log = _events_replay().EventLog(events_path)
    cursor = int(last_event_id or 0)

    # 1) catch-up
    for ev in log.read_since(cursor):
        cursor = int(ev["id"])
        yield format_sse(ev)
        if stop_on_closed and ev.get("type") == "closed":
            return

    # 2) tail
    last_activity = time.monotonic()
    last_beat = time.monotonic()
    while True:
        if is_disconnected is not None:
            try:
                if is_disconnected():
                    return
            except Exception:
                pass

        new_events = log.read_since(cursor)
        if new_events:
            for ev in new_events:
                cursor = int(ev["id"])
                yield format_sse(ev)
                if stop_on_closed and ev.get("type") == "closed":
                    return
            last_activity = time.monotonic()
            last_beat = time.monotonic()
        else:
            now = time.monotonic()
            if now - last_beat >= heartbeat_s:
                last_beat = now
                yield ": ping\n\n"  # comentario SSE: keep-alive, no es evento de dominio
            if now - last_activity >= idle_timeout_s:
                return
            time.sleep(poll_interval)


__all__ = ["format_sse", "replay_events", "iter_sse_events"]
