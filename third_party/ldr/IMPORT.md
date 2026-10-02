# Local Deep Research — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | `https://github.com/LearningCircuit/local-deep-research` |
| Commit importado | `a734d52913879b82783ddd54e1eacfe809de3c3b` |
| Licencia de código | MIT (`LICENSE`, conservada en la raíz) |
| Titular | LearningCircuit, 2025 |
| Fecha de importación | 2026-08-10 |
| Estudio previo | `~/Desktop/T7-SALA-ESTUDIO.md` (Motor B, §1-§8) |
| Árbol testigo | `~/Desktop/oss-estudio/sala-deepresearch/local-deep-research` (clon somero, mismo commit) |
| Qué es | El motor del **modo Deep Research de LA SALA** (plan §6.f). No es un vertical. |

## Integridad antes de cirugía

Se copiaron los **3.303 archivos rastreados por git** del origen, uno por uno, y se
verificó **sha256 archivo por archivo contra el clon testigo: cero diferencias**.

El manifiesto completo vive en [`MANIFEST.sha256`](MANIFEST.sha256) (3.303 líneas,
formato `sha256␣␣ruta`). Su propio hash:

```
8bade054c28f959e035964a96251d9296b312746b91e7df7ea136891907b3f78
```

No viajaron: `.git/`. No hay `node_modules`, `.venv` ni artefactos de build en el árbol
rastreado del origen (medido: `git ls-files | grep -cE 'node_modules|\.venv'` → 0).

### ⚠️ El `.gitignore` de ellos se come archivos, y hay que saberlo

**Lo trae la pieza y se conserva intacto (Ley 3), pero adentro de nuestro repo GOBIERNA.**
`third_party/ldr/.gitignore:40` trae la regla `/*.*` —todo archivo con punto en el nombre,
en su raíz— y sus reglas de `tests/` se llevan otro tanto.

Los números, medidos sobre el árbol **después** de la cirugía (los de antes están arriba):

| | |
|---|---|
| archivos en disco (sin `.git/`, sin `__pycache__`) | **3.118** |
| rastreados por git | **3.080** |
| **sin rastrear** | **38** |

Ninguno de los 38 es código del motor:

| Qué falta en git | Cuántos | Qué se hizo |
|---|---|---|
| `.gitattributes` de ellos | 1 | queda fuera; declarado |
| READMEs y `package.json` de `tests/`, `golden_master_settings.json`, 5 `DEBUG_*.js`, docs sueltos | 37 | quedan fuera; son andamiaje de su suite, que no se corre |

`IMPORT.md`, `EXTIRPACIONES.md` y `MANIFEST.sha256` —los tres documentos que la Ley 4
exige— también los ignoraba esa regla: entraron con **`git add -f`** y ya están rastreados.
Es lo único que se fuerza.

**La diferencia disco↔git está declarada, no disimulada.** Precedente de la casa: con
OpenScience se aceptó el `.gitignore` del origen como autoridad (sus `node_modules` no
viajaron por esa misma razón, `ATTRIBUTIONS.md`). Acá se acepta igual **para lo suyo** y se
fuerza **sólo lo nuestro**, que es lo que la ley de importación obliga a que exista.

⚠️ **El manifiesto es el testigo de ANTES de la cirugía, y por eso ya no cuadra con el
árbol.** `EXTIRPACIONES.md` borró 38 módulos `.py` y 150 archivos de `web/static` y
`web/templates`; un `shasum -c MANIFEST.sha256` va a reportar esos archivos como faltantes.
**Eso es correcto y es el punto**: el manifiesto prueba que lo que entró era idéntico al
origen, y las extirpaciones prueban qué se le hizo después. Si el manifiesto se
re-generara post-cirugía dejaría de servir para lo único que sirve. Los que quedan siguen
verificando byte a byte.

## Alcance heredado — se importa la LIBRERÍA, no la aplicación

Ésta es la frontera de esta pieza, y se declara acá porque es distinta de las anteriores.

LDR publica **dos superficies**: una aplicación web Flask (con cuentas, login y una base
SQLCipher por usuario) y una **librería Python** con API programática. Aleph hereda **la
librería**. La aplicación web no se instala, no se sirve y no se levanta — su superficie
se extirpa en [`EXTIRPACIONES.md`](EXTIRPACIONES.md).

Lo que Aleph usa:

| Subsistema | Para qué |
|---|---|
| `api/` | los cuatro puntos de entrada programáticos (`quick_summary`, `detailed_research`, `generate_report`, `analyze_documents`) |
| `advanced_search_system/` | el núcleo agéntico y sus estrategias: **5 seleccionables** (`constants.py:123-149`, `AVAILABLE_STRATEGIES`) sobre **6 clases** — la sexta, `EnhancedContextualFollowUpStrategy`, no se ofrece en la lista |
| `web_search_engines/` | los 32 motores de búsqueda de fábrica |
| `llm/` + `config/llm_config.py` | la fábrica única del modelo — **la costura** |
| `mcp/server.py` | su servidor MCP de 8 tools (censado, ver `platform/workspaces/sources.py`) |
| `security/egress/` | su política de egreso, que se conserva entera |

## La costura al cerebro

Una sola: el parámetro `llms=` de su API pública. Aleph registra un cliente
OpenAI-compatible apuntado al **borde de dialecto** y lo pasa por parámetro; LDR lo
guarda en su registro (`src/local_deep_research/llm/llm_registry.py`) y su fábrica
`get_llm()` lo devuelve. **Cero corte de código en el camino del modelo.**

El propio repo declara que los LLM registrados por el operador están **exentos** de su
PEP de egreso (`src/local_deep_research/config/llm_config.py`, rama
`_is_user_registered_llm`): la costura elegida es la que ellos dejaron abierta, no un
rodeo.

## Reproducibilidad de runtime

El origen fija sus dependencias en `pdm.lock` (**312 paquetes**, medidos contra PyPI:
153 MIT · 76 BSD · 52 Apache-2.0 · 8 MPL · 7 PSF · 1 ISC — **cero AGPL, cero SSPL**).
Los tres únicos paquetes con rama copyleft son tri-licenciados con salida no-GPL
(`pyphen`, `tld`, `text-unidecode`).

`requires-python = ">=3.12,<3.15"` (`pyproject.toml`).

## Lo que NO se hereda

- **Su cara.** La UI del deep research ya está construida: es la Sala + el canvas.
- **Su identidad.** Aleph es mono-usuario local (Ley 2.bis).
- **Su elección de modelo.** El cerebro es uno solo y lo pone Aleph (Ley 12).
- **Sus verticales.** Deep Research jamás llega a un workspace por default (plan §6.f).
