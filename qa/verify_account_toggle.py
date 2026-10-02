"""TICKET 4 · TOGGLE "conoce tu cuenta" por agente — e2e in-process (probado, no razonado).

Cerebro STUBBEADO (determinista, sin shim): lo único falso es _asm._chat (responde 'stop'
al toque). El resto —executor.run_puppet_e2e, la DB real, el read-path de cuenta, el ceiling
por tier y el paso de account_pinned al motor— es REAL. Prueba:

  (1) DEFAULT (sin la llave) → la memoria de cuenta ENTRA (record.account_injected contiene el
      hecho); es el comportamiento incondicional de hoy, preservado.
  (2) memory.account_read=false → NO entra (record.account_injected ausente) + out.account_read_disabled
      = evidencia honesta.
  (3) memory.account_read=true → entra (explícito == default).
  (4) el flag NO cruza usuarios: el hecho es del owner (aislamiento intacto).

Correr:  cd product/backend && set -a && . ../../infra/.env && set +a && \
         PG_DB=puppet_ai_seguridad ./.venv/bin/python ../../qa/verify_account_toggle.py
"""
from __future__ import annotations
import json, os, sys, uuid

_HERE = os.path.dirname(os.path.abspath(__file__)); _ROOT = os.path.join(_HERE, "..")
for p in (os.path.join(_ROOT, "product", "backend"),
          os.path.join(_ROOT, "platform"),
          os.path.join(_ROOT, "platform", "assembler")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import repo, executor  # noqa: E402

CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"
FACT = "Mi ciudad es Cuenca y prefiero respuestas en euros"

_fail = []
def ok(cond, label, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + label + (("" if cond else f" — {extra}")))
    if not cond: _fail.append(label)


def _recipe(account_read=None):
    mem = {}
    if account_read is not None:
        mem["account_read"] = account_read
    r = {"schema_version": "v1",
         "meta": {"name": "Agente toggle", "nicho": "test"},
         "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                   "temperature": 0, "max_tokens": 128, "max_turns": 2},
         "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": ["add"]}},
         "framing": {"inline": "Sos un test."},
         "rag": {"enabled": False}, "keys": {}, "gates": {}}
    if mem:
        r["memory"] = mem
    return r


def _stub_stop():
    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}
    return fake_chat


def _run(recipe, user_id):
    asm = executor._asm()
    orig = asm._asm._chat
    asm._asm._chat = _stub_stop()
    try:
        return executor.run_puppet_e2e(recipe, "hola", puppet_id=None, user_id=user_id,
                                       conn=None, deadline_s=60.0)
    finally:
        asm._asm._chat = orig


conn = repo.get_conn()
uid = repo.get_or_create_user(conn, f"toggle-{uuid.uuid4().hex[:8]}@test.local", tier="tecnico")["id"]
uid_other = repo.get_or_create_user(conn, f"toggle-other-{uuid.uuid4().hex[:8]}@test.local", tier="tecnico")["id"]
repo.clear_account_memories(conn, uid)
repo.add_account_memory(conn, owner_id=uid, content=FACT, source="user", pinned=True,
                        meta={"provenance": "hecho"})

try:
    print("== 1 · DEFAULT (sin la llave) → la cuenta ENTRA ==")
    o1 = _run(_recipe(None), uid)
    inj1 = (o1.get("record") or {}).get("account_injected") or ""
    ok("Cuenca" in inj1, "default: el hecho de cuenta entró al framing (account_injected)", inj1[:80])
    ok(not o1.get("account_read_disabled"), "default: sin flag account_read_disabled")

    print("== 2 · account_read=false → NO entra + evidencia ==")
    o2 = _run(_recipe(False), uid)
    inj2 = (o2.get("record") or {}).get("account_injected")
    ok(not inj2, "OFF: account_injected ausente (no se inyectó la cuenta)", str(inj2)[:80])
    ok(o2.get("account_read_disabled") is True, "OFF: out.account_read_disabled=True (evidencia honesta)")

    print("== 3 · account_read=true → entra (explícito == default) ==")
    o3 = _run(_recipe(True), uid)
    inj3 = (o3.get("record") or {}).get("account_injected") or ""
    ok("Cuenca" in inj3, "ON explícito: el hecho entró", inj3[:80])
    ok(not o3.get("account_read_disabled"), "ON explícito: sin flag disabled")

    print("== 4 · aislamiento: OTRO usuario nunca ve el hecho ==")
    o4 = _run(_recipe(None), uid_other)
    inj4 = (o4.get("record") or {}).get("account_injected") or ""
    ok("Cuenca" not in inj4, "otro usuario NO ve el hecho de cuenta ajeno (invariante #4)", inj4[:80])
finally:
    repo.clear_account_memories(conn, uid)
    conn.close()

print()
if _fail:
    print(f"✗ {len(_fail)} fallas:"); [print("   -", f) for f in _fail]; sys.exit(1)
print("✓ TICKET 4 · TOGGLE VERDE: default inyecta · false apaga+evidencia · true explícito · aislado")
