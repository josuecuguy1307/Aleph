#!/usr/bin/env python3
"""
session.py — Sesión VIVA del motor de agente de Puppet AI (V2-1, "motor primero").

ADITIVO: NO toca assembler.py. Importa sus building blocks exactamente como lo
hace run_once.py (MCPServer, ToolRegistry, _chat, _load_framing, _load_rag,
_resolve_api_key) cargándolo por ruta de archivo, sin asumir paquete.

Diferencia clave vs run_once.py (one-shot): una `Session` MONTA los MCP servers
del belt al primer uso y los DEJA VIVOS entre mensajes. Cada `send(msg)` corre el
loop de tool-use sobre los mismos servers y el MISMO historial de conversación —
el 2º mensaje NO re-bootea MCPs.

Responsabilidades (D2 del founder):
  (a) montar el belt una sola vez (lazy, al primer send) y mantenerlo vivo;
  (b) send(msg): corre el loop tool-use, devuelve la respuesta final;
  (c) eventos: emite a un callback y los APPENDEA a events.jsonl en el workdir
      ANTES de emitir (turn_started, tool_call_started, tool_call_finished, final);
  (d) gate: el registry se envuelve con make_gated_registry de
      platform/gates/runtime_integration.py. Si el gate decide NEEDS_OK la sesión
      PAUSA con un threading.Event; .approve()/.reject() despausan. Sin OK NO se
      ejecuta JAMÁS (el approval_callback bloquea hasta recibir un veredicto);
  (e) close(): mata los servers.

Público:
    Session(config, *, repo_root, on_event=None, workdir=None,
            matrix=None, deadline_s=600.0)
        .send(message) -> str
        .approve(reason="") / .reject(reason="")     # despausan un gate pendiente
        .pending_approval -> dict | None             # payload del gate en espera
        .events_path -> Path                          # ruta del events.jsonl
        .close()
        context manager (with Session(...) as s: ...)
"""

from __future__ import annotations

import functools
import importlib.util
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional


# ── Carga del assembler y de la integración de gates por ruta de archivo ──────
_THIS_DIR = Path(__file__).resolve().parent
_ASSEMBLER_PATH = _THIS_DIR / "assembler.py"
_REPO_ROOT = _THIS_DIR.parents[1]  # platform/assembler -> repo root
_GATES_INTEGRATION = _REPO_ROOT / "platform" / "gates" / "runtime_integration.py"


def _load_module(name: str, path: Path):
    import aleph_paths
    return aleph_paths.load_module_by_path(name, path)


_asm = _load_module("puppet_assembler", _ASSEMBLER_PATH)
_gates = _load_module("puppet_gates_runtime_integration", _GATES_INTEGRATION)

_transporte_mod = None
_dueno_mod = None


def _dueno():
    """`inspection/dueno.py`, o `None` si no se puede cargar.

    ⚠️ PRIMERO `sys.modules`, y no es prolijidad — es la trampa 1 del acta. El dueño tiene
    ESTADO (tabla de vivos, cosechador, `procesos.jsonl`), y `_load_module` crea un módulo
    NUEVO con el nombre que se le pida: cargarlo por ruta cuando el backend ya lo importó da
    DOS dueños con dos tablas, y `apagar_todo()` barre una y deja viva la otra. `dueno.py` se
    auto-registra bajo `dueno` e `inspection.dueno`; acá se cierra el tercer nombre."""
    global _dueno_mod
    if _dueno_mod is None:
        for _n in ("dueno", "inspection.dueno"):            # el que ya esté vivo GANA
            if _n in sys.modules:
                _dueno_mod = sys.modules[_n]
                break
        else:
            try:
                _dueno_mod = _load_module(
                    "dueno", _REPO_ROOT / "platform" / "inspection" / "dueno.py")
            except Exception:                               # noqa: BLE001
                _dueno_mod = False
    return _dueno_mod or None


