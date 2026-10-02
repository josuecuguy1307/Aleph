"""test_mei_sweep.py — el barrido de _MEI huérfanos. [ver reports/mei-huerfanos-debt.md]

Los tests están escritos contra los TRES FALLOS QUE IMPORTAN, no contra la
implementación. Cualquiera de los tres es peor que la fuga de disco que el barrido viene
a arreglar:

  1. borrar el _MEI de un proceso VIVO      → le arranca el piso a Aleph corriendo
  2. borrar el _MEI de OTRA aplicación      → le rompemos el programa a un tercero
  3. borrar el PROPIO                       → nos suicidamos a mitad del arranque

Y el cuarto, que es la contracara: FALLA CERRADO. Si no se puede saber qué está vivo, o
no se puede confirmar la propia huella, no se borra NADA. El costo de no barrer es disco;
el de barrer mal es cualquiera de los tres de arriba.

Correr:  pytest deploy/fase4/test_mei_sweep.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sidecar_serve as S  # noqa: E402


def _mei(padre: Path, nombre: str, *, de_aleph: bool = True, peso: int = 1024) -> Path:
    """Un _MEI de mentira PERO con la forma real: las marcas que el .spec hace viajar."""
    d = padre / nombre
    (d / "platform" / "db").mkdir(parents=True, exist_ok=True)
    (d / "catalog").mkdir(parents=True, exist_ok=True)
    if de_aleph:
        (d / "platform" / "db" / "schema_sqlite.sql").write_text("x" * peso)
        (d / "catalog" / "brand_domains.json").write_text("{}")
    else:                                   # otro onefile: mismo prefijo, otro contenido
        (d / "otra_app.dat").write_text("no soy de Aleph")
    return d


@pytest.fixture()
def escenario(tmp_path, monkeypatch):
    """Un $TMPDIR con: el propio, un huérfano de Aleph, uno vivo, y uno de otra app."""
    propio = _mei(tmp_path, "_MEIpropio")
    huerfano = _mei(tmp_path, "_MEIhuerfano")
    vivo = _mei(tmp_path, "_MEIvivo")
    ajeno = _mei(tmp_path, "_MEIajeno", de_aleph=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(propio), raising=False)
    monkeypatch.setattr(S, "_mei_vivos", lambda: {str(vivo)})
    return {"propio": propio, "huerfano": huerfano, "vivo": vivo, "ajeno": ajeno}


# ── el camino feliz ──────────────────────────────────────────────────────────────

def test_borra_el_huerfano_de_aleph(escenario):
    censo = S.barrer_mei_huerfanos()
    assert censo["omitido"] is None
    assert censo["borrados"] == [str(escenario["huerfano"])]
    assert not escenario["huerfano"].exists()
    assert censo["bytes"] > 0, "el censo reporta lo que liberó"


# ── los tres que NO se pueden borrar ─────────────────────────────────────────────

def test_NO_borra_el_de_un_proceso_VIVO(escenario):
    """El peor de los tres: borrarle el piso a un Aleph que está andando."""
    S.barrer_mei_huerfanos()
    assert escenario["vivo"].exists(), "un _MEI abierto por alguien NO se toca"


def test_NO_borra_el_de_OTRA_APLICACION(escenario):
    """Cualquier onefile de PyInstaller usa el prefijo `_MEI`. Se mira ADENTRO."""
    S.barrer_mei_huerfanos()
    assert escenario["ajeno"].exists()
    assert (escenario["ajeno"] / "otra_app.dat").exists()


def test_NO_borra_EL_PROPIO(escenario):
    """El proceso que barre está corriendo DESDE uno de estos directorios."""
    S.barrer_mei_huerfanos()
    assert escenario["propio"].exists()
    assert str(escenario["propio"]) not in S.barrer_mei_huerfanos()["borrados"]


# ── falla CERRADO ────────────────────────────────────────────────────────────────

def test_si_no_sabe_QUE_ESTA_VIVO_no_borra_nada(escenario, monkeypatch):
    """`lsof` ausente o roto ⇒ `None` ⇒ cero borrados. No se adivina: el costo de no
    barrer es disco, el de barrer a ciegas es matar un proceso."""
    monkeypatch.setattr(S, "_mei_vivos", lambda: None)
    censo = S.barrer_mei_huerfanos()
    assert censo["borrados"] == []
    assert "lsof" in censo["omitido"]
    assert escenario["huerfano"].exists()


def test_sin_la_huella_propia_no_borra_nada(tmp_path, monkeypatch):
    """Si no podemos confirmar NUESTRAS marcas, no podemos reconocer las ajenas. Pasa si
    el .spec deja de empaquetar alguna: el barrido se apaga solo en vez de adivinar."""
    propio = _mei(tmp_path, "_MEIpropio", de_aleph=False)
    huerfano = _mei(tmp_path, "_MEIhuerfano")
    monkeypatch.setattr(sys, "_MEIPASS", str(propio), raising=False)
    monkeypatch.setattr(S, "_mei_vivos", lambda: set())
    censo = S.barrer_mei_huerfanos()
    assert censo["borrados"] == [] and "marcas" in censo["omitido"]
    assert huerfano.exists()


def test_en_dev_no_hace_nada(monkeypatch):
    """Sin congelar no hay _MEI. Correr el sidecar suelto no puede barrer el $TMPDIR."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    censo = S.barrer_mei_huerfanos()
    assert censo["borrados"] == [] and "congelados" in censo["omitido"]


