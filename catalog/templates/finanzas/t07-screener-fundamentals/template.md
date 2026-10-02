# T07 — Screener de fundamentals que no alucina números

**ID interno:** t07-screener-fundamentals  
**Tier:** average  
**Fricción de onboarding:** CERO-FRICCIÓN (SEC EDGAR sin credenciales + Excel sin credenciales)  
**Origen:** radar P005 §1 (sec-edgar-mcp + haris-musa) + convención de screener de buy-side

---

## Qué hace el agente (galería del workshop)

Le das una lista de tickers y un criterio de filtro (P/E < X, crecimiento de revenue > Y%) y el agente descarga los fundamentals reales de la SEC — no de un agregador que puede estar desactualizado o equivocado — y te devuelve el xlsx con qué empresas pasan el filtro y cuáles no. Cada número tiene la cita exacta del filing del que salió.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `sec-edgar-mcp` | NINGUNO — solo `SEC_EDGAR_USER_AGENT` | Fuente primaria; las descripciones de tools del server tienen instrucciones anti-alucinación incorporadas ("ONLY use data from the returned SEC filing") |
| `excel-mcp-server` | NINGUNO | Construye el xlsx de resultados del screening con fórmulas de filtro |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `tickers` | list[string] | — | El universo a screenear; obligatorio |
| `filtros` | list[dict] | — | Criterios: `[{"metrica": "PE", "operador": "<", "valor": 20}]`; el usuario define qué busca |
| `metricas_mostrar` | list[string] | `["PE", "EV_EBITDA", "Revenue_Growth", "Debt_Equity"]` | Columnas del xlsx de output |
| `output_file` | string | `./screener_<fecha>.xlsx` | Path del resultado |
| `periodo` | enum: `LTM` / `FY_ultimo` | `LTM` | Qué período usar para los cálculos |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo xlsx | SÍ — primario | La tabla de screening con cita al filing es el entregable |
| Email | SÍ — opcional | Para distribuir el screener al equipo o a clientes |
| WhatsApp | SÍ — resumen | "Screener P/E<20 + Revenue Growth>15%: 3 empresas pasan (AAPL, NVDA, MSFT). Ver xlsx completo →". Útil para el analista que quiere validación rápida con el portfolio manager |

---

## Nota de honestidad

Este template cubre solo empresas cotizadas en EE.UU. con filings en SEC EDGAR. Para empresas latinas o europeas, EDGAR no aplica — el cinturón no tiene server verificado para esas fuentes todavía. El workshop declara este límite al usuario si los tickers ingresados no tienen CIK en EDGAR.
