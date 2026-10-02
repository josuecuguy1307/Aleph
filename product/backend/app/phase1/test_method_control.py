#!/usr/bin/env python3
"""test_method_control.py — pieza 5 del MÉTODO: checkpoint B4 decidido por
approve-by-HTTP (held SENTINELA sin ejecución), endpoints pause/resume/remedy,
diagnóstico §5 y CONTINUACIÓN server-side de un run cortado.

Postgres REAL + executor REAL + belt-calc REAL; cerebro SCRIPTEADO (única pieza
guionable) inyectado en LA instancia del assembler que usa el executor.

Corre:  cd product/backend && PYTHONPATH=. PUPPET_METHOD_SYNC_RESUME=1 \
        .venv/bin/python app/phase1/test_method_control.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("PUPPET_METHOD_SYNC_RESUME", "1")

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


RECIPE = {
    "schema_version": "v1", "meta": {"name": "metodo-control-test", "nicho": "test"},
    "model": {"primary": "fake", "base_url": "http://127.0.0.1:9/v1",
              "temperature": 0, "max_tokens": 256, "max_turns": 6},
    "belt": {"belt_ref": "platform/assembler/fixtures/belt-calc.mcp.json",
             "tool_filters": {"calc": ["add"]},
             "action_classes": {"calc": {"add": "read"}}},
    "framing": {"inline": "Agente de prueba del control del método."},
    "rag": {"enabled": False}, "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}


def scripted_route(seq, *, final_text="Conclusión: la suma dio 42 según la tool real; "
                                      "cierro el método con ese dato verificado."):
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


def main() -> int:
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
    except Exception as e:
        print(f"[SKIP] DB no disponible ({e})")
        return 0

    from app.phase1 import executor
    from app.phase1 import methods_repo as mr

    u = repo.get_or_create_user(conn, email=f"metodo-ctl-{uuid.uuid4().hex[:8]}@test.local")
    conn.commit()
    uid = str(u["id"])

    # ── 1 · CHECKPOINT SENTINELA por approve-by-HTTP (sin ejecución) ────────
    print("── 1 · held sentinela server='metodo' → decide SIN execute_held_tool ──")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (user_id, intent) VALUES (%s,%s) RETURNING id",
                    (uid, "test checkpoint"))
        run_a = str(cur.fetchone()[0])
    conn.commit()
    method = mr.create_method(conn, user_id=uid, method=mr.normalize_method(
        {"name": "M control", "steps": [{"text": "p1", "checkpoint": True}]}))
    sid = method["steps"][0]["id"]
    mr.create_method_run(conn, run_id=run_a, method_id=method["id"], user_id=uid,
                         puppet_id=None, space_id=None,
                         state={"spec": method, "current": sid,
                                "step_status": {sid: "pending"}, "attempts": {},
                                "skipped": [], "evidence": {}, "free_notes": [],
                                "lang": "es"},
                         status="waiting_checkpoint")
    held = repo.create_held_action(conn, run_id=run_a, user_id=uid, recipe=RECIPE,
                                   server="metodo", tool="checkpoint",
                                   args={"step_id": sid, "step_text": "p1"},
                                   level="checkpoint", turn_text="p1")
    ap = executor.approve_held_action(str(held["id"]), ok=True, user_id=uid)
    check("1a approve del checkpoint: executed status SIN ejecución de tool",
          ap.get("status") == "executed" and ap.get("checkpoint") is True
          and ap.get("executed") is False, json.dumps(ap, default=str)[:200])
    ctl = mr.read_control(conn, run_a)
    check("1b la decisión quedó durable en method_runs.control",
          (ctl.get("checkpoint") or {}).get("ok") is True
          and ctl["checkpoint"].get("step_id") == sid)
    ap2 = executor.approve_held_action(str(held["id"]), ok=True, user_id=uid)
    check("1c idempotente: re-approve → already_decided", ap2.get("already_decided") is True)

    held2 = repo.create_held_action(conn, run_id=run_a, user_id=uid, recipe=RECIPE,
                                    server="metodo", tool="checkpoint",
                                    args={"step_id": sid}, level="checkpoint")
    rj = executor.approve_held_action(str(held2["id"]), ok=False, user_id=uid)
    ctl = mr.read_control(conn, run_a)
    check("1d rechazo → rejected + control.ok=False",
          rj.get("status") == "rejected" and (ctl.get("checkpoint") or {}).get("ok") is False)
    other = repo.get_or_create_user(conn, email=f"metodo-intr-{uuid.uuid4().hex[:8]}@test.local")
    conn.commit()
    held3 = repo.create_held_action(conn, run_id=run_a, user_id=uid, recipe=RECIPE,
                                    server="metodo", tool="checkpoint",
                                    args={"step_id": sid}, level="checkpoint")
    ap3 = executor.approve_held_action(str(held3["id"]), ok=True, user_id=str(other["id"]))
    check("1e anti-IDOR: otro usuario no decide el checkpoint",
          ap3.get("authorized") is False)

    # ── 2 · diagnóstico §5 (composición de señales) ─────────────────────────
    print("── 2 · diagnose(): capacidad no conectada / credencial / MCP caído ──")
    diag = executor._method_diagnose_factory(RECIPE, None)
    d = diag({"executor": "notion", "text": "x"}, [], "es")
    check("2a executor fuera del belt → connect_mcp",
          d["remedies"]["suggested"] == "connect_mcp", json.dumps(d)[:160])
    d = diag({"executor": "calc", "text": "x"},
             [{"tool": "add", "result": "[tool error] HTTP 401 unauthorized"}], "es")
    check("2b 401 en el fallo → reconnect", d["remedies"]["suggested"] == "reconnect")
    d = diag({"executor": "calc", "text": "x"},
             [{"tool": "add", "result": "[MCP error: no response from calc]"}], "en")
    check("2c MCP caído → retry (y bilingüe EN)",
          d["remedies"]["suggested"] == "retry" and "not responding" in d["diagnosis"])

    # ── 3 · endpoints pause/resume/remedy ───────────────────────────────────
    print("── 3 · endpoints de control ──")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.methods_router import build_methods_router
    events_root = Path(tempfile.mkdtemp(prefix="metodo-ctl-events-"))
    app = FastAPI()
    app.include_router(build_methods_router(get_conn=repo.get_conn,
                                            events_dir=lambda: events_root))
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + repo.mint_session(uid)}
    auth_other = {"Authorization": "Bearer " + repo.mint_session(str(other["id"]))}

    # run VIVO (status 'running' recién creado) con method_run activo
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (user_id, intent) VALUES (%s,%s) RETURNING id",
                    (uid, "run vivo"))
        run_live = str(cur.fetchone()[0])
    conn.commit()
    mr.create_method_run(conn, run_id=run_live, method_id=method["id"], user_id=uid,
                         puppet_id=None, space_id=None,
                         state={"spec": method, "current": sid,
                                "step_status": {sid: "active"}, "attempts": {},
                                "skipped": [], "evidence": {}, "free_notes": [],
                                "lang": "es"},
                         status="active")
    r = client.post(f"/v1/runs/{run_live}/method/pause", headers=auth)
    check("3a pause en run vivo → control.pause",
          r.status_code == 200 and mr.read_control(conn, run_live).get("pause") is True,
          r.text[:150])
    r = client.post(f"/v1/runs/{run_live}/method/pause", headers=auth_other)
    check("3b pause ajeno → 404 indistinguible", r.status_code == 404)
    r = client.post(f"/v1/runs/{run_live}/method/remedy",
                    json={"action": "banana"}, headers=auth)
    check("3c action inválida → 422", r.status_code == 422)
    r = client.post(f"/v1/runs/{run_live}/method/remedy",
                    json={"action": "retry", "step_id": sid}, headers=auth)
    check("3d remedy en vivo → control.remedy",
          r.status_code == 200 and
          (mr.read_control(conn, run_live).get("remedy") or {}).get("action") == "retry")
    edited = dict(method)
    edited["steps"] = method["steps"] + [{"text": "paso nuevo"}]
    r = client.post(f"/v1/runs/{run_live}/method/resume",
                    json={"method": edited}, headers=auth)
    lib = mr.get_method(conn, method["id"], uid)
    check("3e resume vivo con método editado → control.resume_spec + biblioteca actualizada",
          r.status_code == 200 and mr.read_control(conn, run_live).get("resume") is True
          and len(lib["steps"]) == 2, r.text[:200])

    # ── 4 · CONTINUACIÓN de un run cortado (inline por PUPPET_METHOD_SYNC_RESUME) ──
    print("── 4 · continuación server-side (run cortado en fallo → remedy retry) ──")
    ex_mod = executor._asm()
    _orig_route = ex_mod._route_chat
    ex_mod._route_chat = scripted_route([("add", {"a": 20, "b": 22})])
    try:
        puppet = repo.create_puppet(conn, owner_id=uid, name="agente-ctl",
                                    nicho="test", config=RECIPE)
        conn.commit()
        m2 = mr.create_method(conn, user_id=uid, method=mr.normalize_method({
            "name": "M continuación",
            "steps": [{"text": "sumar", "executor": "calc"},
                      {"text": "concluir"}]}))
        s1, s2 = (s["id"] for s in m2["steps"])
        with conn.cursor() as cur:
            cur.execute("INSERT INTO runs (puppet_id, user_id, space_id, intent, status, finished_at) "
                        "VALUES (%s,%s,%s,%s,'error',now()) RETURNING id",
                        (str(puppet["id"]), uid, "sp-metodo-ctl", "sumá 20 y 22 y concluí"))
            run_dead = str(cur.fetchone()[0])
        conn.commit()
        (events_root / "sp-metodo-ctl").mkdir(parents=True, exist_ok=True)
        mr.create_method_run(conn, run_id=run_dead, method_id=m2["id"], user_id=uid,
                             puppet_id=str(puppet["id"]), space_id="sp-metodo-ctl",
                             state={"spec": m2, "current": s1,
                                    "step_status": {s1: "failed", s2: "pending"},
                                    "attempts": {s1: 3}, "skipped": [], "evidence": {},
                                    "free_notes": [], "lang": "es"},
                             status="paused_failure")
        r = client.post(f"/v1/runs/{run_dead}/method/remedy",
                        json={"action": "retry", "step_id": s1}, headers=auth)
        check("4a remedy retry sobre run cortado → continuación", r.status_code == 200
              and r.json().get("resumed") == "continuation", r.text[:200])
        old = mr.get_method_run(conn, run_dead)
        check("4b el method_run viejo queda sellado 'abandoned' (auditoría)",
              old["status"] == "abandoned")
        with conn.cursor() as cur:
            cur.execute("SELECT run_id, status, state FROM method_runs "
                        "WHERE method_id = %s AND run_id != %s "
                        "ORDER BY created_at DESC LIMIT 1", (m2["id"], run_dead))
            row = cur.fetchone()
        check("4c la continuación corrió y COMPLETÓ con evidencia real",
              row is not None and row[1] == "completed",
              f"status={row and row[1]}")
        st = row[2] if row else {}
        check("4d los intentos del paso trabado arrancaron en cero (remedy aplicado)",
              (st.get("step_status") or {}).get(s1) == "done")
        ev_path = events_root / "sp-metodo-ctl" / "events.jsonl"
        ev_types = [json.loads(l).get("type") for l in
                    ev_path.read_text().splitlines()] if ev_path.exists() else []
        check("4e la continuación narró por el MISMO space (method_started + step_done)",
              "method_started" in ev_types and "method_step_done" in ev_types,
              str(ev_types[:10]))

        # resume de un método SIN puppet guardado → 409 honesto
        with conn.cursor() as cur:
            cur.execute("INSERT INTO runs (user_id, intent, status, finished_at) "
                        "VALUES (%s,%s,'error',now()) RETURNING id", (uid, "x"))
            run_dead2 = str(cur.fetchone()[0])
        conn.commit()
        mr.create_method_run(conn, run_id=run_dead2, method_id=m2["id"], user_id=uid,
                             puppet_id=None, space_id=None,
                             state={"spec": m2, "current": s1,
                                    "step_status": {s1: "active", s2: "pending"},
                                    "attempts": {}, "skipped": [], "evidence": {},
                                    "free_notes": [], "lang": "es"},
                             status="paused_user")
        r = client.post(f"/v1/runs/{run_dead2}/method/resume", json={}, headers=auth)
        check("4f resume sin agente guardado → 409 honesto", r.status_code == 409
              and r.json()["detail"]["error"] == "resume_requires_saved_agent")

        # 4g · DOBLE CONTINUACIÓN (H2 del arnés): dos claims sobre el mismo run cortado →
        # solo UNO gana; el segundo 409 already_resumed (no dos threads/dos efectos).
        with conn.cursor() as cur:
            cur.execute("INSERT INTO runs (puppet_id, user_id, space_id, intent, status, finished_at) "
                        "VALUES (%s,%s,%s,%s,'error',now()) RETURNING id",
                        (str(puppet["id"]), uid, "sp-metodo-ctl", "doble"))
            run_race = str(cur.fetchone()[0])
        conn.commit()
        mr.create_method_run(conn, run_id=run_race, method_id=m2["id"], user_id=uid,
                             puppet_id=str(puppet["id"]), space_id="sp-metodo-ctl",
                             state={"spec": m2, "current": s1,
                                    "step_status": {s1: "failed", s2: "pending"},
                                    "attempts": {s1: 3}, "skipped": [], "evidence": {},
                                    "free_notes": [], "lang": "es"},
                             status="paused_failure")
        won = mr.claim_continuation(conn, run_race, list(
            ("paused_user", "waiting_checkpoint", "paused_failure", "scheduled_retry")))
        won2 = mr.claim_continuation(conn, run_race, list(
            ("paused_user", "waiting_checkpoint", "paused_failure", "scheduled_retry")))
        check("4g claim atómico: el 1ro gana, el 2do pierde (anti-doble-continuación)",
              won is True and won2 is False)
        check("4g2 el claim también limpió el control", mr.read_control(conn, run_race) == {})

        # 4h · pop_control ATÓMICO: lee y limpia en una sentencia
        mr.update_method_run(conn, run_race, control_merge={"remedy": {"action": "retry"}})
        popped = mr.pop_control(conn, run_race)
        check("4h pop_control devuelve el control viejo y lo limpia",
              (popped.get("remedy") or {}).get("action") == "retry"
              and mr.read_control(conn, run_race) == {})
    finally:
        ex_mod._route_chat = _orig_route

    # ── 5 · ticket 10 · pausa RETOMABLE 'paused_incomplete' (no 'abandoned') + retoma por space ──
    print("── 5 · ticket 10 · método a mitad → paused_incomplete (retomable) + resume por space ──")
    _mh_mod = executor._method_harness_mod()
    # 5a · UNIT del arnés: finish() con un paso sin settlear (sin flags de espera) sella
    #      'paused_incomplete', NO 'abandoned'; control: método completo sigue → 'completed'.
    _h = _mh_mod.MethodHarness({"name": "m5u", "steps": [{"id": "x1", "text": "paso a mitad"}]})
    _h.start()
    _fin = _h.finish()
    check("5a finish() con paso a mitad → 'paused_incomplete' (no 'abandoned')",
          _fin["status"] == "paused_incomplete", f"status={_fin['status']}")
    check("5a2 'paused_incomplete' ∈ _RESUMABLE del arnés",
          "paused_incomplete" in _mh_mod.MethodHarness._RESUMABLE)
    _hc = _mh_mod.MethodHarness({"name": "mcp", "steps": [{"id": "y1", "text": "p"}]})
    _hc.state["step_status"]["y1"] = "done"
    check("5a3 control: método completo sigue → 'completed' (rama intacta)",
          _hc.finish()["status"] == "completed")

    # 5b · Llave B (migración 0013): method_runs ACEPTA y persiste status='paused_incomplete'.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (user_id, intent) VALUES (%s,%s) RETURNING id", (uid, "pi-constraint"))
        run_pi = str(cur.fetchone()[0])
    conn.commit()
    mr.create_method_run(conn, run_id=run_pi, method_id=method["id"], user_id=uid,
                         puppet_id=None, space_id=None,
                         state={"spec": method, "current": sid, "step_status": {sid: "active"},
                                "attempts": {}, "skipped": [], "evidence": {}, "free_notes": [], "lang": "es"},
                         status="paused_incomplete")
    check("5b Llave B · method_runs persiste 'paused_incomplete' (constraint 0013)",
          mr.get_method_run(conn, run_pi)["status"] == "paused_incomplete")

    # 5c/5d · run REAL a mitad → paused_incomplete en DB (Llave B fuerte), luego RESUME por space
    #         FRESCO (retoma desde la Sala): la continuación revive el arnés desde el paso pausado.
    _orig_route5 = ex_mod._route_chat
    ex_mod._route_chat = scripted_route([])   # texto sin tool → el paso con executor jamás junta evidencia
    try:
        rcp5 = json.loads(json.dumps(RECIPE)); rcp5["model"]["max_turns"] = 1
        pup5 = repo.create_puppet(conn, owner_id=uid, name="agente-pi", nicho="test", config=rcp5)
        conn.commit()
        m5 = mr.create_method(conn, user_id=uid, method=mr.normalize_method({
            "name": "M inspeccion", "steps": [
                {"text": "registrar la medicion con la herramienta", "executor": "calc"},
                {"text": "concluir el informe"}]}))
        p5s1 = m5["steps"][0]["id"]
        (events_root / "sp-pi").mkdir(parents=True, exist_ok=True)
        c5 = repo.get_conn()
        try:
            out5 = executor.run_puppet_e2e(rcp5, "registra la inspeccion",
                                           puppet_id=str(pup5["id"]), user_id=uid,
                                           space_id="sp-pi", conn=c5, method_id=m5["id"],
                                           deadline_s=60.0, approve=lambda *_a, **_k: False)
        finally:
            c5.close()
        run5 = out5.get("run_id")
        conn.commit()   # snapshot fresco para ver lo que el run commiteó
        mrun5 = mr.get_method_run(conn, run5) if run5 else None
        check("5c run REAL a mitad → method_runs.status='paused_incomplete' (no 'abandoned')",
              bool(mrun5) and mrun5["status"] == "paused_incomplete",
              f"status={mrun5 and mrun5['status']}")
        check("5c2 out.method.status = paused_incomplete (surface al front, gatilla la card de la Sala)",
              (out5.get("method") or {}).get("status") == "paused_incomplete",
              json.dumps(out5.get("method"), default=str)[:140])

        # 5d · RESUME por space OVERRIDE (retoma-Sala): NO 409 (antes paused_incomplete no resumía),
        #      continuación sembrada desde el paso pausado, viejo sellado, narra por el space FRESCO.
        ex_mod._route_chat = scripted_route([("add", {"a": 20, "b": 22})])   # ahora la tool sí → progresa
        (events_root / "sp-pi-resume").mkdir(parents=True, exist_ok=True)
        r = client.post(f"/v1/runs/{run5}/method/resume", json={"space": "sp-pi-resume"}, headers=auth)
        check("5d resume de paused_incomplete → 200 + continuación (NO 409 dead-end)",
              r.status_code == 200 and r.json().get("resumed") == "continuation", r.text[:180])
        conn.commit()
        check("5d2 el run viejo quedó sellado 'abandoned' por el claim (auditoría)",
              (mr.get_method_run(conn, run5) or {}).get("status") == "abandoned")
        with conn.cursor() as cur:
            cur.execute("SELECT status, state FROM method_runs WHERE method_id=%s AND run_id!=%s "
                        "ORDER BY created_at DESC LIMIT 1", (m5["id"], run5))
            cont = cur.fetchone()
        check("5d3 la continuación corrió sembrada desde el paso pausado y PROGRESÓ (paso 1 done)",
              cont is not None and cont[0] in ("completed", "paused_incomplete")
              and (cont[1].get("step_status") or {}).get(p5s1) == "done",
              f"status={cont and cont[0]}")
        ev_ov = events_root / "sp-pi-resume" / "events.jsonl"
        ev_ov_types = [json.loads(l).get("type") for l in ev_ov.read_text().splitlines()] if ev_ov.exists() else []
        check("5d4 la continuación narró por el space OVERRIDE (sp-pi-resume), no el del run viejo",
              "method_started" in ev_ov_types, str(ev_ov_types[:8]))
    finally:
        ex_mod._route_chat = _orig_route5

    # limpieza
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id IN (%s,%s)", (uid, str(other["id"])))
    conn.commit()
    conn.close()

    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
