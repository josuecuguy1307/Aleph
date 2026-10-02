#!/usr/bin/env python3
"""verify_b1_multiagente.py — Step 2·B1: los 4 DELTAS del runtime de delegación agente→agente.

HEADLESS (FakeBrain stubea SÓLO el cerebro; las tools son el MCP REAL deleg_server.py; sin
DB/:8090), mismo molde que verify_delegation_real.py. Prueba:
  1. CAP DE PARALELISMO POR TIER   — free=1 serializa (aviso honesto) + concurrencia real medida;
                                     basico=3 no serializa; el techo es del runtime, no de la receta.
  2. GATE ANIDADO — HOIST          — el held (money/write-world) del hijo SUBE al top-level con la
                                     receta DEL HIJO + camino de árbol; NO se ejecutó; piso money en
                                     CUALQUIER nivel (incl. autonomy='autonomo' del hijo) + transitivo.
  3. PRESUPUESTO ANIDADO ACOTADO   — el hijo hereda max_turns/tool_calls a la MITAD (mín 1); un hijo
                                     que haría 6 pasos se corta en su techo (4) y el padre sigue vivo.
  4. STREAMING DEL ÁRBOL           — sub_agent_started/finished con slug+depth; RIEL #5 intacto (los
                                     pasos internos del hijo NO llegan al stream del padre); tipos
                                     registrados en EVENT_TYPES (si no, EventLog los tira silencioso).

El approve-by-HTTP del held anidado (persistir + POST /approve → ejecuta con el belt del hijo) se
prueba VIVO en verify_b1_http.py contra :8090.

Correr:  cd platform/assembler/deleg_fixtures && \\
         PYTHONPATH=<wt>/platform <venv>/bin/python verify_b1_multiagente.py
"""
import sys
import time
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))  # platform/

import verify_delegation_real as V   # FakeBrain, _Patched, _load, _wd, _REPO_ROOT, SCRIPTS
import recipe_assembler as RA
import delegation as D

# ── guiones B1 (extienden los de verify_delegation_real) ─────────────────────────
V.SCRIPTS.update({
    "PARENT_MONEY": [{"tool_calls": [("cajero_sub", {"task": "CHILD_MONEY"})]},
                     {"final": "delegué la compra al cajero"}],
    "CHILD_MONEY":  [{"tool_calls": [("place_order", {"item": "gpu-x"})]},
                     {"final": "intenté colocar la orden"}],
    "PARENT_BUDGET": [{"tool_calls": [("budget_sub", {"task": "CHILD_BUDGET"})]},
                      {"final": "delegué el trabajo largo"}],
    # el hijo QUERRÍA 6 pasos distintos (no-loop: q distinto), pero su techo acotado lo corta.
    "CHILD_BUDGET": [{"tool_calls": [("read_data", {"q": f"paso-{i}"})]} for i in range(1, 7)]
                    + [{"final": "terminé los 6 pasos"}],
    # transitivo: abuelo → capa media benigna → nieto cajero (money del NIETO sube al top)
    "GP_MONEY":  [{"tool_calls": [("mid_plain", {"task": "MID_PLAIN"})]}, {"final": "abuelo ok"}],
    "MID_PLAIN": [{"tool_calls": [("cajero_sub", {"task": "CHILD_MONEY"})]}, {"final": "media ok"}],
})

results: dict = {}


def _record(label, passed, ev):
    results[label] = (bool(passed), ev)
    print(f"  {'✓ CIERRA' if passed else '✗ NO CIERRA'}  {label}\n      {ev}")


def _run(recipe_name, prompt, *, caps_ceiling=None, on_event=None, approve=None, workdir=None):
    """Corre una receta por el motor REAL con el FakeBrain ya instalado por el caller.
    A diferencia de V._run, expone _caps_ceiling y on_event (los ejes de B1)."""
    recipe = V._load(recipe_name)
    kw = dict(repo_root=V._REPO_ROOT, deadline_s=180.0, workdir=workdir, approve=approve)
    if caps_ceiling is not None:
        kw["_caps_ceiling"] = caps_ceiling
    if on_event is not None:
        kw["on_event"] = on_event
    return RA.assemble_and_run(recipe, prompt, **kw)


def _hr(t):
    print("\n" + "═" * 78 + f"\n  {t}\n" + "═" * 78)


