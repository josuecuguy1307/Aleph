"""ORDEN 5 · Evidencia VIVA del gate de propuesta de cuenta contra Postgres real (capa DB).

Doble-llave (probado, no razonado): propuesta nace INERTE (pinned=FALSE → NO la ve la lectura del
framing) · cap anti-spam de pendientes · CONFIRMAR = pinned=TRUE + approved (recién ahí entra a la
lectura) · RECHAZAR borra · anti-IDOR (confirmar/rechazar ajeno no toca nada) · aislamiento cross-user
· UUID guard (id malformado no crashea).

Correr:  cd product/backend && ./.venv/bin/python ../../qa/verify_account_proposal.py
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__)); _ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
from app.phase1 import repo

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond: _fail.append(label)

conn = repo.get_conn()
uA = repo.get_or_create_user(conn, "prop-A@test.local", tier="tecnico")["id"]
uB = repo.get_or_create_user(conn, "prop-B@test.local", tier="tecnico")["id"]
repo.clear_account_memories(conn, uA)
repo.clear_account_memories(conn, uB)

try:
    print("== 1 · la propuesta nace INERTE (pinned=FALSE) y NO entra a la lectura del framing ==")
    p = repo.add_account_proposal(conn, owner_id=uA, content="El usuario vive en Quito",
                                  run_id="run-1", provenance="hecho")
    ok(p and p["pinned"] is False and p["source"] == "agent", "add_account_proposal → source=agent, pinned=FALSE")
    ok((p.get("meta") or {}).get("proposed") is True, "meta.proposed=True")
    framing_read = repo.list_account_memories(conn, uA, pinned_only=True)
    ok(not any("Quito" in x["content"] for x in framing_read),
       "pinned_only=True (lo que lee el run) NO incluye la propuesta inerte")
    pend = repo.list_account_proposals(conn, uA)
    ok(len(pend) == 1 and "Quito" in pend[0]["content"], "list_account_proposals SÍ la muestra (para el panel)")

    print("== 2 · cap anti-spam de pendientes (MAX_PENDING_ACCOUNT_PROPOSALS) ==")
    repo.add_account_proposal(conn, owner_id=uA, content="hecho 2")
    repo.add_account_proposal(conn, owner_id=uA, content="hecho 3")
    over = repo.add_account_proposal(conn, owner_id=uA, content="hecho 4 (excede)")
    ok(over is None, "con 3 pendientes, la 4ta se descarta (None)")
    ok(len(repo.list_account_proposals(conn, uA)) == repo.MAX_PENDING_ACCOUNT_PROPOSALS, "quedan exactamente MAX pendientes")

    print("== 3 · CONFIRMAR = el gate → pinned=TRUE + approved, y RECIÉN AHÍ entra a la lectura ==")
    pid = pend[0]["id"]
    conf = repo.confirm_account_proposal(conn, pid, uA)
    ok(conf and conf["pinned"] is True, "confirmar → pinned=TRUE")
    ok((conf.get("meta") or {}).get("approved") is True, "meta.approved=True (queda la proveniencia source=agent)")
    ok(any("Quito" in x["content"] for x in repo.list_account_memories(conn, uA, pinned_only=True)),
       "el hecho confirmado YA entra a la lectura del framing")
    ok(not any(x["id"] == pid for x in repo.list_account_proposals(conn, uA)),
       "y sale de la lista de pendientes")

    print("== 4 · RECHAZAR borra una propuesta pendiente ==")
    rest = repo.list_account_proposals(conn, uA)
    rid = rest[0]["id"]
    ok(repo.reject_account_proposal(conn, rid, uA) is True, "reject → True (borró)")
    ok(not any(x["id"] == rid for x in repo.list_account_proposals(conn, uA)), "ya no está pendiente")

    print("== 5 · anti-IDOR · confirmar/rechazar la propuesta de OTRO no toca nada ==")
    pb = repo.add_account_proposal(conn, owner_id=uB, content="SECRETO-DE-B: dato privado")
    ok(repo.confirm_account_proposal(conn, pb["id"], uA) is None, "A NO puede confirmar la propuesta de B")
    ok(repo.reject_account_proposal(conn, pb["id"], uA) is False, "A NO puede rechazar la propuesta de B")
    stillB = repo.list_account_proposals(conn, uB)
    ok(len(stillB) == 1 and stillB[0]["pinned"] is False, "la propuesta de B sigue pendiente e intacta")
    ok(not any("SECRETO-DE-B" in x["content"] for x in repo.list_account_proposals(conn, uA)),
       "aislamiento cross-user: A jamás ve la propuesta de B")

    print("== 6 · confirmar/rechazar algo YA confirmado o INEXISTENTE → no-op honesto ==")
    ok(repo.confirm_account_proposal(conn, pid, uA) is None, "re-confirmar (ya pinned) → None")
    ok(repo.reject_account_proposal(conn, pid, uA) is False, "rechazar un confirmado → False (no borra hechos activos)")
    ok(any("Quito" in x["content"] for x in repo.list_account_memories(conn, uA, pinned_only=True)),
       "el hecho confirmado sigue vivo (rechazar no lo tocó)")

    print("== 7 · UUID guard · id malformado no crashea (None/False) ==")
    ok(repo.confirm_account_proposal(conn, "no-es-uuid", uA) is None, "confirm(id malo) → None (sin DataError)")
    ok(repo.reject_account_proposal(conn, "no-es-uuid", uA) is False, "reject(id malo) → False (sin DataError)")
    # la conexión sigue usable tras el id malo
    ok(repo.list_account_proposals(conn, uA) is not None, "la conn sigue viva tras el id malformado")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    try: repo.clear_account_memories(conn, uA)
    except Exception: pass
    try: repo.clear_account_memories(conn, uB)
    except Exception: pass
    conn.close()
sys.exit(1 if _fail else 0)
