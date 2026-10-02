"""
rate_limit.py — ventana fija por sujeto (user_id o, en su defecto, space_id/ip).

Frena el abuso del recon: un sujeto no puede disparar inspecciones sin límite (cada
recon lanza un browser headless + tráfico de red real). Ventana fija simple, persistida
y con lock (el recon corre en subproceso) — suficiente y honesto; no pretende ser un
rate-limiter distribuido.
"""
from __future__ import annotations

from typing import Optional

from . import _state, config


def _prune(events: list[float], window_s: int, t: float) -> list[float]:
    cutoff = t - window_s
    return [e for e in events if e >= cutoff]


def check_and_consume(
    subject: str,
    *,
    max_n: Optional[int] = None,
    window_s: Optional[int] = None,
    bucket: str = "recon",
) -> tuple[bool, dict]:
    """
    Registra un intento del sujeto. Devuelve (allowed, info). Si allowed=False, NO se
    consume cuota (ya estaba al tope) y info trae retry_after.
    """
    max_n = config.RECON_RATE_MAX if max_n is None else max_n
    window_s = config.RECON_RATE_WINDOW_S if window_s is None else window_s
    subject = subject or "anon"
    t = _state.now()
    with _state.locked("rate") as data:
        store = data.setdefault(bucket, {})
        events = _prune(store.get(subject, []), window_s, t)
        if len(events) >= max_n:
            retry_after = max(0.0, window_s - (t - min(events)))
            store[subject] = events
            return False, {"count": len(events), "max": max_n,
                           "retry_after_s": round(retry_after, 1), "window_s": window_s}
        events.append(t)
        store[subject] = events
        return True, {"count": len(events), "max": max_n, "window_s": window_s}


def current(subject: str, *, bucket: str = "recon") -> int:
    data = _state.read("rate")
    events = (data.get(bucket, {}) or {}).get(subject, [])
    return len(_prune(events, config.RECON_RATE_WINDOW_S, _state.now()))
