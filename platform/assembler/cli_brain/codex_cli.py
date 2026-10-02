#!/usr/bin/env python3
"""codex_cli.py — provider 'Mi Codex': `codex exec` como cerebro por suscripción.

Ground truth (BYO-CLI-GROUND-TRUTH.md §1-§4, sondeado vivo en codex-cli 0.118.0):
- Detección: `codex login status` → "Logged in using ChatGPT" exit 0 / "Not logged in"
  exit 1 (texto plano; el estado se decide por exit code).
- Aislamiento del completion (cada pieza PROBADA):
  · stdin cerrado (si queda abierto, codex espera "additional input from stdin");
  · `-m <modelo>` SIEMPRE explícito (el config.toml del usuario puede fijar un modelo
    inválido para su cuenta — visto vivo: model=gpt-5.4 → 400);
  · MCP del usuario OFF: `-c 'mcp_servers={}'` NO funciona; lo probado es el apagado
    POR SERVIDOR `-c mcp_servers.<name>.enabled=false`. Los nombres se enumeran
    leyendo SOLO los headers `[mcp_servers.X]` del config.toml (regex de líneas de
    sección — jamás se parsean valores ni credenciales);
  · web search OFF: `-c web_search="disabled"` (features.web_search_request está
    deprecado — warning observado vivo);
  · `-s read-only --ephemeral` + cwd vacío efímero: codex no tiene switch documentado
    para quitar la tool shell → contención = jail read-only sin workspace + MCP off +
    web off + instrucción; exec_events cuenta CUALQUIER evento de ejecución del JSONL
    y el harness lo asserta en 0. JAMÁS --dangerously-bypass-approvals-and-sandbox.
- Errores (shapes vivos): evento {"type":"error","message":...} + turn.failed; ventana
  agotada = "You've hit your usage limit for ..." (+ "try again at X") / 429; cuenta
  sin plan Codex = 400 invalid_request_error "The 'X' model is not supported when
  using Codex with a ChatGPT account" → model_error narrado honesto.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from .base import (ERR_MODEL, ERR_MODEL_UNAVAILABLE, ERR_NO_AUTH, ERR_RATE_LIMIT, STATE_AUTH_UNKNOWN,
                   STATE_NO_AUTH, STATE_READY,
                   BrainResult, CliBrainProvider, usage_del_cli)

# Señales de ventana agotada (strings reales del binario 0.118.0 + su propio retry-check).
_THROTTLE_RE = re.compile(r"(hit your usage limit|rate.?limit|429|too many requests|"
                          r"usage limit|quota)", re.I)
_AUTH_RE = re.compile(r"(not logged in|401|unauthorized|login required|token expired)", re.I)
_MODEL_UNAVAILABLE_RE = re.compile(
    r"(model is not supported when using Codex with a ChatGPT account|"
    r"model .{0,100} is not supported when using Codex with a ChatGPT account)", re.I)
_RESET_RE = re.compile(r"try again (?:at|in|later[^\w]?)\s*([^\.\"\n]{0,60})", re.I)
# Eventos del JSONL que implican EJECUCIÓN por parte del CLI (deben ser cero).
_EXEC_EVENT_RE = re.compile(r"(command|exec|shell|patch|apply|mcp_tool|web_search|file_change)", re.I)
# Fallback regex: acepta nombre bare O quoted (TOML obliga a quotear nombres con punto/espacio,
# p.ej. [mcp_servers."corp.tools"]). El grupo captura el interior de las comillas o el bare.
_MCP_SECTION_RE = re.compile(r'^\s*\[mcp_servers\.(?:"([^"]+)"|([^\].\s]+))\s*\]', re.M)


def _codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def _toml_key(name: str) -> str:
    """Segmento de key TOML para el override -c: bare si es un ident simple, quoted si no
    (nombre con punto/espacio/comillas → debe ir entre comillas para que codex lo matchee)."""
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def list_mcp_server_names(config_path: Optional[str] = None) -> list[str]:
    """Nombres EXACTOS de los MCP servers del config del usuario. Preferimos tomllib
    (parseo correcto: nombres quoted-con-punto, tablas inline) y solo enumeramos las
    CLAVES de la tabla mcp_servers — jamás leemos ni logueamos los valores (ahí viven
    env/credenciales). Fallback a regex de headers si tomllib no está o el TOML no parsea.
    El bug del regex viejo (review MED #12): `[^\\].]+` truncaba `"corp.tools"` en `"corp`
    → el flag de apagado no matcheaba y el server real quedaba ENCENDIDO."""
    path = config_path or os.path.join(_codex_home(), "config.toml")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    try:
        import tomllib
        data = tomllib.loads(raw.decode("utf-8", "replace"))
        srv = data.get("mcp_servers")
        if isinstance(srv, dict):
            return [str(k) for k in srv.keys()]  # SOLO las claves; los valores se descartan
    except Exception:
        pass  # tomllib ausente (<3.11) o TOML inválido → fallback regex
    names = []
    for m in _MCP_SECTION_RE.finditer(raw.decode("utf-8", "replace")):
        name = (m.group(1) or m.group(2) or "").strip()
        if name and name not in names:
            names.append(name)
    return names


class CodexCliProvider(CliBrainProvider):
    provider_id = "codex_cli"
    display_name = "Codex"
    response_model_id = "codex-cli"

    def _bin_env_var(self) -> str:
        return "PUPPET_CODEX_BIN"

    def _bin_name(self) -> str:
        return "codex"

    def default_model(self) -> str:
        # The user's Codex config may name a model that is unavailable for this
        # account/client. A blank Aleph selection means the account default,
        # obtained from the CLI itself; an explicit selection remains explicit.
        explicit = (os.environ.get("PUPPET_CODEX_CLI_MODEL") or "").strip()
        if explicit:
            return explicit
        from .codex_models import catalog
        binary = self.binary()
        if not binary:
            return ""
        _ids, account_default = catalog(binary)
        return account_default

    # ── detección ────────────────────────────────────────────────────────────
    def build_detect_argv(self, binary: str) -> list[str]:
        return [binary, "login", "status"]

    def parse_detect(self, returncode: int, stdout: str, stderr: str) -> tuple[str, str, dict]:
        # NO surfaceamos la línea CRUDA del CLI (review LOW #2): una versión futura de codex
        # podría imprimir email/cuenta en `login status`. Derivamos un detail FIJO del método.
        low = ((stdout or "") + " " + (stderr or "")).lower()
        if returncode == 0:
            if "chatgpt" in low:
                return STATE_READY, "sesión activa (ChatGPT)", {"authMethod": "chatgpt",
                                                                 "auth_billing": "subscription"}
            # logueado por API key (no plan ChatGPT) → factura por token, NO por suscripción
            if "api key" in low or "api_key" in low or "apikey" in low:
                return STATE_READY, ("sesión activa (con API key — factura por token, "
                                     "NO por suscripción)"), {"authMethod": "api_key",
                                                              "auth_billing": "api_key"}
            return STATE_READY, "sesión activa", {"auth_billing": "unknown"}
        if _AUTH_RE.search(low):
            return STATE_NO_AUTH, "instalado pero sin sesión — corre `codex login`", {}
        return STATE_AUTH_UNKNOWN, "no pude confirmar la sesión de Codex", {}

    # ── completion ───────────────────────────────────────────────────────────
    def build_argv(self, binary: str, prompt: str, model: str, workdir: str,
                   effort: Optional[str] = None, stream: bool = False,
                   sesion=None) -> list[str]:
        # ── F2e · `sesion` SE ACEPTA Y SE IGNORA. Argv byte-idéntico. ──────────────
        # NO es «codex no tiene sesiones»: SÍ las tiene, y funcionan. Medido el 2026-08-03
        # con `gpt-5.6-luna`: `codex exec resume <thread_id> "<prompt>"` devuelve rc=0,
        # el mismo `thread_id`, e input_tokens 11051 → 22125 con 9984 cacheados — o sea que
        # el contexto viajó. Tres cosas lo dejan afuera de esta fase, y las tres son
        # medidas, no supuestas:
        #
        #   1. **`exec resume` RECHAZA `-s/--sandbox`** (medido: `error: unexpected argument
        #      '-s' found`). `-s read-only` es LA JAULA de este provider —sin writes, sin
        #      red de comandos—. Sin ella el modo de sandbox lo decide `config.toml`, o sea
        #      el usuario, que es exactamente lo que el contrato de pureza no confía. Hay un
        #      sustituto plausible (`-c sandbox_mode="read-only"`, que `resume` sí acepta),
        #      pero verificar que aplica la jaula de verdad es una prueba de seguridad —
        #      intentar escribir y que falle—, no un `rc=0`. NO SE MIDIÓ.
        #   2. **No hay `--session-id`.** El id lo elige codex y sólo se descubre leyendo su
        #      evento `thread.started` — y `usa_stream_json()` de codex sigue en False desde
        #      F2a porque su formato no se midió. Fijar el id nosotros, que es lo que hace
        #      barata a toda esta fase, con codex no se puede.
        #   3. `--ephemeral` (su equivalente de `--no-session-persistence`) también está en
        #      el argv de hoy y habría que sacarlo, con la misma consecuencia de disco.
        #
        # DEUDA DECLARADA: con (1) resuelto por una prueba de jaula real y (2) por el mapa
        # de eventos de codex, esto es la misma fase otra vez y entra igual de barata.
        #
        # ── 2026-08-16 · EL TRANSPORTE YA ESTÁ; LO QUE FALTA SIGUE SIENDO SEGURIDAD ──
        # Desde esta tanda la clave de conversación LLEGA hasta acá: el stack la manda
        # (`X-Aleph-Sesion`), el borde la reenvía y el server la lee. Con Claude eso alcanza
        # y la sesión se reusa. Con codex NO se destraba nada, y por eso `--ephemeral` sigue
        # puesto: las dos que faltan son PRUEBAS DE SEGURIDAD contra el binario, no cableado.
        #
        #   · la jaula: `-c sandbox_mode="read-only"` es un sustituto PLAUSIBLE de `-s`, y
        #     plausible no es medido. La prueba es intentar escribir y que falle, no un rc=0.
        #   · el id: hay que leerlo del evento `thread.started`, y el mapa de eventos de
        #     codex sigue sin medirse (`usa_stream_json()` en False desde F2a).
        #
        # Las dos necesitan la `.app` construida. Sacar `--ephemeral` sin cerrarlas cambia
        # una jaula probada por una supuesta y deja que el CLI escriba en el disco del
        # usuario: eso no es una obra pendiente, es un riesgo tomado sin medir.
        # F2a · `stream` se acepta y se IGNORA a propósito. `codex exec --json` ya emite
        # JSONL, así que la lectura incremental de `_run_streaming` lo beneficia igual (el
        # watchdog y el techo de línea aplican), pero el mapa de sus eventos NO se midió
        # contra el binario en esta fase y `usa_stream_json()` sigue en False: el argv y
        # el `parse_result` de codex quedan byte-idénticos. Adivinar su formato sería
        # exactamente el "traducido a ciegas" que esta fase prohíbe.
        # TICKET 27·3 · codex mapea el effort a su config de razonamiento (si es válido); si no, lo ignora.
        _eff = (effort or "").strip().lower()
        _reason = {"low": "low", "medium": "medium", "high": "high", "max": "high"}.get(_eff)
        argv = [
            binary, "exec",
            "--json",                      # eventos JSONL por stdout
            "--skip-git-repo-check",       # el cwd efímero no es un repo
            "-s", "read-only",             # jail: sin writes, sin red de comandos
            "--ephemeral",                 # nada persiste en disco del usuario
            "--color", "never",
            "-m", model,                   # SIEMPRE explícito (config del usuario no confiable)
            "-c", 'web_search="disabled"',
            "-o", os.path.join(workdir, "last-message.txt"),
        ]
        for name in list_mcp_server_names():
            # key TOML correctamente quoteada (nombres con punto/espacio) → el apagado matchea
            argv += ["-c", f"mcp_servers.{_toml_key(name)}.enabled=false"]
        if _reason:
            argv += ["-c", f'model_reasoning_effort="{_reason}"']   # 27·3 · effort → razonamiento de codex
        argv.append(prompt)
        return argv

    def fin_limpio(self, obj: dict) -> bool:
        """El `turn.completed` de codex.

        ⚠️ ESTE PROVIDER NO TIENE `usa_stream_json` — y no lo gana acá. Reconocer el evento
        terminal NO es traducir su formato: `parse_result` sigue leyendo el stdout crudo
        entero, byte por byte igual que antes. Lo único que se agrega es saber CUÁNDO ese
        stdout ya está completo.

        MEDIDO (codex-cli 0.147.0): un turno limpio cierra con `{"type":"turn.completed",
        "usage":{...}}` como ÚLTIMA línea; uno fallido con `{"type":"turn.failed", ...}`
        precedido de un `{"type":"error"}`. Sólo el primero corta.

        ⚠️ Y POR ESO ESTE PROVIDER NECESITA `al_cosechar`: codex escribe su `-o
        last-message.txt` **252 ms DESPUÉS** del `turn.completed`, y `parse_result` lo lee
        como respaldo del texto del agente. Borrarle el workdir al cortar sería sacarle el
        archivo de abajo mientras lo escribe.
        """
        if not isinstance(obj, dict) or obj.get("type") != "turn.completed":
            return False
        return isinstance(obj.get("usage"), dict)

    def classify_error(self, blob: str, returncode: Optional[int] = None) -> tuple[str, str]:
        blob = blob or ""
        if _THROTTLE_RE.search(blob):
            m = _RESET_RE.search(blob)
            return ERR_RATE_LIMIT, (m.group(1).strip() if m else "")
        if _AUTH_RE.search(blob):
            return ERR_NO_AUTH, ""
        if _MODEL_UNAVAILABLE_RE.search(blob):
            return ERR_MODEL_UNAVAILABLE, ""
        return ERR_MODEL, ""

    def parse_result(self, returncode: int, stdout: str, stderr: str, workdir: str,
                     model: str) -> BrainResult:
        events, text = [], ""
        # F2c · sin dato es None, no cero. `usage_medido` dice si el CLI lo reportó.
        usage, usage_medido = usage_del_cli(None, medido=False)
        model_final, model_src = None, ""
        exec_events, err_msgs = 0, []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            events.append(e)
            etype = str(e.get("type") or "")
            item = e.get("item") or {}
            itype = str(item.get("type") or "")
            if etype == "item.completed" and itype == "agent_message":
                text = item.get("text") or item.get("message") or text
            if etype in ("error", "turn.failed"):
                msg = e.get("message") or (e.get("error") or {}).get("message") or ""
                if msg:
                    err_msgs.append(str(msg))
            if etype == "turn.completed":
                # F2c · mismo no-inventar-cero que claude_cli: el parser comparte el patrón.
                # Un `turn.completed` sin `usage` es ausencia de dato, no un turno de 0 tokens.
                usage, usage_medido = usage_del_cli(e.get("usage"))
                if e.get("model"):
                    model_final, model_src = str(e["model"]), "cli-reported"
            if etype == "thread.started" and e.get("model"):
                model_final, model_src = str(e["model"]), "cli-reported"
            # cualquier ejecución del CLI (comando/patch/mcp/web) — debe ser CERO
            if _EXEC_EVENT_RE.search(etype) or (itype and _EXEC_EVENT_RE.search(itype)):
                exec_events += 1
        if not text:
            # cinturón: el archivo -o con el último mensaje del agente
            try:
                with open(os.path.join(workdir, "last-message.txt"), encoding="utf-8") as f:
                    text = f.read().strip()
            except OSError:
                pass
        if returncode != 0 or (err_msgs and not text):
            blob = "\n".join(err_msgs) or (stderr or "")[:400]
            kind, reset = self.classify_error(blob, returncode)
            return BrainResult(ok=False, error_kind=kind, reset_hint=reset,
                               error_detail=blob[:300], exec_events=exec_events,
                               meta={"events": len(events)})
        if not text:
            return BrainResult(ok=False, error_kind=ERR_MODEL,
                               error_detail="codex exec terminó sin mensaje del agente",
                               exec_events=exec_events, meta={"events": len(events)})
        if not model_final:
            # codex validó el -m pedido (400 explícito si no lo soporta) → en un turn
            # EXITOSO el modelo pedido ES el que corrió. Se declara la fuente honesta.
            model_final, model_src = model, "requested-validated"
        return BrainResult(ok=True, text=text, model_final=model_final,
                           model_final_source=model_src, usage=usage,
                           tokens_medidos=usage_medido,
                           exec_events=exec_events, meta={"events": len(events)})
