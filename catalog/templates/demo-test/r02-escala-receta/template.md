# R02 — Escalador de receta para eventos

**ID interno:** r02-escala-receta  
**Tier:** average  
**Fricción de onboarding:** GATEADO — requiere cuenta en Spoonacular API (plan gratis disponible en spoonacular.com)  
**Semilla:** demo-test fixture

---

## Qué hace el agente (galería del workshop)

Tienes una receta para 4 personas y necesitas hacerla para 40. El agente escala todos los ingredientes con precisión, ajusta los tiempos de cocción por lote, y te avisa qué utensilios necesitas para esa cantidad. Ideal para eventos, catering o cocina en cantidad.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `spoonacular-mcp` | GATEADO — `SPOONACULAR_API_KEY` gratis | Base de datos de ingredientes y tiempos de cocción |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `nombre_receta` | string | — | Nombre de la receta a escalar |
| `porciones_original` | number | 4 | Porciones de la receta original |
| `porciones_objetivo` | number | 20 | Porciones que necesitas producir |
| `ajustar_tiempos` | boolean | true | Si recalcular tiempos de cocción para la nueva cantidad |
