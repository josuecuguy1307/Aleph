"""
byok.py — señal TIPADA de fallo de credencial (BYOK) a media tarea → screen 11.

Microtask (e): BYOK falla a media tarea ⇒ señal TIPADA al frontend (screen 11),
NO un 500 mudo. El frontend (screen 11 "tu conexión se cayó") necesita saber, sin
adivinar parseando un stack trace:
  - QUÉ proveedor falló (provider)
  - POR QUÉ (reason: una de un enum cerrado — no texto libre que el front tenga que parsear)
  - en QUÉ run pasó (run_id) y, si se sabe, en qué tool (tool)
  - si es RECUPERABLE re-conectando la key (recoverable)
  - una copy en español lista para mostrar (user_message)

Esta señal NUNCA lleva el valor de la credencial (contrato del vault/BYOK). Solo
metadatos para que el usuario reconecte.

Diseño: una excepción de dominio (BYOKFailure) que el handler de FastAPI mapea a un
JSON tipado con HTTP 424 (Failed Dependency) — un 424 le dice al front "no fue tu
request, fue una dependencia externa (tu key)", distinto de un 500 (bug del server)
y de un 502 (el modelo se cayó). El frontend rutea 424+payload tipado a screen 11.

Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class BYOKReason(str, Enum):
    """Enum CERRADO de motivos de fallo de credencial. El front matchea contra esto,
    no contra texto libre. Agregar un motivo = agregar acá (contrato versionado)."""

    MISSING = "missing"            # no hay key registrada para ese provider
    INVALID = "invalid"            # la key existe pero el provider la rechazó (401/403)
    EXPIRED = "expired"            # la key venció
    RATE_LIMITED = "rate_limited"  # el provider devolvió 429 (cuota/rate)
    REVOKED = "revoked"            # la key fue revocada del lado del provider
    DECRYPT_FAILED = "decrypt_failed"  # no se pudo descifrar el ciphertext (enc.key mala)
    UNKNOWN = "unknown"            # cayó pero no clasificamos el motivo (último recurso)


# ¿Qué motivos se arreglan re-conectando la key? (manda a screen 11 con CTA "reconectar")
_RECOVERABLE = frozenset(
    {
        BYOKReason.MISSING,
        BYOKReason.INVALID,
        BYOKReason.EXPIRED,
        BYOKReason.REVOKED,
        BYOKReason.DECRYPT_FAILED,
    }
)

# Copy en español por motivo (screen 11). Parametrizable; el front la puede override.
_USER_COPY: dict[BYOKReason, str] = {
    BYOKReason.MISSING: "Tu agente necesita conectar {provider}, pero no encontramos esa conexión. Reconéctala para continuar.",
    BYOKReason.INVALID: "La conexión con {provider} fue rechazada. Revisa tu clave y reconéctala.",
    BYOKReason.EXPIRED: "Tu conexión con {provider} venció. Reconéctala para que tu agente continúe.",
    BYOKReason.RATE_LIMITED: "{provider} alcanzó su límite de uso por ahora. Prueba de nuevo en un rato.",
    BYOKReason.REVOKED: "La conexión con {provider} fue revocada. Genera una clave nueva y reconéctala.",
    BYOKReason.DECRYPT_FAILED: "No pudimos abrir tu conexión guardada con {provider}. Reconéctala para resolverlo.",
    BYOKReason.UNKNOWN: "Tu conexión con {provider} se cayó a mitad de la tarea. Reconéctala e intenta de nuevo.",
}

# HTTP status de la señal: 424 Failed Dependency (no 500, no 502).
BYOK_HTTP_STATUS = 424
# Tipo de error estable que el front matchea (además del status).
BYOK_ERROR_TYPE = "byok_failure"

# Pistas para clasificar un error crudo del provider a un BYOKReason (best-effort).
# Heurística defensiva: si no matchea nada, queda UNKNOWN (honesto, no inventamos).
_CLASSIFY_HINTS: list[tuple[BYOKReason, re.Pattern]] = [
    (BYOKReason.RATE_LIMITED, re.compile(r"\b429\b|rate.?limit|too many requests|quota", re.I)),
    (BYOKReason.EXPIRED, re.compile(r"\bexpired\b|expir", re.I)),
    (BYOKReason.REVOKED, re.compile(r"\brevoked\b|revok|disabled key", re.I)),
    (BYOKReason.INVALID, re.compile(r"\b401\b|\b403\b|invalid.*key|incorrect api key|unauthor|authentication", re.I)),
    (BYOKReason.MISSING, re.compile(r"no api key|missing.*key|api key.*not.*(set|found)|no credential", re.I)),
    (BYOKReason.DECRYPT_FAILED, re.compile(r"invalidtoken|decrypt|fernet|signature did not match", re.I)),
]


def classify_provider_error(raw: str) -> BYOKReason:
    """
    Clasifica un mensaje de error crudo del provider/SDK a un BYOKReason del enum.
    Best-effort y CONSERVADOR: si ninguna pista matchea, devuelve UNKNOWN (no inventa).
    El orden importa: rate-limit/expired/revoked antes que el genérico invalid (401/403).
    """
    if not raw:
        return BYOKReason.UNKNOWN
    for reason, pat in _CLASSIFY_HINTS:
        if pat.search(raw):
            return reason
    return BYOKReason.UNKNOWN


@dataclass
class BYOKFailure(Exception):
    """
    Excepción de dominio: una credencial BYOK falló a media tarea.

    NO contiene el valor de la credencial — solo metadatos para que el usuario reconecte.
    El handler de FastAPI la mapea a HTTP 424 + JSON tipado (ver to_signal()).
    """

    provider: str
    reason: BYOKReason = BYOKReason.UNKNOWN
    run_id: Optional[str] = None
    tool: Optional[str] = None
    detail: Optional[str] = None  # detalle técnico opcional (jamás la key)
    _extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # tolerante: si llega un string al enum, lo coercemos; lo desconocido => UNKNOWN
        if isinstance(self.reason, str):
            try:
                self.reason = BYOKReason(self.reason)
            except ValueError:
                self.reason = BYOKReason.UNKNOWN
        Exception.__init__(self, f"BYOK {self.provider} falló: {self.reason.value}")

    @property
    def recoverable(self) -> bool:
        """True si el usuario puede resolverlo reconectando la key (CTA en screen 11)."""
        return self.reason in _RECOVERABLE

    def user_message(self) -> str:
        """Copy en español lista para screen 11 (el provider interpolado)."""
        template = _USER_COPY.get(self.reason, _USER_COPY[BYOKReason.UNKNOWN])
        return template.format(provider=self.provider)

    def to_signal(self) -> dict[str, Any]:
        """
        La SEÑAL TIPADA que viaja al frontend (cuerpo del 424). Forma estable:
          error: 'byok_failure'    — tipo que el front matchea para rutear a screen 11
          screen: 'screen_11'      — destino explícito (no que el front lo deduzca)
          provider, reason, run_id, tool, recoverable, user_message
        Garantía: jamás incluye el valor de la credencial.
        """
        sig: dict[str, Any] = {
            "error": BYOK_ERROR_TYPE,
            "screen": "screen_11",
            "provider": self.provider,
            "reason": self.reason.value,
            "recoverable": self.recoverable,
            "user_message": self.user_message(),
            "run_id": self.run_id,
            "tool": self.tool,
        }
        if self.detail:
            sig["detail"] = self.detail
        if self._extra:
            sig["extra"] = self._extra
        return sig


def from_provider_error(
    provider: str,
    raw_error: str,
    *,
    run_id: Optional[str] = None,
    tool: Optional[str] = None,
) -> BYOKFailure:
    """
    Construye una BYOKFailure clasificando un error crudo del provider. El `raw_error`
    se clasifica a un BYOKReason; se guarda como `detail` (técnico, sin la key).
    """
    reason = classify_provider_error(raw_error)
    # detail: nunca debe llevar la key; truncamos defensivamente.
    detail = (raw_error or "").strip()
    if len(detail) > 400:
        detail = detail[:399].rstrip() + "…"
    return BYOKFailure(
        provider=provider, reason=reason, run_id=run_id, tool=tool, detail=detail or None
    )


__all__ = [
    "BYOKReason",
    "BYOKFailure",
    "classify_provider_error",
    "from_provider_error",
    "BYOK_HTTP_STATUS",
    "BYOK_ERROR_TYPE",
]
