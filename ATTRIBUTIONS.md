# ATTRIBUTIONS — piezas de terceros dentro de Aleph

Registro de todo el código ajeno importado a `third_party/`. La ley que gobierna qué
puede entrar y cómo está en [`third_party/README.md`](third_party/README.md).

**Regla:** ninguna pieza vive en `third_party/` sin su fila acá. Pieza sin fila = pieza
que no entró. La fila se escribe **en el mismo commit** que trae la pieza.

**Cómo se llena cada columna:**

- **Pieza** — el nombre de la carpeta bajo `third_party/`.
- **Repo origen** — URL completa del repo del que se clonó.
- **Commit** — el sha1 exacto importado (completo, no abreviado).
- **Licencia** — la del archivo `LICENSE` real del repo de origen, no la del README ni
  la del badge.
- **Fecha de importación** — `AAAA-MM-DD`.
- **Modificaciones** — qué se le tocó respecto del original. `ninguna` si entró intacta.
  Las únicas cirugías permitidas son amputar su agente y teñir la piel (Ley 6).

---

| Pieza | Repo origen | Commit | Licencia | Fecha de importación | Modificaciones |
|---|---|---|---|---|---|
| **assistant-ui** | https://github.com/assistant-ui/assistant-ui | `0ae51a8e8c4c49c4b8810b9c64845eeeded8b9bc` | MIT | 2026-08-08 | **ninguna** — ver `third_party/assistant-ui/IMPORT.md` |
| **AG-UI** | https://github.com/ag-ui-protocol/ag-ui | `68b99d8bb8910cc624964818000f6b71cce4d66f` | MIT | 2026-08-08 | **ninguna** — ver `third_party/ag-ui/IMPORT.md` |
| **OpenScience** | https://github.com/synthetic-sciences/openscience | `edd585468549a0921be5b3b19cb6284d65d6b5d9` | Apache-2.0 (InkVell Inc. / Synthetic Sciences, 2026) | 2026-08-09 | **sí** — arreglo del esquema de `compute_job`, amputación de su cuenta y su agente (Ley 6), y la piel de Aleph (Ley 3). Corte por corte en `third_party/openscience/EXTIRPACIONES.md`; origen y frontera en `third_party/openscience/IMPORT.md` |
| **doc.haus** | https://github.com/sure-scale/doc-haus.git | `f3cdfd15f7b675e651773b3f6a8ef9468f56ed14` | MIT | 2026-08-09 | **sí** — extirpación de Vertex/BYOK, dos MCPs, probes cloud y puertos fijos; costura al Cerebro de Aleph, pack de tres procesos y piel Legal. Corte por corte en `third_party/dochaus/EXTIRPACIONES.md`; frontera de contenido y CC BY 4.0 en `third_party/dochaus/ATTRIBUTIONS`. |
| **Open CoDesign** | https://github.com/OpenCoworkAI/open-codesign | `b94d7156bf4aeb2c79892c91dc9934911a4e3741` | MIT (OpenCoworkAI Contributors, 2026) | 2026-08-09 | **sí** — OAuth ChatGPT/Codex y updater/release ajenos fuera del arranque; piel visible Aleph y 25 referencias de marca sin licencia individual extirpadas. Frontera SHA-256 y delta: `third_party/codesign/IMPORT.md`, `third_party/codesign/EXTIRPACIONES.md`. |
| **DeepTutor** | https://github.com/HKUDS/DeepTutor | `456f9c24226e008f1ff07a7e3455d7b4d39f6221` | Apache-2.0 (HKUDS) | 2026-08-09 | **sí** — se extirparon Partners, OAuth Codex, CLI-Anything, multiusuario/PocketBase, CORS permisivo y PyMuPDF (AGPL/comercial); queda sólo el binding OpenAI-compatible `custom` y piel Aleph Educación. Ver `third_party/deeptutor/IMPORT.md`, `EXTIRPACIONES.md` y `FASE6-EDUCACION.md`. |
| **Vibe-Trading** | https://github.com/HKUDS/Vibe-Trading | `281c87755f7a619ef41fa8804439909c6926034a` | MIT (Vibe-Trading Contributors, 2026 · `NOTICE` de HKUDS) | 2026-08-09 | **sí** — amputación de superficies de producto ajenas (16 adaptadores de mensajería, el marketplace QVeris con su referido embebido, el puente a OpenBB Workspace, el comando `update`) y la piel de Aleph (Ley 3/6). Corte por corte en `third_party/vibetrading/EXTIRPACIONES.md`; origen y frontera en `third_party/vibetrading/IMPORT.md` |
| **OpenWork** | https://github.com/different-ai/openwork | `fc8b43b530b468026760c5da4e13dbb9c2fd78a0` | MIT **sólo** para `apps/` + `packages/`; `/ee` FSL-1.1-MIT excluido | 2026-08-09 | **sí** — importación limitada al árbol MIT; cortes de nube/identidad, telemetría, updater, suscripción y marca se registran en `third_party/openwork/EXTIRPACIONES.md`; testigo y frontera en `third_party/openwork/IMPORT.md` |
| **OfficeCLI** | https://github.com/iOfficeAI/OfficeCLI | `v1.0.145`; tag commit `e402d2853259177aba05ee6f79d38b7e1ff067ae` | Apache-2.0; LICENSE/NOTICE/THIRD-PARTY-NOTICES preservados | 2026-08-09; identidad verificada 2026-09-13 | ejecutable macOS arm64 idéntico al asset oficial, SHA256 `d66763a563bc844c3cc67036ebc7c4a9caa9319b9592814d9acd3706da231fc1`; skills conservadas. Ver `third_party/officecli/UPSTREAM-IDENTITY.json`; MCP stdio con update/auto-install apagados. |
| **gws** | https://github.com/googleworkspace/cli | `a3768d0e82ad83cca2da97724e46bea4ff0e6dbd` | Apache-2.0 | 2026-08-09 | distribución oficial macOS arm64 y sólo skills Gmail/Calendar/Docs/Sheets; OAuth del usuario queda fuera en Gate 1 — ver `third_party/gws/IMPORT.md` |
| **opencode** | https://github.com/anomalyco/opencode | `v1.17.11` (release oficial; SHA-256 del asset `40723446…ba8342`, **contrastado con el digest que publica GitHub**) | MIT; el repo no publica NOTICE (404) | 2026-08-10 | **sí** — el MOTOR de Oficina, no una elección de Aleph: es la versión que OpenWork pinnea en su propio `constants.json`. Su descarga en build se neutralizó (el binario viaja commiteado) y su auto-update se apaga con `OPENCODE_DISABLE_AUTOUPDATE=1` — ver `third_party/opencode/IMPORT.md` |
| **Local Deep Research** | https://github.com/LearningCircuit/local-deep-research | `a734d52913879b82783ddd54e1eacfe809de3c3b` | MIT (LearningCircuit, 2025) | 2026-08-10 | **sí** — extirpación de su aplicación web Flask y su capa de cuentas (Ley 2.bis), y costura al Cerebro por el parámetro `llms=` que el propio repo dejó. Corte por corte en `third_party/ldr/EXTIRPACIONES.md`; origen, frontera e integridad en `third_party/ldr/IMPORT.md`. **No es un vertical: es el motor del modo Deep Research de LA SALA.** |
| **Vane** (ex-Perplexica) | https://github.com/ItzCrazyKns/Perplexica (redirige a `ItzCrazyKns/Vane`) | `7dc5d088f7262fbc5e39037f84940a8a2193c5fb` | MIT (ItzCrazyKns, 2026) | 2026-08-10 | **sí** — muerte de la cara y de **seis fugas a cuatro terceros** (favicons de Google ×4, geolocalización por IP, coordenadas a BigDataCloud, logos de Clearbit), y costura al Cerebro **por config generada, no por `OPENAI_BASE_URL`** — con esa env var sola el proveedor devuelve lista de modelos vacía. Corte por corte en `third_party/vane/EXTIRPACIONES.md`; frontera `.assets/` e integridad en `third_party/vane/IMPORT.md`. **No es un vertical: es el motor de la búsqueda base de LA SALA.** |

