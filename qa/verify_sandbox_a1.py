#!/usr/bin/env python3
"""verify_sandbox_a1.py — CERTIFICACIÓN de STEP 2 · A1.

A1 = aislamiento de ESTADO por run + LOOPS controlados + MUERTE LIMPIA, cableado al
runtime VIVO. Este harness prueba DE VERDAD (no "el archivo existe"):

  A. PUREZA / AISLAMIENTO DE ESTADO (determinista)
     A.1  _expand_str expande ${VAR}/$VAR contra el env del RUN sin tocar os.environ
          global (era el bug del swap: bajo workers concurrentes una key BYOK de un run
          se filtraba al config de otro). Verifica identidad de os.environ + no-fuga.
     A.2  FRONTERA · clamp_runtime_caps: una receta NO puede subir sus techos por
          encima del tier (solo baja). Tabla free/basico/tecnico.

  B. LOOPS CONTROLADOS + MUERTE LIMPIA (in-process, brain scripteado → determinista;
     belt calc REAL, gate REAL, loop REAL de assemble_and_run — lo único guionado es
     la cognición, para forzar la condición patológica que un modelo no repite a pedido)
     B.1  loop-detection: mismo (tool+args) N× consecutivo ⇒ corta + evento loop_detected
     B.2  budget: max_tool_calls del run ⇒ corta + evento budget_exhausted
     B.3  deadline mid-turn: el run vencido corta dentro del turno, no cuelga
     B.4  compaction VISIBLE: al podar historial emite context_compacted (no silencioso)
     B.5  muerte limpia: al cortar hay respuesta HONESTA no vacía + stop_reason en el record

  C. FRONTERA CABLEADA AL EXECUTOR (in-process, DB real): el path de prod clampa los
     techos de la receta al tier del usuario ANTES de correr (recipe editada no sube).

  D. RUNTIME VIVO (HTTP :8090): un run real por /v1/puppets/run cumple anti-grift
     (degraded==null + model_final == el declarado + tool_calls>0) y dos runs
     CONCURRENTES no se contaminan (run_ids distintos, cada respuesta a lo suyo).

Uso:
    python3 qa/verify_sandbox_a1.py
    BASE=http://127.0.0.1:8090 python3 qa/verify_sandbox_a1.py   # server del worktree
Requisitos vivos (para B/C/D): belt calc bootea (credential-free); Postgres; Ollama
qwen3:8b @ :11434; server del worktree en BASE. A/B/C no tocan la red del modelo.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_THIS = Path(__file__).resolve()
REPO_ROOT = _THIS.parents[1]
sys.path.insert(0, str(REPO_ROOT / "platform" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "platform"))
sys.path.insert(0, str(REPO_ROOT / "platform" / "gates"))

import recipe_assembler as ra  # noqa: E402
from recipe_enforcer import clamp_runtime_caps, TIER_RUNTIME_CAPS  # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8090")
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


# ── brain scripteado: fuerza secuencias de tool-calls que un modelo real no repite ──
def scripted_route(seq, *, final_text="Cierre honesto: resumen de lo hecho.", sleep_s=0.0,
                   validate_history=False):
    """Devuelve un reemplazo de ra._route_chat. `seq` = [(tool, args_dict), ...]; cuando
    se agota, repite el ÚLTIMO. Con tools=[] (cierre honesto / reporter) devuelve texto
    plano final (no tool-call). Firma idéntica a _route_chat.
    validate_history=True: en el cierre, mimetiza a un provider OpenAI-compat y LANZA 400 si
    algún assistant tiene tool_calls sin su reply role:tool → así el test detecta si la
    reparación de huérfanos (A1 #1) NO se aplicó (la síntesis caería al mensaje genérico)."""
    state = {"i": 0}

    def fake(messages, tools, *, base_url=None, primary=None, fallback=None, on_tier_error=None,
             api_key=None, max_tokens=None, temperature=None, route_log=None):
        if sleep_s:
            time.sleep(sleep_s)
        model = "fake-brain"
        if route_log is not None:
            route_log.append({"tier": "test", "model": model, "ok": True})
        if not tools:  # el cierre honesto / reporter pide síntesis SIN tools
            if validate_history:
                _ans = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
                for m in messages:
                    if m.get("role") == "assistant":
                        for tc in (m.get("tool_calls") or []):
                            if tc.get("id") and tc["id"] not in _ans:
                                raise RuntimeError("provider 400: tool_call_id sin response (historial huérfano)")
            return ({"choices": [{"message": {"role": "assistant", "content": final_text},
                                  "finish_reason": "stop"}], "usage": {}}, model)
        i = state["i"]
        state["i"] += 1
        name, args = seq[i] if i < len(seq) else seq[-1]
        tc = {"id": f"call_{i}", "type": "function",
              "function": {"name": name, "arguments": json.dumps(args)}}
        return ({"choices": [{"message": {"role": "assistant", "content": "",
                                          "tool_calls": [tc]},
                              "finish_reason": "tool_calls"}], "usage": {}}, model)
    return fake


def calc_recipe(**model_overrides) -> dict:
    m = {"primary": "fake", "base_url": "http://127.0.0.1:9/v1",
         "temperature": 0, "max_tokens": 128, "max_turns": 10}
    m.update(model_overrides)
    return {"schema_version": "v1", "meta": {"name": "A1 sandbox test", "nicho": "test"},
            "model": m,
            # A2 · el cómputo local se DECLARA write-local (post review: sin heurística de
            # cómputo-por-nombre; add/mul son aritmética en caja → auto bajo balanceado).
            "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]},
                     "action_classes": {"calc": {"add": "write-local", "mul": "write-local"}}},
            "framing": {"inline": "Agente de prueba."},
            "rag": {"enabled": False}, "keys": {}, "gates": {}}


