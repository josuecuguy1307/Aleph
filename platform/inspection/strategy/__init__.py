"""
platform/inspection/strategy/ — §4 · el LOOP EXTERNO (torneo de estrategias).

El loop interno §3 (loop/) forja un MCP verificado con UNA sola estrategia: el
cerebro adivina endpoints y el candado §3 filtra. FASE 2 agrega ENCIMA un torneo
de estrategias con cascada de salida temprana A→B→C→D + el switch de NIVEL-2 de
la tabla §5 (cuando TODOS los candidatos caen 404 y hay un /openapi.json al lado →
no refinar tools, cambiar de estrategia entera).

El candado §3 (loop/validator.py · LiveValidator) sigue siendo EL ÁRBITRO en cada
peldaño: FASE 2 elige QUÉ candidatos generar, NO relaja la validación. "Rinde" =
los candidatos SOBREVIVEN al candado, jamás "devolvió algo".

Frontera de archivos: este módulo NO edita contracts.py ni loop/* (solo los LEE y
reusa por import). Los tipos nuevos viven en strategy/types.py (no en el
contracts.py compartido, para no colisionar con otra lane en paralelo).

  types.py     → Rung, Outcome, DiscoverySignal, StrategyResult, Strategy, ctx, CascadeResult
  openapi.py   → peldaño A: sniff + parseo de OpenAPI/Swagger/GraphQL → CandidateTool
  rungs.py     → A (autodescriptivo) · B (huella→resolver) · C (convención) · D (activo→§3)
  cascade.py   → el orquestador: cascada A→B→C→D, salida temprana, switch nivel-2, forja única
"""
