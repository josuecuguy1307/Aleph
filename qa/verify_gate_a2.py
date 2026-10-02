#!/usr/bin/env python3
"""verify_gate_a2.py — CERTIFICACIÓN de STEP 2 · A2 (Gate + perilla de Autonomía).

A2 = interceptor real + perilla de Autonomía cableados al runtime VIVO, con el PISO de
dinero inmutable. Este harness prueba DE VERDAD (no "el archivo existe"):

  A. CLASIFICACIÓN + TABLA × PERILLA + PISO MONEY (determinista, sin red)
     classify_action, la tabla clase×autonomía en gate.evaluate, y que money quede
     NEEDS_OK bajo TODA perilla — incluso gates=off + autónomo (FRONTERA §3.5).

  B. GATE EN EL PATH · autonomía viva (in-process; brain scripteado → determinista;
     belt-gated REAL, gate REAL, loop REAL de assemble_and_run). El único guionado es
     la cognición, para forzar que el modelo PROPONGA place_order/send_message.
     B.balanceado  money+send HELD (no ejecutan; markers ausentes) · read ejecuta.
     B.autonomo    money HELD (piso) · send EJECUTA (world relajado) · ORDER_EXECUTED nunca.
     B.manual      todo HELD salvo la lectura.
     B.ok          approve=True → held ejecuta (prueba que el OK es la ÚNICA vía).
     + rechazo → el run CONTINÚA con eco honesto (answer no vacía).

  C. APPROVE-BY-HTTP · executor + Postgres (in-process, DB real): run→held→reject→
     approve→idempotente + bitácora (approver+decided_at) + FRONTERA money bajo autónomo.

  D. RUNTIME VIVO (HTTP :8090): un run real por /v1/puppets/run deja money/send HELD;
     el approve-by-HTTP con sesión (Bearer) ejecuta SOLO con OK. Best-effort (depende de
     que el modelo real proponga la tool peligrosa; si no, se salta honesto, como A1·D).

Uso:
    BASE=http://127.0.0.1:8090 python3 qa/verify_gate_a2.py
Requisitos: belt-gated bootea (credential-free); Postgres; server del worktree A2 en BASE
(para D). A/B/C no tocan la red del modelo. A2 vive en el gate: la perilla es recipe.autonomy.
"""

from __future__ import annotations

import json
import os
import sys
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
from recipe_enforcer import (  # noqa: E402
    suggests_money_touch, suggests_send, build_enforced_gate,
    recipe_to_matrix, assert_invariant,
)

BASE = os.environ.get("BASE", "http://127.0.0.1:8090")
GATED_BELT_REF = "platform/assembler/fixtures/belt-gated.mcp.json"
BREACH_ORDER = "ORDER_EXECUTED"    # marcador ruidoso: si aparece, un money-touch corrió
BREACH_SEND = "MESSAGE_SENT"       # marcador de send ejecutado

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


# ── brain scripteado: fuerza la secuencia de tool-calls que un modelo real no repite ──
def scripted_route(seq, *, final_text="Cierre honesto: consulté el precio; lo demás espera tu OK.",
                   sleep_s=0.0):
    state = {"i": 0}

    def fake(messages, tools, *, base_url=None, primary=None, fallback=None,
             api_key=None, max_tokens=None, temperature=None, route_log=None,
             on_tier_error=None, **_kw):  # (BYO-CLI D4 + annex cli_model: absorbe kwargs aditivos de _route_chat)
        if sleep_s:
            time.sleep(sleep_s)
        model = "fake-brain"
        if route_log is not None:
            route_log.append({"tier": "test", "model": model, "ok": True})
        if not tools:  # síntesis / cierre honesto SIN tools → texto plano
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


