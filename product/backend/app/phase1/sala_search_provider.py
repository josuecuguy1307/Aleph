"""Optional SearXNG endpoint for Sala, stored per Aleph user.

The SearXNG server is never part of the proprietary application. Both Sala
packs receive only the validated URL through their per-process environment.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request


class SearchProviderError(ValueError):
    def __init__(self, code: str, copy: str):
        self.code = code
        self.copy = copy
        super().__init__(copy)


def configured_url(user_id: str) -> str:
    from workspaces import memoria

    deltas = memoria.como_quedo(user_id, "sala_busqueda").get("deltas") or {}
    saved = deltas.get("searxng_url", "")
    # An explicit empty value disconnects the provider, even if a developer has
    # ALEPH_SEARXNG_URL in the parent shell. Old installations without a saved
    # choice retain that environment-variable integration.
    if saved is not None and isinstance(saved, str) and saved:
        return saved
    if "searxng_url" in deltas:
        return ""
    return os.environ.get("ALEPH_SEARXNG_URL", "").strip()


def normalize_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value or len(value) > 2048:
        raise SearchProviderError("search_provider_invalid_url", "Enter a SearXNG URL.")
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port  # Raises for malformed ports.
    except ValueError as exc:
        raise SearchProviderError("search_provider_invalid_url", "The search provider URL is invalid.") from exc
    if (parts.scheme not in {"http", "https"} or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or "\\" in value):
        raise SearchProviderError("search_provider_invalid_url", "Use an HTTP(S) URL without credentials, query, or fragment.")
    if any(segment == ".." for segment in parts.path.split("/")):
        raise SearchProviderError("search_provider_invalid_url", "The search provider URL has an invalid path.")
    host = parts.hostname.lower()
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in
                     socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80),
                                        proto=socket.IPPROTO_TCP)}
    except (OSError, ValueError) as exc:
        raise SearchProviderError("search_provider_unreachable", "The search provider host could not be resolved.") from exc
    if not addresses or any(ip.is_link_local or ip.is_multicast or ip.is_unspecified
                            or str(ip) == "169.254.169.254" for ip in addresses):
        raise SearchProviderError("search_provider_invalid_url", "That search provider address is not allowed.")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SearchProviderError("search_provider_unexpected_redirect", "The search provider redirected its API request.")


def validate_instance(raw: str) -> str:
    base = normalize_url(raw)
    probe = base + "/search?" + urllib.parse.urlencode({"q": "aleph-provider-check", "format": "json"})
    request = urllib.request.Request(probe, headers={"Accept": "application/json",
                                                    "User-Agent": "Aleph-provider-check"})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=8) as response:
            if response.status != 200:
                raise SearchProviderError("search_provider_bad_api", "The search provider did not return HTTP 200.")
            payload = response.read(262145)
    except SearchProviderError:
        raise
    except urllib.error.HTTPError as exc:
        raise SearchProviderError("search_provider_bad_api",
                                  f"The search provider returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SearchProviderError("search_provider_unreachable", "Could not connect to the SearXNG JSON API.") from exc
    if len(payload) > 262144:
        raise SearchProviderError("search_provider_bad_api", "The search provider response was too large.")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise SearchProviderError("search_provider_bad_api", "The search provider did not return JSON.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list) or not isinstance(data.get("query"), str):
        raise SearchProviderError("search_provider_bad_api", "The endpoint is not a SearXNG-compatible JSON search API.")
    return base


def pack_meta(meta: dict, user_id: str) -> dict:
    url = configured_url(user_id)
    if not url:
        raise SearchProviderError("search_provider_required", "Web search requires a search provider.")
    validate_instance(url)
    return {**meta, "pack_env": {**dict(meta.get("pack_env") or {}), "ALEPH_SEARXNG_URL": url}}
