"""
inspection — MOTOR DE INSPECCIÓN DE CONTEXTO (capas 1→3).

Dado un software web externo, lo inspecciona vía Playwright (structured-first,
sin visión en esta fase), entiende qué hace y aísla la(s) request(s) reales de
una acción demostrada UNA vez — el corazón del dynamic harness engineering de
Aleph: de una demostración → un capability-block sintetizado.

PRINCIPIO NO NEGOCIABLE: la SESIÓN es un substrate intercambiable debajo de un
MOTOR ÚNICO. Todo lo que está arriba de `session/` (capture/, observe/) depende
SOLO de `session.base.AuthedContext` — jamás de `session.cloud`. Así el
local-attach (Path B) entra después detrás de la misma ABC sin reescribir nada.

Esta fase implementa SOLO el path cloud (CloudSession).
"""
