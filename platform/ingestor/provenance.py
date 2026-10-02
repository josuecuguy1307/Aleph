#!/usr/bin/env python3
"""
provenance.py — Per-datum origin record. Pure data, no I/O.

WHY THIS EXISTS
---------------
The anti-fabrication bar (FOUNDRY, especially Research/Finanzas): a structured
number is worthless to a delegated agent unless the agent can point at WHERE it
came from. "EBITDA fell 12%" is a hallucination risk; "EBITDA fell 12% [BCE
EstMacro012024.pdf, p.15, row 'Diferencia Ingreso y Costo', col '2023', sha256
2175ba…]" is a citation.

Every structured datum the ingestor emits carries a `Provenance`:
  • source  — the file (name + sha256), its url, and when it was fetched.
  • locator — WHERE inside the source: page, the table's row label, the column
              label, plus 0-based row/col indices for an exact re-find.
  • raw     — the original cell text BEFORE cleaning (so a reviewer can audit the
              cleaning, and a disagreement is resolvable against the source).

sha256 is what makes a refresh trustworthy: if the file bytes changed, the hash
changes, and a downstream consumer knows the provenance points at a different
document — no silent drift.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Optional


@dataclass(frozen=True)
class Source:
    """Identity of the raw artifact a datum came from."""
    file: str                      # basename of the raw file
    sha256: str                    # hash of the raw bytes (drift detection)
    kind: str                      # "pdf" | "csv" | ...
    url: Optional[str] = None      # where it was fetched, if any
    fetched_at: Optional[str] = None  # ISO timestamp of the fetch (one-off)


@dataclass(frozen=True)
class Locator:
    """WHERE inside the source the datum sits — enough to re-find it by hand."""
    page: Optional[int] = None     # 1-based PDF page; None for CSV
    table_index: Optional[int] = None  # which table on that page (0-based)
    row_index: Optional[int] = None    # 0-based row within the extracted table
    col_index: Optional[int] = None    # 0-based column
    row_label: Optional[str] = None    # human label of the row (e.g. indicator name)
    col_label: Optional[str] = None    # human label of the column (e.g. "2023")

    def human(self) -> str:
        bits = []
        if self.page is not None:
            bits.append(f"p.{self.page}")
        if self.row_label:
            bits.append(f"row={self.row_label!r}")
        elif self.row_index is not None:
            bits.append(f"row#{self.row_index}")
        if self.col_label:
            bits.append(f"col={self.col_label!r}")
        elif self.col_index is not None:
            bits.append(f"col#{self.col_index}")
        return ", ".join(bits)


@dataclass(frozen=True)
class Provenance:
    source: Source
    locator: Locator
    raw: Any                        # the cell text BEFORE cleaning

    def citation(self) -> str:
        """One-line human citation an agent can show next to the value."""
        return f"{self.source.file} [{self.locator.human()}] (sha256 {self.source.sha256[:12]}…)"

    def to_dict(self) -> dict:
        return {"source": asdict(self.source), "locator": asdict(self.locator),
                "raw": self.raw}


@dataclass
class Datum:
    """One structured value + its full provenance + cleaning audit."""
    value: Any
    provenance: Provenance
    cleaner: str
    ok: bool = True
    error: Optional[str] = None
    field: Optional[str] = None      # logical field name if the recipe assigned one

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "ok": self.ok,
            "error": self.error,
            "cleaner": self.cleaner,
            "provenance": self.provenance.to_dict(),
            "citation": self.provenance.citation(),
        }
