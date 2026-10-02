#!/usr/bin/env python3
"""claude_streamjson.py — Claude como proceso vivo (`claude -p --input-format stream-json`).

MEDIDO (paso 1, claude 2.1.229):
    el proceso queda listo a los ~0,6 s; con el proceso ya tibio el `system/init` llega
    50 ms después del primer mensaje · turno 2 en 1,31-1,45 s

🔴 UNA CONVERSACIÓN POR PROCESO. `--input-format stream-json` es UN stdin: no hay
`session/new` ni `thread/start` que multiplexe. Por eso `multiplexa_sesiones=False` y la
conversación entra en la clave del pool — si no, dos charlas del mismo dueño se pisarían el
historial adentro del mismo proceso.

🔴 LAS BANDERAS QUE **NO** SE PUEDEN PERDER, y que ya vienen de `claude_cli.build_argv`:
`--tools ""` · `--strict-mcp-config` · `--setting-sources ""` · `--disallowedTools <lista>`.
Eso es lo que lo tiene en ~3.705 tokens de preámbulo y en `"tools":[],"mcp_servers":[]`
(medido en el paso 1). Sacarlas acá sería cambiar la pureza del wrapper por velocidad.

⚠️ `--no-session-persistence` **NO** va: con el proceso vivo la conversación vive en el
proceso, y la bandera es del camino de hoy (donde cada turno es un proceso nuevo). Ponerla
acá no rompe nada, pero tampoco dice nada; se omite para que el argv diga la verdad.
"""
from __future__ import annotations

from typing import Optional

from .adaptador import Adaptador, ResultadoTurno
from .vocabulario import ARRANQUE_S, Capabilities, Session

#: La MISMA lista que `claude_cli._DISALLOWED`. Se importa, no se copia: dos listas que
#: tienen que ser iguales son una lista que algún día no lo va a ser.
try:
    from ..claude_cli import _DISALLOWED as DISALLOWED
except Exception:                                           # noqa: BLE001 — import por ruta
    DISALLOWED = ["Bash", "BashOutput", "KillShell", "Read", "Edit", "Write",
                  "NotebookEdit", "Glob", "Grep", "WebFetch", "WebSearch", "Task",
                  "TodoWrite", "SlashCommand"]


