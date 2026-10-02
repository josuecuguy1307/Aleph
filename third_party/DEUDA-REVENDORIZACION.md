# Deuda de re-vendorización

Cada archivo de un tercero que Aleph abrió, con su motivo. Es la contrapartida de la Ley 6.c:
abrir el cuerpo de una pieza se paga cuando esa pieza se vuelve a importar, y esta lista es lo
que hace ese pago posible en vez de sorpresivo.

**Cómo se lee:** si mañana se re-vendoriza un stack, lo que está acá es exactamente lo que hay
que volver a aplicar. Si una fila no se puede volver a aplicar sobre el árbol nuevo, esa fila
es un rediseño pendiente, no un parche.

## Fase 3 — la piel (por la costura, sin abrir el cuerpo)

| Stack | Archivo | Qué se le hizo | Al re-vendorizar |
|---|---|---|---|
| los 6 | `…/public/aleph-piel.{js,css}` | archivos NUESTROS, agregados | copiar de nuevo |
| los 6 | `…/index.html` (o `layout.tsx`) | UNA línea `<script src="/aleph-piel.js">` | volver a agregar la línea |

Cero componentes ajenos modificados. Esta fase entera entró por el punto de extensión.

## Fase 6 — el frame (abre el cuerpo · Ley 6, tercera cirugía)

_Vacía hasta que se abra el primer archivo. Cada entrada lleva: archivo · líneas tocadas ·
qué ítem se reubicó · qué handler conserva · cómo verificar que sigue gobernando._

### Oficina (`openwork`) — 2026-09-08

| Archivo | Líneas | Qué se hizo | Handler |
|---|---|---|---|
| `apps/app/src/react-app/domains/session/sidebar/aleph-frame.tsx` | **nuevo, 140** | archivo NUESTRO: la marca, `‹ Inicio` y `⚙ Settings` | propio (postMessage) |
| `…/sidebar/app-sidebar.tsx` | 6 líneas | 1 import · 1 hook · `<AlephFrameHeader/>` · `<AlephFrameFooter/>` · 4 rótulos condicionales | **intacto** |
| `apps/app/src/i18n/locales/*.ts` (10) | +4 claves c/u | `aleph.frame.*`, claves NUEVAS | — |

**Nada de lógica tocada.** `onCreateTaskInWorkspace`, `onOpenSessionSearch`, `onOpenExtensions`
y la lista de sesiones conservan su handler, su estado y su comportamiento; sólo cambia el
rótulo y aparece la cabecera arriba. Verificado en pantalla: el buscador abre.

**Al re-vendorizar:** copiar `aleph-frame.tsx`, re-aplicar las 6 líneas de `app-sidebar.tsx` y
las 4 claves por locale. Si su `<SidebarHeader>` cambió de forma, la cabecera va igual como
primer hijo.

**Hueco declarado:** la fila de cuenta (`○ Renata O. · Admin`). No se pinta: la identidad que
este stack conoce es la suya, no la de Aleph, y mostrarla sería mentirle al usuario.

### Finanzas (`vibetrading`) — 2026-09-08
| Archivo | Qué | Handler |
|---|---|---|
| `frontend/src/components/layout/aleph-frame.tsx` | **nuevo**: marca, `‹ Inicio`, `⚙ Settings`, grupo y sub-grupo | propio |
| `frontend/src/components/layout/Layout.tsx` | brand oculto · `NAV` partido en `FINANZAS` (Agent·Runtime) y `Más en Finanzas` (Scheduled·Reports·Alpha Zoo·Correlation) · rótulo de sesiones | **intacto**: `renderNav` es el cuerpo EXACTO del `NAV.map` de antes, extraído para llamarlo dos veces |

**Huecos declarados:** `Search` y `Library` — medido, no existen en Finanzas (0 ocurrencias).
**Nota:** su `/settings` sigue ruteado y funcionando; el diseño no le da fila en el NAV.

### Educación (`deeptutor`) — 2026-09-08
| Archivo | Qué | Handler |
|---|---|---|
| `web/components/sidebar/aleph-frame.tsx` | **nuevo** (`"use client"`) | propio |
| `web/components/sidebar/SidebarShell.tsx` | ancho 220→260 · marca oculta · etiqueta de grupo sobre `PRIMARY_NAV` · pie | **intacto** |

