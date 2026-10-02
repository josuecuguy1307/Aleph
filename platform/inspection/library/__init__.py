"""
inspection/library/ — LA BIBLIOTECA DE CAPTURA (§8, el moat).

Cuando el loop externo §4 (strategy/) gana un torneo contra un software, la
estrategia GANADORA se captura indexada por HUELLA de familia y se REINYECTA en
software de la MISMA familia → converge en ~1 vuelta en vez de ~5. El motor
aprende a crackear CATEGORÍAS (Odoo/Supabase/Strapi/…), no instancias.

Frontera (la directiva FASE 3): este paquete es NUEVO y se auto-contiene. LEE
strategy/* y loop/* por import (read-only); NO los edita. La captura y la
reinyección viven en el caller (wrapper), CERO ediciones fuera de library/.

Mapa:
  fingerprint.py  → la HUELLA (host→servicio→familia) · CLAVE de índice · puro/offline
  store.py        → el ALMACÉN (json en dir gitignored, índice por family_id) · serde
  reinject.py     → el WRAPPER caller-side (FASE 3c): lookup → priors en 1 batch
                    → fall-through a run_cascade + captura (FASE 3b)
"""
from __future__ import annotations

from inspection.library import fingerprint, reinject, store  # noqa: F401
from inspection.library.reinject import LibraryResult, inspect_target  # noqa: F401

__all__ = ["fingerprint", "store", "reinject", "LibraryResult", "inspect_target"]
