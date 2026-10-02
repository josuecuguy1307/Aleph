#!/usr/bin/env python3
"""Vara única de Gate 2.5 · Obra 1 (fixtures deterministas + revalidación viva de pins)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT / "platform", ROOT / "product" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.phase1 import catalog_ingest_router as CIR  # noqa: E402
from app.phase1 import catalog_search_router as CSR  # noqa: E402
from inspection import mcp_matcher, mcp_registry  # noqa: E402

FIXTURE = Path(__file__).with_name("fixtures") / "escrutinio_candidates.json"
REPORT = ROOT.parent / "REPORTE-OBRA1-ESCRUTINIO.md"
PINS = {
    "exa": ("ai.exa/exa", "exa search"),
    "alphavantage": ("io.github.alphavantage/alpha_vantage_mcp", "alpha vantage"),
    "context7": ("io.github.upstash/context7", "context 7"),
}


def check(number: int, label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{number} · {label}: {detail or 'falló'}")
    print(f"PASS {number} · {label}" + (f" — {detail}" if detail else ""))


def events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def digest(*paths: Path) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes() if path.exists() else b"<ausente>")
    return h.hexdigest()


def main() -> int:
    raw_entries = json.loads(FIXTURE.read_text(encoding="utf-8"))["servers"]
    candidates = [mcp_registry._candidate(raw) for raw in raw_entries]  # type: ignore[attr-defined]
    candidates = [candidate for candidate in candidates if candidate]
    original_search = mcp_registry.search
    original_get = mcp_registry.get_by_name
    original_load = mcp_registry.load_curated

    with tempfile.TemporaryDirectory(prefix="aleph-escrutinio-") as tmp:
        tmp_path = Path(tmp)
        local_path = tmp_path / "local.json"
        runtime_path = tmp_path / "local.runtime.json"
        os.environ["ALEPH_LOCAL_CATALOG_PATH"] = str(local_path)
        os.environ["ALEPH_CATALOG_RUNTIME_PATH"] = str(runtime_path)
        mcp_registry.search = lambda *_args, **_kwargs: candidates  # type: ignore[assignment]
        mcp_registry.get_by_name = lambda name, **_kwargs: next(  # type: ignore[assignment]
            (candidate for candidate in candidates if candidate["name"] == name), None
        )

        ingest_app = FastAPI()
        ingest_app.include_router(CIR.build_catalog_ingest_router())
        ingest_response = TestClient(ingest_app).post(
            "/v1/catalog/ingest", json={"query": "stripe"}
        )
        final = events(ingest_response)[-1]
        stripe_entry = next(entry for entry in final["entradas"] if entry["id"] == "com.stripe/mcp")
        check(1, "ingesta conserva material", all((
            stripe_entry["manifest_crudo"] == raw_entries[0],
            bool(stripe_entry["fecha_ingesta"]),
            stripe_entry["requisitos"]["requisito"] == "llave",
            bool(stripe_entry["senales_matcher"]["signals"]),
            stripe_entry["consecuencias"] == "se_sabra_al_conectar",
        )))

        search_app = FastAPI()
        search_app.include_router(CSR.build_catalog_search_router(get_conn=None))
        search_client = TestClient(search_app)
        search_body = search_client.get(
            "/v1/catalog/search", params={"q": "stripe", "source": "registry"}
        ).json()
        stripe_item = next(item for item in search_body["items"] if item["id"] == "com.stripe/mcp")
        raw_response = search_client.get(
            "/v1/catalog/raw", params={"catalog_id": "com.stripe/mcp"}
        ).json()
        check(2, "search entrega escrutinio y raw unitario", all((
            stripe_item["requisito"] == "llave",
            stripe_item["fecha_ingesta"] == stripe_entry["fecha_ingesta"],
            isinstance(stripe_item["confianza"], float),
            stripe_item["consecuencias"] == "se_sabra_al_conectar",
            "manifest" not in stripe_item and "manifest_crudo" not in stripe_item,
            raw_response["manifest"] == raw_entries[0],
        )))

        evil = next(item for item in search_body["items"] if item["id"] == "io.github.evil/stripe-mcp")
        check(3, "namespace sin pin no sella", evil["badge"]["verified"] is False
              and evil["badge"]["label"] == "publicado por github: evil")

        curated_without_stripe = json.loads(json.dumps(original_load()))
        curated_without_stripe["services"].pop("stripe")
        mcp_registry.load_curated = lambda: curated_without_stripe  # type: ignore[assignment]
        unpinned_badge = CSR._registry_badge(candidates[0])
        unpinned_entry = CIR.clean_ranked(
            "stripe", mcp_matcher.rank("stripe", [candidates[0]])
        )[0][0]
        mcp_registry.load_curated = original_load  # type: ignore[assignment]
        check(4, "pin pone y quita el sello, incluido Stripe", all((
            stripe_item["badge"]["verified"] is True,
            unpinned_badge["verified"] is False,
            unpinned_entry["official"] is False,
        )))

        # Única sección de red permitida: revalida los tres nombres exactos del pin.
        mcp_registry.search = original_search  # type: ignore[assignment]
        mcp_registry.get_by_name = original_get  # type: ignore[assignment]
        live = {}
        for service, (pin, alias) in PINS.items():
            candidate = mcp_registry.get_by_name(pin, timeout=20.0)
            live[service] = {
                "expected": pin,
                "found": candidate.get("name") if candidate else None,
                "status": candidate.get("status") if candidate else None,
                "is_latest": candidate.get("is_latest") if candidate else None,
                "alias_resolves": (mcp_registry.curated_entry(alias) or {}).get("service"),
            }
        print("PIN_REVALIDATION=" + json.dumps(live, ensure_ascii=False, sort_keys=True))
        check(5, "tests corregidos y tres pins vivos", all(
            value["found"] == value["expected"]
            and value["status"] == "active"
            and value["is_latest"] is True
            and value["alias_resolves"] == service
            for service, value in live.items()
        ))

        mcp_registry.search = lambda *_args, **_kwargs: candidates  # type: ignore[assignment]
        before = digest(local_path, runtime_path)
        for _ in range(4):
            search_client.get("/v1/catalog/search", params={"q": "stripe", "source": "registry"})
        node = subprocess.run([
            "node", "--input-type=module", "-e",
            """import('./product/app/design/cuarto/cuarto.catalog.tools.js').then(async m=>{
              let calls=[]; const f=async(u,o)=>{calls.push([u,o.method]);return {ok:true,json:async()=>({items:[],registry_status:'ok'})}};
              for(let i=0;i<4;i++) await m.buscarRegistro('stripe',{fetchImpl:f});
              if(calls.some(x=>x[1]!=='GET'||!x[0].startsWith('/v1/catalog/search?'))) process.exit(2);
            })""",
        ], cwd=ROOT, capture_output=True, text=True)
        after = digest(local_path, runtime_path)
        check(6, "buscar N veces no persiste", before == after and node.returncode == 0,
              f"sha256={after}")

        legacy_path = tmp_path / "legacy.json"
        legacy = {key: stripe_entry[key] for key in CIR.LEGACY_ENTRY_KEYS}
        legacy_path.write_text(json.dumps([legacy]), encoding="utf-8")
        os.environ["ALEPH_LOCAL_CATALOG_PATH"] = str(legacy_path)
        loaded = next(entry for entry in CIR.list_local() if entry["id"] == legacy["id"])
        check(7, "store viejo migra en lectura", set(loaded) == CIR.ENTRY_KEYS
              and loaded["fecha_ingesta"] is None)

        prediction = REPORT.read_text(encoding="utf-8")
        check(8, "predicción existía antes de correr", "pasará **9 de 9 controles**" in prediction)

        suite = subprocess.run([
            sys.executable, "-m", "pytest", "-q",
            "product/backend/tests/phase1/test_catalog_ingest.py",
            "product/backend/tests/phase1/test_catalog_search.py",
            "product/backend/tests/phase1/test_catalog_validate.py",
        ], cwd=ROOT, capture_output=True, text=True)
        print("GATE1_CATALOG_SUITE=" + (suite.stdout + suite.stderr).strip().replace("\n", " | "))
        check(9, "suite Gate 1 de catálogo verde", suite.returncode == 0)

    mcp_registry.search = original_search  # type: ignore[assignment]
    mcp_registry.get_by_name = original_get  # type: ignore[assignment]
    mcp_registry.load_curated = original_load  # type: ignore[assignment]
    print("VERDE · 9/9 · verify_escrutinio.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
