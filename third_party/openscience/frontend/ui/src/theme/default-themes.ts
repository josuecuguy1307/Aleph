import type { DesktopTheme } from "./types"
/* [Aleph · 2026-08-11] El tema de la casa. Este stack ya tenía la palanca hecha: el
   `--color-*` que usa la app es una capa de ALIAS sobre los tokens semánticos de
   `@synsci/ui`, y el tema —un JSON con semillas y overrides— los define en runtime. Su
   propio comentario en `atlas.css:24` lo dice: «picking a different theme restyles the
   whole app coherently». Así que la piel de Aleph entra por donde el stack quiere, y no
   tocando sus 6.397 líneas de CSS.
   Los `syntax-*` y `markdown-*` quedan como vinieron: colorean CÓDIGO y DOCUMENTOS, que son
   el oficio, no la interfaz. */
import alephThemeJson from "./themes/aleph.json"
import openscienceThemeJson from "./themes/openscience.json"
import synsc1ThemeJson from "./themes/openscience-1.json"
import tokyoThemeJson from "./themes/tokyonight.json"
import draculaThemeJson from "./themes/dracula.json"
import monokaiThemeJson from "./themes/monokai.json"
import solarizedThemeJson from "./themes/solarized.json"
import nordThemeJson from "./themes/nord.json"
import catppuccinThemeJson from "./themes/catppuccin.json"
import ayuThemeJson from "./themes/ayu.json"
import oneDarkProThemeJson from "./themes/onedarkpro.json"
import shadesOfPurpleThemeJson from "./themes/shadesofpurple.json"
import nightowlThemeJson from "./themes/nightowl.json"
import vesperThemeJson from "./themes/vesper.json"
import carbonfoxThemeJson from "./themes/carbonfox.json"
import gruvboxThemeJson from "./themes/gruvbox.json"
import auraThemeJson from "./themes/aura.json"

export const alephTheme = alephThemeJson as DesktopTheme
export const openscienceTheme = openscienceThemeJson as DesktopTheme
export const synsc1Theme = synsc1ThemeJson as DesktopTheme
export const tokyonightTheme = tokyoThemeJson as DesktopTheme
export const draculaTheme = draculaThemeJson as DesktopTheme
export const monokaiTheme = monokaiThemeJson as DesktopTheme
export const solarizedTheme = solarizedThemeJson as DesktopTheme
export const nordTheme = nordThemeJson as DesktopTheme
export const catppuccinTheme = catppuccinThemeJson as DesktopTheme
export const ayuTheme = ayuThemeJson as DesktopTheme
export const oneDarkProTheme = oneDarkProThemeJson as DesktopTheme
export const shadesOfPurpleTheme = shadesOfPurpleThemeJson as DesktopTheme
export const nightowlTheme = nightowlThemeJson as DesktopTheme
export const vesperTheme = vesperThemeJson as DesktopTheme
export const carbonfoxTheme = carbonfoxThemeJson as DesktopTheme
export const gruvboxTheme = gruvboxThemeJson as DesktopTheme
export const auraTheme = auraThemeJson as DesktopTheme

export const DEFAULT_THEMES: Record<string, DesktopTheme> = {
  aleph: alephTheme,
  openscience: openscienceTheme,
  "openscience-1": synsc1Theme,
  aura: auraTheme,
  ayu: ayuTheme,
  carbonfox: carbonfoxTheme,
  catppuccin: catppuccinTheme,
  dracula: draculaTheme,
  gruvbox: gruvboxTheme,
  monokai: monokaiTheme,
  nightowl: nightowlTheme,
  nord: nordTheme,
  onedarkpro: oneDarkProTheme,
  shadesofpurple: shadesOfPurpleTheme,
  solarized: solarizedTheme,
  tokyonight: tokyonightTheme,
  vesper: vesperTheme,
}
