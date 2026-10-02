#!/usr/bin/env python3
"""
cleaners.py — Deterministic, pure value-cleaning primitives for the ingestor.

WHY THIS EXISTS
---------------
"Two clocks" (FOUNDRY F4-C): a model AUTHORS the parse recipe ONCE (expensive,
one-off — it figures out that this BCE column is "miles de dólares" in latin
number format, that `xx` is header noise, that a blank-value row is a group
header). The DETERMINISTIC CODE then RUNS that recipe on every refresh (ms, $0).

This module is the deterministic half. Every function here is PURE: a raw string
in, a cleaned value (or a typed error) out — no model, no I/O, no global state.
That is what makes a refresh cost $0 of cognition: the recipe names which cleaner
to apply per column, and these run in microseconds.

The cleaners are NICHE-AGNOSTIC. The latin-number cleaner exists because a real
BCE PDF writes `-1.075.428` (dot = thousands, comma = decimal); it is not a
"finanzas" rule, it is a locale rule any source in that locale needs. A recipe
for a US source would name `number_en` instead. The forms are generic; the
recipe picks the values.

Each cleaner returns a `CleanResult` so the runner can attach provenance AND
record WHY a value failed validation (anti-fabrication: a cell we could not parse
becomes an explicit error, never a guessed number).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class CleanResult:
    """Outcome of cleaning one raw cell value."""
    ok: bool
    value: Any                 # cleaned, typed value when ok; None when not
    raw: Any                   # the original input, always preserved (provenance)
    cleaner: str               # which cleaner ran (recipe traceability)
    error: Optional[str] = None  # why it failed (anti-fabrication audit trail)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


# ── Cleaners (each: (raw, **opts) -> CleanResult) ──────────────────────────────

def clean_text(raw: Any, *, strip: bool = True, collapse_ws: bool = True,
               drop: tuple[str, ...] = ()) -> CleanResult:
    """
    Normalize a text cell: trim, collapse internal whitespace/newlines, and drop
    a recipe-supplied list of noise tokens (e.g. the literal `xx` the BCE header
    carries, or a footnote marker). Pure string surgery — nothing inferred.
    """
    s = _as_str(raw)
    if strip:
        s = s.strip()
    if collapse_ws:
        s = re.sub(r"\s+", " ", s)
    for token in drop:
        s = s.replace(token, "")
    s = s.strip()
    return CleanResult(True, s, raw, "text")


# Number formats: the recipe declares which locale a column uses. These are the
# two common shapes; both are pure transforms, no guessing of which one applies.
def clean_number_latin(raw: Any, *, allow_blank: bool = True) -> CleanResult:
    """
    Latin/European number: '.' groups thousands, ',' is the decimal separator.
    '-1.075.428'  -> -1075428.0
    '60,5'        -> 60.5
    '116'         -> 116.0
    A blank cell is a legitimate non-value in matrix tables (group-header rows),
    returned ok=True value=None when allow_blank, else an error.
    """
    s = _as_str(raw).strip()
    s = s.replace(" ", "").replace(" ", "")          # NBSP / thin spaces
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")  # unicode minus/dashes
    if s in ("", "-", "n/a", "N/A", "s/d", "S/D", "..."):
        if allow_blank:
            return CleanResult(True, None, raw, "number_latin")
        return CleanResult(False, None, raw, "number_latin", error="blank")
    candidate = s.replace(".", "").replace(",", ".")
    try:
        return CleanResult(True, float(candidate), raw, "number_latin")
    except ValueError:
        return CleanResult(False, None, raw, "number_latin",
                           error=f"not a latin number: {s!r}")


def clean_number_en(raw: Any, *, allow_blank: bool = True) -> CleanResult:
    """
    English number: ',' groups thousands, '.' is the decimal separator.
    '1,075,428.50' -> 1075428.5
    """
    s = _as_str(raw).strip()
    s = s.replace(" ", "").replace(" ", "")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    if s in ("", "-", "n/a", "N/A", "..."):
        if allow_blank:
            return CleanResult(True, None, raw, "number_en")
        return CleanResult(False, None, raw, "number_en", error="blank")
    candidate = s.replace(",", "")
    try:
        return CleanResult(True, float(candidate), raw, "number_en")
    except ValueError:
        return CleanResult(False, None, raw, "number_en",
                           error=f"not an english number: {s!r}")


def clean_percent(raw: Any, *, locale: str = "latin") -> CleanResult:
    """
    Percent cell -> fraction. '60,5%' (latin) -> 0.605 ; '17.8%' (en) -> 0.178.
    Keeps the raw for provenance; a malformed percent is an error, not a guess.
    """
    s = _as_str(raw).strip().rstrip("%").strip()
    base = clean_number_latin(s) if locale == "latin" else clean_number_en(s)
    if not base.ok or base.value is None:
        return CleanResult(base.ok and base.value is None, base.value, raw,
                           "percent", error=base.error)
    return CleanResult(True, base.value / 100.0, raw, "percent")


def clean_date(raw: Any, *, formats: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y",
                                                         "%m/%d/%Y")) -> CleanResult:
    """Parse a date against a recipe-supplied list of strptime formats (first hit wins)."""
    s = _as_str(raw).strip()
    for fmt in formats:
        try:
            return CleanResult(True, datetime.strptime(s, fmt).date().isoformat(),
                               raw, "date")
        except ValueError:
            continue
    return CleanResult(False, None, raw, "date",
                       error=f"no format matched {formats} for {s!r}")


# ── Registry: recipe names a cleaner by string; this maps the name to the fn ───

CLEANERS: dict[str, Callable[..., CleanResult]] = {
    "text": clean_text,
    "number_latin": clean_number_latin,
    "number_en": clean_number_en,
    "percent": clean_percent,
    "date": clean_date,
    # "raw" = keep the value verbatim (still wrapped for provenance)
    "raw": lambda raw, **_: CleanResult(True, raw, raw, "raw"),
}


def apply_cleaner(name: str, raw: Any, opts: Optional[dict] = None) -> CleanResult:
    """Run the cleaner the recipe named. Unknown name = hard error (no silent pass)."""
    fn = CLEANERS.get(name)
    if fn is None:
        return CleanResult(False, None, raw, name, error=f"unknown cleaner {name!r}")
    return fn(raw, **(opts or {}))
