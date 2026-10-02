#!/usr/bin/env python3
"""
selftest_byo.py — DONE-BAR de C3 (BYO-MCP), verificado VIVO y honesto (cero teatro).

Recorre el camino COMPLETO de "pegá tu MCP → Sumar", contra sistemas reales:

  1. Pega una URL de MCP PÚBLICO real (por defecto DeepWiki) → byo_mcp.forge_byo:
       validar (conectar + listar tools) → forjar belt → registrar en un puppet.
  2. El puppet es EFÍMERO (creado en el Postgres real, borrado al final).
  3. Corre el agente con el MOTOR real (recipe_assembler.assemble_and_run) — el MISMO que
     usa la Sala — con un pedido que necesita una tool de ESE MCP.
  4. COMPRUEBA, desde el record real del run, que el agente LLAMÓ una tool del MCP propio y
     que el resultado SALIÓ del MCP remoto (marcadores reales), no de la imaginación del LLM.

Falla ruidoso si algo no es real. NO deja basura: borra el puppet y los belts de prueba.

Uso:
    LITELLM_KEY=<groq_key> python platform/inspection/selftest_byo.py [mcp_url]
(la key de cognición sale de env LITELLM_KEY/GROQ_API_KEY o de infra/.env bajo repo_root.)
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASM_DIR = _REPO_ROOT / "platform" / "assembler"
for _p in (str(_REPO_ROOT / "platform"), str(_REPO_ROOT / "product" / "backend"), str(_ASM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inspection import byo_mcp, registry  # noqa: E402

DEFAULT_MCP_URL = "https://mcp.deepwiki.com/mcp"
TEST_USER_TAG = "selftest-byo"
# pedido que OBLIGA a usar una tool del MCP propio (DeepWiki) sobre un repo conocido:
TEST_PROMPT = (
    "Usa tu herramienta read_wiki_structure para obtener la lista de temas de documentación "
    "del repositorio 'modelcontextprotocol/python-sdk'. Devolveme esa lista tal cual, sin inventar."
)
# marcadores que SOLO aparecen si el contenido vino del MCP remoto real (no del LLM):
REAL_MARKERS = ("Available pages", "Transport", "FastMCP", "Overview")


def _load_assembler():
    spec = importlib.util.spec_from_file_location(
        "puppet_recipe_assembler_selftest", _ASM_DIR / "recipe_assembler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _resolve_cognition_key() -> str:
    import os
    for var in ("LITELLM_KEY", "GROQ_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    env = _REPO_ROOT / "infra" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            for var in ("LITELLM_KEY", "GROQ_API_KEY"):
                if line.startswith(var + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _base_recipe() -> dict:
    """Receta v1 válida con una base keyless (calc) — el BYO se registra ENCIMA por belt_refs[]."""
    return {
        "schema_version": "v1",
        "meta": {"name": "selftest-byo", "nicho": "byo"},
        "model": {
            "primary": "llama-3.3-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1",
            "temperature": 0, "max_tokens": 1024, "max_turns": 6,
        },
        "belt": {
            "belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
            "tool_filters": {"calc": ["add"]},
        },
        "rag": {"enabled": False, "mode": "manual"},
        "keys": {},
        "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
    }


def _fail(msg: str) -> None:
    print(f"\n❌ FALLÓ: {msg}")
    sys.exit(1)


def main() -> None:
    import os
    mcp_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MCP_URL
    key = _resolve_cognition_key()
    if not key:
        _fail("no hay key de cognición (LITELLM_KEY/GROQ_API_KEY ni infra/.env)")
    os.environ["LITELLM_KEY"] = key  # que assemble_and_run la tome sin importar repo_root

    r = registry.repo()
    conn = r.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT owner_id FROM puppets ORDER BY created_at DESC LIMIT 1")
    owner_row = cur.fetchone()
    if not owner_row:
        _fail("no hay ningún owner en la DB para crear el puppet de prueba")
    owner_id = str(owner_row[0])

    puppet = r.create_puppet(conn, owner_id=owner_id, name="selftest-byo",
                             nicho="byo", config=_base_recipe(), status="draft")
    puppet_id = str(puppet["id"])
    print(f"① puppet efímero creado: {puppet_id} (owner {owner_id})")

    try:
        # ── 2) PEGÁ TU MCP → SUMAR (validar + forjar + registrar) ──────────────
        print(f"② pegando MCP público real: {mcp_url}")
        res = byo_mcp.forge_byo(transport="http", url=mcp_url,
                                user_id=TEST_USER_TAG, puppet_id=puppet_id,
                                label="DeepWiki", conn=conn)
        if not res.get("validated"):
            _fail("el MCP no validó")
        print(f"   ✓ validado: server={res['server']} tools={res['tools']}")
        if not res.get("registered"):
            _fail("el belt no se registró en el puppet")
        print(f"   ✓ registrado en la receta: belt_refs={res['belt_refs']}")
        print(f"   ✓ tool_filters[{res['server']}]={res['tool_filters'].get(res['server'])}")

        # ── 3) USAR EN LA SALA (motor real) ────────────────────────────────────
        fresh = r.get_puppet(conn, puppet_id)
        recipe = fresh["config"]
        asm = _load_assembler()
        print("③ corriendo el agente con el MOTOR real (assemble_and_run)…")
        t0 = time.time()
        record = asm.assemble_and_run(recipe, TEST_PROMPT, repo_root=_REPO_ROOT,
                                      deadline_s=150.0)
        dt = time.time() - t0
        print(f"   run terminó en {dt:.1f}s · model_final={record.get('model_final')} "
              f"· ok={record.get('ok')}")

        # ── 4) VERIFICAR (desde el record real, no self-report) ────────────────
        cabled = record.get("tools_cabled") or []
        byo_tools = set(res["tools"])
        cabled_byo = [t for t in cabled if t in byo_tools]
        if not cabled_byo:
            _fail(f"ninguna tool del MCP propio quedó cableada (tools_cabled={cabled})")
        print(f"   ✓ tools del MCP propio cableadas: {cabled_byo}")

        calls = record.get("tool_calls") or []
        byo_calls = [c for c in calls if c.get("tool") in byo_tools]
        if not byo_calls:
            _fail(f"el agente NO llamó ninguna tool del MCP propio (tool_calls={[c.get('tool') for c in calls]})")
        print(f"   ✓ el agente LLAMÓ de verdad: {[c['tool'] for c in byo_calls]}")

        joined = "\n".join(str(c.get("result", "")) for c in byo_calls)
        hits = [m for m in REAL_MARKERS if m in joined]
        if not hits:
            _fail("el resultado de la tool NO trae marcadores del MCP remoto real "
                  f"(¿fabricado?). primeros 200 chars: {joined[:200]!r}")
        print(f"   ✓ resultado REAL del MCP remoto (marcadores: {hits})")
        print(f"   muestra del resultado: {joined[:160]!r}")

        print("\n✅ DONE-BAR C3 VERDE: pegaste una URL de MCP público real → el agente en la "
              "Sala llamó de verdad una tool de ESE MCP y obtuvo un resultado real.")
    finally:
        # limpieza: borrar el puppet efímero + los belts de prueba
        try:
            cur.execute("DELETE FROM puppets WHERE id = %s", (puppet_id,))
            conn.commit()
            print(f"\n🧹 puppet efímero {puppet_id} borrado")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  no se pudo borrar el puppet {puppet_id}: {e}")
        conn.close()
        test_belts = registry.SYNTH_BELTS_DIR / TEST_USER_TAG
        if test_belts.exists():
            shutil.rmtree(test_belts, ignore_errors=True)
            print(f"🧹 belts de prueba borrados: {test_belts}")


if __name__ == "__main__":
    main()
