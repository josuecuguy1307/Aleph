# T06 — Monitor de mercado que avisa cuando algo se mueve

**ID interno:** t06-monitor-mercado  
**Tier:** average  
**Fricción de onboarding:** GATEADO — requiere Alpha Vantage API key gratis (1 minuto en alphavantage.co)  
**Origen:** radar P005 §1 (Alpha Vantage oficial) + necesidad explícita de monitoring identificada en P004 Concepto B

---

## Qué hace el agente (galería del workshop)

Monitorea precios, variaciones y señales técnicas de los activos que te importan y emite un reporte cuando alguno supera los umbrales que definiste. No es una alerta push automática (eso requiere scheduler) — es el agente que ejecutas cada mañana y recibe el estado del día: qué se movió, cuánto, y si algún indicador técnico cruzó tu umbral. Entregable: reporte estructurado + (opcional) xlsx con el histórico de la sesión.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `marketdata-mcp` (Alpha Vantage) | GATEADO — `ALPHA_VANTAGE_API_KEY` gratis | Fuente oficial de precios, variaciones diarias y 50+ indicadores técnicos; sin scraping |
| `excel-mcp-server` | NINGUNO | Guarda el histórico de sesiones como xlsx para seguimiento |

**Nota sobre el protocolo AV:** el server usa 3 meta-tools (TOOL_LIST → TOOL_GET → TOOL_CALL). El framing del agente documenta este workflow para evitar que el modelo base falle en el primer step.

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `tickers` | list[string] | — | Los activos a monitorear; obligatorio |
| `umbral_variacion_pct` | float | `2.0` | Porcentaje de variación diaria que dispara alerta en el reporte |
| `indicadores_tecnicos` | list[string] | `["RSI", "MACD"]` | Qué indicadores incluir; lista de AV disponible via TOOL_LIST |
| `umbral_rsi_sobrecompra` | int | `70` | RSI encima de esto = señal de sobrecompra en el reporte |
| `umbral_rsi_sobreventa` | int | `30` | RSI debajo de esto = señal de sobreventa |
| `guardar_xlsx` | bool | `true` | Si true, guarda el snapshot en xlsx acumulativo |
| `output_xlsx` | string | `./monitor_<fecha>.xlsx` | Path del xlsx de historial |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Texto estructurado (reporte) | SÍ — primario | Lista de activos con variación, señales técnicas y alertas |
| Archivo xlsx | SÍ — secundario | Historial acumulativo de sesiones para análisis de tendencias |
| Email | SÍ — recomendado | Para recibir el reporte de cada mañana sin abrir la app |
| WhatsApp | SÍ — caso de uso principal en LatAm | "AAPL -3.1% (alerta). RSI=28 (sobreventa). BTC +2.3%. SPY plano. Ver reporte completo en adjunto." Este es el template donde WhatsApp tiene más sentido como canal primario de consumo — el profesional lo lee en el celular de camino a la oficina |

---

## Nota de gate (honestidad)

Alpha Vantage free tier tiene rate limits no publicados oficialmente en la página del MCP (nit honesto del belt). Para monitoring de 5-10 tickers con indicadores técnicos, el free tier debería ser suficiente en uso diario. Si el usuario tiene carteras grandes (20+ tickers), puede necesitar el premium tier ($50/mes). El workshop declara esta incertidumbre.
