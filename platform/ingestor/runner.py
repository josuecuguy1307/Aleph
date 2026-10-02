#!/usr/bin/env python3
"""
runner.py — The deterministic refresh engine. Applies a parse recipe to a raw
file and emits structured data + per-datum provenance. ZERO model calls.

WHY THIS EXISTS — the two clocks
--------------------------------
A model authors the parse recipe ONCE (slow clock, paid once): it inspects a new
source and writes down — as JSON — which page/table, which orientation, how each
column cleans, which rows to skip. From then on this runner is the FAST clock: it
loads that recipe and re-derives the structured rows on every refresh in
milliseconds for $0 of cognition. Re-running on the same (or refreshed) file
NEVER touches an LLM — that is the whole point, and the test suite proves it by
asserting no network/model module is ever imported on the refresh path.

The runner is NICHE-AGNOSTIC and FORMAT-BLIND: it consumes the recipe + an
ExtractedTable and produces `Datum`s. Adding a source = writing a recipe, not
editing this file.

Two table orientations the recipe can declare:
  • "matrix"  — first column is a row LABEL (indicator), remaining columns are a
                dimension (years, regions…). Each (row,col) cell becomes a datum.
                This is the BCE/INEC table shape.
  • "records" — first row is a HEADER, each later row is a record; columns map to
                fields. This is the classic CSV shape.

Anti-fabrication is structural: a cell that fails its cleaner becomes a Datum with
ok=False + the error, carrying its provenance — it is NEVER dropped silently nor
replaced with a guessed value. A PDF page that is image-only is refused up front.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from cleaners import apply_cleaner
from extractors import (
    ExtractedTable, extract_csv_table, extract_pdf_table,
    pdf_page_is_textual, sha256_of_file,
)
from provenance import Datum, Locator, Provenance, Source


# A module-level tripwire the tests assert on: if anything on the refresh path
# ever reached out to a model, it would have to import one of these. The runner
# imports NONE of them. (Documented invariant, checked in test_no_cognition.)
COGNITION_MODULES_FORBIDDEN = (
    "openai", "anthropic", "litellm", "groq", "httpx", "requests", "urllib.request",
)


# ── Recipe model ────────────────────────────────────────────────────────────────

@dataclass
class ColumnSpec:
    """How to read and clean one column (matrix) or field (records)."""
    label: str                       # the column/field's human name
    cleaner: str = "raw"             # name in cleaners.CLEANERS
    cleaner_opts: Optional[dict] = None
    field: Optional[str] = None      # logical field name to tag the datum with


@dataclass
class ParseRecipe:
    """
    The reusable, model-authored-once parse spec for ONE source.

    Persisted as JSON next to the data team's catalog. The runner consumes it
    deterministically; nothing here is inferred at refresh time.
    """
    recipe_id: str
    source_kind: str                 # "pdf" | "csv"
    orientation: str                 # "matrix" | "records"
    # location:
    page: Optional[int] = None       # PDF: 1-based page
    table_index: int = 0             # PDF: which table on the page
    delimiter: str = ","             # CSV
    encoding: str = "utf-8"          # CSV
    table_settings: Optional[dict] = None  # pdfplumber tuning
    # shape:
    header_rows_to_skip: int = 0     # rows above the data to drop (titles/noise)
    skip_blank_value_rows: bool = True   # matrix: rows whose value cells are all blank (group headers)
    row_label_cleaner: str = "text"  # matrix: how to clean the row label
    row_label_cleaner_opts: Optional[dict] = None
    columns: list[ColumnSpec] = None  # per data column (matrix) / per field (records)
    # bookkeeping for provenance:
    source_url: Optional[str] = None
    notes: Optional[str] = None
    schema_version: str = "ingestor-recipe/v1"

    @staticmethod
    def from_dict(d: dict) -> "ParseRecipe":
        cols = [ColumnSpec(**c) for c in d.get("columns", [])]
        kw = {k: v for k, v in d.items() if k != "columns"}
        return ParseRecipe(columns=cols, **kw)

    @staticmethod
    def load(path: str) -> "ParseRecipe":
        with open(path, "r", encoding="utf-8") as f:
            return ParseRecipe.from_dict(json.load(f))

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "columns"}
        d["columns"] = [c.__dict__ for c in (self.columns or [])]
        return d


@dataclass
class IngestResult:
    recipe_id: str
    source: Source
    data: list[Datum]
    refreshed_at: str
    n_ok: int
    n_error: int

    def to_dict(self) -> dict:
        return {
            "recipe_id": self.recipe_id,
            "source": self.source.__dict__,
            "refreshed_at": self.refreshed_at,
            "n_ok": self.n_ok,
            "n_error": self.n_error,
            "data": [d.to_dict() for d in self.data],
        }


# ── The engine ───────────────────────────────────────────────────────────────────

def _build_source(path: str, recipe: ParseRecipe,
                  fetched_at: Optional[str]) -> Source:
    return Source(
        file=os.path.basename(path),
        sha256=sha256_of_file(path),
        kind=recipe.source_kind,
        url=recipe.source_url,
        fetched_at=fetched_at,
    )


def _extract(path: str, recipe: ParseRecipe) -> ExtractedTable:
    if recipe.source_kind == "pdf":
        if recipe.page is None:
            raise ValueError("pdf recipe requires `page`")
        # anti-fabrication: refuse an image-only page rather than emit empty rows
        if not pdf_page_is_textual(path, page=recipe.page):
            raise RuntimeError(
                f"page {recipe.page} of {os.path.basename(path)} is image-only / "
                f"non-textual — cannot extract a table without OCR. REPORTED, not faked.")
        return extract_pdf_table(path, page=recipe.page,
                                 table_index=recipe.table_index,
                                 table_settings=recipe.table_settings)
    if recipe.source_kind == "csv":
        return extract_csv_table(path, delimiter=recipe.delimiter,
                                 encoding=recipe.encoding)
    raise ValueError(f"unknown source_kind {recipe.source_kind!r}")


def _ingest_matrix(table: ExtractedTable, recipe: ParseRecipe,
                   source: Source) -> list[Datum]:
    """First col = row label; each subsequent col is a recipe column -> one datum/cell."""
    data: list[Datum] = []
    rows = table.rows[recipe.header_rows_to_skip:]
    for r_off, row in enumerate(rows):
        r_idx = r_off + recipe.header_rows_to_skip
        if not row:
            continue
        label_res = apply_cleaner(recipe.row_label_cleaner, row[0],
                                  recipe.row_label_cleaner_opts)
        row_label = label_res.value
        value_cells = row[1:]
        # group-header rows (label present, all value cells blank) carry no data
        if recipe.skip_blank_value_rows and all(
                (c is None or str(c).strip() == "") for c in value_cells):
            continue
        for c_off, col in enumerate(recipe.columns or []):
            c_idx = c_off + 1
            raw = row[c_idx] if c_idx < len(row) else ""
            res = apply_cleaner(col.cleaner, raw, col.cleaner_opts)
            prov = Provenance(
                source=source,
                locator=Locator(
                    page=table.page, table_index=table.table_index,
                    row_index=r_idx, col_index=c_idx,
                    row_label=row_label, col_label=col.label,
                ),
                raw=raw,
            )
            data.append(Datum(value=res.value, provenance=prov, cleaner=res.cleaner,
                              ok=res.ok, error=res.error, field=col.field or col.label))
    return data


def _ingest_records(table: ExtractedTable, recipe: ParseRecipe,
                    source: Source) -> list[Datum]:
    """First (post-skip) row = header; each later row = record; columns map by index."""
    rows = table.rows[recipe.header_rows_to_skip:]
    if not rows:
        return []
    header = rows[0]
    body = rows[1:]
    data: list[Datum] = []
    for r_off, row in enumerate(body):
        r_idx = r_off + recipe.header_rows_to_skip + 1
        for c_off, col in enumerate(recipe.columns or []):
            raw = row[c_off] if c_off < len(row) else ""
            res = apply_cleaner(col.cleaner, raw, col.cleaner_opts)
            col_label = col.label or (header[c_off] if c_off < len(header) else f"col{c_off}")
            prov = Provenance(
                source=source,
                locator=Locator(
                    page=table.page, table_index=table.table_index,
                    row_index=r_idx, col_index=c_off,
                    row_label=None, col_label=col_label,
                ),
                raw=raw,
            )
            data.append(Datum(value=res.value, provenance=prov, cleaner=res.cleaner,
                              ok=res.ok, error=res.error, field=col.field or col_label))
    return data


def run_ingest(raw_path: str, recipe: ParseRecipe, *,
               fetched_at: Optional[str] = None) -> IngestResult:
    """
    Deterministic refresh entrypoint. raw file + recipe -> structured data with
    provenance. Imports no model/network module — a refresh costs $0 of cognition.
    """
    source = _build_source(raw_path, recipe, fetched_at)
    table = _extract(raw_path, recipe)
    if recipe.orientation == "matrix":
        data = _ingest_matrix(table, recipe, source)
    elif recipe.orientation == "records":
        data = _ingest_records(table, recipe, source)
    else:
        raise ValueError(f"unknown orientation {recipe.orientation!r}")
    n_ok = sum(1 for d in data if d.ok)
    return IngestResult(
        recipe_id=recipe.recipe_id,
        source=source,
        data=data,
        refreshed_at=datetime.now(timezone.utc).isoformat(),
        n_ok=n_ok,
        n_error=len(data) - n_ok,
    )


def run_ingest_from_recipe_file(raw_path: str, recipe_path: str,
                                **kw) -> IngestResult:
    return run_ingest(raw_path, ParseRecipe.load(recipe_path), **kw)
