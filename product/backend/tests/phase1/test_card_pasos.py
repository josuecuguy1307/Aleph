"""Regresión de la card de reparación: las precondiciones llegan medidas, no supuestas."""
from pathlib import Path

from app.phase1 import motor_verdad as motor


def test_placeholder_mcp_nombra_el_paquete_y_no_la_app_kicad():
    cmd = "<mcp-install>/mcp-kicad-sch-api/.venv/bin/python"
    got = motor._instalacion_de(cmd, Path(cmd))
    assert got == {
        "programa": "mcp-kicad-sch-api",
        "paquete": "mcp-kicad-sch-api",
    }
    assert got.get("como") is None


def test_precondicion_de_ruta_se_mide(tmp_path):
    presente = tmp_path / "Programa.app"
    presente.mkdir()
    si = motor._medir_precondicion({
        "id": "programa", "tipo": "ruta", "ruta": str(presente),
    })
    no = motor._medir_precondicion({
        "id": "programa", "tipo": "ruta", "ruta": str(tmp_path / "Falta.app"),
    })
    assert si["comprobada"] is True and si["cumplida"] is True
    assert no["comprobada"] is True and no["cumplida"] is False


def test_precondicion_humana_tcp_no_confirma_sin_escucha():
    got = motor._medir_precondicion({
        "id": "addon",
        "tipo": "humana",
        "verificacion": {"tipo": "tcp", "host": "127.0.0.1", "port": 1},
    })
    assert got["comprobada"] is True
    assert got["cumplida"] is False
    assert "no responde" in got["evidencia"]


def test_servicio_sin_precondiciones_devuelve_lista_vacia():
    assert motor._precondiciones_de({}) == []
    assert motor._precondiciones_de({"reparacion": {}}) == []
    assert motor._precondiciones_de({
        "reparacion": {"precondiciones": None},
    }) == []
