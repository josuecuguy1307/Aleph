"""4.2.a — gating de rol de Motor B (D-A). [Casa 2 · Fase 4]

Prueba, en intérpretes limpios (el rol se lee al importar main.py), que:
  - role=client + forge BLOQUEADO (simula el .exe sin forge/): el backend ARRANCA y las rutas
    Motor B (inspect/forge/session/mesa) NO se montan (ausencia, no flag), pero el curado
    (dispatch/resolve) sí.
  - role=control: Motor B monta.

Se mide sobre app.openapi() (app.routes NO aplana los sub-routers en esta versión de FastAPI),
con guarda de >90 rutas para que un cascarón sin rutas no pase las aserciones en falso-verde.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from inspection import zones

_REPO = Path(zones.__file__).resolve().parents[2]

_CLIENT_BLOCK = r'''
FORGE = __FORGE__
_deny = set("inspection." + m.replace("/", ".") for m in FORGE)
_deny |= {"app.phase1.forge_router", "app.phase1.inspect_router",
          "app.phase1.session_router", "app.phase1.mesa_router"}   # phase1 Motor B, excluidos
class _Deny:
    def find_spec(self, name, path=None, target=None):
        if name in _deny:
            raise ModuleNotFoundError("[sim] excluido del cliente: " + name)
        return None
sys.meta_path.insert(0, _Deny())
'''

_DUMP = r'''
import json, sys
__BLOCK__
import app.main
paths = sorted(app.main.app.openapi()["paths"].keys())
sys.stdout.write("PATHS_JSON:" + json.dumps(paths) + "\n")
'''


def _paths(role: str, block: str) -> set:
    script = _DUMP.replace("__BLOCK__", block)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        ["product/backend", "platform", "platform/db", "platform/flywheel"])
    env["ALEPH_ROLE"] = role
    r = subprocess.run([sys.executable, "-c", script], cwd=str(_REPO),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"[{role}] no levantó: stdout={r.stdout!r}\nstderr={r.stderr[-2500:]!r}"
    line = next(l for l in r.stdout.splitlines() if l.startswith("PATHS_JSON:"))
    return set(json.loads(line[len("PATHS_JSON:"):]))


_MOTOR_B = {"/v1/inspect", "/v1/inspect/forge"}   # rutas Motor B inequívocas


def test_client_boots_without_forge_and_motor_b_gated():
    client = _paths("client", _CLIENT_BLOCK.replace("__FORGE__", repr(sorted(zones.FORGE))))
    control = _paths("control", "")
    assert len(client) > 90, f"cliente con pocas rutas ({len(client)}) — ¿cascarón? (falso-verde)"
    gated_off = control - client
    assert _MOTOR_B <= gated_off, f"Motor B NO gated en cliente: {_MOTOR_B - gated_off}"
    assert "/v1/inspect/dispatch" in client, "dispatch (curado) desapareció del cliente"
    assert any(p.startswith("/v1/resolve") for p in client), "resolve (curado) desapareció del cliente"


def test_control_mounts_motor_b():
    control = _paths("control", "")
    assert _MOTOR_B <= control, f"control NO monta Motor B: {_MOTOR_B - control}"
