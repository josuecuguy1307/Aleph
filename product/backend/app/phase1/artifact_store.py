"""
artifact_store.py — MULTI-ARTIFACT store per session. [Gate 4 · Fase 2 · §5 del contrato]

UN chat ↔ MUCHOS artifacts; one ORDERED list per session, one JSON file per
session, stdlib only (the engine the censo Ó3 called «lo que ya funciona» stays).
What Fase 2 adds — contract: ~/Desktop/FASE2-CONTRATO-ARTEFACTOS.md:

  · PATHS: everything under aleph_paths.data_root()/artifacts. The old
    `parents[4]` arithmetic dies by construction — under PyInstaller it fell
    INSIDE `_MEIPASS` (the bundle temp, purged on close): every app close took
    the user's artifacts with it (censo §J.1, the same measured bug rag_store
    fixed). Client → Application Support, next to aleph.db/rag/espacios;
    control → the historic tree, byte-identical.
  · SCHEMA v2, READ at load (Ó14: declaring without reading is decorative):
    v1/absent repairs IN MEMORY (never rewrites disk on read); a FUTURE version
    refuses WRITES with a visible cause (writing over a newer format is how
    data dies silently) while reads pass through.
  · TYPE: closed union at the WRITE border (artifacts.vocabulary — the ONE
    vocabulary). Unknown type → typed visible rejection, never a silent
    coercion. Legacy strings on disk are preserved as-is at read.
  · PROVENANCE: required block per artifact AND per version (identity inside:
    quién/qué modelo/qué tool/cuándo — built by artifacts.provenance, resolved
    server-side from the space's events.jsonl, never trusted from the client).
  · INTEGRITY: content_sha256 per current content and per version; flock around
    every load-modify-save (two tabs of the same agent share a session since
    the domain key of contract §6.2); atomic tmp+os.replace writes; a corrupt
    file is RENAMED (.corrupt-<ts>) and logged — never silently discarded
    (B-9: fallo visible, jamás mudo).
  · MIGRATION (lossless): at first access per process, every *.json in the old
    tree location that is missing in the new root is COPIED (never moved, never
    overwritten). In frozen the old path falls inside _MEIPASS (empty): what
    J.1 already lost is not recoverable and we say so instead of pretending.

artifact = { id, session_id, title, type, content, content_sha256, provenance,
             versions:[{content, at, content_sha256?, provenance?}...],
             created_at, updated_at }
Rules: new → create+append · edit → snapshot of the PREVIOUS content (with its
provenance) to versions[] + update · revert → restore last previous version,
content AND provenance together · failed run → the caller does NOT call here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aleph.artifacts")

# The OLD arithmetic — kept ONLY as (a) the dev fallback when platform/ is not
# on sys.path, and (b) the source location the migration copies FROM. It is the
# exact path the previous binary wrote to; using it once to rescue data is the
# opposite of depending on it.
_REPO = Path(__file__).resolve().parents[4]
_LEGACY_ART_ROOT = _REPO / "product" / "backend" / "data" / "artifacts"

_MAX_CONTENT = 600_000
_MAX_VERSIONS = 20   # history cap per artifact (no infinite growth)
SCHEMA_VERSION = 2   # of the per-session FILE — read in _load, or it is decoration

_ADVERTISED_PLATFORM = False


def _wire_platform_path() -> None:
    """Put the tree's platform/ on sys.path (the same self-rescue
    aleph_paths.is_client uses for role). In frozen the normal import succeeds
    (bundled), so the parents[] fallback only runs in dev where it is correct."""
    plat = str(_REPO / "platform")
    if plat not in sys.path and (_REPO / "platform").is_dir():
        sys.path.insert(0, plat)


def _import_platform(name: str):
    """Import a FLAT platform/ module (aleph_paths, role)."""
    global _ADVERTISED_PLATFORM
    try:
        return __import__(name)
    except ImportError:
        _wire_platform_path()
        try:
            return __import__(name)
        except ImportError:
            if not _ADVERTISED_PLATFORM:
                log.warning("artifact_store: platform module %r unavailable", name)
                _ADVERTISED_PLATFORM = True
            return None


def _vocab():
    """The one type vocabulary (artifacts.vocabulary), or None if platform/ is
    unreachable — readers repair best-effort without it; the WRITE border
    refuses to run blind (see _validate_type)."""
    try:
        from artifacts import vocabulary
        return vocabulary
    except ImportError:
        _wire_platform_path()
        try:
            from artifacts import vocabulary
            return vocabulary
        except ImportError:
            return None


def art_root() -> Path:
    """Where artifact sessions live. aleph_paths decides by role (client →
    user data dir, control → historic tree); dev without platform falls to the
    tree — the pre-Fase-2 behavior, so nothing regresses in a bare checkout."""
    ap = _import_platform("aleph_paths")
    if ap is not None:
        try:
            return ap.data_root() / "artifacts"
        except Exception:
            pass
    return _LEGACY_ART_ROOT


class StoreError(Exception):
    """Typed, visible store failure (never a silent fallback). The router maps
    `code` → HTTP and surfaces `detail` verbatim."""

    def __init__(self, code: str, http_status: int = 422, **detail: Any):
        self.code = code
        self.http_status = http_status
        self.detail = detail
        super().__init__(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_sid(sid: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]", "_", str(sid or "").strip())[:120]
    return s or "default"


def _sha256(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _path(sid: str) -> Path:
    return art_root() / (_safe_sid(sid) + ".json")


# ── lossless migration from the old tree location ────────────────────────────
_migration_done = False


def _migrate_legacy_once() -> None:
    """Copy every session file from the OLD tree location that the NEW root does
    not have. Idempotent, additive, re-scanned once per process (one listdir —
    cheaper than a marker that could lie). Never moves, never overwrites: if a
    name exists in the new root, the new one rules and the old stays where it
    was, as its own backup. Two processes racing copy identical bytes — benign."""
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    try:
        new = art_root()
        old = _LEGACY_ART_ROOT
        try:
            if old.resolve() == new.resolve():
                return  # control role: data_root() IS the tree — nothing moves
        except OSError:
            return
        if not old.is_dir():
            return
        copied = 0
        new.mkdir(parents=True, exist_ok=True)
        for src in sorted(old.glob("*.json")):
            dst = new / src.name
            if dst.exists():
                continue
            try:
                shutil.copy2(src, dst)
                copied += 1
            except OSError as exc:
                log.warning("artifact migration: could not copy %s: %s", src.name, exc)
        if copied:
            log.info("artifact migration: %d session file(s) copied %s -> %s",
                     copied, old, new)
    except Exception as exc:  # migration must never take the store down
        log.warning("artifact migration failed (store continues): %s", exc)


# ── per-session exclusive lock (two tabs share a session since contract §6.2) ──
@contextmanager
def _locked(sid: str):
    """flock around load-modify-save. POSIX fcntl / Windows msvcrt (the
    events_replay.py pattern); if neither exists, proceed unlocked — the
    pre-Fase-2 behavior, not a new hole."""
    root = art_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / (_safe_sid(sid) + ".lock")
    fh = open(lock_path, "a+")
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except ImportError:
            try:
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            except ImportError:
                pass
        yield
    finally:
        try:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
        finally:
            fh.close()


# ── load / save ──────────────────────────────────────────────────────────────

def _fresh(sid: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "session_id": _safe_sid(sid), "artifacts": []}


def _repair_v1(data: dict) -> dict:
    """v1 (schema_version absent) → v2 shape IN MEMORY (strict at borders,
    repairing in view — ley técnica 2). Disk is untouched by reads: it only
    changes when a real write passes the strict border. Known aliases normalize
    (deterministic map); unknown legacy strings are preserved untouched —
    rewriting them would be guessing, and migration is lossless by law."""
    vocab = _vocab()
    data.setdefault("schema_version", SCHEMA_VERSION)
    for a in data.get("artifacts", []) or []:
        if not isinstance(a, dict):
            continue
        a.setdefault("provenance", None)      # unknown origin, confessed — never invented
        a.setdefault("content_sha256", None)  # not stored by v1; only writes stamp hashes
        if vocab is not None:
            t = a.get("type")
            norm = vocab.normalize(t)
            if norm is not None and norm != t:
                a["type"] = norm              # alias → canonical (in memory)
    data["schema_version"] = SCHEMA_VERSION
    return data


def _load(sid: str) -> dict:
    _migrate_legacy_once()
    p = _path(sid)
    if not p.exists():
        return _fresh(sid)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("session file is not a JSON object")
    except Exception as exc:
        # VISIBLE failure, ZERO loss: the unreadable file is renamed, never
        # discarded (the old policy here — silent discard — is the exact B-9
        # violation the censo flagged on this store).
        quarantine = p.with_name(p.name + f".corrupt-{int(time.time())}")
        try:
            os.replace(p, quarantine)
            log.error("artifact store: unreadable session %s (%s) — moved to %s, starting clean",
                      p.name, exc, quarantine.name)
        except OSError:
            log.error("artifact store: unreadable session %s (%s) — could not quarantine",
                      p.name, exc)
        return _fresh(sid)
    ver = data.get("schema_version")
    if ver in (None, 1):
        return _repair_v1(data)
    if isinstance(ver, int) and ver > SCHEMA_VERSION:
        # Written by a NEWER Aleph: reads pass through raw, writes are refused
        # (see _require_writable) — overwriting a future format destroys data.
        data["_readonly_newer_schema"] = True
        return data
    return data


def _require_writable(data: dict) -> None:
    if data.get("_readonly_newer_schema"):
        raise StoreError("artifact_session_newer_schema", http_status=409,
                         found=data.get("schema_version"), supported=SCHEMA_VERSION)


def _save(sid: str, data: dict) -> None:
    """Atomic write (tmp + os.replace): a process dying mid-write can no longer
    leave a half-JSON behind."""
    data.pop("_readonly_newer_schema", None)
    data["schema_version"] = SCHEMA_VERSION
    root = art_root()
    root.mkdir(parents=True, exist_ok=True)
    p = _path(sid)
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ── the write border (contract §3.4) ─────────────────────────────────────────

def _validate_type(type_: str) -> str:
    """Closed union + aliases from THE vocabulary. Absent → the documented API
    default ('informe'). Present-but-unknown → typed rejection: the silent
    free-string sink of v1 dies here."""
    t = (type_ or "").strip()
    if not t:
        return "informe"
    vocab = _vocab()
    if vocab is None:
        # Border without its vocabulary is a border in name only — fail closed,
        # visibly (never silently accept what we cannot validate).
        raise StoreError("artifact_vocabulary_unavailable", http_status=500)
    norm = vocab.normalize(t)
    if norm is None:
        raise StoreError("artifact_type_invalid", http_status=422,
                         type=t, allowed=sorted(vocab.CANONICAL))
    return norm


def _validate_provenance(provenance: Any) -> dict:
    """Structural presence (dd-agents: a new artifact without its evidence block
    cannot be constructed). The block is built by artifacts.provenance — here we
    only refuse writes that arrive without one."""
    if not isinstance(provenance, dict) or not provenance:
        raise StoreError("artifact_provenance_missing", http_status=422)
    for k in ("schema", "captured_at", "produced_by", "capture_quality"):
        if k not in provenance:
            raise StoreError("artifact_provenance_missing", http_status=422, missing=k)
    return provenance


# ── owner (unchanged semantics; new root + lock) ─────────────────────────────

def get_owner(sid: str) -> Optional[str]:
    """user_id owning the artifact session, or None for anonymous/legacy
    sessions. The router owner-gates on this: with owner → only the owner;
    without → open (does not break old sessions)."""
    o = _load(sid).get("owner")
    return str(o) if o else None


def claim_owner(sid: str, user_id: Optional[str]) -> Optional[str]:
    """Bind the session to an owner the FIRST time (set-if-unset, idempotent).
    Never rewrites an existing owner (the router blocks that with 403 earlier)."""
    if not user_id:
        return get_owner(sid)
    with _locked(sid):
        data = _load(sid)
        if not data.get("owner"):
            _require_writable(data)
            data["owner"] = str(user_id)
            _save(sid, data)
        return str(data.get("owner")) if data.get("owner") else None


# ── reads ────────────────────────────────────────────────────────────────────

def list_artifacts(sid: str) -> list:
    """ORDERED summaries (no heavy content/versions — for the Library).

    `workspace` IS part of the summary, and it is the only field here that does not
    describe the artifact's shape: it says WHERE the work was done. The Library —the
    caller this function names— had no way to tell a workspace's output from the Sala's,
    so its per-space filter could only ever render empty. It is read from provenance and
    never from the item body: provenance is resolved server-side from the space's events,
    which is exactly why it can be trusted to group by.

    `None` for everything the Sala produced. That is not a gap: «no workspace» is the
    honest value for work that did not happen inside one, and it is what puts that work
    under GENERAL and under nothing else.
    """
    out = []
    for a in _load(sid).get("artifacts", []):
        prov = a.get("provenance") if isinstance(a.get("provenance"), dict) else {}
        out.append({"id": a.get("id"), "title": a.get("title"), "type": a.get("type"),
                    "created_at": a.get("created_at"), "updated_at": a.get("updated_at"),
                    "n_versions": len(a.get("versions", [])),
                    "workspace": prov.get("workspace")})
    return out


def get_artifact(sid: str, aid: str) -> Optional[dict]:
    for a in _load(sid).get("artifacts", []):
        if a.get("id") == aid:
            return a
    return None


# ── writes ───────────────────────────────────────────────────────────────────

def create_artifact(sid: str, title: str, type_: str, content: str,
                    provenance: dict) -> dict:
    norm_type = _validate_type(type_)
    prov = _validate_provenance(provenance)
    body = str(content or "")[:_MAX_CONTENT]
    with _locked(sid):
        data = _load(sid)
        _require_writable(data)
        art = {
            "id": uuid.uuid4().hex[:12],
            "session_id": _safe_sid(sid),
            "title": (title or "Obra").strip()[:200],
            "type": norm_type,
            "content": body,
            "content_sha256": _sha256(body),
            "provenance": prov,
            "versions": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        data.setdefault("artifacts", []).append(art)
        _save(sid, data)
        return art


def edit_artifact(sid: str, aid: str, content: str, title: Optional[str] = None,
                  provenance: Optional[dict] = None) -> Optional[dict]:
    """Snapshot of the PREVIOUS content — WITH its provenance — to versions[],
    then update. The new content carries the provenance of the turn that edited
    it (each version owns its identity; openscience store.ts:45-48)."""
    prov = _validate_provenance(provenance) if provenance is not None else None
    body = str(content or "")[:_MAX_CONTENT]
    with _locked(sid):
        data = _load(sid)
        for a in data.get("artifacts", []):
            if a.get("id") == aid:
                _require_writable(data)
                prev_content = a.get("content", "")
                a.setdefault("versions", []).append({
                    "content": prev_content,
                    "at": a.get("updated_at"),
                    "content_sha256": a.get("content_sha256") or _sha256(prev_content),
                    "provenance": a.get("provenance"),
                })
                a["versions"] = a["versions"][-_MAX_VERSIONS:]
                a["content"] = body
                a["content_sha256"] = _sha256(body)
                if prov is not None:
                    a["provenance"] = prov
                if title:
                    a["title"] = title.strip()[:200]
                a["updated_at"] = _now()
                _save(sid, data)
                return a
        return None


def revert_artifact(sid: str, aid: str) -> Optional[dict]:
    """Restore the LAST previous version — content AND provenance together
    (never an old content wearing the new content's identity). None if no
    history."""
    with _locked(sid):
        data = _load(sid)
        for a in data.get("artifacts", []):
            if a.get("id") == aid:
                versions = a.get("versions", [])
                if not versions:
                    return None
                _require_writable(data)
                prev = versions.pop()
                restored = prev.get("content", "")
                a["content"] = restored
                a["content_sha256"] = prev.get("content_sha256") or _sha256(restored)
                a["provenance"] = prev.get("provenance")
                a["updated_at"] = _now()
                _save(sid, data)
                return a
        return None


def reown(old_user_id: str, new_user_id: str) -> int:
    """MERGE (soft login): artifact sessions owned by the device user move to
    the account. Walks the store on disk (no owner index); an unreadable
    session is skipped without breaking the rest. Returns how many changed."""
    _migrate_legacy_once()
    old, new = str(old_user_id), str(new_user_id)
    root = art_root()
    if not old or not new or old == new or not root.is_dir():
        return 0
    n = 0
    for p in sorted(root.glob("*.json")):
        sid = p.stem
        with _locked(sid):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("_readonly_newer_schema"):
                continue
            if str(data.get("owner") or "") == old:
                if isinstance(data.get("schema_version"), int) and data["schema_version"] > SCHEMA_VERSION:
                    log.warning("reown: skipping %s (newer schema %s)", p.name, data.get("schema_version"))
                    continue
                data["owner"] = new
                _save(sid, data)
                n += 1
    return n


__all__ = ["list_artifacts", "get_artifact", "create_artifact", "edit_artifact",
           "revert_artifact", "get_owner", "claim_owner", "reown",
           "art_root", "StoreError", "SCHEMA_VERSION"]