**Frontera de assistant-ui y AG-UI:** se trajo la **clausura transitiva de paquetes
completos**, no el monorepo entero. En un workspace pnpm el paquete es la unidad que se
publica, así que una carpeta `packages/<x>/` completa (con `src`, tests, `package.json` y
`README`) es exactamente lo que `npm install` entrega: no es un cherry-pick de archivos.
Los dos `IMPORT.md` declaran qué entró, qué no y por qué, con los pesos medidos (117 MB de
repos enteros → 8,8 MB de clausura; la diferencia es casi toda GIFs y videos de marketing).

**Frontera de OpenScience:** distinta, y por eso se declara aparte. Acá la unidad no era un
paquete publicable sino **el repo entero**: el stack es un binario auto-contenido (Bun) más
su árbol de skills y conectores, y partirlo habría sido justo el cherry-pick que la Ley 1
prohíbe. Se trajeron los **4.415 archivos rastreados por git**, verificados **byte a byte**
contra el origen (sha256 archivo por archivo, cero diferencias). No viajaron los
`node_modules` (919 MB, reproducibles desde `bun.lock` e ignorados por el `.gitignore`) ni
el historial. Árbol importado: **86 MB**. Detalle en `third_party/openscience/IMPORT.md`.

**Frontera de Vibe-Trading:** como OpenScience, la unidad es **el repo entero** — el stack es un
backend Python (agente + 23 loaders + 5 zoos de factores + 88 skills + la máquina de mandato) más
su frontend React y su cáscara Electron, y partirlo habría sido el cherry-pick que la Ley 1
prohíbe. Se trajeron los **2.185 archivos rastreados por git**, verificados **byte a byte** contra
el origen (sha256 archivo por archivo, cero diferencias sobre los 2.185). No viajaron los
`node_modules` ni el historial. Árbol importado: **63 MB**; tras la extirpación, **46 MB**.
Detalle en `third_party/vibetrading/IMPORT.md`.

