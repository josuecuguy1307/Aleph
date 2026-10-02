"""ORDEN 2 · e2e VIVO (cerebro real Opus vía shim :8923) — motor IN-PROCESS (como verify_c6/b2).

Prueba lo que unit/DB no pueden (probado, no razonado):
  (1) el DESTILADOR real emite la etiqueta [kind/prov] y el parser la extrae (probe directo al shim);
  (2) un run REAL distila → agent_memories.meta.kind persistido y en dominio (cableado end-to-end);
  (3) COLD-RECALL cross-agente de CUENTA: un agente FRESCO del dueño recita un hecho de cuenta que
      NUNCA vio en su historia (⇒ el bloque de cuenta entró a su framing = "todo agente la lee");
  (4) AISLAMIENTO: el agente de OTRO usuario NO ve el hecho de cuenta ajeno.

Prereq: shim Opus :8923 vivo. Correr CON el brain-shim ON:
  cd product/backend && set -a && . ../../infra/.env && set +a && \
  PUPPET_BRAIN_SHIM=1 ./.venv/bin/python ../../qa/verify_memoria_orden2_e2e.py
"""
import sys, os, json, urllib.request
_HERE = os.path.dirname(os.path.abspath(__file__)); _ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
sys.path.insert(0, os.path.join(_ROOT, "platform", "assembler"))
from app.phase1 import repo, executor
from recipe_assembler import _build_distill_messages, _parse_distilled_memory
import models as _models

SHIM = "http://127.0.0.1:8923/v1/chat/completions"
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"
_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond: _fail.append(label)

def _shim(msgs, timeout=90):
    data = json.dumps({"model": "x", "messages": msgs, "max_tokens": 400, "temperature": 0}).encode()
    req = urllib.request.Request(SHIM, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "") or ""

RECIPE = {"schema_version": "v1",
          "meta": {"name": "Agente cuenta", "nicho": "test"},
          "model": {"alias": "brain", "temperature": 0, "max_tokens": 400, "max_turns": 3},
          "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add", "mul"]}},
          "framing": {"inline": "Sos un asistente. Respondé breve, en el idioma del usuario."},
          "rag": {"enabled": False}, "keys": {}, "gates": {}}

def run(prompt, *, puppet_id, user_id, deadline=120):
    return executor.run_puppet_e2e(RECIPE, prompt, puppet_id=puppet_id, user_id=user_id,
                                   conn=None, deadline_s=float(deadline))

print(f"[seam] brain shim_on={_models._BRAIN_SHIM_ON} → {_models.resolve_recipe_model({'alias':'brain'})['base_url']!r}")

conn = repo.get_conn()
uA = repo.get_or_create_user(conn, "acct-e2e-A@test.local", tier="tecnico")["id"]
uB = repo.get_or_create_user(conn, "acct-e2e-B@test.local", tier="tecnico")["id"]
pA = repo.create_puppet(conn, owner_id=uA, name="Fresco A", nicho="general", config=RECIPE)["id"]
pB = repo.create_puppet(conn, owner_id=uB, name="Fresco B", nicho="general", config=RECIPE)["id"]
repo.clear_account_memories(conn, uA); repo.clear_account_memories(conn, uB)
repo.clear_memories(conn, pA); repo.clear_memories(conn, pB)
SENTINEL = "ZORZAL-CUENTA-42"
repo.add_account_memory(conn, owner_id=uA, content=f"El usuario se llama {SENTINEL}.",
                        source="user", meta={"provenance": "hecho"})

try:
    print("== 1 · PROBE directo: el destilador real emite [kind/prov] (shim Opus) ==")
    msgs = _build_distill_messages(
        "De ahora en adelante respondeme SIEMPRE en español con voseo y unidades del SI. "
        "Además: mi cliente actual es Nordvik y el deadline del proyecto es el 30 de agosto.",
        "Entendido. Voy a responderte en español rioplatense con unidades SI de acá en más. "
        "Anoto que tu proyecto Nordvik vence el 30 de agosto.")
    emitted, parsed_ok, samples = 0, 0, 3
    for i in range(samples):
        try:
            raw = _shim(msgs)
        except Exception as e:
            print("    (shim error:", e, ")"); continue
        items = _parse_distilled_memory(raw)
        if "[" in raw and ("skill" in raw.lower() or "episod" in raw.lower()):
            emitted += 1
        if items and all(it["kind"] in ("skill", "episodica") and it["provenance"] in ("hecho", "inferencia") for it in items):
            parsed_ok += 1
        if i == 0:
            print("    muestra 0 →", [(it["kind"], it["provenance"], it["content"][:42]) for it in items][:4])
    ok(emitted >= 2, f"el modelo emite etiqueta skill/episodica ({emitted}/{samples})")
    ok(parsed_ok >= 2, f"el parser extrae kind+prov en-dominio ({parsed_ok}/{samples})")

    print("== 2 · run REAL distila → agent_memories.meta.kind persistido ==")
    saved_kind = None
    for attempt in range(2):
        r = run("Para TODAS nuestras próximas sesiones: preferís respuestas en español rioplatense "
                "(voseo) y con unidades del SI. Confirmá en una línea.", puppet_id=pA, user_id=uA)
        mems = repo.list_memories(conn, pA)
        kinds = [(m.get("meta") or {}).get("kind") for m in mems if (m.get("meta") or {}).get("kind")]
        if kinds:
            saved_kind = kinds
            provs = [(m.get("meta") or {}).get("provenance") for m in mems]
            print(f"    memory_saved={r.get('memory_saved')} model_final={r.get('model_final')} kinds={kinds} provs={provs}")
            break
        print(f"    intento {attempt+1}: distiller vacío (juicio), reintento…  (model_final={r.get('model_final')})")
    ok(saved_kind is not None, "el run persistió ≥1 entrada con meta.kind")
    if saved_kind:
        ok(all(k in ("skill", "episodica") for k in saved_kind), "todo meta.kind persistido ∈ {skill, episodica}")

    print("== 3 · COLD-RECALL cross-agente de CUENTA (agente fresco recita el hecho de cuenta) ==")
    repo.clear_memories(conn, pA)   # el agente NO tiene memoria propia previa: el nombre sólo puede venir de la CUENTA
    r = run("¿Cómo se llama el usuario con el que estás hablando? Respondé SOLO el nombre, sin más texto.",
            puppet_id=pA, user_id=uA)
    ans = (r.get("answer") or "")
    print("    answer:", ans[:130].replace("\n", " "), "| model_final=", r.get("model_final"))
    ok(SENTINEL in ans, f"el agente FRESCO recita el hecho de cuenta ({SENTINEL}) → la cuenta entró a su framing")

    print("== 4 · AISLAMIENTO: el agente de OTRO usuario NO ve la cuenta ajena ==")
    rB = run("¿Cómo se llama el usuario con el que estás hablando? Si no lo sabés, decí exactamente 'no lo sé'.",
             puppet_id=pB, user_id=uB)
    ansB = (rB.get("answer") or "")
    print("    answer(B):", ansB[:130].replace("\n", " "))
    ok(SENTINEL not in ansB, f"el usuario B NO obtiene el nombre de A ({SENTINEL}) — aislamiento H6")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    try:
        repo.clear_account_memories(conn, uA); repo.clear_account_memories(conn, uB)
        repo.clear_memories(conn, pA); repo.clear_memories(conn, pB)
    except Exception:
        pass
    conn.close()
sys.exit(1 if _fail else 0)
