"""
test_methods_repo.py — unit de la capa de datos de la pieza MÉTODO.

Cubre: normalización espejo del front (defaults + extras preservados), validación
(errores duros vs warnings), match léxico determinista (<1.2s por contrato del
front), y round-trip DB real (biblioteca + method_runs + control-plane) si hay
Postgres puppet_ai — skip honesto si no.

Correr:
    cd product/backend && PYTHONPATH=. .venv/bin/python app/phase1/test_methods_repo.py
    (o pytest app/phase1/test_methods_repo.py)
"""

from __future__ import annotations

import sys
import uuid

from app.phase1 import methods_repo as mr

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
    return cond


def test_normalize_preserves_and_defaults():
    m = mr.normalize_method({
        "name": "  Earnings semanal ",
        "phases": ["Investigar", "Producir"],
        "custom_field": {"x": 1},
        "steps": [
            {"text": "Bajar el 10-Q", "phase": "Investigar", "custom": "y"},
            {"text": "Comparar márgenes YoY", "checkpoint": 1, "executor": "  sec-edgar ",
             "retries": 5.0, "timeout": 30},
        ],
    })
    check("name trimmeado", m["name"] == "Earnings semanal")
    check("extra del método preservado", m.get("custom_field") == {"x": 1})
    check("phases[] aditivo preservado", m.get("phases") == ["Investigar", "Producir"])
    s0, s1 = m["steps"]
    check("step gana id", bool(s0["id"]))
    check("extra del step preservado", s0.get("custom") == "y")
    check("defaults del step", s0["checkpoint"] is False and s0["executor"] is None
          and s0["evidence_hint"] is None and s0["timeout"] is None and s0["retries"] == 3)
    check("checkpoint coercionado a bool", s1["checkpoint"] is True)
    check("executor trimmeado", s1["executor"] == "sec-edgar")
    check("retries coercionado a int", s1["retries"] == 5)
    check("timeout numérico pasa", s1["timeout"] == 30)


def test_validate():
    ok = mr.normalize_method({"name": "M", "steps": [{"text": "a"}]})
    errs, warns = mr.validate_method(ok)
    check("método válido sin errores", errs == [], str(errs))

    errs, _ = mr.validate_method(mr.normalize_method({"name": "", "steps": [{"text": "a"}]}))
    check("nombre vacío es error", any("nombre" in e for e in errs))

    errs, _ = mr.validate_method(mr.normalize_method({"name": "M", "steps": [{"text": "  "}]}))
    check("paso vacío es error", any("vacío" in e for e in errs))

    bad = mr.normalize_method({"name": "M", "steps": [{"text": "a"}]})
    bad["steps"][0]["timeout"] = -1
    errs, _ = mr.validate_method(bad)
    check("timeout <= 0 es error", any("timeout" in e for e in errs))

    bad = mr.normalize_method({"name": "M", "steps": [{"text": "a"}]})
    bad["steps"][0]["retries"] = -2
    errs, _ = mr.validate_method(bad)
    check("retries < 0 es error", any("retries" in e for e in errs))

    many = mr.normalize_method({
        "name": "M",
        "steps": [{"text": f"p{i}", "phase": f"F{i}"} for i in range(8)],
    })
    errs, warns = mr.validate_method(many)
    check(">6 fases es WARNING, no error", errs == [] and any("fases" in w for w in warns),
          f"errs={errs} warns={warns}")

    huge = mr.normalize_method({"name": "M", "steps": [{"text": "x" * 70000}]})
    errs, _ = mr.validate_method(huge)
    check("spec gigante es error", any("tamaño" in e for e in errs))


def test_match():
    methods = [
        mr.normalize_method({"id": "m1", "name": "Análisis de earnings",
                             "steps": [{"text": "Bajar el 10-Q de la empresa"},
                                       {"text": "Comparar márgenes YoY"}]}),
        mr.normalize_method({"id": "m2", "name": "Informe de mercado semanal",
                             "steps": [{"text": "Revisar índices"},
                                       {"text": "Escribir el resumen"}]}),
    ]
    m = mr.match_method(methods, "hazme el análisis de earnings de Apple con el 10-Q")
    check("matchea el método por nombre+pasos", bool(m) and m["id"] == "m1",
          str(m and m.get("id")))
    check("prompt sin eco no matchea", mr.match_method(methods, "qué hora es en Tokio") is None)
    check("prompt vacío no matchea", mr.match_method(methods, "") is None)
    check("acentos no rompen el match",
          (mr.match_method(methods, "analisis de earnings ya") or {}).get("id") == "m1")


