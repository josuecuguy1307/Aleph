# Vane (ex-Perplexica) — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | `https://github.com/ItzCrazyKns/Perplexica` — **redirige a `ItzCrazyKns/Vane`** |
| Commit importado | `7dc5d088f7262fbc5e39037f84940a8a2193c5fb` |
| Licencia de código | MIT (`LICENSE`, conservada en la raíz) |
| Titular | ItzCrazyKns, 2026 |
| Versión del paquete | `vane@1.12.2` (`package.json`) |
| Fecha de importación | 2026-08-10 |
| Estudio previo | `~/Desktop/T7-SALA-ESTUDIO.md` (Motor A, §1-§8) |
| Árbol testigo | `~/Desktop/oss-estudio/sala-busqueda/perplexica` (clon somero, mismo commit) |
| Qué es | El motor de la **búsqueda web base de LA SALA** (plan §6.a.bis). No es un vertical. |

## El nombre cambió

El plan lo nombra «Perplexica/Vane». En el disco ya no hay ambigüedad: **el proyecto se
llama Vane**. `package.json:2` dice `"name": "vane"`, el README dice `# Vane 🔍`, y el
commit de HEAD es un merge desde `github.com/ItzCrazyKns/Vane`. La carpeta acá se llama
`vane` por eso. La marca ajena muere igual (Ley 2.bis / 3.8) — el nombre se registra para
que el origen sea rastreable, no para usarlo.

## Integridad antes de cirugía

Se copiaron **233 archivos** rastreados por git, verificados **sha256 archivo por archivo
contra el clon testigo: cero diferencias**. Manifiesto en
[`MANIFEST.sha256`](MANIFEST.sha256); su propio hash:

```
a4c203694bb09ac02bc84dc32309c8ad11aa4ae87e3da69b9b19df9086538f83
```

### ⚠️ Su `.gitignore` ignora `/searxng`, y ahí estaban los tres archivos que importan

`third_party/vane/.gitignore:39` trae `/searxng`. En el repo de origen esos tres archivos
igual están rastreados (se agregaron antes que la regla), pero al copiarlos acá **git los
ignoraba**: quedaban en disco y fuera del control de versiones. Son justamente
`settings.yml`, `limiter.toml` y `uwsgi.ini` — la configuración que el launcher le pasa al
proceso vecino (`SEARXNG_SETTINGS_PATH`). Un clon limpio habría arrancado sin ellos y el
metabuscador habría corrido con su configuración por defecto, **sin el formato `json` que
Vane necesita**: una falla silenciosa y difícil de diagnosticar.

Entraron con `git add -f`, y queda dicho acá para que nadie los borre creyendo que sobran.
Es el único caso en Vane: los otros 230 archivos entraron sin forzar nada.

⚠️ **El manifiesto es el testigo de ANTES de la cirugía.** `EXTIRPACIONES.md` borró y editó
archivos después, así que un `shasum -c` va a marcar diferencias en esos. Es correcto: el
manifiesto prueba que lo que entró era idéntico al origen; las extirpaciones prueban qué se
le hizo después. Re-generarlo post-cirugía lo dejaría sin servir para lo único que sirve.

## Frontera declarada — `.assets/`

El origen rastrea **238** archivos. Entraron **233**. Los 5 que quedaron afuera son todo
el directorio `.assets/`:

| archivo | peso | qué es |
|---|---|---|
| `.assets/demo.gif` | 32 MB | video de demostración del producto ajeno |
| `.assets/vane-screenshot.png` | 1,6 MB | captura de su UI para el README |
| `.assets/sponsers/warp.png` | 436 KB | logo de un patrocinador suyo |
| `.assets/sponsers/exa.png` | — | logo de un patrocinador suyo |
| `.assets/manifest.json` | — | índice de lo anterior |

**Por qué es frontera y no cherry-pick:** `.assets/` **no forma parte de la aplicación**.
No está bajo `public/`, Next.js nunca lo sirve, y el único que lo referencia es el propio
README (`README.md:13,51,68` — medido: cero referencias desde `src/`, `next.config.mjs`
o cualquier `.ts`/`.tsx`). Son los activos de marketing del producto ajeno, es decir
exactamente la identidad que la Ley 2.bis mata de todos modos. Sin ellos el árbol pasa de
36 MB a **2,9 MB**.

Precedente: la misma distinción que `ATTRIBUTIONS.md` ya declara para assistant-ui/AG-UI
(«la diferencia es casi toda GIFs y videos de marketing»).

