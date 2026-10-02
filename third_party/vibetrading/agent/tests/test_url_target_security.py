"""Regression tests for the SSRF URL guard.

[Aleph · F6] La mitad de QQ (fetch de media saliente) se fue con su adaptador;
el guard central se conserva porque ``src/security/network.py`` lo re-exporta.

- ``validate_url_target`` / ``_is_private`` must block non-globally-routable
  ranges, including RFC 6598 ``100.64.0.0/10`` (CGNAT / the default Tailscale
  mesh range). ``ipaddress.is_private`` is ``False`` for 100.64/10, so the old
  ``is_loopback | is_link_local | is_private`` check let those hosts through.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging

import pytest

from src.channels.utils import _is_private, validate_url_target

# ─── central SSRF guard ───


@pytest.mark.parametrize(
    "ip",
    [
        # RFC 6598 shared address space — the default Tailscale/mesh range.
        # is_private is False for these, so they slipped through before the fix.
        "100.64.0.1",
        "100.100.100.100",
        "100.127.255.254",
        # classic private / internal ranges must stay blocked too
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "0.0.0.0",
        "224.0.0.1",  # multicast
        # IPv6 non-global
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_is_private_blocks_non_global_ranges(ip: str) -> None:
    assert _is_private(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_is_private_allows_global_ranges(ip: str) -> None:
    assert _is_private(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize("ip", ["100.64.0.1", "100.100.100.100"])
def test_validate_url_target_blocks_cgnat_ip_literal(ip: str) -> None:
    # IP-literal host → getaddrinfo is a local parse, so this needs no network.
    ok, err = validate_url_target(f"http://{ip}/x")
    assert ok is False
    assert "private" in err or "internal" in err


def test_validate_url_target_allows_public_ip_literal() -> None:
    ok, _err = validate_url_target("http://8.8.8.8/x")
    assert ok is True


def test_validate_url_target_loopback_only_with_opt_in() -> None:
    # Default: loopback is blocked even though it is a literal IP.
    assert validate_url_target("http://127.0.0.1/x")[0] is False
    # The narrow opt-in still allows literal loopback.
    assert validate_url_target("http://127.0.0.1/x", allow_loopback=True)[0] is True
