# T08 — Backtest de estrategia que corre y muestra los números

**ID interno:** t08-notebook-backtesting  
**Tier:** técnico  
**Fricción de onboarding:** GATEADO — requiere (a) Alpha Vantage API key gratis y (b) Jupyter propio con jupyter-collaboration  
**Origen:** radar P005 §1 (jupyter-mcp-server + Alpha Vantage) + perfil de analista quant del nicho finanzas

---

## Qué hace el agente (galería del workshop)

Describes tu estrategia de trading en lenguaje natural ("comprar cuando RSI cruza 30 al alza, vender cuando cruza 70") y el agente descarga el histórico de precios, implementa la estrategia en Python, la corre sobre los datos y produce el notebook con las métricas de performance: retorno total, Sharpe ratio, max drawdown, win rate. No te crees el backtest — lo ejecutas con código real.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `marketdata-mcp` (Alpha Vantage) | GATEADO — `ALPHA_VANTAGE_API_KEY` gratis | Datos históricos de precios (TIME_SERIES_DAILY) para el backtest |
| `jupyter-mcp-server` | Gate de infra — Jupyter propio | El agente implementa la estrategia como código Python y la corre en el kernel; el entregable es el .ipynb reproducible |

**Nota de presupuesto:** este es el template con mayor consumo de tokens del catálogo — el agente genera código, lo ejecuta, interpreta resultados y puede iterar. Se recomienda modelo frontier para tier técnico (Opus/equivalente) para mayor calidad de código. Con modelos OSS pequeños el riesgo de código con errores es mayor.

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `ticker` | string | — | El activo sobre el que hacer el backtest; obligatorio |
| `estrategia_descripcion` | string | — | Descripción en lenguaje natural de la estrategia; obligatorio |
| `fecha_inicio` | string YYYY-MM-DD | `"2020-01-01"` | Inicio del período de backtest |
| `fecha_fin` | string YYYY-MM-DD | `"hoy"` | Fin del período |
| `capital_inicial` | float | `10000` | Capital simulado en USD para el cálculo de retorno monetario |
| `notebook_path` | string | `./backtest_<ticker>_<fecha>.ipynb` | Dónde guardar el notebook |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo .ipynb | SÍ — primario | El backtest reproducible es el artefacto; cualquiera puede volver a correrlo con sus propios datos |
| Email | SÍ — opcional | Para compartir el notebook con el equipo o el portfolio manager |
| WhatsApp | NO en este caso | El backtest es un artefacto técnico denso. Un resumen muy reducido (Sharpe=1.2, MaxDD=-15%, Retorno=+42%) podría ir por WA, pero el tier técnico que usa este template prefiere ver el notebook completo. No se prioriza WA aquí |

---

## Nota de honestidad sobre backtesting

El backtest que produce este agente es un análisis histórico simple (sin costos de transacción, sin slippage, sin datos tick). Es un punto de partida para la idea, no una validación de producción. El framing del agente lo declara explícitamente al usuario antes de mostrar resultados.
