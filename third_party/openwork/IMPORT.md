# OpenWork — importación de Oficina, etapa 1

## Origen y frontera

- **Repo:** `https://github.com/different-ai/openwork`
- **Commit importado:** `fc8b43b530b468026760c5da4e13dbb9c2fd78a0`
- **Fecha:** 2026-08-09
- **Licencia heredada:** MIT para este árbol importado, conforme a `LICENSE` del
  origen: todo contenido fuera de `/ee` es MIT. `LICENSE` se preserva aquí.
- **Unidad importada:** únicamente las rutas git-rastreadas `apps/` y `packages/`.
  No viajan historial, `node_modules`, artefactos generados ni ninguna otra ruta de raíz.
- **Exclusión de licencia:** `/ee` no se extrajo ni se usó como fuente de código. Es
  FSL-1.1-MIT y queda fuera por completo.

## Raíz de build de Aleph

El upstream coordinaba el monorepo desde una raíz que también enumera `ee/*`.
Esa raíz no se importó. Aleph aporta exclusivamente `package.json` y
`pnpm-workspace.yaml` en esta carpeta: abarcan sólo `apps/*` y `packages/*`,
mantienen el catálogo React que estas piezas requieren y permiten producir un
lockfile reproducible sin resolver ni incluir `/ee`. Son infraestructura de
integración de Aleph, no una modificación del árbol importado MIT.

El servidor y el empaquetador de escritorio leen además `constants.json` desde
esa raíz. Aleph aporta su único dato requerido (`opencodeVersion: v1.17.11`),
medido contra el archivo MIT del testigo; no enumera `/ee` ni incorpora código
FSL.

## Testigo antes de cirugía

La extracción se hizo con `git archive` sobre las dos rutas anteriores. El digest es
SHA-256 del manifiesto ordenado `sha256(contenido) + ruta relativa` de los 1.470
archivos git-rastreados, antes de toda modificación local.

```text
apps tree (git):     4011975f1c3ae0eef2793af9f57984744b63607c
packages tree (git): c8f187c3d9d8ab2a097ab72b52bb134f77a55ef4
contenido SHA-256:   4e1ad14a0bc5a459a749617cf2e9e3c68cd377c20a9c9167903a36c8dfff7aa8
archivos:            1470
```

La verificación inicial dio `ee_paths=0` y `FSL_hits=0` dentro de `apps/` y
`packages/`. Las extirpaciones posteriores se documentarán corte por corte en
`EXTIRPACIONES.md`; este archivo conserva la frontera y el testigo del clon intacto.
