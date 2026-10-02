# Belts B1 de nicho — EVIDENCIA REAL (cero false-green)

**Squad:** Tool-belt Engineering · **Fecha:** 2026-06-15 · **Fase 2 (Fundación, carril belts)**
**Carril:** `catalog/belts/` + `catalog/templates/` · **Misión:** BELTS B1 DE NICHO (#5)
**Fuente:** `org/artifacts/FASE0-tabla-tool-caso-bucket.md` §8 (B1 CABLEAR as-is).

> Regla del founder: nada "hecho" sin output crudo de corrida real. Todo lo de abajo se
> EJECUTÓ. Gateway :4000 caído → no se reinició (compartido). No se bindeó :8080.

## Qué se construyó
El resolver (`platform/assembler/belt_resolver.py`) mapea `belt_ref` → slug →
`catalog/templates/<slug>/belt-<slug>.mcp.json`. Faltaban los belts runnable de 4 nichos.
Creados:

| Nicho | belt_ref de la receta | belt runnable creado | .md spec |
|---|---|---|---|
| educacion | `catalog/belts/stem.md` | `catalog/templates/stem/belt-stem.mcp.json` | ya existía |
| research | `catalog/belts/research.md` | `catalog/templates/research/belt-research.mcp.json` | creado |
| programacion | `catalog/belts/programacion.md` | `catalog/templates/programacion/belt-programacion.mcp.json` | creado |
| cowork | `catalog/belts/cowork.md` | `catalog/templates/cowork/belt-cowork.mcp.json` | creado |

(finanzas ya resolvía a `catalog/templates/finanzas/belt-finanzas.mcp.json`.)

## PRUEBA 1 — el resolver resuelve los 5 belt_ref
`python3 platform/assembler/belt_resolver.py <belt_ref>` para los 5 → todos devuelven un
`.mcp.json` real + lista de servers. **ANTES:** stem devolvía el `.md` con `servers: []`
(roto); research/programacion/cowork daban `BeltResolutionError`. **AHORA:** los 5 resuelven.

```
stem.md         -> catalog/templates/stem/belt-stem.mcp.json          servers: [chart, sympy, units]
research.md     -> catalog/templates/research/belt-research.mcp.json  servers: [context7, exa, fetch, filesystem, huggingface, pandoc]
programacion.md -> catalog/templates/programacion/belt-programacion.mcp.json servers: [context7, filesystem, github, script_runner]
cowork.md       -> catalog/templates/cowork/belt-cowork.mcp.json      servers: [filesystem, gmail, google_calendar, google_drive, slack]
```

## PRUEBA 2 — al menos un server arranca por belt (init + tools/list reales)
Harness: `catalog/templates/smoke_belts_b1.py` → `product/belts/client/mcp_client.py`.
Servers BYOK/OAuth (exa/huggingface/context7/github/google_*/slack) se SALTAN (sin
credencial; guardrail #6), no fallan. **ALL PASS:**

```
stem (educacion): 3/3 keyless -> sympy (171 tools), chart (27 tools), units (2 tools)
research:         3 keyless   -> fetch (1), filesystem (14), pandoc (1)   [SKIP exa/huggingface/context7]
programacion:     2 keyless   -> filesystem (14), script_runner (run_python/run_shell)  [SKIP github/context7]
cowork:           1 keyless   -> filesystem (14)   [SKIP google_drive/google_calendar/gmail/slack]
```
Reproducir: `python3 catalog/templates/smoke_belts_b1.py`

## PRUEBA 3 — los tool_filters de la receta calzan con tools vivas
| Nicho | server | filtros | match |
|---|---|---|---|
| educacion | sympy | 8 | **8/8 OK** |
| educacion | chart | 1 | **1/1 OK** |
| educacion | units | 2 | **2/2 OK** |
| programacion | filesystem | 4 | **4/4 OK** |
| programacion | script_runner | 2 | **0/2 MISMATCH** (ver followup) |

## Gates / gated (declarado, NO cableado — guardrails #6/#7)
- **BYOK** (credencial del usuario, no de persona usuaria): `exa` (EXA_API_KEY), `huggingface`
  (HF_TOKEN, MCP remoto vía mcp-remote), `context7` (CONTEXT7_API_KEY), `github`
  (GITHUB_PERSONAL_ACCESS_TOKEN). Declarados con `${VAR}`; sin key el belt degrada al
  backbone keyless.
- **OAuth** (cowork): google_drive/google_calendar/gmail (OAuth Google), slack
  (SLACK_BOT_TOKEN+SLACK_TEAM_ID). Conectados como connectors hosted en el entorno; el
  runtime inyecta credenciales. No se cablearon con cuenta real.
- **SEND-GATE** (no negociable): gmail/slack solo lectura + `create_draft`. NUNCA
  send/post hasta send-gate (B3, Security). Recetas cowork/programacion fijan
  `gates.send=needs_ok`. WhatsApp = B4, gated.
- **GATED al operador:** `mcp-google-sheets` (service account GCP) y `mcp-stata` (licencia) —
  ya declarados en finanzas/cowork, no cableados.

## Followups (no bloquean este carril)
1. **programacion / script_runner — mismatch de nombres:** la receta filtra
   `run_command`/`run_tests` pero el gap (`product/belts/gaps/script_runner_mcp.py`)
   expone `run_python`/`run_shell`. Con el filtro actual ese server expone 0 tools al LLM.
   Fix: alinear en el gap (renombrar/alias) o en la receta. Lane Product/Tool-belt.
2. **finanzas:** el template ya existía (7 servers, incluye sheets/stata gated) — fuera de
   esta misión, solo verificado que resuelve.
