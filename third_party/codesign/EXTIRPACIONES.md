# Open CoDesign — extirpaciones para Aleph Diseño

## Runtime embebido (A″ · inmersión webview)

El pack conserva Electron sólo como **motor headless**: sirve el renderer Vite por
loopback y Aleph lo muestra en su iframe existente. No crea `BrowserWindow`, menú ni una
segunda pantalla. El payload `.app` de Electron no puede viajar como árbol dentro del
sidecar: PyInstaller re-firma los Mach-O que descubre en `third_party/codesign` y rechaza
los frameworks anidados. `bin/aleph-codesign` recibe por eso un ZIP opaco
`release/aleph-diseno-mac-arm64.zip`, lo expande con `ditto` en
`ALEPH_CODESIGN_DATA_DIR/electron-runtime/<sha256>/` y arranca allí el main con
`--aleph-headless --aleph-port=<dinámico>`. El renderer sigue en `out/renderer` y su
bridge HTTP/SSE conserva `window.codesign` sin Electron en runtime.

Delta contra el testigo bruto `b94d7156bf4aeb2c79892c91dc9934911a4e3741`.

| Corte | Superficie | Motivo |
|---|---|---|
| updater/release GitHub | `apps/desktop/src/main/index.ts`, `app-menu.ts`, `electron.vite.config.ts`, `package.json`, `electron-builder.yml`, renderer | La instalación y las actualizaciones pertenecen a Aleph; el binario no consulta el feed del upstream. |
| OAuth ChatGPT/Codex | Registro del arranque retirado de `apps/desktop/src/main/index.ts` | La identidad la resuelve Aleph. Los módulos no alcanzables quedan fuera del bundle mientras el corte de proveedor único se completa por configuración de pack. |
| marca visible | `renderer/index.html`, `packages/ui/src/components/Wordmark.tsx`, exportadores y fallback de arranque | La superficie ve `Diseño · Aleph`; créditos y origen permanecen en `ATTRIBUTIONS.md`. |
| referencias de marca sin licencia individual | 25 archivos `apps/desktop/resources/templates/brand-refs/*/DESIGN.md` | El estudio no encontró licencia individual; no son necesarios para el oficio. |
| selector/modelos y BYOK de imagen | `renderer/src/components/{ModelSwitcher,Settings}.tsx` | La UI no permite elegir modelo, proveedor, endpoint, clave o imagen ajena: queda el único `aleph-brain` que el pack escribe. Al dejar de importarlos, `ModelsTab`, `ImageGenerationTab` y `AddCustomProviderModal` no salen en `out/renderer`. |
| registro upstream de onboarding/conexión/OAuth | `main/index.ts` + grafo de `onboarding-ipc` | El main sólo registra lectura de la config Aleph; no registra handlers de alta/edición de providers, pruebas de conexión, OAuth ni generación de imagen. |

## Espacio certificado (Obra B)

El único header del provider único es `X-Aleph-Space`. `space_for()` lo deriva del `sid`
que F4 ya entrega en el puntero 0600 y el borde lo consume como `space_id`
(`product/backend/app/phase1/router.py:3356-3406`). `X-Aleph-Workspace` fue un header
fantasma: el censo de Diseño no encontró consumidores propios que lo leyeran, por lo que
fue eliminado del lanzador y no se conserva compatibilidad. Éste es el molde Legal:
identidad de vertical ≠ sobre donde se archiva el turno.

No se altera el agent loop, sus tools, sesiones, canvas, preview, archivos ni exportadores
salvo sus pies visibles. La costura de modelo se configura desde Aleph.

## Piel de Aleph — convergencia inline (Gate 4 · F6, 2026-08-10)

La ley 6 permite dos cirugías sobre una pieza importada: amputarle el agente y **teñirle la
piel**. Ésta es la segunda. El test es la ley 3: si el usuario adivina de qué repo vino, se
estandarizó mal.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1 | La boca del agente | `packages/core/src/prompts/sections/identity.md:1` | Decía «You are open-codesign». Se le preguntaba al agente quién era y contestaba el repo de origen — la superficie más usada del vertical. |
| 2 | La letra de la casa, vendorizada | `apps/desktop/src/renderer/src/aleph-fonts.css` (nuevo) · `renderer/src/fonts/outfit-*.woff2` · `renderer/src/main.tsx` (sale `@open-codesign/ui/fonts`) · `packages/ui/src/tokens.css` (`--font-sans`/`--font-display` → Outfit, mono al stack de sistema) | Eran tres familias del proyecto de origen (Fraunces, Geist, JetBrains Mono), declaradas en el código como estética de OTRA empresa. El lienzo vive en otro origen y no puede linkear el `vendor/fonts.css` de la casa: se vendoriza, offline. |
| 3 | El esquema de la casa cruza el borde | `apps/desktop/src/renderer/index.html` (el preload lee `aleph_scheme` y lo persiste en la clave que el stack ya usaba) | El preload buscaba una clave que NADIE escribía: el lienzo abría crema con acento terracota dentro de una casa oscura. El stack ya tenía su bloque `.dark`; ahora lo alcanza. |
| 4 | El wordmark, sin hex inventados | `packages/ui/src/components/Wordmark.tsx` | «Aleph» en azul marino y «Diseño» + ✦ en naranja, tres hex fijos que no se dan vuelta con el tema. Van con los tokens DEL PROPIO STACK, como en el precedente de Ciencia. |
| 5 | La barra, con tokens | `apps/desktop/src/renderer/src/components/TopBar.tsx` (borde inferior + los dos separadores `/`) | Marrón cálido literal fuera del bloque de tema: quedaba visible en oscuro. |
| 6 | El nombre del cerebro | `apps/desktop/src/main/onboarding/config-cache.ts` | Debajo del cuadro de escribir decía `aleph-workspace`, un identificador técnico. Ahora dice el `name` que escribe el lanzador: «Cerebro de Aleph» (ley 12). |
| 7 | La marca en el copy vivo | `packages/i18n/src/locales/{en,es,pt-BR,zh-CN}.json` | «dentro de Open CoDesign» en la pestaña de preview, que es el corazón del oficio. |
| 8 | Sin red por fuentes | `packages/runtime/src/index.ts` (dos bloques) | Cada preview de un diseño salía a `fonts.googleapis.com`: sin conexión el texto esperaba, y con conexión cada vista previa le avisaba a Google. Aleph es offline-first. Servir esas familias localmente queda como candidata de convergencia. |
| 9 | Material de marca ajena sin licencia | `anthropic-home.png` (borrado, sin referencias) · `apps/desktop/resources/templates/brand-refs/` (25 carpetas VACÍAS + su `manifest.json`, borradas) | Los `DESIGN.md` ya se habían quitado por falta de licencia individual y quedaba el índice prometiendo 25 marcas que no existen. `resource-manifest.ts` ahora trata la ausencia como ESTADO, no como fallo: sin el guard, cada generate avisaba «Brand references unavailable» por algo que se sacó a propósito. |

**Lo que NO se tocó:** el oficio entero — su lienzo, sus snapshots y versiones, su sistema de
diseño, sus exportadores y su jerga en inglés (ley 11). Tampoco la pantalla de preferencias
(apariencia, almacenamiento, memoria, diagnóstico, avanzado): se verificó que NO expone
proveedor ni clave — los tabs de modelos e imagen ya estaban fuera del grafo de render.
