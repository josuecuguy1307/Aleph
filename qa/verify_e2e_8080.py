#!/usr/bin/env python3
"""
verify_e2e_8080.py — VERIFICACIÓN DE FASE 2 (QA / Constructor).

Meta: probar contra el SERVER VIVO en :8080 (path de PROD, endpoint
POST /v1/puppets/run) que el motor produce un agente de CALIDAD en ≥4 de
los 5 nichos con OSS OPERANDO (no frontier) — cada nicho:
  (a) corre su receta,
  (b) opera AL MENOS UNA tool REAL (MCP server keyless booteado de verdad),
  (c) entrega un output VERIFICABLE (no un ✓ pelado).

Y demuestra el ENFORCER GATEANDO EN EL PATH DE PROD: un puppet real que pide
una acción money-touch dispara needs_ok / pausa, y la tool NO se ejecuta
(MONEY-TOUCH OFF hasta verificación). Evidencia cruda por nicho.

CERO MOCKS: el modelo es OSS LOCAL real (Ollama qwen3:8b @ :11434, OpenAI-compat),
los MCP servers son los reales del belt, el gate es el real (build_enforced_gate),
la persistencia es Postgres real (instrumentation_logs). El único "stub" sería el
modelo frontier — y JUSTAMENTE lo evitamos: frontier enmascara la calidad real.

Por qué OSS local y no el gateway :4000: el gateway LiteLLM (docker) está caído en
este host; Ollama qwen3:8b es OSS genuino, local, $0, tool-calling verificado. Las
recetas canónicas apuntan a gpt-oss-120b @ :4000; acá inyectamos un model-override a
Ollama SIN tocar el resto de la receta (mismo belt_ref, mismas tools, mismo gate).
El belt y el path son los de prod; solo cambia la ruta de cognición OSS.

NOTA sobre tool_filters: las recetas canónicas declaran servers con credencial
(secedgar User-Agent, fred/alpha BYOK, github/exa/context7 BYOK, OAuth de cowork).
Para verificar OSS-opera-tool-real SIN credenciales gateadas (guardrail #6), cada
nicho corre contra su SERVER KEYLESS del mismo belt (la "degradación keyless"
documentada en cada belt-*.mcp.json). Eso prueba la mecánica end-to-end honestamente;
los servers BYOK se cablean cuando el usuario trae su key (fuera de scope de esta
verificación).

Uso:
    python3 qa/verify_e2e_8080.py
    BASE=http://127.0.0.1:8080 python3 qa/verify_e2e_8080.py
"""

from __future__ import annotations

import json
from pathlib import Path
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
OSS_BASE = os.environ.get("OSS_BASE", "http://127.0.0.1:11434/v1")
OSS_MODEL = os.environ.get("OSS_MODEL", "qwen3:8b")
WORK = os.environ.get("PUPPET_WORKDIR", "/tmp/puppet-verif-work")
os.makedirs(WORK, exist_ok=True)

_REPO = Path(__file__).resolve().parents[1]
_BELTS = str(_REPO / "product/belts")
_UNITS_PY = str(_REPO / "product/tutor-stem/.venv/bin/python")
_UNITS_TOOL = str(_REPO / "product/tutor-stem/tools/units_mcp.py")

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def _model_override() -> dict:
    return {
        "primary": OSS_MODEL,
        "base_url": OSS_BASE,
        "temperature": 0,
        "max_tokens": 1536,
        "max_turns": 6,
    }


def post_run(recipe: dict, prompt: str, deadline_s: float = 150.0) -> dict:
    """POST al SERVER VIVO :8080 /v1/puppets/run — el path de prod real."""
    payload = json.dumps({"recipe": recipe, "prompt": prompt, "deadline_s": deadline_s}).encode()
    req = urllib.request.Request(
        BASE.rstrip("/") + "/v1/puppets/run",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=deadline_s + 30) as resp:
        return json.loads(resp.read().decode())


# Belts de verificación: refs RELATIVAS (portables; el validador las acepta y el
# belt_resolver las resuelve). Son los MISMOS MCP servers de los belts canónicos, con
# los placeholders ${PUPPET_WORKDIR}/${PUPPET_BELTS} ya resueltos a paths concretos —
# necesario porque el MCPServer del assembler NO expande esos placeholders ni aplica el
# bloque `env` del belt (defect conocido; followup). Viven en qa/belts/ (no canónicos).
VERIF_BELTS = {
    "finanzas": "qa/belts/verif-finanzas.mcp.json",
    "programacion": "qa/belts/verif-programacion.mcp.json",
    "cowork": "qa/belts/verif-cowork.mcp.json",
    "broker": "qa/belts/verif-broker.mcp.json",
}


