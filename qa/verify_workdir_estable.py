#!/usr/bin/env python3
"""verify_workdir_estable.py — EL WORKDIR DEL ESPACIO, Y LA INVALIDACIÓN QUE NO SE PIERDE.

EL DEFECTO, medido contra la .app instalada: 4 de las 8 piezas del cinturón cambiaban de
huella en CADA turno —`filesystem` (allow-list), `sqlite` (--db-path), `pysandbox`,
`officecli`—, porque las cuatro referencian `${PUPPET_WORKDIR}` y ése era un `mkdtemp` por
run (`executor.py`, la línea del `run_workdir`). Huella nueva = proceso nuevo, así que el
dueño no podía reusar nada; el restore es paralelo y el reloj lo pone la más lenta, o sea
que sostener las otras cuatro no compraba un milisegundo.

QUÉ MIDE ESTA VARA — las dos mitades, porque una sin la otra es una trampa:

  A · ESTABLE: dos turnos del MISMO espacio dan la MISMA carpeta. Sin esto no hay reuso.
  B · AISLADA: espacios distintos, workspaces distintos y el camino sin espacio dan
      carpetas DISTINTAS. Un workdir estable que además fuera compartido entre espacios
      sería una fuga, no una optimización.
  C · LA RUTA SE SANEA: este string arma un path. Un `space_id` con `/` o `..` escribiría
      fuera de `run_outputs` y le abriría al server `filesystem` una allow-list en
      cualquier lado del disco. Lo que no tiene forma de id cae al `run_id`.
  D · LA INVALIDACIÓN SIGUE GRATIS: el mutante del encargo. Tocar la config —la allow-list
      del server— tiene que dar HUELLA NUEVA aunque el workdir no se mueva. Si esto se
      rompiera, un cinturón editado seguiría atendido por el proceso viejo, que miente.

  E · LA COSECHA NO RE-CAPTURA: con el dir compartido, `_capture_workdir_outputs` hace
      `rglob("*")` sobre todo, así que el .xlsx del turno 3 volvería a entrar como obra del
      turno 5 — el mismo archivo una vez por turno en la Biblioteca. El corte por `mtime`
      es lo que lo impide, y acá se mide con archivos de verdad.

  python3 qa/verify_workdir_estable.py
"""
import os, sys, time, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "product" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform"))
os.environ["ALEPH_WORKDIR_ESPACIO"] = "on"

malas = []
def ok(n, c, d=""):
    print(f"  {'✅' if c else '❌'} {n}" + (f" — {d}" if d and not c else (f" · {d}" if d else "")))
    if not c: malas.append(n)

from app.phase1.executor import _carpeta_del_turno, _capture_workdir_outputs

print("\nA · dos turnos del mismo HILO → la MISMA carpeta")
# ⚠️ LA IDENTIDAD ES EL CHAT, NO EL ESPACIO. Medido contra la DB: tres turnos seguidos
# traían `space_id` DISTINTO (space-…-1, -3, -5) y el mismo `chat_id`. El espacio es del
# TURNO. La vara siembra los dos distintos a propósito: si sembrara uno solo, usar el
# campo equivocado pasaría desapercibido — que es exactamente lo que pasó, y costó un build.
a = _carpeta_del_turno("chat-abc", "space-uno-1", "run-uno")
b = _carpeta_del_turno("chat-abc", "space-dos-2", "run-dos")
ok("misma carpeta aunque cambien space_id y run_id", a == b, a)

print("\nB · el aislamiento que se conserva")
ok("otro hilo → otra carpeta", a != _carpeta_del_turno("chat-xyz", "space-uno-1", "run-tres"))
ok("sin hilo, cae al espacio", _carpeta_del_turno(None, "space-solo", "run-x") == "hilo-space-solo")
ok("sin hilo ni espacio → carpeta del run",
   _carpeta_del_turno(None, None, "run-x") == "run-x")
ok("vacíos → carpeta del run", _carpeta_del_turno("", "", "run-y") == "run-y")

print("\nC · la ruta se sanea (esto arma un path)")
for veneno in ("../../etc", "a/b", "..", "/abs", "x" * 200, "  "):
    got = _carpeta_del_turno(veneno, None, "run-seguro")
    ok(f"«{veneno[:14]}» no arma ruta", got == "run-seguro", f"dio {got!r}")

print("\nD · MUTANTE: config tocada → huella NUEVA (la invalidación no se pierde)")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform" / "inspection"))
import dueno as _du                                             # noqa: E402
wd = tempfile.mkdtemp(prefix="vara-wd-")
h1 = _du.huella("npx", ["server-filesystem", wd], {"A": "1"}, None)
h2 = _du.huella("npx", ["server-filesystem", wd], {"A": "1"}, None)
ok("misma config + mismo workdir → MISMA huella (hay reuso)", h1 == h2, h1[:12])
h3 = _du.huella("npx", ["server-filesystem", wd, "/otro"], {"A": "1"}, None)
ok("allow-list tocada → huella NUEVA (respawn)", h3 != h1, f"{h1[:8]} → {h3[:8]}")
h4 = _du.huella("npx", ["server-filesystem", wd], {"A": "2"}, None)
ok("env tocado → huella NUEVA", h4 != h1, f"{h1[:8]} → {h4[:8]}")

print("\nE · la cosecha toma SÓLO lo que este turno tocó")
raiz = Path(tempfile.mkdtemp(prefix="vara-cosecha-"))
(raiz / "de-un-turno-viejo.txt").write_text("vieja")
time.sleep(1.1)
corte = time.time()
time.sleep(0.1)
(raiz / "de-este-turno.txt").write_text("nueva")
vistos = []
class _RepoFalso:
    @staticmethod
    def create_output(conn, **kw):
        vistos.append(Path(kw.get("uri") or kw.get("path") or "").name)
        return {"id": "x"}
import app.phase1.executor as _ex                                # noqa: E402
_real = _ex.phase1_repo
_ex.phase1_repo = _RepoFalso
try:
    _capture_workdir_outputs(None, "run-z", str(raiz), desde=corte)
    ok("no re-captura la obra del turno anterior", "de-un-turno-viejo.txt" not in vistos,
       f"capturó {vistos}")
    ok("sí captura la de este turno", "de-este-turno.txt" in vistos, f"capturó {vistos}")
    vistos.clear()
    _capture_workdir_outputs(None, "run-z", str(raiz), desde=None)
    ok("sin corte, el barrido completo sigue igual (camino sin espacio)", len(vistos) == 2,
       f"capturó {vistos}")
finally:
    _ex.phase1_repo = _real

print("\n" + "=" * 74)
if malas:
    print(f"ROJO — {len(malas)}: {' · '.join(malas)}"); sys.exit(1)
print("TODO VERDE — el workdir del espacio es estable, aislado, saneado, y no re-cosecha")
print("=" * 74)
