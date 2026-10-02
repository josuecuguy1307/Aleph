"""
audit_log.py — bitácora append-only, encadenada por hash (tamper-evident).

Cada acción guardada (recon disparado, URL rechazada, write replicado, kill-switch
trabado, datos borrados) deja UNA línea JSON con: ts, action, subject, target,
decision, meta, prev (hash de la línea anterior) y hash (de esta). Si alguien edita o
borra una línea del medio, la cadena se rompe y `verify_chain()` lo detecta.

No reemplaza al instrumentation_logs del moat (eso es producto/flywheel); esto es el
registro de SEGURIDAD: quién tocó qué del mundo externo y qué decidió la capa.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from . import config

_GENESIS = "0" * 64


def _audit_path() -> Path:
    config.ensure_safety_dir()
    return config.SAFETY_DIR / "audit.jsonl"


def _last_hash(p: Path) -> str:
    if not p.exists():
        return _GENESIS
    last = None
    try:
        with p.open("rb") as f:
            for raw in f:
                if raw.strip():
                    last = raw
    except OSError:
        return _GENESIS
    if not last:
        return _GENESIS
    try:
        return json.loads(last).get("hash", _GENESIS)
    except (json.JSONDecodeError, ValueError):
        return _GENESIS


def _hash_entry(entry: dict[str, Any]) -> str:
    # hash sobre el contenido canónico SIN el campo hash, incluyendo prev (encadena).
    payload = {k: entry[k] for k in entry if k != "hash"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record(
    action: str,
    *,
    subject: Optional[str] = None,
    target: Optional[str] = None,
    decision: str = "allow",
    **meta: Any,
) -> dict[str, Any]:
    """Append atómico de una entrada encadenada. Best-effort: nunca levanta (un fallo
    de auditoría no debe tumbar el flujo), pero deja rastro en stderr si falla."""
    p = _audit_path()
    try:
        prev = _last_hash(p)
        entry: dict[str, Any] = {
            "ts": round(time.time(), 3),
            "action": action,
            "subject": subject,
            "target": target,
            "decision": decision,
            "meta": meta or {},
            "prev": prev,
        }
        entry["hash"] = _hash_entry(entry)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        # append O_APPEND atómico para líneas chicas; fsync para durabilidad.
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return entry
    except Exception as exc:  # pragma: no cover
        import sys
        print(f"[safety.audit] no se pudo registrar {action!r}: {exc}", file=sys.stderr)
        return {}


def tail(n: int = 20) -> list[dict[str, Any]]:
    p = _audit_path()
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out[-n:]


def verify_chain() -> tuple[bool, Optional[str]]:
    """Recorre la bitácora validando prev↔hash. Devuelve (ok, motivo_de_ruptura)."""
    p = _audit_path()
    if not p.exists():
        return True, None
    prev = _GENESIS
    i = 0
    try:
        with p.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                i += 1
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    return False, f"línea {i}: JSON inválido"
                if entry.get("prev") != prev:
                    return False, f"línea {i}: prev roto (esperaba {prev[:12]}…)"
                expected = _hash_entry(entry)
                if entry.get("hash") != expected:
                    return False, f"línea {i}: hash no coincide (manipulada)"
                prev = entry["hash"]
    except OSError as exc:
        return False, f"io: {exc}"
    return True, None
