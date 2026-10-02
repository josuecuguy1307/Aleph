"""Per-run authenticated browser proxy: resolve, validate and dial one IP snapshot.

Chromium's URL guard remains an independent first check. This proxy makes the
connection-time decision authoritative, including CONNECT, redirects and assets.
"""
from __future__ import annotations

import base64
import hmac
import ipaddress
import select
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from browser import loopback

_MAX_BODY = 10 * 1024 * 1024
_MAX_HEADER = 64 * 1024


class ProxyDenied(Exception):
    pass


def resolve_and_dial(url: str, *, run_id: str, resolver=socket.getaddrinfo,
                     connector=socket.create_connection):
    """Resolve once; reject mixed/private answers; dial a numeric vetted sockaddr."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProxyDenied("invalid target")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in addresses))
    except (OSError, ValueError) as exc:
        raise ProxyDenied("DNS unavailable") from exc
    verdict = loopback.permitir_resueltos(url, run_id=run_id, ips=ips)
    if not verdict.ok:
        raise ProxyDenied(verdict.causa)
    # No hostname is ever passed to connector: it cannot independently re-resolve.
    for ip in ips:
        try:
            return connector((str(ip), port), timeout=15)
        except OSError:
            continue
    raise ProxyDenied("connect unavailable")


class PinnedProxy:
    def __init__(self, run_id: str):
        if not run_id:
            raise ValueError("run_id required")
        self.run_id = run_id
        self.username = secrets.token_urlsafe(24)
        self.password = secrets.token_urlsafe(32)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            rbufsize = 64 * 1024

            def log_message(self, *_args):
                pass  # URLs may contain secrets; never log targets.

            def _authenticated(self):
                raw = self.headers.get("Proxy-Authorization", "")
                expected = "Basic " + base64.b64encode(
                    f"{proxy.username}:{proxy.password}".encode()).decode("ascii")
                if hmac.compare_digest(raw, expected):
                    return True
                self.send_response(407)
                self.send_header("Proxy-Authenticate", 'Basic realm="Aleph browser"')
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return False

            def _deny(self):
                self.send_error(403, "Browser destination denied")
                self.close_connection = True

            def do_CONNECT(self):
                if not self._authenticated():
                    return
                try:
                    authority = urlsplit("https://" + self.path)
                    if not authority.hostname or not authority.port or authority.username:
                        raise ProxyDenied("invalid CONNECT authority")
                    upstream = resolve_and_dial(f"https://{self.path}/", run_id=proxy.run_id)
                except (ValueError, ProxyDenied):
                    self._deny()
                    return
                with upstream:
                    self.send_response(200, "Connection Established")
                    self.end_headers()
                    self._tunnel(upstream)

            def _tunnel(self, upstream):
                pair = (self.connection, upstream)
                for sock in pair:
                    sock.settimeout(30)
                while True:
                    try:
                        ready, _, _ = select.select(pair, [], [], 30)
                        if not ready:
                            break
                        for sock in ready:
                            chunk = sock.recv(65536)
                            if not chunk:
                                return
                            (upstream if sock is self.connection else self.connection).sendall(chunk)
                    except OSError:
                        return

            def _forward(self):
                if not self._authenticated():
                    return
                try:
                    target = urlsplit(self.path)
                    if target.scheme != "http" or not target.hostname or target.username:
                        raise ProxyDenied("absolute HTTP URL required")
                    if self.headers.get("Transfer-Encoding"):
                        raise ProxyDenied("chunked upload not supported")
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > _MAX_BODY:
                        raise ProxyDenied("body too large")
                    headers = [(k, v) for k, v in self.headers.items()
                               if k.lower() not in ("proxy-authorization", "proxy-connection",
                                                    "connection", "keep-alive", "transfer-encoding")]
                    if sum(len(k) + len(v) for k, v in headers) > _MAX_HEADER:
                        raise ProxyDenied("headers too large")
                    upstream = resolve_and_dial(self.path, run_id=proxy.run_id)
                except (ValueError, ProxyDenied):
                    self._deny()
                    return
                with upstream:
                    path = target.path or "/"
                    if target.query:
                        path += "?" + target.query
                    upstream.sendall(f"{self.command} {path} HTTP/1.1\r\n".encode("ascii"))
                    for key, value in headers:
                        upstream.sendall(f"{key}: {value}\r\n".encode("latin-1"))
                    upstream.sendall(b"Connection: close\r\n\r\n")
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            return
                        upstream.sendall(chunk)
                        remaining -= len(chunk)
                    while True:
                        chunk = upstream.recv(65536)
                        if not chunk:
                            break
                        self.connection.sendall(chunk)
                self.close_connection = True

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _forward

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="aleph-pinned-browser-proxy", daemon=True)

    @property
    def server(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
