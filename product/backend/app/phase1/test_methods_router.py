#!/usr/bin/env python3
"""test_methods_router.py — HTTP de la pieza MÉTODO: CRUD + equipar por REFERENCIA.

Router REAL + Postgres REAL (TestClient solo como transporte — cero mocks de lógica).
Cubre el contrato exacto del frontend (formas de respuesta que metodo.api.js parsea),
anti-IDOR (ajeno == 404 indistinguible), y el candado del checklist §9: equipar es
REFERENCIA, no copia (editar el método NO toca el config del puppet; el archivo del
puente D3 lleva el ref verbatim, jamás el objeto).

Corre:  cd product/backend && PYTHONPATH=. .venv/bin/python app/phase1/test_methods_router.py
Requisitos: Postgres puppet_ai vivo (skip honesto si no).
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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


def main() -> int:
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
        conn.close()
    except Exception as e:
        print(f"[SKIP] DB no disponible ({e})")
        return 0

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.methods_router import build_methods_router

    app = FastAPI()
    app.include_router(build_methods_router(get_conn=repo.get_conn))
    client = TestClient(app)

    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, email=f"metodo-router-{uuid.uuid4().hex[:8]}@test.local")
    other = repo.get_or_create_user(conn, email=f"metodo-intruso-{uuid.uuid4().hex[:8]}@test.local")
    conn.commit()
    auth = {"Authorization": "Bearer " + repo.mint_session(u["id"])}
    auth_other = {"Authorization": "Bearer " + repo.mint_session(other["id"])}

    METHOD = {"name": "Earnings semanal", "phases": ["Investigar"], "custom": {"k": 1},
              "requires": [],
              "steps": [{"text": "Bajar el 10-Q", "phase": "Investigar"},
                        {"text": "Comparar márgenes YoY", "checkpoint": True}]}

    print("— CRUD /v1/methods —")
    r = client.get("/v1/methods")
    check("sin sesión → 401 no_session", r.status_code == 401
          and r.json()["detail"]["error"] == "no_session")

    r = client.post("/v1/methods", json=METHOD, headers=auth)
    check("POST crea 201 con id", r.status_code == 201 and bool(r.json().get("id")),
          f"{r.status_code} {r.text[:200]}")
    mid = r.json()["id"]
    check("POST preserva extras + phases[]", r.json().get("custom") == {"k": 1}
          and r.json().get("phases") == ["Investigar"])

    r = client.post("/v1/methods", json={"name": "", "steps": [], "requires": []}, headers=auth)
    check("POST inválido → 422 method_invalid", r.status_code == 422
          and r.json()["detail"]["error"] == "method_invalid")

    r = client.get("/v1/methods", headers=auth)
    check("GET lista {methods:[...]}", r.status_code == 200
          and len(r.json()["methods"]) == 1)

    r = client.get(f"/v1/methods/{mid}", headers=auth)
    check("GET uno {method:{...}}", r.status_code == 200
          and r.json()["method"]["id"] == mid)

    r = client.get(f"/v1/methods/{mid}", headers=auth_other)
    check("GET ajeno → 404 (anti-IDOR indistinguible)", r.status_code == 404)
    r = client.get("/v1/methods/no-es-uuid", headers=auth)
    check("uuid malformado → 404, jamás 500", r.status_code == 404)

    got = client.get(f"/v1/methods/{mid}", headers=auth).json()["method"]
    got["name"] = "Earnings v2"
    r = client.put(f"/v1/methods/{mid}", json=got, headers=auth)
    check("PUT round-trip (objeto entero con server keys)", r.status_code == 200
          and r.json()["name"] == "Earnings v2")
    r = client.put(f"/v1/methods/{mid}", json=got, headers=auth_other)
    check("PUT ajeno → 404", r.status_code == 404)

    print("— equipar por referencia —")
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "agente-metodo-test", "nicho": "general"},
        "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0, "max_tokens": 1024, "max_turns": 6},
        "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
                 "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "agente de prueba"},
        "rag": {"enabled": False},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    conn2 = repo.get_conn()
    puppet = repo.create_puppet(conn2, owner_id=u["id"], name="agente-metodo-test",
                                nicho="general", config=recipe)
    conn2.commit()
    pid = str(puppet["id"])

    r = client.get(f"/v1/puppets/{pid}/methods", headers=auth)
    check("GET equipados vacío", r.status_code == 200 and r.json()["methods"] == [])

    r = client.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    check("POST equipa 201", r.status_code == 201 and r.json()["equipped"] == [mid],
          f"{r.status_code} {r.text[:300]}")
    r = client.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    check("re-equipar es idempotente", r.status_code == 201 and r.json()["equipped"] == [mid])

    r = client.post(f"/v1/puppets/{pid}/methods",
                    json={"method_id": str(uuid.uuid4())}, headers=auth)
    check("equipar método inexistente → 404", r.status_code == 404)
    r = client.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth_other)
    check("equipar en puppet ajeno → 404", r.status_code == 404)

    cfg = repo.get_puppet(conn2, pid)["config"]
    check("la referencia vive en belt.method_refs[]",
          cfg["belt"].get("method_refs") == [mid])
    check("REFERENCIA, no copia: el objeto Method NO está en el config",
          "steps" not in json.dumps(cfg))

    bridge = _REPO / "catalog" / "agents" / f"agent-{pid}.config.json"
    if bridge.exists():
        child = json.loads(bridge.read_text())
        check("puente D3 re-exportado con el ref verbatim (herencia gratis)",
              child.get("belt", {}).get("method_refs") == [mid])
        check("puente NO embebe el objeto (referencia)", "steps" not in json.dumps(child))
    else:
        check("puente D3 re-exportado con el ref verbatim (herencia gratis)", False,
              f"no existe {bridge}")

    # editar el método en la biblioteca NO toca el config del puppet (candado §9)
    got["name"] = "Earnings v3"
    client.put(f"/v1/methods/{mid}", json=got, headers=auth)
    cfg2 = repo.get_puppet(conn2, pid)["config"]
    check("editar el método NO muta el config del puppet (referencia viva)",
          cfg2 == cfg)
    r = client.get(f"/v1/puppets/{pid}/methods", headers=auth)
    check("el equipado ve la versión NUEVA al resolver",
          r.json()["methods"][0]["name"] == "Earnings v3")

    r = client.get(f"/v1/puppets/{pid}/methods", headers=auth_other)
    check("GET equipados de puppet ajeno → 404", r.status_code == 404)

    r = client.delete(f"/v1/puppets/{pid}/methods/{mid}", headers=auth)
    check("DELETE desequipa", r.status_code == 200 and r.json()["equipped"] == [])
    cfg3 = repo.get_puppet(conn2, pid)["config"]
    check("sin métodos, la clave desaparece (receta byte-idéntica)",
          "method_refs" not in cfg3["belt"])
    r = client.delete(f"/v1/puppets/{pid}/methods/{mid}", headers=auth)
    check("desequipar lo no-equipado → 404", r.status_code == 404)

    # ref colgante: equipar y borrar el método → GET reporta missing honesto
    client.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    client.delete(f"/v1/methods/{mid}", headers=auth)
    r = client.get(f"/v1/puppets/{pid}/methods", headers=auth)
    check("método borrado → ref colgante reportada en missing[]",
          r.status_code == 200 and r.json().get("missing") == [mid]
          and r.json()["methods"] == [])

    # limpieza
    with conn2.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (u["id"], other["id"]))
    conn2.commit()
    conn2.close()
    conn.close()
    try:
        bridge.unlink(missing_ok=True)
    except Exception:
        pass

    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
