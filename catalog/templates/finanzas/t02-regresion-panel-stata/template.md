# T02 — Regresión de panel que sale lista para el paper

**ID interno:** t02-regresion-panel-stata  
**Tier:** técnico  
**Fricción de onboarding:** GATEADO — requiere licencia Stata 17+ del usuario  
**Semilla radar:** T2 de P005-radar-finanzas.md

---

## Qué hace el agente (galería del workshop)

Toma tu dataset de panel (firma-año en .dta o CSV), corre efectos fijos con errores estándar clusterizados y produce dos artefactos: (1) el `.do` reproducible que corre limpio desde cero, y (2) la tabla de resultados en convención académica — coeficientes, SE entre paréntesis, estrellas de significancia, N y R² por columna, estilo esttab. Listo para pegar en tu paper o memo de policy.

---

## Servers del belt que usa

| Server | Gate | Por qué |
|---|---|---|
| `mcp-stata` | GATEADO — Stata 17+ licenciado + `STATA_PATH` env | Sin Stata no corre; expone r()/e() para verificar resultados por tool |

**Degradación sin Stata:** si el usuario no tiene licencia Stata, el agente puede correr con `jupyter-mcp-server` + statsmodels/linearmodels para efectos fijos y SE clusterizados. No es idéntico (tabla no es esttab nativo, convención de journal aproximada), pero es funcional. Se declara en el onboarding.

| Server (degradación) | Gate | Por qué |
|---|---|---|
| `jupyter-mcp-server` | Gate de infra — Jupyter propio con JUPYTER_TOKEN | Cubre econometría con pandas/statsmodels cuando no hay Stata |

---

## Parámetros de cirugía (workshop)

| Parámetro | Tipo | Default | Por qué este y no otro |
|---|---|---|---|
| `input_file` | string (path .dta o .csv) | — | El dataset de panel; obligatorio |
| `output_do` | string (path .do) | `./regresion_panel.do` | Dónde guardar el script reproducible |
| `output_table` | string (path .txt/.rtf) | `./tabla_resultados.txt` | Dónde guardar la tabla esttab |
| `var_dependiente` | string | — | Variable Y de la regresión; el agente no puede suponerla |
| `vars_independientes` | list[string] | — | Variables X; el agente las incluye en el do-file |
| `panel_id` | string | `"id_firma"` | Variable de identificación del panel (xtivreg, xtset) |
| `time_var` | string | `"anio"` | Variable de tiempo del panel |
| `cluster_var` | string | igual que `panel_id` | Variable de clustering de SE; por convención en panel = id_firma |

---

## Canales de output

| Canal | Aplica | Por qué |
|---|---|---|
| Archivo .do + .txt | SÍ — primario | El par (do reproducible + tabla) es el entregable del workflow académico |
| Email | SÍ — opcional | Para enviar tabla al co-autor o supervisor |
| WhatsApp | NO | La tabla de regresión y el .do son artefactos técnicos. Un "resumen de resultados" (coeficiente principal + significancia) podría enviarse por WA para comunicación rápida, pero no es el workflow natural de este tier técnico |

---

## Nota de gate (honestidad con el usuario)

Este template requiere Stata 17+ instalado y licenciado. Si al cargar el template el usuario no tiene Stata, el workshop lo declara y ofrece degradación a Jupyter+statsmodels con la advertencia de que la tabla de journal no es idéntica a esttab.
