# ATTRIBUTIONS — OpenScience

> **DEUDA SALDADA (etapa 2, obra 1).** La fila de esta pieza ya está escrita en
> `../../ATTRIBUTIONS.md`, junto con la frontera de su importación, el censo de licencias de
> su árbol de dependencias, y las 43 fuentes científicas en la tabla de «piezas usadas sin
> importar». La pieza está **importada y registrada**.
>
> *(Durante la etapa 1 la fila quedó pendiente: la cosecha de Gate 4 · Fase 3 corría en otra
> terminal sobre el mismo repo y la orden era no tocar ningún archivo existente. Se escribió
> apenas la cosecha mergeó, que es lo que la Ley 4 pedía en cuanto fuera posible hacerlo sin
> pisarle el árbol a otra sesión.)*

---

## Origen

| campo | valor |
|---|---|
| Pieza | `openscience` |
| Repo origen | https://github.com/synthetic-sciences/openscience |
| Commit | `edd585468549a0921be5b3b19cb6284d65d6b5d9` (v2.0.23) |
| Licencia | **Apache-2.0** — archivo `LICENSE` real en la raíz del repo de origen, copiado acá sin tocar |
| Titular del copyright | **InkVell Inc. (Synthetic Sciences)**, Copyright 2026 |
| Paquete npm de origen | `@synsci/openscience` |
| Fecha de importación | 2026-08-09 |
| Archivos | 4.415 rastreados, 86 MB, verificados byte a byte (sha256 archivo por archivo) |

El `NOTICE` del proyecto de origen viaja intacto en la raíz de esta carpeta, como manda la
Ley 3. Declara un solo bundle de terceros (**markitdown**, MIT, de Microsoft, bajo
`backend/cli/skills/data-engineering/markitdown`) y aclara que los conectores científicos
consultan APIs públicas sin redistribuir su dato — cada fuente se rige por sus propios
términos, y quien los consulta es responsable de cumplirlos.

## Licencias del árbol de dependencias

Censo del árbol JS instalado desde `bun.lock` (762 paquetes únicos), medido en el estudio:

| Licencia | Paquetes |
|---|---|
| MIT | 610 |
| Apache-2.0 | 68 |
| ISC | 29 |
| BSD-3-Clause | 21 |
| BSD-2-Clause | 12 |
| BlueOak-1.0.0 | 9 |
| MPL-2.0 (o dual con Apache-2.0) | 3 |
| otras permisivas (MIT-0, 0BSD, CC0, OFL-1.1, Python-2.0, CC-BY-4.0, AFL-2.1) | 8 |
| sin campo declarado (MIT aguas arriba) | 2 |

**Cero GPL. Cero AGPL. Cero SSPL. Cero BUSL. Cero Elastic.** Cumple la condición que
`third_party/README.md` le pone a todo lo que viaja dentro del producto.

Los tres que merecen nota, y por qué ninguno molesta:

- `lightningcss` + su binario de plataforma — **MPL-2.0**, copyleft por archivo, y sólo es
  herramienta de build (Tailwind/Vite). No viaja modificada ni dentro del artefacto.
- `dompurify` — `(MPL-2.0 OR Apache-2.0)`: se elige Apache-2.0.
- `@fontsource-variable/inter` — **OFL-1.1**: redistribuible; lo único prohibido es vender
  la fuente sola.

## Piezas de terceros que este árbol NO trae

| Pieza | Por qué no está |
|---|---|
| `@synsci/atlas` | `optionalDependency` del paquete npm de origen (792 KB, se instalaba siempre). Su repo es **privado** (`synthetic-sciences/thesis`): no es auditable ni reconstruible desde lo público. Se declara MIT, pero una licencia sin fuente accesible no es permiso que se pueda heredar con confianza. Se extirpó su resolvedor y el ofrecimiento de instalarlo. |
| `node_modules` | 919 MB de dependencias instaladas, reproducibles desde `bun.lock`, ignoradas por el `.gitignore` de Aleph. |

## Lo que Aleph le cambió

Todo listado, línea por línea, en [`EXTIRPACIONES.md`](EXTIRPACIONES.md). En resumen: un
arreglo de defecto (`compute_job`), la amputación de la cuenta y el agente del proyecto de
origen (Ley 6), y la piel de Aleph (Ley 3).
