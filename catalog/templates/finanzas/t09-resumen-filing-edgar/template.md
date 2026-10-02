# T09 — Resumen del 10-K sin leer 200 páginas

**ID interno:** t09-resumen-filing-edgar  
**Tier:** average  
**Fricción de onboarding:** CERO-FRICCIÓN (SEC EDGAR sin credenciales)  
**Origen:** radar P005 §1 (sec-edgar-mcp, tools analyze_8k + get_filing_sections) + workflow de equity research

---

## Qué hace el agente (galería del workshop)

Le das el ticker de una empresa y el agente lee el 10-K (o 10-Q, o 8-K) desde EDGAR y te devuelve el resumen estructurado: riesgos principales de la sección de riesgo, métricas clave del año vs. año anterior, cambios en la guía de management, y cualquier evento material del 8-K. Todo citado al filing, nada inventado. En vez de leer 200 páginas, lees 2.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `sec-edgar-mcp` | NINGUNO — solo `SEC_EDGAR_USER_AGENT` | Acceso directo a 10-K, 10-Q, 8-K con extracción de secciones; instrucciones anti-alucinación incorporadas en las tool descriptions |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `ticker` | string | — | La empresa a analizar; obligatorio |
| `tipo_filing` | enum: `10-K` / `10-Q` / `8-K` | `10-K` | Qué tipo de filing leer; 10-K es el reporte anual completo |
| `secciones` | list[string] | `["riesgos", "MD&A", "financieros"]` | Qué secciones incluir en el resumen; el usuario puede sacar o agregar |
| `incluir_insider_trading` | bool | `false` | Si true, incluye resumen de Forms 3/4/5 (insider transactions) del período |
| `formato_output` | enum: `markdown` / `txt` / `xlsx` | `markdown` | Formato del resumen entregado |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Texto estructurado (markdown/txt) | SÍ — primario | El resumen del filing es principalmente texto; no requiere spreadsheet |
| Archivo xlsx | SÍ — opcional | Para quien quiere tabular métricas de múltiples filings en un solo lugar |
| Email | SÍ — recomendado | El analista puede enviar el brief al portfolio manager antes del meeting de inversión |
| WhatsApp | SÍ — resumen ultra-corto | "AAPL 10-K FY2025: Revenue +12% YoY, EPS +8%. Riesgo principal: concentración China. Guía FY2026: revenue $420-430B. Sin eventos material 8-K recientes." Para el profesional que lee el brief en el celular antes de una call |

---

## Nota de honestidad

El server EDGAR incluye explícitamente en sus tool descriptions: "ONLY use data from the returned SEC filing. NEVER add external information. PRESERVE EXACT NUMERIC PRECISION - NO ROUNDING." Esto es anti-alucinación at-the-tool-level — la capa más cercana a la fuente.
