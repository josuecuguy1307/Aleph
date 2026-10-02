#!/usr/bin/env python3
"""Listener OAuth loopback efímero, genérico y sin framework.

El sidecar crea una instancia por proceso. Sólo escucha en la dirección exacta
de ``oauth.redirect_uri``, acepta una vuelta con state válido y cierra el socket
ANTES de canjear el código. Verifier, code y tokens viven sólo en memoria y jamás
aparecen en ``status()``.
"""
from __future__ import annotations

import base64
import hashlib
import html
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional


_MESSAGES = {
    "idle": "OAuth todavía no se inició.",
    "awaiting_consent": "Esperando que autorices en el navegador.",
    "exchanging": "Autorización recibida; guardando el acceso.",
    "connected": "La cuenta quedó conectada.",
    "disconnected": "La cuenta quedó desconectada de Aleph.",
    "denied": "Cancelaste la autorización en el proveedor.",
    "bad_state": "La vuelta de OAuth no coincide; inicia la conexión otra vez.",
    "loopback_timeout": "El proveedor no volvió a Aleph a tiempo; prueba de nuevo.",
    "listener_stopped": "El listener local se detuvo antes de recibir la autorización.",
    "exchange_failed": "El proveedor rechazó el canje del código.",
}


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # El callback deja la conexión en TIME_WAIT. Re-conectar inmediatamente debe
    # poder volver a bindear el MISMO puerto registrado; sigue ligado sólo a loopback.
    allow_reuse_address = True


