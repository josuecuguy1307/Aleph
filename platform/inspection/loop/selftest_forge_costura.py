#!/usr/bin/env python3
"""
selftest_forge_costura.py — VERIFY F5 de la COSTURA · pega a POST /v1/inspect/forge contra un
target REAL autodescriptivo (TMDB · Forma 1 token-en-query) y prueba el contrato ANTES
que cualquier UI, como un script crudo contra el endpoint.

Levanta uvicorn EN ESTE PROCESO sobre un puerto propio (libre, NO :8091), abre el stream
SSE de /v1/forge, recolecta los eventos y verifica los 4 asserts del contrato:

  (a) el endpoint emite la SECUENCIA COMPLETA de eventos del contrato, EN ORDEN:
      sesion.ok → observando → tool.propuesta(×N) → tool.validando → tool.validada
      /tool.descartada → mcp.forjado;
  (b) ≥1 tool.validada con status+payload REALES  Y  ≥1 tool.descartada con motivo real
      (TMDB sí produce drops: el sondeo del borde golpea endpoints inexistentes → 404);
  (c) mcp.forjado trae server≠null + belt_ref + el puppet_id DEL REQUEST;
  (d) 0 eventos fabricados: cada tipo emitido pertenece al vocabulario del contrato y
      mapea a una acción real del motor.

Cerebro: Groq gpt-oss-120b (el endpoint pasa synth_alias="oss"; el shim :8923 no forja).
Requiere: env GROQ_API_KEY  y  el token del target en env FORGE_VERIFY_TMDB_KEY (o --key).

Uso:
    GROQ_API_KEY=… FORGE_VERIFY_TMDB_KEY=… \\
      product/backend/.venv/bin/python platform/inspection/loop/selftest_forge_costura.py
"""
from __future__ import annotations

# ── [Step 5 · P7] OPT-OUT del muro de construcción ────────────────────────────
# Desde P7 el muro premium está ACTIVO POR DEFAULT (antes era staged-off, lo que
# dejaba builds públicos sin muro). Este verificador ejercita el MOTOR, no la
# frontera de tier, y corre con cuentas de prueba sin plan pago: sin este opt-out
# recibiría 402 y probaría otra cosa. La frontera premium tiene sus propios tests
# (test_construction_premium_gate.py, test_muros_default_on.py).
import os as _os
_os.environ.setdefault("PUPPET_ENFORCE_MCP_CONSTRUCTION", "0")

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
for p in (str(_BACKEND), str(_PLATFORM)):
    if p not in sys.path:
        sys.path.insert(0, p)

