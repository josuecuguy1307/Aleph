# WRITER-ES — Belt-Spec: Creative Writer ES v0

**Qué es:** Cinturón MCP del agente escritor creativo en español.
**Fecha:** 2026-06-09
**Estado:** HISTÓRICO/FIXTURE — vertical creative-writer reemplazado por STEM en decisión 2026-06-10, y STEM a su vez cerrado en pivot 2026-06-11 (ver org/NORTH.md). Esta entrada valida el schema del catálogo; no es producto activo.
**Fuente original:** `org/belts/writer-es-v0.md`
**Regla F5 cumplida:** spec producida por Belt Curator (Curation) para revisión por Reviewer Opus antes de handoff a Tool-belt Engineering. Los servers son oficiales del repo Anthropic (verificabilidad por link); tests de ejecución real no fueron parte del scope de este documento de spec.

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Insumo / Research | `@modelcontextprotocol/server-fetch` (npm, stdio) | `exa-mcp-server` (npm, API remota) | $0 | ninguna | solo-spec (links verificados, sin ejecución) |
| Producción / Manuscrito | `@modelcontextprotocol/server-filesystem` (npm, stdio) | `obsidian-mcp` (npm, plugin) | $0 | ninguna | solo-spec (links verificados, sin ejecución) |
| Producción / Memoria de contexto largo | `@modelcontextprotocol/server-memory` (npm, stdio) | `Mem0-MCP` (externo) | $0 | ninguna | solo-spec (links verificados, sin ejecución) |
| Salida / Exportación | `mcp-pandoc` (npm, stdio) | Google Docs / Notion MCP | $0 | ninguna (Pandoc en host) | solo-spec (links verificados, sin ejecución) |

Servers activos en v0: **4** (fetch para research; filesystem + memory para producción; pandoc para salida). Sin solapamiento funcional.

---

## 1. Insumo / Research — `@modelcontextprotocol/server-fetch`

**Instalación:** `npx @modelcontextprotocol/server-fetch` (stdio).
**Licencia:** MIT (repo oficial Anthropic `modelcontextprotocol/servers`, ~83k★ en el monorepo).
**Credenciales:** ninguna para uso básico. **Ejecución:** local con acceso a red.
**Link verificable:** https://github.com/modelcontextprotocol/servers/tree/main/src/fetch

**Criterio de elección:** server de fetch oficial. Permite al agente recuperar páginas web, artículos y documentación de referencia para investigar fuentes antes de escribir, sin salir del contexto. Alternativa Exa-MCP es mejor para búsqueda semántica pero requiere clave API de pago y no es oficial; para v0, fetch cubre el 80% del research sin fricción de auth.

**Criterio de cierre (Lead):** test real pendiente de ejecución. Spec aprobada por Reviewer Opus sobre verificabilidad de links y madurez del repo.

**Nits honestos:** por defecto no filtra contenido. Para v1, considerar un wrapper con lista de dominios bloqueados o rate limiting.

---

## 2. Producción / Manuscrito — `@modelcontextprotocol/server-filesystem`

**Instalación:** `npx @modelcontextprotocol/server-filesystem <directorio>` (stdio).
**Licencia:** MIT (repo oficial Anthropic). **Credenciales:** ninguna — path local configurable por usuario. **Ejecución:** 100% local.
**Link verificable:** https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem

**Criterio de elección:** server de filesystem oficial; da al agente acceso controlado a los archivos del escritor sin necesidad de un sistema externo. Acceso confinado al directorio del proyecto. Alternativa Obsidian-MCP añade dependencia de vault y plugin; no adecuada para persona promedio en v0.

**Criterio de cierre (Lead):** test real pendiente de ejecución. Nota de integración crítica: el Agent Runtime debe configurar el path con scope restringido al directorio del proyecto del usuario — no acceso root ni home. Es parámetro de instanciación, no decisión del agente.

**Nits honestos:** ninguno relevante para v0.

---

## 3. Producción / Memoria de contexto largo — `@modelcontextprotocol/server-memory`

**Instalación:** `npx @modelcontextprotocol/server-memory` (stdio).
**Licencia:** MIT (repo oficial Anthropic, marcado experimental/beta). **Credenciales:** ninguna — almacena en JSON local. **Ejecución:** 100% local.
**Link verificable:** https://github.com/modelcontextprotocol/servers/tree/main/src/memory

**Criterio de elección:** único server oficial de memoria con entidades y relaciones. Mantiene un grafo de conocimiento persistente: personajes, arcos narrativos, reglas del mundo, voz del autor; sobrevive entre sesiones. Alternativas como Mem0-MCP existen pero no son oficiales ni tienen el nivel de mantenimiento del repo de Anthropic.

