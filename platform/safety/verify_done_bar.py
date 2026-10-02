#!/usr/bin/env python3
"""
verify_done_bar.py — demuestra las 3 BARRAS de T9 contra el ENTORNO REAL (no self-report).

Aísla estado en un DATA_ROOT temporal (no toca data/ real, no deja kill-switch trabado).
Ejercita los SEAMS reales (no solo la librería): la tool sintetizada (replay) rechazando
un destino interno, el blast-radius frenando un masivo, y el gate legal por nicho.

  python platform/safety/verify_done_bar.py
"""
from __future__ import annotations

import os
import tempfile

os.environ["ALEPH_DATA_ROOT"] = tempfile.mkdtemp(prefix="aleph-verify-")
os.environ["ALEPH_WRITE_BLAST_MAX"] = "5"
os.environ.pop("ALEPH_SAFETY_ALLOW_PRIVATE_TARGETS", None)

import sys
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLATFORM))

from safety import guards, kill_switch, legal_gates           # noqa: E402
from safety.guards import SafetyBlocked                       # noqa: E402

# el seam real de la tool sintetizada
sys.path.insert(0, str(_PLATFORM / "inspection"))
from inspection.observe.replay import SynthesizedTool         # noqa: E402

OK, BAD = "✓", "✗"
fails = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global fails
    mark = OK if cond else BAD
    if not cond:
        fails += 1
    print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))


print("\nDONE-BAR 1 · el recon rechaza una URL interna")
for u in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:6379/",
          "http://10.0.0.5/", "file:///etc/passwd"):
    try:
        guards.guard_recon(u, subject="verify")
        check(f"recon {u}", False, "NO fue rechazada")
    except SafetyBlocked as e:
        check(f"recon rechaza {u}", True, getattr(e, "meta", {}).get("ssrf_reason", str(e)[:40]))

# el SEAM real de la tool sintetizada (replay) hacia un destino interno
spec_internal = {
    "label": "leak", "category": "write",
    "mcp_tool": {"name": "leak_tool", "inputSchema": {"type": "object", "properties": {}, "required": []}},
    "request": {"method": "POST", "url": "http://169.254.169.254/latest/meta-data/", "body": {"x": 1}},
    "param_slots": [],
}
res = SynthesizedTool(spec_internal).call({}, execute=True, allow_write=True, subject="verify")
check("tool sintetizada (replay) rechaza POST a metadata", res.get("refused") is True
      and res.get("by") == "safety", res.get("reason", "")[:50])

print("\nDONE-BAR 2 · un write masivo se puede frenar")
subj = "verify-blast"
ok_writes = 0
blocked = False
for i in range(8):
    try:
        guards.guard_agent_write(subj, tool="send_email")
        ok_writes += 1
    except SafetyBlocked:
        blocked = True
        break
check("blast-radius frena el masivo", blocked and ok_writes == 5,
      f"{ok_writes} writes pasaron, luego se frenó (cap=5)")
check("kill-switch del sujeto quedó trabado", kill_switch.is_tripped(subject=subj) is not None)
kill_switch.reset(f"user:{subj}")
try:
    guards.guard_agent_write(subj, tool="send_email")
    check("reset reanuda los writes", True)
except SafetyBlocked:
    check("reset reanuda los writes", False)

# kill-switch manual global frena a TODOS
kill_switch.trip("global", "verify")
try:
    guards.guard_agent_write("otro-usuario", tool="x")
    check("kill global frena a todos", False)
except SafetyBlocked:
    check("kill global frena a todos", True)
kill_switch.reset("global")

print("\nDONE-BAR 3 · un nicho legal-gated pide humano")
ing = legal_gates.enforce({"meta": {"nicho": "ingenieria"}}, env="prod")
check("ingeniería exige human-in-loop", ing["require_human"] is True, ing["basis"])
med_prod = legal_gates.enforce({"meta": {"nicho": "medicina"}}, env="prod")
check("medicina en prod BLOQUEADA (HIPAA)", med_prod["allow"] is False, med_prod["reason"] or "")
med_dev = legal_gates.enforce({"meta": {"nicho": "medicina"}}, env="dev")
check("medicina en dev/test permitida con humano", med_dev["allow"] and med_dev["require_human"])
fin = legal_gates.enforce({"meta": {"nicho": "finanzas"}}, env="prod")
check("finanzas anexa descargo de asesoría", "asesoría" in (fin["notice"] or "").lower())

print(f"\n{'TODO VERDE' if fails == 0 else f'{fails} FALLO(S)'}  "
      f"(DATA_ROOT efímero: {os.environ['ALEPH_DATA_ROOT']})")
raise SystemExit(1 if fails else 0)
