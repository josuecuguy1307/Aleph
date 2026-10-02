#!/usr/bin/env python3
"""
verify_shared_memoria_b2.py — EVIDENCIA de MEMORIA COMPARTIDA por COMPOSICIÓN (Step 2 · B2).

Prueba, contra el MOTOR REAL (executor.run_puppet_e2e → assemble_and_run + belt REAL por
subprocess + germen de memoria REAL (npx server-memory) + gate en el path + DB Postgres REAL)
y con SÓLO el cerebro stubeado (B2Brain, guión determinista → cero tokens, headless) — igual
que el harness A3 —, que la memoria COMPARTIDA del Cuarto CIERRA:

  1. DAO + AUTORÍA + AISLAMIENTO + CAPS + OWNER — la capa de datos (clon de A3 con author,
     keyed por composition_id) guarda autoría, aísla entre Cuartos, corta por-tier (prefijo,
     user>agent) y resuelve el dueño anti-IDOR. (Puerto directo del smoke pure-python.)
  2. A ESCRIBE → B LEE (READ + autoría) — el agente A deja una nota en el bus del Cuarto; el
     núcleo (miembro) la RECIBE en su framing atribuida a su autor (record.shared_memory_injected).
  3. C NO CONECTADO → NO LA VE — el mismo Cuarto con la misma nota, pero la línea teal
     (memory.members) NO incluye al núcleo → NO se inyecta el bloque compartido (ACL real).
  4. DOS CUARTOS AISLADOS — dos composiciones (X, Y); la nota de X JAMÁS aparece en el run de Y
     (anti-IDOR por composition_id, el análogo B2 del aislamiento de A3).
  5. WRITE DESTILADO ATRIBUIDO — un agente miembro destila su aporte al cierre limpio → se
     persiste (source='agent') con AUTOR (out.shared_memory_saved ≥ 1), server-side, sin gate.
  6. CANDADO PREMIUM (tier de la CUENTA) — free + memory.shared + agent_refs ≥ 1 → RECHAZO honesto
     + upsell (shared_memory_bus), UPSTREAM de la herencia a hijos; basico → NO es ese rechazo.
     El tier sale de users.tier (la cuenta del dueño), no de recipe.tier (display).
  7. PANEL HTTP — POST una nota → GET la muestra con autor 'Vos'; PATCH; DELETE; anti-IDOR
     (token de OTRO dueño → 403); contenido multibyte (5000×'ñ') sobrevive el byte-cap
     (truncado en frontera UTF-8, NO auto-borrado por enforce_caps).

Uso:  python3 qa/verify_shared_memoria_b2.py     (necesita Postgres puppet_ai vivo + node/npx)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

# El belt de prueba (deleg) y el germen de memoria referencian ${PUPPET_BELTS}/... → apuntá
# PUPPET_BELTS al repo_root ANTES de importar el executor.
os.environ["PUPPET_BELTS"] = str(_REPO_ROOT)
os.environ.pop("PUPPET_SHARED_MEMORY", None)   # el path del germen viaja por parámetro, no por env
# enc.key del token de sesión (panel HTTP): si el entorno no la fija ni existe el keyfile, usamos
# una clave efímera de proceso (mint + verify ocurren en ESTE proceso → consistente; no toca el
# worktree). Si ya viene por env/keyfile, se respeta.
try:
    if not os.environ.get("PUPPET_DB_ENC_KEY") and not (
            _REPO_ROOT / "platform" / "db" / "secrets" / "enc.key").exists():
        from cryptography.fernet import Fernet
        os.environ["PUPPET_DB_ENC_KEY"] = Fernet.generate_key().decode("ascii")
except Exception:
    pass

for p in (str(_REPO_ROOT / "platform" / "assembler"),
          str(_REPO_ROOT / "platform" / "gates"),
          str(_REPO_ROOT / "platform"),
          str(_REPO_ROOT / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import executor, repo  # noqa: E402

results: dict = {}   # label -> (passed, evidencia)


def _hr(t: str):
    print("\n" + "═" * 78 + f"\n  {t}\n" + "═" * 78)


def _ok(label: str, cond: bool, ev: str = ""):
    results[label] = (bool(cond), ev)
    print(f"  [{'OK ' if cond else 'XX '}] {label}" + (f" — {ev}" if ev else ""))


# ── B2Brain — stubea SÓLO el cerebro (mismo mecanismo que la MemBrain de A3). Atiende DOS
#   destilados server-side que pueden dispararse en el mismo run: el A3 ('aprendizajes DURABLES')
#   y el B2 ('COMPARTIR con los OTROS agentes del Cuarto'). Para B2 devuelve las líneas '- <item>'
#   scripteadas; para A3 devuelve NADA (esta suite prueba el bus, no la memoria privada). El turno
#   con tools cierra directo (el agente no necesita tools para estos casos). Thread-safe. ────────
class B2Brain:
    def __init__(self, shared_items):
        self.shared_items = list(shared_items or [])
        self.lock = threading.Lock()

    @staticmethod
    def _final(text):
        return ({"choices": [{"message": {"role": "assistant", "content": text},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
                "b2-brain")

    def route(self, messages, tools, *, base_url, primary, fallback, api_key,
              max_tokens, temperature, route_log, on_tier_error=None):
        route_log.append({"model": "b2-brain", "tier": "primary", "ok": True})
        last = messages[-1] if messages else {}
        content = str(last.get("content", ""))
        # ¿es un call de DESTILADO? (tools vacío + system con el prompt del destilado)
        if not tools and last.get("role") == "system":
            if "COMPARTIR con los OTROS agentes del Cuarto" in content:
                if self.shared_items:
                    return self._final("\n".join("- " + e for e in self.shared_items))
                return self._final("NADA")
            if "aprendizajes DURABLES" in content:
                return self._final("NADA")   # A3 fuera de scope de esta suite
        # cualquier otro cierre sin tools → final benigno
        if not tools:
            return self._final("[cierre]")
        # turno con tools: el agente responde directo (no delega, no llama tools)
        return self._final("Listo, hice la tarea.")


class _Patched:
    """Stubea el cerebro en EL módulo del assembler que USA el executor (importlib lo carga como
    'puppet_recipe_assembler' → objeto de módulo distinto al import top-level). Idéntico a A3."""
    def __init__(self, brain):
        self.brain = brain
        self._mod = None
        self._orig = None

    def __enter__(self):
        self._mod = executor._asm()
        self._orig = self._mod._route_chat
        self._mod._route_chat = self.brain.route
        return self

    def __exit__(self, *a):
        self._mod._route_chat = self._orig


def _recipe(*, members=None, agent_refs=None):
    """Receta de un Cuarto con memory.shared. `members` = línea teal (None → default '*' en el
    executor = todos conectados). `agent_refs` activa la delegación (para el candado premium)."""
    belt = {"belt_ref": "platform/assembler/deleg_fixtures/belt-deleg.mcp.json",
            "tool_filters": {"deleg": ["read_data"]}}
    if agent_refs:
        belt["agent_refs"] = agent_refs
    mem = {"shared": True, "ref": "product/belts/memoria-compartida.mcp.json"}
    if members is not None:
        mem["members"] = members
    return {
        "schema_version": "v1",
        "meta": {"name": "Cuarto B2", "nicho": "general", "descripcion": "cuarto de prueba B2"},
        "model": {"primary": "stub", "base_url": "stub://local", "temperature": 0,
                  "max_tokens": 256, "max_turns": 4},
        "belt": belt,
        "memory": mem,
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }


def _run(recipe, prompt, *, puppet_id, user_id, shared_items=None):
    """Un run E2E por el executor REAL, con el cerebro stubeado por B2Brain."""
    with _Patched(B2Brain(shared_items)):
        return executor.run_puppet_e2e(
            recipe, prompt, puppet_id=puppet_id, user_id=user_id, conn=None, deadline_s=80.0)


# ════════════════════════════════════════════════════════════════════════════════
def _axis1_dao(conn):
    _hr("1 · DAO + AUTORÍA + AISLAMIENTO + CAPS + OWNER (capa de datos, sin cerebro)")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local")["id"]
    pX = repo.create_puppet(conn, owner_id=u, name="CuartoDAO-X", nicho="general", config={})["id"]
    pY = repo.create_puppet(conn, owner_id=u, name="CuartoDAO-Y", nicho="general", config={})["id"]

    mA = repo.add_shared_memory(conn, composition_id=pX, content="hallazgo A: la API usa v2",
                                author_agent_id="agent-A", author_label="Agente A", source="agent")
    repo.add_shared_memory(conn, composition_id=pX, content="nota del usuario",
                           author_agent_id=u, author_label="Vos", source="user")
    lst = repo.list_shared_memories(conn, pX)
    _ok("1a·autoría-preservada",
        len(lst) == 2 and any(x["author_label"] == "Agente A" for x in lst)
        and any(x["author_label"] == "Vos" for x in lst)
        and any(x["author_agent_id"] == "agent-A" for x in lst),
        f"cidX con 2 entradas atribuidas (Agente A / Vos)")

    lstY = repo.list_shared_memories(conn, pY)
    repo.add_shared_memory(conn, composition_id=pY, content="secreto de Y", author_label="Y")
    _ok("1b·aislamiento-entre-Cuartos",
        len(lstY) == 0 and len(repo.list_shared_memories(conn, pX)) == 2
        and len(repo.list_shared_memories(conn, pY)) == 1,
        "cidY no ve cidX; escribir en Y no contamina X")

    own = repo.shared_memory_owner(conn, mA["id"])
    _ok("1c·owner-anti-IDOR", str(own) == str(u), "shared_memory_owner = dueño del Cuarto (JOIN puppets)")

    for i in range(30):
        repo.add_shared_memory(conn, composition_id=pX, content=f"entrada {i}" * 3,
                               author_label="A", source="agent")
    before = repo.shared_memory_usage(conn, pX)["entries"]
    evicted = repo.enforce_shared_memory_caps(conn, pX, max_entries=20, max_bytes=8192)
    after = repo.shared_memory_usage(conn, pX)["entries"]
    kept = repo.list_shared_memories(conn, pX)
    _ok("1d·caps-corte-por-tier",
        after <= 20 and any(x["source"] == "user" for x in kept),
        f"enforce recortó a {after}≤20 (antes {before}, evictó {evicted}); la 'user' sobrevive (prioridad)")

    mU = repo.add_shared_memory(conn, composition_id=pX, content="para editar", author_label="A")
    upd = repo.update_shared_memory(conn, mU["id"], content="editado")
    mD = repo.add_shared_memory(conn, composition_id=pX, content="para borrar", author_label="A")
    deleted = repo.delete_shared_memory(conn, mD["id"])
    ncl = repo.clear_shared_memories(conn, pY)
    _ok("1e·update-delete-clear",
        upd and upd["content"] == "editado" and deleted is True
        and ncl >= 1 and len(repo.list_shared_memories(conn, pY)) == 0,
        "update cambia texto · delete borra uno · clear vacía el Cuarto")


# ════════════════════════════════════════════════════════════════════════════════
def _axis2_read(conn):
    _hr("2 · A ESCRIBE → B LEE — el núcleo (miembro) recibe la nota de otro agente, atribuida")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="basico")["id"]
    rec_cfg = _recipe()   # sin members → default '*' (el núcleo es miembro)
    pid = repo.create_puppet(conn, owner_id=u, name="Núcleo del Cuarto", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pid)
    repo.add_shared_memory(conn, composition_id=pid, content="la API del banco es v2, no v1",
                           author_agent_id="agente-a", author_label="Agente A", source="agent")

    out = _run(rec_cfg, "TASK-2: trabajá con lo que el equipo ya sabe",
               puppet_id=pid, user_id=u, shared_items=[])
    inj = (out.get("record") or {}).get("shared_memory_injected") or ""
    _ok("2·read-con-autoría",
        out.get("ok") and "Agente A" in inj and "la API del banco es v2" in inj,
        f"el bloque compartido inyectado trae [Agente A] + su nota: {inj!r}")


# ════════════════════════════════════════════════════════════════════════════════
def _axis3_not_connected(conn):
    _hr("3 · C NO CONECTADO — la nota existe en el bus, pero un NO-miembro no la ve (ACL teal)")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="basico")["id"]
    # línea teal que NO incluye al núcleo ('nucleo' ∉ members, '*' ∉ members) → no es miembro
    rec_cfg = _recipe(members=["otro-agente-no-nucleo"])
    pid = repo.create_puppet(conn, owner_id=u, name="Cuarto no-conectado", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pid)
    repo.add_shared_memory(conn, composition_id=pid, content="dato que NO debería ver el no-miembro",
                           author_agent_id="agente-a", author_label="Agente A", source="agent")

    entries_exist = len(repo.list_shared_memories(conn, pid)) == 1
    out = _run(rec_cfg, "TASK-3: soy un agente no conectado al cilindro",
               puppet_id=pid, user_id=u, shared_items=[])
    inj = (out.get("record") or {}).get("shared_memory_injected")
    _ok("3·no-miembro-no-inyecta",
        out.get("ok") and entries_exist and not inj,
        f"la entrada existe en el bus pero shared_memory_injected={inj!r} (ausente/vacío) para el no-miembro")


# ════════════════════════════════════════════════════════════════════════════════
def _axis4_isolation(conn):
    _hr("4 · DOS CUARTOS AISLADOS — la nota de X JAMÁS entra al run de Y (anti-IDOR por composición)")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="basico")["id"]
    rec_cfg = _recipe()
    pX = repo.create_puppet(conn, owner_id=u, name="Cuarto X", nicho="general", config=rec_cfg)["id"]
    pY = repo.create_puppet(conn, owner_id=u, name="Cuarto Y", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pX)
    repo.clear_shared_memories(conn, pY)
    repo.add_shared_memory(conn, composition_id=pX, content="SECRETO-DE-X-no-cruza",
                           author_agent_id="ax", author_label="Agente X", source="agent")
    repo.add_shared_memory(conn, composition_id=pY, content="nota-propia-de-Y",
                           author_agent_id="ay", author_label="Agente Y", source="agent")

    outY = _run(rec_cfg, "TASK-4: corro en el Cuarto Y", puppet_id=pY, user_id=u, shared_items=[])
    injY = (outY.get("record") or {}).get("shared_memory_injected") or ""
    _ok("4·sin-fuga-cross-composición",
        outY.get("ok") and "nota-propia-de-Y" in injY and "SECRETO-DE-X" not in injY,
        f"Y ve SÓLO lo suyo; el secreto de X no cruzó: injY={injY!r}")


# ════════════════════════════════════════════════════════════════════════════════
def _axis5_write(conn):
    _hr("5 · WRITE DESTILADO ATRIBUIDO — un miembro deja su aporte al bus, server-side, con autor")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="basico")["id"]
    rec_cfg = _recipe()
    pid = repo.create_puppet(conn, owner_id=u, name="Núcleo Escritor", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pid)

    out = _run(rec_cfg, "TASK-5: aprendé algo que le sirva al equipo", puppet_id=pid, user_id=u,
               shared_items=["hallazgo del equipo: la demo usa la cuenta X"])
    saved = out.get("shared_memory_saved")
    lst = repo.list_shared_memories(conn, pid)
    new = [x for x in lst if x["source"] == "agent" and "hallazgo del equipo" in (x["content"] or "")]
    authored = bool(new) and bool(new[0].get("author_label"))
    _ok("5·distill-persistido-atribuido",
        out.get("ok") and (saved or 0) >= 1 and len(new) == 1 and authored,
        f"shared_memory_saved={saved}; entrada 'agent' nueva atribuida a {new[0].get('author_label') if new else None!r}")


# ════════════════════════════════════════════════════════════════════════════════
def _axis6_premium(conn):
    _hr("6 · CANDADO PREMIUM — el tier de la CUENTA decide; free+bus+hijos → rechazo, basico → pasa")
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="free")["id"]
    rec_cfg = _recipe(agent_refs=["platform/assembler/deleg_fixtures/child_memoria.json"])
    pid = repo.create_puppet(conn, owner_id=u, name="Cuarto Premium", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pid)

    # FREE (users.tier='free') + memory.shared + agent_refs ≥ 1 → rechazo honesto + upsell
    repo.set_tier(conn, u, "free")
    out_free = _run(rec_cfg, "TASK-6: intento cablear el bus siendo free", puppet_id=pid, user_id=u,
                    shared_items=[])
    rec_free = out_free.get("record") or {}
    err_free = rec_free.get("error") or ""
    ups_free = rec_free.get("upsell") or {}
    _ok("6a·free-rechaza-con-upsell",
        out_free.get("ok") is False and "Premium" in err_free
        and ups_free.get("feature") == "shared_memory_bus",
        f"free → error menciona Premium + upsell feature=shared_memory_bus (min_tier={ups_free.get('min_tier')})")

    # BASICO (mismo Cuarto, otro tier de la cuenta) → NO es el rechazo premium
    repo.set_tier(conn, u, "basico")
    out_bas = _run(rec_cfg, "TASK-6b: ahora soy basico", puppet_id=pid, user_id=u, shared_items=[])
    rec_bas = out_bas.get("record") or {}
    _ok("6b·basico-no-es-el-rechazo",
        (rec_bas.get("upsell") or {}).get("feature") != "shared_memory_bus"
        and "Premium" not in (rec_bas.get("error") or ""),
        "basico (shared_bus=True) → el candado premium NO dispara (tier de la cuenta, no de la receta)")
    repo.set_tier(conn, u, "free")


# ════════════════════════════════════════════════════════════════════════════════
def _axis7_http(conn):
    _hr("7 · PANEL HTTP — POST→GET(autor)→PATCH→DELETE + anti-IDOR(403) + multibyte byte-cap")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.router import build_phase1_router

    _ev_dir = _REPO_ROOT / "product" / "backend" / "data" / "events"
    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=repo.get_conn, events_dir=lambda: _ev_dir))
    client = TestClient(app)

    # dueño (free → cap 8192B) + un usuario DISTINTO (para el anti-IDOR)
    owner = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="free")["id"]
    other = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="free")["id"]
    cid = repo.create_puppet(conn, owner_id=owner, name="Cuarto Panel", nicho="general", config={})["id"]
    repo.clear_shared_memories(conn, cid)
    tok = {"Authorization": f"Bearer {repo.mint_session(owner)}"}
    tok_other = {"Authorization": f"Bearer {repo.mint_session(other)}"}
    base = f"/v1/compositions/{cid}/memories"

    # POST del panel → source='user', author_label='Vos'
    rp = client.post(base, json={"content": "recordá: la demo usa la cuenta X"}, headers=tok)
    posted = rp.json() if rp.status_code == 201 else {}
    # GET → la nota aparece con su autor
    rg = client.get(base, headers=tok)
    body = rg.json() if rg.status_code == 200 else {}
    mems = body.get("memories", [])
    got = next((m for m in mems if m.get("id") == posted.get("id")), None)
    _ok("7a·POST→GET-con-autor",
        rp.status_code == 201 and posted.get("source") == "user" and posted.get("author_label") == "Vos"
        and rg.status_code == 200 and got is not None and got.get("author_label") == "Vos",
        f"POST 201 (autor='Vos', source='user'); GET la lista con autor")

    # PATCH → cambia el texto
    rpatch = client.patch(f"{base}/{posted.get('id')}", json={"content": "corrección: cuenta Y"}, headers=tok)
    _ok("7b·PATCH-edita",
        rpatch.status_code == 200 and rpatch.json().get("content") == "corrección: cuenta Y",
        "PATCH cambia el contenido de la nota")

    # DELETE → borra la nota
    rdel = client.delete(f"{base}/{posted.get('id')}", headers=tok)
    after = client.get(base, headers=tok).json().get("memories", [])
    _ok("7c·DELETE-borra",
        rdel.status_code == 200 and rdel.json().get("deleted") is True
        and not any(m.get("id") == posted.get("id") for m in after),
        "DELETE quita la nota del panel")

    # anti-IDOR: token de OTRO dueño → 403 (GET y POST)
    rg_other = client.get(base, headers=tok_other)
    rp_other = client.post(base, json={"content": "intruso"}, headers=tok_other)
    _ok("7d·anti-IDOR-403",
        rg_other.status_code == 403 and rp_other.status_code == 403,
        f"un dueño ajeno recibe 403 en GET({rg_other.status_code}) y POST({rp_other.status_code})")

    # multibyte: 5000×'ñ' (=10000 bytes UTF-8) > cap free (8192B) → truncado por BYTES (no auto-borrado)
    big = "ñ" * 5000
    rbig = client.post(base, json={"content": big}, headers=tok)
    bigid = rbig.json().get("id") if rbig.status_code == 201 else None
    listed = client.get(base, headers=tok).json().get("memories", [])
    row = next((m for m in listed if m.get("id") == bigid), None)
    survived = row is not None
    only_enye = bool(row) and set(row.get("content") or "") == {"ñ"}
    within_cap = bool(row) and int(row.get("bytes") or 0) <= 8192 and int(row.get("bytes") or 0) > 0
    _ok("7e·multibyte-sobrevive-el-cap",
        rbig.status_code == 201 and survived and only_enye and within_cap,
        f"5000×'ñ' → guardado {row.get('bytes') if row else '—'}B ≤ 8192 (byte-cap UTF-8), TODO 'ñ', no auto-borrado")


def _axis8_rollback(conn):
    _hr("8 · ROLLBACK del write-path — un fallo guardando el bus NO envenena la txn (review adversarial)")
    # Regresión del HIGH del review: si add_shared_memory/enforce_shared_memory_caps fallan (deadlock
    # de caps entre runs concurrentes del MISMO Cuarto, error transitorio) y el except NO hace
    # conn.rollback(), la txn queda ABORTADA → persist_run/finish_run crashean en cascada → el run
    # queda colgado en 'running' (zombie) y se pierde la obra + la fila del moat. Con el fix, la txn
    # se cura y el run cierra en estado TERMINAL. Simulamos el fallo envenenando la txn + levantando.
    u = repo.get_or_create_user(conn, email=f"b2h-{uuid.uuid4().hex[:8]}@toy.local", tier="basico")["id"]
    rec_cfg = _recipe()
    pid = repo.create_puppet(conn, owner_id=u, name="Núcleo Rollback", nicho="general", config=rec_cfg)["id"]
    repo.clear_shared_memories(conn, pid)

    _orig = repo.enforce_shared_memory_caps

    def _poison(c, *a, **k):
        try:                                    # aborta la txn de la conexión INTERNA del executor
            with c.cursor() as cur:
                cur.execute("SELECT * FROM __tabla_inexistente_b2__")
        except Exception:
            pass                                # queda InFailedSqlTransaction
        raise RuntimeError("simulated caps deadlock")

    repo.enforce_shared_memory_caps = _poison   # el executor la resuelve por atributo de módulo
    try:
        out = _run(rec_cfg, "TASK-8: aporte que dispara un fallo de persistencia", puppet_id=pid,
                   user_id=u, shared_items=["algo que el equipo debería saber"])
    finally:
        repo.enforce_shared_memory_caps = _orig

    rid = out.get("run_id")
    run_row = repo.get_run(conn, rid) if rid else None
    status = (run_row or {}).get("status")
    # CON el rollback del write-path (el fix): la txn se cura → el run CIERRA OK ('done', la obra
    # se salva), sólo se pierde el batch de memoria = el fail-safe correcto. SIN él: persist_run
    # corre envenenado → el handler externo la marca 'error' (obra perdida) o, sin ese backstop,
    # 'running' (zombie). Aserción con dientes: exige el resultado EXITOSO, no sólo 'no-zombie'.
    _ok("8·write-path-falla-run-cierra-ok",
        rid is not None and bool(out.get("ok")) and status == "done",
        f"run_id={str(rid)[:8]} status={status!r} out.ok={out.get('ok')} — el run cierra 'done' (obra a "
        f"salvo, sólo se pierde el batch de memoria); sin el rollback quedaría 'error'/zombie")


def main():
    conn = repo.get_conn()
    try:
        _axis1_dao(conn)
        _axis2_read(conn)
        _axis3_not_connected(conn)
        _axis4_isolation(conn)
        _axis5_write(conn)
        _axis6_premium(conn)
        _axis7_http(conn)
        _axis8_rollback(conn)
    except Exception:
        import traceback
        traceback.print_exc()
        _ok("harness-corrió", False, "excepción no atrapada (ver traceback)")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _hr("RESUMEN — ¿la MEMORIA COMPARTIDA por COMPOSICIÓN (B2) CIERRA?")
    passed = sum(1 for p, _ in results.values() if p)
    total = len(results)
    for k in sorted(results):
        p, ev = results[k]
        print(f"  {k:<32} {'✓ CIERRA' if p else '✗ NO CIERRA'}")
    print(f"\n  RESULTADO: {passed}/{total} VERDE")
    print("  VEREDICTO:", "TODO VERDE — bus compartido por Cuarto: autoría, ACL teal, aislamiento, "
          "premium y panel cierran" if passed == total and total > 0
          else "ALGO NO CIERRA — revisar antes de seguir")
    return 0 if passed == total and total > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
