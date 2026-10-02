#!/usr/bin/env python3
"""test_method_export.py — .aleph + export free/premium + import re-inspeccionado (§7).

Cubre: whitelist de export (lo acumulado NO viaja, ni premium) · .aleph autónomo
(agente embebe métodos, keys stripeadas, canvas conservado) · MURO fail-closed
staged (free→402 honesto con env ON; basico pasa; tiers basura niegan) · import
con UUID nuevo, re-mapeo de method_refs, agent_refs dropeados con reporte y
belts re-inspeccionados contra el catálogo local.

Corre:  cd product/backend && PYTHONPATH=. .venv/bin/python app/phase1/test_method_export.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import method_export as mx  # noqa: E402
from app.phase1 import methods_repo as mrp  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


METHOD = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Cierre mensual",
    "requires": ["una hoja de cálculo"],
    "phases": ["Preparar"],
    "steps": [{"id": "s-1", "text": "Conciliar cuentas", "phase": "Preparar",
               "checkpoint": False, "executor": "sheets", "evidence_hint": None,
               "timeout": None, "retries": 3},
              {"id": "s-2", "text": "Aprobar el cierre", "phase": "Cerrar",
               "checkpoint": True, "executor": None, "evidence_hint": None,
               "timeout": None, "retries": 3}],
    "run_count": 7, "last_run_at": "2026-07-01", "adjust_log": [{"adjust": "x"}],
    "source": {"kind": "from_run", "run_id": "r-viejo"},
    "created_at": "2026-06-01", "updated_at": "2026-07-01",
}


def test_unit():
    print("── unit · whitelist + formatos ──")
    c = mx.clean_method(METHOD)
    check("lo acumulado NO viaja (run_count/last_run_at/adjust_log/source/id)",
          all(k not in c for k in ("run_count", "last_run_at", "adjust_log",
                                   "source", "id", "created_at", "updated_at")))
    check("el contenido SÍ viaja (steps/phases/name)",
          c["name"] == "Cierre mensual" and len(c["steps"]) == 2
          and c["phases"] == ["Preparar"])

    a = mx.method_to_aleph(METHOD)
    check(".aleph método: envoltorio {aleph_version, type, method}",
          a["aleph_version"] == 1 and a["type"] == "method"
          and "run_count" not in a["method"])

    puppet = {"name": "Mi contador", "nicho": "finanzas",
              "config": {"schema_version": "v0",
                         "belt": {"belt_refs": ["x"], "method_refs": [METHOD["id"]],
                                  "tool_filters": {"x": ["y"]}},
                         "keys": {"stripe": {"byok_ref": "keys:stripe"}},
                         "canvas": {"layout": [{"id": "t1"}]}}}
    ag = mx.agent_to_aleph(puppet, [METHOD])
    check(".aleph agente: keys STRIPEADAS (byok_refs del dueño no viajan)",
          "keys" not in ag["recipe"])
    check(".aleph agente: canvas CONSERVADO (el usuario espera su Cuarto)",
          ag["recipe"].get("canvas") == {"layout": [{"id": "t1"}]})
    check(".aleph agente: schema v1 forzado", ag["recipe"]["schema_version"] == "v1")
    check(".aleph agente: métodos embebidos con ref de re-mapeo",
          ag["methods"][0]["ref"] == METHOD["id"]
          and "run_count" not in ag["methods"][0]["method"])

    for bad, kind in ((None, "aleph_invalid"), ({}, "aleph_invalid"),
                      ({"aleph_version": 1, "type": "zzz"}, "aleph_invalid"),
                      ({"aleph_version": 99, "type": "method", "method": {}},
                       "aleph_version_unsupported")):
        try:
            mx.parse_aleph(bad)
            check(f"parse rechaza {kind}", False, str(bad)[:60])
        except mx.AlephError as e:
            check(f"parse rechaza {kind}", e.kind == kind)

    pdf = mx.to_pdf(METHOD)
    check("PDF simple: bytes PDF válidos con el contenido",
          pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
          and b"Cierre mensual" in pdf and b"[!]" in pdf)
    md = mx.to_markdown(METHOD)
    check("markdown: fases + checkpoint marcado",
          "## Preparar" in md and "🛑" in md and "herramienta: sheets" in md)
    ck = mx.to_checklist(METHOD)
    check("checklist imprimible: [ ] y [!]", "[ ]" in ck and "[!]" in ck)
    raw = json.loads(mx.to_json_raw(METHOD))
    check("json crudo: sin acumulado", "adjust_log" not in raw and "steps" in raw)
    docx = mx.to_docx(METHOD)
    check("docx: bytes zip de Word", docx[:2] == b"PK")


def test_hardening_unit():
    print("── hardening · deep-strip byok + whitelist + envelope ──")
    # F1 · byok_ref anidado en model.* NO viaja
    puppet = {"name": "A", "nicho": "x", "config": {
        "schema_version": "v1", "meta": {"name": "A"},
        "model": {"primary": "gpt", "byok_ref": "keys:user:abc-uuid/openai"},
        "belt": {"belt_ref": "b", "tool_filters": {"b": ["t"]},
                 "creds": {"api_key": "sk-SECRET"}},
        "keys": {"stripe": {"byok_ref": "keys:stripe"}},
        "framing": {"inline": "x"}}}
    ag = mx.agent_to_aleph(puppet, [])
    blob = json.dumps(ag)
    check("F1 byok_ref anidado (model.byok_ref) stripeado", "byok_ref" not in blob)
    check("F1b api_key anidado stripeado", "sk-SECRET" not in blob and "api_key" not in blob)
    check("F1c keys top-level stripeado", "keys:stripe" not in blob)

    # F2 · clean_method es whitelist: un campo inesperado (keys/token) NO sobrevive
    hostile = {"name": "M", "steps": [{"id": "s", "text": "p", "keys": "sk-x", "evil": 1}],
               "keys": "sk-top", "token": "abc", "run_count": 9}
    c = mx.clean_method(hostile)
    check("F2 clean_method whitelist: keys/token/campos raros fuera",
          "keys" not in json.dumps(c) and "token" not in c and "run_count" not in c
          and c["steps"][0].get("evil") is None and c["steps"][0]["text"] == "p")

    # G6 · aleph_version = Infinity → error tipado, no crash
    try:
        mx.parse_aleph({"aleph_version": float("inf"), "type": "method", "method": {}})
        check("G6 aleph_version Infinity → AlephError (no OverflowError)", False)
    except mx.AlephError as e:
        check("G6 aleph_version Infinity → AlephError (no OverflowError)", e.kind == "aleph_invalid")
    except OverflowError:
        check("G6 aleph_version Infinity → AlephError (no OverflowError)", False, "OverflowError crudo")


def test_muro_unit():
    print("── muro · registro + fail-closed (unit) ──")
    from gates import tier_gate as tg
    check("features registradas", tg.PREMIUM_FEATURES.get("method_export_total") == "basico"
          and tg.PREMIUM_FEATURES.get("method_vault") == "basico")
    rej = tg.require_feature("method_export_total", "free")
    check("free → rechazo honesto con mensaje que explica lo que SÍ tiene",
          rej is not None and rej["tier_gated"] and ".aleph" in rej["error"])
    check("basico/tecnico abren", tg.require_feature("method_export_total", "basico") is None
          and tg.require_feature("method_export_total", "tecnico") is None)
    bogus = ["premium", "PREMIUM", "Premium ", "average", "gold", "-1", "None", "",
             "basicoo", "tecnicoo", "free ", "FREE", "vip", "0", "1", "true", "null",
             "basico'; DROP TABLE", "…", "∞", "admin", "root", "sudo", "paid",
             "pro", "plus", "enterprise", "trial", "test", "dev", "staff"]
    leaks = [t for t in bogus if tg.require_feature("method_export_total", t) is None]
    check(f"FAIL-CLOSED: {len(bogus)} tiers basura NIEGAN todos", leaks == [], str(leaks))


def test_http():
    print("── HTTP · export/import + muro staged ──")
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
    except Exception as e:
        print(f"  [SKIP] DB no disponible ({e})")
        return
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.methods_router import build_methods_router

    app = FastAPI()
    app.include_router(build_methods_router(get_conn=repo.get_conn))
    client = TestClient(app)

    free_u = repo.get_or_create_user(conn, email=f"mx-free-{uuid.uuid4().hex[:8]}@test.local")
    prem_u = repo.get_or_create_user(conn, email=f"mx-prem-{uuid.uuid4().hex[:8]}@test.local",
                                     tier="basico")
    conn.commit()
    if (prem_u.get("tier") or "") != "basico":
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tier='basico' WHERE id=%s", (prem_u["id"],))
        conn.commit()
    auth_free = {"Authorization": "Bearer " + repo.mint_session(free_u["id"])}
    auth_prem = {"Authorization": "Bearer " + repo.mint_session(prem_u["id"])}

    m = client.post("/v1/methods", json={k: v for k, v in METHOD.items() if k != "id"},
                    headers=auth_free).json()
    mid = m["id"]

    r = client.get(f"/v1/methods/{mid}/export?format=aleph", headers=auth_free)
    check("free exporta .aleph SIEMPRE (completo, sin acumulado)",
          r.status_code == 200 and ".aleph" in r.headers.get("content-disposition", "")
          and "adjust_log" not in r.text and "run_count" not in r.text)
    r = client.get(f"/v1/methods/{mid}/export?format=pdf", headers=auth_free)
    check("free exporta PDF simple", r.status_code == 200
          and r.content.startswith(b"%PDF"))
    r = client.get(f"/v1/methods/{mid}/export?format=banana", headers=auth_free)
    check("formato inválido → 422", r.status_code == 422)

    old = os.environ.pop("PUPPET_ENFORCE_METHOD_EXPORT", None)
    try:
        r = client.get(f"/v1/methods/{mid}/export?format=md", headers=auth_free)
        check("env OFF (staged): free exporta md (no-op, base demo sigue)",
              r.status_code == 200)
        os.environ["PUPPET_ENFORCE_METHOD_EXPORT"] = "1"
        r = client.get(f"/v1/methods/{mid}/export?format=md", headers=auth_free)
        check("env ON: free → 402 con rechazo honesto",
              r.status_code == 402 and r.json()["detail"]["feature"] == "method_export_total")
        r = client.get(f"/v1/methods/{mid}/export?format=docx", headers=auth_free)
        check("env ON: docx también detrás del muro", r.status_code == 402)
        r = client.get(f"/v1/methods/{mid}/vault", headers=auth_free)
        check("env ON: bóveda free → 402", r.status_code == 402)

        pm = client.post("/v1/methods", json={"name": "M prem", "steps": [{"text": "p"}],
                                              "requires": []},
                         headers=auth_prem).json()
        r = client.get(f"/v1/methods/{pm['id']}/export?format=md", headers=auth_prem)
        check("env ON: basico exporta md", r.status_code == 200 and "M prem" in r.text)
        r = client.get(f"/v1/methods/{pm['id']}/export?format=docx", headers=auth_prem)
        check("env ON: basico exporta docx", r.status_code == 200
              and r.content[:2] == b"PK")
        r = client.get(f"/v1/methods/{pm['id']}/vault", headers=auth_prem)
        check("bóveda premium → 501 honesto (no construida en v1)",
              r.status_code == 501 and r.json()["detail"]["error"] == "vault_not_built")
    finally:
        if old is None:
            os.environ.pop("PUPPET_ENFORCE_METHOD_EXPORT", None)
        else:
            os.environ["PUPPET_ENFORCE_METHOD_EXPORT"] = old

    # ── import: método suelto ──
    aleph_m = client.get(f"/v1/methods/{mid}/export?format=aleph", headers=auth_free).json()
    r = client.post("/v1/aleph/import", json=aleph_m, headers=auth_prem)
    check("import type=method: entra a la biblioteca del receptor con id NUEVO",
          r.status_code == 201 and r.json()["method"]["id"] != mid, r.text[:200])

    # ── roundtrip agente: export → import por OTRO usuario ──
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "agente-aleph", "nicho": "test"},
        "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0, "max_tokens": 1024, "max_turns": 6},
        "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
                 "tool_filters": {"calc": ["add"]},
                 "agent_refs": ["catalog/agents/agent-de-otra-maquina.config.json"],
                 "method_refs": [mid]},
        "framing": {"inline": "test"}, "rag": {"enabled": False},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
        "canvas": {"layout": [{"id": "t1", "gridX": 2, "gridY": 3}]},
        "keys": {"stripe": {"byok_ref": "keys:stripe"}},
    }
    puppet = repo.create_puppet(conn, owner_id=free_u["id"], name="agente-aleph",
                                nicho="test", config=recipe)
    conn.commit()
    pid = str(puppet["id"])
    r = client.get(f"/v1/puppets/{pid}/export.aleph", headers=auth_free)
    check("export.aleph del agente: 200 + keys FUERA + canvas DENTRO + método embebido",
          r.status_code == 200 and '"keys"' not in r.text
          and '"canvas"' in r.text and "Conciliar cuentas" in r.text, r.text[:200])
    ag = r.json()

    r = client.post("/v1/aleph/import", json=ag, headers=auth_prem)
    check("import type=agent: 201 con puppet nuevo", r.status_code == 201, r.text[:300])
    imp = r.json()
    new_pid = imp["puppet"]["id"]
    check("UUID del receptor ≠ origen (identidad server-minted)", new_pid != pid)
    new_cfg = imp["puppet"]["config"]
    new_refs = (new_cfg.get("belt") or {}).get("method_refs") or []
    check("method_refs RE-MAPEADOS a la biblioteca del receptor",
          len(new_refs) == 1 and new_refs[0] != mid, str(new_refs))
    got = client.get(f"/v1/methods/{new_refs[0]}", headers=auth_prem)
    check("el método re-vinculado existe y es del receptor",
          got.status_code == 200 and got.json()["method"]["name"] == "Cierre mensual")
    check("agent_refs del origen DROPEADOS con reporte (no verbatim mudo)",
          "agent_refs" not in (new_cfg.get("belt") or {})
          and imp["reinspection"]["agent_refs_dropped"])
    check("keys del origen JAMÁS entran", "keys" not in new_cfg)
    check("re-inspección: belt del catálogo local RESUELTO",
          "platform/assembler/fixtures/belt-calc.mcp.json" in
          imp["reinspection"]["belts_resolved"])

    r = client.post("/v1/aleph/import", json={"hola": 1}, headers=auth_prem)
    check("import basura → 422 tipado", r.status_code == 422
          and r.json()["detail"]["error"] == "aleph_invalid")

    # G1 · ATOMICIDAD: un agent con métodos válidos pero receta ROTA (sin meta/model/belt)
    # → 422 y CERO métodos creados (la biblioteca no queda poblada de basura)
    before_n = len(client.get("/v1/methods", headers=auth_prem).json()["methods"])
    hostile_agent = {"aleph_version": 1, "type": "agent", "name": "roto", "nicho": "x",
                     "recipe": {"schema_version": "v1"},  # falta meta/model/belt → inválida
                     "methods": [{"ref": "z", "method": {"name": "colado", "steps": [{"text": "p"}],
                                                          "requires": []}}]}
    r = client.post("/v1/aleph/import", json=hostile_agent, headers=auth_prem)
    after_n = len(client.get("/v1/methods", headers=auth_prem).json()["methods"])
    check("G1 receta inválida → 422 y NINGÚN método colado (import atómico)",
          r.status_code == 422 and after_n == before_n, f"{r.status_code} {before_n}->{after_n}")

    # G2 · tope de métodos embebidos
    huge = {"aleph_version": 1, "type": "agent", "name": "big", "nicho": "x",
            "recipe": recipe, "methods": [{"ref": str(i), "method": {"name": f"m{i}",
                     "steps": [{"text": "p"}], "requires": []}} for i in range(250)]}
    r = client.post("/v1/aleph/import", json=huge, headers=auth_prem)
    check("G2 demasiados métodos embebidos → 422", r.status_code == 422)

    # G3 · traversal '..' en belt_refs rechazado por el validador (no toca disco)
    trav = {"aleph_version": 1, "type": "agent", "name": "trav", "nicho": "x",
            "recipe": {"schema_version": "v1", "meta": {"name": "t", "nicho": "x"},
                       "model": {"primary": "openai/gpt-oss-120b",
                                 "base_url": "https://api.groq.com/openai/v1",
                                 "temperature": 0, "max_tokens": 1024, "max_turns": 6},
                       "belt": {"belt_refs": ["../../../../etc/hosts"],
                                "tool_filters": {"x": ["y"]}},
                       "framing": {"inline": "t"}, "rag": {"enabled": False},
                       "gates": {"money_touch": "needs_ok", "send": "needs_ok"}},
            "methods": []}
    r = client.post("/v1/aleph/import", json=trav, headers=auth_prem)
    check("G3 traversal '..' en belt_refs → 422 (sin oráculo de archivos)",
          r.status_code == 422 and r.json()["detail"]["error"] == "recipe_invalid")

    # G6 vía HTTP: Infinity → 422, no 500
    r = client.post("/v1/aleph/import",
                    data=b'{"aleph_version": Infinity, "type": "method", "method": {}}',
                    headers={**auth_prem, "content-type": "application/json"})
    check("G6 HTTP aleph_version Infinity → 422 (no 500)", r.status_code == 422)

    # H5-bypass · atomicidad REAL: input validator-clean pero storage-hostil (NUL byte)
    # → 0 métodos huérfanos (rollback transaccional), no un método colgado sin puppet
    before_n = len(client.get("/v1/methods", headers=auth_prem).json()["methods"])
    nul_agent = {"aleph_version": 1, "type": "agent", "name": "Agente\x00malo", "nicho": "x",
                 "recipe": {"schema_version": "v1", "meta": {"name": "t", "nicho": "x"},
                            "model": {"primary": "openai/gpt-oss-120b",
                                      "base_url": "https://api.groq.com/openai/v1",
                                      "temperature": 0, "max_tokens": 1024, "max_turns": 6},
                            "belt": {"belt_ref": "slug-portable", "tool_filters": {"x": ["y"]}},
                            "framing": {"inline": "t"}, "rag": {"enabled": False},
                            "gates": {"money_touch": "needs_ok", "send": "needs_ok"}},
                 "methods": [{"ref": "o1", "method": {"name": "Método limpio",
                              "steps": [{"text": "paso"}], "requires": []}}]}
    r = client.post("/v1/aleph/import", json=nul_agent, headers=auth_prem)
    after_n = len(client.get("/v1/methods", headers=auth_prem).json()["methods"])
    # ATÓMICO: éxito (NUL saneado) → +1 método CON su puppet; rechazo → +0. Nunca 500,
    # nunca un método huérfano (método creado pero puppet falló).
    if r.status_code in (200, 201):
        ok = (after_n == before_n + 1 and bool(r.json()["puppet"].get("id"))
              and "\x00" not in r.json()["puppet"]["name"])
        check("H5b NUL saneado → import atómico (+1 método CON puppet, nombre limpio)", ok,
              f"{after_n} vs {before_n}")
    else:
        check("H5b NUL rechazado → CERO métodos huérfanos (rollback transaccional)",
              r.status_code == 422 and after_n == before_n, f"{r.status_code} {before_n}->{after_n}")

    # deep-strip ampliado: access_token/client_secret/password anidados no viajan
    p2 = {"name": "A", "nicho": "x", "config": {"schema_version": "v1", "meta": {"name": "A"},
          "model": {"primary": "g", "creds": {"access_token": "AT", "client_secret": "CS",
                                              "password": "PW", "authorization": "Bearer z"}},
          "belt": {"belt_ref": "b", "tool_filters": {"b": ["t"]}}, "framing": {"inline": "x"}}}
    ag2 = mx.agent_to_aleph(p2, [])
    blob2 = json.dumps(ag2)
    check("F1d deep-strip ampliado: access_token/client_secret/password/authorization fuera",
          all(x not in blob2 for x in ("AT", "CS", "PW", "Bearer z")))

    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id IN (%s,%s)",
                    (free_u["id"], prem_u["id"]))
    conn.commit()
    conn.close()
    for pth in (_REPO / "catalog" / "agents").glob("agent-*.config.json"):
        if pid in pth.name or new_pid in pth.name:
            pth.unlink(missing_ok=True)


def main() -> int:
    test_unit()
    test_hardening_unit()
    test_muro_unit()
    test_http()
    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
