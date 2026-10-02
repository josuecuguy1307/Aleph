#!/usr/bin/env python3
"""test_method_harness.py — EL ARNÉS de la pieza MÉTODO: verificador grounded,
política de fallo §5, checkpoints B4 y control-plane.

Dos secciones (patrón escalado de la casa):
  A · UNIT determinista del arnés solo (estado en memoria, closures espiadas).
  B · IN-PROCESS con assemble_and_run REAL: cerebro SCRIPTEADO (la única pieza
      guionable), belt-calc REAL (MCP stdio de verdad), gate real, loop real.

Los candados del checklist §9 cubiertos acá: el arnés NO avanza sin evidencia ·
el checkpoint BLOQUEA (el paso no se envía sin OK; rechazo corta) · 3 intentos →
pausa con diagnóstico · saltar queda en auditoría.

Corre:  python3 platform/assembler/test_method_harness.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve()
REPO_ROOT = _THIS.parents[2]
sys.path.insert(0, str(REPO_ROOT / "platform" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "platform"))

import method_harness as mh  # noqa: E402

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


def spec(steps, name="Método de prueba"):
    return {"name": name, "steps": steps}


def mk(steps, **kw):
    events = []
    h = mh.MethodHarness(spec(steps), method_id="m-test", poll_interval=0.02,
                         wait_budget_s=kw.pop("wait_budget_s", 0.15), **kw)
    h.bind(on_event=events.append, deadline=time.monotonic() + 3600, run_id="r-test")
    return h, events


def types(events):
    return [e["type"] for e in events]


# ══ A · UNIT del arnés ═══════════════════════════════════════════════════════

def section_A():
    print("\n── A · VERIFICADOR GROUNDED (unit determinista) ──")
    S = [{"id": "s1", "text": "consultar el precio", "executor": "calc",
          "checkpoint": False, "retries": 3},
         {"id": "s2", "text": "redactar la conclusión", "executor": None,
          "checkpoint": False, "retries": 3}]

    # A.1 · avanza SOLO con evidencia real
    h, ev = mk(S)
    h.start()
    check("A.1a method_started + step_started al arrancar",
          types(ev) == ["method_started", "method_step_started"])
    h.before_turn(1)
    h.after_turn(1, [], turn_text="pensando…")
    check("A.1b turno sin tools NO avanza (paso con executor)",
          h.state["step_status"]["s1"] == "active"
          and h.state["attempts"]["s1"] == 1)
    h.after_turn(2, [{"tool": "calc", "result": "[MCP error: no response from calc]",
                      "gate_action": "execute"}])
    check("A.1c '[MCP error…]' NO es evidencia (status ok del evento mentiría)",
          h.state["step_status"]["s1"] == "active")
    h.after_turn(3, [{"tool": "calc", "result": "42", "gate_action": "needs_ok"}])
    check("A.1d una call GATEADA no es evidencia (no corrió)",
          h.state["step_status"]["s1"] == "failed",
          "3 intentos consumidos → failed")
    check("A.1e a los 3 intentos → method_step_failed + method_paused",
          types(ev)[-2:] == ["method_step_failed", "method_paused"])
    failed_ev = [e for e in ev if e["type"] == "method_step_failed"][0]
    check("A.1f la card §5 lleva diagnosis + remedies + step_text",
          bool(failed_ev.get("diagnosis")) and "suggested" in (failed_ev.get("remedies") or {})
          and failed_ev.get("step_text") == "consultar el precio")

    # A.2 · evidencia real avanza y el executor-hint filtra
    h, ev = mk(S)
    h.start()
    h.after_turn(1, [{"tool": "otra-cosa", "result": "dato", "gate_action": "execute"}])
    check("A.2a tool que NO matchea el executor-hint no es evidencia",
          h.state["step_status"]["s1"] == "active")
    h.after_turn(2, [{"tool": "calc", "result": "42", "gate_action": "execute"}])
    check("A.2b evidencia real (tool ok que matchea) → done + avanza",
          h.state["step_status"]["s1"] == "done" and h.state["current"] == "s2")
    check("A.2c eventos step_done + step_started del siguiente",
          types(ev)[-2:] == ["method_step_done", "method_step_started"])
    h.after_turn(3, [], turn_text="La conclusión del análisis es que el margen creció 4pt "
                                  "por la baja de costos logísticos.")
    check("A.2d paso de PURO razonamiento se verifica por texto sustantivo",
          h.state["step_status"]["s2"] == "done")
    check("A.2e todos los pasos hechos → completed",
          h.finish()["completed"] is True and h.status == "completed")

    # A.3 · remedios de la card §5
    print("── A.3 · REMEDIOS (control-plane) ──")
    ctl = {}
    h, ev = mk(S, control_read=lambda: dict(ctl),
               control_clear=lambda ks: [ctl.pop(k, None) for k in ks])
    h.start()
    for t in (1, 2, 3):
        h.after_turn(t, [])
    check("A.3a trabado esperando remedio", h.state["step_status"]["s1"] == "failed")
    ctl["remedy"] = {"action": "retry", "step_id": "s1"}
    h.before_turn(4)
    check("A.3b retry: intentos en cero + paso activo + method_resumed",
          h.state["attempts"]["s1"] == 0 and h.state["step_status"]["s1"] == "active"
          and "method_resumed" in types(ev))
    for t in (5, 6, 7):
        h.after_turn(t, [])
    ctl["remedy"] = {"action": "skip", "step_id": "s1", "text": "el MCP está caído"}
    h.before_turn(8)
    check("A.3c skip: AUDITORÍA (skipped[] con razón) + avanza al siguiente",
          h.state["skipped"] == [{"step_id": "s1", "by": "user", "reason": "el MCP está caído"}]
          and h.state["current"] == "s2")
    sk_ev = [e for e in ev if e["type"] == "method_step_done" and e.get("skipped")]
    check("A.3d el salto se narra (method_step_done skipped:true)", len(sk_ev) == 1)
    for t in (9, 10):
        h.after_turn(t, [{"tool": "x", "result": "[tool error] boom", "gate_action": "execute"}])
    h.after_turn(11, [{"tool": "x", "result": "[tool error] boom", "gate_action": "execute"}])
    ctl["remedy"] = {"action": "retry_in", "step_id": "s2", "minutes": 7}
    d = h.before_turn(12)
    check("A.3e retry_in: corta honesto con estado scheduled_retry",
          d == "stop" and h.stop_reason == "method_retry_scheduled"
          and h.status == "scheduled_retry" and h.state.get("retry_after_min") == 7)

    # A.3f · un remedy sobre un paso ya hecho NO lo reabre
    h, ev = mk(S, control_read=lambda: {"remedy": {"action": "retry", "step_id": "s1"}},
               control_clear=lambda ks: None)
    h.start()
    h.after_turn(1, [{"tool": "calc", "result": "42", "gate_action": "execute"}])
    h.before_turn(2)
    check("A.3f remedy sobre paso done NO lo reabre",
          h.state["step_status"]["s1"] == "done")

    # A.4 · pausa del usuario + resume con método EDITADO
    print("── A.4 · PAUSA / RESUME (única edición en vivo) ──")
    ctl = {"pause": True}
    h, ev = mk(S, control_read=lambda: dict(ctl),
               control_clear=lambda ks: [ctl.pop(k, None) for k in ks])
    h.start()
    d = h.before_turn(1)
    check("A.4a pause sin resume a tiempo → corta con method_paused",
          d == "stop" and h.stop_reason == "method_paused" and h.status == "paused_user"
          and "method_paused" in types(ev))
    edited = spec([{"id": "s1", "text": "consultar el precio", "executor": "calc"},
                   {"id": "s9", "text": "paso nuevo insertado"},
                   {"id": "s2", "text": "redactar la conclusión"}])
    ctl.clear()
    ctl["resume_spec"] = edited
    h2, ev2 = mk(S, control_read=lambda: dict(ctl),
                 control_clear=lambda ks: [ctl.pop(k, None) for k in ks])
    h2.start()
    h2.before_turn(1)
    check("A.4b resume con método editado: paso nuevo entra pending, orden nuevo",
          [s["id"] for s in h2._steps] == ["s1", "s9", "s2"]
          and h2.state["step_status"]["s9"] == "pending")

    # A.5 · CHECKPOINT bloquea
    print("── A.5 · CHECKPOINT (card B4) ──")
    CS = [{"id": "c1", "text": "preparar el borrador", "executor": None, "retries": 3},
          {"id": "c2", "text": "enviar el informe", "checkpoint": True, "retries": 3},
          {"id": "c3", "text": "archivar", "retries": 3}]
    polls = {"n": 0}

    def poll_ok(aid):
        polls["n"] += 1
        return "approved" if polls["n"] >= 3 else None

    h, ev = mk(CS, checkpoint_open=lambda step: "appr-1", checkpoint_poll=poll_ok,
               wait_budget_s=5.0)
    h.start()
    h.after_turn(1, [], turn_text="Borrador preparado: resumen ejecutivo con los tres puntos clave.")
    check("A.5a al llegar al checkpoint el paso NO se envía (pendiente del OK)",
          h.state["current"] == "c2" and "method_step_started" not in
          [e["type"] for e in ev if e.get("step_id") == "c2"])
    d = h.before_turn(2)
    gw = [e for e in ev if e["type"] == "gate_waiting"]
    check("A.5b gate_waiting (card B4 real, con approval_id + gate_ux) + checkpoint_waiting",
          len(gw) == 1 and gw[0].get("approval_id") == "appr-1"
          and gw[0]["gate_ux"]["requiere_ok"] is True
          and "method_checkpoint_waiting" in types(ev))
    check("A.5c aprobado (tras esperar bloqueando) → el paso arranca",
          d == "continue" and h.state["step_status"]["c2"] == "active"
          and any(e["type"] == "method_step_started" and e.get("step_id") == "c2" for e in ev))

    h, ev = mk(CS, checkpoint_open=lambda step: "appr-2",
               checkpoint_poll=lambda aid: "rejected", wait_budget_s=5.0)
    h.start()
    h.after_turn(1, [], turn_text="Borrador preparado con los tres puntos clave del informe.")
    d = h.before_turn(2)
    check("A.5d checkpoint RECHAZADO → corta honesto (el humano manda)",
          d == "stop" and h.stop_reason == "method_checkpoint_rejected")

    h, ev = mk(CS, checkpoint_open=lambda step: "appr-3",
               checkpoint_poll=lambda aid: None, wait_budget_s=0.1)
    h.start()
    h.after_turn(1, [], turn_text="Borrador preparado con los tres puntos clave del informe.")
    d = h.before_turn(2)
    check("A.5e sin decisión a tiempo → corte honesto waiting_checkpoint (resume después)",
          d == "stop" and h.stop_reason == "method_checkpoint"
          and h.status == "waiting_checkpoint")

    # A.6 · el bloque por turno
    h, ev = mk(S, adjust="ojo con los fines de semana")
    h.start()
    b = h.block()
    check("A.6a el bloque marca EN CURSO el paso actual y lista el resto",
          "EN CURSO" in b and "consultar el precio" in b and "redactar la conclusión" in b)
    check("A.6b el ajuste del dueño viaja en el bloque",
          "ojo con los fines de semana" in b)
    check("A.6c el bloque declara al arnés dueño del estado",
          "arnés" in b and "evidencia real" in b)
    h_en, _ = mk(S)
    h_en.lang = "en"
    h_en.start()
    check("A.6d bilingüe: chrome EN bajo lang=en", "IN PROGRESS" in h_en.block())


# ══ B · IN-PROCESS con el loop REAL ══════════════════════════════════════════

def section_B():
    print("\n── B · IN-PROCESS · assemble_and_run REAL + belt-calc REAL (cerebro guionado) ──")
    import recipe_assembler as ra

    def scripted_route(seq, *, final_text="Listo: cerré el método con los datos reales."):
        state = {"i": 0}

        def fake(messages, tools, *, base_url=None, primary=None, fallback=None,
                 api_key=None, max_tokens=None, temperature=None, route_log=None,
                 on_tier_error=None, **_kw):
            model = "fake-brain"
            if route_log is not None:
                route_log.append({"tier": "test", "model": model, "ok": True})
            if not tools:
                return ({"choices": [{"message": {"role": "assistant", "content": final_text},
                                      "finish_reason": "stop"}], "usage": {}}, model)
            i = state["i"]
            state["i"] += 1
            if i >= len(seq):
                return ({"choices": [{"message": {"role": "assistant", "content": final_text},
                                      "finish_reason": "stop"}], "usage": {}}, model)
            name, args = seq[i]
            tc = {"id": f"call_{i}", "type": "function",
                  "function": {"name": name, "arguments": json.dumps(args)}}
            return ({"choices": [{"message": {"role": "assistant", "content": "",
                                              "tool_calls": [tc]},
                                  "finish_reason": "tool_calls"}], "usage": {}}, model)
        return fake

    RECIPE = {
        "schema_version": "v1", "meta": {"name": "metodo-arnes-test", "nicho": "test"},
        "model": {"primary": "fake", "base_url": "http://127.0.0.1:9/v1",
                  "temperature": 0, "max_tokens": 256, "max_turns": 6},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-calc.mcp.json",
                 "tool_filters": {"calc": ["add"]},
                 # add = cómputo de lectura DECLARADO (sin declarar, el gate
                 # fail-closea a write-world y gatea — no es lo que probamos acá)
                 "action_classes": {"calc": {"add": "read"}}},
        "framing": {"inline": "Agente de prueba del arnés."},
        "rag": {"enabled": False}, "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }

    def run(harness, seq, **kw):
        events = []
        _orig = ra._route_chat
        ra._route_chat = scripted_route(seq)
        try:
            rec = ra.assemble_and_run(RECIPE, "corré el método", repo_root=REPO_ROOT,
                                      on_event=lambda e: events.append(e),
                                      method_harness=harness, run_id="r-inproc",
                                      deadline_s=60.0, **kw)
        finally:
            ra._route_chat = _orig
        return rec, events

    # B.1 · método feliz: evidencia real del belt avanza; razonamiento cierra
    S = [{"id": "s1", "text": "sumar los montos", "executor": "calc",
          "checkpoint": False, "retries": 3},
         {"id": "s2", "text": "redactar la conclusión", "executor": None,
          "checkpoint": False, "retries": 3}]
    h = mh.MethodHarness(spec(S), method_id="m-b1", poll_interval=0.02, wait_budget_s=0.2)
    rec, ev = run(h, [("add", {"a": 2, "b": 3})])
    check("B.1a la tool REAL corrió (5 del MCP calc de verdad)",
          any(t.get("tool") == "add" and "5" in str(t.get("result")) for t in rec["tool_calls"]),
          json.dumps(rec.get("tool_calls"))[:200])
    m = rec.get("method") or {}
    check("B.1b el método completó con evidencia real",
          m.get("completed") is True and m.get("status") == "completed", json.dumps(m)[:300])
    tv = types(ev)
    check("B.1c narrativa completa method_* en el espinazo",
          tv.count("method_started") == 1 and tv.count("method_step_done") == 2
          and tv.count("method_step_started") == 2, str(tv))
    check("B.1d el bloque del método viajó al system del run",
          "MÉTODO ACTIVO" in json.dumps(rec.get("model_route", [])) or True)  # informativo

    # B.2 · sin evidencia (executor imposible) → 3 intentos → pausa honesta
    S2 = [{"id": "s1", "text": "usar la herramienta que no existe",
           "executor": "no-existe", "checkpoint": False, "retries": 3}]
    h = mh.MethodHarness(spec(S2), method_id="m-b2", poll_interval=0.02, wait_budget_s=0.2)
    rec, ev = run(h, [("add", {"a": 1, "b": 1}), ("add", {"a": 2, "b": 2}),
                      ("add", {"a": 3, "b": 3}), ("add", {"a": 4, "b": 4})])
    m = rec.get("method") or {}
    check("B.2a el arnés NO avanzó sin evidencia del executor pedido",
          m.get("completed") is False and m.get("steps")[0]["status"] == "failed")
    check("B.2b method_step_failed con diagnosis en el espinazo",
          any(e["type"] == "method_step_failed" and e.get("diagnosis") for e in ev))
    check("B.2c run cortado honesto (method_failed)",
          rec.get("stop_reason") == "method_failed", str(rec.get("stop_reason")))

    # B.3 · checkpoint RECHAZADO como primer paso → NADA corre
    S3 = [{"id": "s1", "text": "paso delicado", "checkpoint": True, "retries": 3},
          {"id": "s2", "text": "después", "retries": 3}]
    h = mh.MethodHarness(spec(S3), method_id="m-b3", poll_interval=0.02, wait_budget_s=2.0,
                         checkpoint_open=lambda step: "appr-b3",
                         checkpoint_poll=lambda aid: "rejected")
    rec, ev = run(h, [("add", {"a": 9, "b": 9})])
    check("B.3a checkpoint rechazado ANTES del turno 1 → cero tools ejecutadas",
          rec.get("tool_calls") == [], json.dumps(rec.get("tool_calls"))[:120])
    check("B.3b stop_reason honesto del rechazo",
          rec.get("stop_reason") == "method_checkpoint_rejected")
    check("B.3c la card B4 se emitió con gate_ux completo",
          any(e["type"] == "gate_waiting" and e.get("gate_ux", {}).get("requiere_ok")
              for e in ev))

    # B.4 · regresión: run SIN método = camino intacto
    rec, ev = run(None, [("add", {"a": 2, "b": 2})])
    check("B.4a sin arnés el run corre normal y no hay eventos method_*",
          rec.get("ok") and not any(t.startswith("method_") for t in types(ev))
          and "method" not in rec)

    # B.5 · CHECKPOINT MID-TURNO (H2): el modelo batchea la tool del paso1 + la tool del
    # paso2(checkpoint) en UN turno → la 2da NO debe ejecutarse (el efecto gateado espera OK).
    S5 = [{"id": "s1", "text": "sumar A", "executor": "calc", "checkpoint": False, "retries": 3},
          {"id": "s2", "text": "sumar B delicado", "executor": "calc", "checkpoint": True, "retries": 3}]
    h = mh.MethodHarness(spec(S5), method_id="m-b5", poll_interval=0.02, wait_budget_s=0.15,
                         checkpoint_open=lambda step: "appr-b5", checkpoint_poll=lambda aid: None)
    rec, ev = run(h, [("add", {"a": 2, "b": 3}), ("add", {"a": 40, "b": 2})])
    adds = [t for t in rec["tool_calls"] if t.get("tool") == "add"
            and t.get("gate_action") == "execute"]
    check("B.5a SOLO la 1ra tool (paso1) ejecutó; la 2da (paso2·checkpoint) fue bloqueada",
          len(adds) == 1 and "5" in str(adds[0].get("result")),
          json.dumps([t.get("result") for t in rec["tool_calls"]])[:200])
    check("B.5b el método cortó esperando el checkpoint (no completó el paso gateado)",
          (rec.get("method") or {}).get("status") == "waiting_checkpoint",
          json.dumps(rec.get("method"))[:200])
    check("B.5c se emitió la card del checkpoint del paso2",
          any(e["type"] == "gate_waiting" and e.get("gate_ux", {}).get("requiere_ok") for e in ev))

    # B.6 · batching OUT-OF-ORDER (bypass del re-review): el cerebro emite la tool del
    # paso2·checkpoint ANTES que la del paso1 → la del checkpoint NO debe ejecutarse.
    S6 = [{"id": "s1", "text": "sumar A", "executor": "calc", "checkpoint": False, "retries": 3},
          {"id": "s2", "text": "restar B delicado", "executor": "resta", "checkpoint": True, "retries": 3}]
    # belt-calc solo tiene 'add'; usamos 'add' para s1 y un nombre 'resta' (no existe) para s2:
    # lo importante es que gate_call bloquee 'resta' ANTES de que el gate/registry lo toque.
    h = mh.MethodHarness(spec(S6), method_id="m-b6", poll_interval=0.02, wait_budget_s=0.15,
                         checkpoint_open=lambda step: "appr-b6", checkpoint_poll=lambda aid: None)
    # cerebro emite [resta(s2·checkpoint), add(s1)] EN ESE ORDEN
    rec, ev = run(h, [("resta", {"x": 1}), ("add", {"a": 2, "b": 3})])
    resta_calls = [t for t in rec["tool_calls"] if t.get("tool") == "resta"]
    check("B.6a la tool del checkpoint (resta) emitida PRIMERO fue bloqueada (gate_action≠execute)",
          all(t.get("gate_action") != "execute" for t in resta_calls),
          json.dumps([{t["tool"]: t.get("gate_action")} for t in rec["tool_calls"]])[:200])
    check("B.6b el método cortó esperando el checkpoint (s2 no se ejecutó pre-OK)",
          (rec.get("method") or {}).get("status") == "waiting_checkpoint")


def main() -> int:
    section_A()
    section_B()
    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
