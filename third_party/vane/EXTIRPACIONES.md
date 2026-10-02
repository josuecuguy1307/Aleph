# EXTIRPACIONES — Vane dentro de Aleph

Registro de lo que se le cortó a la pieza importada: **qué · dónde · por qué**. Gobierna
`third_party/README.md` · **Ley 6** («sólo se corta el agente y se tiñe la piel»),
**Ley 5** («cero refactor inicial») y **Ley 2.bis / 3.8** (identidad y marca ajena).

**Base:** `ItzCrazyKns/Perplexica@7dc5d088` (hoy `Vane`, v1.12.2), 233 archivos importados
byte a byte idénticos al origen (sha256 archivo por archivo, cero diferencias — `IMPORT.md`).
**Mapa que ordena estos cortes:** `~/Desktop/T7-SALA-ESTUDIO.md` §2.

---

## 0 · Lo que NO hubo que cortar

| Qué | Medición |
|---|---|
| **Telemetría** | **No tiene.** `grep -riE "telemetry\|analytics\|posthog\|sentry\|mixpanel\|amplitude\|umami\|plausible"` sobre `src/`: **0 hits**. |
| **Cuentas / login** | **No tiene.** `grep -riE "\blogin\b\|signin\|jwt\|nextauth\|passwordHash"` sobre `src/`: **0 hits**. No hay capa de identidad que extirpar: no existe. |
| **SearXNG** | **Nunca entró** (`IMPORT.md`). Es AGPL y va por proceso aparte, como upstream ya lo corre. |
| Su pipeline, sus 16 rutas de API, sus proveedores, sus widgets | **Enteros.** Son el motor y el dominio (LEY 0). |

---

## 1 · La cara — «su UI NO se monta»

§6.a.bis lo sella: *«se hereda el motor sin la cara … La cara ES la Sala»*. No es una
preferencia estética: mientras exista una página, existe la posibilidad de que alguien
navegue a `127.0.0.1:<puerto>` y vea un producto ajeno adentro de Aleph (Ley 3: si el
usuario adivina de qué repo vino, se adaptó mal).

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1.1 | La home | `src/app/page.tsx` (borrado) | La pantalla del producto ajeno. |
| 1.2 | Discover | `src/app/discover/page.tsx` (borrado) | Su feed de artículos del día. |
| 1.2.bis | **La página de un chat** | `src/app/c/[chatId]/page.tsx` (borrado) | La conversación abierta del producto ajeno. **Faltaba en esta tabla**: el commit hablaba de «las tres páginas» y los árboles de página borrados fueron cuatro. Lo encontró una revisión adversarial contando el diff. |
| 1.3 | Library | `src/app/library/page.tsx` · `library/layout.tsx` (borrados) | Su historial de búsquedas. La biblioteca de la casa es la Biblioteca. |
| 1.4 | El root layout, **vaciado** | `src/app/layout.tsx` (58 → 33 líneas) | Next exige un root layout aunque no haya páginas, así que no se borra: se vacía. Con él se fueron `Sidebar`, `SetupWizard`, `ChatProvider`, `ThemeProvider` y `Toaster`. **Los archivos siguen en el árbol** (Ley 5: cero refactor); simplemente ya no los alcanza ninguna ruta y el build no los emite. ⚠️ **CORREGIDO 2026-08-18: «el build no los emite» era cierto y no alcanzaba.** Next no los EMITE, pero `tsc` los TYPECHECKEA igual —el typecheck es del proyecto entero, no del grafo de rutas—, así que tres huérfanos que importaban páginas borradas **rompían `yarn build` con TS2307**. No se vio antes porque la obra corrió bajo régimen de cero varas y nadie buildeó. Se arregló mudando el tipo (§1.12) y borrando los dos sin importadores (§1.11). |
| 1.5 | **`next/font/google`** | `src/app/layout.tsx` (ex-4, ex-14..19) | Bajaba la tipografía Montserrat de Google **en tiempo de build**. En un producto que se vende como privado, y en una casa que empaqueta offline, una fuente que se descarga de un tercero al compilar no entra. |
| 1.6 | El `metadata` del producto ajeno | `src/app/layout.tsx` (ex-21..24) | `title: 'Vane - Direct your curiosity'`. Marca. |
| 1.7 | El manifiesto PWA | `src/app/manifest.ts` (53 líneas, borrado) | Era marca pura: nombre, claim, íconos y capturas del producto ajeno. |
| 1.8 | El favicon y los íconos | `src/app/favicon.ico` · `public/icon.png` · `public/icon-50.png` · `public/icon-100.png` (borrados) | Ídem. |
| 1.9 | Las capturas de su producto | `public/screenshots/` (4 archivos, borrados) | Sólo las usaba el manifiesto PWA (1.7). |
| 1.11 | **Las dos tarjetas de Discover** | `src/components/Discover/MajorNewsCard.tsx` · `SmallNewsCard.tsx` (borrados) | Huérfanas de la página de 1.2: importaban el tipo `Discover` de `@/app/discover/page`, que ya no existe. **Cero importadores vivos** (grep). Murieron con su página; dejarlas era dejar código que no compila para alimentar una pantalla que no existe. |
| 1.10 | El andamio de Vercel | `public/next.svg` · `public/vercel.svg` (borrados) | Boilerplate de `create-next-app`. |

