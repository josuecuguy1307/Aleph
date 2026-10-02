#!/usr/bin/env python3
"""
test_credential_broker_roundtrip.py — EVIDENCIA REAL ejecutada del credential-broker
por end-user (F4-B4, Tier A). NO es declaración: corre contra el Postgres real `puppet_ai`,
escribe credenciales cifradas, las inyecta a un belt real vía el resolver del broker, y
demuestra con fingerprint que la credencial llegó al server SIN exponer el valor.

Qué prueba (cada bloque imprime EVIDENCIA):
  1. ROUND-TRIP: POST-equivalente (repo.upsert_key) guarda la credencial → SELECT crudo
     en Postgres muestra ciphertext ≠ plaintext → el resolver del broker la resuelve →
     el assembler la inyecta al child_env del belt → cred_status() devuelve el fingerprint
     que coincide con sha256(secreto)[:12]. La credencial nunca aparece en claro.
  2. AISLAMIENTO: dos users con dos credenciales distintas → cada resolver devuelve SOLO
     la del suyo (fingerprints distintos); un resolver de A jamás resuelve la de B.
  3. CERO PLAINTEXT: grep del secreto de prueba sobre el run record + la fila de DB → 0
     hits fuera de la fila cifrada.

Corre como script (no pytest) para imprimir la evidencia legible:
    python3 -m app.phase1.test_credential_broker_roundtrip   (desde product/backend)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# permitir ejecución como módulo desde product/backend
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]  # product/backend
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo  # noqa: E402
from app.phase1 import credential_broker as broker  # noqa: E402
from app.phase1 import executor  # noqa: E402

_REPO_ROOT = _HERE.parents[4]
_PROBE_BELT = "platform/assembler/fixtures/belt-credprobe.mcp.json"

# Secretos de prueba (formas reconocibles para el grep anti-fuga). Distintos por usuario.
SECRET_A = "sk-PROBE-USERA-1111aaaa2222bbbb3333cccc"
SECRET_B = "sk-PROBE-USERB-9999zzzz8888yyyy7777xxxx"

EMAIL_A = "broker-test-a@puppet.local"
EMAIL_B = "broker-test-b@puppet.local"
PROVIDER = "probe"


def _fp(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _probe_recipe() -> dict:
    """Receta v1 válida que usa el belt fixture del probe. keys.probe.byok_ref = 'keys:probe'
    (forma canónica §3.4). El user_id se liga afuera, en el resolver del broker."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Cred Broker Probe", "nicho": "test"},
        "model": {
            "primary": "openai/gpt-oss-120b",
            "fallback": "llama-3.3-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1",
            "temperature": 0,
            "max_tokens": 512,
            "max_turns": 3,
        },
        "belt": {
            "belt_ref": _PROBE_BELT,
            "tool_filters": {"credprobe": ["cred_status"]},
        },
        "framing": {
            "inline": (
                "Sos un agente de diagnóstico. Tu ÚNICA tarea: llamar la herramienta "
                "cred_status (sin argumentos) UNA vez y reportar textualmente el JSON que "
                "devuelve. No inventes nada."
            )
        },
        "rag": {"enabled": False},
        "keys": {PROVIDER: {"byok_ref": "keys:probe"}},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }


