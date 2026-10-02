#!/usr/bin/env python3
"""scan_secretos.py — el scan ANTES del push. Step 5 · P11.

Barre un árbol buscando credenciales antes de que salga de la máquina. Se corre sobre
el ÁRBOL DE DEPLOY (que no tiene historial), no sobre el repo de desarrollo — ese tiene
601 commits y su barrido completo es el bloque de safeguards.

DOS CAPAS, porque una sola miente:
  1. PREFIJOS CONOCIDOS — sk_live_, whsec_, ghp_, AKIA…: precisos, casi sin ruido.
  2. ENTROPÍA EN CONTEXTO DE ASIGNACIÓN — `key = "..."` con un valor largo y aleatorio.
     Atrapa lo que no tiene prefijo conocido (una password, un token propio). Trae
     falsos positivos, y por eso los IMPRIME en vez de decidir solo: un scanner que
     esconde sus dudas es peor que no tenerlo.

    python3 deploy/scan_secretos.py <directorio>
"""
from __future__ import annotations

import hashlib
import math
import re
import sys
from pathlib import Path

# ── Capa 1 · prefijos que sólo aparecen en credenciales de verdad ──────────────
PREFIJOS = {
    "Stripe secreta":       re.compile(r"sk_live_[A-Za-z0-9]{16,}"),
    "Stripe de prueba":     re.compile(r"sk_test_[A-Za-z0-9]{16,}"),
    "Stripe webhook":       re.compile(r"whsec_[A-Za-z0-9+/=]{16,}"),
    "GitHub token":         re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS access key":       re.compile(r"AKIA[0-9A-Z]{16}"),
    "Google API key":       re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "OpenAI":               re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "Anthropic":            re.compile(r"sk-ant-[A-Za-z0-9_-]{32,}"),
    "Resend":               re.compile(r"\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}"),
    "Slack token":          re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "clave privada":        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    "URL con contraseña":   re.compile(r"://[A-Za-z0-9._%-]+:[^@\s/'\"]{8,}@[A-Za-z0-9.-]+"),
    "JWT largo":            re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
}

# ── Capa 2 · asignación con valor de alta entropía ─────────────────────────────
ASIGNACION = re.compile(
    r"""(?ix)
    \b(secret|token|passwd|password|api[_-]?key|apikey|auth[_-]?key|
       private[_-]?key|access[_-]?key|credential|bearer)\b
    \s*[:=]\s*
    ['"]([^'"\n]{20,})['"]
    """)

# Palabras que delatan un placeholder o un nombre de variable, no una credencial.
INOCENTES = re.compile(
    r"(?i)(ejemplo|example|placeholder|your[_-]|xxx|\.\.\.|<[a-z_]+>|"
    r"tu[_-]?(key|token)|dummy|fake|sample|test[_-]?key|changeme|redact|"
    r"os\.environ|getenv|process\.env|f['\"]|\{|\$|"
    # concatenación/código, no un literal: `api_key=" + urllib.parse.quote(...)`
    r"\+\s|\.join|\.format|%s)")

# ⚠️ La lista es una ALLOWLIST: lo que no está acá ni se abre. Por eso `enc.key` —una
# clave Fernet de 44 chars, el caso que este scanner existe para atrapar— pasó invisible
# hasta ALEPH-PROD y hasta una capa de la imagen Docker. No fallaron los regex: el archivo
# nunca se leyó. Antes de sacar un artefacto, preguntarse qué extensiones NO están acá.
EXTENSIONES = {".py", ".js", ".mjs", ".json", ".yaml", ".yml", ".sh", ".env",
               ".txt", ".md", ".html", ".toml", ".cfg", ".ini", ".sql",
               ".key", ".pem", ".enc", ".secret", ".token", ".crt", ".p12"}
# 'vendor/' = libs de terceros vendorizadas (React, xlsx, katex…), minificadas: no son
# NUESTRO código ni contienen NUESTROS secretos → skip (mata los falsos positivos de JS min).
SALTAR_DIRS = {"__pycache__", ".git", "node_modules", ".venv", ".pytest_cache", "vendor"}

