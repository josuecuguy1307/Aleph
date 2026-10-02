# T04 — Brief macro que no confunde MoM con YoY

**ID interno:** t04-brief-macro-fred  
**Tier:** average  
**Fricción de onboarding:** GATEADO — requiere API key FRED gratis (registro en fred.stlouisfed.org, 1 minuto)  
**Semilla radar:** T4 de P005-radar-finanzas.md

---

## Qué hace el agente (galería del workshop)

Descarga CPI, desempleo y tasa de referencia de la Fed directamente desde FRED y construye el notebook reproducible que corre de punta a punta. Las variaciones MoM y YoY se calculan con la convención correcta (SAAR donde aplica) — el error clásico del generalista que confunde los dos. Entregable: .ipynb que corre, con gráficos y tabla final lista para incluir en el memo o el report de research.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `fred-mcp-server` | GATEADO — `FRED_API_KEY` gratis | Fuente canónica para series macro (CPI, desempleo, Fed Funds Rate); AV solo trae subset macro |
| `jupyter-mcp-server` | Gate de infra — Jupyter propio | El entregable es el .ipynb que corre; el agente ejecuta código real en el kernel |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `series_ids` | list[string] | `["CPIAUCSL", "UNRATE", "FEDFUNDS"]` | Qué series FRED incluir; el usuario puede agregar (ej. "T10Y2Y" para yield curve) |
| `fecha_inicio` | string YYYY-MM-DD | `"2020-01-01"` | Ventana temporal del análisis |
| `fecha_fin` | string YYYY-MM-DD | `"hoy"` | En blanco = hasta el dato más reciente disponible en FRED |
| `notebook_path` | string | `./brief_macro_<fecha>.ipynb` | Dónde guardar el notebook |
| `incluir_sazonalizacion` | bool | `true` | Si true, usa la serie desestacionalizada de FRED cuando existe (ej. CPIAUCSL ya es SA; FEDFUNDS no aplica) |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo .ipynb | SÍ — primario | El notebook reproducible es el entregable; cualquier colega puede volver a correrlo |
| Email | SÍ — opcional | Enviar el notebook o un PDF export al equipo |
| WhatsApp | SÍ — resumen ejecutivo | En LatAm el analista senior o el cliente piden "¿cómo viene la inflación?" por WA. El agente puede emitir: "CPI EE.UU. +3.2% YoY (abril 2026). Desempleo: 3.9%. Fed Funds: 5.25%. Ver notebook completo en adjunto." Conciso, sin gráficos, enlace al ipynb |

---

## Nota de gate (honestidad)

FRED API key es gratis en fred.stlouisfed.org → My Account → API Keys. Registro de 1 minuto con email. No requiere tarjeta de crédito. El workshop muestra este link al usuario antes de activar el template.
