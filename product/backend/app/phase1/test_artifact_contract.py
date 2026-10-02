"""
test_artifact_contract.py — vara POR ARCHIVO del contrato de artefactos.
[Gate 4 · Fase 2 · §5/§9 del contrato — ~/Desktop/FASE2-CONTRATO-ARTEFACTOS.md]

Qué mide (hermético: ALEPH_DATA_DIR a un tmp, jamás los datos reales):
  1. borde de escritura: provenance estructural (dd-agents) + unión cerrada de tipos
  2. alias → canónico al escribir; desconocido → rechazo tipado, jamás coerción muda
  3. cada versión viaja con SU identidad; revert restaura contenido+procedencia juntos
  4. schema v2 LEÍDA: v1 se repara en memoria sin reescribir el disco; futura rechaza
     escritura visible; corrupto se renombra (.corrupt-*), jamás se descarta
  5. migración del árbol viejo: copia idempotente, jamás pisa, jamás pierde
  6. provenance resuelta de events.jsonl (formato plano de session.py Y anidado en
     payload), con capture_quality honesto y null ≠ 0
  7. export: formatos desde EL vocabulario; cache bajo aleph_paths
  8. anti-drift: el espejo ADVISORY producible_by_llm == stream_chat._ARTIFACT_TYPES

Correr: cd product/backend && .venv/bin/python -m pytest app/phase1/test_artifact_contract.py -q
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]          # product/backend
_REPO = _HERE.parents[4]
for p in (str(_BACKEND), str(_REPO / "platform")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import artifact_store  # noqa: E402
from app.phase1 import artifact_export  # noqa: E402
from artifacts import provenance as prov  # noqa: E402
from artifacts import vocabulary as vocab  # noqa: E402


PROV_OK = {"schema": 1, "captured_at": "2026-08-08T00:00:00+00:00",
           "produced_by": "manual", "capture_quality": "declared"}


@pytest.fixture()
def store_env(tmp_path, monkeypatch):
    """Almacén aislado: datadir tmp + migración reseteada + legacy root tmp."""
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ALEPH_ROLE", raising=False)   # default client (fail-closed)
    legacy = tmp_path / "legacy-tree"
    monkeypatch.setattr(artifact_store, "_LEGACY_ART_ROOT", legacy)
    monkeypatch.setattr(artifact_store, "_migration_done", False)
    return {"tmp": tmp_path, "legacy": legacy}


# ── 1 · borde de escritura ────────────────────────────────────────────────────

def test_create_requires_provenance_and_stamps_identity(store_env):
    with pytest.raises(artifact_store.StoreError) as exc:
        artifact_store.create_artifact("s1", "Obra", "informe", "hola", None)
    assert exc.value.code == "artifact_provenance_missing"

    art = artifact_store.create_artifact("s1", "Obra", "informe", "hola", dict(PROV_OK))
    assert art["provenance"]["produced_by"] == "manual"
    assert art["content_sha256"] == artifact_store._sha256("hola")
    on_disk = json.loads((artifact_store.art_root() / "s1.json").read_text())
    assert on_disk["schema_version"] == artifact_store.SCHEMA_VERSION
    assert on_disk["artifacts"][0]["provenance"]["capture_quality"] == "declared"


def test_type_union_aliases_and_typed_rejection(store_env):
    a = artifact_store.create_artifact("s2", "D", "diagrama", "x", dict(PROV_OK))
    assert a["type"] == "schematic"                      # alias → canónico al escribir
    b = artifact_store.create_artifact("s2", "V", "", "x", dict(PROV_OK))
    assert b["type"] == "informe"                        # ausente → default documentado
    with pytest.raises(artifact_store.StoreError) as exc:
        artifact_store.create_artifact("s2", "B", "banana", "x", dict(PROV_OK))
    assert exc.value.code == "artifact_type_invalid"
    assert "banana" == exc.value.detail["type"]
    assert set(exc.value.detail["allowed"]) == set(vocab.CANONICAL)


# ── 3 · versiones con identidad ───────────────────────────────────────────────

def test_versions_carry_their_own_provenance_and_revert_restores_both(store_env):
    pa = dict(PROV_OK, run_id="run-a")
    pb = dict(PROV_OK, run_id="run-b")
    art = artifact_store.create_artifact("s3", "Obra", "informe", "v1", pa)
    aid = art["id"]
    edited = artifact_store.edit_artifact("s3", aid, "v2", provenance=pb)
    assert edited["provenance"]["run_id"] == "run-b"
    assert edited["versions"][0]["provenance"]["run_id"] == "run-a"
    assert edited["versions"][0]["content_sha256"] == artifact_store._sha256("v1")
    # edit SIN provenance (sync mecánico): snapshotea versión pero CONSERVA identidad
    kept = artifact_store.edit_artifact("s3", aid, "v3")
    assert kept["provenance"]["run_id"] == "run-b"
    # revert: contenido Y procedencia juntos
    rev = artifact_store.revert_artifact("s3", aid)
    assert rev["content"] == "v2" and rev["provenance"]["run_id"] == "run-b"
    rev2 = artifact_store.revert_artifact("s3", aid)
    assert rev2["content"] == "v1" and rev2["provenance"]["run_id"] == "run-a"
    assert rev2["content_sha256"] == artifact_store._sha256("v1")


# ── 4 · schema leída: repara v1, rechaza futura, cuarentena el corrupto ───────

def test_legacy_v1_repairs_in_memory_without_rewriting_disk(store_env):
    root = artifact_store.art_root()
    root.mkdir(parents=True, exist_ok=True)
    legacy_doc = {"session_id": "s4", "owner": "u9", "artifacts": [
        {"id": "aaa111222333", "session_id": "s4", "title": "Vieja", "type": "diagrama",
         "content": "c", "versions": [], "created_at": "x", "updated_at": "x"},
        {"id": "bbb111222333", "session_id": "s4", "title": "Rara", "type": "grafico",
         "content": "c", "versions": [], "created_at": "x", "updated_at": "x"},
    ]}
    p = root / "s4.json"
    p.write_text(json.dumps(legacy_doc), encoding="utf-8")
    before = p.read_bytes()

    a = artifact_store.get_artifact("s4", "aaa111222333")
    assert a["type"] == "schematic" and a["provenance"] is None    # alias reparado, origen confesado
    b = artifact_store.get_artifact("s4", "bbb111222333")
    assert b["type"] == "grafico"                                   # desconocido: se conserva tal cual
    assert artifact_store.get_owner("s4") == "u9"
    assert p.read_bytes() == before                                 # leer NO reescribe el disco
    # una escritura real sube el archivo a v2
    artifact_store.edit_artifact("s4", "aaa111222333", "c2", provenance=dict(PROV_OK))
    assert json.loads(p.read_text())["schema_version"] == artifact_store.SCHEMA_VERSION


def test_newer_schema_refuses_writes_visibly_but_reads_pass(store_env):
    root = artifact_store.art_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "s5.json").write_text(json.dumps(
        {"schema_version": 3, "session_id": "s5",
         "artifacts": [{"id": "ccc111222333", "title": "Futura", "type": "informe",
                        "content": "c", "versions": []}]}), encoding="utf-8")
    assert artifact_store.get_artifact("s5", "ccc111222333")["title"] == "Futura"
    assert artifact_store.get_owner("s5") is None      # lectura passthrough, sin drama
    # (claim sobre sesión SIN dueño = intento de escritura real → debe rechazarse)
    for call in (
        lambda: artifact_store.create_artifact("s5", "N", "informe", "x", dict(PROV_OK)),
        lambda: artifact_store.edit_artifact("s5", "ccc111222333", "x", provenance=dict(PROV_OK)),
        lambda: artifact_store.claim_owner("s5", "u2"),
    ):
        with pytest.raises(artifact_store.StoreError) as exc:
            call()
        assert exc.value.code == "artifact_session_newer_schema"
        assert exc.value.http_status == 409


def test_corrupt_file_is_quarantined_never_discarded(store_env):
    root = artifact_store.art_root()
    root.mkdir(parents=True, exist_ok=True)
    p = root / "s6.json"
    p.write_text("{esto no es json", encoding="utf-8")
    assert artifact_store.list_artifacts("s6") == []               # arranca limpio…
    quarantined = list(root.glob("s6.json.corrupt-*"))
    assert len(quarantined) == 1                                   # …pero NADA se pierde
    assert quarantined[0].read_text() == "{esto no es json"
    assert not p.exists()


# ── 5 · migración sin pérdida ─────────────────────────────────────────────────

def test_migration_copies_missing_never_overwrites(store_env):
    legacy = store_env["legacy"]
    legacy.mkdir(parents=True)
    (legacy / "a.json").write_text(json.dumps({"session_id": "a", "artifacts": [], "mark": "OLD"}))
    (legacy / "b.json").write_text(json.dumps({"session_id": "b", "artifacts": [], "mark": "OLD"}))
    new_root = artifact_store.art_root()
    new_root.mkdir(parents=True, exist_ok=True)
    (new_root / "a.json").write_text(json.dumps({"session_id": "a", "artifacts": [], "mark": "NEW"}))

    artifact_store._migrate_legacy_once()
    assert json.loads((new_root / "a.json").read_text())["mark"] == "NEW"   # jamás pisa
    assert json.loads((new_root / "b.json").read_text())["mark"] == "OLD"   # copia lo que falta
    assert (legacy / "b.json").exists()                                     # copy, no move
    # idempotente: segunda pasada (proceso nuevo simulado) no cambia nada
    artifact_store._migration_done = False
    mt = (new_root / "b.json").stat().st_mtime_ns
    artifact_store._migrate_legacy_once()
    assert (new_root / "b.json").stat().st_mtime_ns == mt


# ── 6 · provenance desde events.jsonl ────────────────────────────────────────

def _events_file(tmp_path, lines, name="sp_test"):
    d = tmp_path / "espacios" / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "events.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return f


def test_provenance_resolves_flat_session_format(store_env):
    f = _events_file(store_env["tmp"], [
        {"type": "belt_ready", "ts": 1.0, "servers": ["calc"]},
        {"type": "tool_call_started", "ts": 2.0, "call_id": "c1", "tool": "calc"},
        {"type": "tool_call_finished", "ts": 3.0, "call_id": "c1", "tool": "calc",
         "status": "ok", "executed": True},
        {"type": "tool_call_finished", "ts": 3.5, "call_id": "c2", "tool": "calc",
         "status": "ok", "executed": True},
        {"type": "tool_call_finished", "ts": 3.7, "call_id": "c3", "tool": "web",
         "status": "gated", "executed": False},                     # NO cuenta
        {"type": "final", "ts": 4.0, "answer": "…", "model_final": "claude-sonnet-5", "ok": True},
        {"type": "closed", "ts": 5.0, "ok": True, "model_final": "claude-sonnet-5",
         "run_id": "run-77", "degraded": None},
    ])
    block = prov.build({"space_id": "sp_test", "run_id": "run-77", "user_id": "u1",
                        "agent_id": "ag1", "produced_by": "run", "intent": "  sumá 2+3  "},
                       f)
    assert block["capture_quality"] == "exact" and block["resolved_from"] == "events"
    assert block["model_final"] == "claude-sonnet-5" and block["ok"] is True
    assert block["degraded"] is None and block["tool_calls"] == 2
    assert block["tools"] == ["calc"] and block["run_id"] == "run-77"
    assert block["intent"] == "sumá 2+3" and block["produced_by"] == "run"


def test_provenance_payload_nested_and_honesty_ladder(store_env):
    # anidado en payload (events_replay) — misma lectura
    f = _events_file(store_env["tmp"], [
        {"id": 1, "type": "tool_call_finished", "space_id": "sp_n", "ts": 1.0,
         "payload": {"call_id": "c1", "tool": "echo", "status": "ok", "executed": True}},
        {"id": 2, "type": "closed", "space_id": "sp_n", "ts": 2.0,
         "payload": {"ok": True, "model_final": "m1", "run_id": "r1", "degraded": None}},
    ], name="sp_n")
    b = prov.build({"space_id": "sp_n"}, f)
    assert b["tool_calls"] == 1 and b["model_final"] == "m1" and b["capture_quality"] == "exact"

    # sin terminal → partial; null ≠ 0 se respeta en el caso sin espacio
    f2 = _events_file(store_env["tmp"], [
        {"type": "tool_call_started", "ts": 1.0, "call_id": "c1", "tool": "calc"},
    ], name="sp_open")
    b2 = prov.build({"space_id": "sp_open"}, f2)
    assert b2["capture_quality"] == "partial" and b2["tool_calls"] == 0

    b3 = prov.build({"space_id": "sp_gone"}, store_env["tmp"] / "espacios" / "sp_gone" / "events.jsonl")
    assert b3["capture_quality"] == "partial" and b3["tool_calls"] is None   # nada resuelto ≠ cero

    b4 = prov.build({"chat_id": "ch1", "produced_by": "stream"}, None)
    assert b4["capture_quality"] == "declared" and b4["resolved_from"] == "declared"
    assert b4["model_final"] is None and b4["tool_calls"] is None

    # run declarado ≠ run firmado → los hechos firmados mandan, la calidad lo paga
    b5 = prov.build({"space_id": "sp_n", "run_id": "OTRO"}, f)
    assert b5["run_id"] == "r1" and b5["capture_quality"] == "partial"


def test_provenance_refs_are_sanitized_never_path_joined(store_env):
    assert prov.safe_ref("../../etc/passwd") is None
    assert prov.safe_ref("sp_ok-1.2:x") == "sp_ok-1.2:x"
    b = prov.build({"space_id": "../evil"}, None)
    assert b["space_id"] is None and b["capture_quality"] == "declared"


# ── 7 · export sobre aleph_paths + vocabulario ───────────────────────────────

def test_export_formats_from_vocabulary_and_cache_location(store_env):
    assert artifact_export.formats_for("planilla") == ["xlsx", "csv"]
    assert artifact_export.formats_for("dashboard") == ["html", "csv"]
    assert artifact_export.formats_for("tipo-desconocido") == ["md"]
    # EL DEFAULT DE `informe` CAMBIÓ A PROPÓSITO, y esta línea es el registro de por qué.
    # Era `md`, y MEDIDO contra la .app instalada eso significaba que el usuario veía en
    # pantalla un informe con tabla y gráfico, apretaba Download y bajaba el MARKDOWN
    # FUENTE — con el bloque ```chart como texto plano.
    # Y es `html` y no `pdf` por una razón concreta: html es el ÚNICO de los cuatro que
    # conserva el gráfico DIBUJADO (SVG inline, sin CDN); pdf y docx sólo pueden conservar
    # sus números como tabla. El pdf queda para imprimir y el md como fuente.
    # Si algún día cambia, que sea por una decisión y no por un merge.
    assert artifact_export.default_format("informe") == "html"
    assert "md" in artifact_export.formats_for("informe")     # la fuente NO se pierde
    assert "pdf" in artifact_export.formats_for("informe")    # y el imprimible tampoco
    art = {"id": "abc123", "type": "informe", "title": "Hola", "content": "# Hola\n\ntexto"}
    info = artifact_export.export(art, None, "sX")
    p = Path(info["path"])
    assert p.exists() and p.read_bytes()
    data_root = Path(os.environ["ALEPH_DATA_DIR"]).resolve()
    assert data_root in p.resolve().parents            # cache DENTRO del datadir, no del árbol
    assert artifact_export.dl_root().resolve() in p.resolve().parents


# ── 8 · anti-drift del espejo ADVISORY ───────────────────────────────────────

def test_vocabulary_mirrors_what_circulates_today():
    # El número es un TESTIGO: si cambia, alguien tocó la unión y lo dice acá.
    # 16 → 17 con `presentacion` [Convergencia · superficie 7]. Las DOS aserciones de
    # abajo siguen intactas a propósito, y eso es la prueba de que el tipo entró sin
    # mover nada: no toca `producible_by_llm` (un modelo no tipea un .pptx) ni
    # `rich_capture` (llega por el puente, no del workdir de una corrida).
    assert len(vocab.CANONICAL) == 17
    from app.phase1 import stream_chat
    assert set(vocab.producible_by_llm()) == set(stream_chat._ARTIFACT_TYPES), \
        "el espejo ADVISORY drifteó: 2.4 debe cablear, no divergir"
    # los 10 de captura rica del executor (censo §C.3) — espejo declarado
    assert set(vocab.rich_capture_types()) == {
        "convergence", "fieldplot", "linechart", "planilla", "cad",
        "volume3d", "imagen", "galeria", "dicom", "schematic"}
    # ningún alias tapa un canónico y todos aterrizan adentro (el assert del módulo, vivo)
    assert not (set(vocab.ALIASES) & set(vocab.CANONICAL))
    assert set(vocab.ALIASES.values()) <= set(vocab.CANONICAL)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
