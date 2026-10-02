#!/usr/bin/env python3
"""claude_cli.py — provider 'Mi Claude Code': `claude -p` como cerebro por suscripción.

Ground truth (BYO-CLI-GROUND-TRUTH.md §1-§3, sondeado vivo en claude 2.1.205):
- Detección: `claude auth status` → JSON {loggedIn, subscriptionType, ...}; exit 0/1.
- Pura cognición: `--tools ""` (disable all) + `--strict-mcp-config` (cero MCP del
  usuario) + `--setting-sources ""` (cero settings/HOOKS del usuario — un hook Stop/
  UserPromptSubmit correría shell arbitrario fuera del gate; review HIGH #3) +
  `--no-session-persistence` + `--disallowedTools <lista>` (cinturón y tiradores).
  cwd = dir vacío efímero → sin CLAUDE.md del PROYECTO. NOTA HONESTA (review #5): el
  `~/.claude/CLAUDE.md` GLOBAL del usuario sí puede cargarse (es su propia persona sobre
  su propio cerebro; el gate de Aleph igual intercepta toda tool real). No lo apagamos
  con `--bare` porque eso mataría el OAuth de la suscripción.
- JAMÁS --bare (mata el OAuth de la suscripción) ni skip-permissions (gate duro en base).
- Env SANEADO (base.sanitized_env): sin ANTHROPIC_API_KEY/secretos ambiente → la
  cognición se atribuye a la SUSCRIPCIÓN, no a una key (review HIGH #0/#15).
- model_final REAL: el JSON trae `modelUsage` {id_real: {...}}; si NO hay entrada real
  NO se fabrica (queda None → el server ecoa el wrapper-id y el badge lo rechaza; #10/#11).
- Rate-limit del plan: is_error/api_error_status en el JSON, o exit≠0 con señal de
  límite en stdout/stderr ("usage limit reached", "resets ...", "...|<epoch>").
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import replace
from typing import Optional

from .base import (ERR_ACCESS_DENIED, ERR_AUTH_EXPIRED, ERR_AUTH_UNKNOWN,
                   ERR_CONFIG_INVALID, ERR_MODEL, ERR_NO_AUTH, ERR_NOT_INSTALLED,
                   ERR_PROVIDER, ERR_RATE_LIMIT, ERR_SERVICE_UNAVAILABLE,
                   ERR_SESION_PERDIDA, STATE_AUTH_EXPIRED, STATE_AUTH_UNKNOWN,
                   STATE_CONFIG_INVALID, STATE_NOT_INSTALLED, STATE_NO_AUTH,
                   STATE_READY, BrainResult, BrainStatus,
                   CliBrainProvider, usage_del_cli)

# F2e · los DOS mensajes MEDIDOS del binario 2.1.220 cuando la sesión no se puede usar:
#   `--resume <id>` de algo que no está  → "No conversation found with session ID: <id>"
#   `--session-id <id>` ya usado         → "Session ID <id> is already in use."
# Los dos significan lo mismo para nosotros —hay que empezar una conversación nueva— y
# los dos salen por stderr con rc=1 y **stdout vacío**.
_SESION_RE = re.compile(r"(no conversation found with session id"
                        r"|session id .{0,80}? is already in use)", re.I)


def _causa_de_sesion(blob: str):
    """La causa tipada del fallo de sesión. Import perezoso: `sesiones` importa de `base`,
    y `base` no importa de acá — hacerlo arriba cerraría el círculo."""
    try:
        from . import sesiones as _s                       # noqa: PLC0415
        return _s.causa_de_resume("", blob[:120])
    except Exception:                                      # noqa: BLE001 — jamás rompe el turno
        return None

# Señales de VENTANA DE LA SUSCRIPCIÓN agotada (strings reales del binario 2.1.205:
# "usage limit reached", "Approaching ... usage limit"). SOLO estas se narran como "tu
# ventana se agotó" — señales transitorias del lado del provider (overloaded/529/capacity)
# NO son la ventana del usuario y se clasifican aparte (review LOW #9), para no mentir la causa.
_THROTTLE_RE = re.compile(r"(usage limit|rate.?limit|\b429\b|too many requests|quota)", re.I)
_TRANSIENT_RE = re.compile(r"(overloaded|\b529\b|capacity|temporarily unavailable|"
                           r"service unavailable|\b503\b)", re.I)
_AUTH_RE = re.compile(r"(\"loggedIn\"\s*:\s*false|not logged in|please run /login|"
                      r"invalid api key|authentication_error|oauth token has expired)", re.I)
_EXPIRED_RE = re.compile(r"(?:oauth|auth(?:entication)?|session|token|credential)"
                         r".{0,50}(?:expired|has expired|expiry)|"
                         r"(?:expired|has expired).{0,50}"
                         r"(?:oauth|auth(?:entication)?|session|token|credential)", re.I)
_ACCESS_RE = re.compile(r"(organization has disabled Claude subscription access|"
                        r"subscription access for Claude Code.{0,80}disabled|"
                        r"(?:organization|account|subscription).{0,80}"
                        r"(?:disabled|not entitled|not authorized).{0,60}Claude Code|"
                        r"Claude Code.{0,80}(?:disabled by your organization|"
                        r"not entitled|organization policy restriction))", re.I)
# "resets at 4pm" / "resets in 2h" / formato histórico "...limit reached|<epoch>"
_RESET_AT_RE = re.compile(r"resets?(?:\s+(?:at|in))?\s+([^\n\"\.]{1,60})", re.I)
_RESET_EPOCH_RE = re.compile(r"limit reached\|(\d{9,12})")

# Tools de Claude Code apagadas explícitamente ADEMÁS de --tools "" (defensa en
# profundidad; la lista es la del shim probado eval/shim_claude_code.py).
_DISALLOWED = ["Bash", "BashOutput", "KillShell", "Read", "Edit", "Write", "NotebookEdit",
               "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite", "SlashCommand"]


class ClaudeCliProvider(CliBrainProvider):
    provider_id = "claude_cli"
    display_name = "Claude Code"
    response_model_id = "claude-code-cli"

    def _bin_env_var(self) -> str:
        return "PUPPET_CLAUDE_BIN"

    def _bin_name(self) -> str:
        return "claude"

    def _bin_fallbacks(self) -> list[str]:
        return ["~/.local/bin/claude"]

    def default_model(self) -> str:
        import os
        return os.environ.get("PUPPET_CLAUDE_CLI_MODEL", "opus")

    # ── detección ────────────────────────────────────────────────────────────
    def build_detect_argv(self, binary: str) -> list[str]:
        return [binary, "auth", "status"]

    def parse_detect(self, returncode: int, stdout: str, stderr: str) -> tuple[str, str, dict]:
        blob = (stdout or "") + (stderr or "")
        try:
            j = json.loads(stdout.strip() or "{}")
        except (json.JSONDecodeError, ValueError):
            j = {}
        status_text = " ".join(str(j.get(k) or "") for k in
                               ("status", "reason", "error", "message"))
        expired_field = any(j.get(k) is True for k in
                            ("expired", "sessionExpired", "tokenExpired", "authExpired"))
        if expired_field or _EXPIRED_RE.search(status_text) or _EXPIRED_RE.search(blob):
            return STATE_AUTH_EXPIRED, "la sesión de Claude Code venció; ejecuta `claude auth login` y vuelve a comprobar", {}
        if returncode == 0 and j.get("loggedIn") is True:
            extra = {}
            # Metadatos NO sensibles, útiles para el copy ("tu plan Max"). Jamás tokens.
            for k in ("authMethod", "subscriptionType"):
                if j.get(k):
                    extra[k] = j[k]
            sub = extra.get("subscriptionType")
            # ATRIBUCIÓN HONESTA (review #0/#17): con el env saneado la sesión suele ser
            # OAuth/suscripción; PERO si el CLI reporta authMethod:api_key, la cognición
            # facturaría POR TOKEN a esa key — NO es "$0 por suscripción". Se marca para que
            # el copy del Cuarto NO prometa $0 y el usuario sepa qué está pagando.
            if str(extra.get("authMethod", "")).lower() in ("api_key", "apikey"):
                extra["auth_billing"] = "api_key"
                detail = "sesión activa (con API key — factura por token, NO por suscripción)"
            else:
                extra["auth_billing"] = "subscription"
                detail = f"sesión activa ({sub})" if sub else "sesión activa"
            return STATE_READY, detail, extra
        # El CLI instalado ofrece JSON con `loggedIn`. Un false sin causa significa logout;
        # `expired` exige una señal EXPLÍCITA de vencimiento en campos o texto. Un error
        # desconocido del comando jamás se traduce a logout.
        if j.get("loggedIn") is False or _AUTH_RE.search(blob):
            return STATE_NO_AUTH, "instalado pero sin sesión — ejecuta `claude auth login`", {}
        return STATE_AUTH_UNKNOWN, f"no pude confirmar la sesión (exit {returncode})", {}

    @staticmethod
    def reconcile_failure(result: BrainResult, fresh: BrainStatus) -> BrainResult:
        """Clasifica el fallo con un sondeo NUEVO, sin guardar la salida cruda del CLI.

        Un 403 o 502 por sí solo no prueba entitlement. `ERR_ACCESS_DENIED` sólo sale del
        patrón explícito en este adaptador Y de un auth recién verificado.
        """
        if result.ok:
            return result
        if fresh.state == STATE_NOT_INSTALLED:
            return replace(result, error_kind=ERR_NOT_INSTALLED,
                           error_detail="Claude Code ya no está instalado o no se encuentra en la ruta configurada.")
        if fresh.state == STATE_CONFIG_INVALID:
            return replace(result, error_kind=ERR_CONFIG_INVALID,
                           error_detail=fresh.detail or "La ruta de Claude Code no es válida.")
        if fresh.state == STATE_AUTH_EXPIRED:
            return replace(result, error_kind=ERR_AUTH_EXPIRED,
                           error_detail="La sesión de Claude Code venció. Ejecuta `claude auth login` y vuelve a comprobar.")
        if fresh.state == STATE_NO_AUTH:
            return replace(result, error_kind=ERR_NO_AUTH,
                           error_detail="Claude Code no tiene una sesión activa. Ejecuta `claude auth login` y vuelve a comprobar.")
        if fresh.state != STATE_READY:
            return replace(result, error_kind=ERR_AUTH_UNKNOWN,
                           error_detail="No pude verificar la sesión de Claude Code. Vuelve a comprobar antes de intentarlo otra vez.")
        if result.error_kind == ERR_ACCESS_DENIED:
            return result                 # el patrón explícito ya se observó en este intento
        if result.error_kind in (ERR_MODEL, ERR_NO_AUTH, ERR_AUTH_EXPIRED, ERR_AUTH_UNKNOWN):
            return replace(result, error_kind=ERR_PROVIDER,
                           error_detail="Claude Code no completó la solicitud; la autenticación está activa, pero la causa del proveedor no se pudo confirmar.")
        return result

    # ── completion ───────────────────────────────────────────────────────────
    # ── streaming (F2a) ──────────────────────────────────────────────────────
    def usa_stream_json(self) -> bool:
        return True

    def parse_stream_line(self, obj: dict) -> tuple[Optional[str], object]:
        """UN evento del `stream-json` → (clase, carga). Formas MEDIDAS sobre el binario
        2.1.220 con `--include-partial-messages` (sonda 2026-08-03, prompt trivial):

            {"type":"system","subtype":"init",...}                       → sistema
            {"type":"system","subtype":"status"|"thinking_tokens",...}   → sistema
            {"type":"stream_event","event":{"type":"content_block_delta",
                 "delta":{"type":"text_delta","text":"OK"}}}             → TEXTO
            {"type":"stream_event","event":{... "thinking_delta", "thinking":"..."}} → pensando
            {"type":"assistant","message":{...}}                         → sistema (snapshot)
            {"type":"rate_limit_event","rate_limit_info":{...,"resetsAt":…}} → sistema
            {"type":"result", "is_error":…, "usage":…, "modelUsage":…}   → RESULTADO

        `signature_delta` NO es texto: es la firma criptográfica del bloque de thinking.
        Se ignora explícitamente — mandarla como token sería basura en pantalla.
        """
        tipo = obj.get("type")
        if tipo == "stream_event":
            ev = obj.get("event") or {}
            if ev.get("type") == "content_block_delta":
                d = ev.get("delta") or {}
                dt = d.get("type")
                if dt == "text_delta" and d.get("text"):
                    return "texto", d["text"]
                if dt == "thinking_delta" and d.get("thinking"):
                    return "pensando", d["thinking"]
                return None, None            # signature_delta y cualquier otro: no es texto
            carga = {"stream_event": ev.get("type")}
            if ev.get("type") == "message_start":
                mdl = ((ev.get("message") or {}).get("model") or "")
                if mdl:
                    carga["model"] = mdl
            return "sistema", carga
        if tipo == "result":
            return "resultado", obj
        if tipo in ("system", "assistant", "user", "rate_limit_event"):
            carga = {"type": tipo, "subtype": obj.get("subtype")}
            # el `system/init` declara el modelo que el CLI va a usar: sirve para rotular
            # los chunks en vuelo sin inventar. El model_final autoritativo sale del result.
            if obj.get("model"):
                carga["model"] = obj["model"]
            if tipo == "rate_limit_event":
                info = obj.get("rate_limit_info") or {}
                for k in ("status", "resetsAt", "rateLimitType"):
                    if info.get(k) is not None:
                        carga[k] = info[k]
            return "sistema", carga
        # El evento final puede llegar sin `type` según versión: se reconoce por su forma.
        if "is_error" in obj and ("usage" in obj or "num_turns" in obj):
            return "resultado", obj
        return None, None

    def fin_limpio(self, obj: dict) -> bool:
        """El evento terminal de claude, y SÓLO si dice que salió bien.

        MEDIDO contra el binario 2.1.229 (tres corridas limpias y dos fallidas):
          · limpio  → última línea `{"is_error":false, ..., "usage":{...}}` (a veces con
            `"type":"result","subtype":"success"`, según versión — por eso se mira
            `is_error`, que está en las dos formas, y no el `type`).
          · fallido → la MISMA última línea con `"is_error":true` (modelo inválido,
            `--resume` de una sesión que no está). Ahí devolvemos False a propósito: el
            `parse_result` de este provider entra al camino de error por `returncode != 0`,
            y ese returncode sólo se conoce esperando el EOF.
        """
        if not isinstance(obj, dict):
            return False
        if obj.get("is_error") is not False:
            return False
        # `usage` o `num_turns` es lo que distingue al evento FINAL de cualquier otro que
        # llevara `is_error` — es el mismo discriminante que usa `parse_stream_line`.
        return ("usage" in obj) or ("num_turns" in obj)

    # ── LAS IMÁGENES, POR SU PROPIO CARRIL ───────────────────────────────────
    def soporta_imagenes(self) -> bool:
        """SÍ, y está MEDIDO vivo contra el binario 2.1.229 (sonda 2026-08-26).

        El carril es `--input-format stream-json`: un mensaje `user` por stdin con bloques
        `image` nativos de Anthropic. Las cuatro cosas que había que comprobar, y su
        resultado, con el argv de PRODUCCIÓN entero (`--tools ""`, `--strict-mcp-config`,
        `--setting-sources ""`, `--disallowedTools …`):

          1. la imagen se VE            → PNG magenta sólido, «¿qué color?» → «Magenta»
          2. convive con `--session-id` → mismo «Magenta» con la sesión fijada por nosotros
          3. sobrevive al `--resume`    → turno 2 SIN imagen, «¿qué color tenía?» → «Magenta»
          4. `--input-format stream-json` EXIGE `--output-format=stream-json` (el CLI
             rechaza la otra combinación con un error explícito) → con imágenes el turno
             es SIEMPRE stream, aunque el llamante no haya pedido streaming.
        """
        return True

    def build_stdin(self, prompt: str, imagenes: list) -> Optional[bytes]:
        """El mensaje `user` multimodal que el CLI lee por stdin. Una sola línea JSON.

        El texto va PRIMERO y las imágenes después, en el orden en que `prompt_bridge` las
        sacó: así la marca `⟦imagen 2⟧` del prompt y el segundo bloque `image` de acá son
        la misma cosa. Sin imágenes no se abre stdin (devuelve `None`) y el turno corre por
        el argv de siempre."""
        if not imagenes:
            return None
        bloques = [{"type": "text", "text": prompt}]
        for im in imagenes:
            # [Aleph] UN ADJUNTO NO ES UNA IMAGEN. Los PDF viajan como bloque `document`,
            # que es lo que el modelo sabe leer; mandarlos como `image` no los mostraría y
            # pegarlos en el prompt como base64 dejaba el turno colgado en «working»
            # (medido el 2026-08-29 con un adjunto real en Legal). `clase` la pone
            # `prompt_bridge` al reconocer la parte; sin ella, es una imagen como siempre.
            if im.get("clase") == "document":
                bloques.append({"type": "document",
                                "source": {"type": "base64",
                                           "media_type": im.get("media_type") or "application/pdf",
                                           "data": im.get("data") or ""}})
                continue
            bloques.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": im.get("media_type") or "image/png",
                                       "data": im.get("data") or ""}})
        linea = json.dumps({"type": "user",
                            "message": {"role": "user", "content": bloques}},
                           ensure_ascii=False)
        return (linea + "\n").encode("utf-8")

    def build_argv(self, binary: str, prompt: str, model: str, workdir: str,
                   effort: Optional[str] = None, stream: bool = False,
                   sesion=None, imagenes: Optional[list] = None) -> list[str]:
        # F2a · CONTRATO MEDIDO (reporte 3 §0.3, binario 2.1.220):
        #   `--output-format stream-json` EXIGE `--verbose` — el CLI rechaza la combinación
        #   sin él con un error explícito. `--include-partial-messages` es lo que convierte
        #   un evento-por-mensaje en un evento-por-token; sin él no hay streaming real.
        #   Sin `stream` el argv queda byte-idéntico al de antes.
        formato = (["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
                   if (stream or imagenes) else ["--output-format", "json"])
        # ── EL PROMPT DEJA DE SER UN ARGUMENTO Y PASA A SER STDIN ─────────────────
        # Con imágenes el mensaje es multimodal y no entra en un argv: viaja entero por
        # `--input-format stream-json` (texto + bloques `image`), que `build_stdin` arma.
        # `-p` se queda SIN posicional —medido: el CLI lo acepta y lee de stdin— y el
        # texto NO se duplica en la línea de comandos.
        entrada = (["-p", "--input-format", "stream-json"] if imagenes else ["-p", prompt])
        # ── F2e · LA SESIÓN, FIJADA POR NOSOTROS ──────────────────────────────────
        # `--no-session-persistence` y las sesiones son INCOMPATIBLES por definición
        # (medido: con la flag puesta, el `--resume` siguiente da «No conversation found»).
        # Sin sesión el argv queda byte-idéntico al de siempre, con la flag adentro.
        #   fresca  → `--session-id <uuid NUESTRO>`   (emdash: sessionIdFlag)
        #   seguir  → `--resume <ese uuid>`           (emdash: resumeFlag)
        if sesion is None:
            sesion_argv = ["--no-session-persistence"]    # nada queda en disco del usuario
        elif sesion.fresca:
            sesion_argv = ["--session-id", sesion.id]
        else:
            sesion_argv = ["--resume", sesion.id]
        argv = [
            binary, *entrada,
            "--model", model,
            *formato,
            "--tools", "",                    # TODAS las tools built-in OFF (verificado vivo)
            "--strict-mcp-config",            # ignora los MCP configurados por el usuario
            "--setting-sources", "",          # cero settings/HOOKS del usuario (no shell fuera del gate)
            *sesion_argv,
            "--disallowedTools", *_DISALLOWED,  # cinturón y tiradores
        ]
        # TICKET 27·3 · DIAL DE ESFUERZO: `claude --effort <level>` es un flag REAL del CLI.
        _eff = (effort or "").strip().lower()
        if _eff in ("low", "medium", "high", "max"):
            argv += ["--effort", _eff]
        return argv

    def classify_error(self, blob: str, returncode: Optional[int] = None) -> tuple[str, str]:
        blob = blob or ""
        if _ACCESS_RE.search(blob):
            return ERR_ACCESS_DENIED, ""
        if _THROTTLE_RE.search(blob):
            return ERR_RATE_LIMIT, self._reset_hint(blob)
        if _AUTH_RE.search(blob):
            return ERR_NO_AUTH, ""
        if _TRANSIENT_RE.search(blob):
            return ERR_SERVICE_UNAVAILABLE, ""
        # Otros rechazos permanecen genéricos hasta observar una señal confiable.
        return ERR_MODEL, ""

    @staticmethod
    def _reset_hint(blob: str) -> str:
        m = _RESET_AT_RE.search(blob)
        if m:
            return m.group(1).strip()
        m = _RESET_EPOCH_RE.search(blob)
        if m:
            try:
                dt = datetime.datetime.fromtimestamp(int(m.group(1)))
                return dt.strftime("%H:%M")
            except (ValueError, OverflowError, OSError):
                pass
        return ""

    def parse_result(self, returncode: int, stdout: str, stderr: str, workdir: str,
                     model: str) -> BrainResult:
        if returncode != 0:
            blob = stdout + "\n" + stderr
            # ── F2e · LA SESIÓN QUE YA NO ESTÁ ────────────────────────────────────
            # Va PRIMERO y va acá, no en el server, por dos razones medidas: (a) los
            # strings son de ESTE binario («No conversation found with session ID: …» y
            # «Session ID … is already in use.»), así que el conocimiento es del provider;
            # (b) en este fallo el CLI **no emite JSON** —stdout queda vacío— y por eso
            # `classify_error` lo mandaba a `model_error` con el detalle «Claude Code
            # rechazó la solicitud», que es falso: no rechazó nada, no encontró la charla.
            if _SESION_RE.search(blob):
                return BrainResult(
                    ok=False, error_kind=ERR_SESION_PERDIDA,
                    error_detail="la conversación que se quiso continuar ya no está en el CLI",
                    meta={"sesion_perdida": True},
                    causa=_causa_de_sesion(blob))
            kind, reset = self.classify_error(blob, returncode)
            # El JSON de error de Claude incluye session_id y otros metadatos internos.
            # Nunca lo devolvemos/logueamos crudo por HTTP: el contrato necesita causa y
            # reset, no identificadores de sesión ni un dump truncado.
            if kind == ERR_RATE_LIMIT:
                detail = "la ventana de uso de Claude Code está agotada"
            elif kind == ERR_ACCESS_DENIED:
                detail = "tu organización deshabilitó el acceso de suscripción a Claude Code"
            elif kind == ERR_NO_AUTH:
                detail = "Claude Code perdió la sesión; vuelve a iniciar sesión"
            else:
                status = None
                try:
                    status = (json.loads((stdout or "").strip() or "{}").get("api_error_status"))
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
                detail = f"Claude Code rechazó la solicitud (status {status or f'exit {returncode}'})"
            return BrainResult(ok=False, error_kind=kind, reset_hint=reset,
                               error_detail=detail)
        try:
            j = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as e:
            return BrainResult(ok=False, error_kind=ERR_MODEL,
                               error_detail=f"salida no-JSON del CLI: {e}: {stdout[:200]}")
        if j.get("is_error") or j.get("api_error_status"):
            blob = json.dumps(j)
            kind, reset = self.classify_error(blob)
            if str(j.get("api_error_status")) == "429":
                kind = ERR_RATE_LIMIT
            if kind == ERR_ACCESS_DENIED:
                return BrainResult(ok=False, error_kind=kind,
                                   error_detail="tu organización deshabilitó el acceso de suscripción a Claude Code")
            return BrainResult(ok=False, error_kind=kind, reset_hint=reset,
                               error_detail=f"is_error: {j.get('subtype')}"
                                            f"/{j.get('api_error_status')}")
        # model_final REAL desde modelUsage. OJO (sondeado vivo): el auxiliar haiku puede
        # tener MÁS outputTokens que el cerebro en respuestas cortas → el discriminador
        # robusto es (a) el prefijo del alias pedido si matchea exactamente una entrada,
        # (b) si no, el CONTEXTO cargado (input+cacheRead+cacheCreation): el cerebro
        # siempre carga la conversación; el auxiliar no.
        mu = j.get("modelUsage") or {}
        model_final, model_src = None, ""
        if isinstance(mu, dict) and mu:
            prefix = {"opus": "claude-opus", "sonnet": "claude-sonnet",
                      "fable": "claude-fable", "haiku": "claude-haiku"}.get(model, model)
            matched = [k for k in mu if k.startswith(prefix)]
            if len(matched) == 1:
                model_final = matched[0]
            else:
                def _ctx(v: dict) -> int:
                    v = v or {}
                    total = 0
                    for f in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                              "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                        try:
                            total += int(v.get(f) or 0)
                        except (TypeError, ValueError):
                            pass
                    return total
                model_final = max(mu.items(), key=lambda kv: _ctx(kv[1]))[0]
            model_src = "cli-reported"
        # F2c · SE ACABÓ EL CERO INVENTADO. `usage_del_cli` pone None donde no hay dato y
        # devuelve si SE MIDIÓ. El `result` es el único origen: los deltas del stream traen
        # un `usage` que miente (medido: `message_start` declara output_tokens=4 para una
        # respuesta de 39). `medido=False` cuando el turno no corrió de verdad — un `usage`
        # en ceros junto a `is_error` es la ausencia del dato, no el dato.
        _sano = not (j.get("is_error") or j.get("api_error_status")
                     or str(j.get("terminal_reason") or "").lower() == "api_error")
        _usage, _medidos = usage_del_cli(j.get("usage"), medido=_sano)
        return BrainResult(
            ok=True, text=j.get("result", "") or "",
            model_final=model_final, model_final_source=model_src,
            usage=_usage, tokens_medidos=_medidos,
            exec_events=int(j.get("num_turns", 1) or 1) - 1,  # >1 turno = ejecutó algo (DEBE ser 0)
            meta={"subtype": j.get("subtype")},
        )
