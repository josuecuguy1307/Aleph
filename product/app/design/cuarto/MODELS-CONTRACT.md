# Contrato `/v1/models` — picker de modelo (Stream A ⇄ Stream C)

> El picker de modelo del agente es del frontend; **la disponibilidad la manda el backend**.
> Hoy `:8080` NO expone `/v1/models` → el frontend cae a la lista CURADA (los aliases reales
> de `platform/assembler/models.py`). Cuando Stream C agregue el endpoint, el front lo consume
> sin tocar nada (mismo patrón que `requirements`).

## Lo que pido a Stream C

`GET /v1/models` → la lista de modelos REALMENTE disponibles, con honestidad de disponibilidad
(Opus-vía-shim anda; los de Groq/Gemini requieren key/crédito; el local necesita ollama):

```jsonc
{
  "models": [
    {
      "id": "opus",                       // estable, lo usa el front para seleccionar
      "alias": "brain",                   // alias de models.py
      "label": "Opus 4.8",
      "tier": "Cerebro premium",
      "model": "claude-code-opus-4.8",    // id que el endpoint espera
      "base_url": "http://127.0.0.1:8923/v1",
      "available": true,                  // ← la VERDAD del backend (key presente / shim vivo / ollama up)
      "availability": "anda (shim dev)",  // texto honesto para el chip
      "need": "dev"                       // dev | local | key:GROQ | key:GEMINI (por si available falta)
    }
  ]
}
```

`compileModel(id)` del front arma la forma PLANA que el validador exige
(`primary/base_url/temperature/max_tokens/max_turns` + `alias`). Idealmente el backend
resuelve por `alias` (portable); hoy el validador exige los campos planos, así que los mando.

## Mientras tanto (curado, honesto)

Lista en `cuarto.models.js::CURATED` (alias reales de models.py):
`opus`(brain·shim/OpenRouter) · `oss`(gpt-oss-120b·Groq) · `llama70`(premium·Groq) ·
`qwen32`(explorer-reason·Groq) · `qwen-local`(oss-direct·ollama $0) · `gemini`(vision·Gemini).
DeepSeek NO está en `models.py` → no se muestra (no se miente disponibilidad).

Disponibilidad mostrada honesta: `dev`→"anda (shim dev)" · `local`→"local · $0 (ollama)" ·
`key:X`→"requiere X key" · desconocida→"se confirma al correr". El modelo **activo real** se
confirma post-run (`record.model_final` + `record.degraded`, ya emitidos por Stream C/C6).
