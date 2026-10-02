#!/usr/bin/env python3
"""
selftest_store.py — GATE OFFLINE de FASE 3a (almacén + huella). Sin red: prueba que
la HUELLA es de la FAMILIA (no la instancia) y que el almacén round-trippea.

  product/backend/.venv/bin/python platform/inspection/library/selftest_store.py

Checks:
  1. dos INSTANCIAS (distinto host, ids concretos distintos) de la MISMA familia →
     MISMO family_id y MISMO shape_hash (la huella ignora host + ids).
  2. capturo la instancia A → lookup por la huella de B la encuentra (el moat: B
     hereda lo de A sin re-cruzar).
  3. round-trip to_dict/from_dict idéntico.
  4. mapeo PLATFORM-LEDGER: templated → PARAMETRIZABLE · familia B → REUSABLE ·
     concretos puros → INSTANCIA.
  5. fallback host: sin doc → family_id host:<sld>.
  6. record_hit incrementa y persiste (flywheel) · stats() agrega META.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C            # noqa: E402
from inspection.library import fingerprint as fp  # noqa: E402
from inspection.library import store             # noqa: E402
from inspection.strategy.types import CascadeResult, Rung  # noqa: E402


def _vt(name: str, endpoint: str, method: str = "GET") -> C.VerifiedTool:
    cand = C.CandidateTool(
        name=name, kind=C.ToolKind.READ, endpoint=endpoint, method=method,
        input_schema={"type": "object", "properties": {}},
        description=f"read {endpoint}", derived_from=("openapi:WidgetCRM",))
    return C.VerifiedTool(candidate=cand, verified_by="200-OK+schema-match")


def _instance(base_url: str, ids: tuple[str, str]) -> CascadeResult:
    """Una instancia de 'WidgetCRM': mismos templates, ids CONCRETOS distintos."""
    verified = (
        _vt("get_things", "/things"),
        _vt("get_thing", f"/things/{ids[0]}"),               # id concreto, distinto por instancia
        _vt("get_user_orders", f"/users/{ids[1]}/orders"),
    )
    return CascadeResult(
        ok=True, base_url=base_url, winner=Rung.A_SELF_DESCRIBING,
        early_exit_at=Rung.A_SELF_DESCRIBING, verified=verified,
        rungs=(), budget={"live_calls": 9, "synth_tokens": 0, "rounds": 0})


def main() -> int:
    ok_all = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok_all
        ok_all = ok_all and cond
        print(f"  {'✅' if cond else '❌'} {label}")

    tmp = Path(tempfile.mkdtemp(prefix="capture-lib-test-"))
    print(f"═══ FASE 3a · almacén offline (root={tmp})\n")

    # instancias A y B de la MISMA familia, distinto host + ids concretos distintos
    a = _instance("https://acme.widgetcrm.io", ("42", "7"))
    b = _instance("https://shop.example.com",  ("99", "315"))

    eps_a = [store.endpoint_to_dict(vt.candidate) for vt in a.verified]
    eps_b = [store.endpoint_to_dict(vt.candidate) for vt in b.verified]
    fp_a = fp.derive("https://acme.widgetcrm.io", endpoints=eps_a, auth_param="api_key",
                     doc_title="WidgetCRM API", doc_version="3.0.0")
    fp_b = fp.derive("https://shop.example.com", endpoints=eps_b, auth_param="api_key",
                     doc_title="WidgetCRM API", doc_version="3.0.0")

    print("— 1 · huella = FAMILIA, no instancia")
    check(f"family_id A==B ({fp_a.family_id})", fp_a.family_id == fp_b.family_id == "doc:widgetcrm-api@3")
    check(f"shape_hash A==B ({fp_a.shape_hash})", fp_a.shape_hash == fp_b.shape_hash)
    check(f"host_sld difiere (A={fp_a.host_sld} B={fp_b.host_sld})", fp_a.host_sld != fp_b.host_sld)
    check("normalize /things/42 == /things/99", fp.normalize_template("/things/42") == fp.normalize_template("/things/99") == "/things/{}")

    print("\n— 2 · capturo A → la huella de B la encuentra (reinyección cross-instancia)")
    cs = store.capture(a, base_url="https://acme.widgetcrm.io", auth_param="api_key",
                       validate_path="/things", doc_title="WidgetCRM API", doc_version="3.0.0", root=tmp)
    check("capture devolvió entrada", cs is not None)
    keys_b = fp.lookup_keys("https://shop.example.com", doc_title="WidgetCRM API", doc_version="3.0.0")
    hit = store.lookup(keys_b, root=tmp)
    check(f"lookup(B) → hit por {keys_b[0]}", hit is not None and hit.family_id == "doc:widgetcrm-api@3")
    check("priors traen los 3 endpoints", hit is not None and len(hit.priors["endpoints"]) == 3)

    print("\n— 3 · round-trip serde")
    rt = store.CapturedStrategy.from_dict(cs.to_dict())
    check("to_dict→from_dict idéntico", rt.to_dict() == cs.to_dict())

    print("\n— 4 · mapeo PLATFORM-LEDGER")
    check(f"templated → PARAMETRIZABLE ({cs.ledger_class})", cs.ledger_class == "PARAMETRIZABLE")
    # familia B (resolver) → REUSABLE
    fam = CascadeResult(ok=True, base_url="https://acme.odoo.com", winner=Rung.B_FINGERPRINT,
                        early_exit_at=Rung.B_FINGERPRINT, family={"server_name": "odoo-mcp", "source": "registry"},
                        verified=(), budget={"live_calls": 2})
    cs_fam = store.capture(fam, base_url="https://acme.odoo.com", root=tmp)
    check(f"familia B → REUSABLE + resolved:odoo-mcp", cs_fam is not None
          and cs_fam.ledger_class == "REUSABLE" and cs_fam.family_id == "resolved:odoo-mcp")
    # endpoints concretos puros (sin template, sin convención) → INSTANCIA
    check("concretos puros → INSTANCIA",
          store.classify_ledger("D", [{"endpoint": "/dashboard/main", "method": "GET"}]) == "INSTANCIA")

    print("\n— 5 · fallback host (sin doc)")
    nodoc = CascadeResult(ok=True, base_url="https://www.alphavantage.co/query",
                          winner=Rung.D_ACTIVE, verified=(_vt("q", "/query"),),
                          budget={"live_calls": 30, "synth_tokens": 45000, "rounds": 4})
    cs_nd = store.capture(nodoc, base_url="https://www.alphavantage.co/query", root=tmp)
    check(f"sin doc → host:alphavantage ({cs_nd.family_id if cs_nd else '∅'})",
          cs_nd is not None and cs_nd.family_id == "host:alphavantage")

    print("\n— 6 · flywheel + META")
    before = hit.hits
    store.record_hit(hit, root=tmp)
    re_hit = store.lookup(keys_b, root=tmp)
    check(f"record_hit persiste (+1 → {re_hit.hits})", re_hit is not None and re_hit.hits == before + 1)
    st = store.stats(root=tmp)
    check(f"stats META: {st['families']} familias, {st['total_hits']} hits, clases={st['by_class']}",
          st["families"] == 3 and st["total_hits"] == 1
          and st["by_class"].get("PARAMETRIZABLE") == 1 and st["by_class"].get("REUSABLE") == 1)

    store.clear(root=tmp)
    print("\n" + "─" * 60)
    print(f"  FASE 3a (almacén + huella): {'✅ VERDE' if ok_all else '❌ ROJO'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