# ── Allowlist POR HASH del valor EXACTO (NUNCA por patrón) ─────────────────────
# [Casa 2 · Fase 4 · 4.2.c] Sólo estos valores EXACTOS pasan. Un JWT distinto — otra
# anon-key o, PEOR, un service_role — tiene OTRO hash y se caza igual. Allowlistear por
# patrón genérico de JWT sería CALLAR el scanner; por hash exacto, no. (Ver el red-test:
# product/backend/tests/test_artifact_scanner.py.)
ALLOWLIST_HASHES = {
    # Supabase ANON key — pública por diseño (product/app/design/aleph-config.js).
    "d9aefe31e8ecf4f54041987779d6ca628a8b01310005d277f5940897e871f9b0":
        "Supabase anon key (pública por diseño)",
}


def _allowlisted(valor: str) -> bool:
    """¿El valor EXACTO está allowlisteado por hash? No degrada el scanner: un secreto real
    distinto tiene otro hash y NO pasa."""
    return hashlib.sha256(valor.strip().encode("utf-8")).hexdigest() in ALLOWLIST_HASHES


def entropia(s: str) -> float:
    if not s:
        return 0.0
    return -sum((n / len(s)) * math.log2(n / len(s))
                for n in (s.count(c) for c in set(s)))


def redactar(s: str) -> str:
    return s[:10] + "…" + f"[{len(s)} chars]" if len(s) > 12 else s


def es_credencial_desnuda(texto: str) -> bool:
    """¿El archivo ENTERO es una credencial, sin asignación que la delate?

    CAPA 3, y la que faltaba. Las capas 1 y 2 buscan un PREFIJO conocido o un
    `campo = "valor"`. Una clave Fernet en su propio archivo no tiene ni una cosa ni la
    otra: son 44 chars pelados y un salto de línea. Por eso `platform/db/secrets/enc.key`
    llegó a ALEPH-PROD y a una capa de la imagen Docker con el scanner en verde.
    """
    cuerpo = texto.strip()
    if not cuerpo or "\n" in cuerpo:
        return False                      # más de una línea: no es un keyfile pelado
    if not (16 <= len(cuerpo) <= 512):
        return False
    if INOCENTES.search(cuerpo):
        return False
    # base64/hex/base64url y nada más: la forma de toda clave serializada
    if not re.fullmatch(r"[A-Za-z0-9+/_=-]+", cuerpo):
        return False
    return entropia(cuerpo) >= 3.6


def main(raiz: str) -> int:
    base = Path(raiz)
    ciertos, dudosos, archivos = [], [], 0

    for p in base.rglob("*"):
        if not p.is_file() or any(d in p.parts for d in SALTAR_DIRS):
            continue
        if p.suffix.lower() not in EXTENSIONES and p.name != ".env":
            continue
        try:
            texto = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        archivos += 1
        rel = p.relative_to(base)

        if es_credencial_desnuda(texto) and not _allowlisted(texto):
            ciertos.append((str(rel), 1, "archivo-credencial",
                            redactar(texto.strip())))

        for etiqueta, rx in PREFIJOS.items():
            for m in rx.finditer(texto):
                if _allowlisted(m.group(0)):
                    continue        # [4.2.c] valor allowlisteado por hash exacto
                linea = texto[:m.start()].count("\n") + 1
                ciertos.append((str(rel), linea, etiqueta, redactar(m.group(0))))

        for m in ASIGNACION.finditer(texto):
            valor = m.group(2)
            if INOCENTES.search(m.group(0)) or entropia(valor) < 3.6:
                continue
            linea = texto[:m.start()].count("\n") + 1
            dudosos.append((str(rel), linea, m.group(1), redactar(valor)))

    print(f"SCAN DE SECRETOS · {base}")
    print(f"archivos inspeccionados: {archivos}\n")

    print(f"── CAPA 1 · credenciales por prefijo conocido: {len(ciertos)}")
    if ciertos:
        for f, l, etq, val in ciertos:
            print(f"   ⛔ {f}:{l}  [{etq}]  {val}")
    else:
        print("   ✓ ninguna")

    print(f"\n── CAPA 2 · asignaciones de alta entropía (revisar a ojo): {len(dudosos)}")
    if dudosos:
        for f, l, campo, val in dudosos:
            print(f"   ⚠ {f}:{l}  {campo} = {val}")
    else:
        print("   ✓ ninguna")

    print()
    if ciertos:
        print("VEREDICTO: NO PUSHEAR — hay credenciales con forma real.")
        return 2
    if dudosos:
        print("VEREDICTO: REVISAR los dudosos a ojo antes de pushear.")
        return 1
    print("VEREDICTO: LIMPIO — sin credenciales detectadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
