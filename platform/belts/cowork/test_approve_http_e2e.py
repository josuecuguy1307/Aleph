#!/usr/bin/env python3
"""
test_approve_http_e2e.py — SPEC EJECUTABLE del approve-by-HTTP (deuda #1 post-Fase-4).

Caso de prueba: cowork-gmail (el PRIMER belt que MANDA algo → caso ideal del send-gate).
Este archivo es NUEVO y AISLADO: **no toca el router ni las recetas**. Hoy todavía no pasa
entero — es la spec que define el contrato del paso 2; cuando ese código aterrice, va verde.

POR QUÉ EXISTE (lo que mi test 15/15 NO prueba):
  test_cowork_gmail_e2e.py inyecta la credencial con un `_byok_resolver` CUSTOM que SALTEA el
  broker. Por el router real, la credencial sale del CREDENTIAL-BROKER ligado al user_id
  (keys cifradas en Postgres). Esta prueba corre por el router REAL (TestClient in-process)
  con el broker REAL — y exige el invariante `construir≠inyectar` en esa capa.

EVIDENCE GATE (lo no-negociable, en orden):
  1. Run cowork-gmail por :8080 con un user con credencial conectada (broker real) →
     el agente deja el BORRADOR y propone el envío → **el gate SOSTIENE** (HELD): el correo
     NO sale (`stub.send_count == 0`), aunque la receta ponga `gates.send="off"` (invariante).
  2. La acción retenida se PERSISTE y se RECUPERA (no se pierde al terminar el run).
  3. El usuario APRUEBA por HTTP → la acción retenida se DISPARA: `send_email` se ejecuta de
     verdad SOLO tras el OK (`send_count` 0→1). RECHAZAR la deja en 0.

CONTRATO OBJETIVO (lo implemento en el paso 2; hoy puede no existir → la prueba lo reporta):
  - `POST /v1/puppets/run` que retiene un send devuelve, además del record, una lista
    `held_actions: [{approval_id, server, tool, args|preview, gate_ux}]` y persiste cada una
    ligada al run_id (recuperable).
  - `POST /v1/runs/{run_id}/approve`  body `{approval_id, ok: bool}` →
        ok=true  → ejecuta la acción retenida (corre send_email) → 200 {executed:true,...}
        ok=false → la descarta → 200 {executed:false,...}; el correo NUNCA sale.
  - El invariante §3.5 se mantiene: el gate fuerza el send aunque la receta lo apague; el
    único camino a ejecutar es el OK explícito por HTTP.

Estado de hoy (sin el paso 2): el router corre el run sincrónico y un send needs_ok NO se
ejecuta ni se expone para aprobar → esta prueba marca PARCIAL (paso 1 verde, pasos 2-3
BLOQUEADOS-pendientes-de-implementar) en vez de fallar a ciegas.

Uso:  python3 platform/belts/cowork/test_approve_http_e2e.py
Exit: 0 = evidence gate completo (paso 2 ya implementado) · 2 = BLOQUEADO (falta algo, con
       el motivo exacto) · 1 = un assert que SÍ deberia pasar hoy falló (regresión real).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[2]
_BACKEND = _REPO / "product" / "backend"
sys.path.insert(0, str(_THIS / "fixtures"))
sys.path.insert(0, str(_BACKEND))  # para `import app.main` / `app.phase1.*`

import gmail_stub as stub  # noqa: E402

DUMMY_GMAIL = "ya29.DUMMY_oauth_approve_http_no_es_token_real"
TOY_EMAIL = "cowork-approve-test@toy.local"
APPROVE_PATH = "/v1/runs/{run_id}/approve"  # CONTRATO OBJETIVO (paso 2)
RUN_PATH = "/v1/puppets/run"

_ok = 0
_fail = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    global _ok, _fail
    print(("[PASS]" if cond else "[FAIL]") + f" {label}" + (f" — {detail}" if detail else ""))
    if cond:
        _ok += 1
    else:
        _fail += 1
    return cond


def blocked(msg: str) -> int:
    print(f"\n[BLOQUEADO] {msg}")
    print("=> La spec quedó escrita y aislada. Corré de nuevo cuando aterrice lo pendiente.")
    return 2


def _send_permitting_recipe() -> dict:
    """Receta INLINE (no toca el archivo de prod): framing que PERMITE mandar — para que el
    agente PROPONGA send_email y el gate tenga algo que retener. gates.send='off' a PROPOSITO:
    el enforcer debe forzar el gate IGUAL (invariante §3.5)."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Cowork Gmail (approve-by-HTTP spec)", "nicho": "cowork",
                 "descripcion": "Caso de prueba del send-gate: dejar borrador y MANDAR (gateado)."},
        "model": {"primary": "openai/gpt-oss-120b", "fallback": "llama-3.3-70b-versatile",
                  "base_url": "https://api.groq.com/openai/v1", "temperature": 0,
                  "max_tokens": 1024, "max_turns": 8},
        "belt": {"belt_ref": "catalog/templates/cowork/belt-cowork-gmail.mcp.json",
                 "tool_filters": {"gmail": ["create_draft", "send_email"]}},
        "framing": {"inline": (
            "Sos un asistente de oficina. Para correo: primero create_draft para dejar el "
            "borrador y LUEGO send_email para mandarlo al destinatario. Usá las herramientas "
            "cableadas. Cuando termines, deci en una frase que hiciste."
        )},
        "rag": {"enabled": False},
        "keys": {"gmail": {"byok_ref": "keys:gmail"}},
        "gates": {"money_touch": "off", "send": "off"},  # ← apagado a proposito (invariante)
    }


