# Vibe-Trading — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | https://github.com/HKUDS/Vibe-Trading |
| Commit importado | `281c87755f7a619ef41fa8804439909c6926034a` (v0.1.13, 2026-08-09 22:56 +0800) |
| Licencia | MIT (`LICENSE` en la raíz del repo de origen — copiado acá sin tocar) |
| Titular | «Vibe-Trading Contributors», Copyright 2026 · `NOTICE` de HKUDS |
| Fecha de importación | 2026-08-09 |
| Modificaciones al código ajeno | **sí** — extirpación de superficies de producto ajenas y la piel de Aleph. Corte por corte en [`EXTIRPACIONES.md`](EXTIRPACIONES.md) |
| Estudio previo | `~/Desktop/FASE6-FINANZAS-ESTUDIO.md` (licencias, censos 2.bis/2.ter, auth en 3 planos, anatomía, costura al modelo, mapa de brokers) |
| Decisión del dueño | **Opción B — VA COMPLETO.** Los 8 conectores con orden real entran vivos, con la máquina de mandato intacta |

---

## Qué se trajo

**El árbol entero** (Ley 1). Los **2.185 archivos rastreados** por git en el commit de
origen, extraídos con `git archive` y verificados **byte a byte**: sha256 archivo por archivo
contra el clon de estudio, **cero diferencias sobre los 2.185**.

No viajaron los `node_modules` / `.venv` (no versionados) ni el historial de git. El árbol
importado en disco pesa **63 MB**.

**Dos archivos quedaron fuera del commit, y conviene decir por qué:** `assets/Frontend.mp4` y
`assets/cli.mp4` (27 MB de video de demo). Los excluye **el propio `.gitignore` del proyecto de
origen** (`.gitignore:84` → `assets/*.mp4`); upstream los tiene trackeados de antes de esa
regla, así que aparecen en su árbol pero no vuelven a entrar en el nuestro. Son marketing y se
extirpan igual en el commit siguiente — no hay pérdida técnica. **Commiteados: 2.183 de 2.185.**

## Por qué esta pieza

De las tres costuras de Aleph —cerebro · compatibilidad · extras—, **sólo el cerebro se le
impone al stack** (Ley 0). Lo que se hereda de Vibe-Trading es su oficio, no su inferencia:

| Qué | Dónde | Por qué importa |
|---|---|---|
| **24 fuentes de mercado** | `agent/backtest/loaders/` | 14 sin llave. **21 de ellas el cinturón de Aleph no las tiene**: A-share (eastmoney, mootdx, tencent, akshare, baostock, sina, tushare), HK, KRX (pykrx), NSE/BSE, cripto spot y perps (okx, ccxt, binance), forex/metales (mt5) |
| **477 archivos de factores en 5 zoos** | `agent/src/factors/zoo/` | alpha101 (Kakushadze) · gtja191 (Guotai Junan) · qlib158 (Microsoft, Apache-2.0) · academic (Fama-French, Carhart, Hou-Xue-Zhang) · fundamental (PIT-safe sobre SEC) |
| **89 skills de oficio** | `agent/src/skills/` | chanlun · elliott-wave · ichimoku · harmonic · smc · options-* · macro · on-chain · regulatory-knowledge · behavioral-finance… |
| **`quantlib`** | `agent/src/quantlib/` | econometría real: ADF, cointegración, Granger, Ljung-Box, VIF, GARCH |
| **La máquina de mandato** | `agent/src/live/` (~7.600 líneas) | Autonomía acotada: techos verificados contra saldo y posiciones reales · caducidad de 30 días · kill switch · contador diario atómico · ledger de auditoría · commit inalcanzable desde el loop del agente |
| **El gate de grounding** | `agent/src/agent/grounding.py` | Se niega a cotizar un símbolo que no resolvió antes, y **sobrescribe la respuesta del modelo** si afirma un precio sin evidencia. Es un tesoro: no se toca |
| **La costura de proveedores** | `agent/src/providers/llm.py:1134` + `llm_providers.json` | Un único constructor OpenAI-compatible, sin lista blanca de hosts. Apuntar el stack al cerebro de Aleph es **pura config, cero corte de código** — probado con el lazo modelo→tool→modelo cerrado |

## La costura al cerebro de Aleph

Cuatro variables en `~/.vibe-trading/.env`. Sin tocar una línea de Python:

```
LANGCHAIN_PROVIDER=aleph
LANGCHAIN_MODEL_NAME=Cerebro de Aleph
OPENAI_BASE_URL=http://127.0.0.1:<puerto>/v1/workspaces/brain/openai
OPENAI_API_KEY=<lo que el borde acepte>
```

El proveedor `aleph` se agrega como **una entrada más** en
`agent/src/providers/llm_providers.json`, que es un archivo de datos, no código — el mismo
movimiento que el `openscience.json` de 15 líneas de F3-CIENCIA. Ver
[`EXTIRPACIONES.md`](EXTIRPACIONES.md) §Costura.

## La decisión sobre los brokers (sellada por el dueño)

**Opción B: va completo.** Los 8 conectores con perfil `live` + `readonly=False` —alpaca,
binance, etoro, futu, mt5, okx, tiger, robinhood— entran **vivos**, con su máquina de
mandato intacta. Fundamento: LEY 0 — ese órgano es del oficio, y para su dominio es mejor
que Ó11 (le agrega techos cuantitativos, caducidad, kill switch y ledger que Ó11 no tiene).
Ó11 sigue gobernando el resto de la casa. La tarjeta de mandato queda anotada como
**candidata ⭐ de la tanda de CONVERGENCIA**.

**Importar vivo ≠ operar.** Ninguna orden con dinero real se dispara en esta fase, y la
barrera es física, no de disciplina: sin credenciales de broker en el entorno, los caminos
al dinero mueren antes de tocar la red. El mapa completo de esos caminos y sus gates está
en [`MAPA-DEL-DINERO.md`](MAPA-DEL-DINERO.md).

## Deuda declarada (no bloquea, pero se anota)

1. **`pyphen` es GPLv2+ / LGPLv2+ / MPL 1.1** (tri-licencia, transitivo de `weasyprint`).
   Aleph **elige MPL 1.1** y lo declara en [`NOTICE-ALEPH.md`](NOTICE-ALEPH.md).
2. **`peewee` y `smartmoneyconcepts`** no declaran campo de licencia en su metadata; ambos
   son MIT aguas arriba. Anotado en `NOTICE-ALEPH.md`.
3. **El `NOTICE` del origen debe viajar al `.app`** — es condición del Apache-2.0 de Qlib
   y de la OFL de las fuentes Inter / JetBrains Mono.
4. **`src/channels/utils.py` sobrevive a la amputación de los canales** porque
   `src/security/network.py` y `src/security/workspace_policy.py` re-exportan de ahí la
   validación de URL (anti-SSRF) y la contención de rutas. Sacarlo sería refactor, y la
   importación no refactoriza (Ley 5). Ver `EXTIRPACIONES.md`.
5. **`load_selected_profile_id()` no valida el id** que lee del archivo del usuario; la
   validación vive en `profile_by_id()`, por donde pasan todos los consumidores. No es un
   agujero (probado con un archivo hostil), pero un id arbitrario viaja un tramo.
6. **97 tools y ~220 KB de payload por turno** en el loop interno del stack. No es un
   defecto, pero es contexto que el cerebro de Aleph va a comer en cada iteración.
