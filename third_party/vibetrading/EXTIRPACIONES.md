# EXTIRPACIONES — qué se le sacó a Vibe-Trading, corte por corte

Base: `281c877` importado byte a byte (2.185 archivos, sha256 idénticos — ver
[`IMPORT.md`](IMPORT.md)). Todo lo de acá es diff **contra ese árbol**.

Las dos cirugías que la ley permite (`third_party/README.md` §6): **amputar la superficie de
producto independiente** y **teñir la piel**. El corazón técnico del oficio —tools, fuentes,
factores, skills, backtest, la máquina de mandato— **no se tocó**.

---

## 0. La cuenta

| Zona | Archivos | Líneas |
|---|---|---|
| Los 16 adaptadores de mensajería + `channelsui` | 34 | 19.223 |
| Tests de lo amputado | 27 | 4.596 |
| QVeris (tool, rutas, loader, skill, panel) | 11 | 3.212 |
| El puente a OpenBB Workspace (+ sus tests) | 13 | 1.821 |
| La wiki | 30 | 4.558 |
| Docs de producto (5 READMEs, CHANGELOG, CONTRIBUTING, CoC, SECURITY, guía) | 10 | 7.804 |
| CI / Docker / devcontainer | 13 | 921 |
| resto (`update`, iconos, assets) | 8 | 2.070 |
| **Borrado** | **136** | **44.205** |
| **Editado dentro de archivos que sobreviven** | **25** | **−762 netas** |

**El commit de extirpación: 136 archivos borrados, 25 modificados, −44.205 / +577 líneas.**

> **Corrección de una cuenta propia.** Un primer conteo dijo «406 archivos, 206.043 líneas».
> Estaba mal por dos motivos y conviene dejarlo escrito: (1) `wc -l` sobre `.mp4` y `.png`
> cuenta bytes de salto de línea, no líneas — 164.823 de esas «líneas» eran binarios; (2)
> comparar `git ls-tree` contra `find` marcó como borrados **270 archivos con nombre en chino**
> (las referencias de las skills `chanlun` y `eastmoney`) sólo porque git los escapa y `find`
> no. **Están todos vivos.** El número bueno es el de `git diff --numstat`, que es el que está
> arriba.

## La vara: el delta es EXACTAMENTE lo amputado

Suite completo (`-m "not integration"`, 9.999 tests recolectados), mismo venv, mismo `HOME`
falso, sobre el mismo commit:

| | pasaron | saltadas | rojas |
|---|---|---|---|
| **Testigo (clon intacto)** | **9.907** | 82 | 0 |
| **Después de extirpar** | **9.665** | 76 | **0** |
| delta | −242 | −6 | — |

Y los −242 se explican **completos**, sin resto:

| Origen del delta | tests |
|---|---|
| 27 archivos de test borrados enteros (canales, QVeris, OpenBB, update, readme-counts, guide-paths) | **205** pasaron + 6 saltadas |
| `test_tools_type_value_safety.py` — el bloque QVeris | 21 |
| `test_url_target_security.py` — la mitad de QQ (el guard SSRF **se conserva**) | 9 |
| `test_agent_config.py` — los 3 tests de config de canales | 3 |
| `test_split_message_nonpositive.py` — los 2 de Signal | 2 |
| `test_metrics.py` — el resampling de `qveris` | 1 |
| `test_state_migration_wiring.py` — el orden del lifespan con canales | 1 |
| **suma** | **242** ✅ |

**Cero regresión:** ninguna roja, y ninguna baja sin nombre.

---

## 1. Los 16 adaptadores de mensajería (~19.700 líneas)

**Por qué:** Aleph es local y mono-usuario. Un bot de Telegram que contesta por vos es
superficie de producto independiente, no oficio financiero.

Borrado en `agent/src/`:

```
channels/{dingtalk,discord,email,feishu,matrix,mochat,msteams,napcat,qq,
          signal,slack,telegram,websocket,wecom,weixin,whatsapp}.py
channels/{base,manager,runtime,registry,config}.py
channels/bus/  channels/pairing/
channelsui/                       (8 archivos, 459 líneas)
api/channels_routes.py
```

Cableado cortado:

