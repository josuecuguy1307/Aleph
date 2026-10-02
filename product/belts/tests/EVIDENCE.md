# Tool-belt FASE 1 — EVIDENCIA REAL (cero false-green)

**Squad:** Tool-belt Engineering · **Fecha:** 2026-06-15
**Carril:** `product/belts/` + `catalog/belts/`
**Fuente:** `org/artifacts/FASE0-tabla-tool-caso-bucket.md` (roll-up §8) + `platform/assembler/RECIPE-SCHEMA.md`

> Regla del founder: nada se marca "hecho" sin output crudo de una corrida real.
> Todo lo de abajo se EJECUTÓ. El gateway LiteLLM :4000 estaba caído (0 listeners,
> `http_code=000`) — NO se reinició (servicio compartido). El test usó **Groq
> directo** con el MISMO modelo OSS `openai/gpt-oss-120b` (alias `constructor-code`
> en `infra/litellm.config.yaml`). El operador es OSS, no frontier.

---

## 1 · ATÓMICAS — backbone compartido (JSON-RPC real init + tools/list)

Sondas stdio ejecutadas el 2026-06-15. Cada server respondió `initialize` + `tools/list`.

| Tool | Comando | serverInfo (real) | tools (muestra real) |
|---|---|---|---|
| `filesystem` | `npx -y @modelcontextprotocol/server-filesystem <dir>` | `secure-filesystem-server 0.2.0` | `read_file`, `read_text_file`, `write_file`, `list_directory`, ... |
| `fetch` | `uvx mcp-server-fetch` | `mcp-fetch 1.27.2` | `fetch` |
| `memory` | `npx -y @modelcontextprotocol/server-memory` | `memory-server 0.6.3` | `create_entities`, ... |
| `pandoc` | `uvx mcp-pandoc` (binario pandoc) | — | Caso 2; verificado previamente en writer-es-v0 (referenciado, no re-ejecutado hoy) |

Belt: `product/belts/atomicas.mcp.json`.

---

## 2 · GAPS construidos (los moat de Tool-belt)

### 2a · script-runner sandbox — Caso 2, B3 (`product/belts/gaps/script_runner_mcp.py`)

`tools/call run_python` con `statistics.mean([10,20,30,40])`:
```
{"ok": true, "exit_code": 0, "stdout": "25\n", "stderr": "", "workdir": "/var/folders/.../puppet_sbx_..."}
```
Gate de Security (RECIPE-SCHEMA §3.5) — script con `sendmail`:
```
{"ok": false, "needs_gate": true, "gate": "money_touch|send",
 "note": "Script matches a money/send pattern. Security must approve ... before execution."}
```
Allow-list — `run_shell ["rm","-rf","/tmp"]`:
```
{"ok": false, "error": "'rm' not in allow-list",
 "allow_list": ["cat","echo","git","ls","octave","octave-cli","pandoc","pytest","python3"]}
```
→ Ejecuta de verdad · declara gate al motor de Security · rechaza fuera de allow-list · cwd efímero aislado.

### 2b · thin API wrapper — Caso 1, B4 (`product/belts/gaps/api_wrapper_mcp.py`)

`tools/call ticker_to_cik {"ticker":"AAPL"}` (llamada HTTP real a SEC):
```
{"ok": true, "ticker": "AAPL", "cik": "0000320193", "title": "Apple Inc."}
```
SSRF blocked — `http_get_json` al metadata endpoint de cloud:
```
{"ok": false, "error": "host '169.254.169.254' not in allow-list",
 "allow_list": ["api.stlouisfed.org","data.sec.gov","www.alphavantage.co","www.sec.gov"]}
```
→ Resuelve datos reales de SEC · host allow-list corta SSRF. Misma forma para FRED/AlphaVantage con `byok_ref`.

---

## 3 · PRUEBA DE FUEGO — un modelo OSS OPERA cada tool (no "responde 200")

Harness: `product/belts/tests/test_oss_operates.py` → `product/belts/client/mcp_client.py`.
Modelo: `openai/gpt-oss-120b` (Groq direct, gateway caído). **3/3 escenarios: el modelo
LLAMÓ la tool y usó su output real para responder.**

| Escenario (nicho) | Tool operada | Llamadas reales del modelo | Resultado verificado |
|---|---|---|---|
| atomicas/filesystem (cowork) | `write_file` | `write_file` → (allow-list bloquea `/tmp`) → self-corrige a `/private/tmp` → `read_text_file` | archivo en disco contiene `reunion 9am lunes` |
| gaps/scriptrunner (finanzas) | `run_python` | generó PV de bono (cupón 50, r=6%, 3y, nominal 1000) → ejecutó | `stdout=973.27` (PV correcto) |
| gaps/apiwrapper (finanzas) | `ticker_to_cik` | `ticker_to_cik(MSFT)` | `0000789019 (MICROSOFT CORP)` (dato real SEC) |

Notas honestas de la corrida (no se ocultan):
- **429 TPM real** (Groq free 8000 tok/min): el cliente trae backoff que parsea
  "try again in Ns" — durmió 8s/22.3s y se recuperó. Quedó como robustez del cliente.
- En filesystem el modelo intentó primero un path fuera del allow-list y el server
  lo RECHAZÓ; el modelo se auto-corrigió. Esa fricción es la seguridad funcionando,
  no un bug — se deja documentada.

Reproducir: `GROQ_API_KEY=... python3 product/belts/tests/test_oss_operates.py`

---

## 4 · Cómo encaja con el resto (compatibilidad verificada)

- Los belts `.mcp.json` usan `mcpServers` + `${VAR}` igual que `catalog/templates/finanzas/belt-finanzas.mcp.json`; `_meta` vive FUERA de `mcpServers` (el assembler itera `mcpServers`, lo ignora).
- `belt_ref` de la receta (RECIPE-SCHEMA §2) puede apuntar a estos belts; `tool_filters` recorta el surface (probado: `gaps` con filtro a 1 tool por escenario).
- El cliente MCP del squad (`client/mcp_client.py`) NO toca `platform/assembler/*` (otro carril); comparte el wire MCP/JSON-RPC para que un belt verificado caiga directo en el assembler.

## 5 · Gated a persona usuaria (no cableado, no bloquea) — guardrail #6
- `mcp-google-sheets` (service account GCP) — gated.
- `mcp-stata` (licencia Stata) — gated; degradación documentada → Jupyter+statsmodels.
- Belts B1/B2 que requieren key de pago (Alpha Vantage, FRED) quedan declarados en `catalog/belts/finanzas.md`; el wrapper Caso-1 se probó KEYLESS (SEC) para no tocar gates.
