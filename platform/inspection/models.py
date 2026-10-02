"""
models.py — los datos estructurados que el motor produce y consume.

Sin dependencias de Playwright: son contenedores puros + serialización. La
REDACCIÓN de secretos vive acá y se aplica EN EL MOMENTO DE CONSTRUIR cada
objeto (no al serializar) para que un secreto nunca quede en memoria del modelo
ni en un dump. Contrato heredado del vault del org: "jamás por valor".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

REDACTED = "***REDACTED***"

# Headers cuyo VALOR nunca guardamos (auth/cookies/keys).
_SECRET_HEADER_NAMES = {
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "api-key", "x-auth-token", "x-csrf-token", "x-xsrf-token",
}
# Nombres de campo con pinta de secreto (para redactar EXAMPLES en el schema).
_SECRET_FIELD_HINT = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|auth|otp|cvv|card[_-]?number|ssn)", re.I
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def looks_secret_name(name: str) -> bool:
    return bool(_SECRET_FIELD_HINT.search(name or ""))


def looks_secret_value(value: Any) -> bool:
    """Heurística: token largo, sin espacios, casi todo alfanumérico."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) < 20 or " " in v:
        return False
    alnum = sum(c.isalnum() or c in "-_.=" for c in v)
    return alnum / max(1, len(v)) > 0.9


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        out[k] = REDACTED if k.lower() in _SECRET_HEADER_NAMES else v
    return out


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    s = str(value)
    if _EMAIL_RE.match(s):
        return "email"
    if s.startswith(("http://", "https://")):
        return "url"
    if re.fullmatch(r"-?\d+", s):
        return "integer"
    if re.fullmatch(r"-?\d*\.\d+", s):
        return "number"
    return "string"


# ──────────────────────────────────────────────────────────────────────────────
# CAPA 1 — red
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class CapturedRequest:
    """Una request observada (request + su response emparejada). HAR estructurado."""
    request_id: str
    method: str
    url: str
    host: str
    path: str
    query: dict[str, str]
    resource_type: str
    request_headers: dict[str, str]          # valores secretos ya redactados
    post_data: Optional[str]                  # body crudo (texto) o None
    post_data_json: Optional[Any]             # JSON o dict de form si parseable
    started_at: float
    # response (se llena al terminar)
    status: Optional[int] = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_mime: Optional[str] = None
    response_body_snippet: Optional[str] = None
    finished_at: Optional[float] = None

    @property
    def is_state_changing(self) -> bool:
        return self.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}

    @property
    def is_xhr(self) -> bool:
        return self.resource_type in {"xhr", "fetch"}

    @property
    def has_body(self) -> bool:
        return bool(self.post_data)

    def to_dict(self, *, full: bool = False) -> dict:
        d = {
            "request_id": self.request_id,
            "method": self.method,
            "url": self.url,
            "host": self.host,
            "path": self.path,
            "query": self.query,
            "resource_type": self.resource_type,
            "status": self.status,
            "response_mime": self.response_mime,
            "has_body": self.has_body,
            "post_data_json": self.post_data_json,
        }
        if full:
            d["request_headers"] = self.request_headers
            d["response_headers"] = self.response_headers
            d["post_data"] = self.post_data
            d["response_body_snippet"] = self.response_body_snippet
            d["started_at"] = self.started_at
            d["finished_at"] = self.finished_at
        return d


# ──────────────────────────────────────────────────────────────────────────────
# CAPA 2 — DOM / eventos de UI
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ObservedEvent:
    """Un evento de UI durante la demostración (click/input/submit)."""
    type: str                       # navigate|click|input|change|submit
    selector: str
    ts: float
    value: Optional[str] = None     # None si el campo era secreto (password)
    tag: Optional[str] = None
    input_type: Optional[str] = None
    text: Optional[str] = None

    def to_dict(self, t0: float = 0.0) -> dict:
        return {
            "type": self.type,
            "selector": self.selector,
            "value": self.value,
            "input_type": self.input_type,
            "text": self.text,
            "t_rel_ms": round((self.ts - t0) * 1000) if t0 else None,
        }


@dataclass
class DomSnapshot:
    url: str
    title: str
    forms: list[dict] = field(default_factory=list)        # {action,method,inputs[]}
    buttons: list[dict] = field(default_factory=list)       # {text,type,name}
    accessibility: Optional[dict] = None                    # árbol a11y (puede ser grande)
    captured_at: float = 0.0

    def to_dict(self, *, with_a11y: bool = False) -> dict:
        d = {
            "url": self.url,
            "title": self.title,
            "forms": self.forms,
            "buttons": self.buttons,
        }
        if with_a11y:
            d["accessibility"] = self.accessibility
        return d


# ──────────────────────────────────────────────────────────────────────────────
# CAPA 3 — acción observada (el deliverable)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class FieldSpec:
    """Un campo del payload de la request primaria + si es variable (param del tool)."""
    name: str
    location: str                    # json|form|query|header|path
    inferred_type: str
    variable: bool                   # True = lo tipeó el humano → parámetro del tool
    example: Any                     # redactado si tiene pinta de secreto
    demonstrated_from: Optional[str] = None  # selector que produjo el valor

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "location": self.location,
            "inferred_type": self.inferred_type,
            "variable": self.variable,
            "example": self.example,
            "demonstrated_from": self.demonstrated_from,
        }


@dataclass
class ObservedAction:
    """
    El resultado de observar UNA demostración: la request real aislada del ruido
    + el schema de campos variables detectados. Esto es lo que la próxima capa
    convierte en una tool MCP / capability-block.
    """
    intent: str
    target_url: str
    demonstrated_at: float
    primary_request: Optional[CapturedRequest]
    field_schema: list[FieldSpec] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)   # [{request,score,reasons,matched}]
    ui_events: list[ObservedEvent] = field(default_factory=list)
    total_requests: int = 0
    noise_filtered: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        t0 = self.demonstrated_at
        return {
            "intent": self.intent,
            "target_url": self.target_url,
            "primary_request": self.primary_request.to_dict(full=True)
            if self.primary_request else None,
            "field_schema": [f.to_dict() for f in self.field_schema],
            "ui_events": [e.to_dict(t0) for e in self.ui_events],
            "stats": {
                "total_requests": self.total_requests,
                "candidates": len(self.candidates),
                "noise_filtered": self.noise_filtered,
            },
            "filtered_har": [
                {
                    "rank": i + 1,
                    "score": c["score"],
                    "reasons": c["reasons"],
                    "matched_fields": c["matched"],
                    **c["request"].to_dict(),
                }
                for i, c in enumerate(self.candidates)
            ],
            "notes": self.notes,
        }
