"""E2E REAL del AUTO-ROUTE de visión (Bloque B) — runs reales contra Gemini + gpt-oss.

Sintetiza una imagen de CONTENIDO CONOCIDO (etiqueta de té de ginseng) y verifica:
  - Estándar (gpt-oss, text-only) + imagen → mode=interpret → la respuesta reporta el
    contenido REAL (ginseng / 20 / té), CERO confabulación.
  - Gemini activo + imagen → mode=raw → la ve directo y reporta lo real.
  - Sin modelo de visión (PUPPET_VISION_DISABLED=1) → mode=blind → mensaje HONESTO, NO
    menciona el contenido (no inventa).
No mockea nada: usa la llave real de infra/.env y el modelo real. Cero asunciones.
"""
import base64, io, os, tempfile, time
from pathlib import Path
import recipe_assembler as ra

REPO = str(Path(__file__).resolve().parents[2])
INLINE_BELT = "platform/assembler/fixtures/belt-calc.mcp.json"
GROQ = "https://api.groq.com/openai/v1"
GEM = "https://generativelanguage.googleapis.com/v1beta/openai"

# ── imagen de contenido CONOCIDO (la "caja de té de ginseng" del done-bar) ──────
def make_known_image():
    # ALTO CONTRASTE (negro sobre blanco, fuente grande) → OCR confiable para cualquier intérprete.
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (760, 460), (255, 255, 255))
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 72)
        mid = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 44)
    except Exception:
        big = ImageFont.load_default(); mid = ImageFont.load_default()
    d.text((50, 50), "GINSENG TEA", fill=(0, 0, 0), font=big)
    d.text((50, 170), "PRINCE OF PEACE", fill=(0, 0, 0), font=mid)
    d.text((50, 250), "INSTANT BEVERAGE", fill=(0, 0, 0), font=mid)
    d.text((50, 350), "20 TEA BAGS", fill=(0, 0, 0), font=big)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

IMG = make_known_image()
PROMPT = ("Leé la etiqueta de la imagen y transcribí TEXTUALMENTE qué dice: la marca, el "
          "producto y la cantidad. Empezá por el texto, sin describir colores ni bordes.")

def recipe(model_primary, base_url, fallback=None):
    m = {"primary": model_primary, "base_url": base_url, "temperature": 0.1,
         "max_tokens": 2048, "max_turns": 1}
    if fallback: m["fallback"] = fallback
    return {"schema_version": "v1",
            "meta": {"name": "chat", "nicho": "general", "output_type": "informe"},
            "model": m, "belt": {"belt_ref": INLINE_BELT, "tool_filters": {"calc": []}},
            "framing": {"inline": ""}, "rag": {"enabled": False}, "keys": {}, "gates": {}}

def run(label, rec, images, disabled=False):
    if disabled: os.environ["PUPPET_VISION_DISABLED"] = "1"
    else: os.environ.pop("PUPPET_VISION_DISABLED", None)
    wd = tempfile.mkdtemp(prefix="vtest_")
    out = ra.assemble_and_run(rec, PROMPT, repo_root=Path(REPO), images=images,
                              deadline_s=120, workdir=wd)
    os.environ.pop("PUPPET_VISION_DISABLED", None)
    ans = (out.get("answer") or "").strip()
    print(f"\n========== {label} ==========")
    print(f"  vision_mode = {out.get('vision')!r}   ok={out.get('ok')}   model_final={out.get('model_final')!r}")
    if out.get("error"): print(f"  ERROR: {out['error']}")
    print(f"  answer: {ans[:400]}")
    return out, ans.lower()

def mentions_real(a):
    return ("ginseng" in a) and ("20" in a or "bag" in a or "bolsit" in a or "sobre" in a or "té" in a or "tea" in a)

fails = []

print("cooldown inicial 50s (Gemini free-tier per-minute, para entrar con cuota fresca)...")
time.sleep(50)
# 1) Estándar (gpt-oss-120b text-only) + imagen → interpret, contenido REAL
o, a = run("1 · Estándar text-only + imagen (→ interpret)", recipe("openai/gpt-oss-120b", GROQ, "llama-3.3-70b-versatile"), [IMG])
if o.get("vision") != "interpret": fails.append("1: vision != interpret (fue %r)" % o.get("vision"))
if not mentions_real(a): fails.append("1: la respuesta NO reporta el contenido real (¿confabuló o vacío?)")

time.sleep(35)  # respetar el límite por-minuto de free-tier (la prueba es de robustez, no de carga)
# 2) Gemini activo + imagen → raw, contenido REAL
o, a = run("2 · Gemini activo + imagen (→ raw)", recipe("gemini-2.5-flash", GEM), [IMG])
if o.get("vision") != "raw": fails.append("2: vision != raw (fue %r)" % o.get("vision"))
if not mentions_real(a): fails.append("2: la respuesta NO reporta el contenido real")

# 3) Sin modelo de visión → blind honesto, SIN confabular (instantáneo, sin llamada a modelo)
o, a = run("3 · Sin visión (PUPPET_VISION_DISABLED) (→ blind honesto)", recipe("openai/gpt-oss-120b", GROQ), [IMG], disabled=True)
if o.get("vision") != "blind": fails.append("3: vision != blind (fue %r)" % o.get("vision"))
if "no puedo ver" not in a: fails.append("3: no devolvió el mensaje honesto")
if "ginseng" in a: fails.append("3: CONFABULÓ — mencionó ginseng sin ver la imagen!")

print("\n=========================================")
if fails:
    print("FALLOS:"); [print("  ✗", f) for f in fails]; raise SystemExit(1)
print("✅ TODOS LOS CASOS E2E PASARON — visión real, cero confabulación")