# vocabulario del contrato (lo que el endpoint tiene DERECHO a emitir). Cualquier tipo
# fuera de este conjunto sería un evento fabricado (assert d).
CONTRACT_TYPES = {
    "forge.iniciado",  # frame de apertura (marca de inicio del stream, no fabrica datos)
    "forge.latido",    # keepalive de transporte (elapsed real, no fabrica datos)
    "sesion.ok", "observando", "sintetizando", "tool.propuesta", "tool.validando",
    "tool.validada", "tool.descartada", "mcp.forjado", "cerrado", "error",
}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _recover_tmdb_from_vault() -> str:
    """Fallback SOLO-DEV: recupera la TMDB key del vault Fernet por-host si está persistida
    (probe previo). NO hay secreto en este archivo; si no está, devolvemos ''."""
    cand = (_REPO_ROOT / "product/backend/data/synth_belts/anon/491b783649bd3901/"
            "tmdb-live/credentials.enc")
    if not cand.exists():
        return ""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("v", _PLATFORM / "gates" / "vault.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        master = os.environ.get("PUPPET_VAULT_MASTER") or f"puppet-dev-{os.uname().nodename}"
        v = m.CredentialVault(str(cand), master_secret=master)
        return v.inject_env({}, ["API_KEY"]).get("API_KEY") or ""
    except Exception:
        return ""


def _boot_server(port: int):
    import uvicorn
    os.environ.setdefault("PUPPET_WORKERS", "0")  # /v1/forge no usa la cola durable
    # VERIFICATION-ONLY: habilita las edge-probes SEMBRADAS solo en este harness. En producto
    # la env NO existe → el endpoint ignora seed_probes → la forja real nunca recibe sondas.
    os.environ["PUPPET_FORGE_ALLOW_SEED_PROBES"] = "1"
    import app.main as m
    config = uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    # esperar /health
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return server, th
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("uvicorn no levantó /health a tiempo")


def _stream_forge(port: int, payload: dict, *, timeout: float = 240.0) -> list[dict]:
    """POST /v1/forge y lee el stream SSE incrementalmente → lista de eventos (dicts)."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/inspect/forge", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    events: list[dict] = []
    cur_event = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("event:"):
                cur_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                blob = line[len("data:"):].strip()
                try:
                    ev = json.loads(blob)
                except json.JSONDecodeError:
                    ev = {"type": cur_event, "_raw": blob}
                events.append(ev)
                print(f"   ◂ {ev.get('type'):16s} "
                      f"{ev.get('nombre') or ev.get('server') or ev.get('url') or ''}")
            elif line == "":
                cur_event = None
    return events


def _order_ok(types: list[str]) -> tuple[bool, str]:
    """Chequea el ORDEN del contrato sobre la secuencia de tipos observada."""
    def first(t):
        return types.index(t) if t in types else -1
    def last(t):
        return max((i for i, x in enumerate(types) if x == t), default=-1)

    i_ses = first("sesion.ok")
    i_obs = first("observando")
    i_prop = first("tool.propuesta")
    i_vdo = first("tool.validando")
    i_res = min([i for i in (first("tool.validada"), first("tool.descartada")) if i >= 0] or [-1])
    i_forj = first("mcp.forjado")

    if i_ses < 0:
        return False, "falta sesion.ok"
    if i_obs < 0 or i_obs < i_ses:
        return False, "observando no viene después de sesion.ok"
    if i_prop < 0 or i_prop < i_obs:
        return False, "tool.propuesta no viene después de observando"
    if i_vdo < 0 or i_vdo < i_prop:
        return False, "tool.validando no viene después de tool.propuesta"
    if i_res < 0 or i_res < i_vdo:
        return False, "tool.validada/descartada no viene después de tool.validando"
    if i_forj < 0 or i_forj < i_res:
        return False, "mcp.forjado no viene al final (después de las validaciones)"
    return True, "orden del contrato OK"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("FORGE_VERIFY_TMDB_KEY", ""))
    ap.add_argument("--url", default="https://api.themoviedb.org/3")
    ap.add_argument("--puppet-id", default="pup-verify-ola0-001")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    key = args.key or _recover_tmdb_from_vault()
    if not key:
        print("ERROR: falta el token del target. Configura FORGE_VERIFY_TMDB_KEY o pasa --key.",
              file=sys.stderr)
        return 2
    if not os.environ.get("GROQ_API_KEY"):
        print("ERROR: falta GROQ_API_KEY (cerebro = Groq gpt-oss-120b).", file=sys.stderr)
        return 2

    port = args.port or _free_port()
    print("═" * 72)
    print(f"  VERIFY COSTURA · POST /v1/inspect/forge → {args.url}  (puerto {port})")
    print("═" * 72)
    # endpoints PLAUSIBLES que NO existen en TMDB (status_code 34 = 404 vivo). Los siembra el
    # caller como EDGE PROBES → pasan por el MISMO candado §5 contra el target vivo y 404ean
    # de verdad → ejercitan tool.descartada con MOTIVO REAL (cero-teatro). gpt-oss-120b no
    # alucina contra TMDB (lo conoce), así que sin estas sondas el camino-drop no se ve.
    seed_probes = [
        {"name": "get_movie_box_office", "endpoint": "/movie/{movie_id}/box_office",
         "path_params": {"movie_id": 550}},
        {"name": "get_movie_awards", "endpoint": "/movie/{movie_id}/awards",
         "path_params": {"movie_id": 550}},
        {"name": "get_person_awards", "endpoint": "/person/{person_id}/awards",
         "path_params": {"person_id": 287}},
    ]
    server, _th = _boot_server(port)
    try:
        # UNA corrida REAL: cerebro=oss (Groq gpt-oss-120b, la forja real) + edge probes
        # sembradas. Produce, en el MISMO stream: validadas (endpoints reales del cerebro,
        # status+payload) · descartadas (las sondas 404, motivo real) · mcp.forjado.
        print(f"\n  cerebro=oss (Groq gpt-oss-120b) · {len(seed_probes)} edge probes · "
              f"puppet_id={args.puppet_id}")
        t0 = time.time()
        events = _stream_forge(port, {
            "url": args.url, "cred": key, "forma": "token", "puppet_id": args.puppet_id,
            "max_rounds": args.rounds, "synth_alias": "oss", "seed_probes": seed_probes})
        dt = time.time() - t0
    finally:
        server.should_exit = True
        time.sleep(0.3)

    types = [e.get("type") for e in events]
    forjado = next((e for e in events if e.get("type") == "mcp.forjado"), None)
    validadas = [e for e in events if e.get("type") == "tool.validada"]
    propuestas = [e for e in events if e.get("type") == "tool.propuesta"]
    descartadas = [e for e in events if e.get("type") == "tool.descartada"]

    print("\n" + "─" * 72)
    print(f"  {len(events)} eventos en {dt:.1f}s · {len(propuestas)} propuesta · "
          f"{len(validadas)} validada · {len(descartadas)} descartada")
    print("─" * 72)

    # ── ASSERT (a) — secuencia completa + orden ────────────────────────────────────
    required = ["sesion.ok", "observando", "tool.propuesta", "tool.validando", "mcp.forjado"]
    have_resultado = ("tool.validada" in types) or ("tool.descartada" in types)
    miss = [t for t in required if t not in types]
    order_ok, order_why = _order_ok(types)
    a = (not miss) and have_resultado and order_ok
    print(f"  (a) secuencia+orden: {'✓' if a else '✗'}  "
          f"{'todos los eventos del contrato, ' + order_why if a else f'falta {miss or order_why}'}")

    # ── ASSERT (b) — ≥1 validada (status+payload reales) Y ≥1 descartada (motivo real) ─
    val_real = [v for v in validadas if v.get("status") is not None and v.get("payload")]
    desc_real = [d for d in descartadas if (d.get("motivo") or "").strip()]
    b = bool(val_real) and bool(desc_real)
    print(f"  (b) validada+descartada reales: {'✓' if b else '✗'}  "
          f"{len(val_real)} validada con status+payload · {len(desc_real)} descartada con motivo real")
    if val_real:
        v0 = val_real[0]
        print(f"        ej validada → {v0.get('nombre')} status={v0.get('status')} "
              f"payload[{len(v0.get('payload') or '')}b]: {(v0.get('payload') or '')[:90]!r}")
    if desc_real:
        d0 = desc_real[0]
        print(f"        ej descartada → {d0.get('nombre')} motivo: {(d0.get('motivo') or '')[:120]!r}")

    # ── ASSERT (c) — mcp.forjado no-hueco + puppet_id del request ───────────────────
    c = bool(forjado) and bool(forjado.get("server")) and bool(forjado.get("belt_ref")) \
        and forjado.get("puppet_id") == args.puppet_id and bool(forjado.get("tools"))
    print(f"  (c) mcp.forjado no-hueco: {'✓' if c else '✗'}  "
          + (f"server={forjado.get('server')} belt_ref={forjado.get('belt_ref')} "
             f"tools={len(forjado.get('tools') or [])} puppet_id={forjado.get('puppet_id')}"
             if forjado else "NO hubo mcp.forjado"))

    # ── ASSERT (d) — 0 eventos fabricados ──────────────────────────────────────────
    fabricados = sorted({t for t in types if t not in CONTRACT_TYPES})
    d = not fabricados
    print(f"  (d) 0 eventos fabricados: {'✓' if d else '✗'}  "
          + ("todos los tipos pertenecen al contrato" if d else f"FUERA DE CONTRATO: {fabricados}"))

    # ── VOLCADO CRUDO (evidencia sin truncar) ──────────────────────────────────────
    print("\n  ══ EVIDENCIA CRUDA ══")
    print("\n  ── (a) secuencia REAL emitida (en orden) ──")
    print("  " + " → ".join(types))
    if val_real:
        print("\n  ── (b) tool.validada CRUDA (status+payload reales) ──")
        print(json.dumps(val_real[0], ensure_ascii=False, indent=2))
    if desc_real:
        print("\n  ── (b) tool.descartada CRUDA (motivo real) ──")
        print(json.dumps(desc_real[0], ensure_ascii=False, indent=2))
    if forjado:
        print("\n  ── (c) mcp.forjado CRUDO (escenario forja · gpt-oss-120b) ──")
        print(json.dumps(forjado, ensure_ascii=False, indent=2))

    ok = a and b and c and d
    print("\n" + ("━" * 72))
    print(f"  RESULTADO: {'✓ VERDE — la costura emite el contrato end-to-end' if ok else '✗ ROJO'}")
    print("━" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
