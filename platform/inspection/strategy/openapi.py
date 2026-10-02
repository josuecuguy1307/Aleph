"""
strategy/openapi.py — peldaño A (AUTODESCRIPTIVO): el software se describe solo.

Sniff (con guard SSRF ANTES de cada fetch) de los lugares canónicos donde una API
publica su contrato — /openapi.json, /swagger.json, /spec.json, .well-known — y de
un /graphql que conteste introspección. Si encuentra un doc, lo PARSEA (Swagger 2.0
y OpenAPI 3.x, JSON; YAML queda fuera — stdlib no trae parser) a CandidateTool de
LECTURA (GET) que el candado §3 puede LLAMAR de verdad.

Clave de diseño (correctud del switch nivel-2): un path param SIN ejemplo real
(example/default/enum del doc) NO se rellena con un valor inventado — se deja sin
llenar → el candado lo dropea como BAD_SHAPE (400-like), NO como 404. Así un
`/pet/{id}` sin id de ejemplo no cuenta como "doc stale" (que es 404 vivo). Inventar
un id arbitrario daría 404 y fingiría staleness donde no la hay.

GraphQL: se DETECTA (emite señal) pero NO se forja — el candado vivo §3 es GET-only
(llama endpoints REST); una mutation/query GraphQL es POST a un único endpoint con
body, fuera del alcance de este validador. Señal sí, candidatas no (honesto).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.strategy.types import DiscoverySignal, StrategyContext  # noqa: E402

# rutas canónicas de auto-descripción (relativas al base_url y a la raíz del host)
_DOC_PATHS = (
    "/openapi.json", "/swagger.json", "/spec.json",
    "/swagger/v1/swagger.json", "/.well-known/openapi.json", "/api-docs",
)
_GRAPHQL_PATHS = ("/graphql", "/api/graphql")
_INTROSPECTION = {"query": "{__schema{queryType{name} types{name kind}}}"}


# ── sniff: dónde mirar (base_url primero, raíz del host después) ─────────────────

def _candidate_doc_urls(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    p = urlparse(base)
    root = f"{p.scheme}://{p.netloc}"
    urls: list[str] = []
    for path in _DOC_PATHS:
        urls.append(base + path)
        if root != base:
            urls.append(root + path)
    # dedup preservando orden
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def discover(ctx: StrategyContext) -> tuple[list[DiscoverySignal], list[C.CandidateTool], dict]:
    """Sniff + parseo. Devuelve (señales, candidatas, meta-del-doc). Cada fetch pasa
    por el guard SSRF (ctx.guarded_get). El primer doc parseable gana."""
    signals: list[DiscoverySignal] = []
    for url in _candidate_doc_urls(ctx.base_url):
        if not ctx.ledger.can_make_call():
            break
        res = ctx.guarded_get(url)            # guard SSRF adentro
        if res is None:
            continue
        kind = _doc_kind(url)
        if res.ok and isinstance(res.json, dict) and _looks_like_openapi(res.json):
            signals.append(DiscoverySignal(kind=kind, url=res.url_redacted, status=res.status,
                                           detail="doc auto-descriptivo parseable"))
            cands, meta = _parse(res.json, ctx.base_url)
            meta["doc_url"] = res.url_redacted
            return signals, cands, meta
        elif res.status and res.status != 404:
            # algo respondió en esa ruta pero no es un openapi (200 raro / 401 / 5xx) → señal débil
            signals.append(DiscoverySignal(kind=kind, url=res.url_redacted, status=res.status,
                                           detail="ruta de doc respondió pero no es OpenAPI parseable"))

    # GraphQL: introspección (POST) — solo DETECTA, no forja (candado §3 es GET-only)
    gql = _probe_graphql(ctx)
    if gql is not None:
        signals.append(gql)
    return signals, [], {}


def _doc_kind(url: str) -> str:
    low = url.lower()
    if "swagger" in low:
        return "swagger"
    if "spec.json" in low:
        return "spec"
    if "graphql" in low:
        return "graphql"
    return "openapi"


def _looks_like_openapi(doc: dict) -> bool:
    return bool(doc.get("openapi") or doc.get("swagger")) and isinstance(doc.get("paths"), dict)


# ── GraphQL: introspección (POST guardado, stdlib — LiveHTTP es GET-only) ────────

def _probe_graphql(ctx: StrategyContext) -> Optional[DiscoverySignal]:
    base = ctx.base_url.rstrip("/")
    p = urlparse(base)
    root = f"{p.scheme}://{p.netloc}"
    for path in _GRAPHQL_PATHS:
        for target in ([base + path, root + path] if root != base else [base + path]):
            if not ctx.ledger.can_make_call():
                return None
            if not ctx.guard.check(target):       # guard SSRF ANTES del fetch
                ctx.emit({"type": "guard.deny", "url": target, "reason": "graphql probe"})
                continue
            ctx.ledger.add_calls(1)
            body = json.dumps(_INTROSPECTION).encode("utf-8")
            req = urllib.request.Request(
                target, data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": "puppet-inspection-strategy/1.0", "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    status = resp.getcode() or 0
            except urllib.error.HTTPError as e:
                status = e.code
                raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                data = None
            if status == 200 and isinstance(data, dict) and (data.get("data") or {}).get("__schema"):
                return DiscoverySignal(
                    kind="graphql", url=target, status=status,
                    detail="introspección viva — API GraphQL (señal; no forjable por el candado GET-only)")
    return None


# ── parseo Swagger 2.0 / OpenAPI 3.x → CandidateTool (solo GET = READ) ──────────

def _parse(doc: dict, base_url: str) -> tuple[list[C.CandidateTool], dict]:
    refs = doc                                  # para resolver $ref locales (#/...)
    server = _effective_server(doc, base_url)
    meta = {"version": doc.get("openapi") or ("swagger-" + str(doc.get("swagger"))),
            "title": (doc.get("info") or {}).get("title", ""),
            "server": server, "n_paths": len(doc.get("paths") or {})}
    cands: list[C.CandidateTool] = []
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared_params = item.get("parameters") or []
        op = item.get("get")
        if not isinstance(op, dict):
            continue                            # solo GET (READ); writes no se ejecutan (§7)
        params = _merge_params(shared_params, op.get("parameters") or [], refs)
        endpoint = _endpoint_for(server, path, base_url)
        path_vals, query_vals, missing_req = _sample_call(params, refs)
        name = _op_name(op, path)
        props = {pn: {"type": "string"} for pn in (path_vals.keys() | query_vals.keys())}
        input_schema: dict[str, Any] = {
            "type": "object", "properties": props,
            "x-sample-call": {"path_params": path_vals, "query": query_vals},
        }
        cands.append(C.CandidateTool(
            name=name, kind=C.ToolKind.READ, endpoint=endpoint, method="GET",
            input_schema=input_schema,
            description=(op.get("summary") or op.get("description") or "")[:200],
            derived_from=("openapi:" + path,)))
    return cands, meta


def _effective_server(doc: dict, base_url: str) -> str:
    """URL absoluta del server que el doc declara. Swagger 2.0: schemes+host+basePath.
    OpenAPI 3.x: servers[0].url (puede ser relativa → se resuelve contra base_url)."""
    if doc.get("swagger"):                      # 2.0
        host = doc.get("host")
        if host:
            scheme = (doc.get("schemes") or ["https"])[0]
            return f"{scheme}://{host}{doc.get('basePath', '')}".rstrip("/")
        return base_url.rstrip("/")
    servers = doc.get("servers") or []          # 3.x
    if servers and servers[0].get("url"):
        return urljoin(base_url.rstrip("/") + "/", servers[0]["url"]).rstrip("/")
    return base_url.rstrip("/")


def _endpoint_for(server: str, path: str, base_url: str) -> str:
    """Endpoint RELATIVO a base_url (el validador llama base_url + endpoint). Si el
    server del doc difiere del base_url, se reconcilia para que la URL final sea la real."""
    full = server.rstrip("/") + path
    base = base_url.rstrip("/")
    if full.startswith(base):
        rel = full[len(base):]
        return rel if rel.startswith("/") else "/" + rel
    return path                                 # doc en otro host/prefijo → mejor esfuerzo


def _merge_params(shared: list, op_params: list, refs: dict) -> list:
    out, seen = [], set()
    for p in list(op_params) + list(shared):    # op pisa shared
        p = _deref(p, refs)
        if not isinstance(p, dict):
            continue
        key = (p.get("name"), p.get("in"))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _sample_call(params: list, refs: dict) -> tuple[dict, dict, list]:
    """Arma el x-sample-call. Path params: SOLO con ejemplo real del doc (si no, se
    omiten → BAD_SHAPE, no 404). Query: ejemplos reales + un genérico tipado para los
    REQUERIDOS sin ejemplo (para darle chance al call); opcionales sin ejemplo se omiten."""
    path_vals: dict[str, Any] = {}
    query_vals: dict[str, Any] = {}
    missing_required: list[str] = []
    for p in params:
        loc = p.get("in")
        name = p.get("name")
        if not name:
            continue
        val = _example_value(p, refs)
        if loc == "path":
            if val is not None:
                path_vals[name] = val
            else:
                missing_required.append(name)   # sin ejemplo → se deja sin llenar (BAD_SHAPE)
        elif loc == "query":
            if val is not None:
                query_vals[name] = val
            elif p.get("required"):
                gen = _generic_value(p, refs)
                if gen is not None:
                    query_vals[name] = gen
    return path_vals, query_vals, missing_required


def _example_value(p: dict, refs: dict) -> Any:
    """Ejemplo REAL del doc (example/default/enum). None si el doc no lo trae."""
    if "example" in p:
        return p["example"]
    sch = _deref(p.get("schema"), refs) if isinstance(p.get("schema"), dict) else p
    if isinstance(sch, dict):
        if "example" in sch:
            return sch["example"]
        if "default" in sch:
            return sch["default"]
        if sch.get("enum"):
            return sch["enum"][0]
    return None


def _generic_value(p: dict, refs: dict) -> Any:
    """Valor genérico tipado SOLO para query params requeridos sin ejemplo."""
    sch = _deref(p.get("schema"), refs) if isinstance(p.get("schema"), dict) else p
    t = (sch or {}).get("type") or p.get("type")
    return {"integer": 1, "number": 1, "boolean": True, "string": "test", "array": []}.get(t)


def _deref(node: Any, refs: dict) -> Any:
    """Resuelve un $ref local (#/a/b/c). No-op si no es ref o no resuelve."""
    if isinstance(node, dict) and isinstance(node.get("$ref"), str) and node["$ref"].startswith("#/"):
        cur: Any = refs
        for seg in node["$ref"][2:].split("/"):
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
            else:
                return node
        return cur
    return node


def _op_name(op: dict, path: str) -> str:
    oid = op.get("operationId")
    if oid:
        slug = "".join(ch if ch.isalnum() else "_" for ch in str(oid)).strip("_")
        if slug:
            return slug[:60]
    segs = [s for s in path.split("/") if s and not s.startswith("{")]
    return ("get_" + "_".join(segs))[:60] if segs else "get_root"


__all__ = ["discover"]
