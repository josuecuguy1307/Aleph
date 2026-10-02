"""4.3 — ALEPH_BUILD (public/founder/dev) + gating de premium-local en COMPILACIÓN. [Casa 2 · Fase 4]

S3: en un build SHIPPED (public/founder) el muro de premium-local va BAKED — `PUPPET_ENFORCE_
METHOD_EXPORT=0` NO puede apagarlo. El opt-out por env vale SÓLO en dev/CI. (El gate real está en
methods_router._enforce_method_premium; acá se fija la lógica de build_id que lo decide.)
"""
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "platform"))
import build_id  # noqa: E402

_OFF = ("0", "false", "no", "off")


def test_default_is_dev(monkeypatch):
    monkeypatch.delenv("ALEPH_BUILD", raising=False)
    assert build_id.current() == "dev"
    assert build_id.is_dev() and not build_id.is_shipped()


def test_env_selects_public_and_founder(monkeypatch):
    monkeypatch.setenv("ALEPH_BUILD", "public")
    assert build_id.is_public() and build_id.is_shipped() and not build_id.is_dev()
    monkeypatch.setenv("ALEPH_BUILD", "founder")
    assert build_id.is_founder() and build_id.is_shipped()


def test_invalid_build_falls_to_dev(monkeypatch):
    monkeypatch.setenv("ALEPH_BUILD", "banana")
    assert build_id.current() == "dev"


def test_shipped_build_CANNOT_optout_the_premium_wall(monkeypatch):
    """La propiedad S3: public/founder ignoran PUPPET_ENFORCE_METHOD_EXPORT=0; dev sí lo respeta.
    Reproduce la condición EXACTA del gate: opt-out = is_dev() AND env∈OFF."""
    monkeypatch.setenv("PUPPET_ENFORCE_METHOD_EXPORT", "0")
    for build in ("public", "founder"):
        monkeypatch.setenv("ALEPH_BUILD", build)
        optout = build_id.is_dev() and os.environ["PUPPET_ENFORCE_METHOD_EXPORT"].lower() in _OFF
        assert optout is False, f"{build}: NO debe poder apagar el muro por env (S3)"
    monkeypatch.setenv("ALEPH_BUILD", "dev")
    optout = build_id.is_dev() and os.environ["PUPPET_ENFORCE_METHOD_EXPORT"].lower() in _OFF
    assert optout is True, "dev: el opt-out por env SÍ debe valer (comodidad CI)"
