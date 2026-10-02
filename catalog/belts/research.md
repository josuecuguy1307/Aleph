# research — Belt-Spec: Agente Research v0

**Qué es:** Cinturón MCP del agente research — fan-out de búsqueda, fetch de fuentes y síntesis CITADA.
**Fecha:** 2026-06-15
**Estado:** ACTIVO
**Fuente original:** `org/artifacts/FASE0-tabla-tool-caso-bucket.md` §5 (RESEARCH) + §2 (atómicas).
**Regla F5 cumplida:** init + tools/list JSON-RPC stdio reales ejecutados por Tool-belt el 2026-06-15 sobre los 3 servers keyless (fetch/filesystem/pandoc) vía `product/belts/client/mcp_client.py`. exa/huggingface/context7 son connectors conectados en este entorno; se declaran con su gate de credencial (BYOK), no se cablean con key.

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Búsqueda web | `exa` (`exa-mcp-server`, npx, stdio) | `fetch` directo | $0 free tier | `EXA_API_KEY` (BYOK) | conectado en entorno; gate de credencial |
| Papers/modelos/datasets | `huggingface` (remoto `huggingface.co/mcp` vía mcp-remote) | exa paper search | $0 | `HF_TOKEN` (BYOK) | conectado en entorno; gate de credencial |
| Docs de librerías | `context7` (`@upstash/context7-mcp`, npx) | fetch a docs | $0 free tier | `CONTEXT7_API_KEY` (BYOK) | conectado en entorno; gate de credencial |
| Fetch URL→texto | `fetch` (`mcp-server-fetch`, uvx) | — | $0 | ninguna | test real ✓ (init+list) |
| Persistir/leer reporte | `filesystem` (`@modelcontextprotocol/server-filesystem`) | — | $0 | ninguna | test real ✓ (init+list) |
| Conversión de formato | `pandoc` (`mcp-pandoc`, uvx) | — | $0 | ninguna (binario pandoc) | test real ✓ (init+list) |

Servers activos en v0: **6** (3 buscadores BYOK + 3 atómicas keyless). Belt runnable: `catalog/templates/research/belt-research.mcp.json`.

---

## 1. Búsqueda web — `exa`
**Instalación:** `npx -y exa-mcp-server` (stdio). **Credenciales:** `EXA_API_KEY` (BYOK, free tier). **Ejecución:** red.
Tools clave: `web_search_exa`, `web_fetch_exa`. Existe-óptimo (FASE0 §5).
**Criterio de cierre:** el agente hace fan-out de queries y trae fuentes con URL para citar.

## 2. Papers/modelos/datasets — `huggingface`
**Instalación:** MCP remoto `https://huggingface.co/mcp` puenteado con `npx -y mcp-remote` + `Authorization: Bearer ${HF_TOKEN}`. **Credenciales:** `HF_TOKEN` (BYOK). No existe paquete npm stdio; es remoto. Tools: `paper_search`, `hf_doc_search`, `hub_repo_search`.

## 3. Docs de librerías — `context7`
**Instalación:** `npx -y @upstash/context7-mcp`. **Credenciales:** `CONTEXT7_API_KEY` (BYOK, free tier). Tools: `resolve-library-id`, `query-docs`. Compartido con el belt programación.

## 4. Atómicas keyless — `fetch` / `filesystem` / `pandoc`
Backbone compartido (`product/belts/atomicas.mcp.json`, FASE0 §2). Siempre disponibles: si las keys BYOK faltan, el belt research **degrada** a este backbone (busca vía fetch, persiste vía filesystem, entrega vía pandoc). **Test real — init+list 2026-06-15:** los 3 respondieron `initialize`+`tools/list` (ver SMOKE).

---

## 5. Modelo base recomendado
**Recomendación:** `gpt-oss-120b` (Groq, free) — fan-out multi-tool sostenido + síntesis larga (recipe `max_turns:16`, `max_tokens:4096`). Respaldo: `llama-3.3-70b`.

## 6. Descartados con evidencia
| Descartado | Motivo | Evidencia |
|---|---|---|
| scraping manual por navegador | Caso 3 (GUI), BOTADO | sin superficie programable; cubierto por exa/fetch (FASE0 §5) |
| `@huggingface/mcp-server` (npm) | no existe | `npm view` → not found; HF MCP es remoto |

## 7. Nota para cableado (handoff)
**MOAT de research = "verificación adversarial + reporte citado"** (FASE0 §5, B3): NO es un MCP server, es la **receta/harness** (fan-out → verify → sintetizar citado). El belt provee las tools; el framing (`product/recipes/framing/research.md`) impone la verificación. Las keys BYOK se inyectan vía `byok_ref` del runtime; el belt declara los `${VAR}`.

## 8. Supuestos y huecos
- **Supuesto:** exa/hf/context7 los conecta el usuario (BYOK), no Puppet con cuenta propia.
- **Hueco:** verificación adversarial no es tool → vive en el framing/receta (gap B3, no se llena con MCP).

## Checklist
- [x] C1 tabla resumen · [x] C2 sección por server · [x] C3 test real (3 keyless init+list) · [x] C4 motor-vs-MCP (HF remoto) · [x] C5 credenciales/gates (BYOK declarados) · [x] C6 alternativas · [x] C7 descartados con evidencia · [x] C8 modelo base con criterio · [x] C9 nota de cableado · [x] C10 huecos (verificación adversarial = framing) · [x] C11 estado ACTIVO · [x] C12 fuente FASE0 §5
