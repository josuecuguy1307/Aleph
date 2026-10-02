"""run_lifecycle.py — EL TURNO SIEMPRE CIERRA (FIX-P10 · §1).

── EL PROBLEMA, MEDIDO ──────────────────────────────────────────────────────────
`runs.status` nace en 'running' y sólo vuelve a 'done'/'error' si el proceso que corre
el turno LLEGA a su `finish_run`. Si el proceso muere antes (la app se cierra, un SIGKILL,
un cuelgue del motor), esa fila queda 'running' PARA SIEMPRE: nadie la vuelve a mirar.
En la base real de persona usuaria (2026-07-26) había **7 runs 'running'** — el más viejo del 25-jul.
Ninguno estaba corriendo. El registro mentía y nada lo corregía.

Un registro que miente es peligroso incluso cuando hoy no gatea nada: cualquier superficie
que en el futuro pregunte "¿hay un turno en vuelo?" recibe un SÍ eterno.

── LA CURA, EN DOS PIEZAS ───────────────────────────────────────────────────────
1. **EL LATIDO DEL MOTOR** (`_VIVOS`) — el único testigo honesto de que un run está VIVO
   es el proceso que lo está corriendo. `create_run` lo anota, `finish_run` lo borra
   (ambos en repo.py: UN choke point, cubre a todo el que cree o cierre runs). Un run
   'running' que NO está en este set no tiene motor detrás: es huérfano.
2. **EL REAPER AL ARRANCAR** — al bootear el cliente, ningún run puede estar vivo (el
   proceso que podría haberlo estado corriendo ya no existe). Todo 'running' pasa a
   'huerfano' con su `finished_at`. Es auto-sanante ante el caso raro de dos sidecars
   sobre el mismo datadir: si el hermano SÍ lo estaba corriendo, su `finish_run` pisa el
   estado terminal correcto al terminar.

`'huerfano'` es un estado NUEVO y deliberado: 'error' mentiría (el turno no falló, se
cortó) y dejarlo en 'running' es justamente el bug. No hay CHECK sobre `runs.status` en
ninguno de los dos dialectos (verificado en 0001_baseline.sql y schema_sqlite.sql), así
que no hace falta migración. Los lectores existentes comparan contra 'running' o 'done'
y un huérfano cae del lado correcto en todos ellos.

── LO QUE ESTE MÓDULO NO HACE ───────────────────────────────────────────────────
No gatea nada. `estado_del_turno()` es EVIDENCIA para el front, no un permiso: la ley del
composer (FIX-P10 §1b) es que un run viejo JAMÁS bloquea el envío. Acá sólo se dice la
verdad; qué hacer con ella lo decide la superficie.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

HUERFANO = "huerfano"

# Un run 'running' de ESTE proceso siempre está vivo (lo dice `_VIVOS`). Uno de OTRO
# proceso —control-plane con varios workers— no se puede ver desde acá, así que sólo se
# lo llama huérfano cuando además es VIEJO. En el cliente (un proceso) el reaper del boot
# ya dejó la base limpia y este techo nunca llega a aplicar.
TTL_SIN_LATIDO_S = 600.0

# Un corte de hace tres días no es noticia. El aviso del composer sólo habla de lo que el
# humano puede recordar como "lo último que hice".
VENTANA_AVISO_S = 86400.0

_VIVOS: set[str] = set()
_LOCK = threading.Lock()


# ── EL LATIDO ─────────────────────────────────────────────────────────────────────
def marcar_vivo(run_id: Any) -> None:
    """Este proceso empezó a correr `run_id`. Lo llama repo.create_run."""
    if not run_id:
        return
    with _LOCK:
        _VIVOS.add(str(run_id))


def marcar_cerrado(run_id: Any) -> None:
    """El turno terminó (bien o mal). Lo llama repo.finish_run."""
    if not run_id:
        return
    with _LOCK:
        _VIVOS.discard(str(run_id))


def esta_vivo(run_id: Any) -> bool:
    if not run_id:
        return False
    with _LOCK:
        return str(run_id) in _VIVOS


def vivos() -> set[str]:
    with _LOCK:
        return set(_VIVOS)


# ── FECHAS DE LOS DOS DIALECTOS ───────────────────────────────────────────────────
def _a_utc(v: Any) -> Optional[datetime]:
    """`started_at` llega datetime en Postgres y TEXT ISO en SQLite. Normaliza o None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).strip().replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001 — una fecha ilegible NO puede tumbar el gate
        return None


