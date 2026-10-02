#!/usr/bin/env python3
"""
STEP 4 · 4A KEYSTONE — space-threaded run + live SSE-spine consumer (committable verify).

Guards the keystone wired into product/app/design/sala/sala.html:
  1. buildBody(prompt, spaceId) threads `space_id` into the run body (keyless + puppet).
  2. La Sala consumes GET /v1/spaces/{id}/stream via fetch+ReadableStream (Bearer-capable,
     NOT EventSource), in PARALLEL with the BLOCKING POST /v1/puppets/run.
  3. The blocking `out` stays the TERMINAL truth (deliverable + held_actions); the stream is
     ADDITIVE live progress.

LAYER B (static, no backend): assert sala.html is actually wired (the file the browser runs).
LAYER A (live, vs a FRESH backend on :8093): two SEQUENTIAL keyless runs, each POSTed WITH a
  space_id while a stdlib mirror of sala.html's fetch/ReadableStream consumer drains the spine:

  · CASE gate    — the real Sala keyless recipe (belt-inline-rich). Post-S16 the belt DECLARES
     calc/run_python as read/write-local (they auto-execute), so the gate is now demonstrated with
     `datatools.write_xlsx`: its name trips the gate's external-write floor ('write') BEFORE any
     declaration, so it stays HELD. Proves the consumer receives the LIVE Frontera freeze
     (`gate_waiting`) BEFORE the blocking POST resolves, and live gate == terminal out.held_actions
     (seam S4: gate no longer post-hoc). [The gate MECHANISM is unchanged; only the example tool
     moved from calc to write_xlsx — S16: the gate protects what touches the world, not arithmetic.]
  · CASE compute — SAME recipe (belt-inline-rich, NO recipe-level action_classes). The BELT itself
     declares calc.*→read (S16), folded server-side by the assembler → calc auto-executes → the
     consumer receives `tool_call_finished{result}` LIVE, and pure-compute → Frontera collapses
     (held==0). Proves the belt's declaration alone un-gates arithmetic (no recipe override needed).

Anti-grift (both cases): degraded∈{None,False} AND tool_calls>0 AND
  model_final ∈ opus-4.8-FAMILY ∪ BYOK   (regex family, NEVER literal equality — a genuine run
  emitted `claude-opus-4.8`, the shim advertises `claude-code-opus-4.8`, BYOK differs; a literal
  match would red-flag a healthy run).

Usage:  STEP4_BASE=http://127.0.0.1:8093 python3 product/app/design/sala/verify_step4_keystone.py
Env: STEP4_BASE (default http://127.0.0.1:8093) · STEP4_TOKEN (Bearer for an owned-space run;
     omit → anonymous/open space) · STEP4_ESPACIOS (events.jsonl dir) · STEP4_BYOK_MODELS (csv).
Exit 0 = all green.
"""
import copy
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("STEP4_BASE", "http://127.0.0.1:8093").rstrip("/")
TOKEN = os.environ.get("STEP4_TOKEN", "").strip()
HERE = Path(__file__).resolve()
SALA_HTML = HERE.parent / "sala.html"
REPO = HERE.parents[4]  # product/app/design/sala/<file> -> repo root
ESPACIOS = Path(os.environ.get("STEP4_ESPACIOS", str(REPO / "product/backend/data/espacios")))

FAMILY_RE = re.compile(r"^claude-(code-)?opus-4[.\-]8$")  # never a literal equality
BYOK_SET = set(filter(None, os.environ.get("STEP4_BYOK_MODELS", "").split(",")))

# Faithful to buildBody()'s keyless else-branch in sala.html (belt-inline-rich → calc real).
KEYLESS_RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "Tu agente", "nicho": "general", "output_type": "informe"},
    "model": {"primary": "openai/gpt-oss-120b", "fallback": "llama-3.3-70b-versatile",
              "base_url": "https://api.groq.com/openai/v1",
              "temperature": 0.2, "max_tokens": 1400, "max_turns": 4},
    "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
             "tool_filters": {"pysandbox": ["run_python"],
                              "datatools": ["write_xlsx", "write_csv"],
                              "calc": ["add", "sub", "mul", "div", "pow", "mod"]}},
    "framing": {"inline": ""},
    "rag": {"enabled": False},
    "keys": {},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}
