# EXTIRPACIONES — Local Deep Research dentro de Aleph

Registro de lo que se le cortó a la pieza importada: **qué · dónde · por qué**. Gobierna
`third_party/README.md` · **Ley 6** («sólo se corta el agente y se tiñe la piel») y
**Ley 5** («cero refactor inicial»), más la **Ley 2.bis** (identidad e infraestructura).

**Base:** `LearningCircuit/local-deep-research@a734d529`, 3.303 archivos importados byte a
byte idénticos al origen (sha256 archivo por archivo, cero diferencias — ver `IMPORT.md`).
**Mapa que ordena estos cortes:** `~/Desktop/T7-SALA-ESTUDIO.md` §3.
**Cómo se eligió el corte:** no a ojo. Ver §4 — se calculó.

---

## 0 · Lo que NO hubo que cortar, y hay que decirlo

| Qué | Medición |
|---|---|
| **Telemetría** | **No tiene.** Medido sobre `src/` en el árbol de hoy: `grep -rliE "posthog\|mixpanel\|sentry_sdk\|amplitude\|segment\|gtag"` da 8 archivos y **los 21 matches son la palabra `segment`** — ninguno es un SDK de telemetría. *(La versión anterior de esta fila decía «un archivo, `web/static/js/pages/note-detail.js`, falso positivo de `existingTags`». Era cierto **antes** del corte y hoy es inverificable: ese archivo lo borró §1.8 de este mismo documento. La conclusión no cambió; la evidencia sí, y por eso se reescribió.)* |
| **Cuentas remotas del fabricante** | **No tiene.** Sus dominios salientes son fuentes de datos (arXiv, PubMed/NCBI, OpenAlex, DOAJ, EuropePMC, Crossref, PubChem, Gutenberg, Wayback, bioRxiv, ADS) y proveedores de modelo. Ningún backend propio. |
| **Su política de egreso** | **Se conserva entera** (`src/local_deep_research/security/egress/`, **3.365 líneas**; el paquete `security/` completo son 10.520 — el número que este documento declaraba antes, atribuido por error al subpaquete). Es del oficio y es buena: decide a dónde puede salir el modelo y la búsqueda, con `PolicyDeniedError` tipado y auditoría. Aleph no tiene nada equivalente — anotada como candidata a CONVERGENCIA. |
| **Sus 32 motores de búsqueda** | **Se conservan enteros** (`web_search_engines/engines/`). Son el dominio (LEY 0). Censados en `platform/workspaces/sources.py`. |
| **Su servidor MCP de 8 tools** | **Se conserva entero** (`mcp/server.py`). No es la puerta de la Sala —es stdio y es ciego al progreso (`mcp/server.py:1053`, `:367-368`)— pero es una puerta legítima para que un agente lo use como tool. Censado. |

---

## 1 · La aplicación web Flask y su capa de cuentas — **38 módulos, 21.784 líneas**

**Por qué sale.** LDR publica dos superficies: una **aplicación** web con cuentas, login y
una base **SQLCipher por usuario donde la contraseña del usuario ES la llave de cifrado**
(`web/auth/password_utils.py:2-12`, que **sobrevive** y lo dice literal; el `web/auth/__init__.py:2` que esta línea citaba antes lo borró §1.1 de este mismo documento, así que se cambió por evidencia verificable en el árbol de hoy), y una **librería**. Aleph es
mono-usuario local: la identidad es una, la instalación (Ley 2.bis). Una cuenta adentro de
la cuenta, jamás. Y la cara del deep research ya existe: es la Sala.

**Cómo se apaga la identidad, primero por su propia costura.** La Ley 2.bis manda usar
**PRIMERO el flag nativo de no-auth si existe**. Existe, y es de primera clase:
`programmatic_mode=True` (`src/local_deep_research/api/research_functions.py:49`), que su
propio docstring define como «*disables database operations and metrics tracking*» (`:74`),
más el decorador `@no_db_settings` (`src/local_deep_research/utilities/db_utils.py:179-204`):
«*runs the wrapped function with the settings database completely disabled … Settings can
only be read from environment variables or the defaults file*». Aleph entra por ahí. Lo que
sigue es el corte de la superficie que ese camino ya no toca.

