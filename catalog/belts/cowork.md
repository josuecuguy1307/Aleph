# cowork — Belt-Spec: Agente Cowork v0

**Qué es:** Cinturón MCP del agente cowork (productividad/oficina) — lee Drive/Calendar/correo, prepara borrador y agenda, y NUNCA manda ni invita sin OK explícito.
**Fecha:** 2026-06-15
**Estado:** ACTIVO
**Fuente original:** `org/artifacts/FASE0-tabla-tool-caso-bucket.md` §7 (COWORK).
**Regla F5 cumplida:** init + tools/list JSON-RPC stdio real el 2026-06-15 sobre `filesystem` (backbone keyless) vía `product/belts/client/mcp_client.py`. Los 4 connectors (drive/calendar/gmail/slack) requieren OAuth/credencial y NO se cablearon con cuenta real (guardrail #6 + regla del plan: NO send sin send-gate).

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Backbone local | `filesystem` (`@modelcontextprotocol/server-filesystem`) | — | $0 | ninguna | test real ✓ (init+list) |
| Docs/archivos | `google_drive` (`@modelcontextprotocol/server-gdrive`) | ms365 | $0 | OAuth Google (BYOK) | conectado en entorno; gate OAuth |
| Agenda | `google_calendar` (`@cocal/google-calendar-mcp`) | ms365 | $0 | OAuth Google (BYOK) | conectado en entorno; gate OAuth |
| Correo (lectura/draft) | `gmail` (`@gongrzhe/server-gmail-autoauth-mcp`) | ms365 Outlook | $0 | OAuth Google (BYOK) | conectado; **send bloqueado por send-gate** |
| Mensajería (lectura/draft) | `slack` (`@modelcontextprotocol/server-slack`) | — | $0 | `SLACK_BOT_TOKEN`+`SLACK_TEAM_ID` (BYOK) | conectado; **send bloqueado por send-gate** |

Servers activos en v0: **5** (filesystem keyless + 4 connectors OAuth). Belt runnable: `catalog/templates/cowork/belt-cowork.mcp.json`.

---

## REGLA CENTRAL DEL BELT — SEND-GATE (no negociable)
`gmail` y `slack` se cablean **solo lectura + `create_draft`**. `send_email`/`post_message` **NUNCA** se exponen hasta que el **send-gate** (B3, Security) apruebe en lenguaje plano (qué/dónde/preview/OK). La receta `cowork.config.json` fija `gates.send=needs_ok`. WhatsApp/mensajería = gap B4, **NO se cabla sin send-gate**. El belt **declara**; Security **hace cumplir**.

---

## 1. Backbone local — `filesystem`
Atómica keyless (FASE0 §2). El agente arma localmente el borrador/agenda antes de tocar Drive/Calendar. **Test real init+list 2026-06-15.** Si los connectors OAuth no están conectados, el belt **degrada** a este backbone (no rompe).

## 2. Docs/archivos — `google_drive`
**Instalación:** `npx -y @modelcontextprotocol/server-gdrive`. **Credenciales:** OAuth Google (BYOK). Tools: `search_files`, `read_file_content`, `create_file`. Crear doc ≠ send (baja consecuencia).

## 3. Agenda — `google_calendar`
**Instalación:** `npx -y @cocal/google-calendar-mcp`. **Credenciales:** OAuth Google (BYOK). Tools: `list_events`, `find_free_time`, `create_event`. **Invitar a terceros pasa por send-gate.**

## 4. Correo — `gmail` (lectura/draft, send GATED)
**Instalación:** `npx -y @gongrzhe/server-gmail-autoauth-mcp`. **Credenciales:** OAuth Google (BYOK). Tools cableadas: `search_messages`, `read_message`, `create_draft`. `send_email` **NO se expone** (send-gate).

## 5. Mensajería — `slack` (lectura/draft, send GATED)
**Instalación:** `npx -y @modelcontextprotocol/server-slack`. **Credenciales:** `SLACK_BOT_TOKEN`+`SLACK_TEAM_ID` (BYOK). Tools: `search_messages`, `read_thread`, `create_draft`. Postear pasa por send-gate.

---

## 6. Modelo base recomendado
**Recomendación:** `gpt-oss-120b` (Groq, free). Respaldo: `llama-3.3-70b`.

## 7. Descartados con evidencia
| Descartado | Motivo | Evidencia |
|---|---|---|
| Suite ofimática de escritorio (GUI) | Caso 3, BOTADO | Drive/Docs vía API (FASE0 §7) |
| `mcp-google-sheets` | GATED al operador (service account GCP) | decisión humana requerida — declarado, no cableado |
| WhatsApp/mensajería | B4 + send-gate | no-existe MCP maduro/seguro; NO sin send-gate (FASE0 §7) |

## 8. Nota para cableado (handoff)
OAuth Google y tokens Slack se inyectan vía `byok_ref`/OAuth del runtime; el belt declara los `${VAR}`. **Sheets (GCP) GATED al operador.** El `tool_filters` de la receta **excluye** todo lo de envío — verificar que ningún filtro liste `send_*`/`post_*` antes de producción.

## 9. Supuestos y huecos
- **Supuesto:** el usuario conecta su Google/Slack (BYOK/OAuth).
- **Hueco:** ms365 (OAuth pendiente, B2) como alternativa a Google; WhatsApp (B4, gated).

## Checklist
- [x] C1 · [x] C2 · [x] C3 (filesystem init+list real) · [x] C4 (connectors hosted vs backbone keyless) · [x] C5 (OAuth/BYOK + Sheets GATED + send-gate) · [x] C6 · [x] C7 · [x] C8 · [x] C9 (excluir send_* del filtro) · [x] C10 · [x] C11 ACTIVO · [x] C12 fuente FASE0 §7