# Post-S16 BOTH cases use the SAME recipe: the BELT (belt-inline-rich._meta.action_classes) declares
# calc.*→read and run_python→write-local, and the assembler folds that into recipe.belt.action_classes
# server-side. So NO recipe-level override is needed — the belt's declaration alone auto-executes calc.
COMPUTE_RECIPE = copy.deepcopy(KEYLESS_RECIPE)
# COMPUTE prompt → induces a calc.mul (auto-executes via the belt declaration; pure-compute collapse).
COMPUTE_PROMPT = ("¿Cuánto es 1234 por 5678? Usá SOLO la herramienta calc (no calcules de cabeza) "
                  "y mostrá el resultado.")
# GATE prompt → induces datatools.write_xlsx (the 'write' external floor keeps it HELD post-S16).
# EXPLÍCITO sobre la tool: sin esto el modelo podría escribir el .xlsx vía pysandbox.run_python
# (write-local → AUTO-EXEC) y el caso no gatearía. Forzamos write_xlsx (la tool gateada) para
# probar el PISO 'write', no la preferencia de tool del modelo.
GATE_PROMPT = ("Generá un archivo Excel (.xlsx) con esta tabla: fila 1 = [a, 1], fila 2 = [b, 2]. "
               "Usá EXCLUSIVAMENTE la herramienta write_xlsx (del server datatools) para escribir "
               "el archivo — NO uses run_python ni pysandbox, NO lo describas: escribilo con write_xlsx.")
PROMPT = COMPUTE_PROMPT   # back-comp (layer_b/otros no lo usan; run_case recibe el prompt explícito)

RESET, GREEN, RED, DIM, BOLD = "\033[0m", "\033[32m", "\033[31m", "\033[2m", "\033[1m"


def _headers(extra=None):
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    if extra:
        h.update(extra)
    return h


def _auth_only():
    return {"Authorization": "Bearer " + TOKEN} if TOKEN else {}


# ── LAYER B · static wiring assertions on the real sala.html ──────────────────
def layer_b():
    txt = SALA_HTML.read_text(encoding="utf-8")
    checks = [
        ("buildBody gains spaceId param",     "function buildBody(prompt, spaceId)" in txt),
        ("space_id threaded in BOTH bodies",  txt.count("space_id:spaceId") >= 2),
        ("newSpaceId() helper present",       "function newSpaceId()" in txt),
        ("openSpineConsumer() present",       "function openSpineConsumer(spaceId" in txt),
        ("consumer opens the space stream",   "/v1/spaces/'+encodeURIComponent(spaceId)+'/stream'" in txt),
        ("consumer uses ReadableStream",      ".getReader()" in txt),
        ("consumer is NOT EventSource",       "new EventSource(" not in txt),
        ("run site opens the consumer",       "openSpineConsumer(_spaceId)" in txt),
        ("run site threads space_id to run",  "buildBody(prompt, _spaceId)" in txt),
        ("consumer stopped at terminal out",  "stopSpineConsumer()" in txt),
    ]
    ok = all(v for _, v in checks)
    print(f"\n{DIM}── LAYER B · static wiring in sala.html ──{RESET}")
    for name, v in checks:
        print(f"  {GREEN+'PASS'+RESET if v else RED+'FAIL'+RESET}  {name}")
    return ok, {"checks": [{"name": n, "ok": v} for n, v in checks]}


# ── LAYER A · live run + parallel spine consumer ──────────────────────────────
def _parse_sse(resp, events, marks, stop_flag):
    """Mirror of sala.html's consumer: SSE frames (blank-line separated) → take the `data:`
    line → JSON.parse → dispatch on the payload's top-level `type`. Records first-seen times."""
    frame = []
    for raw in resp:
        if stop_flag["stop"]:
            break
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            data_line = next((l for l in frame if l.startswith("data:")), None)
            frame = []
            if not data_line:
                continue
            try:
                ev = json.loads(data_line[5:].strip())
            except Exception:
                continue
            events.append(ev)
            typ = ev.get("type") or ev.get("kind")
            now = time.monotonic()
            if typ in ("tool_call_finished", "gate_waiting") and marks["first_work"] is None:
                marks["first_work"] = now
            if typ == "tool_call_finished" and marks["first_tcf"] is None:
                marks["first_tcf"] = now
            if typ == "gate_waiting" and marks["first_gate"] is None:
                marks["first_gate"] = now
            if typ == "closed":
                return
        else:
            frame.append(line)