### 1.1 · La identidad (12 archivos)

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1.1 | El paquete de autenticación entero, menos dos módulos | `web/auth/__init__.py` · `routes.py` · `session_manager.py` · `session_cleanup.py` · `database_middleware.py` · `queue_middleware.py` · `queue_middleware_v2.py` · `cleanup_middleware.py` · `connection_cleanup.py` · `middleware_optimizer.py` (10 archivos) | Login, registro, sesiones, y el middleware que resuelve la contraseña del usuario para abrir su base cifrada. Es la capa de identidad local que la Ley 2.bis extirpa. |
| 1.2 | La app Flask y su fábrica | `web/app.py` · `web/app_factory.py` | Quien crea el servidor, registra los blueprints y monta la sesión. Sin esto no hay app: la librería queda. |
| 1.3 | Su superficie HTTP propia | `web/api.py` · `web/routes/` (11 archivos: `api_routes` · `research_routes` · `settings_routes` · `history_routes` · `metrics_routes` · `news_routes` · `notes_routes` · `unified_search_routes` · `context_overflow_api` · `route_registry` · `_search_constants`) | Los **177** `@login_required` viven acá (contados sobre los 12 archivos borrados en el estado de importación `00fa5ee8`; el «190» que decía antes no lo daba ninguna lectura). Es la aplicación, no el motor. |
| 1.4 | Blueprints Flask que viven FUERA de `web/` | `news/flask_api.py` · `news/web.py` · `news/core/storage_manager.py` · `followup_research/routes.py` · `research_scheduler/routes.py` | **El hallazgo que obligó a medir en vez de suponer:** la app de LDR no está confinada a `web/`. Sus blueprints están repartidos. Cortar «la carpeta web» habría dejado media aplicación viva. |
| 1.5 | Middleware y utilidades de ruta | `web/utils/route_decorators.py` · `web/utils/theme_helper.py` · `web/queue/__init__.py` · `web/queue/manager.py` · `web/database/benchmark_schema.py` | Plomería de la app amputada. |
| 1.6 | Los chequeos de arranque del servidor | `web/warning_checks/` (4 archivos: `__init__` · `backup` · `context` · `hardware`) | Avisos de la app web sobre su propio hosting (backup, VRAM, contexto). Sin app no hay a quién avisarle. |

### 1.2 · La cara (150 archivos, 3,8 MB)

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1.7 | Sus 46 plantillas | `web/templates/` | La UI del deep research **ya está construida: es la Sala + el canvas** (plan §6.f). Ley 3.8: el workspace se embebe, jamás se visita. |
| 1.8 | Sus 104 estáticos (2,8 MB de JS/CSS) | `web/static/` | Ídem. |

### 1.3 · Los entry points

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1.9 | El entry point `ldr-web` | `pyproject.toml` `[project.scripts]` | Apuntaba a `local_deep_research.web.app:main`, que ya no existe. **`ldr-mcp` se conserva.** Nota del propio repo en esas líneas: su entry point `ldr` ya venía roto desde el commit `c1f80e7a8`. |

---

## 2 · Lo que sobrevivió y NO debería — la deuda declarada

La Ley 2.bis lo prevé literalmente: «*si no hay flag, se neutraliza al mínimo … y queda
anotada la extirpación completa como deuda para cuando el fork lo amerite*». Acá el flag
existe y se usa (§1), pero la extirpación **no puede ser completa sin abrirle el cuerpo al
repo**, y eso sería refactor (Ley 5). Lo que queda, con nombre:

