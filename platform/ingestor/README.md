# Ingestor — `raw file → estructurado + provenance`, refresh determinista $0

> FOUNDRY · Fase 4 · Bloque C · C1 (Backend/API). Build-item determinista, **NO un
> conector**. C2 lo aplica a MinEduc/BCE/INEC; C3 registra cada receta como REUSABLE.

## Los dos relojes (el porqué)

```
   archivo crudo (PDF/CSV)
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │  RELOJ LENTO — una sola vez, caro            │
   │  el modelo AUTORA la "receta de parseo":     │   ← offline / documentado.
   │  qué página·tabla, orientación, cómo limpia  │     se persiste como JSON.
   │  cada columna, qué filas saltar              │
   └─────────────────────────────────────────────┘
        │   (recipes/<fuente>.json)
        ▼
   ┌─────────────────────────────────────────────┐
   │  RELOJ RÁPIDO — cada refresh, ms, $0          │
   │  el CÓDIGO determinista corre la receta:      │   ← cero LLM, cero red.
   │  extrae · limpia · valida · adjunta provenance│     probado por test.
   └─────────────────────────────────────────────┘
        │
        ▼
   data ESTRUCTURADA, cada dato con su provenance (fuente + locator + raw)
```

Mandar el PDF al modelo cada refresh quema budget para siempre. Acá el modelo paga
**una vez** por entender la fuente; el refresh es código puro. Un refresh sobre el
mismo archivo produce salida **byte-idéntica** y no importa ningún cliente de modelo
(`test_no_cognition.py` lo prueba con un tripwire en `sys.meta_path`).

## Piezas

| Archivo | Qué es |
|---|---|
| `cleaners.py` | Limpiadores **puros** por columna (número latino/inglés, %, fecha, texto). Cada uno devuelve `CleanResult` — un valor que no parsea es **error explícito**, nunca un número adivinado. |
| `extractors.py` | Extracción determinista del grid crudo: `pdfplumber` (PDF) / `csv` (CSV). Incluye `pdf_page_is_textual` (guard anti-escaneado). |
| `provenance.py` | `Source` (file+sha256+url+fetched_at) · `Locator` (página·tabla·fila·columna·labels) · `Datum` (valor + provenance + audit de limpieza). |
| `runner.py` | El motor del refresh. Toma `ParseRecipe` + archivo → `Datum`s. Format-blind, nicho-agnóstico. Orientaciones `matrix` y `records`. **No importa ningún módulo de cognición/red.** |
| `ingest_cli.py` | CLI del refresh. |
| `recipes/*.json` | Recetas de parseo persistidas (artefacto reusable por fuente — C3). |
| `fixtures/` | Archivo crudo real (PDF BCE) + CSV de muestra con celda-error. |

## La receta de parseo (`recipes/<fuente>.json`)

Concepto **distinto** de la "receta del agente" (`product/recipes/`, el config del
assembler). Para no chocar, esta lleva `schema_version: "ingestor-recipe/v1"`.

Campos: `source_kind` (pdf|csv) · `orientation` (matrix|records) · localización
(`page`/`table_index` PDF, `delimiter`/`encoding` CSV) · forma (`header_rows_to_skip`,
`skip_blank_value_rows`, `row_label_cleaner`) · `columns[]` (label + `cleaner` +
`cleaner_opts` + `field`) · bookkeeping (`source_url`, `notes`).

**Agregar una fuente = escribir una receta, no recodear** (es lo que hará C2).

## Correr un refresh

```bash
cd platform/ingestor
python3 ingest_cli.py \
  --recipe recipes/bce-estmacro-comercializacion-derivados.json \
  --raw fixtures/bce_estmacro012024.pdf \
  --json /tmp/out.json
```

## Provenance — el bar anti-fabricación

Cada dato estructurado lleva su origen para que un agente delegado pueda **citar**, no
alucinar. Ejemplo real (PDF BCE, p.15):

```
valor_2023 = -2128100.0   <- raw '-2.128.100'
provenance: bce_estmacro012024.pdf [p.15, row='DIFERENCIA INGRESOS Y EGRESOS (miles de dólares)', col='2023'] (sha256 2175bad6857a…)
```

- `sha256` detecta drift: si los bytes del archivo cambian, el hash cambia.
- `raw` se preserva siempre → una limpieza es auditable contra la fuente.
- Una celda que no parsea → `Datum(ok=False, error=...)`, **no** un valor inventado.
- Una página PDF image-only → el runner la **rechaza** (no emite filas vacías).

## Evidencia (re-corrible por el Reviewer)

```bash
python3 -m pytest tests/ -q          # 10/10
```

- `test_refresh_is_deterministic_byte_identical` — 2 refreshes = salida idéntica.
- `test_refresh_imports_no_cognition_module` — tripwire: 0 imports de modelo/red.
- `test_provenance_present_on_every_datum` — sin número desnudo.
- `test_csv_records_with_error_cell_reported_not_faked` — celda mala = error, no invento.

## Deuda honesta

- `extract_csv_table` lee el CSV entero en memoria — fino para boletines; un CSV de
  GBs necesitaría streaming (no es el caso de las fuentes BCE/INEC/MinEduc).
- pdfplumber `extract_tables` usa heurística de líneas/texto; tablas con celdas
  fusionadas raras pueden necesitar `table_settings` afinado en la receta (previsto:
  el campo existe). Cada receta nueva debe validarse contra su extracción real.
- FRED (fallback CSV financiero) dio **timeout desde esta IP** durante el build — no
  bloqueó (el PDF BCE es la fuente real usada); se reporta crudo, no se maquilló.
- **Contexto de grupo en tablas matrix anidadas (hallazgo del Reviewer):** en la tabla
  BCE p.15 las filas-grupo (Nafta/Diésel/GLP) no tienen valores y se saltan; por eso
  3 filas distintas comparten el `row_label` "Diferencia Ingreso y Costo". Quedan
  inequívocas por `row_index` (5/12/19) y la provenance es exacta, pero el **derivado**
  no se propaga al label. Mejora prevista para C2: campo opcional `group_label_rows` en
  la receta que arrastre la última fila-grupo como contexto. NO es fabricación — los
  datos son correctos y citables hoy; es enriquecimiento semántico diferido.
- C2 conectará MinEduc/INEC; C3 registra las recetas como REUSABLE en el ledger.
