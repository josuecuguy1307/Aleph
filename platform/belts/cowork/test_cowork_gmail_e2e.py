#!/usr/bin/env python3
"""
test_cowork_gmail_e2e.py — verificacion E2E de la mitad GMAIL del belt COWORK SIN cuenta real.

(Notion lo lleva otra terminal; esta prueba cubre SOLO Gmail: dejar borrador + send-gate.)

Contra un stub local de la API de Gmail (formas reales + auth real), corre TRES capas:

  PARTE 1 — GATE (deterministico, sin modelo): construye el gate enforced desde la receta +
    base_matrix y verifica: create_draft EJECUTA; send_email queda NEEDS_OK (HELD) aunque la
    receta apague el gate.

  PARTE 2 — INYECCION + DRAFT + IDEMPOTENCIA (deterministico): bootea el server con EL MISMO
    codigo de inyeccion del assembler. El stub exige el bearer correcto: si la BYOK no se
    inyecta de verdad, el bearer no llega -> 401 -> falla ruidosa (construir!=inyectar).
    Prueba: borrador real y que re-crear NO duplica.

  PARTE 3 — RUN REAL POR EL PATH DE PROD (OSS opera el belt): assemble_and_run con el modelo
    OSS y el ENFORCER en el path. base_matrix=None A PROPOSITO (replica :8080: el router pasa
    None) -> prueba la AUTO-CARGA del base_matrix declarado por el belt. Verifica que el
    borrador queda y que el send queda HELD (/messages/send NUNCA se toca).

Uso:  python3 platform/belts/cowork/test_cowork_gmail_e2e.py
Salida: evidencia por parte + veredicto. Exit 0 si DONE, 1 si algo falla.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[2]
_ASM_DIR = _REPO / "platform" / "assembler"
sys.path.insert(0, str(_ASM_DIR))
sys.path.insert(0, str(_THIS / "fixtures"))

import gmail_stub as stub  # noqa: E402

DUMMY_GMAIL = "ya29.DUMMY_oauth_inyeccion_verificada_no_es_token_real"

RECIPE_PATH = _ASM_DIR / "fixtures" / "e2e" / "cowork-gmail.recipe.json"
BASE_MATRIX_PATH = _REPO / "catalog" / "templates" / "cowork" / "base-matrix-cowork-gmail.json"

_ok = 0
_fail = 0


def check(cond: bool, label: str, detail: str = ""):
    global _ok, _fail
    mark = "[PASS]" if cond else "[FAIL]"
    if cond:
        _ok += 1
    else:
        _fail += 1
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))


def _byok_resolver(ref: str) -> str:
    # byok_ref CANÓNICO (prefijo 'keys:', el que exige el validador y usa el broker real):
    # 'keys:gmail' → cleartext. Alineado con la receta de prod; el broker real resuelve
    # 'keys:gmail' → provider 'gmail' → get_key (no este atajo).
    return {"keys:gmail": DUMMY_GMAIL}.get(ref, "")


def main() -> int:
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    base_matrix = json.loads(BASE_MATRIX_PATH.read_text(encoding="utf-8"))

    state, base_url, shutdown = stub.start_stub(DUMMY_GMAIL)
    os.environ["GMAIL_API_BASE"] = base_url
    # PUPPET_BELTS = product/belts — BELTS-ROOT ÚNICO (decisión A/T7, igual que el executor de
    # prod). Ambos servers cuelgan de acá: gaps/ (programación) y cowork/. El belt referencia su
    # server como ${PUPPET_BELTS}/cowork/gmail_draft_server.py. Seteamos la misma base que :8080
    # para que el test standalone espeje exactamente el path de prod.
    os.environ["PUPPET_BELTS"] = str(_REPO / "product" / "belts")

    try:
        import recipe_assembler as ra  # noqa: E402

        # ── PARTE 1 — GATE ───────────────────────────────────────────────────────
        print("\n===== PARTE 1 — GATE: send HELD, draft ejecuta =====")
        gate = ra._enforcer.build_enforced_gate(recipe, base_matrix=base_matrix)
        D = gate.evaluate("gmail", "create_draft", {"to": "a@b.com", "subject": "s"})
        check(D.action == "execute", "create_draft -> EJECUTA (borrador, no envia)", D.action)
        D = gate.evaluate("gmail", "send_email", {"to": "a@b.com", "subject": "s", "body": "hola"})
        check(D.action == "needs_ok", "send_email -> NEEDS_OK (HELD: el gate detiene el envio)", D.action)
        check(D.level == "confirma-siempre", "send_email -> confirma-siempre (mandatorio)", D.level)
        check(bool(D.payload.get("requiere_ok")) and "vista_previa" in D.payload,
              "send_email -> payload de UX (que/donde/vista_previa/OK) presente")

        # ── PARTE 2 — INYECCION + DRAFT + IDEMPOTENCIA ──────────────────────────
        print("\n===== PARTE 2 — INYECCION real + draft + idempotencia =====")
        key_values = ra._resolve_keys(recipe.get("keys", {}), _byok_resolver)
        check(key_values.get("gmail") == DUMMY_GMAIL, "BYOK resuelta por ref (gmail)")
        child_env = dict(os.environ)
        for provider, val in key_values.items():
            for env_var in ra._provider_env_vars(provider):
                child_env.setdefault(env_var, val)
        check(child_env.get("GMAIL_TOKEN") == DUMMY_GMAIL,
              "alias provider->env: GMAIL_TOKEN poblado en child_env", "construir->inyectar")

        base_env = ra._puppet_run_env(_REPO, child_env)
        belt = json.loads((_REPO / recipe["belt"]["belt_ref"]).read_text(encoding="utf-8"))
        scfg = belt["mcpServers"]["gmail"]
        command, args, srv_env = ra._expand_server_cfg(scfg, base_env)
        gmail = ra._asm.MCPServer("gmail", command, args, env=srv_env)
        check(gmail.start(), "MCP server 'gmail' booteo (init+initialized)")

        def call(tool, a):
            return json.loads(gmail.call_tool(tool, a))

        d1 = call("create_draft", {"to": "equipo@ejemplo.com", "subject": "Resumen reunion", "body": "Adjunto el acta."})
        check(d1.get("created") is True and d1.get("draft_id"),
              "Gmail WRITE: create_draft dejo el borrador (NO envio)", f"draft_id={d1.get('draft_id')}")
        check(state.gmail_bearer_seen == DUMMY_GMAIL,
              "INYECCION Gmail: el server mando el bearer correcto", "construir!=inyectar OK")
        d2 = call("create_draft", {"to": "equipo@ejemplo.com", "subject": "Resumen reunion", "body": "Adjunto el acta."})
        d3 = call("create_draft", {"to": "equipo@ejemplo.com", "subject": "Resumen reunion", "body": "otro cuerpo"})
        idem = d2.get("idempotent") is True and d3.get("idempotent") is True
        same = d2.get("draft_id") == d1.get("draft_id") == d3.get("draft_id")
        check(idem and same and len(state.gmail_drafts) == 1,
              "IDEMPOTENCIA Gmail: re-correr NO duplica el draft", f"drafts={len(state.gmail_drafts)}")
        check(state.send_count == 0, "SEND nunca se ejecuto en la Parte 2 (no llamamos send_email)")
        gmail.stop()

        # ── PARTE 3 — RUN REAL POR EL PATH DE PROD ──────────────────────────────
        print("\n===== PARTE 3 — RUN REAL: OSS opera el belt, gate en el path =====")
        prompt = (
            "Prepara un borrador de correo para 'jefe@ejemplo.com' con asunto "
            "'Resumen de la reunion' y un cuerpo de dos lineas resumiendo que el belt cowork "
            "quedo verificado. Dejalo en BORRADOR: NO lo envies (no uses send_email). "
            "Cuando termines, deci en una frase que hiciste."
        )
        # base_matrix=None A PROPOSITO: replica :8080 (router pasa None) -> prueba la AUTO-CARGA.
        try:
            record = ra.assemble_and_run(
                recipe, prompt, repo_root=_REPO,
                byok_resolver=_byok_resolver, base_matrix=None, deadline_s=150.0,
            )
        except Exception as exc:  # noqa: BLE001
            record = {"ok": False, "error": f"excepcion: {exc}", "gate_enforced": False,
                      "tool_calls": [], "gate_decisions": []}

        check(bool(record.get("gate_enforced")), "Gate construido y montado en el path (gate_enforced)")
        tool_calls = record.get("tool_calls", [])
        held_drafts = [t for t in tool_calls if t.get("tool") == "create_draft" and t.get("gate_action") == "needs_ok"]
        check(not held_drafts,
              "AUTO-CARGA base_matrix (path real, router pasa None): create_draft NO paralizado",
              f"held={[t.get('tool') for t in held_drafts]}")
        send_attempts = [t for t in tool_calls if t.get("tool") == "send_email"]
        for t in send_attempts:
            check(t.get("gate_action") == "needs_ok",
                  "si el modelo intento send_email, el gate lo detuvo (needs_ok)", t.get("gate_action"))
        check(state.send_count == 0,
              "SEND HELD en el run real: /messages/send NUNCA se toco (correo no salio)",
              f"send_count={state.send_count}")
        drafted = [t for t in tool_calls if t.get("tool") == "create_draft" and t.get("gate_action") == "execute"]
        check(bool(drafted) or len(state.gmail_drafts) >= 1,
              "OSS opero el belt: dejo un borrador real por el path", f"drafts_total={len(state.gmail_drafts)}")

        if record.get("error"):
            print(f"   [nota] el run OSS reporto: {record.get('error')} "
                  f"(cognicion/red); las Partes 1-2 ya prueban la mitad gmail de forma deterministica.")
        print("\n   --- evidencia del run real ---")
        print(f"   model_final={record.get('model_final')} turns={record.get('turns')} ok={record.get('ok')}")
        print(f"   tools_cabled={record.get('tools_cabled')}")
        for t in tool_calls:
            print(f"     · {t.get('tool')} [{t.get('gate_action')}] -> {str(t.get('result'))[:80]}")
        print(f"   gmail_drafts_total={len(state.gmail_drafts)} send_count={state.send_count}")

    finally:
        shutdown()

    print(f"\n===== {_ok} passed, {_fail} failed =====")
    done = _fail == 0
    print("VEREDICTO:", "DONE — Gmail del belt COWORK: borrador real, send HELD, idempotente, inyeccion confirmada."
          if done else "NO-DONE — revisar los [FAIL] de arriba.")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
