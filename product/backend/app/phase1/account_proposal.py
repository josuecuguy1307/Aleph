"""ORDEN 5 · Gate de PROPUESTA para la MEMORIA DE CUENTA (Sistema 2 · WRITE-path) — parte PURA.

Un run NUNCA auto-escribe cuenta: PROPONE un hecho sobre LA PERSONA que nace INERTE (pinned=FALSE →
la lectura, que filtra pinned_only=True, no lo ve) y el usuario lo CONFIRMA (pinned=TRUE) desde el
panel. Acá vive lo puro y determinista:
  · extracción del bloque `{"hecho_de_cuenta": ...}` REUSANDO la guarda anti-eco/laundering endurecida
    de instructions_repo (única fuente — no se duplica);
  · el filtro AUTH-NEVER-PERSIST: una AUTORIZACIÓN jamás se promueve a cuenta (regla dura del MD —
    todo dinero/envío re-gatea SIEMPRE; la memoria no puede abrir un gate).
La DB (add/list/confirm/reject) vive en repo.py; el cableado al run, en executor.py.
"""
from __future__ import annotations
import re
from typing import Any, Optional

from app.phase1.instructions_repo import extract_proposal

_ACCOUNT_KEY = "hecho_de_cuenta"


def extract_account_proposal(answer) -> tuple[Optional[str], Any]:
    """(hecho, answer_limpio) con la MISMA guarda que las instrucciones: un solo bloque que CIERRE
    la respuesta (anti-eco/laundering). Reusa la fuente endurecida, no la copia."""
    return extract_proposal(answer, key=_ACCOUNT_KEY)


# ── filtro AUTH-NEVER-PERSIST ───────────────────────────────────────────────────────────────────
# Un hecho de CUENTA es CONTEXTO sobre la persona ("vive en Quito", "prefiere reportes cortos"),
# JAMÁS una autorización ("puede pagar sin preguntar", "aprobó el envío"). Diseño de DOS SEÑALES para
# no sobre-bloquear hechos legítimos: se marca autorización si (a) hay un PERMISO/APROBACIÓN + una
# ACCIÓN consecuente (dinero/envío), o (b) hay una frase de BYPASS de gate explícita ("sin preguntar",
# "don't ask", "pre-approved", "ya aprobó"). Así "tiene permiso de conducir" (permiso SIN acción) o
# "le gusta que le pregunten antes de enviar" (pide MÁS gate) NO se bloquean. Fail-safe: ante forma de
# autorización, NO se promueve (el hecho se descarta como candidato de cuenta; el gate sigue vivo).
_PERMISSION_TOK = re.compile(
    r"\b(aprob\w*|autoriz\w*|permis\w*|permit\w*|habilit\w*|consent\w*|"
    r"approv\w*|authoriz\w*|permission|allowed\s+to|pre-?approved)\b", re.IGNORECASE)
# grants COLOQUIALES (sin palabra de permiso formal) — sólo cuentan como autorización si además hay
# una ACCIÓN consecuente (misma regla de dos señales), para no bloquear un hecho neutro.
_GRANT_TOK = re.compile(
    r"(luz\s+verde|v[ií]a\s+libre|carta\s+blanca|mano\s+libre|manos\s+libres|visto\s+bueno|"
    r"\bel\s+ok\b|\bdale\b|adelante\s+con|encarg\w*\s+(vos\s+|de\s+)?|hacete\s+cargo|"
    r"ocup\w*\s+(vos\s+|de\s+)?|dej[oáa]\s+que|conf[ií][oa]\s+en\s+que|"
    r"go\s+ahead|green\s*-?\s*light|feel\s+free|carte\s+blanche|free\s+to)", re.IGNORECASE)
_ACTION_TOK = re.compile(
    r"\b(pag\w*|env[ií]\w*|transfer\w*|compr\w*|gast\w*|cobr\w*|mand\w*|orden\w*|gir\w*|"
    r"pay|send|sent|transfer|wire|buy|spend|charge|purchase|order|checkout)\b", re.IGNORECASE)
_STANDING_BYPASS = re.compile(
    r"(sin\s+(que\s+)?(pregunt|consult|confirm|aprob|autoriz|permiso|avis))"
    r"|(no\s+(me\s+)?(pregunt|consult|pidas|pida|confirm|avis))"
    r"|(ya\s+no\s+(pregunt|pidas|consult|confirm))"
    r"|(ya\s+(aprob|autoriz))"
    r"|(la\s+semana\s+pasada\s+(aprob|autoriz|dij|confirm))"
    r"|(don'?t\s+ask)"
    r"|(without\s+(asking|confirm|approv|permission))"
    r"|(pre-?approved)"
    r"|(already\s+approved)", re.IGNORECASE)


def is_authorization_like(content: Any) -> bool:
    """¿El texto codifica una AUTORIZACIÓN/permiso consecuente (no un hecho neutro)? True → NO se
    promueve a cuenta. Dos señales: bypass explícito de gate, O permiso + acción consecuente."""
    if not isinstance(content, str) or not content:
        return False
    if _STANDING_BYPASS.search(content):
        return True
    # dos señales: (permiso formal O grant coloquial) + acción consecuente
    if _ACTION_TOK.search(content) and (_PERMISSION_TOK.search(content) or _GRANT_TOK.search(content)):
        return True
    return False


def screen_account_fact(content: Any) -> tuple[bool, str]:
    """(ok, reason). ok=False BLOQUEA la promoción a cuenta. reasons: 'empty', 'authorization'.
    El bloque del answer igual se recorta afuera (no eco); esto sólo decide si se PROPONE."""
    s = content.strip() if isinstance(content, str) else ""
    if not s:
        return False, "empty"
    if is_authorization_like(s):
        return False, "authorization"     # regla dura: una autorización NUNCA persiste
    return True, ""
