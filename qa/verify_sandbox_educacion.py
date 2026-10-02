#!/usr/bin/env python3
"""verify_sandbox_educacion.py — LA MANO CON LA QUE EDUCACIÓN DIBUJA. [Educación · artefactos]

Antes de esta obra el tutor no podía producir NI UN artefacto: `exec` y `code_execution`
—sus únicas dos manos en un turno de chat— no montaban porque el pack no le daba backend
de sandbox. El síntoma fue un dibujo ASCII y la frase «The graph can't be rendered as an
image in this chat», que **era verdad**.

Esta vara mide la cadena ENTERA, y las tres partes CORREN código de producción:

  A · EL LAUNCHER, EJECUTADO. No se lee: se copia `platform/workspaces/launchers/deeptutor`
      byte a byte a un árbol temporal con un backend y un `node` de mentira que sólo
      imprimen su entorno, y se lo corre. Lo que se afirma es lo que ESE proceso vio:
      `DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS`, el intérprete resuelto, el shim y el PATH.
      Incluye la trampa que hay que no repetir: el `python3` del SANDBOX no puede ser el
      mismo que arranca el backend del stack (uno tiene matplotlib, el otro las
      dependencias del pack).

  B · LA CADENA DEL STACK, con módulos reales y en las DOS direcciones: con la variable,
      `isolation_level()` deja de ser OFF, `_exec_allowed()` da True y
      `compose_enabled_tools()` monta las dos tools; sin ella, nada de eso pasa. Un solo
      lado no probaría que la causa es la variable.

  C · EL GRÁFICO, DE PUNTA A PUNTA. Se corre matplotlib POR EL SANDBOX DE VERDAD
      (`get_sandbox_service().run`), con el PATH que dejó el launcher en A, y se exige un
      PNG con bytes que `collect_public_artifacts` reconozca como artefacto público con su
      URL `/api/outputs/...`. Es el único assert que prueba que la mano dibuja.

Probala cayendo:
  ALEPH_VARA_ROMPER=sinsandbox   se le borra a la COPIA la línea del export → rojo en A y C
  ALEPH_VARA_ROMPER=sinshim      se le borra a la COPIA el PATH del shim    → rojo en A
  ALEPH_VARA_ROMPER=sinflags     B compone sin `has_exec`/`has_code`        → rojo en B

    product/backend/.venv/bin/python qa/verify_sandbox_educacion.py
      0 → la mano está y dibuja · 1 → no · 2 → no medible (NO cuenta como verde)
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
_STACK = _RAIZ / "third_party" / "deeptutor"
_LAUNCHER = _RAIZ / "platform" / "workspaces" / "launchers" / "deeptutor"
_ROMPER = (os.environ.get("ALEPH_VARA_ROMPER") or "").strip().lower()

#: ⚠️ EL RUNTIME DE ESTA VARA ES SUYO, y se fija ANTES de importar nada del stack:
#: `PathService` resuelve sus directorios con `DEEPTUTOR_HOME` y los cachea. Sin esto, la
#: vara escribiría adentro del runtime REAL de Educación —el del dueño— que es el mismo
#: error que `qa/suite_instalada.mjs` cometió con `aleph.db`.
_HOME = Path(tempfile.mkdtemp(prefix="vara-edu-home-"))
os.environ["DEEPTUTOR_HOME"] = str(_HOME)

_FALLOS: list = []
_temporales: list = []


def ok(nombre: str, cond, detalle: str = "") -> None:
    print(("  ✔ " if cond else "  ✘ ") + nombre + (("  · " + detalle) if detalle else ""))
    if not cond:
        _FALLOS.append(nombre)


def no_medible(motivo: str) -> None:
    print(f"[no medible] {motivo}")
    raise SystemExit(2)


if not _LAUNCHER.is_file():
    no_medible(f"no está el launcher: {_LAUNCHER}")
if not _STACK.is_dir():
    no_medible(f"no está el stack: {_STACK}")


# ══ A · EL LAUNCHER, CORRIDO ═══════════════════════════════════════════════════════════
print("\nA · el launcher, EJECUTADO (copia byte-idéntica, backend y node de mentira)")

_tmp = Path(tempfile.mkdtemp(prefix="vara-edu-sandbox-"))
try:
    # El árbol mínimo que el launcher exige. `ROOT` sale de la ubicación del propio script
    # (`$HERE/../../..`), así que la copia tiene que vivir en la misma forma de árbol.
    destino = _tmp / "arbol" / "platform" / "workspaces" / "launchers"
    destino.mkdir(parents=True)
    copia = destino / "deeptutor"
    fuente = _LAUNCHER.read_text(encoding="utf-8")
    if _ROMPER == "sinsandbox":
        fuente = fuente.replace("export DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=1",
                                "# (mutante) sin sandbox")
    if _ROMPER == "sinshim":
        fuente = fuente.replace('PATH="$EDU_BIN:$PATH"', ': # (mutante) sin shim en el PATH')
    copia.write_text(fuente, encoding="utf-8")
    copia.chmod(0o755)

    standalone = _tmp / "arbol" / "third_party" / "deeptutor" / "web" / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("// de mentira\n", encoding="utf-8")

    # El backend y el node de mentira. NO simulan al stack: escriben su entorno y se van.
    # Es lo único que hace falta para saber con qué entorno los habría arrancado.
    falso = _tmp / "falso"
    (falso / "deeptutor_backend").mkdir(parents=True)
    espejo = _tmp / "entorno.json"
    (falso / "deeptutor_backend" / "deeptutor_backend").write_text(
        "#!/bin/sh\n"
        "python3 -c \"import json,os,sys;json.dump(dict(os.environ),open(sys.argv[1],'w'))\" "
        f"'{espejo}' 2>/dev/null || true\n"
        "exit 0\n", encoding="utf-8")
    (falso / "deeptutor_backend" / "deeptutor_backend").chmod(0o755)
    (falso / "node").write_text("#!/bin/sh\nsleep 3\n", encoding="utf-8")
    (falso / "node").chmod(0o755)

    runtime = _tmp / "runtime"
    (runtime / "data" / "user" / "settings").mkdir(parents=True)

    entorno = dict(os.environ)
    entorno.update({
        "DEEPTUTOR_HOME": str(runtime),
        "ALEPH_PACK_PORT": "58999",
        "ALEPH_DEEPTUTOR_BACKEND": str(falso / "deeptutor_backend"),
        "ALEPH_DEEPTUTOR_NODE": str(falso / "node"),
    })
    entorno.pop("ALEPH_EDUCACION_PYTHON", None)
    entorno.pop("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS", None)
    entorno.pop("ALEPH_EDUCACION_PYTHON_RESUELTO", None)

    proc = subprocess.run([str(copia)], env=entorno, capture_output=True, text=True,
                          timeout=180)
    aviso = (proc.stderr or "").strip().splitlines()
    if not espejo.is_file():
        no_medible("el launcher no llegó a arrancar su backend: "
                   + " · ".join(aviso[-3:] or ["(sin stderr)"]))
    visto = json.loads(espejo.read_text(encoding="utf-8"))

    ok("el launcher prende el sandbox",
       visto.get("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS") == "1",
       f"DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS={visto.get('DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS')!r}")

    resuelto = visto.get("ALEPH_EDUCACION_PYTHON_RESUELTO") or ""
    ok("resolvió un intérprete y lo dejó dicho", bool(resuelto), resuelto or "(vacío)")

    tiene_mpl = False
    if resuelto:
        tiene_mpl = subprocess.run([resuelto, "-c", "import matplotlib"],
                                   capture_output=True).returncode == 0
    ok("y ese intérprete importa matplotlib de verdad", tiene_mpl,
       "probado corriéndolo, no leyendo su ruta")

    shim = runtime / "bin" / "python3"
    primero = (visto.get("PATH") or "").split(os.pathsep)[0]
    ok("el shim del sandbox es el primero del PATH",
       primero == str(runtime / "bin") and shim.is_file() and os.access(shim, os.X_OK),
       f"PATH[0]={primero}")
    ok("y el shim fija MPLBACKEND (el sandbox no deja pasar variables nuestras)",
       shim.is_file() and "MPLBACKEND" in shim.read_text(encoding="utf-8"))

    # LA TRAMPA QUE NO SE PUEDE REPETIR. El backend del stack y el `python3` del sandbox
    # son DOS intérpretes distintos: uno necesita las dependencias del pack, el otro
    # matplotlib. Si el shim se comiera al primero, el pack no levantaría — y el síntoma
    # sería «Educación no arranca», tres capas lejos de la causa.
    ok("el arranque del backend NO quedó apuntando al shim del sandbox",
       str(shim) not in (visto.get("PYTHONPATH", "") + " " + str(_LAUNCHER)),
       "resuelto a ruta absoluta antes de tocar el PATH")
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ══ B · LA CADENA DEL STACK, EN LAS DOS DIRECCIONES ════════════════════════════════════
print("\nB · la cadena del stack, con módulos reales y en los dos sentidos")

if str(_STACK) not in sys.path:
    sys.path.insert(0, str(_STACK))
try:
    from deeptutor.agents._shared.tool_composition import (   # noqa: E402
        ToolMountFlags, compose_enabled_tools, default_optional_tools,
    )
    from deeptutor.multi_user.context import get_current_user  # noqa: E402
    from deeptutor.multi_user.tool_access import exec_override  # noqa: E402
    from deeptutor.services.sandbox import (                  # noqa: E402
        ExecRequest, IsolationLevel, Mount, ResourceLimits, get_sandbox_service,
    )
    from deeptutor.services.sandbox.service import reset_sandbox_service  # noqa: E402
except Exception as exc:                                      # noqa: BLE001
    no_medible(f"no se pudieron importar los módulos del stack: {exc}")


def _nivel(con_variable: bool):
    """El nivel de aislamiento que el stack REPORTA con y sin la variable del launcher."""
    previo = os.environ.get("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS")
    if con_variable:
        os.environ["DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"] = "1"
    else:
        os.environ.pop("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS", None)
    reset_sandbox_service()
    try:
        return asyncio.run(get_sandbox_service().isolation_level())
    finally:
        if previo is None:
            os.environ.pop("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS", None)
        else:
            os.environ["DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"] = previo
        reset_sandbox_service()


sin = _nivel(False)
con = _nivel(True)
ok("sin la variable el aislamiento es OFF (el estado de antes)", sin is IsolationLevel.OFF,
   f"isolation_level()={sin}")
ok("con la variable deja de ser OFF", con is not IsolationLevel.OFF,
   f"isolation_level()={con}")

os.environ["DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"] = "1"
reset_sandbox_service()

# ── LA PUERTA DE `exec`, MEDIDA POR SUS ENTRADAS ───────────────────────────────────────
# `_exec_allowed` (`agentic_pipeline.py:557-588`) vive en un módulo que arrastra el stack
# entero (`pydantic_settings`, `loguru`, …), y este árbol no los tiene: importarlo acá
# sería instalar medio pack para medir cuatro líneas. Así que se hace lo honesto — se
# miden SUS TRES ENTRADAS, que son las que deciden el resultado, y se dice cuál es la
# única parte que sale de leer.
#   `level is APPLICATION`   → medido arriba
#   `get_current_user().is_admin` → medido acá (la rama que toma un turno no-partner)
#   `exec_override() is not False` → medido acá (el backstop de `sandbox.run`)
# Si esta vara se corre con un intérprete que SÍ tenga las dependencias del pack, importa
# la función y la mide de verdad — el bloque de abajo lo intenta primero.
_usuario = get_current_user()
_override = exec_override()
ok("el dueño local es admin (la rama que `_exec_allowed` consulta en APPLICATION)",
   _usuario.is_admin is True, f"{_usuario.id} · role={_usuario.role}")
ok("y el backstop por cuenta no lo apaga", _override is not False,
   f"exec_override()={_override!r}")

permitido = bool(_usuario.is_admin) and _override is not False
_medida_real = False
try:
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline  # noqa: E402

    class _Yo:
        def _is_partner_turn(self, _ctx):
            return False

    permitido = asyncio.run(AgenticChatPipeline._exec_allowed(_Yo(), object()))
    _medida_real = True
except Exception as _e:                                       # noqa: BLE001
    print(f"     (·) [no medible] `_exec_allowed` no se pudo importar acá ({type(_e).__name__}:"
          f" {str(_e)[:60]}); el veredicto de esta línea sale de sus entradas, no de correrla")
ok("`exec` queda permitido para el dueño local", permitido is True,
   "función CORRIDA" if _medida_real else "derivado de las tres entradas medidas "
   "(`agentic_pipeline.py:557-588`)")

# ── LAS DOS TOOLS, MONTADAS POR LA FUNCIÓN DE PRODUCCIÓN ───────────────────────────────
class _Registro:
    """El registro de tools, en lo único que `compose_enabled_tools` le pide."""

    def get_enabled(self, pedidas):
        return [type("T", (), {"name": n})() for n in (pedidas or [])]


_OPCIONALES = default_optional_tools()
_flags = ToolMountFlags(has_exec=permitido, has_code=permitido)
if _ROMPER == "sinflags":
    _flags = ToolMountFlags()
montadas = compose_enabled_tools(
    registry=_Registro(), requested_tools=list(_OPCIONALES),
    optional_whitelist=list(_OPCIONALES), mount_flags=_flags)
faltan = [t for t in ("exec", "code_execution") if t not in montadas]
ok("`compose_enabled_tools()` monta exec y code_execution", not faltan,
   f"{len(montadas)} tools · faltan: {faltan or 'ninguna'}")

sin_flags = compose_enabled_tools(
    registry=_Registro(), requested_tools=list(_OPCIONALES),
    optional_whitelist=list(_OPCIONALES), mount_flags=ToolMountFlags())
ok("y sin las flags NO las monta (la causa es el sandbox, no el catálogo)",
   "exec" not in sin_flags and "code_execution" not in sin_flags,
   f"{len(sin_flags)} tools sin sandbox · {len(montadas) - len(sin_flags)} de diferencia")


# ══ C · EL GRÁFICO, DE PUNTA A PUNTA ═══════════════════════════════════════════════════
print("\nC · el gráfico, por el sandbox REAL y en el directorio público de verdad")

from deeptutor.services.path_service import get_path_service                # noqa: E402
from deeptutor.services.sandbox.artifacts import collect_public_artifacts   # noqa: E402

# EL DIRECTORIO NO SE ELIGE: es el que `CodeExecutionTool` usa cuando el pipeline no le
# pasa uno (`tools/builtin/__init__.py`, rama `get_run_code_workspace_dir()`). Elegir otro
# habría medido un directorio inventado — y `is_public_output_path` lo habría rechazado
# con razón, que es lo que pasó en la primera versión de esta vara.
_dir = Path(get_path_service().get_run_code_workspace_dir()) / "python_vara"
_dir.mkdir(parents=True, exist_ok=True)
try:
    (_dir / "main.py").write_text(
        "import matplotlib.pyplot as plt\n"
        "import numpy as np\n"
        "x = np.linspace(-3, 3, 200)\n"
        "plt.plot(x, x**2, label='x²')\n"
        "plt.plot(x, 6*x - 9, label='tangente en x=3')\n"
        "plt.legend(); plt.savefig('grafica.png', dpi=80)\n"
        "print('dibujado')\n", encoding="utf-8")

    # EL PATH QUE DEJÓ EL LAUNCHER EN A. Se rehace el mismo shim con el intérprete que A
    # midió, para que lo que se pruebe sea el que el pack elige y no el del shell de quien
    # corre la vara. Sin intérprete resuelto no hay nada que medir acá.
    _shim_dir = Path(tempfile.mkdtemp(prefix="vara-edu-bin-"))
    if not resuelto:
        no_medible("A no resolvió intérprete: no hay con qué dibujar")
    (_shim_dir / "python3").write_text(
        '#!/bin/sh\nMPLBACKEND="${MPLBACKEND:-Agg}"; export MPLBACKEND\n'
        f'exec "{resuelto}" "$@"\n', encoding="utf-8")
    (_shim_dir / "python3").chmod(0o755)
    os.environ["PATH"] = str(_shim_dir) + os.pathsep + os.environ.get("PATH", "")
    _temporales.append(_shim_dir)

    if _ROMPER == "sinsandbox":
        os.environ.pop("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS", None)
    reset_sandbox_service()
    r = asyncio.run(get_sandbox_service().run(
        ExecRequest(command="python3 main.py", workdir=str(_dir),
                    mounts=(Mount(host_path=str(_dir), sandbox_path=str(_dir),
                                  read_only=False),),
                    limits=ResourceLimits(timeout_s=120)),
        user_id="local-admin"))
    png = _dir / "grafica.png"
    ok("el sandbox corrió el script sin error",
       r.exit_code == 0 and not r.error,
       f"exit={r.exit_code} err={(r.error or '')[:70]!r} stderr={(r.stderr or '')[:70]!r}")
    ok("y dejó un PNG con bytes", png.is_file() and png.stat().st_size > 1000,
       f"{png.stat().st_size if png.is_file() else 0} bytes")

    # Y QUE EL STACK LO RECONOZCA COMO ENTREGABLE, no como un archivo suelto: es la misma
    # función con la que `code_execution` arma las tarjetas de descarga del turno.
    hallados = collect_public_artifacts(_dir)
    ok("`collect_public_artifacts` lo ve, con su URL /api/outputs",
       len(hallados) == 1 and hallados[0].url.startswith("/api/outputs/")
       and hallados[0].size_bytes > 1000,
       (f"{hallados[0].url} · {hallados[0].size_bytes} b · {hallados[0].mime_type}"
        if hallados else "(ninguno)"))
finally:
    shutil.rmtree(_dir, ignore_errors=True)

shutil.rmtree(_HOME, ignore_errors=True)
for _t in _temporales:
    shutil.rmtree(_t, ignore_errors=True)

print()
if _FALLOS:
    print("ROJO — " + " · ".join(_FALLOS))
    raise SystemExit(1)
print("VERDE — el launcher prende el sandbox, el stack monta las dos tools, y el gráfico")
print("        se dibuja de verdad. Lo que NO dice: que el modelo las LLAME en un turno.")
