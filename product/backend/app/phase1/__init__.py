"""
phase1 — Backend & API, FASE 1 (Puppet AI).

Construye SOBRE Fase 0 (platform/db + RECIPE-SCHEMA.md anidado v1 + el loop que ya
emite eventos en platform/assembler/session.py). Cinco piezas:

  recipe_validator  — valida la receta v1 ANIDADA contra el contrato taller↔assembler
                      (RECIPE-SCHEMA.md, A+A+C) y HACE CUMPLIR la INVARIANTE §3.5.
  repo              — repositorio fino sobre platform/db: users / puppets / runs / keys.
  instrumentation   — liga por run_id los 5 campos en instrumentation_logs (no logs sueltos).
  event_stream      — SSE sobre los eventos que YA emite el loop (token-cost CERO).
  byok              — señal TIPADA de fallo BYOK a media tarea (screen 11), no un 500 mudo.

Diseño deliberado: cero estado global, todo recibe `repo_root` / conexión por parámetro,
para que corra igual bajo el venv del backend y el python del sistema (Fase 0).
"""

__all__ = [
    "recipe_validator",
    "repo",
    "instrumentation",
    "event_stream",
    "byok",
]
