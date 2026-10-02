#!/usr/bin/env python3
"""
capture.py — Flywheel data capture helper (schema v0)

Usage:
    python capture.py --from-config <path/to/config.json> \
                      --mission <MISSION_ID> \
                      --nicho <nicho> \
                      --belt-version <semver> \
                      --out <path/to/agents.jsonl>

    python capture.py --json '{"mission":"M003", ...}' \
                      --out <path/to/agents.jsonl>

Appends a single VALIDATED entry to the JSONL file.
Rejects invalid entries with a clear error message.
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "id",
    "mission",
    "nicho",
    "agent_name",
    "model_primary",
    "belt_version",
    "belt_tools",
    "temperature",
    "max_tokens",
    "max_turns",
    "rag_enabled",
    "created_at",
    "updated_at",
]

OPTIONAL_FIELDS = [
    "model_fallback",
    "rag_mode",
    "eval_score",
    "eval_notes",
    "user_feedback",
    "user_feedback_score",
]

ALL_FIELDS = set(REQUIRED_FIELDS + OPTIONAL_FIELDS)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(entry: dict) -> None:
    """Validate entry against schema v0. Raises ValueError with a clear message."""
    errors = []

    # 1. Required fields present
    for field in REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"campo requerido faltante: '{field}'")

    # Stop early if required fields are missing — remaining checks may crash
    if errors:
        raise ValueError("Entrada inválida:\n" + "\n".join(f"  • {e}" for e in errors))

    # 2. Type checks
    if not isinstance(entry["id"], str) or not entry["id"].strip():
        errors.append("'id' debe ser un string no vacío (UUID recomendado)")

    if not isinstance(entry["mission"], str) or not entry["mission"].strip():
        errors.append("'mission' debe ser un string no vacío (ej. 'M003')")

    if not isinstance(entry["nicho"], str) or not entry["nicho"].strip():
        errors.append("'nicho' debe ser un string no vacío (ej. 'tutor-stem-es')")

    if not isinstance(entry["agent_name"], str) or not entry["agent_name"].strip():
        errors.append("'agent_name' debe ser un string no vacío")

    if not isinstance(entry["model_primary"], str) or not entry["model_primary"].strip():
        errors.append("'model_primary' debe ser un string no vacío")

    if not isinstance(entry["belt_version"], str) or not entry["belt_version"].strip():
        errors.append("'belt_version' debe ser un string no vacío (semver, ej. '1.0.0')")

    if not isinstance(entry["belt_tools"], list) or len(entry["belt_tools"]) == 0:
        errors.append("'belt_tools' debe ser una lista no vacía de strings")
    elif not all(isinstance(t, str) and t.strip() for t in entry["belt_tools"]):
        errors.append("'belt_tools' todos los elementos deben ser strings no vacíos")

    temp = entry["temperature"]
    if not isinstance(temp, (int, float)) or not (0.0 <= float(temp) <= 2.0):
        errors.append("'temperature' debe ser un número en [0.0, 2.0]")

    if not isinstance(entry["max_tokens"], int) or entry["max_tokens"] <= 0:
        errors.append("'max_tokens' debe ser un entero positivo")

    if not isinstance(entry["max_turns"], int) or entry["max_turns"] <= 0:
        errors.append("'max_turns' debe ser un entero positivo")

    if not isinstance(entry["rag_enabled"], bool):
        errors.append("'rag_enabled' debe ser un booleano (true/false)")

    # 3. Conditional: rag_mode required when rag_enabled=true
    if entry.get("rag_enabled") is True:
        if "rag_mode" not in entry or not isinstance(entry["rag_mode"], str) or not entry["rag_mode"].strip():
            errors.append("'rag_mode' es requerido cuando 'rag_enabled' es true (ej. 'manual', 'auto')")

    # 4. Optional field type checks (only when present)
    if "model_fallback" in entry and not isinstance(entry["model_fallback"], str):
        errors.append("'model_fallback' debe ser un string")

    if "eval_score" in entry:
        s = entry["eval_score"]
        if not isinstance(s, (int, float)) or not (0.0 <= float(s) <= 1.0):
            errors.append("'eval_score' debe ser un número en [0.0, 1.0]")

    if "eval_notes" in entry and not isinstance(entry["eval_notes"], str):
        errors.append("'eval_notes' debe ser un string")

    if "user_feedback" in entry and not isinstance(entry["user_feedback"], str):
        errors.append("'user_feedback' debe ser un string")

    if "user_feedback_score" in entry:
        fs = entry["user_feedback_score"]
        if not isinstance(fs, int) or not (1 <= fs <= 5):
            errors.append("'user_feedback_score' debe ser un entero en [1, 5]")

    # 5. Timestamp format (basic ISO 8601 check)
    for ts_field in ("created_at", "updated_at"):
        val = entry.get(ts_field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"'{ts_field}' debe ser un string ISO 8601 no vacío")
        else:
            # Accept formats: ends with Z or +HH:MM / -HH:MM, has at least YYYY-MM-DDTHH:MM
            if "T" not in val or len(val) < 16:
                errors.append(f"'{ts_field}' no parece ISO 8601 válido (esperado: YYYY-MM-DDTHH:MM:SSZ)")

    # 6. No unknown fields (warn, not error — schema is v0 and evolving)
    unknown = set(entry.keys()) - ALL_FIELDS
    if unknown:
        print(f"ADVERTENCIA: campos desconocidos ignorados: {sorted(unknown)}", file=sys.stderr)

    if errors:
        raise ValueError("Entrada inválida:\n" + "\n".join(f"  • {e}" for e in errors))


# ---------------------------------------------------------------------------
# Build entry from config.json
# ---------------------------------------------------------------------------

def entry_from_config(config_path: str, mission: str, nicho: str, belt_version: str) -> dict:
    """Build a flywheel entry dict from an M003-style config.json."""
    cfg_file = Path(config_path)
    if not cfg_file.exists():
        raise FileNotFoundError(f"config.json no encontrado: {cfg_file}")

    with cfg_file.open() as f:
        cfg = json.load(f)

    agent_cfg = cfg.get("agent", {})
    runtime_cfg = cfg.get("runtime", {})
    belt_cfg = cfg.get("belt", {})
    rag_cfg = cfg.get("rag", {})

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "id": str(uuid.uuid4()),
        "mission": mission or agent_cfg.get("mission", ""),
        "nicho": nicho or agent_cfg.get("wedge", ""),
        "agent_name": agent_cfg.get("name", ""),
        "model_primary": runtime_cfg.get("model_primary", ""),
        "belt_version": belt_version or agent_cfg.get("version", "1.0.0"),
        "belt_tools": belt_cfg.get("sympy_filter", []),
        "temperature": runtime_cfg.get("temperature", 0),
        "max_tokens": runtime_cfg.get("max_tokens", 0),
        "max_turns": runtime_cfg.get("max_turns", 0),
        "rag_enabled": bool(rag_cfg),
        "created_at": now,
        "updated_at": now,
    }

    # Optional fields
    if runtime_cfg.get("model_fallback"):
        entry["model_fallback"] = runtime_cfg["model_fallback"]

    if rag_cfg.get("v1_mode"):
        entry["rag_mode"] = rag_cfg["v1_mode"]

    return entry


# ---------------------------------------------------------------------------
# Append to JSONL
# ---------------------------------------------------------------------------

def append_entry(entry: dict, out_path: str) -> None:
    """Validate entry and append to JSONL file."""
    validate(entry)
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"OK: entrada registrada en {out_file} (id={entry['id']})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Flywheel capture — appendea una entrada validada al JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Desde config.json de un agente (M003):
  python capture.py \\
    --from-config org/artifacts/M003-agente-stem/config.json \\
    --mission M003 --nicho tutor-stem-es --belt-version 1.0.0 \\
    --out platform/flywheel/agents.jsonl

  # Desde JSON literal:
  python capture.py \\
    --json '{"mission":"M003","nicho":"tutor-stem-es",...}' \\
    --out platform/flywheel/agents.jsonl
""",
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-config", metavar="PATH",
                        help="Path a config.json del agente (relativo al cwd)")
    source.add_argument("--json", metavar="JSON",
                        help="Entrada como JSON literal (string)")

    p.add_argument("--mission", default="",
                   help="ID de misión (ej. M003) — sobreescribe el valor del config")
    p.add_argument("--nicho", default="",
                   help="Nicho del agente — sobreescribe el valor del config")
    p.add_argument("--belt-version", default="",
                   help="Versión del cinturón (semver) — sobreescribe el valor del config")
    p.add_argument("--out", required=True, metavar="PATH",
                   help="Path al archivo JSONL de salida (se crea si no existe)")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.from_config:
            entry = entry_from_config(
                config_path=args.from_config,
                mission=args.mission,
                nicho=args.nicho,
                belt_version=args.belt_version,
            )
        else:
            entry = json.loads(args.json)

        append_entry(entry, args.out)

    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: JSON inválido — {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
