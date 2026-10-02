"""
library/store.py — el ALMACÉN §8. Estrategias GANADORAS indexadas por HUELLA de
familia, persistidas como json en un dir AISLADO y gitignored (hermano de
synth_belts). Es el data-flywheel del moat: qué estrategia funcionó por familia.

Schema CONGELADO (FASE 0): ver CapturedStrategy + FASE3-CAPTURA-NOTES.md.

Mapeo PLATFORM-LEDGER (por entrada):
  • REUSABLE       — ganó el peldaño B (familia resuelta wholesale por el resolver).
  • PARAMETRIZABLE — priors con forma de plantilla (endpoints `{}` / convención):
                     se RE-BINDEAN a cada instancia nueva (el caso común).
  • INSTANCIA      — priors todos concretos (ids minados): no reusan limpio.
  • META           — el ÍNDICE en sí + `hits` por familia (no per-entry; ver stats()).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

_PLATFORM = Path(__file__).resolve().parents[2]   # library → inspection → platform
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C            # noqa: E402
from inspection.library import fingerprint as fp  # noqa: E402

#: dir AISLADO y gitignored (hermano de synth_belts). product/backend/data/capture_library/
CAPTURE_DIR: Path = C.SYNTH_BELTS_DIR.parent / "capture_library"
SCHEMA_VERSION = 1


# ══════════════════════════════════════════════════════════════════════════════
# CapturedStrategy — el registro persistido. *** SCHEMA CONGELADO ***
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class CapturedStrategy:
    family_id: str                  # CLAVE DE ÍNDICE (= fingerprint.family_id)
    fingerprint: dict               # cómo se derivó la huella (auditable)
    winner_rung: str                # A | B | C | D | union
    ledger_class: str               # REUSABLE | PARAMETRIZABLE | INSTANCIA
    priors: dict                    # la RESPUESTA reinyectable (endpoints/auth/signals)
    metadata: dict                  # captured_at, captured_against, score, convergence_first, hits
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "fingerprint": self.fingerprint,
            "winner_rung": self.winner_rung,
            "ledger_class": self.ledger_class,
            "priors": self.priors,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CapturedStrategy":
        return cls(
            family_id=d["family_id"], fingerprint=d.get("fingerprint", {}),
            winner_rung=d.get("winner_rung", ""), ledger_class=d.get("ledger_class", ""),
            priors=d.get("priors", {}), metadata=d.get("metadata", {}),
            schema_version=d.get("schema_version", SCHEMA_VERSION))

    @property
    def hits(self) -> int:
        return int(self.metadata.get("hits", 0))


# ══════════════════════════════════════════════════════════════════════════════
# serde de endpoints ↔ CandidateTool (round-trip al candado §3 en la reinyección)
# ══════════════════════════════════════════════════════════════════════════════
def endpoint_to_dict(cand: C.CandidateTool) -> dict:
    return {
        "name": cand.name,
        "kind": cand.kind.value if isinstance(cand.kind, C.ToolKind) else str(cand.kind),
        "endpoint": cand.endpoint,
        "method": cand.method,
        "input_schema": dict(cand.input_schema or {}),
        "description": cand.description,
        "derived_from": list(cand.derived_from or ()),
    }


def candidate_from_dict(d: dict) -> C.CandidateTool:
    """Reconstruye una CandidateTool desde un endpoint persistido (lo usa la
    reinyección FASE 3c para re-validarla contra la instancia nueva)."""
    kind = d.get("kind", "read")
    return C.CandidateTool(
        name=d["name"],
        kind=C.ToolKind(kind) if not isinstance(kind, C.ToolKind) else kind,
        endpoint=d["endpoint"], method=d.get("method", "GET"),
        input_schema=d.get("input_schema") or {},
        description=d.get("description", ""),
        derived_from=tuple(d.get("derived_from") or ()))


# ══════════════════════════════════════════════════════════════════════════════
# clasificación PLATFORM-LEDGER
# ══════════════════════════════════════════════════════════════════════════════
_CONVENTION_GENERAL = ("", "/api", "/api/v1", "/v1", "/v2", "/status",
                       "/health", "/version", "/info")


def classify_ledger(winner_rung: str, endpoints: Sequence[dict]) -> str:
    if winner_rung == "B":
        return "REUSABLE"
    norms = [fp.normalize_template(e.get("endpoint", "")) for e in endpoints]
    if any("{}" in n for n in norms):
        return "PARAMETRIZABLE"
    if any(n.rstrip("/") in _CONVENTION_GENERAL for n in norms):
        return "PARAMETRIZABLE"
    return "INSTANCIA"


# ══════════════════════════════════════════════════════════════════════════════
# captura (FASE 3b · la llama el wrapper caller-side al ganar)
# ══════════════════════════════════════════════════════════════════════════════
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact_url(url: str) -> str:
    try:
        u = urlparse(url)
        return u.path or "/"
    except Exception:  # noqa: BLE001
        return "/"


def _signals_from_cascade(cascade_result: Any) -> list[dict]:
    out: list[dict] = []
    for sr in getattr(cascade_result, "rungs", ()) or ():
        for s in getattr(sr, "signals", ()) or ():
            out.append({"kind": getattr(s, "kind", ""), "url_path": _redact_url(getattr(s, "url", "")),
                        "status": getattr(s, "status", 0), "detail": getattr(s, "detail", "")})
    return out


def capture(
    cascade_result: Any, *,
    base_url: str,
    auth_param: str = "api_key",
    validate_path: str = "",
    validate_query: Optional[dict] = None,
    doc_title: str = "",
    doc_version: str = "",
    root: Path = CAPTURE_DIR,
) -> Optional[CapturedStrategy]:
    """Persistí la GANADORA con su huella. Devuelve la CapturedStrategy escrita, o
    None si no hubo nada reusable (sin verificadas y sin familia). Idempotente: si
    ya existe una entrada para esa familia, PRESERVA `hits` (señal del flywheel)."""
    if not getattr(cascade_result, "ok", False):
        return None

    verified = getattr(cascade_result, "verified", ()) or ()
    family = getattr(cascade_result, "family", None)
    endpoints = [endpoint_to_dict(vt.candidate) for vt in verified]
    if not endpoints and not family:
        return None                                   # nada reusable

    resolved_name = (family or {}).get("server_name", "") if family else ""
    fingerprint = fp.derive(
        base_url, endpoints=endpoints, auth_param=auth_param,
        doc_title=doc_title, doc_version=doc_version, resolved_server_name=resolved_name)

    winner = getattr(cascade_result, "winner", None)
    winner_rung = (winner.value if winner is not None else
                   ("B" if family else ("union" if endpoints else "?")))
    ledger_class = classify_ledger(winner_rung, endpoints)

    budget = getattr(cascade_result, "budget", {}) or {}
    rungs_run = [getattr(sr.rung, "value", str(sr.rung)) for sr in getattr(cascade_result, "rungs", ()) or ()]
    priors = {
        "auth_param": auth_param,
        "validate_path": validate_path,
        "validate_query": validate_query,
        "endpoints": endpoints,
        "family": family,                              # handoff del resolver (si ganó B)
        "signals": _signals_from_cascade(cascade_result),
    }
    # preservá hits de una entrada previa de la MISMA familia
    existing = _load(_path_for(fingerprint.family_id, root))
    prior_hits = existing.hits if existing else 0

    cs = CapturedStrategy(
        family_id=fingerprint.family_id,
        fingerprint=fingerprint.to_dict(),
        winner_rung=winner_rung,
        ledger_class=ledger_class,
        priors=priors,
        metadata={
            "captured_at": _now(),
            "captured_against": {"host_sld": fingerprint.host_sld,
                                 "base_url_redacted": _redact_url(base_url)},
            "score": {"verified": len(endpoints), "winner": winner_rung},
            "convergence_first": {
                "rungs_run": rungs_run,
                "live_calls": int(budget.get("live_calls", 0)),
                "synth_tokens": int(budget.get("synth_tokens", 0)),
                "rounds": int(budget.get("rounds", 0)),
                "used_brain": bool(getattr(cascade_result, "used_brain", False)),
            },
            "hits": prior_hits,
        })
    _write(cs, root)
    # ÍNDICE multi-clave: aliases bajo las claves más débiles (host) → la reinyección
    # por host pega GRATIS (sin sniff) aunque la familia sea doc/resolved.
    for k in fingerprint.all_keys:
        if k != cs.family_id:
            _write_alias(k, cs.family_id, root)
    return cs


# ══════════════════════════════════════════════════════════════════════════════
# lookup + flywheel (FASE 3c · la reinyección)
# ══════════════════════════════════════════════════════════════════════════════
def lookup(keys: Sequence[str], *, root: Path = CAPTURE_DIR) -> Optional[CapturedStrategy]:
    """Primera familia capturada que matchee una de las claves (fuerte→débil).
    Resuelve ALIAS (host→canónica) transparentemente."""
    for k in keys:
        d = _read_json(_path_for(k, root))
        if d is None:
            continue
        if "alias_of" in d:                     # alias → cargá la canónica
            d = _read_json(_path_for(d["alias_of"], root))
        if d is not None and "family_id" in d:
            return CapturedStrategy.from_dict(d)
    return None


def record_hit(cs: CapturedStrategy, *, root: Path = CAPTURE_DIR) -> CapturedStrategy:
    """Reinyección exitosa → +1 hit (la señal del data-flywheel: qué familias rinden)."""
    cs.metadata["hits"] = cs.hits + 1
    cs.metadata["last_hit_at"] = _now()
    _write(cs, root)
    return cs


# ══════════════════════════════════════════════════════════════════════════════
# META — el índice agregado (no per-entry)
# ══════════════════════════════════════════════════════════════════════════════
def all_entries(*, root: Path = CAPTURE_DIR) -> list[CapturedStrategy]:
    """Entradas CANÓNICAS (los aliases host→canónica se saltan, no se cuentan)."""
    p = Path(root)
    if not p.exists():
        return []
    out = []
    for f in sorted(p.glob("*.json")):
        d = _read_json(f)
        if d is None or "alias_of" in d:
            continue
        out.append(CapturedStrategy.from_dict(d))
    return out


def stats(*, root: Path = CAPTURE_DIR) -> dict:
    entries = all_entries(root=root)
    by_class: dict[str, int] = {}
    for e in entries:
        by_class[e.ledger_class] = by_class.get(e.ledger_class, 0) + 1
    return {
        "ledger": "META",
        "families": len(entries),
        "total_hits": sum(e.hits for e in entries),
        "by_class": by_class,
        "index": [{"family_id": e.family_id, "winner": e.winner_rung,
                   "ledger_class": e.ledger_class, "hits": e.hits,
                   "tools": len(e.priors.get("endpoints", []))} for e in entries],
    }


# ══════════════════════════════════════════════════════════════════════════════
# IO (json atómico)
# ══════════════════════════════════════════════════════════════════════════════
def _path_for(family_id: str, root: Path) -> Path:
    safe = re.sub(r"[^a-z0-9._-]+", "_", family_id.lower()).strip("_") or "x"
    return Path(root) / f"{safe}.json"


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _load(path: Path) -> Optional[CapturedStrategy]:
    """Carga una entrada CANÓNICA (no resuelve aliases; eso lo hace lookup())."""
    d = _read_json(path)
    if d is None or "alias_of" in d or "family_id" not in d:
        return None
    return CapturedStrategy.from_dict(d)


def _write_json(path: Path, payload: dict) -> None:
    Path(path.parent).mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
    os.replace(tmp, path)


def _write(cs: CapturedStrategy, root: Path) -> None:
    _write_json(_path_for(cs.family_id, root), cs.to_dict())


def _write_alias(key: str, family_id: str, root: Path) -> None:
    """Apuntador liviano key→canónica (no dupliza la entrada)."""
    _write_json(_path_for(key, root), {"alias_of": family_id})


def clear(*, root: Path = CAPTURE_DIR) -> int:
    """Borra TODAS las entradas (para tests). Devuelve cuántas borró."""
    p = Path(root)
    if not p.exists():
        return 0
    n = 0
    for f in p.glob("*.json"):
        f.unlink()
        n += 1
    return n


__all__ = [
    "CAPTURE_DIR", "SCHEMA_VERSION", "CapturedStrategy",
    "capture", "lookup", "record_hit", "all_entries", "stats", "clear",
    "endpoint_to_dict", "candidate_from_dict", "classify_ledger",
]