def _consume(space_id, events, marks, stop_flag, deadline):
    url = f"{BASE}/v1/spaces/{space_id}/stream"
    while time.monotonic() < deadline and not stop_flag["stop"]:
        req = urllib.request.Request(url, headers=_auth_only(), method="GET")
        try:
            resp = urllib.request.urlopen(req, timeout=max(5.0, deadline - time.monotonic()))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # events.jsonl not born yet → run hasn't emitted step 1
                time.sleep(0.25)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(0.25)
            continue
        try:
            _parse_sse(resp, events, marks, stop_flag)
        finally:
            try:
                resp.close()
            except Exception:
                pass
        return


def run_case(label, recipe, mode, prompt):
    space_id = f"sala-verify-{mode}-{int(time.time())}"
    post_res = {}
    t0 = time.monotonic()
    deadline = t0 + 320

    def do_post():
        body = {"recipe": recipe, "prompt": prompt, "space_id": space_id, "deadline_s": 240}
        req = urllib.request.Request(BASE + "/v1/puppets/run",
                                     data=json.dumps(body).encode(),
                                     headers=_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=320) as r:
                post_res["out"] = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            post_res["error"] = f"{type(e).__name__}: {e}"
        finally:
            post_res["t_done"] = time.monotonic()

    print(f"\n{DIM}── LAYER A · CASE {BOLD}{label}{RESET}{DIM} · vs {BASE} · space_id={space_id} ──{RESET}")
    events, marks, stop_flag = [], {"first_work": None, "first_tcf": None, "first_gate": None}, {"stop": False}
    t = threading.Thread(target=do_post, daemon=True)
    t.start()
    _consume(space_id, events, marks, stop_flag, deadline)
    t.join(timeout=max(1.0, deadline - time.monotonic()))
    stop_flag["stop"] = True

    if "out" not in post_res:
        print(f"  {RED}POST did not return: {post_res.get('error', 'timeout')}{RESET}")
        return False, {"case": label, "space_id": space_id,
                       "post_error": post_res.get("error", "timeout"), "events_n": len(events)}

    out = post_res["out"]
    t_done = post_res.get("t_done")
    rec = out.get("record") or {}
    model_final = rec.get("model_final") or out.get("model_final")
    degraded = rec.get("degraded", out.get("degraded"))
    tool_calls = rec.get("tool_calls") or []
    held = out.get("held_actions")
    answer = (out.get("answer") or "").strip()
    obra = out.get("obra")

    types = {}
    for e in events:
        k = e.get("type") or e.get("kind") or "?"
        types[k] = types.get(k, 0) + 1
    tcf_result = [e for e in events
                  if (e.get("type") or e.get("kind")) == "tool_call_finished" and "result" in e]
    gate_evs = [e for e in events if (e.get("type") or e.get("kind")) == "gate_waiting"]

    def rel(x):
        return "—" if x is None else f"{x - t0:.1f}s"

    # (1) events.jsonl persisted (disk) + snapshot endpoint agrees
    jsonl = ESPACIOS / space_id / "events.jsonl"
    disk_n = sum(1 for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()) \
        if jsonl.exists() else 0
    snap_n = 0
    try:
        req = urllib.request.Request(f"{BASE}/v1/spaces/{space_id}/events",
                                     headers=_auth_only(), method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            snap_n = len(json.loads(r.read().decode()).get("events", []))
    except Exception:
        pass

    live_before_post = marks["first_work"] is not None and t_done is not None \
        and marks["first_work"] <= t_done

    # (3) terminal out carries deliverable + held ledger  ·  anti-grift  (both cases)
    terminal_ok = out.get("ok") is True and (bool(answer) or obra is not None) and isinstance(held, list)
    mf = model_final or ""
    grift_ok = degraded in (None, False) and len(tool_calls) > 0 \
        and (bool(FAMILY_RE.match(mf)) or mf in BYOK_SET)

    checks = [("(1) events.jsonl populated (disk & snapshot)", disk_n > 0 and snap_n > 0)]
    if mode == "compute":
        checks += [
            ("(2) consumer got tool_call_finished{result} LIVE (≤ POST resolve)",
             live_before_post and marks["first_tcf"] is not None and len(tcf_result) > 0),
            ("(3) terminal out carries deliverable + held ledger", terminal_ok),
            ("(4) pure-compute → Frontera collapses (held==0)",
             isinstance(held, list) and len(held) == 0),
        ]
    else:  # gate
        checks += [
            ("(2·S4) consumer got gate_waiting LIVE Frontera freeze (≤ POST resolve)",
             live_before_post and marks["first_gate"] is not None and len(gate_evs) > 0),
            ("(3) terminal out carries deliverable + held ledger", terminal_ok),
            ("(5) live gate == terminal held_actions (stream ≡ terminal truth)",
             len(gate_evs) == len(held or []) and len(held or []) > 0),
        ]
    checks.append(("(A) anti-grift: !degraded & tools>0 & model_final∈opus-4.8∪BYOK", grift_ok))

    print(f"  {DIM}events via stream: {types}{RESET}")
    print(f"  {DIM}disk_n={disk_n} snap_n={snap_n} first_work@={rel(marks['first_work'])} "
          f"first_tcf@={rel(marks['first_tcf'])} first_gate@={rel(marks['first_gate'])} "
          f"post_done@={rel(t_done)}{RESET}")
    print(f"  {DIM}model_final={model_final!r} degraded={degraded!r} tool_calls={len(tool_calls)} "
          f"held={len(held or [])} ok={out.get('ok')!r} tcf_result={len(tcf_result)}{RESET}")
    print(f"  {DIM}answer[:110]={answer[:110]!r}{RESET}")
    for name, v in checks:
        print(f"  {GREEN+'PASS'+RESET if v else RED+'FAIL'+RESET}  {name}")

    ok = all(v for _, v in checks)
    ev = {"case": label, "mode": mode, "space_id": space_id, "disk_n": disk_n, "snapshot_n": snap_n,
          "event_types": types, "first_work_before_post": live_before_post,
          "tcf_with_result": len(tcf_result), "gate_events": len(gate_evs),
          "model_final": model_final, "degraded": degraded, "tool_calls": len(tool_calls),
          "held_actions": len(held or []), "ok": out.get("ok"), "answer_head": answer[:200],
          "checks": [{"name": n, "ok": v} for n, v in checks]}
    return ok, ev


def main():
    print(f"{DIM}STEP4 keystone verify · base={BASE} · sala={SALA_HTML.name} · espacios={ESPACIOS}{RESET}")
    b_ok, b_ev = layer_b()
    # SEQUENTIAL (qwen/Ollama or shim concurrency → false reds): gate case, then compute case.
    g_ok, g_ev = run_case("gate    (belt-inline · write_xlsx → HELD por piso 'write')", KEYLESS_RECIPE, "gate", GATE_PROMPT)
    c_ok, c_ev = run_case("compute (belt declara calc→read → AUTO-EXEC · collapse)", COMPUTE_RECIPE, "compute", COMPUTE_PROMPT)
    evidence = {"layer_b_ok": b_ok, "gate_ok": g_ok, "compute_ok": c_ok,
                "layer_b": b_ev, "case_gate": g_ev, "case_compute": c_ev}
    out_path = HERE.parent / "EVIDENCE-step4-keystone.json"
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    allok = b_ok and g_ok and c_ok
    print(f"\n{DIM}evidence → {out_path}{RESET}")
    print((GREEN + BOLD + "ALL GREEN ✓" if allok else RED + BOLD + "RED ✗") + RESET
          + f"   (layer_b={'green' if b_ok else 'red'} · gate={'green' if g_ok else 'red'} · "
          f"compute={'green' if c_ok else 'red'})")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
