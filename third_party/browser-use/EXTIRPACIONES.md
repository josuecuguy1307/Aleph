# browser-use — extirpaciones (ley 2.bis · inmersión 3.8)

**Estado: DECLARADAS, NO EJECUTADAS.** Este archivo es el censo de lo que hay que sacar,
medido en el árbol importado. Ninguna se aplicó todavía: el árbol está **byte-idéntico** al
commit `898f23f0…` y su `MANIFEST.sha256` lo prueba.

## 1 · Telemetría — `posthog==7.7.0`

Declarada en `pyproject.toml` como dependencia **directa**. Mismo caso que OpenWork, donde
la caminata encontró «PostHog prendido por defecto con la key horneada»
(`FASE6-OFICINA-ESTUDIO.md:25`). Sale entera.

## 2 · La nube del proyecto — `browser-use-sdk==3.4.2`

SDK del servicio comercial. El README recomienda Browser Use Cloud para producción; la
LEY 0 dice que el stack vale solo, y la 2.bis que la infra del proyecto ajeno se extirpa.
También `browser_use/agent/cloud_events.py`.

## 3 · La capa de identidad y marca (inmersión 3.8)

Cero marca ajena en el camino del usuario. El nombre del proyecto no aparece en pantalla; el
crédito legal vive en `ATTRIBUTIONS.md`, que es donde corresponde y donde sí es exigible.

## 4 · El enchufe al modelo (LEY 2 · LEY 12) — **no es extirpación, es cirugía**

No se borra: se **re-apunta**. `browser_use/llm/openai/chat.py` — `api_key:38`, `base_url:41`,
`_get_client_params():48-67`, y **exactamente 2 sitios que llaman a la red** (`:167-171` y
`:215-220`). El destino es el borde de dialecto de la casa,
`/v1/workspaces/brain/openai/chat/completions`. El patrón escrito está en
`platform/sala/busqueda/config.py` — se lee ése antes de escribir otro.

Los otros 12 directorios de `browser_use/llm/` (anthropic, google, groq, ollama, litellm,
openrouter, azure, aws, deepseek, mistral, cerebras, vercel, browser_use) **quedan**: son
harness, y la LEY 2 sólo corta el enchufe. Lo que hace que no se usen es la config, no el
borrado.

## 5 · Lo que NO se toca

El `SecurityWatchdog` se **conserva entero** y se usa como segunda cerca
(`allowed_domains`), nunca como la primera: está medido que no resuelve DNS y que es
fail-open por defecto. La primera cerca es `platform/browser/loopback.py`, de la casa.
Ver `platform/browser/REGLA-LOOPBACK.md` §R4.