class LoopbackFlowManager:
    """Un único flujo activo por sidecar (el puerto loopback también es único)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._flow: Optional[dict[str, Any]] = None
        self._server: Optional[_LoopbackHTTPServer] = None
        self._last: dict[str, Any] = {"state": "idle", "message": _MESSAGES["idle"]}

    @staticmethod
    def _endpoint(redirect_uri: str) -> tuple[str, int, str]:
        parsed = urllib.parse.urlparse(redirect_uri)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "http" or host not in ("localhost", "127.0.0.1"):
            raise ValueError("redirect_uri debe ser loopback http://localhost")
        if parsed.port is None:
            raise ValueError("redirect_uri loopback necesita puerto explícito")
        return "127.0.0.1", int(parsed.port), parsed.path or "/"

    def start(
        self,
        *,
        provider: str,
        owner: str,
        cfg: dict,
        client_id: str,
        build_authorize_url: Callable[..., str],
        on_code: Callable[[str, str], dict],
        timeout: float = 180.0,
    ) -> dict:
        """Levanta el socket y devuelve la URL de consentimiento.

        ``on_code`` recibe ``(code, verifier)`` después de cerrar el listener.
        """
        redirect_uri = str((cfg or {}).get("redirect_uri") or "")
        host, port, callback_path = self._endpoint(redirect_uri)
        pkce = (cfg or {}).get("pkce")
        if not isinstance(pkce, dict) or pkce.get("required", True) is False:
            raise ValueError("pkce_required: el loopback exige PKCE")
        if str(pkce.get("method") or "S256").upper() != "S256":
            raise ValueError("pkce_method_unsupported: sólo S256")

        with self._lock:
            if self._flow and self._flow.get("state") in ("awaiting_consent", "exchanging"):
                raise RuntimeError("oauth_flow_in_progress")
            verifier, challenge = _pkce_pair()
            csrf = secrets.token_urlsafe(32)
            stop_event = threading.Event()
            manager = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, _fmt, *_args):
                    return

                def do_GET(self):
                    parsed = urllib.parse.urlparse(self.path)
                    if parsed.path != callback_path:
                        self.send_error(404)
                        return
                    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                    result = manager._receive(
                        state=(params.get("state") or [""])[0],
                        code=(params.get("code") or [""])[0],
                        error=(params.get("error") or [""])[0],
                        error_description=(params.get("error_description") or [""])[0],
                    )
                    ok = result.get("accepted", False)
                    title = "Listo — vuelve a Aleph" if ok else "No se pudo conectar"
                    detail = html.escape(result.get("message") or _MESSAGES["exchange_failed"])
                    body = (
                        "<!doctype html><html lang=\"es\"><meta charset=\"utf-8\">"
                        "<title>Aleph · OAuth</title><body style=\"font:16px system-ui;"
                        "max-width:36rem;margin:12vh auto;padding:1.5rem;color:#17151e\">"
                        f"<h1>{title}</h1><p>{detail}</p>"
                        "<p>Ya puedes cerrar esta pestaña.</p></body></html>"
                    ).encode("utf-8")
                    self.send_response(200 if ok else 400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)

            try:
                server = _LoopbackHTTPServer((host, port), Handler)
            except OSError as exc:
                self._last = {
                    "state": "loopback_unavailable",
                    "message": f"No pude abrir localhost:{port}; cierra el proceso que usa ese puerto.",
                    "cause": "port_busy",
                }
                raise RuntimeError("loopback_port_busy") from exc

            authorize_url = build_authorize_url(
                cfg, client_id=client_id, redirect_uri=redirect_uri, state=csrf,
                code_challenge=challenge,
            )
            self._server = server
            self._flow = {
                "provider": provider,
                "owner": str(owner),
                "state": "awaiting_consent",
                "csrf": csrf,
                "verifier": verifier,
                "on_code": on_code,
                "stop_event": stop_event,
                "started_at": time.time(),
                "redirect_uri": redirect_uri,
            }
            self._last = {
                "provider": provider,
                "state": "awaiting_consent",
                "message": _MESSAGES["awaiting_consent"],
            }
            threading.Thread(target=server.serve_forever, name="aleph-oauth-loopback",
                             daemon=True).start()
            threading.Thread(target=self._timeout, args=(stop_event, float(timeout)),
                             name="aleph-oauth-timeout", daemon=True).start()
            return {
                "provider": provider,
                "state": "awaiting_consent",
                "message": _MESSAGES["awaiting_consent"],
                "authorize_url": authorize_url,
                "redirect_uri": redirect_uri,
            }

    def _shutdown_server(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()

    def _receive(self, *, state: str, code: str, error: str,
                 error_description: str) -> dict:
        with self._lock:
            flow = self._flow
            if not flow or flow.get("state") != "awaiting_consent":
                return {"accepted": False, "message": "Este callback ya no está activo."}
            # Un callback sin el secreto CSRF no consume el listener. El navegador legítimo
            # todavía puede volver después de ruido o sondeos ciegos contra localhost.
            if not state or not secrets.compare_digest(state, flow["csrf"]):
                return {"accepted": False, "message": _MESSAGES["bad_state"]}
            flow["stop_event"].set()
            if error:
                flow["state"] = "denied"
                self._last = {
                    "provider": flow["provider"], "state": "denied",
                    "message": error_description[:180] or _MESSAGES["denied"],
                    "cause": error[:80] or "access_denied",
                }
            elif not code:
                flow["state"] = "exchange_failed"
                self._last = {
                    "provider": flow["provider"], "state": "exchange_failed",
                    "message": "El proveedor volvió sin un código de autorización.",
                    "cause": "missing_code",
                }
            else:
                flow["state"] = "exchanging"
                self._last = {
                    "provider": flow["provider"], "state": "exchanging",
                    "message": _MESSAGES["exchanging"],
                }
                callback, verifier = flow["on_code"], flow["verifier"]
                accepted = True
        # El socket muere al RECIBIR la vuelta, antes del canje.
        self._shutdown_server()
        if "accepted" not in locals():
            return {"accepted": False, "message": self._last["message"]}
        threading.Thread(target=self._complete, args=(callback, code, verifier),
                         name="aleph-oauth-exchange", daemon=True).start()
        return {"accepted": True, "message": _MESSAGES["exchanging"]}

    def _complete(self, callback: Callable[[str, str], dict],
                  code: str, verifier: str) -> None:
        try:
            result = callback(code, verifier) or {}
        except Exception:
            result = {"state": "exchange_failed", "cause": "internal_error",
                      "message": _MESSAGES["exchange_failed"]}
        state = str(result.get("state") or "exchange_failed")
        public = {
            "provider": (self._flow or {}).get("provider"),
            "state": state,
            "message": str(result.get("message") or _MESSAGES.get(state)
                           or _MESSAGES["exchange_failed"])[:240],
        }
        for key in ("cause", "granted_scopes", "tools", "scope_source"):
            if key in result:
                public[key] = result[key]
        with self._lock:
            self._last = public
            if self._flow:
                self._flow["state"] = state
                self._flow.pop("csrf", None)
                self._flow.pop("verifier", None)
                self._flow.pop("on_code", None)

    def _timeout(self, stop_event: threading.Event, timeout: float) -> None:
        if stop_event.wait(max(1.0, timeout)):
            return
        with self._lock:
            if not self._flow or self._flow.get("state") != "awaiting_consent":
                return
            self._flow["state"] = "loopback_timeout"
            self._last = {
                "provider": self._flow["provider"], "state": "loopback_timeout",
                "message": _MESSAGES["loopback_timeout"], "cause": "timeout",
            }
        self._shutdown_server()

    def stop(self, reason: str = "listener_stopped") -> dict:
        """Corte explícito para shutdown y para la calibración roja."""
        with self._lock:
            if self._flow and self._flow.get("stop_event"):
                self._flow["stop_event"].set()
            provider = (self._flow or {}).get("provider")
            self._last = {
                "provider": provider, "state": reason,
                "message": _MESSAGES.get(reason, _MESSAGES["listener_stopped"]),
                "cause": reason,
            }
            if self._flow:
                self._flow["state"] = reason
        self._shutdown_server()
        return self.status()

    def status(self, *, owner: Optional[str] = None,
               provider: Optional[str] = None) -> dict:
        with self._lock:
            flow = self._flow or {}
            if owner is not None and str(flow.get("owner") or "") != str(owner):
                return {"state": "idle", "message": _MESSAGES["idle"]}
            if provider is not None and str(flow.get("provider") or "") != str(provider):
                return {"state": "idle", "message": _MESSAGES["idle"]}
            # Copia allowlisted: jamás csrf/verifier/code/callback.
            return dict(self._last)


__all__ = ["LoopbackFlowManager"]
