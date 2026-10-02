#!/usr/bin/env python3
"""verify_diseno_config_unica — Diseño tiene UNA config, y es la que su motor abre.

QUÉ DEFECTO VIGILA, Y POR QUÉ NECESITA VARA
--------------------------------------------
Hasta la obra 1, `pack.escribir_config` le dejaba a Diseño un `config/config.toml` en
dialecto de opencode —un archivo con nombre de TOML y contenido JSON— mientras su motor
leía `config/open-codesign/config.toml`, un TOML `version = 3` que produce
`bin/aleph-codesign`. MEDIDO por `atime` contra un `enter` limpio, con línea de base:

    config/config.toml                mtime=21:42:49  atime=21:42:49   ← sólo la escritura
    config/open-codesign/config.toml  mtime=21:42:49  atime=21:42:50   ← el motor lo ABRE

`atime == mtime` en el primero: su única lectura en toda su vida fue la escritura.

Lo que lo vuelve peligroso no es el archivo de más: es que `_exclusividad_del_cerebro`
inyecta `enabled_providers` EN ESE CUERPO. Declararle `brain_exclusivo: True` a Diseño
habría escrito la lista blanca de la Ley 12 en el archivo muerto — el commit correcto, la
clave presente en disco, y CERO efecto. **Un mecanismo que se ve adoptado y no hace nada
no lo vuelve a mirar nadie**, y ninguna vara existente lo hubiera visto: todas miran que
el archivo tenga la clave, y la tenía.

Por eso esta vara no comprueba que el archivo exista con el contenido correcto. Comprueba
las dos cosas que el defecto rompía sin ruido:

  1 · que `pack.py` NO deje ningún archivo que nadie abre (ni el viejo, ni el default)
  2 · que lo que la casa declara CRUCE de verdad hasta el motor, preguntándoselo al motor

El paso 2 corre sólo si hay un runtime de Diseño expandido en disco; si no lo hay, la
vara lo dice como NO MEDIBLE y no como verde. Una señal ausente no es una medición.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "product" / "backend"))

MARCADOR = "CEREBRO-MARCADOR-VARA"
_verde = True
_no_medibles = 0


def ok(cond: bool, titulo: str, detalle: str = "") -> bool:
    global _verde
    _verde = _verde and bool(cond)
    print("%s %s %s" % ("✅" if cond else "❌", titulo, detalle), flush=True)
    return bool(cond)


def no_medible(titulo: str, motivo: str) -> None:
    global _no_medibles
    _no_medibles += 1
    print("⏳ NO MEDIBLE · %s — %s" % (titulo, motivo), flush=True)


def _puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = int(s.getsockname()[1])
    s.close()
    return puerto


def parte_1_sin_archivo_muerto(meta: dict) -> None:
    """Lo que `pack.py` escribe, y lo que ya no escribe."""
    from workspaces import pack

    print("\n── 1 · Diseño no deja un archivo que nadie abre ──")
    ok(meta.get("config_format") == "launcher",
       "1 · la fila declara que su config la escribe el lanzador",
       repr(meta.get("config_format")))
    ok("config_file" not in meta,
       "1 · y no declara `config_file`, que era lo que nombraba al archivo muerto")

    base = Path(tempfile.mkdtemp(prefix="vara-diseno-config-"))
    try:
        os.environ["ALEPH_DATA_DIR"] = str(base)
        destino = pack.escribir_config(
            "diseno", meta, base_aleph="http://127.0.0.1:8330", token="TOKEN-DE-VARA",
            user_id="u-vara", puppet_id=None, space_id="s-vara", puerto=45678,
            chat_id=None, sid="s-vara")
        pack.escribir_ajustes_plugin(
            "diseno", meta, base_aleph="http://127.0.0.1:8330", token="TOKEN-DE-VARA",
            user_id="u-vara", chat_id=None, sid="s-vara")
        cfg = base / "workspaces" / "diseno" / "config"
        sobrantes = sorted(p.name for p in cfg.glob("*")
                           if p.is_file() and p.name != "aleph-pack.json")
        ok(not sobrantes,
           "1 · el único archivo que `pack.py` le escribe es el puntero",
           "sobrantes=%s" % (sobrantes or "ninguno"))
        ok(destino.name == "aleph-pack.json",
           "1 · y `escribir_config` devuelve ese puntero", destino.name)

        # EL MUERTO QUE DEJÓ LA VERSIÓN ANTERIOR. Dejar de escribirlo no lo borra: en una
        # máquina que ya entró antes de la obra, sigue en disco con una sesión vencida.
        viejo = cfg / "config.toml"
        viejo.write_text(json.dumps({"provider": {"aleph": {"options": {
            "apiKey": "TOKEN-VIEJO-DE-UNA-SESION-VENCIDA"}}}, "model": "aleph/cerebro"}),
            encoding="utf-8")
        pack.escribir_config(
            "diseno", meta, base_aleph="http://127.0.0.1:8330", token="TOKEN-DE-VARA",
            user_id="u-vara", puppet_id=None, space_id="s-vara", puerto=45678,
            chat_id=None, sid="s-vara")
        ok(not viejo.exists(), "1 · y se lleva el `config.toml` muerto de la versión anterior")

        # Y LO AJENO NO SE TOCA: mismo nombre, contenido que no es nuestro.
        ajeno = cfg / "config.toml"
        ajeno.write_text('version = 3\nalgo = "del usuario"\n', encoding="utf-8")
        pack.escribir_config(
            "diseno", meta, base_aleph="http://127.0.0.1:8330", token="TOKEN-DE-VARA",
            user_id="u-vara", puppet_id=None, space_id="s-vara", puerto=45678,
            chat_id=None, sid="s-vara")
        ok(ajeno.exists() and "del usuario" in ajeno.read_text(),
           "1 · pero un `config.toml` que NO es nuestro se respeta")
        ajeno.unlink()

        puntero = json.loads((cfg / "aleph-pack.json").read_text())
        ok(puntero.get("cerebro_label") == meta.get("cerebro_label"),
           "1 · el puntero lleva lo que la fila declara (`cerebro_label`)",
           repr(puntero.get("cerebro_label")))
        ok(oct(os.stat(cfg / "aleph-pack.json").st_mode)[-3:] == "600",
           "1 · y el puntero sigue 0600 — adentro viaja la sesión")

        # EL SECRETO NO SE COPIA DOS VECES. Era el otro costo del archivo muerto.
        copias = [p.name for p in cfg.glob("*")
                  if p.is_file() and "TOKEN-DE-VARA" in p.read_text(errors="replace")]
        ok(copias == ["aleph-pack.json"],
           "1 · y el token de sesión queda en UN solo archivo", str(copias))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def parte_2_cruza_hasta_el_motor(meta: dict) -> None:
    """Lo declarado llega al motor. Se le pregunta AL MOTOR, no al archivo."""
    print("\n── 2 · lo que la casa declara, el motor lo muestra ──")
    lanzador = _RAIZ / "third_party" / "codesign" / "bin" / "aleph-codesign"
    if not lanzador.is_file():
        no_medible("2 · el camino hasta el motor", "no está `bin/aleph-codesign`")
        return

    zips = sorted(_RAIZ.glob("third_party/codesign/apps/desktop/release/*.zip"))
    zips += sorted(Path("/var/folders").glob(
        "*/*/T/_MEI*/third_party/codesign/apps/desktop/release/*.zip"))
    if not zips:
        no_medible("2 · el camino hasta el motor",
                   "no hay runtime de Diseño empaquetado (ni en el árbol ni en un "
                   "congelado montado): correr con la `.app` instalada levantada")
        return
    archivo = zips[-1]
    digest = hashlib.sha256(archivo.read_bytes()).hexdigest()

    datos_reales = Path.home() / ("Library/Application Support/Aleph/workspaces/"
                                  "diseno/data/electron-runtime") / digest
    if not datos_reales.is_dir():
        no_medible("2 · el camino hasta el motor",
                   "el runtime de %s… no está expandido; entrá una vez a Diseño"
                   % digest[:12])
        return

    base = Path(tempfile.mkdtemp(prefix="vara-diseno-e2e-"))
    proc = None
    try:
        (base / "arbol" / "bin").mkdir(parents=True)
        (base / "arbol" / "apps" / "desktop" / "release").mkdir(parents=True)
        (base / "config").mkdir()
        (base / "data" / "electron-runtime").mkdir(parents=True)
        shutil.copy2(lanzador, base / "arbol" / "bin" / "aleph-codesign")
        os.symlink(archivo, base / "arbol/apps/desktop/release" / archivo.name)
        # Symlink, no copia: el runtime se LEE. La vara no escribe en el dato del dueño.
        os.symlink(datos_reales, base / "data/electron-runtime" / digest)

        # EL PUNTERO LO ESCRIBE `pack.py`, NO LA VARA — si lo escribiera a mano, esta
        # parte probaría el lanzador y el motor, pero dejaría a `pack.py` FUERA del lazo,
        # y es justamente el eslabón que la obra cambió. Se le pasa una fila con el
        # `cerebro_label` marcado: así el valor recorre casa → puntero → lanzador → motor.
        from workspaces import pack as _pack

        os.environ["ALEPH_DATA_DIR"] = str(base / "casa")
        _pack.escribir_ajustes_plugin(
            "diseno", {**meta, "cerebro_label": MARCADOR},
            base_aleph="http://127.0.0.1:8330", token="", user_id="u-vara",
            chat_id=None, sid="s-vara")
        escrito = base / "casa" / "workspaces" / "diseno" / "config" / "aleph-pack.json"
        if not ok(escrito.is_file(), "2 · `pack.py` escribió el puntero con el marcador"):
            return
        puntero = base / "config" / "aleph-pack.json"
        shutil.copy2(escrito, puntero)
        os.chmod(puntero, 0o600)

        puerto = _puerto_libre()
        env = dict(os.environ)
        env["XDG_CONFIG_HOME"] = str(base / "config")
        env["ALEPH_CODESIGN_DATA_DIR"] = str(base / "data")
        env["ALEPH_PACK_CONFIG"] = str(puntero)
        proc = subprocess.Popen(
            [sys.executable, str(base / "arbol/bin/aleph-codesign"), "--port", str(puerto)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        toml = base / "config" / "open-codesign" / "config.toml"
        for _ in range(100):
            if toml.is_file():
                break
            time.sleep(0.2)
        if not ok(toml.is_file(), "2 · el lanzador escribe el TOML que el motor lee"):
            return
        ok('name = "%s"' % MARCADOR in toml.read_text(),
           "2 · y el marcador cruzó del puntero al TOML")

        salud = None
        for _ in range(150):
            try:
                salud = urllib.request.urlopen(
                    "http://127.0.0.1:%d/.aleph/health" % puerto, timeout=2).read().decode()
                break
            except Exception:                                        # noqa: BLE001
                if proc.poll() is not None:
                    break
                time.sleep(0.4)
        if not ok(salud is not None, "2 · el motor atiende", (salud or "").strip()):
            return

        req = urllib.request.Request(
            "http://127.0.0.1:%d/.aleph/ipc/onboarding%%3Aget-state" % puerto,
            data=json.dumps({"args": []}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        estado = (json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
                  .get("value") or {})
        ok(estado.get("modelPrimary") == MARCADOR,
           "2 · EL MOTOR MUESTRA LO QUE LA CASA DECLARÓ",
           repr(estado.get("modelPrimary")))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    from app.phase1.router import _WORKSPACE_STACKS

    meta = _WORKSPACE_STACKS.get("diseno")
    if meta is None:
        print("❌ no está la fila de Diseño en el registro")
        return 1
    parte_1_sin_archivo_muerto(meta)
    parte_2_cruza_hasta_el_motor(meta)

    print("\n%s%s" % ("VERDE" if _verde else "ROJO",
                      " · %d no medible(s)" % _no_medibles if _no_medibles else ""))
    return 0 if _verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
