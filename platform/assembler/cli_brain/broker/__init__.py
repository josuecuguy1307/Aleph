"""broker — los CLIs como PROCESO VIVO, detrás de una perilla.

El camino de hoy (un spawn por turno) sigue siendo el respaldo y el default. Esto se
prende con `PUPPET_CLI_BROKER=on` y se mide contra ese respaldo, no contra el mundo viejo.

    vocabulario  ·  las 4 formas (Session · Capabilities · Harness · Discovery)
    pool         ·  quién posee los procesos, indexado por (dueño, CLI, config, charla)
    adaptadores  ·  uno por CLI: su protocolo, sus banderas, su campo de caché
    capa         ·  el enganche en `invoke`, con caída al camino de hoy
"""
