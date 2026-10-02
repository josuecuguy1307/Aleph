#!/usr/bin/env python3
"""verify_puente_imagenes.py — LA IMAGEN VIAJA COMO IMAGEN, NO COMO TEXTO.

EL BUG QUE MIDE. Un mensaje multimodal caía en `f"[Usuario]: {content}"` y se rendía con
`str(list)`: el data-URL entero pegado COMO TEXTO LITERAL en el prompt. El modelo no veía
nada, se pagaba el contexto igual, y `cli.claude_cli` no declaraba `vision` — con razón,
porque el puente no transportaba imágenes.

LAS TRES CAPAS, y hacen falta las tres. Una sola verde no prueba nada de las otras:

  A · EL RENDER      el base64 sale del texto y deja una MARCA; las imágenes vuelven aparte
  B · EL SPAWN       el argv cambia a `--input-format stream-json` y el stdin lleva bloques
                     `image` nativos — y el base64 NO está en la línea de comandos
  C · EL BINARIO     `claude` de verdad, con el argv de PRODUCCIÓN, MIRA la imagen y la nombra

La capa C es la única que prueba que esto sirve; las A y B dicen POR QUÉ sirve. Si el
binario no está o no hay sesión, C sale NO MEDIBLE y la vara lo dice — no verde.

CÓMO CAE. Cada bloque trae su prueba de caída al lado, contra la implementación VIEJA.
"""
import base64
import json
import os
import struct
import subprocess
import sys
import zlib

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.join(_AQUI, "..")
sys.path.insert(0, os.path.join(_RAIZ, "platform", "assembler"))

from cli_brain import prompt_bridge as PB                                  # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider                         # noqa: E402
from cli_brain.registry import SPECS                                       # noqa: E402

_OK = _MAL = 0
_NOMED = []


def ok(cond, desc, extra=""):
    global _OK, _MAL
    if cond:
        _OK += 1
        print(f"  🟢 {desc}")
    else:
        _MAL += 1
        print(f"  🔴 {desc}" + (f"   {extra}" if extra else ""))


def nomedible(desc, porque):
    _NOMED.append(desc)
    print(f"  ⚪ {desc} — NO MEDIBLE: {porque}")


# ── el material: un PNG magenta sólido, chico y sin ambigüedad ────────────────────────
def _png_solido(rgb=(255, 0, 255), lado=120) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * lado for _ in range(lado))

    def _chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw))
            + _chunk(b"IEND", b""))


PNG_B64 = base64.b64encode(_png_solido()).decode()
DATA_URL = "data:image/png;base64," + PNG_B64
PREGUNTA = "¿De qué color es el cuadrado de la imagen? Respondé SOLO con una palabra."
MSGS = [{"role": "user", "content": [{"type": "text", "text": PREGUNTA},
                                     {"type": "image_url", "image_url": {"url": DATA_URL}}]}]

print("EL PUENTE Y LA VERIFICACIÓN VISUAL\n")
print("── A · EL RENDER: el base64 sale del texto ──")
prompt, imgs = PB.render_con_imagenes(MSGS, [], None)
ok(PNG_B64 not in prompt, "A1 · el base64 NO está en el prompt (era el bug entero)",
   f"{len(prompt)} chars de prompt")
ok(len(imgs) == 1 and imgs[0]["data"] == PNG_B64 and imgs[0]["media_type"] == "image/png",
   "A2 · la imagen vuelve APARTE, entera y con su media_type", str(imgs)[:120])
ok("⟦imagen 1⟧" in prompt, "A3 · y deja una marca numerada donde estaba", prompt[:200])
ok(PREGUNTA in prompt, "A4 · el texto que la acompañaba sigue ahí")

# los tres dialectos que llegan de verdad al :8926
_anthr = [{"role": "user", "content": [{"type": "image", "source": {
    "type": "base64", "media_type": "image/jpeg", "data": "QQ=="}}]}]
