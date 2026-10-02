"""Minimal frozen entry point for the Finanzas HTTP workspace.

The public ``cli`` package intentionally imports and re-exports the complete interactive
and legacy command surface.  That work is useful for a terminal invocation, but the Aleph
workspace always starts the already-selected HTTP server command.

── Y TAMBIÉN ATIENDE COMO INTÉRPRETE, PORQUE CONGELADOS SOMOS EL `sys.executable` ──────

EL DEFECTO, VISTO EN PANTALLA. Un `backtest` volvía sin correr nada:

    vibe_trading_backend: error: unrecognized arguments:
      .../_internal/backtest/runner.py
      .../runs/20260829_203445_08_7cb70b
    exit_code: 2, sin artefactos generados

El agente había hecho su trabajo —`config.json` y `code/signal_engine.py` escritos— y el
motor nunca arrancó. El usuario recibía un error de argparse en vez de un backtest.

LA CAUSA ES DE NUESTRO EMPAQUETADO, NO DEL PROYECTO DE ARRIBA. `src/core/runner.py`
elige intérprete así:

    candidates = [ .venv/bin/python, .venv/Scripts/python.exe, Path(sys.executable) ]
    ...
    cmd = [python_cmd, str(entry_script)] + cli_args

Suelto eso anda: `sys.executable` ES un Python. Congelado por PyInstaller **no lo es**: es
este binario. Así que el comando terminaba siendo

    vibe_trading_backend  …/backtest/runner.py  …/runs/<id>

y caía en el argparse de `serve_main`, que sólo conoce `--port/--host/--dev`. Ninguna de
las dos partes está mal por su cuenta: upstream asume la semántica de `sys.executable`, y
congelar rompe esa semántica. Quien la rompió la arregla.

QUÉ SE HACE Y QUÉ NO. Si el primer argumento es la ruta de un `.py` que existe, este
binario se comporta como el intérprete que dice ser: corre ESE script con el resto de los
argumentos y su propio `__name__ == "__main__"`. Cualquier otra invocación —incluida la
normal, que empieza con `--port`— va a `serve_main` byte por byte como antes.

NO se toca `third_party/vibetrading`: el arreglo vive en el archivo que es NUESTRO, así que
un `git merge upstream` no lo pisa ni hay que reaplicarlo. Y no se emula `-c` ni `-m`: no
los usa nadie en este camino, y fingir una superficie que no se probó es peor que no
tenerla.
"""

import os
import runpy
import sys

from api_server import serve_main


def _corre_como_interprete(args: list) -> bool:
    """¿Nos invocaron como si fuéramos `python script.py …`?"""
    return bool(args) and args[0].endswith(".py") and os.path.isfile(args[0])


def _modulo_congelado(ruta: str):
    """El script pedido, traducido al MÓDULO que sí viaja adentro del binario.

    [Aleph] POR QUÉ NO ALCANZABA CON EJECUTAR EL ARCHIVO. El despacho de arriba pide que el
    `.py` EXISTA en disco, y adentro del pack no existe: PyInstaller no copia los fuentes,
    los compila al PYZ. MEDIDO contra la .app instalada el 2026-08-29, con el arreglo del
    despacho YA adentro y funcionando:

        ls  …/_internal/backtest/runner.py   → No such file or directory
        el PYZ                               → 74 módulos `backtest.*`, con `backtest.runner`

    O sea: el archivo que el motor manda ejecutar no está, pero el módulo sí. Sin esta
    traducción el despacho no se dispara y el comando cae igual en el argparse — que es
    exactamente el `unrecognized arguments` que el dueño volvió a ver DESPUÉS de instalar
    el arreglo anterior. Aquél era necesario y no suficiente.

    La ruta llega absoluta y colgada de `sys._MEIPASS`
    (`…/_internal/backtest/runner.py`), así que el nombre del módulo es su ruta relativa
    a esa raíz, sin `.py` y con puntos.

    Args:
        ruta: El primer argumento, que termina en `.py` y no existe en disco.

    Returns:
        El nombre del módulo (`"backtest.runner"`), o `None` si no cae bajo la raíz del
        pack o si ese módulo no viaja — y entonces NO se inventa nada: sigue de largo al
        `serve_main`, que dirá su error de siempre.
    """
    raiz = getattr(sys, "_MEIPASS", "")
    if not raiz:
        return None
    ruta = os.path.abspath(ruta)
    if not ruta.startswith(os.path.abspath(raiz) + os.sep):
        return None
    rel = os.path.relpath(ruta, raiz)[: -len(".py")]
    nombre = rel.replace(os.sep, ".")
    # SE COMPRUEBA QUE EL MÓDULO EXISTA, no se confía en el nombre: un `.py` cualquiera
    # bajo la raíz no tiene por qué ser un módulo, y `run_module` de algo ausente
    # explotaría con un error que no dice nada del problema real.
    try:
        import importlib.util
        return nombre if importlib.util.find_spec(nombre) is not None else None
    except Exception:  # noqa: BLE001 — un nombre inválido es simplemente «no es módulo»
        return None


def _corre(accion) -> int:
    """Corre algo como si fuera `__main__` y devuelve SU código de salida.

    El `SystemExit` de un script no es un error nuestro: es su forma de contestar. Se
    respeta tal cual, que es lo que hace un python de verdad y lo que el motor espera leer.
    """
    try:
        accion()
    except SystemExit as salida:
        return int(salida.code or 0)
    return 0


def main(args: list) -> int:
    if _corre_como_interprete(args):
        script = os.path.abspath(args[0])
        # El script tiene que verse a sí mismo en `argv[0]`, igual que bajo un python real.
        sys.argv = [script] + list(args[1:])
        return _corre(lambda: runpy.run_path(script, run_name="__main__"))

    # ── EL MISMO TRATO PARA EL RESTO DE LA CLASE ──────────────────────────────────────
    # No es un caso, es una FAMILIA: upstream trata a `sys.executable` como un python y lo
    # invoca de las formas en que se invoca a un python. Arreglar sólo `script.py` deja las
    # otras esperando a que alguien las pise. Las tres que faltaban:
    #
    #   · `<script.py>` que NO está en disco   → PyInstaller no copia fuentes, los compila
    #                                            al PYZ. Medido: `backtest/runner.py` no
    #                                            existe y `backtest.runner` sí.
    #   · `-m paquete.modulo`                  → la forma canónica de correr un módulo
    #   · `-c "código"`                        → la de correr una línea suelta
    #
    # Lo que NO se hace: inventar. Si el módulo no viaja o el nombre no resuelve, se sigue
    # de largo al `serve_main`, que dirá su error de siempre. Un despacho que se traga
    # cualquier cosa es peor que uno que no existe.
    if args and args[0].endswith(".py"):
        modulo = _modulo_congelado(args[0])
        if modulo:
            sys.argv = [os.path.abspath(args[0])] + list(args[1:])
            return _corre(lambda: runpy.run_module(modulo, run_name="__main__",
                                                   alter_sys=True))

    if len(args) >= 2 and args[0] == "-m":
        sys.argv = [args[1]] + list(args[2:])
        return _corre(lambda: runpy.run_module(args[1], run_name="__main__",
                                               alter_sys=True))

    if len(args) >= 2 and args[0] == "-c":
        sys.argv = ["-c"] + list(args[2:])
        return _corre(lambda: exec(compile(args[1], "<string>", "exec"),  # noqa: S102
                                   {"__name__": "__main__"}))

    return serve_main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