| Dónde | Qué |
|---|---|
| `agent/api_server.py` | el import de los 4 nombres de canal desde `api.state` · el import de `_start/_stop_channel_runtime` · el auto-start en el preflight · el `_stop_channel_runtime` del shutdown · `register_channels_routes(app)` · el re-export de `ChannelPairingCommandRequest` |
| `agent/src/api/state.py` | `_get_channel_runtime()` entero y sus 3 singletons (−43 líneas) |
| `agent/cli/_legacy.py` | los 9 comandos `cmd_channels_*` + su parser + su dispatch (−192 líneas) |
| `frontend/src/pages/Settings.tsx` | la sección de canales entera, sus 2 handlers, sus 3 estados y su fila del `Promise.allSettled` (−158 líneas con QVeris) |
| `frontend/src/lib/api.ts` | los 4 métodos `/channels/*` y sus 5 interfaces (−42 líneas) |

### ⚠ Lo que NO se borró, y por qué

**`agent/src/channels/utils.py` (179 líneas) SOBREVIVE.** No es descuido:

```
src/security/network.py:8          from src.channels.utils import validate_resolved_url, validate_url_target
src/security/workspace_policy.py:8 from src.channels.utils import is_path_within as _is_path_within
```

Ahí viven **el guard anti-SSRF** (que bloquea loopback, link-local, privadas y el rango CGNAT
`100.64.0.0/10` que `ipaddress.is_private` deja pasar) y **la contención de rutas**. Moverlo
sería refactor, y la importación no refactoriza (Ley 5). Su `__init__.py` se reescribió a 18
líneas que no re-exportan nada y explican la situación.

Sus 20 tests (`test_url_target_security.py`, mitad del guard central) **siguen verdes**.

### Residuo declarado

`agent/src/config/schema.py:429` sigue declarando `class ChannelsConfig` y dos campos
`channels:` en el `AgentConfig`. **Ya no los lee nadie** en camino de producción. Se deja
porque sacarlos es refactor del schema de config; queda como **deuda de limpieza** para el
fork, igual que las ramas muertas `providerID === "synsci"` de OpenScience.

---

## 2. QVeris — el marketplace de pago con referido embebido (~3.200 líneas)

**Por qué:** no es un problema de licencia sino de **qué se hereda**. El link de referido
vivía en **código ejecutable**, no en el README:

```python
# agent/src/tools/qveris_tool.py:21-23  (borrado)
SIGNUP_URL   = "https://qveris.ai/?ref=Vyjjo5G_1cAHJA"
INVITE_CODE  = "Vyjjo5G_1cAHJA"
DEFAULT_BASE_URL = "https://qveris.ai/api/v1"
```

Es una constante viva que la tool le devolvía al usuario cuando le faltaba la key. El proyecto
lo declara abiertamente en su README —es honesto, no oculto— pero **Aleph no puede
redistribuir el código de invitación de HKUDS**.

Borrado: `src/tools/qveris_tool.py` · `src/api/qveris_routes.py` ·
`backtest/loaders/qveris_loader.py` · `src/skills/qveris/` ·
`frontend/src/components/settings/QVerisSettings.tsx` · 5 archivos de test.

**El corte fue por la costura que el propio repo dejó:** 152 líneas marcadas
`# QVERIS-INTEGRATION`, una por una. Se barrieron por marcador en `cli/main.py` (−30) y
`cli/_legacy.py` (−114), **salvo dos casos donde borrar la línea rompía**:

1. `backtest/loaders/registry.py:124` —
   `_NO_NETWORK_FALLBACK_SOURCES = frozenset({"local", "qveris"})`. La línea **define una
   constante**: se **editó** a `frozenset({"local"})`, no se borró.
2. `cli/_legacy.py:3145` — `def cmd_qveris_mode(` tenía la **firma multilínea con sólo las
   continuaciones marcadas**. El barrido dejó un `def` huérfano y el módulo dejó de compilar.
   Se sacó la función entera a mano. *(Lo destapó `py_compile`, no la lectura.)*

En `mcp_server.py` se sacaron las 3 tools (`qveris_search` / `qveris_inspect` /
`qveris_execute`) y su mapa key-gated: **−107 líneas**.

> **Trampa medida:** el primer corte usó «desde el `def` hasta el próximo `@mcp.tool`» y se
> llevó **296 líneas** — porque entre `qveris_execute` y la próxima tool vive el bloque de
> **tools espejadas** (`get_institutional_holdings`, `etf_holdings`, `prediction_market`,
> `research_papers`, registradas por clase y no por decorador). La superficie MCP cayó a **57**
> en vez de 61. Se restauró `mcp_server.py` del origen y se rehizo el corte por el `return` real
> de la función. **La medición contra el binario lo destapó; leer el diff no lo habría hecho.**

