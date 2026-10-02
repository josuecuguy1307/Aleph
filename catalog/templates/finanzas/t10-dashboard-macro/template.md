# T10 — Tablero macro en Excel que se actualiza con un comando

**ID interno:** t10-dashboard-macro  
**Tier:** average  
**Fricción de onboarding:** GATEADO — requiere FRED API key gratis (1 minuto)  
**Origen:** radar P005 §1 (fred-mcp-server + excel-mcp-server) + demanda de reporting de economistas y equipos de research macro en LatAm

---

## Qué hace el agente (galería del workshop)

Construye un Excel de tablero macro actualizable: descarga las series de FRED que te importan (CPI, desempleo, tasa de política monetaria, spread de crédito), calcula las variaciones con la convención correcta, y genera el xlsx con una hoja de datos crudos y una hoja de tablero con las métricas formateadas. La próxima vez que ejecutas el agente, sobreescribe los datos con los valores más recientes — mismo formato, sin trabajo manual.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `fred-mcp-server` | GATEADO — `FRED_API_KEY` gratis | Fuente canónica de datos macro; 3 tools (fred_search, fred_browse, fred_get_series) con transformaciones SAAR incorporadas |
| `excel-mcp-server` | NINGUNO | Construye y actualiza el tablero xlsx con fórmulas vivas |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `series_fred` | list[string] | `["CPIAUCSL", "UNRATE", "FEDFUNDS", "T10Y2Y"]` | Qué series incluir; el usuario puede agregar series FRED por ID |
| `output_file` | string | `./macro_dashboard.xlsx` | Mismo path cada vez = actualización in-situ |
| `ventana_anios` | int | `5` | Cuántos años de historia incluir en el xlsx |
| `calcular_variaciones` | bool | `true` | Si true, incluye columnas MoM y YoY con convención correcta |
| `hoja_cruda` | string | `"Datos"` | Nombre de la hoja con series crudas |
| `hoja_tablero` | string | `"Tablero"` | Nombre de la hoja formateada para presentación |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo xlsx | SÍ — primario | El tablero macro actualizable es el entregable central |
| Email | SÍ — recomendado | Para distribuir el tablero mensual al equipo directivo o a clientes |
| WhatsApp | SÍ — resumen del tablero | "Actualización macro: CPI +3.2% YoY, Fed 5.25%, Curva invertida (-30bp). Dashboard completo en adjunto." Ideal para equipos de research que distribuyen el brief semanal por WA a sus clientes o al equipo senior |

---

## Diferencia con T04 (Brief macro FRED)

T04 produce un notebook .ipynb reproducible para el analista que quiere correr código. T10 produce un Excel actualizable para el equipo que vive en Excel y quiere un tablero que no requiera código. Mismo belt, diferente artefacto y audiencia.
