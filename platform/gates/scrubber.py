#!/usr/bin/env python3
"""
PIEZA 4 — Scrubber de salida.

El output del agente hacia el USUARIO / CANALES (vista previa del gate, mensaje
de Email/WhatsApp, respuesta final) pasa por un filtro que detecta y bloquea:

    • SECRETOS — cadenas con forma de key/token (API keys, OAuth, claves
      privadas, AWS, etc.). Defensa contra B1 del threat-model (eco de la key al
      entregable). Aunque el vault impide que el modelo VEA la key, el scrubber
      es la red de seguridad por si algo con forma de secreto se cuela.
    • PAYLOADS DE FÓRMULA hacia canales — celdas/strings que arrancan con = + - @
      (HYPERLINK/DDE/WEBSERVICE) que en un cliente de mail/WhatsApp/Sheets podrían
      re-ejecutarse. Coordinado con el sanitizer (misión 0013), SIN duplicar:

        ── DIVISIÓN DE TRABAJO (P010 §B1 + done de 0014) ──
        sanitizer/  -> ESCRITURA A ARCHIVOS (.xlsx/.csv): neutraliza la fórmula
                       en el archivo entregado (prefija apóstrofo / rechaza).
        scrubber    -> SALIDA A CANALES (mensaje al usuario, Email, WhatsApp):
                       neutraliza el payload de fórmula EN EL TEXTO del mensaje.
        El scrubber DELEGA en el sanitizer la lógica de neutralización de fórmula
        si el módulo existe (no re-implementa el prefijado); si no existe todavía,
        usa un fallback local equivalente. Cero duplicación de la regla.

    • URLs fuera de lista blanca (C3 — phishing por link inyectado): se marcan.

PARAMETRIZABLE: patrones de secreto y la allowlist de dominios entran por config.
"""

from __future__ import annotations

import importlib.util
import math
import re
from pathlib import Path
from typing import Callable, Optional


# ── Patrones de secreto (forma de key/token) ──────────────────────────────────
#
# AMPLIADO (brecha 3 del review de 0014 — DECISIONS Fase 15, vinculante):
# el scrubber subdetectaba — solo cubría MAYÚSCULAS. Los 3 vectores que pasaron:
#   (1) AIzaSy… — Google API key, case MIXTO (letras minúsc. + mayúsc. + dígitos)
#   (2) hex de 32+ en MINÚSCULA (md5/sha como token, ej. 'a1b2…')
#   (3) tokens genéricos largos de alta entropía (mezcla de clases) que no caían
#       en ningún prefijo conocido ni en el patrón solo-mayúsculas.
# El control positivo (par M002) exige que NÚMEROS financieros largos legítimos
# (puros dígitos, montos, IDs decimales) NO se scrubbeen — por eso los patrones
# nuevos exigen presencia de LETRAS y/o entropía, nunca matchean dígitos solos.

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "clave privada"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bya29\.[0-9A-Za-z\-_]+"), "token OAuth Google"),
    # Google API key (Maps/Cloud/Gemini): 'AIza' + 35 chars de [A-Za-z0-9_-].
    # Case MIXTO — el vector (1) que el patrón solo-mayúsculas dejaba pasar.
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "Google API key (AIza)"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "API key estilo sk-"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "token GitHub"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "token Slack"),
    # Alpha Vantage / FRED: keys de 16-64 alfanum en MAYÚSCULAS+dígitos típicas.
    # Exige al menos UNA letra A-Z (lookahead) para NO comerse números decimales
    # largos legítimos (montos, IDs de cuenta) — control positivo del par M002.
    (re.compile(r"\b(?=[A-Z0-9]*[A-Z])[A-Z0-9]{16,64}\b"), "posible API key (mayúsc./dígitos)"),
    # Hex de 32+ en MINÚSCULA o mixto (md5/sha/token) — vector (2). Exige al menos
    # una letra a-f para NO comerse números decimales largos (control positivo).
    (re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{32,}\b"), "hash/token hex (32+)"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b"), "JWT"),
]

# Prefijos de fórmula peligrosos (igual criterio que el sanitizer de 0013).
FORMULA_TRIGGERS = ("=", "+", "-", "@")


# ── Detector de alta entropía para tokens genéricos (vector 3) ────────────────
#
# Token candidato: una "palabra" de 20+ chars del set base64/base62/url-safe que
# MEZCLA clases (al menos minúsc.+mayúsc., o letras+dígitos) — un nombre/palabra
# normal o un número puro no califica. Se confirma con entropía de Shannon: el
# texto en prosa o los montos no llegan al umbral; una key aleatoria sí.

_TOKEN_CANDIDATE = re.compile(r"\b[A-Za-z0-9_\-+/=]{24,}\b")
_ENTROPY_THRESHOLD = 3.6   # bits/char; prosa ~2.5-3.2, claves random ~4.5+


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _is_high_entropy_secret(token: str) -> bool:
    """¿Token largo de alta entropía con mezcla de clases (no número, no palabra)?"""
    t = token.strip("=")
    if len(t) < 24:
        return False
    has_lower = any(c.islower() for c in t)
    has_upper = any(c.isupper() for c in t)
    has_digit = any(c.isdigit() for c in t)
    # exige MEZCLA de clases: descarta números puros (montos/IDs decimales),
    # palabras de una sola caja, y separadores de miles.
    classes = sum([has_lower, has_upper, has_digit])
    if classes < 2:
        return False
    if not (has_lower or has_upper):  # puro dígito -> jamás
        return False
    return _shannon_entropy(t) >= _ENTROPY_THRESHOLD