### 1.12 · Lo que NO se extirpó: el tipo `Chat`, mudado

`src/components/DeleteChat.tsx` importaba `Chat` de la página borrada en 1.3, pero **sí
tiene un importador vivo** (`Navbar.tsx:5`), así que borrarlo habría arrastrado media
cadena de componentes que la Ley 5 manda dejar quietos.

`Chat` es un tipo de **dominio** —un hilo guardado, seis campos— y estaba en una página por
comodidad de upstream. Se movió tal cual a `src/lib/types.ts`, sin agregarle ni quitarle un
campo, y el import de `DeleteChat` pasó a apuntar ahí. Es la cirugía más chica que deja
compilar el árbol: cero componentes tocados, cero lógica movida.

`public/` pasó de 34 archivos (1,5 MB) a **25 (348 KB)**. Lo que quedó son los íconos del
clima y la tipografía local del motor: dominio, no marca.

---

## 2 · Las fugas a terceros — **6 sitios, 4 destinos**

*(Si algún documento de esta tanda dice «las tres fugas», está mal: son **cuatro destinos** —Google, freeipapi, BigDataCloud y Clearbit— en **seis** sitios de llamada.)*

**Éste es el corte que más importa, y no estaba en el mandato: apareció midiendo.** Vane
se vende como *«privacy-focused … keeping your searches completely private»*, y sin
embargo cuatro terceros distintos recibían al usuario o a sus consultas. Aleph va a
distribuir este código: la fuga sería nuestra.

| # | Qué | Dónde | Por qué sale, y qué quedó |
|---|---|---|---|
| 2.1 | **La IP del usuario a un tercero** | `src/lib/actions.ts` (ex-25, `getApproxLocation`) | Mandaba la IP a `free.freeipapi.com` para adivinar la ciudad y pintar el clima. Es la única llamada del árbol que expone **al usuario** en vez de a su consulta. Se corta la red y se conserva la firma con sus tres claves exactas: devolver `null` habría roto el typecheck en `WeatherWidget.tsx:54,57,60`, que las desestructura. Nada se rellena. |
| 2.2 | **Las coordenadas exactas a un tercero** | `src/components/WeatherWidget.tsx:35` (ex-35..51) | El nombre de la ciudad salía de `api-bdc.io` (BigDataCloud) mandándole las coordenadas del GPS. Las coordenadas —que el usuario ya autorizó— siguen igual y el clima sigue funcionando; la ciudad queda vacía en vez de comprada afuera. |
| 2.3 | **La lista de lo que el usuario mira, a Google** ×3 | `src/components/MessageSources.tsx:46,83,133` | El favicon de cada fuente citada salía de `s2.googleusercontent.com/s2/favicons?domain_url=<URL>` — o sea que Google recibía **cada URL que el usuario consulta**. Re-apuntado al favicon del propio sitio citado: misma función, cero tercero. |
| 2.4 | Ídem, en los pasos del asistente | `src/components/AssistantSteps.tsx:187` | Igual que 2.3. |
| 2.5 | El logo de empresa a Clearbit | `src/components/Widgets/Stock.tsx:299` | `logo.clearbit.com/<host>` en el widget de acciones. Re-apuntado al favicon del propio sitio. |
| 2.6 | **El permiso que dejaba volver la fuga** | `next.config.mjs:7-13` | `images.remotePatterns` tenía un solo host permitido: `s2.googleusercontent.com`. Queda **vacío**. Sin host permitido, `next/image` no sale a ningún lado: es lo que hace que 2.3 y 2.4 no puedan volver por descuido. |