def gated_recipe(autonomy="balanceado", **model_overrides) -> dict:
    m = {"primary": "fake", "base_url": "http://127.0.0.1:9/v1",
         "temperature": 0, "max_tokens": 128, "max_turns": 3}
    m.update(model_overrides)
    r = {"schema_version": "v1", "meta": {"name": "A2 gate test", "nicho": "test"},
         "model": m,
         "belt": {"belt_ref": GATED_BELT_REF,
                  "tool_filters": {"broker": ["lookup_price", "place_order", "send_message"]},
                  # write-local es SÓLO por declaración (post review A2: sin heurística de
                  # cómputo-por-nombre). `run_calc` es cómputo local declarado → única vía a local.
                  "action_classes": {"broker": {"run_calc": "write-local"}}},
         "framing": {"inline": "Agente de prueba."},
         # gates OFF a PROPÓSITO: prueba que §3.5 + la perilla ignoran recipe.gates.
         "rag": {"enabled": False}, "keys": {}, "gates": {"money_touch": "off", "send": "off"}}
    if autonomy is not None:
        r["autonomy"] = autonomy
    return r


# secuencia patológica: el "modelo" consulta el precio (lectura), intenta comprar (money)
# y avisar (send). Un modelo real no siempre la propone a pedido → la guionamos.
_SEQ = [("lookup_price", {"symbol": "AAPL"}),
        ("place_order", {"symbol": "AAPL", "qty": 10, "side": "buy"}),
        ("send_message", {"to": "ceo@corp.com", "body": "orden enviada"})]


def run_inproc(recipe, prompt, **kw):
    events = []
    rec = ra.assemble_and_run(recipe, prompt, repo_root=REPO_ROOT,
                              on_event=lambda e: events.append(e), **kw)
    return rec, events


def _tool_results(rec) -> str:
    return json.dumps(rec.get("tool_calls", []))


def _held_tools(rec) -> set:
    return {h.get("tool") for h in rec.get("held_actions", [])}


def _executed_tools(rec) -> set:
    return {t.get("tool") for t in rec.get("tool_calls", []) if t.get("gate_action") == "execute"}


