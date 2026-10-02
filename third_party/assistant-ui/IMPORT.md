# assistant-ui — origen de esta importación

**No editar nada de esta carpeta.** Todo lo que está debajo de `packages/` es código
ajeno, copiado tal cual. Este archivo es lo único nuestro que vive acá, y sólo declara
de dónde vino.

| campo | valor |
|---|---|
| Repo origen | https://github.com/assistant-ui/assistant-ui |
| Commit importado | `0ae51a8e8c4c49c4b8810b9c64845eeeded8b9bc` |
| Licencia | MIT (`LICENSE` en la raíz del repo de origen — copiado acá sin tocar) |
| Fecha de importación | 2026-08-08 |
| Modificaciones al código ajeno | **ninguna** |

---

## Qué se trajo, y por qué esta frontera

La ley de importación (`../README.md`) manda **traer entero** y **no cherry-pickear
fragmentos**. En un monorepo pnpm la unidad que se distribuye es el **paquete**, no el
repositorio: `npm install @assistant-ui/react` entrega exactamente el contenido de
`packages/react/` (su `files` incluye `src`). Por eso la frontera de esta importación
es la **carpeta de paquete completa**, con su árbol intacto y sus headers intactos.

Se trajeron los **9 paquetes de la clausura transitiva** de lo que Aleph usa —o sea,
`@assistant-ui/react` + `@assistant-ui/react-ag-ui` y todo lo que ellos importan dentro
del propio repo:

| paquete | rol |
|---|---|
| `packages/react` | primitivas del hilo y del composer (la superficie) |
| `packages/core` | runtime, tipos y adaptadores del hilo |
| `packages/store` | store del runtime |
| `packages/tap` | motor de recursos del que depende `core` |
| `packages/assistant-stream` | streaming y serialización de mensajes |
| `packages/react-ag-ui` | **el puente AG-UI → assistant-ui** (la costura que usa Aleph) |
| `packages/react-generative-ui` | dependencia de `react-ag-ui` |
| `packages/cloud` | dependencia de `react` (no se usa el servicio: no se configura) |
| `packages/safe-content-frame` | dependencia de `react` |

## Qué NO se trajo, y por qué

El resto del monorepo: `apps/`, `examples/`, `templates/`, `evals/`, `python/`,
`api-surface/`, `scripts/`, y los 38 paquetes restantes de `packages/` (integraciones con
LangGraph, Vercel AI SDK, Google ADK, Metro, React Native, Vue, etc.).

**Motivo, medido:** el repo entero pesa **63 MB de archivos trackeados**, de los cuales
~17 MB son GIFs y PNGs de marketing y documentación (`.github/assets/assistant-ui-starter.gif`
= 7,5 MB, `perplexity.gif` = 4,7 MB, `apps/docs/public/screenshot/` = varios MB). Nada de
eso es código, ninguno entra al producto, y en git pesan para siempre. La clausura que sí
se trajo pesa **7,4 MB**.

Esto **no es un cherry-pick**: no se eligió archivo por archivo. Se eligieron paquetes
enteros, que es la unidad que el propio repo publica. Cada carpeta bajo `packages/` está
completa —`src`, tests, `package.json`, `README`— tal como su autor la distribuye.

## Cómo se descarta

`rm -rf third_party/assistant-ui` + borrar su fila de `ATTRIBUTIONS.md`. Lo único de Aleph
que la referencia es `tools/sala-v2-build/` (que produce el bundle) y
`product/app/design/sala-v2/`. Ninguna línea de código nuestro vive adentro de esta carpeta.

## Cómo se sube de versión

Se re-copia la misma clausura desde un clon nuevo en el commit nuevo, se corre
`tools/sala-v2-build/build.mjs`, y se actualizan commit + fecha acá y en `ATTRIBUTIONS.md`.
Si la clausura cambió (un paquete nuevo aparece en las dependencias), el script del build
falla al no poder resolverlo — no se pierde en silencio.
