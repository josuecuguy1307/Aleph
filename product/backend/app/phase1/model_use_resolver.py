"""Admisión central de ``model-use/v1`` sobre el catálogo de Modelos v2.

Este módulo no llama proveedores ni ejecuta tools. Fija una decisión secretless que el
gateway podrá consumir después. La separación permite probar owner/scope/capacidades
antes de mover tráfico real.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.phase1.model_use_contract import ModelUse, RouteSnapshot


CatalogReader = Callable[[str], dict[str, Any]]

_CAPABILITY_ALIASES = {
    "razonamiento": "reasoning",
    "visión": "vision",
    "codigo": "code",
    "código": "code",
    "rápido": "fast",
    "rapido": "fast",
}


@dataclass
class ResolutionFailure(Exception):
    code: str
    detail: str
    status_code: int = 409
    extra: Optional[dict[str, Any]] = None

    def as_detail(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.detail, **(self.extra or {})}


def declara_matriz(row: dict[str, Any]) -> bool:
    """¿Esta fila DECLARÓ su matriz técnica? Una lista vacía es una declaración; ausente no.

    La distinción es la misma que ya defiende `modelo_elegido: null` en el catálogo
    («no medí» ≠ «medí y dio cero»), y acá decide entre dos causas distintas.
    """
    return row.get("model_use_capabilities") is not None


def normalized_capabilities(row: dict[str, Any]) -> set[str]:
    """Normaliza sólo la matriz DECLARADA; jamás inventa soporte técnico.

    ⚠️ NO CAE A `capacidades`. Ése es el vocabulario de RASGOS de la UI
    (`razonamiento · codigo · rapido · vision · embeddings`, ver `capacidades_de`), no
    una matriz técnica, y usarlo de respaldo mentía en las dos direcciones — MEDIDO el
    2026-08-12 sobre las 13 filas del catálogo real:

      · POR DEFECTO: seis filas de API caían por ese respaldo y quedaban sin `text`, sin
        `streaming` y sin `tool_calling`, porque esas tres no existen en el vocabulario de
        rasgos. Claude por API se rechazaba a sí mismo para un chat de texto corriente.
      · POR EXCESO: el rasgo `vision` es de la MARCA, no del modelo elegido, así que una
        selección resuelta a un modelo sin visión heredaba `vision` igual.

    Un respaldo que habla otro idioma no es una red de seguridad: contesta con seguridad
    lo que no sabe. Sin declaración no hay admisión — la causa lo dice.
    """
    out: set[str] = set()
    for value in row.get("model_use_capabilities") or []:
        item = str(value or "").strip().casefold()
        if item:
            out.add(_CAPABILITY_ALIASES.get(item, item))
    return out


def _requirements_hash(request: ModelUse) -> str:
    material = {
        "call_class": request.call_class,
        "required": sorted(request.capabilities.required),
        "preferred": sorted(request.capabilities.preferred),
        "tools_required": request.tools.required,
        "structured_output": request.generation.response_schema is not None,
        "stream": request.stream,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _connection_ref(row: dict[str, Any]) -> str:
    """Devuelve una referencia no sensible, nunca URL ni credencial."""
    if row.get("byok_ref"):
        return str(row["byok_ref"])
    if row.get("brain_provider"):
        return "cli:" + str(row["brain_provider"])
    if row.get("local"):
        return "local:" + str(row.get("picker_id") or row.get("slug") or "model")
    if row.get("alias"):
        return "alias:" + str(row["alias"])
    return "managed:" + str(row.get("familia") or "aleph")


# ── EL DEFAULT DEL PROVEEDOR ─────────────────────────────────────────────────────────
#
# DECISIÓN DEL DUEÑO: cuando no se puede decidir QUÉ modelo atiende el turno, se cae a uno
# del proveedor elegido en vez de tirar el turno. Si elegiste Claude y el modelo concreto no
# resuelve, que agarre uno de Claude y siga.
#
# ⚠️ Y NO TAPA EL FALLO, que es la mitad que hace que esto sea una mejora y no un parche:
# el reemplazo se ANOTA en `fallback_chain` —un campo que el contrato ya tenía y que nadie
# llenaba nunca— y el `selection_ref` del snapshot pasa a ser **el que atendió de verdad**,
# no el que se pidió. Así el ledger y la tarjeta miran un dato honesto sin hacer nada nuevo.
#
# 🔴 NUNCA PARA `model_not_connected`. Si falta la llave (o la sesión, o el binario del CLI)
# no hay default que valga: sustituir ahí sería contestar con un modelo que el usuario no
# eligió para tapar que el que eligió no está conectado. Ese caso TIENE que llegarle.

#: Las causas que admiten reemplazo. Lista BLANCA: una causa nueva no entra sola.
CAUSAS_CON_DEFAULT = frozenset({"selection_not_found", "model_unresolved"})


def _log_sustitucion(causa: str, pedido: str, elegido: str, proveedor: str) -> None:
    """Que quede dicho también en el log, no sólo en el snapshot.

    El snapshot lo lee una máquina; esto lo lee quien está mirando por qué su turno corrió
    con otro modelo. Son dos lectores distintos y los dos tienen que poder enterarse.
    """
    import logging
    logging.getLogger("aleph.model_use").warning(
        "model-use: `%s` no resolvió (%s); el turno lo atiende `%s`%s",
        pedido, causa, elegido,
        f" (mismo proveedor: {proveedor})" if proveedor else " (Default del dueño)")


def _sirve(row: dict[str, Any], request: ModelUse) -> bool:
    """¿Esta fila puede atender ESTE pedido? Las mismas puertas que el camino normal.

    No alcanza con que esté conectada: si el pedido exige capacidades, el reemplazo tiene
    que declararlas igual que las exigiría el original. Un fallback que se saltea la matriz
    entrega un turno que el gate habría rechazado.
    """
    if row.get("conectado") is not True:
        return False
    if not str(row.get("model") or "").strip():
        return False
    if request.capabilities.required:
        if not declara_matriz(row):
            return False
        if set(request.capabilities.required) - normalized_capabilities(row):
            return False
    return True


def proveedor_de(row: dict[str, Any], ref: str = "") -> str:
    """El proveedor de una fila, o el que se puede LEER de un `picker_id` roto.

    Cuando la fila existe manda la fila (`brain_provider`). Cuando no existe —`selection_ref`
    apunta a algo que ya no está— lo único que queda es el propio ref, y ahí se lee sólo lo
    que el formato garantiza: `api:<proveedor>` y `<algo>_cli`. **Si no se puede leer, se
    devuelve vacío y el llamante NO adivina**: cae al Default del dueño, que es una elección
    suya, en vez de a un proveedor inventado.
    """
    if row:
        prov = str(row.get("brain_provider") or "").strip()
        if prov:
            return prov
    ref = str(ref or "").strip()
    if ref.startswith("api:"):
        return ref[4:]
    if ref.endswith("_cli"):
        return ref
    return ""


def elegir_reemplazo(rows: list, request: ModelUse, *, proveedor: str,
                     excluir: str, default_id: str) -> Optional[dict[str, Any]]:
    """El reemplazo, en el orden que el dueño pidió: primero SU proveedor.

    1. una fila del MISMO proveedor que sirva — que es la decisión del dueño;
    2. si no hay, el Default del dueño, que también es una elección suya;
    3. si tampoco, `None`: el turno falla con su causa y su copy, como antes.

    Nunca devuelve la fila que acaba de fallar.
    """
    utiles = [r for r in rows
              if str(r.get("picker_id") or "") != excluir and _sirve(r, request)]
    if proveedor:
        mismo = [r for r in utiles if proveedor_de(r) == proveedor]
        if mismo:
            # El Default del dueño gana DENTRO de su proveedor si está entre los que sirven:
            # entre dos filas del mismo proveedor, la que él ya eligió es menos sorpresa.
            for r in mismo:
                if str(r.get("picker_id") or "") == default_id:
                    return r
            return mismo[0]
    for r in utiles:
        if str(r.get("picker_id") or "") == default_id:
            return r
    return None


def resolve_model_use(
    request: ModelUse,
    *,
    owner_id: Optional[str],
    read_catalog: CatalogReader,
    now: Callable[[], float] = time.time,
) -> RouteSnapshot:
    """Admite una llamada o falla fuerte antes de cualquier token/efecto."""
    owner = str(owner_id or "").strip()
    if not owner:
        raise ResolutionFailure(
            "no_session", "Esta acción necesita un dueño derivado de la sesión.", 401
        )

    catalog = read_catalog(owner)
    rows = list(catalog.get("modelos") or [])
    selection_ref = str(request.selection_ref or catalog.get("default_id") or "").strip()
    if not selection_ref:
        raise ResolutionFailure(
            "selection_missing",
            "No hay una selección explícita ni un Default resoluble en Modelos.",
        )

    default_id = str(catalog.get("default_id") or "").strip()
    #: Lo que se pidió, antes de cualquier reemplazo. Si al final atendió otro, esto es lo
    #: que va a `fallback_chain` — el rastro de que hubo sustitución y de qué se pidió.
    pedido = selection_ref
    cadena: list[str] = []

    def _sustituir(causa: str, fila_rota: dict) -> tuple[dict, str]:
        """Busca un reemplazo del proveedor elegido. Devuelve `(fila, ref)` o levanta.

        Levanta LA MISMA causa que traía si no hay con qué reemplazar: el copy de esa causa
        existe justamente para ese caso, y cambiarla por otra sería mentir sobre por qué
        no salió.
        """
        prov = proveedor_de(fila_rota, pedido)
        cand = elegir_reemplazo(rows, request, proveedor=prov,
                                excluir=pedido, default_id=default_id)
        if cand is None:
            return None, ""
        ref = str(cand.get("picker_id") or "")
        cadena.append(pedido)
        _log_sustitucion(causa, pedido, ref, prov)
        return cand, ref

    row = next((r for r in rows if str(r.get("picker_id") or "") == selection_ref), None)
    if row is None:
        row, selection_ref = _sustituir("selection_not_found", {})
        if row is None:
            raise ResolutionFailure(
                "selection_not_found",
                "La selección no existe en el catálogo canónico de este dueño.",
                404,
                {"selection_ref": pedido},
            )
    if row.get("conectado") is not True:
        raise ResolutionFailure(
            "model_not_connected",
            "La selección existe, pero todavía no está conectada y lista.",
            424,
            {"selection_ref": selection_ref, "cause": row.get("causa")},
        )

    # Sin requisitos no hay nada que verificar: una charla que no pide nada no necesita
    # matriz. La invariante 4 habla de una capacidad `required` ausente o NO VERIFICADA,
    # y con `required` vacío no hay ninguna de las dos.
    if request.capabilities.required and not declara_matriz(row):
        raise ResolutionFailure(
            "capability_unknown",
            "La selección todavía no declara qué soporta, así que no se puede admitir "
            "una llamada que exige capacidades. Elige un modelo del catálogo del "
            "proveedor para que Aleph conozca su matriz.",
            409,
            {"selection_ref": selection_ref,
             "required": sorted(request.capabilities.required)},
        )

    supported = normalized_capabilities(row)
    missing = sorted(set(request.capabilities.required) - supported)
    if missing:
        raise ResolutionFailure(
            "capability_unavailable",
            "El modelo elegido no declara todas las capacidades obligatorias.",
            409,
            {"selection_ref": selection_ref, "missing": missing},
        )

    resolved_model = str(row.get("model") or "").strip()
    if not resolved_model:
        _rota = row
        row, selection_ref = _sustituir("model_unresolved", _rota)
        if row is None:
            raise ResolutionFailure(
                "model_unresolved",
                "La selección no produjo un modelo ejecutable.",
                409,
                {"selection_ref": pedido},
            )
        resolved_model = str(row.get("model") or "").strip()

    return RouteSnapshot(
        owner_id=owner,
        workspace_id=request.workspace_id,
        call_id=request.call_id,
        selection_ref=selection_ref,
        selection_scope=request.selection_scope,
        policy_ref=request.policy_ref,
        requirements_hash=_requirements_hash(request),
        resolved_model=resolved_model,
        connection_ref=_connection_ref(row),
        # ⚠️ ACÁ VA EL RASTRO, y el campo ya existía en el contrato desde el principio:
        # estaba declarado y nadie lo llenaba nunca. Vacío = atendió lo que se pidió.
        fallback_chain=cadena,
        admitted_at=now(),
    )


def public_choices(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas mínimas para el chip del chat; cero infraestructura ejecutable."""
    out = []
    for row in catalog.get("modelos") or []:
        if row.get("conectado") is not True or not row.get("picker_id"):
            continue
        out.append({
            "selection_ref": str(row["picker_id"]),
            "label": str(row.get("label") or row["picker_id"]),
            "provider": str(row.get("marca") or row.get("familia") or "Aleph"),
            "tier": row.get("tier"),
            "capabilities": sorted(normalized_capabilities(row)),
            "context_window": row.get("context_window"),
            "cost": row.get("cost"),
            "default": bool(row.get("default")),
        })
    return out


__all__ = [
    "CatalogReader", "ResolutionFailure", "declara_matriz", "normalized_capabilities",
    "public_choices", "resolve_model_use",
]
