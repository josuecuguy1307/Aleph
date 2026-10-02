#!/usr/bin/env python3
"""gate_bundle_aleph.py — EL GATE DE BUILD (FIX-P1B · §8, capa 2).

Corre la MISMA lista que la sonda de arranque (`app.phase1.arranque`) pero contra el
ARTEFACTO YA CONSTRUIDO, no contra el repo. Esa es toda la diferencia y es la que importa:
en el repo `assembler.py` siempre está — el archivo se pierde al empaquetar, y sólo se nota
adentro del .app, tres pantallas más tarde, disfrazado de «Error del proveedor».

CÓMO MIDE (y por qué así): levanta el sidecar congelado y le pregunta a ÉL. Un chequeo
estático del listado del bundle es más barato pero miente en los dos sentidos —PyInstaller
mete módulos en el PYZ, saca otros por `excludes`, y `_MEIPASS` reubica los `datas`—, así
que la única respuesta que vale es la del binario que va a correr en la máquina de alguien.
El sidecar ya sabe contestarla: `GET /v1/motor/arranque`.

USO
    # contra el binario congelado (lo levanta y lo mata solo)
    python3 qa/gate_bundle_aleph.py --sidecar dist/aleph-sidecar --port 8278

    # contra el .app ya armado
    python3 qa/gate_bundle_aleph.py --app "/ruta/Aleph.app"

    # contra un sidecar que ya está corriendo
    python3 qa/gate_bundle_aleph.py --url http://127.0.0.1:8278

SALIDA: silencio y exit 0 si el bundle está completo. Si falta algo NUESTRO: el reporte
legible y exit 1 — el build no se certifica.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
from typing import Optional
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PUERTO_DEFECTO = 8278          # el puerto de FIX-P1B. JAMÁS 25374 (ése es el .app de responsable del proyecto).
PROHIBIDOS = {25374}

_RAIZ = Path(__file__).resolve().parents[1]


# ── [OBRA 6a] LA SEGUNDA MITAD DEL GATE: LOS DATOS ────────────────────────────────────────
#
# Este gate nació mirando MÓDULOS y por eso perdió dos archivos de DATOS en silencio
# (`byo_mcp_server.py` y `curated_mcp_registry.json` — medido en la `.app` instalada, Obra 5).
# La sonda de arranque no los podía ver: pregunta por lo que se importa, y un `.py` que se
# ejecuta por ruta o un `.json` que se lee con `read_text()` no se importan nunca.
#
# ⚠️ ACÁ EL TOC **SÍ** ES EL ORÁCULO CORRECTO, y no contradice el docstring de arriba. Ese
# aviso es sobre MÓDULOS: PyInstaller los mete en el PYZ, los saca por `excludes` y `_MEIPASS`
# los reubica, así que listar el archivo no dice si el import va a resolver. Un DATO no tiene
# ninguna de esas ambigüedades: o es una entrada del archivo comprimido o no viaja. Preguntar
# por él es exacto.
#
# La lista NO se escribe acá: se lee de `deploy/fase4/bundle_datos.py`, la misma que usa el
# `.spec` para meterlos. Una sola fuente para poner y para exigir.

def _datos_requeridos() -> list[str]:
    """Los del repo + los de paquete. Las dos listas viven en `bundle_datos.py`; acá se
    concatenan porque para el TOC son la misma pregunta: ¿está esta entrada adentro?"""
    sys.path.insert(0, str(_RAIZ / "deploy" / "fase4"))
    from bundle_datos import DATOS_REQUERIDOS, destinos_de_paquete
    return list(DATOS_REQUERIDOS) + destinos_de_paquete()


def _raiz_onedir(binario: Path) -> Optional[Path]:
    """`_internal/` si este ejecutable es ONEDIR; `None` si es onefile.

    [TANDA 3] PyInstaller 6 arma el onedir como `<dir>/<exe>` + `<dir>/_internal/`, y ahí
    adentro es donde van los `datas` — que en onefile van adentro del CArchive. Es la
    MISMA raíz que el proceso ve como `sys._MEIPASS` (medido con un onedir mínimo:
    `_MEIPASS == <dir>/_internal`), así que preguntar por el disco acá es preguntar por lo
    mismo que el binario va a mirar en runtime."""
    interno = binario.parent / "_internal"
    if interno.is_dir():
        return interno
    # Y EL OTRO LAYOUT ONEDIR: dentro de un `.app`. El bootloader de PyInstaller detecta
    # que su ejecutable está en `…/Contents/MacOS/` y busca su payload en
    # `…/Contents/Frameworks/`, no en `_internal/` al lado. Sin esta rama el guard leía el
    # TOC del stub (11 entradas) y volvía a dar el rojo falso de 47 archivos — esta vez
    # sobre la .app YA instalada. `base_library.zip` es el discriminante: es lo único que
    # sólo existe en una raíz de payload de PyInstaller.
    if binario.parent.name == "MacOS":
        frameworks = binario.parent.parent / "Frameworks"
        if (frameworks / "base_library.zip").is_file():
            return frameworks
    return None


def _datos_que_faltan(binario: Path) -> tuple[list[str], list[str], str]:
    """(faltantes, presentes, nota). `nota` no vacía = NO MEDIBLE — jamás verde por defecto.

    ⚠️ DOS LAYOUTS, DOS LUGARES DONDE MIRAR — y esto dio un ROJO FALSO antes de tenerlo.
    Medido el 2026-08-22: con un sidecar ONEDIR este guard leía el TOC del CArchive del
    ejecutable, que en onedir sólo trae el bootstrap y el PYZ, y reportó 47 archivos «que
    no viajaron» estando todos en `_internal/` al lado. Abortó el build por un defecto que
    no existía. Es la hermana del verde falso de la obra 6d: el TOC no es el bundle, es
    UNA forma del bundle.
    """
    try:
        requeridos = _datos_requeridos()
    except Exception as e:  # noqa: BLE001
        return [], [], f"no pude leer la lista declarada de datos: {e}"

    interno = _raiz_onedir(binario)
    if interno is not None:
        faltan, estan = [], []
        for rel in requeridos:
            ruta = interno / rel.replace("/", os.sep)
            (estan if ruta.exists() else faltan).append(rel)
        return faltan, estan, ""

    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception as e:  # noqa: BLE001
        return [], [], f"PyInstaller no está disponible para leer el TOC ({e})"
    try:
        toc = set(CArchiveReader(str(binario)).toc)
    except Exception as e:  # noqa: BLE001
        return [], [], f"no pude leer el TOC de {binario.name} ({e})"
    faltan, estan = [], []
    for rel in requeridos:
        (estan if rel.replace(os.sep, "/") in toc else faltan).append(rel)
    return faltan, estan, ""


# ── EL TESTIGO QUE NO ES EL TOC ───────────────────────────────────────────────────────────
#
# ⚠️ UN ARCHIVO EN EL TOC YA NOS DIO UN VERDE FALSO (obra 6d): la entrada estaba y el lector
# la buscaba en otra ruta. Para los datos DE PAQUETE el riesgo es el mismo y peor: litellm
# los abre con `importlib.resources.files("litellm")`, así que el archivo puede estar en el
# TOC bajo un destino que `files()` no mira, y el TOC diría que sí.
#
# Así que además de mirar la lista, se le PREGUNTA AL BINARIO. Y se le pregunta por lo único
# que importa: si al arrancar pudo sellar litellm. Ese sellado (`init_litellm`) es
# EXACTAMENTE el código que abre el mapa de precios, y cuando el archivo no viajó el propio
# binario lo dice con todas las letras:
#
#     [litellm] NO se selló ([Errno 2] … model_prices_and_context_window_backup.json)
#               — el camino C/D va por urllib
#
# Esa línea es tolerante A PROPÓSITO (el boot no se cae por esto), y ahí está la trampa que
# costó la pérdida: la app levanta perfecta y el fallo aparece recién cuando alguien corre un
# agente con piezas. El guard la lee y NO la perdona.
_LITELLM_OK = "[litellm] sellado en el arranque"
_LITELLM_MAL = "[litellm] NO se selló"


def _litellm_del_binario(salida: str) -> tuple[int, str]:
    """(rc, detalle) leyendo lo que el binario dijo de sí mismo al arrancar.

    0 = selló · 1 = no selló · 2 = NO MEDIBLE (no dijo nada: perilla apagada o sin salida).
    """
    if not salida:
        return 2, "no pude leer la salida del binario"
    for linea in salida.splitlines():
        if _LITELLM_MAL in linea:
            return 1, linea.strip()
        if _LITELLM_OK in linea:
            return 0, linea.strip()
    return 2, "el binario no dijo nada de litellm (¿PUPPET_LITELLM=0?)"


def _reportar_litellm(rc: int, detalle: str) -> int:
    if rc == 2:
        print(f"⚠ GATE · litellm: NO MEDIBLE — {detalle}")
        return 2
    if rc == 1:
        print("✗ GATE · litellm NO PUDO SELLAR EN EL BINARIO:")
        print(f"    {detalle}")
        print("\n  El arranque lo tolera a propósito, así que la app levanta perfecta y el")
        print("  fallo aparece recién cuando alguien corre un agente con herramientas: todo")
        print("  run por una vía de API que no sea Groq muere antes del primer token.")
        return 1
    print(f"✓ GATE · litellm: el binario selló con sus datos — {detalle}")
    return 0


def _reportar_datos(faltan: list[str], estan: list[str], nota: str) -> int:
    """0 = todos viajaron · 1 = falta alguno · 2 = NO MEDIBLE (se declara, no se rellena)."""
    if nota:
        print(f"⚠ GATE · datos: NO MEDIBLE — {nota}")
        print("  No se certifica por omisión: un guard que no pudo mirar no dice que está bien.")
        return 2
    if faltan:
        print("✗ GATE · DATOS QUE NO VIAJARON EN EL BUNDLE:")
        for r in faltan:
            print(f"    · {r}")
        print("\n  Están declarados en deploy/fase4/bundle_datos.py como REQUERIDOS, y no")
        print("  están adentro del binario. Un dato que no viaja no falla al construir:")
        print("  falla en la máquina del usuario, callado y días después.")
        return 1
    print(f"✓ GATE · datos: los {len(estan)} archivos declarados viajaron en el bundle")
    return 0


def _libre(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _get(url: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _esperar(base: str, segundos: float, proc=None) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if proc is not None and proc.poll() is not None:
            return False                     # el sidecar se murió: no hay a quién preguntar
        try:
            _get(base + "/health", timeout=1.5)
            return True
        except Exception:
            time.sleep(0.35)
    return False


def _binario_del_app(app: Path) -> Path:
    """El sidecar congelado adentro de un .app de Tauri.

    [integración tanda-b2] Buscaba SÓLO `aleph-sidecar` con guión, y Tauri lo instala como
    `aleph_sidecar` con guión bajo (`Contents/MacOS/aleph_sidecar`) — así que el modo `--app`
    de este gate no podía encontrarlo nunca: era un modo que sólo sabía fallar. No se notó
    porque build_app.sh entra por `--sidecar`, que sí anda. Se aceptan las dos grafías.
    """
    nombres = ("aleph_sidecar", "aleph-sidecar")
    for base in (app / "Contents" / "MacOS", app / "Contents" / "Resources"):
        for n in nombres:
            if (base / n).exists():
                return base / n
    for n in nombres:
        hallados = list((app / "Contents").rglob(n))
        if hallados:
            return hallados[0]
    raise SystemExit(f"gate: no encontré el sidecar dentro de {app} "
                     f"(busqué {' o '.join(nombres)})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate de build: ¿viajaron todos los archivos de Aleph?")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sidecar", help="ruta al binario congelado del sidecar")
    g.add_argument("--app", help="ruta al .app construido")
    g.add_argument("--url", help="sidecar YA corriendo (no lo levanta ni lo mata)")
    ap.add_argument("--port", type=int, default=PUERTO_DEFECTO)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.port in PROHIBIDOS:
        raise SystemExit(f"gate: el puerto {a.port} está reservado — usá otro (p.ej. {PUERTO_DEFECTO})")

    proc = None
    binario = None
    if a.url:
        base = a.url.rstrip("/")
    else:
        binario = Path(a.sidecar) if a.sidecar else _binario_del_app(Path(a.app))
        if not binario.exists():
            raise SystemExit(f"gate: no existe {binario}")
        port = a.port
        while not _libre(port):
            port += 1
            if port in PROHIBIDOS:
                port += 1
        base = f"http://127.0.0.1:{port}"
        # TMPDIR PROPIO (mismo criterio que qa/lib/frozen_guard.mjs). El sidecar es un
        # onefile: al arrancar se descomprime entero (~170 MB) en un `_MEIxxxx` dentro del
        # temp, y sólo lo borra al salir LIMPIO. Este gate mata con SIGKILL —tiene que, el
        # bootloader forkea— así que ese directorio quedaba huérfano SIEMPRE: dos corridas
        # dejaron 1,2 GB. Dándole su propia carpeta, borrarla es exacto y no toca la de
        # ninguna sesión hermana (adivinar cuál `_MEI` es nuestro sería el pecado de matar
        # lo ajeno por parecido).
        tmp = tempfile.mkdtemp(prefix="aleph-gate-")
        atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
        home = Path(tmp) / "home"
        home.mkdir()
        env = dict(os.environ, ALEPH_ROLE=os.environ.get("ALEPH_ROLE", "client"),
                   ALEPH_DATA_DIR=tmp, PUPPET_DATA_DIR=tmp,
                   PUPPET_PORT=str(port), PORT=str(port), TMPDIR=tmp,
                   HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                   XDG_CACHE_HOME=str(home / "cache"), XDG_DATA_HOME=str(home / "data"))
        proc = subprocess.Popen([str(binario), "--port", str(port)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
        if not _esperar(base, 90.0, proc):
            salida = ""
            try:
                if proc.poll() is not None and proc.stdout:
                    salida = proc.stdout.read().decode("utf-8", "replace")[-1500:]
            except Exception:
                pass
            _matar(proc)
            print("✗ GATE: el sidecar congelado NO ARRANCÓ.\n"
                  "  Eso ya es la falla que este gate busca: el bundle no corre.\n"
                  + (("\n--- su salida ---\n" + salida) if salida else ""))
            return 1

    try:
        limite = time.time() + 25.0
        while True:
            try:
                v = _get(base + "/v1/motor/arranque?force=true", timeout=5.0)
                break
            except urllib.error.HTTPError as exc:
                # El boot dispara la misma sonda en background. Mientras esa corrida
                # sigue viva, `force=true` responde 503; no es un dictamen del bundle.
                if exc.code != 503 or time.time() >= limite:
                    raise
                time.sleep(0.35)
    except Exception as e:  # noqa: BLE001
        _matar(proc)
        print(f"✗ GATE: no pude consultar la sonda de arranque ({e}).")
        return 1
    finally:
        pass

    _matar(proc)

    # LA SALIDA DEL BINARIO, leída DESPUÉS de matarlo: mientras vive, `stdout` es un pipe y
    # leerlo bloquearía. Al morir, lo que quedó en el buffer se lee entero de una.
    salida_binario = ""
    if proc is not None and proc.stdout is not None:
        try:
            salida_binario = proc.stdout.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            salida_binario = ""

    # ── LOS DATOS · la mitad que este gate no miraba ────────────────────────────────────
    # Se corre SIEMPRE que haya un binario que mirar, y su rojo pesa igual que el de los
    # módulos: un dato que no viaja rompe al usuario lo mismo que un módulo que no viaja.
    if binario is None:
        datos_rc = 2
        faltan_datos: list[str] = []
        print("⚠ GATE · datos: NO MEDIBLE con --url (no hay binario que mirar). "
              "Usá --sidecar o --app para certificar el bundle entero.")
    else:
        faltan_datos, estan_datos, nota_datos = _datos_que_faltan(binario)
        datos_rc = _reportar_datos(faltan_datos, estan_datos, nota_datos)

    # ── EL TESTIGO DEL BINARIO · no alcanza con que el archivo esté listado ──────────────
    if binario is None:
        litellm_rc, litellm_det = 2, "NO MEDIBLE con --url (no levanté yo el binario)"
        _reportar_litellm(litellm_rc, litellm_det)
    else:
        litellm_rc, litellm_det = _litellm_del_binario(salida_binario)
        _reportar_litellm(litellm_rc, litellm_det)

    # NO MEDIBLE (2) no tumba el gate —se declara y se sigue—, pero un NO (1) sí: es
    # exactamente la pérdida que esta obra cierra.
    todo_ok = bool(v.get("ok")) and datos_rc == 0 and litellm_rc != 1

    if a.json:
        v = dict(v)
        v["datos"] = {"faltan": faltan_datos, "rc": datos_rc}
        v["litellm"] = {"rc": litellm_rc, "detalle": litellm_det}
        print(json.dumps(v, indent=2, ensure_ascii=False))
        return 0 if todo_ok else 1
    if todo_ok:
        e = v.get("entorno") or {}
        print(f"✓ GATE: el bundle está completo (build={e.get('aleph_build')} · "
              f"frozen={e.get('frozen')} · {e.get('ms')} ms)")
        return 0
    if not v.get("ok"):
        print(v.get("reporte") or "✗ GATE: bundle incompleto (sin reporte)")
        print("\n✗ EL ARTEFACTO NO SE CERTIFICA: falta código nuestro adentro del bundle.")
    elif datos_rc != 0:
        print("\n✗ EL ARTEFACTO NO SE CERTIFICA: el código está, los datos no.")
    else:
        # El caso del verde falso: la lista dice que sí y el binario dice que no.
        print("\n✗ EL ARTEFACTO NO SE CERTIFICA: los datos figuran en el bundle, pero el")
        print("  binario NO PUDO USARLOS. Estar listado no es estar donde el lector mira.")
    return 1


def _matar(proc) -> None:
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)   # el bootloader FORKEA: matar el grupo
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
