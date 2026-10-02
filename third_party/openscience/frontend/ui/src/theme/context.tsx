import { onMount, onCleanup, createEffect } from "solid-js"
import { createStore } from "solid-js/store"
import type { DesktopTheme } from "./types"
import { resolveThemeVariant, themeToCss } from "./resolve"
import { DEFAULT_THEMES } from "./default-themes"
import { createSimpleContext } from "../context/helper"

export type ColorScheme = "light" | "dark" | "system"

const STORAGE_KEYS = {
  THEME_ID: "openscience-theme-id",
  COLOR_SCHEME: "openscience-color-scheme",
  THEME_CSS_LIGHT: "openscience-theme-css-light",
  THEME_CSS_DARK: "openscience-theme-css-dark",
} as const

const THEME_STYLE_ID = "openscience-theme"

function ensureThemeStyleElement(): HTMLStyleElement {
  const existing = document.getElementById(THEME_STYLE_ID) as HTMLStyleElement | null
  if (existing) return existing
  const element = document.createElement("style")
  element.id = THEME_STYLE_ID
  document.head.appendChild(element)
  return element
}

function getSystemMode(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function applyThemeCss(theme: DesktopTheme, themeId: string, mode: "light" | "dark") {
  const isDark = mode === "dark"
  const variant = isDark ? theme.dark : theme.light
  const tokens = resolveThemeVariant(variant, isDark)
  const css = themeToCss(tokens)

  if (themeId !== "openscience-1") {
    try {
      localStorage.setItem(isDark ? STORAGE_KEYS.THEME_CSS_DARK : STORAGE_KEYS.THEME_CSS_LIGHT, css)
    } catch {}
  }

  const fullCss = `:root {
  color-scheme: ${mode};
  --text-mix-blend-mode: ${isDark ? "plus-lighter" : "multiply"};
  ${css}
}`

  document.getElementById("openscience-theme-preload")?.remove()
  ensureThemeStyleElement().textContent = fullCss
  document.documentElement.dataset.theme = themeId
  document.documentElement.dataset.colorScheme = mode
}

function cacheThemeVariants(theme: DesktopTheme, themeId: string) {
  if (themeId === "openscience-1") return
  for (const mode of ["light", "dark"] as const) {
    const isDark = mode === "dark"
    const variant = isDark ? theme.dark : theme.light
    const tokens = resolveThemeVariant(variant, isDark)
    const css = themeToCss(tokens)
    try {
      localStorage.setItem(isDark ? STORAGE_KEYS.THEME_CSS_DARK : STORAGE_KEYS.THEME_CSS_LIGHT, css)
    } catch {}
  }
}

export const { use: useTheme, provider: ThemeProvider } = createSimpleContext({
  name: "Theme",
  init: (props: { defaultTheme?: string }) => {
    const [store, setStore] = createStore({
      themes: DEFAULT_THEMES as Record<string, DesktopTheme>,
      /* [Aleph] El tema por defecto es el de la casa. Quien quiera otro lo elige en Ajustes
         —los 16 temas del stack siguen ahí—, pero al entrar por primera vez el workspace
         tiene que verse como Aleph, no como el producto del que vino. */
      themeId: props.defaultTheme ?? "aleph",
      colorScheme: "system" as ColorScheme,
      mode: getSystemMode(),
      previewThemeId: null as string | null,
      previewScheme: null as ColorScheme | null,
    })

    onMount(() => {
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
      const handler = () => {
        if (store.colorScheme === "system") {
          setStore("mode", getSystemMode())
        }
      }
      mediaQuery.addEventListener("change", handler)
      onCleanup(() => mediaQuery.removeEventListener("change", handler))

      /* [Aleph · 2026-08-11] LA CASA MANDA SOBRE LO GUARDADO.
       *
       * Cambiar el tema por defecto no alcanzaba: `localStorage` conservaba el tema elegido
       * en una sesión anterior —medido: `openscience-theme-id = "openscience-1"`— y ganaba
       * al arrancar. El workspace seguía viéndose con la piel del stack aunque el default
       * ya fuera Aleph, y desde afuera parecía que el cambio no había entrado.
       *
       * Cuando Aleph abre el lienzo le pasa `?aleph_scheme=…` en la URL. Esa marca dice
       * «esta vista viene de la casa», y en ese caso el tema es el de la casa: se ignora lo
       * guardado y se persiste el de Aleph, para que una navegación interna —que pierde el
       * `search`— no lo revierta. Es el mismo criterio que en Legal y Diseño.
       *
       * Abierto por fuera de Aleph (sin esa marca), el tema guardado sigue mandando: los 16
       * temas del stack no se pierden y quien eligió uno lo conserva. */
      /* [Aleph · 2026-08-11] Y EL CLARO/OSCURO TAMBIÉN LO MANDA LA CASA.
       *
       * `?aleph_scheme` se leía sólo como marca de presencia (`.has`): el tema pasaba a ser
       * el de Aleph, pero su VALOR —`light` o `dark`— se tiraba, y dos líneas más abajo el
       * `savedScheme` guardado volvía a mandar. Medido: la casa en oscuro y el lienzo en
       * claro. Acá se persiste el esquema de la casa ANTES de esa lectura, para que
       * `savedScheme` lea el de Aleph y una navegación interna —que pierde el `search`— no
       * lo revierta. Mismo criterio que el `themeId` de acá arriba. */
      const marcaDeAleph = new URLSearchParams(window.location.search).get("aleph_scheme")
      const vieneDeAleph = marcaDeAleph !== null
      if (vieneDeAleph && store.themes["aleph"]) {
        setStore("themeId", "aleph")
        localStorage.setItem(STORAGE_KEYS.THEME_ID, "aleph")
      }
      if (marcaDeAleph === "light" || marcaDeAleph === "dark" || marcaDeAleph === "system") {
        localStorage.setItem(STORAGE_KEYS.COLOR_SCHEME, marcaDeAleph)
      }

      const savedTheme = localStorage.getItem(STORAGE_KEYS.THEME_ID)
      const savedScheme = localStorage.getItem(STORAGE_KEYS.COLOR_SCHEME) as ColorScheme | null
      if (savedTheme && store.themes[savedTheme]) {
        setStore("themeId", savedTheme)
      }
      if (savedScheme) {
        setStore("colorScheme", savedScheme)
        if (savedScheme !== "system") {
          setStore("mode", savedScheme)
        }
      }
      const currentTheme = store.themes[store.themeId]
      if (currentTheme) {
        cacheThemeVariants(currentTheme, store.themeId)
      }
    })

    createEffect(() => {
      const theme = store.themes[store.themeId]
      if (theme) {
        applyThemeCss(theme, store.themeId, store.mode)
      }
    })

    const setTheme = (id: string) => {
      const theme = store.themes[id]
      if (!theme) {
        console.warn(`Theme "${id}" not found`)
        return
      }
      setStore("themeId", id)
      localStorage.setItem(STORAGE_KEYS.THEME_ID, id)
      cacheThemeVariants(theme, id)
    }

    const setColorScheme = (scheme: ColorScheme) => {
      setStore("colorScheme", scheme)
      localStorage.setItem(STORAGE_KEYS.COLOR_SCHEME, scheme)
      setStore("mode", scheme === "system" ? getSystemMode() : scheme)
    }

    return {
      themeId: () => store.themeId,
      colorScheme: () => store.colorScheme,
      mode: () => store.mode,
      themes: () => store.themes,
      setTheme,
      setColorScheme,
      registerTheme: (theme: DesktopTheme) => setStore("themes", theme.id, theme),
      previewTheme: (id: string) => {
        const theme = store.themes[id]
        if (!theme) return
        setStore("previewThemeId", id)
        const previewMode = store.previewScheme
          ? store.previewScheme === "system"
            ? getSystemMode()
            : store.previewScheme
          : store.mode
        applyThemeCss(theme, id, previewMode)
      },
      previewColorScheme: (scheme: ColorScheme) => {
        setStore("previewScheme", scheme)
        const previewMode = scheme === "system" ? getSystemMode() : scheme
        const id = store.previewThemeId ?? store.themeId
        const theme = store.themes[id]
        if (theme) {
          applyThemeCss(theme, id, previewMode)
        }
      },
      commitPreview: () => {
        if (store.previewThemeId) {
          setTheme(store.previewThemeId)
        }
        if (store.previewScheme) {
          setColorScheme(store.previewScheme)
        }
        setStore("previewThemeId", null)
        setStore("previewScheme", null)
      },
      cancelPreview: () => {
        setStore("previewThemeId", null)
        setStore("previewScheme", null)
        const theme = store.themes[store.themeId]
        if (theme) {
          applyThemeCss(theme, store.themeId, store.mode)
        }
      },
    }
  },
})
