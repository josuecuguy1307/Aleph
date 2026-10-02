#!/usr/bin/env python3
"""
test_cleaners_and_csv.py — Pure cleaner correctness + the CSV records path +
the anti-fabrication contract (a bad cell is REPORTED, never guessed).
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ING = os.path.abspath(os.path.join(HERE, ".."))
if ING not in sys.path:
    sys.path.insert(0, ING)

from cleaners import (  # noqa: E402
    apply_cleaner, clean_number_en, clean_number_latin, clean_percent, clean_text,
)
from runner import run_ingest_from_recipe_file  # noqa: E402

CSV_RECIPE = os.path.join(ING, "recipes", "sample-records-en.json")
CSV_RAW = os.path.join(ING, "fixtures", "sample_records_en.csv")


# ── pure cleaners ──

def test_latin_number():
    assert clean_number_latin("-1.075.428").value == -1075428.0
    assert clean_number_latin("60,5").value == 60.5
    assert clean_number_latin("116").value == 116.0
    blank = clean_number_latin("")
    assert blank.ok and blank.value is None      # legitimate blank
    bad = clean_number_latin("abc")
    assert not bad.ok and bad.value is None and "not a latin number" in bad.error


def test_en_number():
    assert clean_number_en("1,075,428.50").value == 1075428.5
    assert clean_number_en("1,310,420").value == 1310420.0
    bad = clean_number_en("not_a_number")
    assert not bad.ok and bad.value is None       # NOT guessed


def test_percent():
    assert clean_percent("60,5%", locale="latin").value == pytest.approx(0.605)
    assert clean_percent("17.8%", locale="en").value == pytest.approx(0.178)


def test_text_drops_noise():
    r = clean_text("COMERCIALIZACIÓN xx", drop=("xx",))
    assert r.value == "COMERCIALIZACIÓN"


def test_unknown_cleaner_is_hard_error():
    r = apply_cleaner("does_not_exist", "x")
    assert not r.ok and "unknown cleaner" in r.error


# ── CSV records path + anti-fabrication ──

@pytest.mark.skipif(not os.path.exists(CSV_RAW), reason="csv fixture required")
def test_csv_records_with_error_cell_reported_not_faked():
    result = run_ingest_from_recipe_file(CSV_RAW, CSV_RECIPE)
    # 4 data rows x 3 columns = 12 datums (1 header row skipped)
    assert len(result.data) == 12
    values = {(d.provenance.locator.row_index, d.field): d for d in result.data}

    # row 1 (idx 1): the en-number "1,250,000.5" cleaned correctly
    v = values[(1, "value")]
    assert v.ok and v.value == 1250000.5
    assert v.provenance.raw == "1,250,000.5"  # raw preserved for audit

    # row 3 (idx 3): "N/A" is a legitimate blank, ok with value None
    blank = values[(3, "value")]
    assert blank.ok and blank.value is None

    # row 4 (idx 4): "not_a_number" MUST be an error datum, NOT a guessed value
    err = values[(4, "value")]
    assert not err.ok and err.value is None and err.error
    assert err.provenance.raw == "not_a_number"

    # the result counts the failure honestly
    assert result.n_error == 1


@pytest.mark.skipif(not os.path.exists(CSV_RAW), reason="csv fixture required")
def test_csv_determinism():
    a = run_ingest_from_recipe_file(CSV_RAW, CSV_RECIPE)
    b = run_ingest_from_recipe_file(CSV_RAW, CSV_RECIPE)
    assert [d.to_dict() for d in a.data] == [d.to_dict() for d in b.data]