**La vara de la extirpación de Vibe-Trading:** el suite completo del stack (9.999 tests) corrido
sobre el clon intacto y sobre el árbol operado, mismo venv y mismo `HOME` aislado: **9.907 → 9.665
pasaron, 0 rojas**. El delta de −242 se explica sin resto: 205 de los 27 archivos de test borrados
enteros, y 37 de tests quitados dentro de seis archivos que sobreviven, enumerados uno por uno en
`EXTIRPACIONES.md`. **Cero regresión.**

A esta pieza **sí se le tocó código**, que es la diferencia con las otras dos. Las dos
cirugías de la Ley 6 —amputarle el agente y teñirle la piel— acá tenían mucho que cortar:
el stack traía cuenta propia, billetera propia, proveedor gestionado propio y un camino de
OAuth que usaba el `client_id` del Codex CLI oficial de OpenAI como si fuera suyo. Todo eso
salió. Más un arreglo de defecto previo (`compute_job` mandaba un esquema con raíz `anyOf`
sin `type`, y un proveedor que valida esquemas mataba la sesión entera). **Corte por corte,
con archivo y motivo, en `third_party/openscience/EXTIRPACIONES.md`.**

**Frontera de Local Deep Research:** el repo publica **dos** superficies —una aplicación
web Flask con cuentas y una base SQLCipher por usuario, y una **librería** Python con API
programática—. Aleph hereda **la librería**; la aplicación no se instala ni se sirve. Se
trajeron los **3.303 archivos rastreados por git**, byte a byte (sha256 archivo por
archivo, cero diferencias). Árbol importado: **50 MB**. Detalle en
`third_party/ldr/IMPORT.md`.

**Frontera de Vane:** entraron **233** de los 238 archivos rastreados. Los 5 de afuera son
todo `.assets/` —el GIF de demo de 32 MB, la captura de su UI y los logos de sus
patrocinadores—, que **no forman parte de la aplicación**: no están bajo `public/`,
Next.js nunca los sirve y sólo los referencia su README. Es la misma distinción ya
declarada para assistant-ui/AG-UI. Sin ellos el árbol pasa de 36 MB a **2,9 MB**. Detalle
en `third_party/vane/IMPORT.md`.

**Lo que NO entró con Vane, y es lo importante: SearXNG.** El metabuscador que Vane usa es
**AGPL-3.0**, y este documento lo prohíbe como código adentro. No hizo falta decisión
nuestra: **upstream ya lo corre por el camino Descarga** —lo clona en tiempo de build
(`Dockerfile:56-57`), lo mete en su propio venv con su propio usuario de sistema, y le
habla sólo por HTTP JSON (`src/lib/searxng.ts:25-27`)—. Lo único que el árbol de Vane trae
de SearXNG son **tres archivos de configuración**. Aleph hereda esa separación tal cual:
el pack lo levanta como proceso vecino. **Ninguna línea AGPL viaja dentro del `.app`.**

### Las tres familias tipográficas del estándar (OFL-1.1)

[rediseño · fase 1 · 1.2 · 2026-09-07]

