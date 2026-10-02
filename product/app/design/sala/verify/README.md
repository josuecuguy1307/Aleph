# La Sala — red de seguridad e2e (verify/)

Batería honesta por la **UI viva** (sala.html real, renderers reales). Pass/fail **por capa**:
motor (JSON de `/v1/puppets/run`) · UI (DOM real, introspección dentro de iframes) · consola
(solo se perdona el favicon; una falla de CDN es una falla real). Cero mocks del producto:
solo F3 stubea la respuesta del motor porque su objeto de prueba es el **contrato de falla
del frontend**.

## Correr

```bash
# 1. stack (cada pieza falla honesta en el preflight si falta):
#    postgres arriba, y:
cd product/backend && PUPPET_HTTP_TIMEOUT=240 PUPPET_BRAIN_SHIM=1 PUPPET_BRAIN_SHIM_MODEL=claude-code-opus-4.8 \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080   # backend (240s: Opus vía shim tarda 60-100s/llamada)
python3 eval/shim_claude_code.py                                          # brain Max :8923
python3 product/app/serve.py                                              # front :8091 (desde el worktree a probar)

# stack ALTERNO (sesiones paralelas — no pisar :8080/:8091/:8923 de otra sesión):
#   SHIM_PORT=8924 python3 eval/shim_claude_code.py
#   PUPPET_BRAIN_SHIM_BASE_URL=http://127.0.0.1:8924/v1 ... --port 8094
#   ALEPH_FRONT_PORT=8095 ALEPH_BACKEND=http://127.0.0.1:8094 python3 product/app/serve.py
#   SALA_FRONT/SALA_BACK/SALA_SHIM apuntan el runner al stack alterno.

# pre-requisitos por caso:
#   R4  → Orthanc vivo (:8042; docker compose en _mcp_install/dicom-mcp/tests) con CT:
#         <python-con-pydicom> verify/_seed_orthanc_ct.py   (idempotente, CT sintético)
#   N2  → stub de Gmail: python3 verify/_gmail_stub_run.py <token-dummy> y el backend
#         booteado con GMAIL_API_BASE=<base_url del stub> (.gmail_stub.json)

# 2. batería (desde la raíz del worktree — playwright resuelve del node_modules raíz;
#    en un worktree nuevo: ln -s <repo-primario>/node_modules node_modules):
node product/app/design/sala/verify/run_all.mjs          # todos
node product/app/design/sala/verify/run_all.mjs f3 f4    # subset
```

## Casos (subset CI-able — corre tras cada ola del sprint)

| caso | modo | qué prueba |
|---|---|---|
| S3 planilla | vivo | run_python+write_xlsx reales → grilla hidratada del .xlsx (≥10 filas) + descarga |
| S6 web | vivo | obra web en iframe aislado con estructura real adentro (h1 + CTA); archivo capturado hidrata el iframe |
| F3 errorcard | stub /run | respuesta vacía → errcard + canvas restaurado + ↻ re-dispara el MISMO pedido |
| F4 gate | vivo | place_order RETENIDA (nunca ejecuta en el run) → tarjeta 🔒 → Aprobar → ✓ Hecho |
| R1-R4 héroes | vivo | regresión build→use de los 4 nichos (FEM CalculiX · Quant yfinance · Bode+DRC ngspice/kicad · DICOM 3D Orthanc) con asserts anti-grift al run record: degraded==null, model_final, toda tool ∈ tools_cabled, obra.type, held vacío + bitácora visible |
| N1 economista | vivo | worldbank_series (World Bank REAL) → *.linechart.json → obra linechart (tipo #11) con procedencia |
| N2 ejecutivo | vivo | cowork gmail: borrador MATERIALIZADO en el stub + send_email HELD + send_count==0 + gate visible |
| N3 dev | vivo | script_runner (sandbox real) → informe con code blocks monoespaciados PLANOS (cero highlight.js) |
| N4 periodista | vivo·GATED | forja DESDE /v1/atoms/catalog (jamás fixture); si los átomos research no están → GATED-SKIP explícito |
| M delegación | vivo | M1 delegación VISIBLE (chip «Le pedí a…» + .ai-deleg) + M2 memoria por task-threading explícito (el dato del turno 1 viaja EN task; gap de memoria automática documentado en el caso — delegation.py RIEL #4/#5, DELEGATION-NOTES.md) |
| L1 conversación | vivo·KNOWN-RED | 8 turnos sobre la MISMA obra: hilo/bitácora/1-obra verdes (8/9) pero la FIDELIDAD DE EDICIÓN falla reproducible — el modelo pierde puntos existentes en ediciones secuenciales (hallazgo de producto, launch-relevante). Fuera del default; correr a demanda |

Los casos vivos corren con puppets QA (`seed_puppets.mjs`, idempotente) cuya receta usa
`alias:'brain'` → shim :8923 (Opus real vía cuenta Max, costo cero) y `fallback:'brain'`
**a propósito**: si el shim cae, el run falla VISIBLE — jamás degradación OSS silenciosa
enmascarando un verde.

## Evidencia

`screenshots/<caso>-{obra,full}.png` + `results/summary.json` (matriz por caso con fallas
nombradas y wall-time). Exit ≠ 0 si algo falló. `.state.json` cachea usuario/puppets QA.

## Presupuestos

El shim corre ~55-65s por turno de Opus: casos vivos hasta 240s. La cola postgres es
compartida → el runner es SIEMPRE secuencial y usa el run síncrono (determinístico).