def run_inproc(recipe, prompt, **kw):
    """assemble_and_run con colector de eventos. Devuelve (record, events)."""
    events = []
    rec = ra.assemble_and_run(recipe, prompt, repo_root=REPO_ROOT,
                              on_event=lambda e: events.append(e), **kw)
    return rec, events


# ══════════════════════════════════════════════════════════════════════════════════
def section_A_pure():
    print("\n── A · PUREZA / AISLAMIENTO DE ESTADO (determinista) ──")
    env = {"PUPPET_WORKDIR": "/w", "FOO_API_KEY": "sekret"}
    check("A.1a ${VAR}/path expande", ra._expand_str("${PUPPET_WORKDIR}/m.json", env) == "/w/m.json")
    check("A.1b $VAR expande", ra._expand_str("$FOO_API_KEY", env) == "sekret")
    check("A.1c desconocida queda literal", ra._expand_str("${NOPE}", env) == "${NOPE}")
    check("A.1d no-string passthrough", ra._expand_str(123, env) == 123)
    os.environ["A1_SENTINEL"] = "keep"
    _id = id(os.environ)
    ra._expand_str("${FOO_API_KEY}-${PUPPET_WORKDIR}", env)
    check("A.1e os.environ NO se swapea (misma identidad)", id(os.environ) == _id)
    check("A.1f os.environ intacto (sentinel vive)", os.environ.get("A1_SENTINEL") == "keep")
    check("A.1g env del run NO se filtra a os.environ",
          "FOO_API_KEY" not in os.environ and "PUPPET_WORKDIR" not in os.environ)

    check("A.2a free clampa turns 9999→8", clamp_runtime_caps({"max_turns": 9999}, "free")["max_turns"] == 8)
    check("A.2b free impone 40 tool-calls", clamp_runtime_caps({}, "free")["max_tool_calls"] == 40)
    check("A.2c respeta un pedido MENOR (6<8)", clamp_runtime_caps({"max_turns": 6}, "free")["max_turns"] == 6)
    check("A.2d tecnico techos altos", clamp_runtime_caps({}, "tecnico") == {"max_turns": 40, "max_tool_calls": 400})
    check("A.2e tier desconocido→free", clamp_runtime_caps({}, "x") == {"max_turns": 8, "max_tool_calls": 40})
    _m = {"max_turns": 100}
    clamp_runtime_caps(_m, "free")
    check("A.2f no muta el input", _m == {"max_turns": 100})


