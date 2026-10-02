#!/usr/bin/env python3
"""maritime_osint_server.py — MCP stdio server: OSINT MARÍTIMO (datos REALES).

Cinturón de Rook (hilo 2B). Tools sobre APIs reales:
  • gfw_vessel_search   — Global Fishing Watch: identidad de buques (AIS). Bearer token.
  • gfw_vessel_events    — GFW: eventos ENCOUNTER / LOITERING / GAP ("buque a oscuras").
  • opensanctions_screen — OpenSanctions: screening de sanciones/PEP. header ApiKey.
  • gleif_lei            — GLEIF: LEI + propiedad declarada (keyless).

HONESTIDAD (anti-grift · H2/H15a): una respuesta VACÍA de la fuente = la fuente NO confirma
→ {ok:true, empty:true, ...} y el agente DEBE rehusar honesto (jamás inventar un nombre).
Un fallo del tercero (rate-limit / caída / 4xx-5xx) = {ok:false, external:true, error:...} →
atribución EXTERNA (no un bug de construcción interno). Todo número/nombre sale del lookup real.

GFW pasa por Cloudflare: SIN User-Agent de browser devuelve 403 error-1010 (bloqueo del edge,
NO auth) → mandamos un UA de browser. Tokens por byok_ref: GLOBALFISHINGWATCH_API_KEY,
OPENSANCTIONS_API_KEY (inyectados al child_env por el broker; nunca hardcodeados).

Spawned vía `uv run` (stdlib pura: urllib). Patrón gemelo de backtest_server.py.
"""
import os
import sys
import json
import urllib.parse
import urllib.request
import urllib.error

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_GFW_BASE = "https://gateway.api.globalfishingwatch.org"
_OS_BASE = "https://api.opensanctions.org"
_GLEIF_BASE = "https://api.gleif.org/api/v1"


