"""
mesa/ — La Mesa de Construcción (ola construcción-asistida).

Reorganiza la maquinaria del Motor B (platform/inspection/loop, dispatch, session,
library) en una superficie de CO-CONSTRUCCIÓN visible, con dos inversiones nuevas:

  • RESULTADOS-PRIMERO: cada estación deja artefactos visibles mientras trabaja; una
    construcción abortada queda como BORRADOR RETOMABLE (se re-arranca desde su estación
    con su inventario), jamás spinner-y-muerte.
  • PREGUNTAR-TEMPRANO: cuando el motor duda en una estación, PAUSA y pregunta ahí (una
    pregunta concreta, 2-3 opciones reales), en vez de adivinar y reventar 3 estaciones
    después. Solo en puntos de decisión GENUINOS (anti-fatiga de confirmación).

NO reconstruye el motor: run_internal_loop, provider_and_auth, LiveValidator (el candado),
MCPEmitter, la captura browser-oauth y el vault se REUSAN tal cual. La Mesa los envuelve en
una máquina de estados retomable y proyecta el vocabulario SSE existente sobre 6 estaciones
humanas.

Vocabulario: SIEMPRE "construir / construcción". PROHIBIDA la palabra forja/forjar/forge en
el código, la UI y el copy NUEVOS (el wire viejo — /v1/inspect/forge, eventos forge.*, el
prefijo forged-{slug} — queda intacto por compatibilidad de harnesses y de la Sala).
"""
from __future__ import annotations