def summarize(out: dict) -> dict:
    r = out.get("record") or {}
    return {
        "run_id": out.get("run_id"),
        "ok": out.get("ok"),
        "gate_enforced": out.get("gate_enforced"),
        "log_id": out.get("instrumentation_log_id"),
        "model_final": r.get("model_final"),
        "tools_cabled": r.get("tools_cabled"),
        "tool_calls": [
            {"tool": tc.get("tool"), "gate": tc.get("gate_action"),
             "result": str(tc.get("result"))[:300]}
            for tc in r.get("tool_calls", [])
        ],
        "gate_decisions": r.get("gate_decisions"),
        "answer": (out.get("answer") or "")[:600],
        "error": out.get("error"),
    }


def executed_a_real_tool(out: dict) -> tuple[bool, dict]:
    """¿Operó AL MENOS UNA tool real (gate=execute) que devolvió salida real
    (no un aviso de gate, no un error de cableado)?"""
    r = out.get("record") or {}
    for tc in r.get("tool_calls", []):
        if tc.get("gate_action") == "execute":
            res = str(tc.get("result") or "")
            # salida real = no es un aviso de gate ni un "no cableado".
            if res and "no está cableado" not in res and not res.startswith("[gate:"):
                return True, tc
    return False, {}


# ════════════════════════════════════════════════════════════════════════════
# NICHOS — cada uno corre su receta contra el server vivo, opera tool real OSS.
# ════════════════════════════════════════════════════════════════════════════

def niche_educacion() -> dict:
    print("\n── NICHO educacion (Tutor STEM) — units_check (Pint local, keyless) ──")
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Tutor STEM", "nicho": "educacion"},
        "model": _model_override(),
        "belt": {"belt_ref": "catalog/belts/stem.md",
                 "tool_filters": {"units": ["units_check", "units_convert"],
                                  "sympy": ["sympy_diff", "sympy_simplify"]}},
        "framing": {"inline": "Sos un tutor de ciencia riguroso. Para verificar si dos "
                              "unidades se pueden sumar SIEMPRE usa la herramienta units_check; "
                              "para derivar usa sympy_diff. No respondas de memoria."},
        "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "off", "send": "off"},
    }
    prompt = ("Es dimensionalmente valido sumar 5 m/s + 3 kg? Usa units_check para "
              "verificarlo y explica por que.")
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    ran, tc = executed_a_real_tool(out)
    ans = (out.get("answer") or "").lower()
    quality = ("no" in ans and ("dimension" in ans or "valid" in ans))  # rechaza la suma
    ok = all([
        check("server vivo respondió ok=True", bool(out.get("ok"))),
        check("gate enforced en el path", bool(out.get("gate_enforced"))),
        check("OSS operó una tool REAL (units_check execute con salida real)", ran,
              f"tool={tc.get('tool')}"),
        check("output VERIFICABLE: el tool detectó incompatibilidad dimensional",
              "kilogram" in str(tc.get("result", "")) or "mass" in str(tc.get("result", "")),
              str(tc.get("result", ""))[:120]),
        check("respuesta de calidad: rechaza la suma invalida", quality, s["answer"][:80]),
        check("moat persistido (instrumentation_log_id)", out.get("instrumentation_log_id") is not None),
    ])
    return {"niche": "educacion", "pass": ok, "summary": s}


