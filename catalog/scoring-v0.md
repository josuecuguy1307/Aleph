# SCORING v0 — Catálogo con scoring para la Guía-IA

> Misión rnd-curation-belt-curator (FABLE) · 2026-06-11
> **Regla de fuentes:** Tabla A = cada celda con dato lleva fuente fetcheada HOY (2026-06-11);
> celda sin fuente fetcheada = celda vacía honesta (`—`), no inventada.
> Tabla B = reusa verificación ya ejecutada en `catalog/belts/finanzas.md` (sondas F5 del
> 2026-06-11) y `org/artifacts/P015-radar-mecanica.md` (fetches del 2026-06-11); NO se
> re-fetcheó. Lo NUEVO de esta entrega: madurez 1-5, fricción de conexión y semáforo legal
> (de `org/artifacts/P009-semaforo-legal-mapa-mecanica.md`).
> Consumidor: la Guía-IA (squad Guide-AI Research) — selecciona modelo por carril y servers
> por belt usando estas dos tablas.

**Fetches de HOY usados en Tabla A (12):**
groq.com/pricing · gorilla.cs.berkeley.edu/leaderboard.html (BFCL V4 — tabla NO renderiza vía fetch, ver Nota Honesta N1) · benchlm.ai/agentic (act. 2026-06-09) · artificialanalysis.ai/models/{gpt-oss-120b, qwen3-32b-instruct, llama-3-3-instruct-70b, qwen3-8b-instruct, kimi-k2-6, minimax-m3, glm-5} · docs.z.ai/guides/overview/pricing · platform.minimax.io/docs/guides/pricing-paygo · openrouter.ai/moonshotai/kimi-k2.6 · ollama.com/library/qwen3:8b

---

## TABLA A — MODELOS por carril (7 filas × 6 columnas)

Carriles del org (CLAUDE.md §3 + escalera P011 §5): **$0/Groq** (volumen OSS), **local** (drafts/L0), **escalón-premium** (frontera OSS fuera de Groq), **frontier** (Opus/Fable — fuera de scope de esta tabla, ya asignado por CLAUDE.md).

