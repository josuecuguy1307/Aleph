"""harness_falsified_tier.py — LA PROPIEDAD contra el CONTROL REAL. [Casa 2 · Fase 4 · 4.2.d.1]

Levanta el control REAL (uvicorn · ALEPH_ROLE=control · Postgres · muro ON) y corre el RELAY
REAL del cliente contra él, con un Bearer de un usuario NO-premium. El control (su
enforce_construction_premium autoritativo) responde 402 → el relay yield-ea `dispatch.denied`.
Prueba end-to-end que el tier LOCAL del cliente no autoriza forja: la decide el control.

No es un pytest (necesita Postgres + levantar uvicorn). El criterio permanente y determinista
vive en product/backend/tests/test_bridge_relay.py.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

_REPO = Path(__file__).resolve().parents[2]
_PY = str(_REPO / "product" / "backend" / ".venv" / "bin" / "python")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _Body:
    service = "servicio-inexistente"; url = "https://mi-api.example.com"; credential = "k"
    forma = "token"; puppet_id = "p"; slug = None; local_target = False
    auth_in = "query"; auth_param = "api_key"; auth_header = "Authorization"; auth_template = "Bearer {token}"
    validate_path = "/x"; validate_query = None; api_shape_hint = ""
    login_path = "/l"; login_credentials = None; login_token_where = "json"; login_token_key = "t"
    login_inject_where = "header"; login_inject_name = "Authorization"; login_inject_template = "Bearer {token}"
    login_body_format = "json"; session_key = None; login_url = None
    max_rounds = 3; max_calls = 30; max_tokens = 1000; synth_alias = "oss"; seed_probes = None


def main():
    key = Fernet.generate_key().decode()
    port = _free_port()
    ppath = os.pathsep.join([str(_REPO / "product" / "backend"), str(_REPO / "platform"),
                             str(_REPO / "platform" / "db"), str(_REPO / "platform" / "flywheel")])
    env = dict(os.environ)
    env.update({"ALEPH_ROLE": "control", "PUPPET_ENFORCE_MCP_CONSTRUCTION": "1",
                "PUPPET_DB_ENC_KEY": key, "PYTHONPATH": ppath})

    proc = subprocess.Popen(
        [_PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        env=env, cwd=str(_REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1); up = True; break
            except urllib.error.HTTPError:
                up = True; break            # responde (aunque 4xx) = vivo
            except Exception:
                time.sleep(0.5)
        if not up:
            print("[harness] ROJO: el control REAL no levantó (¿Postgres/esquema?). Log:")
            try:
                print((proc.stdout.read() or b"")[:2500].decode("utf-8", "ignore"))
            except Exception:
                pass
            return 2
        print(f"[harness] control REAL vivo en :{port} — ALEPH_ROLE=control · muro ON")

        os.environ["PUPPET_DB_ENC_KEY"] = key
        os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{port}"
        for p in (str(_REPO / "product" / "backend"), str(_REPO / "platform"), str(_REPO / "platform" / "db")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from app.phase1 import repo
        from app.phase1 import dispatch_router

        token = repo.mint_session("harness-free-user")      # NO-premium (no existe / free en control)
        print(f"[harness] Bearer de usuario NO-premium minteado (mismo enc key → control lo acepta)")

        frames = "".join(dispatch_router._relay_forge_to_control(_Body(), "Bearer " + token))
        print("[harness] --- frames que el cliente relayeó desde el control ---")
        print("\n".join(l for l in frames.splitlines() if l.strip())[:800])

        held = ("dispatch.denied" in frames and "tier_gated" in frames and "mcp.forjado" not in frames)
        print("[harness] " + ("VERDE" if held else "ROJO") +
              ": usuario no-premium → control REAL 402 → dispatch.denied · el muro " +
              ("AGUANTA (el tier local no autoriza forja)" if held else "NO aguanta (!!)"))
        return 0 if held else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
