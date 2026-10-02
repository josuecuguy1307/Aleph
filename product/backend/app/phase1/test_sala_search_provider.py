"""Optional external SearXNG provider: explicit configuration and fail-closed use."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT / "platform", ROOT / "product/backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.phase1 import authz_http, sala_search_provider as provider  # noqa: E402
from app.phase1.sala_busqueda_router import build_sala_busqueda_router  # noqa: E402
from app.phase1.sala_research_router import build_sala_research_router  # noqa: E402
from workspaces import memoria, pack  # noqa: E402


@pytest.fixture
def search_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/search?q=aleph-provider-check&format=json":
                self.send_error(404)
                return
            body = json.dumps({"query": "aleph-provider-check", "results": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_external_provider_round_trip(tmp_path, monkeypatch, search_server):
    monkeypatch.setattr(memoria._ap, "user_data_dir", lambda: tmp_path)
    monkeypatch.delenv("ALEPH_SEARXNG_URL", raising=False)
    monkeypatch.setattr(authz_http, "owner_or_401", lambda _authorization, **_kw: "alice")
    stops = []
    monkeypatch.setattr(pack, "apagar", lambda ws, **_kw: stops.append(ws) or 0)
    app = FastAPI()
    app.include_router(build_sala_busqueda_router(get_conn=lambda: None))
    app.include_router(build_sala_research_router(get_conn=lambda: None))
    client = TestClient(app)

    assert client.get("/v1/sala/search-provider").json()["configured"] is False
    missing = client.post("/v1/sala/buscar", json={"query": "test"})
    assert missing.status_code == 428
    assert missing.json()["detail"]["error"] == "search_provider_required"
    deep_missing = client.post("/v1/sala/investigar", json={"query": "test"})
    assert deep_missing.status_code == 428
    assert deep_missing.json()["detail"]["error"] == "search_provider_required"

    bad = client.put("/v1/sala/search-provider", json={"url": search_server + "/wrong"})
    assert bad.status_code == 422
    assert client.get("/v1/sala/search-provider").json()["configured"] is False

    connected = client.put("/v1/sala/search-provider", json={"url": search_server})
    assert connected.status_code == 200
    assert connected.json()["configured"] is True
    assert client.get("/v1/sala/search-provider").json()["configured"] is True
    assert memoria.como_quedo("alice", "sala_busqueda")["deltas"]["searxng_url"] == search_server
    assert provider.pack_meta({"pack_env": {"KEEP": "yes"}}, "alice")["pack_env"] == {
        "KEEP": "yes", "ALEPH_SEARXNG_URL": search_server,
    }
    assert memoria.como_quedo("bob", "sala_busqueda") == {}
    assert stops == ["sala_busqueda", "sala_research"]

    disconnected = client.delete("/v1/sala/search-provider")
    assert disconnected.status_code == 200
    assert disconnected.json()["configured"] is False
    assert client.post("/v1/sala/buscar", json={"query": "test"}).status_code == 428
    assert client.post("/v1/sala/investigar", json={"query": "test"}).status_code == 428

    memoria.recordar("alice", "sala_busqueda", deltas={"searxng_url": "http://127.0.0.1:1"})
    offline = client.get("/v1/sala/search-provider").json()
    assert offline["configured"] is False
    assert offline["reason"]
    assert client.post("/v1/sala/investigar", json={"query": "test"}).json()["detail"]["error"] == "search_provider_unreachable"


def test_invalid_and_offline_provider(tmp_path, monkeypatch, search_server):
    monkeypatch.setattr(memoria._ap, "user_data_dir", lambda: tmp_path)
    for url in ("file:///etc/passwd", "http://a:b@localhost:80", "http://169.254.169.254/"):
        with pytest.raises(provider.SearchProviderError):
            provider.normalize_url(url)
    memoria.recordar("alice", "sala_busqueda", deltas={"searxng_url": search_server})
    assert provider.pack_meta({}, "alice")["pack_env"]["ALEPH_SEARXNG_URL"] == search_server
    memoria.recordar("alice", "sala_busqueda", deltas={"searxng_url": "http://127.0.0.1:1"})
    with pytest.raises(provider.SearchProviderError) as caught:
        provider.pack_meta({}, "alice")
    assert caught.value.code == "search_provider_unreachable"
