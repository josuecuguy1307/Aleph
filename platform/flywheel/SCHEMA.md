# Flywheel Schema v0

> Data flywheel — qué configuración funcionó por agente creado.
> Formato: JSONL append-only (`agents.jsonl`). Una línea = un agente registrado.

---

## Campos

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `id` | string | SI | Identificador único del registro (UUID v4) |
| `mission` | string | SI | ID de la misión que originó el agente (ej. "M003") |
| `nicho` | string | SI | Nicho del agente (ej. "tutor-stem-es", "finanzas-personal") |
| `agent_name` | string | SI | Nombre del agente (ej. "Tutor STEM-ES") |
| `model_primary` | string | SI | Modelo principal usado (alias LiteLLM o ID directo) |
| `model_fallback` | string | NO | Modelo de fallback si existe |
| `belt_version` | string | SI | Versión del cinturón MCP (semver, ej. "1.0.0") |
| `belt_tools` | list[string] | SI | Lista de tools expuestas al modelo (nombres exactos) |
| `temperature` | number | SI | Temperature usada en el runtime |
| `max_tokens` | integer | SI | max_tokens configurado |
| `max_turns` | integer | SI | Máximo de turnos del bucle tool-use |
| `rag_enabled` | boolean | SI | Si el agente tiene RAG activo |
| `rag_mode` | string | NO | Modo RAG (ej. "manual", "auto") — requerido si rag_enabled=true |
| `eval_score` | number | NO | Score de eval (0.0–1.0) cuando exista resultado de Agent Eval |
| `eval_notes` | string | NO | Notas del evaluador cuando exista |
| `user_feedback` | string | NO | Feedback del usuario cuando exista (texto libre) |
| `user_feedback_score` | integer | NO | Score 1–5 del usuario cuando exista |
| `created_at` | string (ISO 8601) | SI | Timestamp de creación del registro |
| `updated_at` | string (ISO 8601) | SI | Timestamp de última actualización |

---

## Tipos válidos para `nicho`

Sin restricción de valores — string libre, kebab-case recomendado.
Ejemplos: `"tutor-stem-es"`, `"finanzas-personal"`, `"ingenieria-mecanica"`.

---

## Reglas del schema

1. Los campos marcados `SI` son obligatorios — `capture.py` rechaza la entrada si falta alguno.
2. `belt_tools` debe ser una lista no vacía de strings.
3. `temperature` debe ser un número en `[0.0, 2.0]`.
4. `max_tokens` y `max_turns` deben ser enteros positivos.
5. `eval_score` si presente debe ser un número en `[0.0, 1.0]`.
6. `user_feedback_score` si presente debe ser un entero en `[1, 5]`.
7. `rag_mode` es requerido cuando `rag_enabled` es `true`.
8. Los timestamps deben estar en formato ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ` o con offset).

---

## Ejemplo de entrada válida

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "mission": "M003",
  "nicho": "tutor-stem-es",
  "agent_name": "Tutor STEM-ES",
  "model_primary": "constructor-code",
  "model_fallback": "premium",
  "belt_version": "1.0.0",
  "belt_tools": ["sympy_diff", "sympy_integrate", "sympy_solve"],
  "temperature": 0,
  "max_tokens": 2048,
  "max_turns": 8,
  "rag_enabled": true,
  "rag_mode": "manual",
  "created_at": "2026-06-11T00:00:00Z",
  "updated_at": "2026-06-11T00:00:00Z"
}
```

---

## Archivos

| Archivo | Propósito |
|---|---|
| `agents.jsonl` | Registro append-only; una entrada JSON por línea |
| `SCHEMA.md` | Este documento — define y documenta el schema |
| `capture.py` | Helper CLI para appendear entradas validadas |
| `TEST.md` | Evidencia de test de rechazo de entrada inválida |

---

> v0 — 2026-06-11 — Squad Database, Puppet AI Engineering
