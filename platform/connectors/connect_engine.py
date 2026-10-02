#!/usr/bin/env python3
"""
connect_engine.py — el MOTOR del connect-wizard universal (D2).

Una sola pieza, GENÉRICA: consume CUALQUIER onboarding object v3 y corre el flujo
paste → adjunta credencial vía `auth` → `validate` (+ `content_probe` si
`requires_sharing`) → estado. CERO ramas por-conector: todo sale del object.

Estados (los que el wizard pinta):
  connected        — validate 200 (y, si requires_sharing, content_probe con contenido)
  connected_empty  — validate 200 pero content_probe vacío (solo si requires_sharing) → ámbar
  invalid          — 401/403 → rojo + errors.invalid (o el error mapeado)
  network          — error de transporte / 5xx → errors.network

`auth` se inyecta en TODA request (validate y content_probe). Esquemas: bearer · basic ·
header · query (RECIPE-SCHEMA v3). Headers no-credenciales (ej. Notion-Version) van en
validate.headers / content_probe.headers.

api_base: para conectores self-hosted (needs_base_url) lo trae el user (su dominio); para
APIs globales hoy NO está en el object (gap documentado — ver verify notes). El motor lo
recibe como parámetro, así que NO contiene ningún nombre de conector.

Stdlib only. `http` es inyectable (tests sin socket); por defecto urllib real.
"""
from __future__ import annotations
import base64, json, urllib.request, urllib.error
from typing import Any, Callable, Optional


def _interp(template: str, creds: dict) -> str:
    out = template
    for k, v in (creds or {}).items():
        out = out.replace("{" + k + "}", str(v))
    return out


def apply_auth(auth: dict, creds: dict, headers: dict, params: dict) -> tuple[dict, dict]:
    """Inyecta las credenciales en headers/params según el esquema. Genérico, sin
    nombres de conector. Nunca loguea el valor."""
    if not auth:
        return headers, params
    scheme = auth.get("scheme")
    if scheme == "bearer":
        headers["Authorization"] = "Bearer " + _interp(auth["token"], creds)
    elif scheme == "basic":
        u = _interp(auth["username"], creds); p = _interp(auth["password"], creds)
        headers["Authorization"] = "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()
    elif scheme == "header":
        headers[auth["name"]] = _interp(auth["value"], creds)
    elif scheme == "query":
        # [FIX-P11 · §1] `name` vale igual que `param`. Los objects del catálogo usan `name`
        # para las DOS variantes (header y query) —es el nombre del campo, no importa si va
        # en la cabecera o en la query— y este código sólo aceptaba `param`. Resultado
        # medido hoy: POST /v1/connectors/massive/connect → 500 KeyError('param'). Un 500 es
        # la peor forma de rechazar una llave: ni siquiera llega a decir qué pasó, y la
        # persona ve un fallo genérico sobre una credencial que podía estar perfecta.
        clave = auth.get("param") or auth.get("name")
        if not clave:
            raise ValueError("auth.scheme='query' sin `param` ni `name`")
        params[clave] = _interp(auth["value"], creds)
    else:
        raise ValueError(f"auth.scheme desconocido: {scheme!r}")
    return headers, params


def _dotted(obj: Any, path: str) -> Any:
    cur = obj
    for part in (path or "").split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _empty(body: Any, empty_when: str) -> bool:
    """Evalúa el predicado de vacío del object. Soporta la forma de los objetos v3:
    'results.length == 0' (y variantes <campo>.length == 0). Sin eval de código."""
    if not empty_when:
        return False
    ew = empty_when.replace(" ", "")
    if ew.endswith(".length==0"):
        field = ew[:-len(".length==0")]
        val = _dotted(body, field) if field else body
        return not val  # None o lista vacía → vacío
    return False


def _urllib_http(method: str, url: str, headers: dict, params: dict,
                 body: Optional[dict] = None, timeout: float = 10.0):
    if params:
        from urllib.parse import urlencode
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode(errors="replace")
            try: return r.status, json.loads(raw)
            except json.JSONDecodeError: return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try: return e.code, json.loads(raw)
        except json.JSONDecodeError: return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return None, str(e)  # None status = error de transporte (incl. api_base faltante)


