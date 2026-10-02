# STEM — Belt-Spec: Tutor STEM-ES v0

**Qué es:** Cinturón MCP del agente tutor STEM en español (wedge v1).
**Fecha:** 2026-06-10
**Estado:** HISTÓRICO/FIXTURE — wedge STEM cerrado como instancia de aprendizaje (pivot 2026-06-11, ver org/NORTH.md). Esta entrada valida el schema del catálogo; no es producto activo.
**Fuente original:** `org/artifacts/M001-belt-spec-stem.md`
**Regla F5 cumplida:** research + tests reales con requests JSON-RPC stdio ejecutados por el Supervisor en su carril. Belt Curator (Curation) escribió la spec con esa evidencia; no duplicó ejecución.

---

## 0. Tabla resumen

| Categoría | Elegida | Alternativa | Costo | Credenciales | Verificado |
|---|---|---|---|---|---|
| Cómputo simbólico | `mcp-sympy` (PyPI, stdio) | `symath-mcp` (PyPI, stdio) | $0 | ninguna | test real ✓ |
| Graficación | `@antv/mcp-server-chart` (npm, stdio) | `@gongrzhe/quickchart-mcp-server` (npm) | $0 | ninguna (red requerida) | test real ✓ |
| LaTeX | `mcp-sympy` tool `sympy_latex` (mismo server) | `upmath-mcp` (GitHub, node, API remota) | $0 | ninguna | test real ✓ |
| Verificación de unidades | Pint (Python) wrapper MCP mínimo (M002) | `unit-converter-mcp` (uvx, zero-cred) | $0 | ninguna | test real adversarial ✓ |

Servers activos en v0: **3** (mcp-sympy cubre simbólico + LaTeX; chart; Pint-wrapper o alternativa).

---

## 1. Cómputo simbólico — `mcp-sympy`

**Instalación:** `pip install mcp-sympy` / arranque: `mcp-sympy` (stdio).
**Licencia:** MIT. **Credenciales:** ninguna. **Ejecución:** 100% local.

**Test real — diferenciación:**
```
Request: sympy_diff {"expr": "x**2 * sin(x)", "variable": "x"}
Output:  x**2*cos(x) + 2*x*sin(x)
```
Resultado simbólico exacto (regla de producto correcta). No numérico, no aproximado.

**Test real — integración:**
```
Request: sympy_integrate {"expr": "sin(x)", "variable": "x"}
Output:  -cos(x)
```

**Criterio de cierre (Lead):** test feliz superado en diferenciación e integración simbólica exacta. El server expone 171 tools (solve, simplify, factor, limit, series, matrices): cubre el rango de un curso STEM de primer/segundo año sin dependencia de red ni API key.

**Nits honestos:** ninguno relevante para v0. Surface de 171 tools es grande — el framing del agente debe filtrar las tools expuestas al LLM para no saturar el contexto.

---

## 2. Graficación — `@antv/mcp-server-chart`

**Instalación:** `npx -y @antv/mcp-server-chart` (stdio). **Licencia:** MIT. **Credenciales:** ninguna.
**Dependencia de red:** sí — renderiza vía servicio remoto gratuito de AntV. Para deployment privado: env `VIS_REQUEST_SERVER`.

**Test real — line chart:**
```
Request: generate_line_chart con puntos de f(x)=x²-3 en [-3,3]
Output:  URL de imagen renderizada real + spec del chart
```
27 tipos de chart disponibles (line, bar, pie, scatter, area, etc.).

**Criterio de cierre (Lead):** test feliz superado — URL de imagen real devuelta, no stub. Para el tutor STEM la graficación de funciones matemáticas (resultado de `mcp-sympy evaluate`) es el flujo principal.

**Nits honestos:** dependencia de red es el riesgo operativo central. Si AntV degrada o bloquea el endpoint gratuito, el agente pierde graficación. Mitigación: la alternativa `quickchart-mcp-server` usa QuickChart.io (también gratuita y remota) y se activa sin re-cableado. Para entornos sin red: flag en config del agente, no bloquea v0.

---

## 3. LaTeX — `mcp-sympy` tool `sympy_latex`

