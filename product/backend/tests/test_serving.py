"""4.4.0 serving=C — el backend sirve el FRONTEND (design/) además de /v1, same-origin.
[Casa 2 · Fase 4] Portado de product/app/serve.py: en el .exe el backend es el único proceso.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
for p in (_REPO / "product" / "backend", _REPO / "platform", _REPO / "platform" / "db"):
    sys.path.insert(0, str(p))
from app.main import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

_c = TestClient(app)


def test_root_redirects_to_home():
    r = _c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/Home.dc.html"


def test_backend_serves_frontend_and_capa0_renderers():
    assert _c.get("/Home.dc.html").status_code == 200               # el frontend
    assert _c.get("/vendor/marked.min.js").status_code == 200       # renderer Capa 0 (markdown)
    assert _c.get("/vendor/xlsx.full.min.js").status_code == 200    # renderer Capa 0 (xlsx)


def test_api_not_shadowed_by_staticfiles():
    r = _c.get("/v1/atoms/catalog")
    assert r.status_code == 200 and "atoms" in r.text               # /v1 matchea antes del mount


def test_cuarto_redirects_to_pixi():
    r = _c.get("/Cuarto.dc.html", follow_redirects=False)
    assert r.status_code in (302, 307) and "cuarto.pixi.html" in r.headers["location"]
