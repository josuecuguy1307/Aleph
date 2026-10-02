#!/usr/bin/env python3
"""
test_zotero_injection_invariant.py — EVIDENCIA REAL del invariante "construir ≠ inyectar"
para Zotero (Familia 4, token guiado). Responde a la pregunta que YA mordió al org:
¿la llave BYOK del usuario LLEGA DE VERDAD al server que la consume, o solo se guarda?

Prueba causal, SIN token real (usa una llave de juguete FALSA):

  POSITIVO (user A, con llave guardada):
    upsert_key(A,'zotero', FAKE)  → make_user_resolver(A) la resuelve (DB→resolver)
    → el assembler la mapea a ZOTERO_API_KEY (resolver→env-var canónico)
    → el zotero_server la recibe y LLAMA a la API VIVA de Zotero
    → Zotero responde 403 "Invalid key"  ← la llave LLEGÓ y se transmitió (fake → 403)

  NEGATIVO (user C, SIN llave):  control que hace la prueba causal
    resolver(C) → ""  → no se inyecta nada
    → el zotero_server responde "missing_credential"  ← NO llegó (porque no se guardó)

La DIFERENCIA 403-Invalid-key (positivo) vs missing_credential (negativo) demuestra que
la inyección OCURRE de verdad: si estuviera el bug (construir sin inyectar), el caso
POSITIVO también daría missing_credential. No da: da 403 contra Zotero vivo.

Dos caminos, ambos del path de PROD:
  [A] DETERMINISTA — usa las MISMAS funciones del assembler (_resolve_keys +
      _provider_env_vars) para armar el child_env y arranca el zotero_server real.
      Cero LLM → cero flakiness. Es el núcleo de la prueba.
  [B] END-TO-END — executor.run_puppet_e2e con la receta research-zotero y el resolver
      del broker (idéntico a lo que arma /v1/puppets/run). Corrobora por el loop entero.

Corre como script (imprime evidencia):
    cd product/backend && python3 -m app.phase1.test_zotero_injection_invariant
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo  # noqa: E402
from app.phase1 import credential_broker as broker  # noqa: E402
from app.phase1 import executor  # noqa: E402

_REPO_ROOT = _HERE.parents[4]
_ZOTERO_SERVER = _REPO_ROOT / "platform" / "assembler" / "fixtures" / "zotero_server.py"
_RECIPE = _REPO_ROOT / "platform" / "assembler" / "fixtures" / "e2e" / "research-zotero.recipe.json"

FAKE = "ZTOYfake1nject10nPr00f9988"   # llave de juguete reconocible (para grep anti-fuga)
EMAIL_A = "zotero-inject-a@puppet.local"
EMAIL_C = "zotero-inject-c@puppet.local"
PROVIDER = "zotero"


def _fp(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _jsonrpc(server_env: dict, calls: list[dict]) -> list[dict]:
    """Arranca el zotero_server real por stdio con `server_env` y manda los JSON-RPC."""
    lines = "\n".join(json.dumps(c) for c in calls) + "\n"
    proc = subprocess.run(
        [sys.executable, str(_ZOTERO_SERVER)],
        input=lines, capture_output=True, text=True, env=server_env, timeout=40,
    )
    out = []
    for ln in proc.stdout.splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _tool_text(resp: dict) -> str:
    try:
        return resp["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return json.dumps(resp)


def main() -> int:
    print("=" * 80)
    print("INVARIANTE construir≠inyectar · ZOTERO (Familia 4) — la llave LLEGA al server")
    print("=" * 80)

    # importar las MISMAS funciones del assembler que usa prod (no reimplementamos nada)
    asm = executor._asm()
    conn = repo.get_conn()
    failures: list[str] = []
    try:
        ua = repo.get_or_create_user(conn, EMAIL_A, "Zotero Inject A")
        uc = repo.get_or_create_user(conn, EMAIL_C, "Zotero Inject C (sin key)")
        uid_a, uid_c = ua["id"], uc["id"]
        print(f"\n[setup] user A (con key) = {uid_a}")
        print(f"        user C (SIN key)  = {uid_c}")

        # ── guardar la llave de juguete de A (write path de prod = repo.upsert_key,
        #    el MISMO que POST /v1/connectors/zotero/connect llama al validar) ──
        meta = repo.upsert_key(conn, user_id=uid_a, provider=PROVIDER, secret=FAKE)
        print(f"\n[1] upsert_key(A,'zotero') → meta sin secreto: {json.dumps(meta, default=str)}")
        if FAKE in json.dumps(meta, default=str):
            failures.append("FUGA: upsert_key devolvió el secreto en claro")

        # ── resolver del broker LIGADO al user (idéntico al de /v1/puppets/run) ──
        res_a = broker.make_user_resolver(uid_a, get_conn=repo.get_conn)
        res_c = broker.make_user_resolver(uid_c, get_conn=repo.get_conn)
        got_a = res_a("keys:zotero")
        got_c = res_c("keys:zotero")
        print(f"\n[2] resolver_A('keys:zotero') → fp={_fp(got_a) if got_a else None} (len {len(got_a)})")
        print(f"    resolver_C('keys:zotero') → {got_c!r}  (vacío = no tiene key)")
        if _fp(got_a) != _fp(FAKE):
            failures.append("resolver_A NO devolvió la key guardada (DB→resolver roto)")
        if got_c != "":
            failures.append("resolver_C devolvió algo (aislamiento roto)")

        # ════════════════════════════════════════════════════════════════════
        # [A] DETERMINISTA — armar child_env con las funciones del assembler y
        #     arrancar el zotero_server REAL. Cero LLM.
        # ════════════════════════════════════════════════════════════════════
        print("\n[A] DETERMINISTA — child_env del assembler → zotero_server real → Zotero vivo")
        recipe = json.loads(_RECIPE.read_text())

        # Esto es EXACTAMENTE lo que hace recipe_assembler.assemble_and_run:
        #   key_values = _resolve_keys(recipe.keys, byok_resolver)
        #   por cada provider → inyecta a child_env bajo _provider_env_vars(provider)
        def build_child_env(resolver) -> dict:
            import os
            kv = asm._resolve_keys(recipe.get("keys", {}), resolver)
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            for provider, val in kv.items():
                for var in asm._provider_env_vars(provider):
                    env[var] = val
            return env, kv

        env_a, kv_a = build_child_env(res_a)
        env_c, kv_c = build_child_env(res_c)
        print(f"    A: providers resueltos={sorted(kv_a)} · env vars inyectadas="
              f"{[k for k in env_a if k != 'PATH']}")
        print(f"    C: providers resueltos={sorted(kv_c)} · env vars inyectadas="
              f"{[k for k in env_c if k != 'PATH']}")
        if "ZOTERO_API_KEY" not in env_a:
            failures.append("A: el assembler NO mapeó la key a ZOTERO_API_KEY (resolver→env roto)")
        if "ZOTERO_API_KEY" in env_c:
            failures.append("C: se inyectó ZOTERO_API_KEY sin key guardada (¡fuga!)")

        calls = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "whoami", "arguments": {}}},
        ]
        resp_a = _jsonrpc(env_a, calls)
        resp_c = _jsonrpc(env_c, calls)
        txt_a = _tool_text(resp_a[-1]) if resp_a else "(sin respuesta)"
        txt_c = _tool_text(resp_c[-1]) if resp_c else "(sin respuesta)"
        print(f"\n    POSITIVO (A, key inyectada) whoami → {txt_a}")
        print(f"    NEGATIVO (C, sin key)       whoami → {txt_c}")

        a_reached = ("403" in txt_a) or ("Invalid key" in txt_a) or ('"status": 4' in txt_a)
        c_missing = "missing_credential" in txt_c
        if a_reached:
            print("    ✓ POSITIVO: la llave LLEGÓ al server (Zotero vivo la rechazó por fake=403),"
                  " NO 'missing_credential' → inyección PROBADA")
        else:
            failures.append(f"POSITIVO no probó inyección: {txt_a}")
        if c_missing:
            print("    ✓ NEGATIVO: sin key guardada → 'missing_credential' (fail-closed honesto)")
        else:
            failures.append(f"NEGATIVO no dio missing_credential: {txt_c}")
        if a_reached and c_missing:
            print("    ✓✓ CAUSAL: positivo≠negativo ⇒ la inyección OCURRE (no es 'construir sin inyectar')")

        # anti-fuga: el secreto jamás en claro en las respuestas del server
        if FAKE in (txt_a + txt_c):
            failures.append("FUGA: el secreto apareció en la respuesta del server")

        # ════════════════════════════════════════════════════════════════════
        # [B] END-TO-END — el loop entero por el path de prod (corroboración)
        # ════════════════════════════════════════════════════════════════════
        print("\n[B] END-TO-END — executor.run_puppet_e2e (resolver del broker, como /v1/puppets/run)")
        try:
            out = executor.run_puppet_e2e(
                recipe, "Llamá whoami UNA vez y reportá textual el JSON que devuelve.",
                user_id=uid_a, conn=None, byok_resolver=res_a, deadline_s=90.0,
            )
            rec = out.get("record", {}) or {}
            tcs = rec.get("tool_calls", []) or []
            print(f"    run_id={out.get('run_id')} ok={out.get('ok')} "
                  f"gate_enforced={out.get('gate_enforced')} byok_providers={rec.get('byok_providers')} "
                  f"model_final={rec.get('model_final')}")
            for tc in tcs:
                print(f"      [{tc.get('tool')} | {tc.get('gate_action')}] → {str(tc.get('result'))[:200]}")
            whoami_calls = [t for t in tcs if t.get("tool") == "whoami"]
            reached = any(("403" in str(t.get("result")) or "Invalid key" in str(t.get("result")))
                          for t in whoami_calls)
            rec_blob = json.dumps(rec, default=str)
            if FAKE in rec_blob:
                failures.append("FUGA: el secreto apareció en el run record")
            else:
                print("    ✓ anti-fuga: el secreto NO aparece en el run record")
            if rec.get("byok_providers") == ["zotero"]:
                print("    ✓ byok_providers=['zotero'] → el run resolvió e inyectó la key")
            if reached:
                print("    ✓ e2e: whoami golpeó Zotero vivo con la key inyectada (403 fake)")
            elif whoami_calls:
                print(f"    ⚠ e2e: whoami corrió pero sin 403 claro (resultado arriba)")
            else:
                print("    ⚠ e2e: el modelo no llamó whoami este run (no invalida [A]; [A] es determinista)")
        except Exception as exc:
            print(f"    ⚠ e2e excepción (no invalida [A]): {type(exc).__name__}: {exc}")

    finally:
        # cleanup
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM keys WHERE user_id IN (%s,%s)", (uid_a, uid_c))
                cur.execute("DELETE FROM users WHERE id IN (%s,%s)", (uid_a, uid_c))
            conn.commit()
            print("\n[cleanup] keys + users de prueba borrados (estado limpio).")
        except Exception as exc:
            print(f"[cleanup] aviso: {exc}")
        conn.close()

    print("\n" + "=" * 80)
    if failures:
        print("RESULTADO: ✗ FALLAS:")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULTADO: ✓ INYECCIÓN PROBADA — la llave del usuario LLEGA al server (construir = inyectar).")
    print("           Sin token real: positivo da 403 (fake) y negativo da missing_credential.")
    print("           Con el token real que pegues por el connect-wizard: el mismo path escribe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