# ════════════════════════════════════════════════════════════════════════════════
# DELTA 1 — CAP DE PARALELISMO POR TIER (free=1 serializa; concurrencia real medida)
# ════════════════════════════════════════════════════════════════════════════════
def t_parallel_cap():
    _hr("DELTA 1 · CAP DE PARALELISMO POR TIER — free=1 serializa (runtime, no receta)")
    brain = V.FakeBrain(V.SCRIPTS)

    # sonda de concurrencia REAL: envolvemos _run_one_child para medir el máx simultáneo.
    def _measured(caps, tag):
        counter = {"cur": 0, "max": 0}
        lock = threading.Lock()
        orig = D._run_one_child

        def wrapped(*a, **k):
            with lock:
                counter["cur"] += 1
                counter["max"] = max(counter["max"], counter["cur"])
            try:
                time.sleep(0.06)   # ventana de solape para detectar concurrencia
                return orig(*a, **k)
            finally:
                with lock:
                    counter["cur"] -= 1
        D._run_one_child = wrapped
        events = []
        try:
            with V._Patched(brain):
                rec = _run("parent_two.json", "PARENT_TWO", caps_ceiling=caps,
                           on_event=events.append, workdir=V._wd(f"b1-parcap-{tag}"))
        finally:
            D._run_one_child = orig
        return rec, events, counter["max"]

    FREE = {"max_turns": 8, "max_tool_calls": 40, "max_parallel": 1}
    BAS = {"max_turns": 20, "max_tool_calls": 150, "max_parallel": 3}

    rec_f, ev_f, cc_f = _measured(FREE, "free")
    ser_f = [e for e in ev_f if e.get("type") == "delegation_serialized"]
    subs_f = rec_f.get("sub_runs", [])
    both_ok_f = len(subs_f) == 2 and all(s.get("ok") for s in subs_f)
    free_ok = (bool(ser_f) and ser_f[0]["max_parallel"] == 1 and ser_f[0]["requested"] == 2
               and both_ok_f and cc_f == 1)   # concurrencia REAL medida = 1
    _record("B1·cap-paralelo·free=1", free_ok,
            f"free: evento serialized(req={ser_f[0]['requested'] if ser_f else '?'},max=1) + 2 hijos ok={both_ok_f}; "
            f"concurrencia REAL medida={cc_f} (esperado 1)")

    rec_b, ev_b, cc_b = _measured(BAS, "basico")
    ser_b = [e for e in ev_b if e.get("type") == "delegation_serialized"]
    subs_b = rec_b.get("sub_runs", [])
    bas_ok = (not ser_b and len(subs_b) == 2 and all(s.get("ok") for s in subs_b) and cc_b == 2)
    _record("B1·cap-paralelo·basico=3", bas_ok,
            f"basico(3)≥2 pedidos → sin serializar; 2 hijos concurrentes; concurrencia REAL medida={cc_b} (esperado 2)")

    # unidades: tier_max_parallel + el techo absoluto no lo evade una receta
    units = (D.tier_max_parallel({"max_parallel": 1}) == 1
             and D.tier_max_parallel({"max_parallel": 3}) == 3
             and D.tier_max_parallel({"max_parallel": 10}) == 10
             and D.tier_max_parallel(None) == D._MAX_PARALLEL
             and D.tier_max_parallel({"max_parallel": 1000}) == 1000
             and D._HARD_PARALLEL_CEILING >= 10)
    _record("B1·cap-paralelo·units", units,
            f"tier_max_parallel free→1 basico→3 tecnico→10 None→{D._MAX_PARALLEL}; hard-ceiling={D._HARD_PARALLEL_CEILING}")


