#!/usr/bin/env python3
"""verify_finanzas_interprete — el binario congelado de Finanzas atiende como intérprete.

POR QUÉ. `src/core/runner.py` lanza el backtest con `[sys.executable, runner.py, run_dir]`.
Suelto eso anda porque `sys.executable` ES un Python; congelado por PyInstaller es el
binario del pack, y el comando cae en el argparse de `serve_main`:

    vibe_trading_backend: error: unrecognized arguments:
      .../backtest/runner.py  .../runs/20260829_203445_08_7cb70b   (exit 2)

Medido en la pantalla del dueño: el agente escribió `config.json` y `signal_engine.py`, y
el motor no arrancó nunca.

QUÉ MIDE. El despacho de `deploy/fase4/vibetrading_pack_serve.py`, aislado y sin congelar:
con la ruta de un `.py` por delante tiene que CORRER ESE SCRIPT; con cualquier otra cosa
tiene que ir a `serve_main` sin tocar los argumentos.

⚠️ NO MIDE EL BINARIO. Es una vara del despacho, no del pack congelado — para eso hace
falta un build de Finanzas y un `backtest` de punta a punta. Se dice acá para que nadie lea
su verde como «el backtest ya corre en la .app».

Uso:  python3 qa/verify_finanzas_interprete.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ENTRY = pathlib.Path(__file__).resolve().parents[1] / "deploy/fase4/vibetrading_pack_serve.py"


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aleph-fin-"))
    guion = tmp / "runner.py"
    guion.write_text(
        "import sys\n"
        "print('CORRIO', sys.argv[0].endswith('runner.py'), sys.argv[1:])\n"
        "sys.exit(7)\n", encoding="utf-8")

    # Se carga el módulo por RUTA y se le pone un `serve_main` de mentira: así la vara no
    # necesita el árbol de Finanzas importable, y además puede ver si `serve_main` fue
    # llamado y con qué.
    import importlib.util
    marca = {}

    def _serve_main_falso(args):
        marca["args"] = list(args)
        return 0

    spec = importlib.util.spec_from_file_location("_entry_fin", ENTRY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["api_server"] = type(sys)("api_server")
    sys.modules["api_server"].serve_main = _serve_main_falso        # type: ignore[attr-defined]
    spec.loader.exec_module(mod)                                    # type: ignore[union-attr]

    fallas = []

    # EL ENTRYPOINT SIN DESPACHO NO TIENE `main`: eso es el defecto, no un accidente de la
    # vara. Se dice así y se corta, en vez de reventar con un AttributeError que obliga a
    # leer el traceback para entender qué pasó.
    if not hasattr(mod, "main"):
        print("❌ el entrypoint no expone `main(args)`: manda TODO a `serve_main`, así que")
        print("   `vibe_trading_backend <runner.py> <run_dir>` cae en su argparse (exit 2).")
        return 1

    # 1 · con un .py por delante → corre el script y devuelve SU código
    salida = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys,types;"
         "m=types.ModuleType('api_server');m.serve_main=lambda a:0;sys.modules['api_server']=m;"
         "s=importlib.util.spec_from_file_location('e',%r);"
         "mo=importlib.util.module_from_spec(s);s.loader.exec_module(mo);"
         "sys.exit(mo.main([%r,'RUNDIR']))" % (str(ENTRY), str(guion))],
        capture_output=True, text=True)
    if "CORRIO True ['RUNDIR']" not in salida.stdout:
        fallas.append("no corrió el script: stdout=%r stderr=%r"
                      % (salida.stdout[-200:], salida.stderr[-300:]))
    if salida.returncode != 7:
        fallas.append("no devolvió el código del script (esperaba 7, dio %d)" % salida.returncode)

    # 2 · invocación normal → va a serve_main, con los argumentos intactos
    marca.clear()
    mod.main(["--port", "9999"])
    if marca.get("args") != ["--port", "9999"]:
        fallas.append("la invocación normal no llegó intacta a serve_main: %r" % (marca.get("args"),))

    # 3 · un .py que NO existe no se intercepta
    marca.clear()
    mod.main(["/no/existe/x.py"])
    if marca.get("args") != ["/no/existe/x.py"]:
        fallas.append("un .py inexistente se interceptó en vez de ir a serve_main")

    # 4 · un argumento que CASUALMENTE termina en `.py`, y ADEMÁS existe, no se intercepta:
    #     la guarda mira `args[0]`, no «hay un .py en algún lado». Es el caso que preguntó
    #     desktop-88 y se mide en vez de afirmarse.
    marca.clear()
    mod.main(["--config", str(guion)])
    if marca.get("args") != ["--config", str(guion)]:
        fallas.append("`--config <algo.py>` se interceptó como script: %r" % (marca.get("args"),))

    # 5 · …y tampoco si el `.py` real viene DESPUÉS de una bandera con valor.
    marca.clear()
    mod.main(["--port", "9999", str(guion)])
    if marca.get("args") != ["--port", "9999", str(guion)]:
        fallas.append("un `.py` que no es el primer argumento se interceptó: %r"
                      % (marca.get("args"),))

    # ── 6 a 10 · LA CLASE ENTERA, no sólo el caso que mordió ──────────────────────────
    # Upstream trata a `sys.executable` como un python, así que lo invoca de las formas en
    # que se invoca a un python. MEDIDO contra la .app instalada el 2026-08-29, con el
    # despacho de `script.py` ya adentro y funcionando:
    #     ls  …/_internal/backtest/runner.py  → No such file or directory
    #     el PYZ                              → 74 módulos `backtest.*`, con `backtest.runner`
    # PyInstaller no copia los fuentes: los compila. Por eso pedir `os.path.isfile` dejaba
    # el despacho sin disparar y el comando caía igual en el argparse — el mismo
    # `unrecognized arguments` que se volvió a ver DESPUÉS de instalar el arreglo previo.
    raiz = tmp / "_MEIPASS_falso"
    paquete = raiz / "paquete_de_prueba"
    paquete.mkdir(parents=True, exist_ok=True)
    (paquete / "__init__.py").write_text("", encoding="utf-8")
    (paquete / "corredor.py").write_text(
        "import sys\nprint('CORRIO_COMO_MODULO', sys.argv[1:])\nsys.exit(9)\n",
        encoding="utf-8")

    sys.path.insert(0, str(raiz))
    viejo_mei = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = str(raiz)                                        # type: ignore[attr-defined]
    try:
        # 6 · un `.py` que NO está en disco pero viaja como módulo bajo la raíz del pack
        nombre = mod._modulo_congelado(str(paquete / "corredor.py"))
        if nombre != "paquete_de_prueba.corredor":
            fallas.append("un `.py` bajo la raíz no se tradujo a su módulo: %r" % (nombre,))

        # 7 · uno FUERA de la raíz no se traduce: no se inventa un módulo
        if mod._modulo_congelado("/tmp/nada/que/ver/con/el/pack.py") is not None:
            fallas.append("se tradujo un `.py` que no cuelga de la raíz del pack")

        # 8 · un nombre que NO es módulo tampoco: se comprueba, no se confía
        (raiz / "suelto.py").write_text("x = 1\n", encoding="utf-8")
        if mod._modulo_congelado(str(raiz / "no_existe_este.py")) is not None:
            fallas.append("se tradujo un nombre que no resuelve a ningún módulo")

        # 9 · `-m paquete.modulo`, la forma canónica
        marca.clear()
        codigo = mod.main(["-m", "paquete_de_prueba.corredor", "--x", "1"])
        if codigo != 9 or "args" in marca:
            fallas.append("`-m modulo` no se corrió como módulo (código %r, serve_main %r)"
                          % (codigo, marca.get("args")))
    finally:
        if viejo_mei is None:
            delattr(sys, "_MEIPASS")
        else:
            sys._MEIPASS = viejo_mei                                # type: ignore[attr-defined]
        sys.path.remove(str(raiz))

    # 10 · `-c "código"`, la de correr una línea suelta
    marca.clear()
    codigo = mod.main(["-c", "import sys; sys.exit(11)"])
    if codigo != 11 or "args" in marca:
        fallas.append("`-c código` no se ejecutó (código %r, serve_main %r)"
                      % (codigo, marca.get("args")))

    if fallas:
        print("❌ %d falla(s):" % len(fallas))
        for f in fallas:
            print("   ·", f)
        return 1
    print("✅ 10/10 — script en disco · script que sólo viaja como módulo · `-m` · `-c`,")
    print("        y la invocación normal, `--config algo.py` y un `.py` que no va")
    print("        primero NO se interceptan (no se inventa un módulo que no viaja)")
    print("⚪ [no medible acá] que el backtest corra en la .app: eso pide build de Finanzas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
