"""test_bridge.py — EL MECANISMO DEL PUENTE, CON EL REGISTRO VACÍO.
[Gate 4 · Fase 3 · cosecha]

POR QUÉ EXISTE. La Fase 3 escribió el puente y midió sus 9 casos contra un stack heredado
vivo; la cosecha sacó ese stack, así que `TABLE` y `ACCEPTS` quedaron vacíos. Un mecanismo
sin ninguna fila registrada es un mecanismo que **nadie corre**, y eso es exactamente lo que
el censo de la casa llama defecto («un mecanismo sin consumidor es un mecanismo que nadie
prueba»). Estos tests son ese consumidor: instancian un workspace SINTÉTICO —no un stack, un
fixture— y ejercitan el mecanismo entero.

Y prueban lo que hay que probar dos veces: no sólo que el puente traduce, sino **que jamás
rellena**. Cada test de la clase `TestJamasElDato` corresponde a una tentación que la
medición real descartó, y está escrito para caer si alguien decide «completar» un hueco.

El registro se toca con `monkeypatch`, jamás a nivel de módulo: un fixture que dejara filas
sembradas volvería a poner a `GET /v1/workspaces` en «hay un workspace» y la vara de la
cosecha mediría un registro que no está vacío.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import bridge, vocabulary  # noqa: E402


#: Un workspace de prueba con una fila por cada adaptador de forma que el puente conserva.
#: No es un stack: es el fixture mínimo que hace corribles las cuatro formas medidas.
_WS = "taller"
_FILAS = {
    "ficha_plana": {
        "type": "informe", "adapt": bridge.ADAPTERS["snapshot"],
        "shape_changes": "objeto plano → tabla markdown de dos columnas",
        "never_filled": "un campo ausente sale «—», jamás 0",
    },
    "ficha_anidada": {
        "type": "informe", "adapt": bridge.ADAPTERS["card"],
        "shape_changes": "objeto con anidados → tabla + bloques JSON",
        "never_filled": "los anidados se muestran íntegros, no se resumen",
    },
    "tabla": {
        "type": "planilla", "adapt": bridge.ADAPTERS["table"], "degrades_to": ("informe",),
        "shape_changes": "`results` → `rows`; el análisis viaja como nota, no como fila",
        "never_filled": "una columna que el origen no trajo queda ausente en su fila",
    },
    "curva": {
        "type": "linechart", "adapt": bridge.ADAPTERS["curve"],
        "shape_changes": "`equity_curve:[{date,…}]` → {labels, series}",
        "never_filled": "los huecos viajan null; una serie que no vino no se crea vacía",
    },
}


@pytest.fixture
def taller(monkeypatch):
    """Registra el workspace sintético SÓLO durante el test."""
    monkeypatch.setitem(bridge.TABLE, _WS, _FILAS)
    monkeypatch.setitem(bridge.ACCEPTS, _WS, ("planilla", "linechart", "informe"))
    return _WS


# ── EL REGISTRO VACÍO ES UN ESTADO SANO ───────────────────────────────────────────────

class TestRegistroVacio:
    """El puente contesta lo que corresponde, con registro y sin él."""

    def test_ninguna_fila_sin_su_caso_ejecutado(self):
        """[F3-ciencia] Esta vara REEMPLAZA a «el registro nace vacío».

        Aquélla existía para que nadie sembrara una fila a nivel de módulo mientras no
        hubiera ningún stack adentro. Entró Ciencia y esa afirmación dejó de ser cierta —
        pero su INTENCIÓN sigue valiendo, y acá queda más fuerte: la regla del puente no
        es «cero filas», es **«ninguna fila sin su caso EJECUTADO al lado»**, que es la
        mitad del valor de esta tabla y lo que la hace extraíble en Fase 6.

        Una fila que no declare qué se midió, qué cambió de forma y qué jamás se rellena
        es una fila escrita de intuición, y ésas son exactamente las que esta vara mata.
        """
        for ws, filas in bridge.TABLE.items():
            assert filas, f"{ws} está en la tabla sin una sola fila"
            for kind, fila in filas.items():
                donde = f"{ws}.{kind}"
                assert fila.get("type"), f"{donde}: sin tipo canónico"
                assert callable(fila.get("adapt")), f"{donde}: sin adaptador"
                assert str(fila.get("caso", "")).strip(), (
                    f"{donde}: SIN CASO EJECUTADO. Una fila se agrega midiendo, jamás de intuición.")
                assert fila.get("shape_changes"), f"{donde}: no declara qué cambió de forma"
                assert fila.get("never_filled"), f"{donde}: no declara qué jamás se rellena"
            # Un workspace con filas tiene que declarar qué acepta de vuelta (ley 7) —
            # SALVO que esté declarado como MODO que sólo produce (Fase 6: la Sala trajo
            # esa categoría, que antes no existía). Lo que no está en ninguna de las dos
            # listas es un olvido, y por eso la invariante sigue existiendo.
            assert ws in bridge.ACCEPTS or ws in bridge.SOLO_PRODUCEN, (
                f"{ws} cruza artefactos pero no declara `accepts` "
                f"ni está declarado en `SOLO_PRODUCEN`")

    def test_un_modo_no_puede_a_la_vez_solo_producir_y_aceptar(self):
        """Las dos listas son excluyentes: si acepta, no «sólo produce».

        Sin esta afirmación, agregar una fila en `ACCEPTS` para algo declarado
        `SOLO_PRODUCEN` pasaría en silencio y el modo se volvería destino de artefactos —
        que es exactamente lo que la regla sellada de Fase 6 prohíbe.
        """
        cruce = bridge.SOLO_PRODUCEN & set(bridge.ACCEPTS)
        assert not cruce, f"declarados como sólo-producen pero aceptan: {sorted(cruce)}"

    def test_lo_declarado_solo_produce_existe_en_la_tabla(self):
        """Los productores heredados tienen fila; sala_browser es nativo sin cruce."""
        huerfanos = bridge.SOLO_PRODUCEN - set(bridge.TABLE)
        assert huerfanos == {"sala_browser"}, (
            f"SOLO_PRODUCEN cambió su excepción nativa sin revisar el contrato: {sorted(huerfanos)}"
        )

    def test_lo_que_acepta_es_del_vocabulario(self):
        """Aceptar un tipo que no existe sería prometer una compatibilidad imposible."""
        for ws, tipos in bridge.ACCEPTS.items():
            for t in tipos:
                assert vocabulary.normalize(t) == t, f"{ws} acepta «{t}», que no es canónico"

    def test_un_workspace_desconocido_no_acepta_ni_reclama_nada(self):
        assert bridge.accepts("fantasma") == ()
        assert bridge.kinds("fantasma") == ()
        assert bridge.claims("fantasma", "informe") is False

    def test_cruzar_sin_registro_levanta_la_causa_con_copy(self):
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross("fantasma", {"kind": "lo_que_sea", "data": {"a": 1}})
        assert e.value.code == "workspace_kind_unknown"
        # Regla sellada: ninguna causa llega a una superficie sin copy.
        assert bridge.CAUSES[e.value.code].strip()

    def test_todas_las_causas_tienen_copy(self):
        vacias = [k for k, v in bridge.CAUSES.items() if not str(v).strip()]
        assert not vacias, f"causas sin copy: {vacias}"

    def test_as_json_es_serializable_y_lleva_las_causas(self):
        j = bridge.as_json()
        assert set(j["workspaces"]) == set(bridge.TABLE)
        # Los adaptadores son código y NO viajan; la contabilidad sí, porque es lo que
        # lee el reporte, la vara y la extracción del traductor de Fase 6.
        for ws, datos in j["workspaces"].items():
            for kind, fila in datos["kinds"].items():
                assert "adapt" not in fila, f"{ws}.{kind}: el adaptador no puede viajar"
                assert fila.get("caso"), f"{ws}.{kind}: el caso medido no viajó"
        assert set(j["causes"]) == set(bridge.CAUSES)
        json.dumps(j)          # la lee el reporte y una vara: tiene que viajar por HTTP


# ── SE ADAPTA LA FORMA ────────────────────────────────────────────────────────────────

class TestSeAdaptaLaForma:

    def test_ficha_plana_a_informe(self, taller):
        obra = bridge.cross(taller, {"kind": "ficha_plana",
                                     "data": {"ticker": "ABC", "precio": 10, "pe": 3.5}})
        assert obra["type"] == "informe"
        # Cada clave del origen aparece UNA vez, con su valor tal cual.
        assert obra["content"].count("| ticker |") == 1
        assert "ABC" in obra["content"] and "10" in obra["content"]

    def test_tabla_a_planilla_renombrando_la_llave(self, taller):
        obra = bridge.cross(taller, {"kind": "tabla",
                                     "data": {"query": "q", "count": 2,
                                              "results": [{"a": 1}, {"a": 2}],
                                              "analysis": "dos filas"}})
        assert obra["type"] == "planilla"
        assert obra["rows"] == [{"a": 1}, {"a": 2}]     # `results` → `rows`, sin tocar filas
        assert obra["note"] == "dos filas"              # el análisis NO se convierte en fila

    def test_curva_a_linechart(self, taller):
        curva = [{"date": "2026-01-01", "equity": 100}, {"date": "2026-01-02", "equity": 110}]
        obra = bridge.cross(taller, {"kind": "curva", "data": {"equity_curve": curva}})
        assert obra["type"] == "linechart"
        assert obra["labels"] == ["2026-01-01", "2026-01-02"]
        assert [s["name"] for s in obra["series"]] == ["equity"]
        assert obra["series"][0]["values"] == [100, 110]

    def test_el_tipo_sale_normalizado_contra_el_vocabulario(self, taller):
        # `claims` normaliza antes de comparar: `table` y `planilla` no pueden dar
        # respuestas distintas (el alias es del vocabulario, no del puente).
        assert bridge.claims(taller, "planilla") is True
        assert bridge.claims(taller, "table") is True
        assert bridge.claims(taller, "cad") is False


# ── JAMÁS EL DATO ─────────────────────────────────────────────────────────────────────

class TestJamasElDato:
    """Cada test es una tentación que la medición real descartó."""

    def test_un_campo_ausente_sale_raya_jamas_cero(self, taller):
        obra = bridge.cross(taller, {"kind": "ficha_plana",
                                     "data": {"ticker": "ABC", "pe": None}})
        assert "| pe | — |" in obra["content"], obra["content"]
        assert "| pe | 0 |" not in obra["content"]

    def test_los_huecos_de_la_curva_no_se_interpolan(self, taller):
        curva = [{"date": "d1", "equity": 100}, {"date": "d2", "equity": None},
                 {"date": "d3", "equity": 120}]
        obra = bridge.cross(taller, {"kind": "curva", "data": {"equity_curve": curva}})
        assert obra["series"][0]["values"] == [100, None, 120]

    def test_una_serie_que_el_origen_no_calculo_no_se_crea_vacia(self, taller):
        curva = [{"date": "d1", "strategy": 1, "benchmark": None},
                 {"date": "d2", "strategy": 2, "benchmark": None}]
        obra = bridge.cross(taller, {"kind": "curva", "data": {"equity_curve": curva}})
        nombres = [s["name"] for s in obra["series"]]
        assert nombres == ["strategy"], f"se inventó una serie: {nombres}"

    def test_el_count_del_origen_no_se_recalcula(self, taller):
        # El origen dice 99 y trae 1 fila: la inconsistencia es SUYA y se muestra.
        obra = bridge.cross(taller, {"kind": "tabla",
                                     "data": {"count": 99, "results": [{"a": 1}]}})
        assert len(obra["rows"]) == 1

    def test_una_curva_sin_ninguna_serie_con_valores_se_rechaza(self, taller):
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross(taller, {"kind": "curva",
                                  "data": {"equity_curve": [{"date": "d1", "equity": None}]}})
        assert e.value.code == "artifact_shape_unusable"


# ── LAS TRES LECTURAS DE UNA LISTA VACÍA ──────────────────────────────────────────────

class TestTresLecturasDelVacio:
    """El hallazgo que la medición obligó a hacer: una lista vacía es tres cosas."""

    def test_a_la_tool_fallo_y_lo_confiesa(self, taller):
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross(taller, {"kind": "tabla",
                                  "data": {"count": 0, "results": [],
                                           "note": "Screener could not run: expresión inválida"}})
        assert e.value.code == "workspace_tool_failed"
        # La causa viaja CON EL TEXTO DEL ORIGEN: decir «llegó sin filas» taparía el fallo.
        assert "could not run" in e.value.detail

    def test_b_la_tool_corrio_y_no_encontro_nada_degrada_a_informe(self, taller):
        obra = bridge.cross(taller, {"kind": "tabla",
                                     "data": {"scanned": 120, "matches": 0, "results": [],
                                              "note": "No matching setups were found."}})
        # El cero MEDIDO es un resultado, no un error — y tampoco es una planilla vacía.
        assert obra["type"] == "informe"
        assert "120" in obra["content"]
        assert "No matching setups" in obra["content"]

    def test_c_no_vino_la_lista_y_nada_dice_por_que(self, taller):
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross(taller, {"kind": "tabla", "data": {"query": "q"}})
        assert e.value.code == "artifact_shape_unusable"

    def test_la_degradacion_tiene_que_estar_declarada_en_la_fila(self, taller):
        # `_table` puede devolver informe; la fila lo declara en `degrades_to`. Si alguien
        # borra esa declaración, el assert del puente cae — la tabla dejaría de describir
        # lo que el código hace, y una tabla que miente es peor que no tenerla.
        assert "informe" in bridge.TABLE[taller]["tabla"]["degrades_to"]


# ── LA CONTABILIDAD ES OBLIGATORIA ────────────────────────────────────────────────────

def test_cada_fila_declara_su_contabilidad(taller):
    """`shape_changes` y `never_filled` no son decoración: son lo que la Fase 6 extrae.
    Una fila sin ellos es una fila escrita de intuición, no de una medición."""
    for kind, fila in bridge.TABLE[taller].items():
        assert str(fila.get("shape_changes", "")).strip(), f"{kind} sin shape_changes"
        assert str(fila.get("never_filled", "")).strip(), f"{kind} sin never_filled"
        assert callable(fila.get("adapt")), f"{kind} sin adaptador"


# ── CIENCIA · LOS 10 CASOS EJECUTADOS ─────────────────────────────────────────────────

class TestCiencia:
    """Las 10 clases del stack de Ciencia, con los payloads que su clasificador devolvió
    de verdad sobre archivos de verdad.

    CÓMO SE MIDIERON: se levantó el stack sobre el proyecto que dejó la corrida de TP53
    —con su FASTA, su figura y su informe— y se crearon archivos genuinos de las clases
    que faltaban (un .ipynb válido, un PDB con átomos, un VCF con la variante R175H de
    TP53, un pickle, un zip). `GET /file/artifacts` clasificó los 13 y devolvió las 10
    clases. Los payloads de abajo son ESOS, copiados tal cual — no una paráfrasis.
    """

    #: La forma REAL, medida: el stack entrega una REFERENCIA, no el dato.
    REFERENCIAS = {
        "report":    {"name": "hallazgos.md", "path": "hallazgos.md", "kind": "report", "format": "md", "size": 648},
        "figure":    {"name": "tp53_composicion.png", "path": "tp53_composicion.png", "kind": "figure", "format": "png", "size": 49669},
        "dataset":   {"name": "composicion.csv", "path": "composicion.csv", "kind": "dataset", "format": "csv", "size": 93},
        "notebook":  {"name": "analisis.ipynb", "path": "analisis.ipynb", "kind": "notebook", "format": "ipynb", "size": 479},
        "structure": {"name": "modelo.pdb", "path": "modelo.pdb", "kind": "structure", "format": "pdb", "size": 308},
        "sequence":  {"name": "tp53_P04637.fasta", "path": "tp53_P04637.fasta", "kind": "sequence", "format": "fasta", "size": 490},
        "genomics":  {"name": "variantes.vcf", "path": "variantes.vcf", "kind": "genomics", "format": "vcf", "size": 131},
        "spectrum":  {"name": "espectro.mzml", "path": "espectro.mzml", "kind": "spectrum", "format": "mzml", "size": 66},
        "model":     {"name": "modelo.pkl", "path": "modelo.pkl", "kind": "model", "format": "pkl", "size": 58},
        "archive":   {"name": "entrega.zip", "path": "entrega.zip", "kind": "archive", "format": "zip", "size": 622},
    }

    def test_las_diez_clases_cruzan(self):
        assert set(bridge.kinds("ciencia")) == set(self.REFERENCIAS)
        for kind, ref in self.REFERENCIAS.items():
            obra = bridge.cross("ciencia", {"kind": kind, "name": ref["name"], "data": ref})
            assert vocabulary.normalize(obra["type"]) == obra["type"]
            assert obra["title"] == ref["name"]

    def test_una_referencia_da_ficha_honesta_jamas_forma_vacia(self):
        """Con sólo la referencia no hay planilla ni imagen posible: hay una ficha que
        dice lo que se sabe. Una grilla en blanco o un marco vacío serían una mentira."""
        for kind in ("figure", "dataset"):
            obra = bridge.cross("ciencia", {"kind": kind, "name": "x", "data": self.REFERENCIAS[kind]})
            assert obra["type"] == "informe"
            assert "rows" not in obra and "cols" not in obra
            # Una ficha es un informe con SU markdown: nunca un data URI en `content`.
            assert not str(obra.get("content", "")).startswith("data:")
            # La ficha DICE el formato y el tamaño reales; no los adivina.
            assert self.REFERENCIAS[kind]["format"] in obra["content"]

    def test_con_el_dato_sale_el_tipo_rico(self):
        o = bridge.cross("ciencia", {"kind": "report", "name": "hallazgos.md",
                                     "data": {"name": "hallazgos.md", "content": "# 393 aa"}})
        assert o["type"] == "informe" and "393" in o["content"]

        # EL SOBRE YA ARMADO sigue entrando — y sale por `content`, que es el campo que
        # el renderer lee (`sala-render.js:577`). Emitíamos `data_uri`, que no lo consume
        # NADIE en el árbol: toda imagen de este puente pintaba «Sin imagen.».
        o = bridge.cross("ciencia", {"kind": "figure", "name": "f.png",
                                     "data": {"name": "f.png", "data_uri": "data:image/png;base64,iVBOR"}})
        assert o["type"] == "imagen" and o["content"].startswith("data:image/png")
        assert "data_uri" not in o

        filas = [{"residuo": "P", "conteo": 45}, {"residuo": "S", "conteo": 38}]
        o = bridge.cross("ciencia", {"kind": "dataset", "name": "c.csv",
                                     "data": {"name": "c.csv", "rows": filas, "columns": ["residuo", "conteo"]}})
        assert o["type"] == "planilla" and o["rows"] == filas and o["cols"] == ["residuo", "conteo"]

    def test_jamas_el_dato(self):
        """Un artefacto sin nada adentro se rechaza CON CAUSA, no se rellena."""
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross("ciencia", {"kind": "report", "name": "x", "data": {}})
        assert e.value.code == "artifact_data_missing"
        assert bridge.CAUSES[e.value.code].strip()

    def test_un_kind_que_el_stack_no_emite_no_se_inventa(self):
        with pytest.raises(bridge.BridgeError) as e:
            bridge.cross("ciencia", {"kind": "equity_curve", "data": {"a": 1}})
        assert e.value.code == "workspace_kind_unknown"

    def test_lo_que_ciencia_reclama_y_lo_que_cae_a_la_base(self):
        """Ley 4 y 7: lo no reclamado NO se rechaza — cae a la base, que es el suelo
        común. Un `cad` de otro workspace se ve ahí, no se pierde ni rompe nada."""
        for t in ("informe", "imagen", "planilla"):
            assert bridge.claims("ciencia", t) is True
        for t in ("cad", "dicom", "volume3d", "linechart"):
            assert bridge.claims("ciencia", t) is False


# ── DOS CASOS SINTÉTICOS DE ARTEFACTOS DURABLES ───────────────────────────────────────

class TestCaminataDelDueno:
    """Dos registros sintéticos con la forma de artefactos DURABLES.

    Lo que estos dos casos agregaron a la tabla:
    un artefacto PROMOVIDO a durable trae `sha256`, `version` y `captureQuality`, y la
    primera versión de la ficha los tiraba. Llevarlos es forma; tirarlos era perder la
    única prueba de que el artefacto es el que dice ser.
    """

    #: `captureQuality: "declared"` es del vocabulario del propio stack, y es exactamente
    #: lo que el contrato de artefactos pide para lo que nace de sus funciones.
    TOP10 = {"name": "synthetic_top10.png", "path": "/tmp/aleph-fixture/synthetic_top10.png",
             "kind": "figure", "format": "png", "size": 1024, "version": 1,
             "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             "captureQuality": "declared"}
    ALPHAFOLD = {"name": "synthetic_3d.png", "path": "/tmp/aleph-fixture/synthetic_3d.png",
                 "kind": "figure", "format": "png", "size": 2048, "version": 1,
                 "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "captureQuality": "declared"}

    @pytest.mark.parametrize("data", [TOP10, ALPHAFOLD])
    def test_la_ficha_lleva_la_procedencia_entera(self, data):
        obra = bridge.cross("ciencia", {"kind": "figure", "name": data["name"], "data": data})
        assert obra["type"] == "informe"
        for prueba in (data["sha256"], str(data["version"]), data["captureQuality"]):
            assert prueba in obra["content"], f"la ficha perdió «{prueba}»"

    @pytest.mark.parametrize("data", [TOP10, ALPHAFOLD])
    def test_ciencia_reclama_los_dos(self, data):
        obra = bridge.cross("ciencia", {"kind": "figure", "name": data["name"], "data": data})
        assert bridge.claims("ciencia", obra["type"]) is True

    def test_lo_que_NO_calza_por_tipo_cae_a_la_base(self):
        """En estos dos casos nada cayó a la base, y eso es correcto: los dos cruzaron a
        `informe`, que Ciencia acepta. La base es para lo que llega de OTRO workspace con
        un tipo que éste no muestra — y entonces no se rechaza: se ve en el suelo común
        (ley 4). Se afirma acá para que la regla quede medida y no supuesta."""
        for t in ("informe", "imagen", "planilla"):
            assert bridge.claims("ciencia", t) is True
        for ajeno in ("cad", "dicom", "volume3d", "linechart", "3d"):
            assert bridge.claims("ciencia", ajeno) is False, f"{ajeno} no debería reclamarse"

    def test_los_bytes_del_png_jamas_se_inventan(self):
        """El título del artefacto NARRA pLDDT medio 52.90 y las 6 cisteínas. Eso es del
        cálculo del stack: la ficha no lo re-deriva de la imagen ni lo copia como si lo
        hubiera medido."""
        obra = bridge.cross("ciencia", {"kind": "figure", "name": "x.png", "data": self.ALPHAFOLD})
        assert obra["type"] == "informe"
        assert "52.90" not in obra["content"] and "pLDDT" not in obra["content"]


class TestArtefactosDeCienciaLleganALaPantalla:
    """LA VARA DE ESTA OBRA: el oficio de Ciencia produce graficas, cuadernos e informes,
    y ninguno de los tres llegaba PINTADO a la pantalla.

    Los tres payloads de aca NO son inventados: son la forma exacta que arma
    `platform/workspaces/plugins/openscience.js:154-168` - lee el archivo del disco y
    cruza `content` (base64 para `figure`/`image`, utf8 para el resto) mas `encoding`,
    `path` y `format`. Los adaptadores conocian OTROS sobres (`data_uri` ya armado, filas
    ya estructuradas), asi que el `if` fallaba siempre y las tres cosas degradaban a la
    ficha de un archivo. Cada test de abajo se puso ROJO antes del arreglo.
    """

    # Un PNG de 1x1 real (no un string que se le parece): los bytes tienen que pasar el
    # olfateo de firma, que es lo que decide el mime.
    PNG_1x1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGNgAAACAAEA//8DAAAGAAVXv6vUAAAAAElFTkSuQmCC"

    def _figura(self, **extra):
        d = {"name": "figura sintética", "path": "synthetic_top10.png",
             "format": "png", "bytes": 1024,
             "content": self.PNG_1x1, "encoding": "base64"}
        d.update(extra)
        return {"kind": "figure", "name": d["name"], "data": d}

    def test_la_grafica_sale_pintable_y_no_como_ficha_de_archivo(self):
        obra = bridge.cross("ciencia", self._figura())
        assert obra["type"] == "imagen", "una figura con sus bytes no es una ficha"
        # El campo tiene que ser el que el renderer LEE. Ver `sala-render.js:577`
        # (`a.content || a.url`) y su validador de forma en `:745`.
        assert obra["content"].startswith("data:image/png;base64,")
        assert obra["content"].endswith(self.PNG_1x1)
        # Y una sola llave de mas marcaria la obra como RICA en `router.py:6064`, que le
        # mete el JSON entero adentro de `content` y rompe el camino de vuelta.
        assert set(obra) == {"type", "title", "content"}

    def test_el_nombre_del_artefacto_es_una_frase_y_la_extension_vive_en_la_ruta(self):
        """Ciencia manda `name` = la ETIQUETA (una frase, sin punto). Resolver la
        extension solo desde `name` mandaba TODA figura a la ficha."""
        obra = bridge.cross("ciencia", self._figura())
        assert obra["type"] == "imagen"
        assert obra["title"] == "figura sintética"

    def test_los_bytes_le_ganan_a_la_extension_declarada(self):
        """La trampa que ya esta escrita en el archivo: creerle a una sola fuente. Un
        `.png` que por dentro es un PDF armaria un data URI bien formado que ningun
        navegador puede pintar - el marco vacio, ahora con la bendicion del puente."""
        import base64
        pdf = base64.b64encode(b"%PDF-1.7\nno soy una imagen").decode()
        obra = bridge.cross("ciencia", self._figura(content=pdf))
        assert obra["type"] == "informe", "unos bytes que no son imagen no se pintan"
        assert not obra["content"].startswith("data:")

    def test_sin_bytes_sigue_saliendo_la_ficha(self):
        """Lo que esta obra NO cambia: solo la referencia -> la ficha honesta de siempre."""
        obra = bridge.cross("ciencia", {"kind": "figure", "name": "f.png", "data": {
            "name": "f.png", "path": "f.png", "format": "png", "bytes": 44962}})
        assert obra["type"] == "informe"
        # Y la ficha DICE el tamano: el plugin lo manda en `bytes` y `_CAMPOS_FICHA` no
        # miraba esa llave, asi que la unica cifra que la ficha tenia se perdia.
        assert "bytes" in obra["content"] and "44" in obra["content"]

    def test_el_csv_crudo_se_parte_en_grilla(self):
        """El plugin manda el CSV tal como salio del disco, en `content` utf8. Buscar
        `rows`/`records` en la raiz no lo encontraba nunca."""
        obra = bridge.cross("ciencia", {"kind": "dataset", "name": "composicion.csv", "data": {
            "name": "composicion.csv", "path": "composicion.csv", "format": "csv",
            "encoding": "utf8", "content": "aa,n,pct\nLeu,6,20.0\nCys,6,20.0\nGly,4,13.3\n"}})
        assert obra["type"] == "planilla"
        assert obra["cols"] == ["aa", "n", "pct"]
        assert obra["rows"] == [["Leu", "6", "20.0"], ["Cys", "6", "20.0"], ["Gly", "4", "13.3"]]

    def test_el_tsv_tambien_y_no_como_una_columna_mentirosa(self):
        obra = bridge.cross("ciencia", {"kind": "dataset", "name": "c.tsv", "data": {
            "name": "c.tsv", "path": "c.tsv", "format": "tsv", "encoding": "utf8",
            "content": "aa\tn\nLeu\t6\nCys\t6\n"}})
        assert obra["type"] == "planilla" and obra["cols"] == ["aa", "n"]

    # -- EL CUADERNO --------------------------------------------------------------------
    CUADERNO = {
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {"cell_type": "markdown", "source": ["# Composicion de TP53\n"]},
            {"cell_type": "code",
             "source": ["import matplotlib.pyplot as plt\n", "plt.bar(aa, n)\n"],
             "outputs": [{"output_type": "display_data", "data": {
                 "image/png": PNG_1x1,
                 "text/plain": ["<Figure size 640x480 with 1 Axes>"]}}]},
            {"cell_type": "code", "source": ["print(total)\n"],
             "outputs": [{"output_type": "stream", "name": "stdout", "text": ["17358.56\n"]}]},
            {"cell_type": "code", "source": ["1/0\n"],
             "outputs": [{"output_type": "error", "ename": "ZeroDivisionError",
                          "evalue": "division by zero",
                          "traceback": ["[0;31mZeroDivisionError[0m: division by zero"]}]},
            {"cell_type": "code", "source": ["# nunca corrio\n"], "outputs": []},
        ],
    }

    def _cruzar_cuaderno(self, nb):
        return bridge.cross("ciencia", {"kind": "notebook", "name": "analisis.ipynb", "data": {
            "name": "analisis.ipynb", "path": "analisis.ipynb", "format": "ipynb",
            "encoding": "utf8", "content": json.dumps(nb)}})

    def test_el_cuaderno_se_lee_en_vez_de_ser_un_muro_de_json(self):
        obra = self._cruzar_cuaderno(self.CUADERNO)
        cuerpo = obra["content"]
        assert obra["type"] == "informe"
        # Lo que se veia antes: la serializacion cruda del cuaderno.
        assert not cuerpo.lstrip().startswith("{")
        assert chr(34) + "cell_type" + chr(34) not in cuerpo
        assert chr(34) + "outputs" + chr(34) not in cuerpo
        # Lo que se ve ahora: el markdown, el codigo en su fence, la figura embebida,
        # la salida de stdout y el error del kernel sin sus codigos ANSI.
        assert "# Composicion de TP53" in cuerpo
        assert "```python\nimport matplotlib.pyplot as plt\nplt.bar(aa, n)\n```" in cuerpo
        assert "![](data:image/png;base64," + self.PNG_1x1 + ")" in cuerpo
        assert "17358.56" in cuerpo
        assert "ZeroDivisionError: division by zero" in cuerpo
        assert "" not in cuerpo, "la traza del kernel viaja con color ANSI"

    def test_la_imagen_le_gana_al_texto_plano_de_la_misma_salida(self):
        """Un plot llega como png Y como `<Figure size ...>`. Mostrar el texto seria
        entregar la descripcion de la figura en vez de la figura."""
        cuerpo = self._cruzar_cuaderno(self.CUADERNO)["content"]
        assert "<Figure size 640x480" not in cuerpo

    def test_una_celda_que_nunca_corrio_sale_sin_salida_inventada(self):
        cuerpo = self._cruzar_cuaderno(self.CUADERNO)["content"]
        assert "```python\n# nunca corrio\n```" in cuerpo

    def test_un_ipynb_ilegible_no_se_rompe_ni_se_traga(self):
        obra = bridge.cross("ciencia", {"kind": "notebook", "name": "roto.ipynb", "data": {
            "name": "roto.ipynb", "path": "roto.ipynb", "format": "ipynb",
            "encoding": "utf8", "content": "esto no es JSON"}})
        assert obra["type"] == "informe" and obra["content"] == "esto no es JSON"

    def test_un_cuaderno_vacio_es_ficha_y_no_un_panel_en_blanco(self):
        obra = self._cruzar_cuaderno({"cells": []})
        assert obra["type"] == "informe" and "analisis.ipynb" in obra["content"]

    def test_las_imagenes_del_cuaderno_tienen_tope_y_se_dice_cuando_se_pasa(self):
        """Sin truncar en silencio: el tope es el mismo que la casa ya declaro para una
        obra, y la salida omitida DICE que lo esta."""
        gorda = "A" * (bridge._TOPE_IMAGENES_CUADERNO + 10)
        obra = self._cruzar_cuaderno({"cells": [
            {"cell_type": "code", "source": ["plt.show()\n"],
             "outputs": [{"output_type": "display_data", "data": {"image/png": gorda}}]}]})
        assert "salida omitida" in obra["content"] and str(len(gorda)) in obra["content"]
        assert gorda not in obra["content"]
