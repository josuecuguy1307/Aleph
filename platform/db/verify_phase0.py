"""
verify_phase0.py — EVIDENCIA del gate de Fase 0 (Database & Data).

No declara nada: corre contra el Postgres real y muestra output.
  1. Conecta + SELECT de prueba corre.
  2. Las 7 tablas existen.
  3. puppets guarda la receta como config.json JSONB parametrizable (round-trip).
  4. Inserta un instrumentation_logs de prueba con los 5 campos ligados por
     run_id (intent·belt·trayectoria·señal·costo) y lo lee de vuelta.
  5. BYOK: cifra una key, demuestra que el BYTEA almacenado NO es plaintext,
     y la descifra de vuelta.

Limpia sus filas de prueba al final (rollback de un savepoint dedicado), salvo
--keep para inspección manual.

Uso:
    python3 platform/db/verify_phase0.py
"""

from __future__ import annotations

import json
import sys

from psycopg2.extras import Json, RealDictCursor

from db import decrypt_secret, encrypt_secret, get_conn

EXPECTED_TABLES = [
    "users", "puppets", "runs", "outputs",
    "historial", "keys", "instrumentation_logs",
]

INSTR_FIELDS = ["intent", "belt", "trayectoria", "senal", "costo"]


def line(c="─"):
    print(c * 72)


