"""Unit tests RÁPIDOS y deterministas del AUTO-ROUTE de visión (Bloque B) — sin red.

Cubren la LÓGICA pura: detección multimodal, los tres modos de route(), el orden de la
cadena de proveedores, y el fallback de describe_images (Gemini falla → Scout) con un
chat_fn falso. El flujo REAL (modelos de verdad, cero mocks) lo cubre test_vision_route_e2e.py.

Corré:  python3 test_vision_router.py
"""
import os
from unittest.mock import patch
from pathlib import Path
import vision_router as v

GROQ = "https://api.groq.com/openai/v1"
GEM = "https://generativelanguage.googleapis.com/v1beta/openai"
REPO = Path(__file__).resolve().parents[2]
IMG = ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="]


def test_is_multimodal():
    mm = [("gemini-2.5-flash", GEM), ("meta-llama/llama-4-scout-17b-16e-instruct", GROQ),
          ("claude-opus-4-8", ""), ("claude-3-5-sonnet", ""), ("gpt-4o", ""),
          ("anything", GEM)]  # endpoint Gemini = multimodal por definición
    txt = [("openai/gpt-oss-120b", GROQ), ("openai/gpt-oss-20b", GROQ),
           ("llama-3.3-70b-versatile", GROQ), ("deepseek-chat", GROQ), ("unknown-model", "")]
    for m, b in mm:
        assert v.is_multimodal_model(m, b) is True, ("debe ser multimodal", m, b)
    for m, b in txt:
        assert v.is_multimodal_model(m, b) is False, ("debe ser text-only", m, b)
    print("  ✓ is_multimodal_model: multimodal vs text-only")


def test_route_modes():
    os.environ.pop("PUPPET_VISION_DISABLED", None)
    # sin imágenes → text
    assert v.route(primary="openai/gpt-oss-120b", base_url=GROQ, images=[], repo_root=REPO)["mode"] == "text"
    # modelo activo multimodal → raw
    assert v.route(primary="gemini-2.5-flash", base_url=GEM, images=IMG, repo_root=REPO)["mode"] == "raw"
    # text-only + cognición Groq, SIN gemini (repo_root sin infra/.env) → interpret vía Scout
    r = v.route(primary="openai/gpt-oss-120b", base_url=GROQ, images=IMG, repo_root=Path("/tmp"),
                cognition_key="k", cognition_base_url=GROQ)
    assert r["mode"] == "interpret" and r["providers"][0]["label"] == "Llama-4 Scout"
    # text-only + NINGÚN proveedor → blind honesto
    r = v.route(primary="openai/gpt-oss-120b", base_url=GROQ, images=IMG, repo_root=Path("/tmp"),
                cognition_key="", cognition_base_url="")
    assert r["mode"] == "blind" and "No puedo ver" in r["message"]
    print("  ✓ route(): text / raw / interpret / blind")


def test_vision_disabled_forces_blind():
    os.environ["PUPPET_VISION_DISABLED"] = "1"
    try:
        r = v.route(primary="openai/gpt-oss-120b", base_url=GROQ, images=IMG, repo_root=REPO,
                    cognition_key="k", cognition_base_url=GROQ)
        assert r["mode"] == "blind", "PUPPET_VISION_DISABLED debe forzar blind aunque haya llaves"
    finally:
        os.environ.pop("PUPPET_VISION_DISABLED", None)
    print("  ✓ PUPPET_VISION_DISABLED=1 → blind (simulación B2)")


def test_provider_chain_order():
    # Synthetic local configuration; never requires a developer's infra/.env.
    with patch.object(v, "_read_env_var", return_value=""), patch.dict(
            os.environ, {"GEMINI_API_KEY": "TEST_ONLY_FAKE"}, clear=True):
        provs = v.vision_providers(REPO, cognition_key="k", cognition_base_url=GROQ)
    labels = [p["label"] for p in provs]
    assert labels and labels[0] == "Gemini 2.5 Flash", ("Gemini debe ir primero", labels)
    assert "Llama-4 Scout" in labels, ("Scout debe estar como fallback", labels)
    print("  ✓ vision_providers(): orden Gemini → Scout")