_resp = [{"role": "user", "content": [{"type": "input_image", "image_url": DATA_URL}]}]
ok(PB.extraer_imagenes(_anthr) == [{"media_type": "image/jpeg", "data": "QQ=="}],
   "A5 · el dialecto Anthropic nativo también se reconoce", str(PB.extraer_imagenes(_anthr)))
ok(len(PB.extraer_imagenes(_resp)) == 1, "A6 · …y el de responses (`input_image`)")

# el caso que hace que esto sirva para Diseño: la captura vuelve en un RESULTADO DE TOOL
_tool = [{"role": "tool", "tool_call_id": "c1", "name": "preview",
          "content": [{"type": "text", "text": "render listo"},
                      {"type": "image_url", "image_url": {"url": DATA_URL}}]}]
ok(len(PB.extraer_imagenes(_tool)) == 1,
   "A7 · la imagen que vuelve en un RESULTADO DE TOOL también viaja (es el caso de Diseño)")

# dos imágenes: la marca y el orden tienen que ser la misma cosa
_dos = [{"role": "user", "content": [
    {"type": "text", "text": "antes "}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    {"type": "text", "text": " después "}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBB"}}]}]
_p2, _i2 = PB.render_con_imagenes(_dos, [], None)
ok(_p2.index("⟦imagen 1⟧") < _p2.index("⟦imagen 2⟧") and [x["data"] for x in _i2] == ["AAA", "BBB"],
   "A8 · con varias, la marca N y la imagen N son la misma", f"{_p2!r} {_i2}")

# lo que NO viaja, y se dice
_url = [{"role": "user", "content": [{"type": "image_url",
                                      "image_url": {"url": "https://ejemplo/x.png"}}]}]
_pu, _iu = PB.render_con_imagenes(_url, [], None)
ok(_iu == [] and "https://ejemplo/x.png" in _pu,
   "A9 · una imagen por URL remota NO se descarga acá: se rinde como su URL y no cuenta", _pu[:160])

# la cola incremental adjunta SÓLO lo suyo
_cola_p, _cola_i = PB.render_incremental_con_imagenes(MSGS, [], None)
ok(len(_cola_i) == 1 and PNG_B64 not in _cola_p,
   "A10 · el render INCREMENTAL hace lo mismo (era el otro f-string con el mismo bug)")

print("  ── prueba de caída de A: la implementación vieja ──")
_viejo = f"[Usuario]: {MSGS[0]['content']}"
ok(PNG_B64 in _viejo, "A0 · el render viejo SÍ pegaba el base64 → A1 daría rojo con él",
   "si esto no da verde, la vara no está midiendo el bug")

print("\n── B · EL SPAWN: el argv y el stdin ──")
P = ClaudeCliProvider()
ok(P.soporta_imagenes() is True, "B1 · el provider DECLARA que transporta imágenes")
argv = P.build_argv("claude", prompt, "opus", "/tmp/x", stream=True, imagenes=imgs)
ok("--input-format" in argv and argv[argv.index("--input-format") + 1] == "stream-json",
   "B2 · con imágenes el argv pide `--input-format stream-json`", " ".join(argv[:8]))
ok(argv[argv.index("-p") + 1].startswith("--"),
   "B3 · `-p` queda SIN posicional: el prompt se fue a stdin", " ".join(argv[:6]))
ok(not any(PNG_B64 in a for a in argv),
   "B4 · el base64 NO está en la línea de comandos (ni el prompt entero)")
ok("--output-format" in argv and argv[argv.index("--output-format") + 1] == "stream-json",
   "B5 · y el formato de salida es el que ese modo EXIGE")

crudo = P.build_argv("claude", "hola", "opus", "/tmp/x", stream=True)
ok(crudo[1] == "-p" and crudo[2] == "hola" and "--input-format" not in crudo,
   "B6 · SIN imágenes el argv queda byte-idéntico al de siempre", " ".join(crudo[:6]))
ok(P.build_stdin("hola", []) is None, "B7 · …y no se abre stdin")

payload = P.build_stdin(prompt, imgs)
linea = json.loads(payload.decode("utf-8").strip())
bloques = linea["message"]["content"]
ok(linea["type"] == "user" and linea["message"]["role"] == "user",
   "B8 · el stdin es UN mensaje `user` en una línea JSON")
ok(bloques[0]["type"] == "text" and PREGUNTA in bloques[0]["text"],
   "B9 · el texto va primero, con la marca adentro")
ok(len(bloques) == 2 and bloques[1]["type"] == "image"
   and bloques[1]["source"]["data"] == PNG_B64
   and bloques[1]["source"]["media_type"] == "image/png",
   "B10 · y la imagen va como bloque `image` nativo, no como texto", str(bloques[1])[:120])

_spec = {s.provider_id: s for s in SPECS}
ok("vision" in _spec["claude_cli"].capabilities,
   "B11 · la fila de `claude_cli` DECLARA vision — la declaración SIGUE al transporte")
ok("vision" not in _spec["codex_cli"].capabilities
   and "vision" not in _spec["grok_cli"].capabilities,
   "B12 · …y los dos puentes que son de sólo texto NO la declaran (fail-closed)")

_codex_ok = True
try:
    from cli_brain.codex_cli import CodexCliProvider
    _codex_ok = CodexCliProvider().soporta_imagenes() is False
except Exception as e:                                                     # noqa: BLE001
    _codex_ok = False
ok(_codex_ok, "B13 · y el default del gancho es NO transportar (nadie lo hereda por error)")

print("\n── C · EL BINARIO: `claude` mira la imagen ──")
_bin = P.binary()
if not _bin:
    nomedible("C1 · el modelo nombra el color de la imagen", "no hay binario `claude` acá")
elif os.environ.get("ALEPH_VARA_SIN_RED"):
    nomedible("C1 · el modelo nombra el color de la imagen", "ALEPH_VARA_SIN_RED")
else:
    est = P.detect()
    if est.state != "ready":
        nomedible("C1 · el modelo nombra el color de la imagen",
                  f"el CLI no está listo ({est.state}: {est.detail})")
    else:
        import tempfile
        wd = tempfile.mkdtemp(prefix="vara-imagenes-")
        av = P.build_argv(_bin, prompt, "sonnet", wd, stream=True, imagenes=imgs)
        r = subprocess.run(av, cwd=wd, input=P.build_stdin(prompt, imgs),
                           capture_output=True, timeout=180)
        salida = (r.stdout or b"").decode("utf-8", "replace")
        dicho = ""
        for ln in salida.splitlines():
            try:
                o = json.loads(ln)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(o, dict) and isinstance(o.get("result"), str):
                dicho = o["result"]
        ok("magenta" in dicho.lower(),
           "C1 · el modelo NOMBRA el color: vio la imagen de verdad",
           f"dijo {dicho!r} · rc={r.returncode} · stderr={(r.stderr or b'')[:200]!r}")
        # la prueba de caída de C, y es la corrida que fallaba antes: sin adjuntar nada,
        # el mismo prompt (con su marca) NO puede saber el color.
        av2 = P.build_argv(_bin, prompt, "sonnet", wd, stream=True)
        r2 = subprocess.run(av2, cwd=wd, capture_output=True, timeout=180)
        dicho2 = ""
        for ln in (r2.stdout or b"").decode("utf-8", "replace").splitlines():
            try:
                o = json.loads(ln)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(o, dict) and isinstance(o.get("result"), str):
                dicho2 = o["result"]
        ok("magenta" not in dicho2.lower(),
           "C2 · …y SIN adjuntarla no lo sabe (la C1 mide la imagen, no la suerte)",
           f"dijo {dicho2!r}")

print(f"\n{_OK} verdes · {_MAL} rojas · {len(_NOMED)} no medibles")
raise SystemExit(0 if _MAL == 0 else 1)
