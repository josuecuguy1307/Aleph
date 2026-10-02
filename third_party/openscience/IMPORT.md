# OpenScience — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | https://github.com/synthetic-sciences/openscience |
| Commit importado | `edd585468549a0921be5b3b19cb6284d65d6b5d9` (v2.0.23) |
| Licencia | Apache-2.0 (`LICENSE` en la raíz del repo de origen — copiado acá sin tocar) |
| Titular | InkVell Inc. (Synthetic Sciences), Copyright 2026 |
| Fecha de importación | 2026-08-09 |
| Modificaciones al código ajeno | **sí** — un arreglo de defecto + la amputación de su cuenta/agente + la piel de Aleph. Todo listado en [`EXTIRPACIONES.md`](EXTIRPACIONES.md) |
| Estudio previo | `~/Desktop/FASE3N-CIENCIA-ESTUDIO.md` (licencias, censos de dominios y fuentes, auth, anatomía, costura al modelo) |

---

## Qué se trajo

**El árbol entero** (Ley 1). Los **4.415 archivos rastreados** por git en el commit de
origen, verificados **byte a byte**: sha256 archivo por archivo, cero diferencias contra
el clon de estudio antes de operar.

No viajaron los `node_modules` (919 MB de dependencias instaladas, reproducibles desde
`bun.lock`, e ignorados por el `.gitignore` de Aleph) ni el historial de git. El árbol
importado pesa **86 MB**.

## Por qué esta pieza

De las tres costuras de Aleph —cerebro · compatibilidad · extras—, **sólo el cerebro se le
impone al stack** (Ley 0). Lo que se hereda de OpenScience es su dominio, no su
inferencia:

| Qué | Dónde | Por qué importa |
|---|---|---|
| **43 conectores científicos** | `backend/cli/src/science/connectors/` | UniProt · RCSB PDB · AlphaFold · Ensembl · NCBI · ChEMBL · PubChem · arXiv · OpenAlex · Crossref y 33 más. APIs públicas, sin llaves salvo dos opcionales, con política de red disciplinada (timeout, backoff en 429/5xx, caché TTL, throttle por host) |
| **294 skills** | `backend/cli/skills/` | 23 MB, 1.193 `.md` + 280 `.py`, en 17 familias (ml-training 52, biology 43, databases 32, …) |
| **Procedencia** | `backend/cli/src/science/provenance/` | `envelope.ts` · `review.ts` · `store.ts` — conversa directo con el contrato de artefactos de Gate 4 · Fase 2 |
| **Kernel científico** | `backend/cli/src/science/kernel/` + tools `notebook` / `rkernel` | celdas de Python con entorno propio, medido funcionando en el estudio |
| **15 agentes** | `backend/cli/src/agent/` | `research` (default), `biology`, `physics`, `ml` + 11 subagentes |
| **La costura de proveedores** | `backend/cli/src/config/config.ts:1071-1074` + `provider/provider.ts` | apuntar el stack al cerebro de Aleph es **pura config, cero corte de código** — probado con el lazo modelo→tool→modelo cerrado |

## La costura al cerebro de Aleph

Un archivo `openscience.json` en el proyecto. Sin tocar una línea de TypeScript:

```json
{
  "provider": {
    "aleph": {
      "name": "Aleph (cerebro propio)",
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:4000/v1", "apiKey": "…" },
      "models": { "brain": {}, "constructor-code": {} }
    }
  }
}
```

`baseURL` apunta a la puerta LiteLLM de Aleph (`infra/delegate.py:14`); los alias salen de
`infra/litellm.config.yaml`. Si la puerta rota credenciales, `config.ts:1077`
(`options.tokenCommand`) ya lo resuelve sin código.

## Deuda declarada (no bloquea, pero se anota)

1. **El binario del proyecto de origen está firmado adhoc, sin Team ID y sin notarizar.**
   Si el sidecar se arma desde este árbol, hay que re-firmarlo con el Dev ID de Aleph y
   notarizarlo con el bundle. El atajo del certificado autofirmado ya se midió en
   Gate 2 · F5 y falla con `-25293`.
2. **61 de las 294 skills no declaran procedencia clara** (22 sin campo, 39 con
   `Unknown`). El campo se renombró a `upstream-license:` porque describe la librería que
   la skill envuelve, no la skill. Ver [`NOTICE-ALEPH.md`](NOTICE-ALEPH.md).
3. **Quedan ramas muertas `providerID === "synsci"`** en `provider/transform.ts`,
   `provider/inference.ts`, `cli/cmd/models.ts` y `acp/agent.ts`. Son inertes (sin
   superficie Atlas ese proveedor no puede materializarse) y sacarlas es refactor, que la
   importación no hace (Ley 5). Se limpian en la fase de cableado.
4. **La fila en `../../ATTRIBUTIONS.md` está pendiente.** Ver [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)
   en esta carpeta: trae la fila lista para pegar. Hoy no se tocó ningún archivo existente
   del repo porque la cosecha de Gate 4 · Fase 3 corre en paralelo sobre el mismo árbol.