**Criterio de cierre (Lead):** test real pendiente. Tool-belt Engineering debe definir dónde se persiste el grafo JSON (por proyecto o por usuario global) antes de empaquetar.

**Nits honestos:** marcado experimental en el repo; comportamiento en edge cases de grafos grandes no documentado.

---

## 4. Salida / Exportación — `mcp-pandoc`

**Instalación:** `npx mcp-pandoc` + Pandoc instalado en host (stdio).
**Licencia:** MIT (listado oficialmente en el README de `modelcontextprotocol/servers`, 550★, último release v0.8.1 ago-2025).
**Credenciales:** ninguna. **Dependencia de sistema:** Pandoc instalado en el host.
**Link verificable:** https://github.com/vivekVells/mcp-pandoc

**Criterio de elección:** único server MCP maduro para conversión de documentos. Convierte el manuscrito a DOCX, PDF, EPUB, HTML u otros formatos sin salir del flujo. Pandoc es estándar de la industria editorial. Alternativa Google Docs/Notion requieren OAuth y añaden complejidad innecesaria en v0.

**Criterio de cierre (Lead):** test real pendiente. Setup del agente debe verificar si Pandoc está instalado; si no, guiar al usuario a instalarlo o usar un contenedor con Pandoc preinstalado.

**Nits honestos:** dependencia de sistema — el onboarding del agente necesita un paso de verificación de Pandoc que los otros servers no requieren.

---

## 5. Modelo base recomendado

**Recomendación:** frontier (Claude o equivalente) — la spec no especifica modelo concreto para este vertical.
**Criterio:** el escritor creativo no requiere tool-use multi-MCP encadenado de alta precisión (como el tutor STEM); el flujo es principalmente: research → escritura → memoria → exportación con tools individuales. La especificación de modelo concreto queda pendiente para cuando el vertical se reactive.

**Nota:** esta spec fue producida antes del pivot a FINANZAS/MECÁNICA; el modelo base para el vertical writer-es no fue validado con tests.

---

## 6. Framing del agente (registrado para referencia)

**Rol presentado al usuario:** "Tu escritor creativo — te ayuda a investigar, escribir y estructurar tus proyectos literarios."
**Tono:** Colaborativo, no prescriptivo. Habla en español neutro según configuración del usuario.

**Acciones autónomas (sin aprobación):**
- Buscar fuentes en la web para nutrir una escena o personaje
- Leer y escribir archivos del manuscrito dentro del directorio del proyecto
- Guardar y actualizar entidades en memoria (personajes, reglas de mundo, arcos)
- Generar borradores, reescrituras o variantes de fragmentos
- Convertir el manuscrito a un formato de salida dentro del directorio del proyecto

**Acciones que requieren aprobación humana (gate):**
- Eliminar o renombrar archivos existentes del manuscrito
- Sobreescribir una versión final marcada por el usuario
- Exportar a un directorio fuera del proyecto o compartir por cualquier canal externo
- Publicar en cualquier plataforma (Wattpad, Substack, Medium, editorial digital, etc.)

**Gate crítico — NUNCA publica sin aprobación humana explícita.**

---

## 7. Descartados con evidencia

| Descartado | Motivo | Evidencia |
|---|---|---|
| `exa-mcp-server` como elegida | Requiere API key de pago | Credencial obligatoria; no es oficial; aumenta fricción de onboarding para v0 |
| `obsidian-mcp` (StevenStavrakis) como elegida | Requiere plugin Obsidian | No adecuado para persona promedio en v0; añade dependencia de vault y configuración no trivial |
| `Mem0-MCP` como elegida | No oficial | Sin nivel de mantenimiento del repo Anthropic; alternativa externa |
| Google Docs / Notion MCP como elegida | OAuth obligatorio | Añaden complejidad innecesaria en v0; ningún MCP maduro para ninguna de estas plataformas verificado |

---

## 8. Nota para cableado (handoff a Tool-belt Engineering)

**@modelcontextprotocol/server-filesystem:**
```
npx @modelcontextprotocol/server-filesystem <directorio>
# Credenciales: ninguna — path local configurable por usuario
# CRÍTICO: Agent Runtime debe configurar path con scope restringido al directorio del
#          proyecto del usuario (no acceso root ni home). Parámetro de instanciación.
```

**@modelcontextprotocol/server-memory:**
```
npx @modelcontextprotocol/server-memory
# Credenciales: ninguna — almacena en JSON local
# Definir antes de empaquetar: dónde se persiste el grafo (por proyecto o por usuario global)
```

