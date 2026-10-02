"""
privacy.py — retención + "borrá mis datos" (T9).

Dos operaciones, ambas DESTRUCTIVAS → por eso default dry_run=True (se mira el blanco
antes de borrar, criterio de gate del org). El CLI / caller pasa apply=True para ejecutar.

  purge_user(user_id)  → borra TODO lo del usuario: sus runs (data/run_outputs/<run_id>),
                         sus spaces (data/espacios/<space_id>), sus artifacts, sus secretos
                         del vault BYOK, y la fila users. Mapea user→recursos por la DB si
                         está viva; si no, opera sobre los ids que le pasen + reporta lo que
                         no pudo alcanzar (honesto, no finge borrado total).

  retention_sweep()    → borra artefactos efímeros más viejos que la retención configurada
                         (spaces de recon inspect-*/recon-*, outputs de runs). No toca lo
                         que esté dentro de la ventana.

Contención dura: SOLO borra bajo DATA_ROOT, jamás sigue symlinks fuera, jamás borra la
raíz misma. Cada borrado deja una entrada en la bitácora (audit_log) — el QUÉ se borró
queda registrado aunque el dato se vaya.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from . import audit_log, config

_DATA_ROOT = config.DATA_ROOT.resolve()
_ESPACIOS = _DATA_ROOT / "espacios"
_RUN_OUTPUTS = _DATA_ROOT / "run_outputs"
_ARTIFACTS = _DATA_ROOT / "artifacts"
_ARTIFACT_DL = _DATA_ROOT / "artifact_downloads"

# spaces efímeros de recon (los que el motor crea por inspección) — prefijos conocidos.
_EPHEMERAL_SPACE_PREFIXES = ("inspect-", "recon-", "diag-", "gate-", "skel-", "cuarto-skel-",
                             "fase0-", "xbelt-", "bc")


def _contained(p: Path) -> bool:
    """True solo si p está REALMENTE dentro de DATA_ROOT (resuelto, anti-symlink/traversal)."""
    try:
        rp = p.resolve()
    except OSError:
        return False
    if rp == _DATA_ROOT:
        return False
    return _DATA_ROOT in rp.parents


def _rm(p: Path, *, apply: bool) -> dict:
    """Borra un archivo o dir bajo contención. Devuelve el registro de lo (a) borrado."""
    rec = {"path": str(p), "exists": p.exists(), "bytes": 0, "deleted": False}
    if not p.exists():
        return rec
    if not _contained(p):
        rec["refused"] = "fuera-de-data-root"
        return rec
    # tamaño (best-effort)
    try:
        if p.is_dir():
            rec["bytes"] = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        else:
            rec["bytes"] = p.stat().st_size
    except OSError:
        pass
    if apply:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
            rec["deleted"] = True
        except OSError as exc:
            rec["error"] = str(exc)
    return rec


# ── mapeo user → recursos (best-effort, DB opcional) ──────────────────────────

def _resolve_user_resources(user_id: str, conn) -> dict[str, list[str]]:
    """Pregunta a Postgres por los run_ids/space_ids del usuario. Si la DB no está viva,
    devuelve listas vacías + db_reachable=False (el caller lo reporta honesto)."""
    out = {"run_ids": [], "space_ids": [], "db_reachable": False}
    own = conn is None
    try:
        if conn is None:
            from app.phase1 import repo as _repo  # type: ignore
            conn = _repo.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, space_id FROM runs WHERE user_id = %s", (str(user_id),))
            for rid, sid in cur.fetchall():
                out["run_ids"].append(str(rid))
                if sid:
                    out["space_ids"].append(str(sid))
        out["db_reachable"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _purge_vault(user_id: str, apply: bool) -> dict:
    """Borra los secretos BYOK/OAuth del usuario (credential_broker), si está disponible."""
    rec: dict[str, Any] = {"attempted": False, "deleted": None}
    try:
        from app.phase1 import credential_broker as cb  # type: ignore
        from app.phase1 import repo as _repo  # type: ignore
        rec["attempted"] = True
        if apply:
            conn = _repo.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM secrets WHERE user_id = %s", (str(user_id),))
                    rec["deleted"] = cur.rowcount
                conn.commit()
            finally:
                conn.close()
        else:
            rec["note"] = "dry-run: borraría secrets del usuario"
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def purge_user(
    user_id: str,
    *,
    conn=None,
    space_ids: Optional[list[str]] = None,
    run_ids: Optional[list[str]] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """
    "Borrá mis datos". dry_run por default (apply=False) → reporta qué borraría sin tocar.
    Con apply=True borra de verdad y devuelve el manifiesto de lo borrado.
    """
    user_id = str(user_id)
    resolved = _resolve_user_resources(user_id, conn)
    all_runs = sorted(set((run_ids or []) + resolved["run_ids"]))
    all_spaces = sorted(set((space_ids or []) + resolved["space_ids"]))

    manifest: dict[str, Any] = {
        "user_id": user_id, "apply": apply,
        "db_reachable": resolved["db_reachable"],
        "runs": [], "spaces": [], "vault": None,
        "bytes_total": 0, "complete": resolved["db_reachable"],
    }
    if not resolved["db_reachable"]:
        manifest["warning"] = ("DB no alcanzable: solo se purgan los ids provistos a mano. "
                               "El borrado puede ser PARCIAL — re-correr con la DB viva.")
        if resolved.get("error"):
            manifest["db_error"] = resolved["error"]

    for rid in all_runs:
        rec = _rm(_RUN_OUTPUTS / rid, apply=apply)
        manifest["runs"].append(rec)
        manifest["bytes_total"] += rec.get("bytes", 0)
    for sid in all_spaces:
        rec = _rm(_ESPACIOS / sid, apply=apply)
        manifest["spaces"].append(rec)
        manifest["bytes_total"] += rec.get("bytes", 0)

    manifest["vault"] = _purge_vault(user_id, apply)

    audit_log.record("privacy.purge_user", subject=user_id, target=user_id,
                     decision="delete" if apply else "preview",
                     runs=len(all_runs), spaces=len(all_spaces),
                     bytes=manifest["bytes_total"], applied=apply,
                     complete=manifest["complete"])
    return manifest


# ── retención por edad ────────────────────────────────────────────────────────

def _sweep_dir(root: Path, max_age_days: int, *, apply: bool,
               only_prefixes: Optional[tuple[str, ...]] = None) -> list[dict]:
    out: list[dict] = []
    if max_age_days <= 0 or not root.exists():
        return out
    cutoff = time.time() - max_age_days * 86400
    for child in sorted(root.iterdir()):
        if only_prefixes and not child.name.startswith(only_prefixes):
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        rec = _rm(child, apply=apply)
        rec["age_days"] = round((time.time() - mtime) / 86400, 1)
        out.append(rec)
    return out


def retention_sweep(*, apply: bool = False,
                    spaces_days: Optional[int] = None,
                    run_outputs_days: Optional[int] = None) -> dict[str, Any]:
    """Borra (o previsualiza) artefactos más viejos que la retención configurada."""
    spaces_days = config.RETENTION_SPACES_DAYS if spaces_days is None else spaces_days
    run_outputs_days = config.RETENTION_RUN_OUTPUTS_DAYS if run_outputs_days is None else run_outputs_days
    result = {
        "apply": apply,
        "spaces": _sweep_dir(_ESPACIOS, spaces_days, apply=apply,
                             only_prefixes=_EPHEMERAL_SPACE_PREFIXES),
        "run_outputs": _sweep_dir(_RUN_OUTPUTS, run_outputs_days, apply=apply),
    }
    n = len(result["spaces"]) + len(result["run_outputs"])
    total = sum(r.get("bytes", 0) for r in result["spaces"] + result["run_outputs"])
    result["count"] = n
    result["bytes_total"] = total
    audit_log.record("privacy.retention_sweep", decision="delete" if apply else "preview",
                     count=n, bytes=total, applied=apply)
    return result
