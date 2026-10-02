# T03 — Tabla de comparables con fuente citada al filing

**ID interno:** t03-tabla-comparables  
**Tier:** técnico  
**Fricción de onboarding:** CERO-FRICCIÓN (SEC EDGAR sin credenciales; Excel sin credenciales)  
**Semilla radar:** T3 de P005-radar-finanzas.md

---

## Qué hace el agente (galería del workshop)

Toma 4-5 tickers de empresas comparables y el agente construye la tabla de múltiplos de valuación (EV/EBITDA, P/E, EV/Revenue) directamente desde filings reales de la SEC. Cada número tiene footnote que indica exactamente de qué filing proviene. El agregado es la mediana (no la media), los outliers se marcan. Entregable: xlsx con fórmulas vivas y columna de fuente por cada múltiplo.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `sec-edgar-mcp` | NINGUNO — solo `SEC_EDGAR_USER_AGENT` ("Nombre (email)") | Fuente primaria de fundamentals US GAAP con cita al filing exacto |
| `excel-mcp-server` | NINGUNO — solo `EXCEL_FILES_PATH` | Construye el xlsx de comparables con múltiplos calculados como fórmulas vivas |

Este es el template multi-MCP del catálogo: EDGAR → datos con cita → Excel → tabla con fórmulas.

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `tickers` | list[string] | — | Los 4-5 comparables; obligatorio — el agente no puede inferirlos |
| `output_file` | string (path) | `./comparables_<fecha>.xlsx` | Dónde guardar el xlsx |
| `multiplos` | list[enum] | `["EV_EBITDA", "PE", "EV_Revenue"]` | Qué múltiplos incluir; el analista puede sacar o agregar |
| `periodo` | enum: `LTM` / `NTM` / `FY_ultimo` | `LTM` | Convención temporal; LTM (Last Twelve Months) es el estándar de comps |
| `sec_user_agent` | string | `"${SEC_EDGAR_USER_AGENT}"` | Identificación ante la SEC; requisito de cortesía, no clave secreta |

Lo demás queda fijo: instrucciones anti-alucinación del server EDGAR ("ONLY use data from the returned filing, NEVER add external information, PRESERVE EXACT NUMERIC PRECISION"), cálculo de mediana como función Excel, marcado de outliers > 2σ.

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo xlsx | SÍ — primario | La tabla de comps es el entregable para el comité de inversión o el memo |
| Email | SÍ — recomendado | El analista suele enviar la tabla al equipo o al cliente antes del meeting |
| WhatsApp | SÍ — resumen | Para LatAm es común que el cliente o el analista senior pida "dame los múltiplos clave por WA". El agente puede emitir un mensaje corto: "[AAPL] EV/EBITDA: 22x | [MSFT] 20x | Mediana: 21x — ver comps completos en adjunto". El xlsx sigue siendo el artefacto primario |

---

## Nota de gate (honestidad)

EDGAR requiere solo un User-Agent en formato "Nombre (email)" — es un dato público, no una credencial. El agente lo toma del env `SEC_EDGAR_USER_AGENT`. Cero fricción de onboarding.
