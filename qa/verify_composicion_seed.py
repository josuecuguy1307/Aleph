"""ORDEN 4 · Evidencia VIVA de la COMPOSICIÓN (seed del bus) contra Postgres real.

Doble-llave (probado, no razonado):
  • happy path: memorias de agentes miembro → bus de la composición, con PROCEDENCIA (origin_agent_id/
    origin_memory_id/kind + author_label = nombre del agente origen). El ORIGEN no se toca (préstamo).
  • INVARIANTE #4: una id de account_memories NO se puede sembrar (otra tabla → 'not_found') → la
    memoria de CUENTA jamás llega a un bus que otros agentes leerían.
  • lo CONFIDENCIAL no es mezclable → 'confidential'.
  • anti-IDOR: memoria de un agente de OTRO usuario → 'not_owned', jamás entra al bus.
  • idempotencia: re-sembrar las mismas ids no duplica ('already_seeded').

Correr:  cd product/backend && ./.venv/bin/python ../../qa/verify_composicion_seed.py
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
from app.phase1 import repo

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        _fail.append(label)

RCP = {"schema_version": "v1", "meta": {"name": "x", "nicho": "test"},
       "model": {"alias": "brain"}, "belt": {}, "framing": {"inline": "x"},
       "rag": {"enabled": False}, "keys": {}, "gates": {}}

conn = repo.get_conn()
uA = repo.get_or_create_user(conn, "seed-A@test.local", tier="tecnico")["id"]
uB = repo.get_or_create_user(conn, "seed-B@test.local", tier="tecnico")["id"]
# agentes miembro (de A) + un agente de B (para anti-IDOR) + la composición (Cuarto guardado de A)
pCAD = repo.create_puppet(conn, owner_id=uA, name="Ingeniero CAD", nicho="ing", config=RCP)["id"]
pMED = repo.create_puppet(conn, owner_id=uA, name="Radiólogo", nicho="med", config=RCP)["id"]
pTEAM = repo.create_puppet(conn, owner_id=uA, name="Equipo Mixto", nicho="general", config=RCP)["id"]
pB = repo.create_puppet(conn, owner_id=uB, name="Agente de B", nicho="general", config=RCP)["id"]
for _p in (pCAD, pMED, pTEAM, pB):
    repo.clear_memories(conn, _p)
repo.clear_shared_memories(conn, pTEAM)
repo.clear_account_memories(conn, uA)

try:
    # memorias de origen
    mc1 = repo.add_memory(conn, puppet_id=pCAD, content="Tolerancia estándar del taller: 0.1mm",
                          source="agent", meta={"kind": "skill", "provenance": "hecho"})["id"]
    mc2 = repo.add_memory(conn, puppet_id=pCAD, content="El proyecto Nordvik usa acero 4140",
                          source="agent", meta={"kind": "episodica", "provenance": "hecho",
                                                "run_id": "run-A"})["id"]
    mm1 = repo.add_memory(conn, puppet_id=pMED, content="Protocolo de ventana ósea del equipo",
                          source="agent", meta={"kind": "skill", "provenance": "hecho"})["id"]
    mconf = repo.add_memory(conn, puppet_id=pCAD, content="Credencial del PLM: admin/secreto",
                            source="agent", meta={"kind": "episodica", "confidential": True})["id"]
    mB = repo.add_memory(conn, puppet_id=pB, content="MEMORIA-DE-B: no cruza dueños",
                         source="agent", meta={"kind": "skill"})["id"]
    macct = repo.add_account_memory(conn, owner_id=uA, content="HECHO-DE-CUENTA: soy de Quito")["id"]

    print("== 1 · happy path: piezas elegidas → bus, con procedencia; origen intacto ==")
    res = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                               memory_ids=[mc1, mc2, mm1], max_entries=200, max_bytes=131072)
    ok(len(res["seeded"]) == 3 and not res["skipped"], "3 sembradas, 0 saltadas")
    bus = repo.list_shared_memories(conn, pTEAM)
    bc = {b["content"]: b for b in bus}
    ok("Tolerancia estándar del taller: 0.1mm" in bc and "El proyecto Nordvik usa acero 4140" in bc
       and "Protocolo de ventana ósea del equipo" in bc, "las 3 notas están en el bus")
    _cadnote = bc.get("El proyecto Nordvik usa acero 4140")
    ok(_cadnote and _cadnote.get("author_label") == "Ingeniero CAD", "author_label = nombre del agente origen")
    ok(_cadnote and str((_cadnote.get("meta") or {}).get("origin_memory_id")) == str(mc2),
       "procedencia: origin_memory_id apunta a la memoria de origen")
    ok(_cadnote and (_cadnote.get("meta") or {}).get("kind") == "episodica", "procedencia: kind conservado")
    ok(_cadnote and str((_cadnote.get("meta") or {}).get("origin_agent_id")) == str(pCAD), "procedencia: origin_agent_id")
    # ORIGEN intacto (préstamo, no transfusión)
    orig = repo.list_memories(conn, pCAD)
    ok(len(orig) == 3, "el estante del agente origen sigue con sus 3 (nada movido/borrado)")

    print("== 2 · INVARIANTE #4 · una id de CUENTA NO se puede sembrar (otra tabla) ==")
    r2 = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                              memory_ids=[macct], max_entries=200, max_bytes=131072)
    ok(r2["seeded"] == [] and r2["skipped"] and r2["skipped"][0]["reason"] == "not_found",
       "id de account_memories → 'not_found' (no existe en agent_memories)")
    ok(not any("HECHO-DE-CUENTA" in b["content"] for b in repo.list_shared_memories(conn, pTEAM)),
       "el hecho de CUENTA NUNCA aparece en el bus")

    print("== 3 · lo CONFIDENCIAL no es mezclable ==")
    r3 = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                              memory_ids=[mconf], max_entries=200, max_bytes=131072)
    ok(r3["seeded"] == [] and r3["skipped"][0]["reason"] == "confidential", "confidencial → 'confidential'")
    ok(not any("admin/secreto" in b["content"] for b in repo.list_shared_memories(conn, pTEAM)),
       "la credencial confidencial NUNCA entra al bus")

    print("== 4 · anti-IDOR · memoria de agente de OTRO usuario ==")
    r4 = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                              memory_ids=[mB], max_entries=200, max_bytes=131072)
    ok(r4["seeded"] == [] and r4["skipped"][0]["reason"] == "not_owned", "memoria de B → 'not_owned'")
    ok(not any("MEMORIA-DE-B" in b["content"] for b in repo.list_shared_memories(conn, pTEAM)),
       "la memoria de B NUNCA entra al bus de A")

    print("== 5 · idempotencia · re-sembrar las mismas ids no duplica ==")
    before = len(repo.list_shared_memories(conn, pTEAM))
    r5 = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                              memory_ids=[mc1, mc2], max_entries=200, max_bytes=131072)
    ok(r5["seeded"] == [] and all(s["reason"] == "already_seeded" for s in r5["skipped"]),
       "re-seed → 'already_seeded', 0 nuevas")
    ok(len(repo.list_shared_memories(conn, pTEAM)) == before, "el conteo del bus no cambió (sin duplicados)")

    print("== 6 · FIX review · id MALFORMADO (no-UUID) → 'malformed', NO 500, y el válido igual siembra ==")
    mm2 = repo.add_memory(conn, puppet_id=pMED, content="Nota de protocolo extra",
                          source="agent", meta={"kind": "skill"})["id"]
    r6 = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=uA,
                              memory_ids=["no-es-uuid", mm2], max_entries=200, max_bytes=131072)
    ok(any(s["reason"] == "malformed" for s in r6["skipped"]), "el id no-UUID → skipped 'malformed' (jamás toca la DB)")
    ok(len(r6["seeded"]) == 1, "el id VÁLIDO de la misma lista SÍ se sembró (sin 500 ni siembra rota)")
    ok(any("Nota de protocolo extra" == b["content"] for b in repo.list_shared_memories(conn, pTEAM)),
       "la pieza válida quedó en el bus pese al id malo previo")

    print("== 7 · FIX review · el cap NO miente · pieza que excede el techo se trunca; evicted reportado ==")
    pBIG = repo.create_puppet(conn, owner_id=uA, name="Grande", nicho="general", config=RCP)["id"]
    repo.clear_memories(conn, pBIG)
    pSMALL = repo.create_puppet(conn, owner_id=uA, name="Cuarto chico", nicho="general", config=RCP)["id"]
    repo.clear_shared_memories(conn, pSMALL)
    big = repo.add_memory(conn, puppet_id=pBIG, content="X" * 9000, source="agent",
                          meta={"kind": "skill"})["id"]
    # techo chico (free): la pieza de 9000B se TRUNCA a 8192 → cabe → sobrevive y 'seeded' no miente
    r7 = repo.seed_shared_bus(conn, composition_id=pSMALL, owner_id=uA, memory_ids=[big],
                              max_entries=20, max_bytes=8192)
    surv = repo.list_shared_memories(conn, pSMALL)
    ok(len(r7["seeded"]) == len(surv) and len(surv) == 1,
       "la pieza truncada al techo sobrevive; 'seeded' = lo que REALMENTE quedó (no miente)")
    ok(all(x["bytes"] <= 8192 for x in surv), "ninguna entrada del bus excede el techo de bytes")
    ok("evicted_total" in r7 and "evicted_seeded" in r7, "la respuesta expone la disclosure de desalojo")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    for _p in (pCAD, pMED, pTEAM, pB, locals().get("pBIG"), locals().get("pSMALL")):
        try: repo.clear_memories(conn, _p)
        except Exception: pass
    for _c in (pTEAM, locals().get("pSMALL")):
        try: repo.clear_shared_memories(conn, _c)
        except Exception: pass
    try: repo.clear_account_memories(conn, uA)
    except Exception: pass
    conn.close()
sys.exit(1 if _fail else 0)
