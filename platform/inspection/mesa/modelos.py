"""
mesa/modelos.py — el estado de una construcción + su serde (borrador retomable).

Una CONSTRUCCIÓN es la unidad de trabajo persistente de la Mesa. Su snapshot es lo que
convierte "no terminó" en "no se perdió": guarda la estación exacta, el inventario aprovechable
(tools que SÍ validaron, superficie observada, identidad del software) y la pregunta pendiente
si el motor pausó. Retomarla re-arranca DESDE su estación con ese inventario.

INVARIANTE DE SEGURIDAD: el snapshot NUNCA guarda la credencial en claro ni la Session
completa (headers/cookies llevan el token real). Solo viaja `cred_ref` (puntero al vault) y/o
`session_key` (capability reuse-only). La verificación §6.6 grep-ea el snapshot buscando cero
credencial.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ── Estados de una construcción ────────────────────────────────────────────────
# trabajando  → un intento del motor está corriendo (hay thread vivo)
# pausada     → sin thread; espera respuesta humana (pregunta pendiente) o input
# terminada   → equipó la pieza (ok) o cerró sin nada aprovechable (revisar `ok`)
ESTADOS = ("trabajando", "pausada", "terminada")


@dataclass
class Opcion:
    """Una opción concreta de una pregunta temprana. `abre` referencia un flujo fuera-de-banda
    (p.ej. 'credencial' → el widget de credencial; 'browser' → captura 2FA) — la pregunta JAMÁS
    pide la credencial en el chat."""
    id: str
    label: str
    detalle: str = ""
    abre: Optional[str] = None   # None | "credencial" | "browser" | "docs" | "ejemplo"

    def to_dict(self) -> dict:
        d = {"id": self.id, "label": self.label}
        if self.detalle:
            d["detalle"] = self.detalle
        if self.abre:
            d["abre"] = self.abre
        return d


@dataclass
class Pregunta:
    """Una pregunta temprana concreta con 2-3 opciones reales. Se emite EN la estación donde el
    motor dudó, antes de avanzar."""
    pregunta_id: str
    estacion: str
    codigo: str                       # P1..P5 (para el harness / anti-fatiga)
    texto: str
    opciones: list[Opcion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"pregunta_id": self.pregunta_id, "estacion": self.estacion,
                "codigo": self.codigo, "pregunta": self.texto,
                "opciones": [o.to_dict() for o in self.opciones]}


@dataclass
class Inventario:
    """Lo aprovechable de un intento — el corazón del borrador retomable. Todo serializable;
    las tools usan el dict de store.endpoint_to_dict / _cand_detail (round-trip al candado)."""
    identidad: dict = field(default_factory=dict)          # {server, host, title, docs?}
    superficie: list[dict] = field(default_factory=list)   # endpoints observados
    tools_propuestas: list[dict] = field(default_factory=list)
    tools_validadas: list[dict] = field(default_factory=list)   # las que SÍ pasaron el candado
    tools_descartadas: list[dict] = field(default_factory=list)
    belt_ref: Optional[str] = None
    puppet_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Inventario":
        d = d or {}
        return cls(
            identidad=d.get("identidad") or {},
            superficie=list(d.get("superficie") or []),
            tools_propuestas=list(d.get("tools_propuestas") or []),
            tools_validadas=list(d.get("tools_validadas") or []),
            tools_descartadas=list(d.get("tools_descartadas") or []),
            belt_ref=d.get("belt_ref"),
            puppet_id=d.get("puppet_id"),
        )


@dataclass
class Snapshot:
    """El borrador retomable, escrito en cada transición de estación. `pedido` guarda cómo
    re-lanzar el motor (SIN cred: solo cred_ref/session_key + perillas de forma). `decisiones`
    registra las respuestas humanas (consentimiento auditable)."""
    construccion_id: str
    estado: str
    estacion: Optional[str]
    ok: bool = False
    service: Optional[str] = None
    pedido: dict = field(default_factory=dict)             # url, forma, cred_ref, session_key, alcance, perillas
    inventario: Inventario = field(default_factory=Inventario)
    pregunta: Optional[Pregunta] = None
    decisiones: list[dict] = field(default_factory=list)   # [{pregunta_id, codigo, opcion, at}]
    space_id: Optional[str] = None
    principal_ns: Optional[str] = None                     # namespace del vault (auditoría; NO la cred)
    creada_en: float = 0.0
    tocada_en: float = 0.0
    convergencia: str = ""

    def to_dict(self) -> dict:
        return {
            "construccion_id": self.construccion_id,
            "estado": self.estado,
            "estacion": self.estacion,
            "ok": self.ok,
            "service": self.service,
            "pedido": dict(self.pedido),
            "inventario": self.inventario.to_dict(),
            "pregunta": self.pregunta.to_dict() if self.pregunta else None,
            "decisiones": list(self.decisiones),
            "space_id": self.space_id,
            "principal_ns": self.principal_ns,
            "creada_en": self.creada_en,
            "tocada_en": self.tocada_en,
            "convergencia": self.convergencia,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        preg = None
        if d.get("pregunta"):
            p = d["pregunta"]
            preg = Pregunta(
                pregunta_id=p["pregunta_id"], estacion=p["estacion"],
                codigo=p.get("codigo", ""), texto=p.get("pregunta", ""),
                opciones=[Opcion(id=o["id"], label=o["label"], detalle=o.get("detalle", ""),
                                 abre=o.get("abre")) for o in (p.get("opciones") or [])],
            )
        return cls(
            construccion_id=d["construccion_id"],
            estado=d.get("estado", "pausada"),
            estacion=d.get("estacion"),
            ok=bool(d.get("ok", False)),
            service=d.get("service"),
            pedido=dict(d.get("pedido") or {}),
            inventario=Inventario.from_dict(d.get("inventario") or {}),
            pregunta=preg,
            decisiones=list(d.get("decisiones") or []),
            space_id=d.get("space_id"),
            principal_ns=d.get("principal_ns"),
            creada_en=float(d.get("creada_en") or 0.0),
            tocada_en=float(d.get("tocada_en") or 0.0),
            convergencia=d.get("convergencia", ""),
        )

    def resumen(self) -> dict:
        """Vista corta para listar borradores (GET /v1/construcciones)."""
        return {
            "construccion_id": self.construccion_id,
            "estado": self.estado,
            "estacion": self.estacion,
            "ok": self.ok,
            "service": self.service or (self.pedido or {}).get("url"),
            "tools_validadas": len(self.inventario.tools_validadas),
            "pregunta_pendiente": bool(self.pregunta),
            "tocada_en": self.tocada_en,
        }


def ahora() -> float:
    # el motor no usa time.time en scripts de workflow, pero acá corremos en el backend real.
    return time.time()


__all__ = ["ESTADOS", "Opcion", "Pregunta", "Inventario", "Snapshot", "ahora"]