def main() -> int:
    state, base_url, shutdown = stub.start_stub(DUMMY_GMAIL)
    os.environ["GMAIL_API_BASE"] = base_url  # el subprocess del belt hereda os.environ (in-process)

    try:
        # ── import guardado del app real + TestClient (no toca el router; solo lo ejercita) ──
        try:
            from fastapi.testclient import TestClient
            from app.main import app
            from app.phase1 import repo, credential_broker
        except Exception as exc:  # noqa: BLE001
            return blocked(f"app/TestClient no importable en este entorno: {exc}")

        # ── setup: user de juguete + credencial Gmail por el BROKER REAL (cifrada at-rest) ──
        try:
            conn = repo.get_conn()
            user = repo.get_or_create_user(conn, TOY_EMAIL, "Cowork Approve Test")
            uid = user["id"]
            repo.upsert_key(conn, user_id=uid, provider="gmail", secret=DUMMY_GMAIL)
            conn.close()
            session_token = repo.mint_session(uid)
        except Exception as exc:  # noqa: BLE001
            return blocked(f"no pude preparar user+key en Postgres (DB?): {exc}")

        # construir≠inyectar EN LA CAPA DEL BROKER: el resolver real del router resuelve la
        # credencial cifrada de ESTE user (no el atajo del assembler).
        resolver = credential_broker.make_user_resolver(uid)
        check(resolver("keys:gmail") == DUMMY_GMAIL,
              "BROKER REAL resuelve keys:gmail del user (construir≠inyectar en la capa del router)")

        client = TestClient(app)
        auth = {"Authorization": f"Bearer {session_token}"}

        # ── PASO 1 — RUN por el router real: el gate SOSTIENE (HELD), correo NO sale ──────
        print("\n===== PASO 1 — run por el router real: send HELD =====")
        body = {"recipe": _send_permitting_recipe(),
                "prompt": "Prepara un borrador para 'jefe@ejemplo.com' (asunto 'Resumen', cuerpo breve) y mandalo.",
                "user_id": uid}
        r = client.post(RUN_PATH, json=body, headers=auth)
        if r.status_code == 422:
            return blocked(f"la receta no valida por el router (keys-fix de Terminal 1 aun no aterrizo?): {r.text[:300]}")
        if r.status_code not in (200, 201):
            return blocked(f"{RUN_PATH} devolvio {r.status_code}: {r.text[:300]}")
        out = r.json()
        record = out.get("record", out)
        run_id = out.get("run_id") or record.get("run_id")
        tool_calls = record.get("tool_calls", [])
        send_decisions = [t for t in tool_calls if t.get("tool") == "send_email"]

        check(bool(out.get("gate_enforced") or record.get("gate_enforced")),
              "gate_enforced=True por el router real")
        proposed_send = bool(send_decisions)
        check(proposed_send,
              "el agente PROPUSO send_email (hay algo para retener/aprobar)",
              "si no, re-correr (modelo no propuso envio)")
        if proposed_send:
            check(all(t.get("gate_action") == "needs_ok" for t in send_decisions),
                  "send_email retenido por el gate (needs_ok) aunque gates.send='off' (INVARIANTE §3.5)")
        check(state.send_count == 0,
              "HELD: el correo NO salio (/messages/send intacto)", f"send_count={state.send_count}")
        check(len(state.gmail_drafts) >= 1, "el BORRADOR existe (create_draft ejecuto)",
              f"drafts={len(state.gmail_drafts)}")

        # ── PASO 2/3 — APPROVE-BY-HTTP: el OK dispara la accion retenida ─────────────────
        print("\n===== PASO 2/3 — approve por HTTP: el OK ejecuta la accion retenida =====")
        held = out.get("held_actions") or record.get("held_actions")
        if not held:
            print("\n[BLOQUEADO] el run NO expone `held_actions` para aprobar.")
            print("   → Hoy el router corre sincrónico y un send needs_ok NO se persiste ni se")
            print("     expone. ESO es el paso 2 (MI trabajo, tras confirmar Terminal 1):")
            print("     (a) persistir la accion retenida ligada al run_id y exponerla en la respuesta;")
            print("     (b) POST /v1/runs/{run_id}/approve {approval_id, ok} que la ejecuta/descarta;")
            print("     (c) re-correr esta misma spec → debe quedar verde (send 0→1 solo tras OK).")
            print(f"\n   PASO 1 (HELD por el router real) = {'VERDE' if _fail == 0 else 'con fallas'}; "
                  f"PASOS 2-3 = pendientes de implementar.")
            return 2 if _fail == 0 else 1

        # Si el contrato ya existe: probar OK ejecuta + reject NO ejecuta.
        approval_id = held[0].get("approval_id")
        ra = client.post(APPROVE_PATH.format(run_id=run_id), json={"approval_id": approval_id, "ok": True}, headers=auth)
        check(ra.status_code == 200, "POST approve {ok:true} → 200", f"status={ra.status_code}")
        check(state.send_count == 1,
              "EVIDENCIA: el correo se mando SOLO tras el OK (send_count 0→1)", f"send_count={state.send_count}")

        # segundo run → RECHAZAR → no debe mandar
        r2 = client.post(RUN_PATH, json=body, headers=auth)
        out2 = r2.json()
        held2 = out2.get("held_actions") or (out2.get("record", {}) or {}).get("held_actions") or []
        if held2:
            rid2 = out2.get("run_id")
            rj = client.post(APPROVE_PATH.format(run_id=rid2),
                             json={"approval_id": held2[0].get("approval_id"), "ok": False}, headers=auth)
            check(rj.status_code == 200, "POST approve {ok:false} → 200", f"status={rj.status_code}")
            check(state.send_count == 1,
                  "EVIDENCIA: rechazar NO manda (send_count se queda en 1)", f"send_count={state.send_count}")

    finally:
        shutdown()

    print(f"\n===== {_ok} passed, {_fail} failed =====")
    done = _fail == 0
    print("VEREDICTO:", "DONE — approve-by-HTTP cierra: HELD por el router real, OK ejecuta, reject no."
          if done else "NO-DONE — revisar los [FAIL].")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
