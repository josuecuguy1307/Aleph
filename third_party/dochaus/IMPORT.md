# doc.haus — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | `https://github.com/sure-scale/doc-haus.git` |
| Commit importado | `f3cdfd15f7b675e651773b3f6a8ef9468f56ed14` |
| Licencia de código | MIT (`LICENSE`, conservada en la raíz) |
| Fecha de importación | 2026-08-09 |
| Estudio previo | `~/Desktop/FASE6-LEGAL-ESTUDIO.md` |
| Árbol testigo | `~/Desktop/oss-estudio/dochaus` (clon limpio, mismo commit) |

## Integridad antes de cirugía

Se copió el árbol completo salvo `.git`, `node_modules` y `.DS_Store`. Antes de toda
cirugía, los **5.761 archivos regulares** importados dieron este manifiesto SHA-256:

```
75d0ff660420705a086569b6dc8b565685a1d9c9c26a2f33bebbbb8fcae0732b
```

El origen tiene 5.822 entradas rastreadas: la diferencia incluye entradas que no son
archivos regulares del árbol materializable (por ejemplo `packages/console/app/public/email`).
El clon testigo queda intacto fuera de Aleph; este directorio conserva la licencia y el
origen para que cada extirpación sea revisable en `EXTIRPACIONES.md`.

## Reproducibilidad de runtime

El lock raíz traía `ghostty-web` desde la rama móvil `main`: bajo el Bun requerido
`1.3.14`, `bun install --frozen-lockfile` rechazaba el árbol porque la resolución guardada
`20bd361` ya no era la que el manifiesto mutable resolvía. El 2026-08-09 se regeneró
**sólo esa entrada** con Bun 1.3.14 a `83c0a07` (y su integridad), y la misma orden
congelada volvió a instalar **4.541 paquetes**. Es una deuda de procedencia explícita del
upstream: el hash queda congelado ahora, pero `packages/app/package.json` aún declara
`github:anomalyco/ghostty-web#main`; una actualización futura debe auditar esa fuente antes
de mover el lock.

El build de Aleph materializa ese lock y embebe el árbol resultante, el launcher y Bun en
la `.app` mediante O1; ninguna instalación distribuida puede depender de un Bun externo.

## Alcance heredado

Se importa el motor OpenCode, la capa legal `dochaus/`, el ingest de matters/redlines y
la web. La inferencia, proveedores, puertos y ciclo de vida **no** se heredan: se sustituyen
por el Cerebro y el pack de Aleph. El contenido jurídico tiene inventario separado en
[`ATTRIBUTIONS`](ATTRIBUTIONS).
