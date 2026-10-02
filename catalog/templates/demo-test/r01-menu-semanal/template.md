# R01 — Menú semanal equilibrado

**ID interno:** r01-menu-semanal  
**Tier:** average  
**Fricción de onboarding:** CERO-FRICCIÓN (ninguna credencial de tercero)  
**Semilla:** demo-test fixture

---

## Qué hace el agente (galería del workshop)

Planifica tu menú de la semana en segundos. Dices cuántas personas comen, qué restricciones tienen (vegetariano, sin gluten, etc.) y cuánto tiempo quieres cocinar por día. El agente arma 7 cenas equilibradas con variedad de proteínas y verduras, y genera la lista de compras ordenada por sección del supermercado.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `recetas-mcp` | NINGUNO | Búsqueda y escalado de recetas |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `personas` | number | 2 | Cantidad de comensales para calcular porciones |
| `restricciones` | string | "" | Restricciones alimentarias separadas por coma |
| `tiempo_max_min` | number | 45 | Tiempo máximo de cocción por día en minutos |
| `incluir_lista_compras` | boolean | true | Si generar la lista de compras automáticamente |
