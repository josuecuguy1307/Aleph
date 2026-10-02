#!/usr/bin/env python3
"""
precio_server.py — MCP stdio server del belt de ELECTRONICA: PRECIO + STOCK REAL.

Le da al agente de electrónica lo que el belt de esquemáticos no tiene: el precio $
y el stock REAL de un componente, en vivo, por número de parte o descripción.

Tools:
  quote_component(query)  -> cotiza UN componente: precio unitario (USD), stock,
       distribuidor, código LCSC, fabricante y los tramos de precio por cantidad.
  quote_bom(components)    -> cotiza un BOM entero (lista de {part, qty}) -> tabla
       cotizada con subtotales + total, y ESCRIBE `bom.planilla.json` en
       ${PUPPET_WORKDIR} -> La Sala lo rinde con el renderer `planilla` (BOM cotizado).

Fuente: catálogo SMT de JLCPCB (parts del ensamblaje LCSC) — API pública, SIN llave.
Patrón de salida-a-La-Sala idéntico al fem_server.py (von Mises -> fieldplot): el
texto-resumen lo lee el cerebro; el artifact estructurado lo rinde el front.

Cero fabricación: todo precio y todo stock sale de la API en vivo, nunca de memoria.
Si la API no responde o no hay match, el server devuelve un error HONESTO (no un
precio inventado). El valor es el precio REAL; un precio fabricado sería el grift que
evitamos.
"""
import json
import os
import sys
import urllib.error
import urllib.request