| Familia | Pesos | Origen | Licencia |
|---|---|---|---|
| **Instrument Serif** | 400 | Google Fonts (`fonts.gstatic.com`) | OFL-1.1 |
| **Poppins** | 200 · 300 · 400 · 500 | Google Fonts | OFL-1.1 |
| **JetBrains Mono** | 400 · 500 | Google Fonts | OFL-1.1 |

**20 archivos `.woff2`, 293 KB en total**, en `product/app/design/vendor/fonts/`, con su hoja
generada en `vendor/fonts-estandar.css`. Mismo procedimiento que `fonts-sistema.css` (Outfit
+ Newsreader, Casa 2 · F1.b): se pide el CSS a `fonts.googleapis.com`, se bajan los `woff2`
que referencia y se reescribe cada `url()` a la copia local. **Los `unicode-range` quedan
intactos**, así que el navegador baja sólo el subset que la pantalla necesita. La app es
offline-first: **no se linkea Google Fonts en runtime**.

Cada archivo se verificó byte a byte contra la firma `wOF2` y lleva su sha256 en el nombre
(`<familia>-<sha256[:8]>.woff2`), igual que las dos anteriores.

**OFL-1.1 permite redistribuir dentro del producto**; lo único que prohíbe es vender la
fuente sola. Es la misma licencia bajo la que ya viaja `@fontsource-variable/inter` dentro
del binario de Ciencia.

### El interruptor de la piel (`aleph-piel.js` / `aleph-piel.css`)

[rediseño · fase 1 · cable de seguridad (b) · 2026-09-07]

A los **seis** stacks con cara propia —OpenScience, OpenWork, Vibe-Trading, DeepTutor,
doc.haus y Open CoDesign— se les agregaron **dos archivos de Aleph** en su `public/` y
**una línea** en su `index.html` (en DeepTutor, en su `app/layout.tsx`):

| Archivo | De quién | Qué hace |
|---|---|---|
| `public/aleph-piel.js` | **de Aleph** — byte-idéntico en los seis, y una vara lo exige | lee `aleph_piel` de la URL del `<iframe>` y, sólo si dice `v2`, agrega la hoja |
| `public/aleph-piel.css` | **de Aleph** | la piel. En la fase 1 está vacía a propósito: sólo trae un testigo |
| `<script src="/aleph-piel.js">` | 1 línea en el `index.html` de upstream | la única cirugía sobre código ajeno |

Es la **misma costura** que `aleph-picker-unico.js` ya usa desde 2026-08-22 y la que la
**Ley 6** de `third_party/README.md` permite: teñir la piel *por el punto de extensión que
el propio repo dejó* —`public/` se sirve tal cual—, sin abrir el cuerpo de ningún
componente. Fuera de Aleph el archivo es un **no-op** (LEY 0: `window.parent === window`
⇒ return), así que los seis árboles siguen corriendo sueltos exactamente como su upstream.

Existe para que el rediseño de UI sea **reversible sin build**: la hoja viaja siempre
adentro del `dist`, y apagarla es una palabra en la casa. Vara: `qa/verify_piel_flag.mjs`
(y su corredor `.py`), que mide los dos brazos del interruptor y la Ley 0.

### Lo que viaja DENTRO del artefacto construido

`product/app/design/sala-v2/vendor/assistant-ui.bundle.js` (643 KB) se construye desde esas
dos carpetas con `tools/sala-v2-build/`. El bundle **también embebe 90 paquetes de npm**
—las dependencias que assistant-ui y AG-UI declaran— así que sus licencias se distribuyen
con Aleph y se anotan acá. El inventario exacto, con versión y licencia paquete por paquete,
lo escribe el propio build en
`product/app/design/sala-v2/vendor/assistant-ui.bundle.manifest.json`: **no se transcribe a
mano, se genera**, para que no pueda quedar desactualizado en silencio.

