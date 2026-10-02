# NOTICE — lo que Aleph declara sobre esta pieza

El `NOTICE` del proyecto de origen vive intacto en la raíz de esta carpeta y no se toca
(`third_party/README.md` · Ley 3). Este archivo es **lo que Aleph agrega**: qué se le
cambió, y qué queda declarado como deuda de procedencia.

---

## 1 · Las skills: el campo `license:` era el de la librería, no el de la skill

Las 292 `SKILL.md` traían un campo `license:` en su front-matter. Leído literalmente,
decía que Aleph estaría distribuyendo seis skills GPL dentro de un producto cerrado — lo
que `third_party/README.md` prohíbe.

**Se midió, y no era eso.** Los seis directorios que declaraban GPL
(`biology/bioservices`, `biology/cobrapy`, `biology/etetoolkit`, `biology/pathml`,
`biology/scikit-survival`, `coding/denario`) contienen sólo `SKILL.md` + `references/` +
`scripts/` escritos por el proyecto de origen. Ejemplo verificado:
`backend/cli/skills/biology/bioservices/scripts/batch_id_converter.py` es código propio
que *usa* la librería, no código vendorizado de ella. **No hay contaminación copyleft.**

El campo describía **la librería aguas arriba que la skill envuelve**. Estaba mal
nombrado, y un nombre mal puesto en un campo de licencia es exactamente la clase de cosa
que después se lee mal en una auditoría. Por eso:

> **`license:` → `upstream-license:` en las 270 skills que lo declaraban.**

El código no lee ese campo (se verificó: cero referencias a `license` en
`backend/cli/src/skill/`), así que el renombre no cambia comportamiento. Las dos
apariciones restantes de `license:` en el árbol de skills están en el **cuerpo** de
`writing/hugging-face-paper-publisher/SKILL.md` — son YAML de ejemplo dentro de la
documentación, no front-matter, y quedaron intactas.

### Censo después del renombre

| `upstream-license:` | skills |
|---|---|
| MIT (contando la variante «MIT license») | 180 |
| **Unknown** | **39** |
| BSD-3-Clause | 15 |
| Apache-2.0 | 13 |
| GPL (3.0 ×3, 2.0 ×2, «GPLv3» ×1) | 6 |
| BSD-2-Clause | 2 |
| una URL en vez de una licencia (sympy, pydicom, polars, matplotlib) | 4 |
| condiciones de uso en prosa (KEGG no-comercial, HMDB, IDC, MATLAB/Octave, CeCILL, «Proprietary (API key required)», cc-by-4.0) | ~9 |
| **sin ningún campo** | **22** |
| **total de `SKILL.md`** | **292** |

## 2 · Deuda declarada: 61 skills sin procedencia clara

**22 sin campo + 39 con `Unknown` = 61 de 292.**

Las 22 sin campo son las de primera mano del proyecto de origen (`writing/*`,
`research/*`, `visualization/*`, y tres de `biology/`): quedan cubiertas por el
Apache-2.0 del repo, que es la licencia del `LICENSE` real y del `package.json`.

Las 39 con `Unknown` son las que hay que resolver una por una antes de que esta pieza
viaje dentro de un artefacto firmado. **Hoy no bloquean**: son texto y scripts propios del
proyecto de origen, distribuidos bajo su Apache-2.0; el `Unknown` describe la librería que
envuelven, no la skill.

**Cómo se salda:** o se completa el `upstream-license:` de cada una, o se borra el
directorio. No hay tercera opción — una skill que no puede decir qué envuelve es una
skill que no se puede auditar.

## 3 · Atribución de red: las consultas ya no salen a nombre de un tercero

La pieza importada se identificaba ante las fuentes científicas con el buzón y el dominio
del proyecto de origen, en tres lugares. Toda consulta a Crossref y OpenAlex quedaba
atribuida a `support@syntheticsciences.ai`, y Crossref **no tenía override** por entorno.

Ahora los tres leen un solo contacto, `CONTACTO_CIENCIA`
(`backend/cli/src/science/connectors/http.ts`), sobreescribible con `ALEPH_SCIENCE_MAILTO`.

No es cosmética: Crossref y OpenAlex dan **cola rápida** («polite pool») a quien se
identifica con un buzón real, y el resto de las fuentes lo usan para avisar si el cliente
se porta mal. Tiene que ser de quien opera la instalación.

## 4 · Lo que este árbol NO distribuye

`@synsci/atlas` entraba siempre como `optionalDependency` del paquete npm del proyecto de
origen (792 KB). Su repo es **privado** (`synthetic-sciences/thesis`). Se declara MIT,
pero una licencia sin fuente accesible no es un permiso que se pueda heredar con
confianza, ni un binario que se pueda auditar dentro de un `.app`. **No está en este
árbol**, y se extirpó tanto su resolvedor (`openscience/atlas-package.ts`) como el
ofrecimiento del asistente de primer arranque de instalarlo por `npm -g`.