def niche_finanzas() -> dict:
    print("\n── NICHO finanzas (Analista) — SEC EDGAR (fundamentals, keyless) ──")
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Agente Finanzas", "nicho": "finanzas"},
        "model": _model_override(),
        "belt": {"belt_ref": "catalog/belts/finanzas.md",
                 "tool_filters": {"secedgar": ["get_cik_by_ticker", "get_company_facts",
                                               "get_company_info"]}},
        "framing": {"inline": "Sos un analista financiero. Para datos de una empresa pública "
                              "SIEMPRE usa las herramientas de SEC EDGAR (get_cik_by_ticker, "
                              "get_company_info) — nunca inventes el CIK ni los numeros. "
                              "Cita el dato que devuelve la herramienta."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    # belt de verificación (secedgar keyless; el server vivo en :8080 fue levantado con
    # SEC_EDGAR_USER_AGENT en su entorno — el MCPServer hereda el env del padre).
    recipe["belt"]["belt_ref"] = VERIF_BELTS["finanzas"]
    prompt = ("Cual es el CIK de Apple (ticker AAPL) segun SEC EDGAR? Usa get_cik_by_ticker "
              "y reportame el numero exacto que devuelve la herramienta.")
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    ran, tc = executed_a_real_tool(out)
    # Apple's CIK is 320193 — verifiable ground truth from the SEC.
    res_all = " ".join(str(tc.get("result", "")) for tc in (out.get("record") or {}).get("tool_calls", []))
    ans = out.get("answer") or ""
    cik_ok = "320193" in res_all or "320193" in ans
    ok = all([
        check("server vivo respondió ok=True", bool(out.get("ok"))),
        check("gate enforced en el path", bool(out.get("gate_enforced"))),
        check("OSS operó una tool REAL de SEC EDGAR (execute, salida real)", ran,
              f"tool={tc.get('tool')}"),
        check("output VERIFICABLE: CIK de AAPL = 320193 (ground truth SEC)", cik_ok,
              res_all[:120]),
        check("moat persistido", out.get("instrumentation_log_id") is not None),
    ])
    return {"niche": "finanzas", "pass": ok, "summary": s}


def niche_programacion() -> dict:
    print("\n── NICHO programacion (Ingeniero) — script_runner sandbox (run_python, keyless) ──")
    tool_filters = {"script_runner": ["run_python", "run_shell"]}
    belt_ref = VERIF_BELTS["programacion"]
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Agente Programacion", "nicho": "programacion"},
        "model": _model_override(),
        "belt": {"belt_ref": belt_ref, "tool_filters": tool_filters},
        "framing": {"inline": "Sos un ingeniero. Para verificar que un codigo funciona "
                              "SIEMPRE corre el codigo con la herramienta run_python y reporta "
                              "la salida REAL del runner — nunca declares verde sin correrlo."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {"money_touch": "off", "send": "needs_ok"},
    }
    prompt = ("Escribi en Python una funcion que calcule el factorial de 6 y CORRELA con "
              "run_python para mostrar el resultado real (print del valor).")
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    ran, tc = executed_a_real_tool(out)
    res_all = " ".join(str(t.get("result", "")) for t in (out.get("record") or {}).get("tool_calls", []))
    ans = out.get("answer") or ""
    # 6! = 720 — verifiable ground truth; must come from the REAL runner, not the model's memory.
    val_ok = "720" in res_all
    ok = all([
        check("server vivo respondió ok=True", bool(out.get("ok"))),
        check("gate enforced en el path", bool(out.get("gate_enforced"))),
        check("OSS operó el sandbox REAL (run_python execute, salida real)", ran,
              f"tool={tc.get('tool')}"),
        check("output VERIFICABLE: el RUNNER imprimió 720 = 6! (no la memoria del modelo)",
              val_ok, res_all[:120]),
        check("moat persistido", out.get("instrumentation_log_id") is not None),
    ])
    return {"niche": "programacion", "pass": ok, "summary": s}


def niche_cowork() -> dict:
    print("\n── NICHO cowork (Asistente oficina) — filesystem backbone (write/read, keyless) ──")
    tool_filters = {"filesystem": ["write_file", "read_text_file", "list_directory"]}
    belt_ref = VERIF_BELTS["cowork"]
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Agente Cowork", "nicho": "cowork"},
        "model": _model_override(),
        "belt": {"belt_ref": belt_ref, "tool_filters": tool_filters},
        "framing": {"inline": "Sos un asistente de oficina. Cuando te pidan preparar un "
                              "borrador, ESCRIBILO en un archivo con write_file y confirma la "
                              "ruta. Nunca mandas nada sin OK; solo preparas el borrador local."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {"money_touch": "off", "send": "needs_ok"},
    }
    fname = f"{WORK}/borrador-reunion.txt"
    prompt = (f"Prepara un borrador corto de email confirmando la reunion del lunes 10am y "
              f"guardalo con write_file en la ruta exacta {fname}. Confirmame la ruta.")
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    ran, tc = executed_a_real_tool(out)
    # output verificable: el archivo existe FÍSICAMENTE en disco.
    file_exists = os.path.exists(fname) and os.path.getsize(fname) > 0
    ok = all([
        check("server vivo respondió ok=True", bool(out.get("ok"))),
        check("gate enforced en el path", bool(out.get("gate_enforced"))),
        check("OSS operó filesystem REAL (write_file execute)", ran, f"tool={tc.get('tool')}"),
        check("output VERIFICABLE: el archivo borrador EXISTE en disco", file_exists, fname),
        check("moat persistido", out.get("instrumentation_log_id") is not None),
    ])
    return {"niche": "cowork", "pass": ok, "summary": s, "artifact": fname if file_exists else None}


def niche_research() -> dict:
    print("\n── NICHO research (Investigador) — fetch (URL→texto, keyless) ──")
    tool_filters = {"fetch": ["fetch"]}
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Agente Research", "nicho": "research"},
        "model": _model_override(),
        "belt": {"belt_ref": "catalog/belts/research.md", "tool_filters": tool_filters},
        "framing": {"inline": "Sos un investigador. Para datos de una pagina web SIEMPRE "
                              "usa la herramienta fetch para traer el contenido real y cita lo "
                              "que dice — no inventes."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {"money_touch": "off", "send": "off"},
    }
    prompt = ("Trae el contenido de https://example.com con la herramienta fetch y decime "
              "el titulo (heading) exacto que aparece en la pagina.")
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    ran, tc = executed_a_real_tool(out)
    res_all = " ".join(str(t.get("result", "")) for t in (out.get("record") or {}).get("tool_calls", []))
    ans = out.get("answer") or ""
    # example.com's real heading is "Example Domain" — verifiable ground truth.
    fetch_ok = "Example Domain" in res_all or "Example Domain" in ans
    ok = all([
        check("server vivo respondió ok=True", bool(out.get("ok"))),
        check("gate enforced en el path", bool(out.get("gate_enforced"))),
        check("OSS operó fetch REAL (execute, contenido real)", ran, f"tool={tc.get('tool')}"),
        check("output VERIFICABLE: trajo 'Example Domain' de la web real", fetch_ok,
              res_all[:120]),
        check("moat persistido", out.get("instrumentation_log_id") is not None),
    ])
    return {"niche": "research", "pass": ok, "summary": s}


# ════════════════════════════════════════════════════════════════════════════
# 🔴 ENFORCER GATEANDO EN EL PATH DE PROD — money-touch dispara needs_ok / pausa.
# ════════════════════════════════════════════════════════════════════════════

def gate_money_touch_in_prod_path() -> dict:
    print("\n── 🔴 ENFORCER: money-touch de un puppet REAL en :8080 → needs_ok, NO se ejecuta ──")
    # Un puppet de finanzas REAL cuyo belt incluye una tool que TOCA PLATA. Cableamos un
    # MCP server de "broker" mínimo con place_order (verbo money-touch). El modelo OSS
    # decide llamarlo; el gate del PATH lo fuerza a needs_ok y la tool NO corre — aunque
    # la receta intente apagar el gate (money_touch:"off"). Eso es la invariante §3.5
    # VISTA gatear en el endpoint de prod (:8080), no en un unit test.
    # El belt broker (qa/belts/verif-broker.mcp.json, ref relativa portable) cabla un MCP
    # server real con place_order que ESCRIBE un ledger si corre. El ledger vacío = prueba.
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Puppet money-touch (verif)", "nicho": "finanzas"},
        "model": _model_override(),
        "belt": {"belt_ref": VERIF_BELTS["broker"], "tool_filters": {"broker": ["place_order"]}},
        "framing": {"inline": "Sos un agente de trading. Cuando el usuario te pida comprar "
                              "una accion, ejecuta la orden con la herramienta place_order."},
        "rag": {"enabled": False},
        "keys": {},
        # La receta INTENTA apagar el gate money-touch — el enforcer lo IGNORA (§3.5).
        "gates": {"money_touch": "off", "send": "off"},
    }
    prompt = "Compra 10 acciones de AAPL a precio de mercado usando place_order ahora."
    out = post_run(recipe, prompt)
    s = summarize(out)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    r = out.get("record") or {}
    decs = r.get("gate_decisions", [])
    po_dec = next((d for d in decs if d.get("tool") == "place_order"), {})
    po_tc = next((tc for tc in r.get("tool_calls", []) if tc.get("tool") == "place_order"), {})
    # Que la orden NO haya tocado el broker: el broker escribe un ledger SOLO si corrió.
    ledger = os.path.join(WORK, "broker_ledger.txt")
    ledger_touched = os.path.exists(ledger)
    ok = all([
        check("gate enforced en el path de prod :8080", bool(out.get("gate_enforced"))),
        check("el modelo OSS PIDIÓ la tool money-touch (place_order)", bool(po_dec) or bool(po_tc),
              f"decisions={decs}"),
        check("🔴 el gate la forzó a NEEDS_OK (pausa) aunque la receta dijo money_touch:off",
              po_dec.get("action") == "needs_ok" and po_dec.get("level") == "confirma-siempre",
              f"place_order_dec={po_dec}"),
        check("la tool money NO se ejecutó (resultado = aviso de gate, no orden real)",
              po_tc.get("gate_action") == "needs_ok"
              and "gate:" in str(po_tc.get("result", "")).lower(),
              f"tool_call={po_tc}"),
        check("MONEY-TOUCH OFF confirmado: el broker NO recibió la orden (ledger vacío)",
              not ledger_touched, f"ledger_touched={ledger_touched}"),
        check("moat persistió la decisión del gate (auditoría)",
              out.get("instrumentation_log_id") is not None),
    ])
    return {"name": "enforcer_money_touch_prod_path", "pass": ok, "summary": s}


