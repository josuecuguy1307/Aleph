"""modelos_caducidad.py — VERDE VIEJO NO EXISTE. (Gate 2 · F4c · obra 3)

La pertenencia de un modelo **caduca**, y por eso se re-evalúa en TRES momentos. Es la
misma ley que el acta le puso a los conectores, calcada:

    1. AL ARRANCAR      — lo que era cierto ayer puede no serlo hoy (se apagó Ollama, se
                          cerró la sesión del CLI, venció una llave).
    2. AL EQUIPAR       — elegir un cerebro es el momento en que la respuesta importa;
                          contestarla con una medición vieja es adivinar.
    3. MEDICIÓN RANCIA  — pasado el TTL, el verde deja de afirmarse hasta re-medir.

O verde con fecha fresca, o causa con botón. **No hay verde sin fecha.**

⚠️ [F9] LO QUE ESTE MÓDULO MIDE **NO** ES LO MISMO QUE `modelos_discovery.FORMA_V`, y
confundirlos costó un defecto que sólo apareció sobre el binario instalado:

    caducidad (acá)          ¿envejeció lo que el PROVEEDOR nos dijo?  → se re-mide
    FORMA_V (discovery)      ¿cambiamos NOSOTROS de idea sobre la forma? → se TIRA

Un caché puede estar fresquísimo por esta vara y ser inservible igual, porque lo escribió una
versión del producto que guardaba otros campos. Es lo que pasó con `salidas` en F9: el
catálogo de openrouter tenía horas de vida y llegaba sin el campo que el copy necesita, así
que el rechazo perdía su frase sellada y caía al genérico. Hacen falta las DOS vigencias.

══ LO QUE ESTE MÓDULO NO HACE, Y ES DELIBERADO ══════════════════════════════════════

No degrada `ultimo_veredicto`. Ni una sola línea de acá escribe esa columna: usa
`modelos_repo.anotar_medicion`, que por construcción no la toca. Si el re-verify pudiera
bajar el veredicto a `roto`, un modelo que se rompe hoy aparecería mañana en la ADUANA como
si nunca hubiera andado — el anti-yo-yo muerto en silencio, con el síntoma a un arranque de
distancia de la causa. La invariante está declarada en el schema y probada en `verify_f4c`.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

#: Cuánto vale una medición antes de tener que repetirla. Mismo TTL que el front
#: (`modelos.widget.js:TTL_MEDICION_MS`), porque una sola verdad sobre «rancio».
TTL_MEDICION_S = 24 * 60 * 60


def rancia(ultima_verificacion: Optional[str], ahora: Optional[float] = None) -> bool:
    """¿Envejeció? **Sin medición previa NO es rancia**: es «nunca se midió», que tiene
    otro camino (medir por primera vez, no re-medir).

    El molde pagó este bug con nombre: un `NaN` colapsaba a `0` y la función respondía
    «rancia» sobre una pieza sin medición previa, disparando re-verifys de la nada.
    """
    if not ultima_verificacion:
        return False
    # ⚠️ `calendar.timegm`, NO `time.mktime`. El timestamp se escribe en UTC
    # (`modelos_repo._ahora_iso` usa `gmtime`) y `mktime` lo interpretaría como hora
    # LOCAL: en esta máquina (UTC-3) eso corre la cuenta 3 horas y una medición de hace
    # 25 h da «fresca». Lo cazó la primera prueba de esta función, y es exactamente la
    # clase de error que nadie ve hasta que un verde viejo se afirma como nuevo.
    import calendar
    try:
        t = calendar.timegm(time.strptime(str(ultima_verificacion)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return False
    return ((ahora if ahora is not None else time.time()) - t) > TTL_MEDICION_S


def a_re_verificar(filas: list, *, ahora: Optional[float] = None) -> list:
    """Qué modelos hay que volver a medir. Devuelve refs, no promesas.

    Se re-mide lo que **afirma estar bien con una medición vieja**: eso es lo único que
    puede estar mintiendo en verde. Un modelo que ya muestra su causa no necesita que le
    confirmemos que sigue roto — y volver a medirlo cuesta un spawn por nada.
    """
    out = []
    for f in filas or []:
        reg = f.get("registro") or {}
        if not f.get("estuvo_completa"):
            continue                      # nunca anduvo: su camino es el trámite, no re-medir
        if f.get("causa"):
            continue                      # ya muestra su causa: no hay verde que confirmar
        if rancia(reg.get("ultima_verificacion"), ahora):
            out.append(f.get("ref"))
    return out


def barrer_al_arrancar(owner: str, get_conn: Callable, *,
                       medir: Optional[Callable[[str], dict]] = None) -> dict:
    """Momento 1 · el barrido del arranque. **En hilo aparte y barato.**

    Devuelve el parte MEDIDO. Nunca levanta: un barrido que tumba el boot es peor que un
    verde viejo.

    ⚠️ NO BLOQUEA EL BOOT — el llamador lo corre en un `threading.Thread`, igual que el
    barrido local de conectores: «abrir Aleph no puede esperar 42 spawns, así que el
    barrido no bloquea el boot: la pantalla se pinta con lo último que se sabe y se repinta
    cuando el barrido vuelve».
    """
    parte: dict[str, Any] = {"revisadas": 0, "re_medidas": 0, "fallaron": []}
    try:
        from app.phase1 import centro_modelos as _CM
        from app.phase1 import modelos_repo as _MR
        filas = (_CM.filas(owner=owner, get_conn=get_conn) or {}).get("filas") or []
        conn = get_conn()
        try:
            memoria = {m["modelo_id"]: m for m in _MR.listar(conn, user_id=owner)}
            for f in filas:
                ref = f.get("ref")
                if not ref or ref not in memoria:
                    continue
                parte["revisadas"] += 1
                if not rancia((memoria[ref] or {}).get("ultima_verificacion")):
                    continue
                # RE-MEDIR. La medición viva se anota; el veredicto NO se toca.
                try:
                    res = medir(ref) if medir else {}
                    _MR.anotar_medicion(conn, user_id=owner, modelo_id=ref,
                                        causa=res.get("causa"),
                                        evidencia=res.get("evidencia"), commit=False)
                    parte["re_medidas"] += 1
                except Exception as exc:              # noqa: BLE001
                    # Lo que no se pudo mirar, POR NOMBRE. Un barrido que sólo canta sus
                    # éxitos deja una pieza rota invisible para siempre.
                    parte["fallaron"].append({"modelo": ref, "motivo": type(exc).__name__})
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:                          # noqa: BLE001 — el boot no se cae por esto
        parte["error"] = type(exc).__name__
    return parte


__all__ = ["TTL_MEDICION_S", "rancia", "a_re_verificar", "barrer_al_arrancar"]
