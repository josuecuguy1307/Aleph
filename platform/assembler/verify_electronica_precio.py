#!/usr/bin/env python3
"""
verify_electronica_precio.py — verificación REAL del conector PRECIO+STOCK de electrónica.

Tres niveles, todo contra cosas vivas (cero stub, cero mock):

  L1 · DATO REAL (runtime MCPServer)
      Arranca precio_server.py con el MISMO cliente MCP que usa :8080
      (platform/assembler.MCPServer: subprocess stdio + JSON-RPC 2.0) y llama
      quote_component / quote_bom. Imprime el dato CRUDO del catálogo (part, precio,
      stock, distribuidor) — si fuera inventado, no coincidiría con el catálogo.

  L2 · E2E CON OPUS (assemble_and_run + brain shim :8923)
      El puppet de electrónica corre por el path de PROD (belt_ref → enforcer → loop)
      con el cerebro Opus real (shim local, sin crédito). Verifica que el agente LLAMA
      la tool de precio, arma el BOM cotizado, y que model_final=claude-code-opus-4.8 /
      degraded=null.

  L3 · CAPTURA DEL ARTIFACT (executor)
      Importa _capture_rich_obra del executor y confirma que el bom.planilla.json que
      el run dejó en el workdir se surfacea como obra type=planilla → La Sala lo rinde.

Uso:  product/backend/.venv/bin/python platform/assembler/verify_electronica_precio.py
"""
import os
import sys
import tempfile
from pathlib import Path

# ── EL SHIM DEBE ESTAR EN EL ENV ANTES DE IMPORTAR models/assembler ──────────
# models.py lee PUPPET_BRAIN_SHIM* al IMPORTAR (resuelve el brain a nivel módulo).
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ["PUPPET_BRAIN_SHIM_MODEL"] = "claude-code-opus-4.8"
os.environ.setdefault("PUPPET_BELTS", str(_REPO / "product" / "belts"))

sys.path.insert(0, str(_HERE))
from assembler import MCPServer                      # noqa: E402
import recipe_assembler as ra                        # noqa: E402

_BELT = _REPO / "catalog" / "templates" / "electronica" / "belt-electronica.mcp.json"

_results = []


def check(label, cond, detail=""):
    _results.append((bool(cond), label, detail))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {label}" + (f" — {detail}" if detail else ""))


def _base_env(workdir):
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = workdir
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    return env


def _expand(s, env):
    out = s
    for k, v in env.items():
        out = out.replace("${" + k + "}", v)
    return out


# ════════════════════════════════════════════════════════════════════════════
def level1_real_data():
    import json
    print("\n=== L1 · DATO REAL del catálogo (runtime MCPServer) ===")
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    scfg = belt["mcpServers"]["precio"]
    workdir = tempfile.mkdtemp(prefix="verify-precio-")
    env = _base_env(workdir)
    command = _expand(scfg["command"], env)
    args = [_expand(a, env) for a in scfg.get("args", [])]
    srv = MCPServer("precio", command, args, env=env)

    if not srv.start():
        check("P1 initialize handshake", False, "el server precio no inicializó")
        return None
    check("P1 initialize handshake", True)

    tools = [t.get("name") for t in srv.list_tools()]
    check("P2 tools/list expone quote_component + quote_bom",
          {"quote_component", "quote_bom"}.issubset(set(tools)), f"tools={tools}")

    raw = srv.call_tool("quote_component", {"query": "STM32F103C8T6"})
    d = json.loads(raw)
    print("\n  ── DATO CRUDO quote_component('STM32F103C8T6') ──")
    for k in ("mpn", "manufacturer", "lcsc_code", "unit_price_usd", "currency", "stock", "distributor", "url"):
        print(f"     {k:16}= {d.get(k)}")
    real_ok = (d.get("ok") and d.get("mpn") == "STM32F103C8T6" and d.get("lcsc_code") == "C8734"
               and isinstance(d.get("stock"), int) and d["stock"] > 0
               and isinstance(d.get("unit_price_usd"), (int, float)) and d["unit_price_usd"] > 0
               and d.get("distributor") == "JLCPCB/LCSC")
    check("P3 quote_component → precio+stock REAL (STM32F103C8T6=C8734)", real_ok,
          f"${d.get('unit_price_usd')} · stock={d.get('stock')} · {d.get('distributor')}")

    bom = srv.call_tool("quote_bom", {"title": "BOM verify", "components": [
        {"part": "STM32F103C8T6", "qty": 1}, {"part": "AMS1117-3.3", "qty": 2},
        {"part": "100nF 0603 X7R", "qty": 10}, {"part": "PJ-320A", "qty": 1}]})
    b = json.loads(bom)
    planilla_path = Path(workdir) / "bom.planilla.json"
    check("P4 quote_bom → tabla cotizada + total + artifact", (
        b.get("ok") and b.get("priced_lines", 0) >= 3 and b.get("total_usd", 0) > 0
        and planilla_path.exists()),
        f"total=${b.get('total_usd')} · priced={b.get('priced_lines')}/{b.get('line_count')} · planilla={planilla_path.exists()}")
    srv.stop()
    return None