| Qué queda | Por qué no se pudo cortar | Riesgo real |
|---|---|---|
| `web/auth/decorators.py` y `web/auth/password_utils.py` | Los importan módulos de dominio que sobreviven (`research_library/routes/*.py`, `chat/routes.py`, `benchmarks/web_api/*`). Cortarlos obliga a editar esos archivos o sus `__init__.py` — refactor de código ajeno. | **Ninguno en ejecución**: `login_required` es un decorador que sólo corre dentro de un request de Flask, y **no hay app Flask** (§1.2). Es código inerte. |
| **Flask como sustrato** | Medido **antes** del corte: **58 de 590 archivos** importan `flask`/`werkzeug`; **después**: **31 de 552**, y **26 de esos 31 viven fuera de `web/`**. No están confinados a la app — están en `settings/manager.py`, `security/*` (5), `utilities/*` (3), `database/*` (3), `metrics/*` (2) y hasta en el núcleo de investigación (`advanced_search_system/parallel_search.py`). Usan `flask.g` / `has_app_context()` como **contexto ambiente**, no como servidor. | Ninguno: sin app, `has_app_context()` es `False` y esos caminos caen a su rama sin-contexto. Pero significa que **Flask sigue siendo una dependencia de runtime**. |
| Las rutas de dominio (`research_library/**/routes/`, `chat/routes.py`) | Las sostienen los `__init__.py` de sus propios paquetes. | Código muerto **por partida doble**: no hay quién las registre (su `app_factory` salió) y les falta su plantilla (§1.7). Declarado. |

**Deuda con nombre: `ldr-flask-es-sustrato-no-capa`.** Sacar Flask del todo exige un fork
real del motor, no una importación. No la paga esta fase.

---

## 3 · Adiciones de Aleph — lo que se le puso, no lo que se le sacó

**Ninguna dentro de `third_party/ldr/`.** El árbol importado no recibió una sola línea de
Aleph: la costura vive afuera, en `platform/sala/research/`. Es la forma más limpia de la
Ley 7 («si se tira, es una carpeta»): borrar `third_party/ldr/` no deja nada nuestro
enredado adentro.

Cómo se enchufa, sin tocarlo: `platform/sala/research/cerebro.py` construye un cliente
OpenAI-compatible contra el borde de dialecto y se lo pasa **por parámetro** —
`quick_summary(..., llms={"aleph": llm}, provider="aleph")` — que es la puerta que el propio
repo dejó abierta (`api/research_functions.py:44,90-95,102,141`), y que su PEP de egreso
**exime explícitamente** (`config/llm_config.py:167-171`).

---

## 3.bis · Lo que quedó APUNTANDO AL VACÍO, y por qué no se toca

Un corte deja referencias colgando en archivos que no son código Python. Ninguna de éstas
rompe nada de lo que Aleph corre —el pack importa la librería, no construye ni empaqueta
con las herramientas de ellos—, pero **quien pague la deuda de empaquetado se las va a
encontrar**, así que se declaran acá en vez de que las descubra.

| Dónde | Qué quedó apuntando al vacío | Qué pasa si alguien lo corre |
|---|---|---|
| `.github/workflows/release-gate.yml:465-474` | `targets = {"ldr-web", "ldr-mcp"}` + `assert not missing` | Falla con `missing console_scripts: {'ldr-web'}`. **Irónico y deliberado dejarlo:** `pyproject.toml:123-126` cita ESE workflow como el que atrapa entry points muertos, y es el argumento con el que §1.9 justifica el borrado. |
| `Dockerfile:390` | `CMD [ "ldr-web" ]` | Su contenedor arranca y muere. Aleph no usa ese Dockerfile: el pack levanta el proceso (`platform/sala/research/arranque.sh`). |
| `vite.config.js:6,22` | `root: 'src/local_deep_research/web/static'` y su entry `.../static/js/app.js` | `npm run build` aborta. Ese build producía la cara, que es justo lo que se extirpó (§1.8). |
| `MANIFEST.in:4-5` | `recursive-include …/web/templates *` y `…/web/static *` | Nada: el build backend es `pdm-backend` y no lee `MANIFEST.in`. Vive por el camino `pip install -e .` que `pyproject.toml:135-137` declara conservar. |
| `pyproject.toml:142` | `"local_deep_research.web" = ["templates/*", "static/*", "static/**/*"]` | Ídem: package-data de directorios que ya no existen. |
| `pyproject.toml:339,342,350,355` | Cuatro `per-file-ignores` de ruff sobre archivos borrados | Nada; configuración muerta. |

