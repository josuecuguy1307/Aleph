# Recetas de los 5 nichos — Caso HOLY SHIT + Bar de calidad

**Qué es:** por nicho del build (Cowork · Research · Programación · Educación · Finanzas),
(a) el caso **HOLY SHIT** concreto — la tarea que prueba VALOR, no "agente de X" generico —
y (b) el **BAR DE CALIDAD** explicito: contra qué juzga persona usuaria que el output es "bueno".
**Carril:** Product (dueño del wedge). **Fecha:** 2026-06-15 (FASE 1).
**Contrato:** las recetas viven en `product/recipes/<nicho>.config.json`, validadas contra
el schema v1 anidado A+A+C (`platform/assembler/RECIPE-SCHEMA.md`). Tools elegidas del
menu B1/B2/B3 de `org/artifacts/FASE0-tabla-tool-caso-bucket.md`.

> **Principio del bar:** el bar es la **diferencia medible contra el modelo pelado**
> (ChatGPT/Gemini sin belt). Si un generalista lo hace igual de bien, no es el bar — es ruido.
> Cada bar es un criterio binario que persona usuaria (o Agent Eval) puede marcar pass/fail mirando el
> output, NO una vibe. Esto es lo que Agent Eval mide como "equipado vs pelado".

---

## 1. FINANZAS — `finanzas.config.json`
**Belt:** `catalog/belts/finanzas.md` (7 servers sondados, test real ✓). Receta cabla
secedgar + excel (B1, cero-friccion, surface sondado) + fred + alphavantage (B2, key gratis).
Sheets/Stata quedan FUERA de la receta v0: **gateados a persona usuaria** (GCP / licencia).

### Caso HOLY SHIT
> "Armame la tabla de **comparables (trading comps)** de Apple contra 3 peers
> (Microsoft, Google, Amazon): trae revenue, net income y EBITDA del ultimo 10-K
> de **cada uno desde el filing de la SEC**, calcula los multiplos (P/E, EV/EBITDA)
> en un **Excel con las formulas vivas** (no numeros pegados), y dejame anotado de
> qué filing salió cada número."

Por qué es HOLY SHIT y no generico: encadena **multi-MCP real con costo de error alto** —
sec-edgar (CIK -> financials, fuente primaria con cita) -> excel (workbook con `<f>` vivas) ->
verificacion cruzada. ChatGPT pelado **alucina los numeros** (no tiene el filing) y entrega
celdas con valores pegados que no se recalculan. Aquí cada número rastrea a un filing real.

### Bar de calidad (pass/fail observable)
1. **Cita al filing:** cada número de los estados financieros trae el origen (CIK + form +
   periodo). Cero números sin procedencia. *(pelado: inventa o cita "memoria")*
2. **Fórmulas vivas:** los multiplos en el .xlsx existen como `<f>` en el XML
   (ej. `=EV/EBITDA`), recalculables si cambia un input — NO valores pegados.
   *(pelado: pega numeros muertos)*
3. **Precisión exacta:** los numeros coinciden con el 10-K (sin redondeo silencioso);
   el filing manda, no la estimacion del modelo.
4. **Honestidad de hueco:** si un peer no reporta EBITDA directo, lo dice y muestra cómo
   lo derivó — no lo inventa.
5. **Gate de plata:** ninguna accion que toque dinero/cuentas se ejecuta sin OK (la receta
   declara `money_touch: needs_ok`; el motor lo fuerza por §3.5 aunque la receta dijera off).

---

## 2. EDUCACIÓN — `educacion.config.json`
**Belt:** `catalog/belts/stem.md` (3 servers, test real ✓; `units` = MOAT M002, test
adversarial ✓). Tutor STEM-ES — el unico nicho con MOAT ya construido (`units_check`).

### Caso HOLY SHIT
> "Resolveme este problema de física: un bloque de 5 kg baja por un plano inclinado a
> 30° con μ=0.2. Quiero la aceleración **paso a paso con el método que pide mi profe**
> (diagrama de cuerpo libre -> ecuaciones -> despeje), las **unidades chequeadas**
> en cada paso, y una **gráfica** de v(t) los primeros 3 segundos."

