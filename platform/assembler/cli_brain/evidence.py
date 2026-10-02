"""Sanitized, per-device CLI execution evidence for provider status.

Only typed outcomes are persisted. Prompts, responses, tokens and raw CLI output
must never enter this file.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from .base import ERR_ACCESS_DENIED, STATE_ACCESS_DENIED, STATE_READY
from .registry import spec_by_id

_LOCK = threading.RLock()
_MODEL_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
# A provider policy can change outside Aleph. A past denial must not lock the
# provider forever; after a day the UI returns to unverified until the user tries.
EVIDENCE_TTL_S = 24 * 60 * 60


def _path() -> Path:
    import aleph_paths
    return Path(aleph_paths.user_data_dir()) / "modelos" / "cli-provider-evidence.json"


def _read() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version") == 1:
            return data.get("providers") if isinstance(data.get("providers"), dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def get(provider_id: str) -> dict:
    if spec_by_id(provider_id) is None:
        return {}
    with _LOCK:
        entry = _read().get(provider_id)
    return entry if isinstance(entry, dict) else {}


def _write(providers: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".cli-provider-evidence-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "providers": providers}, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def record_provider_rate_limit(provider_id: str, *, retry_after_s=None, reset_hint: str = "",
                               reset_at=None, reason: str = "rate_limit",
                               occurred_at=None) -> dict:
    """Persist the original provider limit as history, never as live quota truth."""
    if spec_by_id(provider_id) is None:
        raise ValueError("unknown CLI provider")
    try:
        retry = float(retry_after_s) if retry_after_s is not None else None
        if retry is not None and retry <= 0:
            retry = None
    except (TypeError, ValueError):
        retry = None
    try:
        reset = float(reset_at) if reset_at is not None else None
    except (TypeError, ValueError):
        reset = None
    at = float(occurred_at) if occurred_at is not None else time.time()
    event = {
        "state": "provider_rate_limited",
        "occurred_at": at,
        "retry_after_s": retry,
        "reset_hint": str(reset_hint or ""),
        "reset_at": reset,
        "reason": str(reason or "rate_limit")[:80],
        "origin": "provider",
    }
    with _LOCK:
        providers = dict(_read())
        previous = dict(providers.get(provider_id) or {})
        try:
            prior_at = float(previous.get("state_event_at", 0) or 0)
        except (TypeError, ValueError):
            prior_at = 0.0
        if at < prior_at:
            return dict(previous.get("last_provider_rate_limit") or event)
        sequence = int(previous.get("state_sequence", 0)) + 1
        previous.update({
            "state_sequence": sequence,
            "state_event_at": at,
            "last_provider_rate_limit": event,
            "last_execution_state": "provider_rate_limited",
            "quota_availability": "unknown",
        })
        providers[provider_id] = previous
        _write(providers)
    return dict(event)


def record(provider_id: str, *, ok: bool, error_kind: str = "", actual_model: str = "",
           retry_after_s=None, reset_hint: str = "", occurred_at=None) -> dict:
    if spec_by_id(provider_id) is None:
        raise ValueError("unknown CLI provider")
    access = "allowed" if ok else "denied" if error_kind == ERR_ACCESS_DENIED else "unknown"
    model = actual_model if isinstance(actual_model, str) and _MODEL_ID.fullmatch(actual_model) else ""
    occurred_at = float(occurred_at) if occurred_at is not None else time.time()
    entry = {
        "access_state": access,
        "last_test_state": "passed" if ok else "failed",
        "last_error_kind": "" if ok else str(error_kind or "unknown_provider_error")[:48],
        "actual_model": model if ok else "",
        "checked_at": occurred_at,
        "quota_availability": "unknown",
    }
    with _LOCK:
        providers = dict(_read())
        previous = dict(providers.get(provider_id) or {})
        try:
            prior_at = float(previous.get("state_event_at", 0) or 0)
        except (TypeError, ValueError):
            prior_at = 0.0
        # A response observed earlier can finish its persistence write after a newer
        # request. Do not let that stale write replace the newer provider state.
        if occurred_at < prior_at:
            return dict(previous)
        sequence = int(previous.get("state_sequence", 0)) + 1
        limit_event = previous.get("last_provider_rate_limit")
        if previous.get("execution_verified_after_limit_at") is not None:
            entry["execution_verified_after_limit_at"] = previous["execution_verified_after_limit_at"]
        if previous.get("execution_verified_at") is not None:
            entry["execution_verified_at"] = previous["execution_verified_at"]
        if not ok and error_kind == "rate_limit":
            try:
                retry = float(retry_after_s) if retry_after_s is not None else None
                if retry is not None and retry <= 0:
                    retry = None
            except (TypeError, ValueError):
                retry = None
            limit_event = {
                "state": "provider_rate_limited",
                "occurred_at": occurred_at,
                "retry_after_s": retry,
                "reset_hint": str(reset_hint or ""),
                "reset_at": occurred_at + retry if retry is not None else None,
                "reason": "rate_limit",
                "origin": "provider",
            }
            entry["last_execution_state"] = "provider_rate_limited"
        elif ok:
            entry["last_execution_state"] = (
                "execution_verified_after_limit" if isinstance(limit_event, dict)
                else "execution_verified"
            )
            entry["execution_verified_at"] = occurred_at
        else:
            entry["last_execution_state"] = "execution_failed"
        entry["state_sequence"] = sequence
        entry["state_event_at"] = occurred_at
        if isinstance(limit_event, dict):
            entry["last_provider_rate_limit"] = dict(limit_event)
        # A successful real invocation supersedes any earlier provider-limit state, but
        # retains the event and its original retry/reset hint for diagnostics.
        if ok and isinstance(limit_event, dict):
            entry["execution_verified_after_limit_at"] = occurred_at
        providers[provider_id] = entry
        _write(providers)
    return entry


def clear_access(provider_id: str) -> None:
    """Forget an old entitlement verdict when Claude auth is no longer verified.

    Keep the last execution outcome for diagnostics, but never revive an old
    ACCESS_ALLOWED / ACCESS_DENIED after a subsequent login.
    """
    if spec_by_id(provider_id) is None:
        return
    with _LOCK:
        providers = dict(_read())
        entry = providers.get(provider_id)
        if not isinstance(entry, dict) or entry.get("access_state") == "unknown":
            return
        providers[provider_id] = {**entry, "access_state": "unknown"}
        _write(providers)


def decorate_status(status: dict) -> dict:
    """Keep auth and access independent, while blocking a proven denial."""
    out = dict(status)
    history = get(str(out.get("provider") or ""))
    entry = history
    checked = entry.get("checked_at")
    if not isinstance(checked, (int, float)) or checked < time.time() - EVIDENCE_TTL_S:
        entry = {}
    access = entry.get("access_state") if entry.get("access_state") in ("allowed", "denied") else "unknown"
    if out.get("auth_state") != "authenticated":
        access = "unknown"
    out["access_state"] = access
    out["last_test_state"] = entry.get("last_test_state", "not_run")
    out["last_test_at"] = entry.get("checked_at")
    out["last_error_kind"] = entry.get("last_error_kind", "")
    out["last_actual_model"] = entry.get("actual_model", "")
    out["quota_availability"] = "unknown"
    out["last_execution_state"] = history.get("last_execution_state", "not_verified")
    out["last_provider_rate_limit"] = history.get("last_provider_rate_limit")
    out["execution_verified_after_limit_at"] = history.get("execution_verified_after_limit_at")
    if out.get("state") == STATE_READY and access == "denied":
        out["state"] = STATE_ACCESS_DENIED
        out["detail"] = "sesión activa; el proveedor denegó el acceso de suscripción"
    return out
