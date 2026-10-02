"""ORDEN 3 · e2e VIVO — recall relevante en un run REAL (motor in-process, cerebro Opus vía shim).

Prueba end-to-end lo que el unit no puede (probado, no razonado):
  (1) en un run REAL, el executor selecciona SKILL (siempre) + la episódica RELEVANTE al pedido y
      EXCLUYE las episódicas irrelevantes del framing (recorder que envuelve el selector real);
  (2) el agente USA el hecho relevante en su respuesta (comportamiento).

Correr:  cd product/backend && set -a && . ../../infra/.env && set +a && \
         PUPPET_BRAIN_SHIM=1 ./.venv/bin/python ../../qa/verify_recall_relevante_e2e.py
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__)); _ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
sys.path.insert(0, os.path.join(_ROOT, "platform", "assembler"))
from app.phase1 import repo, executor
import app.phase1.memory_recall as mr

_fail = []
def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c: _fail.append(label)

CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"
RECIPE = {"schema_version": "v1", "meta": {"name": "Recall A", "nicho": "test"},
          "model": {"alias": "brain", "temperature": 0, "max_tokens": 400, "max_turns": 3},
          "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
          "framing": {"inline": "Sos un asistente. Respondé breve, usando lo que sabés del usuario."},
          "rag": {"enabled": False}, "keys": {}, "gates": {}}

# recorder: envuelve el selector REAL (no lo stubea) para OBSERVAR qué eligió el run
_real_select = executor.select_relevant_memories
_agent_selection = {"contents": None}
def _recording_select(memories, request, *, k=mr.EPISODIC_TOPK, always_kinds=("skill",), order="recency"):
    out = _real_select(memories, request, k=k, always_kinds=always_kinds, order=order)
    if always_kinds == ("skill",):   # la llamada del AGENTE (la de cuenta usa always_kinds=())
        _agent_selection["contents"] = [m.get("content", "") for m in out]
    return out
executor.select_relevant_memories = _recording_select

conn = repo.get_conn()
u = repo.get_or_create_user(conn, "recall-e2e@test.local", tier="tecnico")["id"]
p = repo.create_puppet(conn, owner_id=u, name="Recall A", nicho="general", config=RECIPE)["id"]
repo.clear_memories(conn, p)
# 1 skill (siempre viaja) + 1 episódica RELEVANTE + 3 episódicas IRRELEVANTES
repo.add_memory(conn, puppet_id=p, content="Prefiere respuestas en español rioplatense (voseo)",
                source="agent", meta={"kind": "skill", "provenance": "hecho"})
repo.add_memory(conn, puppet_id=p, content="El deadline del proyecto NORDVIK es el 30 de agosto",
                source="agent", meta={"kind": "episodica", "provenance": "hecho"})
repo.add_memory(conn, puppet_id=p, content="El cliente ZEPHYR tiene su oficina en Lima",
                source="agent", meta={"kind": "episodica", "provenance": "hecho"})
repo.add_memory(conn, puppet_id=p, content="El servidor de staging es 10.0.0.5",
                source="agent", meta={"kind": "episodica", "provenance": "hecho"})
repo.add_memory(conn, puppet_id=p, content="La factura de mayo quedó en 4200 dólares",
                source="agent", meta={"kind": "episodica", "provenance": "hecho"})
# captura EXPLÍCITA del usuario (source='user'), IRRELEVANTE al pedido de Nordvik: debe entrar IGUAL
# (promesa "lo guardé" — no se cae por relevancia).
repo.add_memory(conn, puppet_id=p, content="Recordá que soy alérgico al maní",
                source="user", pinned=True, meta={"explicit": True})

try:
    r = executor.run_puppet_e2e(RECIPE, "¿Cuál es el deadline del proyecto Nordvik? Respondé breve.",
                                puppet_id=p, user_id=u, conn=None, deadline_s=120.0)
    sel = _agent_selection["contents"] or []
    joined = " ".join(sel)
    print("    seleccionado al framing:", [s[:40] for s in sel])
    print("    answer:", (r.get("answer") or "")[:130].replace("\n", " "))

    print("== 1 · el run seleccionó skill + episódica RELEVANTE, excluyó las IRRELEVANTES ==")
    ok(sel is not None and len(sel) > 0, "el recorder capturó la selección del agente")
    ok(any("Prefiere respuestas en español" in s for s in sel), "SKILL entró (siempre viaja)")
    ok("NORDVIK" in joined.upper(), "la episódica RELEVANTE (Nordvik) entró")
    ok("ZEPHYR" not in joined.upper() and "10.0.0.5" not in joined and "factura" not in joined.lower(),
       "las episódicas IRRELEVANTES (Zephyr/servidor/factura) NO entraron al framing")
    ok("maní" in joined or "alérgico" in joined.lower(),
       "la captura EXPLÍCITA (source='user') irrelevante entró IGUAL (promesa 'lo guardé')")

    print("== 2 · el agente USÓ el hecho relevante ==")
    ans = (r.get("answer") or "")
    ok(("agosto" in ans.lower()) or ("30" in ans), "la respuesta usa el deadline (30 de agosto)")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    executor.select_relevant_memories = _real_select
    try:
        repo.clear_memories(conn, p)
    except Exception:
        pass
    conn.close()
sys.exit(1 if _fail else 0)
