#!/usr/bin/env python3
"""
selftest_dispatch_order.py — DONE-BAR del DESPACHADOR §0.5 (buscá-antes-de-forjar) contra el
endpoint HTTP REAL `POST /v1/inspect/dispatch`, ANTES que la UI, como script crudo.

Levanta uvicorn en este proceso sobre un puerto propio (libre, NO :8091) con el gate de
verificación encendido (PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES=1) y prueba los 4 asserts:

  (a) target con MCP VERIFICADO en el registry → el resolver lo trae y se EQUIPA por el path
      1-B; el Motor B (forja) NO corre (cero eventos del contrato de forja).
  (b) target SIN MCP en el registry → el resolver da MISS y recién ahí se dispara la FORJA
      (Motor B real: TMDB vivo + Groq) → mcp.forjado.
  (c) un IMPOSTOR DNS (namespace sin ownership) es RECHAZADO por el resolver → no se equipa
      (rejected_impostor=True, cero mcp.equipado).
  (d) AMBOS caminos terminan en PIEZA REAL: el encontrado trae belt_ref+tools reales del MCP
      local; el forjado trae server+belt_ref+tools reales del Motor B.

(a)/(c) son determinísticos y offline (candidatos sembrados arbitrados por el MATCHER REAL +
un MCP local stdio real como blanco del equip). (b)/(d-forjado) corre el Motor B de verdad
(necesita GROQ_API_KEY y la TMDB key — del env FORGE_VERIFY_TMDB_KEY o del vault del árbol main).

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/selftest_dispatch_order.py
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
for p in (str(_BACKEND), str(_PLATFORM)):
    if p not in sys.path:
        sys.path.insert(0, p)

_FAKE = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp.py")
# árbol main: tiene el vault con la TMDB key persistida (probe previo). Solo lectura, dev.
_MAIN_TREE = _REPO_ROOT

CONTRACT_DISPATCH = {"dispatch.iniciado", "resolver.buscando", "resolver.encontrado",
                     "mcp.equipado", "resolver.miss", "dispatch.forjando", "cerrado", "error"}
CONTRACT_FORGE = {"forge.iniciado", "forge.latido", "sesion.ok", "observando", "sintetizando",
                  "tool.propuesta", "tool.validando",
                  "tool.validada", "tool.descartada", "mcp.forjado", "cerrado", "error"}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _recover_tmdb_from_vault() -> str:
    # Tests never recover credentials from a developer/user vault.
    return os.environ.get("FORGE_VERIFY_TMDB_KEY", "")


def _boot_server(port: int):
    import uvicorn
    os.environ.setdefault("PUPPET_WORKERS", "0")
    os.environ["PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES"] = "1"   # gate de verificación (a)/(c)
    import app.main as m
    config = uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return server, th
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("uvicorn no levantó /health a tiempo")


def _stream_dispatch(port: int, payload: dict, *, timeout: float = 240.0) -> list[dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/inspect/dispatch", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    events: list[dict] = []
    cur = None
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
                tag = ev.get("server") or ev.get("server_name") or ev.get("nombre") or ev.get("url") or ""
                print(f"   ◂ {str(ev.get('type')):20s} {tag}")
    return events


def _fake_spec(tmp: Path, *, tools: list[str], server_name: str) -> dict:
    cfg = tmp / f"cfg-{uuid.uuid4().hex[:8]}.json"
    cfg.write_text(json.dumps({"server_name": server_name,
                               "tools": [{"name": t, "description": f"fake {t}",
                                          "inputSchema": {"type": "object"}} for t in tools],
                               "fail": []}), encoding="utf-8")
    return {"transport": "stdio", "command": sys.executable, "args": [_FAKE, str(cfg)],
            "package_env_var": None, "needs_credential": False, "signature": []}


def _cand(name, namespace, vendor, vendor_kind, title, desc, url):
    return {"name": name, "namespace": namespace, "leaf": name.split("/")[-1], "vendor": vendor,
            "vendor_kind": vendor_kind, "title": title, "description": desc, "version": "1.0.0",
            "status": "active", "is_latest": True,
            "repository": {"url": f"https://github.com/{vendor}/x"},
            "remotes": [{"type": "streamable-http", "url": url}], "packages": [], "source": "registry"}


# ── (a) FOUND verificado → equip 1-B, sin forja ───────────────────────────────────
def assert_found(port: int, tmp: Path) -> tuple[bool, dict]:
    print("═" * 72 + "\n  (a) FOUND (registry verificado) → equip 1-B · Motor B NO corre\n" + "═" * 72)
    spec = _fake_spec(tmp, tools=["get_account", "list_charges"], server_name="stripe-local")
    verified = _cand("com.stripe/mcp", "com.stripe", "stripe", "dns", "Stripe",
                     "Stripe payments MCP", "https://mcp.stripe.com")
    evs = _stream_dispatch(port, {"service": "stripe", "credential": None,
                                  "seed_candidates": [verified], "seed_spec": spec})
    types = [e.get("type") for e in evs]
    found = next((e for e in evs if e.get("type") == "resolver.encontrado"), None)
    equip = next((e for e in evs if e.get("type") == "mcp.equipado"), None)
    closed = next((e for e in evs if e.get("type") == "cerrado"), None)
    no_forge = not (set(types) & {"forge.iniciado", "observando", "tool.propuesta",
                                  "tool.validada", "mcp.forjado", "dispatch.forjando"})
    real_piece = bool(equip and equip.get("belt_ref") and equip.get("tools")
                      and equip.get("origin") == "registry")
    ok = (bool(found) and found.get("origin") == "registry" and found.get("verified") is True
          and real_piece and no_forge and bool(closed) and closed.get("path") == "registry"
          and closed.get("forjado") is False)
    print(f"\n  encontrado={bool(found)} origin={found and found.get('origin')} "
          f"verified={found and found.get('verified')}")
    print(f"  equipado: belt_ref={equip and equip.get('belt_ref')} tools={equip and equip.get('tools')}")
    print(f"  Motor B NO corrió: {no_forge}  ·  cerrado.path={closed and closed.get('path')}")
    print(f"\n  (a) {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok, (equip or {})


# ── (c) IMPOSTOR DNS → rechazado, sin equip ───────────────────────────────────────
def assert_impostor(port: int) -> bool:
    print("═" * 72 + "\n  (c) IMPOSTOR DNS (namespace sin ownership) → RECHAZADO por el resolver\n" + "═" * 72)
    impostor = _cand("io.github.evil/stripe-mcp", "io.github.evil", "evil", "github_org",
                     "Stripe (unofficial)", "stripe-like community fork", "https://evil.example/mcp")
    # SIN url → si el resolver lo equivocadamente aceptara, ni siquiera podría forjar; lo que
    # importa: el impostor NO se equipa.
    evs = _stream_dispatch(port, {"service": "stripe", "credential": None,
                                  "seed_candidates": [impostor]})
    types = [e.get("type") for e in evs]
    miss = next((e for e in evs if e.get("type") == "resolver.miss"), None)
    equipped = any(t == "mcp.equipado" for t in types)
    encontrado = any(t == "resolver.encontrado" for t in types)
    ok = (bool(miss) and miss.get("rejected_impostor") is True and not equipped and not encontrado)
    print(f"\n  resolver.miss={bool(miss)} rejected_impostor={miss and miss.get('rejected_impostor')}")
    print(f"  reason: {(miss or {}).get('reason', '')[:90]!r}")
    print(f"  ¿se equipó el impostor? {equipped}  ·  ¿resolver.encontrado? {encontrado}")
    print(f"\n  (c) {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok


# ── (b)+(d-forjado) MISS → Motor B forja una pieza real ───────────────────────────
def assert_miss_forge(port: int, tmdb_key: str) -> tuple[bool, dict]:
    print("═" * 72 + "\n  (b) MISS (sin MCP en registry) → se dispara la FORJA (Motor B · TMDB+Groq)\n" + "═" * 72)
    # seed_candidates=[] fuerza el MISS determinísticamente; url=TMDB → el Motor B forja.
    evs = _stream_dispatch(port, {
        "service": "https://api.themoviedb.org/3", "url": "https://api.themoviedb.org/3",
        "credential": tmdb_key, "forma": "token", "synth_alias": "oss", "max_rounds": 2,
        "seed_candidates": []}, timeout=300.0)
    types = [e.get("type") for e in evs]
    miss = next((e for e in evs if e.get("type") == "resolver.miss"), None)
    forjando = next((e for e in evs if e.get("type") == "dispatch.forjando"), None)
    forjado = next((e for e in evs if e.get("type") == "mcp.forjado"), None)
    ran_motor_b = bool(set(types) & {"forge.iniciado", "observando", "tool.validada"})
    real_piece = bool(forjado and forjado.get("server") and forjado.get("belt_ref")
                      and forjado.get("tools"))
    ok = (bool(miss) and bool(forjando) and forjando.get("origin") == "forged"
          and ran_motor_b and real_piece)
    print(f"\n  resolver.miss={bool(miss)} → dispatch.forjando={bool(forjando)} (Motor B disparado)")
    print(f"  Motor B corrió: {ran_motor_b}")
    print(f"  mcp.forjado: server={forjado and forjado.get('server')} "
          f"belt_ref={forjado and forjado.get('belt_ref')} tools={len(forjado.get('tools') or []) if forjado else 0}")
    print(f"\n  (b)+(d-forjado) {'✅ VERDE' if ok else '❌ ROJO'}")
    return ok, (forjado or {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("FORGE_VERIFY_TMDB_KEY", ""))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--skip-forge", action="store_true", help="omite (b)/(d-forjado) si no hay GROQ/TMDB")
    args = ap.parse_args()

    tmdb_key = args.key or _recover_tmdb_from_vault()
    have_forge = bool(tmdb_key) and bool(os.environ.get("GROQ_API_KEY")) and not args.skip_forge

    port = args.port or _free_port()
    print("═" * 72)
    print(f"  DONE-BAR DESPACHADOR §0.5 · POST /v1/inspect/dispatch  (puerto {port})")
    print(f"  forja-en-vivo (b/d): {'SÍ (TMDB+Groq)' if have_forge else 'OMITIDA (sin GROQ/TMDB)'}")
    print("═" * 72)

    server, _th = _boot_server(port)
    tmp = Path(tempfile.mkdtemp(prefix="disp-order-"))
    results = {}
    forged = {}
    equipped = {}
    try:
        results["(a) found→equip"], equipped = assert_found(port, tmp)
        results["(c) impostor"] = assert_impostor(port)
        if have_forge:
            results["(b) miss→forge"], forged = assert_miss_forge(port, tmdb_key)
        else:
            print("\n  ⚠ (b)/(d-forjado) OMITIDO: falta GROQ_API_KEY o la TMDB key.")
    finally:
        server.should_exit = True
        time.sleep(0.3)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # (d) ambos caminos en pieza real
    d_found = bool(equipped.get("belt_ref") and equipped.get("tools"))
    d_forged = bool(forged.get("belt_ref") and forged.get("tools")) if have_forge else None
    results["(d) ambos pieza real"] = d_found and (d_forged if have_forge else True)

    print("\n" + "═" * 72)
    for k, v in results.items():
        print(f"  {k:24s}: {'✅ VERDE' if v else '❌ ROJO'}")
    if not have_forge:
        print("  (b)/(d-forjado) no evaluados (forja en vivo omitida)")
    allok = all(results.values())
    print("═" * 72 + f"\n  TOTAL: {'✅ TODO VERDE' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
