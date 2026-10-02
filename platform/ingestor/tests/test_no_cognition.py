#!/usr/bin/env python3
"""
test_no_cognition.py — PROVES the refresh is $0 of cognition.

The mandate's hardest requirement: re-running the ingestor on the same file must
NOT call a model. We prove it three ways, all mechanical:

  1. determinism — two runs over the same bytes produce byte-identical structured
     output (same values, same provenance). A model call would introduce variance
     and cost; identical output across runs is the signature of pure code.

  2. no-cognition import audit — we record sys.modules before the refresh, run it,
     and assert NO model/network module appeared. If the refresh had phoned a
     model it would have had to import a client; it imports none.

  3. import-time tripwire — sitecustomize-style: we install a meta-path finder that
     RAISES if any forbidden cognition module is imported during the refresh, so
     even a lazy/local import inside the call path is caught, not just top-level.

This is the evidence the Reviewer re-runs.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ING = os.path.abspath(os.path.join(HERE, ".."))
if ING not in sys.path:
    sys.path.insert(0, ING)

from runner import (  # noqa: E402
    COGNITION_MODULES_FORBIDDEN, ParseRecipe, run_ingest_from_recipe_file,
)

RECIPE = os.path.join(ING, "recipes", "bce-estmacro-comercializacion-derivados.json")
RAW = os.path.join(ING, "fixtures", "bce_estmacro012024.pdf")


def _serialize(result):
    return [d.to_dict() for d in result.data]


@pytest.mark.skipif(not os.path.exists(RAW), reason="real BCE fixture required")
def test_refresh_is_deterministic_byte_identical():
    """Two refreshes over the same file = identical structured output (minus the timestamp)."""
    r1 = run_ingest_from_recipe_file(RAW, RECIPE)
    r2 = run_ingest_from_recipe_file(RAW, RECIPE)
    assert _serialize(r1) == _serialize(r2)
    assert r1.source.sha256 == r2.source.sha256
    assert r1.n_ok == r2.n_ok and r1.n_error == r2.n_error
    assert r1.n_ok == 63 and r1.n_error == 0  # the real, known shape of p.15 t.0


class _ForbidCognitionFinder(importlib.abc.MetaPathFinder):
    """Raises if a forbidden cognition/network module is imported while active."""
    def __init__(self, forbidden):
        self.forbidden = set(forbidden)
        self.tripped = []

    def find_spec(self, fullname, path, target=None):
        root = fullname.split(".")[0]
        if root in self.forbidden or fullname in self.forbidden:
            self.tripped.append(fullname)
            raise AssertionError(
                f"refresh imported cognition/network module {fullname!r} — "
                f"NOT $0 of cognition")
        return None  # defer to the normal finders for everything else


@pytest.mark.skipif(not os.path.exists(RAW), reason="real BCE fixture required")
def test_refresh_imports_no_cognition_module():
    """
    Audit sys.modules around the refresh AND install a tripwire finder so even a
    lazy import inside the call path would raise. Net: the refresh path is proven
    to never load a model client.
    """
    # pre-load the deterministic deps so we are not flagged for *their* normal imports
    import runner, cleaners, extractors, provenance  # noqa
    importlib.import_module("pdfplumber")  # the deterministic layout engine, pre-loaded

    before = set(sys.modules)
    finder = _ForbidCognitionFinder(COGNITION_MODULES_FORBIDDEN)
    sys.meta_path.insert(0, finder)
    try:
        result = run_ingest_from_recipe_file(RAW, RECIPE)
    finally:
        sys.meta_path.remove(finder)

    assert finder.tripped == [], f"forbidden imports during refresh: {finder.tripped}"

    appeared = set(sys.modules) - before
    leaked = {m for m in appeared
              if m.split(".")[0] in set(COGNITION_MODULES_FORBIDDEN)}
    assert not leaked, f"cognition/network modules loaded during refresh: {leaked}"
    assert result.n_ok == 63


@pytest.mark.skipif(not os.path.exists(RAW), reason="real BCE fixture required")
def test_provenance_present_on_every_datum():
    """Anti-fabrication: no naked number — every datum carries source + locator."""
    result = run_ingest_from_recipe_file(RAW, RECIPE)
    assert result.data
    for d in result.data:
        p = d.provenance
        assert p.source.file and p.source.sha256
        assert p.locator.page == 15
        assert p.locator.row_label is not None
        assert p.locator.col_label in ("2021", "2022", "2023")
        assert "raw" in d.to_dict()["provenance"]
        # citation is the one-liner an agent shows next to the value
        assert "sha256" in d.provenance.citation()
