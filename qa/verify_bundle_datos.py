#!/usr/bin/env python3
"""verify_bundle_datos.py — LA VARA DE LA OBRA 6a: que viaje lo que el repo tiene.

    python3 qa/verify_bundle_datos.py --nuevo <sidecar recién construido>
                                      [--viejo /Applications/Aleph.app]
                                      [--sin-lector <un .app con los datos y el lector roto>]

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ MIDE, Y POR QUÉ ASÍ

La Obra 5 midió en `/Applications/Aleph.app` que dos archivos que el repo tiene no viajaban
en el bundle: el PUENTE `byo_mcp_server.py` (por eso toda pieza HTTP aterrizaba verde y
amanecía rota) y el override curado `curated_mcp_registry.json` (por eso `pinned_servers()`
valía 8 en el repo y **0** en la app: ningún ✓ oficial existía y el anti-impostor duro por
pin estaba muerto). Las dos pérdidas fueron MUDAS.

⚠️ **EL NEGATIVO ES LA MITAD QUE IMPORTA.** Un guard que nunca cortó no prueba nada: puede
estar mirando la nada y salir verde. Por eso el testigo 1 corre el guard NUEVO contra un
bundle que se SABE incompleto —el que está instalado hoy— y exige que ROJEE, nombrando los
dos archivos. Sin ese rojo, el verde del testigo 2 no vale.

⚠️ **NO MEDIBLE SE DECLARA, JAMÁS SE RELLENA.** Si falta un binario que mirar, el testigo
dice que no pudo medir y la vara sale distinto de verde. Un guard que no pudo mirar no está
diciendo que todo está bien.

──────────────────────────────────────────────────────────────────────────────────────────
[OBRA 6d] LA PREGUNTA QUE FALTABA: ¿EL CÓDIGO LO ENCUENTRA?

Los testigos 1/2/4a/4b/4c salieron **los cinco verdes** sobre un build cuyo catálogo público
devolvía **500 en todas sus rutas**. Miran el TOC y el `_MEIPASS` —si el archivo ESTÁ— y ésa
es otra pregunta. El curado viajaba perfecto y su lector lo buscaba en el TMPDIR del sistema,
porque `mcp_registry` vive en el PYZ y su `parents[2]` cae en el PADRE de `_MEIPASS`.

El testigo 5 le pregunta al BINARIO por `/v1/catalog/search?source=registry` y exige 200 con
al menos un ✓. Un dato que viaja y que nadie encuentra es, para el usuario, un dato que no
viajó — y esta vara ahora lo sabe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "deploy" / "fase4"))
sys.path.insert(0, str(RAIZ / "platform"))

FALLOS: list[str] = []
RESULTADO: dict[str, object] = {}


def ok(nombre: str, cond: bool, detalle=None) -> bool:
    RESULTADO[nombre] = bool(cond)
    print(("✅ " if cond else "❌ ") + nombre + (f": {detalle}" if detalle is not None else ""))
    if not cond:
        FALLOS.append(nombre)
    return bool(cond)


def no_medible(nombre: str, motivo: str) -> None:
    RESULTADO[nombre] = "NO_MEDIBLE"
    print(f"⚪ {nombre}: NO MEDIBLE — {motivo}")
    FALLOS.append(f"{nombre} (no medible)")


def _binario_del_app(app: Path) -> Path:
    return app / "Contents" / "MacOS" / "aleph_sidecar"


def _gate(binario: Path, puerto: int) -> tuple[int, str]:
    """Corre el guard real (no una copia de su lógica) y devuelve (exit, salida)."""
    r = subprocess.run(
        [sys.executable, str(RAIZ / "qa" / "gate_bundle_aleph.py"),
         "--sidecar", str(binario), "--port", str(puerto)],
        capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stdout + r.stderr)


def _toc(binario: Path) -> set[str]:
    from PyInstaller.archive.readers import CArchiveReader
    return set(CArchiveReader(str(binario)).toc)


def _meipass_de(binario: Path, puerto: int) -> Path | None:
    """Levanta el sidecar en un TMPDIR propio y devuelve su `_MEIxxxx` — el directorio REAL
    al que `${PUPPET_REPO}` resuelve en runtime. Es la única forma de contestar «¿el proceso
    encuentra el puente?» sin creerle a una lista."""
    tmp = tempfile.mkdtemp(prefix="aleph-vara6a-")
    env = dict(os.environ, ALEPH_ROLE="client", ALEPH_DATA_DIR=tmp, PUPPET_DATA_DIR=tmp,
               TMPDIR=tmp, PUPPET_PORT=str(puerto), PORT=str(puerto))
    proc = subprocess.Popen([str(binario), "--port", str(puerto)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        limite = time.time() + 90
        while time.time() < limite:
            mei = sorted(Path(tmp).glob("_MEI*"))
            if mei and (mei[0] / "platform").exists():
                return mei[0]
            if proc.poll() is not None:
                return None
            time.sleep(0.5)
        return None
    finally:
        # se copia lo que hace falta ANTES de matar: el bootloader borra su _MEI al salir
        pass


def _matar(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass


def _sellos_del_binario(binario: Path, puerto: int) -> dict:
    """[OBRA 6d] LE PREGUNTA AL CÓDIGO, NO AL TOC. Levanta el sidecar y le pide el catálogo
    público: `pinned_servers()` sólo puede contestar si el LECTOR encuentra el archivo.

    Ésta es la pregunta que faltaba y que costó una instalación. Los testigos 4a/4b/4c miran
    el TOC y el `_MEIPASS` —o sea, si el archivo ESTÁ— y salieron los tres verdes sobre un
    build cuyo catálogo público devolvía 500 en todas sus rutas. Un dato que viaja y que
    nadie encuentra es, para el usuario, un dato que no viajó.

    Devuelve {ok, http, items, sellos, detalle}. `ok` sólo es True con HTTP 200 y al menos
    un ✓ oficial: un 200 con cero sellos es exactamente el síntoma de que el curado no se
    está leyendo, que es lo que este testigo existe para ver.
    """
    import urllib.error
    import urllib.request

    tmp = tempfile.mkdtemp(prefix="aleph-vara6d-")
    # ⚠️ TMPDIR PROPIO Y APARTE DEL DATA DIR: `_MEIPASS` cuelga del TMPDIR, y la ruta rota
    # que este testigo persigue se calcula desde ahí. Compartirlos escondería el bug.
    env = dict(os.environ, ALEPH_ROLE="client", ALEPH_DATA_DIR=tmp, PUPPET_DATA_DIR=tmp,
               TMPDIR=tmp, PUPPET_PORT=str(puerto), PORT=str(puerto))
    proc = subprocess.Popen([str(binario), "--port", str(puerto)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    base = f"http://127.0.0.1:{puerto}"
    try:
        limite = time.time() + 120
        vivo = False
        while time.time() < limite:
            if proc.poll() is not None:
                return {"ok": False, "http": None, "detalle": "el sidecar no arrancó"}
            try:
                urllib.request.urlopen(base + "/health", timeout=2).read()
                vivo = True
                break
            except Exception:
                time.sleep(0.4)
        if not vivo:
            return {"ok": False, "http": None, "detalle": "no respondió /health en 120s"}
        url = base + "/v1/catalog/search?q=stripe&source=registry&limit=20"
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                cuerpo = json.loads(r.read().decode("utf-8", "replace"))
                http = r.status
        except urllib.error.HTTPError as e:
            return {"ok": False, "http": e.code,
                    "detalle": f"HTTP {e.code} — el lector no encontró el dato"}
        except Exception as e:  # noqa: BLE001
            return {"ok": None, "http": None, "detalle": f"sin red al registro: {e}"}
        items = cuerpo.get("items") or []
        if cuerpo.get("registry_status") == "unreachable" or not items:
            # Sin candidatos no hay a quién ponerle el sello: no se puede concluir nada.
            return {"ok": None, "http": http, "items": len(items),
                    "detalle": "el registro público no devolvió candidatos"}
        sellos = [i.get("server_name") for i in items if (i.get("badge") or {}).get("verified")]
        return {"ok": http == 200 and len(sellos) > 0, "http": http, "items": len(items),
                "sellos": len(sellos), "ejemplo": (sellos[0] if sellos else None)}
    finally:
        _matar(proc)
        shutil.rmtree(tmp, ignore_errors=True)


# ── [OBRA 6d] EL GUARD DE CLASE ─────────────────────────────────────────────────────────
# Directorios de DATOS que viajan (deben leerse desde `resource_root()`) — los `_DATA_DIRS`
# del `.spec`. Si el spec suma uno, sumalo acá.
#
# ⚠️ LOS `_TARGET_DIRS` NO ENTRAN, y la distinción la hace el propio spec: son «los targets
# planos cargados por ruta (aleph_paths.load_module_by_path)» — CÓDIGO, no datos. A esos se
# les pasa una ruta del árbol a propósito, porque el loader ya es frozen-aware y la reubica a
# `resource_root()`; y varios sólo alimentan un `sys.path.insert`, donde una ruta inexistente
# es inofensiva (los imports resuelven por el PYZ). Meterlos acá acusaba a `forge`,
# `transcribe`, `transcripts_cli` e `inspect_run` de un bug que no tienen.
_DIRS_DEL_SPEC = ("catalog", "product/belts", "product/app/design", "docs/guia")
# ⚠️ Y LOS DATOS SUELTOS, derivados de `DATOS_REQUERIDOS` — la MISMA lista que el `.spec` usa
# para meterlos y el gate para exigirlos. Sin esto el guard no veía `platform/inspection/data`
# y por lo tanto NO PODÍA ACUSAR AL CASO ÍNDICE: salía verde sobre el árbol que tenía el bug.
# Lo destapó auditar el guard contra el árbol de main antes de mergear.
from bundle_datos import DATOS_REQUERIDOS as _DATOS_DECLARADOS  # noqa: E402

_DIRS_QUE_VIAJAN = tuple(sorted(set(_DIRS_DEL_SPEC) | {
    d.rsplit("/", 1)[0] for d in _DATOS_DECLARADOS if "/" in d}))
# Módulos que viajan como ARCHIVOS (`_TARGET_DIRS`): ahí `__file__` es real y `parents[N]`
# SÍ resuelve. Medido contra el bundle, no supuesto: `recipe_assembler.py` existe en disco
# bajo `<_MEIPASS>/platform/assembler/`, y `mcp_registry.py` no (vive en el PYZ).
_VIAJAN_COMO_ARCHIVO = ("platform/gates/", "platform/connectors/", "platform/assembler/",
                        "platform/db/", "platform/flywheel/", "platform/sanitizer/")


def _clase_parents_a_datos() -> list[str]:
    """Módulos del PYZ que componen una ruta a un dir QUE VIAJA desde un `parents[N]` crudo.

    Ésa es la clase entera del bug, en una sola frase: `parents[N]` es la raíz del ÁRBOL, y
    congelado el árbol no existe — sólo `_MEIPASS`. En un módulo que viaja como archivo el
    cálculo sale bien de casualidad (su `__file__` es real); en uno del PYZ el `__file__` es
    sintético y el resultado cae en el TMPDIR del sistema.

    ⚠️ NO EXIGE PROBAR QUE SE LEE, y es a propósito. La primera versión pedía ver un
    `.read_text()`/`.exists()` sobre la variable, y por eso se le escapaba
    `_BELT_DIRS = [_REPO / "catalog" / "templates", …]`: la lectura ocurre sobre la variable
    del `for`, no sobre la lista. Componer una ruta a un dir que viaja sólo tiene sentido para
    usarla, así que la composición ALCANZA como acusación. Un falso positivo se resuelve
    usando `resource_root()`, que es lo correcto igual.
    """
    import re
    DEF = re.compile(r"^\s*(_?[A-Za-z][A-Za-z0-9_]*)\s*=\s*"
                     r"(?:Path\(__file__\)\.resolve\(\)|_?[A-Za-z][A-Za-z0-9_]*)\.parents\[\d\]\s*$")
    malos: list[str] = []
    for py in sorted(RAIZ.rglob("*.py")):
        rel = py.relative_to(RAIZ).as_posix()
        if not (rel.startswith("platform/") or rel.startswith("product/backend/")):
            continue
        if any(x in rel for x in ("/tests/", "/test_", "verify_", "selftest", "/.venv/",
                                  "demo_", "/fixtures/", "tests_", "fire_")):
            continue
        # `platform/eval` no viaja en el bundle (no está en el `.spec`) y no corre en el
        # sidecar: es el banco de evaluación. Su `parents[N]` mira un árbol que sí existe.
        if rel.startswith("platform/eval/"):
            continue
        if rel.startswith(_VIAJAN_COMO_ARCHIVO):
            continue                     # su `__file__` es real: `parents[N]` resuelve
        texto = py.read_text(errors="replace")
        # Un archivo que YA consulta `resource_root()` tiene su camino bueno; el `parents[N]`
        # que le queda es el fallback del `except` para dev suelto, y ése es correcto.
        # Sin esta regla el guard acusaría a `credential_broker` y `motor_verdad`, que hacen
        # exactamente lo que hay que hacer.
        if "resource_root()" in texto:
            continue
        lineas = texto.splitlines()
        raices: dict[str, int] = {}
        for i, l in enumerate(lineas):
            m = DEF.match(l)
            if m:
                raices[m.group(1)] = i + 1
                continue
            if l.strip().startswith("#") or not raices:
                continue
            # La composición se busca en CUALQUIER parte de la línea —dentro de una lista, de
            # un return, de un argumento—, no sólo en `X = raiz / "..."`.
            for raiz in raices:
                for mm in re.finditer(r"\b" + re.escape(raiz) + r"\b((?:\s*/\s*[\"'][^\"']+[\"'])+)",
                                      l):
                    # el destino COMPLETO, no su primer segmento: `product/belts` viaja en el
                    # bundle y `product/backend/data` es el dir de ESCRITURA del usuario —
                    # otra clase, que se arregla con `data_root()` y no con `resource_root()`.
                    destino = "/".join(re.findall(r"[\"']([^\"']+)[\"']", mm.group(1)))
                    # Un `.py` NO es un dato: se carga con `aleph_paths.load_module_by_path`,
                    # que YA es frozen-aware y reubica el sufijo repo-relativo a
                    # `resource_root()`. Pasarle una ruta del árbol es lo correcto — acusarlo
                    # sería pedirle a media docena de módulos que arreglen algo que no está
                    # roto. Medido: `advisor`, `repo`, `event_stream`, `inspect_router` y
                    # `smithery_router` cargan todos por esa vía.
                    if destino.endswith(".py"):
                        continue
                    if destino.startswith(_DIRS_QUE_VIAJAN):
                        malos.append(f"{rel}:{i+1} · {raiz} (parents[N] @L{raices[raiz]})"
                                     f" / {destino}")
    return malos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nuevo", help="sidecar construido desde esta rama")
    ap.add_argument("--sin-lector", dest="sin_lector",
                    help="[6d] bundle CON los datos pero con el LECTOR roto — el negativo del "
                         "testigo 5. Distinto de --viejo, que es un bundle SIN los datos.")
    ap.add_argument("--viejo", default="/Applications/Aleph.app",
                    help="un bundle que se SABE incompleto, para calibrar en negativo")
    a = ap.parse_args()

    from bundle_datos import DATOS_REQUERIDOS
    print("═" * 90)
    print("OBRA 6a · VARA DEL EMPAQUETADO")
    print("═" * 90)
    print(f"  datos declarados ({len(DATOS_REQUERIDOS)}):")
    for d in DATOS_REQUERIDOS:
        print(f"      · {d}")
    print()

    # ── 1 · EL NEGATIVO: el guard nuevo contra un bundle sin los datos → ROJO ────────────
    viejo = _binario_del_app(Path(a.viejo)) if a.viejo else None
    if not viejo or not viejo.exists():
        no_medible("1_negativo_el_guard_rojea", f"no existe el bundle viejo ({viejo})")
    else:
        faltaban = _toc(viejo)
        ya_incompleto = [d for d in DATOS_REQUERIDOS if d not in faltaban]
        if not ya_incompleto:
            no_medible("1_negativo_el_guard_rojea",
                       "el bundle de calibración YA trae los datos: no sirve de negativo")
        else:
            rc, salida = _gate(viejo, 8281)
            nombra = all(d in salida for d in ya_incompleto)
            ok("1_negativo_el_guard_rojea", rc == 1 and nombra,
               {"exit": rc, "nombra_los_que_faltan": nombra, "faltaban": ya_incompleto})

    # ── 2 · EL POSITIVO: el guard contra el bundle nuevo → VERDE ────────────────────────
    nuevo = Path(a.nuevo) if a.nuevo else None
    if not nuevo or not nuevo.exists():
        no_medible("2_positivo_el_guard_verde", "no se pasó --nuevo (o no existe)")
        no_medible("4a_datos_en_el_toc", "sin bundle nuevo")
        no_medible("4b_el_proceso_encuentra_el_puente", "sin bundle nuevo")
        no_medible("4c_pins_en_el_bundle", "sin bundle nuevo")
    else:
        rc, salida = _gate(nuevo, 8283)
        ok("2_positivo_el_guard_verde", rc == 0, {"exit": rc, "cola": salida.strip()[-160:]})

        # ── 4a · los dos archivos, en el TOC del binario nuevo ──────────────────────────
        toc = _toc(nuevo)
        faltan = [d for d in DATOS_REQUERIDOS if d not in toc]
        ok("4a_datos_en_el_toc", not faltan, {"faltan": faltan, "total_toc": len(toc)})

        # ── 4b · el PROCESO los encuentra donde `${PUPPET_REPO}` resuelve ───────────────
        tmp = tempfile.mkdtemp(prefix="aleph-vara6a-")
        env = dict(os.environ, ALEPH_ROLE="client", ALEPH_DATA_DIR=tmp, PUPPET_DATA_DIR=tmp,
                   TMPDIR=tmp, PUPPET_PORT="8285", PORT="8285")
        proc = subprocess.Popen([str(nuevo), "--port", "8285"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        mei = None
        try:
            limite = time.time() + 120
            while time.time() < limite:
                cands = sorted(Path(tmp).glob("_MEI*"))
                if cands and (cands[0] / "platform" / "inspection").exists():
                    mei = cands[0]
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
            if mei is None:
                no_medible("4b_el_proceso_encuentra_el_puente",
                           "el sidecar nuevo no llegó a desplegar su _MEIPASS")
                no_medible("4c_pins_en_el_bundle", "sin _MEIPASS")
            else:
                puente = mei / "platform" / "inspection" / "byo_mcp_server.py"
                ok("4b_el_proceso_encuentra_el_puente", puente.is_file(),
                   {"ruta": str(puente).replace(str(tmp), "<tmp>"),
                    "bytes": puente.stat().st_size if puente.is_file() else 0})

                # ── 4c · pinned_servers() > 0 con el archivo QUE VIAJÓ ──────────────────
                # `pinned_servers()` es función pura del curado: se cuenta sobre el archivo
                # del bundle, sin red y sin adivinar.
                curado = mei / "platform" / "inspection" / "data" / "curated_mcp_registry.json"
                pins = 0
                if curado.is_file():
                    d = json.loads(curado.read_text(encoding="utf-8"))
                    pins = sum(1 for s in (d.get("services") or {}).values()
                               if isinstance(s, dict) and (s.get("pin") or "").strip())
                ok("4c_pins_en_el_bundle", pins > 0, {"pins": pins})
        finally:
            _matar(proc)
            shutil.rmtree(tmp, ignore_errors=True)

    # ── 5 · [OBRA 6d] ¿EL CÓDIGO LO ENCUENTRA? ──────────────────────────────────────────
    # El testigo que faltaba. Todo lo de arriba mira si el archivo ESTÁ; esto le pregunta al
    # binario si su lector lo ENCUENTRA, que es una pregunta distinta y es la que costó una
    # instalación: 4a/4b/4c salieron verdes sobre un build cuyo catálogo público daba 500.
    if nuevo and nuevo.exists():
        r = _sellos_del_binario(nuevo, 8287)
        if r.get("ok") is None:
            no_medible("5_el_codigo_encuentra_el_curado", r.get("detalle", "sin medición"))
        else:
            ok("5_el_codigo_encuentra_el_curado", r["ok"], r)
    else:
        no_medible("5_el_codigo_encuentra_el_curado", "no se pasó --nuevo (o no existe)")

    # NEGATIVO — y necesita SU PROPIO bundle de calibración, distinto del de `--viejo`.
    # Los dos negativos miden fallas distintas y un bundle no puede servir para los dos:
    #   `--viejo`       → un bundle SIN los datos          (el guard del TOC tiene que rojear)
    #   `--sin-lector`  → un bundle CON los datos pero con el LECTOR roto (éste)
    # Es justamente la diferencia que esta obra existe para marcar: que el archivo esté no
    # significa que alguien lo encuentre.
    sin_lector = Path(a.sin_lector) if getattr(a, "sin_lector", None) else None
    if sin_lector is not None:
        bin_viejo = _binario_del_app(sin_lector) if sin_lector.is_dir() else sin_lector
        if bin_viejo.exists():
            rv = _sellos_del_binario(bin_viejo, 8289)
            if rv.get("ok") is None:
                no_medible("5_negativo_el_bundle_de_antes_no_lo_encuentra",
                           rv.get("detalle", "sin medición"))
            else:
                ok("5_negativo_el_bundle_de_antes_no_lo_encuentra", rv["ok"] is False, rv)
        else:
            no_medible("5_negativo_el_bundle_de_antes_no_lo_encuentra",
                       f"no existe el binario de calibración ({bin_viejo})")
    else:
        no_medible("5_negativo_el_bundle_de_antes_no_lo_encuentra",
                   "no se pasó --sin-lector (un bundle CON los datos y el lector roto)")

    # ── 6 · [OBRA 6d] EL GUARD DE CLASE · que no vuelva a pasar con OTRO dato ────────────
    # El testigo 5 mide el curado. Éste mide LA CLASE: ningún módulo del PYZ puede componer
    # una ruta a un directorio que viaja desde un `parents[N]` crudo. Es lo que convierte un
    # caso suelto en una clase cerrada — el archivo siguiente no puede repetirlo callado.
    malos = _clase_parents_a_datos()
    ok("6_ningun_lector_del_pyz_usa_parents", not malos,
       {"infractores": malos} if malos else {"revisados": "platform/ + product/backend/"})

    # NEGATIVO — el guard tiene que saber SEÑALAR. Se le da el patrón exacto que esta obra
    # arregló, escrito a mano, y tiene que encontrarlo: un guard que no puede acusar a nadie
    # es un guard que va a salir verde para siempre.
    _tmp_negativo = RAIZ / "platform" / "inspection" / "_guard_6d_negativo.py"
    try:
        _tmp_negativo.write_text(
            "from pathlib import Path\n"
            "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
            "_X = _REPO_ROOT / 'catalog' / 'brands.json'\n"
            "def leer():\n"
            "    return _X.read_text()\n", encoding="utf-8")
        detectados = _clase_parents_a_datos()
        ok("6_negativo_el_guard_sabe_acusar",
           any("_guard_6d_negativo.py" in m for m in detectados),
           {"detectado": [m for m in detectados if "_guard_6d_negativo" in m]})
    finally:
        _tmp_negativo.unlink(missing_ok=True)

    # ── 3 · load_curated: dev calla, congelado GRITA ─────────────────────────────────────
    from inspection import mcp_registry as R
    original = R._CURATED_PATH
    try:
        R._CURATED_PATH = Path("/no/existe/curated_mcp_registry.json")
        frozen_previo = getattr(sys, "frozen", None)
        try:
            if hasattr(sys, "frozen"):
                del sys.frozen
        except Exception:
            pass
        dev_calla = R.load_curated() == {}

        sys.frozen = True
        try:
            R.load_curated()
            congelado_grita = False
            exc = None
        except R.CuradoAusenteError as e:
            congelado_grita = True
            exc = str(e)[:90]

        no_se_disfraza = not issubclass(R.CuradoAusenteError, R.RegistryError)
        ok("3_dev_calla_congelado_grita", dev_calla and congelado_grita and no_se_disfraza,
           {"dev_devuelve_{}": dev_calla, "congelado_levanta": congelado_grita,
            "no_hereda_de_RegistryError": no_se_disfraza, "excepcion": exc})
    finally:
        R._CURATED_PATH = original
        if frozen_previo is None:
            try:
                del sys.frozen
            except Exception:
                pass
        else:
            sys.frozen = frozen_previo

    print()
    print("═" * 90)
    print("MEDIDO=" + json.dumps(RESULTADO, ensure_ascii=False))
    if FALLOS:
        print(f"\n❌ verify_bundle_datos: {len(FALLOS)} sin verde → {FALLOS}")
        return 1
    print("\n✅ verify_bundle_datos: TODO VERDE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