**@modelcontextprotocol/server-fetch:**
```
npx @modelcontextprotocol/server-fetch
# Credenciales: ninguna para uso básico
# Para v1: considerar wrapper con lista de dominios bloqueados o rate limiting
```

**mcp-pandoc:**
```
npx mcp-pandoc
# Pandoc debe estar instalado en el host (dependencia de sistema)
# Setup del agente: verificar presencia de Pandoc; guiar instalación si ausente,
#                  o usar contenedor con Pandoc preinstalado
```

**Alternativas activables sin re-cableado (si elegida falla):**
```
# Research: npx exa-mcp-server (requiere EXA_API_KEY — gateada al operador si se activa)
# Memoria: Mem0-MCP (externo, no oficial)
# Filesystem: sin alternativa directa en v0
# Exportación: sin alternativa directa en v0
```

---

## 9. Supuestos y huecos

### Supuestos asumidos en v0
- El usuario trabaja con archivos locales (no en la nube). Si el flujo principal es Google Docs o Notion, este stack no es el correcto y requiere un cinturón diferente.
- "Publicación" significa exportar un archivo final, no gestionar una cuenta en plataforma.
- El escritor trabaja en español pero los MCP servers son agnósticos al idioma — el framing en español es responsabilidad del prompt del agente, no del tool-belt.

### Huecos explícitos (funciones sin MCP server real maduro hoy)

| Función deseada | Estado actual | Recomendación |
|---|---|---|
| Control de estilo y gramática (LanguageTool, Grammarly) | No existe MCP server oficial ni maduro verificado con comunidad activa. Hay experimentos en GitHub sin mantenimiento. | Dejar para v1. En v0, el modelo base (frontier) maneja estilo directamente en el prompt. |
| Integración con Obsidian (vault como base de conocimiento) | Existe `obsidian-mcp` (StevenStavrakis/obsidian-mcp en npm) pero requiere plugin adicional y configuración no trivial. | Evaluar para v1 cuando el perfil de usuario sea "escritor técnico/avanzado con vault Obsidian". |
| Búsqueda semántica en fuentes (tipo Exa) | Exa MCP existe pero requiere API key de pago. | Candidato directo para v1 si el tier del usuario incluye acceso a APIs externas. |
| Integración con plataformas de publicación (Substack, Medium, Wattpad) | No existe MCP server maduro para ninguna de estas plataformas verificado hoy. | Hueco real. Para v1 se necesita desarrollo custom por Tool-belt Engineering o esperar madurez del ecosistema. |
| Historial de versiones del manuscrito | No existe MCP server de Git/versioning maduro y fácil para la persona promedio. | En v0, filesystem + convención de nombres (`capitulo-01-v2.md`) cubre el caso básico. |

---

## Checklist de validación

- [x] **C1** — Tabla resumen completa: todas las columnas (Categoría / Elegida / Alternativa / Costo / Credenciales / Verificado)
- [x] **C2** — Cada server elegido tiene sección propia numerada (§1 fetch, §2 filesystem, §3 memory, §4 pandoc)
- [x] **C3** — Cada categoría tiene criterio de elección y nota de verificación; tests de ejecución real no eran parte del scope de esta spec (se declara explícitamente: "solo-spec (links verificados, sin ejecución)")
- [x] **C4** — Distinción motor-vs-MCP: no aplica en este belt — todos los servers son wrappers MCP directamente instalables, sin motor intermedio a verificar por separado
- [x] **C5** — Credenciales/gates documentados: Exa-MCP marcada "requiere API key de pago — gateada al operador si se activa en §8"; todos los elegidos "ninguna"
- [x] **C6** — Alternativas activables sin re-cableado listadas en §8 para cada elegida (con advertencias donde aplican)
- [x] **C7** — Descartados con evidencia real: razón técnica concreta para cada uno (OAuth, plugin, API key, falta de mantenimiento)
- [x] **C8** — Modelo base: declarado como pendiente con razón explícita (spec producida antes de pivot; no validado con tests)
- [x] **C9** — Nota de cableado con comandos exactos para handoff a Tool-belt Engineering (§8), incluyendo nota crítica de scope de filesystem
- [x] **C10** — Supuestos y huecos declarados explícitamente en §9: 3 supuestos + 5 huecos con recomendaciones
- [x] **C11** — Estado declarado: HISTÓRICO/FIXTURE
- [x] **C12** — Fuente original referenciada: `org/belts/writer-es-v0.md`
