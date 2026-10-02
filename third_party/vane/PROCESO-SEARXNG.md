# SearXNG — el proceso vecino (camino Descarga)

> **Nota de release (2026-09-22): documento histórico, arquitectura reemplazada.**
> La distribución propietaria actual **no empaqueta ni inicia SearXNG**. Los dos modos
> de La Sala sólo consumen la URL de una instancia independiente, configurada de forma
> explícita por el usuario; sin ella no arrancan. El servidor, su `lib/` y los archivos
> `third_party/vane/searxng/` quedan fuera del `.app`. Las secciones antiguas que
> describen un SearXNG «vecino» dentro de la aplicación no son instrucciones vigentes.
> La prueba de ausencia es `qa/verify_bundle_without_searxng.py` y debe ejecutarse
> sobre cada bundle nuevo. El bundle congelado r5 aún contiene AGPL y sigue bloqueado.

**Por qué este archivo existe:** SearXNG es **AGPL-3.0**, y `third_party/README.md` lo
prohíbe explícitamente como código adentro: *«Copyleft fuerte (GPL / AGPL). Jamás como
código adentro. Esos motores se usan por el camino Descarga: proceso aparte, hablado por
API/CLI/MCP»*. Este documento dice cómo se cumple eso acá, y por qué casi no costó nada.

---

## 1 · Upstream ya lo hacía así — no fue una decisión nuestra

Lo medido sobre el árbol importado, con línea:

| Hecho | Evidencia |
|---|---|
| El directorio `searxng/` del repo son **tres archivos de configuración**, cero código | `third_party/vane/searxng/{settings.yml,limiter.toml,uwsgi.ini}` |
| SearXNG se **clona en tiempo de build**, no vive en el árbol | `Dockerfile:56-57` — `git clone "https://github.com/searxng/searxng" "/usr/local/searxng/searxng-src"` |
| Vive en **su propio venv** | `Dockerfile:59-62` |
| Corre con **su propio usuario de sistema** | `Dockerfile:40-43` |
| Se levanta como **proceso aparte**, antes del motor | `entrypoint.sh:6` (flask, `0.0.0.0:8080`), y recién en `:32` `exec node server.js` |
| El único contacto es **HTTP JSON** | `src/lib/searxng.ts:25-27` — `${searxngURL}/search?format=json` |
| La URL es **configuración**, no un puerto horneado | `src/lib/config/index.ts:104-116` (`search.searxngURL`, env `SEARXNG_API_URL`) |

Y existe `Dockerfile.slim`: **el mismo Vane sin SearXNG adentro**, esperando una instancia
externa (`docs/installation/UPDATING.md:19,22`), con `CMD ["node","server.js"]` y sin
`entrypoint.sh`. Es exactamente la forma que Aleph quiere, publicada por ellos.

**Conclusión: la frontera AGPL ya estaba trazada por upstream. Aleph la hereda, no la
inventa.** Ni una línea AGPL viaja adentro del `.app`.

---

## 2 · Las tres formas de tenerlo, en orden

Las implementa `platform/sala/busqueda/arranque.sh`.

### (1) Declarado — `ALEPH_SEARXNG_URL`

Alguien ya corre un SearXNG (propio, en otra máquina de la casa, o el que quiera) y da su
URL. **El pack no levanta nada** y se lo pasa a Vane tal cual.

Es el camino para desarrollo y para quien ya tiene uno. También es el camino honesto para
una instalación que decida no empaquetarlo.

### (2) Vecino — sus piezas al lado del launcher, SIN venv

`platform/sala/busqueda/searxng/lib/` — un **directorio plano**, no un venv, y esa palabra es
la corrección importante de esta sección.

**Por qué no un venv.** Un venv graba su `home` en `pyvenv.cfg` y la ruta del árbol de build
en cada shebang de `bin/*`. Copiado adentro de la `.app` produce algo que no arranca en la
máquina del usuario. Las dependencias van con `pip install --target`, que no graba ninguna
ruta, y se alcanzan por `PYTHONPATH`. Por eso el launcher usa `-m flask --app searx.webapp`
(módulo) y no `--app searx/webapp.py` (archivo): sin venv no hay `cd` al que volver.

**Un solo intérprete para los dos modos.** No hay `searxng/bin/python3`: SearXNG corre con el
Python que ya viaja en `platform/sala/research/runtime/bin/python3`, que es lo que hace cierta
la frase «una instalación, dos clientes». El spec hornea las dos piezas por separado y falla
fuerte si falta cualquiera (`aleph_sidecar.spec:536` y `:540`).

El launcher le elige un **puerto libre** (`bind(("127.0.0.1", 0))`), le genera un
**`SEARXNG_SECRET` propio** —el `settings.yml` de upstream trae uno publicado en un repo
público y su `entrypoint.sh` nunca exporta el override, medido— y lo mata en el
`trap EXIT INT TERM`.

