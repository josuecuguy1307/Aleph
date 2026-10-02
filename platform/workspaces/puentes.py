"""puentes.py — LLEVAR UN AJUSTE DE LA CASA HASTA DONDE EL STACK DE VERDAD LO LEE.
[rediseño · fase 4]

POR QUÉ EXISTE, Y POR QUÉ NO ES «ESCRIBIR UN ARCHIVO»
────────────────────────────────────────────────────
Mover un control de la pantalla de un stack a nuestro Settings es fácil. Lo difícil es que
siga gobernando: el almacén de la casa (`memoria.py`) es nuestro, y el que obedece es el
motor del stack, que lee OTRA COSA en OTRO momento. Entre los dos hace falta un puente, y
un puente mal tendido se ve perfecto y no hace nada.

EL CASO DE LEGAL, MEDIDO ANTES DE ESCRIBIR UNA LÍNEA. Sus preferencias viven en
`$WORKSPACE_ROOT/.preferences/`, y ahí hay **dos archivos que no se leen igual**:

    preferences.json   lo relee `dochaus/lib/research.ts:78-84` EN CADA LLAMADA, sin caché
    drafting.md        lo monta `opencode.json` como `config.instructions` y el motor lo
                       relee EN CADA TURNO

y el markdown **sólo se re-renderiza dentro de `writeDraftingPreferences`**
(`services/ingest/src/preferences.ts:66-67`, dos `writeFileSync` seguidos). O sea: escribir
el JSON a mano deja Postura, Formalidad y Detalle cambiadas en pantalla **y al modelo
obedeciendo el texto viejo**. Es exactamente el defecto nº12, y era el riesgo declarado de
esta fase.

LA COSTURA, Y ES DE ELLOS
─────────────────────────
No hace falta tocar `preferences.ts` ni ningún archivo del stack. El propio doc.haus expone
la operación completa por HTTP y su servidor público la proxea:

    services/ingest/src/server.ts:48   app.put("/preferences", … writeDraftingPreferences …)
    apps/web/script/serve-dist.ts:27-31  /ingest/* → el servicio de ingest
    apps/web/src/config.ts:5             INGEST_URL = "/ingest"

Así que el puente es: **GET `{url}/ingest/preferences` → mergear lo nuestro → PUT**. El
stack re-renderiza su markdown con su propio código, que es lo único que garantiza que el
formato del texto sea el que su motor espera.

⚠️ Y POR ESO EL PUENTE NECESITA EL PACK ARRIBA. Es una limitación real y se dice: si Legal
no está corriendo, el ajuste queda guardado en la casa y se proyecta en el próximo `enter`.
Lo que NO se hace es escribir el archivo por atrás «mientras tanto»: eso dejaría el JSON y
el markdown discrepando, que es peor que no haber escrito nada.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

_log = logging.getLogger("aleph.puentes")

#: Qué stack lee cada ajuste. Sale de `memoria.AJUSTES[...]["lee_ws"]`, no se repite acá:
#: dos listas del mismo hecho se desincronizan el primer día.


def _legal(url: str, campos: dict[str, Any], timeout: float = 6.0) -> tuple[bool, str]:
    """Mergea `campos` en las preferencias de Legal por SU endpoint. `(ok, causa)`.

    Se hace GET antes del PUT y no un PUT pelado: `writeDraftingPreferences` reemplaza el
    objeto entero (`{...DEFAULT_DRAFTING, ...input}`), así que mandar sólo nuestros tres
    campos le borraría al estudio el Attorney, el Firm y el House style. Mergear es
    obligatorio, no cortesía.
    """
    base = url.rstrip("/") + "/ingest/preferences"
    try:
        with urllib.request.urlopen(base, timeout=timeout) as r:
            actual = json.loads(r.read().decode("utf-8") or "{}")
    except Exception as e:  # noqa: BLE001
        return False, f"no_pude_leer:{getattr(e, 'reason', e)}"
    if not isinstance(actual, dict):
        return False, "respuesta_no_es_objeto"
    cuerpo = {**actual, **campos}
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(base, data=datos, method="PUT",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return False, f"http_{r.status}"
    except Exception as e:  # noqa: BLE001
        return False, f"no_pude_escribir:{getattr(e, 'reason', e)}"
    return True, ""


#: `ws -> función(url, campos) -> (ok, causa)`. Un stack sin fila no tiene puente y sus
#: ajustes no se dibujan: es la regla de la fase, no un olvido.
PUENTES = {"legal": _legal}


def proyectar(ws: str, url: Optional[str], resueltos: dict, declarados: dict) -> dict:
    """Proyecta al stack `ws` los ajustes que ÉL lee. Devuelve un parte, nunca levanta.

    El parte se devuelve y se registra a propósito: un puente que falla en silencio es
    indistinguible de uno que no existe, y esta fase entera es sobre eso.
    """
    parte: dict[str, Any] = {"ws": ws, "intentado": False, "ok": False,
                             "campos": {}, "causa": ""}
    fn = PUENTES.get(ws)
    if not fn:
        parte["causa"] = "sin_puente"
        return parte
    campos = {}
    for clave, meta in declarados.items():
        if ws not in (meta.get("lee_ws") or []):
            continue
        destino = meta.get("campo")
        if not destino:
            continue
        if clave in resueltos:
            campos[destino] = resueltos[clave]
    if not campos:
        parte["causa"] = "nada_que_proyectar"
        return parte
    parte["campos"] = campos
    if not url:
        # El pack no está corriendo. NO se escribe el archivo por atrás: ver el encabezado.
        parte["causa"] = "pack_apagado"
        return parte
    parte["intentado"] = True
    ok, causa = fn(url, campos)
    parte["ok"], parte["causa"] = ok, causa
    if not ok:
        _log.warning("puente %s: no proyectó %s — %s", ws, list(campos), causa)
    return parte
