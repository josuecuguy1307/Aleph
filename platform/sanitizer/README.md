---
entregar_a: [toolbelt, frontend]
pieza: engineering/PARAMETRIZABLE
mision: 2026-06-11-0013-saneo-formulas-escritura
vector_mitigado: P010 / A4 (CSV-formula-injection, CWE-1236)
---

# platform/sanitizer — Saneo de fórmulas en el camino de escritura

Interceptor genérico del runtime que neutraliza **inyección de fórmula/DDE en archivos
entregados** (CWE-1236). Nació del nit-grave del Reviewer en el threat-model 0011: cada
gate del agente es server-side y pre-entrega, pero un `.xlsx`/Sheet se abre **client-side,
después** de todos los gates. Si entra texto no confiable (celda ajena, nota de un filing
SEC) que empieza con `= + - @`, la app de planilla lo evalúa en la máquina de la víctima.

## Qué hace

- **`formula_guard.py`** — `FormulaGuard`, inspector puro (sin I/O, sin deps de Excel).
  Un valor-celda es peligroso si es cadena cuyo primer char no-espacio ∈ `= + - @`. Si su
  forma no está en la **lista blanca de fórmulas legítimas del template**, se **neutraliza**
  (prefijo `'` → celda `t="inlineStr"`, texto inerte, sin `<f>`) o se **rechaza con log**
  (`policy="reject"`). Funciones siempre-prohibidas (`HYPERLINK`, `WEBSERVICE`, `IMPORT*`,
  `DDE`, `CALL`, `RTD`…) y la firma DDE `|...!` se bloquean **aunque** un template las pida.
- **`runtime_overlay.py`** — `install(registry)` envuelve `ToolRegistry.call` de forma
  **aditiva** (rebind de un método de instancia; **`assembler.py` no se toca**). Cubre
  `write_data_to_excel`, `apply_formula`, y los writes de Sheets (`batch_update_cells`,
  `update_cells`, `add_rows`). Un solo interceptor → todo template que escribe planilla.
- **`demo_neutralize.py`** — reproductor: corre los 3 payloads + el control y abre el xlsx
  producido para mostrar el estado real de la celda (el Reviewer lo re-corre tal cual).

## Cómo se integra (toolbelt / frontend)

```python
from platform.sanitizer.runtime_overlay import install, default_guard
install(registry, guard=default_guard())   # una línea, antes del tool-use loop
```

La **lista blanca es el único parámetro por nicho** (`FINANZAS_TEMPLATE_FUNCTIONS` es la
instancia finanzas: SUMIFS, VAR/STDEV, lookup, date/text helpers). Cualquier vertical pasa
la suya. Frontend: cuando una celda se neutraliza, el `on_event` da el material para
avisar al usuario *"reemplazamos una fórmula sospechosa por texto"* en la vista previa.

## Verificación

`python3 -m pytest platform/sanitizer/tests/ -v` → **11/11**. Los 3 ataques quedan inertes
y las 2 fórmulas legítimas siguen vivas, comprobado **a nivel XML del archivo producido**
(`t="inlineStr"` sin `<f>` para los ataques; `<f>` real para SUMIFS/VAR).

---

## POSICIÓN (Fase 15)

**Recomendación:** adoptar el interceptor como **default-on** en el runtime para todo
template que escriba planillas, vía `install()` (sin tocar el assembler). Cerrar el vector
A4 de P010 como **mitigado**. Política por defecto: **`prefix`** (apóstrofo) — deja un
artefacto visible-pero-inerte que el usuario puede inspeccionar — con `reject` disponible
para flujos que prefieran muro duro.

**3 números:**
1. **3/3** payloads del threat-model neutralizados, verificados a nivel XML (sin elemento
   `<f>`, `t="inlineStr"`) — no por aserción de API, por los bytes del archivo.
2. **2/2** fórmulas legítimas de template (T01 SUMIFS, T05 varianza) **siguen vivas** como
   `<f>` real — falso-positivo = 0 en el control (lección M002 honrada).
3. **0** líneas de `assembler.py` modificadas y **0** parches por template: 1 interceptor
   genérico en `ToolRegistry.call` cubre los 5 templates que escriben planilla (T01,03,05,07,10).

**Confianza: ALTA** en el mecanismo (la inertness está garantizada por el tipo `inlineStr`
del archivo, no por una convención frágil; los 3 payloads canónicos están cubiertos y la
lista de funciones prohibidas es explícita). **MEDIA** en la cobertura exhaustiva de la
lista blanca: la derivamos de T01/T05 + helpers comunes; un template real con una fórmula
legítima fuera de la lista daría falso-positivo (se neutralizaría algo válido) — fácil de
arreglar (agregar la función), pero hay que medirlo contra los 10 templates corriendo.

**Qué cambiaría la conclusión:**
- Si un template legítimo usara una función **no** en la lista blanca y que **sí** tenga
  superficie de I/O (improbable en finanzas, pero p.ej. un vertical que use `RTD` para
  datos en vivo) → habría que decidir caso por caso y la regla "prohibida siempre" cedería.
- Si la víctima abre el archivo en un cliente que **ignora el `'` y re-evalúa `inlineStr`**
  como fórmula (no conocemos uno; Excel/LibreOffice/Sheets no lo hacen) → el prefijo no
  bastaría y habría que mover todo a `policy="reject"` por defecto.
- Si apareciera un payload que **no** lidera con `= + - @` ni dispara una función prohibida
  pero igual ejecuta en algún cliente → ampliaría el set de chars/firmas y bajaría la
  confianza hasta re-verificar.
