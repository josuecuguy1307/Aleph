#!/usr/bin/env python3
"""test_cura_frontier.py — MURALLA PREMIUM · la FRONTERA de la CURA (bypass inverso · persona usuaria).

La cura (health-check de drift, /v1/inspect/healthcheck) re-versiona GRATIS una tool que YA existía
(v+1 por drift de shape/endpoint). Pero NO puede fabricar una capability NET-NEW (que no estaba en
el manifest previo) inline por el path libre: si la deriva exige síntesis nueva → ESCALA al gate
premium de construcción, no la fabrica gratis. Revalidar-lo-existente = libre · sintetizar-lo-
inexistente = premium. Estos tests prueban que el bypass inverso está cerrado.

Corre:  PYTHONPATH=<wt>/platform python3 -m pytest platform/inspection/test_cura_frontier.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLATFORM = _HERE.parents[1]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import inspect_run
from inspection.inspect_run import _cura_is_net_new, re_inspect
from inspection.observe.synthesize import _slug


# ── 1 · el helper puro de la frontera ────────────────────────────────────────────
def test_cura_is_net_new_helper():
    # re-versión = MISMA identidad → NO net-new (cura libre)
    assert _cura_is_net_new("registrar_asistencia", "registrar_asistencia") is False
    # identidad distinta = capability nueva → net-new (gate premium)
    assert _cura_is_net_new("registrar_asistencia", "exportar_reporte") is True
    # FAIL-CLOSED: nombre faltante/vacío → net-new (nunca fabricar gratis por la duda)
    assert _cura_is_net_new("registrar_asistencia", None) is True
    assert _cura_is_net_new("registrar_asistencia", "") is True
    assert _cura_is_net_new(None, "x") is True
    assert _cura_is_net_new("", "") is True


# ── 2 · la identidad = slug del intent (la clave del manifest que compara la frontera) ─
def test_identity_key_is_intent_slug():
    a = _slug("registrar asistencia")
    b = _slug("exportar reporte mensual")
    assert a and b and a != b, "intents distintos deben dar identidades distintas"
    assert _slug("registrar asistencia") == a, "mismo intent → misma identidad (re-versión estable)"


# ── fakes para aislar re_inspect del recon real (Playwright/browser) ──────────────
class _FakeEmitter:
    def __init__(self, space_id):
        self.events = []
    def inspeccion_analizando(self, **k): self.events.append(("analizando", k))
    def drift(self, **k): self.events.append(("drift", k))
    def error(self, **k): self.events.append(("error", k))
    def close(self): self.events.append(("close", {}))


class _FakeApp:
    base_url = "http://127.0.0.1:0"
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeCtx:
    async def aclose(self): pass


class _FakeSession:
    def __init__(self, *a, **k): pass
    async def provide_context(self): return _FakeCtx()


class _SpyRegistry:
    def __init__(self):
        self.persisted = []
        self.registered = []
        self.marks = []
    def persist_belt(self, spec, user_id=None):
        self.persisted.append(spec)
        return {"belt_ref": "belts/new.mcp.json", "server_name": "srv", "tool_name": "t"}
    def register_into_puppet(self, *a, **k):
        self.registered.append((a, k))
    def mark_belt(self, belt_ref, **k):
        self.marks.append((belt_ref, k))


def _run_re_inspect_with_synth_name(frozen_name, synthesized_name):
    """Corre re_inspect forzando DRIFT y una re-síntesis con `synthesized_name`, aislado del
    browser. Devuelve (result, spy_registry, emitter)."""
    # frozen spec en disco (lo lee re_inspect)
    tmp = Path(tempfile.mkdtemp()) / "frozen.spec.json"
    tmp.write_text(json.dumps({
        "mcp_tool": {"name": frozen_name, "description": "x", "inputSchema": {}},
        "endpoint": "http://old/endpoint", "_synth": {"version": 1},
    }), encoding="utf-8")

    import inspection.observe.recorder as _rec
    import inspection.observe.correlate as _corr
    import inspection.observe.healthcheck as _hc
    import inspection.session.cloud as _cloud

    spy = _SpyRegistry()
    saved = {}
    async def _fake_record(ctx, **k): return {"bundle": True}

    # patch module-level + function-local sources
    patches = [
        (inspect_run, "SpaceEmitter", _FakeEmitter),
        (inspect_run, "BenignTestApp", _FakeApp),
        (inspect_run, "registry", spy),
        (inspect_run, "synthesize_tool", lambda action: {
            "mcp_tool": {"name": synthesized_name, "description": "d", "inputSchema": {}},
            "label": "L", "category": "read", "endpoint": "http://new/endpoint", "params": []}),
        # stamp_spec se RE-importa function-local en re_inspect (línea ~261) desde su módulo
        # fuente → hay que parchear ahí, no en inspect_run (si no, el import local lo re-liga al real).
        (_hc, "stamp_spec", lambda *a, **k: None),
        (_rec, "record_demonstration", _fake_record),
        (_corr, "correlate", lambda bundle: object()),
        (_hc, "healthcheck_spec", lambda frozen, fresh: {
            "healthy": False, "drift": True, "endpoint_changed": True,
            "changes": ["x"], "fields_added": [], "fields_removed": []}),
        (_cloud, "CloudSession", _FakeSession),
    ]
    for obj, name, val in patches:
        saved[(id(obj), name)] = getattr(obj, name)
        setattr(obj, name, val)
    try:
        result = asyncio.run(re_inspect(
            space_id="t-space", belt_ref="belts/existing.mcp.json", spec_path=str(tmp),
            puppet_id="pup-1", user_id="user-1", fixture_drift=True, auto_resynth=True))
    finally:
        for obj, name, _ in patches:
            setattr(obj, name, saved[(id(obj), name)])
    return result, spy


# ── 3 · NET-NEW por la cura → ESCALA, NO se fabrica gratis ────────────────────────
def test_re_inspect_net_new_escalates_not_fabricated():
    result, spy = _run_re_inspect_with_synth_name("registrar_asistencia", "exportar_reporte")
    assert result.get("action") == "escalate_construction", (
        f"la cura fabricó una tool NET-NEW gratis en vez de escalar (bypass inverso): {result}")
    assert result.get("net_new") is True and result.get("would_synthesize") == "exportar_reporte"
    assert spy.persisted == [], "SEV: se PERSISTIÓ una tool net-new por el path libre de cura (moat vaciado)"
    assert spy.registered == [], "SEV: se REGISTRÓ una tool net-new en el puppet gratis"
    # se marcó stale con la razón de escalada (honesto), no se re-versionó
    assert any("NET-NEW" in (m[1].get("reason") or "") for m in spy.marks), "no marcó el escalamiento honesto"


# ── 4 · RE-VERSIÓN (misma identidad) → CURA LIBRE: se re-forja v+1 ────────────────
def test_re_inspect_reversion_persists_free():
    result, spy = _run_re_inspect_with_synth_name("registrar_asistencia", "registrar_asistencia")
    assert result.get("action") == "resynthesized", f"la re-versión libre no ocurrió: {result}"
    assert result.get("version") == 2, "la re-versión debe subir a v+1"
    assert len(spy.persisted) == 1, "la cura de una tool existente debe re-forjarla (libre)"
    assert len(spy.registered) == 1, "la tool re-versionada debe re-registrarse en el puppet"


if __name__ == "__main__":
    tests = [test_cura_is_net_new_helper, test_identity_key_is_intent_slug,
             test_re_inspect_net_new_escalates_not_fabricated, test_re_inspect_reversion_persists_free]
    print("═" * 78)
    print("  MURALLA PREMIUM · FRONTERA DE LA CURA (bypass inverso)")
    print("═" * 78)
    ok = 0
    for fn in tests:
        try:
            fn(); print(f"  ✓ {fn.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}\n      → {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {fn.__name__}\n      → {type(e).__name__}: {e}")
    print(f"  {ok}/{len(tests)} verdes")
    raise SystemExit(0 if ok == len(tests) else 1)