def _servidor_stdio(user_id: Optional[str] = None):
    """La clase con la que la Sesión VIVA spawnea sus servers.

    TRES CAPAS, las mismas que el runtime de runs (`recipe_assembler._servidor_stdio`):
      · `ALEPH_DUENO=on` (D5) → se le PIDE al dueño: él posee el proceso, lo anota antes de
        spawnearlo, y al cerrar la Sesión sólo se SUELTA — así una conexión que otro agente
        tiene prestada no se muere porque esta Sesión terminó, que es el objetivo del §7
        paso 4 del diseño.
      · si no → se spawnea acá y el TRANSPORTE lo elige `inspection/transporte.py`.
      · si nada carga → `_asm.MCPServer`. El fallback ES el comportamiento conocido.
    """
    DU = _dueno()
    if DU is not None:
        try:
            if DU.encendido():
                return functools.partial(DU.ServidorPrestado, user_id=user_id,
                                         motivo="sesión")
        except Exception:                                   # noqa: BLE001
            pass
    global _transporte_mod
    if _transporte_mod is None:
        try:
            _transporte_mod = _load_module(
                "puppet_transporte_sesion",
                _REPO_ROOT / "platform" / "inspection" / "transporte.py")
        except Exception:                                   # noqa: BLE001
            _transporte_mod = False
    if not _transporte_mod:
        return _asm.MCPServer
    try:
        return _transporte_mod.servidor_stdio()
    except Exception:                                       # noqa: BLE001
        return _asm.MCPServer

ApprovalGate = _gates.ApprovalGate
OutputScrubber = _gates.OutputScrubber
make_gated_registry = _gates.make_gated_registry


# ── Matriz de gate por defecto: todo auto-ejecuta (segura para el belt echo) ──
# El motor SOPORTA el pausado; la matriz decide qué pausa. Cambiar de nicho =
# cambiar este JSON, no el motor.
_DEFAULT_MATRIX = {
    "levels": {
        "auto-ejecuta": {"copy": "Tu agente lo hace solo.", "requires_ok": False, "blocked": False},
        "confirma-siempre": {
            "copy": "Tu agente te pregunta cada vez, antes de hacerlo.",
            "requires_ok": True, "once_per_session": False, "blocked": False,
        },
    },
    "default_level": "auto-ejecuta",
    "tier": "average",
    "rules": [],
}


