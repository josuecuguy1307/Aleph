#!/usr/bin/env python3
"""test_obra_cap.py — ticket B3/IN4 · una obra rica grande NO tumba el run.

_capture_rich_obra embebe el JSON de la obra inline en out["obra"]. Un artefacto grande (el
offender real: un fieldplot 512×1682 ≈ 7.9 MB) inflaba la respuesta y tumbaba el run. El cap
(_cap_obra) downsamplea las grillas o devuelve un placeholder liviano; la obra completa queda
descargable en Biblioteca. Estos tests prueban el cap sin DB/red.

Corre:  PYTHONPATH=<wt>/product/backend python3 -m pytest .../test_obra_cap.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import repo as phase1_repo
from app.phase1.executor import (
    _cap_obra, _capture_rich_obra, _capture_workdir_outputs,
    _downsample_fieldplot, _MAX_OBRA_BYTES,
)


def _fieldplot(nx: int, ny: int) -> dict:
    n = nx * ny
    vals = [(-100.0 + (i % 97) * 0.37) for i in range(n)]   # determinista
    return {"type": "fieldplot",
            "grid": {"nx": nx, "ny": ny, "values": vals, "min": -107.0, "max": -43.0,
                     "unit": "dB", "interpolate": True}}


def _bytes(o) -> int:
    return len(json.dumps(o, ensure_ascii=False).encode("utf-8"))


def test_small_obra_passes_through_unchanged():
    small = _fieldplot(128, 64)              # ~76 KB, bajo el cap
    assert _bytes(small) < _MAX_OBRA_BYTES
    assert _cap_obra(small) is small, "una obra chica NO debe tocarse (identidad preservada)"


def test_oversized_fieldplot_downsamples_under_cap():
    big = _fieldplot(512, 1682)              # ~13 MB > cap → downsample
    assert _bytes(big) > _MAX_OBRA_BYTES, "pre-condición: la grilla grande excede el cap"
    capped = _cap_obra(big)
    assert capped is not big, "una obra sobre-cap debe transformarse"
    assert capped.get("type") == "fieldplot", "downsample preserva el tipo → La Sala lo sigue rindiendo"
    assert "_downsampled" in capped, "debe marcar que fue downsampleada"
    assert _bytes(capped) <= _MAX_OBRA_BYTES, "SEV: la obra capada SIGUE excediendo el cap (tumbaría el run)"
    g = capped["grid"]
    assert g["nx"] * g["ny"] == len(g["values"]), "la grilla downsampleada debe ser consistente (nx*ny==len)"
    assert g["nx"] < 512 and g["ny"] < 1682, "debe haber reducido dimensiones"
    assert g["min"] == -107.0 and g["unit"] == "dB", "preserva min/max/unit (la escala del render)"


def test_oversized_non_grid_falls_to_placeholder():
    huge = {"type": "imagen", "content": "A" * (_MAX_OBRA_BYTES + 100)}   # no downsampleable
    capped = _cap_obra(huge)
    assert capped.get("oversized") is True, "una obra grande no-grilla debe caer al placeholder liviano"
    assert capped.get("type") == "imagen" and "Biblioteca" in capped.get("note", "")
    assert _bytes(capped) < 10_000, "el placeholder debe ser CHICO (no re-embebe la obra)"


def test_failsafe_non_dict_returned_as_is():
    assert _cap_obra("no soy dict") == "no soy dict"
    assert _cap_obra(None) is None


def test_downsample_helper_rejects_bad_shape():
    # values cuya longitud no cuadra con nx*ny → None (→ placeholder, no crash)
    assert _downsample_fieldplot({"grid": {"nx": 10, "ny": 10, "values": [1, 2, 3]}}) is None
    assert _downsample_fieldplot({"grid": {}}) is None


# ── LA PROMESA ES REAL: el placeholder dice "descargable en tu Biblioteca" ──────────
# persona usuaria (probarlo, no razonarlo): que la obra COMPLETA exista de verdad como output
# descargable cuando el placeholder lo promete. El seam: _capture_rich_obra lee el
# artifact del workdir y lo embebe inline (→ capado a placeholder si es grande) MIENTRAS
# _capture_workdir_outputs escanea el MISMO workdir y captura ese archivo como kind=file
# (uri=ruta, bytes completos) = la fila de Biblioteca. Los dos leen el mismo disco: el
# placeholder no promete un archivo que no está — apunta al que el escaneo SÍ capturó.

class _RecordingCreateOutput:
    """Reemplaza phase1_repo.create_output para capturar lo persistido SIN DB.
    Se usa como context manager para restaurar el original (corre bajo pytest y standalone)."""
    def __init__(self):
        self.rows: list[dict] = []
        self._orig = None
    def __enter__(self):
        self._orig = phase1_repo.create_output
        def _fake(conn, *, run_id, kind, mime=None, uri=None, bytes_=None, content=None, **kw):
            row = {"id": f"out_{len(self.rows)+1}", "run_id": run_id, "kind": kind,
                   "mime": mime, "uri": uri, "bytes": bytes_}
            self.rows.append(row)
            return row
        phase1_repo.create_output = _fake
        return self
    def __exit__(self, *exc):
        phase1_repo.create_output = self._orig
        return False


def test_placeholder_promise_full_obra_is_downloadable_in_biblioteca():
    """Obra grande NO-downsampleable (imagen) → out['obra'] es el placeholder que promete
    Biblioteca, Y el archivo COMPLETO queda capturado como output kind=file (la fila real de
    Biblioteca), con sus bytes completos > cap. La promesa del placeholder no es hueca."""
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        big_content = "A" * (_MAX_OBRA_BYTES + 500_000)          # > cap, no es grilla
        obra_file = wd / "segmentacion.imagen.json"
        obra_file.write_text(json.dumps({"type": "imagen", "content": big_content}))
        full_bytes = obra_file.stat().st_size
        assert full_bytes > _MAX_OBRA_BYTES, "pre-cond: el archivo en disco excede el cap inline"

        # (1) inline: _capture_rich_obra lo lee → _cap_obra lo capa a placeholder que PROMETE Biblioteca
        inline = _cap_obra(_capture_rich_obra(str(wd)))
        assert inline.get("oversized") is True and "Biblioteca" in inline.get("note", ""), \
            "la obra grande debe caer al placeholder que promete Biblioteca"
        assert _bytes(inline) < 10_000, "el placeholder es liviano (NO reembebe la obra)"

        # (2) Biblioteca: _capture_workdir_outputs escanea el MISMO workdir y captura el archivo REAL
        with _RecordingCreateOutput() as rec:
            captured = _capture_workdir_outputs(object(), "run_promise", str(wd))
        mine = [r for r in rec.rows if Path(r["uri"] or "").name == "segmentacion.imagen.json"]
        assert len(mine) == 1, "SEV: el placeholder promete Biblioteca pero el archivo NO se capturó como output"
        row = mine[0]
        assert row["kind"] == "file", "la obra descargable debe ser kind=file"
        assert row["bytes"] == full_bytes, "Biblioteca guarda la obra COMPLETA (bytes completos, no el placeholder)"
        assert Path(row["uri"]).resolve() == obra_file.resolve(), "la uri apunta al archivo real en disco"
        # y el valor de retorno (evidencia) también lo lista
        assert any(c["name"] == "segmentacion.imagen.json" and c["bytes"] == full_bytes for c in captured)


def test_downsampled_fieldplot_full_resolution_still_in_biblioteca():
    """Aun cuando la grilla se downsamplea inline (para no tumbar el run), la obra a resolución
    COMPLETA sigue descargable en Biblioteca (kind=file con los bytes completos)."""
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        big = _fieldplot(512, 1682)                              # ~13 MB > cap
        obra_file = wd / "vonmises.fieldplot.json"
        obra_file.write_text(json.dumps(big))
        full_bytes = obra_file.stat().st_size
        assert full_bytes > _MAX_OBRA_BYTES

        inline = _cap_obra(_capture_rich_obra(str(wd)))
        assert "_downsampled" in inline and _bytes(inline) <= _MAX_OBRA_BYTES, \
            "inline: la grilla se downsamplea para entrar en el cap"
        assert inline["grid"]["nx"] < 512, "el inline perdió resolución (downsample)"

        with _RecordingCreateOutput() as rec:
            _capture_workdir_outputs(object(), "run_fp", str(wd))
        mine = [r for r in rec.rows if Path(r["uri"] or "").name == "vonmises.fieldplot.json"]
        assert len(mine) == 1 and mine[0]["bytes"] == full_bytes, \
            "la obra a resolución COMPLETA (no downsampleada) sigue en Biblioteca kind=file"


if __name__ == "__main__":
    tests = [test_small_obra_passes_through_unchanged, test_oversized_fieldplot_downsamples_under_cap,
             test_oversized_non_grid_falls_to_placeholder, test_failsafe_non_dict_returned_as_is,
             test_downsample_helper_rejects_bad_shape,
             test_placeholder_promise_full_obra_is_downloadable_in_biblioteca,
             test_downsampled_fieldplot_full_resolution_still_in_biblioteca]
    ok = 0
    for fn in tests:
        try:
            fn(); print(f"  ✓ {fn.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}\n      → {e}")
    print(f"  {ok}/{len(tests)} verdes")
    raise SystemExit(0 if ok == len(tests) else 1)
