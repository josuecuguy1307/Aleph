# FINANZAS — Belt-Spec: Agente de Finanzas v0

**Qué es:** Cinturón MCP del agente de finanzas (nicho #1 de NORTH) — Excel/Sheets local y colaborativo, econometría Stata, datos de mercado/fundamentals/macro y data science reproducible.
**Fecha:** 2026-06-11
**Estado:** ACTIVO — primera entrada de PRODUCCIÓN del catálogo (stem.md y writer-es.md son fixtures históricos que validan el schema).
**Fuente original:** no es migración. Construida desde el radar `org/artifacts/P005-radar-finanzas.md` (RADAR tick #1, 17 servers evaluados con 18 fetches reales el 2026-06-11).
**Regla F5 cumplida:** sondas JSON-RPC stdio EJECUTADAS de verdad por el Belt Curator (Curation) el 2026-06-11 sobre los 3 servers sin credenciales + 2 de los gateados; output crudo pegado abajo. Los 2 servers con gate duro (Stata/licencia, Sheets/OAuth) quedan en estado honesto "solo-spec" con el intento crudo de arranque pegado. NUNCA se declara "test real ✓" sin output ejecutado (lección 0003).

> **Picks = los 7 del radar P005, sin sustituciones.** Cambios de server requieren justificación escrita; no hubo ninguno. La kill-list de P005 (§2 de ese doc: negokaz, SepineTam, freema, yahoo-finance, massive/polygon, data-exploration, xero, ms-365) se REFERENCIA, no se re-litiga.

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Excel local | `excel-mcp-server` (PyPI `excel-mcp-server`, stdio) | `negokaz/excel-mcp-server` (kill-list: Windows-only, stale) | $0 | ninguna | test real ✓ |
| Google Sheets | `mcp-google-sheets` (PyPI, stdio) | `freema/mcp-gsheets` (kill-list: 73★ vs 903★) | $0 | gate Google Cloud (service account / OAuth) | solo-spec (links verificados, sin ejecución) |
| Econometría Stata | `mcp-stata` (PyPI `mcp-stata`, stdio/uvx) | `hanlulong/stata-mcp` (acoplado a VS Code) | $0 (server) | gate de LICENCIA Stata 17+ del usuario | solo-spec (links verificados, sin ejecución) |
| Datos de mercado | Alpha Vantage `marketdata-mcp` (PyPI `marketdata-mcp-server`, stdio) o MCP oficial remoto HTTP | `financial-datasets/mcp-server` (key propia) | $0 (free tier) | gate de key gratis (`ALPHA_VANTAGE_API_KEY`) | test real ✓ (init+tools/list con key dummy) |
| Fundamentals US GAAP | `sec-edgar-mcp` (PyPI, stdio) | `financial-datasets/mcp-server` | $0 | ninguna (solo `SEC_EDGAR_USER_AGENT`) | test real ✓ |
| Macro | `fred-mcp-server` (npm, stdio) | subset macro de Alpha Vantage | $0 | gate de key FRED gratis (`FRED_API_KEY`) | test real ✓ (init+tools/list con key dummy) |
| Data science | `jupyter-mcp-server` (PyPI, stdio) | `reading-plus-ai/...` (kill-list: ejecuta Python sin sandbox) | $0 | gate de infra (Jupyter propio + `JUPYTER_TOKEN`) | test real ✓ |

Servers activos en v0: **7** (excel local sin fricción · sheets colaborativo · Stata econometría · Alpha Vantage mercado · SEC EDGAR fundamentals · FRED macro · Jupyter data science). Sin solapamiento funcional decisivo; mercado y fundamentals se solapan parcialmente (AV trae fundamentals como subset) y se resuelve por fuente: EDGAR = primaria con cita al filing, AV = mercado/precio/técnicos.

---

## Matriz de credenciales / gates (el `done` la exige)

Tres clases de fricción de onboarding, ordenadas de menor a mayor:

| Clase | Servers | Qué pide | Quién lo provee | Bloquea v0 |
|---|---|---|---|---|
| **CERO-FRICCIÓN** | `excel-mcp-server`, `sec-edgar-mcp`, `jupyter-mcp-server` | Nada de terceros. Excel: solo `EXCEL_FILES_PATH`. EDGAR: solo un `SEC_EDGAR_USER_AGENT` ("Nombre (email)", dato público). Jupyter: infra local propia (`JUPYTER_TOKEN`) — NO cuenta de tercero. | El propio deploy de Puppet | No |
| **GATE DE CUENTA / KEY** | `mcp-google-sheets`, Alpha Vantage `marketdata-mcp`, `fred-mcp-server` | AV: `ALPHA_VANTAGE_API_KEY` (gratis, alphavantage.co). FRED: `FRED_API_KEY` (gratis). Sheets: proyecto Google Cloud + service account u OAuth. | El usuario final (key propia) o Puppet (cuenta de servicio compartida) — **decisión del operador** sobre quién paga/posee | No para AV/FRED/EDGAR; Sheets sí condiciona el flujo colaborativo |
| **GATE DE LICENCIA** | `mcp-stata` | Stata 17+ (MP/SE/BE) licenciado e instalado localmente. El server es $0 y AGPL; el gate es la **licencia comercial de Stata del usuario** | El usuario final (licencia Stata) — **gateada — decisión del operador / usuario** | Sí para la pata Stata; mitigado por pandas/Jupyter (ver §3) |

Nota de seguridad: ninguna key se escribió ni imprimió en este documento ni en las sondas. Donde se necesitó una credencial para arrancar, se usó un literal `DUMMY_PROBE_KEY` no funcional cuyo único efecto es pasar el chequeo de "variable presente"; la validación real contra el proveedor ocurre recién en la primera llamada de datos.

---

## 1. Excel local — `excel-mcp-server`

**Instalación:** `uvx excel-mcp-server stdio` (stdio). **Licencia:** MIT. **Credenciales:** ninguna. **Ejecución:** 100% local (openpyxl; NO requiere Excel instalado).
**Env:** `EXCEL_FILES_PATH=<dir>`. En modo stdio los paths de tool deben ser **absolutos** (ver nit).

**Test real — crear workbook + escribir datos + aplicar fórmula viva + leer de vuelta (ejecutado 2026-06-11):**
```
Request: initialize
Output:  {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{...},"serverInfo":{"name":"excel-mcp","version":"1.27.2"},"instructions":"Excel MCP Server for manipulating Excel files"}}

Request: tools/call create_workbook {"filepath":"/tmp/finanzas-probe/excel_files/probe.xlsx"}
Output:  {"content":[{"type":"text","text":"Created workbook at /tmp/finanzas-probe/excel_files/probe.xlsx"}],"isError":false}

Request: tools/call write_data_to_excel {"filepath":".../probe.xlsx","sheet_name":"Sheet1","data":[["a","b","sum"],[2,3,null],[10,20,null]]}
Output:  {"content":[{"type":"text","text":"Data written to Sheet1"}],"isError":false}

Request: tools/call apply_formula {"filepath":".../probe.xlsx","sheet_name":"Sheet1","cell":"C2","formula":"=A2+B2"}
Output:  {"content":[{"type":"text","text":"Applied formula '=A2+B2' to cell C2"}],"isError":false}

Request: tools/call read_data_from_excel {"filepath":".../probe.xlsx","sheet_name":"Sheet1","start_cell":"A1","end_cell":"C3"}
Output:  {"range":"A1:C3","sheet_name":"Sheet1","cells":[
           {"address":"A2","value":2,...},{"address":"B2","value":3,...},
           {"address":"C2","value":"=A2+B2",...}, ... ]}
```

**Test real — la fórmula es VIVA, no pegada (verificación a nivel de archivo .xlsx, ejecutado 2026-06-11):**
```
Request: unzip probe.xlsx → xl/worksheets/sheet1.xml, grep celda C2
Output:  <c r="C2"><f>A2+B2</f><v /></c>
```
[Interpretación: C2 contiene el elemento `<f>A2+B2</f>` — una fórmula Excel viva en el XML del archivo, no un valor numérico pegado. Esto es exactamente el requisito E3 del task-set P005 ("SUMIFS vivos, no valores pegados"). El server lee la fórmula de vuelta como `"=A2+B2"`, confirmando round-trip.]

**Criterio de cierre (Lead):** test feliz superado de punta a punta (crear → escribir → fórmula viva → leer) + verificación a nivel de archivo de que la fórmula persiste como `<f>`. Cubre E1 (leer xlsx crudo) y E3 (producir xlsx con fórmulas vivas) sin pedir nada al usuario — el server sin fricción de onboarding del nicho.

**Nits honestos:**
- **Discrepancia con el radar:** P005 reportó v0.1.8 con 31 tools. La sonda arrancó `version: 1.27.2` con **25 tools** en `tools/list` (apply_formula, validate_formula_syntax, format_range, read/write_data_to_excel, create_workbook/worksheet, create_chart/pivot_table/table, copy/delete/rename_worksheet, get_workbook_metadata, merge/unmerge/get_merged_cells, copy_range, delete_range, validate_excel_range, get_data_validation_info, insert_rows/columns, delete_sheet_rows/columns). Mismo proyecto, versión más nueva — el radar usó el versionado viejo del repo; el publicado en PyPI es 1.27.2. No cambia el pick. Surface más madura que la documentada.
- En stdio el server **rechaza paths relativos** ("Invalid filename: must be an absolute path when not in SSE mode"). El Agent Runtime debe inyectar paths absolutos. Documentado para cableado (§9).

---

## 2. Google Sheets — `mcp-google-sheets`

**Instalación:** `uvx mcp-google-sheets` (stdio). **Licencia:** MIT. **Credenciales:** **gate Google Cloud** — 4 modos (service account headless [recomendado], OAuth 2.0 interactivo, credencial base64 inyectada, ADC). **Ejecución:** local con red a la API de Google.

**Estado: solo-spec (links verificados, sin ejecución de tools).** El server **falla al arrancar sin credenciales** — no llega a `tools/list`. Output crudo del intento (ejecutado 2026-06-11):
```
Request: uvx mcp-google-sheets  (sin GOOGLE_APPLICATION_CREDENTIALS, sin credentials.json)
Output (stderr):
  Tool filtering disabled. All tools are enabled.
  Trying OAuth authentication flow
  Error with OAuth flow: [Errno 2] No such file or directory: 'credentials.json'
  Attempting to use Application Default Credentials (ADC)
  ADC will check: GOOGLE_APPLICATION_CREDENTIALS, gcloud auth, and metadata service
  Error using Application Default Credentials: Your default credentials were not found...
```
[Interpretación: a diferencia de fred/alpha-vantage (que listan tools con key dummy y validan recién en la llamada), `mcp-google-sheets` **gatea la construcción del cliente al arranque**: sin un `credentials.json` o ADC válido, el proceso no expone `tools/list`. Por eso el estado honesto es solo-spec, no "test real ✓". El surface (19 tools: list/create_spreadsheet, get_sheet_data/formulas, update_cells, batch_update_cells, share_spreadsheet, add_chart, find_in_spreadsheet, etc.) queda verificado por el radar vía fetch, no por ejecución.]

**Criterio de cierre (Lead):** ejecución real PENDIENTE de una service account de Google Cloud. Gate de cuenta — **decisión del operador** sobre si Aleph provee una cuenta de servicio compartida o el usuario trae su proyecto GCP. Cubre el flujo colaborativo (FP&A comparte sheets); el flujo de archivo local lo cubre §1 sin este gate.

**Nits honestos:** es la categoría con el gate de onboarding más pesado del lote después de Stata. El task T5 del radar (varianza budget-vs-actual en Sheets) existe **a propósito** para medir el flujo de onboarding con cuenta — no se puede sondar sin ella.

---

## 3. Econometría Stata — `mcp-stata` — [DISTINCIÓN MOTOR-VS-MCP]

**Instalación:** `uvx mcp-stata` (stdio, standalone, sin IDE). **Licencia:** AGPL-3.0 (gate de licencia para redistribución comercial; para USO no bloquea). **Credenciales:** **gate de LICENCIA — Stata 17+ (MP/SE/BE) licenciado e instalado localmente** (`STATA_PATH`). **Ejecución:** local.

**Estado: solo-spec (links verificados, sin ejecución).** Stata NO está instalado en esta máquina (gate de licencia confirmado). El server **gatea al arranque**: intenta descubrir el binario Stata y aborta antes de `tools/list`. Output crudo del intento (ejecutado 2026-06-11):
```
Request: uvx mcp-stata  (sin Stata instalado, STATA_PATH no configurado)
Output (stderr):
  [mcp-stata] INFO: server starting
  [mcp-stata] INFO: version: 3.3.0
  [mcp-stata] INFO: STATA_PATH env at startup: <not set>
  ERROR  Stata discovery failed: Could not automatically locate Stata.
         To fix this issue:
         1. Set STATA_PATH to point to your Stata executable, ...

Chequeo del gate (ejecutado 2026-06-11):
  which stata stata-mp stata-se stata-be  →  not found (los 4)
  ls /Applications/Stata*                  →  no matches
```
[Interpretación: el server arranca (v3.3.0, coincide con el radar), pero su discovery de Stata falla y NUNCA expone tools sin un binario Stata local. Esto es un gate de LICENCIA, no de cuenta: la licencia es del USUARIO, no del server. El paquete `mcp-stata` 3.3.0 está vivo en PyPI (124 releases verificadas). El surface (10 tools: stata_run, stata_get_results r()/e()/s(), stata_load_data, stata_inspect_data, etc.) queda verificado por el radar.]

**Decisión motor-vs-MCP (la pata data science cubre la espera de la licencia):** Stata es un MOTOR licenciado, no un wrapper instalable libremente — el gate es estructural, no de madurez del MCP. Mientras la licencia Stata del usuario final no esté disponible, **pandas/statsmodels corriendo dentro de `jupyter-mcp-server` (§7) cubren la pata econométrica** (regresión OLS/efectos fijos, errores clusterizados vía statsmodels/linearmodels) con cero gate de licencia. La diferencia real: Stata expone `r()/e()` nativos (lo que pide E2 del task T2: verificar resultados de regresión por tool) y la convención de tabla estilo journal/esttab que un generalista no produce; statsmodels lo aproxima pero no es idéntico. **Recomendación: `mcp-stata` es el pick canónico para el usuario QUE YA TIENE Stata; para el resto, el belt degrada a Jupyter+statsmodels y lo declara explícito en el onboarding** (pregunta #1 de la Guía en P005 §4: "¿Dónde vive tu trabajo: Excel/Sheets/Stata/Jupyter?").

**Criterio de cierre (Lead):** ejecución real PENDIENTE de una licencia Stata del usuario. Gate de licencia — **gateada — decisión del operador / usuario final**. No bloquea v0: la degradación a Jupyter+pandas mantiene la pata econométrica viva.

**Nits honestos:** AGPL-3.0 implica cuidado en redistribución comercial (P005 lo marca; para uso interno/usuario no bloquea). `hanlulong/stata-mcp` es alternativa pero acopla a VS Code (2 tools vs 10) — queda en radar, no como pick.

---

## 4. Datos de mercado — Alpha Vantage `marketdata-mcp`

**Instalación local:** `uvx --from marketdata-mcp-server marketdata-mcp` (stdio). **Instalación remota (oficial del vendor):** HTTP `https://mcp.alphavantage.co/mcp?apikey=KEY` (cero instalación). **Licencia:** del vendor. **Credenciales:** **gate de key GRATIS** — env `ALPHA_VANTAGE_API_KEY` (alphavantage.co/support/#api-key). **Ejecución:** local con red (o 100% remoto).

**Test real — initialize + tools/list con key DUMMY (ejecutado 2026-06-11):**
```
Request: uvx --from marketdata-mcp-server marketdata-mcp   (env ALPHA_VANTAGE_API_KEY=DUMMY_PROBE_KEY)
Request: initialize
Output:  {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"alphavantage-mcp","version":"1.0.0"}}}

Request: tools/list
Output:  {"tools":[
           {"name":"TOOL_LIST","description":"List all available Alpha Vantage API tools... You MUST call TOOL_GET(tool_name) to retrieve the full inputSchema before calling TOOL_CALL..."},
           {"name":"TOOL_GET","description":"Get the full schema for one or more tools..."},
           {"name":"TOOL_CALL","description":"Execute a tool by name with the provided arguments..."}
         ]}
```
[Interpretación + SORPRESA vs radar: el server arranca y lista tools con una key DUMMY — la key real se valida recién en la llamada de datos, no al arranque. PERO el surface NO son los "100+ tools en 9 categorías" como top-level: el server expone **3 meta-tools de descubrimiento progresivo** (`TOOL_LIST` → `TOOL_GET` → `TOOL_CALL`). El agente ve 3 tools; los 100+ (TIME_SERIES_DAILY, etc.) se alcanzan A TRAVÉS de ese protocolo de 3 pasos. Esto es el "progressive tool discovery / token-eficiente" que el radar mencionó al pasar, pero la implicación práctica para el cableado es fuerte: el agente debe conocer el workflow TOOL_LIST→TOOL_GET→TOOL_CALL o las llamadas fallan. Esto se parece estructuralmente a los meta-tools de massive/polygon que el radar descartó — la diferencia es que AV es oficial y estable, no experimental.]

**Test real adicional — el env var del radar estaba mal (ejecutado 2026-06-11):**
```
Request: marketdata-mcp con ALPHAVANTAGE_API_KEY=DUMMY  (var SIN guión, como sugería el contexto)
Output (stderr):  ERROR av_mcp.main:serve - API key required. Provide via argument or ALPHA_VANTAGE_API_KEY environment variable
                  Error: API key required
                  Usage: marketdata-mcp YOUR_API_KEY  /  ALPHA_VANTAGE_API_KEY=YOUR_KEY marketdata-mcp
```
[Interpretación: el nombre correcto de la variable es `ALPHA_VANTAGE_API_KEY` (con guión bajo entre ALPHA y VANTAGE), y el ejecutable es `marketdata-mcp` (no `marketdata-mcp-server`, que es el nombre del paquete PyPI). Dato corregido para el cableado.]

**Criterio de cierre (Lead):** init + tools/list ejecutados (test real ✓); llamada de datos real PENDIENTE de una key gratis (gate de cuenta — el usuario la saca en 1 minuto). El pick de mercado del belt: oficial, opción remota (cero instalación) y la key es del usuario.

**Nits honestos:** rate limits del free tier no publicados en la página del MCP — sondear en el wiring. El protocolo de 3 meta-tools añade superficie de error si el modelo base es pequeño; el framing del agente debe documentar el workflow. Alternativa `financial-datasets/mcp-server` (10 tools directos, sin meta-protocolo) si AV ratelimitea o si se prefiere surface plano.

---

## 5. Fundamentals US GAAP — `sec-edgar-mcp`

**Instalación:** `uvx sec-edgar-mcp` (stdio). **Licencia:** AGPL-3.0 (licencia comercial disponible). **Credenciales:** **ninguna** — solo `SEC_EDGAR_USER_AGENT` ("Nombre (email)", requisito de cortesía de la SEC, datos públicos). **Ejecución:** local con red a la API pública de la SEC.

**Test real — initialize + tools/list + llamada real a la API de la SEC (ejecutado 2026-06-11):**
```
Request: uvx sec-edgar-mcp   (env SEC_EDGAR_USER_AGENT="Aleph Probe (contact@aleph.app)")
Request: initialize
Output:  {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18",...,"serverInfo":{"name":"SEC EDGAR MCP","version":"1.27.2"}}}

Request: tools/list
Output:  21 tools: get_cik_by_ticker, get_company_info, search_companies, get_company_facts,
         get_recent_filings, get_filing_content, analyze_8k, get_filing_sections, get_financials,
         get_segment_data, get_key_metrics, compare_periods, discover_company_metrics,
         get_xbrl_concepts, discover_xbrl_concepts, get_insider_transactions, get_insider_summary,
         get_form4_details, analyze_form4_transactions, analyze_insider_sentiment, get_recommended_tools

Request: tools/call get_cik_by_ticker {"ticker":"AAPL"}
Output:  {"content":[{"type":"text","text":"{
           \"success\": true,
           \"cik\": \"0000320193\",
           \"ticker\": \"AAPL\",
           \"suggestion\": \"Use CIK '0000320193' instead of ticker 'AAPL' for more reliable and faster API calls\"
         }"}],"isError":false}
```
[Interpretación: el server resolvió AAPL → CIK `0000320193` consultando la API LIVE de la SEC EDGAR (sin key, solo User-Agent). 0000320193 es el CIK real de Apple Inc. — número correcto, no alucinado. Esto es la pata fundamentals end-to-end: una tool real contra la fuente primaria. Las descripciones de tools incluyen instrucciones anti-alucinación ("ONLY use data from the returned SEC filing. NEVER add external information. PRESERVE EXACT NUMERIC PRECISION - NO ROUNDING"), exactamente lo que pide E4 (cita al filing).]

**Criterio de cierre (Lead):** test feliz superado de punta a punta — init + 21 tools + llamada real a la SEC con CIK correcto. La fuente PRIMARIA (no agregador) para fundamentals US GAAP — clave para E4 (convenciones del campo) y para valuación con cita al filing (task T3). Cero fricción de credenciales.

**Nits honestos:**
- **Discrepancia con el radar:** P005 reportó v1.0.8 con ~316★. La sonda arrancó `version: 1.27.2`. (Curiosamente, 3 de los servers Python del lote — excel, sec-edgar, jupyter — reportan todos `1.27.2`; coincide con el patrón de versionado del framework `fastmcp` subyacente más que con la versión del proyecto. El paquete `sec-edgar-mcp` instalado es el correcto por nombre y tools.) No cambia el pick.
- AGPL-3.0: mismo cuidado de redistribución comercial que Stata; para uso interno/usuario no bloquea.

---

## 6. Macro — `fred-mcp-server`

**Instalación:** `npx -y fred-mcp-server` (stdio, Node). **Licencia:** AGPL-3.0. **Credenciales:** **gate de key FRED gratis** — env `FRED_API_KEY`. **Ejecución:** local con red.

**Test real — initialize + tools/list con key DUMMY (ejecutado 2026-06-11):**
```
Request: node .../fred-mcp-server/build/index.js   (env FRED_API_KEY=DUMMY_PROBE_KEY_NOT_REAL)
Request: initialize
Output:  {"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":true}},
          "serverInfo":{"name":"fred","version":"1.0.2","description":"Federal Reserve Economic Data (FRED) MCP Server for retrieving economic data series"}},"jsonrpc":"2.0","id":1}
  (stderr:  FRED MCP Server starting...  /  FRED MCP Server running on stdio)

Request: tools/list
Output:  {"result":{"tools":[
           {"name":"fred_browse","description":"Browse FRED's complete catalog through categories, releases, or sources..."},
           {"name":"fred_search","description":"Search for FRED economic data series by keywords, tags, or filters..."},
           {"name":"fred_get_series","description":"Retrieve data for any FRED series by its ID. Supports data transformations, frequency changes, and date ranges.",
             "inputSchema":{...,"units":{"enum":["lin","chg","ch1","pch","pc1","pca","cch","cca","log"]},
             "frequency":{"enum":["d","w","bw","m","q","sa","a",...]}, "series_id" required ...}}
         ]},"jsonrpc":"2.0","id":2}
```
[Interpretación: el server (v1.0.2, coincide con el radar) arranca y lista sus 3 tools con una key DUMMY — la key real se valida recién en la llamada de datos, no al arranque (igual que Alpha Vantage, distinto de Sheets/Stata que gatean al arranque). `fred_get_series` expone exactamente las transformaciones que pide el task T4: `units=pch/pc1` (percent change MoM/YoY) y `frequency` para agregación — el corazón de la convención SAAR/anualización que el generalista hace mal.]

**Test honesto sobre la sonda:** el lanzamiento vía `npx -y` produjo silencio en el primer intento (artefacto de timing del wrapper npx + cierre de stdin bajo el harness). Confirmado que es artefacto de npx, no del server: corriendo el entry `build/index.js` cacheado directamente con node, el handshake JSON-RPC completo aparece (pegado arriba). Para el cableado: usar el binario resuelto, no depender del timing de `npx -y` en cold start.

**Criterio de cierre (Lead):** init + tools/list ejecutados (test real ✓); llamada de datos real PENDIENTE de una key FRED gratis (gate de cuenta). FRED es LA fuente canónica macro para el flujo Stata/econometría (AV trae solo un subset macro).

**Nits honestos:** semi-stale en el radar (9 meses sin release a junio 2026) — vigilar staleness en el próximo tick. Surface pequeño (3 tools) pero suficiente: browse/search/get_series cubre el pull de CPI/desempleo/tasa del task T4.

---

## 7. Data science — `jupyter-mcp-server`

**Instalación:** `uvx jupyter-mcp-server --transport stdio ...` (stdio). **Licencia:** BSD-3. **Credenciales:** **gate de INFRA** — un Jupyter server propio corriendo con `JUPYTER_TOKEN` + JupyterLab 4.4.x + jupyter-collaboration (RTC). NO es cuenta de tercero — compatible con el local-first de NORTH. **Ejecución:** local.

**Test real — montar Jupyter efímero + initialize + tools/list + EJECUTAR código real en el kernel (ejecutado 2026-06-11):**
```
Setup: venv efímero con jupyterlab==4.4.10 + jupyter-collaboration + ipykernel (sin tocar el env quant del usuario);
       jupyter lab --port=8899 --IdentityProvider.token=PUPPETPROBE  →  HTTP 200 en /api

Request: uvx jupyter-mcp-server --transport stdio --runtime-url http://127.0.0.1:8899 --runtime-token *** --document-id probe.ipynb
Request: initialize
Output:  {"jsonrpc":"2.0","id":1,"result":{...,"serverInfo":{"name":"Jupyter MCP Server","version":"1.27.2"}}}
  (stderr: Auto-enrolling document 'probe.ipynb' with new kernel / Initializing MCP_SERVER mode)

Request: tools/list
Output:  18 tools: list_files, list_kernels, use_notebook, list_notebooks, restart_notebook,
         unuse_notebook, read_notebook, insert_cell, overwrite_cell_source, edit_cell_source,
         execute_cell, insert_execute_code_cell, read_cell, delete_cell, move_cell,
         execute_code, connect_to_jupyter  (+ use_notebook create/connect modes)

Request: tools/call execute_code {"code":"import statistics\nv=[101.2,98.7,103.4,99.1,100.6]\nprint('mean',round(statistics.mean(v),4))\nprint('stdev',round(statistics.stdev(v),4))","timeout":40}
Output:  {"content":[{"type":"text","text":"mean 100.6\nstdev 1.8748\n"}],"isError":false}
```
[Interpretación: el server se conectó al Jupyter LIVE, listó 18 tools y EJECUTÓ Python real en el kernel devolviendo mean=100.6 / stdev=1.8748 (correctos). Esto es E3 para data science: el entregable que CORRE, no prosa. La combinación insert_execute_code_cell + read_cell cubre el .ipynb reproducible del task T4. Encaja con el env quant ya existente del founder (que tiene JupyterLab 4.5.8 — para producción solo falta agregarle jupyter-collaboration, que su env no tiene hoy).]

**Decisión motor-vs-MCP (refuerza §3):** Jupyter+kernel ES el motor de cómputo numérico general. Con pandas/statsmodels dentro, **absorbe la pata econométrica mientras la licencia Stata espera** — esta es la razón por la que el belt no se bloquea si el usuario no tiene Stata.

**Criterio de cierre (Lead):** test feliz superado de punta a punta — montar infra + init + 18 tools + ejecución real de código con resultado correcto. Gate de infra (no de cuenta de tercero): el deploy de Puppet corre el Jupyter; el usuario no necesita credencial externa.

**Nits honestos:**
- Misma versión reportada `1.27.2` que excel/sec-edgar (patrón fastmcp); paquete correcto por nombre/tools.
- El gate de infra requiere `jupyter-collaboration` (RTC: jupyter_server_ydoc + pycrdt). El env quant del founder (JupyterLab 4.5.8) NO lo tiene instalado hoy — la sonda usó un venv efímero aparte para no mutar su env. Para producción, Tool-belt Engineering debe empaquetar un Jupyter con la extensión de colaboración. Documentado en §9.

---

## 8. Modelo base recomendado

**Recomendación:** `gpt-oss-120b` (Groq, free tier) como piso medido; frontier (Opus/equivalente) para las tareas multi-MCP de alto costo de error (T3 comps con cita al filing).
**Criterio:** el agente de finanzas encadena tool-use multi-MCP sostenido —p.ej. T3: sec-edgar (CIK→financials) → excel (xlsx con múltiplos vivos) → verificación cruzada— y el protocolo de 3 pasos de Alpha Vantage (TOOL_LIST→TOOL_GET→TOOL_CALL) penaliza modelos chicos que no sostienen el workflow. Misma lección que el belt STEM: modelos pequeños fallan en tool-use multi-MCP sostenido (registrado con `qwen3:8b`).

| Candidato | Tier | Notas |
|---|---|---|
| `gpt-oss-120b` (Groq) | free | RECOMENDADO como piso — tool-use sostenido, sin reasoning overhead |
| frontier (Opus/Claude) | paid | RECOMENDADO para T3/error-alto-costo — gates de confianza (Trust): número malo en comps cuesta caro |
| `llama-3.3-70b` (Groq) | free | Respaldo válido para tareas de un solo MCP (T1 cierre mensual) |
| `qwen3:8b` (local) | local | DESCARTADO como base — demasiado chico para el protocolo meta-tool de AV y multi-MCP |

**Qué valida Agent Eval (FOUNDRY post-wiring):** mide equipado-vs-pelado con el task-set T1–T5 de P005 §3. La afirmación "sostiene tool-use multi-MCP" es recomendación a validar, no hecho declarado — el eval runner es el gate de confianza antes de declarar el belt operativo (secuencia EVAL-FRAMEWORK-SPEC §5).

---

## 9. Nota para cableado (handoff a Tool-belt Engineering)

Comandos exactos de instalación/arranque por server elegido (env vars por nombre; NUNCA un valor de key real):

**excel-mcp-server (Excel local):**
```
uvx excel-mcp-server stdio
# Env: EXCEL_FILES_PATH=<dir del proyecto del usuario>
# CRÍTICO: en stdio los paths de tool deben ser ABSOLUTOS (rechaza relativos)
# Tools clave: create_workbook, write_data_to_excel, apply_formula (fórmula viva <f>), read_data_from_excel
# Credenciales: ninguna. Versión publicada: 1.27.2 (25 tools), no v0.1.8 del radar
```

**sec-edgar-mcp (fundamentals US GAAP):**
```
uvx sec-edgar-mcp
# Env: SEC_EDGAR_USER_AGENT="Nombre Apellido (email)"   (requisito de la SEC; dato público)
# Tools clave: get_cik_by_ticker, get_financials, get_xbrl_concepts, get_company_facts, get_insider_transactions
# Credenciales: ninguna. Fuente primaria; descripciones anti-alucinación incorporadas
```

**jupyter-mcp-server (data science):**
```
# 1) Levantar un Jupyter propio CON jupyter-collaboration:
#    pip install "jupyterlab==4.4.*" jupyter-collaboration ipykernel
#    jupyter lab --port=8899 --IdentityProvider.token=$JUPYTER_TOKEN --no-browser
# 2) uvx jupyter-mcp-server --transport stdio \
#       --runtime-url http://127.0.0.1:8899 --runtime-token $JUPYTER_TOKEN \
#       --document-url http://127.0.0.1:8899 --document-token $JUPYTER_TOKEN --document-id <nb>.ipynb
# Tools clave: insert_execute_code_cell, execute_code, read_cell, read_notebook
# Credenciales: JUPYTER_TOKEN (infra propia, no cuenta de tercero)
# NOTA: el env quant del founder tiene JupyterLab 4.5.8 pero NO jupyter-collaboration — agregarla
```

**marketdata-mcp / Alpha Vantage (datos de mercado):**
```
# Local:  uvx --from marketdata-mcp-server marketdata-mcp
# Remoto (oficial): HTTP https://mcp.alphavantage.co/mcp?apikey=$ALPHA_VANTAGE_API_KEY
# Env: ALPHA_VANTAGE_API_KEY   (con guión bajo; gratis en alphavantage.co)  ← NOMBRE corregido vs contexto
# Ejecutable local: marketdata-mcp  (no marketdata-mcp-server)
# WORKFLOW OBLIGATORIO del agente: TOOL_LIST -> TOOL_GET(tool_name) -> TOOL_CALL(tool_name, args)
#   (3 meta-tools de descubrimiento progresivo; los 100+ endpoints viven detrás de TOOL_CALL)
# Credenciales: key gratis — gate de cuenta (decisión del operador: key del usuario vs cuenta Aleph)
```

**fred-mcp-server (macro):**
```
npx -y fred-mcp-server      # usar el binario resuelto; npx -y en cold start tiene timing flako
# Env: FRED_API_KEY   (gratis)
# Tools clave: fred_get_series (units=pch/pc1 para MoM/YoY; frequency para agregación), fred_search, fred_browse
# Credenciales: key gratis — gate de cuenta. Server v1.0.2 (semi-stale: vigilar próximo tick)
```

**mcp-google-sheets (Sheets colaborativo) — gate de cuenta, activar cuando el operador provea GCP:**
```
uvx mcp-google-sheets
# Env: GOOGLE_APPLICATION_CREDENTIALS=<service-account.json>  (modo headless recomendado)
#      o credentials.json (OAuth) o ADC
# Credenciales: gate Google Cloud — DECISIÓN DEL OPERADOR (cuenta de servicio Aleph vs proyecto GCP del usuario)
# Tools clave: get_sheet_data, get_sheet_formulas, batch_update_cells, share_spreadsheet, add_chart
```

**mcp-stata (econometría) — gate de licencia, activar cuando el usuario tenga Stata:**
```
uvx mcp-stata
# Env: STATA_PATH=<ruta al ejecutable Stata 17+>   (licencia del USUARIO)
# Tools clave: stata_run, stata_get_results (r()/e()/s()), stata_load_data, stata_inspect_data
# Credenciales: licencia Stata — GATEADA decisión usuario/operador
# DEGRADACIÓN sin Stata: Jupyter + pandas/statsmodels/linearmodels (efectos fijos, SE clusterizados)
```

**Alternativas activables sin re-cableado (si elegida falla):**
```
# Mercado:        financial-datasets/mcp-server (10 tools directos, sin meta-protocolo; key propia)
# Excel:          negokaz/excel-mcp-server (SOLO si Windows; en kill-list por stale + Windows-only)
# Sheets:         freema/mcp-gsheets (mismo gate Google; 27 tools)
# Stata:          hanlulong/stata-mcp (requiere VS Code; 2 tools)
# Econometría sin Stata: jupyter-mcp-server + statsmodels (ya en el belt)
```

---

## 10. Supuestos y huecos

### Supuestos asumidos en v0
- El selector primario del belt es la pregunta #1 de la Guía (P005 §4): dónde vive el trabajo (Excel local / Sheets / Stata / Jupyter) decide qué servers se activan y qué credenciales pide el onboarding.
- Los servers gateados por KEY GRATIS (AV, FRED) listan tools sin credencial válida y fallan recién en la llamada de datos — verificado en sonda. Los gateados por CUENTA/LICENCIA (Sheets, Stata) gatean al arranque — verificado en sonda. Esta asimetría es real y condiciona qué se puede sondar sin credencial.
- El env quant del founder cubre la pata Jupyter en desarrollo; para producción falta empaquetar `jupyter-collaboration`.

### Huecos explícitos (funciones sin ejecución real verificada hoy)

| Función deseada | Estado actual | Recomendación |
|---|---|---|
| Llamada de datos real Alpha Vantage / FRED | init+tools/list ejecutados; la llamada de datos necesita key gratis | Sacar key gratis (1 min) y sondar la primera llamada + rate limits en el wiring |
| Sheets end-to-end (task T5) | solo-spec; gatea al arranque sin service account | Decisión del operador: cuenta de servicio Aleph compartida. Recién ahí se sondea |
| Stata r()/e() reales (task T2) | solo-spec; gate de licencia, Stata no instalado | Degradación a Jupyter+statsmodels cubre v0; activar mcp-stata cuando el usuario traiga licencia |
| Tabla estilo journal/esttab (T2) | sin equivalente exacto fuera de Stata | statsmodels.summary2 + formateo manual aproxima; gap real de convención hasta tener Stata |

---

## Checklist de validación

- [x] **C1** — Tabla resumen completa: todas las columnas (Categoría / Elegida / Alternativa / Costo / Credenciales / Verificado) — §0
- [x] **C2** — Cada server elegido tiene sección propia numerada (§1 excel, §2 sheets, §3 stata, §4 alpha-vantage, §5 sec-edgar, §6 fred, §7 jupyter)
- [x] **C3** — Cada categoría tiene test real con output crudo copiado exacto donde fue ejecutable (excel, sec-edgar, jupyter, AV, fred); las 2 categorías con gate duro (sheets/OAuth, stata/licencia) pegan el output crudo del INTENTO de arranque y se declaran "solo-spec" honestamente — NO se parafrasea ni se sobre-declara (lección 0003)
- [x] **C4** — Distinción motor-vs-MCP declarada: §3 (Stata = motor licenciado; degradación a Jupyter+pandas) y §7 (Jupyter absorbe la pata econométrica mientras espera la licencia)
- [x] **C5** — Credenciales/gates documentados: matriz dedicada (3 clases: cero-fricción / gate de cuenta / gate de licencia) + por server; Sheets y Stata marcados "gateada — decisión del operador / usuario"
- [x] **C6** — Alternativas activables sin re-cableado listadas en §9 para cada elegida
- [x] **C7** — Descartados con evidencia: la kill-list de P005 §2 (8 servers) se REFERENCIA (no se re-litiga, por spec); las alternativas con su motivo de no-pick están en §0 y §9
- [x] **C8** — Modelo base recomendado con criterio específico para ESTE nicho: §8 (tool-use multi-MCP + protocolo meta-tool de AV; gpt-oss-120b piso, frontier para T3)
- [x] **C9** — Nota de cableado con comandos exactos para handoff a Tool-belt Engineering — §9
- [x] **C10** — Supuestos y huecos declarados explícitamente — §10 (3 supuestos + 4 huecos)
- [x] **C11** — Estado declarado: ACTIVO (primera entrada de producción)
- [⚠] **C12** — Fuente original (path absoluto si es migración): N/A — esta entrada NO es migración; se construye desde el radar `org/artifacts/P005-radar-finanzas.md` (referenciado en el frontmatter). El criterio C12 aplica solo a migraciones; marcado ⚠ con nota, no re-escrito para auto-aprobarse.
