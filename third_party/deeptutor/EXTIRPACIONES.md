# EXTIRPACIONES — DeepTutor dentro de Aleph

**Base:** `HKUDS/DeepTutor@456f9c2` · **Mapa:** `~/Desktop/FASE6-EDUCACION-ESTUDIO.md`.

Este registro se actualiza en cada corte. Gobiernan Ley 0 (cerebro único), 2.bis
(identidad/infraestructura propia fuera), 2.ter (sin catálogo/fuente duplicada) y 3.8.

## Cortes realizados

| Corte | Prueba física | Razón |
|---|---|---|
| Partners | fuera `deeptutor/partners`, `services/partners`, router y subagente | canales, identidad y egress ajenos |
| OAuth Codex | fuera `services/codex_auth`, adaptador, router y dependencia | segundo camino de modelo/identidad |
| CLI-Anything | fuera `services/cli_apps`, router, catálogo activo y tool view | es opcional: el tutor y su prueba siguen vivos sin hub ni instalación de CLIs |
| Multiusuario / auth / PocketBase | fuera `multi_user`, `auth.py`, cliente/store PocketBase, los compose/scripts de sidecar y montaje API; settings ya no exporta `POCKETBASE_*` | identidad, roles, secretos y tenant propios |
| CORS permisivo | `api/main.py` lista sólo orígenes explícitos de loopback/configuración | `https?://.*` y comodines no se exponen |
| Marca y proveedores | registro de proveedor reducido a `custom`; metadata y cabecera visibles dicen `Aleph Educación` | no hay preset, OAuth ni adaptador de proveedor ajeno |
| PyMuPDF / PyMuPDF4LLM | dependencia y engine removidos; `pypdfium2>=5.12.1` en core/CLI | AGPL/comercial fuera; se conserva extracción/rasterización |

Los cinco directorios de corte principales sumaban **21.304 líneas Python** en el clon
intacto antes de operar. El resto son costuras, routers, dependencias y tests asociados.
La copia de origen intacta sigue en `~/Desktop/oss-estudio/deeptutor/`; los órganos
separados durante esta operación se guardaron recuperablemente bajo
`/tmp/gate4-educacion-extirpated/`.

## Costura y 2.ter

`deeptutor/services/provider_registry.py` sólo declara `custom`, con backend
OpenAI-compatible. `ChatAgent.generate()` propaga su `binding` hasta
`BaseAgent.call_llm()`; no puede caer a un preset upstream. El testigo
`qa/verify_deeptutor_tutoring_bridge.py` levanta un fixture HTTP determinista (sin
inferencia local), ejecuta una tutoría y escribe
`reports/gate4-educacion/tutoria-testigo.json`.

`runtime/providers/view.py` devuelve una vista de herramientas vacía: no hay catálogo
MCP/CLI-Anything que montar. El chequeo estructural `qa/verify_deeptutor_extirpations.py`
afirma tanto esa ausencia como que un catálogo `binding: custom` resuelve a `custom`.

## Vara de PDF acordada

`pypdfium2` cubre los dos usos reales de PyMuPDF encontrados: texto por página para
adjuntos/KB y rasterización de página. PyMuPDF4LLM aportaba otra capacidad: conversión
PDF/e-book a Markdown con extracción de imágenes. Se quita, no se sustituye por una
aproximación ni por AGPL. La vara debe probar texto, número de páginas y bitmap no vacío
con una muestra PDF; no puede afirmar Markdown/imágenes porque esa capacidad deja de
formar parte de la importación.

La vara ejecutada es `qa/verify_deeptutor_pdf.py`: genera un PDF de una página, confirma
que `document_extractor.extract_text_from_bytes()` recupera el texto y que
`pypdfium2.PdfDocument(...)[0].render()` produce un bitmap con dimensiones positivas.

## §2 · Piel y superficie alcanzable (Gate 4 · F6 · Educación, 2026-08-10)

