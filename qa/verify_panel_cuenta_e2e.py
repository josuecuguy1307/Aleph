"""ORDEN 6 · Panel VER + PODAR de la MEMORIA DE CUENTA — anti-IDOR/cross-user (probado, no razonado).

Las 2 rutas nuevas del panel, contra la MISMA vara que el orden 5: HTTP real (TestClient) + Postgres
real + tokens de sesión de DOS usuarios distintos. El invariante #4 (la cuenta jamás cruza de
usuario) se PRUEBA, no se razona:

  1. VER (GET /v1/account/memories) sólo devuelve los hechos ACTIVOS (pinned=TRUE) del DUEÑO de la
     sesión — nunca los de otro usuario; trae source/meta para el badge kind/prov.
  2. anti-IDOR PODAR (DELETE /v1/account/memories/{id}) — el token de B NO puede borrar el hecho de
     A: 404 y el hecho de A SIGUE VIVO. El 404 es INDISTINGUIBLE del de un id inexistente (sin
     oráculo de existencia cross-user).
  3. PODAR lo PROPIO funciona (A borra su hecho → 200 → desaparece de su VER).
  4. UUID malformado → 404 (jamás 500 / DataError).
  5. sin sesión → 401 en ambas rutas.
  6. una propuesta INERTE (pinned=FALSE, orden 5) NO aparece en VER (que es sólo lo activo).

Correr:  cd product/backend && set -a && . ../../infra/.env && set +a && \
         ./.venv/bin/python ../../qa/verify_panel_cuenta_e2e.py
"""
from __future__ import annotations
import os, sys, uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
for p in (str(_REPO / "platform"), str(_REPO / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import repo  # noqa: E402
from app.phase1.account_router import build_account_router  # noqa: E402

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond: _fail.append(label)

from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

app = FastAPI()
app.include_router(build_account_router(get_conn=repo.get_conn))
client = TestClient(app, raise_server_exceptions=False)   # 500 → respuesta, no excepción (así lo cazamos)

conn = repo.get_conn()
uA = repo.get_or_create_user(conn, f"panel-A-{uuid.uuid4().hex[:8]}@test.local", tier="tecnico")["id"]
uB = repo.get_or_create_user(conn, f"panel-B-{uuid.uuid4().hex[:8]}@test.local", tier="tecnico")["id"]
tokA = {"Authorization": f"Bearer {repo.mint_session(uA)}"}
tokB = {"Authorization": f"Bearer {repo.mint_session(uB)}"}
repo.clear_account_memories(conn, uA)
repo.clear_account_memories(conn, uB)

try:
    # ── setup: A tiene 2 hechos ACTIVOS (uno directo del usuario, uno propuesto-por-agente-confirmado)
    #           + 1 propuesta INERTE; B tiene 1 hecho activo propio.
    mA_user = repo.add_account_memory(conn, owner_id=uA, content="El usuario vive en Quito",
                                      source="user", pinned=True, meta={"provenance": "hecho"})
    # un hecho de origen AGENTE: propuesta inerte → confirmada (así el badge distingue prov)
    prop = repo.add_account_proposal(conn, owner_id=uA, content="Prefiere reportes cortos",
                                     run_id="run-xyz", provenance="hecho")
    repo.confirm_account_proposal(conn, prop["id"], uA)
    # una propuesta que queda INERTE (no debe aparecer en VER)
    prop_inert = repo.add_account_proposal(conn, owner_id=uA, content="Trabaja de noche",
                                           run_id="run-abc", provenance="inferencia")
    mB = repo.add_account_memory(conn, owner_id=uB, content="B vive en Lima",
                                 source="user", pinned=True)

    print("== 1 · VER · GET /v1/account/memories devuelve SÓLO lo activo del dueño de la sesión ==")
    rA = client.get("/v1/account/memories", headers=tokA)
    bodyA = rA.json() if rA.status_code == 200 else {}
    memsA = bodyA.get("memories", [])
    idsA = {m["id"] for m in memsA}
    contentsA = " || ".join(m.get("content", "") for m in memsA)
    ok(rA.status_code == 200, "GET 200 con sesión")
    ok(mA_user["id"] in idsA and prop["id"] in idsA, "trae los 2 hechos ACTIVOS de A")
    ok(prop_inert["id"] not in idsA, "NO trae la propuesta INERTE (pinned=FALSE) — VER es sólo lo activo")
    ok("Lima" not in contentsA and mB["id"] not in idsA, "NO trae NADA de B (cross-user)")
    # kind/prov visible para el badge: source + meta presentes
    byid = {m["id"]: m for m in memsA}
    ok(byid.get(mA_user["id"], {}).get("source") == "user", "badge prov: el hecho directo tiene source='user'")
    ok(byid.get(prop["id"], {}).get("source") == "agent", "badge prov: el confirmado tiene source='agent'")
    ok("meta" in (byid.get(mA_user["id"]) or {}), "cada fila trae meta (kind/prov para el badge)")
    ok(isinstance(bodyA.get("usage"), dict) and "entries" in bodyA["usage"], "trae usage (cap del panel)")

    # B ve lo SUYO y sólo lo suyo (espejo del cross-user)
    rB = client.get("/v1/account/memories", headers=tokB)
    idsB = {m["id"] for m in (rB.json().get("memories", []) if rB.status_code == 200 else [])}
    ok(rB.status_code == 200 and mB["id"] in idsB and mA_user["id"] not in idsB,
       "B ve lo suyo y NADA de A (aislamiento simétrico)")

    print("== 2 · anti-IDOR PODAR · B NO puede borrar el hecho de A ==")
    rdel_idor = client.delete(f"/v1/account/memories/{mA_user['id']}", headers=tokB)
    still = repo.get_account_memory(conn, mA_user["id"])
    ok(rdel_idor.status_code == 404, "DELETE del hecho de A con token de B → 404")
    ok(still is not None and str(still["owner_id"]) == str(uA), "el hecho de A SIGUE VIVO (no lo borró B)")
    # el 404 debe ser INDISTINGUIBLE del de un id que no existe (sin oráculo de existencia cross-user)
    rdel_ghost = client.delete(f"/v1/account/memories/{uuid.uuid4()}", headers=tokB)
    ok(rdel_ghost.status_code == 404 and rdel_ghost.json() == rdel_idor.json(),
       "404 de 'ajeno' == 404 de 'inexistente' (sin oráculo de existencia)")

    print("== 3 · PODAR lo PROPIO · A borra su hecho ==")
    rdel_own = client.delete(f"/v1/account/memories/{mA_user['id']}", headers=tokA)
    ok(rdel_own.status_code == 200 and rdel_own.json().get("ok") is True, "A borra su hecho → 200 ok")
    ok(repo.get_account_memory(conn, mA_user["id"]) is None, "el hecho quedó efectivamente borrado")
    after = client.get("/v1/account/memories", headers=tokA).json().get("memories", [])
    ok(all(m["id"] != mA_user["id"] for m in after), "ya no aparece en el VER de A")
    ok(any(m["id"] == prop["id"] for m in after), "el OTRO hecho activo de A sigue (borrado quirúrgico, no en masa)")

    print("== 4 · UUID malformado → 404, jamás 500 ==")
    rbad = client.delete("/v1/account/memories/not-a-uuid", headers=tokA)
    ok(rbad.status_code == 404, f"id malformado → 404 (fue {rbad.status_code}, NO 500)")

    print("== 5 · sin sesión → 401 en ambas rutas ==")
    r401g = client.get("/v1/account/memories")
    r401d = client.delete(f"/v1/account/memories/{prop['id']}")
    ok(r401g.status_code == 401, "GET sin token → 401")
    ok(r401d.status_code == 401, "DELETE sin token → 401")
    # y el hecho de A NO se tocó por el intento sin sesión
    ok(repo.get_account_memory(conn, prop["id"]) is not None, "el DELETE sin sesión no borró nada")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    try: repo.clear_account_memories(conn, uA)
    except Exception: pass
    try: repo.clear_account_memories(conn, uB)
    except Exception: pass
    conn.close()
sys.exit(1 if _fail else 0)
