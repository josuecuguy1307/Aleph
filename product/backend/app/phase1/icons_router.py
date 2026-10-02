"""
icons_router.py — GET /v1/icons/{slug} : la CARA de cada servicio conectable (ticket 8).

Pipeline: slug → dominio (catalog/brand_domains.json, mapa CURADO — jamás input del
usuario, anti-SSRF por construcción) → snapshot empaquetado en `catalog/brand_icons`
→ favicon cacheado en el área de datos ESCRIBIBLE del runtime
(`aleph_paths.data_root()/brand_icons`) → FileResponse.

Doctrina (legal / marca):
  - El logo se sirve INTACTO (bytes tal cual los publica el servicio; cero edición).
  - Uso nominativo: identifica el servicio al que la pieza SE CONECTA; el copy de las
    superficies dice "conecta con X", nunca "oficial de X".
  - TAKEDOWN: "blocked": true en brand_domains.json → 404 + purga del cache → toda
    superficie cae al fallback genérico (iniciales + color). Sin deploy de código.
  - Custom/construidos (Motor B) NO están en el mapa → 404 → íconos genéricos propios.

Nunca un fetch en vivo si existe asset empaquetado. Para servicios sin snapshot, el
primer GET puebla el cache (una vez); los fallos se negativa-cachean (.miss con TTL)
para no martillar la red. Sin red (dev offline / harness sin backend) el endpoint
degrada honesto a 404 y el front dibuja el fallback — ninguna superficie se rompe.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

# El mapa es recurso INMUTABLE del artefacto; el cache es dato MUTABLE persistente.
# Import guardado porque algunos tests importan este router sin pasar por app.main.
try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_CATALOG_ROOT = _ap.resource_root() / "catalog"
_MAP_PATH = _CATALOG_ROOT / "brand_domains.json"
_BUNDLED_DIR = _CATALOG_ROOT / "brand_icons"


def _cache_dir() -> Path:
    """Cache escribible. En cliente vive fuera de `_MEIPASS`; en control conserva
    `product/backend/data/brand_icons` mediante el contrato role-aware de data_root()."""
    return _ap.data_root() / "brand_icons"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-\.]{0,63}$")
_MISS_TTL_S = 6 * 3600          # reintento de un favicon caído: cada 6 h, no por render
_FETCH_TIMEOUT_S = 6
_MAX_BYTES = 300_000            # un favicon real pesa KBs; más que esto es sospechoso

# El proveedor de favicon es HOST FIJO; el único dato variable (domain) sale del mapa
# curado. 64px cubre la cara más grande que dibujamos (36px CSS @2x).
_FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=64"

_map_cache: dict = {"mtime": None, "data": None}


def _load_map() -> dict:
    """brand_domains.json con cache por mtime (editar el JSON aplica sin reiniciar)."""
    try:
        mtime = _MAP_PATH.stat().st_mtime
    except OSError:
        return {}
    if _map_cache["mtime"] != mtime:
        try:
            _map_cache["data"] = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
            _map_cache["mtime"] = mtime
        except (json.JSONDecodeError, OSError):
            return _map_cache["data"] or {}
    return _map_cache["data"] or {}


def _resolve(slug: str) -> Optional[dict]:
    """slug (server o connector, o alias) → entrada {domain, blocked?} del mapa curado."""
    found = _resolve_with_slug(slug)
    return found[1] if found else None


def _resolve_with_slug(slug: str) -> Optional[tuple[str, dict]]:
    """slug o alias → (slug canónico, entrada). Un alias sirve el mismo asset/cache."""
    domains = (_load_map().get("domains") or {})
    if slug in domains:
        return slug, domains[slug]
    for canonical, entry in domains.items():
        if slug in (entry.get("aliases") or []):
            return canonical, entry
    return None


def _bundled_icon(slug: str) -> Optional[Path]:
    """Snapshot inmutable que viaja con el artefacto. No depende de red ni de cache."""
    png = _BUNDLED_DIR / f"{slug}.png"
    try:
        if png.is_file() and png.stat().st_size > 0:
            return png
    except OSError:
        return None
    return None


def _fetch_favicon(domain: str, dest: Path) -> bool:
    """Trae el favicon UNA vez y lo cachea. True si quedó un archivo servible."""
    url = _FAVICON_URL.format(domain=urllib.parse.quote(domain, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aleph-icon-cache/1.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            data = r.read(_MAX_BYTES + 1)
        if not ctype.startswith("image/") or not data or len(data) > _MAX_BYTES:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return True
    except Exception:
        return False


def build_icons_router() -> APIRouter:
    router = APIRouter(prefix="/v1/icons", tags=["icons"])

    @router.get("")
    def manifest():
        """Los slugs CONOCIDOS (con dominio curado y sin takedown). El front decide
        sincrónicamente logo-real vs genérico sin disparar 404s por pieza."""
        domains = (_load_map().get("domains") or {})
        known: list[str] = []
        for slug, entry in domains.items():
            if entry.get("blocked"):
                continue
            known.append(slug)
            known.extend(entry.get("aliases") or [])
        return {"known": sorted(known)}

    @router.get("/{slug}")
    def icon(slug: str):
        slug = (slug or "").lower()
        if not _SLUG_RE.match(slug):
            return JSONResponse({"error": "bad_slug"}, status_code=404)
        found = _resolve_with_slug(slug)
        entry = found[1] if found else None
        canonical = found[0] if found else slug
        cache_dir = _cache_dir()
        png = cache_dir / f"{canonical}.png"
        if entry is None or entry.get("blocked"):
            # takedown: purgar lo cacheado para que el fallback sea inmediato
            if entry is not None and entry.get("blocked"):
                png.unlink(missing_ok=True)
            return JSONResponse({"error": "unknown_service"}, status_code=404)
        bundled = _bundled_icon(canonical)
        if bundled is not None:
            return FileResponse(
                bundled, media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400",
                         "X-Aleph-Icon-Source": "bundled"},
            )
        if png.exists():
            return FileResponse(
                png, media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400",
                         "X-Aleph-Icon-Source": "cache"},
            )
        if not png.exists():
            miss = cache_dir / f"{canonical}.miss"
            if miss.exists() and (time.time() - miss.stat().st_mtime) < _MISS_TTL_S:
                return Response(status_code=404, headers={"Cache-Control": "public, max-age=300"})
            if not _fetch_favicon(entry.get("domain", ""), png):
                cache_dir.mkdir(parents=True, exist_ok=True)
                miss.touch()
                return Response(status_code=404, headers={"Cache-Control": "public, max-age=300"})
            miss.unlink(missing_ok=True)
        return FileResponse(
            png, media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400",
                     "X-Aleph-Icon-Source": "cache"},
        )

    return router
