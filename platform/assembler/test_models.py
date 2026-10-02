#!/usr/bin/env python3
"""test_models.py — la ABSTRACCIÓN DE MODELOS (T5). Determinista, SIN RED, cero mocks.

Prueba lo que el done-bar exige verificar de la capa de modelos:
  - "cambiar de modelo = 1 línea": precedencia env PUPPET_BRAIN > model.alias > primary/base_url;
  - BACK-COMPAT: una receta histórica (id directo) resuelve idéntica;
  - el alias 'brain' apunta al cerebro e2e con su fallback OSS;
  - precio MEDIDO×CONSTANTE; sin tarifa documentada → usd None (no se inventa).

Corre con:  python3 test_models.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import models  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[FAIL] {name} — {detail}")


# ── 1. alias 'brain' = cerebro e2e Opus, fallback OSS ──────────────────────────
r = models.resolve_recipe_model({"alias": "brain", "max_tokens": 512})
check("1.1 brain → Opus 4.8", r["primary"] == "anthropic/claude-opus-4.8", r["primary"])
check("1.2 brain → endpoint OpenRouter", "openrouter.ai" in r["base_url"], r["base_url"])
check("1.3 brain → key OPENROUTER_API_KEY", r["key_env"] == "OPENROUTER_API_KEY", str(r["key_env"]))
check("1.4 brain → fallback resuelto a id OSS concreto",
      r["fallback"] == "openai/gpt-oss-120b", str(r["fallback"]))
check("1.5 alias reportado", r["alias"] == "brain", str(r["alias"]))

# ── 2. BACK-COMPAT: receta histórica (id directo, sin alias) intacta ───────────
hist = {"primary": "openai/gpt-oss-120b", "fallback": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1"}
r2 = models.resolve_recipe_model(hist)
check("2.1 sin alias → primary intacto", r2["primary"] == "openai/gpt-oss-120b", r2["primary"])
check("2.2 sin alias → base_url intacto", r2["base_url"] == hist["base_url"], r2["base_url"])
check("2.3 sin alias → fallback intacto", r2["fallback"] == "llama-3.3-70b-versatile", str(r2["fallback"]))
check("2.4 sin alias → alias None", r2["alias"] is None, str(r2["alias"]))
check("2.5 key inferida del endpoint Groq", r2["key_env"] == "GROQ_API_KEY", str(r2["key_env"]))

# ── 3. PUPPET_BRAIN: producción respeta elección; desarrollo conserva palanca ──
os.environ["PUPPET_BRAIN"] = "oss"
try:
    os.environ["ALEPH_ROLE"] = "client"
    r3 = models.resolve_recipe_model(hist)
    check("3.1 cliente no pierde su selección", r3["alias"] is None and r3["override_blocked"], str(r3["alias"]))
    os.environ["ALEPH_ROLE"] = "dev"
    r3dev = models.resolve_recipe_model(hist)
    check("3.2 desarrollo aplica override declarado", r3dev["alias"] == "oss" and r3dev["override_used"]
          and r3dev["override_source"] == "PUPPET_BRAIN", str(r3dev["alias"]))
finally:
    del os.environ["PUPPET_BRAIN"]
    del os.environ["ALEPH_ROLE"]

# ── 4. precio: MEDIDO × CONSTANTE; sin tarifa → None (no se inventa) ───────────
p = models.price("openai/gpt-oss-120b", 1_000_000, 1_000_000)
check("4.1 gpt-oss-120b usd = 0.15 in + 0.60 out", p and abs(p["usd"] - 0.75) < 1e-9, str(p and p["usd"]))
check("4.2 desglose input correcto", p and abs(p["usd_input"] - 0.15) < 1e-9, str(p and p["usd_input"]))
check("4.3 trae fuente documentada", p and "groq.com" in p["source"], str(p and p.get("source")))
check("4.4 ollama local = $0", (models.price("qwen3:8b", 1000, 1000) or {}).get("usd") == 0.0)
check("4.5 Opus SIN tarifa documentada → None (no inventa)",
      models.price("anthropic/claude-opus-4.8", 1000, 500) is None)
check("4.6 modelo desconocido → None", models.price("foo/bar", 10, 10) is None)

# ── 5. resolución de un alias directo + id directo ────────────────────────────
check("5.1 resolve('oss') → gpt-oss-120b", models.resolve("oss").model == "openai/gpt-oss-120b")
check("5.2 resolve(id directo) back-compat",
      models.resolve("mi-modelo", base_url_hint="https://api.groq.com/openai/v1").model == "mi-modelo")

# ── 6. DEV SHIM SEAM (C6): PUPPET_BRAIN_SHIM=1 apunta el brain al shim local ────
# El seam se computa al IMPORTAR models, así que recargamos el módulo con la env puesta y
# después restauramos. SIN env el default ya quedó probado arriba (1.1–1.4 = contrato v1).
import importlib  # noqa: E402
os.environ["PUPPET_BRAIN_SHIM"] = "1"
try:
    importlib.reload(models)
    rs = models.resolve_recipe_model({"alias": "brain"})
    check("6.1 shim ON → brain.base_url = shim :8923", "127.0.0.1:8923" in rs["base_url"], rs["base_url"])
    check("6.2 shim ON → brain.primary es un id Opus (no anthropic/ de OpenRouter)",
          "opus" in rs["primary"].lower() and not rs["primary"].startswith("anthropic/"), rs["primary"])
    check("6.3 shim ON → sin key (localhost no necesita auth)", rs["key_env"] is None, str(rs["key_env"]))
    check("6.4 shim ON → fallback OSS intacto (red de seguridad debajo)",
          rs["fallback"] == "openai/gpt-oss-120b", str(rs["fallback"]))
finally:
    del os.environ["PUPPET_BRAIN_SHIM"]
    importlib.reload(models)  # restaurar el default congelado para el resto del proceso
# tras restaurar, el default vuelve a ser el contrato v1 (OpenRouter)
_restored = models.resolve_recipe_model({"alias": "brain"})
check("6.5 sin env (restaurado) → vuelve al contrato v1 OpenRouter",
      "openrouter.ai" in _restored["base_url"] and _restored["primary"] == "anthropic/claude-opus-4.8",
      f'{_restored["primary"]} @ {_restored["base_url"]}')

print(f"\n=== {_passed} passed, {_failed} failed ===")
sys.exit(1 if _failed else 0)