`public/screenshots/` **entró en la importación cruda** y después **salió en la cirugía**
(`EXTIRPACIONES.md` §1.9). El razonamiento original —«lo consume el manifiesto PWA, o sea
es código»— era correcto sobre el árbol importado (`src/app/manifest.ts:14,19,24,29`) y
dejó de serlo cuando ese manifiesto murió por marca ajena: sin él, las capturas son lo que
siempre fueron, capturas del producto ajeno. Se deja escrito el cambio de criterio en vez
de borrar la frase, porque la frontera de una importación se juzga por lo que se decidió y
cuándo.

## SearXNG **no está acá**, y es correcto

El motor de metabúsqueda que Vane usa es **AGPL-3.0**, y `third_party/README.md` lo
prohíbe como código adentro. No hizo falta ninguna decisión nuestra: **upstream ya lo
corre por el camino Descarga.**

- El directorio `searxng/` del origen son **tres archivos de configuración**
  (`settings.yml`, `limiter.toml`, `uwsgi.ini`) — cero código de SearXNG.
- SearXNG se clona en tiempo de build (`Dockerfile:56-57`), vive en su propio venv
  (`Dockerfile:59-62`) y corre como **proceso aparte** con su propio usuario de sistema
  (`Dockerfile:40-43`, `entrypoint.sh:6`).
- El único contacto es HTTP JSON: `src/lib/searxng.ts:25-27`.

Aleph hereda esa separación tal cual: el pack levanta SearXNG como proceso vecino y le
pasa su URL a Vane por `SEARXNG_API_URL`. Ver `third_party/vane/PROCESO-SEARXNG.md`.

## Alcance heredado — el motor, jamás la cara

`Dockerfile.slim` del propio origen es la referencia de qué entra: es **Vane sin SearXNG**,
apuntando a una instancia externa (`docs/installation/UPDATING.md:19,22`), y su arranque
es `CMD ["node", "server.js"]` sin `entrypoint.sh`. Eso es exactamente la forma que Aleph
quiere.

Lo que Aleph usa:

| Superficie | Para qué |
|---|---|
| `src/lib/agents/search/**` | el pipeline: clasificador → investigador agéntico → escritor |
| `src/lib/searxng.ts` | el cliente HTTP del metabuscador |
| `src/lib/models/**` | los proveedores — **la costura** (ver abajo: NO es `OPENAI_BASE_URL`) |
| `src/lib/session.ts` | el emisor de bloques y sus parches RFC-6902 |
| `src/app/api/chat/route.ts` | **la puerta**: NDJSON de bloques con progreso real |

Lo que **no** se monta: `src/app/page.tsx`, `src/app/c/`, `src/app/discover/`,
`src/app/library/` y todo `src/components/`. Nunca se navega a ellas.

## La puerta es `/api/chat`, no `/api/search`

Medido en el estudio y confirmado en el árbol importado: `/api/search` —la API que el
repo **documenta**— le pasa al investigador una sesión descartable
(`src/lib/agents/search/api.ts:31`, `SessionManager.createSession()`), así que **todo el
progreso del pipeline se emite a una sesión que nadie escucha**. La puerta con progreso
real es `/api/chat` (`src/app/api/chat/route.ts:159-211`).

## Los embeddings — decisión del dueño, registrada

Vane exige un modelo de embeddings para su reranker. El borde de dialecto de Aleph sirve
`chat/completions`, no `/v1/embeddings`. **El dueño autorizó el proveedor `transformers`
local** (`src/lib/models/providers/transformers/`), con el precedente ONNX de Legal: es un
**motor del stack**, no el cerebro. La LEY 12 sigue intacta — el modelo que *razona* es
uno solo y es el nuestro; el que mide coseno es una herramienta del motor.

## La costura al cerebro — **no es una env var**

`OPENAI_BASE_URL` **no alcanza**, y conviene decirlo acá porque es lo intuitivo: con una
`baseURL` que no es la de OpenAI, el proveedor devuelve **lista de modelos vacía**
(`src/lib/models/providers/openai/index.ts:138-150`) y el selector queda sin nada. La
costura real la escribe `platform/sala/busqueda/config.py`, que traduce el archivo del pack
al `data/config.json` de Vane **entero**: un proveedor, un modelo declarado a mano, y el
setup ya resuelto.

## Reproducibilidad de runtime

`yarn.lock`: **874 `name@version`** medidos contra el registro npm —
689 MIT · 58 Apache-2.0 · 46 ISC · 39 BSD · 14 LGPL-3.0-or-later · 2 MPL-2.0.
**Cero AGPL, cero SSPL, cero GPL puro.** Los 14 LGPL son todos `@img/sharp-*`: binarios
nativos por plataforma de `sharp`, dependencias opcionales de carga dinámica (en un Mac
se instala uno solo). Seis paquetes quedaron sin licencia resuelta y están declarados en
el estudio, §2.3.
