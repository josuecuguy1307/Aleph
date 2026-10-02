#!/usr/bin/env python3
"""ORDEN 4 · TEST ESPEJO de HERENCIA/COMPOSICIÓN (probado, no razonado) contra el MOTOR REAL.

Cerebro stubeado (guión determinista, cero tokens) + executor REAL + Postgres REAL. Dos partes:

  PARTE A · HERENCIA [solo pericia] al REUSAR (standalone, _depth==0):
    un agente con 1 pericia + 2 episódicas RELEVANTES corre con recipe.memory.inherit='skill_only'.
    Aunque el pedido matchee las episódicas (Nordvik), al framing entra SÓLO la pericia — la herencia
    acota el conjunto elegible ANTES del recall. (record.memory_injected = sólo skill.)

  PARTE B · el HIJO en COMPOSICIÓN (miembro delegado, _depth==1) → framing SIN episódica NI cuenta:
    el dueño tiene un hecho de CUENTA; el bus se siembra [solo pericia] (sólo la pieza skill, vía
    seed_shared_bus); el núcleo delega a un hijo miembro. El hijo lee el BUS (su único canal
    transferible) → ve la pericia, NO la episódica (no sembrada), NO el hecho de cuenta (no sembrable
    + gate _depth). Es la promesa de persona usuaria: la herencia jamás arrastra cuenta a un agente compartido.

Correr:  cd product/backend && set -a && . ../../infra/.env && set +a && \
         ./.venv/bin/python ../../qa/verify_herencia_espejo_e2e.py
"""
from __future__ import annotations
import os, sys, json, threading, uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
os.environ["PUPPET_BELTS"] = str(_REPO)
os.environ.pop("PUPPET_SHARED_MEMORY", None)
try:
    if not os.environ.get("PUPPET_DB_ENC_KEY") and not (
            _REPO / "platform" / "db" / "secrets" / "enc.key").exists():
        from cryptography.fernet import Fernet
        os.environ["PUPPET_DB_ENC_KEY"] = Fernet.generate_key().decode("ascii")
except Exception:
    pass
