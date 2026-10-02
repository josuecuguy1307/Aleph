"""fase4_freeze_probe.py — CASA 2 · Fase 4 · 4.0 · el freeze que falla rápido.

Sonda READ-ONLY de la hipótesis B5∪B6: bajo PyInstaller, belts/catalog NO viajan
(datas ausentes) y `parents[N]` mide mal en `_MEIPASS` → el discovery devuelve 0.
Entregable = el ROJO reproducible + el modo de fallo exacto. NO es un fix.

Corre igual congelado (`.exe`/onedir) o suelto (`python fase4_freeze_probe.py`) para
contrastar dev-verde vs frozen-rojo. Fuerza `ALEPH_ROLE=client` (el rol del cliente).
"""
import os
import sys
import pathlib
import traceback

os.environ.setdefault("ALEPH_ROLE", "client")


def P(k, v=""):
    print(f"[probe] {k}: {v}", flush=True)


P("frozen", getattr(sys, "frozen", False))
P("_MEIPASS", getattr(sys, "_MEIPASS", None))
P("sys.executable", sys.executable)
P("cwd", os.getcwd())
P("PUPPET_BELTS", os.environ.get("PUPPET_BELTS") or "(unset)")

# ── Probe A · catálogo (iterdir sobre catalog/templates; catalog.py parents[3]) ──
try:
    from app import catalog
    root = catalog.CATALOG_ROOT
    P("A.CATALOG_ROOT", str(root))
    P("A.CATALOG_ROOT.exists", root.exists())
    # Discovery directo (iterdir sobre catalog/templates/<nicho>/<template>) — mismo
    # camino que catalog.py, sin depender del nombre de la función.
    nichos, total = 0, 0
    if root.exists():
        for nd in sorted(root.iterdir()):
            if nd.is_dir():
                nichos += 1
                total += sum(1 for t in nd.iterdir() if t.is_dir())
    P("A.catalog_nichos", nichos)
    P("A.catalog_templates_total", total)
except Exception:  # noqa: BLE001
    P("A.catalog PROBE FAILED")
    traceback.print_exc()

# ── Probe B · belts root + rglob (idiom de atoms_router; parents[4]) ──
try:
    from app.phase1 import atoms_router
    bp = pathlib.Path(atoms_router._belts_root())
    P("B._belts_root", str(bp))
    P("B._belts_root.exists", bp.exists())
    cnt = len(list(bp.rglob("*.mcp.json"))) if bp.exists() else -1
    P("B.mcp_json_count", cnt)
except Exception:  # noqa: BLE001
    P("B.atoms_router PROBE FAILED")
    traceback.print_exc()

# ── Probe C · endpoints REALES vía TestClient (/v1/atoms/catalog = vitrina agregada) ──
_app = None
try:
    from app.main import app as _app  # noqa: F401
    P("C.app_import", "OK")
except Exception:  # noqa: BLE001
    P("C.app_import FAILED (no se puede sondear el endpoint)")
    traceback.print_exc()

if _app is not None:
    try:
        from starlette.testclient import TestClient
        client = TestClient(_app)
        for path in ("/v1/atoms/catalog", "/v1/belts/cards?ref=catalog/belts/finanzas.md"):
            try:
                r = client.get(path)
                n = None
                try:
                    j = r.json()
                    if isinstance(j, list):
                        n = len(j)
                    elif isinstance(j, dict):
                        for key in ("cards", "atoms", "results", "items", "templates"):
                            if isinstance(j.get(key), list):
                                n = len(j[key])
                                break
                except Exception:  # noqa: BLE001
                    pass
                P(f"C GET {path}", f"status={r.status_code} bytes={len(r.text)} items={n} head={r.text[:160]!r}")
            except Exception as e:  # noqa: BLE001
                P(f"C GET {path} EXC", repr(e))
    except Exception:  # noqa: BLE001
        P("C.TestClient PROBE FAILED")
        traceback.print_exc()

# ── Probe D · serving=C · el backend sirve el FRONTEND (Home + Capa 0 assets) ──
if _app is not None:
    try:
        from starlette.testclient import TestClient
        _c = TestClient(_app)
        for path in ("/", "/Home.dc.html", "/vendor/marked.min.js", "/vendor/xlsx.full.min.js"):
            r = _c.get(path, follow_redirects=False)
            loc = r.headers.get("location")
            P(f"D GET {path}", f"status={r.status_code} {loc or (str(len(r.content)) + 'B')}")
    except Exception:  # noqa: BLE001
        P("D.serving PROBE FAILED")
        traceback.print_exc()

# ── Probe E · el catch-all de serving NO shadowea los 404 de la API ──
# El mount('/') es _FrontendStatic: un método ≠ GET/HEAD a un path SIN router debe dar
# **404 nativo**, no el **405** de StaticFiles (regresión de test_espacios ×3 con serving=C).
# Guarda de regresión CONGELADA del fix 4.4.0.
if _app is not None:
    try:
        from starlette.testclient import TestClient
        _e = TestClient(_app)
        checks = [
            ("POST", "/espacios/no-existe/mensajes", 404),
            ("POST", "/espacios/no-existe/aprobaciones/g1", 404),
            ("PUT", "/whatever/random", 404),
            ("GET", "/no-such-file-xyz.html", 404),  # GET a archivo inexistente = 404 de StaticFiles
        ]
        for method, path, want in checks:
            r = _e.request(method, path, json={"x": 1} if method != "GET" else None)
            ok = "OK" if r.status_code == want else "**MISMATCH**"
            P(f"E {method} {path}", f"status={r.status_code} want={want} {ok}")
    except Exception:  # noqa: BLE001
        P("E.no-shadow PROBE FAILED")
        traceback.print_exc()

P("DONE")
