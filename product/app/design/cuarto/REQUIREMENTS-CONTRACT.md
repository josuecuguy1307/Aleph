# Contrato `requirements` por átomo — C2 (Stream A ⇄ Stream B)

> El panel de **Opciones** del inspector se ARMA según lo que cada átomo declara que
> necesita — no es fijo. Esto es el contrato del campo `requirements` que cada átomo
> de `GET /v1/atoms/catalog` puede traer.

## Estado actual (ACORDADO con Stream B · C3)

Stream B (`F1-byomcp`, `atoms_router.py`) **ya emite** `requirements` por átomo con ESTA forma
(ver `FASE1-C3-BYO-NOTES.md`) — es el **contrato del backend**:

```jsonc
"requirements": {
  "connection": { "needed": true, "auth": "keyless|token|oauth|byok",
                  "connector": "feedoracle", "connectable": true, "state": "ready|connectable|connected" },
  "params": [],                                  // subset del inputSchema de la tool ([] casi siempre)
  "gate": { "gated": true, "level": "send|money|null" }
}
```

**Convergencia (sin pedirle cambios a Stream B):** el frontend mantiene un **modelo interno de
panel** (`connect`/`gate.applicable`/`params`/`readonly`/`tuning`/`capabilities`, descrito abajo) y
`cuarto.catalog.js` lo resuelve así:
- **Siempre deriva** el modelo interno de los campos que el catálogo ya trae (funciona aunque el
  backend no mande `requirements` — el `:8080` vivo hoy NO lo manda todavía).
- **Si el átomo trae `requirements`** (forma Stream B de arriba), `_mergeBackendRequirements` la
  **mapea encima** (autoridad del backend): `connection→connect`, `gate.gated→gate.applicable`,
  `params` se anexan. Cuando `F1-byomcp` mergee a `:8080`, el panel consume lo del backend sin
  tocar el frontend. `byok` se trata como `token` para el campo de llave.

## Forma del campo

```jsonc
"requirements": {
  // bloque CONEXIÓN — presente SÓLO si el átomo necesita una conexión externa para andar.
  // Ausente para tools keyless. Renderiza "Activar + llave/OAuth".
  "connect": {
    "kind": "oauth" | "token" | "personal_token",
    "connector": "gmail",        // nombre → GET /v1/connectors/{connector}
    "connectable": true,         // false = gateado (p.ej. app OAuth sin registrar) → botón inactivo + motivo
    "label": "Conectar Gmail"    // humano
  },

  // bloque GATE — presente si la pieza PUEDE tocar el mundo (muestra la perilla Autonomía).
  "gate": { "applicable": true, "default": "needs_ok" },   // auto | needs_ok | always_stop

  // params del átomo, en HUMANO + default inteligente (default 100% humano, cero jerga).
  // type ∈ multitoggle | select | number | text. v1 deriva 'tools' (qué hace la pieza) → tool_filters.
  "params": [
    { "key": "tools", "label": "Qué hace esta pieza", "type": "multitoggle",
      "options": [ { "value": "create_draft", "label": "create draft", "on": true } ] }
  ],

  // Fuente de SOLO-LECTURA (keyless, lee del mundo): panel mínimo — sin connect, sin gate,
  // sin params editables. Sólo muestra qué puede leer.
  "readonly": false,

  // perillas universales del agente que aplican a esta pieza (detail→prompt, steps→loop).
  "tuning": ["detail", "steps"]
}
```

## Reglas de derivación (frontend, mientras el backend no lo traiga)

| Condición del átomo | `requirements` resultante |
|---|---|
| `atom==="conexion"` o (`auth!=="keyless"` y hay `connector`) | `connect` con `kind=auth`, `connectable` del catálogo |
| `atom==="tool"` y `zone==="fuentes"` y `auth==="keyless"` | `readonly:true`, sin connect/gate/params editables |
| `zone==="entrega"` o `atom==="conexion"` | `gate.applicable:true` |
| tiene `tools[]` y no es readonly | `params:[{key:"tools", multitoggle}]` (→ `config.belt.tool_filters[server]`) |

## Qué pediría a Stream B (si quiere ir más allá de la derivación)

1. **Params reales de tool** (más allá del toggle de `tools[]`): si un server MCP declara params
   por tool (p.ej. `max_results`, `format`), exponerlos en `requirements.params` con label humano
   + default. Hoy no hay fuente de esos params en el catálogo.
2. **`capability_line`** del conector dentro de `connect` (ya vive en `/v1/connectors`), para no
   pegarle un 2do fetch por átomo.
3. **`gate.default` real** por tool (money/send) si el enforcer lo sabe a nivel de tool.
