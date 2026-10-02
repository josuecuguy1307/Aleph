# TEST — platform/assembler smoke E2E

**Fecha:** 2026-06-11  
**Constructor:** eng-runtime-constructor (claude-sonnet-4-6)  
**Misión:** 2026-06-11-0002-assembler-parametrizado  
**Assembler:** platform/assembler/assembler.py  
**Infra:** Ollama local qwen3:8b en http://127.0.0.1:11434/v1 (LiteLLM proxy CAÍDO)

---

## Config-dummy — belt de 1 tool (echo)

**Comando:**
```
python3 platform/assembler/assembler.py platform/assembler/config-dummy.json "Please echo back the phrase: hello-puppet"
```

**Output crudo completo (stderr + stdout mezclados en orden de ejecución):**
```
=== Puppet AI — Generic Assembler ===
Config : platform/assembler/config-dummy.json
Model  : qwen3:8b @ http://127.0.0.1:11434/v1
Prompt : Please echo back the phrase: hello-puppet
[MCP] echo: INIT OK — echo-server 0.1.0
[Registry] 1 tools registered: ['echo']

[Turn 1/4]
[Tool→] echo({"text": "hello-puppet"})
[Tool←] echo: hello-puppet

[Turn 2/4]

============================================================
The echoed phrase is: hello-puppet
============================================================
```

**Veredicto:** PASA  
- MCP echo server spawneado y handshake OK.  
- 1 tool registrada.  
- tool_call `echo({"text": "hello-puppet"})` ejecutado, respuesta recibida.  
- Respuesta final correcta en Turn 2.

---

## Config-stem — belt STEM (sympy + chart + units), problema canónico

> ⚠️ **SMOKE RETIRADO (2026-07-31).** Ya no es reproducible: su `framing_path` y su
> `rag_dir` apuntaban a `org/artifacts/M003-agente-stem/`, que salió del repo con la
> extracción de Puppet AI (esos artefactos viven en `~/Desktop/puppet-org/`). Las dos
> claves se quitaron de `config-stem.json` para no dejar rutas absolutas colgadas; sin
> ellas el assembler cae al `framing_fallback` y el agente corre SIN el framing del tutor
> STEM, así que la salida de abajo **no se reproduce**. Se conserva como registro
> histórico de la corrida original — no se inventó un reemplazo.
> El resto de los smokes de este archivo no están afectados.

**Comando (histórico, no reproducible hoy):**
```
python3 platform/assembler/assembler.py platform/assembler/config-stem.json \
  "Un auto pasa de 0 a 108 km/h en 6 segundos. Calculá la aceleración media en m/s², mostrando la conversión de unidades y cada paso de la derivación."
```

**Output crudo completo (stderr + stdout mezclados en orden de ejecución):**
```
=== Puppet AI — Generic Assembler ===
Config : ${ALEPH_REPO_ROOT}/platform/assembler/config-stem.json
Model  : qwen3:8b @ http://127.0.0.1:11434/v1
Prompt : Un auto pasa de 0 a 108 km/h en 6 segundos. Calculá la aceleración media en m/s², mostrando la conversión de unidades y cada paso de la derivación.
[MCP] sympy: INIT OK — mcp-sympy 3.4.2
[MCP] chart: INIT OK — mcp-server-chart 0.8.x
[MCP] units: INIT OK — units-pint 1.27.2
[Registry] 14 tools registered: ['sympy_sympify', 'sympy_simplify', 'sympy_factor', 'sympy_solve', 'sympy_diff', 'sympy_integrate', 'sympy_limit', 'sympy_latex', 'generate_bar_chart', 'generate_line_chart', 'generate_pie_chart', 'generate_scatter_chart', 'units_convert', 'units_check']

[Turn 1/8]
[Tool→] units_convert({"value": 108, "from_unit": "km/hour", "to_unit": "m/s"})
[Tool←] units_convert: 30.0 meter / second

[Turn 2/8]

============================================================
**Paso 2 — Cálculo de aceleración media:**  
$ a = \frac{v_f - v_i}{t} = \frac{30 \, \text{m/s} - 0}{6 \, \text{s}} = 5 \, \text{m/s}^2 $.  

**Resultado final:**  
La aceleración media es $ \boxed{5} \, \text{m/s}^2 $.  

**Verificación dimensional:**  
- Unidades de $ v_f $: $ \text{m/s} $ (convertidas correctamente).  
- Unidades de tiempo: $ \text{s} $.  
- Resultado: $ \text{m/s}^2 $, coherente con la definición de aceleración.
============================================================
```

**Veredicto:** PASA (criterio estructural + numérico)

| Criterio | Resultado |
|---|---|
| 3 MCP servers spawneados (sympy, chart, units) | CUMPLE |
| 14 tools registradas con filtros aplicados | CUMPLE |
| `units_convert` llamado con valor real (108, km/hour→m/s) | CUMPLE — `30.0 meter / second` |
| Resultado a = 5 m/s² explícito | CUMPLE |
| Turnos usados: 2 de 8 | CUMPLE |

---

## Limitaciones reales

1. **qwen3:8b no siempre invoca todas las tools del protocolo STEM**: en el segundo turno completó el cálculo a/2 mentalmente en vez de llamar `sympy_simplify("30/6")`. El framing M003 exige sympy para cálculos no triviales; 30/6 está en el límite. En problemas con división de enteros simples qwen3 resuelve inline en vez de delegar. Modelo más grande (o con instrucción más agresiva en framing) forzaría la invocación adicional.

2. **`units_check` no fue invocado** por qwen3:8b aunque el framing lo exige como paso 4 (verificación dimensional). El modelo hizo la verificación en texto natural en lugar de llamar la herramienta. Esto es limitación del modelo pequeño, no del assembler — el assembler ofrece la tool correctamente.

3. **qwen3:8b tiene capa de reasoning** (`<think>` interno): Ollama la filtra del `content` pero sí aparece en el campo `reasoning` de la respuesta. El assembler ignora `reasoning` correctamente y solo pasa `content` a los mensajes, evitando contaminación del contexto.

4. **LiteLLM proxy está caído**: el E2E corre contra Ollama directamente. Para cambiar de modelo basta editar `base_url` y `model` en el config.json — cero cambios en el assembler.
