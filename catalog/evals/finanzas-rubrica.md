# RÚBRICA DE CALIDAD — task-set FINANZAS (T1-T5)

> **PRE-ESCRITA 2026-06-11, ANTES de cualquier corrida** (anti-gaming
> EVAL-FRAMEWORK-SPEC §3: la rúbrica no se ajusta después de ver outputs).
> Misión 2026-06-11-0018 · rnd-eval-designer (Fable 2, squad Agent Eval).
>
> **Capa 0 — COMPLETÓ (binaria, la decide el checker mecánico, no el juez):**
> el artifact existe, abre, y pasa el checker del task-set. Si no completó,
> calidad = N/A (no se califica prosa sobre un artifact que no existe).
>
> **Capa 1 — CALIDAD 0-2 (solo sobre celdas que completaron):**
> tres ejes del spec (rigor · verificabilidad · formato profesional), cada uno 0-2
> con los criterios concretos de abajo. **Score de celda = min(rigor, verificabilidad,
> formato)** — el mínimo, no el promedio: un estado de resultados con totales que no
> cuadran es inservible por elocuente que sea el resto.

## Variantes cero-fricción declaradas (gates sin key en este entorno)
- **T2**: Stata no está licenciado en esta máquina → variante Python (statsmodels OLS
  con efectos fijos y SE clusterizados). Misma exigencia E1-E4; la convención de tabla
  journal se exige igual.
- **T3**: sin red dentro del sandbox de ejecución → fundamentals pre-extraídos a CSV
  con columna `fuente_filing` (el modelo DEBE citarla en footnotes). E1 se conserva
  (archivo crudo); E2/E3/E4 intactos.
- **T4**: FRED API key es gate → las series vienen en el CSV fixture (formato largo,
  como las exporta FRED). SAAR/YoY se exige igual.
- **T5**: Google Sheets exige cuenta GCP → variante xlsx local con formato condicional
  real (openpyxl lo serializa y el checker lo lee). Convención F/U intacta.

---

## T1 — Cierre mensual (xlsx sucio → estado de resultados con fórmulas vivas)

**Completó (checker):** existe `estado_resultados.xlsx`, abre con openpyxl, tiene ≥2
hojas, y la hoja de estado de resultados contiene ≥3 fórmulas vivas (`=SUM`/`=SUMIF`).

| Eje | 0 | 1 | 2 |
|---|---|---|---|
| Rigor | Totales del P&L difieren >1% del recálculo sobre datos limpios, o no dedupe (los 12 duplicados siguen contando) | Totales cuadran ±1% pero la limpieza es parcial (fechas mixtas no normalizadas O categorías inconsistentes no unificadas) | Dedupe correcto (520→507 filas según T1-reference.json), fechas normalizadas, categorías unificadas, totales cuadran exacto (±0.01) |
| Verificabilidad | Valores pegados (sin fórmula viva en los totales) | Fórmulas vivas en totales pero referencian rangos hardcodeados parciales (no cubren todas las filas limpias) | SUMIFS/SUM vivos que referencian la hoja de datos limpios completa; cambiar un dato fuente cambia el total |
| Formato | Sin estructura de estado de resultados (volcado de números) | Estructura P&L reconocible pero sin convención: negativos sin paréntesis O sin subtotales (utilidad bruta/operativa/neta) | Orden NIIF/GAAP (ingresos → costo → ut. bruta → opex → ut. operativa → ut. neta), subtotales presentes, formato numérico con negativos entre paréntesis |

## T2 — Regresión de panel con tabla formato journal (variante Python)

**Completó (checker):** existe `regresion_panel.py`, corre limpio (exit 0) con el python
del harness, y produce `tabla_regresion.md` (o .txt).

| Eje | 0 | 1 | 2 |
|---|---|---|---|
| Rigor | Corre OLS pooled sin efectos fijos, o el coeficiente de `inversion_id` difiere >20% del de referencia FE-within | Efectos fijos correctos pero SE NO clusterizados por firma (usa SE clásicos/robustos simples) | FE por firma + SE clusterizados por firma; coeficientes ±5% de la referencia |
| Verificabilidad | El .py no es reproducible (paths absolutos de su sandbox, seeds faltantes, no corre dos veces igual) | Corre reproducible pero no reporta N y R² en la tabla | Corre reproducible; tabla reporta coef, SE, N, R² por columna; los números salen del objeto de resultados, no tipeados a mano |
| Formato | Volcado de summary() crudo | Tabla propia pero sin convención: faltan SE entre paréntesis O estrellas de significancia | Convención journal: coef con SE entre paréntesis debajo, estrellas (* p<0.10, ** p<0.05, *** p<0.01), N y R² al pie |