def _http_get(url: str, headers: dict, timeout: int = 25) -> tuple:
    """(status, body_json_or_text, err). Nunca lanza. Clasifica el fallo como del TERCERO."""
    req = urllib.request.Request(url, headers={**headers, "User-Agent": _UA, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), None
            except json.JSONDecodeError:
                return r.status, raw, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw
        return e.code, body, "http_%s" % e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, None, "network: %s" % (str(e)[:150])


def _external_fail(status, err, detail=""):
    """Fallo del TERCERO (rate-limit / caída / 4xx-5xx) → atribución EXTERNA honesta."""
    return {"ok": False, "external": True, "status": status,
            "error": "la fuente externa no respondió con datos (%s)" % (err or status),
            "detail": (str(detail)[:200] if detail else "")}


# ── GFW ────────────────────────────────────────────────────────────────────────
def _run_gfw_vessel_search(args: dict) -> dict:
    q = (args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "query es requerido"}
    tok = (os.environ.get("GLOBALFISHINGWATCH_API_KEY") or "").strip()
    if not tok:
        return {"ok": False, "error": "falta el token de Global Fishing Watch (BYOK)"}
    params = {"query": q, "datasets[0]": "public-global-vessel-identity:latest",
              "limit": int(args.get("limit", 5) or 5)}
    url = _GFW_BASE + "/v3/vessels/search?" + urllib.parse.urlencode(params)
    status, body, err = _http_get(url, {"Authorization": "Bearer %s" % tok})
    if status != 200 or not isinstance(body, dict):
        return _external_fail(status, err, body)
    entries = body.get("entries") or []
    if not entries:
        # VACÍO = la fuente NO confirma → el agente debe rehusar honesto (no inventar).
        return {"ok": True, "empty": True, "query": q, "total": 0,
                "note": "GFW no devolvió buques para esa búsqueda — la fuente no confirma. No inventes una identidad."}
    out = []
    for e in entries[:5]:
        ri = (e.get("registryInfo") or [{}])
        ri0 = ri[0] if ri else {}
        out.append({"dataset": e.get("dataset"),
                    "name": ri0.get("shipname") or e.get("shipname"),
                    "imo": ri0.get("imo"), "mmsi": ri0.get("ssvid") or ri0.get("mmsi"),
                    "flag": ri0.get("flag"), "callsign": ri0.get("callsign")})
    return {"ok": True, "empty": False, "query": q, "total": body.get("total"),
            "vessels": out, "note": "Identidad AIS real de Global Fishing Watch."}


def _run_gfw_vessel_events(args: dict) -> dict:
    vessel_id = (args.get("vessel_id") or "").strip()
    event_type = (args.get("event_type") or "gap").strip().lower()  # gap|encounter|loitering
    if not vessel_id:
        return {"ok": False, "error": "vessel_id es requerido (id de GFW)"}
    tok = (os.environ.get("GLOBALFISHINGWATCH_API_KEY") or "").strip()
    if not tok:
        return {"ok": False, "error": "falta el token de Global Fishing Watch (BYOK)"}
    ds = {"gap": "public-global-gaps-events:latest", "encounter": "public-global-encounters-events:latest",
          "loitering": "public-global-loitering-events:latest"}.get(event_type, "public-global-gaps-events:latest")
    params = {"vessels[0]": vessel_id, "datasets[0]": ds, "limit": int(args.get("limit", 5) or 5)}
    url = _GFW_BASE + "/v3/events?" + urllib.parse.urlencode(params)
    status, body, err = _http_get(url, {"Authorization": "Bearer %s" % tok})
    if status != 200 or not isinstance(body, dict):
        return _external_fail(status, err, body)
    entries = body.get("entries") or []
    if not entries:
        return {"ok": True, "empty": True, "event_type": event_type, "total": 0,
                "note": "GFW no reporta eventos %s para ese buque — la fuente no confirma." % event_type}
    return {"ok": True, "empty": False, "event_type": event_type, "total": body.get("total"),
            "events": [{"start": e.get("start"), "end": e.get("end"), "type": e.get("type"),
                        "position": e.get("position")} for e in entries[:5]],
            "note": "Eventos AIS reales de Global Fishing Watch."}


# ── OpenSanctions ────────────────────────────────────────────────────────────────
def _run_opensanctions_screen(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name es requerido"}
    tok = (os.environ.get("OPENSANCTIONS_API_KEY") or "").strip()
    if not tok:
        return {"ok": False, "error": "falta el token de OpenSanctions (BYOK)"}
    params = {"q": name, "limit": int(args.get("limit", 5) or 5)}
    url = _OS_BASE + "/search/default?" + urllib.parse.urlencode(params)
    status, body, err = _http_get(url, {"Authorization": "ApiKey %s" % tok})
    if status != 200 or not isinstance(body, dict):
        return _external_fail(status, err, body)
    results = body.get("results") or []
    if not results:
        return {"ok": True, "empty": True, "name": name, "hits": 0,
                "note": "OpenSanctions no devolvió coincidencias — SIN HIT (no es evidencia de culpa ni de inocencia)."}
    hits = []
    for r in results[:5]:
        props = r.get("properties") or {}
        hits.append({"caption": r.get("caption"), "schema": r.get("schema"),
                     "datasets": r.get("datasets"), "topics": props.get("topics"),
                     "score": r.get("score")})
    return {"ok": True, "empty": False, "name": name, "hits": len(results),
            "results": hits, "note": "Screening real de OpenSanctions (sanciones/PEP)."}


# ── PAGO de informe premium (money-touch · el gate lo RETIENE antes de ejecutar) ──
def _run_pay_premium_report(args: dict) -> dict:
    """Compra un informe premium de un registro societario (de PAGO). Es money-touch:
    el enforcer de Security la clasifica y el gate la RETIENE (HELD, needs_ok) ANTES de
    ejecutarla — este cuerpo NO corre sin el OK explícito del humano por approve-by-HTTP.
    (Aun si corriera, es un stub: no hay cobro real; el punto es que el gate la sostiene.)"""
    provider = (args.get("provider") or "").strip()
    amount = args.get("amount_usd")
    return {"ok": True, "paid": True, "provider": provider, "amount_usd": amount,
            "note": "STUB — no debería ejecutarse sin OK (money-gate)."}


# ── GLEIF (keyless) ──────────────────────────────────────────────────────────────
def _run_gleif_lei(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name es requerido"}
    params = {"filter[entity.legalName]": name, "page[size]": int(args.get("limit", 5) or 5)}
    url = _GLEIF_BASE + "/lei-records?" + urllib.parse.urlencode(params)
    status, body, err = _http_get(url, {})
    if status != 200 or not isinstance(body, dict):
        return _external_fail(status, err, body)
    data = body.get("data") or []
    if not data:
        return {"ok": True, "empty": True, "name": name, "total": 0,
                "note": "GLEIF no tiene un LEI para esa entidad — la fuente no confirma."}
    out = []
    for d in data[:5]:
        attr = (d.get("attributes") or {})
        ent = attr.get("entity") or {}
        out.append({"lei": attr.get("lei"), "legalName": (ent.get("legalName") or {}).get("name"),
                    "jurisdiction": ent.get("jurisdiction"), "status": ent.get("status"),
                    "country": ((ent.get("legalAddress") or {}).get("country"))})
    return {"ok": True, "empty": False, "name": name, "total": len(data),
            "records": out, "note": "Registros LEI reales de GLEIF (propiedad declarada)."}


TOOLS = [
    {"name": "gfw_vessel_search",
     "description": "Busca la identidad de un buque en Global Fishing Watch (AIS real): nombre, IMO, MMSI, bandera. Si GFW no devuelve resultados, lo dice honesto (empty) — NO inventes una identidad.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Nombre / IMO / MMSI del buque."},
         "limit": {"type": "number"}}, "required": ["query"]}},
    {"name": "gfw_vessel_events",
     "description": "Eventos AIS de un buque en GFW: gap ('a oscuras'), encounter, loitering. Vacío = la fuente no confirma (honesto).",
     "inputSchema": {"type": "object", "properties": {
         "vessel_id": {"type": "string", "description": "id de GFW del buque."},
         "event_type": {"type": "string", "description": "gap | encounter | loitering."},
         "limit": {"type": "number"}}, "required": ["vessel_id"]}},
    {"name": "opensanctions_screen",
     "description": "Screening de sanciones/PEP en OpenSanctions. Sin coincidencias = SIN HIT (honesto, no es prueba). Con hit: dataset + topics + score.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Nombre de persona/empresa a screenear."},
         "limit": {"type": "number"}}, "required": ["name"]}},
    {"name": "gleif_lei",
     "description": "Busca el LEI y la propiedad declarada de una entidad en GLEIF (keyless). Vacío = sin LEI (honesto).",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Razón social de la entidad."},
         "limit": {"type": "number"}}, "required": ["name"]}},
    {"name": "pay_for_premium_report",
     "description": "Compra (DE PAGO) el informe premium completo de propiedad de un registro societario. Toca dinero: requiere el OK explícito del humano (queda RETENIDO hasta la aprobación).",
     "inputSchema": {"type": "object", "properties": {
         "provider": {"type": "string", "description": "Registro/proveedor del informe premium."},
         "amount_usd": {"type": "number", "description": "Monto a pagar en USD."}},
      "required": ["provider"]}},
]

_DISPATCH = {
    "gfw_vessel_search": _run_gfw_vessel_search,
    "gfw_vessel_events": _run_gfw_vessel_events,
    "opensanctions_screen": _run_opensanctions_screen,
    "gleif_lei": _run_gleif_lei,
    "pay_for_premium_report": _run_pay_premium_report,
}


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
            "serverInfo": {"name": "maritime-osint-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            fn = _DISPATCH.get(name)
            if fn is None:
                raise ValueError("unknown tool %s" % name)
            val = fn(args)
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
