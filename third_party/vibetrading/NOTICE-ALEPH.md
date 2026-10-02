# NOTICE — lo que Aleph declara sobre esta pieza

El `NOTICE` y el `LICENSE` del proyecto de origen viven intactos en la raíz de esta carpeta y
no se tocan (`third_party/README.md` · Ley 3). Este archivo es **lo que Aleph agrega**: las
elecciones de licencia que hace, y lo que queda declarado como deuda de procedencia.

---

## 1 · Obligaciones que viajan con el `.app`

El `NOTICE` del origen **no es decorativo**: es la condición de dos licencias del árbol.
**Tiene que empaquetarse con el producto.**

| Qué obliga | Por qué |
|---|---|
| **Microsoft Qlib** — el zoo `qlib158` | Apache-2.0 §4(d): el `NOTICE` aguas arriba se redistribuye. Vive en `agent/src/factors/zoo/qlib158/NOTICE` |
| **Inter y JetBrains Mono** (`@fontsource` 5.3.0) | SIL OFL-1.1: se redistribuyen con su licencia y no se venden solas. `frontend/public/fonts/LICENSE` |

El `NOTICE` del origen además declara —bien, y conviene conservarlo tal cual— la doctrina de
copyright de los factores: las 101 Formulaic Alphas (Kakushadze, arXiv:1601.00991), las 191 de
Guotai Junan, y Fama-French / Carhart / Hou-Xue-Zhang están **reimplementadas como fórmulas**,
que son contenido factual; prosa, tablas y figuras de los papers **no** se reproducen. Cada zoo
tiene su `LICENSE.md`.

## 2 · `pyphen` — Aleph elige MPL 1.1

`pyphen` es el **único** paquete con GPL en el árbol de 180 dependencias instaladas. Los
clasificadores de su metadata declaran **tres** licencias:

```
License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)
License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)
License :: OSI Approved :: Mozilla Public License 1.1 (MPL 1.1)
```

Es **tri-licencia a elección del receptor**. `third_party/README.md` prohíbe copyleft fuerte
dentro del producto, y esa prohibición se cumple eligiendo:

> **Aleph recibe y redistribuye `pyphen` bajo la Mozilla Public License 1.1.**

Llega como transitivo de `weasyprint`, que existe para renderizar el informe HTML/PDF del
Shadow Account. Si algún día se extirpa el Shadow Account, `pyphen` se va solo.

**Cero AGPL. Cero SSPL. Cero BUSL. Cero Elastic. Cero licencia no-comercial** en los 180
paquetes.

## 3 · Dos paquetes sin campo de licencia

| Paquete | Metadata | Aguas arriba |
|---|---|---|
| `peewee` | sin `License` ni `License-Expression` ni clasificador | **MIT** |
| `smartmoneyconcepts` | ídem | **MIT** |

Es un campo faltante, no una licencia hostil. Queda anotado para que una auditoría futura no lo
lea como «desconocida».

## 4 · Lo que Aleph NO redistribuye

Las **23 fuentes de mercado** del stack son **APIs públicas que se consultan**, no datos que
viajen adentro. Aleph no redistribuye ni un tick. Las que piden llave (Tushare, Finnhub,
AlphaVantage, Tiingo, FMP, Longbridge, y los terminales locales de Futu y MetaTrader 5) son
opcionales y la llave la pone el usuario.

**QVeris se extirpó** — ver `EXTIRPACIONES.md` §2. No era un problema de licencia: era un
acuerdo comercial de terceros con **código de invitación de HKUDS incrustado en código
ejecutable**, y eso Aleph no lo redistribuye.

## 5 · Deuda de procedencia declarada

1. **Los 5 `frontend/src/i18n/locales/*.json`** conservan cadenas con la marca del origen.
   Ninguna llega hoy a la pantalla por los caminos que sobreviven. Se saldan en la **tanda de
   CONVERGENCIA** (estandarización de piel), no acá.
2. **`agent/src/config/schema.py:429`** sigue declarando `ChannelsConfig`, que ya no lee nadie.
   Sacarlo es refactor del schema; queda como limpieza para el fork.
3. **`agent/src/channels/utils.py`** sobrevive a la amputación de los canales porque
   `src/security/` re-exporta de ahí el guard anti-SSRF y la contención de rutas. Mover ese
   módulo a `src/security/` es la limpieza correcta, y es refactor: no se hizo en la
   importación (Ley 5).
