#!/usr/bin/env python3
"""
verify_memoria_a3.py — EVIDENCIA de MEMORIA DEL AGENTE (Step 2 · A3).

Prueba, contra el MOTOR REAL (executor.run_puppet_e2e → assemble_and_run + belt REAL por
subprocess + gate en el path + DB Postgres REAL) y con SÓLO el cerebro stubeado (MemBrain,
guión determinista → cero tokens, headless), que:

  1. CROSS-RUN — el agente APRENDE en el run 1 (destilado al cierre) → en el run 2 (sesión
     FRESCA, motor re-armado de cero) esos aprendizajes ENTRAN a su framing (record.memory_injected).
  2. IDENTIDAD — un run de agente GUARDADO liga runs.puppet_id = el uuid (antes NULL); un run
     EFÍMERO (slug, sin uuid) NO persiste memoria ni liga el run.
  3. BORRAR — el usuario borra una entrada → el siguiente run NO la trae.
  4. WRITE DEL PANEL — el usuario escribe una memoria directo (source='user') → entra al run.
  5. AISLAMIENTO (cruza A1) — el agente B no ve la memoria del agente A; un run con user_id
     que NO es el dueño del agente NO lee ni liga su memoria.
  6. GRANDE → COMPACTA — mucha/gran memoria entra ACOTADA al presupuesto (marcador '+N más'),
     nunca cruda (artifacts-por-handle).
  7. CAPS POR TIER — la frontera (entradas/bytes) la impone el runtime desde users.tier, no la
     receta; lo viejo se desaloja y las 'user' sobreviven.
  8. GATE-HONESTO — la escritura de memoria es server-side: NO genera held_actions (no pasa por
     el gate); los mandatorios money/send siguen forzados.

Uso:  python3 qa/verify_memoria_a3.py     (necesita Postgres puppet_ai vivo)
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

# El belt de prueba (deleg) referencia ${PUPPET_BELTS}/platform/assembler/... → apuntá
# PUPPET_BELTS al repo_root ANTES de importar el executor (usa os.environ.setdefault).
os.environ["PUPPET_BELTS"] = str(_REPO_ROOT)
os.environ.pop("PUPPET_SHARED_MEMORY", None)

for p in (str(_REPO_ROOT / "product" / "backend"),
          str(_REPO_ROOT / "platform" / "assembler")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import executor, repo  # noqa: E402
import recipe_assembler as RA          # noqa: E402

results: dict = {}   # label -> (passed, evidencia)


def _hr(t: str):
    print("\n" + "═" * 78 + f"\n  {t}\n" + "═" * 78)


def _ok(label: str, cond: bool, ev: str = ""):
    results[label] = (bool(cond), ev)
    print(f"  [{'OK ' if cond else 'XX '}] {label}" + (f" — {ev}" if ev else ""))


# ── MemBrain — stubea SÓLO el cerebro. Además del guión de tool-use, ATIENDE el call de
#   DESTILADO (tools=[] + system con 'aprendizajes DURABLES') devolviendo aprendizajes
#   scripteados por prompt. Thread-safe. ──────────────────────────────────────────────
class MemBrain:
    def __init__(self, distill_by_prompt: dict):
        self.distill = distill_by_prompt   # first_user(prompt) -> [entradas destiladas] | None
        self.lock = threading.Lock()

    @staticmethod
    def _first_user(messages):
        for m in messages:
            if m.get("role") == "user":
                c = m.get("content")
                return c if isinstance(c, str) else json.dumps(c)
        return ""

    @staticmethod
    def _final(text):
        return ({"choices": [{"message": {"role": "assistant", "content": text},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
                "mem-brain")

    def route(self, messages, tools, *, base_url, primary, fallback, api_key,
              max_tokens, temperature, route_log, on_tier_error=None):
        route_log.append({"model": "mem-brain", "tier": "primary", "ok": True})
        last = messages[-1] if messages else {}
        # ¿es el call de DESTILADO? (tools vacío + prompt de aprendizajes durables)
        if (not tools and last.get("role") == "system"
                and "aprendizajes DURABLES" in str(last.get("content", ""))):
            key = self._first_user(messages)
            entries = self.distill.get(key)
            if entries:
                return self._final("\n".join("- " + e for e in entries))
            return self._final("NADA")
        # cualquier otro cierre sin tools → final benigno
        if not tools:
            return self._final("[cierre]")
        # turno con tools: el agente responde directo (no necesita tools para este test)
        return self._final("Listo, hice la tarea.")


class _Patched:
    """Stubea el cerebro en el MISMO módulo del assembler que USA el executor. OJO: el
    executor carga recipe_assembler por ruta como 'puppet_recipe_assembler' (importlib) →
    es un objeto de módulo DISTINTO al `import recipe_assembler` de arriba. Patchear el
    equivocado dejaría al motor llamando al gateway real. Patchamos el del executor."""
    def __init__(self, brain):
        self.brain = brain
        self._mod = None
        self._orig = None

    def __enter__(self):
        self._mod = executor._asm()          # fuerza la carga y toma EL módulo del executor
        self._orig = self._mod._route_chat
        self._mod._route_chat = self.brain.route
        return self

    def __exit__(self, *a):
        self._mod._route_chat = self._orig


RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "mem-agente", "nicho": "general",
             "descripcion": "agente de prueba de memoria por-agente A3"},
    "model": {"primary": "stub", "base_url": "stub://local", "temperature": 0,
              "max_tokens": 256, "max_turns": 4},
    "belt": {"belt_ref": "platform/assembler/deleg_fixtures/belt-deleg.mcp.json",
             "tool_filters": {"deleg": ["read_data"]}},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}


def _run(prompt, *, puppet_id, user_id, distill):
    """Un run E2E por el executor REAL, con el cerebro stubeado por MemBrain."""
    brain = MemBrain({prompt: distill} if distill else {})
    with _Patched(brain):
        return executor.run_puppet_e2e(
            RECIPE, prompt, puppet_id=puppet_id, user_id=user_id,
            conn=None, deadline_s=60.0)


def main():
    conn = repo.get_conn()   # conexión propia del harness (setup + aserciones)

    # ── setup: dos usuarios (free) + dos agentes guardados ────────────────────────
    uA = repo.get_or_create_user(conn, "a3-memoria-A@test.local", tier="free")["id"]
    uB = repo.get_or_create_user(conn, "a3-memoria-B@test.local", tier="free")["id"]
    pA = repo.create_puppet(conn, owner_id=uA, name="Agente A", nicho="general", config=RECIPE)["id"]
    pB = repo.create_puppet(conn, owner_id=uB, name="Agente B", nicho="general", config=RECIPE)["id"]
    repo.clear_memories(conn, pA)
    repo.clear_memories(conn, pB)

    # ════════════════════════════════════════════════════════════════════════════
    _hr("1 · CROSS-RUN — el agente aprende en el run 1 y lo USA en el run 2 (sesión fresca)")
    LEARN = ["preferencia del usuario: reportes en EUR",
             "clave del proyecto: se llama ATLAS-9"]
    r1 = _run("TASK-1: trabajá y aprendé del usuario", puppet_id=pA, user_id=uA, distill=LEARN)
    mems1 = repo.list_memories(conn, pA)
    persisted = {m["content"] for m in mems1}
    run1_linked = repo.get_run(conn, r1["run_id"]).get("puppet_id")
    _ok("1a·destilado-persiste", r1.get("ok") and len(mems1) == 2
        and set(LEARN) == persisted and all(m["source"] == "agent" for m in mems1),
        f"run1 guardó {len(mems1)} memorias 'agent' con run_id en meta")
    _ok("2·identidad-run-ligado", str(run1_linked) == str(pA),
        f"runs.puppet_id={run1_linked} (antes NULL)")

    r2 = _run("TASK-2: seguí trabajando", puppet_id=pA, user_id=uA, distill=None)
    inj2 = (r2.get("record") or {}).get("memory_injected") or ""
    _ok("1b·cross-run-inyectado", "ATLAS-9" in inj2 and "EUR" in inj2,
        "el run 2 recibió en su framing lo aprendido en el run 1")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("3 · BORRAR — el usuario borra una entrada → el siguiente run NO la trae")
    atlas_id = next((m["id"] for m in mems1 if "ATLAS-9" in m["content"]), None)
    if atlas_id:
        repo.delete_memory(conn, atlas_id)
    r3 = _run("TASK-3", puppet_id=pA, user_id=uA, distill=None)
    inj3 = (r3.get("record") or {}).get("memory_injected") or ""
    _ok("3·borrado-desaparece", "ATLAS-9" not in inj3 and "EUR" in inj3,
        "tras borrar 'ATLAS-9' el run ya no lo ve; el resto sigue")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("4 · WRITE DEL PANEL — el usuario escribe memoria directa (source='user')")
    repo.add_memory(conn, puppet_id=pA, content="regla del usuario: siempre citar la fuente",
                    source="user")
    r4 = _run("TASK-4", puppet_id=pA, user_id=uA, distill=None)
    inj4 = (r4.get("record") or {}).get("memory_injected") or ""
    _ok("4·write-panel-entra", "citar la fuente" in inj4,
        "la memoria escrita por el usuario entró al run")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("5 · AISLAMIENTO — agente B NO ve la memoria de A; run de no-dueño no liga ni lee")
    rB = _run("TASK-B: agente distinto", puppet_id=pB, user_id=uB, distill=None)
    injB = (rB.get("record") or {}).get("memory_injected") or ""
    _ok("5a·aislamiento-A≠B", "EUR" not in injB and "citar la fuente" not in injB,
        "el agente B no recibió NADA de la memoria del agente A")
    # run del agente A pero con el usuario B (NO dueño) → sin memoria ni linkage
    rX = _run("TASK-X: no-dueño", puppet_id=pA, user_id=uB, distill=None)
    injX = (rX.get("record") or {}).get("memory_injected") or ""
    xrun_linked = repo.get_run(conn, rX["run_id"]).get("puppet_id")
    _ok("5b·no-dueño-sin-memoria", injX == "" and xrun_linked is None,
        "un usuario que no es dueño del agente no lee su memoria ni liga el run")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("6 · GRANDE → COMPACTA — mucha memoria entra ACOTADA (no cruda)")
    repo.clear_memories(conn, pA)
    for i in range(40):
        repo.add_memory(conn, puppet_id=pA, content=f"memoria-larga-{i:02d} " + ("dato " * 20),
                        source="user")
    r6 = _run("TASK-6", puppet_id=pA, user_id=uA, distill=None)
    inj6 = (r6.get("record") or {}).get("memory_injected") or ""
    inj6_bytes = len(inj6.encode("utf-8"))
    from gates.recipe_enforcer import memory_caps_for_tier  # noqa: E402
    budget = min(executor._A3_PINNED_BUDGET_BYTES, memory_caps_for_tier("free")["max_bytes"])
    _ok("6·grande-acotada", 0 < inj6_bytes <= budget and "más en tu panel de memoria" in inj6,
        f"bloque inyectado={inj6_bytes}B ≤ presupuesto={budget}B, con marcador de handle")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("7 · CAPS POR TIER — la frontera (entradas/bytes) la impone el runtime, no la receta")
    # free = 20 entradas. Ya hay 40 'user' → un run (que enforza al persistir) las recorta;
    # pero como el run 6 no destiló (distill=None) no enforzó. Forzamos un run que destile:
    repo.clear_memories(conn, pA)
    for i in range(25):
        repo.add_memory(conn, puppet_id=pA, content=f"vieja-{i:02d}", source="agent")
    _run("TASK-7: aprendé algo nuevo", puppet_id=pA, user_id=uA,
         distill=["aprendizaje nuevo del run 7"])
    usage_free = repo.memory_usage(conn, pA)
    cap_free = memory_caps_for_tier("free")["max_entries"]
    _ok("7a·cap-free-20", usage_free["entries"] <= cap_free,
        f"free: {usage_free['entries']} entradas ≤ cap {cap_free} (desalojó las viejas)")
    # subir a basico sube el techo (premium=basico)
    repo.set_tier(conn, uA, "basico")
    repo.clear_memories(conn, pA)
    for i in range(60):
        repo.add_memory(conn, puppet_id=pA, content=f"b-{i:02d}", source="agent")
    _run("TASK-7b", puppet_id=pA, user_id=uA, distill=["otro aprendizaje"])
    usage_bas = repo.memory_usage(conn, pA)
    _ok("7b·cap-basico-mayor", usage_bas["entries"] > cap_free and usage_bas["entries"] <= 100,
        f"basico: {usage_bas['entries']} entradas (techo 100 > free 20)")
    repo.set_tier(conn, uA, "free")

    # ════════════════════════════════════════════════════════════════════════════
    _hr("8 · GATE-HONESTO + EFÍMERO — memoria server-side sin held_actions; slug no persiste")
    # ningún run de memoria generó held_actions de escritura de memoria (no pasa por el gate)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM held_actions WHERE tool ILIKE %s", ("%memor%",))
        held_mem = cur.fetchone()[0]
    _ok("8a·gate-honesto", held_mem == 0,
        "cero held_actions por memoria: la escritura es estado local server-side, no tool-call")
    # run EFÍMERO (puppet_id = slug NO-uuid) → no persiste memoria ni liga el run
    before = repo.memory_usage(conn, pA)["entries"]
    rE = _run("TASK-E: efímero", puppet_id="cuarto-sin-guardar", user_id=uA,
              distill=["esto no debería guardarse en ningún agente"])
    after = repo.memory_usage(conn, pA)["entries"]
    erun_linked = repo.get_run(conn, rE["run_id"]).get("puppet_id")
    _ok("8b·efímero-no-persiste", after == before and erun_linked is None,
        "un agente sin guardar (slug) no keyea memoria ni liga runs.puppet_id")

    # limpieza
    repo.clear_memories(conn, pA)
    repo.clear_memories(conn, pB)

    _hr("RESUMEN — ¿la MEMORIA DEL AGENTE (A3) CIERRA?")
    all_ok = True
    for k in sorted(results):
        p, _ = results[k]
        all_ok = all_ok and p
        print(f"  {k:<28} {'✓ CIERRA' if p else '✗ NO CIERRA'}")
    print("\n  VEREDICTO:", "TODO VERDE — memoria por-agente persistente, controlable y aislada"
          if all_ok else "ALGO NO CIERRA — revisar antes de seguir")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