Es el camino Descarga completo: **proceso aparte, código aparte, licencia aparte.** Ni una
línea AGPL entra al `.app`.

⚠️ **LOS DOS LAUNCHERS TIENEN QUE PEDIR LA MISMA FORMA.** `research/arranque.sh` pedía la
forma vieja (`bin/python3` + `src`) mientras `busqueda/arranque.sh` ya pedía `lib/searx`.
Con la instalación real al lado, el modo largo salía por su `else` y decía **«falta
SearXNG»** a un directorio de distancia del SearXNG instalado, con `exit 69`. Lo custodia
`qa/verify_searxng_lo_encuentran_los_dos.sh`, que **extrae la condición de cada launcher** y
la evalúa contra la disposición que el spec hornea de verdad — así que si una de las dos se
mueve sola, la vara se entera.

### (3) No está — **fallo visible, jamás mudo**

Sin metabuscador este modo **no busca**. Arrancar igual sería prometer una capacidad que no
existe, así que el launcher sale con `exit 69` y un mensaje que dice qué falta y cómo
resolverlo. El pack lo traduce a la causa tipada `pack_no_arranco` con su copy
(`product/backend/app/phase1/router.py`, `_COPY_PACK`).

Es el mismo criterio que el plan fijó para OpenBB en Finanzas: *«Motor apagado = ⚪
no-configurado visible, jamás fallo mudo»* (§3.3).

---

## 3 · La configuración que sí viaja

Los tres archivos de `third_party/vane/searxng/` **sí** están en el árbol y **sí** se usan:
son configuración, no código, y son de Vane, no de SearXNG.

`settings.yml` declara `formats: [html, json]` — sin `json` la API que Vane consume no
existe— y habilita `wolframalpha`. El launcher se lo pasa por `SEARXNG_SETTINGS_PATH`.

⚠️ **`settings.yml:14` trae un `secret_key` de ejemplo en claro**, con un comentario del
propio repo que dice que lo pisa `${SEARXNG_SECRET}`. Cuando se produzca el venv de (2)
hay que generar uno propio: un secreto publicado en un repo público no es un secreto.
Anotado como parte de la obra de empaquetado.

---

## 4 · Estado — el camino (2) EXISTE y se midió

Las tres viñetas de esta sección decían «el venv no está construido», «no se midió el
peso» y «nada se corrió». Las tres dejaron de ser ciertas: se reemplazan por lo medido en
vez de tacharlas, porque lo que importa es el número, no el cambio de estado.

| lo que decía | lo medido (2026-08-18) |
|---|---|
| «el venv de (2) no está construido» | **construido**, con `deploy/fase6/producir_busqueda.sh`. `searxng-2026.8.17+374939b`, `import searx` OK |
| «no se midió el peso» | venv + clon = **~450 MB** en disco |
| «no se midió el arranque en frío» | **8 intentos de 0,5 s ≈ 4 s** hasta que contesta. Muy por debajo de los 25 s de `ALEPH_PACK_ARRANQUE_S`; no hay que subir nada |
| «nada se corrió» | el launcher entero corrió: SearXNG en puerto libre, secreto propio 0600, migraciones aplicadas, Vane **200 en `/api/providers`**, y el trap se llevó al hijo sin dejar huérfanos |

**Búsqueda real, sin una sola llave:** `GET /search?format=json&q=…` devolvió **39
resultados** de duckduckgo y otros. Es la confirmación medida de que el modo es keyless de
fábrica — no una lectura del código.

### La receta tiene un orden que no es decorativo

`setup.py` de SearXNG importa `searx/__init__.py`, que importa `msgspec`: **necesita sus
dependencias instaladas para poder declarar sus dependencias.** Sin pre-sembrarlas y sin
`--no-build-isolation`, pip muere con `ModuleNotFoundError: msgspec` en «Getting
requirements to build editable». Es exactamente lo que hace `Dockerfile:60-62` de upstream,
y está replicado en el script.

### ⚠️ Lo que SIGUE abierto: el venv **no es relocatable**

Medido: `bin/python3` sale symlink al Python del host, `pyvenv.cfg` apunta a su `home`, y
los shebangs de `bin/*` llevan la ruta absoluta del árbol de build. El script ya fuerza
`--copies` para el primer problema, pero **los otros dos siguen**: copiar este directorio
adentro de una `.app` produce un venv que no arranca en la máquina del usuario.

Es la pieza que falta para el camino (2) **distribuido**. En esta máquina el camino (2)
funciona entero; para el `.app` hay que resolver que el venv apunte a un Python que viaje.
Hasta entonces, una instalación distribuida tiene el camino (1) `ALEPH_SEARXNG_URL` y, si
no, el fallo visible del camino (3).