# ════════════════════════════════════════════════════════════════════════════════
# DELTA 2 — GATE ANIDADO: HOIST del held del hijo al top-level (+ piso money + transitivo)
# ════════════════════════════════════════════════════════════════════════════════
def t_nested_gate_hoist():
    _hr("DELTA 2 · GATE ANIDADO — el held (money) del hijo SUBE al humano; el padre NO auto-aprueba")
    brain = V.FakeBrain(V.SCRIPTS)
    with V._Patched(brain):
        rec = _run("parent_money.json", "PARENT_MONEY", workdir=V._wd("b1-money"), approve=None)
    held = rec.get("held_actions", [])
    po = [h for h in held if h.get("tool") == "place_order"]
    child = (rec.get("sub_runs") or [{}])[0]
    cwd = child.get("workdir", "")
    leaked = (Path(cwd) / "ORDER_PLACED.flag").exists() if cwd else False
    hoisted_ok = (bool(po) and po[0].get("via_delegation") is True
                  and po[0].get("agent_path") == ["cajero_sub"]
                  and (po[0].get("recipe") or {}).get("meta", {}).get("name") == "cajero_sub")
    child_gd = [g for g in child.get("gate_decisions", []) if g["tool"] == "place_order"]
    floor_ok = bool(child_gd) and child_gd[0]["action"] == "needs_ok"
    money_ok = hoisted_ok and (not leaked) and floor_ok
    _record("B1·gate-anidado·hoist-money", money_ok,
            f"place_order del hijo → held HOISTEADO (path={po[0].get('agent_path') if po else '?'}, "
            f"recipe=cajero_sub, via_deleg={po[0].get('via_delegation') if po else '?'}); NO ejecutó (leak={leaked}); "
            f"piso money={child_gd[0]['action'] if child_gd else '?'} bajo autonomy={child_gd[0].get('autonomy') if child_gd else '?'} (receta pedía 'autonomo')")

    # el padre NO auto-aprobó pese a approve=True (RIEL #1): el held sigue retenido y sube igual.
    brain2 = V.FakeBrain(V.SCRIPTS)
    with V._Patched(brain2):
        rec2 = _run("parent_money.json", "PARENT_MONEY", workdir=V._wd("b1-money-approveall"),
                    approve=lambda *a: True)   # el padre aprueba TODO — NO debe alcanzar al hijo
    child2 = (rec2.get("sub_runs") or [{}])[0]
    leaked2 = (Path(child2.get("workdir", "")) / "ORDER_PLACED.flag").exists() if child2.get("workdir") else False
    po2 = [h for h in rec2.get("held_actions", []) if h.get("tool") == "place_order"]
    no_autoapprove = (not leaked2) and bool(po2)
    _record("B1·gate-anidado·padre-no-autoaprueba", no_autoapprove,
            f"padre approve=True NO se reenvía al hijo (RIEL #1): order NO ejecutó (leak={leaked2}); held sube igual={bool(po2)}")

    # transitivo: money del NIETO (abuelo→media→cajero) sube al top con camino de 2 niveles + receta del nieto
    brain3 = V.FakeBrain(V.SCRIPTS)
    with V._Patched(brain3):
        recg = _run("gp_money.json", "GP_MONEY", workdir=V._wd("b1-money-gp"))
    pog = [h for h in recg.get("held_actions", []) if h.get("tool") == "place_order"]
    trans_ok = (bool(pog) and pog[0].get("agent_path") == ["mid_plain", "cajero_sub"]
                and (pog[0].get("recipe") or {}).get("meta", {}).get("name") == "cajero_sub")
    _record("B1·gate-anidado·transitivo", trans_ok,
            f"money del NIETO subió al top: path={pog[0].get('agent_path') if pog else '?'} + receta del nieto (cajero_sub)")


# ════════════════════════════════════════════════════════════════════════════════
# DELTA 3 — PRESUPUESTO ANIDADO ACOTADO (hijo max_turns < padre; hijo en loop no cuelga al padre)
# ════════════════════════════════════════════════════════════════════════════════
def t_child_budget():
    _hr("DELTA 3 · PRESUPUESTO ANIDADO — el hijo hereda un techo ACOTADO; se corta antes que el árbol")
    # unidad: mitad, mín 1, max_parallel se conserva, None → None
    b = D.bounded_child_caps({"max_turns": 8, "max_tool_calls": 40, "max_parallel": 1})
    unit_ok = (b == {"max_turns": 4, "max_tool_calls": 20, "max_parallel": 1}
               and D.bounded_child_caps(None) is None
               and D.bounded_child_caps({"max_turns": 1}) == {"max_turns": 1}
               and D.bounded_child_caps({}) == {})
    _record("B1·presupuesto·units", unit_ok,
            f"bounded_child_caps(free 8/40) → {b} (mitad, mín 1, max_parallel intacto); None→None")

    # vivo: padre free(8 turnos) delega a un hijo que QUERRÍA 6 pasos → se corta en su techo (4)
    brain = V.FakeBrain(V.SCRIPTS)
    with V._Patched(brain):
        rec = _run("parent_budget.json", "PARENT_BUDGET",
                   caps_ceiling={"max_turns": 8, "max_tool_calls": 40, "max_parallel": 1},
                   workdir=V._wd("b1-budget"))
    child = (rec.get("sub_runs") or [{}])[0]
    child_reads = len([t for t in child.get("tool_calls", []) if t.get("tool") == "read_data"])
    parent_alive = bool(rec.get("ok"))
    cut = 0 < child_reads <= 4 and child_reads < 6
    budget_ok = unit_ok and cut and parent_alive
    _record("B1·presupuesto·hijo-acotado", budget_ok,
            f"hijo QUERRÍA 6 pasos, corrió {child_reads} (techo hijo=4 < padre=8); padre vivo={parent_alive}, "
            f"hijo truncado={child.get('truncated')}/{child.get('stop_reason')}")