class ScrubReport:
    """Resultado de pasar un texto por el scrubber."""

    def __init__(self, clean_text: str, findings: list):
        self.clean_text = clean_text
        self.findings = findings          # [{tipo, detalle}]
        self.blocked = bool(findings)     # hubo algo que neutralizar

    def __repr__(self) -> str:
        return f"ScrubReport(blocked={self.blocked}, findings={len(self.findings)})"


class OutputScrubber:
    """
    Escanea y neutraliza texto que va a un usuario o canal.

    `scrub(text)` devuelve un ScrubReport con el texto limpio + los hallazgos.
    Quien lo monta decide si bloquea el envío o muestra el texto saneado.
    """

    def __init__(self, *,
                 secret_patterns=None,
                 url_allowlist: Optional[list] = None,
                 sanitizer_path: Optional[str] = None,
                 entropy_scan: bool = True):
        self.secret_patterns = secret_patterns or SECRET_PATTERNS
        self.url_allowlist = url_allowlist or []
        self._neutralize_formula = self._load_sanitizer(sanitizer_path)
        # barrido de entropía para tokens genéricos largos (vector 3 de 0014).
        self.entropy_scan = entropy_scan

    def scrub(self, text: str) -> ScrubReport:
        if not text:
            return ScrubReport(text or "", [])
        findings = []
        clean = text

        # 1) secretos -> reemplazo por marcador
        for rx, label in self.secret_patterns:
            def _repl(m, _label=label):
                findings.append({"tipo": "secreto", "detalle": _label})
                return "[secreto removido]"
            clean = rx.sub(_repl, clean)

        # 1b) tokens genéricos largos de ALTA ENTROPÍA con mezcla de clases
        #     (vector 3): lo que no cae en ningún prefijo conocido. Confirmado por
        #     entropía de Shannon -> prosa y montos NO califican (control positivo).
        if self.entropy_scan:
            def _repl_ent(m):
                tok = m.group(0)
                if _is_high_entropy_secret(tok):
                    findings.append({"tipo": "secreto", "detalle": "token de alta entropía"})
                    return "[secreto removido]"
                return tok
            clean = _TOKEN_CANDIDATE.sub(_repl_ent, clean)

        # 2) payloads de fórmula al inicio de línea -> neutralizar (delega al sanitizer)
        out_lines = []
        for line in clean.split("\n"):
            stripped = line.lstrip()
            if stripped and stripped[0] in FORMULA_TRIGGERS:
                neutral = self._neutralize_formula(stripped)
                if neutral != stripped:
                    findings.append({"tipo": "formula", "detalle": stripped[:40]})
                    indent = line[: len(line) - len(stripped)]
                    out_lines.append(indent + neutral)
                    continue
            out_lines.append(line)
        clean = "\n".join(out_lines)

        # 3) URLs fuera de la allowlist -> marcar
        if self.url_allowlist:
            for m in re.finditer(r"https?://([^\s/]+)", clean):
                host = m.group(1).lower()
                if not any(host == d or host.endswith("." + d) for d in self.url_allowlist):
                    findings.append({"tipo": "url-no-confiable", "detalle": host})

        return ScrubReport(clean, findings)

    # ── coordinación con el sanitizer (sin duplicar) ──

    def _load_sanitizer(self, sanitizer_path: Optional[str]) -> Callable[[str], str]:
        """
        Si existe platform/sanitizer/ (misión 0013), reutiliza SU función de
        neutralización de fórmula. Si no, usa el fallback local equivalente.
        Esto evita re-implementar la regla del prefijado en dos lugares.
        """
        candidates = []
        if sanitizer_path:
            candidates.append(Path(sanitizer_path))
        # ubicación canónica del artifact de 0013
        repo_root = Path(__file__).resolve().parents[2]
        candidates.append(repo_root / "platform" / "sanitizer" / "sanitizer.py")

        for cand in candidates:
            if cand.exists():
                try:
                    import aleph_paths
                    mod = aleph_paths.load_module_by_path("puppet_sanitizer", cand)
                    if mod:
                        for fn_name in ("neutralize_formula", "neutralize_cell", "sanitize_cell", "neutralize"):
                            fn = getattr(mod, fn_name, None)
                            if callable(fn):
                                return fn
                except Exception:
                    pass
        return _fallback_neutralize_formula


def _fallback_neutralize_formula(value: str) -> str:
    """
    Fallback equivalente al sanitizer (0013) cuando el módulo aún no existe:
    prefija apóstrofo a un valor que arranca con = + - @, neutralizándolo como
    texto (no se re-ejecuta en Sheets/Excel/clientes de mail).
    """
    if value and value[0] in FORMULA_TRIGGERS:
        return "'" + value
    return value
