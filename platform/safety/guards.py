"""
guards.py — la FACHADA que los seams importan (una sola superficie, fail-closed).

Los archivos core llaman SOLO a esto (un import + una línea), nunca a las piezas
internas. Cada guard COMPONE las defensas y devuelve/levanta de forma que el core solo
pueda volverse MÁS estricto, jamás más laxo:

  guard_recon(target_url, subject)        → rate-limit + anti-SSRF + audit (recon)
  guard_replay(url, subject, is_write)    → kill-switch + blast-radius + anti-SSRF + audit
  guard_agent_write(subject, niche)       → kill-switch + blast-radius (write sin URL)
  legal_precheck(recipe, env)             → postura legal por nicho (el caller la impone)

Levanta SafetyBlocked (subclase de PermissionError) cuando hay que cortar — el core lo
deja propagar o lo traduce a un refused honesto. NUNCA traga la excepción en silencio.
"""
from __future__ import annotations

from typing import Any, Optional

from . import audit_log, kill_switch, legal_gates, rate_limit
from .url_guard import UrlBlocked, assert_inspectable


class SafetyBlocked(PermissionError):
    """La capa de safety cortó la acción. `reason` describe por qué (auditable)."""

    def __init__(self, reason: str, **meta: Any):
        self.reason = reason
        self.meta = meta
        super().__init__(reason)


def guard_recon(target_url: str, *, subject: Optional[str] = None,
                allow_local_fixture: bool = False) -> str:
    """
    Guard del recon (lo que el motor está por NAVEGAR). Orden:
      1) rate-limit por sujeto (frena abuso de volumen)
      2) anti-SSRF sobre el target (rangos internos / metadata / esquema / allowlist)
    Devuelve la URL validada o levanta SafetyBlocked. Audita ambos resultados.
    """
    subj = subject or "anon"
    ok, info = rate_limit.check_and_consume(subj, bucket="recon")
    if not ok:
        audit_log.record("recon.ratelimited", subject=subj, target=target_url,
                         decision="block", **info)
        raise SafetyBlocked("rate-limit de recon excedido", subject=subj, **info)
    try:
        url = assert_inspectable(target_url, allow_local_fixture=allow_local_fixture)
    except UrlBlocked as exc:
        audit_log.record("recon.url_blocked", subject=subj, target=target_url,
                         decision="block", reason=exc.reason)
        raise SafetyBlocked(f"target sin derecho a inspección: {exc.reason}",
                            subject=subj, url=target_url, ssrf_reason=exc.reason) from exc
    audit_log.record("recon.allowed", subject=subj, target=url, decision="allow")
    return url


def guard_replay(url: str, *, subject: Optional[str] = None, is_write: bool = False,
                 niche: Optional[str] = None) -> str:
    """
    Guard de la tool sintetizada que pega a la API real (replay). Orden:
      1) si es write: kill-switch + blast-radius (un masivo se auto-frena)
      2) anti-SSRF sobre la URL reconstruida (la request observada pudo apuntar a interno)
    El gate de WRITE explícito (allow_write) sigue siendo del core — esto es ADICIONAL.
    """
    subj = subject or "anon"
    if is_write:
        allowed, info = kill_switch.register_write(subj, niche=niche)
        if not allowed:
            audit_log.record("replay.write_blocked", subject=subj, target=url,
                             decision="block", **info)
            raise SafetyBlocked(f"write frenado: {info.get('blocked', 'kill-switch')}",
                                subject=subj, **info)
    try:
        url = assert_inspectable(url)   # replay externo: política pública estricta
    except UrlBlocked as exc:
        audit_log.record("replay.url_blocked", subject=subj, target=url,
                         decision="block", reason=exc.reason)
        raise SafetyBlocked(f"replay a destino no permitido: {exc.reason}",
                            subject=subj, url=url, ssrf_reason=exc.reason) from exc
    audit_log.record("replay.allowed", subject=subj, target=url, decision="allow",
                     is_write=is_write)
    return url


def guard_agent_write(subject: Optional[str] = None, *, niche: Optional[str] = None,
                      tool: Optional[str] = None) -> None:
    """
    Guard de un write/send del agente que NO pasa por una URL (p.ej. un MCP tool-call
    send/money). kill-switch + blast-radius. Levanta SafetyBlocked si se frena.
    """
    subj = subject or "anon"
    allowed, info = kill_switch.register_write(subj, niche=niche)
    if not allowed:
        audit_log.record("agent.write_blocked", subject=subj, target=tool,
                         decision="block", **info)
        raise SafetyBlocked(f"write del agente frenado: {info.get('blocked', 'kill-switch')}",
                            subject=subj, tool=tool, **info)
    audit_log.record("agent.write_allowed", subject=subj, target=tool, decision="allow", **info)


def legal_precheck(recipe: dict, *, env: Optional[str] = None) -> dict[str, Any]:
    """
    Postura legal por nicho. ADITIVA: el caller la impone (corta si allow=False, fuerza
    human-in-loop si require_human). Devuelve el dict de legal_gates.enforce y lo audita.
    """
    decision = legal_gates.enforce(recipe, env=env)
    audit_log.record("legal.precheck", subject=decision.get("nicho"),
                     decision="block" if not decision["allow"] else
                     ("require_human" if decision["require_human"] else "allow"),
                     env=decision.get("env"), basis=decision.get("basis"))
    return decision