def section_B_loops():
    print("\n── B · LOOPS CONTROLADOS + MUERTE LIMPIA (brain scripteado, belt/gate/loop REALES) ──")
    _orig = ra._route_chat
    try:
        # B.1 loop-detection: misma add(1,1) siempre → corta al 3er consecutivo
        ra._route_chat = scripted_route([("add", {"a": 1, "b": 1})])
        rec, ev = run_inproc(calc_recipe(max_turns=10, loop_detect_n=3), "loop")
        types = [e.get("type") for e in ev]
        check("B.1a emite loop_detected", "loop_detected" in types, f"types={set(types)}")
        check("B.1b stop_reason=loop_detected", rec.get("stop_reason") == "loop_detected", f"stop={rec.get('stop_reason')}")
        check("B.1c cortó ANTES de max_turns", rec.get("turns", 99) < 10, f"turns={rec.get('turns')}")
        check("B.1d ejecutó exactamente N=3 (result-aware, no ∞)", len(rec.get("tool_calls", [])) == 3, f"calls={len(rec.get('tool_calls', []))}")
        check("B.1e truncated marcado", rec.get("truncated") is True)

        # B.2 budget: distintas calls, techo 2 → budget_exhausted a la 3ra
        ra._route_chat = scripted_route([("add", {"a": 1, "b": 1}), ("mul", {"a": 2, "b": 2}),
                                         ("add", {"a": 3, "b": 3}), ("mul", {"a": 4, "b": 4})])
        rec, ev = run_inproc(calc_recipe(max_turns=10, max_tool_calls=2, loop_detect_n=9), "budget")
        types = [e.get("type") for e in ev]
        check("B.2a emite budget_exhausted", "budget_exhausted" in types, f"types={set(types)}")
        check("B.2b stop_reason=budget_exhausted", rec.get("stop_reason") == "budget_exhausted")
        check("B.2c ejecutó exactamente el techo (2)", len(rec.get("tool_calls", [])) == 2, f"calls={len(rec.get('tool_calls', []))}")

        # B.3 deadline mid-turn: brain tarda 0.4s, deadline absoluto now+0.3 → corta en el turno
        ra._route_chat = scripted_route([("add", {"a": 1, "b": 1})], sleep_s=0.4)
        t0 = time.monotonic()
        rec, ev = run_inproc(calc_recipe(max_turns=10, loop_detect_n=9), "deadline",
                             _deadline_abs=time.monotonic() + 0.3)
        elapsed = time.monotonic() - t0
        check("B.3a stop_reason=deadline", rec.get("stop_reason") == "deadline", f"stop={rec.get('stop_reason')}")
        check("B.3b NO se colgó (<10s)", elapsed < 10.0, f"elapsed={elapsed:.1f}s")
        check("B.3c truncated marcado", rec.get("truncated") is True)

        # B.4 compaction VISIBLE (UNA vez) + SIN falso loop: 12 turnos con calls DISTINTAS
        # y loop_detect_n default → poda >8 → context_compacted una vez; NUNCA loop_detected.
        ra._route_chat = scripted_route([("add", {"a": k, "b": k}) for k in range(1, 13)],
                                        final_text="fin")
        rec, ev = run_inproc(calc_recipe(max_turns=12), "compaction")
        types = [e.get("type") for e in ev]
        check("B.4a emite context_compacted (pruning no silencioso)",
              "context_compacted" in types, f"types={set(types)}")
        check("B.4b context_compacted UNA sola vez (no spam por-turno)",
              types.count("context_compacted") == 1, f"count={types.count('context_compacted')}")
        check("B.4c SIN falso loop con calls variadas (result-aware)",
              "loop_detected" not in types, f"types={set(types)}")

        # B.5 muerte limpia + REPARACIÓN de huérfanos (#1): el techo de tool-calls corta ANTES
        # de ejecutar la 3ra call → su tool_call queda huérfano. Con un cierre que VALIDA el
        # historial como un provider OpenAI-compat, la síntesis SÓLO devuelve el texto final si
        # la reparación cerró el huérfano; si no, lanzaría 400 → caería al mensaje genérico.
        ra._route_chat = scripted_route(
            [("add", {"a": 1, "b": 1}), ("mul", {"a": 2, "b": 2}), ("add", {"a": 3, "b": 3})],
            final_text="Síntesis honesta: junté 2 resultados antes de cortar.",
            validate_history=True)
        rec, ev = run_inproc(calc_recipe(max_turns=10, max_tool_calls=2, loop_detect_n=9), "orphan repair")
        ans = (rec.get("answer") or "").strip()
        check("B.5a síntesis honesta tras corte (historial reparado, sin 400)",
              ans == "Síntesis honesta: junté 2 resultados antes de cortar.", f"answer={ans!r}")
        check("B.5b stop_reason=budget_exhausted", rec.get("stop_reason") == "budget_exhausted")
        check("B.5c evento final presente", any(e.get("type") == "final" for e in ev))
    finally:
        ra._route_chat = _orig