### Legal (`dochaus`) — 2026-09-08
| Archivo | Qué | Handler |
|---|---|---|
| `apps/web/src/components/aleph-frame.tsx` | **nuevo** (sin pie: Legal ya tiene el suyo) | propio |
| `apps/web/src/components/Sidebar.tsx` | marca oculta · `sidebar-label` «Workspace» → nombre del espacio en mono | **intacto** — su `onOpenSettings` no se toca |

---

## Oficina (`openwork`) — 2026-09-09 · «el frame», la segunda tanda

Esta tanda vuelve a abrir el cuerpo de `openwork` en cinco archivos más. La superficie de
conflicto al re-vendorizar creció; acá está entera, con el motivo de cada corte.

| Archivo | Qué se tocó | Handler |
|---|---|---|
| `src/react-app/domains/session/sidebar/aleph-frame.tsx` | **nuestro**. El pie pasa de un solo `⚙` a: `⚙ Settings` + los ítems que la casa contesta en el censo (`Ir a…`, `Conectores`) + la fila de cuenta. La cabecera acepta `acciones`. `Mascota` se exporta con `size`. | propio |
| `…/sidebar/app-sidebar.tsx` | las dos flechas del historial se extraen a `flechasDelHistorial` y, con el frame prendido, se dibujan dentro de la cabecera en vez de en su franja | **intacto**: mismos `onClick`, mismo `disabled`, mismos rótulos |
| `…/session/chat/session-empty-hero.tsx` | el saludo del estándar (mascota + frase por franja horaria) reemplaza el par titular/bajada, y las cuatro sugerencias no se dibujan | **intacto**: `DEFAULT_SUGGESTIONS` y el camino de las tarjetas de organización quedan enteros y se pintan con el flag apagado |
| `…/session/chat/session-page.tsx` | el `SidebarTrigger` de la barra de arriba se apaga (se movió a la cabecera) · el tope de la columna del saludo 800→900 | **intacto** |
| `…/session/surface/composer/composer.tsx` | el enchufe → los dos palitos · el rótulo del enviar se va al `aria-label` · la pista del atajo · cuatro clases de medida | **intacto**: `fileInput.click()`, `setToolMenuOpen`, `props.onSend` y el menú entero sin tocar |
| `…/session/surface/composer/editor.tsx` | una clase en el placeholder | **intacto** |
| `…/shell/ui-state-store.ts` | **arreglo de correctitud, no de diseño** (ver abajo) | — |
| `src/i18n/locales/*.ts` (10) | 5 claves nuevas: `composer_hint` y las 4 del saludo | claves nuevas, ninguna pisada |

### El arreglo que no es cosmético
`readLegacyNumber` hacía `Number(localStorage.getItem(key))`. Con la clave AUSENTE eso da
`Number(null) === 0`, que es finito, así que en vez de devolver `null` —«no hay valor
guardado, usá el default»— caía al `clampNumber(0, min, max)` y devolvía el **mínimo**.
Medido en el DOM: toda instalación nueva arrancaba con el sidebar en **220 px** y el
`DEFAULT_WORKSPACE_LEFT_SIDEBAR_WIDTH = 260` de dos pantallas más arriba no se usaba nunca.
Es también la razón por la que la regla `--sidebar-width: 260px` de `aleph-piel.css` no se
veía: el provider la escribe INLINE y el inline gana. Al re-vendorizar, este parche vale
igual aunque el frame se apague; si upstream lo arregló, quedarse con el suyo.

### Huecos y divergencias declaradas
- **La fila de cuenta ya no es hueco.** Se llena con la identidad de **Aleph**, que la
  cáscara contesta por el mensaje nuevo `aleph-identidad?` / `aleph-identidad`. El
  `AccountStatusMenu` del stack **sigue apagado** al embeber y tiene que seguirlo: la
  identidad que él conoce es la suya, y su menú es además una segunda puerta de ajustes.
- **Las flechas ← →** no están dibujadas en el mockup y se conservan igual: son historial
  —función—, y no tienen otra casa. Se movieron para no dejar una segunda barra.
- **La barra de arriba** (`session-page.tsx:1086`) se conserva: lleva el buscador en la
  conversación y el interruptor del panel lateral, que el diseño no ubica en ningún lado.
