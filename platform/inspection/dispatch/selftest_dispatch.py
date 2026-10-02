#!/usr/bin/env python3
"""
selftest_dispatch.py — DONE-BAR DURO del seam dispatch/ (verify-from-environment,
DETERMINÍSTICO, sin cerebro y sin :8923).

  product/backend/.venv/bin/python platform/inspection/dispatch/selftest_dispatch.py

Cubre:
  1. CLASSIFIER → 3 veredictos por las señales del matcher (fixtures de candidatos).
  2. DUDOSO → probe_mcp ARBITRA contra un fake MCP stdio local: el tool real se FORJA, el
     phantom (no listado) y el caído (no responde) se DROPEAN. CERO cerebro.
  3. CONFIABLE → liveness OK → equipado.
  4. NADA → ruteado a run_cascade (cascade_fn inyectado: NO se ejecuta el synth caro).
  5. GATE §0.5 → disparado ANTES de tocar el mundo (deny bloquea; auto saltea; sin confirm =
     fail-closed).
  6. SSRF §9 → el guard rechaza una URL interna ANTES de que probe_mcp conecte.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))
_REPO_ROOT = _PLATFORM.parent

from inspection import contracts as C                      # noqa: E402
from inspection.loop.guard import PublicHTTPGuard          # noqa: E402
from inspection.dispatch import liveness                   # noqa: E402
from inspection.dispatch.classifier import classify        # noqa: E402
from inspection.dispatch.dispatcher import dispatch         # noqa: E402
from inspection.dispatch.models import Draft, Verdict       # noqa: E402

_FAKE = str(Path(_HERE) / "fixtures" / "fake_mcp.py")


# ── helpers ──────────────────────────────────────────────────────────────────────
def _principal() -> C.Principal:
    return C.Principal(anon_id=f"disp-{uuid.uuid4().hex[:12]}")


def _fake_spec(tmp: Path, *, tools: list[dict], fail: list[str], server_name: str) -> dict:
    import json
    cfg = tmp / f"cfg-{uuid.uuid4().hex[:8]}.json"
    cfg.write_text(json.dumps({"server_name": server_name, "tools": tools, "fail": fail}),
                   encoding="utf-8")
    return {"transport": "stdio", "command": sys.executable, "args": [_FAKE, str(cfg)],
            "package_env_var": None, "needs_credential": False, "signature": []}


def _tool(name: str) -> dict:
    return {"name": name, "description": f"fake {name}", "inputSchema": {"type": "object"}}


def _draft(spec: dict, *, service: str, server: str, claimed=()) -> Draft:
    return Draft(service=service, server_name=server, spec=spec, vendor_kind="test",
                 source="fixture", score=0.6, verified_vendor=False,
                 claimed_tools=tuple(claimed), reason="fixture draft")


def _cleanup(result) -> None:
    """Borra el belt forjado (synth_belts es gitignored, pero dejamos limpio igual)."""
    try:
        ref = (result.forged or {}).get("belt_ref") if isinstance(result.forged, dict) else None
        if ref:
            shutil.rmtree((_REPO_ROOT / ref).parent, ignore_errors=True)
    except Exception:
        pass


def _yes(_req) -> bool:
    return True


def _no(_req) -> bool:
    return False


# ── candidatos fixture para el classifier (forma de mcp_registry._candidate) ─────
def _cand_verified() -> dict:
    return {"name": "com.stripe/mcp", "namespace": "com.stripe", "leaf": "mcp",
            "vendor": "stripe", "vendor_kind": "dns", "title": "Stripe",
            "description": "Stripe payments MCP", "version": "1.0.0", "status": "active",
            "is_latest": True, "repository": {"url": "https://github.com/stripe/mcp"},
            "remotes": [{"type": "streamable-http", "url": "https://mcp.stripe.com",
                         "headers": [{"name": "Authorization", "value": "Bearer {key}",
                                      "isSecret": True}]}],
            "packages": [], "source": "registry"}


def _cand_community() -> dict:
    return {"name": "io.github.randomdev/weather-mcp", "namespace": "io.github.randomdev",
            "leaf": "weather-mcp", "vendor": "randomdev", "vendor_kind": "github_org",
            "title": "Weather MCP", "description": "weather forecast tools", "version": "0.2.0",
            "status": "active", "is_latest": True,
            "repository": {"url": "https://github.com/randomdev/weather-mcp"},
            "remotes": [{"type": "streamable-http", "url": "https://weather.example/mcp"}],
            "packages": [], "source": "registry"}


# ── 1 · CLASSIFIER: 3 veredictos ─────────────────────────────────────────────────
def donebar_classifier() -> bool:
    print("═" * 72 + "\n  1 · CLASSIFIER → {CONFIABLE, DUDOSO, NADA} de las señales del matcher\n" + "═" * 72)
    v1, d1 = classify("stripe", candidates=[_cand_verified()])
    v2, d2 = classify("weather", candidates=[_cand_community()])
    v3, d3 = classify("zxqw-no-existe", candidates=[])
    print(f"    stripe (vendor DNS verificado)  → {v1.value:9s} verified={d1 and d1.verified_vendor} score={d1 and d1.score}")
    print(f"    weather (community below-bar)   → {v2.value:9s} verified={d2 and d2.verified_vendor} score={d2 and d2.score}")
    print(f"    sin candidatos                  → {v3.value:9s} draft={d3}")
    ok = (v1 is Verdict.CONFIABLE and d1 and d1.verified_vendor
          and v2 is Verdict.DUDOSO and d2 and not d2.verified_vendor and d2.spec
          and v3 is Verdict.NADA and d3 is None)
    print(f"\n  DONE-BAR classifier: {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


# ── 2 · DUDOSO: probe arbitra (real forjado · phantom + caído dropeados) ─────────
def donebar_dudoso() -> bool:
    print("═" * 72 + "\n  2 · DUDOSO → probe_mcp arbitra: real FORJADO · phantom + caído DROPEADOS · 0 cerebro\n" + "═" * 72)
    tmp = Path(tempfile.mkdtemp(prefix="disp-dudoso-"))
    # fake MCP lista [get_weather (real), get_broken (caído)]; el borrador reclama además
    # get_ghost (phantom = nunca listado).
    spec = _fake_spec(tmp, tools=[_tool("get_weather"), _tool("get_broken")],
                      fail=["get_broken"], server_name="weather-dudoso")
    draft = _draft(spec, service="weather", server="weather-mcp",
                   claimed=["get_weather", "get_broken", "get_ghost"])

    res = dispatch("weather", secret=None, principal=_principal(), auto=False, confirm=_yes,
                   classify_fn=lambda *a, **k: (Verdict.DUDOSO, draft), verify_calls=True)
    print(f"    path={res.path} ok={res.ok} verified={res.verified} dropped={res.dropped} "
          f"brain={res.used_brain} gate_shown={res.gate_shown}")
    ok = (res.ok and res.path == "dudoso"
          and res.verified == ("get_weather",)
          and set(res.dropped) == {"get_ghost", "get_broken"}
          and res.used_brain is False and res.gate_shown is True)
    _cleanup(res)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n  DONE-BAR dudoso: {'✅ VERDE' if ok else '❌ ROJO'} "
          f"(get_weather forjado · get_ghost=phantom + get_broken=caído dropeados · 0 cerebro)")
    return ok


# ── 3 · CONFIABLE: liveness OK → equipado ────────────────────────────────────────
def donebar_confiable() -> bool:
    print("═" * 72 + "\n  3 · CONFIABLE → liveness OK → equipado\n" + "═" * 72)
    tmp = Path(tempfile.mkdtemp(prefix="disp-conf-"))
    spec = _fake_spec(tmp, tools=[_tool("get_account"), _tool("list_charges")], fail=[],
                      server_name="stripe-confiable")
    draft = Draft(service="stripe", server_name="com.stripe/mcp", spec=spec, vendor_kind="dns",
                  source="registry", score=0.99, verified_vendor=True, reason="vendor verificado")
    res = dispatch("stripe", secret=None, principal=_principal(), auto=False, confirm=_yes,
                   classify_fn=lambda *a, **k: (Verdict.CONFIABLE, draft))
    print(f"    path={res.path} ok={res.ok} verified={res.verified} brain={res.used_brain} "
          f"gate_shown={res.gate_shown}")
    ok = (res.ok and res.path == "confiable"
          and set(res.verified) == {"get_account", "list_charges"}
          and res.used_brain is False and res.gate_shown is True
          and isinstance(res.forged, dict) and res.forged.get("belt_ref"))
    _cleanup(res)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n  DONE-BAR confiable: {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


# ── 4 · NADA: ruteado a run_cascade (synth NO ejecutado) ─────────────────────────
def donebar_nada() -> bool:
    print("═" * 72 + "\n  4 · NADA → ruteado a run_cascade (cascade inyectado · synth NO corre)\n" + "═" * 72)
    calls = {"n": 0, "args": None}

    class _FakeCascade:
        ok = True
        verified = ()
        forged = None
        used_brain = False
        convergence = "fake-cascade (synth NO ejecutado)"
        error = ""

    def fake_cascade(base_url, api_key, principal, **knobs):
        calls["n"] += 1
        calls["args"] = (base_url, api_key)
        return _FakeCascade()

    res = dispatch("cualquier-cosa", secret="k", principal=_principal(),
                   base_url="https://api.example.com", candidates=[], auto=True,
                   cascade_fn=fake_cascade)
    print(f"    path={res.path} routed_to={res.meta.get('routed_to')} "
          f"cascade_called={calls['n']} base_url={calls['args'] and calls['args'][0]}")
    ok = (res.path == "nada" and res.meta.get("routed_to") == "run_cascade"
          and calls["n"] == 1 and calls["args"][0] == "https://api.example.com"
          and res.used_brain is False)

    # y NADA sin base_url → fallo honesto, sin tocar nada
    res2 = dispatch("x", candidates=[], auto=True)
    ok = ok and (res2.path == "nada" and not res2.ok and "base_url" in res2.reason)
    print(f"    sin base_url → ok={res2.ok} reason='{res2.reason[:48]}…'")
    print(f"\n  DONE-BAR nada: {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


# ── 5 · GATE §0.5: disparado antes de tocar el mundo ─────────────────────────────
def donebar_gate() -> bool:
    print("═" * 72 + "\n  5 · GATE §0.5 → deny bloquea · auto saltea · sin confirm = fail-closed\n" + "═" * 72)
    tmp = Path(tempfile.mkdtemp(prefix="disp-gate-"))
    spec = _fake_spec(tmp, tools=[_tool("get_x")], fail=[], server_name="gate")
    draft = _draft(spec, service="svc", server="svc-mcp", claimed=["get_x"])
    cf = lambda *a, **k: (Verdict.DUDOSO, draft)

    r_deny = dispatch("svc", principal=_principal(), auto=False, confirm=_no, classify_fn=cf)
    r_auto = dispatch("svc", principal=_principal(), auto=True, confirm=None, classify_fn=cf,
                      verify_calls=True)
    r_none = dispatch("svc", principal=_principal(), auto=False, confirm=None, classify_fn=cf)

    print(f"    deny  → path={r_deny.path} ok={r_deny.ok} gate_shown={r_deny.gate_shown}")
    print(f"    auto  → path={r_auto.path} ok={r_auto.ok} gate_shown={r_auto.gate_shown}")
    print(f"    none  → path={r_none.path} ok={r_none.ok} gate_shown={r_none.gate_shown}")
    ok = (r_deny.path == "blocked" and not r_deny.ok and r_deny.gate_shown is True
          and r_auto.ok and r_auto.path == "dudoso" and r_auto.gate_shown is False
          and r_none.path == "blocked" and not r_none.ok and r_none.gate_shown is False)
    _cleanup(r_auto)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n  DONE-BAR gate: {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


# ── 6 · SSRF §9: el guard rechaza la URL interna ANTES de conectar ───────────────
def donebar_ssrf() -> bool:
    print("═" * 72 + "\n  6 · SSRF §9 → guard rechaza URL interna ANTES de probe_mcp\n" + "═" * 72)
    spec = {"transport": "http", "url": "http://169.254.169.254/latest/meta-data",
            "header_name": "Authorization", "header_template": "Bearer {key}",
            "needs_credential": True, "signature": []}
    draft = _draft(spec, service="evil", server="evil-mcp", claimed=["get_x"])
    res = dispatch("evil", secret="k", principal=_principal(), auto=True,
                   classify_fn=lambda *a, **k: (Verdict.DUDOSO, draft), guard=PublicHTTPGuard())
    print(f"    path={res.path} ok={res.ok} reason='{res.reason[:70]}…'")
    # también probamos el guard directo (allow IP pública / deny interna) por unidad
    g = PublicHTTPGuard()
    deny = g.check("http://169.254.169.254/x")     # link-local + http → denegada
    allow = g.check("https://1.1.1.1/x")            # IP pública literal → permitida
    ok = (not res.ok and ("rechaz" in res.reason.lower() or "§9" in res.reason)
          and (not deny) and bool(allow))
    print(f"    guard.check(metadata-ip)={bool(deny)} · guard.check(public-ip)={bool(allow)}")
    print(f"\n  DONE-BAR ssrf: {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


def main() -> int:
    runners = {
        "classifier": donebar_classifier,
        "dudoso": donebar_dudoso,
        "confiable": donebar_confiable,
        "nada": donebar_nada,
        "gate": donebar_gate,
        "ssrf": donebar_ssrf,
    }
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which != "all":
        return 0 if runners[which]() else 1
    results = {k: f() for k, f in runners.items()}
    print("\n" + "═" * 72)
    for k, v in results.items():
        print(f"  {k:11s}: {'✅ VERDE' if v else '❌ ROJO'}")
    allok = all(results.values())
    print("═" * 72 + f"\n  TOTAL: {'✅ TODO VERDE' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