# ════════════════════════════════════════════════════════════════════════════════
# DELTA 4 — STREAMING DEL ÁRBOL (sub_agent_started/finished; RIEL #5 intacto; tipos registrados)
# ════════════════════════════════════════════════════════════════════════════════
def t_streaming():
    _hr("DELTA 4 · STREAMING DEL ÁRBOL — el círculo del sub-agente se enciende/apaga en vivo")
    brain = V.FakeBrain(V.SCRIPTS)
    events = []
    with V._Patched(brain):
        rec = _run("parent.json", "PARENT_COORD", on_event=events.append, workdir=V._wd("b1-stream"))
    started = [e for e in events if e.get("type") == "sub_agent_started"]
    finished = [e for e in events if e.get("type") == "sub_agent_finished"]
    order_ok = (len(started) == 1 and len(finished) == 1
                and events.index(started[0]) < events.index(finished[0]))
    slug_s = started[0].get("slug") if started else None
    slug_f = finished[0].get("slug") if finished else None
    slug_ok = bool(slug_s) and slug_s == slug_f
    depth_ok = started and started[0].get("depth") == 1 and finished[0].get("depth") == 1
    # RIEL #5: el read_data INTERNO del hijo NO aparece en el stream del padre (child on_event=None)
    child_leaked = any((e.get("tool_raw") == "read_data" or e.get("tool") == "read_data") for e in events)
    stream_ok = order_ok and slug_ok and depth_ok and (not child_leaked)
    _record("B1·streaming·started-finished", stream_ok,
            f"started→finished ({len(started)}/{len(finished)}) slug={slug_s!r} depth=1; "
            f"RIEL#5: read_data del hijo NO se filtró al padre={not child_leaked}")

    # tipos registrados en EVENT_TYPES (si no, EventLog los tira silencioso = círculo invisible)
    try:
        from flywheel import events_replay as ER
        types_ok = {"sub_agent_started", "sub_agent_finished", "delegation_serialized"} <= ER.EVENT_TYPES
    except Exception as exc:
        types_ok = False
        print(f"      [warn] no pude importar flywheel.events_replay: {exc}")
    _record("B1·streaming·event-types-registrados", types_ok,
            "sub_agent_started/finished/delegation_serialized ∈ EVENT_TYPES (no se caen silenciosos)")

    # regresión: el evento de compat tool_call_finished(delegation) sigue emitiéndose
    tcf = [e for e in events if e.get("type") == "tool_call_finished" and e.get("kind") == "delegation"]
    _record("B1·streaming·compat-tool_call_finished", len(tcf) == 1,
            f"el evento de compat delegation sigue vivo ({len(tcf)}=1) — no rompe Sala/flywheel")


def main():
    t_parallel_cap()
    t_nested_gate_hoist()
    t_child_budget()
    t_streaming()

    print("\n" + "═" * 78 + "\n  RESUMEN B1 — ¿los 4 deltas del runtime de delegación CIERRAN?\n" + "═" * 78)
    ok = 0
    for label in sorted(results):
        passed, ev = results[label]
        print(f"  {label:<42} {'✓ CIERRA' if passed else '✗ NO CIERRA'}")
        ok += 1 if passed else 0
    total = len(results)
    print(f"\n  {ok}/{total} CIERRAN")
    print("  VEREDICTO:", "TODO VERDE — B1 headless cierra" if ok == total
          else "ALGO NO CIERRA — revisar antes de seguir")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