Segunda tanda de cortes, esta vez sobre **lo que el usuario ve**. El criterio de
admisión fue la **alcanzabilidad**: una superficie sólo se corta si existe un camino
real hasta ella (entrada de navegación, o URL que `proxy.ts` deja pasar). Todo lo que
la verificación adversarial declaró inalcanzable quedó intacto y está listado abajo.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1 | La pestaña «Partners & Agents» con seis CLIs ajenos | `web/lib/settings-nav.ts` (array `AGENT_CHILDREN`, su entrada en `SETTINGS_CATEGORIES`, sus 6 filas de `STORAGE_PATHS`, el import de `@/components/agents/agent-icons` y el icono `Bot`) · `web/app/(utility)/settings/agents/` (7 `page.tsx`, dir borrado) | Seis fichas con el logo de Claude Code, Codex, Gemini CLI, Kimi CLI, MiMo y OpenCode dentro de Ajustes. Ley 12: el selector no ofrece cerebros ajenos, y la marca de un tercero no vive en la casa. |
| 2 | La paleta de Tailwind en las fichas de Ajustes | `web/lib/settings-nav.ts` (10 campos `tile:`) | Cada ficha del hub pintaba un color distinto —violeta, esmeralda, ámbar, rosa, fucsia, índigo, naranja, lima, teal— que no es la paleta de la casa. Colapsados a un único `bg-[var(--accent)]/10 text-[var(--accent)]`. |
| 3 | La tienda «EduHub» | `web/components/space/EduHubImportModal.tsx` (borrado, 583 líneas) · `web/components/space/SkillsSection.tsx` (el botón «Import from EduHub», el estado `importOpen`, el render condicional del modal y los dos imports que quedaban colgando) · la clave `Import from EduHub` en los dos locales | Un mercado de skills de otra casa, alcanzable desde «Learning Space» en la nav lateral. |
| 4 | Las rutas de identidad | `web/app/(auth)/` (login · register · layout) · `web/app/(admin)/` (admin/users · layout) · `web/app/(utility)/profile/` | Ley 2.bis: Aleph es mono-usuario local; cuentas, logins, registros, perfiles y admin no existen. `proxy.ts:62` deja pasar cualquier ruta con `AUTH_ENABLED` apagado, así que eran alcanzables escribiendo la URL. **Ruta muerta, módulo vivo**: `lib/auth.ts`, `hooks/useAuthStatus.ts` y `components/auth/*` siguen porque los usan superficies que quedan (`SettingsSectionGrid`, las dos sidebars, `CliAppsSection`, `McpStoreSection`, el gate de 401 de `lib/api.ts`). |
| 5 | La marca del proyecto de origen en pantalla | `web/locales/en/app.json` y `web/locales/zh/app.json` (40 VALORES en cada uno) · `web/components/memory/MemoryHub.tsx:101` | «DeepTutor» → «Aleph Educación» donde nombra al producto, → «the tutor» / «导师» donde es el sujeto de la frase (Ley 11: la jerga del oficio se queda, la marca se va). Sólo se movieron VALORES; las 33 claves que aún dicen «DeepTutor» son la llave de búsqueda de los `t()` del árbol y moverlas dejaría la pantalla en blanco. La única clave que sí se movió es la de `MemoryHub`, en los dos locales y en el `.tsx`, las tres a la vez. |
| 6 | Dos temas sin lado de la línea claro/oscuro | `web/app/(utility)/settings/appearance/page.tsx` | Fuera Cream (id `light`) y Glass. Quedan Default (`snow`) y Dark, los dos únicos que `aleph_scheme` sabe direccionar. La copia debajo de la grilla describía los cuatro: se reescribió para no mentir. |
| 7 | El logotipo del proyecto de origen en la pestaña | `web/public/favicon-16x16.png` · `favicon-32x32.png` · `apple-touch-icon.png` | Los tres son la misma marca «Ai» sobre libro y mano del proyecto de origen. Se miraron antes de borrarlos. El bloque `icons:{}` de `app/layout.tsx` lo saca la sesión que lleva ese archivo. |

**Medición al cerrar:** `npx tsc --noEmit` en `web/` → **0 errores de código fuente**.
Los 26 que salen son de `.next/types/validator.ts` y `.next-deeptutor/types/validator.ts`,
validadores de ruta GENERADOS por builds viejos que todavía listan las rutas borradas; se
regeneran solos. `scripts/i18n_parity.mjs` → `[i18n:parity] OK` (2.929 claves, paridad
en/zh exacta), y los dos JSON cargan con `json.load`.

### Lo que NO se cortó, y por qué

Una verificación adversarial refutó siete hallazgos de la auditoría por
**inalcanzabilidad**: el código existe, pero nadie lo renderiza porque la cadena de datos
no llega o el endpoint no está montado. No se tocó ninguno.

- `web/components/settings/ServiceConfigEditor.tsx` (la consola BYOK de siete servicios
  con Base URL y API key) y `web/components/settings/CodexOAuthCard.tsx` (el OAuth de
  ChatGPT/Codex): **`GET /api/v1/settings` no está montado**. `deeptutor/api/main.py` sólo
  registra `chat` y `unified_ws`; el router `deeptutor/api/routers/settings.py` no se
  incluye, y de hecho ya no importaría — su línea 22 pide `deeptutor.multi_user.context`,
  la 23 `deeptutor.multi_user.model_access` y la 24 `deeptutor.services.codex_auth`, y los
  tres módulos se fueron en la primera tanda. Es la prueba física de que la consola está
  muerta desde el backend.
- `web/components/chat/home/ModelSelector.tsx`, `web/app/(workspace)/co-writer/sampleTemplate.ts`
  y el chip «Pro Vide Writing ↗» de `co-writer/[docId]/page.tsx`: misma cadena muerta.
- `web/app/(utility)/settings/network/`: refutado.
- `web/.next-deeptutor/` (106 MB de un build viejo): fuera de criterio para esta fase.

### Deudas anotadas, no ejecutadas

- `web/components/settings/SubagentSettingsEditor.tsx` (750 líneas) queda sin ninguna ruta
  que lo monte: era el editor de las seis fichas de CLIs. Nadie lo importa ya.
- `web/lib/admin-users.ts` queda sin más consumidor que su propio test
  (`tests/admin-users-filter.test.ts`): lo usaba la página de admin borrada.
- `web/lib/skills-api.ts` conserva el cliente HTTP del hub (`listHubSkills`, «view on
  EduHub») sin UI que lo llame. Es capa de datos, no superficie.
- `web/components/auth/LogoutButton.tsx:22` hace `router.replace("/login")`, y
  `lib/api.ts:91` y `lib/session-api.ts:122` mandan a `/login?next=…` ante un 401. Los tres
  caminos están detrás de `runtimeAuthEnabled` / `AUTH_ENABLED`, apagados en Aleph, así que
  hoy no se alcanzan; si alguna vez se prenden, apuntan a una ruta que ya no existe.
- `web/public/logo.png`, `logo_black.png`, `logo-ver2.png` y `banner.png` siguen siendo
  marca del proyecto de origen. `logo-ver2.png` sólo lo referencia `sampleTemplate.ts`, que
  está en la lista de refutados.
- `web/lib/theme-utils.ts` cicla por los cuatro temas viejos (`snow · light · dark · glass`),
  pero **nadie lo importa**: es código muerto, no un camino a Cream/Glass.