- **El menú de los dos palitos** queda en dos paneles; el mockup 35c lo dibuja en una
  columna. Pasarlo a una columna es meterle un nivel de navegación, o sea cambiarle el
  funcionamiento a un botón que ya existe.
- **Su Settings propio** (MCP, plugins, extensiones, variables de entorno, memoria,
  avanzado, recovery, updates) **no se muda**: es estado real de su backend. El doc decía
  «Oficina no tiene ajustes propios» y contra el código eso es falso — 23 archivos en
  `domains/settings/pages/`. La puerta del SIDEBAR converge; lo hondo se alcanza por
  `Configure`, que el propio mockup 35c pone adentro de los dos palitos.

### Ciencia (`openscience`) — 2026-09-09

⚠️ **Es el único de los seis donde el frame se CONSTRUYÓ en vez de mudarse.** Los otros cuatro
ya traían un `aleph-frame.tsx` de una fase anterior; openscience no —medido:
`find third_party -name 'aleph-frame*'` daba cuatro archivos y éste no estaba— y su inyección
nunca le llegó, porque `aleph-piel.js` ancla en `[data-sidebar="sidebar"]` /
`[data-slot="sidebar-inner"]` y este stack no expone ninguno (grep = 0).
**Y es SolidJS, no React**: nada de lo escrito para los otros cuatro se copia tal cual.

| Archivo | Qué se hizo | Handler |
|---|---|---|
| `frontend/workspace/src/pages/aleph-frame.tsx` | **nuevo, ~420**: archivo NUESTRO — la marca, `‹ Inicio`, `⚙ Settings`, la cuenta, la fila (`FilaFrame`), la etiqueta de grupo y los glifos del artboard | propio (postMessage) |
| `frontend/workspace/src/pages/session.tsx` | `SessionsSidebar` con una rama `Show when={frame.activo}`; `Header` sólo en móvil y `SessionTabStrip` sólo sin frame; dos props nuevas (`terminalVivo`, `computo`); un `createEffect` que lee `/settings/compute` para el rótulo `Local` | **intacto**: cada fila recibe el `onClick` que ya tenía (`onNew`, `onSearch`, `onContext(...)`, `onCollapse`) |
| `frontend/workspace/src/components/prompt-input.tsx` | el glifo del clip (era `Icon name="plus"`), la pista del atajo, y `Run review` dentro de los dos palitos | **intacto**: `attach` es el mismo, y `onRunReview` llega desde la página |
| `frontend/workspace/src/components/prompt-input.css` | tres `#4f8cff` → `var(--aleph-acento, #4f8cff)` | — (mismo valor con el flag apagado) |
| `frontend/workspace/src/atlas/CommandPalette.tsx` | el comando `open-settings` converge a Aleph con el frame puesto | **intacto** con el flag apagado |
| `frontend/workspace/src/notebook/NotebookView.tsx` | `#d99b35` (naranja clavado) → `var(--color-warning)` | — |

**Al re-vendorizar:** copiar `aleph-frame.tsx` y `e2e/aleph-frame.spec.ts`; re-aplicar la rama
de `SessionsSidebar` (es UN `Show` con `fallback`, y el `fallback` es el JSX de antes sin
tocar), los dos `Show` de `Header`/`SessionTabStrip`, y los cinco retoques puntuales de la
tabla. Si su `session.tsx` cambió de forma, lo que hay que conservar es que **el `fallback`
sea literalmente su código de hoy**: así el camino sin frame no depende de nosotros.

**Huecos declarados, medidos por FUNCIÓN:**
- **El contador de `Library`** (el artboard dibuja `128`): el stack no publica un total de
  archivos del proyecto. Se dibuja la fila sin número antes que inventar uno.
- **`⌘⇧F`**: el artboard lo pinta y en este stack la paleta abre con **⌘K** (`useGlobalKeys`).
  Se pinta el que EXISTE; pintar `⌘⇧F` sería una tecla que no hace nada.
- **`Back to projects`**: adentro de Aleph no lleva a ninguna parte (`home.tsx` entra solo al
  proyecto del pack), así que no tiene fila. Fuera de Aleph el frame está apagado y su botón
  sigue en la cabecera.
- **Los tres enlaces PROFUNDOS al Settings del stack** —«Manage compute…», «Set up model» y el
  alta de proveedores de su picker— siguen vivos a propósito: son su plomería, y el brief
  converge la PUERTA, no las credenciales ni el estado de su backend.