def section_C_frontera_executor():
    print("\n── C · FRONTERA (techo de tier: el choke point lo enforza + el executor lo pasa) ──")
    # C.3 · el techo se ENFORZA en assemble_and_run (choke point que TODO agente del árbol
    # comparte), no sólo se pasa: receta max_turns=9999 + _caps_ceiling free(8) + 50 calls
    # DISTINTAS → el run corta en ≤8 turnos. Una receta (o child_model 'own') no puede subirlo.
    _o = ra._route_chat
    try:
        ra._route_chat = scripted_route([("add", {"a": k, "b": k}) for k in range(1, 60)], final_text="fin")
        rec, _ev = run_inproc(calc_recipe(max_turns=9999, loop_detect_n=99), "caps clamp",
                              _caps_ceiling={"max_turns": 8, "max_tool_calls": 40})
        check("C.3a _caps_ceiling clampa max_turns en runtime (≤8, no 9999)",
              rec.get("turns", 999) <= 8, f"turns={rec.get('turns')}")
        check("C.3b truncated por techo de tier", rec.get("truncated") is True)
    finally:
        ra._route_chat = _o

    # C.1 · el EXECUTOR (path de prod) resuelve el tier del usuario y pasa el techo correcto.
    conn = None
    try:
        sys.path.insert(0, str(REPO_ROOT / "product" / "backend"))
        from app.phase1 import executor as _ex
        from app.phase1 import repo as _repo
        conn = _repo.get_conn()
        holder = {}

        class _FakeAsm:
            def assemble_and_run(self, recipe, prompt, **kw):
                holder["ceiling"] = kw.get("_caps_ceiling")
                raise RuntimeError("captured-for-frontera-test")  # corta antes del post-proceso

        _ex._asm = lambda: _FakeAsm()

        def _ceiling_for(email, tier, expect):
            holder.clear()
            u = _repo.get_or_create_user(conn, email=email, tier=tier)
            _ex.run_puppet_e2e(calc_recipe(max_turns=9999, max_tool_calls=9999),
                               "x", user_id=u["id"], conn=conn)
            _ceil = holder.get("ceiling") or {}
            check(f"C.1 executor resuelve tier '{tier}' → pasa techo {expect} (⊇; B1·Δ1 sumó max_parallel)",
                  isinstance(_ceil, dict) and all(_ceil.get(k) == v for k, v in expect.items()),
                  f"got={_ceil}")

        _ceiling_for("a1-front-free@puppet.local", "free", {"max_turns": 8, "max_tool_calls": 40})
        _ceiling_for("a1-front-tec@puppet.local", "tecnico", {"max_turns": 40, "max_tool_calls": 400})
    except Exception as exc:  # setup vivo faltante → honesto, no falso-verde
        check("C.1 frontera-executor corrió (DB/app disponibles)", False, f"setup falló: {exc}")
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _post_run(recipe, prompt, deadline_s=150.0):
    payload = json.dumps({"recipe": recipe, "prompt": prompt, "deadline_s": deadline_s}).encode()
    req = urllib.request.Request(BASE.rstrip("/") + "/v1/puppets/run", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=deadline_s + 30) as r:
        return json.loads(r.read().decode())


