"""
mcp_registry.py — cliente del REGISTRO PÚBLICO de MCPs + cache + override curado.

El RESOLVER (mcp_resolver.py) necesita, dado un nombre de servicio, ENCONTRAR el MCP que
ya existe. La fuente principal es el registro OFICIAL de Model Context Protocol:

    https://registry.modelcontextprotocol.io  —  GET /v0/servers?search=<q>  (paginado por
    cursor; API en freeze v0.1 pero EN PREVIEW: puede haber resets / caídas).

Es METADATA: cada server se mapea a su forma de correr — `remotes[]` (hosted, Streamable
HTTP) o `packages[]` (local: npm/pypi/oci) — y a CÓMO se configura la credencial
(`headers[]` en un remote, `environmentVariables[]` en un package). NO aloja el código.

Forma REAL de la respuesta (verificada en vivo 2026-06-22, schema 2025-12-11):
    {"servers":[{"server":{"name":"com.stripe/mcp","description":..,"title":..,"version":..,
        "repository":{"url":..,"source":"github"},
        "remotes":[{"type":"streamable-http","url":"https://mcp.stripe.com",
                    "headers":[{"name":"Authorization","value":"Bearer {key}",
                                "isSecret":true,"isRequired":true}]}],
        "packages":[{"registryType":"pypi","identifier":..,"transport":{"type":"stdio"},
                     "environmentVariables":[{"name":"AIRTABLE_API_KEY","isSecret":true,..}]}]},
      "_meta":{"io.modelcontextprotocol.registry/official":{"status":"active","isLatest":true,..}}}],
     "metadata":{"nextCursor":..,"count":N}}

Lo CLAVE para el matcher: `name` es un namespace REVERSE-DNS con ownership verificado por el
registro — `com.stripe/<x>` exige DNS de stripe.com, `io.github.<org>/<x>` está atado a esa
cuenta de GitHub. Esa es la señal anti-impostor más fuerte (ver mcp_matcher.py).

Cache + override:
  - CACHE (runtime, por-servicio): resoluciones que YA validaron → no dependemos de que el
    registro esté vivo en cada request + fallback graceful. NUNCA cachea la credencial.
  - OVERRIDE curado (versionado, chico): pin explícito servicio→server name. Es anti-impostor
    duro (si persona usuaria fija "stripe"→com.stripe/mcp, nadie con nombre parecido lo desplaza) y
    semilla offline. NO es la fuente — la fuente es el registro.

Stdlib pura (urllib + json). Cero red en import.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _raiz_de_recursos() -> Path:
    """Raíz de lo que VIAJA en el bundle. En dev es la raíz del árbol; congelado, `_MEIPASS`.

    ⚠️ [OBRA 6d] `parents[2]` NO SIRVE PARA LEER UN DATO EMPAQUETADO, y la razón es sutil:
    en el build `public` este módulo vive dentro del PYZ, así que su `__file__` es sintético
    (`<_MEIPASS>/inspection/mcp_registry.py`, una ruta que no existe en disco) y `parents[2]`
    cae en el **PADRE de `_MEIPASS`** — el TMPDIR del sistema. Medido en la `.app` instalada:
    buscaba `/private/var/folders/…/T/platform/inspection/data/curated_mcp_registry.json`.

    En `founder` no se nota: ahí `platform/inspection` viaja ENTERO como archivos
    (`_FORGE_TRAVELS`), el módulo existe en disco bajo `<_MEIPASS>/platform/inspection/` y
    `parents[2]` sí da `_MEIPASS`. La misma asimetría public/founder que la Obra 6a ya había
    identificado como causa raíz — se arregló que el archivo VIAJARA, no que el código lo
    ENCONTRARA, y el `CuradoAusenteError` de esa obra convirtió el fallo mudo en un 500 en
    todo el catálogo público.

    Ojo con el comentario de `_dir_datos` de acá abajo, que decía «bajo PyInstaller
    `_REPO_ROOT` cae DENTRO de `_MEIPASS`»: es falso, cae un nivel más arriba. Esa creencia
    es la que dejó pasar el bug. Queda corregida.
    """
    try:
        import aleph_paths
        return aleph_paths.resource_root()
    except Exception:                    # noqa: BLE001 — dev suelto sin aleph_paths
        return _REPO_ROOT


_CURATED_PATH = _raiz_de_recursos() / "platform" / "inspection" / "data" / "curated_mcp_registry.json"


# cache runtime (por-árbol, gitignored bajo product/backend/data como synth_belts)
def _dir_datos(nombre: str) -> Path:
    """`<data_root>/<nombre>` — el dir de datos del USUARIO, no el árbol.
    ⚠️ EL BUNDLE ES SÓLO LECTURA (CLAUDE.md · clase ya pagada en synth_belts, el pin
    del sello y la caché del resolver). Lo que se ESCRIBE va al dir de datos del usuario,
    nunca al bundle: bajo PyInstaller el árbol de recursos es un temp que se borra al cerrar,
    así que lo que se escriba ahí NO existe en el arranque siguiente.
    Cae al árbol sólo si `aleph_paths` no se puede importar (dev suelto): en frozen siempre
    resuelve, porque `aleph_paths` viaja en el bundle.
    """
    try:
        import aleph_paths
        return aleph_paths.data_root() / nombre
    except Exception:                    # noqa: BLE001
        return _REPO_ROOT / "product" / "backend" / "data" / nombre

_CACHE_DIR = _dir_datos("resolver_cache")

REGISTRY_BASE = "https://registry.modelcontextprotocol.io"
_SEARCH_PATH = "/v0/servers"
_OFFICIAL_META = "io.modelcontextprotocol.registry/official"
_UA = "puppet-mcp-resolver/1.0"

# TLD-ish primeros labels de un namespace reverse-DNS (com.stripe → vendor=stripe).
_KNOWN_HEADS = {"com", "io", "ai", "net", "org", "dev", "app", "co", "sh", "xyz", "cloud", "tools"}


class RegistryError(Exception):
    """El registro público no respondió / respondió algo no parseable."""


class CuradoAusenteError(Exception):
    """[OBRA 6a] El override CURADO no está adentro de un build congelado — DEFECTO DE BUILD.

    ⚠️ NO HEREDA DE `RegistryError`, y eso es lo único importante de esta clase. Quien
    atrapa `RegistryError` está diciendo «el registro público no contestó» y degrada a
    `registry_status:"unreachable"`. Si esta falla entrara por esa puerta, la app le diría
    al usuario que el catálogo público está caído cuando lo que pasó es que a NUESTRO
    artefacto le falta un archivo. Sería la mentira exacta que la regla T-3 prohíbe:
    inalcanzable ≠ inexistente, y ninguno de los dos es «se me perdió un archivo».
    """


# ── normalización de nombres ────────────────────────────────────────────────────

def normalize(s: str) -> str:
    """minúsculas, sin acentos, sin separadores → comparable. 'Air-Table' → 'airtable'."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "mcp"


