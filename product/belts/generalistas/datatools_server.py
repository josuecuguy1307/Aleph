#!/usr/bin/env python3
"""
datatools_server.py — Data-tools MCP server (stdio, JSON-RPC 2.0), keyless.

Belt DEFAULT (inline) · leg "archivos descargables". Produce ARCHIVOS REALES en
${PUPPET_WORKDIR} a partir de datos que el modelo ya tiene (computados con
run_python o de su contexto). El run-executor captura el workdir → Biblioteca,
así el .xlsx/.csv queda descargable de verdad. NO ejecuta código del modelo:
recibe datos estructurados (header + rows) y los escribe — superficie chica.

  • write_xlsx(filename, sheet_name, header, rows)
        Escribe un .xlsx REAL (openpyxl) en PUPPET_WORKDIR. Header en negrita,
        filas tal cual. Devuelve {ok, filename, path, rows, cols, cells}.
  • write_csv(filename, header, rows)
        Escribe un .csv REAL (stdlib csv) en PUPPET_WORKDIR.

Guardrails (mismo principio que pysandbox/finanzas):
  - escribe SOLO bajo ${PUPPET_WORKDIR} (Path(fn).name → nunca escapa el workdir).
  - read/compute/write-de-su-propio-output: el enforcer la clasifica auto-ejecuta
    (no toca plata ni manda afuera; el nombre no matchea money/send hints).
  - límites de tamaño para no abusar (filas/cols acotadas).
"""

import csv
import json
import os
import sys
from pathlib import Path

_MAX_ROWS = 50000
_MAX_COLS = 200
_CELL_LIMIT = 32000  # límite duro de openpyxl por celda


def _workdir() -> Path:
    wd = os.environ.get("PUPPET_WORKDIR")
    p = Path(wd).resolve() if wd else Path.cwd().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(filename: str, default: str, ext: str) -> Path:
    """Basename only (nunca escapa el workdir) + extensión forzada."""
    fn = (filename or default).strip() or default
    fn = Path(fn).name  # tira cualquier dir/.. → solo el nombre
    if not fn.lower().endswith(ext):
        fn = fn.rsplit(".", 1)[0] + ext if "." in fn else fn + ext
    return _workdir() / fn


def _coerce(v):
    """Celda → str/num seguro para openpyxl/csv (sin objetos raros)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return s[:_CELL_LIMIT]


def _norm_rows(header, rows):
    rows = rows or []
    if not isinstance(rows, list):
        raise ValueError("rows debe ser una lista de filas")
    rows = rows[:_MAX_ROWS]
    out = []
    for r in rows:
        if not isinstance(r, list):
            r = [r]
        out.append([_coerce(c) for c in r[:_MAX_COLS]])
    hdr = [_coerce(c) for c in (header or [])[:_MAX_COLS]] if header else None
    ncols = max([len(r) for r in out] + [len(hdr) if hdr else 0] + [0])
    return hdr, out, ncols


def _write_xlsx(filename, sheet_name, header, rows) -> dict:
    import openpyxl
    from openpyxl.styles import Font

    hdr, body, ncols = _norm_rows(header, rows)
    out_path = _safe_name(filename, "datos.xlsx", ".xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (str(sheet_name or "Hoja1").strip() or "Hoja1")[:31]
    cells = 0
    if hdr:
        ws.append(hdr)
        for c in ws[1]:
            c.font = Font(bold=True)
        cells += len(hdr)
    for r in body:
        ws.append(r)
        cells += len(r)
    wb.save(out_path)
    return {
        "ok": True, "filename": out_path.name, "path": str(out_path),
        "rows": len(body), "cols": ncols, "cells": cells,
        "note": "Archivo .xlsx REAL escrito en el workdir del run; queda descargable en Biblioteca.",
    }


def _write_csv(filename, header, rows) -> dict:
    hdr, body, ncols = _norm_rows(header, rows)
    out_path = _safe_name(filename, "datos.csv", ".csv")
    n = 0
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if hdr:
            w.writerow(hdr)
        for r in body:
            w.writerow(r)
            n += 1
    return {
        "ok": True, "filename": out_path.name, "path": str(out_path),
        "rows": n, "cols": ncols,
        "note": "Archivo .csv REAL escrito en el workdir del run; queda descargable en Biblioteca.",
    }


TOOLS = [
    {
        "name": "write_xlsx",
        "description": (
            "Escribe un archivo Excel (.xlsx) REAL y descargable a partir de datos "
            "estructurados. Usa esta tool cuando el usuario pida un Excel/planilla: "
            "pasa los datos como `header` (lista de títulos de columna) y `rows` "
            "(lista de filas, cada fila una lista de celdas). NO transcribas la tabla "
            "en markdown: esta tool produce el .xlsx de verdad. Los números deben "
            "venir de datos reales (compútalos con run_python si hace falta)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Nombre del .xlsx.", "default": "datos.xlsx"},
                "sheet_name": {"type": "string", "description": "Nombre de la hoja.", "default": "Hoja1"},
                "header": {"type": "array", "items": {"type": "string"}, "description": "Títulos de columna (opcional)."},
                "rows": {"type": "array", "items": {"type": "array"}, "description": "Filas de datos (lista de listas)."},
            },
            "required": ["rows"],
        },
    },
    {
        "name": "write_csv",
        "description": (
            "Escribe un archivo CSV REAL y descargable a partir de `header` + `rows` "
            "(igual que write_xlsx pero en CSV). Para datos tabulares simples."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Nombre del .csv.", "default": "datos.csv"},
                "header": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array"}},
            },
            "required": ["rows"],
        },
    },
]


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "datatools-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "write_xlsx":
                val = _write_xlsx(args.get("filename"), args.get("sheet_name"),
                                  args.get("header"), args.get("rows"))
            elif name == "write_csv":
                val = _write_csv(args.get("filename"), args.get("header"), args.get("rows"))
            else:
                raise ValueError(f"unknown tool {name}")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": False,
            }})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)}],
                "isError": True,
            }})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
