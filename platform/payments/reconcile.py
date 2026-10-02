"""reconcile.py — LA RED DE SEGURIDAD. Step 5 · Casa 1 · P5 (§2 regla 6).

Los webhooks se pierden. Dodo reintenta 8 veces con backoff hasta ~28 h y después
abandona: si el server estuvo caído toda la ventana, ese evento NO VUELVE MÁS. Sin
reconciliación, un cliente que pagó queda en free para siempre y nadie se entera hasta
que escribe enojado.

Este job pregunta al procesador cuál es la verdad y corrige la deriva. Corre periódico.

DOS DIRECCIONES, y las dos importan:
  · ASCENSO perdido  — pagó, el webhook se perdió, sigue en free. Pierde plata y
    confianza.
  · BAJA perdida     — canceló o le rebotó la tarjeta, el webhook se perdió, sigue
    premium gratis. Pierde plata.
Un job que sólo mira una dirección deja la otra abierta.

QUÉ NO HACE: no inventa suscripciones. Sólo reconcilia las que YA existen localmente
(las creó un webhook alguna vez). Una suscripción que nunca llegó a la DB no se
descubre acá — para eso está el checkout, que la siembra. Descubrirlas exigiría barrer
la API del procesador por cuenta, y eso es otro job (y otro costo).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Optional


#: Estados que ya no cambian: no tiene sentido gastar una llamada a la API por ellos.
#: `baja` NO está acá a propósito — una cuenta dada de baja puede reactivarse, y el
#: período pagado sigue corriendo hasta su fin.
_TERMINALES = {"terminal"}


def reconciliar(conn, procesador, repo, *, limite: int = 200,
                solo_account_id: Optional[str] = None,
                ahora: Optional[_dt.datetime] = None,
                log: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
    """Compara el estado local contra el del procesador y corrige lo que derivó.

    `solo_account_id` acota el barrido a UNA cuenta. Sirve para el caso de soporte más
    común y más caro en confianza — "pagué y no se activó" —: en vez de pedirle al
    usuario que espere al próximo barrido, se reconcilia su cuenta en el momento.

    Devuelve un resumen contable: {revisadas, corregidas, tiers_cambiados, errores,
    detalle[]}. No lanza: un fallo consultando UNA suscripción no puede abortar el
    barrido de las demás — si no, una sola suscripción rota congela la reconciliación
    de todas.
    """
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    _log = log or (lambda _m: None)
    resumen: dict[str, Any] = {
        "revisadas": 0, "corregidas": 0, "tiers_cambiados": 0,
        "errores": 0, "detalle": [],
    }

    sql = ("SELECT id, account_id, processor, external_id, plan, status, "
           "       current_period_end "
           "FROM subscriptions "
           "WHERE processor = %s AND NOT (status = ANY(%s)) ")
    params: list = [procesador.nombre, list(_TERMINALES)]
    if solo_account_id:
        sql += "AND account_id = %s::uuid "
        params.append(str(solo_account_id))
    sql += "ORDER BY updated_at ASC LIMIT %s"
    params.append(limite)

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        filas = cur.fetchall()

    for (_id, account_id, _proc, external_id, plan, status_local, fin_local) in filas:
        resumen["revisadas"] += 1
        try:
            remoto = procesador.consultar_estado(external_id)
        except Exception as e:  # noqa: BLE001
            resumen["errores"] += 1
            _log(f"error consultando {external_id}: {type(e).__name__}: {e}")
            continue

        if remoto is None:
            # El procesador no lo conoce. NO se borra ni se degrada: puede ser un
            # corte de red, un id de otro entorno (test vs live) o un cambio de API.
            # Degradar por una respuesta ambigua le cortaría el servicio a alguien
            # que sí pagó — se registra y se deja como está.
            resumen["errores"] += 1
            _log(f"{external_id}: el procesador no lo reconoce — sin cambios")
            continue

        difiere_estado = remoto.status != status_local
        difiere_fin = _diferente_fecha(remoto.current_period_end, fin_local)
        if not (difiere_estado or difiere_fin):
            continue

        # DERIVA DETECTADA: la verdad del procesador manda.
        repo.upsert_subscription(
            conn, account_id=str(account_id), processor=procesador.nombre,
            external_id=external_id, plan=plan, status=remoto.status,
            current_period_end=remoto.current_period_end,
            grace_until=None,
            # `event_at=ahora` a propósito: la reconciliación es la observación MÁS
            # reciente que tenemos, así que gana sobre cualquier webhook anterior.
            # (El guard anti-desorden compara contra last_event_at.)
            event_at=ahora,
        )
        resumen["corregidas"] += 1

        antes = _tier_de(conn, account_id)
        despues = repo.resync_account_tier(
            conn, str(account_id), reason=f"reconciliation:{remoto.status}")
        if antes != despues:
            resumen["tiers_cambiados"] += 1
            _log(f"{external_id}: tier {antes} → {despues} "
                 f"(local={status_local!r} remoto={remoto.status!r})")

        resumen["detalle"].append({
            "external_id": external_id,
            "status_local": status_local, "status_remoto": remoto.status,
            "tier_antes": antes, "tier_despues": despues,
        })

    return resumen


def _tier_de(conn, account_id) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id = %s", (account_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _diferente_fecha(a, b) -> bool:
    """Compara fechas tolerando None y desfasajes de segundos (los procesadores
    redondean distinto). Un minuto de diferencia no es deriva."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    if a.tzinfo is None:
        a = a.replace(tzinfo=_dt.timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=_dt.timezone.utc)
    return abs((a - b).total_seconds()) > 60