Por qué es HOLY SHIT: el dolor exacto del ICP — ChatGPT da pasos plausibles con **unidades
mal y resultados alucinados**. Aquí sympy hace el simbólico EXACTO, el wrapper Pint
**rechaza** una suma dimensionalmente incoherente (ej. "5 m/s + 3 kg" -> DimensionalityError),
y la gráfica sale de la función resuelta, no de puntos inventados.

### Bar de calidad (pass/fail observable)
1. **Rigor simbólico:** la derivación/despeje viene de `sympy` (exacto, no aproximado);
   se puede re-derivar y da lo mismo. *(pelado: pasos plausibles, a veces mal)*
2. **Unidades coherentes:** cada paso pasa `units_check`; si el alumno mete una operacion
   dimensionalmente imposible, el agente la **rechaza** y explica — no la "resuelve" igual.
3. **Método del curso:** sigue la estructura que el RAG de material del profe define
   (DCL -> ΣF=ma -> despeje), no un atajo distinto. *(este es el diferenciador del RAG)*
4. **Gráfica fiel:** la curva v(t) sale de la función resuelta (URL de imagen real de `chart`),
   los ejes rotulados con unidades — no un dibujo ilustrativo.
5. **Sin gates:** nicho de cero consecuencia (no toca plata ni manda) — `gates: off/off`.

---

## 3. RESEARCH — `research.config.json`
**Belt:** `catalog/belts/research.md` (a curar por Curation; tools son MCPs **conectados
en este entorno**: exa, huggingface, context7 — evidencia directa tabla FASE 0 §5).
MOAT del nicho = el harness verificacion-adversarial + reporte citado (B3).

### Caso HOLY SHIT
> "Quiero un brief de 1 página sobre el **estado del arte en cuantización de LLMs a 4-bit
> en 2025**: busca los papers clave, los repos/modelos relevantes, **verifica que cada
> claim tenga fuente**, y dame el reporte con **citas a cada afirmación** y una nota de
> qué quedó sin confirmar."

Por qué es HOLY SHIT: fan-out (exa web + huggingface papers/repos + context7 docs) ->
**verificación adversarial** (cada claim contra su fuente) -> síntesis CITADA. ChatGPT pelado
entrega un resumen fluido **sin respaldo verificable** y con citas a veces fabricadas. Aquí
cada afirmación rastrea a una fuente real fetchada.

### Bar de calidad (pass/fail observable)
1. **Toda afirmación citada:** cada claim del reporte tiene fuente (URL/paper id) que existe
   y dice lo que el reporte dice. Cero citas fabricadas. *(pelado: inventa citas)*
2. **Fan-out real:** usó ≥2 fuentes distintas (web + papers/repos), no una sola búsqueda.
3. **Verificación adversarial:** el agente marca explícitamente lo que **no pudo confirmar**
   en vez de presentarlo como hecho. *(pelado: presenta todo con igual confianza)*
4. **Trazable:** un humano puede abrir cada cita y comprobarla en <1 min.
5. **Sin gates:** solo lee/escribe archivos locales — `gates: off/off`.

---

## 4. PROGRAMACIÓN — `programacion.config.json`
**Belt:** `catalog/belts/programacion.md` (github + context7 **conectados**, tabla FASE 0 §6).
MOAT del nicho = el **script-runner sandbox** (B3, a construir por AI/ML) — corre tests sin
reventar el host. La receta declara su contrato de tools (`script_runner`) aunque la pieza
esté en build: el cableado de tool real lo hace AI/ML; Product define qué pide la receta.

### Caso HOLY SHIT
> "En este repo hay un bug: la función `parse_date` revienta con fechas en formato
> ISO con timezone. Arreglalo, **corré los tests** y mostrame que pasan — y si no había
> test para ese caso, **agregá uno** que lo cubra."

Por qué es HOLY SHIT: edita código (filesystem) + consulta docs al día (context7) + **corre
los tests en sandbox** y solo declara verde con el **pass real del runner**. ChatGPT pelado
dice "esto debería funcionar" sin ejecutar nada. Aquí el verde es del runner, no del modelo.

### Bar de calidad (pass/fail observable)
1. **Verde real, no prometido:** el "pasa" viene del output del runner (pytest/jest), no de
   la afirmación del modelo. Si no corrió, no está verde. *(pelado: "deberia funcionar")*
2. **Test que cubre el bug:** existe un test nuevo que **falla antes** del fix y **pasa
   después** — prueba que el fix arregla EL caso reportado.