# ── parseo del namespace reverse-DNS → vendor (la señal de autenticidad) ────────

def vendor_of(name: Any) -> dict[str, str]:
    """De `com.stripe/mcp` / `io.github.org/x` / `ai.smithery/x` extrae quién es el DUEÑO
    verificado del namespace. Devuelve {namespace, leaf, vendor, vendor_kind}.

    vendor_kind:
      'dns'        — namespace de dominio (com.stripe → dueño = stripe.com). Señal fuerte.
      'github_org' — io.github.<org> (verificado por la cuenta GitHub <org>).
      'unknown'    — no se pudo descomponer.
    El vendor es el label que, si coincide con el servicio pedido, prueba que el publicador
    ES el dueño real del servicio (no un impostor con nombre parecido).

    ACEPTA LAS TRES FORMAS que circulan por este módulo: el nombre suelto, un candidato de
    `search()` (plano, con `name`) y una entrada cruda del registro (`{"server": {...}}`).
    Antes sólo aceptaba el string y hacía `.strip()` a secas, así que pasarle lo que
    `search()` devuelve —el uso natural, y el único que importa— moría con
    `AttributeError: 'dict' object has no attribute 'strip'`. Eso dejaba el ANTI-IMPOSTOR
    inaplicable sobre resultados del registro, que es justo donde vive el impostor."""
    if isinstance(name, dict):
        name = name.get("name") or ((name.get("server") or {}).get("name")
                                    if isinstance(name.get("server"), dict) else None)
    name = (name or "").strip() if isinstance(name, str) else ""
    namespace, _, leaf = name.partition("/")
    labels = [l for l in namespace.split(".") if l]
    if len(labels) >= 3 and labels[0] == "io" and labels[1] == "github":
        return {"namespace": namespace, "leaf": leaf, "vendor": labels[2], "vendor_kind": "github_org"}
    if len(labels) >= 2 and labels[0] in _KNOWN_HEADS:
        # com.stripe → vendor=stripe ; ai.smithery → vendor=smithery
        return {"namespace": namespace, "leaf": leaf, "vendor": labels[1], "vendor_kind": "dns"}
    if len(labels) >= 2:
        return {"namespace": namespace, "leaf": leaf, "vendor": labels[1], "vendor_kind": "dns"}
    return {"namespace": namespace, "leaf": leaf, "vendor": labels[0] if labels else namespace,
            "vendor_kind": "unknown"}


