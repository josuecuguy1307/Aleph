#!/usr/bin/env python3
"""
finanzas_data_server.py — Belt de FINANZAS (stdio, JSON-RPC 2.0). $0, keyless.

Tres tools DETERMINISTAS para el agente de finanzas. El principio del nicho —
"número = fuente, nunca inventado" — se hace ESTRUCTURAL: los números NO viajan
por los argumentos del modelo. El modelo orquesta (qué serie, qué PDF, qué
archivo de salida); los números los traen las tools desde la fuente y quedan en
un store EN PROCESO. `build_workbook` escribe el .xlsx LEYENDO ese store, no lo
que el modelo "dice" que vale un dato. Así un modelo no puede inyectar una cifra:
lo más que puede hacer es pedir un handle que no existe (y la tool lo reporta).

  • worldbank_series(country, indicator, start_year, end_year)
        Jala una serie macro REAL de la API pública del Banco Mundial
        (api.worldbank.org, sin key). Cada observación queda con su procedencia
        (indicador, país, año, URL exacta, lastupdated del proveedor, recuperado).
        Devuelve un handle + muestra; la serie completa vive en el store.

  • bce_pdf_ingest(recipe, pdf)
        Corre el INGESTOR DETERMINISTA del repo (platform/ingestor/runner.py) sobre
        un PDF del Banco Central del Ecuador. Cero modelo, cero red: re-deriva las
        celdas estructuradas + procedencia por dato (página, fila, columna, sha256).
        Devuelve un handle + muestra; los datums viven en el store.

  • build_workbook(filename, handles)
        Escribe un .xlsx REAL (openpyxl) en PUPPET_WORKDIR a partir de los handles
        del store. UNA hoja por fuente; CADA fila de dato lleva su valor + su
        columna de procedencia. Una hoja "PROCEDENCIA" resume las fuentes. Devuelve
        la ruta absoluta + un conteo de celdas de dato, TODAS trazadas a fuente.

Sólo stdlib + openpyxl (ya en el entorno). Read/compute/write-de-su-propio-output:
ninguna tool toca plata ni manda afuera, así que el enforcer de gates las
clasifica como auto-ejecuta. El archivo que produce es la OBRA del run.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── ubicación en el repo (para defaults del ingestor) ───────────────────────────
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]                      # …/puppet-ai
_INGESTOR_DIR = _REPO_ROOT / "platform" / "ingestor"
_DEFAULT_BCE_RECIPE = _INGESTOR_DIR / "recipes" / "bce-estmacro-comercializacion-derivados.json"
_DEFAULT_BCE_PDF = _INGESTOR_DIR / "fixtures" / "bce_estmacro012024.pdf"

_WB_BASE = "https://api.worldbank.org/v2"
_UA = "puppet-ai-toolbelt/0.1 (finanzas; mailto:contact@example.invalid)"
_TIMEOUT = 25

# ── STORE en proceso: handle -> {kind, source, columns, rows} ───────────────────
# rows: lista de {"cells": {col: value}, "provenance": <str>, "ok": bool, "raw": <str|None>}
_STORE: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── TOOL 1 — World Bank (serie macro real, keyless) ─────────────────────────────

def _worldbank_series(country: str, indicator: str,
                      start_year: int, end_year: int) -> dict:
    country = (country or "EC").strip().upper()
    indicator = (indicator or "NY.GDP.MKTP.CD").strip().upper()
    sy = int(start_year or 2015)
    ey = int(end_year or 2023)
    if ey < sy:
        sy, ey = ey, sy
    qs = urllib.parse.urlencode({"format": "json", "date": f"{sy}:{ey}", "per_page": 1000})
    url = f"{_WB_BASE}/country/{urllib.parse.quote(country)}/indicator/{urllib.parse.quote(indicator)}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    retrieved = _now_iso()
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    # payload = [meta, observations]
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        msg = ""
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            msg = payload[0].get("message", [{}])
        return {"ok": False, "error": f"World Bank no devolvió datos para {indicator}/{country}",
                "detail": str(msg)[:300], "url": url}

    meta, obs = payload[0], payload[1]
    lastupdated = meta.get("lastupdated")
    ind_name = obs[0]["indicator"]["value"] if obs else indicator
    ctry_name = obs[0]["country"]["value"] if obs else country

    rows = []
    for o in obs:
        val = o.get("value")
        if val is None:
            continue  # la API trae años sin observación; no inventamos
        cita = (f"World Bank Open Data — {ind_name} ({indicator}), {ctry_name}, "
                f"año {o.get('date')} = {val}. lastupdated={lastupdated}. "
                f"fuente: {url} (recuperado {retrieved})")
        rows.append({
            "cells": {"anio": int(o["date"]), "valor": val},
            "provenance": cita,
            "ok": True,
            "raw": None,
        })
    rows.sort(key=lambda r: r["cells"]["anio"])

    handle = f"wb:{indicator}:{country}"
    _STORE[handle] = {
        "kind": "worldbank",
        "source": {"provider": "World Bank Open Data API", "url": url,
                   "indicator_id": indicator, "indicator_name": ind_name,
                   "country_id": country, "country_name": ctry_name,
                   "lastupdated": lastupdated, "retrieved_at": retrieved},
        "columns": [("anio", "Año"), ("valor", f"{ind_name} ({indicator})")],
        "rows": rows,
    }

    # OBRA RICA linechart: la serie REAL como artifact estructurado en el workdir del run →
    # _capture_rich_obra (executor) la surfacea como out["obra"] y La Sala la rinde con su
    # renderer de serie temporal. Fail-open: si no se puede escribir, la tool sigue sirviendo.
    if rows:
        try:
            workdir = Path(os.environ.get("PUPPET_WORKDIR", ".")).resolve()
            obra = {
                "type": "linechart",
                "title": f"{ind_name} — {ctry_name}",
                "labels": [str(r["cells"]["anio"]) for r in rows],
                "series": [{"name": ind_name, "data": [r["cells"]["valor"] for r in rows]}],
                "source": f"World Bank Open Data — {indicator}, {ctry_name} "
                          f"(lastupdated {lastupdated}, recuperado {retrieved})",
            }
            fname = f"worldbank-{indicator.replace('.', '_')}-{country}.linechart.json"
            (workdir / fname).write_text(json.dumps(obra, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return {
        "ok": True,
        "handle": handle,
        "indicator": indicator, "indicator_name": ind_name,
        "country": ctry_name, "n_obs": len(rows),
        "years": [r["cells"]["anio"] for r in rows],
        "sample": [{"anio": r["cells"]["anio"], "valor": r["cells"]["valor"]} for r in rows[:4]],
        "source_url": url, "lastupdated": lastupdated,
        "note": "Serie en el store. Pasa este handle a build_workbook; no transcribas los números.",
    }


# ── TOOL 2 — ingestor BCE (determinista, $0, sin red ni modelo) ─────────────────

def _bce_pdf_ingest(recipe: str | None, pdf: str | None) -> dict:
    recipe_path = Path(recipe).expanduser() if recipe else _DEFAULT_BCE_RECIPE
    pdf_path = Path(pdf).expanduser() if pdf else _DEFAULT_BCE_PDF
    if not recipe_path.is_absolute():
        recipe_path = _REPO_ROOT / recipe_path
    if not pdf_path.is_absolute():
        pdf_path = _REPO_ROOT / pdf_path
    if not recipe_path.exists():
        return {"ok": False, "error": f"recipe no existe: {recipe_path}"}
    if not pdf_path.exists():
        return {"ok": False, "error": f"pdf no existe: {pdf_path}"}

    # importar el runner determinista del repo (no es paquete; ajustamos sys.path)
    if str(_INGESTOR_DIR) not in sys.path:
        sys.path.insert(0, str(_INGESTOR_DIR))
    from runner import run_ingest_from_recipe_file  # type: ignore

    result = run_ingest_from_recipe_file(str(pdf_path), str(recipe_path))
    rd = result.to_dict()

    rows = []
    for d in rd["data"]:
        if d["value"] is None and d["ok"]:
            continue  # blancos legítimos: no son dato
        loc = d["provenance"]["locator"]
        rows.append({
            "cells": {
                "campo": d.get("field"),
                "indicador": loc.get("row_label"),
                "periodo": loc.get("col_label"),
                "valor": d["value"],
            },
            "provenance": d["citation"],
            "ok": d["ok"],
            "raw": d["provenance"].get("raw"),
            "error": d.get("error"),
        })

    handle = f"bce:{rd['recipe_id']}"
    _STORE[handle] = {
        "kind": "ingestor",
        "source": {"provider": "Banco Central del Ecuador (ingestor determinista)",
                   "file": rd["source"]["file"], "sha256": rd["source"]["sha256"],
                   "url": rd["source"].get("url"), "recipe_id": rd["recipe_id"],
                   "refreshed_at": rd["refreshed_at"]},
        "columns": [("campo", "Campo"), ("indicador", "Indicador (fila)"),
                    ("periodo", "Período (col)"), ("valor", "Valor")],
        "rows": rows,
    }
    return {
        "ok": True,
        "handle": handle,
        "recipe_id": rd["recipe_id"],
        "source_file": rd["source"]["file"],
        "sha256": rd["source"]["sha256"][:16] + "…",
        "n_datums": len(rows), "n_ok": rd["n_ok"], "n_error": rd["n_error"],
        "sample": [{"indicador": r["cells"]["indicador"], "periodo": r["cells"]["periodo"],
                    "valor": r["cells"]["valor"], "raw": r["raw"]} for r in rows[:4]],
        "note": "Datums en el store. Pasa este handle a build_workbook; no transcribas los números.",
    }


# ── TOOL (BYOK) — Alpha Vantage: PRUEBA el invariante construir≠inyectar ─────────
# Lee la key de ALPHA_VANTAGE_API_KEY del ENTORNO (que el assembler puebla desde la
# credencial BYOK del usuario vía byok_resolver). El flag `key_present` en la respuesta
# es la prueba de COMPORTAMIENTO: si la key llegó al server, es true; si se "construyó
# pero no se inyectó" (el bug que ya mordió), es false y la tool lo dice sin maquillar.

def _alphavantage_quote(symbol: str) -> dict:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    # `${...}` = el literal SIN EXPANDIR. Desde que la receta DECLARA
    # `ALPHA_VANTAGE_API_KEY: ${ALPHA_VANTAGE_API_KEY}`, un usuario que no conectó Alpha
    # Vantage recibe ese texto tal cual (`_expand_str` deja lo desconocido literal). Sin
    # este guard, `key_present` daría TRUE con una llave que no existe — y `key_present` es
    # justamente la prueba de comportamiento del invariante construir≠inyectar, o sea que
    # mentiría el único testigo que esta tool existe para dar. Mismo guard que gmail/drive.
    if key.startswith("${"):
        key = ""
    key_present = bool(key)
    symbol = (symbol or "IBM").strip().upper()
    if not key_present:
        return {"ok": False, "key_present": False, "symbol": symbol,
                "error": "no llegó ninguna ALPHA_VANTAGE_API_KEY al server (la credencial "
                         "se construyó pero NO se inyectó, o el usuario no conectó Alpha Vantage)."}
    qs = urllib.parse.urlencode({"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": key})
    url = f"https://www.alphavantage.co/query?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    retrieved = _now_iso()
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if "Error Message" in body:
        return {"ok": False, "key_present": True, "symbol": symbol,
                "error": "Alpha Vantage rechazó la consulta: " + str(body.get("Error Message"))[:160]}
    q = body.get("Global Quote") or {}
    price = q.get("05. price")
    if price is None:
        return {"ok": False, "key_present": True, "symbol": symbol,
                "error": "Alpha Vantage no devolvió precio (posible rate-limit).",
                "detail": str(body)[:200]}
    # url SIN la key (la procedencia no filtra credenciales)
    safe_url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}"
    cita = (f"Alpha Vantage GLOBAL_QUOTE {symbol} = {price} USD "
            f"(trading day {q.get('07. latest trading day')}). fuente: {safe_url} "
            f"(recuperado {retrieved}; key del usuario inyectada vía BYOK)")
    return {"ok": True, "key_present": True, "symbol": symbol,
            "price": price, "latest_trading_day": q.get("07. latest trading day"),
            "provenance": cita,
            "note": "Precio REAL de Alpha Vantage con la key del usuario inyectada en el server (invariante build≠inject verificado)."}


# ── TOOL 3 — escribir el .xlsx desde el store (números = fuente) ─────────────────

def _build_workbook(filename: str, handles: list) -> dict:
    import openpyxl
    from openpyxl.styles import Font

    if not handles:
        return {"ok": False, "error": "no pasaste handles; primero trae datos (worldbank_series / bce_pdf_ingest)"}
    missing = [h for h in handles if h not in _STORE]
    if missing:
        return {"ok": False, "error": f"handles no encontrados en el store: {missing}. "
                f"Usa los handles que devolvieron las tools de datos."}

    workdir = Path(os.environ.get("PUPPET_WORKDIR", ".")).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    fn = (filename or "finanzas.xlsx").strip()
    if not fn.lower().endswith(".xlsx"):
        fn += ".xlsx"
    out_path = workdir / Path(fn).name   # nunca fuera del workdir

    wb = openpyxl.Workbook()
    cover = wb.active
    cover.title = "PROCEDENCIA"
    cover.append(["Puppet AI — Agente de Finanzas — Obra con procedencia por dato"])
    cover["A1"].font = Font(bold=True, size=13)
    cover.append([])
    cover.append(["Generado (UTC)", _now_iso()])
    cover.append(["Regla del nicho", "número = fuente, nunca inventado. Cada celda numérica traza a su fuente."])
    cover.append([])
    cover.append(["Hoja", "Fuente", "Filas de dato", "URL / archivo"])
    for c in cover[6]:
        c.font = Font(bold=True)

    total_cells = 0
    sheets_info = []
    used_titles = {"PROCEDENCIA"}
    for h in handles:
        entry = _STORE[h]
        src = entry["source"]
        kind = entry["kind"]
        # título de hoja seguro y único
        base_title = "World Bank" if kind == "worldbank" else "BCE"
        title = base_title
        i = 2
        while title in used_titles:
            title = f"{base_title} {i}"; i += 1
        used_titles.add(title)
        ws = wb.create_sheet(title=title)

        col_keys = [k for k, _ in entry["columns"]]
        headers = [label for _, label in entry["columns"]] + ["Procedencia (fuente exacta)"]
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True)

        n_data = 0
        for r in entry["rows"]:
            row_vals = [r["cells"].get(k) for k in col_keys] + [r["provenance"]]
            ws.append(row_vals)
            # contar celdas numéricas de dato (la columna 'valor') que están trazadas
            v = r["cells"].get("valor")
            if isinstance(v, (int, float)):
                n_data += 1
        total_cells += n_data

        # anchos legibles
        for col_cells in ws.columns:
            width = min(60, max(12, max((len(str(c.value)) for c in col_cells if c.value is not None), default=12)))
            ws.column_dimensions[col_cells[0].column_letter].width = width

        url_or_file = src.get("url") or src.get("file") or ""
        cover.append([title, src.get("provider", kind), n_data, url_or_file])
        sheets_info.append({"sheet": title, "kind": kind, "data_cells": n_data,
                            "provider": src.get("provider"), "source": url_or_file})

    wb.save(out_path)
    return {
        "ok": True,
        "path": str(out_path),
        "filename": out_path.name,
        "sheets": sheets_info,
        "total_data_cells": total_cells,
        "all_traced": True,
        "note": f"Obra escrita: {out_path}. {total_cells} celdas de dato, cada una con su procedencia.",
    }


# ── MCP plumbing (stdio JSON-RPC, idéntico patrón a crossref_server.py) ──────────

TOOLS = [
    {
        "name": "worldbank_series",
        "description": ("Jala una serie macroeconómica REAL del Banco Mundial (API pública, "
                        "sin key). Ej: PIB de Ecuador. Cada observación queda con su procedencia. "
                        "Devuelve un HANDLE; los números viven en el store (no los transcribas). "
                        "indicator por defecto NY.GDP.MKTP.CD (PIB US$ corrientes), country 'EC'."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Código ISO-2 del país (ej. 'EC' Ecuador).", "default": "EC"},
                "indicator": {"type": "string", "description": "Código de indicador WB (ej. 'NY.GDP.MKTP.CD').", "default": "NY.GDP.MKTP.CD"},
                "start_year": {"type": "integer", "description": "Año inicial.", "default": 2015},
                "end_year": {"type": "integer", "description": "Año final.", "default": 2023},
            },
            "required": [],
        },
    },
    {
        "name": "bce_pdf_ingest",
        "description": ("Corre el ingestor DETERMINISTA del repo sobre un PDF del Banco Central del "
                        "Ecuador y devuelve sus celdas estructuradas con procedencia por dato (página, "
                        "fila, columna, sha256). Cero modelo, cero red. Sin argumentos usa el PDF y la "
                        "receta del BCE ya incluidos. Devuelve un HANDLE; los datums viven en el store."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipe": {"type": "string", "description": "Ruta a la receta de parseo (opcional; default BCE)."},
                "pdf": {"type": "string", "description": "Ruta al PDF (opcional; default BCE EstMacro 01-2024)."},
            },
            "required": [],
        },
    },
    {
        "name": "alphavantage_quote",
        "description": ("Consulta el precio actual de una acción en Alpha Vantage usando la "
                        "API key que el USUARIO conectó (BYOK, inyectada al server). Devuelve el "
                        "precio + procedencia. Si la key no llegó al server, lo reporta honesto. "
                        "Símbolo por defecto 'IBM'."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker (ej. 'IBM', 'AAPL').", "default": "IBM"},
            },
            "required": [],
        },
    },
    {
        "name": "build_workbook",
        "description": ("Escribe un archivo .xlsx REAL con las series ya jaladas. Pásale la lista de "
                        "HANDLES (los que devolvieron worldbank_series y bce_pdf_ingest) y un nombre de "
                        "archivo. Una hoja por fuente, cada fila con su columna de procedencia. Los "
                        "números los toma del store (tú NO los escribes). Devuelve la ruta del archivo."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Nombre del .xlsx de salida.", "default": "finanzas.xlsx"},
                "handles": {"type": "array", "items": {"type": "string"},
                            "description": "Handles devueltos por las tools de datos."},
            },
            "required": ["handles"],
        },
    },
]


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "finanzas-data-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "worldbank_series":
                val = _worldbank_series(args.get("country", "EC"), args.get("indicator", "NY.GDP.MKTP.CD"),
                                        args.get("start_year", 2015), args.get("end_year", 2023))
            elif name == "bce_pdf_ingest":
                val = _bce_pdf_ingest(args.get("recipe"), args.get("pdf"))
            elif name == "alphavantage_quote":
                val = _alphavantage_quote(args.get("symbol", "IBM"))
            elif name == "build_workbook":
                val = _build_workbook(args.get("filename", "finanzas.xlsx"), args.get("handles", []))
            else:
                raise ValueError(f"unknown tool {name}")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": not val.get("ok", True),
            }})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {type(exc).__name__}: {exc}"}],
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
