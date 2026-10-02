# FASE 3 · BIBLIOTECA DE CAPTURA (§8, el moat) — notas + schema CONGELADO

> Cuando el loop externo §4 (`strategy/`) gana un torneo contra un software, la
> estrategia GANADORA se captura indexada por HUELLA de familia y se REINYECTA en
> software de la MISMA familia → converge en ~1 vuelta en vez de ~5. El motor aprende
> a crackear CATEGORÍAS, no instancias. Base = main 21a656f. Rama `motor-fase3-captura`.

## Frontera (lo que esta lane respeta)
- Módulo NUEVO autocontenido: `platform/inspection/library/`.
- **CERO ediciones fuera de `library/`** (salvo 1 línea en `.gitignore`). La captura y la
  reinyección viven en el CALLER (`reinject.inspect_target`), no en el orquestador.
- LEE (read-only import) `strategy/{types,cascade,rungs,openapi}` y `loop/*`. NO los edita
  ni reconstruye. `loop/*` ni se toca.

## Módulos
| archivo | qué hace | red |
|---|---|---|
| `fingerprint.py` | la HUELLA host→servicio→familia · CLAVE de índice · PURO (solo stdlib) | no |
| `store.py` | el ALMACÉN (json en dir gitignored, índice multi-clave por family_id) + serde + ledger map | no |
| `reinject.py` | el WRAPPER caller-side: `inspect_target` (lookup→reinyecta-1-batch / miss→cascada+captura) | sí |
| `selftest_store.py` | gate OFFLINE 3a (huella cross-host, round-trip, ledger map, flywheel) | no |
| `selftest_reinject.py` | DONE-BAR VIVO 3 (httpbin determinista + pokeapi cerebro→reinyección) | sí |

## La HUELLA (host→servicio→familia) — orden de fuerza
1. `resolved:<server_name>` — el peldaño B resolvió una familia (mcp_resolver, anti-impostor DNS).
2. `doc:<title>@<major>` — `info.title` del doc autodescriptivo. Identifica SELF-HOSTED
   (Odoo/Strapi/Supabase): el host varía por instancia, el doc NO.
3. `host:<sld>` — el SLD (APIs single-instance: AlphaVantage/TMDB). IPs → host entero.

`shape_hash` = sha256 sobre el conjunto ordenado de `MÉTODO template-normalizado`
(ids/números → `{}`) + auth_param. Dos instancias del mismo software → MISMO shape_hash.
**Índice multi-clave:** la entrada canónica vive bajo `family_id`; bajo las claves más
débiles (host) se escriben ALIAS (`{"alias_of": …}`) → la reinyección por host pega GRATIS
(sin sniff) aunque la familia sea doc/resolved.

## Schema de ESTRATEGIA CAPTURADA — **CONGELADO (schema_version 1)**
```jsonc
{
  "schema_version": 1,
  "family_id": "doc:widgetcrm-api@2",      // CLAVE DE ÍNDICE (host-independiente)
  "fingerprint": { "kind":"resolved|doc|host", "host_sld":"…", "doc_title":"…",
                   "doc_version":"2", "resolved_server_name":"", "shape_hash":"sha256:…" },
  "winner_rung": "A|B|C|D|union",
  "ledger_class": "REUSABLE|PARAMETRIZABLE|INSTANCIA",
  "priors": {                               // la RESPUESTA reinyectable
    "auth_param":"api_key", "validate_path":"/things", "validate_query":null,
    "endpoints":[ {"name","kind","endpoint","method","input_schema","description","derived_from"} ],
    "family": null,                         // handoff del resolver (si ganó B)
    "signals":[ {"kind","url_path","status","detail"} ]
  },
  "metadata": {
    "captured_at":"<ISO>", "captured_against":{"host_sld","base_url_redacted"},
    "score":{"verified":N,"winner":"…"},
    "convergence_first":{"rungs_run":[…],"live_calls":N,"synth_tokens":T,"rounds":R,"used_brain":bool},
    "hits": 0                               // veces reinyectada (data-flywheel)
  }
}
```
`priors.endpoints` es forma `CandidateTool` → round-trip directo al candado §3 en la
reinyección (verify-before-trust: si la instancia divergió, los priors caen → fall-through).

## Mapeo PLATFORM-LEDGER
- **REUSABLE** — ganó B (familia resuelta wholesale por el resolver).
- **PARAMETRIZABLE** — priors con plantilla (`{}` / convención): se re-bindean por instancia (caso común).
- **INSTANCIA** — priors concretos puros (ids minados): no reusan limpio.
- **META** — el ÍNDICE en sí + `hits` por familia (`store.stats()`), no per-entry.

## Reinyección (FASE 3c) — mecanismo (`inspect_target`)
1. ANTES de la cascada: lookup host-key (GRATIS) → si falla, 1 sniff del doc → doc-key.
2. HIT → reconstruí priors como CandidateTool → MISMO `LiveValidator` (candado §3) en 1 batch
   → forjá con `MCPEmitter`. SIN A/B/C, SIN D, SIN cerebro, SIN tanteo. `record_hit(+1)`.
3. MISS / priors divergieron → `run_cascade` genérico; si gana → `store.capture(...)`.

El candado de la reinyección usa los MISMOS componentes que `build_context` (provider→sesión
validada+cifrada Fernet, LiveValidator, MCPEmitter); el guard es INYECTABLE (default
`PublicHTTPGuard` fail-closed, idéntico a la cascada). SSRF guard ANTES de cada fetch
(sniff incluido). Cred/sesión → Fernet, nada en claro. Almacén en dir gitignored.

## DONE-BAR (verify-from-environment · el moat PROBADO)
- **OFFLINE** (`selftest_store.py`, 12/12 ✅): dos instancias (hosts distintos, ids concretos
  distintos) de la misma familia → MISMO family_id + shape_hash. Prueba que la huella es de la
  FAMILIA, no la instancia (la generalización cross-host del moat).
- **VIVO httpbin** (✅, determinista, sin cerebro): 1ra vez gana en A + captura; 2da vez host-key
  GRATIS → reinyecta. **B.calls 2 < A.calls 8**, 0 cerebro ambas.
- **VIVO pokeapi** (✅, con shim): 1ra vez A vacío → C/D, el **cerebro** mina 26 endpoints
  (D:23, C:3). 2da vez host-key → reinyecta los 26 priors en 1 batch.

  | | calls | tokens | brain |
  |---|---|---|---|
  | 1ra vez (A) | 57 | 44 650 | **True** |
  | reinyección (B) | **27** | **0** | **False** |

  → **B ≪ A: ~½ las calls, 0 tokens, 0 cerebro.** La reinyección AHORRA cerebro (el punto).

## Scope / handoff
- Done-bar = CONVERGENCIA RELATIVA (B ≪ A), no exhaustividad ni cobertura. No se mapeó software
  gigante (se prueba el MECANISMO, no se repite el costo PokéAPI).
- Las dos instancias VIVAS comparten host loopback no es necesario: la reinyección por host pega
  para repetir el mismo target; la generalización CROSS-HOST (doc-key) se prueba offline. Una prueba
  con DOS servers locales corriendo a la vez exige pasar el guard de loopback → 1 línea aditiva
  `guard=None` en `cascade.build_context` (NO hecha; el wrapper ya acepta `guard=` para su fast-path).
- Throttle: el cerebro es 1 run vivo a la vez (cupo Max); la reinyección lo elude por diseño.