class ClaudeStreamJson(Adaptador):
    provider_id = "claude_cli"
    CAPS = Capabilities(
        multiplexa_sesiones=False,      # ← un stdin = una conversación
        streaming_incremental=True,
        interrumpible=False,
        reporta_usage=True,
        campo_cache_lectura="cache_read_input_tokens",
        campo_cache_escritura="cache_creation_input_tokens",
        jaula_por_turno=False,
        tope_sesiones_por_proceso=1,
    )

    @staticmethod
    def config(*, modelo: str, effort: str = "") -> dict:
        return {"cli": "claude", "modelo": modelo, "effort": effort or "",
                # las banderas de pureza entran en la HUELLA para que un proceso levantado
                # sin ellas no pueda ser reusado por un turno que las exige
                "pureza": ["--tools=", "--strict-mcp-config", "--setting-sources=",
                           "--disallowedTools:" + ",".join(sorted(DISALLOWED))]}

    def argv_de_arranque(self) -> list:
        argv = [self.binario, "-p",
                "--input-format", "stream-json",
                "--output-format", "stream-json", "--verbose",
                "--include-partial-messages",
                "--model", (self.cfg.get("modelo") or "opus"),
                "--tools", "",                     # TODAS las built-in OFF
                "--strict-mcp-config",             # cero MCP del usuario
                "--setting-sources", "",           # cero settings/HOOKS del usuario
                "--disallowedTools", *DISALLOWED]
        eff = (self.cfg.get("effort") or "").strip().lower()
        if eff in ("low", "medium", "high", "max"):
            argv += ["--effort", eff]
        return argv

    def saludar(self, plazo: float = ARRANQUE_S) -> None:
        """Abre el proceso y NADA MÁS.

        ⚠️ MEDIDO, y es contraintuitivo: con `--input-format stream-json` claude **no emite
        una sola línea hasta que llega el primer mensaje**. Esperar acá un `system/init`
        sería esperar para siempre. Lo que sí ocurre en esos ~600 ms es el arranque de node
        y la carga de config — y por eso, cuando el mensaje llega a un proceso ya tibio, el
        `init` sale a los 50 ms.
        """
        self.cano.abrir()

    def abrir_sesion(self, ses: Session, plazo: float = ARRANQUE_S) -> None:
        # No hay handshake de sesión: el proceso ES la sesión. El id lo pone claude en su
        # primer `system/init` y se anota ahí.
        ses.id_remoto = ses.id_remoto or None

    def turno(self, ses: Session, prompt: str, on_evento=None,
              plazo: float = 180.0) -> ResultadoTurno:
        estado = {"uso": {}, "texto": "", "fin": None, "modelo": None, "tools": None}

        def _mirar(o: dict) -> None:
            t = o.get("type")
            if t == "system" and o.get("subtype") == "init":
                ses.id_remoto = ses.id_remoto or o.get("session_id")
                estado["tools"] = list(o.get("tools") or [])
                estado["mcp"] = list(o.get("mcp_servers") or [])
            elif t == "stream_event":
                ev = o.get("event") or {}
                if ev.get("type") == "content_block_delta":
                    d = (ev.get("delta") or {})
                    if d.get("type") == "text_delta" and d.get("text") and on_evento:
                        on_evento("texto", d["text"])
                    elif d.get("type") == "thinking_delta" and d.get("thinking") and on_evento:
                        on_evento("pensando", d["thinking"])
                elif ev.get("type") == "message_start":
                    estado["modelo"] = ((ev.get("message") or {}).get("model")) or None
            elif t == "assistant":
                for b in ((o.get("message") or {}).get("content") or []):
                    if isinstance(b, dict) and b.get("type") == "text":
                        estado["texto"] = b.get("text") or estado["texto"]

        try:
            self.cano.escribir({"type": "user",
                                "message": {"role": "user",
                                            "content": [{"type": "text", "text": prompt}]}})
        except Exception as e:                              # noqa: BLE001
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle=f"no pude escribirle a claude: {e}")

        obj, muerto = self._esperar(_es_terminal, plazo, on_linea=_mirar)
        if muerto:
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle="el proceso de claude cerró a mitad del turno")
        if obj is None:
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle=f"claude no cerró el turno en {plazo:.0f} s")
        if obj.get("is_error"):
            return ResultadoTurno(ok=False,
                                  error_detalle=str(obj.get("result")
                                                    or obj.get("subtype") or "")[:300])
        u = dict(obj.get("usage") or {})
        texto = estado["texto"] or str(obj.get("result") or "")
        return ResultadoTurno(
            ok=True, texto=texto,
            model_final=estado["modelo"],
            usage_bruto=dict(u),          # crudo: `usage_del_cli` conoce sus nombres
            cache_lectura=u.get("cache_read_input_tokens"),
            cache_escritura=u.get("cache_creation_input_tokens"),
            razonamiento=((u.get("output_tokens_details") or {}).get("thinking_tokens")),
            tokens_medidos=bool(u),
            exec_events=0,
            meta={"advertised_tools": estado.get("tools"),
                  "mcp_servers": estado.get("mcp"),
                  "api_ms": obj.get("duration_api_ms")})


def _es_terminal(o: dict) -> bool:
    """El evento final de claude, en las DOS formas que emite según versión: con `type`
    (`result`) y sin él (se reconoce por `is_error` + `usage`/`num_turns`). Es el mismo
    discriminante que `claude_cli.parse_stream_line`."""
    if o.get("type") == "result":
        return True
    return "is_error" in o and ("usage" in o or "num_turns" in o)


__all__ = ["ClaudeStreamJson"]