def _ollama_recipe():
    return {"schema_version": "v1", "meta": {"name": "A1 live", "nicho": "test"},
            "model": {"primary": "qwen3:8b", "base_url": "http://127.0.0.1:11434/v1",
                      "temperature": 0, "max_tokens": 512, "max_turns": 6},
            "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]},
                     # A2 · cómputo local declarado write-local → auto bajo balanceado (default).
                     "action_classes": {"calc": {"add": "write-local", "mul": "write-local"}}},
            "framing": {"inline": "Sos un agente de cálculo. Para sumar SIEMPRE usá la "
                                  "herramienta add (no calcules de cabeza). Respondé el número."},
            "rag": {"enabled": False}, "keys": {}, "gates": {}}


def _record_of(resp):
    return resp.get("record") or resp.get("run", {}).get("record") or resp


def section_D_live_http():
    print(f"\n── D · RUNTIME VIVO (HTTP {BASE}) ──")
    try:
        with urllib.request.urlopen(BASE.rstrip("/") + "/health", timeout=5) as r:
            r.read()
    except Exception as exc:
        check("D · server VIVO en BASE (skippeable si está caído)", False,
              f"{BASE} no responde: {exc}. Levantá el server del worktree en :8090.")
        return

    # D.1 concurrencia: 2 runs simultáneos con números distintos → sin cross-contamination
    results = {}

    def _fire(key, a, b):
        try:
            results[key] = _post_run(_ollama_recipe(), f"cuánto es {a} + {b}")
        except Exception as e:
            results[key] = {"_error": str(e)}

    t1 = threading.Thread(target=_fire, args=("x", 2, 2))
    t2 = threading.Thread(target=_fire, args=("y", 5, 5))
    t0 = time.monotonic()
    t1.start(); t2.start(); t1.join(); t2.join()
    elapsed = time.monotonic() - t0

    rx, ry = results.get("x", {}), results.get("y", {})
    recx, recy = _record_of(rx), _record_of(ry)
    check("D.1a ambos runs concurrentes completaron (no hang)",
          "_error" not in rx and "_error" not in ry and elapsed < 200,
          f"elapsed={elapsed:.1f}s errx={rx.get('_error')} erry={ry.get('_error')}")
    idx = recx.get("run_id") or rx.get("run_id")
    idy = recy.get("run_id") or ry.get("run_id")
    check("D.1b run_ids DISTINTOS (estado aislado por run)", bool(idx) and bool(idy) and idx != idy,
          f"idx={idx} idy={idy}")
    ansx = (recx.get("answer") or "") + json.dumps(recx.get("tool_calls", []))
    ansy = (recy.get("answer") or "") + json.dumps(recy.get("tool_calls", []))
    # cada run debe reflejar SUS números, no los del otro (sin cruce de estado)
    check("D.1c run X refleja lo suyo (4), no lo de Y (10/25)",
          ("4" in ansx) and ("25" not in ansx), f"ansX={ansx[:160]}")
    check("D.1d run Y refleja lo suyo (10/25), no 4-de-X solamente",
          ("10" in ansy or "25" in ansy), f"ansY={ansy[:160]}")

    # D.2 anti-grift (modo producción) sobre un run real
    check("D.2a X degraded==null (no cayó a red de seguridad)", recx.get("degraded") in (None, "", "null"),
          f"degraded={recx.get('degraded')}")
    check("D.2b X model_final == el declarado (qwen3:8b)", (recx.get("model_final") or "").startswith("qwen3"),
          f"model_final={recx.get('model_final')}")
    check("D.2c X operó tool real (tool_calls>0)", len(recx.get("tool_calls", []) or []) > 0,
          f"tool_calls={recx.get('tool_calls')}")


def main():
    print("=" * 78)
    print("STEP 2 · A1 — CERTIFICACIÓN (sandbox de estado + loops + muerte limpia)")
    print("=" * 78)
    section_A_pure()
    section_B_loops()
    section_C_frontera_executor()
    section_D_live_http()
    # [H3] La barra decorativa va ARRIBA: la ÚLTIMA línea es el veredicto.
    print("\n" + "=" * 78)
    print(f"RESULTADO: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
