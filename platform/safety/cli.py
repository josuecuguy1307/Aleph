#!/usr/bin/env python3
"""
cli.py — consola del operador para la capa de safety.

Uso (desde la raíz del repo, con el venv del backend):
  python platform/safety/cli.py status
  python platform/safety/cli.py check-url http://169.254.169.254/latest/meta-data/
  python platform/safety/cli.py kill global "incidente: agente en loop"
  python platform/safety/cli.py kill user:0e890e35 "blast-radius manual"
  python platform/safety/cli.py reset global
  python platform/safety/cli.py blast 0e890e35            # cuántos writes lleva el sujeto
  python platform/safety/cli.py audit 30                  # últimas 30 líneas + verificar cadena
  python platform/safety/cli.py purge-user <user_id>      # dry-run
  python platform/safety/cli.py purge-user <user_id> --apply
  python platform/safety/cli.py retention                 # dry-run
  python platform/safety/cli.py retention --apply
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# bootstrap de path: permite correr el archivo directo (`from safety...`)
_PLATFORM = Path(__file__).resolve().parents[1]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from safety import audit_log, kill_switch, privacy, rate_limit, url_guard  # noqa: E402


def _pp(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]

    if cmd == "status":
        chain_ok, chain_err = audit_log.verify_chain()
        _pp({
            "killswitch": kill_switch.status(),
            "audit_chain_ok": chain_ok,
            "audit_chain_error": chain_err,
            "recent_audit": audit_log.tail(5),
        })
        return 0

    if cmd == "check-url":
        if not rest:
            print("uso: check-url <url> [--allow-local-fixture]"); return 2
        allow = "--allow-local-fixture" in rest
        url = rest[0]
        ok, reason = url_guard.is_safe(url, allow_local_fixture=allow)
        _pp({"url": url, "inspectable": ok, "reason": reason})
        return 0 if ok else 1

    if cmd == "kill":
        if not rest:
            print("uso: kill <scope> [reason]   scope ∈ global | user:<id> | niche:<n>"); return 2
        scope = rest[0]
        reason = " ".join(rest[1:]) or "manual"
        _pp(kill_switch.trip(scope, reason))
        return 0

    if cmd == "reset":
        if not rest:
            print("uso: reset <scope>"); return 2
        _pp(kill_switch.reset(rest[0]))
        return 0

    if cmd == "blast":
        if not rest:
            print("uso: blast <subject>"); return 2
        subj = rest[0]
        _pp({"subject": subj, "writes_in_window": kill_switch.write_count(subj),
             "recon_in_window": rate_limit.current(subj)})
        return 0

    if cmd == "audit":
        n = int(rest[0]) if rest and rest[0].isdigit() else 20
        chain_ok, chain_err = audit_log.verify_chain()
        _pp({"chain_ok": chain_ok, "chain_error": chain_err, "tail": audit_log.tail(n)})
        return 0 if chain_ok else 1

    if cmd == "purge-user":
        if not rest:
            print("uso: purge-user <user_id> [--apply]"); return 2
        apply = "--apply" in rest
        uid = rest[0]
        _pp(privacy.purge_user(uid, apply=apply))
        return 0

    if cmd == "retention":
        apply = "--apply" in rest
        _pp(privacy.retention_sweep(apply=apply))
        return 0

    print(f"comando desconocido: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