| Licencia | Paquetes | Ejemplos |
|---|---|---|
| MIT | 86 | react · react-dom · radix-ui · @floating-ui/* · zod · zustand · nanoid · uuid · fast-json-patch |
| Apache-2.0 | 1 | rxjs |
| Apache-2.0 AND BSD-3-Clause | 1 | @bufbuild/protobuf |
| BSD-3-Clause | 1 | secure-json-parse |
| 0BSD | 1 | tslib |

**Cero copyleft.** Ninguna es GPL ni AGPL, que es la condición que `third_party/README.md`
pone para que algo pueda vivir adentro del producto.

### OpenScience: su árbol de dependencias

El stack de Ciencia no se empaqueta como bundle JS sino como **binario auto-contenido**
(Bun compila un solo Mach-O/ELF). Sus dependencias quedan **adentro del ejecutable**, así
que sus licencias se distribuyen con Aleph igual que las de arriba. Censo del árbol JS
instalado desde su `bun.lock` — **762 paquetes únicos**:

| Licencia | Paquetes |
|---|---|
| MIT | 610 |
| Apache-2.0 | 68 |
| ISC | 29 |
| BSD-3-Clause | 21 |
| BSD-2-Clause | 12 |
| BlueOak-1.0.0 | 9 |
| MPL-2.0 (o dual con Apache-2.0) | 3 |
| otras permisivas (MIT-0, 0BSD, CC0-1.0, OFL-1.1, Python-2.0, CC-BY-4.0, AFL-2.1) | 8 |
| sin campo declarado en su `package.json` (MIT aguas arriba) | 2 |

**Cero GPL. Cero AGPL. Cero SSPL. Cero BUSL. Cero Elastic.** Los tres que merecen nota:
`lightningcss` es **MPL-2.0** pero es herramienta de build y no viaja modificada;
`dompurify` es dual y se elige su Apache-2.0; `@fontsource-variable/inter` es **OFL-1.1**,
redistribuible (lo único prohibido es vender la fuente sola).

**Lo que NO viaja:** `@synsci/atlas`. Entraba siempre como `optionalDependency` del paquete
npm de origen y viene del repo **privado** `synthetic-sciences/thesis`. Se declara MIT,
pero una licencia sin fuente accesible no es un permiso que se pueda heredar con confianza
ni un binario que se pueda auditar dentro de un `.app`. Se extirpó su declaración, su
resolvedor y el lanzador que lo instalaba globalmente.

**Deuda declarada:** 61 de las 294 skills no dicen con claridad qué librería envuelven (22
sin campo, 39 con `Unknown`). El campo se renombró de `license:` a `upstream-license:`
porque describía la librería aguas arriba, no la skill — leído literalmente parecía decir
que Aleph distribuía seis skills GPL, y se verificó que no hay código copyleft vendorizado.
Detalle y forma de saldarlo en `third_party/openscience/NOTICE-ALEPH.md`.

---

## Piezas usadas SIN importar

Motores y repos que Aleph usa pero cuyo código **no** vive en este árbol —copyleft fuerte
por el camino Descarga (proceso aparte), o repos leídos sólo como patrón. Se anotan acá
para que el rastro no se pierda, aunque no haya código nuestro que atribuir.

| Pieza | Repo origen | Licencia | Cómo se usa |
|---|---|---|---|
| **42 fuentes científicas** (UniProt · RCSB PDB · PDBe · AlphaFold DB · InterPro · SIFTS · Ensembl · NCBI E-utilities · NCBI Gene · ClinVar · dbSNP · gnomAD · UCSC · MyGene · MyVariant · ChEMBL · PubChem · ChEBI · BindingDB · GuideToPharmacology · SureChEMBL · Reactome · KEGG · STRING · IntAct · BioGRID · WikiPathways · Open Targets · GEO · ArrayExpress · Expression Atlas · GTEx · Human Protein Atlas · DepMap · Single Cell Atlas · Europe PMC · Crossref · OpenAlex · Semantic Scholar · arXiv · bioRxiv · PubMed) | APIs web públicas — no hay repo | **cada una la suya** | Los conectores de `third_party/openscience/backend/cli/src/science/connectors/` las **consultan**; Aleph no redistribuye su dato. Sin llaves, salvo dos opcionales (Semantic Scholar, OpenAlex). |

**Lo que hay que mirar antes de vender algo construido con esto:** dos de esas fuentes
ponen condiciones que no son las de una API pública cualquiera. **KEGG** exige licencia
comercial para uso no académico. **HMDB** pide permiso explícito para redistribuir porciones
significativas con fines comerciales. Ninguna afecta el código —no viaja dato de ellas en
el árbol— pero sí afectan a quien publique resultados o un producto derivado. Se anotan acá
para que el rastro no se pierda: el `NOTICE` del proyecto de origen ya avisa que cada fuente
se rige por sus propios términos y que **el responsable de cumplirlos es quien consulta**.

Toda consulta sale identificada con el contacto de quien opera la instalación
(`ALEPH_SCIENCE_MAILTO`, default en `science/connectors/http.ts`) — no con el buzón del
proyecto de origen, que era lo que la pieza traía.
