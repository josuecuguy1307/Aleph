"""
library/fingerprint.py — la HUELLA (host→servicio→familia). PURO y OFFLINE
(solo stdlib): la CLAVE de índice del almacén §8 y la base de la reinyección.

La huella resuelve en orden de fuerza (host→servicio→familia, la cadena que la
directiva nombra):

  1. resolved  — el peldaño B resolvió una familia conocida (mcp_resolver), con
                 anti-impostor por namespace DNS. La más fuerte. `resolved:<name>`.
  2. doc       — el doc autodescriptivo (peldaño A) trae `info.title` + versión.
                 Esto identifica software SELF-HOSTED (Odoo/Strapi/Supabase) donde
                 el HOST varía por instancia pero el doc NO. `doc:<title>@<major>`.
  3. host      — el SLD del host (APIs single-instance: AlphaVantage/TMDB).
                 `host:<sld>`.

`family_id` (la clave) y `lookup_keys` (lo que la reinyección consulta) comparten
los MISMOS formateadores (`resolved_key`/`doc_key`/`host_key`) → una sola fuente de
verdad: lo que se captura bajo una clave se encuentra bajo esa misma clave.

NO importa strategy/* ni loop/* (frontera + pureza): replica las ~6 líneas de
`_service_from_host` de strategy/rungs en vez de depender de su símbolo privado.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Sequence
from urllib.parse import urlparse

# subdominios de "API" a descartar antes de quedarnos con el SLD (mismo criterio
# que strategy/rungs._service_from_host — replicado para no acoplarse a un privado).
_API_SUBDOMAINS = ("api", "www", "app", "rest", "data", "cloud", "v1", "v2", "v3")

# un segmento de path que parece un ID concreto (no parte de la FORMA de la familia):
# dígitos puros, hash hex largo, o uuid. Se normaliza a `{}` para que `/things/42` y
# `/things/99` colapsen al MISMO template → la huella es de la FAMILIA, no la instancia.
_ID_SEG = re.compile(r"^(\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F-]{16,})$")


def host_sld(base_url: str) -> str:
    """host → SLD, tirando subdominios de API y el TLD. IPs se devuelven enteras
    (no tienen SLD significativo). api.themoviedb.org → themoviedb."""
    host = (urlparse(base_url).hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    if parts and all(p.isdigit() for p in parts):     # IP literal (127.0.0.1) → entera
        return host
    while parts and parts[0] in _API_SUBDOMAINS:
        parts = parts[1:]
    if len(parts) >= 2:
        return parts[-2]                               # SLD
    return parts[0] if parts else host


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return out.strip("-") or "x"


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _major(version: str) -> str:
    """'3.0.0'→'3' · 'swagger-2.0'→'2' · 'v2'→'2' · '' → ''."""
    m = re.search(r"(\d+)", str(version or ""))
    return m.group(1) if m else ""


def normalize_template(path: str) -> str:
    """Path → template family-relative: segmentos que parecen IDs concretos → `{}`,
    los placeholders `{id}` ya presentes → `{}`, resto en minúsculas. Sin query."""
    p = (path or "/").split("?")[0]
    if not p.startswith("/"):
        p = "/" + p
    segs = p.split("/")
    norm = []
    for s in segs:
        if not s:
            norm.append(s)
        elif s.startswith("{") and s.endswith("}"):
            norm.append("{}")
        elif _ID_SEG.match(s):
            norm.append("{}")
        else:
            norm.append(s.lower())
    return "/".join(norm) or "/"


def shape_hash(endpoints: Sequence[dict], auth_param: str = "") -> str:
    """Firma DURABLE de familia: sha256 sobre el conjunto ORDENADO de
    `MÉTODO template-normalizado` + el auth_param. Dos instancias del mismo
    software (mismos endpoints, distinto host) → MISMO shape_hash."""
    keys = sorted({
        f"{(e.get('method') or 'GET').upper()} {normalize_template(e.get('endpoint', ''))}"
        for e in endpoints
    })
    blob = "|".join(keys) + f"::auth={auth_param}"
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ── formateadores de clave (ÚNICA fuente de verdad para family_id y lookup) ──────
def resolved_key(server_name: str) -> str:
    return f"resolved:{_slug(server_name)}"


def doc_key(title: str, version: str = "") -> str:
    t = _slug(_norm_title(title))
    v = _major(version)
    return f"doc:{t}@{v}" if v else f"doc:{t}"


def host_key(base_url: str) -> str:
    return f"host:{host_sld(base_url)}"


@dataclass(frozen=True)
class Fingerprint:
    """La huella derivada de un target/ganadora. `family_id` es la clave de índice."""
    kind: str                       # resolved | doc | host
    host_sld: str
    doc_title: str = ""             # normalizado
    doc_version: str = ""           # major
    resolved_server_name: str = ""
    shape_hash: str = ""

    @property
    def family_id(self) -> str:
        if self.resolved_server_name:
            return resolved_key(self.resolved_server_name)
        if self.doc_title:
            return doc_key(self.doc_title, self.doc_version)
        return f"host:{self.host_sld}"

    @property
    def all_keys(self) -> list[str]:
        """TODAS las claves bajo las que esta huella es indexable, fuerte→débil.
        La canónica (family_id) primero; las demás se escriben como ALIAS para que
        la reinyección por host (gratis, sin red) pegue aunque la familia sea doc."""
        keys = [self.family_id]
        host_k = f"host:{self.host_sld}"
        if host_k not in keys and self.host_sld:
            keys.append(host_k)
        return keys

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "host_sld": self.host_sld,
            "doc_title": self.doc_title, "doc_version": self.doc_version,
            "resolved_server_name": self.resolved_server_name,
            "shape_hash": self.shape_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        return cls(
            kind=d.get("kind", "host"), host_sld=d.get("host_sld", ""),
            doc_title=d.get("doc_title", ""), doc_version=d.get("doc_version", ""),
            resolved_server_name=d.get("resolved_server_name", ""),
            shape_hash=d.get("shape_hash", ""))


def derive(
    base_url: str, *,
    endpoints: Optional[Sequence[dict]] = None,
    auth_param: str = "",
    doc_title: str = "",
    doc_version: str = "",
    resolved_server_name: str = "",
) -> Fingerprint:
    """Construye la huella desde señales OBSERVABLES. `endpoints` son dicts (forma
    CandidateTool serializada) → mantiene este módulo puro (no toca contracts)."""
    host = host_sld(base_url)
    sh = shape_hash(endpoints or [], auth_param)
    if resolved_server_name:
        kind = "resolved"
    elif doc_title:
        kind = "doc"
    else:
        kind = "host"
    return Fingerprint(
        kind=kind, host_sld=host,
        doc_title=_norm_title(doc_title), doc_version=_major(doc_version),
        resolved_server_name=resolved_server_name, shape_hash=sh)


def lookup_keys(
    base_url: str, *,
    doc_title: str = "", doc_version: str = "", resolved_server_name: str = "",
) -> list[str]:
    """Las claves a consultar en el almacén, MISMO orden de fuerza que family_id.
    La reinyección prueba estas claves (fuerte→débil) ANTES de la cascada genérica.
    `host:<sld>` siempre va al final como red de seguridad (gratis, sin red)."""
    keys: list[str] = []
    if resolved_server_name:
        keys.append(resolved_key(resolved_server_name))
    if doc_title:
        keys.append(doc_key(doc_title, doc_version))
    keys.append(host_key(base_url))
    # dedup preservando orden
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


__all__ = [
    "Fingerprint", "derive", "lookup_keys",
    "host_sld", "normalize_template", "shape_hash",
    "resolved_key", "doc_key", "host_key",
]