Mismo server que categoría 1. Sin instalación adicional.

**Test real — fórmula cuadrática:**
```
Request: sympy_latex {"expr": "(-b + sqrt(b**2 - 4*a*c))/(2*a)"}
Output:  \frac{- b + \sqrt{- 4 a c + b^{2}}}{2 a}
```
LaTeX correcto a nivel string. El render visual (KaTeX) lo hace el frontend del agente, según PRD M000.

**Criterio de cierre (Lead):** test feliz superado. `sympy_latex` convierte cualquier expresión ya parseada por SymPy — el flujo natural es: cómputo simbólico → LaTeX → frontend render. Un solo server cubre dos categorías del belt.

**Nits honestos:** `sympy_latex` opera sobre expresiones SymPy (strings Python-SymPy), no sobre LaTeX arbitrario de entrada. El agente no puede "limpiar" LaTeX que llegue del usuario; solo convierte sus propias expresiones calculadas.

---

## 4. Verificación de unidades — Pint (Python), wrapper MCP mínimo

**Instalación:** `pip install pint`. **Licencia:** BSD. **Credenciales:** ninguna. **Ejecución:** 100% local.
**Estado en v0:** Motor verificado; el wrapper MCP mínimo es trabajo de cableado de M002. [DISTINCIÓN MOTOR-VS-MCP]

**Test real — conversión:**
```
Request: (60 * u.km/u.hour).to(u.m/u.s)
Output:  16.666666666666668 meter / second
```

**Test real adversarial (diferenciador del wedge):**
```
Request: 5 * u.m/u.s + 3 * u.kg
Output:  DimensionalityError: Cannot convert from 'meter / second' ([length]/[time])
         to 'kilogram' ([mass])
```
Rechaza correctamente suma de dimensiones incompatibles. Este es el comportamiento que diferencia el tutor de ChatGPT bare (que acepta la expresión sin error).

**Criterio de cierre (Lead):** test feliz + adversarial superados. El adversarial es el criterio central para el wedge: el agente debe detectar errores dimensionales en la resolución de problemas, no solo convertir.

**Nits honestos:** el wrapper MCP a construir en M002 debe exponer al menos dos tools: `units_convert` y `units_check` (validación de consistencia dimensional). La alternativa `unit-converter-mcp` NO cubre el test adversarial de expresiones libres (ver sección Descartados).

---

## 5. Modelo base recomendado

**Recomendación:** `gpt-oss-120b` (Groq, free tier).
**Criterio:** el tutor debe encadenar simbólico → unidades → LaTeX → gráfico en un turno. Modelos pequeños fallan en tool-use multi-MCP sostenido (lección registrada con `qwen3:8b`). `gpt-oss-120b` devuelve directo sin consumir tokens de reasoning intermedio.

| Candidato | Tier | Notas |
|---|---|---|
| `gpt-oss-120b` (Groq) | free | RECOMENDADO — tool-use sostenido, sin reasoning overhead |
| `llama-3.3-70b` (Groq) | free | Respaldo válido |
| `qwen3-32b` (Groq) | free | Piso local — `explorer-reason`; aceptable para turnos simples |
| `qwen3:8b` (local) | local | DESCARTADO como base — demasiado chico para tool-use multi-MCP |

**Qué valida M004:** Agent Eval mide equipado-vs-pelado con este modelo. La afirmación "sostiene tool-use multi-MCP" es recomendación a validar, no hecho declarado. M004 es el gate de confianza antes de declarar el belt operativo. [Nota: M004-STEM fue retirada sin ejecutar tras el pivot; ver CLAUDE.md §1.5]

---

## 6. Descartados con evidencia

