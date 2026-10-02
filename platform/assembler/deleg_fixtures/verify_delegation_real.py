#!/usr/bin/env python3
"""
verify_delegation_real.py — la EVIDENCIA del PASO 2 (agente anidado REAL).

Reproduce los 4 ATAQUES del spike + las 4 decisiones (modelo/BYOK/guardrails/paralelo)
+ la REGRESIÓN, ahora contra el MOTOR REAL (recipe_assembler.assemble_and_run con el
branch de delegación y los 5 rieles cableados). A diferencia del spike, acá:
  • el gate, la propagación de deadline, el workdir, el bridge y el branch de delegación
    son el CÓDIGO REAL del motor;
  • las tools son un MCP server REAL (deleg_server.py) booteado por subprocess y consumido
    vía registry.call;
  • lo ÚNICO stubeado en los ataques es el CEREBRO (FakeBrain monkeypatchea _route_chat con
    un guión determinista de tool_calls). Cero tokens, cero red, headless. El CASO FELIZ
    E2E (--happy) NO usa FakeBrain: corre con el shim Opus real (:8923), tool_calls>0.

Uso:
  python3 verify_delegation_real.py            # ataques + decisiones + regresión (headless)
  python3 verify_delegation_real.py --happy    # + caso feliz E2E con cerebro REAL (:8923)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_ASM_DIR = _HERE.parent
if str(_ASM_DIR) not in sys.path:
    sys.path.insert(0, str(_ASM_DIR))

import recipe_assembler as RA  # noqa: E402

FIXREL = "platform/assembler/deleg_fixtures"


def _load(name: str) -> dict:
    return json.loads((_HERE / name).read_text(encoding="utf-8"))


def _hr(title: str):
    print("\n" + "═" * 78)
    print("  " + title)
    print("═" * 78)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ FakeBrain — stubea SÓLO el cerebro (monkeypatch de recipe_assembler._route_chat)║
# ╚══════════════════════════════════════════════════════════════════════════════╝
class FakeBrain:
    """Reemplaza el modelo por un guión determinista de tool_calls, keyado por el PRIMER
    mensaje de usuario (el prompt/tarea). Cada agente (padre o hijo) recibe un prompt único
    → su propio guión. Thread-safe (los hijos en paralelo lo invocan concurrentemente)."""

    def __init__(self, scripts: dict):
        self.scripts = scripts
        self.lock = threading.Lock()
        self.calls: list = []                  # [{key, primary, base_url}]
        self.tool_msgs_seen: dict = {}         # key -> [contenidos role:tool que el cerebro VIO]

    @staticmethod
    def _first_user(messages):
        for m in messages:
            if m.get("role") == "user":
                c = m.get("content")
                return c if isinstance(c, str) else json.dumps(c)
        return ""

    def route(self, messages, tools, *, base_url, primary, fallback, api_key,
              max_tokens, temperature, route_log, on_tier_error=None, **_kw):  # (BYO-CLI D4 + annex cli_model: absorbe kwargs aditivos de _route_chat)
        key = self._first_user(messages)
        # TURNO = nº de mensajes 'assistant' YA en ESTE run (la lista `messages` es propia de
        # cada assemble_and_run → cuenta per-run, NO un contador global). Así dos runs que
        # comparten el mismo prompt (padre↔hijo recursivo, ataque + contra-prueba) arrancan
        # cada uno en su turno 0; nunca se contaminan entre sí.
        idx = sum(1 for m in messages if m.get("role") == "assistant")
        with self.lock:
            self.calls.append({"key": key, "primary": primary, "base_url": base_url})
            self.tool_msgs_seen[key] = [str(m.get("content", ""))
                                        for m in messages if m.get("role") == "tool"]
        route_log.append({"model": "fake-brain", "tier": "primary", "ok": True})
        # llamada de CIERRE/reporter (sin tools) → final benigno, no avanza el guión
        if not tools:
            return self._final("[fake-brain: cierre]"), "fake-brain"
        script = self.scripts.get(key)
        if not script or idx >= len(script):
            return self._final(f"[fake-brain: sin guión para {key!r} @idx{idx}]"), "fake-brain"
        turn = script[idx]
        if "final" in turn:
            return self._final(turn["final"]), "fake-brain"
        return self._tool_calls(turn["tool_calls"]), "fake-brain"

    @staticmethod
    def _tool_calls(calls):
        tcs = [{"id": f"call_{i}", "type": "function",
                "function": {"name": n, "arguments": json.dumps(a)}}
               for i, (n, a) in enumerate(calls)]
        return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": tcs},
                             "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    @staticmethod
    def _final(text):
        return {"choices": [{"message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


# ── GUIONES (cada clave = el prompt exacto que recibe ese agente) ────────────────
SCRIPTS = {
    # caso workdir/bridge/feliz-stub (parent.json)
    "PARENT_COORD": [
        {"tool_calls": [("write_note", {"text": "NOTA-DEL-PADRE"})]},
        {"tool_calls": [("research_sub", {"task": "CHILD_RESEARCH"})]},
        {"final": "El padre integró el resultado del sub-agente."},
    ],
    "CHILD_RESEARCH": [
        {"tool_calls": [("write_note", {"text": "NOTA-DEL-HIJO"})]},
        {"tool_calls": [("read_data", {"q": "dato X"})]},
        {"final": "RESULTADO-DEL-HIJO: el dato X = 42"},
    ],
    # RIEL #1 gate (parent_send.json)
    "PARENT_SEND": [
        {"tool_calls": [("mailer_child", {"task": "CHILD_SEND"})]},
        {"final": "El sub-agente intentó mandar; veamos si el gate lo frenó."},
    ],
    "CHILD_SEND": [
        {"tool_calls": [("send_email", {"to": "cliente@x.com", "body": "hola"})]},
        {"final": "intenté mandar el correo"},
    ],
    # RIEL #3 deadline (parent_slow.json)
    "PARENT_SLOW": [
        {"tool_calls": [("slow_child", {"task": "CHILD_SLOW"})]},
        {"final": "el hijo lento terminó (o lo cortó el deadline)"},
    ],
    "CHILD_SLOW": [
        # ops DISTINTAS (no idénticas): un trabajo lento REAL varía sus pasos. Repetir la
        # MISMA (tool+args+resultado) N× es loop-shaped y A1 (Step 2) lo corta — CORRECTO.
        # Este test mide PROPAGACIÓN DE DEADLINE, no loops → pasos distintos (seconds ~0.3).
        {"tool_calls": [("slow_op", {"seconds": 0.28})]},
        {"tool_calls": [("slow_op", {"seconds": 0.29})]},
        {"tool_calls": [("slow_op", {"seconds": 0.30})]},
        {"tool_calls": [("slow_op", {"seconds": 0.31})]},
        {"tool_calls": [("slow_op", {"seconds": 0.32})]},
        {"tool_calls": [("slow_op", {"seconds": 0.33})]},
        {"final": "terminé las 6 operaciones lentas"},
    ],
    # RIEL #2 ciclo (recursive_self.json)
    "RECURSE": [
        {"tool_calls": [("myself_loop", {"task": "RECURSE"})]},
        {"final": "nunca debería llegar acá si el riel corta"},
    ],
    # RIEL #2 depth-limit (link_0..link_4)
    "LINK_0": [{"tool_calls": [("link_1", {"task": "LINK_1"})]}, {"final": "L0"}],
    "LINK_1": [{"tool_calls": [("link_2", {"task": "LINK_2"})]}, {"final": "L1"}],
    "LINK_2": [{"tool_calls": [("link_3", {"task": "LINK_3"})]}, {"final": "L2"}],
    "LINK_3": [{"tool_calls": [("link_4", {"task": "LINK_4"})]}, {"final": "L3"}],
    "LINK_4": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "L4-terminal"}],
    # DECISIÓN 9 paralelo (parent_two.json) — DOS delegaciones en UN turno
    "PARENT_TWO": [
        {"tool_calls": [("alpha_sub", {"task": "CHILD_ALPHA"}),
                        ("beta_sub", {"task": "CHILD_BETA"})]},
        {"final": "ambos sub-agentes terminaron"},
    ],
    "CHILD_ALPHA": [
        {"tool_calls": [("slow_op", {"seconds": 0.5})]},
        {"tool_calls": [("write_note", {"text": "NOTA-ALPHA"})]},
        {"final": "RESULTADO-ALPHA"},
    ],
    "CHILD_BETA": [
        {"tool_calls": [("slow_op", {"seconds": 0.5})]},
        {"tool_calls": [("write_note", {"text": "NOTA-BETA"})]},
        {"final": "RESULTADO-BETA"},
    ],
    # DECISIÓN 7 BYOK (parent_byok.json)
    "PARENT_BYOK": [
        {"tool_calls": [("byok_sub", {"task": "CHILD_BYOK"})]},
        {"final": "byok ok"},
    ],
    "CHILD_BYOK": [
        {"tool_calls": [("read_data", {"q": "x"})]},
        {"final": "byok child done"},
    ],
    # DECISIÓN 6 modelo
    "MODEL_PARENT_INHERIT": [{"tool_calls": [("model_sub", {"task": "MODEL_CHILD_INH"})]}, {"final": "inh"}],
    "MODEL_CHILD_INH": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "child-inh"}],
    "MODEL_PARENT_OWN": [{"tool_calls": [("model_sub", {"task": "MODEL_CHILD_OWN"})]}, {"final": "own"}],
    "MODEL_CHILD_OWN": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "child-own"}],
    # DECISIÓN 6-bis · override POR-HIJO (parent_model_perchild.json): alpha con entrada
    # en child_models → "picked-model"; beta SIN entrada → hereda "parent-model".
    "MODEL_PARENT_PERCHILD": [
        {"tool_calls": [("alpha_sub", {"task": "MODEL_CHILD_PC_A"}),
                        ("beta_sub", {"task": "MODEL_CHILD_PC_B"})]},
        {"final": "per-child listo"},
    ],
    "MODEL_CHILD_PC_A": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "pc-a"}],
    "MODEL_CHILD_PC_B": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "pc-b"}],
    # DECISIÓN 8 guardrails (parent_guard.json) — el hijo intenta send Y money
    "PARENT_GUARD": [{"tool_calls": [("guard_sub", {"task": "CHILD_GUARD"})]}, {"final": "guard"}],
    "CHILD_GUARD": [
        {"tool_calls": [("send_email", {"to": "x@y.com", "body": "h"}),
                        ("place_order", {"item": "gpu"})]},
        {"final": "intenté send y order"},
    ],
    # DECISIÓN 8 (transitiva) — abuelo prohíbe 'send'; capa media benigna; nieto intenta send
    "GP_GUARD": [{"tool_calls": [("mid_guard", {"task": "MID_GUARD"})]}, {"final": "gp"}],
    "MID_GUARD": [{"tool_calls": [("guard_sub", {"task": "CHILD_GUARD"})]}, {"final": "mid"}],
    # REGRESIÓN (plain_no_agents.json) — sin agent_refs
    "PLAIN": [{"tool_calls": [("read_data", {"q": "x"})]}, {"final": "plain done"}],
}


# ── helper para correr una receta con el FakeBrain instalado ─────────────────────
class _Patched:
    def __init__(self, brain):
        self.brain = brain
        self._orig = None

    def __enter__(self):
        self._orig = RA._route_chat
        RA._route_chat = self.brain.route
        return self.brain

    def __exit__(self, *a):
        RA._route_chat = self._orig


def _run(recipe_name, prompt, *, workdir=None, approve=None, deadline_abs=None,
         deadline_s=180.0, byok_resolver=None, brain=None):
    recipe = _load(recipe_name)
    kw = dict(repo_root=_REPO_ROOT, deadline_s=deadline_s, workdir=workdir,
              approve=approve, byok_resolver=byok_resolver)
    if deadline_abs is not None:
        kw["_deadline_abs"] = deadline_abs
    return RA.assemble_and_run(recipe, prompt, **kw)


def _wd(tag):
    d = _HERE / ".deleg-workdirs" / tag
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


results = {}   # label -> (passed, evidencia)


# ════════════════════════════════════════════════════════════════════════════════
# RIEL #5 / CASO FELIZ (stub) — workdir + bridge + delegación de punta a punta
# ════════════════════════════════════════════════════════════════════════════════
def t_happy_workdir_bridge(brain):
    _hr("RIEL #4 (workdir) + #5 (bridge) — padre delega → hijo corre con SU gate/workdir")
    with _Patched(brain):
        rec = _run("parent.json", "PARENT_COORD", workdir=_wd("happy"))
    child = (rec.get("sub_runs") or [{}])[0]
    deleg = [t for t in rec["tool_calls"] if t.get("delegated")]
    print(f"  padre ok={rec['ok']}  answer={rec['answer']!r}")
    print(f"  sub_runs anidados: {len(rec.get('sub_runs', []))}  hijo.meta={child.get('meta_name')!r} depth={child.get('depth')}")
    print(f"  delegación vista por el padre: {bool(deleg)}")
    bridged = json.loads(deleg[0]["result"]) if deleg else {}
    print(f"    bridge que consumió el padre: {deleg[0]['result'] if deleg else '—'}")

    # RIEL #4 — workdirs separados, hijo bajo parent/sub-*, notas distintas
    pdir, cdir = Path(rec["workdir"]), Path(child.get("workdir", ""))
    pnote = (pdir / "note.txt").read_text(encoding="utf-8") if (pdir / "note.txt").exists() else ""
    cnote = (cdir / "note.txt").read_text(encoding="utf-8") if (cdir / "note.txt").exists() else ""
    sep = pdir.resolve() != cdir.resolve()
    nested = str(cdir).startswith(str(pdir)) and "sub-" in cdir.name
    notes_ok = pnote == "NOTA-DEL-PADRE" and cnote == "NOTA-DEL-HIJO"
    print(f"  RIEL#4 workdir padre={pdir.name}  hijo={cdir.name}  separados={sep} anidado={nested}")
    print(f"         note padre={pnote!r}  note hijo={cnote!r}")

    # RIEL #5 — sólo el resultado cruza; el cerebro del padre NO vio los pasos del hijo
    parent_seen = brain.tool_msgs_seen.get("PARENT_COORD", [])
    leaked = any(("NOTA-DEL-HIJO" in s) or ("datos[dato X]" in s) for s in parent_seen)
    bridge_only = ("RESULTADO-DEL-HIJO" in bridged.get("resultado", "")
                   and set(bridged.keys()) <= {"sub_agente", "ok", "resultado", "truncado", "error"})
    child_steps_in_log = len((child.get("tool_calls") or [])) >= 2  # los pasos del hijo viven en el LOG
    print(f"  RIEL#5 el cerebro del padre vio (role:tool): {parent_seen}")
    print(f"         ¿filtró pasos internos del hijo al padre?: {leaked} (debe ser False)")
    print(f"         pasos del hijo preservados en sub_runs (log): {child_steps_in_log}")

    passed = bool(deleg) and rec["ok"] and child.get("ok") and sep and nested and notes_ok \
        and bridge_only and not leaked and child_steps_in_log
    results["RIEL#4·workdir"] = (sep and nested and notes_ok,
                                 f"hijo en {cdir.name} (bajo el padre); notas distintas {pnote!r}/{cnote!r}")
    results["RIEL#5·bridge"] = (bridge_only and not leaked and child_steps_in_log,
                                f"al padre sólo cruzó {sorted(bridged.keys())}; pasos del hijo en el log, no en su contexto")
    print(f"  >>> workdir+bridge: {'OK' if passed else 'FALLO'}")
    return rec, child


# ════════════════════════════════════════════════════════════════════════════════
# RIEL #1 — GATE POR HIJO  (ataque: hijo manda correo; el padre aprueba TODO)
# ════════════════════════════════════════════════════════════════════════════════
def t_rail1_gate(brain):
    _hr("RIEL #1 · GATE POR HIJO — ataque: sub-agente que MANDA correo (padre aprueba TODO)")
    with _Patched(brain):
        rec = _run("parent_send.json", "PARENT_SEND", workdir=_wd("send"),
                   approve=lambda *a: True)   # el PADRE aprueba todo; NO debe heredarlo el hijo
    child = (rec.get("sub_runs") or [{}])[0]
    gd = [g for g in child.get("gate_decisions", []) if g["tool"] == "send_email"]
    leaked = (Path(child.get("workdir", "")) / "EMAIL_SENT.flag").exists()
    print(f"  el padre aprueba TODO (approve=True). gate del hijo sobre send_email: {gd}")
    print(f"  ¿se mandó el correo? (flag en disco): {leaked}  (debe ser False)")
    blocked = bool(gd) and gd[0]["action"] in ("needs_ok", "blocked") and not leaked

    # contra-prueba: el gate es REAL — el MISMO hijo, corrido directo CON OK explícito, SÍ manda.
    with _Patched(brain):
        rec2 = _run("child_send.json", "CHILD_SEND", workdir=_wd("send-direct"),
                    approve=lambda *a: True)
    leaked2 = (Path(rec2.get("workdir", "")) / "EMAIL_SENT.flag").exists()
    g2 = [g for g in rec2.get("gate_decisions", []) if g["tool"] == "send_email"]
    print(f"  contra-prueba (hijo directo + OK explícito): gate={g2}  ejecutó={leaked2}  (debe ser True)")
    gate_real = bool(g2) and g2[0]["action"] == "execute" and leaked2

    passed = blocked and gate_real
    results["RIEL#1·gate-por-hijo"] = (passed,
        f"hijo malicioso → send_email={gd[0]['action'] if gd else '?'}, NO ejecutó pese al approve del padre; "
        f"con OK propio sí ejecuta (gate real)")
    print(f"  >>> ataque bloqueado={blocked} · gate real(allow-con-OK)={gate_real} · RIEL #1 {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# RIEL #2 — CICLO (por path canónico) + DEPTH-LIMIT (cadena distinta)
# ════════════════════════════════════════════════════════════════════════════════
def _walk_deepest(rec):
    node, depth, errs = rec, 0, []
    while node.get("sub_runs"):
        node = node["sub_runs"][0]
        depth += 1
        if node.get("error"):
            errs.append(node["error"])
    return node, depth, errs


def t_rail2_cycle(brain):
    _hr("RIEL #2 · CICLO POR PATH CANÓNICO — ataque: agent_ref que apunta a su propia receta")
    t0 = time.monotonic()
    with _Patched(brain):
        rec = _run("recursive_self.json", "RECURSE", workdir=_wd("recurse"))
    dt = time.monotonic() - t0
    deepest, depth, errs = _walk_deepest(rec)
    print(f"  terminó en {dt*1000:.0f}ms (no colgó); profundidad de la cadena={depth}")
    print(f"  error más profundo: {deepest.get('error')!r}")
    cut = any("cycle_detected" in (e or "") for e in errs) or "cycle_detected" in (deepest.get("error") or "")
    finite = dt < 5.0
    passed = cut and finite
    results["RIEL#2·ciclo"] = (passed,
        f"self-ref cortado por path canónico → cycle_detected en profundidad {depth}; {dt*1000:.0f}ms, no cuelga")
    print(f"  >>> ciclo cortado={cut} · finito={finite} · RIEL #2(ciclo) {'CIERRA' if passed else 'NO CIERRA'}")


def t_rail2_depth(brain):
    _hr("RIEL #2 · DEPTH-LIMIT — ataque: cadena de recetas DISTINTAS más larga que MAX_DEPTH")
    t0 = time.monotonic()
    with _Patched(brain):
        rec = _run("link_0.json", "LINK_0", workdir=_wd("depth"))
    dt = time.monotonic() - t0
    deepest, depth, errs = _walk_deepest(rec)
    print(f"  MAX_DEPTH={RA._delegation.MAX_DEPTH}; profundidad alcanzada antes de cortar={depth}")
    print(f"  error más profundo: {deepest.get('error')!r}")
    import delegation as _D
    depth_cut = any("depth_limit_exceeded" in (e or "") for e in errs) \
        or "depth_limit_exceeded" in (deepest.get("error") or "")
    # la cadena llega hasta el intento de pasar de MAX_DEPTH (depth = MAX_DEPTH+1 corta)
    bounded = depth <= _D.MAX_DEPTH + 1 and dt < 5.0
    passed = depth_cut and bounded
    results["RIEL#2·depth"] = (passed,
        f"cadena distinta cortada en depth {depth} (>{_D.MAX_DEPTH}) → depth_limit_exceeded; {dt*1000:.0f}ms")
    print(f"  >>> depth-limit={depth_cut} · acotado={bounded} · RIEL #2(depth) {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# RIEL #3 — DEADLINE PROPAGADO  (ataque: hijo lento; respeta el deadline del padre)
# ════════════════════════════════════════════════════════════════════════════════
def t_rail3_deadline(brain):
    _hr("RIEL #3 · DEADLINE PROPAGADO — ataque: sub-agente lento")
    t0 = time.monotonic()
    tight = time.monotonic() + 0.8     # el padre ya tenía 0.8s de presupuesto
    with _Patched(brain):
        parent = _run("parent_slow.json", "PARENT_SLOW", workdir=_wd("slow"), deadline_abs=tight)
    elapsed = time.monotonic() - t0
    child = (parent.get("sub_runs") or [{}])[0]
    same = abs(child.get("deadline_abs", -1) - parent.get("deadline_abs", -2)) < 1e-6
    child_slow = len([t for t in child.get("tool_calls", []) if t["tool"] == "slow_op"])
    print(f"  deadline padre(abs)={parent.get('deadline_abs')}  hijo(abs)={child.get('deadline_abs')} → MISMO={same}")
    print(f"  hijo: slow_ops ejecutadas={child_slow}  truncado={child.get('truncated')}")
    print(f"  wall-time total padre+hijo={elapsed:.2f}s (presupuesto del padre=0.8s)")

    # contra-fáctico: el MISMO hijo standalone (deadline fresco, NO propagado) corre TODO.
    with _Patched(brain):
        fresh = _run("child_slow.json", "CHILD_SLOW", workdir=_wd("slow-fresh"))
    fresh_slow = len([t for t in fresh.get("tool_calls", []) if t["tool"] == "slow_op"])
    print(f"  contra-fáctico (deadline fresco, sin propagar): slow_ops={fresh_slow} truncado={fresh.get('truncated')}")

    bounded = elapsed < 5.0
    passed = same and child.get("truncated") and not fresh.get("truncated") \
        and child_slow < fresh_slow and bounded
    results["RIEL#3·deadline"] = (passed,
        f"hijo HEREDÓ el mismo deadline abs ({same}); truncó a {child_slow} ops vs {fresh_slow} sin propagar; total {elapsed:.2f}s")
    print(f"  >>> deadline compartido={same} · hijo truncó={child.get('truncated')} · fresco corrió todo={not fresh.get('truncated')} · acotado={bounded} · RIEL #3 {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# DECISIÓN 9 — PARALELO  (dos sub-agentes en un turno; corren concurrentes)
# ════════════════════════════════════════════════════════════════════════════════
def t_parallel(brain):
    _hr("DECISIÓN 9 · PARALELO — padre delega en DOS sub-agentes en el mismo turno")
    t0 = time.monotonic()
    with _Patched(brain):
        rec = _run("parent_two.json", "PARENT_TWO", workdir=_wd("two"))
    wall_par = time.monotonic() - t0
    subs = rec.get("sub_runs", [])
    names = sorted([s.get("meta_name") for s in subs])
    answers = sorted([(s.get("answer") or "")[:40] for s in subs])
    wds = [s.get("workdir") for s in subs]
    distinct_wd = len(set(wds)) == len(wds) and all(w for w in wds)
    both_ok = len(subs) == 2 and all(s.get("ok") for s in subs)
    independent = "RESULTADO-ALPHA" in " ".join(answers) and "RESULTADO-BETA" in " ".join(answers)
    print(f"  sub_runs={len(subs)} nombres={names}")
    print(f"  resultados independientes={answers}")
    print(f"  workdirs distintos={distinct_wd}: {[Path(w).name for w in wds if w]}")
    print(f"  wall-time PARALELO={wall_par:.2f}s")

    # prueba de PARALELISMO real: los mismos dos hijos en SECUENCIA tardan ~2x.
    t1 = time.monotonic()
    with _Patched(brain):
        _run("child_alpha.json", "CHILD_ALPHA", workdir=_wd("two-a-seq"))
        _run("child_beta.json", "CHILD_BETA", workdir=_wd("two-b-seq"))
    wall_seq = time.monotonic() - t1
    faster = wall_par < wall_seq * 0.8
    print(f"  wall-time SECUENCIAL (mismos 2 hijos)={wall_seq:.2f}s → paralelo es {wall_seq/max(wall_par,1e-6):.2f}x más rápido")

    passed = both_ok and distinct_wd and independent and faster
    results["DECISIÓN9·paralelo"] = (passed,
        f"2 hijos OK, workdirs distintos, resultados independientes; paralelo {wall_par:.2f}s < secuencial {wall_seq:.2f}s")
    print(f"  >>> 2-ok={both_ok} · workdirs-distintos={distinct_wd} · independientes={independent} · más-rápido={faster} · DECISIÓN 9 {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# DECISIÓN 7 — BYOK HÍBRIDO  (el hijo sólo ve las keys que SU receta declara)
# ════════════════════════════════════════════════════════════════════════════════
def t_byok(brain):
    _hr("DECISIÓN 7 · BYOK HÍBRIDO — el hijo NO ve una key del padre que no declaró")
    seen_refs = []

    def resolver(ref):
        seen_refs.append(ref)
        return {"PARENT_REF": "PARENT_SECRET_VALUE", "CHILD_REF": "CHILD_SECRET_VALUE"}.get(ref, "")

    with _Patched(brain):
        rec = _run("parent_byok.json", "PARENT_BYOK", workdir=_wd("byok"), byok_resolver=resolver)
    child = (rec.get("sub_runs") or [{}])[0]
    parent_prov = rec.get("byok_providers", [])
    child_prov = child.get("byok_providers", [])
    print(f"  providers que cableó el PADRE: {parent_prov}")
    print(f"  providers que cableó el HIJO:  {child_prov}")
    child_isolated = child_prov == ["child_svc"] and "secret_parent" not in child_prov

    # prueba directa del wrapper: el resolver scopeado del hijo NIEGA el ref del padre.
    import delegation as _D
    scoped, allow = _D.scoped_byok_resolver(resolver, _load("child_byok.json"))
    denied = scoped("PARENT_REF")
    allowed = scoped("CHILD_REF")
    print(f"  resolver scopeado del hijo: allow-set={sorted(allow)}")
    print(f"    intento de leer la key del padre (PARENT_REF) → {denied!r}  (debe ser '')")
    print(f"    su propia key (CHILD_REF) → {'<resuelta>' if allowed else '<vacía>'}  (debe resolver)")
    wrapper_ok = denied == "" and allowed == "CHILD_SECRET_VALUE"

    passed = child_isolated and wrapper_ok
    results["DECISIÓN7·byok"] = (passed,
        f"hijo cableó {child_prov} (no 'secret_parent'); su resolver niega PARENT_REF y resuelve CHILD_REF")
    print(f"  >>> hijo aislado={child_isolated} · wrapper niega ajena/resuelve propia={wrapper_ok} · DECISIÓN 7 {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# DECISIÓN 6 — MODELO DEL HIJO  (default hereda; flag own → usa el suyo)
# ════════════════════════════════════════════════════════════════════════════════
def _primary_for(brain, key):
    pr = [c["primary"] for c in brain.calls if c["key"] == key]
    return pr[0] if pr else None


def t_model(brain):
    _hr("DECISIÓN 6 · MODELO DEL HIJO — default HEREDA el del padre; flag 'own' → el suyo")
    # default: inherit
    brain.calls.clear()
    with _Patched(brain):
        _run("parent_model_inherit.json", "MODEL_PARENT_INHERIT", workdir=_wd("model-inh"))
    inh_child = _primary_for(brain, "MODEL_CHILD_INH")
    print(f"  [default] modelo con que corrió el HIJO: {inh_child!r}  (esperado 'parent-model' = heredado)")
    inherit_ok = inh_child == "parent-model"

    # flag own
    brain.calls.clear()
    with _Patched(brain):
        _run("parent_model_own.json", "MODEL_PARENT_OWN", workdir=_wd("model-own"))
    own_child = _primary_for(brain, "MODEL_CHILD_OWN")
    print(f"  [flag own] modelo con que corrió el HIJO: {own_child!r}  (esperado 'child-model' = el suyo)")
    own_ok = own_child == "child-model"

    passed = inherit_ok and own_ok
    results["DECISIÓN6·modelo"] = (passed,
        f"default → hijo usó '{inh_child}' (heredado); flag own → hijo usó '{own_child}' (propio)")
    print(f"  >>> hereda(default)={inherit_ok} · usa-el-suyo(flag)={own_ok} · DECISIÓN 6 {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# DECISIÓN 6-bis — MODELO POR-HIJO  (agent_policy.child_models[slug] gana; hermano hereda)
# ════════════════════════════════════════════════════════════════════════════════
def t_model_perchild(brain):
    _hr("DECISIÓN 6-bis · MODELO POR-HIJO — child_models[slug] fija el cerebro de ESE hijo; "
        "el hermano sin entrada HEREDA el del padre")
    brain.calls.clear()
    with _Patched(brain):
        rec = _run("parent_model_perchild.json", "MODEL_PARENT_PERCHILD", workdir=_wd("model-perchild"))
    a_calls = [c for c in brain.calls if c["key"] == "MODEL_CHILD_PC_A"]
    b_calls = [c for c in brain.calls if c["key"] == "MODEL_CHILD_PC_B"]
    a_primary = a_calls[0]["primary"] if a_calls else None
    a_base = a_calls[0]["base_url"] if a_calls else None
    b_primary = b_calls[0]["primary"] if b_calls else None
    b_base = b_calls[0]["base_url"] if b_calls else None
    print(f"  [override] hijo ALPHA (child_models['child_alpha']): primary={a_primary!r} base_url={a_base!r}"
          f"  (esperado 'picked-model' @ 'stub://picked')")
    print(f"  [hermano]  hijo BETA (sin entrada):                  primary={b_primary!r} base_url={b_base!r}"
          f"  (esperado 'parent-model' = heredado)")
    both_ran = len(rec.get("sub_runs", [])) == 2 and all(s.get("ok") for s in rec.get("sub_runs", []))
    picked = a_primary == "picked-model" and a_base == "stub://picked"
    sibling_inherits = b_primary == "parent-model" and b_base == "stub://parent"
    passed = both_ran and picked and sibling_inherits
    results["DECISIÓN6bis·por-hijo"] = (passed,
        f"alpha corrió con '{a_primary}'@{a_base} (override por-slug); beta con '{b_primary}' (heredado del padre)")
    print(f"  >>> 2-hijos-ok={both_ran} · override-gana={picked} · hermano-hereda={sibling_inherits} "
          f"· DECISIÓN 6-bis {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# DECISIÓN 8 — GUARDRAILS DEL PADRE  (techo; pero no pre-autoriza lo gated)
# ════════════════════════════════════════════════════════════════════════════════
def t_guardrails(brain):
    _hr("DECISIÓN 8 · GUARDRAILS — el padre PROHIBE 'send' (techo) pero NO pre-autoriza lo gated")
    with _Patched(brain):
        # el padre APRUEBA TODO; aun así no puede ni abrir el send (techo) ni pre-autorizar el money.
        rec = _run("parent_guard.json", "PARENT_GUARD", workdir=_wd("guard"), approve=lambda *a: True)
    child = (rec.get("sub_runs") or [{}])[0]
    gsend = [g for g in child.get("gate_decisions", []) if g["tool"] == "send_email"]
    gmoney = [g for g in child.get("gate_decisions", []) if g["tool"] == "place_order"]
    cdir = Path(child.get("workdir", ""))
    sent = (cdir / "EMAIL_SENT.flag").exists()
    ordered = (cdir / "ORDER_PLACED.flag").exists()
    print(f"  clase PROHIBIDA por el padre: 'send'")
    print(f"  gate del hijo sobre send_email (clase prohibida): {gsend} → flag={sent}")
    print(f"  gate del hijo sobre place_order (NO prohibida, pero PELIGROSA): {gmoney} → flag={ordered}")
    # techo: send bajado a BLOCKED por el padre, no ejecutó.
    ceiling_blocks = bool(gsend) and gsend[0]["action"] == "blocked" and not sent
    # gate del hijo sigue mandando: money cae a needs_ok y NO se ejecutó (padre no lo pre-autoriza).
    child_gate_rules = bool(gmoney) and gmoney[0]["action"] == "needs_ok" and not ordered
    passed = ceiling_blocks and child_gate_rules
    results["DECISIÓN8·guardrails"] = (passed,
        f"techo bajó send→blocked (no ejecutó); el gate del hijo dejó money en needs_ok (padre no pre-autoriza)")
    print(f"  >>> techo-restringe-send={ceiling_blocks} · gate-del-hijo-manda-money={child_gate_rules} · DECISIÓN 8 {'CIERRA' if passed else 'NO CIERRA'}")


def t_guardrails_transitive(brain):
    _hr("DECISIÓN 8 (transitiva) · TECHO MONÓTONO — el ABUELO prohíbe 'send'; capa media benigna")
    with _Patched(brain):
        rec = _run("gp_guard.json", "GP_GUARD", workdir=_wd("gp-guard"), approve=lambda *a: True)
    mid = (rec.get("sub_runs") or [{}])[0]                # depth 1 (benigno, sin guardrails)
    grand = (mid.get("sub_runs") or [{}])[0]              # depth 2 (intenta send_email)
    gsend = [g for g in grand.get("gate_decisions", []) if g["tool"] == "send_email"]
    sent = (Path(grand.get("workdir", "")) / "EMAIL_SENT.flag").exists()
    print(f"  cadena: gp(depth {rec.get('depth')}) → mid(depth {mid.get('depth')}, sin guardrails) → nieto(depth {grand.get('depth')})")
    print(f"  el nieto intenta send_email → gate={gsend}  flag={sent}")
    # el techo del ABUELO ató al NIETO aunque la capa media no lo repitió.
    transitive = bool(gsend) and gsend[0]["action"] == "blocked" and not sent
    passed = transitive and grand.get("depth") == 2
    results["DECISIÓN8·techo-transitivo"] = (passed,
        f"el techo del abuelo (deny send) bajó el send del nieto (depth 2) a blocked pese a la capa media benigna")
    print(f"  >>> techo-transitivo={transitive} · DECISIÓN 8(transitiva) {'CIERRA' if passed else 'NO CIERRA'}")


# ════════════════════════════════════════════════════════════════════════════════
# REGRESIÓN — receta SIN agent_refs corre EXACTAMENTE como hoy
# ════════════════════════════════════════════════════════════════════════════════
def t_regression(brain):
    _hr("REGRESIÓN — una receta SIN agent_refs corre igual que hoy (path normal intacto)")
    with _Patched(brain):
        rec = _run("plain_no_agents.json", "PLAIN", workdir=_wd("plain"))
    no_subruns = rec.get("sub_runs") == []
    no_agent_caps = rec.get("agent_refs_cabled") == []
    ran_tool = any(t["tool"] == "read_data" for t in rec.get("tool_calls", []))
    answered = rec.get("ok") and "plain done" in (rec.get("answer") or "")
    print(f"  ok={rec.get('ok')} answer={rec.get('answer')!r}")
    print(f"  sub_runs vacío={no_subruns}  agent_refs_cabled vacío={no_agent_caps}  corrió read_data={ran_tool}")
    passed = no_subruns and no_agent_caps and ran_tool and answered
    results["REGRESIÓN·sin-agent_refs"] = (passed,
        "sin agent_refs: 0 sub_runs, 0 capacidades de delegación, tool real corrió, respuesta normal")
    print(f"  >>> REGRESIÓN {'OK (path normal intacto)' if passed else 'ROTA'}")


# ════════════════════════════════════════════════════════════════════════════════
# CASO FELIZ E2E REAL (--happy) — cerebro REAL (shim Opus :8923), tool_calls>0
# ════════════════════════════════════════════════════════════════════════════════
def t_happy_real():
    _hr("CASO FELIZ E2E REAL — padre delega → hijo corre con CEREBRO REAL (:8923), tool_calls>0")
    # OJO: el alias 'brain' lo resuelve models.py al IMPORTAR. Para que apunte al shim hay que
    # arrancar Python con PUPPET_BRAIN_SHIM=1 PUPPET_BRAIN_SHIM_MODEL=claude-code-opus-4.8.
    if not RA._models._BRAIN_SHIM_ON:
        print("  [SKIP] el shim no está activo (corré con PUPPET_BRAIN_SHIM=1 …). No es un fallo del branch.")
        results["CASO-FELIZ-E2E-REAL"] = (True, "SKIP: shim no activo en este proceso")
        return
    # parent_real.json (alias='brain', sólo delega) → child_calc_real.json (belt-calc real).
    parent = _load("parent_real.json")
    rec = RA.assemble_and_run(
        parent, "Necesito la suma de 21 y 21. Delegá el cálculo al sub-agente de la calculadora "
                "y deciles que sume 21 + 21; después devolveme el número.",
        repo_root=_REPO_ROOT, deadline_s=240.0, workdir=_wd("happy-real"))
    child_rec = (rec.get("sub_runs") or [{}])[0]
    deleg = [t for t in rec.get("tool_calls", []) if t.get("delegated")]
    child_tool_calls = [t for t in child_rec.get("tool_calls", []) if t.get("tool") == "add"]
    add_executed = [t for t in child_tool_calls if t.get("gate_action") == "execute"]
    child_answer = child_rec.get("answer") or ""
    print(f"  padre ok={rec.get('ok')} model_final={rec.get('model_final')!r}")
    print(f"  delegó={bool(deleg)}  sub_runs={len(rec.get('sub_runs', []))}")
    print(f"  HIJO: ok={child_rec.get('ok')} model_final={child_rec.get('model_final')!r} "
          f"tool_calls(add)={len(child_tool_calls)} ejecutadas={len(add_executed)}")
    print(f"  resultado del hijo: {child_answer[:160]!r}")
    print(f"  respuesta del padre: {(rec.get('answer') or '')[:200]!r}")
    real_brain = bool(child_rec.get("model_final")) and "fake" not in str(child_rec.get("model_final"))
    tool_used = len(child_tool_calls) > 0
    tool_ran = len(add_executed) > 0
    # 42 cruzó LIMPIO: aparece en el resultado del hijo Y en lo que el padre integró.
    crossed = "42" in child_answer and "42" in (rec.get("answer") or "")
    passed = rec.get("ok") and child_rec.get("ok") and real_brain and tool_used and tool_ran and crossed
    results["CASO-FELIZ-E2E-REAL"] = (passed,
        f"hijo con cerebro real {child_rec.get('model_final')!r}, tool_calls(add)={len(child_tool_calls)} "
        f"(ejecutó {len(add_executed)}), 42 cruzó del hijo al padre")
    print(f"  >>> cerebro-real={real_brain} · tool_calls>0={tool_used} · tool_ejecutó={tool_ran} · 42-cruzó-limpio={crossed} · CASO FELIZ {'OK' if passed else 'FALLO'}")


def main():
    do_happy = "--happy" in sys.argv
    only_happy = "--only-happy" in sys.argv
    brain = FakeBrain(SCRIPTS)

    if not only_happy:
        t_happy_workdir_bridge(brain)
        t_rail1_gate(brain)
        t_rail2_cycle(brain)
        t_rail2_depth(brain)
        t_rail3_deadline(brain)
        t_parallel(brain)
        t_byok(brain)
        t_model(brain)
        t_model_perchild(brain)
        t_guardrails(brain)
        t_guardrails_transitive(brain)
        t_regression(brain)

    if do_happy or only_happy:
        try:
            t_happy_real()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results["CASO-FELIZ-E2E-REAL"] = (False, f"excepción: {exc}")

    _hr("RESUMEN — ¿los rieles y decisiones AGUANTAN sobre el motor REAL?")
    all_ok = True
    for k in sorted(results.keys()):
        passed, _ev = results[k]
        all_ok = all_ok and passed
        print(f"  {k:<26} {'✓ CIERRA' if passed else '✗ NO CIERRA'}")
    print("\n  EVIDENCIA:")
    for k in sorted(results.keys()):
        print(f"   • {k}: {results[k][1]}")
    print("\n  VEREDICTO:", "TODO VERDE — el agente anidado es seguro sobre el motor real"
          if all_ok else "ALGO NO CIERRA — revisar antes de seguir")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