**Superficie MCP: 64 → 61 tools, medidas contra el servidor corriendo.** Las 4 espejadas están
de vuelta. De las 61, **59 corren sin ninguna llave** (quedan key-gated `get_macro_series`/FRED
e `iwencai_search`).

**Fuentes de mercado: 24 → 23.** `qveris` era la única de pago con créditos.

---

## 3. El puente a OpenBB Workspace (1.054 líneas)

`agent/src/openbb_bridge/` entero + las 3 líneas de `api_server.py:291-293` marcadas
`# OPENBB-WORKSPACE-INTEGRATION` + sus 6 archivos de test.

**Por qué:** registraba `/agents.json` y `/v1/query` para que **otro producto** (OpenBB
Workspace, `pro.openbb.co`) consumiera este agente como custom agent. Es integración con
infraestructura de un tercero, no oficio.

---

## 4. El comando `update` (226 líneas)

`agent/cli/commands/update.py` + su dispatch + su test.

**Por qué:** iba a `https://pypi.org/pypi/vibe-trading-ai/json` a buscar versión nueva. El ciclo
de actualización de esta casa es el del pack (Gate 4 · F5).
*(Se verificó que `fetch_latest_version` no lo llamaba nadie más: no había chequeo automático al
arrancar.)*

---

## 5. La marca y la superficie de producto independiente (ley 3.8)

| Borrado | Peso |
|---|---|
| `README_ar.md` · `README_ja.md` · `README_ko.md` · `README_zh.md` | 860 KB |
| `README.md` → reemplazado por 15 líneas que apuntan a `IMPORT.md` / `EXTIRPACIONES.md` | 192 KB → 1 KB |
| `wiki/` (30 archivos, Cloudflare Pages de `vibetrading.wiki`) | 5,9 MB |
| `assets/` (2 mp4 de demo + capturas de marketing) | 35 MB |
| `.github/` (issue templates, workflows de wiki y CI) · `.devcontainer/` | 677 KB |
| `CHANGELOG.md` · `CONTRIBUTING.md` · `CODE_OF_CONDUCT.md` · `SECURITY.md` · `AGENT_CONTRIBUTOR_GUIDE.md` | 54 KB |
| `Dockerfile` · `docker-compose.yml` · `.dockerignore` | 9 KB |

**Árbol: 63 MB → 46 MB.**

Y la marca en la cara, que estaba **concentrada en 3 lugares** (por eso fue barata):

| Archivo:línea | Antes | Ahora |
|---|---|---|
| `frontend/index.html:7` | `<title>Vibe-Trading — vibe trading with your professional financial agent team</title>` | `<title>Finanzas — Aleph</title>` |
| `frontend/index.html:142` | meta description con el claim de producto | «Finanzas — el workspace de investigación de mercados de Aleph.» |
| `Layout.tsx:107` | `'Vibe-Trading sidebar'` | `'Barra lateral de Finanzas'` |
| `Layout.tsx:117` | `aria-label="Vibe-Trading"` | `aria-label="Finanzas"` |
| `Layout.tsx:122` | `<span>Vibe-Trading</span>` | `<span>Finanzas</span>` |

**Nota sobre `SECURITY.md`:** traía el aviso de impostores (el token falso y el Discord con
phishing de wallet) — una virtud del proyecto, señalada en el estudio §3.4. Muere igual: con la
marca extirpada, un usuario de Aleph no va a buscar «el Discord de Vibe-Trading», así que el
aviso queda sin destinatario. Lo técnico que traía (la política del sandbox de backtest) vive
igual en los docstrings del código.

**Lo que NO se tocó:** `LICENSE` y `NOTICE` del origen, intactos y obligatorios
(`third_party/README.md` §3). El `NOTICE` **tiene que viajar al `.app`**: es condición del
Apache-2.0 de Qlib y de la OFL de las fuentes.

### Residuo declarado

Los 5 archivos de `frontend/src/i18n/locales/*.json` conservan menciones de marca en cadenas
traducidas (`"Vibe-Trading sidebar"`, y textos de la sección de canales que ya no se renderiza).
No se tocaron en esta etapa: son 5 idiomas × N claves y el barrido de i18n es trabajo de la
**tanda de CONVERGENCIA** (estandarización de piel). Ninguna de esas claves llega hoy a la
pantalla por los caminos que sobreviven.

---

## 6. Docs del oficio actualizadas (no amputadas — corregidas)

La ley 0 exige que el oficio quede **coherente**, no sólo vivo:

| Archivo | Cambio |
|---|---|
| `agent/SKILL.md` | `Available MCP Tools (60)` → `(57)` · 4 contadores `89 skills` → `88` · 2 contadores `24 sources` → `23` · 5 filas de qveris |
| `agent/src/skills/data-routing/SKILL.md` | la fila de `qveris` de la tabla de fuentes |

