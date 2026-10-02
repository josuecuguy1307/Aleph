#!/usr/bin/env python3
"""
gmail_draft_server.py — Gmail MCP server (stdio, JSON-RPC 2.0) para el belt COWORK.

FAMILIA 3 (OAuth Connect): el usuario autoriza SU cuenta de Gmail por el botón
"Conectar Gmail"; el credential-broker (B4) guarda/renueva el OAuth por end-user y el
runtime inyecta el access-token como ${GMAIL_TOKEN} al entorno de ESTE subprocess.
Este server solo consume un bearer — es agnóstico a cómo se obtuvo (OAuth o pegado).
Multi-usuario por construcción; jamás la cuenta de dev.

REGLA SEND-GATE-FIRST (no negociable): la barrera es el GATE, no la ausencia de la tool.
  • create_draft  → crea un draft real en Gmail. NO envía. (ESCRITURA segura, auto-ejecuta
                    vía base-matrix-cowork.json; idempotente por (to, subject)).
  • send_email    → envía un correo REAL. Su nombre matchea SEND_HINTS → el enforcer lo fuerza a
                    `needs_ok` AUNQUE la receta apague el gate: en un run gateado SIN aprobación,
                    send_email NUNCA llega a este código → el correo NO sale (HELD). [ticket 29,
                    jul-2026] el atom de catálogo "gmail-draft" ("Correo (Gmail)") SÍ lo lista ahora
                    → pieza send-capable CON su gate (zona Entrega, level=send). El gate del motor
                    (recipe_enforcer §3.5, hard-floor server-side) es la garantía, no que la tool
                    falte de la receta.

IDEMPOTENCIA (bar: re-correr NO duplica el draft)
  create_draft: lista los drafts y compara (to, subject); si ya hay uno igual, lo devuelve
  con created=false en vez de crear otro. (Gmail drafts.list da solo ids → se hace
  drafts.get(format=metadata) por cada uno, acotado a los primeros 50.)

CONFIG (entorno)
  GMAIL_TOKEN     (o GMAIL_ACCESS_TOKEN / GMAIL_API_KEY) — bearer OAuth (inyectado por BYOK).
  GMAIL_API_BASE  (opcional) — default https://gmail.googleapis.com. Apuntalo a un stub
                               local para verificar el flujo SIN cuenta real.
  GMAIL_USER      (opcional) — default 'me'.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

_TIMEOUT = 25
_DEFAULT_BASE = "https://gmail.googleapis.com"

# [i18n-bi] bilingüe server-side (PUPPET_LANG, default es; no-op hasta que el runtime lo
# setee). Mismo patrón que fem_server.py: descripciones, notas del borrador y errores que
# el usuario ve salen en su idioma. La REGLA send-gate-first no cambia.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
GMAIL_I18N = {
    "es": {
        "err.no_token": ("no hay credencial de Gmail en el entorno del server (GMAIL_TOKEN ausente o "
                         "sin expandir): la BYOK/OAuth no se inyectó. Conecta Gmail (Familia 3) y "
                         "verifica la inyección (construir≠inyectar)."),
        "err.rejected": "Gmail rechazó la credencial (%s): %s.",
        "err.api": "Gmail API %s: %s",
        "err.unreachable": "no pude alcanzar Gmail (%s): %s",
        "err.draft_needs": "create_draft necesita 'to' y 'subject'",
        "err.unknown_tool": "tool desconocida: %s",
        "note.idempotent": "ya existía un borrador con ese destinatario y asunto — no se duplicó",
        "note.draft_saved": "borrador guardado — NO se envió",
        "tool.create_draft.desc": ("Prepara un BORRADOR de correo en Gmail (NO lo envía). Idempotente: si ya hay un "
                                   "borrador con el mismo destinatario y asunto, no crea otro. Deja siempre el correo "
                                   "como borrador; mandarlo es una acción aparte que requiere OK del usuario."),
        "tool.send_email.desc": ("Envía un correo de verdad. ACCIÓN DE ALTA CONSECUENCIA: requiere OK explícito del "
                                 "usuario (pasa por el send-gate). No la uses para 'dejar listo' un correo — para eso "
                                 "está create_draft."),
        "p.to": "Destinatario.", "p.subject": "Asunto.", "p.body": "Cuerpo del correo.",
    },
    "en": {
        "err.no_token": ("no Gmail credential in the server environment (GMAIL_TOKEN missing or "
                         "unexpanded): the BYOK/OAuth was not injected. Connect Gmail (Family 3) and "
                         "verify the injection (build≠inject)."),
        "err.rejected": "Gmail rejected the credential (%s): %s.",
        "err.api": "Gmail API %s: %s",
        "err.unreachable": "could not reach Gmail (%s): %s",
        "err.draft_needs": "create_draft needs 'to' and 'subject'",
        "err.unknown_tool": "unknown tool: %s",
        "note.idempotent": "a draft with that recipient and subject already existed — not duplicated",
        "note.draft_saved": "draft saved — NOT sent",
        "tool.create_draft.desc": ("Prepare an email DRAFT in Gmail (does NOT send it). Idempotent: if a draft with "
                                   "the same recipient and subject already exists, it does not create another. Always "
                                   "leave the email as a draft; sending it is a separate action that requires the user's OK."),
        "tool.send_email.desc": ("Send an email for real. HIGH-CONSEQUENCE ACTION: requires the user's explicit OK "
                                 "(goes through the send-gate). Do not use it to 'leave ready' an email — create_draft "
                                 "is for that."),
        "p.to": "Recipient.", "p.subject": "Subject.", "p.body": "Email body.",
    },
}


def _t(key):
    return GMAIL_I18N.get(PUPPET_LANG, {}).get(key) or GMAIL_I18N["es"].get(key) or key


def _token() -> str:
    for var in ("GMAIL_TOKEN", "GMAIL_ACCESS_TOKEN", "GMAIL_API_KEY"):
        val = (os.environ.get(var) or "").strip()
        if val and not val.startswith("${"):
            return val
    return ""


def _base() -> str:
    b = (os.environ.get("GMAIL_API_BASE") or "").strip()
    if not b or b.startswith("${"):
        return _DEFAULT_BASE
    return b.rstrip("/")


def _user() -> str:
    u = (os.environ.get("GMAIL_USER") or "").strip()
    return u if u and not u.startswith("${") else "me"


class GmailError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None) -> dict:
    token = _token()
    if not token:
        raise GmailError(_t("err.no_token"))
    url = _base() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else err.get("error", raw)
        except json.JSONDecodeError:
            msg = raw
        if e.code in (401, 403):
            raise GmailError(_t("err.rejected") % (e.code, msg))
        raise GmailError(_t("err.api") % (e.code, msg))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GmailError(_t("err.unreachable") % (_base(), e))


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _b64url_decode(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii")).decode("utf-8", errors="replace")


def _rfc822(to: str, subject: str, body: str) -> str:
    # TICKET 20 · el Subject es un HEADER (ASCII-only). Un "·" o acento crudo sale como Ã,Â· en el
    # cliente (verificado en el inbox de persona usuaria, H-12). Si el subject tiene no-ASCII, se codifica
    # RFC 2047 (=?UTF-8?B?…?=); si es ASCII puro queda igual (no rompe la idempotencia por subject).
    subj = subject or ""
    try:
        subj.encode("ascii")
    except UnicodeEncodeError:
        from email.header import Header
        subj = Header(subj, "utf-8").encode()
    return f"To: {to}\r\nSubject: {subj}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{body}"


def _header(msg: dict, name: str) -> str:
    for h in (((msg.get("payload") or {}).get("headers")) or []):
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _find_existing_draft(to: str, subject: str) -> dict | None:
    u = _user()
    listing = _request("GET", f"/gmail/v1/users/{u}/drafts?maxResults=50")
    for d in (listing.get("drafts") or [])[:50]:
        did = d.get("id")
        if not did:
            continue
        full = _request("GET", f"/gmail/v1/users/{u}/drafts/{did}?format=metadata")
        msg = full.get("message", {}) or {}
        if _header(msg, "Subject").strip() == (subject or "").strip() and \
           _header(msg, "To").strip() == (to or "").strip():
            return {"draft_id": did, "message_id": msg.get("id")}
    return None


def _create_draft(to: str, subject: str, body: str = "") -> dict:
    to = (to or "").strip()
    subject = (subject or "").strip()
    if not to or not subject:
        raise GmailError(_t("err.draft_needs"))
    existing = _find_existing_draft(to, subject)
    if existing:
        return {**existing, "to": to, "subject": subject, "created": False, "idempotent": True,
                "note": _t("note.idempotent")}
    raw = _b64url(_rfc822(to, subject, body))
    out = _request("POST", f"/gmail/v1/users/{_user()}/drafts", {"message": {"raw": raw}})
    msg = out.get("message", {}) or {}
    return {"draft_id": out.get("id"), "message_id": msg.get("id"),
            "to": to, "subject": subject, "created": True, "idempotent": False,
            "note": _t("note.draft_saved")}


def _send_email(to: str, subject: str, body: str = "") -> dict:
    """SEND real. En un run gateado este código NO se alcanza (el gate detiene send_email
    antes de invocar la tool). Si llegara a correr (run sin gate), manda de verdad — por
    eso JAMÁS se cabla en una receta de producción sin el send-gate en el path."""
    to = (to or "").strip()
    raw = _b64url(_rfc822(to, (subject or "").strip(), body))
    out = _request("POST", f"/gmail/v1/users/{_user()}/messages/send", {"raw": raw})
    return {"message_id": out.get("id"), "to": to, "subject": subject, "sent": True}


TOOLS = [
    {
        "name": "create_draft",
        "description": _t("tool.create_draft.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": _t("p.to")},
                "subject": {"type": "string", "description": _t("p.subject")},
                "body": {"type": "string", "description": _t("p.body")},
            },
            "required": ["to", "subject"],
        },
    },
    {
        "name": "send_email",
        "description": _t("tool.send_email.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": _t("p.to")},
                "subject": {"type": "string", "description": _t("p.subject")},
                "body": {"type": "string", "description": _t("p.body")},
            },
            "required": ["to", "subject"],
        },
    },
]

_DISPATCH = {
    "create_draft": lambda a: _create_draft(a.get("to", ""), a.get("subject", ""), a.get("body", "")),
    "send_email": lambda a: _send_email(a.get("to", ""), a.get("subject", ""), a.get("body", "")),
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
            "serverInfo": {"name": "gmail-draft-server", "version": "0.1.0"},
        }})
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
                raise GmailError(_t("err.unknown_tool") % name)
            val = fn(args)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": False,
            }})
        except Exception as exc:  # noqa: BLE001
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}], "isError": True,
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
