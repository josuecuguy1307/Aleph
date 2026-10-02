# Primer-run guiado — que nadie caiga en un Cuarto/Sala vacío

Aleph sirve a **dos personas por igual** (F0 §1). El cold-start tiene que dar
**primer-valor** a las dos sin caer en una pantalla vacía. Esto es la guía + el script
que lo hace real (`seed_user.py`), no una promesa.

## El problema que resuelve

Hoy, un usuario nuevo:
- en el **Cuarto** vería el diorama vacío (paleta de átomos, pero cero agente armado),
- en la **Sala** vería *"Todavía no hay trabajo. Pídele algo abajo y aparece aquí."*

Ninguna de las dos da valor en el primer minuto. El cold-start siembra **puppets de
arranque** (templates) y dispara un **primer-run** que devuelve un dato real.

## Sembrar (las dos personas)

```bash
# no-técnico (average): siembra los keyless de arranque y corre uno
ALEPH_REPO=/path/to/aleph ALEPH_API=http://127.0.0.1:8080 \
  product/backend/.venv/bin/python \
  onboarding/seed_user.py --email nuevo@aleph.test --persona average

# técnico (dev): siembra TODOS los nichos para bajar a código / BYOK
... onboarding/seed_user.py --email dev@aleph.test --persona dev
```

El script: registra/ingresa al usuario → **valida** cada template → crea un puppet por
template → corre el keyless de arranque → imprime el **primer-valor real**. Resultado en
`onboarding/seed_result.json`.

---

## Camino NO-TÉCNICO (average) — por chat / opciones

1. **Eliges a qué te dedicas** (onboarding ya lo hace: Finanzas / Research / …).
2. **Te aparece tu primer agente listo** — no un lienzo vacío. Es el template `finanzas`
   (o `genérico`), ya cableado con una tool keyless que funciona.
3. **Primer-run en un clic**: el agente corre su `first_prompt` de ejemplo y te muestra un
   dato real (ej. *PIB de Alemania, último año, citado del Banco Mundial*).
4. **Ajustas por perillas (modo Opciones)**: Autonomía (gate on/off), Detalle, Pasos.
5. *(Modo Chat — "describe y el sistema escribe" — llega cuando se mergee el compilador
   chat→receta, Fase 5. Hasta entonces el average arranca desde template + opciones, que
   ya dan primer-valor.)*

**Cero jerga, cero pantalla vacía, valor en el primer minuto.**

---

## Camino TÉCNICO (dev) — por código / BYOK

1. **Siembras los 5 templates** (`--persona dev`). Tu Cuarto queda con un agente por nicho.
2. **Bajas a código (modo Código)**: lees el handler real de cualquier tool —
   `GET /v1/tools/{ref}/handler` (depth-3, read-only en v1).
3. **Traes lo tuyo**: override del modelo en la receta (`model.base_url`/`primary` → tu
   gateway, tu Ollama, tu endpoint) y BYOK por `keys.<provider>.byok_ref` (cargas la key
   en Conexiones; nunca va en la receta).
4. **Corres por API**: `POST /v1/puppets/run` con tu `recipe` o `puppet_id` y un prompt.
   Te devuelve el run record completo (tool_calls con resultado, gate_decisions, model_route).
5. **Motores locales**: ingeniería (Docker/FreeCAD) y medicina (Orthanc) corren cuando su
   motor está encendido; si no, el agente lo dice honesto (no inventa). Electrónica (KiCad
   sch-api) y finanzas (Banco Mundial) corren keyless ya.

**Llave en mano para el código, sin perder el gate ni la honestidad.**

---

## Verificación (verify-from-environment)

El cold-start no se da por hecho: `seed_user.py` corre contra el `:8080` real y reporta
qué se creó y **qué dato real** salió. Si el primer-run no da valor, lo dice 🔴 — no finge.
Ver el resultado verificado en [`EJEMPLO.md`](EJEMPLO.md).
