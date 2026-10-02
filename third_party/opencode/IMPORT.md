# opencode — el MOTOR de Oficina

**Qué es.** El harness de agentes que OpenWork usa por debajo. No es una elección de
Aleph: es la dependencia que el propio OpenWork pinnea en su
`third_party/openwork/constants.json` (`{"opencodeVersion": "v1.17.11"}`) y que su script
de build baja de GitHub (`apps/desktop/scripts/prepare-sidecar.mjs:236`).

**Por qué entra.** Bajo la ley 2 el HARNESS se hereda entero y sólo se corta el enchufe al
modelo. Este binario ES el harness de OpenWork —su loop, sus tools, sus sesiones—; sin él
el cuerpo sirve la UI y la API pero no corre un turno. El enchufe al modelo se re-cablea
por la única costura que la casa impone (ley 12): el `PATCH /runtime-config/providers`
que `platform/workspaces/pack.py::enchufar_cerebro` manda apenas el motor contesta.

Decisión del dueño, 2026-08-10: entra como CUARTA pieza del vertical, con el mismo trato
que las manos (OfficeCLI v1.0.143, gws v0.22.5).

## Procedencia, pinneada y verificada

| Campo | Valor |
|---|---|
| Repo | `anomalyco/opencode` |
| Licencia | **MIT** (`LICENSE` en esta carpeta, tomado de `v1.17.11`; el repo no publica NOTICE — 404) |
| Tag | `v1.17.11` — el EXACTO de `openwork/constants.json`, no «el último» |
| Publicado | 2026-06-25T12:09:29Z |
| Asset | `opencode-darwin-arm64.zip` |
| SHA-256 del zip | `40723446013dea8252eea4f180d707f75e805af54ee85a14fd7c126513ba8342` |
| SHA-256 del binario | `996fea55451be04cfa27c0d9dbbf0468cb611cde43075fe3dac799772d0b710f` |
| Tamaño | 41.266.381 b comprimido · 129.461.090 b en disco |
| Ruta en el árbol | `third_party/opencode/bin/opencode-darwin-arm64` |

**El SHA se verificó CONTRA LA FUENTE, no sólo calculado.** La API de GitHub publica el
digest del asset y coincide byte a byte con el del archivo bajado:

```
digest publicado por GitHub : sha256:4072344601…ba8342
shasum -a 256 del descargado: 4072344601…ba8342
```

Esto salda el pendiente que el estudio de F6 había dejado anotado como «motor = binario de
anomalyco/opencode **sin verificar sha256**».

**Y se le preguntó al binario, no al TOC:** `./opencode-darwin-arm64 --version` → `1.17.11`.

## Las dos costuras que este binario necesita

1. **La descarga en build, neutralizada.** El paso que baja el binario de GitHub no corre:
   el build usa ESTE binario commiteado. Causa: local-first y reproducibilidad — un build
   que sale a la red no es reproducible y no es local. Asiento en
   `third_party/openwork/EXTIRPACIONES.md`.
2. **El auto-update, apagado por su propia costura.** El binario trae actualización viva:
   subcomando `opencode upgrade [target]` y la variable `OPENCODE_DISABLE_AUTOUPDATE`. El
   pack arranca el motor con `OPENCODE_DISABLE_AUTOUPDATE=1`, igual que las manos se
   arrancan con `OFFICECLI_SKIP_UPDATE=1`. Un motor que se actualiza solo deja de ser el
   que este `IMPORT.md` describe, y el SHA de arriba pasaría a mentir.

## Observado, no tocado

El binario declara además `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_DISABLE_LSP_DOWNLOAD`
y `OPENCODE_ALWAYS_NOTIFY_UPDATE`. OpenWork ya le pasa un `OPENCODE_MODELS_URL` propio
(`apps/server/src/cli.ts:64`). Queda anotado para la fase de red: el catálogo de modelos
del motor es una salida a un tercero que la ley 12 vuelve innecesaria —el modelo lo pone
Aleph—, pero apagarla sin medir qué se rompe sería adivinar.

## Deuda abierta (no de hoy)

Con este binario ya son **tres** los que viajan en git: `officecli` (32 MB), `gws` (15 MB)
y `opencode` (123 MiB). Eso pide una estrategia de artefactos post-gate —Git LFS o una
morada aparte con el mismo trato de SHA pinneado—. Anotado en el acta; no se resuelve en
esta fase.
