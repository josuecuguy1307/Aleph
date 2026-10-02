/**
 * aleph-frame.spec.ts — LA VARA DEL FRAME DE CIENCIA.
 * [rediseño · CIENCIA · el frame]
 *
 * QUÉ MIDE, Y POR QUÉ ASÍ. El frame sólo se enciende con `aleph_piel=v2` Y estando adentro de
 * un `<iframe>` (`window.parent !== window`). Una pestaña suelta de Playwright no cumple lo
 * segundo, así que acá se navega primero a la app —para quedar en su origen y que corran los
 * `addInitScript` del fixture— y después se reemplaza el documento por uno que embebe la app
 * en un iframe del MISMO origen. Mismo origen es load-bearing: permite leer los estilos
 * computados de adentro y escuchar los `postMessage` que el frame le manda al padre.
 *
 * ⚠️ Y SE MIDE LAS DOS CARAS. Cada cosa que el frame apaga se comprueba también con el flag
 * APAGADO, que es el default de `piel.js` para Ciencia hasta que esta obra se revise: si la
 * vara sólo mirara la cara nueva, un frame que se comió la vieja pasaría en verde.
 */
import { test, expect, type FrameLocator, type Page } from "@playwright/test"
import { test as base } from "./fixtures"
import { sessionPath } from "./utils"

/* ⚠️ SIN `aleph_scheme`, Y ESTÁ MEDIDO. En ESTE banco, pasar `aleph_scheme` en la URL hace
 * que la app recargue y quede apuntando a otro puerto que el arnés no levantó: sale el
 * banner rojo de «no se puede conectar» y la paleta pierde la mitad de sus comandos. Nada
 * que ver con el frame — se comprobó con las cuatro combinaciones (con/sin piel × con/sin
 * scheme) y el banner sigue al SCHEME, no al flag. El tema se prueba estampando
 * `data-aleph-scheme` a mano, que es lo que `aleph-piel.js` termina haciendo igual. */
const QUERY = "aleph_piel=v2&aleph_ws=ciencia&aleph_label=Ciencia&aleph_user=Renata%20O.&aleph_rol=Pro"

/** Embebe la app en un iframe del mismo origen y devuelve el localizador de adentro. */
async function abrirEnAleph(page: Page, directory: string, query = QUERY): Promise<FrameLocator> {
  await page.goto(sessionPath(directory))
  const url = `${sessionPath(directory)}?${query}`
  await page.evaluate((src) => {
    document.body.innerHTML = ""
    document.documentElement.style.height = "100%"
    document.body.style.cssText = "margin:0;height:100vh;overflow:hidden"
    // El buzón: lo que el frame le pida al padre queda acá para poder juzgarlo.
    ;(window as unknown as { __buzon: unknown[] }).__buzon = []
    window.addEventListener("message", (ev) => {
      ;(window as unknown as { __buzon: unknown[] }).__buzon.push(ev.data)
    })
    const f = document.createElement("iframe")
    f.id = "ws-frame"
    f.style.cssText = "border:0;width:100%;height:100%;display:block"
    f.src = src
    document.body.appendChild(f)
  }, url)
  const dentro = page.frameLocator("#ws-frame")
  await expect(dentro.locator('[data-component="prompt-input"]')).toBeVisible({ timeout: 30_000 })
  return dentro
}

const buzon = (page: Page) => page.evaluate(() => (window as unknown as { __buzon: unknown[] }).__buzon)

base("el frame dibuja la barra del diseño y apaga la de arriba", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)
  const barra = dentro.locator("aside.session-sidebar")

  // La cabecera: mascota, wordmark, el nombre del espacio y UN control de plegar.
  await expect(barra.locator(".aleph-frame-wordmark")).toHaveText("Aleph")
  await expect(barra.locator(".aleph-frame-espacio")).toHaveText("Ciencia")
  await expect(barra.locator(".aleph-frame-plegar")).toHaveCount(1)
  await expect(barra.locator(".session-sidebar__collapse")).toHaveCount(0)
  // `‹ Inicio` es la PRIMERA fila del raíz, con su glifo, y la línea la separa del bloque.
  const filas = barra.locator(".aleph-frame-fila .aleph-frame-fila-txt")
  await expect(filas.nth(0)).toHaveText("Inicio")
  await expect(barra.locator(".aleph-frame-cabecera .aleph-frame-sep")).toHaveCount(1)

  // El bloque estándar, en orden.
  await expect(filas.nth(1)).toHaveText("New chat")
  await expect(filas.nth(2)).toHaveText("Search")
  await expect(filas.nth(3)).toHaveText("Library")

  // La sección del espacio, con Terminal y Compute promovidos.
  await expect(barra.locator(".aleph-frame-grupo-txt").first()).toHaveText("CIENCIA")
  await expect(filas.nth(4)).toHaveText("Terminal")
  await expect(filas.nth(5)).toHaveText("Compute")
  await expect(barra.locator(".aleph-frame-fila-valor")).toHaveText("Local")
  await expect(barra.locator(".aleph-frame-fila-punto")).toHaveCount(1)

  // RECENT SESSIONS con su contador, y el pie con Settings y la cuenta.
  await expect(barra.locator(".aleph-frame-grupo-txt").nth(1)).toHaveText("RECENT SESSIONS")
  await expect(barra.locator(".aleph-frame-pie-item").first()).toContainText("Settings")
  await expect(barra.locator(".aleph-frame-cuenta-nom")).toHaveText("Renata O.")
  await expect(barra.locator(".aleph-frame-cuenta-rol")).toHaveText("Pro")

  // ⚠️ SIN BARRA DE ARRIBA Y SIN TIRA DE TABS — y son nodos que NO existen, no nodos
  // escondidos: `toHaveCount(0)` no pasa con un `display:none`.
  await expect(dentro.locator(".workspace-header")).toHaveCount(0)
  await expect(dentro.locator(".workspace-tabs")).toHaveCount(0)
})

