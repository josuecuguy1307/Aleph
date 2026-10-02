#!/usr/bin/env python3
"""
Smoke test estructural para los 10 templates de finanzas.
Valida: parseo JSON correcto + paths de belt_path y framing_path resolvibles.
NO corre el LLM. NO necesita credenciales. Solo stdlib.

Uso:
    python smoke_test.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
BELT_PATH = BASE / "belt-finanzas.mcp.json"

TEMPLATES = [
    "t01-cierre-mensual",
    "t02-regresion-panel-stata",
    "t03-tabla-comparables",
    "t04-brief-macro-fred",
    "t05-varianza-fp-a",
    "t06-monitor-mercado",
    "t07-screener-fundamentals",
    "t08-notebook-backtesting",
    "t09-resumen-filing-edgar",
    "t10-dashboard-macro",
]

REQUIRED_FIELDS = ["belt_path", "framing_fallback", "base_url", "model"]


def check_template(name: str) -> dict:
    result = {"template": name, "ok": True, "errors": [], "warnings": []}
    config_path = BASE / name / "config.json"

    # 1. El archivo existe
    if not config_path.exists():
        result["ok"] = False
        result["errors"].append(f"config.json no encontrado: {config_path}")
        return result

    # 2. Parsea como JSON
    try:
        cfg = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        result["ok"] = False
        result["errors"].append(f"JSON inválido: {e}")
        return result

    # 3. Campos obligatorios presentes
    for field in REQUIRED_FIELDS:
        if field not in cfg:
            result["ok"] = False
            result["errors"].append(f"Campo requerido ausente: '{field}'")

    # 4. belt_path resuelve a un archivo existente
    belt_raw = cfg.get("belt_path", "")
    belt_p = Path(belt_raw)
    if not belt_p.exists():
        result["ok"] = False
        result["errors"].append(f"belt_path no existe: {belt_raw}")
    else:
        # 4b. El belt es JSON válido con mcpServers
        try:
            belt_cfg = json.loads(belt_p.read_text())
            if "mcpServers" not in belt_cfg:
                result["ok"] = False
                result["errors"].append(f"belt_path sin 'mcpServers': {belt_raw}")
            else:
                result["belt_servers"] = list(belt_cfg["mcpServers"].keys())
        except json.JSONDecodeError as e:
            result["ok"] = False
            result["errors"].append(f"belt_path JSON inválido: {e}")

    # 5. framing_path: si presente, verificar que apunta a algún lugar razonable
    framing_raw = cfg.get("framing_path")
    if framing_raw and framing_raw != "null":
        framing_p = Path(framing_raw)
        if not framing_p.exists():
            # Es un warning, no error: framing_fallback cubre el caso
            result["warnings"].append(
                f"framing_path no existe (se usará framing_fallback): {framing_raw}"
            )

    # 6. framing_fallback no vacío
    fb = cfg.get("framing_fallback", "")
    if not fb or not fb.strip():
        result["ok"] = False
        result["errors"].append("framing_fallback está vacío")

    # 7. tool_filters: si presente, cada server debe estar en belt
    belt_servers = result.get("belt_servers", [])
    tf = cfg.get("tool_filters", {})
    if tf and belt_servers:
        for sname in tf:
            if sname not in belt_servers:
                result["warnings"].append(
                    f"tool_filters['{sname}'] no está en belt mcpServers {belt_servers}"
                )

    return result


def main():
    print("=" * 60)
    print("SMOKE TEST ESTRUCTURAL — Templates Finanzas")
    print(f"Base: {BASE}")
    print(f"Belt compartido: {BELT_PATH}")
    print("=" * 60)

    # Verificar que el belt compartido existe y es válido
    if not BELT_PATH.exists():
        print(f"\n[FATAL] belt-finanzas.mcp.json no encontrado: {BELT_PATH}")
        sys.exit(2)
    try:
        belt_shared = json.loads(BELT_PATH.read_text())
        shared_servers = list(belt_shared.get("mcpServers", {}).keys())
        print(f"\nBelt compartido OK — servers: {shared_servers}")
    except json.JSONDecodeError as e:
        print(f"\n[FATAL] belt-finanzas.mcp.json JSON inválido: {e}")
        sys.exit(2)

    print()
    all_ok = True
    results = []

    for name in TEMPLATES:
        r = check_template(name)
        results.append(r)
        status = "OK " if r["ok"] else "FAIL"
        servers = r.get("belt_servers", [])
        print(f"[{status}] {name}")
        if servers:
            print(f"       belt_servers referenciados: {servers}")
        for err in r["errors"]:
            print(f"       ERROR: {err}")
        for warn in r["warnings"]:
            print(f"       WARN : {warn}")
        if not r["ok"]:
            all_ok = False

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    print(f"RESULTADO: {passed}/{len(results)} templates OK, {failed} FAIL")
    if all_ok:
        print("SMOKE: PASS — todos los configs parsean y sus belt_paths resuelven")
    else:
        print("SMOKE: FAIL — ver errores arriba")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