def edad_s(v: Any) -> Optional[float]:
    d = _a_utc(v)
    if d is None:
        return None
    try:
        return (datetime.now(timezone.utc) - d).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def es_huerfano(run: dict) -> bool:
    """Un run 'running' SIN latido del motor (y, fuera de este proceso, viejo)."""
    if not run or str(run.get("status") or "") != "running":
        return False
    if esta_vivo(run.get("id")):
        return False
    e = edad_s(run.get("started_at"))
    return e is None or e >= TTL_SIN_LATIDO_S


# ── EL REAPER DEL BOOT ────────────────────────────────────────────────────────────
def reapear_al_arrancar(conn=None) -> dict:
    """Todo run 'running' al bootear es huérfano: ningún proceso vivo lo está corriendo.

    Devuelve {'huerfanos': n} (0 y silencioso si la base no está lista — el boot NUNCA se
    cae por esto, pero tampoco falla mudo: el conteo se imprime y va al reporte)."""
    from app.phase1 import repo as _repo

    cerrar = conn is None
    n = 0
    try:
        if conn is None:
            conn = _repo.get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = %s, finished_at = now() WHERE status = 'running'",
                (HUERFANO,),
            )
            n = int(cur.rowcount or 0)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            if conn is not None:
                conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"[runs] reaper de huérfanos NO corrió: {type(exc).__name__}: {exc}", flush=True)
        return {"huerfanos": 0, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if cerrar and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    with _LOCK:
        _VIVOS.clear()
    if n:
        print(f"[runs] reaper: {n} run(s) quedaron cortados y se marcaron huérfanos", flush=True)
    return {"huerfanos": n}


# ── LA EVIDENCIA PARA EL COMPOSER ─────────────────────────────────────────────────
def estado_del_turno(conn, user_id: Optional[str]) -> dict:
    """¿Tiene este dueño un turno REALMENTE en vuelo? ¿Le quedó uno cortado?

    {
      "vivo": {"run_id", "intent", "edad_s"} | None,   # motor latiendo AHORA
      "huerfanos": [ ... ],                            # 'running' sin latido (mentira viva)
      "cortado": {"run_id", "intent", "started_at"} | None,   # el aviso honesto
    }

    Contrato: esto NO es un permiso. `vivo` existe para narrar, no para bloquear.
    """
    out: dict = {"vivo": None, "huerfanos": [], "cortado": None}
    if not user_id:
        return out
    from app.phase1 import repo as _repo

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, intent, status, started_at FROM runs "
                "WHERE user_id = %s AND status IN ('running', %s) "
                "ORDER BY started_at DESC LIMIT 40",
                (user_id, HUERFANO),
            )
            filas = [_repo._row_to_dict(cur, r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 — sin evidencia, el front sigue abierto
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    for f in filas:
        if not f:
            continue
        rid, st = str(f.get("id")), str(f.get("status") or "")
        e = edad_s(f.get("started_at"))
        if st == "running" and esta_vivo(rid):
            if out["vivo"] is None:
                out["vivo"] = {"run_id": rid, "intent": f.get("intent"), "edad_s": e}
            continue
        if st == "running":
            out["huerfanos"].append({"run_id": rid, "intent": f.get("intent"), "edad_s": e})
        # el AVISO: el corte más reciente dentro de la ventana que el humano recuerda
        if out["cortado"] is None and (st == HUERFANO or st == "running") and e is not None \
                and e <= VENTANA_AVISO_S:
            out["cortado"] = {"run_id": rid, "intent": f.get("intent"),
                              "started_at": str(f.get("started_at")), "edad_s": e}
    return out


__all__ = [
    "HUERFANO", "TTL_SIN_LATIDO_S", "VENTANA_AVISO_S",
    "marcar_vivo", "marcar_cerrado", "esta_vivo", "vivos",
    "edad_s", "es_huerfano", "reapear_al_arrancar", "estado_del_turno",
]