| Modelo | Carril | Benchmark agéntico (fuente HOY) | Precio $/1M in/out (fuente HOY) | Latencia reportada (fuente HOY) | Best-for (carril del org) |
|---|---|---|---|---|---|
| **gpt-oss-120b** | $0/Groq — piso medido | AA Intelligence Index **33 (#5/62)**; incluye τ²-Bench Telecom + Terminal-Bench Hard + GDPval-AA (score por-bench no publicado → `—`) — [AA/gpt-oss-120b](https://artificialanalysis.ai/models/gpt-oss-120b) | **$0.15 / $0.60** — [groq.com/pricing](https://groq.com/pricing) (AA coincide; blended $0.20) | **500 t/s** en Groq ([groq.com/pricing](https://groq.com/pricing)); mediana cross-provider TTFT 0.92s, 334.9 t/s ([AA](https://artificialanalysis.ai/models/gpt-oss-120b)) | **Piso del belt finanzas** (finanzas.md §8): tool-use multi-MCP sostenido en carril near-zero; default de constructores |
| **qwen3-32b** | $0/Groq — respaldo | AA Intelligence Index **15** (fetch reportó "15 / 74 en su clase"; ambigüedad score-vs-rank declarada, ver N2) — [AA/qwen3-32b](https://artificialanalysis.ai/models/qwen3-32b-instruct); τ²/Terminal evaluados, score por-bench `—` | **$0.29 / $0.59** en Groq — [groq.com/pricing](https://groq.com/pricing) · ($0.15/$0.59 en Alibaba — [AA](https://artificialanalysis.ai/models/qwen3-32b-instruct)) | **662 t/s** en Groq ([groq.com/pricing](https://groq.com/pricing)); Alibaba API: TTFT 2.63s, 68.7 t/s ([AA](https://artificialanalysis.ai/models/qwen3-32b-instruct)) | Diversidad de proveedor en el carril $0; 2º modelo del eval P011 |
| **llama-3.3-70b** | $0/Groq — respaldo single-MCP | AA Intelligence Index **14 (#13/39)** — [AA/llama-3.3-70b](https://artificialanalysis.ai/models/llama-3-3-instruct-70b); τ²/Terminal evaluados, score por-bench `—` | **$0.59 / $0.79** en Groq — [groq.com/pricing](https://groq.com/pricing) (mediana providers $0.58/$0.71 — [AA](https://artificialanalysis.ai/models/llama-3-3-instruct-70b)) | **394 t/s** en Groq ([groq.com/pricing](https://groq.com/pricing)); TTFT mediana 1.72s, 85.1 t/s ([AA](https://artificialanalysis.ai/models/llama-3-3-instruct-70b)) | Tareas de UN solo MCP (T1 cierre mensual, finanzas.md §8); el más caro del carril Groq con el índice más bajo → candidato a degradar tras eval P011 |
| **qwen3:8b (local)** | Local — drafts/L0 | AA Intelligence Index **11 (#42/74)** (versión hosted como proxy del local) — [AA/qwen3-8b](https://artificialanalysis.ai/models/qwen3-8b-instruct) | **$0 marginal** (local, Apache-2.0, 5.2GB Q4_K_M, 30.6M pulls) — [ollama.com/library/qwen3:8b](https://ollama.com/library/qwen3:8b) | `—` (latencia local depende del hardware; sin fuente medible hoy. Referencia hosted, NO local: TTFT 3.74s, 39.6 t/s — [AA](https://artificialanalysis.ai/models/qwen3-8b-instruct)) | Drafts internos near-zero. **DESCARTADO como base de belt** (finanzas.md §8: falla multi-MCP y meta-protocolo AV) |
| **Kimi K2.6** (candidato) | Escalón-premium | BenchLM agentic **86% — #10 overall, mejor open-weight del ranking** ([benchlm.ai/agentic](https://benchlm.ai/agentic), act. 2026-06-09) · AA Intelligence Index 54 (#1/89 de su clase) — [AA/kimi-k2-6](https://artificialanalysis.ai/models/kimi-k2-6) | **$0.67 / $3.39** (OpenRouter — [openrouter.ai/moonshotai/kimi-k2.6](https://openrouter.ai/moonshotai/kimi-k2.6)) · AA reporta $0.95/$4.00. Página oficial Moonshot fetcheada HOY pero no renderizó números → celda oficial `—` (N3) | TTFT 2.28s, **54.4 t/s** ([AA](https://artificialanalysis.ai/models/kimi-k2-6)). Verboso: 170M tokens en el eval AA vs 43M mediana → costo efectivo sube | Tareas multi-MCP de alto costo de error (T3 comps) si el eval lo valida vs frontier; el agentic score más alto del lote OSS |
| **MiniMax M3** (candidato) | Escalón-premium | BenchLM agentic **80.2%** ([benchlm.ai/agentic](https://benchlm.ai/agentic)) · AA Intelligence Index **55 (#1/165)** — [AA/minimax-m3](https://artificialanalysis.ai/models/minimax-m3) | **$0.30 / $1.20** (≤512k tokens; cache read $0.06) — página oficial [platform.minimax.io/docs/guides/pricing-paygo](https://platform.minimax.io/docs/guides/pricing-paygo) (búsqueda del día indica que es tarifa con descuento de lanzamiento 50% sobre $0.60/$2.40 — N4) | TTFT 2.61s, **47.5 t/s** ([AA](https://artificialanalysis.ai/models/minimax-m3)) | **Candidato #1 del escalón-premium por ratio agentic/precio** (~3x más barato que Kimi/GLM); contexto 1M tokens. Primero en cola del eval P011 |
| **GLM-5** (candidato) | Escalón-premium | BenchLM agentic **77.5%** ([benchlm.ai/agentic](https://benchlm.ai/agentic)) · AA Intelligence Index 50 (#6/89) — [AA/glm-5](https://artificialanalysis.ai/models/glm-5) | **$1.00 / $3.20** (cache $0.20) — página oficial [docs.z.ai/guides/overview/pricing](https://docs.z.ai/guides/overview/pricing) (AA coincide) | TTFT 1.82s, **73.6 t/s** — el más rápido de los 3 candidatos ([AA](https://artificialanalysis.ai/models/glm-5)) | Alternativa razonadora del escalón-premium cuando la latencia de salida importa (73.6 t/s vs 47-54 de los otros dos) |

### Notas honestas (anti-gaming)
- **N1 — BFCL V4:** la página se fetcheó HOY ([gorilla.cs.berkeley.edu/leaderboard.html](https://gorilla.cs.berkeley.edu/leaderboard.html), V4, act. 2026-04-12) pero la tabla de scores es JS-rendered y NO se obtuvo por fetch → **ninguna celda de esta tabla cita un número BFCL**. Las celdas de τ²-Bench/Terminal-Bench por-modelo quedan `—` porque AA los incorpora al índice sin publicar el score individual en la página fetcheada.
- **N2 — qwen3-32b:** el fetch de AA devolvió "Intelligence Index Score: 15 out of 74 models in its class" — no distingue inequívocamente score 15 vs rank #15. Se registra tal cual; resolver en el próximo tick con la API de AA.
- **N3 — Kimi K2.6 precio oficial:** platform.moonshot.ai → redirect a platform.kimi.ai; la página de pricing fetcheada no expone los números en el HTML servido. Se usa OpenRouter (página de serving real, fetcheada hoy) y AA como segundas fuentes; la celda "precio first-party" queda vacía.
- **N4 — MiniMax M3:** la página oficial muestra $0.30/$1.20 como tarifa estándar ≤512k HOY; fuentes secundarias del día la describen como descuento de lanzamiento (estándar $0.60/$2.40, visible en la misma página para >512k). La Guía debe presupuestar con $0.60/$2.40.

### KILL-LIST Tabla A (candidatos evaluados HOY y descartados)
| Candidato | Por qué se descarta |
|---|---|
| gpt-oss-20b ($0.075/$0.30, 1000 t/s — groq.com/pricing) | Dominado por gpt-oss-120b en el MISMO carril $0; P011 §1 ya lo rankea detrás. No agrega carril nuevo |
| llama-4-scout ($0.11/$0.34 — groq.com/pricing) | Dominado en tool-use/agentic por gpt-oss-120b y qwen3-32b (P011 §1 kill) |
| Qwen3.5 397B Reasoning | BenchLM agentic 69.4% — debajo de los 3 candidatos elegidos, sin carril servible barato verificado hoy |
| GLM-5.1 ($1.40/$4.40 — docs.z.ai) | 40% más caro que GLM-5 sin score agéntico citable fetcheado hoy → no entra sin dato |
| DeepSeek V4 Pro | BenchLM lo menciona ("Best Open Weight", 87) pero AUSENTE del ranking detallado fetcheado → dato no confirmable hoy; vigilancia L1, no tabla |

---

## TABLA B — MCPs: belt finanzas (7) + picks mecánica (3) — 10 filas × 7 columnas

**Verificación reusada, NO re-fetcheada** (instrucción de la misión): sondas F5 y fetches del 2026-06-11 en `catalog/belts/finanzas.md` §1-§7 y `org/artifacts/P015-radar-mecanica.md` §1. Semáforo legal: `org/artifacts/P009-semaforo-legal-mapa-mecanica.md` §2-§3 (cláusulas fetcheadas 2026-06-11).

**Criterio de MADUREZ 1-5 (declarado):**
- **5** = first-party del vendor con mantenimiento activo
- **4** = release estable publicado (PyPI/npm/semver) + activo + sonda F5 real ejecutada
- **3** = beta con adopción alta, o release estable pero con staleness o gate que impidió la sonda
- **2** = beta temprana sin releases formales ni adopción
- **1** = alpha/experimental

**Escala de FRICCIÓN de conexión:** CERO (sin credencial de tercero) < BAJA (key gratis auto-servicio) < MEDIA (infra propia o key+setup) < ALTA (cuenta cloud + configuración) < MUY ALTA (licencia comercial del usuario).

| # | Server | Belt / categoría | Madurez (1-5) | Verificación (fuente) | Fricción de conexión | Semáforo legal (P009) |
|---|---|---|---|---|---|---|
| 1 | excel-mcp-server (haris-musa) | Finanzas / Excel local | **4** — PyPI v1.27.2, 25 tools, activo | test real ✓ end-to-end con fórmula viva `<f>` (finanzas.md §1) | **CERO** — solo `EXCEL_FILES_PATH` (finanzas.md Matriz) | 🟢 VERDE (P009 §3.1: MIT, sin servicio detrás) |
| 2 | mcp-google-sheets (xing5) | Finanzas / Sheets colaborativo | **3** — 903★ MIT, sin sonda (gatea al arranque) | solo-spec; output crudo del intento pegado (finanzas.md §2) | **ALTA** — proyecto Google Cloud + service account/OAuth; decisión del operador (finanzas.md Matriz) | 🟢 VERDE con nota OAuth multiusuario (P009 §3.2) |
| 3 | mcp-stata (tmonk) | Finanzas / econometría | **3** — PyPI v3.3.0, 124 releases, sonda bloqueada por gate | solo-spec; intento de arranque pegado, discovery falla sin binario (finanzas.md §3) | **MUY ALTA** — licencia Stata 17+ del usuario; degradación a Jupyter+statsmodels (finanzas.md §3) | 🟡 AMARILLO (P009 §3.3: EULA §2.7(vii) "embed" ambiguo; consultar StataCorp) |
| 4 | Alpha Vantage marketdata-mcp (oficial) | Finanzas / datos de mercado | **5** — first-party del vendor, opción remota oficial | test real ✓ init+tools/list con key dummy; meta-protocolo de 3 tools descubierto (finanzas.md §4) | **BAJA técnica** (key 1-min) **pero ALTA legal**: uso profesional requiere key/acuerdo comercial (P009 §3.4) | 🔴 ROJO — único rojo: free tier = "personal, non-commercial"; el belt dispara 3/4 criterios de uso comercial. Re-gatear, no sustituir (P009 §3.4) |
| 5 | sec-edgar-mcp (stefanoamorelli) | Finanzas / fundamentals US GAAP | **4** — PyPI, 21 tools, activo | test real ✓ con llamada LIVE a la SEC (AAPL→CIK 0000320193) (finanzas.md §5) | **CERO** — solo `SEC_EDGAR_USER_AGENT` declarativo (finanzas.md Matriz) | 🟢 VERDE — el activo legal del belt: dominio público, 10 req/s (P009 §3.5) |
| 6 | fred-mcp-server (stefanoamorelli) | Finanzas / macro | **3** — v1.0.2, semi-stale 9 meses (vigilar tick) | test real ✓ init+tools/list con key dummy (finanzas.md §6) | **BAJA** — `FRED_API_KEY` gratis (finanzas.md Matriz) | 🟡 AMARILLO (P009 §3.6: aviso no-endorsement OBLIGATORIO en el producto + series de terceros + OFAC) |
| 7 | jupyter-mcp-server (datalayer) | Finanzas / data science | **4** — BSD-3, 18 tools, activo | test real ✓ con ejecución de código en kernel vivo (mean/stdev correctos) (finanzas.md §7) | **MEDIA** — infra propia: JupyterLab 4.4.x + jupyter-collaboration + `JUPYTER_TOKEN`; NO cuenta de tercero (finanzas.md §7) | 🟢 VERDE (P009 §3.7) |
| 8 | matlab-mcp-core-server (MathWorks) | Mecánica / cálculo numérico | **5** — OFICIAL MathWorks, 956★, v0.10.1 (2026-06-10), 17 releases | fetch verificado P015 §1; **sonda F5 PENDIENTE** (sin licencia MATLAB en el entorno) | **MUY ALTA** — MATLAB R2021a+ licenciado del usuario (P015 §1) | 🟢 VERDE (P009 §3.8: BSD-modificada "solely with MathWorks products" — legal exactamente para el uso del belt) |
| 9 | neka-nat/freecad-mcp | Mecánica / CAD open-source | **3** — 1.1k★ (mayor adopción del nicho) pero 0 releases formales | fetch verificado P015 §1; sonda F5 PENDIENTE | **BAJA** — FreeCAD gratis instalado + addons; sin cuenta ni key (P015 §1) | 🟢 VERDE (P009 §3.9: MIT + FreeCAD LGPL local) |
| 10 | hedless/onshape-mcp | Mecánica / CAD cloud | **3** — v0.3.0 semántico, 45 tools, 94★; licencia con defecto de forma | fetch verificado P015 §1; sonda F5 PENDIENTE | **MEDIA-ALTA** — API keys del Developer Portal + plan PAGO Onshape para trabajo comercial (free plan = documentos PÚBLICOS) (P009 §3.10) | 🟡 AMARILLO (P009 §3.10: MIT solo-en-README, LICENSE file 404 → issue de formalización ANTES del wiring; fallback altendky/Apache-2.0) |

**Lectura agregada para la Guía:** 6🟢 / 3🟡 / 1🔴 (P009). Los 2 servers de madurez 5 son first-party de vendor — y los DOS cargan el gate más pesado de su belt (legal ROJO en AV, licencia MUY ALTA en MATLAB): oficialidad ≠ baja fricción.

### KILL-LIST Tabla B (referenciada, no re-litigada)
- **P005 §2 (finanzas, 8 descartados):** negokaz/excel (Windows-only, stale) · SepineTam · freema/gsheets (73★ vs 903★) · yahoo-finance · massive/polygon (meta-tools experimentales) · data-exploration (Python sin sandbox) · xero · ms-365.
- **P015 §2 (mecánica, 6 descartados):** Tsuchijo/matlab-mcp (dominado por el oficial) · GreatApo/FEA-MCP (stale, civil, Windows) · jianzhichun/abaqus (GUI-wrapper, 2 tools) · jango-blockchained/mcp-freecad (redundante) · Joe-Spencer + AuraFriday Fusion (fragmentación) · daobataotie/CAD-MCP (drafting 2D, fuera de scope).

---

## Huecos declarados
- Scores por-benchmark (τ²-Bench, Terminal-Bench, BFCL) por modelo: NO publicados en las páginas fetcheadas hoy → celdas `—`. Próximo paso: corrida propia P011 (la máquina de la verdad es nuestro eval, no el leaderboard ajeno).
- Sondas F5 de los 3 picks de mecánica: pendientes (gates de licencia/cuenta documentados en P015); la madurez de la fila 8-10 es evidencia de repo, no de ejecución.
- Latencia local real de qwen3:8b: requiere medición en el hardware del deploy; sin fuente, sin número.