## T3 — Tabla de comps con fundamentals citados (variante fixture)

**Completó (checker):** existe `comps.xlsx`, abre, contiene fórmulas vivas para los
múltiplos y una fila de mediana con `=MEDIAN`.

| Eje | 0 | 1 | 2 |
|---|---|---|---|
| Rigor | EV mal construido (olvida deuda o caja) o múltiplos difieren >2% del recálculo | EV correcto pero algún múltiplo usa el dato equivocado (P/E con ingreso operativo, etc.) | EV = mkt cap + deuda − caja; EV/EBITDA, EV/Revenue, P/E correctos ±0.5%; outlier señalado |
| Verificabilidad | Múltiplos pegados como valores | Fórmulas vivas pero sin las columnas fuente en el workbook (no se puede auditar de dónde sale) | Fórmulas vivas que referencian columnas de datos crudos dentro del workbook; cada número rastreable |
| Formato | Sin mediana o usa promedio como agregado | Mediana presente pero sin footnotes de filing | Mediana (=MEDIAN) como agregado, footnote por ticker citando el filing fuente (`fuente_filing` del fixture), outlier marcado |

## T4 — Brief macro reproducible (variante CSV local)

**Completó (checker):** existe `brief_macro.ipynb`, ejecuta end-to-end sin error vía
nbclient, y produce una tabla final con las tres series.

| Eje | 0 | 1 | 2 |
|---|---|---|---|
| Rigor | Confunde MoM con MoM anualizado, o YoY mal calculado (>0.1pp vs referencia) | YoY correcto pero anualización MoM sin compuesto (multiplica ×12 en vez de ^12) | MoM anualizado compuesto ((p_t/p_{t-1})^12−1) para CPI, YoY correcto para las 3 series, ±0.05pp de referencia |
| Verificabilidad | El notebook no corre end-to-end (celdas rotas, estado oculto) | Corre pero con celdas muertas/sin orden (depende de ejecución manual previa) | Corre limpio top-to-bottom en kernel fresco; números de la tabla salen del cómputo, no tipeados |
| Formato | Sin gráfico ni tabla final | Tabla final presente pero sin unidades/períodos claros, o gráfico sin ejes etiquetados | ≥1 gráfico etiquetado + tabla final con período, serie, YoY y MoM anualizado, unidades explícitas (%, pp) |

## T5 — Varianza budget-vs-actual con convención F/U (variante xlsx local)

**Completó (checker):** el workbook entregado (`varianzas.xlsx`) tiene una hoja nueva de
varianzas con fórmulas vivas y ≥1 regla de formato condicional serializada.

| Eje | 0 | 1 | 2 |
|---|---|---|---|
| Rigor | Varianzas con signo crudo (actual−budget) sin convención F/U (gasto mayor aparece "positivo") | F/U correcto en ingresos pero invertido o inconsistente en líneas de gasto | Convención F/U correcta en TODAS las líneas: ingreso ↑ = F, gasto ↑ = U; magnitudes cuadran ±0.01 |
| Verificabilidad | Varianzas pegadas como valores | Fórmulas vivas pero no referencian las hojas de budget/actual fuente | Fórmulas vivas cruzando hojas budget/actual; recalculables |
| Formato | Sin formato condicional ni etiquetas F/U | Formato condicional presente pero sin bridge de las 3 mayores varianzas | Formato condicional aplicado + etiquetas F/U + bridge textual identificando las 3 mayores varianzas con explicación |

---

## Disciplina de aplicación
1. El checker mecánico decide COMPLETÓ antes de que el juez vea el output.
2. El juez (eval-designer) califica SOLO contra esta tabla; criterio no listado = no puntúa.
3. Si un modelo chico empata o gana al grande, se reporta tal cual.
4. El Reviewer re-corre ≥2 celdas y re-aplica esta rúbrica a ciegas (verify-before-trust).
5. Esta rúbrica es INSTANCIA del nicho finanzas; el runner jamás la importa — vive acá.