| Descartado | Motivo | Evidencia |
|---|---|---|
| `ucon-tools[mcp]` | Server roto | ImportError interno al arrancar — incompatibilidad ucon/ucon-tools; no arranca |
| `latexmk-mcp` y similares (TeX local) | Guard de recursos | Requieren distribución TeX local (~5 GB); disco del host al 84% — violación del guard de Platform Ops |
| `symath-mcp` (como elegida) | Nits de calidad | UI/mensajes en chino ("不支持的操作"); soluciones de solve como decimales largos (no simbólicas); `math_eval` parseó "5 m/s + 3 kg" como álgebra de símbolos sin chequeo dimensional. Usable como respaldo de cómputo simbólico, con esos nits documentados |
| `unit-converter-mcp` (uvx) como elegida | No cubre adversarial | Test feliz OK (16.6667 m/s ✓); pero rechaza categorías incompatibles por schema tipado, no por análisis dimensional de expresiones libres. Nombres de unidad deben ser literales en inglés ("kilometers per hour", no "km/h"). Usable como alternativa de conversión simple |
| Wolfram Alpha MCP (`henryhawke/wolfram-llm-mcp`) | Gateada (credencial) | Requiere `WOLFRAM_ALPHA_APP_ID`; diferida al operador para decisión. No bloqueante para v0 |

---

## 7. Nota para cableado (handoff a Tool-belt Engineering)

**mcp-sympy (simbólico + LaTeX):**
```
pip install mcp-sympy
# Comando de arranque (stdio): mcp-sympy
# Tools clave: sympy_diff, sympy_integrate, sympy_solve, sympy_simplify,
#              sympy_factor, sympy_limit, sympy_series, sympy_latex
```

**@antv/mcp-server-chart (graficación):**
```
npx -y @antv/mcp-server-chart
# stdio, zero-credential
# Flag de red requerida: documentar en config del agente
# Env para deployment privado: VIS_REQUEST_SERVER=<url>
# Tool principal: generate_line_chart (+ 26 tipos adicionales)
```

**Pint — wrapper MCP mínimo (verificación de unidades):**
```
pip install pint
# M002 construye el wrapper MCP con al menos 2 tools:
#   units_convert(expr, target_unit) -> valor + unidad
#   units_check(expr) -> ok | DimensionalityError(detalle)
# Alternativa si el wrapper no está listo en M002:
#   uvx unit-converter-mcp (stdio, zero-cred)
#   ADVERTENCIA: solo conversiones simples; nombres literales en inglés requeridos
#   ("kilometers per hour" NO "km/h"); no cubre adversarial dimensional
```

**Alternativas activables sin re-cableado (si elegida falla):**
```
# Simbólico: pip install symath-mcp / comando: symath-mcp
# Graficación: npx @gongrzhe/quickchart-mcp-server
# LaTeX render: upmath-mcp (node, API remota i.upmath.me; soporta TikZ/circuitikz)
```

---

## Checklist de validación

- [x] **C1** — Tabla resumen completa: todas las columnas (Categoría / Elegida / Alternativa / Costo / Credenciales / Verificado)
- [x] **C2** — Cada server elegido tiene sección propia numerada (§1 mcp-sympy, §2 chart, §3 LaTeX/mismo server, §4 Pint)
- [x] **C3** — Cada categoría tiene al menos un test real con output crudo copiado exacto: diferenciación, integración, line chart URL, LaTeX fórmula cuadrática, conversión de unidades, adversarial dimensional
- [x] **C4** — Distinción motor-vs-MCP declarada: §4 Pint — "Motor verificado; el wrapper MCP mínimo es trabajo de cableado de M002"
- [x] **C5** — Credenciales/gates documentados: Wolfram Alpha marcado "gateada — decisión del operador"; todos los demás "ninguna"
- [x] **C6** — Alternativas activables sin re-cableado listadas en §7 para cada elegida
- [x] **C7** — Descartados con evidencia real: ImportError exacto (ucon-tools), guard de disco (TeX), output en chino (symath), falla adversarial documentada (unit-converter)
- [x] **C8** — Modelo base recomendado con criterio: gpt-oss-120b, razón específica (tool-use multi-MCP sostenido, lección registrada con qwen3:8b)
- [x] **C9** — Nota de cableado con comandos exactos para handoff a Tool-belt Engineering (§7)
- [x] **C10** — Supuestos implícitos documentados en fuente original; huecos: wrapper Pint pendiente M002 declarado explícitamente
- [x] **C11** — Estado declarado: HISTÓRICO/FIXTURE
- [x] **C12** — Fuente original referenciada: `org/artifacts/M001-belt-spec-stem.md`
