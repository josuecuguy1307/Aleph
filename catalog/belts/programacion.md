# programacion — Belt-Spec: Agente Programación v0

**Qué es:** Cinturón MCP del agente programación — edita el repo, corre tests/comandos en sandbox aislado y solo declara verde con pass real.
**Fecha:** 2026-06-15
**Estado:** ACTIVO
**Fuente original:** `org/artifacts/FASE0-tabla-tool-caso-bucket.md` §6 (PROGRAMACIÓN) + `product/belts/gaps.mcp.json` (script-runner B3).
**Regla F5 cumplida:** init + tools/list JSON-RPC stdio reales el 2026-06-15 sobre los 2 servers keyless (filesystem + script_runner) vía `product/belts/client/mcp_client.py`. github/context7 son connectors conectados en este entorno; se declaran con su gate de credencial (BYOK), no se cablean con key.

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Repos/PRs/issues | `github` (`@modelcontextprotocol/server-github`, npx) | GitHub remote MCP oficial | $0 | `GITHUB_PERSONAL_ACCESS_TOKEN` (BYOK) | conectado en entorno; gate de credencial |
| Docs de SDK | `context7` (`@upstash/context7-mcp`, npx) | fetch a docs | $0 free tier | `CONTEXT7_API_KEY` (BYOK) | conectado en entorno; gate de credencial |
| Editar el repo | `filesystem` (`@modelcontextprotocol/server-filesystem`) | — | $0 | ninguna | test real ✓ (init+list) |
| Ejecutar código/tests | `script_runner` (gap B3, `gaps/script_runner_mcp.py`) | — | $0 | ninguna | test real ✓ (init+list+call, ver EVIDENCE.md) |

Servers activos en v0: **4** (2 BYOK + filesystem keyless + script_runner gap). Belt runnable: `catalog/templates/programacion/belt-programacion.mcp.json`.

---

## 1. Repos/PRs/issues — `github`
**Instalación:** `npx -y @modelcontextprotocol/server-github`. **Credenciales:** `GITHUB_PERSONAL_ACCESS_TOKEN` (BYOK). Tools (read-only v1): `search_code`, `get_file_contents`, `list_pull_requests`, `get_issue`. Existe-óptimo (FASE0 §6).

## 2. Docs de SDK — `context7`
**Instalación:** `npx -y @upstash/context7-mcp`. **Credenciales:** `CONTEXT7_API_KEY` (BYOK, free tier). Tools: `resolve-library-id`, `query-docs`. Compartido con research.

## 3. Editar el repo — `filesystem`
Atómica keyless (FASE0 §2). Tools: `read_file`, `write_file`, `edit_file`, `list_directory`. **Test real init+list 2026-06-15.**

## 4. Ejecutar código/tests — `script_runner` (MOAT, gap B3)
**Server:** `product/belts/gaps/script_runner_mcp.py` (`python3 ${PUPPET_BELTS}/gaps/script_runner_mcp.py`). **Credenciales:** ninguna.
El moat: corre/parsea SIN reventar el host — cwd efímero aislado, timeout, output cap, **allow-list de binarios** (`cat,echo,git,ls,octave,octave-cli,pandoc,pytest,python3`), y **declara `needs_gate`** ante patrones money/send (RECIPE-SCHEMA §3.5; Security HACE CUMPLIR). **Test real (EVIDENCE.md §2a):** `run_python` ejecutó PV de bono `stdout=973.27`; `run_shell ["rm","-rf"]` → rechazado por allow-list; script con `sendmail` → `needs_gate:true`.
**[DISTINCIÓN MOTOR-vs-MCP]** El runner ejecuta real; los tools que la receta nombra (`run_command`/`run_tests`) son **aspiracionales** — el gap hoy expone `run_python`/`run_shell`.

---

## 5. Modelo base recomendado
**Recomendación:** `gpt-oss-120b` (Groq, free) — tool-use largo (recipe `max_turns:20`). Respaldo: `llama-3.3-70b`.

## 6. Descartados con evidencia
| Descartado | Motivo | Evidencia |
|---|---|---|
| IDE GUI (VS Code interactivo) | Caso 3, BOTADO | edición vía filesystem + ejecución vía script-runner (FASE0 §6) |
| LSP / runner de tests dedicado | B4 (no-existe maduro) | followup; hoy cubierto por script_runner genérico |

## 7. Nota para cableado (handoff)
- **GATE DE NOMBRES (followup):** la receta filtra `script_runner: ["run_command","run_tests"]` pero el gap expone `run_python`/`run_shell`. Alinear antes de producción (renombrar/aliasing en el gap, o corregir la receta — lane Product/Tool-belt). El belt cabla el server real; el resolver resuelve igual.
- **GATE DE SEGURIDAD:** `gates.send=needs_ok` en la receta; el script_runner declara `needs_gate`; Security es quien aprueba. El belt NO ejecuta lo gateado.

## 8. Supuestos y huecos
- **Supuesto:** el usuario trae su GITHUB_PERSONAL_ACCESS_TOKEN (BYOK).
- **Hueco:** LSP wrapper + runner de tests por-framework (pytest/jest/go) = B4 pendiente; hoy se cubre con el runner genérico + allow-list.

## Checklist
- [x] C1 · [x] C2 · [x] C3 (filesystem+script_runner init+list reales; script_runner call en EVIDENCE.md) · [x] C4 (motor-vs-MCP: run_command/run_tests aspiracionales) · [x] C5 (BYOK + send-gate) · [x] C6 · [x] C7 · [x] C8 · [x] C9 (gate de nombres + seguridad) · [x] C10 · [x] C11 ACTIVO · [x] C12 fuente FASE0 §6
