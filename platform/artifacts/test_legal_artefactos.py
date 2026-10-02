"""test_legal_artefactos.py — LAS FILAS DE LEGAL, CRUZADAS DE VERDAD.
[Legal · artefactos]

POR QUÉ EXISTE, Y QUÉ HABRÍA CAZADO. Hasta esta obra `legal` tenía UNA sola clave
(`legal_review`), así que todo el oficio de doc.haus —redlines, documentos redactados,
ediciones con control de cambios— habría vuelto `422 workspace_kind_unknown` si alguien lo
hubiera posteado. Es el mismo agujero medido en Oficina, y allá tardó meses en verse porque
el plugin se tragaba el rechazo a su propia bitácora. Un `cross()` que nadie corre no
prueba nada, así que acá se corre con los payloads LITERALES que arma
`platform/workspaces/plugins/dochaus.js`.

Se mide contra la tabla REAL, sin `monkeypatch`: estas filas están en el registro de
producción y lo que hay que probar es justamente que estén.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import bridge  # noqa: E402


def _redline(**cambios):
    """El payload que el plugin arma para `redline` / `tracked-changes`."""
    data = {"name": "Redline en NDA.docx", "document": "NDA.docx",
            "path": "/m/NDA.docx", "antes": "El plazo será de cinco (5) años.",
            "despues": "El plazo será de dos (2) años.", "autor": "doc.haus",
            "redline_id": 7, "alcance": "redline", "resumen": "Recorded as pending redline #7."}
    data.update(cambios)
    return {"kind": "legal_redline", "name": data["name"], "data": data}


def _documento(**cambios):
    data = {"name": "NDA.docx", "path": "/m/NDA.docx", "size": 18_432,
            "encoding": "base64", "content": "UEsDBBQ=", "que_es": "documento redactado"}
    data.update(cambios)
    return {"kind": "legal_document", "name": data["name"], "data": data}


class TestCruzaDeVerdad:
    def test_el_redline_cruza_y_lleva_los_dos_lados(self):
        obra = bridge.cross("legal", _redline())
        assert obra["type"] == "informe"
        # LA VARA ES EL ARTEFACTO: no alcanza con que cruce, tiene que traer el cambio.
        assert "cinco (5) años" in obra["content"]
        assert "dos (2) años" in obra["content"]
        assert "doc.haus" in obra["content"]

    def test_la_degradacion_del_docx_es_DECLARADA_y_no_accidental(self):
        # ESTE TEST NACIÓ ROJO Y TENÍA RAZÓN EL CÓDIGO. Se escribió afirmando que un
        # `.docx` cruza como `documento`, y cae: `_tipado_o_ficha` lo degrada a `informe`
        # porque sus bytes vienen en base64 y Aleph no puede re-derivar el texto sin
        # parsear OOXML —o sea, sin DERIVAR dato—. La ficha honesta es lo correcto; lo que
        # hay que probar no es el tipo sino que la caída esté DECLARADA en la fila, porque
        # una degradación no declarada es una tabla que dejó de describir lo que el código
        # hace (el `assert` de `cross()` la mataría).
        obra = bridge.cross("legal", _documento())
        assert obra["type"] == "informe"
        assert "informe" in bridge.TABLE["legal"]["legal_document"]["degrades_to"]
        assert obra["title"] == "NDA.docx"

    def test_un_md_utf8_llega_entero(self):
        obra = bridge.cross("legal", _documento(name="minuta.md", encoding="utf8",
                                                content="# Minuta\n\nPunto uno."))
        assert obra["type"] == "documento"
        assert "Punto uno." in obra["content"]


class TestJamasElDato:
    def test_un_redline_sin_ningun_lado_se_RECHAZA_con_causa(self):
        # Un panel que dice «hubo un cambio» sin decir cuál es la mentira barata que este
        # puente existe para no entregar.
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross("legal", _redline(antes=None, despues=None))
        assert e.value.code in bridge.CAUSES        # regla sellada: la causa tiene copy

    def test_el_lado_que_falta_se_NOMBRA_y_no_se_reconstruye(self):
        # Una cláusula que se AGREGA no tiene `antes`, y eso es un cambio legítimo: cruza.
        # Lo que no puede pasar es que el puente lea el documento para rellenarlo.
        obra = bridge.cross("legal", _redline(antes=None))
        assert "no devolvió el texto anterior" in obra["content"]
        assert "cinco (5) años" not in obra["content"]

    def test_no_se_inventa_autor_ni_numero_de_redline(self):
        obra = bridge.cross("legal", _redline(autor=None, redline_id=None))
        assert "doc.haus" not in obra["content"]


class TestLegalReclamaSuPropiaSalida:
    def test_legal_acepta_el_documento_que_produce(self):
        # Sin esto, `claims()` daba False sobre el `.docx` que Legal acababa de redactar y
        # la obra caía a la base en vez de volver a su escritorio.
        assert bridge.claims("legal", "documento")
        assert bridge.claims("legal", "informe")

    def test_las_filas_declaran_su_contabilidad(self):
        # El contrato del puente: cada fila dice qué fue FORMA y qué nunca se rellena. Es
        # la materia prima del traductor universal, y una fila muda no sirve para eso.
        for kind in ("legal_redline", "legal_document"):
            fila = bridge.TABLE["legal"][kind]
            assert fila["shape_changes"] and fila["never_filled"] and fila["caso"]
