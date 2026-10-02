# Recipe Enforcer — la INVARIANTE §3.5 hecha código

> Squad **Security** · FASE 1 · 2026-06-15 · cierra el gap "la receta DECLARA, Security HACE CUMPLIR".
> Construido sobre la base de Fase 18 (misión 0014, `approval_gate.py`) — no la reinventa, la PUENTEA a la receta v1.

## Qué problema cierra

El `ApprovalGate` (Fase 18) consume una **matriz**. El schema de receta v1 (RECIPE-SCHEMA, aprobado A+A+C)
trae su propia sección `gates`, que un puppet podría declarar en `off`:

```jsonc
"gates": { "money_touch": "off", "send": "off" }   // ← la receta intenta apagarlos
```

La **INVARIANTE NO-NEGOCIABLE** (orden del founder, RECIPE-SCHEMA §3.5):
- el motor **FUERZA** `money_touch`/`send` **aunque la receta los omita o los ponga en `off`**;
- la receta puede **AGREGAR** gates, **NUNCA QUITAR** los mandatorios;
- default **FAIL-CLOSED** para tools desconocidas que escriben/mandan (lección Fase 18).

`recipe_enforcer.py` es el motor que lo hace cumplir. **No confía en `recipe["gates"]`** para decidir si
gatear: deriva la matriz efectiva por **clasificación de la tool en Security** y planta las reglas
mandatorias SIEMPRE y PRIMERO (ganan el match), inmunes a lo que diga la receta.

## API

| Símbolo | Qué hace |
|---|---|
| `recipe_to_matrix(recipe, base_matrix=None)` | receta v1 → matriz efectiva con los gates mandatorios forzados. |
| `build_enforced_gate(recipe, ...)` | receta → `ApprovalGate` listo, con `assert_invariant` corrido (fail-closed de arranque). |
| `assert_invariant(matrix)` | guard duro: la matriz DEBE traer ambos mandatorios en `confirma-siempre`, antes de cualquier regla laxa. Si falla, **no se levanta el puppet**. |
| `suggests_money_touch / suggests_send(tool)` | la clasificación de Security (qué toca plata / qué manda). VERBOS, no sustantivos. |
| `classify_tools(tool_filters)` | recorre el subset curado de la receta y reporta qué cae en money/send (para el preview del taller). |

## Cómo lo usa el runtime

```python
from recipe_enforcer import build_enforced_gate
gate = build_enforced_gate(puppet_recipe, bound_args={"spreadsheet_id": sid})
# gate ya tiene money_touch + send forzados a confirma-siempre, diga lo que diga la receta.
```

## La lección "seguro pero no paralizado" (par M002)

Las hints de send/money son **verbos** (`send`, `dispatch`, `place_order`), **no** el sustantivo
(`message`, `order`). Un primer intento usó `"message"` como hint y **paralizó** `search_messages`
(una lectura legítima) → rompía el principio rector. Se corrigió en dos lados:
- `recipe_enforcer.SEND_HINTS` / `MONEY_TOUCH_HINTS`: solo verbos de envío/movimiento.
- `approval_gate._WRITE_EFFECT_HINTS`: se quitaron los sustantivos `message`/`msg`/`dm` (el envío real
  siempre trae el verbo: `dispatch_message` matchea por `dispatch`). Los 68 tests de Fase 18 siguen verdes.

## Evidencia (re-corrible)

```
python3 platform/gates/tests_recipe_enforcer.py   # 21 PASS · 0 FAIL — invariante §3.5
python3 platform/gates/tests_gates.py             # 68 PASS · 0 FAIL — sin regresión (base Fase 18)
python3 -m pytest platform/sanitizer/tests/ -q    # 11 passed — sanitizer de fórmulas (P014)
```

Cubre: (1a) money_touch `off` IGUAL gatea · (1b) send `off` IGUAL gatea · (1c) omisión no desactiva ·
(2) desconocida-que-escribe fail-closed + control-positivo lectura pasa · (3) la receta agrega, nunca quita ·
(4) `assert_invariant` rechaza una matriz manipulada sin mandatorios.