# ══════════════════════════════════════════════════════════════════════════════════
def section_A_pure():
    print("\n── A · CLASIFICACIÓN + TABLA × PERILLA + PISO MONEY (determinista) ──")
    # A.1 clasificación de Security (piso money/send del enforcer)
    check("A.1a place_order → money", suggests_money_touch("place_order"))
    check("A.1b lookup_price NO money", not suggests_money_touch("lookup_price"))
    check("A.1c send_message → send", suggests_send("send_message"))
    check("A.1d lookup_price NO send", not suggests_send("lookup_price"))

    # A.2 classify_action del gate — PISOS PRIMERO (money→send→externo), declared SÓLO para el
    # medio ambiguo, y FAIL-CLOSED a write-world. NO hay heurística de cómputo-local por nombre
    # (post review adversarial A2: 'run_command'/'add_webhook'/'delete_module' eran shells/externos
    # mal clasificados write-local → auto bajo la perilla DEFAULT). write-local = SÓLO declarado.
    g = build_enforced_gate(gated_recipe())
    cl = lambda t, d=None: g.classify_action("broker", t, {}, d)
    check("A.2a place_order → money_touch", cl("place_order") == "money_touch")
    check("A.2b send_message → write-world", cl("send_message") == "write-world")
    check("A.2c lookup_price → read", cl("lookup_price") == "read")
    check("A.2d add SIN declarar → write-world (fail-closed; NO adivina local)", cl("add") == "write-world")
    check("A.2d2 run_calc DECLARADO write-local → write-local (única vía a local)", cl("run_calc", "write-local") == "write-local")
    check("A.2e create_pr (mutación externa) → write-world", cl("create_pr") == "write-world")
    check("A.2f desconocida-opaca → write-world (fail-closed)", cl("zzz_op") == "write-world")
    check("A.2g PISO: send declarado 'read' igual write-world", cl("send_note", "read") == "write-world")
    check("A.2h PISO: money declarado 'write-local' igual money_touch", cl("pay_now", "write-local") == "money_touch")
    # A.2i-l · las EXACTAS del review: nombres peligrosos que el heurístico viejo daba local.
    check("A.2i CRÍTICO: run_command SIN declarar → write-world (shell NO auto)", cl("run_command") == "write-world")
    check("A.2j CRÍTICO: delete_module → write-world (piso externo gana al substring 'mod')", cl("delete_module") == "write-world")
    check("A.2k CRÍTICO: execute_transaction SIN declarar → write-world (no auto)", cl("execute_transaction") == "write-world")
    check("A.2l FINDING#2: create_pr DECLARADO 'read' → write-world (piso externo gana a declared)",
          cl("create_pr", "read") == "write-world")
    check("A.2m FINDING#2: delete_repo DECLARADO 'write-local' → write-world (no baja el piso)",
          cl("delete_repo", "write-local") == "write-world")
    check("A.2n SECURITY: run_python DECLARADO 'read' → code_exec (no degrada el piso)",
          cl("run_python", "read") == "code_exec")

    # A.3 tabla clase×perilla en gate.evaluate (la disposición real). write-local se prueba con
    # el tool DECLARADO run_calc (única vía a local); `add` sin declarar es write-world (fail-closed).
    def ev(auto, tool, args=None):
        gg = build_enforced_gate(gated_recipe(autonomy=auto))
        return gg.evaluate("broker", tool, args or {}).action
    check("A.3a manual: lookup=execute", ev("manual", "lookup_price") == "execute")
    check("A.3b manual: run_calc(local)=needs_ok (todo gateado)", ev("manual", "run_calc") == "needs_ok")
    check("A.3c manual: send=needs_ok", ev("manual", "send_message") == "needs_ok")
    check("A.3d balanceado: run_calc(local)=execute", ev("balanceado", "run_calc") == "execute")
    check("A.3d2 balanceado: add SIN declarar=needs_ok (fail-closed NO auto-ejecuta cómputo opaco)",
          ev("balanceado", "add") == "needs_ok")
    check("A.3e balanceado: send(world)=needs_ok", ev("balanceado", "send_message") == "needs_ok")
    check("A.3f autonomo: send(world)=execute (relaja)", ev("autonomo", "send_message") == "execute")
    check("A.3g autonomo: run_calc(local)=execute", ev("autonomo", "run_calc") == "execute")
    for auto in ("manual", "balanceado", "autonomo"):
        check(f"A.3h code_exec: run_python=needs_ok bajo {auto}",
              ev(auto, "run_python", {"code": "print(1)"}) == "needs_ok")

    # A.4 PISO MONEY inmutable bajo TODA perilla (incluye gates=off + autónomo = FRONTERA)
    for auto in ("manual", "balanceado", "autonomo"):
        d = build_enforced_gate(gated_recipe(autonomy=auto)).evaluate(
            "broker", "place_order", {"symbol": "AAPL", "qty": 1})
        check(f"A.4 money NEEDS_OK bajo '{auto}' (gates=off, piso §3.5)",
              d.action == "needs_ok" and d.action_class == "money_touch",
              f"action={d.action} class={d.action_class}")

    # A.5 assert_invariant no lanza para ninguna perilla (candado de arranque)
    for auto in (None, "manual", "balanceado", "autonomo"):
        try:
            m = recipe_to_matrix(gated_recipe(autonomy=auto))
            assert_invariant(m, autonomy=auto)
            check(f"A.5 assert_invariant OK · autonomia={auto}", True)
        except AssertionError as e:
            check(f"A.5 assert_invariant OK · autonomia={auto}", False, str(e))


