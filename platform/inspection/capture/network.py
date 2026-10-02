"""
capture/network.py — listener page.on(request/response) → HAR estructurado.

Captura TODA la red durante la demostración (el ruido y la señal). El emparejado
request↔response es por identidad del objeto Request de Playwright. Los headers
secretos se redactan al construir el CapturedRequest. El body de la response es
best-effort y SOLO para xhr/fetch chicas (la señal vive en el REQUEST, no acá).
"""
from __future__ import annotations

import json
import time
import urllib.parse
from typing import Optional

from inspection.models import CapturedRequest, redact_headers

_MAX_RESP_SNIPPET = 1500


def _parse_post(post_data: Optional[str], content_type: str):
    if not post_data:
        return None
    ct = (content_type or "").lower()
    if "application/json" in ct or post_data.lstrip().startswith(("{", "[")):
        try:
            return json.loads(post_data)
        except (json.JSONDecodeError, ValueError):
            pass
    if "application/x-www-form-urlencoded" in ct or ("=" in post_data and "&" in post_data):
        try:
            return {k: v[0] if len(v) == 1 else v
                    for k, v in urllib.parse.parse_qs(post_data, keep_blank_values=True).items()}
        except ValueError:
            pass
    return None


class NetworkRecorder:
    def __init__(self, capture_response_body: bool = True):
        self.capture_response_body = capture_response_body
        self._by_req: dict[object, CapturedRequest] = {}
        self._order: list[CapturedRequest] = []
        self._n = 0
        self._page = None
        self._h_req = None
        self._h_resp = None
        self._h_failed = None

    def attach(self, ctx_or_page) -> None:
        # acepta un AuthedContext (.on) o una Page directa (.on)
        self._page = getattr(ctx_or_page, "page", ctx_or_page)
        self._h_req = self._on_request
        self._h_resp = self._on_response
        self._h_failed = self._on_finished
        self._page.on("request", self._h_req)
        self._page.on("response", self._h_resp)
        self._page.on("requestfailed", self._h_failed)
        self._page.on("requestfinished", self._h_failed)

    def detach(self) -> None:
        if not self._page:
            return
        for event, h in (("request", self._h_req), ("response", self._h_resp),
                         ("requestfailed", self._h_failed), ("requestfinished", self._h_failed)):
            try:
                self._page.remove_listener(event, h)
            except Exception:
                pass

    def dump(self) -> list[CapturedRequest]:
        return list(self._order)

    # ── handlers ──
    def _on_request(self, request) -> None:
        try:
            self._n += 1
            parsed = urllib.parse.urlsplit(request.url)
            query = {k: v[0] if len(v) == 1 else v
                     for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
            headers = dict(request.headers or {})
            post = request.post_data
            cr = CapturedRequest(
                request_id=f"req-{self._n:03d}",
                method=request.method,
                url=request.url,
                host=parsed.netloc,
                path=parsed.path,
                query=query,
                resource_type=request.resource_type,
                request_headers=redact_headers(headers),
                post_data=post,
                post_data_json=_parse_post(post, headers.get("content-type", "")),
                started_at=time.time(),
            )
            self._by_req[request] = cr
            self._order.append(cr)
        except Exception:
            pass  # un fallo capturando jamás rompe la demostración

    async def _on_response(self, response) -> None:
        try:
            cr = self._by_req.get(response.request)
            if cr is None:
                return
            cr.status = response.status
            rh = dict(response.headers or {})
            cr.response_headers = redact_headers(rh)
            cr.response_mime = rh.get("content-type")
            cr.finished_at = time.time()
            if self.capture_response_body and cr.is_xhr:
                try:
                    body = await response.text()
                    cr.response_body_snippet = body[:_MAX_RESP_SNIPPET]
                except Exception:
                    pass
        except Exception:
            pass

    def _on_finished(self, request) -> None:
        try:
            cr = self._by_req.get(request)
            if cr and cr.finished_at is None:
                cr.finished_at = time.time()
        except Exception:
            pass
