"""
transcribe.py — 🎙️ voz → texto (Groq Whisper), ADITIVO. Solo stdlib (urllib + multipart manual).

La Sala graba audio → lo manda acá → Groq `whisper-large-v3` lo transcribe → texto al input.
Reusa la key de cognición del assembler (GROQ_API_KEY de infra/.env). Cero deps nuevas.
"""
from __future__ import annotations

import importlib.util
import sys
import urllib.request
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
_ASM_DIR = _REPO / "platform" / "assembler"

_asm_mod = None
def _asm():
    global _asm_mod
    if _asm_mod is None:
        if str(_ASM_DIR) not in sys.path:
            sys.path.insert(0, str(_ASM_DIR))
        import aleph_paths
        _asm_mod = aleph_paths.load_module_by_path("puppet_assembler_whisper", _ASM_DIR / "recipe_assembler.py")
    return _asm_mod


def _multipart(fields: dict, file_field: str, filename: str, file_bytes: bytes, file_ct: str):
    """Arma un cuerpo multipart/form-data (stdlib, sin `requests`)."""
    boundary = "----puppetwhisper" + uuid.uuid4().hex
    nl = b"\r\n"
    buf = []
    for k, v in fields.items():
        buf.append(b"--" + boundary.encode() + nl)
        buf.append(('Content-Disposition: form-data; name="%s"' % k).encode() + nl + nl)
        buf.append(str(v).encode() + nl)
    buf.append(b"--" + boundary.encode() + nl)
    buf.append(('Content-Disposition: form-data; name="%s"; filename="%s"' % (file_field, filename)).encode() + nl)
    buf.append(("Content-Type: %s" % file_ct).encode() + nl + nl)
    buf.append(file_bytes + nl)
    buf.append(b"--" + boundary.encode() + b"--" + nl)
    return b"".join(buf), "multipart/form-data; boundary=" + boundary


def transcribe(audio_bytes: bytes, filename: str = "audio.webm", mime: str = "audio/webm",
               model: str = "whisper-large-v3", base_url: str = "https://api.groq.com/openai/v1") -> str:
    """Transcribe audio real con Groq Whisper. Devuelve el texto (str). Lanza en error de red/API."""
    import json
    key = _asm()._resolve_cognition_key(_REPO)
    body, ct = _multipart({"model": model, "response_format": "json", "temperature": "0"},
                          "file", filename, audio_bytes, mime or "application/octet-stream")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/audio/transcriptions", data=body, method="POST",
        headers={"Content-Type": ct, "Authorization": "Bearer " + key, "User-Agent": "puppet-sala/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        obj = json.loads(r.read().decode("utf-8", "replace"))
    return (obj.get("text") or "").strip()


__all__ = ["transcribe"]
