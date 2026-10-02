#!/usr/bin/env python3
"""
verify_async_run.py — PRUEBA VIVA del camino ASÍNCRONO del run (Gap #3).

Demuestra que un run VÁLIDO de ~50-60s (cerebro Opus real) llega al final SIN
cortarse, surfaceando progreso por SSE/EVENTS — el cliente NO se cuelga esperando
una respuesta bloqueante. Es el reverso del bug: el camino síncrono /v1/puppets/run
retiene la conexión la duración entera del run y un cliente con timeout < latencia
del cerebro (45s < ~55s) lo aborta. Acá:

  1) POST /v1/runs/enqueue        → devuelve job_id YA (no bloquea por el run).
  2) GET  /v1/spaces/{id}/stream  → SSE: progreso EN VIVO (tool_call_*, final,
                                     run_done, closed), cada evento con su timestamp.
  3) GET  /v1/jobs/{job_id}       → estado/resultado honesto del job (record completo).

Mide el wall-clock real, confirma model_final y los tool_calls reales, y verifica
que el stream siguió vivo más allá de 45s sin abortar.

Stdlib only. Corre contra un backend ya levantado (default :8085).

Uso:
    python verify_async_run.py --base http://127.0.0.1:8085 --recipe /ruta/recipe.json
    # recipe.json = {"recipe": {...}}  (mismo cuerpo que /v1/recipes/validate)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Optional


def _post(base: str, path: str, body: dict, timeout: float = 30.0) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": "<non-json>"}


def _get(base: str, path: str, timeout: float = 30.0) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": "<non-json>"}


class SSEConsumer(threading.Thread):
    """Consume el SSE del espacio en un hilo, sellando cada evento con su offset (s)
    desde t0. Reintenta el connect mientras el events.jsonl todavía no existe (el
    worker lo crea al reclamar el job) — igual que el cliente real del Cuarto."""

    def __init__(self, base: str, space_id: str, t0: float, connect_tries: int = 80,
                 connect_gap: float = 0.25, read_timeout: float = 240.0):
        super().__init__(daemon=True)
        self.base = base
        self.space_id = space_id
        self.t0 = t0
        self.connect_tries = connect_tries
        self.connect_gap = connect_gap
        self.read_timeout = read_timeout
        self.events: list[dict[str, Any]] = []
        self.connected_at: Optional[float] = None
        self.closed_at: Optional[float] = None
        self.last_event_at: Optional[float] = None
        self.error: Optional[str] = None
        self.stop_flag = threading.Event()

    def _now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def run(self) -> None:
        url = f"{self.base}/v1/spaces/{self.space_id}/stream"
        resp = None
        for _ in range(self.connect_tries):
            if self.stop_flag.is_set():
                return
            try:
                resp = urllib.request.urlopen(url, timeout=self.read_timeout)
                self.connected_at = self._now()
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    time.sleep(self.connect_gap)  # events.jsonl aún no existe → reintentar
                    continue
                self.error = f"HTTP {e.code}"
                return
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                time.sleep(self.connect_gap)
                continue
        if resp is None:
            self.error = self.error or "no se pudo conectar al stream (timeout de connect)"
            return

        cur_event: Optional[str] = None
        try:
            for raw in resp:
                if self.stop_flag.is_set():
                    break
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith(":"):
                    continue  # heartbeat / comentario SSE
                if line.startswith("event:"):
                    cur_event = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    try:
                        ev = json.loads(payload)
                    except Exception:
                        ev = {"_raw": payload}
                    etype = ev.get("type") or cur_event or "?"
                    off = self._now()
                    self.last_event_at = off
                    self.events.append({"t": off, "type": etype,
                                        "tool": ev.get("tool") or ev.get("tool_raw"),
                                        "model_final": ev.get("model_final"),
                                        "ok": ev.get("ok"),
                                        "run_id": ev.get("run_id")})
                    if etype in ("closed", "run_done", "stream_idle_close"):
                        if etype == "closed":
                            self.closed_at = off
                    cur_event = None
                # línea en blanco = separador de frame
        except Exception as e:  # noqa: BLE001
            self.error = f"read: {type(e).__name__}: {e}"
        finally:
            try:
                resp.close()
            except Exception:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8085")
    ap.add_argument("--recipe", required=True, help="JSON con {\"recipe\": {...}}")
    ap.add_argument("--prompt", default=(
        "Calculá PASO A PASO usando SOLO las herramientas, una operación por turno: "
        "(1) sumá 123 + 877. (2) multiplicá ese resultado por 12. (3) sumale 4096. "
        "(4) multiplicá por 7. (5) sumale 55. Mostrá el resultado de cada paso y el total final."))
    ap.add_argument("--space", default=None)
    ap.add_argument("--max-wait", type=float, default=240.0)
    args = ap.parse_args()

    recipe_body = json.loads(open(args.recipe).read())
    recipe = recipe_body.get("recipe", recipe_body)
    space_id = args.space or f"fixrun-{int(time.time())}-{int(time.monotonic()*1000) % 100000}"

    print(f"== verify_async_run ==  base={args.base}  space={space_id}")

    # 0) validar (no encolar basura — el 422 sobre receta inválida es correcto)
    st, val = _post(args.base, "/v1/recipes/validate", {"recipe": recipe})
    print(f"[validate] status={st} valid={val.get('valid')} errors={val.get('errors')}")
    if not (st == 200 and val.get("valid")):
        print("RECETA INVÁLIDA — abortando (esto es correcto, no es el bug del run).")
        return 2

    t0 = time.monotonic()
    sse = SSEConsumer(args.base, space_id, t0)
    sse.start()

    # 1) ENQUEUE — vuelve YA con job_id (el request NO se bloquea por el run)
    st, enq = _post(args.base, "/v1/runs/enqueue",
                    {"recipe": recipe, "prompt": args.prompt, "space_id": space_id})
    enq_dt = round(time.monotonic() - t0, 2)
    print(f"[enqueue] status={st} job_id={enq.get('job_id')} (devolvió en {enq_dt}s — NO bloqueó)")
    if st != 201 or not enq.get("job_id"):
        print(f"ENQUEUE FALLÓ: {enq}")
        sse.stop_flag.set()
        return 3
    job_id = enq["job_id"]

    # 2) esperar a que el job termine, mostrando progreso del SSE en vivo
    last_n = 0
    job = {}
    deadline = t0 + args.max_wait
    while time.monotonic() < deadline:
        st, job = _get(args.base, f"/v1/jobs/{job_id}")
        status = job.get("status")
        if len(sse.events) > last_n:
            for ev in sse.events[last_n:]:
                extra = f" tool={ev['tool']}" if ev.get("tool") else ""
                extra += f" model_final={ev['model_final']}" if ev.get("model_final") else ""
                print(f"  SSE  t+{ev['t']:>6.2f}s  {ev['type']}{extra}")
            last_n = len(sse.events)
        if status in ("done", "error"):
            break
        time.sleep(1.0)

    total = round(time.monotonic() - t0, 2)
    # drenar últimos eventos del SSE (final/run_done/closed pueden llegar justo al cierre)
    time.sleep(2.0)
    for ev in sse.events[last_n:]:
        extra = f" tool={ev['tool']}" if ev.get("tool") else ""
        extra += f" model_final={ev['model_final']}" if ev.get("model_final") else ""
        print(f"  SSE  t+{ev['t']:>6.2f}s  {ev['type']}{extra}")
    sse.stop_flag.set()

    # 3) RESULTADO honesto (record completo del job)
    result = job.get("result") or {}
    record = result.get("record") or {}
    tool_events = [e for e in sse.events if e["type"] in ("tool_call_started", "tool_call_finished")]
    tool_finished = [e for e in sse.events if e["type"] == "tool_call_finished"]
    types_seen = sorted({e["type"] for e in sse.events})

    print("\n== RESULTADO ==")
    print(f"  wall-clock total          : {total}s")
    print(f"  job.status                : {job.get('status')}")
    print(f"  run_id                    : {result.get('run_id')}")
    print(f"  ok                        : {result.get('ok')}")
    print(f"  model_final               : {record.get('model_final')}")
    print(f"  degraded                  : {result.get('degraded')}")
    print(f"  error                     : {result.get('error')}")
    print(f"  tool_calls (record.turns) : {record.get('turns')}")
    print(f"  tools_cabled              : {record.get('tools_cabled')}")
    print(f"  SSE event types           : {types_seen}")
    print(f"  SSE tool_call_finished    : {len(tool_finished)}")
    print(f"  SSE connected_at          : t+{sse.connected_at}s")
    print(f"  SSE last_event_at         : t+{sse.last_event_at}s")
    print(f"  SSE error                 : {sse.error}")

    # ── VEREDICTO del done-bar ──────────────────────────────────────────────
    checks = {
        "run llegó al final (job done)": job.get("status") == "done",
        "ok=true": result.get("ok") is True,
        "model_final=claude-opus-4.8": record.get("model_final") == "claude-opus-4.8",
        "tool_calls reales (>=1 finished por SSE)": len(tool_finished) >= 1,
        "duró > 45s (supera el timeout del cliente viejo)": total > 45.0,
        "SSE vivo más allá de 45s (no cortó mudo)": (sse.last_event_at or 0) > 45.0,
        "no degradado a OSS (cerebro Opus respondió)": not result.get("degraded"),
    }
    print("\n== VEREDICTO done-bar ==")
    ok_all = True
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'XX'}] {k}")
        ok_all = ok_all and v
    print(f"\n{'✅ DONE-BAR VERDE' if ok_all else '❌ falta algo'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
