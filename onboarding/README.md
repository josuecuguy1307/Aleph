# onboarding/ — Cold-start → primer-valor (T10)

Que **ningún usuario nuevo caiga en un Cuarto/Sala vacío**, ni el no-técnico ni el dev.
Templates + seed + primer-run guiado, verificados contra el `:8080` real.

## Piezas

| archivo | qué es |
|---|---|
| `templates/*.starter.json` | Recetas v1 de arranque (conformes al `recipe_validator` real), una por niche + `generico` (keyless, siempre funciona). **Llena el hueco**: electrónica y medicina no tenían template antes. |
| `seed_user.py` | Cold-start: registra/ingresa un usuario → valida cada template → crea un puppet por template (`POST /v1/puppets`) → corre el keyless de arranque (`POST /v1/puppets/run`) → **primer-valor real**. |
| `PRIMER-RUN.md` | La guía de primer-run para las **dos personas** (no-técnico por chat/opciones; dev por código/BYOK). |
| `EJEMPLO.md` | Un ejemplo end-to-end **verificado** con dato real (verify-from-environment). |

## Correr (cold-start verificable)

```bash
ALEPH_REPO=/path/to/aleph ALEPH_API=http://127.0.0.1:8080 \
  product/backend/.venv/bin/python \
  onboarding/seed_user.py --persona average     # o --persona dev
```

Salida verificada en `onboarding/seed_result.json`.

## Decisiones (honestas)

- **Templates keyless de arranque** apuntan `model.base_url` a **ollama local** (`qwen3:8b`)
  para dar primer-valor **sin asumir ninguna key**. El dev cambia a su gateway/BYOK.
- Cada template lleva un bloque `_onboarding` (persona, `first_prompt`, `runs_keyless`,
  `requires_engine`) — metadata de onboarding, **no** parte del contrato de receta; el
  seed la **quita** (`_*`) antes de mandar la receta al backend (el validador rechaza
  claves top desconocidas).
- Los nichos con **motor local** (ingeniería: Docker/FreeCAD; medicina: Orthanc) se siembran
  igual, pero su `first_prompt` solo da valor con el motor prendido. El template lo dice;
  el agente, sin motor, **lo reporta honesto** en vez de inventar.
- **Divergencia de contrato** (igual que la nota del eval): los templates codean contra la
  receta v1 **plana** que el motor valida hoy, no contra la forma F0 §4 (`nucleo/blocks`).
  T5 debe congelar la fuente de verdad antes del merge.
