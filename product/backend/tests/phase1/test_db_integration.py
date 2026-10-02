"""
test_db_integration.py — EVIDENCIA REAL contra Postgres puppet_ai (Fase 0).

Inserta y lee de verdad: user → puppet (receta validada) → run → BYOK key (cifrada) →
instrumentation_logs (los 5 campos ligados por run_id). Limpia todo con ROLLBACK al final
(cada test usa una conexión que NUNCA hace commit propio fuera de los helpers de repo;
para no ensuciar la DB usamos un email/datos namespaced y borramos el user al cerrar —
ON DELETE CASCADE limpia puppets/runs/keys/instrumentation).

Se SALTA si la DB no está (conftest: DB_AVAILABLE). No es un mock — o corre contra el
Postgres real o se salta honestamente.
"""

import uuid

import pytest

pytestmark = pytest.mark.db

from app.phase1 import repo
from app.phase1 import instrumentation as instr


@pytest.fixture
def cleanup_user(db_conn):
    """
    Crea un user de test namespaced y limpia TODO lo suyo al final.

    OJO (descubierto con verificación real): en el schema de Fase 0, runs.user_id y
    runs.puppet_id son ON DELETE SET NULL — borrar el user NO borra sus runs (ni la
    instrumentation que cuelga de ellos). Es una decisión del schema (la señal del moat
    sobrevive a la cuenta). Por eso el cleanup borra en ORDEN de dependencia:
    instrumentation_logs → runs → puppets → user. Así los tests no dejan huérfanos en
    el Postgres real.
    """
    email = f"phase1-test-{uuid.uuid4().hex[:8]}@puppet.test"
    user = repo.get_or_create_user(db_conn, email, display_name="Phase1 Test")
    yield user
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM instrumentation_logs WHERE run_id IN "
            "(SELECT id FROM runs WHERE user_id = %s OR puppet_id IN "
            "(SELECT id FROM puppets WHERE owner_id = %s))",
            (user["id"], user["id"]),
        )
        cur.execute(
            "DELETE FROM runs WHERE user_id = %s OR puppet_id IN "
            "(SELECT id FROM puppets WHERE owner_id = %s)",
            (user["id"], user["id"]),
        )
        cur.execute("DELETE FROM users WHERE id = %s", (user["id"],))
    db_conn.commit()


def test_user_roundtrip(db_conn, cleanup_user):
    fetched = repo.get_user(db_conn, cleanup_user["id"])
    assert fetched is not None
    assert fetched["email"] == cleanup_user["email"]
    assert fetched["tier"] == "free"


def test_puppet_create_and_list(db_conn, cleanup_user, valid_recipe):
    p = repo.create_puppet(
        db_conn, owner_id=cleanup_user["id"], name="Agente Finanzas",
        nicho="finanzas", config=valid_recipe,
    )
    assert p["id"]
    assert p["recipe_schema_version"] == "v1"
    assert p["version"] == 1
    assert p["config"]["meta"]["nicho"] == "finanzas"  # JSONB roundtrip
    listed = repo.list_puppets(db_conn, cleanup_user["id"], nicho="finanzas")
    assert any(x["id"] == p["id"] for x in listed)


def test_update_config_bumps_version(db_conn, cleanup_user, valid_recipe):
    p = repo.create_puppet(db_conn, owner_id=cleanup_user["id"], name="X",
                           nicho="finanzas", config=valid_recipe)
    valid_recipe["model"]["temperature"] = 0.5
    p2 = repo.update_config(db_conn, p["id"], valid_recipe)
    assert p2["version"] == 2
    assert p2["config"]["model"]["temperature"] == 0.5


def test_byok_encrypted_at_rest_never_plaintext(db_conn, cleanup_user):
    secret = "sk-test-1234567890ABCD"
    meta = repo.upsert_key(db_conn, user_id=cleanup_user["id"], provider="fred", secret=secret)
    # el retorno SOLO trae metadatos, jamás el secreto.
    assert "ciphertext" not in meta and "secret" not in meta
    assert meta["last4"] == "ABCD"
    # el plaintext NO está en la columna ciphertext (verificación directa).
    with db_conn.cursor() as cur:
        cur.execute("SELECT ciphertext FROM keys WHERE user_id=%s AND provider=%s",
                    (cleanup_user["id"], "fred"))
        ct = bytes(cur.fetchone()[0])
    assert secret.encode() not in ct  # el plaintext NUNCA toca Postgres
    # pero el runtime SÍ puede descifrar (uso interno).
    assert repo.get_key(db_conn, cleanup_user["id"], "fred") == secret
    # list_keys solo metadatos.
    keys = repo.list_keys(db_conn, cleanup_user["id"])
    assert keys[0]["provider"] == "fred" and keys[0]["last4"] == "ABCD"


def test_moat_row_links_five_fields_by_run_id(db_conn, cleanup_user, valid_recipe):
    # crea puppet + run, luego escribe LA fila del moat ligada por run_id.
    p = repo.create_puppet(db_conn, owner_id=cleanup_user["id"], name="M",
                           nicho="finanzas", config=valid_recipe)
    run = repo.create_run(db_conn, puppet_id=p["id"], user_id=cleanup_user["id"],
                          space_id="sp_moat", intent="analizá AAPL")
    events = [
        {"id": 1, "type": "turn_started", "payload": {"turn": 1}},
        {"id": 2, "type": "tool_call_finished", "tool": "get_financials",
         "wall_s": 0.34, "gate_decision": "OK", "result": "ok"},
        {"id": 3, "type": "final", "payload": {"answer": "AAPL ..."}},
    ]
    traj = instr.build_trayectoria(events)
    log_id = instr.persist_run(
        db_conn, run_id=run["id"], intent="analizá AAPL",
        belt=valid_recipe,  # snapshot de la receta (campo 2)
        trayectoria=traj,    # campo 3
        senal=instr.build_signal(explicit="up", saved=True),   # campo 4
        costo=instr.build_cost(prompt_tokens=120, completion_tokens=80),  # campo 5
    )
    assert log_id > 0
    # lectura real: los 5 campos ligados por el MISMO run_id.
    row = instr.get_log(db_conn, run["id"])
    assert row is not None
    assert str(row["run_id"]) == str(run["id"])      # EL LIGADOR
    assert row["intent"] == "analizá AAPL"           # (1)
    assert row["belt"]["meta"]["nicho"] == "finanzas"  # (2)
    assert len(row["trayectoria"]) == 2              # (3) 1 model_call + 1 tool_call
    assert row["senal"]["explicit"] == "up"          # (4)
    assert row["costo"]["total_tokens"] == 200       # (5)
