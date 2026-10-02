#!/usr/bin/env python3
"""
extractors.py — Deterministic raw-table extraction. NO model, NO cognition.

WHY THIS EXISTS
---------------
The recipe says WHERE the table is (which page, which table index, or which CSV
delimiter). These extractors fetch exactly that grid of raw strings — they do not
interpret it. Interpretation (which row is a label, which column is a year, how
to clean a number) is the recipe's job, applied in runner.py.

Splitting "get the grid" from "apply the recipe" is what lets the SAME runner
handle PDF and CSV: each extractor returns the same shape — a list of rows of raw
cells — and the runner is format-blind from there.

pdfplumber is a deterministic layout engine (no LLM). For a CSV we use the stdlib
csv module. Both are $0 of cognition by construction.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractedTable:
    """A raw grid pulled from one location in a source."""
    rows: list[list[str]]              # raw cell strings, never cleaned here
    page: Optional[int] = None         # 1-based PDF page (None for CSV)
    table_index: Optional[int] = None  # which table on that page


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ── PDF ────────────────────────────────────────────────────────────────────────

def extract_pdf_table(path: str, *, page: int, table_index: int = 0,
                      table_settings: Optional[dict] = None) -> ExtractedTable:
    """
    Pull ONE table from ONE page of a PDF, deterministically.

    `page` is 1-based (matches what a human reads off the document and what the
    recipe stores). `table_index` selects among multiple tables on that page.
    `table_settings` is passed straight to pdfplumber (lines vs. text strategy);
    the recipe can tune it once if a table needs it.

    Raises if the page/table does not exist — a recipe pointing at a missing
    table is a hard failure, not a silent empty result (anti-false-green).
    """
    import pdfplumber  # local import: only PDF recipes pay the dependency cost

    with pdfplumber.open(path) as pdf:
        if page < 1 or page > len(pdf.pages):
            raise ValueError(f"page {page} out of range (1..{len(pdf.pages)})")
        pg = pdf.pages[page - 1]
        tables = pg.extract_tables(table_settings or {})
        if table_index >= len(tables):
            raise ValueError(
                f"table_index {table_index} not found on page {page} "
                f"(found {len(tables)} table(s))")
        raw = tables[table_index]
        rows = [[("" if c is None else str(c)) for c in row] for row in raw]
        return ExtractedTable(rows=rows, page=page, table_index=table_index)


def count_pdf_tables(path: str, *, page: int) -> int:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages[page - 1].extract_tables())


def pdf_page_is_textual(path: str, *, page: int, min_chars: int = 30) -> bool:
    """
    Anti-fabrication guard: a scanned/image PDF page yields ~0 extractable chars.
    The recipe runner calls this before trusting a PDF page; if it is image-only
    we REPORT it (cannot read) instead of emitting empty/garbage rows.
    """
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        if page < 1 or page > len(pdf.pages):
            raise ValueError(f"page {page} out of range (1..{len(pdf.pages)})")
        txt = pdf.pages[page - 1].extract_text() or ""
        return len(txt.strip()) >= min_chars


# ── CSV ─────────────────────────────────────────────────────────────────────────

def extract_csv_table(path: str, *, delimiter: str = ",",
                      encoding: str = "utf-8") -> ExtractedTable:
    """Read a whole CSV into a raw grid. Deterministic stdlib parse."""
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = [[c for c in row] for row in reader]
    return ExtractedTable(rows=rows, page=None, table_index=None)


def extract_csv_string(text: str, *, delimiter: str = ",") -> ExtractedTable:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return ExtractedTable(rows=[list(r) for r in reader], page=None, table_index=None)
