#!/usr/bin/env python3
"""grok_cli.py — provider 'Mi Grok': `grok -p` como cerebro por suscripción.

Ground truth (E0/E1.3, grok 1.0.5 · 5115b46bc909), no inventado:
- Binario: PUPPET_GROK_BIN → PATH → ~/.grok/bin/grok
- Detect: `grok models` — exit 0 siempre; "You are logged in with grok.com." vs
  "You are not authenticated."
- Cognición: `-p` + `--output-format streaming-json` (hace falta para VER tools:[])
  + `--agent aleph-zero` (perfil E0: allow ask_user_question + deny de esa misma tool
  y de shell/read/MCP/Agent, mcpInheritance none) + `--permission-mode default`
  + `--no-subagents` + `--no-auto-update`
- JSON: `text` / `usage.{input,output,cache_*,reasoning}_tokens` / `modelUsage`
- Sesión: `--session-id` T1 · `--resume` T2; store `~/.grok/sessions/<cwd-urlencoded>/<id>/`
- Fail-closed: si `available_commands.tools` no es [] o hay tool_call, el turno FALLA.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Optional

from .base import (ERR_MODEL, ERR_NO_AUTH, ERR_RATE_LIMIT, ERR_SESION_PERDIDA,
                   STATE_AUTH_UNKNOWN, STATE_NO_AUTH, STATE_READY,
                   BrainResult, CliBrainProvider, usage_del_cli)

_AUTH_OK_RE = re.compile(r"you are logged in", re.I)
_AUTH_NO_RE = re.compile(r"(not authenticated|please log in|login required|unauthoriz)", re.I)
_THROTTLE_RE = re.compile(r"(rate.?limit|\b429\b|too many requests|quota|usage limit)", re.I)
#: LAS DOS FORMAS MEDIDAS del binario 1.0.5 cuando la sesión no se puede usar, capturadas
#: contra el CLI el 2026-08-25 (no supuestas):
#:
#:   `--resume <id que no está>`   → rc 1, stderr:
#:       «Failed to restore session from remote: fetching session record:
#:        session get failed: 404 Not Found»
#:   `--session-id <id ya usado>`  → rc 1, stderr:
#:       «Error: Session ID <uuid> is already in use.»
#:
#: ⚠️ LA SEGUNDA NO ESTABA, y era la que dejaba la conversación MUERTA PARA SIEMPRE.
#: Medido: la primera la reconocía (`session .{0,80}not found` matchea «session get failed:
#: 404 Not Found»), la segunda NO — así que un turno que moría a mitad dejaba el id
#: quemado, y todos los turnos siguientes de esa charla salían `model_error` en ~1 s con la
#: respuesta vacía. Tres seguidos, medidos. Con la forma reconocida, `server.py` renueva el
#: id y rehace el turno, que es lo que ya hace con claude por este mismo motivo.
_SESION_RE = re.compile(r"(session .{0,80}not found|no session|unknown session"
                        r"|session id .{0,80}? is already in use)", re.I)
_TOOL_EVENT = frozenset({
    "tool", "tool_call", "tool_use", "tool_result", "tool_start", "tool_end",
})

_PERFIL_NOMBRE = "aleph-zero"
_tls = threading.local()


def _perfil_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents", "aleph-zero.md")


def _instalar_perfil(workdir: str) -> str:
    """Copia el perfil E0 al workdir para que `--agent aleph-zero` lo encuentre."""
    src = _perfil_path()
    dest_dir = os.path.join(workdir, ".grok", "agents")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "aleph-zero.md")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(body)
    return dest


def _tls_reset() -> None:
    _tls.advertised = None          # None = no vimos available_commands
    _tls.text = ""
    _tls.exec_events = 0
    _tls.tool_names = []


def _causa_de_sesion(blob: str):
    try:
        from . import sesiones as _s
        return _s.causa_de_resume("", blob[:120])
    except Exception:
        return None


class GrokCliProvider(CliBrainProvider):
    provider_id = "grok_cli"
    display_name = "Grok"
    response_model_id = "grok-cli"

    def _bin_env_var(self) -> str:
        return "PUPPET_GROK_BIN"

    def _bin_name(self) -> str:
        return "grok"

    def _bin_fallbacks(self) -> list[str]:
        return ["~/.grok/bin/grok"]

    def default_model(self) -> str:
        return os.environ.get("PUPPET_GROK_CLI_MODEL", "grok-4.6")

    def build_detect_argv(self, binary: str) -> list[str]:
        return [binary, "models"]

    def parse_detect(self, returncode: int, stdout: str, stderr: str) -> tuple[str, str, dict]:
        blob = (stdout or "") + "\n" + (stderr or "")
        if _AUTH_OK_RE.search(blob):
            extra = {"auth_billing": "subscription"}
            return STATE_READY, "sesión activa (grok.com)", extra
        if _AUTH_NO_RE.search(blob):
            return STATE_NO_AUTH, "instalado pero sin sesión — corre `grok` e inicia sesión", {}
        return STATE_AUTH_UNKNOWN, f"no pude confirmar la sesión (exit {returncode})", {}

    def usa_stream_json(self) -> bool:
        return True

    def parse_stream_line(self, obj: dict) -> tuple[Optional[str], object]:
        tipo = obj.get("type")
        if tipo == "available_commands":
            tools = obj.get("tools") if isinstance(obj.get("tools"), list) else []
            _tls.advertised = list(tools)
            if tools:
                _tls.tool_names = list(tools)
            return "sistema", {"available_commands": True, "n_tools": len(tools)}
        if tipo == "text" and obj.get("data"):
            _tls.text = getattr(_tls, "text", "") + str(obj["data"])
            return "texto", str(obj["data"])
        if tipo == "thought" and obj.get("data"):
            return "pensando", str(obj["data"])
        if tipo in _TOOL_EVENT:
            _tls.exec_events = getattr(_tls, "exec_events", 0) + 1
            name = obj.get("name") or obj.get("tool") or tipo
            _tls.tool_names = list(getattr(_tls, "tool_names", [])) + [str(name)]
            return "sistema", {"tool_event": tipo, "name": name}
        if tipo == "end":
            carga = dict(obj)
            carga["text"] = getattr(_tls, "text", "") or carga.get("text") or ""
            carga["advertised_tools"] = getattr(_tls, "advertised", None)
            carga["tool_calls"] = int(getattr(_tls, "exec_events", 0) or 0)
            return "resultado", carga
        if tipo == "usage":
            return "sistema", {"usage": True}
        return None, None

    def fin_limpio(self, obj: dict) -> bool:
        """El `end` de grok, y sólo con `stopReason` de fin normal.

        MEDIDO (grok 1.0.5): un turno limpio cierra con
        `{"type":"end","stopReason":"end_turn","usage":{...}}` como ÚLTIMA línea. Un turno
        fallido (modelo inválido) **no emite `end` en absoluto** — sale un `{"type":"error"}`
        y después stderr—, así que acá no hay nada que decidir: sin `end`, sin corte.

        `stopReason` se compara contra una lista CERRADA. Cualquier otro motivo de parada
        (que no medimos) se trata como no-limpio y espera el EOF: fail-closed.
        """
        if not isinstance(obj, dict) or obj.get("type") != "end":
            return False
        if str(obj.get("stopReason") or "") not in ("end_turn", "stop"):
            return False
        return isinstance(obj.get("usage"), dict)

    def build_argv(self, binary: str, prompt: str, model: str, workdir: str,
                   effort: Optional[str] = None, stream: bool = False,
                   sesion=None) -> list[str]:
        _tls_reset()
        _instalar_perfil(workdir)
        formato = "streaming-json" if stream else "json"
        argv = [
            binary, "-p", prompt,
            "--model", model,
            "--output-format", formato,
            "--no-auto-update",
            "--agent", _PERFIL_NOMBRE,
            "--permission-mode", "default",
            "--no-subagents",
        ]
        if sesion is None:
            pass
        elif sesion.fresca:
            argv += ["--session-id", sesion.id]
        else:
            argv += ["--resume", sesion.id]
        _eff = (effort or "").strip().lower()
        if _eff in ("low", "medium", "high", "max"):
            argv += ["--effort", _eff]
        return argv

    def classify_error(self, blob: str, returncode: Optional[int] = None) -> tuple[str, str]:
        blob = blob or ""
        if _THROTTLE_RE.search(blob):
            return ERR_RATE_LIMIT, ""
        if _AUTH_NO_RE.search(blob):
            return ERR_NO_AUTH, ""
        return ERR_MODEL, ""

    def parse_result(self, returncode: int, stdout: str, stderr: str, workdir: str,
                     model: str) -> BrainResult:
        blob = (stdout or "") + "\n" + (stderr or "")
        if _SESION_RE.search(blob):
            return BrainResult(
                ok=False, error_kind=ERR_SESION_PERDIDA,
                error_detail="la conversación que se quiso continuar ya no está en el CLI",
                meta={"sesion_perdida": True},
                causa=_causa_de_sesion(blob))
        j = _parse_json_blob(stdout)
        if j is None and returncode != 0:
            kind, reset = self.classify_error(blob, returncode)
            return BrainResult(ok=False, error_kind=kind, reset_hint=reset,
                               error_detail=f"Grok rechazó la solicitud (exit {returncode})")
        if j is None:
            return BrainResult(ok=False, error_kind=ERR_MODEL,
                               error_detail=f"salida no-JSON del CLI: {(stdout or '')[:200]}")

        advertised = j.get("advertised_tools")
        if advertised is None:
            advertised = getattr(_tls, "advertised", None)
        tool_calls = int(j.get("tool_calls") or getattr(_tls, "exec_events", 0) or 0)
        if advertised is None:
            return BrainResult(
                ok=False, error_kind=ERR_MODEL, exec_events=tool_calls,
                error_detail="Grok no anunció available_commands — no puedo confirmar tools=[] "
                             "(fail-closed)",
                meta={"fail_closed": "tools_unconfirmed"})
        if list(advertised):
            return BrainResult(
                ok=False, error_kind=ERR_MODEL, exec_events=max(tool_calls, 1),
                error_detail="Grok anunció tools no vacías — cerebro no es puro: "
                             + ",".join(str(t) for t in advertised[:12]),
                meta={"fail_closed": "tools_advertised", "tools": list(advertised)})
        if tool_calls > 0:
            return BrainResult(
                ok=False, error_kind=ERR_MODEL, exec_events=tool_calls,
                error_detail=f"Grok ejecutó {tool_calls} tool_call(s) — cerebro no es puro",
                meta={"fail_closed": "tool_call"})

        if returncode != 0:
            kind, reset = self.classify_error(blob, returncode)
            return BrainResult(ok=False, error_kind=kind, reset_hint=reset,
                               error_detail=f"Grok rechazó la solicitud (exit {returncode})",
                               exec_events=0)

        text = j.get("text") or getattr(_tls, "text", "") or ""
        mu = j.get("modelUsage") or {}
        model_final, model_src = None, ""
        if isinstance(mu, dict) and mu:
            model_final = max(mu.items(), key=lambda kv: _ctx(kv[1]))[0]
            model_src = "cli-reported"
        usage, medidos = usage_del_cli(j.get("usage"), medido=True)
        return BrainResult(
            ok=True, text=text,
            model_final=model_final, model_final_source=model_src,
            usage=usage, tokens_medidos=medidos,
            exec_events=0,
            meta={"session_id": j.get("sessionId"), "stop_reason": j.get("stopReason"),
                  "advertised_tools": [], "tool_calls": 0},
        )


def _ctx(v) -> int:
    v = v or {}
    if not isinstance(v, dict):
        return 0
    total = 0
    for f in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
              "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        try:
            total += int(v.get(f) or 0)
        except (TypeError, ValueError):
            pass
    return total


def _parse_json_blob(stdout: str):
    raw = (stdout or "").strip()
    if not raw:
        return None
    if raw[0] == "{":
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    # streaming-json entero (tests / fallback): última línea `end` + tools vistas
    advertised = None
    text = ""
    end = None
    calls = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(o, dict):
            continue
        if o.get("type") == "available_commands" and isinstance(o.get("tools"), list):
            advertised = list(o["tools"])
        if o.get("type") == "text" and o.get("data"):
            text += str(o["data"])
        if o.get("type") in _TOOL_EVENT:
            calls += 1
        if o.get("type") == "end":
            end = o
    if end is None:
        return None
    end = dict(end)
    end.setdefault("text", text)
    end["advertised_tools"] = advertised
    end["tool_calls"] = calls
    return end
