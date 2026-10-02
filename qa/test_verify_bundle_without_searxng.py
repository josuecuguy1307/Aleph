"""The release absence gate catches server payloads but permits API clients."""
from __future__ import annotations

from pathlib import Path

from qa.verify_bundle_without_searxng import verify


def test_bundle_absence_gate(tmp_path: Path):
    app = tmp_path / "Aleph.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_text("test")
    client = app / "Contents/Resources/third_party/vane/src/lib/searxng.ts"
    client.parent.mkdir(parents=True)
    client.write_text("// optional API client")
    assert verify(app) == []

    server = app / "Contents/Frameworks/platform/sala/busqueda/searxng/lib/searx/webapp.py"
    server.parent.mkdir(parents=True)
    server.write_text("# AGPL server")
    assert verify(app)


def test_spec_never_declares_server_payload():
    spec = Path(__file__).resolve().parents[1] / "deploy/fase4/aleph_sidecar.spec"
    source = spec.read_text()
    assert "_SEARXNG_LIB" not in source
    assert '"third_party/vane/searxng"' not in source
    assert '"platform/sala/busqueda/searxng/lib"' not in source
