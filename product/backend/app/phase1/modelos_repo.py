"""modelos_repo.py — EL REGISTRO DE MODELOS (Gate 2 · F4c).

La memoria que hace posible la regla ANTI-YO-YO del acta. Sin esto, el estado de un modelo
se calcula en vuelo y se olvida en cada arranque; con esto, Aleph puede distinguir:

    nunca estuvo completa  → onboarding a medias → ADUANA, con su trámite
    lo estuvo y hoy falla  → REGRESIÓN           → LOCAL, con su causa operativa

══ LA INVARIANTE, Y POR QUÉ HAY DOS VERBOS Y NO UNO ═════════════════════════════════

`ultimo_veredicto` es MEMORIA DE LARGO PLAZO —«esta pieza ANDUVO alguna vez»— y **NO se
degrada cuando un re-verify posterior falla**. Las mediciones vivas van a
`causa`/`ultima_verificacion`/`evidencia`.

Está calcado del molde, donde la regla es explícita: el barrido de arranque de conectores
escribe SÓLO `conexion` y `credencial` y **jamás toca el veredicto** — «escribir
`sin_medir` encima de un `verde` que sigue siendo cierto sería borrar evidencia buena»
(`centro_conexiones.py:1902-1904`).

Por eso la escritura está partida en DOS verbos con nombres que dicen lo que hacen:

    anotar_medicion(...)   ← el camino NORMAL. Pisa la medición viva. JAMÁS el veredicto.
    coronar_probado(...)   ← el ÚNICO que sube el veredicto a 'probado'. Se llama cuando
                             el modelo CORRIÓ de verdad.

No es ceremonia: si hubiera un solo `upsert(**campos)`, degradar el veredicto sería un
descuido de una línea, y el anti-yo-yo moriría **en silencio** — la pieza aparecería en la
aduana recién en el próximo arranque, lejos del commit que lo causó. Con dos verbos, hacerlo
exige escribirlo a propósito.

Sólo cliente (SQLite), como `conexiones`. Declarado en `role.TABLAS_SOLO_CLIENTE`.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

#: El veredicto que significa «anduvo». Único valor que habilita `estuvo_completa`.
PROBADO = "probado"


def _ahora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _fila(r) -> dict:
    """Fila cruda → dict con la derivación ya hecha. UN solo lugar que la calcula."""
    d = dict(r)
    ev = d.get("evidencia")
    if isinstance(ev, str) and ev:
        try:
            d["evidencia"] = json.loads(ev)
        except (ValueError, TypeError):
            d["evidencia"] = {}
    # ── LA DERIVACIÓN (calcada de `centro_conexiones.py:1999`) ──────────────────────
    # No hay columna `estuvo_completa`: un booleano aparte es un segundo dato que puede
    # desincronizarse del veredicto que lo justifica. El veredicto es la fuente.
    d["estuvo_completa"] = d.get("ultimo_veredicto") == PROBADO
    return d


def leer(conn, *, user_id: str, modelo_id: str) -> Optional[dict]:
    r = conn.execute(
        "SELECT * FROM modelos_estado WHERE user_id = ? AND modelo_id = ?",
        (user_id, modelo_id)).fetchone()
    return _fila(r) if r else None


def listar(conn, *, user_id: str) -> list:
    rs = conn.execute(
        "SELECT * FROM modelos_estado WHERE user_id = ? ORDER BY ultima_verificacion DESC",
        (user_id,)).fetchall()
    return [_fila(r) for r in rs]


def anotar_medicion(conn, *, user_id: str, modelo_id: str, via: Optional[str] = None,
                    causa: Optional[str] = None, evidencia: Optional[dict] = None,
                    ts: Optional[str] = None, commit: bool = True) -> None:
    """El camino NORMAL. Pisa la medición viva y **JAMÁS toca `ultimo_veredicto`**.

    Se llama en cada verify —el del arranque, el de equipar, el de la medición rancia— y
    tanto si salió bien como si salió mal. Que un modelo falle hoy no borra que anduvo
    ayer: eso es justamente lo que lo mantiene en el local con su causa en vez de
    mandarlo a la aduana como si nunca hubiera funcionado.

    `causa=None` es un verify que salió BIEN (sin causa que reportar). El veredicto lo
    sube `coronar_probado`, no esto.
    """
    ev = json.dumps(evidencia, ensure_ascii=False) if evidencia is not None else None
    conn.execute(
        """INSERT INTO modelos_estado (user_id, modelo_id, via, causa, ultima_verificacion,
                                       evidencia)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, modelo_id) DO UPDATE SET
             via                 = COALESCE(excluded.via, modelos_estado.via),
             causa               = excluded.causa,
             ultima_verificacion = excluded.ultima_verificacion,
             evidencia           = COALESCE(excluded.evidencia, modelos_estado.evidencia)
           -- ⚠️ `ultimo_veredicto` NO figura en el SET, y ésa es toda la invariante.
        """,
        (user_id, modelo_id, via, causa, ts or _ahora_iso(), ev))
    if commit:
        conn.commit()


def coronar_probado(conn, *, user_id: str, modelo_id: str, via: Optional[str] = None,
                    evidencia: Optional[dict] = None, ts: Optional[str] = None,
                    commit: bool = True) -> None:
    """El ÚNICO verbo que sube `ultimo_veredicto` a `probado`. El modelo CORRIÓ.

    «Probado» no es «está instalado» ni «el binario existe»: es que se le mandó una prueba
    real y contestó. Es la misma vara que el motor usa para las conexiones —haber invocado
    una tool de verdad— y es lo que hace que `estuvo_completa` signifique algo.

    Limpia la causa: si acaba de andar, no hay falla vigente que reportar.
    """
    ev = json.dumps(evidencia, ensure_ascii=False) if evidencia is not None else None
    conn.execute(
        """INSERT INTO modelos_estado (user_id, modelo_id, via, ultimo_veredicto, causa,
                                       ultima_verificacion, evidencia)
           VALUES (?, ?, ?, ?, NULL, ?, ?)
           ON CONFLICT(user_id, modelo_id) DO UPDATE SET
             via                 = COALESCE(excluded.via, modelos_estado.via),
             ultimo_veredicto    = excluded.ultimo_veredicto,
             causa               = NULL,
             ultima_verificacion = excluded.ultima_verificacion,
             evidencia           = COALESCE(excluded.evidencia, modelos_estado.evidencia)
        """,
        (user_id, modelo_id, via, PROBADO, ts or _ahora_iso(), ev))
    if commit:
        conn.commit()


def olvidar(conn, *, user_id: str, modelo_id: str, commit: bool = True) -> None:
    """Borra la memoria de un modelo. Para cuando el usuario lo DESINSTALA a propósito.

    Es el único camino legítimo por el que una pieza vuelve a la aduana: no porque se
    rompió, sino porque el usuario la sacó. La diferencia es la razón de ser del
    anti-yo-yo, y por eso tiene un verbo aparte en vez de ser un efecto de otro.
    """
    conn.execute("DELETE FROM modelos_estado WHERE user_id = ? AND modelo_id = ?",
                 (user_id, modelo_id))
    if commit:
        conn.commit()


__all__ = ["PROBADO", "leer", "listar", "anotar_medicion", "coronar_probado", "olvidar"]
