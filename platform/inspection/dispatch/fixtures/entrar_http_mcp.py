"""Servidor MCP HTTP local para probar keyless y 401 sin tocar la red externa."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def build_server(host: str, port: int, observations: list[dict]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802 — contrato de BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            observations.append({
                "path": self.path,
                "headers": {str(k): str(v) for k, v in self.headers.items()},
                "body": raw.decode("utf-8", "replace"),
            })
            if self.path == "/needs-key":
                body = json.dumps({"error": "credential required"}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            request = json.loads(raw or b"{}")
            if "id" not in request:  # notifications/initialized
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "entrar-http", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": [{
                    "name": "http_ping",
                    "description": "señal HTTP local",
                    "inputSchema": {"type": "object", "properties": {}},
                }]}
            else:
                result = {"content": [{"type": "text", "text": "pong"}]}
            body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)
