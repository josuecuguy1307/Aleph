# T05 — Varianza budget-vs-actual que el equipo puede leer de un vistazo

**ID interno:** t05-varianza-fp-a  
**Tier:** average  
**Fricción de onboarding:** GATEADO — requiere Google Cloud service account u OAuth (decisión del operador)  
**Semilla radar:** T5 de P005-radar-finanzas.md

---

## Qué hace el agente (galería del workshop)

Toma el Google Sheet donde tienes tu histórico y tu presupuesto, y agrega una hoja de varianzas en el mismo spreadsheet. Formato FP&A estándar: favorable (F) / desfavorable (U) con el signo correcto por convención, formato condicional verde/rojo, y un bridge que explica las tres mayores varianzas en texto plano. Nadie tiene que hacer nada manualmente después.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `mcp-google-sheets` | GATEADO — service account Google Cloud o OAuth | El sheet vive en Google Drive; no hay forma de accederlo sin credencial Google |

**Nota de gate:** este es el único template del catálogo con el gate de credenciales más pesado. La ventaja: el entregable vive en el sheet compartido, no en un archivo local que hay que distribuir. Para el flujo FP&A colaborativo (equipo de finanzas + CFO en el mismo sheet), el gate vale la pena.

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `spreadsheet_id` | string | — | El ID del Google Sheet (en la URL: .../spreadsheets/d/**ID**/edit); obligatorio |
| `hoja_actual` | string | `"Actual"` | Nombre de la pestaña con los valores reales |
| `hoja_budget` | string | `"Budget"` | Nombre de la pestaña con el presupuesto |
| `hoja_varianzas` | string | `"Varianzas"` | Nombre de la pestaña a crear/sobrescribir con las varianzas |
| `convencion_fu` | enum: `ingresos-positivo-F` / `costos-positivo-F` | `ingresos-positivo-F` | Convención de signo FP&A: F si ingreso > budget; U si costo > budget |
| `top_varianzas` | int | `3` | Cuántas varianzas explicar en el bridge de texto |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Google Sheet (in-situ) | SÍ — primario | El entregable es la hoja nueva en el mismo spreadsheet compartido |
| Email | SÍ — opcional | Link al sheet o export PDF para quien no tiene acceso |
| WhatsApp | SÍ — resumen | Para LatAm: "Varianza total mes: -$42k (U). Top 3: [Ventas -$30k, Marketing +$5k F, COGS -$17k U]. Ver detalle → [link al sheet]". Conciso y accionable para el CEO o CFO por WA |

---

## Nota de gate (honestidad)

Este template es el único del catálogo que requiere configuración de Google Cloud. El workshop debe mostrar instrucciones explícitas: (1) crear proyecto GCP, (2) habilitar Sheets API, (3) crear service account, (4) compartir el sheet con el email de la service account. Si Aleph decide proveer una cuenta de servicio compartida (decisión del operador), el usuario solo pega el spreadsheet_id. Esta diferencia de fricción debe ser visible en la galería del workshop.