# ── normalización de una entrada cruda del registro → candidato ─────────────────

def _candidate(entry: dict) -> Optional[dict]:
    """Aplana el registro sin perder el manifest que alimenta el escrutinio posterior."""
    server = (entry or {}).get("server") or {}
    name = server.get("name")
    if not name:
        return None
    meta = ((entry.get("_meta") or {}).get(_OFFICIAL_META)) or {}
    v = vendor_of(name)
    return {
        "name": name,
        "namespace": v["namespace"],
        "leaf": v["leaf"],
        "vendor": v["vendor"],
        "vendor_kind": v["vendor_kind"],
        "title": server.get("title") or "",
        "description": server.get("description") or "",
        "version": server.get("version") or "",
        "status": meta.get("status") or "",
        "is_latest": bool(meta.get("isLatest")),
        "repository": server.get("repository") or {},
        "remotes": server.get("remotes") or [],
        "packages": server.get("packages") or [],
        "schema": server.get("$schema") or "",
        "source": "registry",
        # La ingesta necesita conservar lo que el registro realmente declaró. Mantener el
        # envelope completo evita reconstruir (e inventar) permisos o requisitos después.
        "_manifest_raw": entry,
    }


# ── el cliente HTTP del registro (búsqueda) ─────────────────────────────────────

