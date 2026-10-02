#!/usr/bin/env python3
"""verify_cinturon_paralelo.py — ¿el cinturón arranca EN PARALELO con el dueño puesto?

EL AGUJERO QUE CIERRA. `restaurador.restaurar_servers` levanta con un
`ThreadPoolExecutor(8)`; `dueno._nacer_de_veras` tomaba `_LOCK_DIFF_PIDS` alrededor de
`start()` ENTERO —spawn **más** handshake— para poder atribuir los pids por diff. Con el
dueño puesto, el pool quedaba anulado: las ocho piezas hacían fila.

CÓMO SE MIDE, y por qué así. **Con servers de fixture que duermen, no con los reales.**
Un server real tarda distinto en cada corrida según el caché de uv/npx: la MISMA pieza dio
7.738 ms en frío y ~300 ms en caliente. Con servers reales el veredicto lo decide el caché
y no el código — y esta vara ya se equivocó una vez por eso: comparó una corrida en frío
contra una en caliente y concluyó al revés. Acá el retardo lo pone el fixture y es igual
en las dos posiciones.

  A · N piezas de T segundos arrancan en ~T, no en N×T
  B · el diff de pids SIGUE atribuyendo bien (el lock no se sacó: se acortó)
  C · un server SIN la costura `al_spawnear` degrada al comportamiento de antes, no a
      uno sin diff
  D · el lock se suelta SIEMPRE, también cuando el arranque falla

    python3 -m inspection.verify_cinturon_paralelo
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parent))

import dueno as DU                                                  # noqa: E402

_FALLOS, _OK = [], 0
#: cuánto duerme cada fixture en su saludo. Grande respecto del spawn (~50 ms) para que
#: la diferencia entre fila y paralelo no se pueda confundir con ruido.
T_SALUDO = 1.5
N_PIEZAS = 5


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


def _spec(n: int) -> dict:
    return {"command": sys.executable,
            "args": [str(_AQUI / "fixtures_cinturon" / "mcp_lento.py")],
            "env": {"ALEPH_MCP_LENTO_S": str(T_SALUDO), "ALEPH_PIEZA": f"p{n}"}}


def _dueno_limpio(tmp: str):
    os.environ["ALEPH_DUENO"] = "on"
    d = DU.Dueno(libro=DU._Libro(Path(tmp) / "procesos.jsonl"), max_vivas=16)
    return d


def a0_el_fixture_de_verdad_duerme(tmp):
    """CONTROL DEL INSTRUMENTO. Si el fixture no durmiera, TODO sería rápido y el caso A
    daría verde con el código en fila — un 0 sin disparador. Un mutante que le sacaba el
    `sleep` sobrevivió a la primera versión de esta vara justamente por esto."""
    print(f"\n[A0] control: UNA pieza sola tarda ~{T_SALUDO}s (el fixture duerme de verdad)")
    d = _dueno_limpio(tmp)
    t0 = time.monotonic()
    d.pedir("sola", spec=_spec(0), user_id="vara", motivo="vara").soltar()
    dt = time.monotonic() - t0
    ok(dt >= T_SALUDO * 0.8,
       f"A0: una pieza sola tarda {dt:.2f}s (>= {T_SALUDO*0.8:.1f}s)",
       f"tardó {dt:.2f}s: el fixture NO está durmiendo y el caso A no puede distinguir "
       f"fila de paralelo")
    d.apagar_todo(motivo="fin A0")


def a2_por_la_costura(tmp):
    """El OTRO camino: un servidor que NO sabe su pid pero SÍ tiene `al_spawnear`.

    Es el del puente SDK. El producto usa hoy el cliente viejo (que sí expone `pid`), así
    que sin este caso la costura sería código que ninguna vara toca — y un mutante que la
    borrara pasaría en verde. Pasó: el mutante M2 sobrevivió a la primera versión."""
    print(f"\n[A2] por la COSTURA: {N_PIEZAS} piezas sin `pid` pero con `al_spawnear`")

    class _ConCostura:
        """Sin `pid` (fuerza el diff) y con `al_spawnear` (permite soltar el lock)."""
        def __init__(self, name, command, args, env=None, rpc_timeout=30.0, cwd=None):
            self.name = name
            self._cmd = [command, *(args or [])]
            self._env = env
            self._p = None
            self._aviso = None

        def al_spawnear(self, fn):
            self._aviso = fn

        def start(self):
            import subprocess
            self._p = subprocess.Popen(self._cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env={**os.environ, **(self._env or {})})
            if self._aviso:                       # ← el hijo YA existe
                self._aviso()
            time.sleep(T_SALUDO)                  # ← el «handshake», fuera del lock
            return True

        def list_tools(self):
            return []

        def call_tool(self, *a, **k):
            return ""

        def diagnostico(self):
            return {}

        def stop(self):
            if self._p:
                self._p.kill()

    d = _dueno_limpio(tmp)
    d._servidor_cls = _ConCostura
    errores = []

    def _una(n):
        try:
            d.pedir(f"cos{n}", spec=_spec(n), user_id="vara", motivo="vara").soltar()
        except Exception as e:                              # noqa: BLE001
            errores.append(f"{n}: {type(e).__name__}: {e}")

    t0 = time.monotonic()
    hilos = [threading.Thread(target=_una, args=(n,)) for n in range(N_PIEZAS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)
    dt = time.monotonic() - t0
    serie = N_PIEZAS * T_SALUDO
    ok(not errores, "A2: arrancaron sin error", "; ".join(errores[:2]))
    print(f"    wall={dt:.2f}s · en fila serían {serie:.1f}s")
    ok(dt < serie * 0.6,
       f"A2: {dt:.2f}s — la costura suelta el lock antes del handshake",
       f"tardó {dt:.2f}s: `al_spawnear` no está soltando el lock")
    d.apagar_todo(motivo="fin A2")


def a_arrancan_en_paralelo(tmp):
    print(f"\n[A] {N_PIEZAS} piezas de {T_SALUDO}s arrancan en ~{T_SALUDO}s, no en "
          f"{N_PIEZAS*T_SALUDO}s")
    d = _dueno_limpio(tmp)
    errores = []
    t0 = time.monotonic()

    def _una(n):
        try:
            pr = d.pedir(f"pieza{n}", spec=_spec(n), user_id="vara", motivo="vara")
            pr.soltar()
        except Exception as e:                              # noqa: BLE001
            errores.append(f"{n}: {type(e).__name__}: {e}")

    hilos = [threading.Thread(target=_una, args=(n,)) for n in range(N_PIEZAS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)
    dt = time.monotonic() - t0
    ok(not errores, "A: las piezas arrancaron sin error", "; ".join(errores[:3]))
    serie = N_PIEZAS * T_SALUDO
    print(f"    wall={dt:.2f}s · en fila serían {serie:.1f}s · en paralelo ~{T_SALUDO:.1f}s")
    ok(dt < serie * 0.6,
       f"A: {dt:.2f}s está más cerca del paralelo que de la fila "
       f"(umbral {serie*0.6:.1f}s)",
       f"tardó {dt:.2f}s con {N_PIEZAS} piezas de {T_SALUDO}s: es FILA, el lock del diff "
       f"está cubriendo el handshake")
    d.apagar_todo(motivo="fin A")


def b_el_diff_sigue_atribuyendo(tmp):
    print("\n[B] el diff de pids sigue atribuyendo bien")
    d = _dueno_limpio(tmp)
    pr = d.pedir("solita", spec=_spec(99), user_id="vara", motivo="vara")
    est = d.estado()
    fila = [v for v in est["vivas"] if v.get("entity_id") == "solita"]
    ok(bool(fila), "B: la conexión está en la tabla", str(est["vivas"])[:200])
    pids = (fila[0].get("pids") if fila else None) or []
    ok(len(pids) >= 1, f"B: y tiene pids atribuidos ({pids})",
       "sin pids el barrido de huérfanos y la lápida quedan ciegos")
    vivo = all(os.path.exists(f"/proc/{p}") or _vive(p) for p in pids) if pids else False
    ok(vivo, "B: y los pids anotados EXISTEN de verdad", str(pids))
    pr.soltar()
    d.apagar_todo(motivo="fin B")


def _vive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def c_sin_la_costura_degrada(tmp):
    print("\n[C] un server SIN `al_spawnear` degrada al camino de antes, no a uno sin diff")
    d = _dueno_limpio(tmp)

    class _SinCostura:
        """El cliente viejo: no tiene `al_spawnear` ni `pid`."""
        def __init__(self, name, command, args, env=None, **kw):
            self.name = name
            self._cmd = [command, *(args or [])]
            self._env = env
            self._p = None

        def start(self):
            import subprocess
            self._p = subprocess.Popen(self._cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env={**os.environ, **(self._env or {})})
            time.sleep(0.3)
            return True

        def list_tools(self):
            return []

        def call_tool(self, *a, **k):
            return ""

        def diagnostico(self):
            return {}

        def stop(self):
            if self._p:
                self._p.kill()

    d._servidor_cls = _SinCostura
    pr = d.pedir("vieja", spec=_spec(1), user_id="vara", motivo="vara")
    fila = [v for v in d.estado()["vivas"] if v.get("entity_id") == "vieja"]
    ok(bool(fila) and (fila[0].get("pids") or []),
       "C: sin la costura, el diff igual atribuye pids",
       f"{fila}")
    pr.soltar()
    d.apagar_todo(motivo="fin C")


def d_el_lock_se_suelta_si_falla(tmp):
    print("\n[D] el lock se suelta también cuando el arranque FALLA")
    d = _dueno_limpio(tmp)
    malo = {"command": sys.executable, "args": ["-c", "import sys; sys.exit(3)"]}
    try:
        d.pedir("rota", spec=malo, user_id="vara", motivo="vara").soltar()
    except Exception:                                       # noqa: BLE001 — se espera
        pass
    # el disparador: si el lock quedó tomado, este `acquire` no entra
    libre = DU._LOCK_DIFF_PIDS.acquire(timeout=3)
    ok(libre, "D: el lock del diff quedó libre después del fallo",
       "quedó TOMADO: el próximo arranque del cinturón se cuelga para siempre")
    if libre:
        DU._LOCK_DIFF_PIDS.release()
    d.apagar_todo(motivo="fin D")


def main() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="verify-cinturon-")
    print("=" * 74)
    print("VERIFY CINTURÓN PARALELO — el dueño no puede anular el pool del restaurador")
    print("=" * 74)
    for f in (a0_el_fixture_de_verdad_duerme, a_arrancan_en_paralelo, a2_por_la_costura,
              b_el_diff_sigue_atribuyendo, c_sin_la_costura_degrada,
              d_el_lock_se_suelta_si_falla):
        try:
            f(tmp)
        except Exception as e:                              # noqa: BLE001
            ok(False, f"{f.__name__} explotó", f"{type(e).__name__}: {e}")
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