def main(keep: bool = False) -> int:
    conn = get_conn()
    conn.autocommit = False
    ok = True
    try:
        # ── 1. SELECT de prueba ─────────────────────────────────────────────
        line("=")
        print("1 · CONEXIÓN + SELECT DE PRUEBA")
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, version();")
            db, user, ver = cur.fetchone()
        print(f"   db={db}  user={user}")
        print(f"   {ver.split(',')[0]}")
        print("   SELECT corre ✓")

        # ── 2. Las 7 tablas existen ─────────────────────────────────────────
        line()
        print("2 · TABLAS EXISTEN")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' ORDER BY table_name;
            """)
            present = [r[0] for r in cur.fetchall()]
        for t in EXPECTED_TABLES:
            mark = "✓" if t in present else "✗ FALTA"
            print(f"   {mark}  {t}")
            ok = ok and (t in present)

        # ── set-up: user → puppet (receta JSONB) → run ──────────────────────
        line()
        print("3 · puppets guarda la receta como config.json JSONB parametrizable")
        receta = {
            "model": "gpt-oss-120b",
            "base_url": "http://127.0.0.1:4000/v1",
            "belt_version": "1.0.0",
            "tool_filters": {"sympy": ["sympy_diff", "sympy_solve"]},
            "framing": "tutor riguroso",
            "rag": {"enabled": True, "mode": "manual"},
            "temperature": 0,
            "max_turns": 8,
            "max_tokens": 2048,
        }
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO users (email, display_name, tier) "
                "VALUES (%s,%s,%s) RETURNING id;",
                ("verify+phase0@puppet.ai", "Verify Phase0", "tecnico"),
            )
            user_id = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO puppets (owner_id, name, nicho, config) "
                "VALUES (%s,%s,%s,%s) RETURNING id;",
                (user_id, "Tutor STEM verify", "educacion", Json(receta)),
            )
            puppet_id = cur.fetchone()["id"]

            # round-trip: consultar DENTRO de la receta JSONB (prueba que es parametrizable)
            cur.execute(
                "SELECT config->>'model' AS model, config->'rag'->>'mode' AS rag_mode "
                "FROM puppets WHERE id=%s;", (puppet_id,),
            )
            row = cur.fetchone()
        print(f"   receta guardada y consultada DENTRO del JSONB: "
              f"model={row['model']!r} rag_mode={row['rag_mode']!r} ✓")
        ok = ok and row["model"] == "gpt-oss-120b" and row["rag_mode"] == "manual"

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO runs (puppet_id, user_id, space_id, intent, status) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id;",
                (puppet_id, user_id, "sp_verify_01",
                 "Convertí 108 km/h a m/s con verificación de unidades", "done"),
            )
            run_id = cur.fetchone()["id"]

        # ── 4. instrumentation_logs: los 5 campos ligados por run_id ────────
        line()
        print("4 · instrumentation_logs — 5 campos ligados por run_id (EL MOAT)")
        intent = "Convertí 108 km/h a m/s con verificación de unidades"
        belt = {  # (2) la receta usada (snapshot)
            "model": receta["model"], "belt_version": receta["belt_version"],
            "tool_filters": receta["tool_filters"], "rag": receta["rag"],
        }
        trayectoria = [  # (3) secuencia model+tool calls, c/u latency_ms y error
            {"seq": 1, "kind": "model_call", "name": "gpt-oss-120b",
             "latency_ms": 812, "error": None},
            {"seq": 2, "kind": "tool_call", "name": "units_check",
             "latency_ms": 47, "error": None,
             "args": "108 km/h -> m/s", "result": "30 m/s"},
            {"seq": 3, "kind": "model_call", "name": "gpt-oss-120b",
             "latency_ms": 604, "error": None},
        ]
        senal = {  # (4) explícita + implícita
            "explicit": "up",
            "implicit": {"saved": True, "edited": False, "abandoned": False},
        }
        costo = {  # (5) tokens
            "prompt_tokens": 1320, "completion_tokens": 210, "total_tokens": 1530,
            "by_model": {"gpt-oss-120b": 1530},
        }
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO instrumentation_logs "
                "(run_id, intent, belt, trayectoria, senal, costo) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id;",
                (run_id, intent, Json(belt), Json(trayectoria), Json(senal), Json(costo)),
            )
            instr_id = cur.fetchone()["id"]
        print(f"   insertado instrumentation_logs.id={instr_id}  run_id={run_id}")

        # leer de vuelta — JOIN por run_id para probar el ligado
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT il.run_id, il.intent, il.belt, il.trayectoria, il.senal, il.costo,
                       r.space_id, p.nicho, p.config->>'model' AS receta_model
                FROM instrumentation_logs il
                JOIN runs r    ON r.id = il.run_id
                JOIN puppets p ON p.id = r.puppet_id
                WHERE il.id = %s;
            """, (instr_id,))
            got = cur.fetchone()
        print(f"   leído de vuelta vía JOIN por run_id (nicho={got['nicho']}, "
              f"space={got['space_id']}):")
        for f in INSTR_FIELDS:
            val = got[f]
            preview = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else repr(val)
            if len(preview) > 70:
                preview = preview[:67] + "..."
            present = val is not None
            ok = ok and present
            print(f"      {'✓' if present else '✗'} {f:<12} = {preview}")
        # checks duros de integridad del ligado y del contenido
        checks = {
            "run_id liga": str(got["run_id"]) == str(run_id),
            "trayectoria con latency+error por call":
                all("latency_ms" in s and "error" in s for s in got["trayectoria"]),
            "señal explícita + implícita":
                got["senal"].get("explicit") == "up"
                and set(got["senal"]["implicit"]) == {"saved", "edited", "abandoned"},
            "costo en tokens": got["costo"]["total_tokens"] == 1530,
            "belt = receta (snapshot coincide con puppet.config)":
                got["belt"]["model"] == got["receta_model"],
        }
        for label, passed in checks.items():
            ok = ok and passed
            print(f"      {'✓' if passed else '✗'} {label}")

        # ── 5. BYOK cifrada at-rest ─────────────────────────────────────────
        line()
        print("5 · keys BYOK — cifradas at-rest (nunca plaintext)")
        plaintext = "sk-secret-BYOK-ABCD-1234"
        token = encrypt_secret(plaintext)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO keys (user_id, provider, ciphertext, last4) "
                "VALUES (%s,%s,%s,%s) RETURNING id;",
                (user_id, "openai", token, plaintext[-4:]),
            )
            key_id = cur.fetchone()["id"]
            # leer el BYTEA crudo tal como quedó en la DB
            cur.execute("SELECT ciphertext, last4 FROM keys WHERE id=%s;", (key_id,))
            stored = cur.fetchone()
        raw = bytes(stored["ciphertext"])
        contains_plain = plaintext.encode() in raw
        roundtrip = decrypt_secret(raw)
        print(f"   plaintext original : {plaintext!r}")
        print(f"   BYTEA en DB (head) : {raw[:48]!r}...")
        print(f"   ¿la DB contiene el plaintext? {'SÍ ✗' if contains_plain else 'NO ✓'}")
        print(f"   descifrado de vuelta == original: "
              f"{'✓' if roundtrip == plaintext else '✗'}  (last4 visible: {stored['last4']})")
        ok = ok and (not contains_plain) and (roundtrip == plaintext)

        line("=")
        if keep:
            conn.commit()
            print(f"VEREDICTO: {'✓ TODO PASA' if ok else '✗ HAY FALLOS'}  (--keep: filas de prueba PERSISTIDAS)")
        else:
            conn.rollback()
            print(f"VEREDICTO: {'✓ TODO PASA' if ok else '✗ HAY FALLOS'}  (filas de prueba revertidas con ROLLBACK)")
        return 0 if ok else 1
    except Exception as exc:
        conn.rollback()
        print(f"\n✗ EXCEPCIÓN: {type(exc).__name__}: {exc}")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(keep="--keep" in sys.argv))