for p in (str(_REPO / "platform" / "assembler"), str(_REPO / "platform" / "gates"),
          str(_REPO / "platform"), str(_REPO / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import executor, repo  # noqa: E402

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        _fail.append(label)


class MirrorBrain:
    """Guión determinista. El PADRE delega a 'memoria_sub'; el HIJO y el standalone cierran directo.
    Los destilados (system sin tools) devuelven NADA (no es lo que probamos)."""
    def __init__(self):
        self.lock = threading.Lock()

    @staticmethod
    def _final(text):
        return ({"choices": [{"message": {"role": "assistant", "content": text},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}, "mirror")

    @staticmethod
    def _delegate(fn, args):
        tcs = [{"id": "call_0", "type": "function",
                "function": {"name": fn, "arguments": json.dumps(args)}}]
        return ({"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": tcs},
                              "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}, "mirror")

    def route(self, messages, tools, *, base_url, primary, fallback, api_key,
              max_tokens, temperature, route_log, on_tier_error=None, **_kw):
        route_log.append({"model": "mirror", "tier": "primary", "ok": True})
        with self.lock:
            last = messages[-1] if messages else {}
            content = str(last.get("content", ""))
            # destilado server-side (system, sin tools) → NADA
            if not tools and last.get("role") == "system":
                return self._final("NADA")
            # primer user msg (task) determina el rol
            first_user = next((m for m in messages if m.get("role") == "user"), {})
            task = str(first_user.get("content", ""))
            if "DELEGA-AL-HIJO" in task and tools:
                # ¿ya delegué? si el último es un tool result, cerrá; si no, delegá.
                if last.get("role") == "tool":
                    return self._final("delegué al hijo y cerré")
                return self._delegate("memoria_sub", {"task": "HIJO-LEE-EL-BUS"})
            # standalone (parte A) o hijo (parte B) → cierre directo
            return self._final("listo")


class _Patched:
    def __init__(self, brain):
        self.brain = brain; self._mod = None; self._orig = None
    def __enter__(self):
        self._mod = executor._asm(); self._orig = self._mod._route_chat
        self._mod._route_chat = self.brain.route; return self
    def __exit__(self, *a):
        self._mod._route_chat = self._orig


CALC_BELT = "platform/assembler/fixtures/belt-calc.mcp.json"

def _standalone_recipe(inherit):
    return {"schema_version": "v1", "meta": {"name": "Reuso A", "nicho": "general"},
            "model": {"primary": "stub", "base_url": "stub://local", "temperature": 0,
                      "max_tokens": 256, "max_turns": 3},
            "belt": {"belt_ref": CALC_BELT, "tool_filters": {"calc": ["add"]}},
            "memory": {"inherit": inherit},
            "framing": {"inline": "Sos un asistente. Respondé breve."},
            "rag": {"enabled": False}, "gates": {"money_touch": "needs_ok", "send": "needs_ok"}}

def _parent_recipe():
    # núcleo de composición con bus + delegación a memoria_sub (child_memoria.json → slug 'memoria_sub')
    return {"schema_version": "v1", "meta": {"name": "Equipo", "nicho": "general"},
            "model": {"primary": "stub", "base_url": "stub://local", "temperature": 0,
                      "max_tokens": 256, "max_turns": 4},
            "belt": {"belt_ref": "platform/assembler/deleg_fixtures/belt-deleg.mcp.json",
                     "agent_refs": ["platform/assembler/deleg_fixtures/child_memoria.json"],
                     "tool_filters": {"deleg": ["read_data"]}},
            "memory": {"shared": True, "ref": "product/belts/memoria-compartida.mcp.json"},
            "rag": {"enabled": False}, "gates": {"money_touch": "needs_ok", "send": "needs_ok"}}


conn = repo.get_conn()
u = repo.get_or_create_user(conn, f"heren-{uuid.uuid4().hex[:8]}@test.local", tier="tecnico")["id"]
brain = MirrorBrain()
try:
    # ══ PARTE A · HERENCIA [solo pericia] standalone ══════════════════════════════════════════
    print("== PARTE A · heredar [solo pericia] → al framing entra SÓLO la pericia (episódica fuera) ==")
    pA = repo.create_puppet(conn, owner_id=u, name="Reuso A", nicho="general",
                            config=_standalone_recipe("skill_only"))["id"]
    repo.clear_memories(conn, pA)
    repo.add_memory(conn, puppet_id=pA, content="Prefiere respuestas en español rioplatense (voseo)",
                    source="agent", meta={"kind": "skill", "provenance": "hecho"})
    repo.add_memory(conn, puppet_id=pA, content="El deadline del proyecto NORDVIK es el 30 de agosto",
                    source="agent", meta={"kind": "episodica", "provenance": "hecho", "run_id": "run-X"})
    repo.add_memory(conn, puppet_id=pA, content="El plano de NORDVIK va en acero 4140",
                    source="agent", meta={"kind": "episodica", "provenance": "hecho", "run_id": "run-X"})
    with _Patched(brain):
        outA = executor.run_puppet_e2e(_standalone_recipe("skill_only"),
                                       "¿Cuál es el deadline de NORDVIK?",
                                       puppet_id=pA, user_id=u, conn=None, deadline_s=90.0)
    injA = (outA.get("record") or {}).get("memory_injected") or ""
    print("    memory_injected:", injA[:120].replace("\n", " "))
    ok(outA.get("ok"), "el run standalone cerró OK")
    ok("voseo" in injA or "rioplatense" in injA, "la PERICIA entró al framing")
    ok("NORDVIK" not in injA.upper(), "NINGUNA episódica entró (aunque el pedido matcheaba Nordvik) — herencia acotó")

    # control: SIN herencia (continuación normal) la episódica relevante SÍ entra → prueba que el
    # filtro es la herencia, no otra cosa.
    with _Patched(brain):
        outN = executor.run_puppet_e2e(_standalone_recipe(None),
                                       "¿Cuál es el deadline de NORDVIK?",
                                       puppet_id=pA, user_id=u, conn=None, deadline_s=90.0)
    injN = (outN.get("record") or {}).get("memory_injected") or ""
    ok("NORDVIK" in injN.upper(), "CONTROL sin herencia: la episódica relevante SÍ entra (recall orden-3)")

    # ── REGRESIÓN review orden 6 (MEDIUM) · la captura EXPLÍCITA del usuario SOBREVIVE a 'skill_only' ──
    # Un 'skill_only' PERSISTIDO en la receta corre en el A3-read de CADA corrida (no sólo al reusar).
    # apply_inheritance va ANTES de select_relevant_memories → si dropeara source='user', el always_sources
    # del recall ya no podría rescatar el "recordá esto". La doble-llave debe regir igual: source='user'
    # viaja como la pericia bajo herencia; sólo lo destilado (source='agent') se poda.
    print("== REGRESIÓN · 'recordá esto' (source='user') sobrevive a 'skill_only' persistido en TODO run ==")
    repo.add_memory(conn, puppet_id=pA, content="RECORDA-ESTO-VERDE: mi color favorito es el verde",
                    source="user", pinned=True, meta={"explicit": True})
    with _Patched(brain):
        outU = executor.run_puppet_e2e(_standalone_recipe("skill_only"),
                                       "una pregunta cualquiera sin relación",
                                       puppet_id=pA, user_id=u, conn=None, deadline_s=90.0)
    injU = (outU.get("record") or {}).get("memory_injected") or ""
    print("    memory_injected:", injU[:140].replace("\n", " "))
    ok("VERDE" in injU.upper(), "la captura EXPLÍCITA del usuario SOBREVIVE a 'skill_only' persistido (doble-llave)")
    ok("voseo" in injU or "rioplatense" in injU, "la pericia también sigue viajando bajo 'skill_only'")
    ok("NORDVIK" not in injU.upper(), "la episódica DESTILADA sigue fuera (sólo pericia + source='user')")

    # ══ PARTE B · el HIJO en composición → sin episódica NI cuenta ════════════════════════════
    print("== PARTE B · hijo delegado lee el bus sembrado [solo pericia] → sin episódica NI cuenta ==")
    # hecho de CUENTA del dueño (existe, pero NO debe llegar al hijo)
    repo.clear_account_memories(conn, u)
    repo.add_account_memory(conn, owner_id=u, content="HECHO-DE-CUENTA: el usuario vive en Quito")
    # agente fuente con 1 pericia + 1 episódica; sólo la pericia se elige para el bus
    pSRC = repo.create_puppet(conn, owner_id=u, name="Fuente", nicho="general", config={})["id"]
    repo.clear_memories(conn, pSRC)
    sk = repo.add_memory(conn, puppet_id=pSRC, content="PERICIA-SEMBRADA: medí siempre en milímetros",
                         source="agent", meta={"kind": "skill"})["id"]
    repo.add_memory(conn, puppet_id=pSRC, content="EPISODICA-NO-SEMBRADA: el cliente Zephyr está en Lima",
                    source="agent", meta={"kind": "episodica", "run_id": "run-Z"})
    pTEAM = repo.create_puppet(conn, owner_id=u, name="Equipo", nicho="general",
                               config=_parent_recipe())["id"]
    repo.clear_shared_memories(conn, pTEAM)
    seed = repo.seed_shared_bus(conn, composition_id=pTEAM, owner_id=u, memory_ids=[sk],
                                max_entries=200, max_bytes=131072)
    ok(len(seed["seeded"]) == 1, "[solo pericia] → 1 pieza sembrada al bus (la episódica NO se eligió)")

    with _Patched(brain):
        outB = executor.run_puppet_e2e(_parent_recipe(), "DELEGA-AL-HIJO",
                                       puppet_id=pTEAM, user_id=u, conn=None, deadline_s=120.0)
    subs = (outB.get("record") or {}).get("sub_runs") or []
    ok(len(subs) >= 1, f"el padre delegó → hay {len(subs)} sub_run(s) (el hijo corrió)")
    child = subs[0] if subs else {}
    cinj = child.get("shared_memory_injected") or ""
    print("    hijo · shared_memory_injected:", cinj[:120].replace("\n", " "))
    ok("PERICIA-SEMBRADA" in cinj, "el HIJO lee la pericia sembrada (bus)")
    ok("EPISODICA-NO-SEMBRADA" not in cinj and "Zephyr" not in cinj,
       "la episódica NO sembrada NO aparece en el framing del hijo")
    ok("HECHO-DE-CUENTA" not in cinj and "Quito" not in cinj,
       "el hecho de CUENTA NUNCA aparece en el framing del hijo (bus)")
    # canales gated _depth==0: el hijo (depth 1) no recibe A3 privada NI cuenta
    ok(not (child.get("account_injected") or "").strip() if isinstance(child.get("account_injected"), str)
       else not child.get("account_injected"),
       "el hijo NO tiene account_injected (cuenta gated _depth==0)")
    ok(not (child.get("memory_injected") or "").strip() if isinstance(child.get("memory_injected"), str)
       else not child.get("memory_injected"),
       "el hijo NO tiene memory_injected (A3 privada gated _depth==0)")
    # y el bus tampoco contiene la cuenta (no sembrable) — prueba directa sobre la tabla
    busrows = repo.list_shared_memories(conn, pTEAM)
    ok(not any("HECHO-DE-CUENTA" in (b.get("content") or "") for b in busrows),
       "el bus de la composición NO contiene el hecho de cuenta (no sembrable)")

    print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
finally:
    for _p in ("pA", "pSRC", "pTEAM"):
        try: repo.clear_memories(conn, locals().get(_p))
        except Exception: pass
    try:
        repo.clear_account_memories(conn, u)
        repo.clear_shared_memories(conn, locals().get("pTEAM"))
    except Exception:
        pass
    conn.close()
sys.exit(1 if _fail else 0)
