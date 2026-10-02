#!/usr/bin/env python3
"""test_method_brain.py — cerebro de la pieza MÉTODO: structure / propose_edit /
from_run / match / adjust_permanent.

Doctrina de la casa: la ÚNICA pieza guionable es la COGNICIÓN (_call_brain
scripteado, patrón scripted_route de verify_gate_a2) — parseo, validación
semántica, normalización, DB, router y eventos son SIEMPRE los reales. El
camino con Opus vivo se certifica en qa/verify_metodo_backend.py (best-effort).

Corre:  cd product/backend && PYTHONPATH=. .venv/bin/python app/phase1/test_method_brain.py
Requisitos: Postgres puppet_ai vivo para la sección router (skip honesto si no).
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import method_brain as mb  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
    return cond


def scripted_brain(payloads):
    """Cognición GUIONADA: devuelve los contenidos de `payloads` en orden."""
    seq = list(payloads)

    def fake(messages, *, max_tokens=1600):
        content = seq.pop(0) if seq else seq_last[0]
        seq_last[0] = content
        return content, "scripted-brain"
    seq_last = [payloads[-1] if payloads else ""]
    return fake


def test_parse_json():
    check("json con fences", mb._parse_json("```json\n{\"a\": 1}\n```") == {"a": 1})
    check("json con prosa alrededor",
          mb._parse_json("claro, acá va:\n{\"a\": 2}\ngracias") == {"a": 2})
    check("lista con prosa", mb._parse_json("resultado: [1,2]") == [1, 2])
    check("basura → None", mb._parse_json("no hay json acá") is None)


def test_structure(monkey):
    caps = ["una fuente de filings SEC", "una hoja de cálculo"]
    monkey(mb, "_capability_contract",
           lambda lang: ("estructura + vocabulario 5a", caps))
    monkey(mb, "_call_brain", scripted_brain([json.dumps({
        "name": "Cierre mensual",
        "steps": [{"text": "Conciliar cuentas", "phase": "Preparar"},
                  {"text": "Aprobar el cierre", "phase": "Cerrar", "checkpoint": True},
                  {"text": "", "phase": "X"}],
        "requires": ["una hoja de cálculo"],
    })]))
    d = mb.structure_draft(text="mi SOP de cierre: conciliar, aprobar")
    check("structure: draft normalizado sin id", "id" not in d and d["name"] == "Cierre mensual")
    check("structure: paso vacío dropeado", len(d["steps"]) == 2)
    check("structure: checkpoint sobrevive", d["steps"][1]["checkpoint"] is True)
    check("structure: source.kind", d.get("source", {}).get("kind") == "structure")
    check("structure: requires[] sale en el mismo pase y canónico",
          d.get("requires") == ["una hoja de cálculo"])

    monkey(mb, "_call_brain", scripted_brain(["no puedo con esto"]))
    try:
        mb.structure_draft(text="algo")
        check("structure: respuesta no-JSON → brain_invalid", False)
    except mb.MethodBrainError as e:
        check("structure: respuesta no-JSON → brain_invalid", e.kind == "brain_invalid")

    monkey(mb, "_call_brain", scripted_brain([
        json.dumps({"name": "X", "steps": [], "requires": []})]))
    try:
        mb.structure_draft(text="algo")
        check("structure: cero pasos → brain_invalid", False)
    except mb.MethodBrainError as e:
        check("structure: cero pasos → brain_invalid", e.kind == "brain_invalid")

    try:
        mb.structure_draft()
        check("structure: sin material → doc_invalid", False)
    except mb.MethodBrainError as e:
        check("structure: sin material → doc_invalid", e.kind == "doc_invalid")

    try:
        mb.structure_draft(data_b64="@@no-es-b64@@", mime="application/pdf")
        check("structure: b64 inválido → doc_invalid", False)
    except mb.MethodBrainError as e:
        check("structure: b64 inválido → doc_invalid", e.kind == "doc_invalid")

    # imagen: el content del user debe llevar la data-URL (multimodal RAW)
    seen = {}

    def spy(messages, *, max_tokens=1600):
        seen["user"] = messages[-1]["content"]
        return json.dumps({"name": "De imagen", "steps": [{"text": "p1"}],
                           "requires": []}), "spy"
    monkey(mb, "_call_brain", spy)
    img64 = base64.b64encode(b"\x89PNG fake").decode()
    d = mb.structure_draft(data_b64=img64, mime="image/png")
    parts = seen["user"]
    check("structure imagen: viaja como data-URL multimodal",
          isinstance(parts, list) and any(
              p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,")
              for p in parts))

    monkey(mb, "_call_brain", scripted_brain([json.dumps({
        "name": "Marca prohibida", "steps": [{"text": "Buscar"}],
        "requires": ["EDGAR"],
    })]))
    try:
        mb.structure_draft(text="buscar filings")
        check("capacidad inventada/marca jamás pasa el vocabulario", False)
    except mb.MethodBrainError as e:
        check("capacidad inventada/marca jamás pasa el vocabulario",
              e.kind == "brain_invalid" and "EDGAR" in e.detail)

    monkey(mb, "_call_brain", scripted_brain([
        json.dumps({"requires": ["una fuente de filings SEC"]})]))
    req = mb.extract_requires({"name": "legado", "steps": [{"text": "Bajar 10-Q"}]})
    check("backfill legado extrae requires[] canónico una vez",
          req == ["una fuente de filings SEC"])


def test_propose_edit(monkey):
    method = {"name": "M", "steps": [
        {"id": "s-aaaa1111", "text": "paso uno"},
        {"id": "s-bbbb2222", "text": "paso dos"},
    ]}
    monkey(mb, "_call_brain", scripted_brain([json.dumps({
        "summary": "agregué la validación del RUC",
        "steps": [{"id": "s-aaaa1111", "text": "paso uno"},
                  {"text": "validar el RUC"},
                  {"id": "s-inventado", "text": "paso dos editado"},
                  {"id": "s-aaaa1111", "text": "duplicado malicioso"}],
    })]))
    out = mb.propose_edit(method, "agregá un paso que valide el RUC antes")
    check("propose: summary presente", out["summary"].startswith("agregué"))
    ids = [s["id"] for s in out["steps"]]
    check("propose: id conocido preservado", ids[0] == "s-aaaa1111")
    check("propose: paso nuevo gana id fresco", ids[1] not in ("s-aaaa1111", "s-bbbb2222"))
    check("propose: id alucinado re-acuñado", ids[2] != "s-inventado")
    check("propose: id duplicado re-acuñado (no roba identidad)", ids[3] != "s-aaaa1111")

    monkey(mb, "_call_brain", scripted_brain([json.dumps({"error": "no aplica"})]))
    try:
        mb.propose_edit(method, "hacé algo imposible")
        check("propose: error del cerebro → brain_invalid", False)
    except mb.MethodBrainError as e:
        check("propose: error del cerebro → brain_invalid", e.kind == "brain_invalid")

    monkey(mb, "_call_brain", scripted_brain([json.dumps({"summary": "x", "steps": []})]))
    try:
        mb.propose_edit(method, "borrá todo")
        check("propose: propuesta vacía rechazada ('borrá todo' lavado)", False)
    except mb.MethodBrainError as e:
        check("propose: propuesta vacía rechazada ('borrá todo' lavado)",
              e.kind == "brain_invalid")

    try:
        mb.propose_edit(method, "   ")
        check("propose: instrucción vacía → brain_invalid sin llamar al cerebro", False)
    except mb.MethodBrainError as e:
        check("propose: instrucción vacía → brain_invalid sin llamar al cerebro",
              e.kind == "brain_invalid")


def test_freeze_from_run():
    rid = str(uuid.uuid4())
    evs = [
        {"type": "plan_declared", "run_id": rid,
         "steps": [{"paso": "Bajar datos", "tool": "sec-edgar"},
                   {"paso": "Analizar márgenes"}]},
        {"type": "tool_call_finished", "run_id": rid, "status": "ok",
         "tool": "sec-edgar", "result": "{...}"},
    ]
    d = mb.freeze_from_run(evs, run_id=rid, intent="análisis 10-Q")
    check("from_run: plan_declared manda", len(d["steps"]) == 2
          and d["steps"][0]["text"] == "Bajar datos"
          and d["steps"][0]["executor"] == "sec-edgar")
    check("from_run: nombre desde el intent", "análisis 10-Q" in d["name"])
    check("from_run: source.run_id", d["source"]["run_id"] == rid)

    evs2 = [
        {"type": "tool_call_finished", "run_id": rid, "status": "ok",
         "tool": "calc", "result": "42"},
        {"type": "tool_call_finished", "run_id": rid, "status": "ok",
         "tool": "calc", "result": "43"},
        {"type": "tool_call_finished", "run_id": rid, "status": "ok",
         "tool": "rota", "result": "[MCP error: no response from rota]"},
        {"type": "tool_call_finished", "run_id": rid, "status": "ok",
         "tool": "mail", "result": "enviado"},
        {"type": "tool_call_finished", "run_id": str(uuid.uuid4()), "status": "ok",
         "tool": "otro-run", "result": "x"},
    ]
    d2 = mb.freeze_from_run(evs2, run_id=rid, intent=None)
    tools = [s["executor"] for s in d2["steps"]]
    check("from_run sin plan: tools reales, dedupe consecutivo, sin errores, sin cruce de runs",
          tools == ["calc", "mail"], str(tools))

    try:
        mb.freeze_from_run([], run_id=rid, intent=None)
        check("from_run: run sin material → error honesto", False)
    except mb.MethodBrainError as e:
        check("from_run: run sin material → error honesto", e.kind == "run_sin_material")


def test_router(monkey):
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
    except Exception as e:
        print(f"  [SKIP] DB no disponible ({e}) — sección router no probada")
        return
    import tempfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.methods_router import build_methods_router

    events_root = Path(tempfile.mkdtemp(prefix="metodo-events-"))
    app = FastAPI()
    app.include_router(build_methods_router(get_conn=repo.get_conn,
                                            events_dir=lambda: events_root))
    client = TestClient(app)

    u = repo.get_or_create_user(conn, email=f"metodo-brain-{uuid.uuid4().hex[:8]}@test.local")
    conn.commit()
    auth = {"Authorization": "Bearer " + repo.mint_session(u["id"])}

    # structure por HTTP con cerebro guionado
    monkey(mb, "_call_brain", scripted_brain([json.dumps(
        {"name": "HTTP método", "steps": [{"text": "p1", "phase": "F"}],
         "requires": []})]))
    r = client.post("/v1/methods/structure", json={"text": "mi proceso"}, headers=auth)
    check("HTTP structure → {draft}", r.status_code == 200
          and r.json()["draft"]["name"] == "HTTP método", r.text[:200])

    monkey(mb, "_call_brain", scripted_brain(["basura sin json"]))
    r = client.post("/v1/methods/structure", json={"text": "x"}, headers=auth)
    check("HTTP structure cerebro roto → 502 tipado", r.status_code == 502
          and r.json()["detail"]["error"] == "brain_invalid")

    # match end-to-end: puppet real + método equipado
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "agente-match", "nicho": "general"},
        "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0, "max_tokens": 1024, "max_turns": 6},
        "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
                 "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "test"}, "rag": {"enabled": False},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    puppet = repo.create_puppet(conn, owner_id=u["id"], name="agente-match",
                                nicho="general", config=recipe)
    conn.commit()
    pid = str(puppet["id"])
    m = client.post("/v1/methods", json={
        "name": "Análisis de earnings",
        "steps": [{"text": "Bajar el 10-Q"}, {"text": "Comparar márgenes"}],
        "requires": [],
    }, headers=auth).json()
    client.post(f"/v1/puppets/{pid}/methods", json={"method_id": m["id"]}, headers=auth)

    r = client.post("/v1/methods/match",
                    json={"puppet_id": pid, "prompt": "hazme el análisis de earnings del 10-Q"},
                    headers=auth)
    check("HTTP match: eco → {match:{method_id,name}}", r.status_code == 200
          and (r.json()["match"] or {}).get("method_id") == m["id"], r.text[:200])
    r = client.post("/v1/methods/match",
                    json={"puppet_id": pid, "prompt": "qué hora es"}, headers=auth)
    check("HTTP match: sin eco → null", r.json()["match"] is None)
    r = client.post("/v1/methods/match",
                    json={"puppet_id": "cuarto-slug-no-guardado", "prompt": "análisis earnings"},
                    headers=auth)
    check("HTTP match: puppet no guardado → null (fail-open, no 404)",
          r.status_code == 200 and r.json()["match"] is None)

    # from_run: run real + events.jsonl con plan
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (user_id, space_id, intent) VALUES (%s,%s,%s) RETURNING id",
                    (u["id"], "sp-metodo-test", "cerrar el mes"))
        run_id = str(cur.fetchone()[0])
    conn.commit()
    evdir = events_root / "sp-metodo-test"
    evdir.mkdir(parents=True, exist_ok=True)
    (evdir / "events.jsonl").write_text(json.dumps(
        {"type": "plan_declared", "run_id": run_id, "space_id": "sp-metodo-test",
         "steps": [{"paso": "Conciliar", "tool": "sheets"}, {"paso": "Reportar"}]}) + "\n")
    monkey(mb, "_call_brain", scripted_brain([json.dumps({"requires": []})]))
    r = client.post("/v1/methods/from_run", json={"run_id": run_id}, headers=auth)
    check("HTTP from_run: crea el método desde el plan REAL", r.status_code == 201
          and len(r.json()["method"]["steps"]) == 2, r.text[:300])
    mid_frozen = r.json()["method"]["id"]
    r = client.post("/v1/methods/from_run", json={"run_id": run_id}, headers=auth)
    check("HTTP from_run: idempotente por run_id", r.json()["method"]["id"] == mid_frozen)
    r = client.post("/v1/methods/from_run", json={"run_id": str(uuid.uuid4())}, headers=auth)
    check("HTTP from_run: run ajeno/inexistente → 404", r.status_code == 404)

    # adjust_permanent: cerebro guionado aplica; fallo NO muta
    monkey(mb, "_call_brain", scripted_brain([json.dumps({
        "summary": "sumé validación",
        "steps": [{"text": "Bajar el 10-Q"}, {"text": "Validar el RUC"},
                  {"text": "Comparar márgenes"}]})]))
    r = client.post(f"/v1/methods/{m['id']}/adjust_permanent",
                    json={"adjust": "validá el RUC antes de comparar", "run_id": run_id},
                    headers=auth)
    check("HTTP adjust_permanent: aplica y persiste", r.status_code == 200
          and len(r.json()["method"]["steps"]) == 3
          and r.json()["method"]["adjust_log"][0]["summary"] == "sumé validación",
          r.text[:300])
    monkey(mb, "_call_brain", scripted_brain(["rompido"]))
    before = client.get(f"/v1/methods/{m['id']}", headers=auth).json()["method"]
    r = client.post(f"/v1/methods/{m['id']}/adjust_permanent",
                    json={"adjust": "otra cosa"}, headers=auth)
    after = client.get(f"/v1/methods/{m['id']}", headers=auth).json()["method"]
    check("HTTP adjust_permanent: cerebro roto → 502 y el método NO se toca",
          r.status_code == 502 and before == after)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (u["id"],))
    conn.commit()
    conn.close()


def main() -> int:
    originals = {}

    def monkey(mod, attr, fn):
        originals.setdefault((id(mod), attr), getattr(mod, attr))
        setattr(mod, attr, fn)

    print("— parse robusto —")
    test_parse_json()
    print("— structure (cognición guionada) —")
    test_structure(monkey)
    print("— propose_edit (validación semántica) —")
    test_propose_edit(monkey)
    print("— from_run (determinista) —")
    test_freeze_from_run()
    print("— router HTTP —")
    test_router(monkey)

    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