# [i18n-bi] bilingüe server-side: el server hornea sus strings al idioma del run
# (PUPPET_LANG, default es; no-op hasta que el runtime lo setee). Mismo patrón que
# fem_server.py / quant_chart.py. Lo que RENDERIZA La Sala (descripciones de tools,
# columnas de la planilla, notas, errores honestos) sale en el idioma del usuario.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
PRECIO_I18N = {
    "es": {
        "tool.quote_component.desc": (
            "Cotiza UN componente electrónico REAL por número de parte (MPN, ej. "
            "'STM32F103C8T6', 'AMS1117-3.3') o descripción (ej. '100nF 0603 X7R'). "
            "Devuelve el precio unitario en USD, el stock disponible, el distribuidor, "
            "el código LCSC, el fabricante y los tramos de precio por cantidad. Úsala "
            "cuando el usuario pida el precio, el costo o la disponibilidad/stock de una "
            "pieza. Todo número sale del catálogo en vivo, nunca de memoria."
        ),
        "tool.quote_component.param.query": "Número de parte (MPN) o descripción del componente a cotizar.",
        "tool.quote_bom.desc": (
            "Cotiza un BOM ENTERO (lista de materiales) y arma una planilla cotizada. "
            "Recibe una lista de componentes; cada uno es un objeto {part, qty} (part = "
            "MPN o descripción; qty = cantidad, default 1) o simplemente el string del "
            "part. Cotiza cada línea contra el catálogo real (precio según el tramo de "
            "cantidad + stock + LCSC + fabricante), calcula subtotales y el total, y "
            "produce el artifact `planilla` (BOM cotizado) que La Sala rinde como tabla. "
            "Úsala cuando el usuario pida cotizar una lista de componentes, un BOM o el "
            "costo de un circuito. Todo precio y stock sale de la API, nunca inventado."
        ),
        "tool.quote_bom.param.components": "Lista de componentes a cotizar. Cada item: {part, qty} o un string MPN/descripción.",
        "tool.quote_bom.param.part": "MPN o descripción del componente.",
        "tool.quote_bom.param.qty": "Cantidad (default 1).",
        "tool.quote_bom.param.title": "Título opcional de la planilla (ej. 'BOM regulador 3.3V').",
        "err.missing_query": "falta 'query' (MPN o descripción del componente)",
        "err.catalog_no_response": "catálogo no respondió (%s)",
        "err.catalog_unparseable": "respuesta del catálogo no parseable (%s)",
        "err.no_results": "sin resultados en el catálogo para '%s'",
        "err.missing_components": "falta 'components' (lista de {part, qty} o de strings MPN)",
        "err.no_match": "sin match en el catálogo",
        "note.quote_component": "Precio y stock REALES del catálogo JLCPCB/LCSC en vivo (no de memoria).",
        "col.num": "#", "col.component": "Componente", "col.mpn": "MPN",
        "col.manufacturer": "Fabricante", "col.lcsc": "LCSC", "col.stock": "Stock",
        "col.qty": "Cant.", "col.unit_price": "P. Unit. (USD)",
        "col.subtotal": "Subtotal (USD)", "col.distributor": "Distribuidor",
        "row.no_match": "(sin match)", "row.total": "TOTAL",
        "artifact.source": "Catálogo JLCPCB/LCSC en vivo (precio + stock reales)",
        "bom.title_default": "BOM cotizado",
        "note.bom": "BOM cotizado contra el catálogo JLCPCB/LCSC en vivo (precio + stock reales).",
        "note.bom.written": " · planilla escrita (%s)",
        "note.bom.write_failed": " · (no pude escribir la planilla: %s)",
    },
    "en": {
        "tool.quote_component.desc": (
            "Quote ONE REAL electronic component by part number (MPN, e.g. "
            "'STM32F103C8T6', 'AMS1117-3.3') or description (e.g. '100nF 0603 X7R'). "
            "Returns the unit price in USD, available stock, the distributor, the LCSC "
            "code, the manufacturer and the per-quantity price breaks. Use it when the "
            "user asks for the price, cost or availability/stock of a part. Every number "
            "comes from the live catalog, never from memory."
        ),
        "tool.quote_component.param.query": "Part number (MPN) or description of the component to quote.",
        "tool.quote_bom.desc": (
            "Quote an ENTIRE BOM (bill of materials) and build a quoted spreadsheet. "
            "Takes a list of components; each is an object {part, qty} (part = MPN or "
            "description; qty = quantity, default 1) or just the part string. Quotes each "
            "line against the real catalog (price by quantity break + stock + LCSC + "
            "manufacturer), computes subtotals and the total, and produces the `planilla` "
            "artifact (quoted BOM) that The Room renders as a table. Use it when the user "
            "asks to quote a list of components, a BOM or the cost of a circuit. Every "
            "price and stock comes from the API, never invented."
        ),
        "tool.quote_bom.param.components": "List of components to quote. Each item: {part, qty} or an MPN/description string.",
        "tool.quote_bom.param.part": "MPN or description of the component.",
        "tool.quote_bom.param.qty": "Quantity (default 1).",
        "tool.quote_bom.param.title": "Optional spreadsheet title (e.g. 'BOM 3.3V regulator').",
        "err.missing_query": "missing 'query' (MPN or component description)",
        "err.catalog_no_response": "catalog did not respond (%s)",
        "err.catalog_unparseable": "catalog response not parseable (%s)",
        "err.no_results": "no results in the catalog for '%s'",
        "err.missing_components": "missing 'components' (list of {part, qty} or MPN strings)",
        "err.no_match": "no match in the catalog",
        "note.quote_component": "REAL price and stock from the live JLCPCB/LCSC catalog (not from memory).",
        "col.num": "#", "col.component": "Component", "col.mpn": "MPN",
        "col.manufacturer": "Manufacturer", "col.lcsc": "LCSC", "col.stock": "Stock",
        "col.qty": "Qty", "col.unit_price": "Unit price (USD)",
        "col.subtotal": "Subtotal (USD)", "col.distributor": "Distributor",
        "row.no_match": "(no match)", "row.total": "TOTAL",
        "artifact.source": "Live JLCPCB/LCSC catalog (real price + stock)",
        "bom.title_default": "Quoted BOM",
        "note.bom": "BOM quoted against the live JLCPCB/LCSC catalog (real price + stock).",
        "note.bom.written": " · spreadsheet written (%s)",
        "note.bom.write_failed": " · (could not write the spreadsheet: %s)",
    },
}


def _t(key):
    return PRECIO_I18N.get(PUPPET_LANG, {}).get(key) or PRECIO_I18N["es"].get(key) or key


# Catálogo SMT de JLCPCB (mismo que alimenta su ensamblaje LCSC). Keyless: no requiere
# cuenta ni API key. Se puede pisar por env para apuntar a un mirror/proxy en CI.
_JLC_ENDPOINT = os.environ.get(
    "PRECIO_JLC_ENDPOINT",
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList",
)
_TIMEOUT = int(os.environ.get("PRECIO_TIMEOUT", "25"))
# UA de navegador: el edge de JLCPCB/LCSC rechaza UA de urllib por defecto (igual que
# Cloudflare con otros catálogos). No es evasión: es el header que el catálogo público
# espera de un cliente legítimo.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/605.1.15"
_DISTRIBUTOR = "JLCPCB/LCSC"

