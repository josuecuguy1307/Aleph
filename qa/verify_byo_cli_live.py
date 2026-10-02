#!/usr/bin/env python3
"""verify_byo_cli_live.py — eje VIVO del BYO-CLI (D2 real · D1 vivo · D5 e2e · D4 provocado).

SECUENCIAL (regla de los harnesses vivos). Gasta ~2-3 completions mínimas de la
suscripción del usuario (claude). Requiere: Postgres puppet_ai vivo + infra/.env +
product/backend/.venv. Puertos: cli_brain :8926 · backend efímero :8106 (no pisa
:8080/:8090/:8093/:8097/:8098 de otras sesiones).

HONESTIDAD DE ENTORNO: si la cuenta ChatGPT de esta máquina no tiene plan Codex
(caso sondeado: 400 "not supported when using Codex with a ChatGPT account"), el
run VIVO de codex se marca **ENV-BLOCKED** con la evidencia impresa — jamás un verde
fingido. El resto de los ejes de codex (detección viva, clasificación del error real,
e2e degradado-visible) SÍ corren vivos.

Ejes:
  L1 · detección REAL de ambos providers (estados de esta máquina)
  L2 · completion viva claude-code-cli por el server → model_final REAL cli-reported
  L3 · completion viva codex-cli → verde si el plan lo permite / ENV-BLOCKED honesto
  L4 · D5 e2e claude_cli: recipe brain_provider → backend → cli server → CLI del
       usuario → tool_call real (calc) → final/closed con brain_provider + model_final
       REAL en el espinazo del espacio
  L5 · D5 e2e codex_cli: SIN false green (o corre de verdad, o degrada/falla VISIBLE)
  L6 · D4 PROVOCADO: cli server con CLI fake rate-limited (señal real del binario) →
       brain_window_exhausted en el espinazo (provider_name + reset) + degraded narrable

Run: product/backend/.venv/bin/python qa/verify_byo_cli_live.py
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "platform" / "assembler"))

CLI_PORT = int(os.environ.get("BYO_CLI_LIVE_CLI_PORT", "8926"))
BACK_PORT = int(os.environ.get("BYO_CLI_LIVE_BACK_PORT", "8106"))
CLI_BASE = f"http://127.0.0.1:{CLI_PORT}"
BACK_BASE = f"http://127.0.0.1:{BACK_PORT}"

FAILS: list[str] = []
ENV_BLOCKED: list[str] = []


def ok(cond: bool, label: str, extra: str = "") -> None:
    print(("✓ " if cond else "✗ ") + label + ((" · " + extra) if extra else ""))
    if not cond:
        FAILS.append(label)


def envblocked(label: str, evidence: str) -> None:
    print(f"◌ ENV-BLOCKED · {label}\n    evidencia: {evidence[:220]}")
    ENV_BLOCKED.append(label)


def http_json(method: str, url: str, payload: dict | None = None, timeout: float = 30):
    req = urllib.request.Request(url, method=method,
                                 data=(json.dumps(payload).encode() if payload is not None else None),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def wait_port(url: str, secs: float = 20) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.4)
    return False


def load_env_file(p: Path) -> dict:
    out = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def start_cli_server(extra_env: dict | None = None) -> subprocess.Popen:
    # el puerto DEBE estar libre: si un server viejo sobrevive, este no bindea y el
    # harness hablaría con el equivocado (falso resultado). Abortamos honesto.
    if not wait_port_free(CLI_PORT, 10):
        raise RuntimeError(f"el puerto {CLI_PORT} ya está ocupado — matá el server viejo "
                           f"(lsof -t -iTCP:{CLI_PORT} -sTCP:LISTEN | xargs kill) y reintentá")
    env = dict(os.environ, PUPPET_CLI_BRAIN_PORT=str(CLI_PORT), PUPPET_CLI_BRAIN_DETECT_TTL="5")
    env.update(extra_env or {})
    p = subprocess.Popen([sys.executable, str(REPO / "platform/assembler/cli_brain/server.py")],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_port(f"{CLI_BASE}/health", 15):
        raise RuntimeError("cli_brain server no levantó")
    return p


def stop(p: subprocess.Popen | None) -> None:
    if p is None:
        return
    try:
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=8)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
            pass


def wait_port_free(port: int, secs: float = 15) -> bool:
    """Espera a que el puerto quede LIBRE de verdad (el TERM puede tardar; si el server
    viejo sobrevive, el nuevo no binde y el harness hablaría con el equivocado)."""
    import socket
    t0 = time.time()
    while time.time() - t0 < secs:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.3)
    return False


def recipe_for(bp: str) -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": f"byo-{bp}", "nicho": "general", "output_type": "informe"},
        "model": {"primary": "claude-code-cli" if bp == "claude_cli" else "codex-cli",
                  "base_url": f"{CLI_BASE}/v1", "alias": bp, "brain_provider": bp,
                  "temperature": 0, "max_tokens": 700, "max_turns": 6, "fallback": None},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 "tool_filters": {"calc": ["mul", "add"]}},
        "rag": {"enabled": False},
    }


PROMPT = "Multiplicá 1234 por 5678 usando la calculadora (tool mul) y respondé SOLO el número."


def space_events(space_id: str) -> list[dict]:
    code, body = http_json("GET", f"{BACK_BASE}/v1/spaces/{space_id}/events", timeout=20)
    if code != 200:
        return []
    evs = body.get("events") if isinstance(body, dict) else body
    return evs if isinstance(evs, list) else []


def run_case(bp: str, space_id: str, timeout: float = 220) -> tuple[dict, list[dict]]:
    code, out = http_json("POST", f"{BACK_BASE}/v1/puppets/run",
                          {"recipe": recipe_for(bp), "prompt": PROMPT,
                           "space_id": space_id, "deadline_s": 170}, timeout=timeout)
    evs = space_events(space_id)
    return ({"http": code, **(out if isinstance(out, dict) else {})}, evs)


def main() -> int:
    # ── sanity de entorno ─────────────────────────────────────────────────────────
    envf = load_env_file(REPO / "infra" / ".env")
    if not envf:
        print("infra/.env ausente — symlinkeá al repo primario"); return 2

    print("══ L1 · detección REAL de ambos providers ══")
    from cli_brain.detect import detect_all
    det = detect_all(ttl=0)
    for pid, st in det.items():
        print(f"  · {pid}: {st['state']} — {st['detail']}")
    from cli_brain.registry import provider_ids
    ok(set(det) == set(provider_ids()), "detección = ids del registro")
    ok(all(st["state"] in ("ready", "no_auth", "not_installed") for st in det.values()),
       "estados dentro del contrato de 3 valores")
    claude_ready = det["claude_cli"]["state"] == "ready"
    codex_ready = det["codex_cli"]["state"] == "ready"
    ok(claude_ready, "claude_cli READY en esta máquina (prerequisito del eje vivo)")

    procs: list[subprocess.Popen | None] = [None, None]
    try:
        print("\n══ L2 · completion viva claude-code-cli (server :%d) ══" % CLI_PORT)
        procs[0] = start_cli_server()
        code, body = http_json("POST", f"{CLI_BASE}/v1/chat/completions",
                               {"model": "claude-code-cli",
                                "messages": [{"role": "user", "content": "Respondé con exactamente: PONG"}]},
                               timeout=180)
        meta = (body.get("aleph_cli_brain") or {}) if isinstance(body, dict) else {}
        ok(code == 200 and (body.get("choices") or [{}])[0].get("message", {}).get("content", "").strip() == "PONG",
           "claude vivo: 200 + PONG", f"http={code}")
        ok(str(body.get("model", "")).startswith("claude-") and body.get("model") != "claude-code-cli",
           "model_final REAL del CLI (no un eco)", str(body.get("model")))
        ok(meta.get("model_final_source") == "cli-reported" and meta.get("exec_events") == 0,
           "cli-reported + exec_events 0 (puro in/out)", json.dumps(meta))

        print("\n══ L3 · completion viva codex-cli ══")
        code, body = http_json("POST", f"{CLI_BASE}/v1/chat/completions",
                               {"model": "codex-cli",
                                "messages": [{"role": "user", "content": "Respondé con exactamente: PONG"}]},
                               timeout=180)
        codex_live_green = False
        if code == 200:
            codex_live_green = True
            ok(bool((body.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()),
               "codex VIVO: 200 + texto", str(body.get("model")))
        else:
            e = (body.get("error") or {}) if isinstance(body, dict) else {}
            if e.get("error_kind") == "model_error" and "not supported" in (e.get("message") or ""):
                envblocked("codex run vivo (la cuenta ChatGPT no tiene plan Codex)", e.get("message") or "")
                ok(e.get("brain_provider") == "codex_cli" and code == 502,
                   "…pero el error VIVO llega CLASIFICADO (502 model_error + provider) — contrato real ejercitado",
                   f"http={code}")
            elif e.get("error_kind") == "rate_limit":
                envblocked("codex run vivo (ventana agotada AHORA)", e.get("message") or "")
                ok(code == 429, "…429 throttled clasificado", f"http={code}")
            else:
                ok(False, "codex vivo: error NO clasificado (ni verde ni env-blocked)", json.dumps(e)[:180])

        # ── backend efímero ──────────────────────────────────────────────────────
        print("\n══ backend efímero :%d (brain_provider manda; sin PUPPET_BRAIN) ══" % BACK_PORT)
        benv = dict(os.environ)
        benv.update(envf)
        for k in ("PUPPET_BRAIN", "PUPPET_BRAIN_SHIM", "PUPPET_BRAIN_SHIM_MODEL",
                  "PUPPET_BRAIN_BASE_URL", "PUPPET_BRAIN_MODEL"):
            benv.pop(k, None)
        benv.update(PUPPET_HTTP_TIMEOUT="240",
                    PUPPET_CLI_BRAIN_BASE_URL=f"{CLI_BASE}/v1",
                    PUPPET_OSS_DIRECT="1")  # red de seguridad ON → la degradación se NARRA
        procs[1] = subprocess.Popen(
            [str(REPO / "product/backend/.venv/bin/python"), "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(BACK_PORT)],
            cwd=str(REPO / "product" / "backend"), env=benv,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        okup = wait_port(f"{BACK_BASE}/health", 30) or wait_port(f"{BACK_BASE}/docs", 10)
        ok(okup, "backend efímero arriba")
        if not okup:
            return 1

        print("\n══ L4 · D5 e2e claude_cli: Cuarto→backend→CLI del usuario→espinazo ══")
        sid = f"byo-live-claude-{int(time.time())}"
        out, evs = run_case("claude_cli", sid)
        rec = out.get("record") or {}
        ok(out.get("http") in (200, 201) and out.get("ok") is True, "run ok", f"http={out.get('http')} err={str(out.get('error'))[:80]}")
        ok(rec.get("brain_provider") == "claude_cli", "record.brain_provider = claude_cli", str(rec.get("brain_provider")))
        mf = str(rec.get("model_final") or "")
        window_hit = bool(rec.get("brain_window_exhausted"))
        if window_hit:
            envblocked("claude e2e verde (la ventana Max se agotó DURANTE el harness — D4 real observado)",
                       json.dumps(rec.get("brain_window_exhausted")))
        else:
            ok(mf.startswith("claude-") and mf != "claude-code-cli",
               "model_final REAL reportado por el CLI", mf)
            ok(not rec.get("degraded"), "sin degradación (corrió el cerebro pedido)", str(rec.get("degraded")))
        calls = [c for c in (rec.get("tool_calls") or []) if c.get("gate_action") == "execute"]
        ok(len(calls) >= 1, "≥1 tool ejecutada REAL (calc)", str(len(calls)))
        ok("7006652" in str(out.get("answer") or rec.get("answer") or ""), "la respuesta trae el número real",
           str(out.get("answer"))[:60])
        types = [e.get("type") for e in evs]
        ok("tool_call_finished" in types, "espinazo: tool_call_finished", str(types[:12]))
        fin = next((e for e in evs if e.get("type") == "final"), {})
        clo = next((e for e in evs if e.get("type") == "closed"), {})
        ok(fin.get("brain_provider") == "claude_cli", "espinazo final.brain_provider", str(fin.get("brain_provider")))
        ok(clo.get("brain_provider") == "claude_cli" and str(clo.get("model_final", "")).startswith("claude-"),
           "espinazo closed enriquecido (brain_provider + model_final real)",
           f"{clo.get('brain_provider')}/{clo.get('model_final')}")

        print("\n══ L5 · D5 e2e codex_cli: JAMÁS false green ══")
        sid2 = f"byo-live-codex-{int(time.time())}"
        out2, evs2 = run_case("codex_cli", sid2)
        rec2 = out2.get("record") or {}
        mf2 = str(rec2.get("model_final") or "")
        if codex_live_green:
            ok(out2.get("ok") is True and mf2.startswith("gpt"), "codex e2e VIVO verde", mf2)
        else:
            false_green = bool(out2.get("ok")) and not rec2.get("degraded") and mf2.startswith("gpt")
            ok(not false_green, "SIN false green: o degrada VISIBLE o falla honesto",
               f"ok={out2.get('ok')} degraded={bool(rec2.get('degraded'))} mf={mf2}")
            ok(rec2.get("brain_provider") == "codex_cli", "record.brain_provider = codex_cli")
            if out2.get("ok") and rec2.get("degraded"):
                ok(True, "degradación VISIBLE (red oss-direct respondió; el switch queda narrable)",
                   json.dumps(rec2.get("degraded"))[:120])
                envblocked("codex e2e verde (mismo bloqueo de plan; corrió el camino degradado-visible)",
                           json.dumps(rec2.get("degraded"))[:180])
            else:
                envblocked("codex e2e verde (falla honesta end-to-end)", str(out2.get("error"))[:180])

        print("\n══ L6 · D4 PROVOCADO: ventana agotada (CLI fake con la señal real) ══")
        stop(procs[0]); procs[0] = None
        ok(wait_port_free(CLI_PORT), "puerto %d liberado (el server real murió de verdad)" % CLI_PORT)
        tmp = Path(tempfile.mkdtemp(prefix="byo-fake-rl-"))
        fake = tmp / "claude"
        fake.write_text(textwrap.dedent("""\
            #!/bin/bash
            if [ "$1" = "auth" ]; then echo '{"loggedIn": true, "subscriptionType": "max"}'; exit 0; fi
            echo 'Claude AI usage limit reached|1783650000 — resets at 18:00' >&2
            exit 1
        """))
        fake.chmod(0o755)
        procs[0] = start_cli_server({"PUPPET_CLAUDE_BIN": str(fake)})
        # preflight: el server que quedó en :8926 DEBE ser el fake (429 directo) — si no,
        # el eje D4 estaría midiendo al claude real (falso negativo del harness, no del producto)
        pcode, pbody = http_json("POST", f"{CLI_BASE}/v1/chat/completions",
                                 {"model": "claude-code-cli",
                                  "messages": [{"role": "user", "content": "x"}]}, timeout=60)
        ok(pcode == 429 and ((pbody.get("error") or {}).get("type") == "throttled"),
           "preflight: el server fake responde 429 throttled", f"http={pcode}")
        sid3 = f"byo-live-window-{int(time.time())}"
        out3, evs3 = run_case("claude_cli", sid3, timeout=200)
        rec3 = out3.get("record") or {}
        wev = next((e for e in evs3 if e.get("type") == "brain_window_exhausted"), None)
        ok(wev is not None, "espinazo: brain_window_exhausted EMITIDO", str([e.get('type') for e in evs3][:10]))
        if wev:
            ok(wev.get("provider_name") == "Claude Code" and wev.get("brain_provider") == "claude_cli",
               "…con el NOMBRE del provider real", json.dumps(wev)[:150])
            ok("agotó" in (wev.get("message") or ""), "…mensaje narrable en humano", (wev.get("message") or "")[:100])
        ok(bool(rec3.get("brain_window_exhausted")), "record.brain_window_exhausted presente (llega al closed)")
        nev = next((e for e in evs3 if e.get("type") == "notice" and e.get("kind") == "degraded"), None)
        if out3.get("ok"):
            ok(bool(rec3.get("degraded")), "el run completó DEGRADADO visible (red oss-direct)", str(rec3.get("degraded"))[:100])
            ok(nev is not None, "espinazo: notice degraded (el switch se narra — ya no se pierde)",
               str([e.get('type') for e in evs3][:12]))
            ok(not str(rec3.get("model_final", "")).startswith("claude-"),
               "model_final honesto = el fallback, no el cerebro caído", str(rec3.get("model_final")))
        else:
            ok(bool(out3.get("error")), "sin fallback disponible → falla HONESTA con error", str(out3.get("error"))[:100])

    finally:
        stop(procs[0])
        stop(procs[1])

    print("\n" + "═" * 64)
    if ENV_BLOCKED:
        print(f"◌ env-blocked ({len(ENV_BLOCKED)}):")
        for e in ENV_BLOCKED:
            print("  - " + e)
    if FAILS:
        print(f"✗ {len(FAILS)} FALLA(S):")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("✓ verify_byo_cli_live: TODO VERDE (con env-blocked honestos arriba)" if ENV_BLOCKED
          else "✓ verify_byo_cli_live: TODO VERDE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
