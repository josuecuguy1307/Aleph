#!/usr/bin/env python3
"""
selftest_catalog_equip.py — DONE-BAR de EQUIPAR-DESDE-REGISTRO (FREE) contra el endpoint HTTP
REAL `POST /v1/catalog/equip`, en role=client, datadir AISLADO, cero mocks.

Prueba el carril libre del catálogo público (buscar→curar→equipar) que reemplaza el dead-end
del dispatcher en el cliente. Reusa los fixtures del done-bar del dispatcher (candidatos
arbitrados por el matcher REAL + un MCP local stdio real como blanco de la curación/equip).

Asserts:
  (auth)  sin sesión → 401 (mutación = identidad; el device-user de login-suave siempre la da).
  (a)     CONFIABLE + curación pasa → mcp.equipado (belt_ref + tools reales) + cerrado{registry,
          ok} · Motor B NO corre (cero eventos de forja) · PERSISTIDO en la receta del puppet.
  (b1)    IMPOSTOR DNS sembrado → resolver.miss + cerrado{cause:no_confiable, rejected_impostor}.
  (b2)    ELEGISTE-OTRO (confiable=X, elegiste Y) → anti-impostor al elegir frena · no_confiable.
  (c)     REGISTRO CAÍDO (REGISTRY_BASE inalcanzable) → resolver.registry_down +
          cerrado{cause:registry_unreachable, retry} · JAMÁS mudo, JAMÁS "no existe".
  (d)     CURACIÓN RECHAZO (MCP vivo pero firma no matchea) → curacion.rechazo +
          cerrado{cause:curacion_rechazo} · NADA se equipa crudo.
  (premium) el endpoint FREE nunca forja (cero eventos de forja en ningún camino); el miss
          legítimo señala premium_available:true → la construcción sigue por dispatch (Motor B).

Uso:  product/backend/.venv/bin/python \\
        platform/inspection/dispatch/selftest_catalog_equip.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
for p in (str(_BACKEND), str(_PLATFORM)):
    if p not in sys.path:
        sys.path.insert(0, p)

# datadir AISLADO + role=client ANTES de importar app.main (bootstrap de schema del cliente).
_TMP = Path(tempfile.mkdtemp(prefix="cat-equip-"))
os.environ["ALEPH_ROLE"] = "client"
os.environ["ALEPH_DATA_DIR"] = str(_TMP / "data")
os.environ["PUPPET_SQLITE_PATH"] = str(_TMP / "data" / "aleph.db")
os.environ["PUPPET_WORKERS"] = "0"
os.environ["PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES"] = "1"   # gate de verificación (matcher REAL)

from inspection.dispatch.selftest_dispatch_order import _free_port, _fake_spec, _cand  # noqa: E402

_FAKE = str(_HERE / "fixtures" / "fake_mcp.py")


def _cred_spec(tmp: Path, *, tools: list, server_name: str) -> dict:
    """Como _fake_spec pero el MCP PIDE credencial (package_env_var) → _equip_found hace el
    round-trip por el vault y REGISTRA la pieza en la receta del puppet (registered:true). Es el
    caso realista del registry: casi todo confiable (Stripe/GitHub/…) exige tu llave."""
    spec = _fake_spec(tmp, tools=tools, server_name=server_name)
    spec["needs_credential"] = True
    spec["package_env_var"] = "FAKE_TOKEN"
    return spec


def _sig_mismatch_spec(tmp: Path, *, server_name: str) -> dict:
    """MCP local que ARRANCA y expone tools, pero con una FIRMA esperada que NINGUNA matchea →
    validate_live lo rechaza ('expone tools pero ninguna matchea la firma'). El sistema inmune
    cazando un server mal-etiquetado: vivo, pero no es el que dice ser."""
    spec = _fake_spec(tmp, tools=["alpha_tool", "beta_tool"], server_name=server_name)
    spec["signature"] = ["stripe", "charge", "payment"]   # ninguna aparece en los nombres
    return spec


def _boot_client(port: int):
    import uvicorn
    import app.main as m
    config = uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(160):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return server, th
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("uvicorn (client) no levantó /health a tiempo")


def _mk_user_session_puppet():
    """Crea user + sesión + un puppet vacío en la DB del cliente (SQLite). Devuelve (token, puppet_id)."""
    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        u = repo.register_user(conn, email=f"equip-{uuid.uuid4().hex[:8]}@demo.ai",
                               password="equip-demo-2026", display_name="Equip Test")
        uid = u["id"]
        pup = repo.create_puppet(conn, owner_id=uid, name="Agente de prueba", nicho="qa",
                                 config={"schema_version": "v1", "meta": {"name": "Agente de prueba",
                                         "nicho": "qa"}, "belt": {"belt_refs": [], "tool_filters": {}},
                                         "canvas": {"nucleos": [{"model": "included"}], "blocks": [],
                                         "links": [], "layout": []}})
    finally:
        conn.close()
    token = repo.mint_session(uid)
    return token, pup["id"], uid


def _puppet_belt_refs(puppet_id: str) -> list:
    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        p = repo.get_puppet(conn, puppet_id)
        cfg = p["config"] if p and isinstance(p.get("config"), dict) else {}
        return (cfg.get("belt") or {}).get("belt_refs", [])
    finally:
        conn.close()


def _stream(port: int, payload: dict, *, token: str = None, timeout: float = 120.0):
    data = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = "Bearer " + token
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/catalog/equip", data=data,
                                 headers=headers, method="POST")
    events, cur = [], None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("event:"):
                    cur = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    blob = line[len("data:"):].strip()
                    try:
                        ev = json.loads(blob)
                    except json.JSONDecodeError:
                        ev = {"type": cur, "_raw": blob}
                    events.append(ev)
                    tag = ev.get("server") or ev.get("server_name") or ev.get("cause") or ev.get("reason") or ""
                    print(f"   ◂ {str(ev.get('type')):26s} {str(tag)[:60]}")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "events": events}
    return {"http_error": None, "events": events}


_FORGE_EVENTS = {"forge.iniciado", "observando", "sintetizando", "tool.propuesta",
                 "tool.validando", "tool.validada", "mcp.forjado", "dispatch.forjando"}


def _no_forge(evs) -> bool:
    return not ({e.get("type") for e in evs} & _FORGE_EVENTS)


def _closed(evs):
    return next((e for e in evs if e.get("type") == "cerrado"), None)


def main() -> int:
    port = _free_port()
    print("═" * 72)
    print(f"  DONE-BAR · /v1/catalog/equip (FREE · equipar-desde-registro) · client :{port}")
    print(f"  datadir aislado: {_TMP}")
    print("═" * 72)
    server, _ = _boot_client(port)
    token, puppet_id, uid = _mk_user_session_puppet()
    results = {}

    # ── (auth) sin sesión → 401 (mutación = identidad) ──────────────────────────
    print("\n── (auth) sin sesión → 401 ──")
    spec = _fake_spec(_TMP, tools=["get_account", "list_charges"], server_name="stripe-local")
    verified = _cand("com.stripe/mcp", "com.stripe", "stripe", "dns", "Stripe",
                     "Stripe payments MCP", "https://mcp.stripe.com")
    r = _stream(port, {"service": "stripe", "seed_candidates": [verified], "seed_spec": spec})
    results["auth_401"] = (r["http_error"] == 401)
    print(f"  → http_error={r['http_error']}  {'✅' if results['auth_401'] else '❌'}")

    # ── (a) CONFIABLE + curación pasa → equipado + PERSISTIDO ────────────────────
    print("\n── (a) CONFIABLE → curación pasa → equipado + persistido ──")
    before = _puppet_belt_refs(puppet_id)
    cred_spec = _cred_spec(_TMP, tools=["get_account", "list_charges"], server_name="stripe-local")
    r = _stream(port, {"service": "stripe", "server_name": "com.stripe/mcp",
                       "credential": "tok_test_stripe_123", "puppet_id": puppet_id,
                       "seed_candidates": [verified], "seed_spec": cred_spec},
                token=token)
    evs = r["events"]
    found = next((e for e in evs if e.get("type") == "resolver.encontrado"), None)
    curando = next((e for e in evs if e.get("type") == "curacion.probando"), None)
    equip = next((e for e in evs if e.get("type") == "mcp.equipado"), None)
    closed = _closed(evs)
    after = _puppet_belt_refs(puppet_id)
    persisted = bool(equip and equip.get("belt_ref") and equip.get("belt_ref") in after
                     and equip.get("belt_ref") not in before)
    results["a_equip"] = bool(
        found and found.get("verified") is True and curando
        and equip and equip.get("origin") == "registry" and equip.get("belt_ref")
        and equip.get("tools") and equip.get("registered") is True
        and _no_forge(evs) and closed and closed.get("path") == "registry"
        and closed.get("ok") is True and persisted)
    print(f"  encontrado={bool(found)} curó={bool(curando)} equipado.belt={equip and equip.get('belt_ref')}")
    print(f"  registered={equip and equip.get('registered')} persistido_en_receta={persisted} "
          f"no_forge={_no_forge(evs)}  {'✅' if results['a_equip'] else '❌'}")

    # ── (b1) IMPOSTOR DNS sembrado → no_confiable ───────────────────────────────
    print("\n── (b1) IMPOSTOR (namespace sin ownership) → gate frena ──")
    impostor = _cand("io.github.evil/stripe-mcp", "io.github.evil", "evil", "github_org",
                     "Stripe (unofficial)", "community fork", "https://evil.example/mcp")
    r = _stream(port, {"service": "stripe", "seed_candidates": [impostor], "seed_spec": spec},
                token=token)
    evs = r["events"]; closed = _closed(evs)
    miss = next((e for e in evs if e.get("type") == "resolver.miss"), None)
    results["b1_impostor"] = bool(
        miss and not next((e for e in evs if e.get("type") == "mcp.equipado"), None)
        and _no_forge(evs) and closed and closed.get("cause") == "no_confiable")
    print(f"  miss={bool(miss)} rejected_impostor={closed and closed.get('rejected_impostor')} "
          f"cause={closed and closed.get('cause')}  {'✅' if results['b1_impostor'] else '❌'}")

    # ── (b2) ELEGISTE-OTRO (anti-impostor al elegir) → no_confiable ─────────────
    print("\n── (b2) confiable=com.stripe/mcp, elegiste io.github.evil → frena ──")
    r = _stream(port, {"service": "stripe", "server_name": "io.github.evil/stripe-mcp",
                       "seed_candidates": [verified], "seed_spec": spec}, token=token)
    evs = r["events"]; closed = _closed(evs)
    miss = next((e for e in evs if e.get("type") == "resolver.miss"), None)
    results["b2_picked_wrong"] = bool(
        miss and miss.get("trusted") == "com.stripe/mcp"
        and not next((e for e in evs if e.get("type") == "mcp.equipado"), None)
        and closed and closed.get("cause") == "no_confiable")
    print(f"  miss.trusted={miss and miss.get('trusted')} cause={closed and closed.get('cause')} "
          f" {'✅' if results['b2_picked_wrong'] else '❌'}")

    # ── (c) REGISTRO CAÍDO (REGISTRY_BASE inalcanzable) → registry_unreachable ──
    print("\n── (c) registro caído → fallo VISIBLE con causa (no mudo) ──")
    # SIN seed → el resolver pega al registry vivo; lo apuntamos a un host inalcanzable (mismo
    # daño que la CA ausente del binario frozen: registro inalcanzable). Fallo de red REAL.
    from inspection import mcp_registry
    _orig_base = mcp_registry.REGISTRY_BASE
    mcp_registry.REGISTRY_BASE = "https://127.0.0.1:1"   # connection refused → RegistryError
    try:
        r = _stream(port, {"service": "un-servicio-cualquiera-xyz"}, token=token)
    finally:
        mcp_registry.REGISTRY_BASE = _orig_base
    evs = r["events"]; closed = _closed(evs)
    down = next((e for e in evs if e.get("type") == "resolver.registry_down"), None)
    results["c_registry_down"] = bool(
        down and down.get("retry") is True and _no_forge(evs)
        and closed and closed.get("cause") == "registry_unreachable" and closed.get("retry") is True
        and not next((e for e in evs if e.get("type") == "mcp.equipado"), None))
    print(f"  registry_down={bool(down)} cause={closed and closed.get('cause')} "
          f"retry={closed and closed.get('retry')}  {'✅' if results['c_registry_down'] else '❌'}")

    # ── (d) CURACIÓN RECHAZO (vivo pero firma no matchea) → curacion_rechazo ────
    print("\n── (d) MCP vivo pero firma no matchea → curación rechaza (nada crudo) ──")
    bad_spec = _sig_mismatch_spec(_TMP, server_name="stripe-local")
    r = _stream(port, {"service": "stripe", "server_name": "com.stripe/mcp", "puppet_id": puppet_id,
                       "seed_candidates": [verified], "seed_spec": bad_spec}, token=token)
    evs = r["events"]; closed = _closed(evs)
    rechazo = next((e for e in evs if e.get("type") == "curacion.rechazo"), None)
    belt_after_d = _puppet_belt_refs(puppet_id)
    results["d_curacion_rechazo"] = bool(
        rechazo and not next((e for e in evs if e.get("type") == "mcp.equipado"), None)
        and _no_forge(evs) and closed and closed.get("cause") == "curacion_rechazo"
        # NADA crudo entró: la receta quedó igual que tras (a) (no sumó la pieza rechazada)
        and belt_after_d == after)
    print(f"  curacion.rechazo={bool(rechazo)} cause={closed and closed.get('cause')} "
          f"receta_intacta={belt_after_d == after}  {'✅' if results['d_curacion_rechazo'] else '❌'}")

    # ── (premium) el FREE nunca forja; el miss legítimo apunta a premium ────────
    print("\n── (premium) miss legítimo → premium_available, cero forja ──")
    # servicio inexistente con candidatos vacíos (matcher da miss legítimo, NO impostor)
    r = _stream(port, {"service": "servicio-inexistente-zzz", "seed_candidates": [],
                       "seed_spec": None}, token=token)
    evs = r["events"]; closed = _closed(evs)
    miss = next((e for e in evs if e.get("type") == "resolver.miss"), None)
    results["premium_intact"] = bool(
        miss and _no_forge(evs) and closed and closed.get("cause") == "no_confiable"
        and closed.get("premium_available") is True
        and not next((e for e in evs if e.get("type") == "mcp.equipado"), None))
    print(f"  miss={bool(miss)} premium_available={closed and closed.get('premium_available')} "
          f"no_forge={_no_forge(evs)}  {'✅' if results['premium_intact'] else '❌'}")

    # ── veredicto ──
    print("\n" + "═" * 72)
    allok = all(results.values())
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'}  {k}")
    print("═" * 72)
    print(f"  {'✅ TODO VERDE' if allok else '❌ HAY ROJOS'}")
    try:
        server.should_exit = True
    except Exception:
        pass
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