---

## 7. La costura al cerebro — pendiente de Etapa 2

Esta etapa **no** cableó el cerebro. Lo que la Etapa 2 va a hacer, y que el estudio ya midió:
agregar una entrada `aleph` a `agent/src/providers/llm_providers.json` (archivo de **datos**) y
las 4 variables del `.env`. **Cero corte de código en `llm.py`.**

---

## 8. Lo que explícitamente NO se tocó

- **`agent/src/live/` entero** (~7.600 líneas): mandato, gates, kill switch, contador diario,
  auditoría, runner, flatten. **Decisión del dueño: Opción B, va completo.** Ver
  [`MAPA-DEL-DINERO.md`](MAPA-DEL-DINERO.md).
- **Los 13 conectores de broker y sus 43 perfiles**, incluidos los 8 con orden real.
- **Las 89 skills** (menos la de qveris → 88), los **477 archivos de factores**, los 5 zoos.
- **Los 23 loaders** de mercado y su cadena de ruteo por riesgo de bloqueo de IP.
- **El gate de grounding e identidad** (`src/agent/grounding.py`) — el que se niega a cotizar un
  símbolo que no resolvió antes. Es un tesoro del oficio.
- **`quantlib`**, el motor de backtest, el swarm, el Shadow Account, el Alpha Zoo.
- **`LICENSE`** y **`NOTICE`** del origen.

## Piel de Aleph — convergencia inline (Gate 4 · F6, 2026-08-10)

La ley 6 permite dos cirugías sobre una pieza importada: amputarle el agente y **teñirle la
piel**. Ésta es la segunda. El test es la ley 3: si el usuario adivina de qué repo vino, se
estandarizó mal.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1 | La letra de la casa, vendorizada | `frontend/index.html` (los 8 `@font-face` de Inter y los 6 de JetBrains Mono salen; entran los de Outfit con sus `unicode-range`) · `frontend/public/fonts/outfit-*.woff2` · `tailwind.config.ts` (`sans`, `serif` y `mono`) · los 14 woff2 ajenos borrados | Inter llevaba toda la letra y el titular de bienvenida iba en SERIF de 34px — y en este sistema la serif es gesto de MARCA, que Aleph reserva para su wordmark. La mono pasa al stack de sistema, igual que en la casa. |
| 2 | El titular de bienvenida | `frontend/src/components/chat/WelcomeScreen.tsx:251` | Salía en `font-serif`; ahora en la sans de la casa, con el mismo peso y tracking que el titular de Aleph. |
| 3 | El acento | `frontend/src/index.css` (`:root` y `.dark`) | Era el naranja de marca del proyecto de origen y pintaba el menú activo, el botón de enviar y el «Guardar». Es el violeta de `aleph-tokens.css` — #5A4FD6 en claro, #8D8BEE en oscuro, con la tinta de encima dada vuelta en oscuro porque ahí el acento es claro. |
| 4 | El esquema de la casa cruza el borde | `frontend/public/theme-boot.js` · `frontend/src/aleph.ts` (nuevo) | La mesa elegía tema por el sistema operativo y podía abrir clara dentro de una casa oscura. Ahora lee `aleph_scheme` y lo persiste en la clave que ya usaba. `aleph.ts` captura los parámetros UNA vez al cargar, porque el router pierde el `search` en cuanto navega. |
| 5 | El interruptor de tema, adentro | `frontend/src/components/layout/Layout.tsx` (las dos formas: colapsada y expandida) | Dos interruptores para lo mismo son dos verdades. Adentro de Aleph lo gobierna la casa; corriendo suelto, el stack lo conserva. |
| 6 | El sello de versión y su «About» | `frontend/src/components/layout/Layout.tsx` | Marketing de otro producto adentro de la casa. La versión que le importa al usuario es la de Aleph. |
| 7 | El proveedor anunciado en la barra del turno | `frontend/src/components/chat/ModelRuntimeBar.tsx` | Decía «OpenAI · Cerebro de Aleph». Ley 12: el cerebro es uno solo y no tiene proveedor que mostrar. |
| 8 | La consola de conexión | `frontend/src/pages/Settings.tsx` (la `<section>` «Connection» entera, con `applyProviderDefaults`, `onProviderChange`, `refreshModels`, `keyStatus`, `apiKeyDisabled` y los estados de credencial) | 23 proveedores en un desplegable, Base URL editable y campo de API key. Un usuario que apunte la mesa a otro proveedor rompe el circuito certificado —selector, `model_final` honesto, S8 y ledger— sin enterarse. El `submit` conserva la forma y manda `api_key: undefined`. |
| 9 | «Local API access» | `frontend/src/pages/Settings.tsx` | Un campo para fabricarse una clave de acceso a la API local del stack: identidad del proyecto heredado (ley 2.bis). El módulo `apiAuth` sigue vivo; muere la pantalla. |
| 10 | La marca en el copy vivo | `frontend/src/i18n/locales/{en,ja,ko,zh-CN,ar}.json` | «Vibe-Trading sidebar» y la descripción de canales. Los comandos literales del CLI NO se tocaron: eso es el oficio (ley 11). |
| 11 | La ruta del proyecto de origen en un error | `agent/src/api/helpers.py:186` | Devolvía «~/.vibe-trading/.env» a la pantalla; adentro de Aleph el archivo vive en el dir de datos del dueño. Ahora devuelve sólo el nombre, que es lo único cierto en las dos formas de correrlo. |
| 12 | El ícono y el wordmark | `frontend/public/favicon.svg` (la placa naranja de marca fuera; las tres velas del oficio quedan, en el campo y el acento de Aleph) · `frontend/public/logo.svg` (borrado: wordmark literal del proyecto de origen, sin una sola referencia en el árbol) | El favicon se ve en la pestaña: la superficie más barata para delatar de qué repo vino. |

