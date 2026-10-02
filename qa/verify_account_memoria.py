"""ORDEN 2 · Sistema 2 · Evidencia VIVA de la MEMORIA DE CUENTA contra Postgres real.

Doble-llave (probado, no razonado): CRUD + provenance en meta · AISLAMIENTO cross-cuenta ·
anti-IDOR (account_memory_owner) · caps por tier (retención user>agent, corte por prefijo) ·
compactación al framing (_build_pinned_memory, el MISMO que lee el run). Sin servidor: DB directa.

Correr:  cd product/backend && ./.venv/bin/python ../../qa/verify_account_memoria.py
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
from app.phase1 import repo
from app.phase1.executor import _build_pinned_memory, _A3_PINNED_BUDGET_BYTES
from gates.recipe_enforcer import account_memory_caps_for_tier

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        _fail.append(label)

conn = repo.get_conn()
EA = "acct-mem-A@test.local"
EB = "acct-mem-B@test.local"
uA = repo.get_or_create_user(conn, EA, tier="free")["id"]
uB = repo.get_or_create_user(conn, EB, tier="free")["id"]
# reset idempotente
repo.clear_account_memories(conn, uA)
repo.clear_account_memories(conn, uB)

try:
    print("== 1 · CRUD + provenance en meta ==")
    m = repo.add_account_memory(conn, owner_id=uA, content="El usuario habla español (voseo)",
                                meta={"provenance": "hecho"})
    ok(m and str(m["owner_id"]) == str(uA), "add → owner_id correcto")
    ok(m["source"] == "user", "source DEFAULT 'user' (ascenso = acto del usuario)")
    ok((m.get("meta") or {}).get("provenance") == "hecho", "meta.provenance persistido")
    got = repo.list_account_memories(conn, uA)
    ok(len(got) == 1 and got[0]["content"].startswith("El usuario habla"), "list → round-trip")
    # provenance inferencia también viaja
    m2 = repo.add_account_memory(conn, owner_id=uA, content="Probablemente es de Ecuador",
                                 source="agent", meta={"provenance": "inferencia"})
    ok((m2.get("meta") or {}).get("provenance") == "inferencia", "inferencia (source=agent) persiste con su provenance")

    print("== 2 · AISLAMIENTO cross-cuenta (H6: la cuenta de otro JAMÁS) ==")
    repo.add_account_memory(conn, owner_id=uB, content="SECRETO-DE-B: nunca cruza")
    listA = repo.list_account_memories(conn, uA)
    listB = repo.list_account_memories(conn, uB)
    ok(all(str(x["owner_id"]) == str(uA) for x in listA), "list(A) = SÓLO de A")
    ok(not any("SECRETO-DE-B" in x["content"] for x in listA), "el secreto de B NO aparece en A")
    ok(len(listB) == 1 and "SECRETO-DE-B" in listB[0]["content"], "list(B) = SÓLO de B")

    print("== 3 · anti-IDOR · account_memory_owner ==")
    ok(str(repo.account_memory_owner(conn, m["id"])) == str(uA), "owner de la entrada de A = A")
    ok(repo.account_memory_owner(conn, "00000000-0000-0000-0000-000000000000") is None, "id inexistente → None")

    print("== 4 · caps por tier (free=15) · retención user>agent, corte por prefijo ==")
    repo.clear_account_memories(conn, uA)
    # 2 entradas del USUARIO (viejas) + 20 destiladas por agente (nuevas): el corte debe conservar
    # las 2 del usuario aunque sean las más viejas (prioridad estricta user>agent).
    uid1 = repo.add_account_memory(conn, owner_id=uA, content="USER-KEEP-1", source="user")["id"]
    uid2 = repo.add_account_memory(conn, owner_id=uA, content="USER-KEEP-2", source="user")["id"]
    for i in range(20):
        repo.add_account_memory(conn, owner_id=uA, content=f"agent-fact-{i:02d}", source="agent")
    caps = account_memory_caps_for_tier("free")
    evicted = repo.enforce_account_memory_caps(conn, uA, max_entries=caps["max_entries"],
                                               max_bytes=caps["max_bytes"])
    after = repo.list_account_memories(conn, uA)
    ok(len(after) == caps["max_entries"], f"quedan exactamente {caps['max_entries']} (evictó {evicted})")
    survivors = {x["content"] for x in after}
    ok("USER-KEEP-1" in survivors and "USER-KEEP-2" in survivors,
       "las 2 del USUARIO sobreviven por encima de las 'agent' (aunque más viejas)")
    ok(repo.account_memory_usage(conn, uA)["entries"] == caps["max_entries"], "usage refleja el techo")

    print("== 5 · compactación al framing (el MISMO builder que lee el run) ==")
    repo.clear_account_memories(conn, uA)
    repo.add_account_memory(conn, owner_id=uA, content="Reportá siempre en español, tono directo")
    repo.add_account_memory(conn, owner_id=uA, content="Prefiere unidades del SI")
    amems = repo.list_account_memories(conn, uA, pinned_only=True)
    budget = min(_A3_PINNED_BUDGET_BYTES, caps["max_bytes"])
    block = _build_pinned_memory(amems, budget_bytes=budget)
    ok(block and "español" in block and "SI" in block, "el bloque compacto contiene los hechos de cuenta")
    ok(block.startswith("- "), "formato de apuntes (- ...)")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    # cleanup: borra la memoria de cuenta de los users de prueba (idempotente; los users quedan
    # reutilizables por email). No tocamos nada de otra cuenta.
    try:
        repo.clear_account_memories(conn, uA)
        repo.clear_account_memories(conn, uB)
    except Exception:
        pass
    conn.close()

sys.exit(1 if _fail else 0)
