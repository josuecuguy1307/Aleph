"""modelos_semilla.py — LA SEMILLA PARA VER, cuando el proveedor todavía no habló.

Lee `catalog/modelos.json` y sirve sus filas SÓLO cuando el catálogo vivo vino vacío.

⚠️ POR QUÉ EXISTE. Sin llave, siete de nuestras ocho vías de API devuelven CERO modelos
—medido el 2026-08-07: el único que contesta sin credencial es OpenRouter, porque su
`/models` es público—. Una tarjeta vacía se lee como «este proveedor no tiene modelos», y
eso es una afirmación que nadie midió. Peor: el usuario no puede distinguir «no hay nada»
de «se rompió algo».

⚠️ LA SEMILLA NUNCA LE GANA AL PROVEEDOR. Se aplica en UN solo caso —catálogo vivo con
cero filas— y jamás se mezcla con filas medidas: o están las del proveedor, o está la
semilla. Mezclarlas dejaría una lista donde dos filas contiguas significan cosas distintas
y la pantalla no tendría cómo decir cuál es cuál.

⚠️ EL GATILLO QUE HAY QUE VIGILAR, con las palabras con las que nació:

    «Si alguien promueve esos 22 a verdad sin llave de por medio, vuelve el mismo bug con
    otro nombre.»

Los 22 son las filas `verificado: false` de la tabla: su `context` y sus `capacidades` son
lo que OPENROUTER publica sobre modelos de OTRO proveedor, y su `model_id` directo es una
convención (se le quitó el prefijo de vendor), no una medición. Esta casa ya pagó una tabla
escrita a mano que se pudrió —F6-bis midió los dos ids que estaban en el código y ninguno
existía ya—. La única defensa es que la marca viaje SIEMPRE y que ninguna superficie la
pueda perder por el camino: por eso `verificado` y `fuente_dato` son campos de la fila y no
un adorno de la respuesta.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import aleph_paths as _ap
except ImportError:  # pragma: no cover — dev sin `platform/` en el path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

#: Cómo se dice «esto no lo midió el proveedor». NO es «puede estar mal»: es de quién es
#: cada dato. La diferencia importa porque la acción que se le pide al usuario es distinta
#: —no «desconfiá», sino «conectá tu llave y te lo dice el dueño del modelo»—.
FUENTE_OTRO_PROVEEDOR = "otro_proveedor"
FUENTE_PROVEEDOR = "proveedor"
FUENTE_SIN_DATO = "sin_dato"

_cache: Optional[dict] = None


def _tabla() -> dict:
    """La tabla, leída una vez. Sin ella esto es no-op y la tarjeta queda como estaba."""
    global _cache
    if _cache is None:
        f = _ap.resource_root() / "catalog" / "modelos.json"
        try:
            _cache = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — sin tabla se sigue como antes, no se rompe nada
            _cache = {}
    return _cache


def _fuente_de(fila: dict) -> str:
    if fila.get("verificado"):
        return FUENTE_PROVEEDOR
    if fila.get("context") is None and not (fila.get("capacidades") or []):
        return FUENTE_SIN_DATO
    return FUENTE_OTRO_PROVEEDOR


def filas_de(slug: str) -> list[dict]:
    """Las filas de semilla de esta vía, con su marca puesta. Lista vacía si no hay.

    Cada fila sale con la MISMA forma que una del catálogo vivo (§11) más dos campos que
    el vivo no necesita: `verificado` y `fuente_dato`. Se agregan acá y no se derivan río
    abajo a propósito — un consumidor que tenga que deducir si el dato es medido va a
    deducir mal el día que alguien agregue un tercer origen.
    """
    prov = (_tabla().get("proveedores") or {}).get(slug) or {}
    salida: list[dict] = []
    for m in prov.get("modelos") or []:
        salida.append({
            "provider_id": str(slug).split(".", 1)[-1],
            "model_id": m.get("model_id"),
            "label": m.get("label"),
            "context": m.get("context"),
            "capacidades": list(m.get("capacidades") or []),
            "salidas": list(m.get("salidas") or []),
            "free": m.get("free"),
            "verificado": bool(m.get("verificado")),
            "fuente_dato": _fuente_de(m),
        })
    return salida


def sembrar(catalogo: dict[str, Any], slug: str) -> dict[str, Any]:
    """El catálogo a servir. Devuelve el vivo intacto salvo que haya venido vacío.

    Cuando siembra, `fuente` pasa a `semilla` y `descubierto_en` se pone en None: la fecha
    del descubrimiento es del PROVEEDOR y acá no hubo ninguno. Poner la fecha de la tabla
    ahí haría que la tarjeta dijera «catálogo del proveedor · 2026-08-13» sobre algo que el
    proveedor nunca mandó — exactamente la mentira que esta pieza vino a evitar.

    `causa` se CONSERVA. La semilla no cura el problema: si la llave falta o es inválida,
    eso sigue siendo cierto y la tarjeta tiene que poder decirlo mientras muestra la lista.
    """
    if (catalogo.get("modelos") or []):
        return catalogo
    filas = filas_de(slug)
    if not filas:
        return catalogo
    return {**catalogo, "modelos": filas, "fuente": "semilla", "descubierto_en": None,
            "rancio": False,
            "semilla": {"alcance": "principales",
                        "generado_en": (_tabla().get("_generado_en") or None)}}


# ── EL DETECTOR DE VEJEZ ────────────────────────────────────────────────────────────────
#
# ⚠️ LA TABLA NO PUEDE ENVEJECER CALLADA, y no es una preocupación teórica: esta casa ya
# tuvo una tabla escrita a mano que se pudrió y nadie se enteró hasta que un turno falló
# (F6-bis: los dos ids del código habían dejado de existir). Con una tabla de 31 filas y un
# ritmo medido de ~1 modelo nuevo por proveedor por mes, la pregunta no es SI se va a
# desactualizar sino cuándo.
#
# LO QUE NO SE HACE: salir a preguntar. Ni un fetch nuestro, ni una tarea de fondo, ni un
# tercero. La tabla se contrasta **cuando el usuario conecta su llave y el proveedor habla
# solo** — o sea, con lo que ya vino por un motivo que no es éste. El detector es gratis:
# el dato ya estaba sobre la mesa y nadie lo estaba mirando.

def _ahora_iso() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def contrastar(vivo: dict[str, Any], slug: str) -> Optional[dict[str, Any]]:
    """Qué le erró la tabla, contra lo que el proveedor acaba de publicar.

    Devuelve None si no hay con qué contrastar —sin filas de semilla, o sin catálogo vivo—.
    **La ausencia de catálogo NO es un veredicto**: es la misma ley que `verificar_vigente`
    («sin catálogo no hay veredicto») y que el guard del PUT. No saber nunca es motivo para
    acusar a nadie, ni siquiera a nuestra propia tabla.

    Mira dos cosas y las separa, porque no se resuelven igual:
      · `muertos`   — ids que la tabla ofrece y el proveedor no tiene. Son los graves: la
                      tabla está mandando gente a un modelo que no existe.
      · `distintos` — el id existe pero un campo no coincide. La tabla miente sobre el
                      detalle, no sobre la existencia.
    """
    filas = filas_de(slug)
    vivas = vivo.get("modelos") or []
    if not filas or not vivas or vivo.get("fuente") == "semilla":
        return None
    por_id = {str(m.get("model_id")): m for m in vivas}
    muertos, distintos = [], []
    for f in filas:
        mid = str(f.get("model_id"))
        real = por_id.get(mid)
        if real is None:
            muertos.append(mid)
            continue
        # Sólo se comparan los campos que la tabla AFIRMA. Un hueco declarado (`context:
        # null`, `capacidades: []`) no puede estar equivocado: no dijo nada.
        if f.get("context") is not None and real.get("context") != f.get("context"):
            distintos.append({"model_id": mid, "campo": "context",
                              "tabla": f.get("context"), "proveedor": real.get("context")})
        if f.get("capacidades") and sorted(f["capacidades"]) != sorted(real.get("capacidades") or []):
            distintos.append({"model_id": mid, "campo": "capacidades",
                              "tabla": sorted(f["capacidades"]),
                              "proveedor": sorted(real.get("capacidades") or [])})
    return {"slug": slug, "medido_en": _ahora_iso(),
            "catalogo_de": vivo.get("descubierto_en"),
            "filas_tabla": len(filas), "filas_proveedor": len(vivas),
            "muertos": muertos, "distintos": distintos,
            "al_dia": not muertos and not distintos}


def _dir_contraste():
    from app.phase1.centro_modelos import modelos_dir
    d = modelos_dir() / "semilla_contraste"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registrar(parte: Optional[dict[str, Any]]) -> None:
    """Deja el veredicto en disco. UPDATE por vía, jamás una bitácora que crece.

    Lo que importa es el ÚLTIMO contraste de cada proveedor, no su historia: un archivo
    que crece con cada pintada del selector sería una fuga con forma de log. Y jamás
    rompe la pantalla — enterarse de que la tabla envejeció no puede costar el catálogo.
    """
    if not parte:
        return
    try:
        f = _dir_contraste() / (str(parte["slug"]).split(".", 1)[-1] + ".json")
        f.write_text(json.dumps(parte, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — el detector jamás tumba lo que vino a vigilar
        pass


def contrastes() -> list[dict[str, Any]]:
    """Todo lo contrastado hasta hoy. Para forense y para la superficie que lo muestre."""
    salida = []
    try:
        for f in sorted(_dir_contraste().glob("*.json")):
            try:
                salida.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 — un archivo ilegible no esconde a los demás
                continue
    except Exception:  # noqa: BLE001
        pass
    return salida


__all__ = ["filas_de", "sembrar", "contrastar", "registrar", "contrastes",
           "FUENTE_PROVEEDOR", "FUENTE_OTRO_PROVEEDOR", "FUENTE_SIN_DATO"]