**Lo que NO se tocó:** el oficio entero — sus 64 tools, sus fuentes de mercado, sus gráficos,
su cartera, la máquina de mandato con sus negativas, y su jerga en inglés (ticker, spread,
P/E). Tampoco los comandos de su CLI, que son parte del oficio y no marca.

**Nota de la auditoría:** el vertical NO tiene locale español y su selector de idioma propio
tampoco lo ofrece — queda anotado para la pantalla unificada de la convergencia, no se
resuelve acá.

---

## El español, que no es piel sino idioma (Convergencia · Superficie 5, 2026-08-12)

Ni amputación ni piel: es la **tercera clase de edición** que este árbol recibió, y ya tenía
precedente propio antes de esta. El stack nació bilingüe —inglés y chino— y Aleph corre en
español; donde ese supuesto está horneado en un regex, la función no falla: **devuelve de
menos, en silencio**. Las dos veces se arregló igual: editando el archivo, **siguiendo la
forma que el código ya tenía** (nunca una más laxa), con la medición escrita al lado.

| # | Qué | Dónde | Antes → después, medido |
|---|---|---|---|
| 1 | **El gate anti-alucinación** no examinaba una afirmación de precio en español, así que el número inventado no se comparaba con nada | `agent/src/agent/grounding.py:157` | ver [`HALLAZGO-GATE-IDIOMA.md`](HALLAZGO-GATE-IDIOMA.md) — Gate 4 · F6 |
| 2 | **El tokenizador de la búsqueda FTS5** partía las palabras con tilde o eñe: `[a-zA-Z0-9_]{2,}` | `agent/src/session/search.py:_sanitize_fts_query` | `'año fiscal'` → `"fiscal"` · `'pérdida máxima'` → `"rdida" OR "xima"` · `'sesión'` → `"sesi"`. Contra un FTS5 real: **1/6 → 6/6**, con **0 regresiones** en 10 casos de inglés, chino, japonés y basura |

**Del #2, tres cosas que conviene no perder:**

- **No es culpa de FTS5, y por eso no se cambia de motor.** Con `unicode61` —el tokenizador
  por defecto— las mismas seis consultas dan 6 de 6. El texto se rompía **antes** de que FTS5
  lo viera.
- **La exclusión de kana es load-bearing.** El primer intento usó `\w{2,}` a secas y **rompió
  el japonés**: `日本の株式` daba `"日" OR "本" OR "の株式"` en vez de los cuatro tokens de
  antes, porque `の` es hiragana y no entra en los rangos CJK. Lo destapó medir el caso que el
  arreglo prometía no tocar.
- **No-regresión:** `tests/test_session_search.py` → **20 passed**.

> **Corrección a la §8 de este documento.** «Lo que explícitamente NO se tocó» todavía lista
> `src/agent/grounding.py`, y ese archivo **sí** se editó en Gate 4 · F6 (fila 1 de arriba).
> La lista se escribió antes de esa obra y no se actualizó. Queda corregido acá en vez de
> reescribir aquella sección, para que la historia siga siendo legible en orden.
