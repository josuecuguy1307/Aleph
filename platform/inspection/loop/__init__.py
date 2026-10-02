"""
inspection.loop — EL LOOP INTERNO (§3) del motor de inspección, encarnado.

contracts.py CLAVA la forma (ABCs/Protocols, tipos del working set, §5 tabla de
fallas). Este paquete la IMPLEMENTA, real y contra software vivo (TMDB v3):

    Capa 0  guard.PublicHTTPGuard      anti-SSRF · corre ANTES de tocar el target
    Capa 1  session.TMDBTokenSession   Forma 1 (token en query) · valida la key viva
    Capa 2  observer.LiveObserver      1ra vuelta PASIVA, vueltas siguientes ACTIVAS
    Capa 3  synth.BrainSynthesizer     Opus 4.8 REAL vía shim (degraded:true si cae)
    Capa 4  validator.LiveValidator    EL CANDADO · llama cada candidata viva
    Capa 5  emit.MCPEmitter            VERIFIED → MCP forjado DESDE CERO + belt cards
    §6      engine.run_internal_loop    convergencia + budget + log del working set

PRINCIPIO (gap #1): el motor FABRICA un MCP real desde API+credencial cruda. Nada
de config muerto, nada de catálogo pre-armado: la única entrada es base_url+api_key;
el resto lo destapa el loop contra el entorno vivo y lo cierra el candado.
"""
