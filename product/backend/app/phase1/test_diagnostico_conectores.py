"""Varas del diagnosticador: evidencia, cubos cerrados y remedio con manos."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2]
_PLATFORM = Path(__file__).resolve().parents[4] / "platform"
for _path in (str(_BACKEND), str(_PLATFORM)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.phase1 import diagnostico_conectores as diag  # noqa: E402
from app.phase1 import motor_verdad as motor  # noqa: E402
from app.phase1 import remedios_conectores as remedios  # noqa: E402
from inspection import byo_mcp  # noqa: E402
from inspection import mcp_http_client  # noqa: E402


def _script(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "server_roto.py"
    path.write_text(source, encoding="utf-8")
    return path


def _afirmar_server_roto(veredicto: dict) -> None:
    text = json.dumps(veredicto, ensure_ascii=False).lower()
    assert veredicto["patron"]["codigo"] == "server_roto_o_incompatible"
    # LEY · LA CONFESIÓN ES INTERNA (persona usuaria, 2026-08-04). El título decía «Este servidor está
    # roto o es incompatible — no es tu configuración»: jerga («servidor») más una disculpa.
    # Lo que el usuario ve es la tercera salida declarada; lo técnico NO se perdió, y las
    # dos mitades se afirman juntas para que nadie pueda «cumplir la ley» borrando evidencia.
    assert veredicto["presentacion"]["titulo"] == "No disponible por ahora."
    assert veredicto["patron"]["codigo"] == "server_roto_o_incompatible"   # la causa, intacta
    assert "traceback" in veredicto["evidencia"]["stderr"].lower()         # la evidencia, intacta
    assert "proveedor" not in text
    assert "revisá el comando" not in text
    assert "revisa el comando" not in text


def test_stdio_captura_traceback_y_exit_code(tmp_path):
    bad = _script(
        tmp_path,
        "raise ModuleNotFoundError(\"No module named 'mcp.server.fastmcp'\")\n",
    )
    out = motor.prueba_mcp(spec={
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(bad)],
    })
    _afirmar_server_roto(out["veredicto"])
    assert out["evidencia"]["exit_code"] != 0
    assert out["evidencia"]["red"]["consultada"] is False
    assert out["veredicto"]["escalon"] == "local"


def test_attribute_error_del_sdk_es_la_misma_clase():
    raw = (
        'Traceback (most recent call last):\n  File "git_server.py", line 9\n'
        "AttributeError: 'Server' object has no attribute 'list_tools'"
    )
    out = diag.producir({
        "tipo": "mcp", "ref": "git", "estado": "roto", "causa": "error_upstream",
        "evidencia": {
            "stderr": raw, "exit_code": 1, "transport": "stdio", "destino": "uvx",
            "red": {"consultada": False},
        },
    })
    _afirmar_server_roto(out)


_SERVER_QUE_RECHAZA_EL_SALUDO = (
    "import json, sys\n"
    "request = json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {\n"
    "  'code': -32022, 'message': 'Unsupported protocol version',\n"
    "  'data': {'requested': request['params']['protocolVersion'],\n"
    "           'supported': ['2026-07-28']}}}), flush=True)\n"
)


def _hay_sdk() -> bool:
    try:
        from inspection import transporte as TP
        return bool(TP._hay_sdk()[0])
    except Exception:                                      # noqa: BLE001
        return False


def _deriva_con(transporte, tmp_path, monkeypatch):
    """Corre la prueba REAL contra un server que rechaza el saludo, con el transporte
    pedido. Devuelve el veredicto."""
    if transporte == "sdk" and not _hay_sdk():
        pytest.skip("sin `mcp` en este intérprete — la mitad `sdk` la cubre la vara del "
                    "venv del producto, que sí lo tiene")
    monkeypatch.setenv("ALEPH_TRANSPORTE", transporte)
    for nombre in list(sys.modules):
        if nombre.split(".")[0] in {"transporte", "transporte_sdk"}:
            sys.modules.pop(nombre, None)
    server = _script(tmp_path, _SERVER_QUE_RECHAZA_EL_SALUDO)
    out = motor.prueba_mcp(spec={
        "transport": "stdio", "command": sys.executable, "args": [str(server)],
    })
    return out["veredicto"]


@pytest.mark.parametrize("transporte", ["viejo", "sdk"])
def test_deriva_de_protocolo_captura_ambas_revisiones(tmp_path, monkeypatch, transporte):
    """LA MISMA DERIVA, POR LOS DOS TRANSPORTES (recableo · sesión 2).

    Lo que NO puede cambiar es el veredicto: `deriva_protocolo`, escalón local, las dos
    revisiones capturadas y la respuesta cruda con el -32022. Lo que SÍ cambia —y es
    correcto— son los NÚMEROS: cada cliente pide la revisión que pide. El viejo manda
    `2024-11-05` clavado en una constante; el SDK manda `LATEST_HANDSHAKE_VERSION`
    (`2025-11-25`, medido — no `LATEST_PROTOCOL_VERSION`, que es otra constante y se usa
    en `server/discover`). Fijar el número acá ataría la vara a un cliente.

    Regresión que este test cazó: el puente NO registraba la evidencia de protocolo cuando
    el saludo se rechazaba, así que la deriva se perdía y el fallo caía a `no_habla_mcp`.
    """
    verdict = _deriva_con(transporte, tmp_path, monkeypatch)
    assert verdict["patron"]["codigo"] == "deriva_protocolo"
    assert verdict["causa"] == "deriva_protocolo"
    assert verdict["escalon"] == "local"
    proto = verdict["evidencia"]["protocolo"]
    assert proto["servidor"] == "2026-07-28"
    assert proto["cliente"] and proto["cliente"] != proto["servidor"]
    assert '"code": -32022' in verdict["evidencia"]["respuesta"]
    # LEY · las dos revisiones del protocolo son dato NUESTRO: siguen enteras en
    # `evidencia.protocolo` (asertado arriba) y salen de la card, que ahora sólo dice lo
    # accionable. Poner dos números de protocolo delante del usuario no lo ayudaba a nada.
    assert verdict["presentacion"]["titulo"] == "No disponible por ahora."


def test_la_revision_que_pide_cada_cliente_es_la_suya(tmp_path, monkeypatch):
    """El número no es incidental: es lo que el registro persiste en `version_negociada`.
    Se fija cuál pide cada uno para que un cambio de constante no pase inadvertido."""
    viejo = _deriva_con("viejo", tmp_path, monkeypatch)["evidencia"]["protocolo"]["cliente"]
    assert viejo == "2024-11-05", "el cliente viejo dejó de pedir su constante"
    try:
        from inspection import transporte as TP
        hay, _ = TP._hay_sdk()
    except Exception:                                      # noqa: BLE001
        hay = False
    if not hay:
        pytest.skip("sin SDK en este intérprete: la mitad `sdk` la cubre la vara del venv")
    nuevo = _deriva_con("sdk", tmp_path, monkeypatch)["evidencia"]["protocolo"]["cliente"]
    assert nuevo == "2025-11-25", f"el SDK cambió su LATEST_HANDSHAKE_VERSION: {nuevo}"


def test_error_de_protocolo_sin_los_dos_lados_no_inventa_version():
    out = diag.producir({
        "tipo": "mcp", "ref": "sin-version", "estado": "roto",
        "evidencia": {
            "transport": "stdio", "red": {"consultada": False},
            "respuesta": {
                "error": {
                    "code": -32022,
                    "message": "Unsupported protocol version",
                    "data": {"requested": "2024-11-05", "supported": []},
                },
            },
        },
    })
    assert out["patron"]["codigo"] == "desconocido"
    assert "2026-07-28" not in json.dumps(out, ensure_ascii=False)


def test_deriva_http_transporta_payload_estructurado(monkeypatch):
    client = mcp_http_client.MCPHttpClient("https://mcp.example.test")
    response = {
        "jsonrpc": "2.0", "id": 1,
        "error": {
            "code": -32022, "message": "Unsupported protocol version",
            "data": {
                "requested": "2024-11-05",
                "supported": ["2026-07-28"],
            },
        },
    }
    monkeypatch.setattr(client, "_post", lambda payload: response)
    with pytest.raises(mcp_http_client.MCPHttpError) as caught:
        client._rpc("initialize", {})
    evidence = caught.value.evidencia
    out = diag.producir({
        "tipo": "mcp", "ref": client.url, "estado": "roto",
        "evidencia": {**evidence, "transport": "http", "destino": client.url},
    })
    assert out["patron"]["codigo"] == "deriva_protocolo"
    assert out["escalon"] == "nuestro"
    assert out["evidencia"]["respuesta"].startswith('{"error"')
    assert out["evidencia"]["protocolo"]["servidor"] == "2026-07-28"


def test_stderr_acotado_conserva_las_ultimas_lineas(tmp_path):
    bad = _script(
        tmp_path,
        "import sys\n"
        "for i in range(140): print('linea-' + str(i), file=sys.stderr)\n"
        "raise ImportError('sdk incompatible al final')\n",
    )
    with pytest.raises(byo_mcp.BYOValidationError) as caught:
        byo_mcp.probe_mcp(
            transport="stdio", command=sys.executable, args=[str(bad)], timeout=2,
        )
    ev = caught.value.evidencia
    assert ev["stderr_lineas"] <= ev["stderr_cap_lineas"] == 80
    assert ev["stderr_bytes"] <= ev["stderr_cap_bytes"] == 32 * 1024
    assert "sdk incompatible al final" in ev["stderr"]
    assert "linea-0\n" not in ev["stderr"]


def test_proceso_que_no_completa_saludo_se_clasifica_sin_perder_crudo(tmp_path):
    bad = _script(tmp_path, "import sys\nprint('zebra 7 %% ruido', file=sys.stderr)\nraise SystemExit(9)\n")
    out = motor.prueba_mcp(spec={
        "transport": "stdio", "command": sys.executable, "args": [str(bad)],
    })
    verdict = out["veredicto"]
    # LEY · «no habla como un servidor MCP» es vocabulario nuestro. El código de patrón y la
    # causa —lo que repair y el [?] consumen— no se tocan.
    assert verdict["patron"] == {
        "codigo": "no_habla_mcp", "reconocido": True,
        "mensaje": "No disponible por ahora.",
    }
    assert verdict["causa"] == "no_es_mcp"
    assert "zebra 7 %% ruido" in verdict["presentacion"]["detalle"]
    assert "no respondió al saludo initialize de MCP" in verdict["presentacion"]["detalle"]


def test_red_no_consultada_no_puede_ser_red_ni_proveedor():
    for legacy in ("sin_red", "proveedor_caido", "error_upstream"):
        out = diag.producir({
            "tipo": "mcp", "ref": "freecad", "estado": "roto", "causa": legacy,
            "evidencia": {
                "detail": "fallo local", "transport": "stdio", "destino": "uvx",
                "red": {"consultada": False},
            },
        })
        assert out["escalon"] not in {"red", "proveedor"}


def test_credencial_faltante_declara_widget_ejecutable():
    out = diag.producir({
        "tipo": "key", "ref": "fred", "estado": "roto", "causa": "falta_key",
        "evidencia": {"connector": "fred", "red": {"consultada": False}},
    })
    assert out["presentacion"]["plantilla"] == "conexion"
    assert out["camino"]["estado"] == "ejecutable"
    assert out["camino"]["widget"] == "conexion_inline"
    assert out["camino"]["connector"] == "fred"


def test_deriva_comando_url_verificada_y_gate_428(tmp_path, monkeypatch):
    monkeypatch.setenv("ALEPH_REMEDIOS_CATALOGO_PATH", str(tmp_path / "remedios.json"))
    remedios.reset_pruebas()
    item = remedios.resolver(
        {"transport": "stdio", "command": "uvx", "args": ["dicom-mcp"]},
        catalog_id="medicina#dicom",
        url_checker=lambda url: {"ok": True, "url": url, "status": 200},
        buscar_ia=False,
    )
    assert item["como"] == "uvx dicom-mcp"
    assert item["url"] == "https://pypi.org/project/dicom-mcp"
    assert item["url_verificada"] is True

    app = FastAPI()
    app.include_router(motor.build_motor_router())
    client = TestClient(app)
    before = client.post("/v1/motor/instalar", json={"remedio_id": item["remedio_id"]})
    assert before.status_code == 428
    assert before.json()["detail"]["error"] == "falta_confirmacion"
    # El comando mostrado vive del lado servidor: no se acepta uno alternativo del body.
    assert remedios.obtener(item["remedio_id"])["como"] == "uvx dicom-mcp"


def test_hueco_con_fuente_abre_guia_oficial(tmp_path, monkeypatch):
    monkeypatch.setenv("ALEPH_REMEDIOS_CATALOGO_PATH", str(tmp_path / "remedios.json"))
    remedios.reset_pruebas()
    out = remedios.resolver(
        {"transport": "stdio", "command": "/repo/.venv/bin/dicom-mcp", "args": []},
        catalog_id="medicina#dicom", fuente="https://github.com/example/dicom-mcp",
        buscar_ia=False,
    )
    assert out["estado"] == "guia"
    assert out["mensaje"] == "Este conector necesita una preparación guiada."
    assert out["url"] == "https://github.com/example/dicom-mcp"
    assert remedios.camino_de(out) == {
        "estado": "ejecutable",
        "accion": "abrir_guia",
        "label": "Abrir guía oficial",
        "url": "https://github.com/example/dicom-mcp",
        "fuente": "https://github.com/example/dicom-mcp",
    }


def test_runtime_publico_se_vuelve_instalacion_sin_curacion_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("ALEPH_REMEDIOS_CATALOGO_PATH", str(tmp_path / "remedios.json"))
    monkeypatch.setenv("ALEPH_CATALOG_RUNTIME_PATH", str(tmp_path / "runtime.json"))
    (tmp_path / "runtime.json").write_text(json.dumps({
        "version": 1,
        "entries": {
            "io.github.acme/nuevo": {
                "version": 1,
                "catalog_id": "io.github.acme/nuevo",
                "source": "https://github.com/acme/nuevo",
                "remotes": [],
                "packages": [{
                    "registry": "npm", "identifier": "@acme/nuevo",
                    "transport": "stdio", "args": [], "environment": [],
                }],
            },
        },
    }), encoding="utf-8")
    remedios.reset_pruebas()
    out = remedios.resolver(
        {}, catalog_id="io.github.acme/nuevo", buscar_ia=False,
        url_checker=lambda url: {"ok": True, "url": url, "status": 200},
    )
    assert out["como"] == "npx -y @acme/nuevo"
    assert out["url"] == "https://www.npmjs.com/package/@acme/nuevo"
    assert remedios.camino_de(out)["label"] == "Instalarlo"


def test_writeback_ia_evitar_segunda_busqueda(tmp_path, monkeypatch):
    monkeypatch.setenv("ALEPH_REMEDIOS_CATALOGO_PATH", str(tmp_path / "remedios.json"))
    remedios.reset_pruebas()
    monkeypatch.setattr(remedios, "_BUSCADOR_IA", lambda spec, fuente: {
        "como": "uvx repo-mcp",
        "url": "https://github.com/example/repo-mcp",
        "fuente": "https://github.com/example/repo-mcp",
    })
    spec = {"transport": "stdio", "command": "/repo/.venv/bin/server", "args": []}
    first = remedios.resolver(
        spec, catalog_id="custom#repo", fuente="https://github.com/example/repo-mcp",
    )
    assert first["origen"] == "busqueda_ia"
    assert remedios._BUSQUEDAS_IA == 1
    remedios.confirmar(first["remedio_id"])
    second = remedios.resolver(
        spec, catalog_id="custom#repo", fuente="https://github.com/example/repo-mcp",
    )
    assert second["origen"] == "catalogo"
    assert second["como"] == first["como"]
    assert remedios._BUSQUEDAS_IA == 1


def test_calibraciones_rojas_cortan_su_knob(tmp_path, monkeypatch):
    raw = (
        'Traceback (most recent call last):\n  File "server.py", line 1\n'
        "ModuleNotFoundError: sdk_roto"
    )
    base = {
        "tipo": "mcp", "ref": "plantado", "estado": "roto", "causa": "error_upstream",
        "evidencia": {
            "stderr": raw, "exit_code": 1, "transport": "stdio", "destino": "uvx",
            "red": {"consultada": False},
        },
    }
    _afirmar_server_roto(diag.producir(base))
    drift = {
        "tipo": "mcp", "ref": "protocol-knob", "estado": "roto",
        "evidencia": {
            "transport": "stdio", "red": {"consultada": False},
            "protocolo": {
                "cliente": "2024-11-05", "servidor": "2026-07-28",
                "incompatible": True,
            },
        },
    }
    assert diag.producir(drift)["patron"]["codigo"] == "deriva_protocolo"
    monkeypatch.setenv("ALEPH_DIAGNOSTICO_NEUTRALIZAR", "1")
    with pytest.raises(AssertionError):
        _afirmar_server_roto(diag.producir(base))
    assert diag.producir(drift)["patron"]["codigo"] == "desconocido"
    monkeypatch.delenv("ALEPH_DIAGNOSTICO_NEUTRALIZAR")

    monkeypatch.setenv("ALEPH_REMEDIOS_CATALOGO_PATH", str(tmp_path / "url.json"))
    good = remedios.resolver(
        {"transport": "stdio", "command": "uvx", "args": ["url-knob-mcp"]},
        catalog_id="knob#url-ok", buscar_ia=False,
        url_checker=lambda url: {"ok": True, "url": url, "status": 200},
    )
    assert good["url_verificada"] is True
    broken = remedios.resolver(
        {"transport": "stdio", "command": "uvx", "args": ["url-knob-broken"]},
        catalog_id="knob#url-broken", buscar_ia=False,
        url_checker=lambda url: {"ok": False, "url": url, "status": None},
    )
    with pytest.raises(AssertionError):
        assert broken["url_verificada"] is True

    bad = _script(tmp_path, "raise ImportError('captura-knob')\n")
    out = motor.prueba_mcp(spec={
        "transport": "stdio", "command": sys.executable, "args": [str(bad)],
    })
    _afirmar_server_roto(out["veredicto"])
    sin_captura = {
        **out["veredicto"],
        "evidencia": {**out["veredicto"]["evidencia"], "stderr": ""},
    }
    with pytest.raises(AssertionError):
        _afirmar_server_roto(sin_captura)