**Por qué no se arreglan:** son la infraestructura de distribución **de ellos**, y tocarla
sería refactor (Ley 5) sobre archivos que Aleph no ejecuta. La regla del repo es que lo
que se descarta se descarta como carpeta (Ley 7): si mañana esta pieza se va, estas
referencias se van con ella.

---

## 4 · Cómo se eligió el corte — se calculó, no se estimó

El corte no salió de leer nombres de carpeta. Se construyó el **grafo de imports** de los
590 módulos del paquete (AST, distinguiendo import de nivel superior de import perezoso) y
se calculó el **corte máximo seguro**:

1. **Semilla** = la aplicación Flask: todo bajo `web/` (menos el contrato que el núcleo
   necesita: `web/models`, `web/server_config`, `web/themes`) **más** todo módulo que
   importe `flask`/`werkzeug` y no esté en ese contrato — que es lo que destapó los
   blueprints de `news/`, `followup_research/` y `research_scheduler/` (§1.4).
2. **Cierre monótono**: si un módulo que sobrevive importa uno marcado para cortar, el
   objetivo se **rescata** (nunca al revés). El corte sólo se achica, así que termina.
3. **Verificación**: tras el corte, **aristas colgando = 0**. Ningún módulo superviviente
   importa un módulo borrado, ni al nivel superior ni perezosamente.

Resultado: **38 módulos, 21.784 líneas**, 26 rescatados (§2), cero aristas rotas.

El herramental de la medición vive en el scratchpad de la sesión
(`alcance_ldr.py`, `corte_ldr.py`) y el reporte de la obra lo cita.

---

## 5 · Lo que este corte NO midió

- **No se corrió nada.** Régimen de la fase: cero varas. El corte está verificado por
  análisis estático de imports, que es una prueba fuerte de que nada quedó colgando —
  pero no es lo mismo que haber importado el paquete. La confirmación de import queda
  para quien pague la deuda de empaquetado.
- **Su suite de tests quedó en el árbol y no colecciona. Entera.**

  Una revisión adversarial sobre esta misma rama corrigió lo que este documento decía
  antes —«`tests/web/` y `tests/ui_tests/` prueban la superficie amputada»—, que
  **minimizaba**. Lo medido, verificado de nuevo acá:

  `tests/conftest.py:23` hace `from local_deep_research.web.app_factory import create_app`
  **al nivel superior**, y pytest carga el `conftest` raíz para **toda** colección bajo
  `tests/`. Con `web/app_factory.py` extirpado (§1.2), `pytest third_party/ldr/tests/<lo
  que sea>` muere en colección — incluso un directorio sano como `tests/mcp`.

  Además, **129 archivos de test** importan directamente algún módulo borrado, repartidos
  así (medición propia, coincide con la del revisor): `tests/web/` 72 · `tests/news/` 17 ·
  `tests/security/` 10 · `tests/research_library/` 7 · `tests/auth_tests/` 5 ·
  `tests/connected/` 3 · `tests/research_scheduler/` 3 · `tests/infrastructure_tests/` 2 ·
  y el resto sueltos. **La mitad está fuera de los dos directorios que este documento
  nombraba.**

  **No se toca y no se corre.** La suite de un stack heredado no es vara de esta casa
  (regla sellada), y arreglarla sería reescribir 129 archivos ajenos. Pero la declaración
  ahora dice el tamaño real del hecho en vez de uno cómodo.
