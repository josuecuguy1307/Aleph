"""
advisor.py — GATE ADVISOR (ticket 5): clasifica la CONSECUENCIA de cada tool a la hora
de DISEÑAR (El Cuarto) y sugiere dónde va una compuerta, REUSANDO la misma observación
que el gate de runtime ya hace (platform/gates/approval_gate.py se carga por ruta —
UNA sola fuente de hints, cero listas duplicadas que driftean).

Doctrina (ticket 5):
  - FAIL-CLOSED: una tool ambigua (ni lectura obvia ni verbo conocido) se trata como
    CONSECUENTE → gate sugerido. Un falso positivo sólo significa "pregunta"; seguro.
  - SUGERIR, NO FORZAR: el advisor propone y el usuario decide. La PLATA no es
    sugerencia: ya tiene piso server-side inmutable (recipe_validator / enforcer →
    needs_ok SIEMPRE) → se reporta piso_server=True y la UI la pinta como candado
    del sistema, no como fantasma clickeable.
  - EXFILTRACIÓN, no sólo acción externa: una LECTURA con canal saliente
    parametrizable (search(query…) / fetch(url…) / browse / download) puede sacar
    datos del usuario hacia afuera metiéndolos en la query/URL — sin ser un "envío".
    El runtime la auto-ejecuta (lectura obvia); ESE es el hueco que el advisor cubre:
    clase propia ("exfil"), consecuente, gate sugerido. Crítico con memoria de cuenta
    en el contexto (aleph-memoria-diseno.md, invariante #4).

El advisor espeja la disposición del runtime bajo la perilla DEFAULT (balanceado):
donde el runtime va a FRENAR (hold), el advisor sugiere hacer la barrera VISIBLE como
pieza-gate de la receta; donde el runtime ejecuta pero hay canal de salida (exfil),
el advisor agrega la sugerencia que el runtime no ve. Clasificar acá NO ejecuta nada.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GATE_PATH = _REPO_ROOT / "platform" / "gates" / "approval_gate.py"


def _load_gate():
    """Carga platform/gates/approval_gate.py por ruta (el backend no asume que platform
    sea un paquete; mismo patrón que executor.py usa para el assembler)."""
    import aleph_paths
    return aleph_paths.load_module_by_path("aleph_approval_gate_hints", _GATE_PATH)


_gate = _load_gate()

# ── Canal SALIENTE PARAMETRIZABLE (heurística PROPIA del advisor — el runtime no la
# necesita porque no cambia su disposición; acá sí, porque cambia la SUGERENCIA).
# Substring case-insensitive sobre el nombre: tools cuyo argumento típico viaja
# hacia afuera (query/url/término libre). "get"/"list"/"read" NO están: sus params
# suelen ser ids locales, no texto libre que exfiltra.
_EXFIL_CHANNEL_HINTS = (
    "search", "query", "fetch", "lookup", "browse", "crawl", "navigate",
    "http", "url", "web", "request", "download", "resolve", "ask",
    "buscar", "consultar", "navegar", "descargar",
)

# Clases → copy bilingüe (el front elige por lang; mismo patrón que el overlay `en`
# de los connectors). El copy explica POR QUÉ en lenguaje de persona promedio.
_WHY = {
    "plata": {
        "es": "toca plata — el sistema ya la frena SIEMPRE antes de ejecutar (piso, no opción)",
        "en": "touches money — the system already holds it EVERY time before it runs (a floor, not an option)",
    },
    "envio": {
        "es": "manda cosas afuera (mails, mensajes, posts) — con compuerta, nada sale sin tu OK",
        "en": "sends things out (emails, messages, posts) — with a gate, nothing leaves without your OK",
    },
    "escritura": {
        "es": "cambia cosas fuera del agente (crea, edita, borra) — con compuerta, confirmas antes",
        "en": "changes things outside the agent (creates, edits, deletes) — with a gate, you confirm first",
    },
    "exfil": {
        "es": "lee, pero lo que consulta VIAJA afuera (la búsqueda/URL puede llevar tus datos — p. ej. lo que sabe de tu cuenta)",
        "en": "it reads, but what it asks TRAVELS out (the query/URL can carry your data — e.g. what it knows about your account)",
    },
    "lectura": {
        "es": "sólo lee — no toca nada afuera",
        "en": "read-only — touches nothing outside",
    },
    "ambigua": {
        "es": "no puedo asegurar qué toca — ante la duda, mejor con compuerta (puedes sacarla cuando quieras)",
        "en": "can't be sure what it touches — when in doubt, better gated (you can remove it anytime)",
    },
}


def classify_tool(name: str) -> dict:
    """Nombre de tool → clase de consecuencia + sugerencia de gate. PURA (no ejecuta).

    Orden (primer match gana): plata → envío → escritura/efecto → exfil → lectura
    obvia → AMBIGUA (fail-closed = consecuente). Espeja el runtime: plata/envío por
    los MISMOS espejos del enforcer; escritura por _WRITE_EFFECT_HINTS; lectura por
    token completo (_is_obvious_read). El exfil corre ANTES de la lectura obvia:
    search/fetch SON lectura obvia y justamente por eso el runtime las suelta.
    """
    n = (name or "").strip()
    low = n.lower()
    if not n:
        return _result(n, "ambigua", consecuente=True, sugerir=True)
    if _gate._suggests_money(low):
        # piso server-side (recipe_validator §3.5): se INFORMA, no se sugiere.
        return _result(n, "plata", consecuente=True, sugerir=False, piso=True)
    if _gate._suggests_send(low):
        return _result(n, "envio", consecuente=True, sugerir=True)
    if _gate._suggests_write_or_send(low):
        return _result(n, "escritura", consecuente=True, sugerir=True)
    is_read = _gate._is_obvious_read(low)
    if any(h in low for h in _EXFIL_CHANNEL_HINTS):
        # canal saliente parametrizable: aunque sea "lectura", la consulta viaja afuera.
        return _result(n, "exfil", consecuente=True, sugerir=True)
    if is_read:
        return _result(n, "lectura", consecuente=False, sugerir=False)
    return _result(n, "ambigua", consecuente=True, sugerir=True)   # FAIL-CLOSED


def _result(name: str, clase: str, *, consecuente: bool, sugerir: bool, piso: bool = False) -> dict:
    return {
        "tool": name,
        "clase": clase,
        "consecuente": consecuente,
        "sugerir_gate": sugerir,
        "piso_server": piso,
        "why": {"code": clase, **_WHY[clase]},
    }


class ClassifyIn(BaseModel):
    tools: list[str]


def build_advisor_router() -> APIRouter:
    router = APIRouter(prefix="/v1/advisor", tags=["advisor"])

    @router.post("/classify")
    def classify(body: ClassifyIn):
        """Clasifica un lote de nombres de tool (dedup, orden estable). Sin estado,
        sin credenciales, sin ejecutar nada — apto para llamarse en cada colocación."""
        seen: dict[str, dict] = {}
        for t in body.tools[:500]:                       # tope sano; una pieza trae ~decenas
            key = str(t)
            if key not in seen:
                seen[key] = classify_tool(key)
        out = list(seen.values())
        resumen = {
            "total": len(out),
            "consecuentes": sum(1 for r in out if r["consecuente"]),
            "sugeridos": sum(1 for r in out if r["sugerir_gate"]),
            "piso_server": sum(1 for r in out if r["piso_server"]),
        }
        return {"tools": out, "resumen": resumen}

    return router