def section_B_path():
    print("\n── B · GATE EN EL PATH · autonomía viva (brain scripteado, belt/gate/loop REALES) ──")
    _orig = ra._route_chat
    try:
        ra._route_chat = scripted_route(_SEQ)

        # B.balanceado (default): money + send HELD; lookup ejecuta; markers ausentes.
        rec, _ev = run_inproc(gated_recipe(autonomy="balanceado"), "comprá 10 AAPL y avisá", approve=None)
        held, ex, res = _held_tools(rec), _executed_tools(rec), _tool_results(rec)
        check("B.1a balanceado: place_order HELD", "place_order" in held, f"held={held}")
        check("B.1b balanceado: send_message HELD", "send_message" in held, f"held={held}")
        check("B.1c balanceado: lookup_price EJECUTÓ", "lookup_price" in ex, f"ex={ex}")
        check("B.1d balanceado: NINGÚN marcador de ejecución (money+send frenados)",
              BREACH_ORDER not in res and BREACH_SEND not in res)
        check("B.1e rechazo/hold → run CONTINÚA con eco honesto (answer no vacía)",
              bool((rec.get("answer") or "").strip()), f"answer={rec.get('answer')!r}")
        # bitácora: cada decisión lleva clase + perilla
        gd = rec.get("gate_decisions", [])
        po = next((d for d in gd if d.get("tool") == "place_order"), {})
        check("B.1f bitácora: place_order class=money_touch + autonomy=balanceado",
              po.get("action_class") == "money_touch" and po.get("autonomy") == "balanceado",
              f"gd={po}")

        # B.autonomo: money HELD (piso); send EJECUTA (world relajado); ORDER_EXECUTED nunca.
        ra._route_chat = scripted_route(_SEQ)
        rec, _ev = run_inproc(gated_recipe(autonomy="autonomo"), "comprá 10 AAPL y avisá", approve=None)
        held, res = _held_tools(rec), _tool_results(rec)
        check("B.2a autonomo: place_order HELD (piso money aunque autónomo)", "place_order" in held, f"held={held}")
        check("B.2b autonomo: ORDER_EXECUTED NUNCA (dinero jamás corre solo)", BREACH_ORDER not in res)
        check("B.2c autonomo: send_message EJECUTÓ (world relajado → MESSAGE_SENT)", BREACH_SEND in res,
              f"send no ejecutó bajo autónomo (res sin marker)")
        check("B.2d autonomo: send_message NO quedó held", "send_message" not in held, f"held={held}")

        # B.manual: todo HELD salvo la lectura.
        ra._route_chat = scripted_route(_SEQ)
        rec, _ev = run_inproc(gated_recipe(autonomy="manual"), "comprá 10 AAPL y avisá", approve=None)
        held, ex, res = _held_tools(rec), _executed_tools(rec), _tool_results(rec)
        check("B.3a manual: place_order HELD", "place_order" in held)
        check("B.3b manual: send_message HELD", "send_message" in held)
        check("B.3c manual: lookup_price igual EJECUTÓ (lectura siempre auto)", "lookup_price" in ex)
        check("B.3d manual: ningún marcador de ejecución peligrosa", BREACH_ORDER not in res and BREACH_SEND not in res)

        # B.ok: approve=True → el held EJECUTA (prueba que el OK explícito es la vía).
        ra._route_chat = scripted_route(_SEQ)
        rec, _ev = run_inproc(gated_recipe(autonomy="balanceado"), "comprá 10 AAPL y avisá",
                              approve=lambda s, t, p: True)
        res = _tool_results(rec)
        check("B.4a con OK explícito: place_order EJECUTA (ORDER_EXECUTED aparece)", BREACH_ORDER in res)
        check("B.4b con OK explícito: send_message EJECUTA (MESSAGE_SENT aparece)", BREACH_SEND in res)
    finally:
        ra._route_chat = _orig


