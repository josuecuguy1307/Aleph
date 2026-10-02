"""Contrato y calibraciones rojas de Catálogos Dos."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[4]
for _path in (_REPO / "platform", _REPO / "product" / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.phase1 import catalog_ingest_router as CIR  # noqa: E402
from app.phase1 import catalog_equip_router as CER  # noqa: E402
from app.phase1 import authz  # noqa: E402
from inspection import mcp_matcher, mcp_registry  # noqa: E402


def _candidate(*, owner: str = "stripe", vendor_kind: str = "dns",
               service: str = "stripe", title: str = "Stripe",
               description: str = "Payment tools", both: bool = False,
               status: str = "active", is_latest: bool = True) -> dict:
    candidate = {
        "name": f"com.{owner}/{service}-mcp",
        "namespace": f"com.{owner}",
        "leaf": f"{service}-mcp",
        "vendor": owner,
        "vendor_kind": vendor_kind,
        "title": title,
        "description": description,
        "status": status,
        "is_latest": is_latest,
        "repository": {"url": f"https://example.test/{owner}/stripe"},
        "remotes": [{"type": "streamable-http", "url": "https://example.test/use"}],
        "packages": ([{"registryType": "npm", "identifier": "@example/stripe"}]
                     if both else []),
        "source": "registry",
    }
    candidate["_manifest_raw"] = {"server": {
        "name": candidate["name"], "title": title, "description": description,
        "repository": candidate["repository"], "remotes": candidate["remotes"],
        "packages": candidate["packages"],
    }, "_meta": {"io.modelcontextprotocol.registry/official": {
        "status": status, "isLatest": is_latest,
    }}}
    return candidate


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_coreano_se_normaliza_y_schema_es_exacto():
    cand = _candidate(
        service="결제", title="결제 서버", description="결제를 처리하는 원시 매니페스트"
    )
    ranked = mcp_matcher.rank("stripe", [cand])
    entries, rejected = CIR.clean_ranked("stripe", ranked)
    assert rejected == []
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) == CIR.ENTRY_KEYS
    assert CIR.valid_entry(entry)
    assert entry["nombre"] == "stripe"
    visible = json.dumps({
        "nombre": entry["nombre"],
        "descripcion": entry["descripcion_1linea"],
        "checklist": entry["checklist"],
    }, ensure_ascii=False)
    assert not re.search(r"[\uac00-\ud7af]", visible)
    assert entry["descripcion_1linea"]["es"].startswith("Usá ")
    assert entry["checklist"]["es"][0].startswith("Revisá ")


def test_cero_jerga_cruda_en_la_voz_limpia():
    cand = _candidate(
        title="Stripe MCP Server",
        description="Raw JSON-RPC manifest over streamable-http / stdio via npx.",
        both=True,
    )
    entry = CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [cand]))[0][0]
    visible = json.dumps({
        "nombre": entry["nombre"],
        "descripcion": entry["descripcion_1linea"],
        "checklist": entry["checklist"],
    }, ensure_ascii=False)
    assert not CIR._RAW_JARGON.search(visible)


def test_candidato_visible_nunca_dice_que_no_hubo_candidatos():
    bad = _candidate(owner="intruso", vendor_kind="github_org", title="Stripe")
    decision = mcp_matcher.best_match("stripe", [bad])
    assert decision["ranked"], "el candidato se conserva para explicar el rechazo"
    assert "no devolvió candidatos" not in decision["reason"]


def test_ingesta_muestra_las_cuatro_etapas_y_persiste(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEPH_LOCAL_CATALOG_PATH", str(tmp_path / "local.json"))
    monkeypatch.setenv("ALEPH_CATALOG_RUNTIME_PATH", str(tmp_path / "runtime.json"))
    cand = _candidate(title="결제 서버", description="MCP server manifest stdio")
    monkeypatch.setattr(mcp_registry, "search", lambda *a, **k: [cand])
    app = FastAPI()
    app.include_router(CIR.build_catalog_ingest_router())
    response = TestClient(app).post("/v1/catalog/ingest", json={"query": "stripe"})
    assert response.status_code == 200
    events = _events(response)
    assert [event["etapa"] for event in events] == [
        "leyendo", "limpiando", "clasificando", "veredicto",
    ]
    final = events[-1]
    assert final["ok"] is True and len(final["entradas"]) == 1
    assert CIR.valid_entry(final["entradas"][0])
    saved = json.loads((tmp_path / "local.json").read_text(encoding="utf-8"))
    assert saved == final["entradas"]
    runtime = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    spec = runtime["entries"][cand["name"]]
    assert spec["remotes"][0]["url"] == "https://example.test/use"
    assert spec["source"] == "https://example.test/stripe/stripe"


def test_runtime_conserva_paquete_y_datos_requeridos_sin_contaminar_ficha():
    cand = _candidate(both=True)
    cand["packages"][0]["transport"] = {"type": "stdio"}
    cand["packages"][0]["environmentVariables"] = [{
        "name": "STRIPE_KEY", "isSecret": True, "isRequired": True,
    }]
    spec = CIR._runtime_spec(cand)
    assert spec["packages"] == [{
        "registry": "npm",
        "identifier": "@example/stripe",
        "transport": "stdio",
        "args": [],
        "environment": [{"name": "STRIPE_KEY", "required": True, "secret": True}],
    }]
    entry = CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [cand]))[0][0]
    assert set(entry) == CIR.ENTRY_KEYS


def test_ingesta_es_publica_sin_abrir_otras_mutaciones():
    assert authz.is_public_v1("/v1/catalog/ingest", "POST")
    assert not authz.is_public_v1("/v1/catalog/otra-mutacion", "POST")


def test_ingesta_publica_sigue_cerrada_en_control(monkeypatch):
    monkeypatch.setenv("ALEPH_ROLE", "control")
    app = FastAPI()
    app.include_router(CIR.build_catalog_ingest_router())
    response = TestClient(app).post(
        "/v1/catalog/ingest", json={"query": "stripe"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "catalogo_local_solo_cliente"


def test_official_sale_del_pin_y_no_del_namespace():
    cand = _candidate(
        owner="billing", vendor_kind="github_org", service="billing",
        title="Billing", description="Billing and invoice tools",
    )
    scored = mcp_matcher.rank("billing", [cand])
    assert scored[0]["verified_vendor"] is True
    entries, rejected = CIR.clean_ranked("billing", scored)
    assert rejected == []
    assert len(entries) == 1
    assert entries[0]["official"] is False
    assert entries[0]["confianza"] == scored[0]["score"]


def test_ingesta_stripe_pierde_official_al_quitar_pin(monkeypatch):
    cand = _candidate()
    cand.update({"name": "com.stripe/mcp", "leaf": "mcp"})
    cand["_manifest_raw"]["server"]["name"] = cand["name"]
    assert CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [cand]))[0][0]["official"] is True
    curated = mcp_registry.load_curated()
    curated["services"].pop("stripe")
    monkeypatch.setattr(mcp_registry, "load_curated", lambda: curated)
    assert CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [cand]))[0][0]["official"] is False


def test_ingesta_conserva_crudo_fecha_requisitos_senales_y_consecuencias():
    cand = _candidate(both=True)
    cand["remotes"][0]["headers"] = [{
        "name": "Authorization", "value": "Bearer {key}",
        "isSecret": True, "isRequired": True,
    }]
    cand["_manifest_raw"]["server"]["remotes"] = cand["remotes"]
    scored = mcp_matcher.rank("stripe", [cand])
    entry = CIR.clean_ranked("stripe", scored)[0][0]
    assert entry["manifest_crudo"] == cand["_manifest_raw"]
    assert entry["fecha_ingesta"].endswith("+00:00")
    assert entry["requisitos"]["requisito"] == "llave"
    assert entry["requisitos"]["headers"] == [{
        "name": "Authorization", "required": True, "secret": True,
    }]
    assert entry["senales_matcher"]["signals"] == scored[0]["signals"]
    assert entry["consecuencias"] == "se_sabra_al_conectar"

    cand["_manifest_raw"]["server"]["tools"] = [
        {"name": "send_invoice"}, {"name": "delete_invoice"},
    ]
    consequences = CIR.scrutiny_consequences(cand)
    assert consequences["send"] is True and consequences["delete"] is True
    assert consequences["write"] is False


def test_reingesta_actualiza_escrutinio_aunque_baje_confianza(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEPH_LOCAL_CATALOG_PATH", str(tmp_path / "local.json"))
    first = CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [_candidate()]))[0][0]
    first["confianza"] = 0.9
    first["fecha_ingesta"] = "2026-01-01T00:00:00+00:00"
    assert CIR._persist([first]) == 1
    later = {**first, "confianza": 0.5, "fecha_ingesta": "2026-08-04T00:00:00+00:00",
             "senales_matcher": {"score": 0.5, "signals": {}}}
    assert CIR._persist([later]) == 0
    saved = json.loads((tmp_path / "local.json").read_text(encoding="utf-8"))[0]
    assert saved["confianza"] == 0.9
    assert saved["fecha_ingesta"] == later["fecha_ingesta"]
    assert saved["senales_matcher"] == later["senales_matcher"]


def test_store_viejo_se_migra_en_lectura(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEPH_LOCAL_CATALOG_PATH", str(tmp_path / "local.json"))
    current = CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [_candidate()]))[0][0]
    legacy = {key: current[key] for key in CIR.LEGACY_ENTRY_KEYS}
    (tmp_path / "local.json").write_text(json.dumps([legacy]), encoding="utf-8")
    loaded = next(entry for entry in CIR.list_local() if entry["id"] == legacy["id"])
    assert set(loaded) == CIR.ENTRY_KEYS
    assert loaded["fecha_ingesta"] is None
    assert loaded["requisitos"]["medido"] is False
    assert loaded["consecuencias"] == "se_sabra_al_conectar"


def test_version_no_vigente_y_sin_forma_no_fingen_falta_de_origen():
    stale = _candidate(status="deprecated", is_latest=False)
    accepted, rejected = CIR.clean_ranked("stripe", mcp_matcher.rank("stripe", [stale]))
    assert accepted == []
    assert rejected[0] == {
        "id": stale["name"], "veredicto": "descartado",
        "causa": CIR.CAUSE_STALE,
    }

    no_runner = _candidate()
    no_runner["remotes"] = []
    accepted, rejected = CIR.clean_ranked(
        "stripe", mcp_matcher.rank("stripe", [no_runner])
    )
    assert accepted == []
    assert rejected[0]["veredicto"] == "descartado"
    assert rejected[0]["causa"] == CIR.CAUSE_NO_RUNNER


def test_caida_igual_muestra_las_cuatro_etapas(monkeypatch):
    def down(*_args, **_kwargs):
        raise mcp_registry.RegistryError("detalle crudo")

    monkeypatch.setattr(mcp_registry, "search", down)
    app = FastAPI()
    app.include_router(CIR.build_catalog_ingest_router())
    events = _events(TestClient(app).post(
        "/v1/catalog/ingest", json={"query": "stripe"}
    ))
    assert [event["etapa"] for event in events] == [
        "leyendo", "limpiando", "clasificando", "veredicto",
    ]
    assert events[-1]["causa"] == "registro_no_disponible"
    assert "detalle crudo" not in json.dumps(events, ensure_ascii=False)


def test_validator_exige_nfkc_url_pasos_unicos_y_de_una_linea():
    entry = CIR.clean_ranked(
        "stripe", mcp_matcher.rank("stripe", [_candidate()])
    )[0][0]
    assert CIR.valid_entry(entry)
    assert not CIR.valid_entry({**entry, "nombre": "Cafe\u0301"})
    assert not CIR.valid_entry({**entry, "fuente": "no-es-una-url"})
    assert not CIR.valid_entry({
        **entry,
        "checklist": {
            **entry["checklist"],
            "es": ["Pégala aquí.", "Pegá tu llave acá."],
        },
    })
    assert not CIR.valid_entry({
        **entry,
        "checklist": {**entry["checklist"], "en": ["First line\nsecond line"]},
    })


def test_no_confiable_separa_las_dos_causas(monkeypatch, tmp_path):
    monkeypatch.setenv("PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES", "1")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(CER.build_catalog_equip_router())
    client = TestClient(app)

    garbage = _candidate(owner="intruso", vendor_kind="github_org", title="Stripe")
    first = _events(client.post("/v1/catalog/equip", json={
        "service": "stripe", "server_name": garbage["name"],
        "seed_candidates": [garbage],
    }))
    first_closed = next(event for event in first if event["type"] == "cerrado")
    assert first_closed["cause"] == "no_confiable"
    assert first_closed["cause_literal"] == "sin_prueba_de_origen"
    first_miss = next(event for event in first if event["type"] == "resolver.miss")
    assert "ranked" not in first_miss
    assert not CER._RAW_RED_JARGON.search(first_miss["reason"])

    official = _candidate()
    second = _events(client.post("/v1/catalog/equip", json={
        "service": "stripe", "server_name": "com.intruso/stripe",
        "seed_candidates": [official],
        "seed_spec": {"transport": "http", "url": "https://unused.invalid"},
    }))
    second_closed = next(event for event in second if event["type"] == "cerrado")
    assert second_closed["cause"] == "no_confiable"
    assert second_closed["cause_literal"] == "candidato_distinto_del_oficial"
    second_miss = next(event for event in second if event["type"] == "resolver.miss")
    assert "ranked" not in second_miss
    assert not CER._RAW_RED_JARGON.search(second_miss["reason"])