def test_describe_fallback_gemini_to_scout():
    # chat_fn falso: el PRIMER proveedor (Gemini) tira 429; el SEGUNDO (Scout) responde.
    calls = []
    def fake_chat(msgs, tools, base_url, model, key, max_tokens, temp):
        calls.append(model)
        if "gemini" in model.lower():
            raise RuntimeError("HTTP 429: rate limited")
        return {"choices": [{"message": {"content": "GINSENG TEA 20 BAGS"}}]}
    provs = [{"primary": "gemini-2.5-flash", "base_url": GEM, "key": "x", "label": "Gemini 2.5 Flash"},
             {"primary": "meta-llama/llama-4-scout-17b-16e-instruct", "base_url": GROQ, "key": "y", "label": "Llama-4 Scout"}]
    txt, used = v.describe_images(IMG, provs, fake_chat)
    assert txt == "GINSENG TEA 20 BAGS" and used == "Llama-4 Scout", (txt, used)
    assert len(calls) == 2, "debe intentar Gemini y luego Scout"
    print("  ✓ describe_images(): Gemini 429 → cae a Scout (no a blind)")


def test_describe_all_fail_returns_empty():
    def fake_chat(*a, **k):
        raise RuntimeError("HTTP 500")
    provs = [{"primary": "gemini-2.5-flash", "base_url": GEM, "key": "x", "label": "G"}]
    txt, used = v.describe_images(IMG, provs, fake_chat)
    assert txt == "" and used is None, "todos fallan → ('', None) → el caller cae a blind"
    print("  ✓ describe_images(): todos fallan → vacío (→ blind, no confabula)")


def test_describe_surfaces_usage_for_cost():
    # review #18: el gasto de VISIÓN (key propia, aparte del cerebro) DEBE surfacearse — clave
    # en un run BYO-CLI ('$0 por suscripción'), donde sería el único gasto real. El hook on_usage
    # dispara con el modelo REAL + usage del intérprete que respondió; el retorno sigue 2-tupla.
    seen = []
    def fake_chat(msgs, tools, base_url, model, key, max_tokens, temp):
        return {"choices": [{"message": {"content": "MATE 500G"}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 40}}
    provs = [{"primary": "gemini-2.5-flash", "base_url": GEM, "key": "x", "label": "Gemini 2.5 Flash"}]
    txt, used = v.describe_images(IMG, provs, fake_chat, on_usage=lambda m, u: seen.append((m, u)))
    assert (txt, used) == ("MATE 500G", "Gemini 2.5 Flash"), "retorno byte-idéntico (2-tupla)"
    assert len(seen) == 1 and seen[0][0] == "gemini-2.5-flash", ("on_usage debe traer el modelo real", seen)
    assert seen[0][1].get("prompt_tokens") == 900, ("on_usage debe traer el usage real p/ el ledger", seen)
    print("  ✓ describe_images(): on_usage surfacea el gasto de visión (ledger completo, #18)")


def test_injected_context_grounds():
    ctx = v.injected_context("GINSENG TEA · 20 BAGS", label="Gemini 2.5 Flash")
    assert "GINSENG" in ctx and "SOLO" in ctx and "no inventes" in ctx
    print("  ✓ injected_context(): instruye al agente a NO inventar")


if __name__ == "__main__":
    for fn in [test_is_multimodal, test_route_modes, test_vision_disabled_forces_blind,
               test_provider_chain_order, test_describe_fallback_gemini_to_scout,
               test_describe_all_fail_returns_empty, test_describe_surfaces_usage_for_cost,
               test_injected_context_grounds]:
        fn()
    print("\n✅ TODOS LOS UNIT TESTS DE vision_router PASARON (rápidos, sin red)")
