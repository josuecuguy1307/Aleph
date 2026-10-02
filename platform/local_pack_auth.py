"""Frontera HTTP común para packs costosos que sólo acepta al sidecar padre."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

MAX_BODY = 128 * 1024


def _secret() -> str:
    path = Path(os.environ.get("ALEPH_PACK_INTERNAL_CAP_FILE", ""))
    try:
        if not path.is_file() or path.is_symlink():
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def guard_post(handler, *, max_body: int = MAX_BODY) -> bool:
    """Rechaza antes de leer cuerpo. `/health` sigue siendo la única ruta pública."""
    def reject(status: int, error: str) -> bool:
        data = json.dumps({"error": error}).encode()
        handler.close_connection = True
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(data)
        return False

    port = str(os.environ.get("ALEPH_PACK_PORT") or "").strip()
    if handler.headers.get("Host", "").lower() != f"127.0.0.1:{port}":
        return reject(403, "local_host_required")
    if handler.headers.get("Origin"):
        return reject(403, "origin_forbidden")
    if handler.headers.get("Sec-Fetch-Site", "").lower() in ("cross-site", "same-site"):
        return reject(403, "cross_site_forbidden")
    if handler.headers.get("Transfer-Encoding"):
        return reject(400, "transfer_encoding_forbidden")
    lengths = handler.headers.get_all("Content-Length") or []
    if len(lengths) != 1:
        return reject(411, "content_length_required")
    try:
        length = int(lengths[0])
    except ValueError:
        return reject(400, "content_length_invalid")
    if length < 0 or length > max_body:
        return reject(413, "body_too_large")
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return reject(415, "json_required")
    expected = _secret()
    auth = handler.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return reject(401, "pack_capability_required")
    return True
