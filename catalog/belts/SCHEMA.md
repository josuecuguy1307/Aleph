# Belt Catalog — Schema v1

**Mantenido por:** Squad Curation (R&D)
**Fecha:** 2026-06-11
**Extraído de:** `org/artifacts/M001-belt-spec-stem.md` (formato real probado, wedge STEM)

Las entradas de este catálogo documenta cinturones MCP curados por nicho.
Una entrada = un cinturón v0 listo para handoff a Tool-belt Engineering.

---

## Próximas entradas reales (en orden de prioridad — org/NORTH.md)

- **#1 FINANZAS** — Excel/Sheets, Stata, data science. Ecosistema MCP más maduro.
- **#2 INGENIERÍA MECÁNICA** — MATLAB/CAD. Métrica ledger: ensamblar #2 debe costar ≤50% del #1.

---

## Template de entrada (secciones numeradas)

```
# [SLUG] — Belt-Spec: [Nombre del nicho] v[N]

**Qué es:** [Una línea: cinturón MCP del agente X para nicho Y]
**Fecha:** YYYY-MM-DD
**Estado:** [HISTÓRICO/FIXTURE | ACTIVO | EN REVISIÓN]
**Fuente original:** [path absoluto al doc de origen, si es migración]
**Regla F5 cumplida:** [research + tests reales ejecutados por quién; no se declara sin evidencia]

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| [nombre] | `[server]` ([pkg], [transport]) | `[server]` | $0/$X/mes | ninguna / [var] | test real ✓ / pendiente |

Servers activos en v[N]: **[N]** ([descripción breve de qué cubre cada uno])

---

## [N]. [Nombre de categoría] — `[server-slug]`

**Instalación:** `[comando exacto]` / arranque: `[comando]` ([transport]).
**Licencia:** [SPDX]. **Credenciales:** [ninguna | VAR=xxx]. **Ejecución:** [local | red requerida].

**Test real — [nombre del test]:**
```
Request: [llamada exacta tal como se ejecutó]
Output:  [output crudo, copiado exacto]
```
[Interpretación: qué demuestra este output]

**Criterio de cierre (Lead):** [qué se necesita para declarar esta categoría cerrada]

**Nits honestos:** [limitaciones reales; "ninguno relevante" si aplica]

---

## [N+1]. Modelo base recomendado

**Recomendación:** `[model-id]` ([proveedor], [tier])
**Criterio:** [por qué este modelo para este nicho — basado en evidencia, no en supuesto]

| Candidato | Tier | Notas |
|---|---|---|
| `[id]` | free/paid | RECOMENDADO — [razón] |
| `[id]` | free | Respaldo válido |
| `[id]` | local | DESCARTADO — [razón] |

---

## [N+2]. Descartados con evidencia

| Descartado | Motivo | Evidencia |
|---|---|---|
| `[server]` | [categoría del motivo] | [qué falló exactamente, output crudo si aplica] |

---

## [N+3]. Nota para cableado (handoff a Tool-belt Engineering)

Comandos exactos de instalación y configuración por server elegido:

**[server-slug] ([categoría]):**
```
[comando de instalación]
# Comando de arranque (transport): [comando]
# Tools clave: [lista]
# Credenciales: [vars o "ninguna"]
# Notas de integración: [lo que Tool-belt Engineering necesita saber]
```

**Alternativas activables sin re-cableado (si elegida falla):**
```
# [categoría]: [comando]
```

---

## [N+4]. Supuestos y huecos

### Supuestos asumidos en v[N]
- [supuesto 1]

### Huecos explícitos (funciones sin MCP server real maduro hoy)

| Función deseada | Estado actual | Recomendación |
|---|---|---|
| [función] | [estado real] | [qué hacer] |

---

## Checklist de validación (marcar al pie de cada entrada)

- [ ] **C1** — Tabla resumen completa: todas las columnas (Categoría / Elegida / Alternativa / Costo / Credenciales / Verificado)
- [ ] **C2** — Cada server elegido tiene sección propia numerada
- [ ] **C3** — Cada categoría tiene al menos un test real con output crudo copiado exacto (no parafraseado)
- [ ] **C4** — Distinción motor-vs-MCP declarada cuando aplica (motor verificado ≠ wrapper MCP listo)
- [ ] **C5** — Credenciales/gates documentados: qué variables se necesitan, si alguna está gateada a una decisión del operador
- [ ] **C6** — Alternativas activables sin re-cableado listadas para cada elegida
- [ ] **C7** — Descartados con evidencia real (output crudo o motivo técnico, no "no me gustó")
- [ ] **C8** — Modelo base recomendado con criterio (no solo nombre — por qué para ESTE nicho)
- [ ] **C9** — Nota de cableado con comandos exactos para handoff a Tool-belt Engineering
- [ ] **C10** — Supuestos y huecos declarados explícitamente (huecos = funciones sin MCP maduro hoy)
- [ ] **C11** — Estado de la entrada declarado (HISTÓRICO/FIXTURE | ACTIVO | EN REVISIÓN)
- [ ] **C12** — Fuente original referenciada con path absoluto (si es migración)
```

---

## Convenciones del catálogo

**Transports:** `stdio` (proceso local) | `http/sse` (servidor remoto) | `streamable-http`
**Costo:** `$0` = gratuito sin límite relevante; especificar tier si hay límite operativo
**Verificado:** `test real ✓` = output crudo existe en la spec; `solo-spec (links verificados, sin ejecución)` = research verificado por fetch pero sin test ejecutado; `pendiente` = ni siquiera links verificados. Cualquier estado nuevo se agrega aquí antes de usarse en una entrada (lección 0003).
**Motor-vs-MCP:** cuando un motor Python/CLI está verificado pero el wrapper MCP aún no existe, declararlo explícitamente como "motor verificado; wrapper = trabajo futuro de M00X"
**Credenciales/gates:** si una credencial está gateada a una decisión del operador (decisión humana requerida), marcarlo con "gateada — decisión del operador"
