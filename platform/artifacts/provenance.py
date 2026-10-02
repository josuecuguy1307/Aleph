"""provenance.py — the identity INSIDE the artifact. [Gate 4 · Fase 2 · §3 del contrato]

Builds the `provenance` block that every new artifact (and every version) carries:
quién (user_id/agent_id) · qué modelo (model_final) · qué tool (tools/tool_calls)
· cuándo (captured_at) — plus the re-verifiable reference (space_id/run_id).

THE ANTI-GRIFT RULE (contract §3.2): the client only sends REFERENCES; the facts
(model_final, ok, degraded, tool_calls, tools) are resolved SERVER-SIDE by reading
the space's events.jsonl — the same signed records the Sala's estadoDeCostura and
qa/anti-fake-suite/check_provenance.py judge. If a surface could declare
model_final it would fabricate capacity (the exact class of bug that
sala.html:4289-4293 guards against for territories).

HONESTY RULES:
  - null != 0 (not-measured != measured-zero — the repo's latency_ms rule).
  - Nothing is ever downgraded to invented: no terminal event -> model_final null,
    never the recipe's model (the recipe is intent, not fact — Fase 1's lesson).
  - `capture_quality` says how much the block is worth (openscience
    backend/cli/src/artifact/store.ts:14): exact | declared | partial | unknown.

Events are read in BOTH shapes: flat (platform/assembler/session.py puts fields
at top level) and payload-nested (platform/flywheel/events_replay.py) — the same
normalization check_provenance.py applies.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aleph.artifacts")

SCHEMA = 1
QUALITY = ("exact", "declared", "partial", "unknown")
#: `workspace` [Gate 4 · Fase 3 · 3.4 · ley 0]: the content was produced by a FUNCTION
#: OF AN INHERITED STACK — one of its own tools, running in
#: its own process. Aleph measured the MODEL of that turn — it made the call and read
#: the answer — but it did not execute the function, so the artifact's content is
#: something Aleph was TOLD about. See `_cap_workspace` below: this value caps the
#: capture quality at `declared` even when the space closed cleanly. Saying `exact`
#: there would be the fabrication the anti-grift exists to catch.
PRODUCED_BY = ("run", "stream", "manual", "workspace", "unknown")

#: Producers whose CONTENT Aleph did not itself execute.
_DECLARED_CONTENT = ("workspace",)

#: Conservative charset for client-sent references. A ref is an OPAQUE id used
#: to compose a filesystem path (events_dir()/<space_id>/events.jsonl) — anything
#: outside this set is dropped (treated as absent), NEVER path-joined.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

#: Reference fields accepted from the caller, in the order they appear in the block.
#:
#: [Convergencia · superficie 7] The last three are the FOREIGN passport's identity, and
#: they are references — never facts. When an inherited stack carries its own provenance
#: (OpenScience's `ProvenanceEnvelope`, `science/provenance/envelope.ts`), Aleph re-derives
#: its own block from its own events and CAPS the quality at `declared` (`_cap_workspace`).
#: That is correct — Aleph measured the model, not the kernel — but until now the other
#: side was dropped whole: the crossing plugin copied four display fields and left
#: `contentHash` and the envelope behind, so a file the stack HAD executed and hashed
#: arrived with no way back.
#:
#: This module's own rule (see `_cap_workspace`) is «the reference stays, so anyone can
#: re-derive later». These three are that reference, and nothing more:
#:   · `source_sha256`   — the stack's content hash of the artifact BYTES
#:   · `source_run_ref`  — the run id inside the stack's own envelope
#:   · `source_commit`   — the code revision the envelope pinned
#: They are NEVER read to decide `capture_quality`: a foreign passport claiming `exact`
#: cannot buy credibility here, which is the whole point of the cap. They exist so the
#: claim is CHECKABLE — which is the opposite of trusting it.
_REF_FIELDS = ("space_id", "run_id", "chat_id", "agent_id", "user_id",
               "method_id", "method_run_id",
               "source_sha256", "source_run_ref", "source_commit")


def safe_ref(value: Any) -> Optional[str]:
    """The reference if it is shaped like an opaque id; None otherwise (dropped,
    logged). Dropping instead of erroring is deliberate: the artifact is the
    user's work — a malformed ref must not block persisting it."""
    s = str(value or "").strip()
    if not s:
        return None
    if not _SAFE_REF_RE.match(s):
        log.warning("provenance: dropped malformed ref %r", s[:40])
        return None
    return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_events(path: Path) -> Optional[dict]:
    """Read a space's events.jsonl and derive the signed facts.

    Returns None when the file is missing/unreadable (nothing resolved), else:
      {model_final, ok, degraded, run_id, tool_calls, tools, terminal_seen}
    `tool_calls` counts tool_call_finished with executed==True — the same signal
    the Sala's anti-grift reads (`executed` es la señal de «corrió»)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    tool_calls = 0
    tools: list[str] = []
    term: dict[str, Any] = {}
    terminal_seen = False
    parsed_any = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        payload = ev.get("payload")
        data = {**ev, **payload} if isinstance(payload, dict) else ev
        parsed_any = True
        etype = data.get("type")
        if etype == "tool_call_finished":
            if data.get("executed") is True:
                tool_calls += 1
                name = str(data.get("tool") or data.get("tool_name") or "?")
                if name not in tools:
                    tools.append(name)
        elif etype in ("final", "closed"):
            # later events override earlier ones (closed comes after final).
            for k in ("model_final", "ok", "degraded", "run_id"):
                if k in data:
                    term[k] = data[k]
            if etype == "closed":
                terminal_seen = True
    if not parsed_any:
        return None
    return {
        "model_final": term.get("model_final"),
        "ok": term.get("ok"),
        "degraded": term.get("degraded"),
        "run_id": term.get("run_id"),
        "tool_calls": tool_calls,
        "tools": sorted(tools),
        "terminal_seen": terminal_seen,
    }


def build(refs: dict, events_path: Optional[Path]) -> dict:
    """The provenance block for one write (create or edit — each version carries
    its own; contract §4).

    refs: client-declared REFERENCES only (space_id, run_id, chat_id, agent_id,
          user_id, method_id, method_run_id, source_sha256, source_run_ref,
          source_commit, intent, produced_by) — sanitized here; facts are never
          taken from it. The three `source_*` are the inherited stack's own
          passport and are inert: they are stored so the claim can be re-derived,
          and they NEVER feed `capture_quality` (see `_cap_workspace`).
    events_path: the space's events.jsonl (composed by the ROUTER from a
          safe_ref'd space_id), or None when there is no space to consult.
    """
    block: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": _now(),
        "produced_by": "unknown",
        "capture_quality": "unknown",
        "space_id": None, "run_id": None, "chat_id": None,
        "agent_id": None, "user_id": None, "intent": None,
        "model_final": None, "ok": None, "degraded": None,
        "tool_calls": None, "tools": None,
        "method_id": None, "method_run_id": None,
        "workspace": None,          # [F3 · 3.4] which inherited stack produced it
        # [Convergencia · superficie 7] The foreign passport, as REFERENCES. See _REF_FIELDS.
        "source_sha256": None, "source_run_ref": None, "source_commit": None,
        "resolved_from": None,
    }
    for k in _REF_FIELDS:
        block[k] = safe_ref(refs.get(k))
    pb = str(refs.get("produced_by") or "").strip().lower()
    if pb in PRODUCED_BY:
        block["produced_by"] = pb
    else:
        block["produced_by"] = "run" if block["space_id"] else "unknown"
    intent = str(refs.get("intent") or "").strip()
    if intent:
        block["intent"] = intent[:200]
    block["workspace"] = safe_ref(refs.get("workspace"))

    declared_run = block["run_id"]

    if block["space_id"] is None:
        # Nothing measurable to consult: the block holds only declared refs and
        # says so (dd-agents honesty: omit/annotate, never fabricate).
        block["capture_quality"] = "declared"
        block["resolved_from"] = "declared"
        return block

    resolved = _resolve_events(events_path) if events_path is not None else None
    if resolved is None:
        # A space was referenced but its events were not readable — keep the
        # reference (re-verifiable later, doc-haus §1.2) and confess.
        block["capture_quality"] = "partial"
        block["resolved_from"] = None
        return block

    block["resolved_from"] = "events"
    block["model_final"] = resolved["model_final"]
    block["ok"] = resolved["ok"]
    block["degraded"] = resolved["degraded"]
    block["tool_calls"] = resolved["tool_calls"]
    block["tools"] = resolved["tools"]
    if resolved["run_id"]:
        block["run_id"] = safe_ref(resolved["run_id"]) or block["run_id"]

    quality = "exact" if resolved["terminal_seen"] else "partial"
    if declared_run and resolved["run_id"] and str(declared_run) != str(resolved["run_id"]):
        # The client claimed one run and the space closed another: the signed
        # side wins the fields, the mismatch costs the quality.
        log.warning("provenance: declared run_id %s != events run_id %s (space %s)",
                    declared_run, resolved["run_id"], block["space_id"])
        quality = "partial"
    block["capture_quality"] = _cap_workspace(block["produced_by"], quality)
    return block


def _cap_workspace(produced_by: str, quality: str) -> str:
    """[Gate 4 · Fase 3 · 3.4 · ley 0] An artifact born from an INHERITED STACK'S OWN
    FUNCTION never claims `exact`, even when the space closed with a clean terminal.

    The terminal is real and so is `model_final`: Aleph made the model call and read
    the answer. What Aleph did NOT do is run `screen_stocks` — that happened in the
    stack's process, against the stack's sources, and everything Aleph knows about it
    arrived as a claim. `exact` is reserved for what Aleph executed and saw.

    This is the ley 0 trade written into the type: the domain belongs to the stack, so
    the artifact belongs to the stack — and the contract says so out loud instead of
    borrowing the credibility of a run Aleph did not perform. The reference stays, so
    anyone can re-derive the model side later (doc-haus §1.2)."""
    if produced_by in _DECLARED_CONTENT and quality == "exact":
        return "declared"
    return quality


__all__ = ["SCHEMA", "QUALITY", "PRODUCED_BY", "safe_ref", "build"]