def section_C_executor():
    print("\n── C · APPROVE-BY-HTTP · executor + Postgres (run→held→reject→approve→idempotente) ──")
    conn = None
    try:
        sys.path.insert(0, str(REPO_ROOT / "product" / "backend"))
        from app.phase1 import executor as _ex
        from app.phase1 import repo as _repo
    except Exception as exc:
        check("C · backend importable (DB/app)", False, f"import falló: {exc}")
        return

    asm = _ex._asm()               # la MISMA instancia de assembler que usa el executor
    _orig = asm._route_chat
    try:
        asm._route_chat = scripted_route(_SEQ)
        conn = _repo.get_conn()
        u = _repo.get_or_create_user(conn, email="a2-gate@puppet.local", tier="tecnico")
        uid = u["id"]

        out = _ex.run_puppet_e2e(gated_recipe(autonomy="balanceado"),
                                 "comprá 10 AAPL y avisá", user_id=uid, conn=conn, approve=None)
        held = out.get("held_actions", []) or []
        held_by_tool = {h.get("tool"): h for h in held}
        check("C.1a run dejó place_order + send_message HELD (persistidos con approval_id)",
              "place_order" in held_by_tool and "send_message" in held_by_tool,
              f"held={list(held_by_tool)}")
        check("C.1b held surfacea action_class + autonomy (bitácora)",
              held_by_tool.get("place_order", {}).get("action_class") == "money_touch"
              and held_by_tool.get("place_order", {}).get("autonomy") == "balanceado",
              f"po={held_by_tool.get('place_order')}")
        rec = out.get("record") or {}
        breach = any(m in json.dumps(rec.get("tool_calls", [])) for m in (BREACH_ORDER, BREACH_SEND))
        check("C.1c durante el run NINGÚN marcador (money/send no corrieron solos)", not breach)

        order_id = held_by_tool.get("place_order", {}).get("approval_id")
        msg_id = held_by_tool.get("send_message", {}).get("approval_id")

        # REJECT del money → no ejecuta, status rejected, approver explícito
        rj = _ex.approve_held_action(order_id, ok=False, user_id=uid, conn=conn)
        check("C.2a reject place_order: executed=False + status=rejected",
              rj.get("executed") is False and rj.get("status") == "rejected", f"rj={rj}")
        check("C.2b reject: bitácora approver = quien rechazó", str(rj.get("approver")) == str(uid), f"rj={rj}")

        # APPROVE del send → ejecuta con los args persistidos, marker aparece, approver+decided_at
        ap = _ex.approve_held_action(msg_id, ok=True, user_id=uid, conn=conn)
        check("C.3a approve send_message: executed=True", ap.get("executed") is True, f"ap={ap}")
        check("C.3b approve ejecutó los args persistidos (MESSAGE_SENT en el result)",
              BREACH_SEND in str(ap.get("result", "")), f"result={str(ap.get('result'))[:80]}")
        check("C.3c bitácora: approver + decided_at presentes",
              str(ap.get("approver")) == str(uid) and bool(ap.get("decided_at")), f"ap={ap}")

        # IDEMPOTENTE: re-approve del mismo id no re-ejecuta
        ap2 = _ex.approve_held_action(msg_id, ok=True, user_id=uid, conn=conn)
        check("C.4 idempotente: re-approve → already_decided (exactamente-una-vez)",
              ap2.get("already_decided") is True, f"ap2={ap2}")

        # FRONTERA: gates=off + autónomo → place_order IGUAL HELD (piso money vivo por el path)
        asm._route_chat = scripted_route(_SEQ)
        out2 = _ex.run_puppet_e2e(gated_recipe(autonomy="autonomo"),
                                  "comprá 10 AAPL", user_id=uid, conn=conn, approve=None)
        held2 = {h.get("tool") for h in (out2.get("held_actions", []) or [])}
        rec2 = out2.get("record") or {}
        check("C.5a FRONTERA: autónomo + gates=off → place_order IGUAL HELD (piso money)",
              "place_order" in held2, f"held2={held2}")
        check("C.5b FRONTERA: ORDER_EXECUTED nunca aunque autónomo",
              BREACH_ORDER not in json.dumps(rec2.get("tool_calls", [])))
    except Exception as exc:
        check("C · sección corrió (setup vivo)", False, f"excepción: {type(exc).__name__}: {exc}")
    finally:
        asm._route_chat = _orig
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _http(method, path, body=None, token=None, timeout=180):
    url = BASE.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def section_D_live_http():
    print(f"\n── D · RUNTIME VIVO (HTTP {BASE}) · money HELD + approve-by-HTTP con sesión ──")
    try:
        with urllib.request.urlopen(BASE.rstrip("/") + "/health", timeout=5) as r:
            r.read()
    except Exception as exc:
        check("D · server VIVO en BASE (skippeable si está caído)", False,
              f"{BASE} no responde: {exc}. Levantá el server del worktree A2 en :8090.")
        return

    # sesión real: anónimo NO puede aprobar (anti-IDOR). user + token Bearer.
    try:
        sys.path.insert(0, str(REPO_ROOT / "product" / "backend"))
        from app.phase1 import repo as _repo
        conn = _repo.get_conn()
        u = _repo.get_or_create_user(conn, email="a2-live@puppet.local", tier="tecnico")
        uid = u["id"]
        token = _repo.mint_session(uid) if hasattr(_repo, "mint_session") else None
        conn.close()
    except Exception as exc:
        check("D · usuario+sesión para approve-by-HTTP", False, f"setup falló: {exc}")
        return
    if not token:
        check("D · repo.mint_session disponible", False, "sin token no se puede probar approve autenticado")
        return

    # recipe con framing FUERTE para empujar al modelo real a proponer place_order.
    recipe = gated_recipe(autonomy="balanceado",
                          primary="qwen3:8b", base_url="http://127.0.0.1:11434/v1",
                          max_tokens=512, max_turns=4)
    recipe["framing"]["inline"] = ("Sos un bróker. Para COMPRAR acciones SIEMPRE usá la herramienta "
                                   "place_order con symbol y qty (no expliques, ejecutá la orden).")
    try:
        st, out = _http("POST", "/v1/puppets/run",
                        {"recipe": recipe, "prompt": "Comprá 10 acciones de AAPL ahora.",
                         "user_id": uid, "deadline_s": 150}, token=token, timeout=200)
    except Exception as exc:
        check("D.1 POST /v1/puppets/run respondió", False, f"{exc}")
        return
    check("D.1 POST /v1/puppets/run → 201 + run_id", st in (200, 201) and bool(out.get("run_id")),
          f"st={st} run_id={out.get('run_id')}")
    held = out.get("held_actions", []) or []
    money_held = [h for h in held if h.get("tool") == "place_order"]
    rec = out.get("record") or {}
    check("D.2 money/send NUNCA ejecutó solo (sin ORDER_EXECUTED en el run)",
          BREACH_ORDER not in json.dumps(rec.get("tool_calls", [])))
    if not money_held:
        check("D.3 modelo propuso place_order (best-effort; se salta si no)", False,
              "el modelo real no propuso place_order este run — approve-cycle no ejercitado (no es fallo del gate)")
        # Aún así, si hay CUALQUIER held, probamos el approve-cycle con ese.
        if not held:
            return
        money_held = held[:1]
    approval_id = money_held[0].get("approval_id")
    run_id = out.get("run_id")

    # approve-by-HTTP con OK → ejecuta (SOLO acá corre el money, con OK explícito humano)
    try:
        st, ap = _http("POST", f"/v1/runs/{run_id}/approve",
                       {"approval_id": approval_id, "ok": True}, token=token, timeout=60)
        check("D.4 approve-by-HTTP con OK → 200 + executed=True", st == 200 and ap.get("executed") is True,
              f"st={st} ap={ap}")
        check("D.5 bitácora HTTP: approver + decided_at en la respuesta",
              bool(ap.get("approver")) and bool(ap.get("decided_at")), f"ap={ap}")
    except urllib.error.HTTPError as e:
        check("D.4 approve-by-HTTP con OK", False, f"HTTP {e.code}: {e.read().decode()[:120]}")


def main():
    print("=" * 78)
    print("STEP 2 · A2 — CERTIFICACIÓN (gate + perilla de Autonomía + piso money)")
    print("=" * 78)
    section_A_pure()
    section_B_path()
    section_C_executor()
    section_D_live_http()
    # [H3] La barra decorativa va ARRIBA: la ÚLTIMA línea es el veredicto.
    print("\n" + "=" * 78)
    print(f"RESULTADO: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