def _summarize(value: Any, limit: int = 1200) -> str:
    """Render compacto y truncado de un valor para el transcript/eventos."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# ── Registry de la sesión: gated + emisor de eventos por tool-call ─────────────

def _build_session_registry_cls():
    """
    Construye la clase de registry de la sesión:
        ToolRegistry  ->  GatedRegistry (gate+scrubber+sandbox)  ->  EventingRegistry
    El gate va DEBAJO (decide antes de ejecutar); los eventos los emite la capa
    de arriba envolviendo `call`.
    """
    GatedRegistry = make_gated_registry(_asm.ToolRegistry)

    class _SessionRegistry(GatedRegistry):
        def __init__(self, servers, tool_filters, *, emit, **kwargs):
            super().__init__(servers, tool_filters, **kwargs)
            self._emit = emit
            self.calls: list = []

        def call(self, tool_name: str, arguments: dict) -> str:
            call_id = uuid.uuid4().hex[:12]
            self._emit("tool_call_started", {
                "call_id": call_id,
                "tool": tool_name,
                "args": _summarize(arguments, limit=600),
            })
            t0 = time.perf_counter()
            # GatedRegistry.call: gate -> (pausa vía approval_callback) -> ejecuta -> scrubber
            result = super().call(tool_name, arguments)
            dt = time.perf_counter() - t0
            # ¿el gate frenó? (gate_log lo registra; lo leemos sin acoplar fuerte)
            last_gate = self.gate_log[-1] if self.gate_log else {}
            self.calls.append({
                "tool": tool_name,
                "args": _summarize(arguments, limit=400),
                "result": _summarize(result, limit=1200),
            })
            self._emit("tool_call_finished", {
                "call_id": call_id,
                "tool": tool_name,
                "result": _summarize(result, limit=1200),
                "gate_decision": last_gate.get("decision"),
                "wall_s": round(dt, 3),
            })
            return result

    return _SessionRegistry


_SessionRegistry = _build_session_registry_cls()


# Helper aditivo en el ToolRegistry base para reportar nombres de tools.
def _tool_names(self) -> list:
    return [t["function"]["name"] for t in self._schema]


if not hasattr(_asm.ToolRegistry, "tool_names"):
    _asm.ToolRegistry.tool_names = _tool_names  # type: ignore[attr-defined]


# ── La Sesión ─────────────────────────────────────────────────────────────────

class Session:
    """
    Sesión viva de un agente equipado. Monta el belt una vez, lo deja vivo entre
    mensajes, corre el loop de tool-use por cada send() y emite eventos.
    """

    def __init__(
        self,
        config: dict,
        *,
        repo_root: Optional[Path] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
        workdir: Optional[Path] = None,
        matrix: Optional[dict] = None,
        deadline_s: float = 600.0,
        user_id: Optional[str] = None,
    ):
        self.config = config
        self.repo_root = Path(repo_root) if repo_root else _REPO_ROOT
        self._on_event = on_event
        self.deadline_s = max(5.0, float(deadline_s))
        self._user_id = user_id or config.get("user_id") or config.get("owner") or None

        # workdir donde vive el events.jsonl
        self.workdir = Path(workdir) if workdir else (self.repo_root / ".sessions" / uuid.uuid4().hex[:8])
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.workdir / "events.jsonl"
        self.session_id = uuid.uuid4().hex[:12]

        # gate: la matriz decide qué pausa; el motor soporta el pausado siempre.
        self._matrix = matrix if matrix is not None else _DEFAULT_MATRIX
        self._gate = ApprovalGate(self._matrix)
        self._scrubber = OutputScrubber()

        # estado de pausa por aprobación (threading.Event)
        self._approval_event = threading.Event()
        self._approval_verdict: Optional[bool] = None
        self._pending_payload: Optional[dict] = None
        self._approval_lock = threading.Lock()

        # estado del belt (lazy)
        self._servers: list = []
        self._registry: Optional[_SessionRegistry] = None
        self._booted = False
        self._closed = False

        # historial de conversación: persiste entre send() — clave de la sesión viva
        framing = _asm._load_framing(
            config.get("framing_path"),
            config.get("framing_fallback", "Eres un asistente útil."),
        )
        rag_ctx = _asm._load_rag(config.get("rag_dir"))
        self._messages: list = [
            {"role": "system", "content": framing + rag_ctx},
        ]
        self._turn_counter = 0

    # ── eventos ──────────────────────────────────────────────────────────────

    def _emit(self, kind: str, data: dict) -> None:
        """
        Appendea el evento a events.jsonl ANTES de emitirlo al callback.
        Persistir-antes-de-emitir: si el callback explota, el evento ya quedó.
        """
        evt = {
            "ts": time.time(),
            "session_id": self.session_id,
            "type": kind,
            **data,
        }
        line = json.dumps(evt, ensure_ascii=False)
        # 1) persistir primero
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # 2) emitir después
        if self._on_event is not None:
            try:
                self._on_event(kind, evt)
            except Exception:
                # un callback roto no debe tumbar la sesión
                pass

    # ── gate: callback de aprobación que PAUSA con threading.Event ────────────

    def _approval_callback(self, payload: dict) -> bool:
        """
        Lo invoca el GatedRegistry cuando el gate decide NEEDS_OK. BLOQUEA el hilo
        del loop hasta que .approve()/.reject() pongan un veredicto. SIN OK no
        ejecuta jamás (espera indefinida, o hasta el deadline del send()).
        """
        with self._approval_lock:
            self._pending_payload = payload
            self._approval_verdict = None
            self._approval_event.clear()
        # avisamos que hay un gate esperando (persistido + emitido)
        self._emit("gate_waiting", {"payload": payload})
        # esperamos el veredicto (con tope = deadline del send actual)
        timeout = max(1.0, self._deadline - time.monotonic())
        got = self._approval_event.wait(timeout=timeout)
        with self._approval_lock:
            verdict = bool(self._approval_verdict) if got else False
            self._pending_payload = None
        self._emit("gate_resolved", {"approved": verdict, "timed_out": not got})
        return verdict

    @property
    def pending_approval(self) -> Optional[dict]:
        """Payload del gate que está esperando OK, o None si nada espera."""
        with self._approval_lock:
            return self._pending_payload

    def approve(self, reason: str = "") -> None:
        """Despausa un gate pendiente con un OK. El loop ejecuta la tool."""
        with self._approval_lock:
            self._approval_verdict = True
        self._approval_event.set()

    def reject(self, reason: str = "") -> None:
        """Despausa un gate pendiente con un NO. El loop NO ejecuta la tool."""
        with self._approval_lock:
            self._approval_verdict = False
        self._approval_event.set()

    # ── boot del belt (lazy, una sola vez, queda vivo) ────────────────────────

    def _boot(self) -> None:
        if self._booted:
            return
        belt_path_raw = self.config.get("belt_path", "")
        belt_path = Path(belt_path_raw)
        if not belt_path.is_absolute():
            belt_path = self.repo_root / belt_path
        if not belt_path.exists():
            raise RuntimeError(f"No encontramos el equipo del agente ({belt_path_raw}).")

        mcp_cfg = json.loads(belt_path.read_text(encoding="utf-8"))
        servers_raw: dict = mcp_cfg.get("mcpServers", {})
        tool_filters: dict = self.config.get("tool_filters", {}) or {}

        # boot solo de los servers que el agente usa; si no hay filtros, todos.
        if tool_filters:
            wanted = set(tool_filters.keys())
            servers_raw = {k: v for k, v in servers_raw.items() if k in wanted}

        started: list = []
        skipped: list = []
        # QUIÉN SPAWNEA (D5): con `ALEPH_DUENO=on` se le PIDE al dueño y él posee el proceso;
        # sin la perilla se spawnea acá como siempre. Los dos caminos usan el MISMO transporte
        # (sesión 3 del SDK) — dejar la Sesión en el cliente viejo habría partido el producto
        # en dos transportes según por dónde entrara el usuario.
        #
        # ⚠️ EL `user_id` NO ES OPCIONAL PARA COMPARTIR, y por eso se pasa hasta acá. La clave
        # del dueño es `(user_id, entity_id, huella)`: con `user_id=None` TODAS las Sesiones
        # caen en el mismo balde y dos usuarios distintos compartirían proceso. Hoy la Sesión
        # no inyecta credenciales, así que no hay llave que filtrar — pero sí estado del
        # server (el belt de memoria escribe un archivo, el de filesystem tiene allow-list), y
        # eso ya es cruzar usuarios. Cuando no hay dueño conocido se usa la IDENTIDAD DE ESTA
        # SESIÓN, que comparte entre mensajes (lo que la Sesión ya hacía sola) y con nadie más.
        _Servidor = _servidor_stdio(self._user_id or f"sesión:{self.session_id}")
        try:
            for sname, scfg in servers_raw.items():
                srv = _Servidor(sname, scfg["command"], scfg.get("args", []))
                if srv.start():
                    started.append(srv)
                else:
                    skipped.append(sname)

            if not started:
                raise RuntimeError(
                    "El agente no pudo encender sus herramientas."
                    + (f" No arrancaron: {', '.join(skipped)}." if skipped else "")
                )

            self._servers = started
            self._registry = _SessionRegistry(
                started, tool_filters,
                emit=self._emit,
                gate=self._gate,
                scrubber=self._scrubber,
                sandbox=None,
                approval_callback=self._approval_callback,
            )
        except BaseException:
            # ⚠️ LO QUE YA ARRANCÓ SE SUELTA, PASE LO QUE PASE. Antes, si `_SessionRegistry`
            # levantaba —o si el `raise` de «no arrancó ninguna» ocurría con algunas ya
            # arriba— los servers de `started` quedaban vivos y FUERA de `self._servers`, así
            # que `close()` no los podía soltar nunca: huérfanos con refcount 1 que el
            # cosechador no toca porque figuran prestados. Con `BaseException` para que un
            # `KeyboardInterrupt` a mitad del boot tampoco los deje colgados.
            for srv in started:
                try:
                    srv.stop()
                except Exception:                           # noqa: BLE001 — soltar no falla
                    pass
            self._servers = []
            self._registry = None
            raise
        self._booted = True
        self._emit("belt_ready", {
            "servers": [s.name for s in started],
            "servers_skipped": skipped,
            "tools": self._registry.tool_names(),
        })

    @property
    def booted(self) -> bool:
        return self._booted

    # ── send: corre el loop de tool-use sobre el belt vivo ────────────────────

    def send(self, message: str) -> str:
        """
        Corre un turno completo de tool-use con el mensaje del usuario sobre el
        belt VIVO (lo bootea si es el primer send). Devuelve la respuesta final.
        """
        if self._closed:
            raise RuntimeError("La sesión está cerrada.")

        self._deadline = time.monotonic() + self.deadline_s
        booted_before = self._booted
        self._boot()  # no-op si ya estaba vivo -> el 2º mensaje NO re-bootea

        assert self._registry is not None
        self._messages.append({"role": "user", "content": message})

        base_url = self.config["base_url"]
        model = self.config["model"]
        api_key = _asm._resolve_api_key(self.config)
        max_turns = int(self.config.get("max_turns", 8))
        max_tokens = int(self.config.get("max_tokens", 2048))
        temperature = float(self.config.get("temperature", 0))

        final_answer: Optional[str] = None
        truncated = False

        for turn in range(1, max_turns + 1):
            if time.monotonic() > self._deadline:
                truncated = True
                break

            self._turn_counter += 1
            self._emit("turn_started", {
                "turn": turn,
                "global_turn": self._turn_counter,
                "reused_belt": booted_before,
            })

            resp = _asm._chat(
                self._messages, self._registry.schema(),
                base_url, model, api_key, max_tokens, temperature,
            )
            choice = resp["choices"][0]
            msg = choice["message"]
            finish = choice.get("finish_reason", "")
            self._messages.append(msg)

            if finish == "tool_calls" or (msg.get("tool_calls") and finish != "stop"):
                tool_calls = msg.get("tool_calls", [])
                if not tool_calls:
                    final_answer = msg.get("content", "") or ""
                    break
                for tc in tool_calls:
                    tc_id = tc["id"]
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError, TypeError):
                        fn_args = {}
                    result_text = self._registry.call(fn_name, fn_args)
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_text,
                    })
            else:
                final_answer = msg.get("content", "") or ""
                break
        else:
            truncated = True

        if final_answer is None:
            last = self._messages[-1]
            final_answer = (
                last.get("content", "") if last.get("role") == "assistant" else ""
            ) or "[el agente llegó al límite de pasos sin una respuesta final]"

        self._emit("final", {
            "answer": _summarize(final_answer, limit=4000),
            "turns_truncated": truncated,
        })
        return final_answer

    # ── cierre ────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Mata los MCP servers. Idempotente."""
        if self._closed:
            return
        for srv in self._servers:
            try:
                srv.stop()
            except Exception:
                pass
        self._servers = []
        self._registry = None
        self._booted = False
        self._closed = True
        try:
            self._emit("closed", {})
        except Exception:
            pass

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