TOOLS = [
    {
        "name": "quote_component",
        "description": _t("tool.quote_component.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": _t("tool.quote_component.param.query"),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "quote_bom",
        "description": _t("tool.quote_bom.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": _t("tool.quote_bom.param.components"),
                    "items": {
                        "type": "object",
                        "properties": {
                            "part": {"type": "string", "description": _t("tool.quote_bom.param.part")},
                            "qty": {"type": "number", "description": _t("tool.quote_bom.param.qty")},
                        },
                    },
                },
                "title": {
                    "type": "string",
                    "description": _t("tool.quote_bom.param.title"),
                },
            },
            "required": ["components"],
        },
    },
]


# ── ACCESO AL CATÁLOGO (en vivo, keyless) ────────────────────────────────────

def _search(keyword: str, page_size: int = 8) -> list:
    """Busca en el catálogo SMT de JLCPCB. Devuelve la lista cruda de componentes.
    Lanza urllib.error / ValueError si la API no responde o el shape cambia."""
    body = json.dumps({"keyword": keyword, "currentPage": 1, "pageSize": page_size}).encode("utf-8")
    req = urllib.request.Request(
        _JLC_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
            "Accept": "application/json",
            "Origin": "https://jlcpcb.com",
            "Referer": "https://jlcpcb.com/parts",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    info = (payload or {}).get("data", {}).get("componentPageInfo", {}) or {}
    return info.get("list", []) or []


def _pick_best(rows: list, keyword: str) -> dict | None:
    """Elige el mejor match. Para un MPN exacto, lo prefiere SIEMPRE; si la consulta es
    descriptiva, prefiere parte 'preferida' con stock; si nada califica, el primero."""
    if not rows:
        return None
    kw = keyword.strip().lower().replace(" ", "")
    for r in rows:  # match exacto de MPN gana
        mpn = str(r.get("componentModelEn") or "").strip().lower().replace(" ", "")
        if mpn and mpn == kw:
            return r
    in_stock_pref = [r for r in rows if r.get("preferredComponentFlag") and (r.get("stockCount") or 0) > 0]
    if in_stock_pref:
        return max(in_stock_pref, key=lambda r: r.get("stockCount") or 0)
    in_stock = [r for r in rows if (r.get("stockCount") or 0) > 0]
    if in_stock:
        return in_stock[0]
    return rows[0]


def _price_for_qty(breaks: list, qty: float) -> tuple:
    """Devuelve (precio_unitario, tramo) para la cantidad pedida usando los tramos del
    catálogo. endNumber == -1 = sin tope superior. Si no hay tramo que la contenga, usa
    el primer tramo (q1)."""
    chosen = None
    for b in breaks:
        start = b.get("startNumber", 1)
        end = b.get("endNumber", -1)
        if qty >= start and (end == -1 or qty <= end):
            chosen = b
            break
    if chosen is None and breaks:
        chosen = breaks[0]
    if not chosen:
        return None, None
    return float(chosen.get("productPrice")), chosen


def _lcsc_url(c: dict) -> str:
    suffix = c.get("urlSuffix")
    if suffix:
        return "https://www.lcsc.com/product-detail/" + str(suffix) + ".html"
    return c.get("lcscGoodsUrl") or ""


def _normalize(c: dict, query: str, qty: float = 1.0) -> dict:
    """Mapea el componente crudo del catálogo al contrato que reporta el server."""
    breaks_raw = c.get("componentPrices") or []
    breaks = [
        {"qty_from": b.get("startNumber"), "qty_to": (None if b.get("endNumber") == -1 else b.get("endNumber")),
         "unit_usd": float(b.get("productPrice"))}
        for b in breaks_raw if b.get("productPrice") is not None
    ]
    unit, _tramo = _price_for_qty(breaks_raw, qty)
    return {
        "query": query,
        "mpn": c.get("componentModelEn"),
        "manufacturer": c.get("componentBrandEn"),
        "lcsc_code": c.get("componentCode"),
        "category": c.get("componentTypeEn"),
        "distributor": _DISTRIBUTOR,
        "currency": "USD",
        "unit_price_usd": unit,
        "stock": int(c.get("stockCount") or 0),
        "min_qty": c.get("minPurchaseNum") or 1,
        "price_breaks": breaks,
        "url": _lcsc_url(c),
    }


# ── TOOLS ────────────────────────────────────────────────────────────────────

def _quote_component(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": _t("err.missing_query")}
    try:
        rows = _search(query)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {"ok": False, "error": _t("err.catalog_no_response") % exc}
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": _t("err.catalog_unparseable") % exc}
    best = _pick_best(rows, query)
    if not best:
        return {"ok": False, "error": _t("err.no_results") % query}
    out = _normalize(best, query)
    out["ok"] = True
    out["note"] = _t("note.quote_component")
    return out


def _coerce_items(components) -> list:
    """Normaliza la lista del BOM a [{part, qty}]. Acepta strings o objetos."""
    items = []
    for it in components or []:
        if isinstance(it, str):
            items.append({"part": it.strip(), "qty": 1})
        elif isinstance(it, dict):
            part = (it.get("part") or it.get("mpn") or it.get("query") or it.get("name") or "").strip()
            if not part:
                continue
            try:
                qty = float(it.get("qty") or it.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1
            items.append({"part": part, "qty": qty if qty > 0 else 1})
    return items


def _fmt_money(v) -> str:
    return "—" if v is None else "%.4f" % float(v)


def _quote_bom(args: dict) -> dict:
    items = _coerce_items(args.get("components"))
    if not items:
        return {"ok": False, "error": _t("err.missing_components")}
    title = (args.get("title") or _t("bom.title_default")).strip()

    lines = []
    total = 0.0
    priced = 0
    for it in items:
        part, qty = it["part"], it["qty"]
        try:
            rows = _search(part)
            best = _pick_best(rows, part)
        except Exception as exc:  # una línea que falla NO tumba el BOM
            best, err = None, str(exc)
        else:
            err = None
        if not best:
            lines.append({"query": part, "qty": qty, "found": False,
                          "error": err or _t("err.no_match")})
            continue
        info = _normalize(best, part, qty)
        unit = info["unit_price_usd"]
        subtotal = (unit or 0.0) * qty
        if unit is not None:
            total += subtotal
            priced += 1
        info.update({"found": True, "qty": qty, "subtotal_usd": round(subtotal, 4)})
        lines.append(info)

    # ── artifact `planilla` (BOM cotizado) -> ${PUPPET_WORKDIR} -> La Sala lo rinde ──
    cols = [_t("col.num"), _t("col.component"), _t("col.mpn"), _t("col.manufacturer"),
            _t("col.lcsc"), _t("col.stock"), _t("col.qty"), _t("col.unit_price"),
            _t("col.subtotal"), _t("col.distributor")]
    rows_out = []
    for i, ln in enumerate(lines, 1):
        if ln.get("found"):
            rows_out.append([
                str(i), ln["query"], str(ln.get("mpn") or "—"), str(ln.get("manufacturer") or "—"),
                str(ln.get("lcsc_code") or "—"), str(ln.get("stock", 0)),
                str(int(ln["qty"]) if float(ln["qty"]).is_integer() else ln["qty"]),
                _fmt_money(ln.get("unit_price_usd")), _fmt_money(ln.get("subtotal_usd")), _DISTRIBUTOR,
            ])
        else:
            rows_out.append([str(i), ln["query"], _t("row.no_match"), "—", "—", "—",
                             str(int(ln["qty"]) if float(ln["qty"]).is_integer() else ln["qty"]),
                             "—", "—", "—"])
    rows_out.append(["", _t("row.total"), "", "", "", "", "", "", "%.4f" % round(total, 4), "USD"])

    artifact = {
        "type": "planilla",
        "title": title,
        "source": _t("artifact.source"),
        "cols": cols,
        "rows": rows_out,
    }
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    artifact_note = ""
    try:
        path = os.path.join(workdir, "bom.planilla.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False)
        artifact_note = _t("note.bom.written") % os.path.basename(path)
    except Exception as exc:
        artifact_note = _t("note.bom.write_failed") % exc

    return {
        "ok": True,
        "title": title,
        "currency": "USD",
        "distributor": _DISTRIBUTOR,
        "lines": lines,
        "line_count": len(lines),
        "priced_lines": priced,
        "total_usd": round(total, 4),
        "note": _t("note.bom") + artifact_note,
    }


# ── PROTOCOLO MCP (stdio JSON-RPC 2.0) — idéntico a fem_server.py ─────────────

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
            "serverInfo": {"name": "precio-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "quote_component":
                val = _quote_component(args)
            elif name == "quote_bom":
                val = _quote_bom(args)
            else:
                raise ValueError("unknown tool %s" % name)
            is_err = not val.get("ok", True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": is_err}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": "Method not found: %s" % method}})


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
