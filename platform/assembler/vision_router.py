"""
vision_router.py — AUTO-ROUTE transparente de imágenes (Puppet AI · Bloque B).

GARANTÍA: la imagen SIEMPRE llega a algo que la VE, y el agente NUNCA confabula
sobre una imagen que no puede ver.

Tres modos (los decide `route()`):
  raw       — el modelo ACTIVO ya es multimodal (Gemini / BYOK Claude·GPT-vision) →
              la imagen va RAW (image_url) a él; la ve directo.
  interpret — el modelo activo es text-only (gpt-oss Veloz/Estándar) → un modelo
              multimodal INTERPRETA la imagen y su descripción se INYECTA como texto;
              el agente sigue en SU modelo (no se lo reemplaza, no pierde su belt).
  blind     — no hay NINGÚN modelo de visión disponible → rechazo honesto; NO se manda
              la imagen al text-only, NO se inventa contenido.

Aislado en su propio módulo a propósito: Bloque B no toca classify_artifact_action ni
el versionado de obra (Bloque A). El call-site en recipe_assembler.assemble_and_run es
mínimo (una llamada a route() + ramas) → merge limpio con A.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── mensajes / prompts (texto de producto, español) ──────────────────────────
HONEST_BLIND_MESSAGE = (
    "No puedo ver imágenes en este momento — no hay un modelo de visión disponible. "
    "Activa Gemini (o conecta tu propio modelo con visión, como Claude o GPT) y vuelve a "
    "enviarme la imagen. No voy a adivinar qué contiene."
)

# Prompt de extracción: TRANSCRIPCIÓN PRIMERO (el contenido textual es lo que el agente
# text-only necesita para responir), luego una descripción breve. SOLO lo que REALMENTE se ve,
# sin interpretar intención ni inventar. La salida se inyecta como contexto del agente.
# (Lección: un prompt "describí todo lo que ves" hace que el modelo se vaya en colores/layout
#  y NO transcriba el texto; pedir la transcripción AL FRENTE y explícita lo arregla.)
VISION_EXTRACT_PROMPT = (
    "Tu tarea es EXTRAER el contenido de esta imagen para que alguien que NO la ve pueda "
    "trabajar con él.\n"
    "1) TRANSCRIBE, línea por línea y AL PIE DE LA LETRA, TODO el texto visible tal como "
    "está escrito (marcas, títulos, nombres, números, etiquetas, celdas de tablas). Si no "
    "hay texto, di 'sin texto'.\n"
    "2) Después, en pocas frases, describe qué ES la imagen y sus elementos visuales clave "
    "(objeto/foto/captura/gráfico; colores y disposición si son relevantes).\n"
    "Reporta SOLO lo que REALMENTE aparece. No interpretes intención, no resumas de memoria, "
    "no inventes datos ausentes. Si algo no se distingue, decilo."
)


def extract_images(images):
    """Quédate solo con data-URLs (el front manda data:image/...;base64,...)."""
    return [im for im in (images or []) if isinstance(im, str) and im.startswith("data:")]


# Patrones de modelos MULTIMODALES conocidos (ven imágenes nativamente). Conservador: lo
# DESCONOCIDO se trata como text-only (→ interpret), que es el camino SEGURO (grounded);
# nunca se manda RAW a un modelo que quizá no ve (riesgo de confabulación).
_MULTIMODAL_PATTERNS = (
    "gemini",
    "llama-4", "llama4", "scout", "maverick",
    "gpt-4o", "gpt-4.1", "gpt-4-vision", "gpt-4-turbo", "gpt-5", "chatgpt-4o",
    "o1", "o3", "o4-mini", "o4",
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    "pixtral", "qwen2.5-vl", "qwen2-vl", "qwen-vl", "qwen3-vl",
    "internvl", "llava", "grok-vision", "grok-2-vision", "grok-4",
)
# text-only EXPLÍCITO (gana sobre cualquier match accidental de arriba): la cognición incluida.
_TEXT_ONLY_PATTERNS = ("gpt-oss",)


def is_multimodal_model(primary, base_url=""):
    """¿El modelo activo VE imágenes? El endpoint de Gemini = sí por definición; si no, por nombre."""
    p = (primary or "").lower()
    if "generativelanguage.googleapis.com" in (base_url or "").lower():
        return True
    for t in _TEXT_ONLY_PATTERNS:
        if t in p:
            return False
    for t in _MULTIMODAL_PATTERNS:
        if t in p:
            return True
    return False


def _read_env_var(env_path, var):
    """Lee VAR=valor de un .env SIN imprimir el valor (standalone, no importa el assembler)."""
    try:
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def vision_disabled():
    """Simulación honesta de 'no hay modelo de visión' (para VERIFICAR el fallback B2 en vivo).
    PUPPET_VISION_DISABLED=1 → route() devuelve blind aunque existan las llaves."""
    return os.environ.get("PUPPET_VISION_DISABLED", "") not in ("", "0", "false", "False")


def vision_providers(repo_root, *, cognition_key="", cognition_base_url=""):
    """Lista ORDENADA de intérpretes multimodales DISPONIBLES (preferencia → fallback):
       1) Gemini 2.5 Flash — si GEMINI_API_KEY está en infra/.env (modelo de visión más fuerte).
       2) Groq Llama-4 Scout — si la cognición incluida es Groq (misma key, MÁS confiable ante
          el 429 de free-tier de Gemini → la interpretación no colapsa a 'blind' por un rate-limit).
       Lista vacía = no hay NINGÚN modelo de visión → blind honesto."""
    if vision_disabled():
        return []
    provs = []
    infra = Path(repo_root) / "infra" / ".env"
    gkey = _read_env_var(infra, "GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    if gkey:
        provs.append({
            "primary": (_read_env_var(infra, "GEMINI_VISION_MODEL")
                        or os.environ.get("GEMINI_VISION_MODEL", "") or "gemini-2.5-flash"),
            "base_url": (_read_env_var(infra, "GEMINI_API_BASE")
                         or os.environ.get("GEMINI_API_BASE", "")
                         or "https://generativelanguage.googleapis.com/v1beta/openai"),
            "key": gkey,
            "label": "Gemini 2.5 Flash",
        })
    if cognition_key and "groq.com" in (cognition_base_url or "").lower():
        provs.append({
            "primary": (os.environ.get("GROQ_VISION_MODEL", "")
                        or "meta-llama/llama-4-scout-17b-16e-instruct"),
            "base_url": cognition_base_url or "https://api.groq.com/openai/v1",
            "key": cognition_key,
            "label": "Llama-4 Scout",
        })
    return provs


def route(*, primary, base_url, images, repo_root, cognition_key="", cognition_base_url=""):
    """Decide CÓMO manejar un turno con imágenes. Devuelve un dict con 'mode':
       'text' (sin imágenes) | 'raw' | 'interpret' (con 'providers') | 'blind' (con 'message')."""
    imgs = extract_images(images)
    if not imgs:
        return {"mode": "text", "images": []}
    if is_multimodal_model(primary, base_url):
        return {"mode": "raw", "images": imgs}
    provs = vision_providers(
        repo_root, cognition_key=cognition_key, cognition_base_url=cognition_base_url)
    if not provs:
        return {"mode": "blind", "images": imgs, "message": HONEST_BLIND_MESSAGE}
    return {"mode": "interpret", "images": imgs, "providers": provs}


def describe_images(images, providers, chat_fn, *, max_tokens=1536, on_usage=None):
    """Interpreta las imágenes probando los `providers` EN ORDEN hasta que uno responda no-vacío
    (Gemini 429 → Scout). Devuelve (texto, label_usado) o ("", None) si TODOS fallan → blind.
    `chat_fn` = el primitivo _chat del assembler (mismo path HTTP/timeout/errores).

    `on_usage(model, usage)` — callback OPCIONAL que se dispara con el modelo REAL y el
    `usage` del intérprete que respondió, para que el caller emita un cost-event. Esta
    llamada GASTA una key propia (Gemini/BYOK), aparte del cerebro: sin esto, en un run con
    cerebro BYO-CLI ('$0 por suscripción') el gasto de visión quedaba INVISIBLE en el ledger
    (review #18). El retorno se mantiene byte-idéntico (2-tupla) — la visibilidad va por el hook."""
    content = [{"type": "text", "text": VISION_EXTRACT_PROMPT}] + [
        {"type": "image_url", "image_url": {"url": im}} for im in images
    ]
    msgs = [{"role": "user", "content": content}]
    for prov in (providers or []):
        try:
            resp = chat_fn(msgs, [], prov["base_url"], prov["primary"],
                           prov["key"], max_tokens, 0)
            txt = (resp["choices"][0]["message"]["content"] or "").strip()
            if txt:
                if on_usage:
                    try:
                        on_usage(prov["primary"], resp.get("usage") or {})
                    except Exception:
                        pass   # la contabilidad jamás rompe la respuesta de visión
                return txt, prov["label"]
        except Exception:
            continue   # este intérprete falló (429/transporte) → probá el siguiente
    return "", None


def injected_context(description, *, label="un modelo de visión"):
    """Texto que se INYECTA en el turno del agente con lo que el modelo de visión VIO.
    El agente text-only responde sobre contenido REAL, nunca sobre una imagen que no recibió."""
    body = description.strip() if description else "(no se pudo leer contenido de la imagen)"
    return (
        "[CONTENIDO DE LA(S) IMAGEN(ES) ADJUNTA(S), interpretado por " + label + ". "
        "Esto es lo que REALMENTE se ve; responde basándote SOLO en esto y no inventes "
        "nada que no figure aquí:]\n" + body
    )
