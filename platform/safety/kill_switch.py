"""
kill_switch.py — freno de mano + blast-radius de los writes del agente.

Dos cosas, una superficie:

  KILL-SWITCH (manual): el operador (o un auto-trip) traba un SCOPE y, desde ese
  momento, todo write externo de ese scope se RECHAZA hasta el reset. Scopes:
    - "global"        → frena todo
    - "user:<id>"     → frena a un usuario
    - "niche:<n>"     → frena un nicho entero
  Persistido (sobrevive reinicios) — el freno NO se cae si se reinicia :8080.

  BLAST-RADIUS (automático): cada write se cuenta por sujeto en una ventana. Si supera
  WRITE_BLAST_MAX, la capa AUTO-TRABA el kill-switch de ese sujeto y bloquea — así un
  agente que entra en loop o un prompt-injection que dispara 1000 envíos se frena solo,
  sin esperar a que un humano mire. El humano luego revisa la bitácora y hace reset.
"""
from __future__ import annotations

from typing import Optional

from . import _state, audit_log, config


# ── KILL-SWITCH manual ────────────────────────────────────────────────────────

def trip(scope: str, reason: str = "manual", *, by: str = "operator") -> dict:
    scope = scope or "global"
    with _state.locked("killswitch") as data:
        switches = data.setdefault("switches", {})
        switches[scope] = {"reason": reason, "by": by, "at": _state.now()}
    audit_log.record("killswitch.trip", subject=by, target=scope,
                     decision="block", reason=reason)
    return {"scope": scope, "tripped": True, "reason": reason}


def reset(scope: str, *, by: str = "operator") -> dict:
    scope = scope or "global"
    existed = False
    with _state.locked("killswitch") as data:
        switches = data.setdefault("switches", {})
        existed = switches.pop(scope, None) is not None
    # Un reset da BORRÓN Y CUENTA NUEVA del blast-radius del scope: si no, el contador
    # de la ventana sigue por encima del cap y el próximo write re-traba en el acto
    # (el operador dijo "este sujeto está OK ahora" → su ventana arranca limpia).
    with _state.locked("blast") as data:
        writes = data.setdefault("writes", {})
        if scope == "global":
            writes.clear()
        elif scope.startswith("user:"):
            writes.pop(scope.split("user:", 1)[1], None)
    audit_log.record("killswitch.reset", subject=by, target=scope,
                     decision="allow", existed=existed)
    return {"scope": scope, "reset": True, "was_tripped": existed}


def _tripped_scope(subject: Optional[str], niche: Optional[str]) -> Optional[dict]:
    data = _state.read("killswitch")
    switches = data.get("switches", {}) or {}
    for scope in ("global",
                  f"user:{subject}" if subject else None,
                  f"niche:{niche}" if niche else None):
        if scope and scope in switches:
            return {"scope": scope, **switches[scope]}
    return None


def is_tripped(subject: Optional[str] = None, niche: Optional[str] = None) -> Optional[dict]:
    """Devuelve la info del switch trabado que aplica al sujeto/nicho, o None."""
    return _tripped_scope(subject, niche)


def status() -> dict:
    return _state.read("killswitch").get("switches", {}) or {}


# ── BLAST-RADIUS automático ───────────────────────────────────────────────────

def _prune(events: list[float], window_s: int, t: float) -> list[float]:
    cutoff = t - window_s
    return [e for e in events if e >= cutoff]


def register_write(subject: str, *, niche: Optional[str] = None) -> tuple[bool, dict]:
    """
    Cuenta UN write del sujeto. Devuelve (allowed, info).

    - Si el kill-switch (global/user/niche) ya está trabado → (False, motivo).
    - Si este write hace superar WRITE_BLAST_MAX en la ventana → AUTO-TRABA el
      kill-switch del usuario y devuelve (False) — el masivo se frena en el acto.
    - Si no, consume y devuelve (True).
    """
    subject = subject or "anon"
    # 1) ¿ya trabado? (renombramos las claves del switch para no chocar con el `reason`
    #    posicional de SafetyBlocked cuando el caller hace **info)
    tr = _tripped_scope(subject, niche)
    if tr is not None:
        return False, {"blocked": "killswitch", "scope": tr.get("scope"),
                       "switch_reason": tr.get("reason"), "switch_by": tr.get("by")}

    t = _state.now()
    max_n = config.WRITE_BLAST_MAX
    window_s = config.WRITE_BLAST_WINDOW_S
    auto_trip = False
    with _state.locked("blast") as data:
        store = data.setdefault("writes", {})
        events = _prune(store.get(subject, []), window_s, t)
        events.append(t)
        store[subject] = events
        count = len(events)
        if count > max_n:
            auto_trip = True

    if auto_trip:
        trip(f"user:{subject}", reason=f"blast-radius: {count} writes en {window_s}s > {max_n}",
             by="auto")
        audit_log.record("blast.autotrip", subject=subject, target=f"user:{subject}",
                         decision="block", count=count, max=max_n, window_s=window_s)
        return False, {"blocked": "blast-radius", "count": count, "max": max_n,
                       "window_s": window_s}
    return True, {"count": count, "max": max_n, "window_s": window_s}


def write_count(subject: str) -> int:
    data = _state.read("blast")
    events = (data.get("writes", {}) or {}).get(subject, [])
    return len(_prune(events, config.WRITE_BLAST_WINDOW_S, _state.now()))