def connect(obj: dict, creds: dict, *, api_base: str = "",
            http: Callable = _urllib_http) -> dict:
    """Corre el flujo del wizard para UN object. Devuelve {state, identity, message}.
    100% data-driven: ni un nombre de conector acá.

    Ruteo por `auth_method` (los 4 casos), genérico:
      keyless      → connected directo (sin credencial).
      admin_oauth  → gate (lo habilita la institución; no hay flujo de user X).
      oauth        → oauth_pending (necesita la app OAuth de Puppet registrada; gateado).
      personal_token → validate (+ content_probe si requires_sharing) ← el flujo completo.
    """
    am = obj.get("auth_method")
    if am == "keyless":
        return {"state": "connected", "message": obj.get("capability_line", "Listo.")}
    if am == "admin_oauth":
        return {"state": "gate",
                "message": obj.get("admin_requirement")
                or "Esta función necesita que tu institución la habilite."}
    if am == "oauth":
        return {"state": "oauth_pending", "provider": obj.get("provider"),
                "message": f"Conecta con {obj.get('provider','el proveedor')} — "
                           "requiere el registro OAuth de Puppet (gateado)."}

    auth = obj.get("auth") or {}
    errors = obj.get("errors") or {}

    # ── validate ──
    v = obj.get("validate") or {}

    # ── [FIX-P11 · §1] SIN VALIDADOR NO SE PRUEBA NADA — Y NO SE MIENTE ─────────────────
    # El bug medido (caso índice Exa, 2026-07-27): un object con `validate` pero SIN `path`
    # caía igual al request de abajo, que entonces pegaba contra la RAÍZ del api_base
    # (`api_base + ""`). Eso no valida nada: es un GET a la portada de la API. Y lo que la
    # raíz conteste decide el veredicto de la llave de la persona:
    #     GET https://api.exa.ai        → 404  → `status != 200` → "Esa llave no sirve"
    #     GET https://api.coingecko…/v3 → 404  → idem            → "Esa llave no sirve"
    #     GET https://api.massive.com   → 404  → idem            → "Esa llave no sirve"
    #     GET https://context7.com      → 200  (¡el HTML de la home!) → pasa como buena
    # O sea: tres proveedores rechazaban CUALQUIER llave —incluida una recién generada en su
    # dashboard— y el cuarto aceptaba cualquier cosa. Dos caras de la misma mentira.
    # Sin `path` declarado NO hay validador: se guarda la llave y se dice la verdad.
    if not str(v.get("path") or "").strip():
        return {"state": "connected_unverified", "identity": None, "unverifiable": True,
                "message": obj.get("unverified_line")
                or "Guardé tu llave cifrada. No tengo forma directa de probarla aquí — "
                   "la verifico de punta a punta en el primer uso real y te aviso."}

    headers, params = apply_auth(auth, creds, dict(v.get("headers") or {}), {})
    status, body = http(v.get("method", "GET"), api_base.rstrip("/") + v.get("path", ""),
                        headers, params)

    if status is None:
        return {"state": "network", "message": errors.get("network", "No pude verificar ahora.")}
    # 401/403 SÍ es un veredicto sobre la llave: el proveedor la miró y la rechazó.
    if status in (401, 403):
        return {"state": "invalid", "message": errors.get("invalid", "Esa llave no funcionó.")}
    if status >= 500:
        return {"state": "network", "message": errors.get("network", "No pude verificar ahora.")}
    if status != 200:
        # [FIX-P11 · §1] Un no-200 que NO es 401/403 no dice nada de la llave: dice que el
        # endpoint que elegimos no era el que creíamos (404 = ruta mal, 405 = método mal).
        # Con `soft` declarado —la clase "no sé validarla directo"— eso NO puede degradar a
        # "tu llave no sirve": es culpa nuestra, no de su credencial.
        if v.get("soft"):
            return {"state": "connected_unverified", "identity": None, "unverifiable": True,
                    "http_status": status,
                    "message": obj.get("unverified_line")
                    or "Guardé tu llave cifrada. El proveedor no me dejó confirmarla aquí "
                       "(respondió %s a mi chequeo) — la verifico en el primer uso real." % status}
        return {"state": "invalid", "message": errors.get("invalid", "Esa llave no funcionó.")}

    # ── 200-con-error-en-body (clase de APIs que NUNCA devuelven 401: Alpha Vantage,
    # varias más). `validate.invalid_when` = lista de campos dotted; si ALGUNO está
    # presente (no nulo) en el body, la llave es inválida pese al 200. GENÉRICO y
    # data-driven (sin nombres de conector); default-off (sin el campo, sin cambio). ──
    inv_when = v.get("invalid_when") or []
    if isinstance(body, dict) and any(_dotted(body, f) is not None for f in inv_when):
        return {"state": "invalid", "message": errors.get("invalid", "Esa llave no funcionó.")}

    # ── CAPACIDAD (scope) — el "asesino silencioso". `validate.require` = campos dotted que
    # DEBEN ser truthy en la respuesta (ej. access.user.write para Zotero). Una key que
    # AUTENTICA pero NO tiene el permiso que el belt necesita (read-only) muere ACÁ, en el
    # connect, con un mensaje claro — no en el primer uso (el WRITE). El validate prueba la
    # CAPACIDAD, no solo el auth. GENÉRICO y data-driven; default-off (sin `require`, sin cambio). ──
    for rule in (v.get("require") or []):
        fld = rule.get("field") if isinstance(rule, dict) else rule
        if isinstance(body, dict) and not _dotted(body, fld):
            ekey = (rule.get("error") if isinstance(rule, dict) else None) or "invalid"
            return {"state": "invalid",
                    "message": errors.get(ekey, errors.get("invalid", "A tu llave le falta un permiso necesario."))}

    identity = _dotted(body, v.get("identity_field", "")) if isinstance(body, dict) else None

    # ── 200 pero el proveedor NO permite validar la key (clase no-validable: Alpha
    # Vantage y otras APIs que sirven data hasta con una key inexistente). Si el object
    # declara `validate.soft: true`, NO mentimos un verde: estado `connected_unverified`
    # (ámbar) — la key se acepta/guarda pero se confirma recién en el PRIMER USO real.
    # GENÉRICO (sin nombres de conector), default-off. ──
    # [FIX-P11 · §2] `soft` gobierna LO AMBIGUO, no lo confirmado. Un 200 de un endpoint que
    # el object declara como su validador ES una verificación: el proveedor miró la llave y
    # la aceptó. Seguir contestando "no pude confirmarla" ahí sería dejar en ámbar algo que
    # ya está probado — el espejo del bug de §1 (decir que no se probó lo que sí se probó).
    # Sin `path` no se llega hasta acá (se cortó arriba), así que un 200 acá siempre viene
    # de un endpoint declarado a propósito.
    if v.get("soft") and not str(v.get("path") or "").strip():
        return {"state": "connected_unverified", "identity": identity,
                "message": obj.get("unverified_line")
                or "Guardé tu llave, pero el proveedor no me deja confirmarla aquí. "
                   "La pruebo en el primer uso y, si no anda, te aviso."}

    # ── content_probe (solo si requires_sharing) ──
    if obj.get("requires_sharing"):
        cp = obj.get("content_probe") or {}
        h2, p2 = apply_auth(auth, creds, dict(cp.get("headers") or {}), {})
        cbody_method = cp.get("method", "POST")
        cstatus, cbody = http(cbody_method, api_base.rstrip("/") + cp.get("path", ""),
                              h2, p2, body={} if cbody_method == "POST" else None)
        if cstatus is None or (isinstance(cstatus, int) and cstatus >= 500):
            return {"state": "network", "message": errors.get("network", "No pude verificar ahora.")}
        if _empty(cbody, cp.get("empty_when", "")):
            return {"state": "connected_empty", "identity": identity,
                    "message": obj.get("share_instruction", "Comparte algo para poder verlo.")}

    return {"state": "connected", "identity": identity,
            "message": obj.get("capability_line", "Listo.")}


__all__ = ["connect", "apply_auth"]