# ════════════════════════════════════════════════════════════════════════════
RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "Agente de Electrónica", "nicho": "electronica",
             "descripcion": "Diseña esquemáticos y cotiza componentes con precio+stock real."},
    "belt": {
        "belt_ref": "catalog/templates/electronica/belt-electronica.mcp.json",
        "tool_filters": {"precio": ["quote_component", "quote_bom"]},
    },
    "keys": {},
    "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
    "model": {"alias": "brain", "max_turns": 8, "max_tokens": 2000, "temperature": 0},
    "framing": {"inline": (
        "Sos un agente de electrónica. Para precio y stock de componentes usás las tools "
        "quote_component (1 pieza) y quote_bom (lista/BOM). TODO precio y stock que reportes "
        "sale de la tool, jamás de memoria. Si te piden cotizar varios componentes o un BOM, "
        "llamá quote_bom UNA vez con la lista completa (cada item {part, qty}); esa tool arma "
        "la planilla cotizada. Después resumí el total y los componentes sin stock. Cero "
        "precios inventados.")},
    "rag": {"enabled": False},
}

PROMPT = ("Cotizá este BOM para un circuito regulador con micro: "
          "1× STM32F103C8T6, 2× AMS1117-3.3, 10× 100nF 0603 X7R, 1× PJ-320A. "
          "Dame el precio unitario y el stock real de cada uno y el costo total en USD. "
          "Armá la planilla cotizada.")


def level2_opus_e2e():
    print("\n=== L2 · E2E con OPUS (assemble_and_run + brain shim :8923) ===")
    workdir = tempfile.mkdtemp(prefix="verify-precio-e2e-")
    events = []
    rec = ra.assemble_and_run(
        RECIPE, PROMPT,
        repo_root=_REPO,
        deadline_s=300.0,
        workdir=workdir,
        on_event=lambda e: events.append(e),
    )
    model_final = rec.get("model_final")
    degraded = rec.get("degraded")
    tool_calls = rec.get("tool_calls", []) or []
    precio_calls = [c for c in tool_calls if str(c.get("tool", "")).startswith("quote_")]

    print(f"\n  model_final = {model_final}")
    print(f"  degraded    = {degraded}")
    print(f"  tools_cabled= {rec.get('tools_cabled')}")
    print(f"  tool_calls  = {[c.get('tool') for c in tool_calls]}")
    if precio_calls:
        c0 = precio_calls[0]
        print("\n  ── TOOL_CALL de precio (lo que el agente ejecutó) ──")
        print(f"     tool : {c0.get('tool')}")
        print(f"     args : {str(c0.get('args'))[:600]}")
        print(f"     result(trunc): {str(c0.get('result'))[:400]}")
    print("\n  ── RESPUESTA del agente (BOM) ──")
    print("   " + (rec.get("answer", "") or "").replace("\n", "\n   ")[:1400])

    check("E1 el run terminó OK", rec.get("ok"), rec.get("error") or "")
    check("E2 tool_call de precio ejecutada (quote_bom/quote_component)",
          len(precio_calls) >= 1, f"{[c.get('tool') for c in precio_calls]}")
    check("E3 model_final = claude-code-opus-4.8", model_final == "claude-code-opus-4.8", str(model_final))
    check("E4 degraded = null (Opus real, sin fallback)", degraded is None, str(degraded))

    # planilla artifact dejado por el run
    planilla = Path(workdir) / "bom.planilla.json"
    import json
    obra = None
    if planilla.exists():
        try:
            obra = json.loads(planilla.read_text())
        except Exception:
            obra = None
    check("E5 el run dejó bom.planilla.json (type=planilla con filas)",
          bool(obra and obra.get("type") == "planilla" and obra.get("rows")),
          f"filas={len(obra.get('rows', [])) if obra else 0}")
    if obra:
        print("\n  ── BOM PLANILLA (artifact que rinde La Sala) ──")
        print("   cols:", obra.get("cols"))
        for r in obra.get("rows", []):
            print("   ", " | ".join(str(x) for x in r))
    return workdir


# ════════════════════════════════════════════════════════════════════════════
def level3_executor_capture(workdir):
    print("\n=== L3 · CAPTURA del artifact por el executor ===")
    if not workdir:
        check("C1 _capture_rich_obra surfacea la planilla", False, "no hubo workdir del L2")
        return
    sys.path.insert(0, str(_REPO / "product" / "backend"))
    from app.phase1.executor import _capture_rich_obra
    obra = _capture_rich_obra(workdir)
    ok = bool(obra and obra.get("type") == "planilla" and isinstance(obra.get("rows"), list) and obra["rows"])
    check("C1 _capture_rich_obra → obra type=planilla (La Sala la rinde)", ok,
          f"type={obra.get('type') if obra else None} · filas={len(obra.get('rows', [])) if obra else 0}")


def main():
    level1_real_data()
    wd = level2_opus_e2e()
    level3_executor_capture(wd)
    passed = sum(1 for ok, _, _ in _results if ok)
    total = len(_results)
    print(f"\n=== RESULTADO: {passed}/{total} VERDE ===")
    if passed != total:
        print("ROJO en:", [lbl for ok, lbl, _ in _results if not ok])
        return 1
    print("Conector precio+stock de electrónica verificado: dato real + Opus e2e + planilla.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