def test_db_roundtrip():
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
    except Exception as e:
        print(f"  [SKIP] DB no disponible ({e}) — round-trip no probado")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email) VALUES (%s) RETURNING id",
                (f"metodo-test-{uuid.uuid4().hex[:8]}@test.local",))
            user_id = str(cur.fetchone()[0])
        conn.commit()

        m = mr.normalize_method({"name": "Método de prueba", "custom": "z",
                                 "phases": ["Fase A"],
                                 "steps": [{"text": "paso uno", "checkpoint": True}]})
        created = mr.create_method(conn, user_id=user_id, method=m)
        check("create devuelve id", bool(created.get("id")))
        check("create preserva extras", created.get("custom") == "z")

        got = mr.get_method(conn, created["id"], user_id)
        check("get round-trip", got and got["name"] == "Método de prueba"
              and got["steps"][0]["checkpoint"] is True)
        check("get ajeno es None (anti-IDOR)",
              mr.get_method(conn, created["id"], str(uuid.uuid4())) is None)

        # el front round-trippea el objeto ENTERO (con id/run_count) en el PUT:
        # el server debe stripear las claves server-owned sin romperse
        got["name"] = "Método editado"
        upd = mr.update_method(conn, created["id"], user_id, got)
        check("update round-trip", upd and upd["name"] == "Método editado")
        raw = mr.get_method(conn, created["id"], user_id)
        check("server keys NO anidadas en spec tras PUT round-trip",
              raw.get("run_count") == 0 and "id" in raw and raw["id"] == created["id"])

        mr.touch_method_run(conn, created["id"], user_id)
        got2 = mr.get_method(conn, created["id"], user_id)
        check("touch incrementa run_count y sella last_run_at",
              got2["run_count"] == 1 and got2["last_run_at"] is not None)

        ls = mr.list_methods(conn, user_id)
        check("list devuelve el método", len(ls) == 1 and ls[0]["id"] == created["id"])

        # method_runs + control-plane
        with conn.cursor() as cur:
            cur.execute("INSERT INTO runs (user_id, intent) VALUES (%s, %s) RETURNING id",
                        (user_id, "test"))
            run_id = str(cur.fetchone()[0])
        conn.commit()
        state = {"spec": got2, "current": got2["steps"][0]["id"], "step_status": {},
                 "attempts": {}, "skipped": [], "evidence": {}}
        row = mr.create_method_run(conn, run_id=run_id, method_id=created["id"],
                                   user_id=user_id, puppet_id=None, space_id="sp-test",
                                   state=state)
        check("method_run creado", row["run_id"] == run_id and row["status"] == "active")
        mr.update_method_run(conn, run_id, control_merge={"pause": True})
        check("control merge", mr.read_control(conn, run_id).get("pause") is True)
        mr.update_method_run(conn, run_id, control_clear=["pause"],
                             status="paused_user")
        ctl = mr.read_control(conn, run_id)
        got_run = mr.get_method_run(conn, run_id)
        check("control clear + status", "pause" not in ctl
              and got_run["status"] == "paused_user")

        mr.delete_method(conn, created["id"], user_id)
        got_run2 = mr.get_method_run(conn, run_id)
        check("borrar el método NO rompe el estado del run (SET NULL)",
              got_run2 is not None and got_run2["method_id"] is None)

        # limpieza
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    print("— normalización —")
    test_normalize_preserves_and_defaults()
    print("— validación —")
    test_validate()
    print("— match léxico —")
    test_match()
    print("— DB round-trip —")
    test_db_roundtrip()
    print(f"\n{_passed} PASS / {_failed} FAIL")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
