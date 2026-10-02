"""EL verde del carve lógico. [Casa 2 · Fase 4]

Prueba, en un intérprete LIMPIO con TODOS los módulos FORGE bloqueados (simulando el `.exe`
del cliente donde forge/ no viaja), que:
  1. cada módulo RESOLVE|SHARED (zones.ships()) IMPORTA sin forge presente, y
  2. la rama miss del dispatcher (NADA/forja) SIN forge falla HONESTO
     — `DispatchResult(ok=False, reason="forjar = premium / control-plane")` — nunca crash ni stub.

Si un edge resolve→forge se re-introduce (import top-level de forge en zona que viaja), (1) se
pone rojo. Es la garantía de que la allowlist de 4.2 va a poder excluir forge sin romper el curado.
"""
import os
import subprocess
import sys
from pathlib import Path

from inspection import zones

_REPO = Path(zones.__file__).resolve().parents[2]  # platform/inspection/zones.py → repo

_CHECK = r'''
import importlib, sys
FORGE = __FORGE__
SHIPS = __SHIPS__

_forge_dotted = set("inspection." + m.replace("/", ".") for m in FORGE)

class _DenyForge:
    """Simula forge/ ausente: cualquier import de un módulo FORGE explota (como en el cliente)."""
    def find_spec(self, name, path=None, target=None):
        if name in _forge_dotted:
            raise ModuleNotFoundError("[carve-sim] forge ausente: " + name)
        return None

sys.meta_path.insert(0, _DenyForge())

# (1) resolve + shared importan sin forge
fails = []
for m in SHIPS:
    mod = "inspection." + m.replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    try:
        importlib.import_module(mod)
    except Exception as e:  # noqa: BLE001
        fails.append((mod, repr(e)))
if fails:
    print("IMPORT-FAIL", fails)
    sys.exit(1)

# (2) la rama miss (NADA) sin forge → honest fail-closed, no crash
from inspection.dispatch.dispatcher import dispatch
from inspection.dispatch.models import Verdict
res = dispatch("x", base_url="https://example.com/api",
               classify_fn=lambda *a, **k: (Verdict.NADA, None), auto=True)
if res.ok is not False or "premium / control-plane" not in (res.reason or ""):
    print("MISS-FAIL", res.ok, repr(res.reason))
    sys.exit(2)

print("OK", len(SHIPS), "ships importan sin forge; miss falla honesto")
'''


def _run_in_clean_interpreter():
    script = (_CHECK
              .replace("__FORGE__", repr(sorted(zones.FORGE)))
              .replace("__SHIPS__", repr(sorted(zones.ships()))))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        ["product/backend", "platform", "platform/db", "platform/flywheel"])
    env["ALEPH_ROLE"] = "client"
    return subprocess.run([sys.executable, "-c", script], cwd=str(_REPO),
                          capture_output=True, text=True, env=env)


def test_resolve_and_shared_import_without_forge_and_miss_fails_honest():
    r = _run_in_clean_interpreter()
    assert r.returncode == 0, (
        f"carve roto — stdout={r.stdout!r}\nstderr={r.stderr[-2500:]!r}")
    assert "OK" in r.stdout, r.stdout