def _raw_select_ciphertext(conn, user_id: str) -> dict:
    """SELECT CRUDO de la fila keys del usuario: el ciphertext tal cual está en disco."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT provider, ciphertext, enc_scheme, last4 FROM keys "
            "WHERE user_id = %s AND provider = %s",
            (user_id, PROVIDER),
        )
        row = cur.fetchone()
    if not row:
        return {}
    provider, ciphertext, enc_scheme, last4 = row
    cb = bytes(ciphertext) if not isinstance(ciphertext, (bytes, bytearray)) else bytes(ciphertext)
    return {
        "provider": provider,
        "enc_scheme": enc_scheme,
        "last4": last4,
        "ciphertext_bytes": cb,
        "ciphertext_b64_head": cb[:48].hex(),
        "ciphertext_len": len(cb),
    }


def main() -> int:
    print("=" * 78)
    print("F4-B4 · CREDENTIAL-BROKER POR END-USER — ROUND-TRIP REAL (Postgres puppet_ai)")
    print("=" * 78)

    conn = repo.get_conn()
    failures: list[str] = []
    try:
        # ── setup: dos usuarios ──────────────────────────────────────────────
        ua = repo.get_or_create_user(conn, EMAIL_A, "Broker Test A")
        ub = repo.get_or_create_user(conn, EMAIL_B, "Broker Test B")
        uid_a, uid_b = ua["id"], ub["id"]
        print(f"\n[setup] user A = {uid_a}\n        user B = {uid_b}")

        # ── 1) GUARDAR la credencial CIFRADA (el write path de prod: repo.upsert_key,
        #       igual que POST /v1/keys → repo.upsert_key) ───────────────────────
        meta_a = repo.upsert_key(conn, user_id=uid_a, provider=PROVIDER, secret=SECRET_A)
        meta_b = repo.upsert_key(conn, user_id=uid_b, provider=PROVIDER, secret=SECRET_B)
        print("\n[1] upsert_key devolvió SOLO metadatos (sin secreto, sin ciphertext):")
        print("    A:", json.dumps(meta_a, default=str))
        print("    B:", json.dumps(meta_b, default=str))
        # el return de upsert NO debe traer el secreto ni el ciphertext
        for label, meta, secret in (("A", meta_a, SECRET_A), ("B", meta_b, SECRET_B)):
            blob = json.dumps(meta, default=str)
            if secret in blob:
                failures.append(f"FUGA: upsert_key({label}) devolvió el secreto en claro")
            if "ciphertext" in meta:
                failures.append(f"FUGA: upsert_key({label}) devolvió el ciphertext")

        # ── 1b) SELECT CRUDO: ciphertext ≠ plaintext en Postgres ───────────────
        raw_a = _raw_select_ciphertext(conn, uid_a)
        raw_b = _raw_select_ciphertext(conn, uid_b)
        print("\n[1b] SELECT crudo en Postgres (lo que vive en disco):")
        print(f"    A: enc_scheme={raw_a['enc_scheme']} last4={raw_a['last4']} "
              f"len={raw_a['ciphertext_len']} ciphertext[hex:0..48]={raw_a['ciphertext_b64_head']}…")
        print(f"    B: enc_scheme={raw_b['enc_scheme']} last4={raw_b['last4']} "
              f"len={raw_b['ciphertext_len']} ciphertext[hex:0..48]={raw_b['ciphertext_b64_head']}…")
        # ciphertext ≠ plaintext (la prueba de cifrado at-rest)
        for label, raw, secret in (("A", raw_a, SECRET_A), ("B", raw_b, SECRET_B)):
            ct = raw.get("ciphertext_bytes", b"")
            if secret.encode() in ct:
                failures.append(f"CRÍTICO: ciphertext({label}) contiene el plaintext (NO cifrado)")
            else:
                print(f"    ✓ ciphertext({label}) ≠ plaintext (el secreto NO aparece en los bytes)")
        # last4 sí debe coincidir (es metadato no secreto)
        if raw_a["last4"] != SECRET_A[-4:]:
            failures.append("last4(A) no coincide con los últimos 4 del secreto")
        # ciphertexts distintos entre usuarios
        if raw_a["ciphertext_bytes"] == raw_b["ciphertext_bytes"]:
            failures.append("CRÍTICO: ciphertext(A) == ciphertext(B) (no hay aislamiento)")
        else:
            print("    ✓ ciphertext(A) ≠ ciphertext(B) (dos users, dos cifrados distintos)")

        # ── 2) RESOLVER del broker LIGADO al user → descifra en memoria ────────
        resolver_a = broker.make_user_resolver(uid_a, get_conn=repo.get_conn)
        resolver_b = broker.make_user_resolver(uid_b, get_conn=repo.get_conn)
        # forma canónica de byok_ref que viaja en la receta
        ref = "keys:probe"
        val_a = resolver_a(ref)
        val_b = resolver_b(ref)
        print("\n[2] resolver del broker (descifra en memoria; acá mostramos SOLO fingerprint):")
        print(f"    resolver_A(keys:probe) → fp={_fp(val_a) if val_a else None} (len {len(val_a)})")
        print(f"    resolver_B(keys:probe) → fp={_fp(val_b) if val_b else None} (len {len(val_b)})")
        if val_a != SECRET_A:
            failures.append("resolver_A no devolvió la credencial de A")
        if val_b != SECRET_B:
            failures.append("resolver_B no devolvió la credencial de B")
        # AISLAMIENTO CRUZADO: resolver de A jamás devuelve la credencial de B
        if val_a == SECRET_B or val_b == SECRET_A:
            failures.append("CRÍTICO: cruce de credenciales entre usuarios")
        else:
            print("    ✓ aislamiento: resolver_A≠B; cada uno resuelve SOLO su credencial")

        # ── 3) RUN REAL: el assembler inyecta la credencial de A al belt del probe.
        #       El modelo llama cred_status(); el fingerprint debe coincidir con A. ──
        print("\n[3] RUN E2E real (user A): assembler → child_env del belt → cred_status()")
        recipe = _probe_recipe()
        out_a = executor.run_puppet_e2e(
            recipe,
            "Llamá cred_status y reportá el JSON.",
            user_id=uid_a,
            conn=conn,
            byok_resolver=resolver_a,
            deadline_s=90.0,
        )
        rec = out_a.get("record") or {}
        print(f"    run_id={out_a.get('run_id')} ok={out_a.get('ok')} "
              f"gate_enforced={out_a.get('gate_enforced')}")
        print(f"    tools_cabled={rec.get('tools_cabled')} byok_providers={rec.get('byok_providers')}")
        # buscar el resultado de cred_status en los tool_calls del record
        observed_fp = None
        for tc in rec.get("tool_calls", []) or []:
            if tc.get("tool") in ("credprobe", "cred_status") or "fingerprint" in str(tc.get("result", "")):
                try:
                    # el result puede venir trimmeado; parseamos el JSON embebido
                    res = tc.get("result", "")
                    start = res.find("{")
                    if start >= 0:
                        parsed = json.loads(res[start:res.rfind("}") + 1])
                        observed_fp = parsed.get("fingerprint_sha256_12")
                        print(f"    cred_status() → present={parsed.get('present')} "
                              f"length={parsed.get('length')} fingerprint={observed_fp}")
                except Exception:
                    pass
        expected_fp = _fp(SECRET_A)
        if observed_fp == expected_fp:
            print(f"    ✓ INYECCIÓN PROBADA: fingerprint del server = sha256(secretoA)[:12] = {expected_fp}")
        else:
            # El modelo OSS podría no llamar la tool de forma confiable; lo registramos como
            # señal pero NO lo damos por probado a ciegas — la evidencia dura es el fingerprint.
            failures.append(
                f"el run no produjo el fingerprint esperado vía el modelo "
                f"(observado={observed_fp}, esperado={expected_fp}); ver bloque [3b] determinista"
            )

        # ── 3b) INYECCIÓN DETERMINISTA (sin depender del modelo): cableamos el belt
        #        a mano con el resolver de A y leemos cred_status directo del server. ──
        print("\n[3b] Inyección DETERMINISTA (registry directo, sin LLM):")
        det = _direct_injection_probe(recipe, resolver_a)
        print(f"    cred_status() directo → {json.dumps(det)}")
        if det.get("fingerprint_sha256_12") == expected_fp:
            print(f"    ✓ el child_env del belt recibió la credencial de A (fp coincide)")
        else:
            failures.append("inyección determinista NO entregó la credencial al child_env del belt")

        # cross-user determinista: con el resolver de B, el MISMO belt debe ver la cred de B
        det_b = _direct_injection_probe(recipe, resolver_b)
        if det_b.get("fingerprint_sha256_12") == _fp(SECRET_B):
            print(f"    ✓ aislamiento E2E: con resolver_B el belt ve la cred de B (fp distinto de A)")
        else:
            failures.append("aislamiento E2E falló: resolver_B no entregó la cred de B al belt")

        # ── 4) CERO PLAINTEXT en el run record + DB blob ───────────────────────
        print("\n[4] anti-fuga: el secreto NUNCA en claro en el run record:")
        record_blob = json.dumps(out_a, default=str, ensure_ascii=False)
        leaked_in_record = [s for s in (SECRET_A, SECRET_B) if s in record_blob]
        if leaked_in_record:
            failures.append(f"FUGA en run record: {leaked_in_record}")
        else:
            print("    ✓ run record (model_route/tool_calls/belt/usage): 0 hits del secreto")

        # limpieza: borrar las credenciales y users de prueba (estado limpio)
        repo.delete_key(conn, uid_a, PROVIDER)
        repo.delete_key(conn, uid_b, PROVIDER)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = ANY(%s)", ([EMAIL_A, EMAIL_B],))
        conn.commit()
        print("\n[cleanup] credenciales + users de prueba borrados (estado limpio).")

    finally:
        conn.close()

    print("\n" + "=" * 78)
    if failures:
        print("RESULTADO: ✗ FALLÓ")
        for f in failures:
            print("  •", f)
        return 1
    print("RESULTADO: ✓ ROUND-TRIP COMPLETO — cifrado at-rest + inyección por usuario + "
          "aislamiento + cero plaintext.")
    return 0


def _direct_injection_probe(recipe: dict, resolver) -> dict:
    """Cablea el belt del probe a mano (sin el modelo) con el resolver dado, arranca el
    server con el child_env construido por el assembler, y llama cred_status() directo.
    Demuestra que la credencial del usuario llega al subprocess, deterministicamente."""
    import importlib.util as _ilu
    asm_dir = _REPO_ROOT / "platform" / "assembler"
    if str(asm_dir) not in sys.path:
        sys.path.insert(0, str(asm_dir))
    spec = _ilu.spec_from_file_location("puppet_recipe_assembler_probe", asm_dir / "recipe_assembler.py")
    ra = _ilu.module_from_spec(spec)
    spec.loader.exec_module(ra)

    # replicamos EXACTAMENTE el cableo del assembler: resolve keys → child_env →
    # expand server cfg → MCPServer(env=...). Reusamos sus helpers (no reimplementamos).
    import json as _json
    belt_path = _REPO_ROOT / _PROBE_BELT
    mcp_cfg = _json.loads(belt_path.read_text(encoding="utf-8"))
    scfg = mcp_cfg["mcpServers"]["credprobe"]

    key_values = ra._resolve_keys(recipe.get("keys", {}), resolver)
    import os as _os
    child_env = dict(_os.environ)
    for provider, val in key_values.items():
        for ev in ra._provider_env_vars(provider):
            child_env.setdefault(ev, val)
    base_env = ra._puppet_run_env(_REPO_ROOT, child_env)
    command, args, srv_env = ra._expand_server_cfg(scfg, base_env)
    srv = ra._asm.MCPServer("credprobe", command, args, env=srv_env)
    if not srv.start():
        return {"error": "server no arrancó"}
    try:
        raw = srv.call_tool("cred_status", {})
        return _json.loads(raw)
    finally:
        srv.stop()


if __name__ == "__main__":
    raise SystemExit(main())
