"""Límite de memoria del webhook público, sin depender de Postgres ni del SDK de Dodo."""

from __future__ import annotations

import base64
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[4]
for path in (REPO_ROOT / "platform", REPO_ROOT / "product" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.phase1 import payments_router, repo  # noqa: E402
from payments import base  # noqa: E402


WEBHOOK_SECRET = base64.b64encode(b"body-limit-webhook-secret-for-tests!!").decode()


class _Conn:
    def close(self):
        pass


class _Processor:
    nombre = "dodo"

    def __init__(self, expected: bytes):
        self.expected = expected
        self.calls = 0

    def verificar_webhook(self, raw: bytes, _headers: dict):
        self.calls += 1
        assert raw == self.expected
        return base.EventoVerificado(
            webhook_id="msg_body_limit",
            tipo="invoice.created",
            at=dt.datetime.now(dt.timezone.utc),
            payload={"ok": True},
        )


@pytest.fixture()
def route(monkeypatch):
    processors = []

    def install(expected: bytes):
        processor = _Processor(expected)
        processors.append(processor)
        monkeypatch.setattr(base, "get_procesador", lambda _name: processor)
        return processor

    monkeypatch.setattr(repo, "claim_webhook_event", lambda *_args, **_kwargs: False)
    app = FastAPI()
    app.include_router(payments_router.build_payments_router(lambda: _Conn(), rol="control"))
    return TestClient(app, raise_server_exceptions=False), install, processors


def test_rechaza_content_length_sobre_limite_antes_de_verificar(route):
    client, install, _ = route
    processor = install(b"nunca")

    response = client.post(
        "/v1/payments/webhook/dodo",
        content=b"x" * (payments_router._MAX_WEBHOOK_BODY_BYTES + 1),
    )

    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "webhook_body_demasiado_grande"
    assert processor.calls == 0


def test_rechaza_body_chunked_al_cruzar_limite(route):
    client, install, _ = route
    processor = install(b"nunca")
    chunk = b"x" * (payments_router._MAX_WEBHOOK_BODY_BYTES // 2 + 1)

    response = client.post(
        "/v1/payments/webhook/dodo",
        content=(piece for piece in (chunk, chunk)),
    )

    assert response.status_code == 413
    assert processor.calls == 0


def test_body_chunked_bajo_limite_conserva_bytes_y_ack_de_duplicado(route):
    client, install, _ = route
    pieces = (b'{"espacio": ', b' true, "texto": "a  b"}')
    expected = b"".join(pieces)
    processor = install(expected)

    response = client.post(
        "/v1/payments/webhook/dodo",
        content=(piece for piece in pieces),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "duplicate": True}
    assert processor.calls == 1


def test_webhook_dodo_firmado_bajo_limite_conserva_ack(route, monkeypatch):
    client, _, _ = route
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "noop-para-tests")
    monkeypatch.setenv("DODO_PAYMENTS_WEBHOOK_KEY", WEBHOOK_SECRET)
    monkeypatch.setenv("DODO_PAYMENTS_ENVIRONMENT", "test_mode")
    webhook_id = "msg_body_limit_firmado"
    timestamp = int(time.time())
    body = json.dumps({
        "type": "invoice.created",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data": {},
    }).encode()
    from standardwebhooks.webhooks import Webhook
    signature = Webhook(WEBHOOK_SECRET).sign(
        webhook_id,
        dt.datetime.fromtimestamp(timestamp, dt.timezone.utc),
        body.decode(),
    )

    response = client.post(
        "/v1/payments/webhook/dodo",
        content=body,
        headers={
            "webhook-id": webhook_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": signature,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "duplicate": True}


def test_procesador_desconocido_no_consume_el_body(route, monkeypatch):
    client, _, _ = route
    consumed = False

    def body():
        nonlocal consumed
        consumed = True
        yield b"x" * (payments_router._MAX_WEBHOOK_BODY_BYTES + 1)

    def unknown(_name):
        raise ValueError("unknown")

    monkeypatch.setattr(base, "get_procesador", unknown)
    response = client.post("/v1/payments/webhook/otro", content=body())

    assert response.status_code == 404
    assert consumed is False