base("con el flag apagado la barra vieja queda intacta", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory, "aleph_ws=ciencia&aleph_label=Ciencia")
  await expect(dentro.locator(".aleph-frame-cabecera")).toHaveCount(0)
  await expect(dentro.locator(".session-sidebar__project")).toHaveCount(1)
  await expect(dentro.locator(".session-sidebar__collapse")).toHaveCount(1)
  await expect(dentro.getByRole("button", { name: "New research" })).toBeVisible()
  await expect(dentro.getByRole("button", { name: "Customize Aleph Ciencia" })).toHaveCount(1)
  await expect(dentro.locator(".workspace-header")).toHaveCount(1)
})

base("los dos botones de Aleph PIDEN, no navegan", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)

  await dentro.locator(".aleph-frame-fila").first().click()
  await dentro.locator(".aleph-frame-pie-item").first().click()
  // `postMessage` es una tarea: leer el buzón en el mismo tick del click da siempre vacío.
  await page.waitForTimeout(250)

  const pedidos = (await buzon(page)) as Array<{ type?: string; section?: string }>
  expect(pedidos.map((p) => p?.type)).toContain("aleph-go-home")
  expect(pedidos.find((p) => p?.type === "aleph-open-settings")?.section).toBe("perfil")
  // Y la app de adentro NO navegó: sigue en su sesión.
  await expect(dentro.locator('[data-component="prompt-input"]')).toBeVisible()
})

base("las filas movidas siguen abriendo su panel", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)
  const fila = (nombre: string) =>
    dentro.locator(".aleph-frame-fila").filter({ has: dentro.locator(".aleph-frame-fila-txt", { hasText: nombre }) })

  // `Library` es el viejo `Files`: mismo `onContext("files")`.
  await fila("Library").click()
  await expect(dentro.getByRole("region", { name: "Files", exact: true })).toBeVisible()
  await expect(fila("Library")).toHaveAttribute("data-activa", "true")

  // `Terminal` es el viejo `Terminal`.
  await fila("Terminal").click()
  await expect(fila("Terminal")).toHaveAttribute("data-activa", "true")
})

base("la barrita: el clip, los dos palitos con sus cinco opciones, y la pista", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)

  // El clip: un solo botón de adjuntar, sin submenú, y ya no es un «+».
  const clip = dentro.locator(".workspace-composer__attach")
  await expect(clip).toHaveCount(1)
  await expect(clip.locator("svg path")).toHaveCount(1)

  // Los dos palitos: el menú de la sesión, entero.
  await dentro.locator(".workspace-composer__overflow > summary").click()
  const menu = dentro.locator(".workspace-composer__capability-list")
  for (const opcion of ["Delegation", "Auto-review", "Run review", "Reviewer model", "Specialist", "Compute"]) {
    await expect(menu.getByText(opcion, { exact: true })).toBeVisible()
  }

  // La pista del atajo, debajo de la caja.
  await expect(dentro.locator(".aleph-composer-pista")).toHaveText(
    "Enter para enviar · Shift+Enter para salto de línea",
  )
})

base("un solo acento y ningún token que caiga a un literal", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)
  const dep = page.frames()[1]

  // `--color-danger` tenía CERO declaraciones y 24 usos: los 24 caían a `#b23a2e`, un rojo
  // de modo claro. Ahora resuelve al rojo del estándar.
  const rojo = await dep.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-danger").trim(),
  )
  expect(rojo).not.toBe("")
  expect(rojo.toLowerCase()).toBe("#b6392b")

  // El azul propio del composer sale por token: el interruptor encendido es índigo.
  await dentro.locator(".workspace-composer__overflow > summary").click()
  const interruptor = dentro.locator('.workspace-composer__capability-switch[data-checked="true"]').first()
  await expect(interruptor).toBeVisible()
  const fondo = await interruptor.evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(fondo).toBe("rgb(71, 71, 201)")
})

/* ⚠️ LA PUERTA DE LA PALETA NO ES MEDIBLE ACÁ, Y ESO NO ES VERDE.
 * `CommandPalette` lista el comando «Settings» sólo en la rama SIN proyecto activo, y adentro
 * de Aleph el único estado posible es CON proyecto (`home.tsx` entra solo al del pack). O sea
 * que el disparador no está presente en esta pantalla: la ronda es NO MEDIBLE, no aprobada.
 * Lo que sí se mide acá abajo es que el pie del frame manda `aleph-open-settings`, que es la
 * puerta que el frente 4 pide converger. */

base("la barra plegada conserva sus glifos", async ({ page, directory }) => {
  const dentro = await abrirEnAleph(page, directory)
  const barra = dentro.locator("aside.session-sidebar")
  await dentro.locator(".aleph-frame-plegar").click()
  await expect(barra).toHaveAttribute("data-collapsed", "true")
  await expect(barra.locator(".aleph-frame-fila-txt").first()).toBeHidden()
  await expect(barra.locator(".aleph-frame-fila-glifo").first()).toBeVisible()
})

export { test, expect }
