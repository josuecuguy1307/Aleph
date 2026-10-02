#!/usr/bin/env bash
# producir_browser.sh — las dependencias de BROWSER USE que faltan en el lib compartido.
# [Gate 4 · Fase 6 · §6.a]
#
# POR QUÉ SÓLO «LAS QUE FALTAN» Y NO LAS 36: el `lib` que Deep Research produce
# (`platform/sala/research/lib`, 535 paquetes) ya cubre la mayoría por solapamiento —
# medido en el build 5 sobre el bundle extraído: 15 de 25 muestreadas ya estaban (dotenv,
# pydantic, openai, httpx, anyio, requests, anthropic, ollama, PIL, click…). Bajar las 36
# duplicaría ~200 MB adentro del onefile, que es justo lo que la poda de §6.f acaba de
# sacar. Se instala SOBRE el mismo lib, sin dependencias, y pip resuelve lo que ya está.
#
# ⚠️ `posthog` NO ESTÁ EN ESTA LISTA, Y ES A PROPÓSITO. Está declarada como extirpación
# (`third_party/browser-use/EXTIRPACIONES.md` §1: telemetría, mismo caso que OpenWork).
# Y no hace falta parchear el árbol importado para que no la use: su import es PEREZOSO y
# está detrás de una guarda —`telemetry/service.py:82-85` sólo hace `from posthog import
# Posthog` si `CONFIG.ANONYMIZED_TELEMETRY`— así que apagarla por entorno
# (`ANONYMIZED_TELEMETRY=false`, que `arranque.sh` exporta) deja el import inalcanzable.
# Árbol ajeno intacto (ley 0), telemetría muerta, y un paquete menos que empaquetar.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$RAIZ/platform/sala/research/lib"
RT="$RAIZ/platform/sala/research/runtime/bin/python3"

morir() { echo "producir_browser: $*" >&2; exit 1; }
decir() { echo "  · $*"; }

[ -x "$RT" ] || morir "falta el runtime compartido ($RT). Se produce con producir_busqueda.sh"
[ -d "$LIB" ] || morir "falta el lib compartido ($LIB). Se produce con producir_research.sh"

# Las versiones son las que FIJA el proyecto importado (`pyproject.toml`), no «la última»:
# un pin que se mueve solo es un build que no se puede reproducir.
PAQUETES=(
  "bubus==1.5.6"          # el bus de eventos del loop — 20 archivos lo importan
  "cdp-use==1.4.5"        # EL QUE MANEJA EL NAVEGADOR (CDP). Indispensable — 25 archivos
  "uuid7==0.1.0"          # ids de turno — 9 archivos
  "mcp==1.26.0"           # el cliente MCP del harness — 4 archivos
  "groq==1.0.0"           # un proveedor de su capa de modelos: el harness ENTERO queda (ley 2)
  "pyotp==2.9.0"          # 2FA de los sitios que el agente visita
  "cloudpickle==3.1.2"
  "markdownify==1.2.2"    # página → markdown, que es lo que el agente lee
  "reportlab==4.4.9"
  # ── TRANSITIVAS QUE `--no-deps` SALTEA Y EL LIB NO TRAE ──────────────────────────
  # No se adivinan: las dijo la verificación por import de este mismo script, que es
  # para lo que existe. `mcp` monta un server ASGI y arrastra starlette.
  "starlette==0.42.0"
  "sse-starlette==2.1.3"
)

decir "instalando ${#PAQUETES[@]} paquetes en el lib compartido (sin deps: ya están)"
"$RT" -m pip install --quiet --no-deps --target "$LIB" --upgrade "${PAQUETES[@]}" \
  || morir "pip falló"

# ── LA VERIFICACIÓN ES POR RESULTADO, NO POR CÓDIGO DE SALIDA ─────────────────────────
# Un `pip install` que devuelve 0 no prueba que el módulo IMPORTE: puede quedar a medio
# instalar, o chocar con una versión que ya estaba. Se importa de verdad, con el mismo
# intérprete y el mismo path que va a usar el pack.
decir "verificando por IMPORT, no por exit code"
PYTHONPATH="$LIB:$RAIZ/third_party/browser-use" ANONYMIZED_TELEMETRY=false \
  "$RT" - <<'PY' || morir "algún módulo no importa después de instalar"
import sys
faltan = []
# ⚠️ EL NOMBRE DEL PAQUETE NO ES EL DEL MÓDULO: el paquete `uuid7` de PyPI instala
# `uuid_extensions` (browser-use hace `from uuid_extensions import uuid7str`). Verificar
# por el nombre del paquete habría dado un falso rojo — o peor, un falso verde si el
# módulo estuviera y el paquete no.
for m in ("bubus", "cdp_use", "uuid_extensions", "mcp", "groq", "pyotp",
          "cloudpickle", "markdownify", "reportlab", "starlette", "sse_starlette"):
    try: __import__(m)
    except Exception as e: faltan.append(f"{m}: {type(e).__name__}")
if faltan:
    print("  ✗ no importan: " + " · ".join(faltan)); sys.exit(1)
# y la prueba que de verdad importa: el Agent, que es lo que el build 5 no pudo construir
from browser_use import Agent, BrowserProfile           # noqa: F401
from browser_use.llm.openai.chat import ChatOpenAI      # noqa: F401
print("  ✓ los 9 importan · Agent, BrowserProfile y ChatOpenAI resuelven")
PY

# posthog NO debe estar. Si aparece, alguien la arrastró como dependencia de otra.
if [ -d "$LIB/posthog" ]; then
  morir "posthog quedó en el lib y está declarada como extirpación (EXTIRPACIONES.md §1)"
fi
decir "✓ posthog ausente, como manda la extirpación"
echo "✓ dependencias de browser use producidas en $LIB"
