# T01 — Cierre mensual que se reconcilia solo

**ID interno:** t01-cierre-mensual  
**Tier:** average  
**Fricción de onboarding:** CERO-FRICCIÓN (ninguna credencial de tercero)  
**Semilla radar:** T1 de P005-radar-finanzas.md

---

## Qué hace el agente (galería del workshop)

Toma tu archivo Excel de transacciones del mes, lo limpia (fechas mixtas, duplicados, categorías inconsistentes), y produce una hoja de Estado de Resultados con SUMIFS vivos — no valores pegados. Los totales recalculan solos si cambias un dato. Formato NIIF: negativos entre paréntesis, subtotales por categoría, estructura de ingresos→EBITDA→utilidad neta.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `excel-mcp-server` | NINGUNO — solo `EXCEL_FILES_PATH` | Lee el xlsx crudo, escribe fórmulas vivas, produce el entregable final |

Servers del belt NO usados en este template: sheets (no aplica — flujo local), stata, alphavantage, secedgar, fred, jupyter.

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `input_file` | string (path absoluto) | — | El xlsx de transacciones del mes; sin él el agente no puede empezar |
| `output_file` | string (path absoluto) | `<mismo dir>/cierre_<mes>.xlsx` | Dónde guardar el entregable; default evita sobreescribir el original |
| `mes_label` | string | `"" (detectar del archivo)"` | Etiqueta del mes en los encabezados del estado de resultados (ej. "Junio 2026") |
| `columna_fecha` | string | `"Fecha"` | Nombre de la columna de fecha en el xlsx — varía por empresa |
| `columna_monto` | string | `"Monto"` | Nombre de la columna de importe — varía por empresa |
| `columna_categoria` | string | `"Categoría"` | Nombre de la columna de categoría contable — varía por empresa |
| `estructura` | enum: `NIIF` / `GAAP` / `simple` | `NIIF` | Formato del estado de resultados: orden de líneas, convención de negativos |

Lo demás queda fijo en el framing: reglas de limpieza (dedup por fecha+monto+categoría, normalización de fechas con dateutil), estructura de subtotales, instrucciones anti-alucinación de números.

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo xlsx | SÍ — primario | El entregable es el archivo con fórmulas vivas; es el canal natural |
| Email | SÍ — opcional | El analista puede querer enviarlo al CFO directamente desde el agente |
| WhatsApp | NO | El cierre mensual es un archivo xlsx con fórmulas — no es un mensaje de texto. Un resumen del estado podría enviarse por WhatsApp, pero el artefacto primario no cabe en ese canal. Evaluar en v2 si hay demanda de "resumen ejecutivo por WA" |

---

## Framing (resumen para el assembler)

Eres un agente de contabilidad para profesionales de finanzas en Latinoamérica. Tu única fuente de verdad son los datos del archivo Excel que te dan. Nunca inventes números. Usas fórmulas Excel vivas (SUMIFS, no valores pegados). Sigues la estructura NIIF por defecto: ingresos operativos → costos → utilidad bruta → gastos operativos → EBITDA → depreciación → EBIT → intereses → EBT → impuestos → utilidad neta. Negativos entre paréntesis. Al terminar confirmas que los totales cierran recalculando desde los datos crudos.
