# Flywheel Schema v0 — Test de rechazo de entrada inválida

> Ejecutado: 2026-06-11 — Squad Database, Puppet AI Engineering

---

## Comando

```bash
python platform/flywheel/capture.py \
  --json '{"id":"test-bad","mission":"M003","nicho":"tutor-stem-es","agent_name":"Test Agent","model_primary":"gpt-4","belt_version":"1.0.0","belt_tools":[],"temperature":5.0,"max_tokens":-10,"max_turns":0,"rag_enabled":true,"created_at":"bad-ts","updated_at":"bad-ts"}' \
  --out platform/flywheel/agents.jsonl
```

## Output crudo (stderr + exit code)

```
ERROR: Entrada inválida:
  • 'belt_tools' debe ser una lista no vacía de strings
  • 'temperature' debe ser un número en [0.0, 2.0]
  • 'max_tokens' debe ser un entero positivo
  • 'max_turns' debe ser un entero positivo
  • 'rag_mode' es requerido cuando 'rag_enabled' es true (ej. 'manual', 'auto')
  • 'created_at' no parece ISO 8601 válido (esperado: YYYY-MM-DDTHH:MM:SSZ)
  • 'updated_at' no parece ISO 8601 válido (esperado: YYYY-MM-DDTHH:MM:SSZ)
EXIT: 1
```

## Violaciones inyectadas y detectadas

| Violación inyectada | Error reportado |
|---|---|
| `belt_tools: []` (lista vacía) | `'belt_tools' debe ser una lista no vacía de strings` |
| `temperature: 5.0` (fuera de [0,2]) | `'temperature' debe ser un número en [0.0, 2.0]` |
| `max_tokens: -10` (negativo) | `'max_tokens' debe ser un entero positivo` |
| `max_turns: 0` (cero) | `'max_turns' debe ser un entero positivo` |
| `rag_enabled: true` sin `rag_mode` | `'rag_mode' es requerido cuando 'rag_enabled' es true` |
| `created_at: "bad-ts"` | `'created_at' no parece ISO 8601 válido` |
| `updated_at: "bad-ts"` | `'updated_at' no parece ISO 8601 válido` |

Resultado: **7 errores detectados, entrada rechazada, JSONL no modificado, exit code 1.**

---

## Test de campo requerido faltante

```bash
python platform/flywheel/capture.py \
  --json '{"mission":"M003","nicho":"tutor-stem-es",...}' \
  --out platform/flywheel/agents.jsonl
```

Output:
```
ERROR: Entrada inválida:
  • campo requerido faltante: 'id'
EXIT: 1
```

---

## Estado del JSONL después de los tests

El archivo `agents.jsonl` contiene exactamente 1 línea (la entrada válida de M003).
Las entradas inválidas no fueron escritas.
