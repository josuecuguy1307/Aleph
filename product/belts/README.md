# product/belts — Tool-belt Engineering (cinturones MCP)

El equipamiento del agente. Tool-belt envuelve, configura y prueba conectores MCP
por campo. Fuente de verdad de QUÉ cablear: `org/artifacts/FASE0-tabla-tool-caso-bucket.md`
(ejes Caso × Bucket). Contrato de cómo lo consume la receta: `platform/assembler/RECIPE-SCHEMA.md`.

## Layout
```
product/belts/
  atomicas.mcp.json        # backbone compartido (>=4 nichos): filesystem, fetch, memory, pandoc — UNA vez
  gaps.mcp.json            # los GAPs que construye Tool-belt (script-runner + api-wrapper)
  gaps/
    script_runner_mcp.py   # Caso 2 / B3 MOAT: genera->ejecuta en sandbox->parsea (run_python/run_shell)
    api_wrapper_mcp.py     # Caso 1 / B4: wrapper delgado de API (ticker_to_cik/http_get_json, host allow-list)
  client/
    mcp_client.py          # cliente MCP stdio del squad (harness de prueba; NO toca el assembler)
  tests/
    test_oss_operates.py   # PRUEBA REAL: un modelo OSS OPERA cada tool en tarea de nicho
    EVIDENCE.md            # output crudo de las corridas (cero false-green)
```

## Reglas de carril
- Backbone = atómicas compartidas, **no** tools por-nicho duplicadas (FASE0 §2).
- Caso 3 (GUI-only) está BOTADO — no es candidato.
- Send/money NO se cablea sin send-gate; el script-runner ya DECLARA `needs_gate` (RECIPE-SCHEMA §3.5, Security HACE CUMPLIR).
- Sheets (GCP) y Stata (licencia) GATED a persona usuaria — declaradas, no cableadas.

## Variables de entorno que expanden los belts
- `${PUPPET_WORKDIR}` — espacio del run (filesystem/memory escriben acá).
- `${PUPPET_BELTS}` — ruta absoluta a este dir (los GAPs Python se invocan por path).

## Cómo se prueba un belt (el patrón del squad)
```
PUPPET_WORKDIR=/tmp/run PUPPET_BELTS=$PWD/product/belts \
  python3 product/belts/client/mcp_client.py product/belts/gaps.mcp.json   # lista tools
GROQ_API_KEY=... python3 product/belts/tests/test_oss_operates.py          # OSS opera las tools
```
Evidencia de la última corrida: `tests/EVIDENCE.md` (3/3 escenarios OPERATED con `gpt-oss-120b`).