**Censo de dominios después del corte** (`grep` sobre `src/`): quedan los endpoints de los
proveedores de modelo (que la costura no usa: apuntamos al borde), `api.open-meteo.com` y
`nominatim.openstreetmap.org` (las fuentes propias del widget de clima, keyless — LEY 0),
y los `localhost` de Ollama / LM Studio / SearXNG. **Ninguno expone al usuario.**

---

## 3 · Lo que NO se cortó, y por qué

| Qué | Por qué queda |
|---|---|
| `src/components/**` entero | Ley 5: cero refactor. Sin una ruta que los alcance, el build no los emite. Borrarlos sería reescribir el árbol ajeno para ganar cero. |
| `src/app/api/search/route.ts` | **La puerta que Aleph NO usa** (le pasa al investigador una sesión descartable, `src/lib/agents/search/api.ts:31`, así que no rinde progreso). Se conserva porque es dominio del stack y porque su existencia está documentada: la decisión de no usarla se explica en `platform/sala/busqueda/etapas.py`, no borrando código ajeno. |
| Su `README.md` con badges, Discord y patrocinadores | El usuario nunca lo ve; el origen está declarado en `IMPORT.md`. Borrar la documentación de origen de una pieza de terceros oscurece de dónde vino. |
| `Dockerfile`, `Dockerfile.slim`, `docker-compose.yaml`, `entrypoint.sh` | No se usan (el pack levanta los procesos), pero son **la evidencia de que SearXNG va aparte** y la referencia de cómo se construye su runtime. Se citan en `IMPORT.md` y en `PROCESO-SEARXNG.md`. |

---

## 4 · La deuda que el dueño resolvió por decreto, y la que queda abierta

**Resuelta — los embeddings.** Vane exige un modelo de embeddings para su reranker y el
borde de Aleph no sirve `/v1/embeddings` (medido: esa ruta no existe en todo el backend).
El dueño autorizó el proveedor `transformers` **local**, con el precedente ONNX de Legal:
el motor del oficio puede computar localmente; el que no puede es **el cerebro**. La
frontera queda escrita en `platform/sala/busqueda/config.py`.

**Resuelta — la cancelación.** El motor no la tiene: `BaseLLM.streamText(input)`
(`src/lib/models/base/llm.ts:12-19`) **no acepta signal**, y los únicos `AbortController`
del árbol son el timeout de SearXNG (`src/lib/searxng.ts:41-42`) y el corte del stream de
`/api/search:115`, que sólo deja de escribir mientras el lazo sigue gastando. **El dueño
la declaró deuda: no se construye en esta fase.** Para la búsqueda base no es requisito
(sí lo es para el modo largo, que corre sobre el otro motor y sí la tiene).

**Abierta — los pesos del reranker.** `@huggingface/transformers` resuelve el modelo por su
cuenta en la primera corrida (`src/lib/models/providers/transformers/transformerEmbedding.ts:27-30`):
una instalación fría sale a la red de Hugging Face en su primera búsqueda. Es exactamente
el cabo que el precedente de Legal dejó sin resolver («pesos vendorizados vs. descarga en
primer uso»). Censado en `platform/workspaces/sources.py` para que se vea, no para que se
olvide. **Deuda: `vane-pesos-del-reranker-no-vendorizados`.**

**Abierta — dos defectos suyos, anotados y no tocados** (Ley 5; son de ellos, y ninguno nos
pega hoy):
- `src/lib/models/providers/openai/index.ts:154` — `getConfiguredModelProviderById(this.id)!`
  revienta con un `TypeError` mudo si el proveedor se borró de la config, en vez de dar
  causa (viola la ley técnica 9, pero es su código).
- `src/lib/agents/search/researcher/actions/search/baseSearch.ts:73-86` — si los embeddings
  fallan, **todo pasa con similitud 1** y el filtro `> 0.5` deja de filtrar. Degrada en
  silencio hacia «todo es relevante».