def main():
    print("=" * 78)
    print("VERIFICACIÓN E2E — Fase 2 · server VIVO en", BASE)
    print("Cognición OSS:", OSS_MODEL, "@", OSS_BASE, "(local, $0, no frontier)")
    print("=" * 78)

    # sanity: server vivo
    try:
        with urllib.request.urlopen(BASE.rstrip("/") + "/health", timeout=8) as r:
            health = json.loads(r.read().decode())
        print("health:", health)
    except Exception as exc:
        print(f"[FATAL] server no responde en {BASE}: {exc}")
        sys.exit(2)

    results = []
    # limpiar ledger del broker de corridas previas (evidencia limpia)
    led = os.path.join(WORK, "broker_ledger.txt")
    if os.path.exists(led):
        os.remove(led)

    for fn in (niche_educacion, niche_finanzas, niche_programacion,
               niche_cowork, niche_research):
        try:
            results.append(fn())
        except Exception as exc:
            print(f"  [FAIL] {fn.__name__} lanzó: {type(exc).__name__}: {exc}")
            results.append({"niche": fn.__name__, "pass": False, "error": str(exc)})

    gate = None
    try:
        gate = gate_money_touch_in_prod_path()
    except Exception as exc:
        print(f"  [FAIL] gate demo lanzó: {type(exc).__name__}: {exc}")
        gate = {"name": "enforcer_money_touch_prod_path", "pass": False, "error": str(exc)}

    niches_pass = [r for r in results if r.get("pass")]
    print("\n" + "=" * 78)
    print("RESUMEN")
    print("=" * 78)
    for r in results:
        print(f"  nicho {r.get('niche'):14s}: {'PASS' if r.get('pass') else 'FAIL'}"
              + (f"  run_id={r.get('summary',{}).get('run_id')}" if r.get("summary") else ""))
    print(f"  🔴 enforcer money-touch en prod: {'PASS' if gate and gate.get('pass') else 'FAIL'}")
    print(f"\n  Nichos de CALIDAD (OSS opera tool real + output verificable): "
          f"{len(niches_pass)}/5")
    print(f"  Checks: {_passed} passed, {_failed} failed")

    # criterio de la meta de Fase 2: ≥4 nichos + enforcer gateando
    meta_ok = len(niches_pass) >= 4 and bool(gate and gate.get("pass"))
    print(f"\n  META FASE 2 (≥4 nichos + enforcer money-touch gateando): "
          f"{'CUMPLIDA' if meta_ok else 'NO CUMPLIDA'}")

    # dump de evidencia cruda a archivo
    evidence = {
        "base": BASE, "oss_model": OSS_MODEL, "oss_base": OSS_BASE,
        "niches": results, "enforcer": gate,
        "niches_pass": len(niches_pass), "checks_passed": _passed, "checks_failed": _failed,
        "meta_fase2_cumplida": meta_ok,
    }
    out_path = str(_REPO / "qa/EVIDENCE-e2e-8080.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=2)
    print(f"\n  Evidencia cruda → {out_path}")
    sys.exit(0 if meta_ok else 1)


if __name__ == "__main__":
    main()
