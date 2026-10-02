# browser-use — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | `https://github.com/browser-use/browser-use` |
| **Commit importado** | `898f23f0b672ef44b4a01835ff4b3368e91812fd` |
| Licencia de código | **MIT** (`LICENSE`, conservada en la raíz) |
| Titular | Gregor Zunic, 2024 |
| Versión del paquete | `browser-use 0.13.8` (`pyproject.toml:2,5`) |
| Fecha de importación | 2026-08-18 |
| Estudio previo | `~/Desktop/SCOUT-BROWSER-USE.md` (columna A, candidato A1) |
| Árbol testigo | `~/Desktop/oss-estudio/browser-use-clone` (clon somero, mismo commit) |
| Qué es | El motor de **browser use** de la casa (plan §6.a, capacidad general). **No es un vertical.** |

## Integridad antes de cirugía

Se copiaron los **494 archivos rastreados por git**, verificados **sha256 archivo por
archivo contra el clon testigo: cero diferencias**. Manifiesto en `MANIFEST.sha256`; su
propio hash:

```
cf0491dc766a81e7312dd3d6648330f67f79f79200039c85bc709ae0735cdc7a
```

## ⚠️ Corrección al estudio previo: **NO usa Playwright**

El scouting reportó «Motor: Playwright», leído de un resumen del README. **Medido en el
árbol es falso**: `pyproject.toml` no declara `playwright` en ninguna parte (la única
mención es una línea comentada, `:243`). Maneja Chrome/Chromium **por CDP directo**, con
`cdp-use==1.4.5`, y busca el binario con `find_chrome_executable()`
(`browser_use/browser/chrome.py:38-70`).

**Consecuencia para el empaquetado**: el `chromium-headless-shell` que ya viaja
(`third_party/vane/.playwright`, `deploy/fase4/aleph_sidecar.spec:534,551`) **no se apunta
con `PLAYWRIGHT_BROWSERS_PATH`** —ese camino no aplica— sino con el campo
`executable_path` del perfil (`browser_use/browser/profile.py:417`). Es **config, un campo**.
Que el headless-shell recortado le alcance a CDP **no está medido** — ver el reporte.

## Licencias de las dependencias

**36 dependencias directas** (`pyproject.toml`), resueltas contra la metadata de PyPI en la
versión exacta que el proyecto fija. **Cero AGPL, SSPL, BUSL o GPL.** Reparto: MIT · Apache-2.0
· BSD-3-Clause · PSF-2.0 · MIT-CMU · «Apache-2.0 AND MIT» (aiohttp).

⚠️ **El árbol TRANSITIVO no está medido y no se puede medir desde el repo**: el proyecto no
trae lock file (`uv.lock` ausente; `git ls-files | grep lock` = 0 coincidencias reales), así
que la resolución completa exige instalar contra el runtime. **`[no medible]` hasta ese
paso**, y es condición para importar de verdad — el precedente es Vane, que midió 874
paquetes.

## El runtime y el chromium — MEDIDOS el 2026-08-18

**Runtime**: el contrato de los dos que ya cuelgan es el mismo y NO es un venv —
`busqueda/arranque.sh:90-96` (`$AQUI/../research/runtime`, exporta `PYTHONHOME` sólo cuando
usa el propio) y `research/arranque.sh:26` (`$AQUI/runtime/bin/python3`), con caída al
`python3` del sistema y `unset PYTHONHOME`. Medido en el árbol de la sesión de búsqueda:
**Python 3.13.13**, `sys.prefix` = la propia carpeta del runtime. browser-use cuelga de ahí
con la misma forma. (El choque que costó el último commit de main —«el elif pedía un venv
que ya no se produce»— es exactamente esto: la forma es *runtime plano*, jamás venv.)

**Chromium — el `[no medible]` del reporte anterior, RESUELTO**: se corrió el
`chrome-headless-shell` que ya viaja
(`third_party/vane/.playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/`)
con `--remote-debugging-port`, y **habla CDP**:

```
/json/version → Browser: HeadlessChrome/147.0.7727.15 · Protocol-Version: 1.3
                webSocketDebuggerUrl: ws://127.0.0.1:<port>/devtools/browser/…
/json/list    → un target type:"page" navegable
```

O sea: **no hace falta un Chrome completo**; se apunta con `profile.executable_path`
(`browser_use/browser/profile.py:417`). ⚠️ Consecuencia para la mitad visual: headless-shell
**no abre ventana**, así que lo que el usuario ve son capturas por CDP, no un navegador real
en pantalla.
