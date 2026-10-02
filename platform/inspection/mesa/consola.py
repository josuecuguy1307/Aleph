"""
mesa/consola.py — el candado por-tool + la consola de prueba (núcleo puro, provider inyectado).

Dos gestos de "Tomar el mando" / "Probarlas", sobre una sesión YA adquirida (el router la arma
con provider_and_auth y la pasa):

  • validar_tools(session, provider, [spec]) → mismo candado que el motor (LiveValidator.validate),
    idéntico para una tool escrita/editada a mano. Una tool rota (404 / sample-call incompleto /
    write sin forma) es RECHAZADA por el candado, no equipada. Devuelve la Validation serializada
    con verified_by diferenciado (200-OK+schema-match fuerte vs OPTIONS/schema/dry-run débiles).

  • probar_tool(session, provider, spec, args, execute) → ejecuta UNA tool con args del usuario.
    READ + execute=True → GET vivo real {request, response{status,json}}. READ + execute=False →
    dry-run: la request ARMADA sin pegarla. WRITE → SIEMPRE {gated:true, request} (§7: los writes
    JAMÁS se ejecutan para probar; se muestran armados y se piden con OK humano). El guard T9
    corre antes de cualquier fetch.

NO reconstruye el candado: reusa LiveValidator y LiveHTTP tal cual. El provider trae la auth
uniforme (el motor no distingue de qué forma vino).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.library import store  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.validator import LiveValidator, _query_of  # noqa: E402


def _http_for(session: C.Session, provider: Any, *, ledger=None) -> LiveHTTP:
    """Arma el LiveHTTP con la auth de la Session UNIFORME (espeja engine.py:131-135):
    Forma 1 (token en query) → inyecta el secreto; Forma 2/3 → headers/cookies ya en la sesión.
    (El guard anti-SSRF vive dentro del LiveValidator para el camino write; el read reusa la
    sesión ya validada por la puerta, Capa 1.)"""
    inline_auth = bool(session.headers) or bool(session.cookies)
    query_secret = "" if inline_auth else getattr(provider, "secret", "")
    auth_param = getattr(provider, "auth_param", "") or ""
    return LiveHTTP(secret=query_secret, auth_param=auth_param,
                    headers=session.headers, cookies=session.cookies, ledger=ledger)


def _candidatos(specs: Sequence[dict]) -> list[C.CandidateTool]:
    """Deserializa specs de tool (dict) a CandidateTool con el MISMO puente que la biblioteca
    usa para reinyectar priors — así una tool a mano entra al candado igual que una del motor."""
    out: list[C.CandidateTool] = []
    for s in specs or []:
        # aceptamos tanto el shape 'endpoint_to_dict' como el shape del evento tool.propuesta
        d = dict(s or {})
        if "input_schema" not in d and ("params" in d or "x-sample-call" in d):
            d["input_schema"] = d.get("params") or {}
        if "x-sample-call" in d:  # conveniencia: sample-call al ras del spec
            d.setdefault("input_schema", {})
            if isinstance(d["input_schema"], dict):
                d["input_schema"].setdefault("x-sample-call", d["x-sample-call"])
        d.setdefault("kind", "read")
        d.setdefault("method", "GET")
        d.setdefault("description", "")
        if not d.get("endpoint") or not d.get("name"):
            continue
        out.append(store.candidate_from_dict(d))
    return out


def _serialize_verified(v: C.VerifiedTool) -> dict:
    return {
        "nombre": v.candidate.name,
        "endpoint": v.candidate.endpoint,
        "method": v.candidate.method,
        "kind": v.candidate.kind.value,
        "verified_by": v.verified_by,
        # fuerza del veredicto para la UI (200-OK+schema-match = fuerte; el resto = declarado)
        "fuerza": "fuerte" if str(v.verified_by).startswith("200") else "declarado",
        "payload": v.sample_response,
    }


def _serialize_failed(f: C.FailedTool) -> dict:
    return {
        "nombre": f.candidate.name,
        "endpoint": f.candidate.endpoint,
        "method": f.candidate.method,
        "kind": f.candidate.kind.value,
        "motivo": f.detail or f.failure.symptom,
        "symptom": f.failure.symptom,
        "clase": f.failure.name,
        "move": f.failure.move,
    }


def validar_tools(session: C.Session, provider: Any, specs: Sequence[dict], *,
                  ledger=None) -> dict:
    """El candado 5/5 sobre tools arbitrarias (editadas / escritas a mano). Mismo LiveValidator
    que el motor. Devuelve {verificadas:[...], descartadas:[...], total, ok}."""
    cands = _candidatos(specs)
    if not cands:
        return {"verificadas": [], "descartadas": [], "total": 0, "ok": False,
                "error": "sin tools válidas (cada spec necesita name + endpoint)"}
    http = _http_for(session, provider, ledger=ledger)
    validator = LiveValidator(http, ledger=ledger)
    validation = validator.validate(session, cands)
    return {
        "verificadas": [_serialize_verified(v) for v in validation.verified],
        "descartadas": [_serialize_failed(f) for f in validation.failed],
        "total": len(cands),
        "ok": bool(validation.verified),
    }


def probar_tool(session: C.Session, provider: Any, spec: dict, args: dict, *,
                execute: bool = False, ledger=None) -> dict:
    """Ejecuta UNA tool con args del usuario. READ execute=True → GET vivo. READ execute=False →
    dry-run (request armada). WRITE → siempre gated (nunca ejecuta). Devuelve la request y, para
    reads ejecutados, la respuesta real."""
    cands = _candidatos([spec])
    if not cands:
        return {"ok": False, "error": "spec inválida (falta name/endpoint)"}
    cand = cands[0]
    # combinar el sample-call del spec con los args del usuario (los args ganan)
    sample = dict((cand.input_schema or {}).get("x-sample-call") or {})
    path_params = dict(sample.get("path_params") or {})
    query = dict(sample.get("query") or {})
    for k, val in (args or {}).items():
        # heurística mínima: si {k} aparece en el endpoint es path param, si no es query
        if "{" + k + "}" in cand.endpoint:
            path_params[k] = val
        else:
            query[k] = val

    # resolver la URL concreta (mismo criterio que el candado)
    base = session.base_url.rstrip("/")
    endpoint = cand.endpoint
    faltan = []
    import re as _re
    for name in _re.findall(r"\{([a-zA-Z0-9_]+)\}", cand.endpoint):
        if name in path_params and path_params[name] not in (None, ""):
            endpoint = endpoint.replace("{" + name + "}", str(path_params[name]))
        else:
            faltan.append(name)
    url = base + endpoint
    request = {"method": cand.method, "url": url, "path_params": path_params,
               "query": {k: v for k, v in query.items() if v not in (None, "")}}

    if cand.kind is C.ToolKind.WRITE:
        # §7 · el write JAMÁS se ejecuta para probar. Se muestra armado y se pide OK.
        return {"ok": True, "gated": True, "approval_required": True, "kind": "write",
                "request": request,
                "nota": "Esta herramienta ESCRIBE. No la ejecuto sola: te muestro la llamada "
                        "y la corre el agente con tu OK."}

    if faltan:
        return {"ok": False, "kind": "read", "request": request,
                "error": f"faltan valores para: {', '.join(faltan)}"}

    if not execute:
        # dry-run: la request ARMADA, sin pegarla (previsualización de Modo Guiado)
        return {"ok": True, "dry_run": True, "kind": "read", "request": request}

    # READ real: GET vivo con la auth de la sesión.
    http = _http_for(session, provider, ledger=ledger)
    res = http.get(url, _query_of(cand) if not query else query)
    return {
        "ok": bool(res.ok), "dry_run": False, "kind": "read", "request": request,
        "response": {"status": res.status, "json": res.json,
                     "text": (res.text or "")[:900], "elapsed_ms": res.elapsed_ms,
                     "url": res.url_redacted, "reason": res.reason},
    }


__all__ = ["validar_tools", "probar_tool"]
