# AG-UI — origen de esta importación

**No editar nada de esta carpeta.** Todo lo que está debajo de `sdks/` es código ajeno,
copiado tal cual. Este archivo es lo único nuestro que vive acá, y sólo declara de dónde vino.

| campo | valor |
|---|---|
| Repo origen | https://github.com/ag-ui-protocol/ag-ui |
| Commit importado | `68b99d8bb8910cc624964818000f6b71cce4d66f` |
| Licencia | MIT (`LICENSE` en la raíz del repo de origen — copiado acá sin tocar) |
| Fecha de importación | 2026-08-08 |
| Modificaciones al código ajeno | **ninguna** |

---

## Qué se trajo, y por qué esta frontera

Misma frontera que `../assistant-ui/IMPORT.md`: la unidad importada es el **paquete
completo**, que es lo que el repo publica a npm. Se trajeron los **4 paquetes del SDK de
TypeScript** que forman la clausura transitiva de lo que Aleph usa:

| paquete | rol |
|---|---|
| `sdks/typescript/packages/core` | **el protocolo**: `EventType` y los schemas Zod de cada evento |
| `sdks/typescript/packages/client` | `AbstractAgent` — la costura que Aleph implementa |
| `sdks/typescript/packages/encoder` | dependencia de `client` |
| `sdks/typescript/packages/proto` | dependencia de `encoder` |

**`AbstractAgent` es el punto de extensión declarado por el propio repo**
(`packages/client/src/agent/agent.ts:140`, `abstract run(input): Observable<BaseEvent>`).
El adaptador de Aleph lo implementa desde afuera: no se abre el cuerpo de ninguna clase
ajena. Es exactamente la cirugía que la ley 6 permite —tocar por la costura que el repo
dejó— y de hecho ni siquiera hace falta tocar: alcanza con heredar.

## Qué NO se trajo, y por qué

`sdks/python`, `sdks/dotnet`, `sdks/community` (c++, go, dart, rust, java, kotlin, ruby),
`integrations/` (23 frameworks), `middlewares/`, `apps/`, `docs/`.

**Motivo, medido:** el repo entero pesa **54 MB de archivos trackeados**, con
`docs/videos/Dojo-overview.mp4` (3,1 MB), `apps/dojo/src/files.json` (3,9 MB) e imágenes de
documentación arriba. Los SDKs de otros lenguajes no los usa nadie en Aleph: el adaptador
es TypeScript porque corre en la pantalla. La clausura que sí se trajo pesa **1,5 MB**.

**Nota sobre el SDK de Python:** se evaluó y se dejó afuera a propósito. El adaptador vive
en el borde de la pantalla, no en el backend —ver la tabla de mapeo en
`product/app/design/sala-v2/agui/aleph-agent.js`— justamente porque la ley de esta fase es
**no tocar el backend de Gate 1-3**. Si una fase futura mueve la traducción al servidor,
`sdks/python` se importa entonces, con su propia fila.

## Cómo se descarta

`rm -rf third_party/ag-ui` + borrar su fila de `ATTRIBUTIONS.md`.

## Cómo se sube de versión

Igual que assistant-ui: re-copiar la clausura desde un clon nuevo, correr
`tools/sala-v2-build/build.mjs`, actualizar commit y fecha acá y en `ATTRIBUTIONS.md`.
