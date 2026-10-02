"""
platform/safety/ — T9 · capa TRANSVERSAL de guards (additiva, fail-closed).

NO contiene lógica core. Es una capa que se monta ENCIMA de los seams ya existentes
(recon, replay, run-executor) y solo puede RECHAZAR / FRENAR / PEDIR-HUMANO — nunca
permite algo que el core no permitiría. Cuatro frentes (directiva T9):

  1. SSRF/abuse en el recon  → url_guard + rate_limit  ("solo software con derecho")
  2. blast-radius en writes  → kill_switch + audit_log  (un write masivo se FRENA)
  3. gates legales por nicho → legal_gates             (ingeniería human-in-loop, etc.)
  4. privacidad              → privacy                 (retención + "borrá mis datos")

La fachada que los seams importan vive en `guards.py`. Todo es stdlib (mismo criterio
que el resto de servers locales del org). Si una dependencia (DB/red) no está, el guard
degrada FAIL-CLOSED y lo dice honesto — nunca finge verde.
"""

from .url_guard import assert_inspectable, classify_url, open_public_url, UrlBlocked  # noqa: F401
from .guards import (  # noqa: F401
    SafetyBlocked,
    guard_recon,
    guard_replay,
    guard_agent_write,
    legal_precheck,
)

__all__ = [
    "assert_inspectable",
    "classify_url",
    "open_public_url",
    "UrlBlocked",
    "SafetyBlocked",
    "guard_recon",
    "guard_replay",
    "guard_agent_write",
    "legal_precheck",
]