def _get(path: str, params: dict, timeout: float) -> dict:
    url = REGISTRY_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method="GET",
                                 headers={"Accept": "application/json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RegistryError(f"HTTP {e.code} del registro MCP")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RegistryError(f"registro MCP inalcanzable: {getattr(e, 'reason', e)}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RegistryError(f"respuesta no-JSON del registro MCP: {e}")


def search(query: str, *, limit: int = 30, max_pages: int = 3,
           timeout: float = 12.0) -> list[dict]:
    """Busca en el registro oficial por `?search=`. Devuelve candidatos normalizados.
    Pagina por cursor hasta max_pages. Levanta RegistryError si el registro no responde
    (el caller decide el fallback a cache/curado)."""
    q = (query or "").strip()
    if not q:
        return []
    out: list[dict] = []
    cursor: Optional[str] = None
    for _ in range(max(1, max_pages)):
        params: dict[str, Any] = {"search": q, "limit": min(max(1, limit), 100)}
        if cursor:
            params["cursor"] = cursor
        data = _get(_SEARCH_PATH, params, timeout)
        for entry in (data.get("servers") or []):
            c = _candidate(entry)
            if c:
                out.append(c)
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor or len(out) >= limit:
            break
    return out


def get_by_name(name: str, *, timeout: float = 12.0) -> Optional[dict]:
    """Trae UN server por su name exacto (para resolver un pin del curado/cache contra el
    registro vivo). Usa la búsqueda y filtra por name == . Devuelve el isLatest si hay varios."""
    cands = [c for c in search(name, limit=50, timeout=timeout) if c["name"] == name]
    if not cands:
        return None
    for c in cands:
        if c.get("is_latest"):
            return c
    return cands[0]


# ── override curado (versionado, chico) ─────────────────────────────────────────

def load_curated() -> dict:
    """Lee el override curado versionado. Forma:
        {"services": {"stripe": {"pin": "com.stripe/mcp", "aliases": ["stripe payments"]}, ...}}
    `pin` fija el server name canónico (anti-impostor duro).

    ──────────────────────────────────────────────────────────────────────────────────────
    [OBRA 6a] FALLO VISIBLE, JAMÁS MUDO — y la asimetría es a propósito:

      · EN DEV (suelto), si falta el archivo → `{}` en silencio. Es una condición legítima:
        un árbol puede no tener el override curado y todo lo demás sigue funcionando.
      · EN UN BUILD CONGELADO, si falta el archivo → **GRITA** (`CuradoAusenteError`). Ahí
        no es una condición: es un DEFECTO DEL ARTEFACTO. Este `except` que devolvía `{}`
        es exactamente lo que hizo que `pinned_servers()` valiera 8 en el repo y **0** en
        `/Applications/Aleph.app` sin que nadie se enterara — ningún ✓ oficial existía y el
        anti-impostor duro por pin estaba muerto en producción (medido, Obra 5).

    Esto es el BACKSTOP, no la defensa. La defensa es `qa/gate_bundle_aleph.py`, que se
    niega a certificar un build al que le falte un dato declarado en `bundle_datos.py`. Si
    esta excepción llega a levantarse alguna vez, es que un artefacto salió sin pasar por el
    gate — y entonces sí queremos el ruido, no un `{}` que disimula.
    """
    congelado = bool(getattr(sys, "frozen", False))
    try:
        return json.loads(_CURATED_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if congelado:
            raise CuradoAusenteError(
                f"el override curado no viajó en este build: falta {_CURATED_PATH}. "
                f"Es un defecto del artefacto (ver deploy/fase4/bundle_datos.py), no una "
                f"caída del registro público.") from None
        return {}
    except Exception as exc:  # noqa: BLE001 — ilegible/corrupto
        if congelado:
            raise CuradoAusenteError(
                f"el override curado del build es ilegible ({exc}). Defecto del artefacto."
            ) from None
        return {}


def curated_entry(service: str) -> Optional[dict]:
    """Devuelve el override curado de un servicio (por nombre o alias), o None."""
    data = load_curated()
    services = data.get("services") or {}
    key = normalize(service)
    for sname, spec in services.items():
        names = [sname] + list((spec or {}).get("aliases") or [])
        if any(normalize(n) == key for n in names):
            return {"service": sname, **(spec or {})}
    return None


def pinned_servers() -> dict[str, str]:
    """Índice inverso ``{server_name: servicio}`` de los pins declarados.

    Ésta es la única fuente del sello oficial. Un namespace DNS/GitHub sólo identifica al
    publicador; no prueba por sí mismo que la pieza sea la oficial del producto buscado.
    """
    pins: dict[str, str] = {}
    for service, spec in (load_curated().get("services") or {}).items():
        pin = (spec or {}).get("pin") if isinstance(spec, dict) else None
        if isinstance(pin, str) and pin.strip():
            pins[pin.strip()] = str(service)
    return pins


# ── cache de resoluciones validadas (runtime, NUNCA la credencial) ──────────────

def _cache_path(service: str) -> Path:
    return _CACHE_DIR / f"{slugify(service)}.json"


def cache_get(service: str, *, max_age_s: float = 7 * 24 * 3600) -> Optional[dict]:
    """Resolución cacheada de un servicio (server + config de credencial, SIN secreto), o
    None si no hay / venció. Sirve de fallback si el registro se cayó."""
    p = _cache_path(service)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ts = rec.get("cached_at", 0)
    if max_age_s and (time.time() - ts) > max_age_s:
        rec["stale"] = True
    return rec


def cache_put(service: str, resolved: dict) -> Path:
    """Guarda una resolución VALIDADA. `resolved` NO debe contener la credencial — solo el
    server elegido + cómo correrlo + dónde va la credencial (no su valor)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {**resolved, "service": service, "cached_at": time.time()}
    p = _cache_path(service)
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


__all__ = [
    "RegistryError", "REGISTRY_BASE",
    "normalize", "slugify", "vendor_of",
    "search", "get_by_name",
    "load_curated", "curated_entry", "pinned_servers",
    "cache_get", "cache_put",
]
