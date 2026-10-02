#!/usr/bin/env python3
"""
prove_injection.py — VERIFICA el invariante construir≠inyectar (end-to-end, prod).

Cadena completa multi-usuario:
  login → connect alphavantage (key='demo', BYOK cifrada) → run con user_id
  → broker resuelve la key del user → assembler la inyecta al child_env →
  el server la lee → precio REAL de Alpha Vantage.

Control negativo: el MISMO run SIN user_id (anónimo) → sin byok_resolver →
la key NO se inyecta → el server reporta key_present=false. Así la bandera
key_present PRUEBA inyección real (no es siempre-true).
"""
import json, sys, urllib.request, urllib.error

BASE = "http://localhost:8080"
EMAIL = "tier4-byok-probe@demo.ai"


def _post(path, payload, token=None, timeout=120):
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": "err"}


RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "Finanzas BYOK probe", "nicho": "finanzas",
             "descripcion": "Consulta un precio de mercado con la key del usuario (BYOK)."},
    "model": {"primary": "openai/gpt-oss-120b", "fallback": "llama-3.3-70b-versatile",
              "base_url": "https://api.groq.com/openai/v1", "temperature": 0,
              "max_tokens": 512, "max_turns": 4},
    "belt": {"belt_ref": "platform/connectors/finanzas/belt-finanzas-data.mcp.json",
             "tool_filters": {"finanzas": ["alphavantage_quote"]}},
    "framing": {"inline": "Eres un analista. Para saber el precio de una acción llama alphavantage_quote "
                          "con el símbolo pedido. No inventes el precio."},
    "rag": {"enabled": False},
    "keys": {"alphavantage": {"byok_ref": "keys:alphavantage"}},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}
PROMPT = "¿Cuál es el precio actual de IBM?"


def _av_call(out):
    rec = out.get("record") or {}
    for t in rec.get("tool_calls", []):
        if t.get("tool") == "alphavantage_quote":
            res = t["result"]
            if isinstance(res, dict):
                return res
            s = str(res)
            # el registry antepone '[tool error] ' a los isError=True: parseá desde el primer '{'
            i = s.find("{")
            if i >= 0:
                try:
                    return json.loads(s[i:])
                except Exception:
                    pass
            return {"raw": s}
    return None


# 1) login
st, user = _post("/v1/auth/login", {"email": EMAIL, "display_name": "BYOK Probe"})
uid, tok = user["id"], user["session_token"]
print(f"[login] user_id={uid[:8]}… token={'sí' if tok else 'no'}")

# 2) connect alphavantage con key 'demo' (BYOK cifrada at-rest)
st, conn = _post("/v1/connectors/alphavantage/connect",
                 {"creds": {"key": "demo"}, "user_id": uid}, token=tok)
print(f"[connect] status={st} state={conn.get('state')} stored={conn.get('stored')}")

# 3) RUN con user_id → debe inyectar la key
st, with_user = _post("/v1/puppets/run", {"recipe": RECIPE, "prompt": PROMPT, "user_id": uid}, token=tok)
av1 = _av_call(with_user) or {}
print(f"\n[run CON user] ok={with_user.get('ok')} run_id={(with_user.get('run_id') or '')[:8]}…")
print(f"   alphavantage_quote: key_present={av1.get('key_present')} price={av1.get('price')} symbol={av1.get('symbol')}")
print(f"   provenance: {str(av1.get('provenance'))[:120]}")

# 4) CONTROL NEGATIVO: mismo run SIN user_id → sin byok_resolver → key NO inyectada
st, anon = _post("/v1/puppets/run", {"recipe": RECIPE, "prompt": PROMPT})
av2 = _av_call(anon) or {}
print(f"\n[run SIN user (control)] ok={anon.get('ok')}")
print(f"   alphavantage_quote: key_present={av2.get('key_present')} (esperado false) error={str(av2.get('error'))[:80]}")

# veredicto
injected = av1.get("key_present") is True and av1.get("price") is not None
control = av2.get("key_present") is False
print(f"\n=== VEREDICTO INVARIANTE construir≠inyectar ===")
print(f"  con BYOK → key llegó al server + precio real : {'✅' if injected else '❌'}")
print(f"  sin BYOK → key NO llegó (control negativo)    : {'✅' if control else '❌'}")
ok = injected and control
print(f"\n{'✅ VERDE — la credencial del usuario SE INYECTA de verdad al punto de uso' if ok else '❌ ROJO — la inyección no se comporta como debe'}")
sys.exit(0 if ok else 1)