3. **Sin regresiones:** la suite completa sigue verde tras el cambio (no rompió otra cosa).
4. **Docs al día:** si usó una API, la verificó contra context7 (versión actual), no de memoria.
5. **Gate de salida:** `git push` / abrir PR = `send: needs_ok` (sale del sandbox; el motor lo
   fuerza). Editar/correr local = libre.

---

## 5. COWORK — `cowork.config.json`
**Belt:** `catalog/belts/cowork.md` (google_drive/calendar/gmail/slack **conectados**, tabla
FASE 0 §7). PRECONDICIÓN dura: el **send-gate** (B3, Security) debe existir antes de cablear
envío. Por eso la receta solo cabla **lectura + draft + agenda**, NUNCA `send_message` directo,
y declara `send: needs_ok`.

### Caso HOLY SHIT
> "Tengo que mandar el resumen de la reunión de ayer al equipo. Buscá las notas en mi Drive,
> revisá el hilo de Slack del proyecto, **redactá el correo de resumen** con los action items,
> y proponé **3 horarios** para el follow-up mirando mi calendario — **dejámelo todo en
> borrador para que yo apruebe antes de mandar**."

Por qué es HOLY SHIT: cruza Drive + Slack + Calendar + Gmail en una tarea de oficina real,
y respeta la frontera de confianza — **prepara todo pero no manda ni invita sin OK**. ChatGPT
pelado no tiene acceso a tu Drive/correo; un agente mal diseñado mandaría sin preguntar. Aquí
el valor es el trabajo hecho + la **delegación segura**.

### Bar de calidad (pass/fail observable)
1. **Contexto real cruzado:** el borrador usa contenido REAL del Drive y del hilo de Slack
   (no genérico) — se nota que leyó las fuentes. *(pelado: no tiene acceso)*
2. **Nada se envía sin OK:** el correo queda como **draft** y los horarios como **propuesta**;
   ningún `send`/invite se ejecuta sin aprobación. La receta declara `send: needs_ok` y el
   motor lo fuerza (§3.5) — aunque la receta dijera off, el gate aplica por clasificación.
3. **Horarios válidos:** los 3 slots propuestos son huecos reales libres del calendario
   (find_free_time), no inventados.
4. **Action items fieles:** los del resumen salen de las notas/hilo, no agregados de la nada.
5. **Preview antes del gate:** el agente muestra QUÉ va a mandar y A DÓNDE antes de pedir OK
   (lenguaje plano del send-gate).

---

## 6. Roll-up de decisiones de gate por nicho (invariante §3.5)

| Nicho | money_touch | send | Por qué |
|---|---|---|---|
| finanzas | needs_ok | needs_ok | toca plata/cuentas; envío de reportes |
| educacion | off | off | cero consecuencia (resolver/graficar local) |
| research | off | off | solo lee/escribe archivos locales |
| programacion | off | needs_ok | push/PR sale del sandbox; ejecución local libre |
| cowork | off | needs_ok | Email/Slack/invite = envío; **precondición send-gate** |

> La receta DECLARA; **Security HACE CUMPLIR**. Poner un gate en `off` NO lo desactiva para
> tools clasificadas como money/send — el motor lo fuerza igual (§3.5, orden del founder).

## 7. Estado y huecos honestos
- **finanzas / educacion:** belts REALES con surface sondado (`finanzas.md`, `stem.md`).
  Las tool_filters salen de tools con `tools/list` ejecutado (cero-friccion) o sondado (fred/AV).
- **research / programacion / cowork:** las tools son MCPs **conectados en este entorno**
  (evidencia tabla FASE 0), pero el **belt-spec formal todavía no lo escribió Curation**
  — el `belt_ref` apunta al slug del nicho (portable, decisión B); el runtime lo resolverá
  cuando exista el `.mcp.json`. La receta es válida de FORMA hoy; el cableado depende de que
  Curation cierre esos 3 belts y AI/ML construya `script_runner` (prog) + Security el send-gate.
- **Gateado a persona usuaria (no cableado en estas recetas):** Google Sheets (cuenta GCP) y Stata
  (licencia) — quedan FUERA de `finanzas.config.json` v0 a propósito.
- **Validación:** `product/recipes/validate_recipes.py` chequea las 5 recetas contra el
  schema v1 (R1-R8 del contrato §3). Ver traza determinística en el reporte de cierre.
