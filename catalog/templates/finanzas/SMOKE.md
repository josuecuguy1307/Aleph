# SMOKE ESTRUCTURAL — Templates Finanzas

**Ejecutado:** 2026-06-11  
**Script:** `catalog/templates/finanzas/smoke_test.py` (stdlib Python, sin dependencias, sin LLM)  
**Qué valida:** parse JSON correcto de cada config.json + belt_path resuelve a archivo existente con `mcpServers` válido + campos requeridos presentes + framing_fallback no vacío + tool_filters referencia servers del belt

---

## Output crudo del script

```
============================================================
SMOKE TEST ESTRUCTURAL — Templates Finanzas
Base: ${ALEPH_REPO_ROOT}/catalog/templates/finanzas
Belt compartido: ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/belt-finanzas.mcp.json
============================================================

Belt compartido OK — servers: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']

[OK ] t01-cierre-mensual
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t01-cierre-mensual/framing.md
[OK ] t02-regresion-panel-stata
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t02-regresion-panel-stata/framing.md
[OK ] t03-tabla-comparables
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t03-tabla-comparables/framing.md
[OK ] t04-brief-macro-fred
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t04-brief-macro-fred/framing.md
[OK ] t05-varianza-fp-a
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t05-varianza-fp-a/framing.md
[OK ] t06-monitor-mercado
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t06-monitor-mercado/framing.md
[OK ] t07-screener-fundamentals
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t07-screener-fundamentals/framing.md
[OK ] t08-notebook-backtesting
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t08-notebook-backtesting/framing.md
[OK ] t09-resumen-filing-edgar
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t09-resumen-filing-edgar/framing.md
[OK ] t10-dashboard-macro
       belt_servers referenciados: ['excel', 'sheets', 'stata', 'alphavantage', 'secedgar', 'fred', 'jupyter']
       WARN : framing_path no existe (se usará framing_fallback): ${ALEPH_REPO_ROOT}/catalog/templates/finanzas/t10-dashboard-macro/framing.md

============================================================
RESULTADO: 10/10 templates OK, 0 FAIL
SMOKE: PASS — todos los configs parsean y sus belt_paths resuelven
============================================================
```

---

## Interpretación de los WARN

Los 10 warnings de `framing_path no existe` son **esperados y no son errores**. Los archivos `framing.md` por template son el framing completo (largo, específico de dominio) que Tool-belt Engineering escribe al momento del deploy con el agente real. El `framing_fallback` en cada `config.json` cubre el caso para el assembler ahora mismo y es suficiente para el smoke estructural.

El assembler (`platform/assembler/assembler.py`, función `_load_framing`) usa `framing_fallback` cuando `framing_path` no existe o está en null — comportamiento confirmado en el código fuente.

---

## Resultado

**SMOKE: PASS — 10/10 configs parsean como JSON válido y sus belt_paths resuelven a archivos existentes con mcpServers válido.**
