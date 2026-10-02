"""
mcp_matcher.py — EL MATCHER DE SIMILITUD: de N candidatos del registro → el mejor, o
"no encontrado". Es la pieza central del resolver y es SEGURIDAD, no ranking cosmético.

Un string-match solo (¿el nombre se parece?) es trivial de engañar: cualquiera publica
`io.github.atacante/stripe-mcp` con el nombre "stripe". Por eso rankeamos por VARIAS
señales y la más fuerte es de AUTENTICIDAD, no de parecido:

  1. NOMBRE/ALIAS (fuzzy, normalizado) — señal base, débil sola.
  2. NAMESPACE VERIFICADO POR DNS — la más fuerte. El registro verifica ownership:
     `com.stripe/<x>` exige DNS de stripe.com; `io.github.<org>/<x>` está atado a esa
     cuenta. Si el vendor del namespace ES el servicio pedido, el publicador es el dueño
     real → anti-impostor. Un server de comunidad con nombre parecido NO tiene esto.
  3. CONFIANZA — status active, isLatest, repo declarado, hosted oficial. Señales del
     propio registro (descargas/estrellas del paquete = hook de enriquecimiento, abajo).
  4. SEMÁNTICA — overlap de la descripción del server con la intención. Desempate.

Score = combinación ponderada en [0,1]. UMBRAL: si el mejor no pasa MIN_SCORE, se devuelve
"no encontrado" — NUNCA se equipa el mejor-de-malos (regla de seguridad). Mejor honesto que
un MCP equivocado/malicioso.

Stdlib pura (difflib). Sin red.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Optional

from inspection.mcp_registry import normalize

# ── pesos (suman ~1.0; el vendor DNS domina, es la señal anti-impostor) ─────────
W_NAME = 0.30
W_VENDOR = 0.45
W_TRUST = 0.10
W_SEMANTIC = 0.15

# umbral mínimo para un candidato con NAMESPACE VERIFICADO (com.stripe, io.github.<org>):
# el ownership verificado ya es la garantía fuerte, así que el piso es moderado.
MIN_SCORE = 0.50
# umbral MUCHO más alto para un candidato SIN namespace verificado: un MCP de comunidad con
# nombre parecido es justo el vector del impostor (io.github.evil/stripe-mcp saca buen
# name-signal por el leaf). Sin la prueba de ownership exigimos un match casi perfecto e
# inequívoco; en la práctica, para un servicio "de marca" el oficial ES verificado, así que
# un comunitario con score alto es sospechoso, no confiable. Regla de seguridad, no cosmética.
UNVERIFIED_MIN_SCORE = 0.80
# margen mínimo del #1 sobre el #2 cuando NINGUNO tiene vendor verificado (ambigüedad
# entre dos comunitarios → preferimos "no encontrado" a adivinar).
MIN_MARGIN_COMMUNITY = 0.12

# palabras de relleno que no aportan a la semántica.
_STOP = {"mcp", "server", "the", "a", "an", "and", "or", "for", "to", "of", "with",
         "your", "api", "tools", "tool", "access", "manage", "integration", "official"}


def _fuzzy(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # substring fuerte (uno contenido en el otro) pesa, pero menos que igualdad
    if a in b or b in a:
        return max(0.82, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def _name_signal(query: str, cand: dict) -> float:
    """Mejor fuzzy entre la query y los nombres del candidato (leaf, title, vendor)."""
    cands = [cand.get("leaf", ""), cand.get("title", ""), cand.get("vendor", "")]
    # tokens del leaf separados por - o _ (p.ej. 'stripe-billing' → 'stripe','billing')
    leaf = cand.get("leaf", "")
    for tok in leaf.replace("_", "-").split("-"):
        cands.append(tok)
    return max((_fuzzy(query, c) for c in cands if c), default=0.0)


def _vendor_signal(query: str, cand: dict) -> tuple[float, bool]:
    """Señal anti-impostor. Devuelve (score, verified). El vendor del namespace verificado
    que coincide con el servicio pedido es la prueba más fuerte de autenticidad."""
    vendor = cand.get("vendor", "")
    kind = cand.get("vendor_kind", "")
    sim = _fuzzy(query, vendor)
    if sim < 0.86:
        return (0.0, False)  # el vendor no es el servicio → sin crédito anti-impostor
    if kind == "dns":
        return (1.0 * sim, True)          # dominio verificado (com.stripe) — máximo
    if kind == "github_org":
        return (0.85 * sim, True)         # cuenta GitHub verificada (io.github.<org>)
    return (0.0, False)


def _trust_signal(cand: dict) -> float:
    s = 0.0
    if cand.get("status") == "active":
        s += 0.45
    if cand.get("is_latest"):
        s += 0.20
    if (cand.get("repository") or {}).get("url"):
        s += 0.15
    # tener un remote hosted oficial o un paquete publicado = corre de verdad
    if cand.get("remotes"):
        s += 0.12
    if cand.get("packages"):
        s += 0.08
    # enriquecimiento opcional (descargas/estrellas) inyectado por el resolver:
    s += float(cand.get("_trust_boost", 0.0) or 0.0)
    return min(1.0, s)


def _tokens(text: str) -> set[str]:
    out = set()
    for raw in (text or "").replace("/", " ").replace("-", " ").replace("_", " ").split():
        t = normalize(raw)
        if t and t not in _STOP and len(t) > 2:
            out.add(t)
    return out


def _semantic_signal(query: str, cand: dict) -> float:
    """Overlap de tokens entre la intención (query) y title+description del server."""
    q = _tokens(query)
    if not q:
        return 0.0
    doc = _tokens(cand.get("title", "") + " " + cand.get("description", ""))
    if not doc:
        return 0.0
    inter = q & doc
    if not inter:
        return 0.0
    # cobertura de la query (cuánto de lo que pedí aparece en el server)
    return len(inter) / len(q)


def score_candidate(query: str, cand: dict) -> dict:
    """Devuelve el desglose de señales + score total de un candidato."""
    name = _name_signal(query, cand)
    vendor, verified = _vendor_signal(query, cand)
    trust = _trust_signal(cand)
    semantic = _semantic_signal(query, cand)
    total = (W_NAME * name + W_VENDOR * vendor + W_TRUST * trust + W_SEMANTIC * semantic)
    return {
        "name": cand.get("name"),
        "score": round(total, 4),
        "verified_vendor": verified,
        "signals": {
            "name": round(name, 3),
            "vendor": round(vendor, 3),
            "trust": round(trust, 3),
            "semantic": round(semantic, 3),
        },
        "candidate": cand,
    }


def rank(query: str, candidates: list[dict]) -> list[dict]:
    """Rankea todos los candidatos de mayor a menor score (con desglose)."""
    scored = [score_candidate(query, c) for c in (candidates or [])]
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored


def best_match(query: str, candidates: list[dict],
               *, min_score: float = MIN_SCORE) -> dict:
    """Elige el mejor candidato CONFIABLE o devuelve un 'no encontrado' honesto.

    Devuelve:
      {"found": True, "winner": <scored>, "ranked": [...], "reason": "..."}
      {"found": False, "winner": None, "ranked": [...], "reason": "<por qué no>"}

    Reglas de seguridad:
      - si el mejor score < min_score → no encontrado (no equipamos el mejor-de-malos).
      - si NADIE tiene vendor verificado y el #1 no supera al #2 por un margen → ambiguo →
        no encontrado (dos comunitarios con nombre parecido = no adivinamos).
    """
    ranked = rank(query, candidates)
    if not ranked:
        return {"found": False, "winner": None, "ranked": [],
                "reason": "el registro no devolvió candidatos para ese servicio"}
    top = ranked[0]
    if top["verified_vendor"]:
        # namespace verificado por el registro (DNS / cuenta GitHub) → piso moderado
        if top["score"] < min_score:
            return {"found": False, "winner": None, "ranked": ranked,
                    "reason": (f"el mejor candidato verificado ({top['name']}) no alcanza el "
                               f"umbral ({top['score']:.2f} < {min_score:.2f})")}
        return {"found": True, "winner": top, "ranked": ranked,
                "reason": "vendor verificado por namespace"}
    # SIN namespace verificado: bar mucho más alto + inequívoco (anti-impostor)
    if top["score"] < UNVERIFIED_MIN_SCORE:
        return {"found": False, "winner": None, "ranked": ranked,
                "reason": (f"el mejor candidato ({top['name']}, {top['score']:.2f}) NO tiene "
                           f"namespace verificado y no alcanza el umbral estricto "
                           f"({UNVERIFIED_MIN_SCORE:.2f}) que exijo sin prueba de ownership; "
                           f"no equipo un MCP de comunidad con tu credencial sin estar seguro")}
    second = ranked[1]["score"] if len(ranked) > 1 else 0.0
    if (top["score"] - second) < MIN_MARGIN_COMMUNITY:
        return {"found": False, "winner": None, "ranked": ranked,
                "reason": (f"ambigüedad: ningún candidato tiene namespace verificado y el "
                           f"#1 ({top['name']}, {top['score']:.2f}) no supera claramente al "
                           f"#2 ({second:.2f}); no adivino entre MCPs de comunidad")}
    return {"found": True, "winner": top, "ranked": ranked,
            "reason": "match inequívoco por encima del umbral estricto (sin namespace verificado)"}


__all__ = ["score_candidate", "rank", "best_match",
           "MIN_SCORE", "UNVERIFIED_MIN_SCORE", "MIN_MARGIN_COMMUNITY",
           "W_NAME", "W_VENDOR", "W_TRUST", "W_SEMANTIC"]
