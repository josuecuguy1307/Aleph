#!/usr/bin/env python3
"""
selftest_resolver.py — DONE-BAR del resolver de MCPs, verificable sin credenciales reales.

Corre:
  product/backend/.venv/bin/python platform/inspection/selftest_resolver.py
  (agregá LIVE=1 para incluir una resolución contra el registro oficial en vivo.)

Cubre (cero theater):
  1. vendor_of: el parseo del namespace reverse-DNS → vendor (la señal anti-impostor).
  2. matcher: elige el vendor verificado sobre comunidad; aplica el umbral (no equipa
     mejor-de-malos); margen de ambigüedad entre comunitarios.
  3. provider/env-var canónicos (deben matchear _provider_env_vars del assembler).
  4. SEGURIDAD: equip_resolved forja un manifest con PLACEHOLDER ${VAR}, NUNCA el secreto
     en claro (el agujero de la sonda D). Lee el manifest del disco y lo prueba.
  5. (LIVE) resolución end-to-end de "stripe" contra el registro: com.stripe/mcp verificado.
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # platform/ en el path

from inspection import mcp_matcher, mcp_registry, mcp_resolver  # noqa: E402

_FAILS = []


def check(name, cond):
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        _FAILS.append(name)


# 1) vendor_of
print("1) vendor_of (namespace reverse-DNS → vendor):")
check("com.stripe/mcp → vendor=stripe kind=dns",
      mcp_registry.vendor_of("com.stripe/mcp") == {"namespace": "com.stripe", "leaf": "mcp",
                                                    "vendor": "stripe", "vendor_kind": "dns"})
v = mcp_registry.vendor_of("io.github.acme/x")
check("io.github.acme/x → vendor=acme kind=github_org",
      v["vendor"] == "acme" and v["vendor_kind"] == "github_org")
check("ai.smithery/foo → vendor=smithery",
      mcp_registry.vendor_of("ai.smithery/foo")["vendor"] == "smithery")

# 2) matcher con candidatos canned (determinista, sin red)
print("2) matcher (4 señales + umbral anti-impostor):")
official = {"name": "com.stripe/mcp", "vendor": "stripe", "vendor_kind": "dns", "leaf": "mcp",
            "title": "", "description": "Stripe payments MCP", "status": "active",
            "is_latest": True, "repository": {"url": "https://github.com/stripe/x"},
            "remotes": [{"type": "streamable-http", "url": "https://mcp.stripe.com"}], "packages": []}
impostor = {"name": "io.github.evil/stripe-mcp", "vendor": "evil", "vendor_kind": "github_org",
            "leaf": "stripe-mcp", "title": "", "description": "stripe mcp", "status": "active",
            "is_latest": True, "repository": {}, "remotes": [], "packages": [{"x": 1}]}
d = mcp_matcher.best_match("stripe", [official, impostor])
check("elige com.stripe/mcp (vendor verificado) sobre el impostor",
      d["found"] and d["winner"]["candidate"]["name"] == "com.stripe/mcp")
check("el impostor con vendor!=servicio NO tiene crédito anti-impostor",
      mcp_matcher.score_candidate("stripe", impostor)["signals"]["vendor"] == 0.0)
d2 = mcp_matcher.best_match("stripe", [impostor])
check("solo-impostor (sin vendor verificado, bajo umbral) → NO encontrado",
      not d2["found"])
two_comm = [dict(impostor, name="io.github.a/stripe-mcp", vendor="a"),
            dict(impostor, name="io.github.b/stripe-mcp", vendor="b")]
check("dos comunitarios parejos → ambigüedad → NO encontrado",
      not mcp_matcher.best_match("stripe", two_comm)["found"])

# 3) provider / env-var canónicos
print("3) provider / env-var (contrato con el assembler):")
check("provider_for('stripe') == 'resolver_stripe'",
      mcp_resolver.provider_for("stripe") == "resolver_stripe")
check("env_var_for('resolver_stripe') == 'RESOLVER_STRIPE_API_KEY'",
      mcp_resolver.env_var_for("resolver_stripe") == "RESOLVER_STRIPE_API_KEY")

# 4) SEGURIDAD: la forja escribe PLACEHOLDER, no el secreto
print("4) seguridad: el manifest forjado lleva placeholder, NO el secreto:")
# dir temporal BAJO el repo (forge_byo_belt exige que el belt_ref sea relativo al repo root)
import inspection.registry as _reg  # noqa: E402
tmp_root = _reg.SYNTH_BELTS_DIR.parent / ("_selftest_" + os.urandom(4).hex())
_orig = _reg.SYNTH_BELTS_DIR
try:
    _reg.SYNTH_BELTS_DIR = tmp_root
    resolution = {
        "server_name": "com.stripe/mcp",
        "source": "registry", "vendor_kind": "dns",
        "spec": {"transport": "http", "url": "https://mcp.stripe.com",
                 "header_name": "Authorization", "header_template": "Bearer {key}",
                 "needs_credential": True, "signature": ["stripe"]},
    }
    fake_probe = {"transport": "http", "url": "https://mcp.stripe.com",
                  "headers": {"Authorization": "Bearer sk_test_SELFTEST_SECRET_DO_NOT_PERSIST"},
                  "server_info": {}, "tools": [{"name": "get_stripe_account_info",
                                                "description": "x", "inputSchema": {}}]}
    out = mcp_resolver.equip_resolved(resolution, fake_probe, user_id="user-XYZ",
                                      puppet_id=None, service="stripe", conn=None)
    belt_dir = tmp_root / "user-XYZ"
    manifests = list(belt_dir.rglob("manifest.json"))
    check("forjó bajo synth_belts/<user_id> (no anon)", belt_dir.exists() and bool(manifests))
    blob = "".join(p.read_text() for p in belt_dir.rglob("*") if p.is_file())
    check("el secreto del probe NO aparece en NINGÚN archivo forjado",
          "sk_test_SELFTEST_SECRET_DO_NOT_PERSIST" not in blob)
    man = json.loads(manifests[0].read_text())
    check("el header del manifest es el placeholder ${RESOLVER_STRIPE_API_KEY}",
          man["headers"]["Authorization"] == "Bearer ${RESOLVER_STRIPE_API_KEY}")
    check("byok_env_var reportado == RESOLVER_STRIPE_API_KEY",
          out.get("byok_env_var") == "RESOLVER_STRIPE_API_KEY")
finally:
    _reg.SYNTH_BELTS_DIR = _orig
    shutil.rmtree(tmp_root, ignore_errors=True)

# 5) LIVE (opcional)
if os.environ.get("LIVE"):
    print("5) LIVE: resolución contra el registro oficial:")
    try:
        r = mcp_resolver.resolve_service("stripe")
        check("stripe → com.stripe/mcp verificado (dns)",
              r["server_name"] == "com.stripe/mcp" and r["vendor_kind"] == "dns")
        try:
            mcp_resolver.resolve_service("totally-fake-xyz-9000")
            check("servicio inexistente → NotFound", False)
        except mcp_resolver.NotFound:
            check("servicio inexistente → NotFound honesto", True)
    except Exception as e:  # noqa: BLE001
        check(f"registro vivo accesible ({e})", False)

print()
if _FAILS:
    print(f"FALLÓ: {len(_FAILS)} checks → {_FAILS}")
    sys.exit(1)
print("DONE-BAR resolver: TODO VERDE ✓")
