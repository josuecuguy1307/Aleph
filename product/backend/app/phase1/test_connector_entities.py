from __future__ import annotations

from pathlib import Path
import sys

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_PLATFORM = Path(__file__).resolve().parents[4] / "platform"
for _path in (str(_BACKEND), str(_PLATFORM)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.phase1.atoms_router import collect_atoms  # noqa: E402


@pytest.fixture(autouse=True)
def _dir_de_datos_aislado(tmp_path, monkeypatch):
    """El catálogo de este test es EL DE LA CAJA, no el de la máquina que lo corre.

    ⚠️ `collect_atoms()` camina también el `synth_belts` del dir de datos — o sea las
    piezas que quien corre el test haya traído. Sin aislar, los números sellados de acá
    (63 entradas legacy, las 48 entidades con su símbolo) medían el escritorio del
    desarrollador: con 8 piezas traídas daban 101 y 86, y el test rojeaba por tener datos,
    no por una regresión. Un golden que depende de la máquina no es un golden.

    Se aísla con `ALEPH_DATA_DIR` a un tmp vacío, que es la misma perilla que usan las
    varas. Lo que las piezas traídas hacen con la proyección se mide donde corresponde:
    `qa/verify_pieza_en_el_cuarto.py`, con su fixture propio.
    """
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path / "datos"))
from app.phase1.connector_entities import (  # noqa: E402
    DIORAMA_SYMBOLS,
    assert_unique_logos,
    build_entities,
    stable_tool_aliases,
)


EXPECTED_DIORAMA_SYMBOLS = {
    "alphavantage": "datos", "arxiv": "leer", "backtest": "calculo",
    "biomcp": "leer", "cad": "calculo", "ccxt": "datos", "chart": "media",
    "coingecko": "datos", "context7": "leer", "crossref": "leer",
    "datatools": "escribir", "dicom": "leer", "duckduckgo": "buscar",
    "exa": "buscar", "excel": "datos", "fem": "calculo", "fetch": "leer",
    "filesystem": "almacenamiento", "fred": "datos", "freecad": "calculo",
    "git": "codigo", "github": "codigo", "globalfishingwatch": "datos",
    "gmail": "comunicacion", "huggingface": "generico", "jupyter": "codigo",
    "kicad": "calculo", "maad": "media", "maritime": "datos",
    "massive": "datos", "materialsproject": "datos", "openalex": "leer",
    "openfda": "datos", "openfoam": "calculo", "opensanctions": "datos",
    "orcid": "leer", "pandoc": "escribir", "precio": "datos",
    "pubmed": "leer", "pysandbox": "codigo", "script_runner": "codigo",
    "secedgar": "datos", "segmentacion": "calculo", "spice": "calculo",
    "sqlite": "datos", "wikipedia": "leer", "yfinance": "datos",
    "zotero": "leer",
}


def test_migracion_63_sin_perdida_y_fred_es_una_entidad():
    data = build_entities(collect_atoms())
    migration = data["migration"]

    assert migration["legacy_entries"] == 63
    assert migration["legacy_mcp_entries"] == 46
    assert migration["legacy_credential_entries"] == 17
    assert migration["tools_before_visible"] == 157
    assert migration["tools_before_declared"] == migration["tools_after"] == 160
    assert migration["tools_lost"] == []
    assert migration["orphaned"] == []

    fred_rows = [entity for entity in data["entities"] if entity["id"] == "fred"]
    assert len(fred_rows) == 1
    fred = fred_rows[0]
    assert fred["name"] == "FRED"
    assert fred["logo"] == "fred"
    assert fred["tool_count"] == 8
    assert [(server["name"], len(server["tools"])) for server in fred["servers"]] == [
        ("fred", 5),
        ("fred_official", 3),
    ]
    assert {
        server["credential_binding"]["credential_provider"]
        for server in fred["servers"]
    } == {"fred"}
    assert {
        server["credential_binding"]["runtime_provider"]
        for server in fred["servers"]
    } == {"fred", "feedoracle"}

    conversion = next(
        row for row in migration["credential_conversions"]
        if row["legacy_entry"] == "credential:fred"
    )
    assert conversion == {
        "legacy_entry": "credential:fred",
        "provider": "fred",
        "entity": "fred",
        "converted_to": "entity:fred.credential",
        "visible_piece": False,
    }


def test_las_48_entidades_visibles_tienen_simbolo_funcional_curado():
    data = build_entities(collect_atoms())
    actual = {
        entity["id"]: entity["diorama_symbol"]
        for entity in data["entities"]
    }
    assert actual == EXPECTED_DIORAMA_SYMBOLS
    assert set(actual.values()) <= DIORAMA_SYMBOLS
    assert actual["huggingface"] == "generico"


def test_simbolo_ausente_o_invalido_degrada_a_generico():
    data = build_entities([
        {
            "id": "future-service", "service": "future-service",
            "server": "future-server", "belt_ref": "qa/future.mcp.json",
            "tools": ["future_tool"], "auth": "keyless",
        },
    ])
    assert data["entities"][0]["diorama_symbol"] == "generico"


def test_credencial_compartida_se_resuelve_una_vez_para_dos_entidades():
    atoms = [
        {
            "id": "uno", "service": "uno", "server": "server_uno",
            "belt_ref": "qa/uno.mcp.json", "tools": ["read_one"],
            "auth": "token", "credential_provider": "shared",
        },
        {
            "id": "dos", "service": "dos", "server": "server_dos",
            "belt_ref": "qa/dos.mcp.json", "tools": ["read_two"],
            "auth": "token", "credential_provider": "shared",
        },
    ]
    data = build_entities(atoms, key_rows=[{
        "provider": "shared", "last4": "1234", "created_at": "2026-07-28T00:00:00Z",
    }])
    assert len(data["entities"]) == 2
    assert {
        entity["credential"]["provider"] for entity in data["entities"]
    } == {"shared"}
    assert all(entity["credential"]["connected"] for entity in data["entities"])


def test_alias_de_colision_es_unico_y_estable():
    servers = [
        {"name": "beta", "tools": ["search", "other"]},
        {"name": "alpha", "tools": ["search"]},
    ]
    first = stable_tool_aliases(servers)
    second = stable_tool_aliases(reversed(servers))
    assert first == second
    assert first["alpha"]["search"] == "alpha__search"
    assert first["beta"]["search"] == "beta__search"
    assert first["beta"]["other"] == "other"
    assert len({
        final for mapping in first.values() for final in mapping.values()
    }) == 3


def test_calibracion_roja_logo_duplicado_dispara_la_guarda():
    with pytest.raises(ValueError, match="logo duplicado"):
        assert_unique_logos([
            {"id": "uno", "logo": "misma-marca"},
            {"id": "dos", "logo": "misma-marca"},
        ])


def test_nombre_y_descripcion_oficiales_tienen_precedencia():
    data = build_entities([
        {
            "id": "community-package", "service": "vendor", "server": "community",
            "belt_ref": "qa/community.mcp.json", "tools": ["search"],
            "auth": "keyless", "label": "Nombre del paquete",
            "sub": "Una descripción comunitaria mucho más larga que no debe ganar.",
        },
        {
            "id": "vendor-official", "service": "vendor", "server": "official",
            "belt_ref": "qa/official.mcp.json", "tools": ["get"],
            "auth": "keyless", "label": "Vendor", "sub": "Descripción oficial.",
            "official": True,
        },
    ])
    entity = data["entities"][0]
    assert entity["official"] is True
    assert entity["name"] == "Vendor"
    assert entity["description"] == "Descripción oficial."