# ── el censo ─────────────────────────────────────────────────────────────────────

def test_dry_run_cuenta_sin_borrar(escenario):
    """Contar primero, borrar después — la misma regla que con los procesos huérfanos."""
    censo = S.barrer_mei_huerfanos(dry_run=True)
    assert censo["borrados"] == [str(escenario["huerfano"])]
    assert escenario["huerfano"].exists(), "dry-run NO borra"


def test_el_censo_separa_candidatos_de_los_nuestros(escenario):
    censo = S.barrer_mei_huerfanos(dry_run=True)
    assert censo["candidatos"] == 4          # los cuatro _MEI del directorio
    assert censo["de_aleph"] == 2            # huérfano + vivo (el propio ya está excluido)
    assert censo["vivos"] == 1


def test_no_levanta_nunca_aunque_el_directorio_no_se_pueda_listar(tmp_path, monkeypatch):
    """Un fallo del barrido NO puede impedir que la app arranque."""
    propio = _mei(tmp_path, "_MEIpropio")
    monkeypatch.setattr(sys, "_MEIPASS", str(propio), raising=False)
    monkeypatch.setattr(os, "listdir", lambda _p: (_ for _ in ()).throw(OSError("nope")))
    censo = S.barrer_mei_huerfanos()
    assert censo["borrados"] == [] and censo["omitido"]


# ── el fallo que YA PASÓ: creer que no hay nada vivo porque no se está mirando ──
#
# `_mei_vivos` depende de que `sys.executable` sea el binario del onefile. Congelado lo
# es; suelto NO. Cuando no lo es, `ps` no matchea a nadie y la versión anterior devolvía
# un conjunto VACÍO — que significa «no hay nada vivo», o sea barra libre. En la vara eso
# borró un `_MEI` que un proceso tenía abierto. La cura: la función se busca a sí misma.

def test_si_NO_SE_VE_A_SI_MISMO_devuelve_None_y_no_vacio():
    """Estamos corriendo. Si el barrido no encuentra su propio PID entre los que cree
    nuestros, no está mirando lo que cree — y `None` (no sé) frena el borrado, mientras
    que `set()` (no hay nadie) lo habilita."""
    import sys as _s
    previo = _s.executable
    try:
        _s.executable = "/no/existe/binario-que-nadie-corre"
        assert S._mei_vivos() is None, "sin verse a sí mismo tiene que decir «no sé»"
    finally:
        _s.executable = previo


def test_en_dev_tambien_dice_no_se_y_esta_BIEN():
    """Corriendo bajo `python3` la autoverificación falla a propósito: `sys.executable`
    resuelve a `python3.13` y `ps` reporta `python3`. Devolver `None` ahí es CORRECTO —
    en dev no estamos congelados y no hay ningún `_MEI` nuestro que barrer. El positivo
    de verdad se mide contra el binario congelado (el test de abajo)."""
    assert S._mei_vivos() is None


def test_EL_POSITIVO_lsof_encuentra_de_verdad_un_MEI_abierto(tmp_path):
    """EL POSITIVO, y hace falta: un barrido que contestara «no sé» SIEMPRE pasaría todos
    los tests negativos de arriba y no barrería nunca nada.

    Se prueba `_mei_abiertos_por` —la parte medible— con un proceso REAL que tiene un
    archivo abierto adentro de un directorio con nombre `_MEI…`. Si `lsof` deja de
    reportar lo que tiene abierto un PID, o si el patrón deja de matchear la ruta, esto
    se pone rojo y el barrido no puede quedar «seguro por inútil»."""
    import subprocess as sp
    d = tmp_path / "_MEIdeverdad"
    d.mkdir()
    archivo = d / "abierto.dat"
    archivo.write_text("x")
    # un proceso que mantiene el archivo abierto hasta que lo matemos
    p = sp.Popen([sys.executable, "-c",
                  f"f=open({str(archivo)!r}); import time; time.sleep(30)"])
    try:
        for _ in range(50):                       # esperar a que abra
            vistos = S._mei_abiertos_por([p.pid])
            if vistos:
                break
            import time as _t
            _t.sleep(0.1)
        assert any(str(d) in v or os.path.realpath(str(d)) in v for v in vistos), (
            f"lsof no vio el _MEI abierto por el pid {p.pid}: {vistos}")
    finally:
        p.kill()
        p.wait()


def test_sin_pids_no_llama_a_lsof_y_devuelve_vacio():
    assert S._mei_abiertos_por([]) == set()


def test_el_None_frena_el_barrido_de_punta_a_punta(tmp_path, monkeypatch):
    """Integración de lo de arriba: el «no sé» tiene que llegar hasta el borrado.

    A propósito NO usa la fixture `escenario`, que parchea `_mei_vivos` con un doble: acá
    lo que se prueba es la función REAL fallando por no verse a sí misma."""
    propio = _mei(tmp_path, "_MEIpropio")
    huerfano = _mei(tmp_path, "_MEIhuerfano")
    monkeypatch.setattr(sys, "_MEIPASS", str(propio), raising=False)
    monkeypatch.setattr(sys, "executable", "/no/existe/binario-que-nadie-corre")
    censo = S.barrer_mei_huerfanos()
    assert censo["borrados"] == [] and "lsof" in censo["omitido"]
    assert huerfano.exists(), "no se borra lo que no se pudo descartar"
