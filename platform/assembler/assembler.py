#!/usr/bin/env python3
"""
Puppet AI — Generic Agent Assembler
Reads a config.json, spawns MCP servers, builds tool registry, runs tool-use loop.

Usage:
    python assembler.py <config.json> "<prompt>"

All domain-specific constants (model, base_url, belt path, framing, tool filters, RAG dir)
live in config.json — zero niched constants in this file.
"""

import json
import os
import select
import subprocess
import sys
import threading
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Optional

# ── EL PUENTE BYO LO SIRVE EL SIDECAR ─────────────────────────────────────────
# Import DURO, al revés que el traductor de abajo, y por una razón: si este módulo no está,
# toda pieza HTTP del usuario se lanza con un `python3` externo que no puede leer el PYZ y
# muere en `arranque`. Eso ya pasó y costó la clase HTTP entera (Obra 5/6a). Un ImportError
# acá es ruidoso y correcto; un `None` silencioso volvería a esconderlo.
_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))
import puente_sidecar  # noqa: E402

# ── EL SOBRE DEL TURNO ────────────────────────────────────────────────────────
# Plano y con rescate, como el traductor y el registro de abajo: este archivo se corre
# suelto, se carga por ruta desde el sidecar congelado y viaja en el PYZ. Sin el módulo, el
# pedido al `:8926` sale sin id de intento ni deadline —el estado que medimos, un deadline
# nuevo por ejecución— pero el turno CORRE igual: el sobre mejora el corte, no lo habilita.
try:
    import sobre_turno as _sobre_turno            # type: ignore
except ImportError:                               # pragma: no cover
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sobre_turno as _sobre_turno        # type: ignore
    except ImportError:
        class _SinSobre:                          # el turno sigue, sin sobre
            @staticmethod
            def cabeceras(_es_cli): return {}
            @staticmethod
            def campos_del_cuerpo(_es_cli): return {}
        _sobre_turno = _SinSobre()                # type: ignore

# ── EL TRADUCTOR (Gate 2 · F1) ────────────────────────────────────────────────
# Import BLANDO y a propósito. `assembler.py` se corre suelto (`python assembler.py
# config.json "prompt"`), se carga por ruta desde el sidecar congelado, y viaja en el
# bundle. Si el traductor no está —un árbol a medias, una copia vieja— este archivo tiene
# que seguir funcionando exactamente como antes de F4a, no reventar en el import.
# `_traductor is None` es la rama de compatibilidad, y está probada.
try:
    import errores_modelo as _traductor          # type: ignore
except ImportError:                              # pragma: no cover
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import errores_modelo as _traductor      # type: ignore
    except ImportError:
        _traductor = None                        # type: ignore

# ── EL REGISTRO DE OBRAS EN VUELO (Gate 4 · F5 · 5.2) ─────────────────────────
# Import blando por el mismo motivo que el traductor: este archivo corre suelto y viaja en
# el bundle. Sin el módulo, `_turnos_obra` es un objeto mudo cuyos métodos no hacen nada, y
# el camino es byte-idéntico al de antes de esta obra.
try:
    import turnos_obra as _turnos_obra           # type: ignore
except ImportError:                              # pragma: no cover
    class _SinRegistro:
        def atar_socket(self, _resp): pass
        def soltar_socket(self): pass
        def fue_detenido(self, _c=None): return False
    _turnos_obra = _SinRegistro()                # type: ignore


def _detenido_por_el_usuario() -> Exception:
    """El corte que pidió una persona, TIPADO — con una causa que YA EXISTE.

    `turno_detenido` está en el vocabulario cerrado desde F2d y tiene copy en las dos
    superficies, así que acá no se inventa nada: se reusa lo que el chat ya usa
    (`stream_chat._detenido`), para que parar una OBRA y parar un CHAT se lean igual.

    `reintentable=True` a propósito: el turno no falló, lo pararon. Volver a mandarlo es
    perfectamente sensato y esconderle el botón a alguien que sólo cambió de opinión sería
    tratar su decisión como un error.
    """
    if _traductor is None:                       # pragma: no cover — árbol a medias
        return RuntimeError("turno detenido")
    try:
        return _traductor.ErrorDeModelo(
            _traductor.CausaModelo(
                causa=_traductor.TURNO_DETENIDO, estado=_traductor.ROTO,
                detalle="Paraste este turno.", evidencia={"origen": "usuario"},
                reintentable=True, fuente=_traductor.FUENTE_URLLIB),
            "turno detenido")
    except Exception:                            # noqa: BLE001 — tipar jamás rompe el turno
        return RuntimeError("turno detenido")


# ── MCP STDIO CLIENT ─────────────────────────────────────────────────────────
# ⚠️ LEGACY — SÓLO FALLBACK. SE RETIRA POST-CERTIFICACIÓN. NO AGREGAR CONSUMIDORES.
#
# Desde la sesión 3 del SDK, el camino real es `inspection/transporte_sdk.ServidorSDK`.
# `MCPServer` ya no lo alcanza nadie del producto: el único que devuelve esta clase es
# `inspection/transporte.py::servidor_stdio()`, y sólo con `ALEPH_TRANSPORTE=viejo`.
# Existe para eso, y sólo para eso: el rollback de un click mientras la certificación final
# en la `.app` no pase. Después se borra junto con `mcp_http_client`.
#
# Para spawnear un server MCP, andá por `inspection.transporte`. Un uso directo vuelve a
# partir el producto en dos transportes, y lo caza `test_frontera_transporte.py`.

class MCPServer:
    """Manages one MCP server subprocess over JSON-RPC 2.0 stdio."""

    STDERR_MAX_BYTES = 32 * 1024
    STDERR_MAX_LINES = 80
    PROTOCOL_VERSION = "2024-11-05"
    # El cliente sólo usa initialize, notifications/initialized, tools/list y
    # tools/call: ese subconjunto es compatible en estas dos revisiones. Un server
    # puede negociar 2025-03-26 aunque le pidamos 2024-11-05; eso no es por sí solo
    # una rotura. Revisiones que no declaramos acá siguen fallando cerradas.
    SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26"})

    def __init__(self, name: str, command: str, args: list, env: Optional[dict] = None,
                 rpc_timeout: float = 30.0, cwd: Optional[str] = None):
        self.name = name
        # EL ÚNICO PUNTO DONDE SE DECIDE QUÉ PROCESO SE LANZA. `normalizar_cmd` sólo toca el
        # puente BYO y sólo congelado (ver `puente_sidecar`); cualquier otro comando pasa
        # intacto. Va acá y no en el call-site porque los call-sites son muchos y uno que se
        # olvide vuelve a dejar una pieza HTTP lanzándose con un python3 que no existe.
        self._cmd = puente_sidecar.normalizar_cmd([command] + list(args or []))
        # Even the explicitly selected legacy transport must not turn `None`
        # into Popen's ambient host environment. Use the same bounded baseline
        # and declared per-server values as the SDK transport.
        from inspection.transporte_sdk import entorno_hijo
        self._env = entorno_hijo(env)
        # cwd: directorio de trabajo del hijo. None = hereda el del padre (default de
        # Popen), que es el comportamiento de siempre. El registro (CONTRACT-CONEXION-v1
        # §1) puede declararlo; antes de esto el ejecutor no podía honrarlo y la
        # restauración caía al camino viejo cuando aparecía.
        self._cwd = cwd
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._req_id = 0
        self._rpc_timeout = max(0.1, float(rpc_timeout))
        self._stderr_lines = deque()
        self._stderr_bytes = 0
        self._stderr_lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None
        self._last_exit_code: Optional[int] = None
        self._last_rpc_response: Optional[dict] = None
        self._last_start_error: str = ""
        self._protocol_evidence: dict = {"cliente": self.PROTOCOL_VERSION}

    def _record_protocol_response(self, response: Optional[dict]) -> None:
        """Conserva la negociación sin adivinar versiones ausentes.

        Desde MCP 2026-07-28, UnsupportedProtocolVersion (-32022) expone
        ``data.requested`` y ``data.supported``. En revisiones legacy, el
        ``initialize`` exitoso devuelve ``result.protocolVersion``.
        """
        if not isinstance(response, dict):
            return
        self._last_rpc_response = response
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        result = response.get("result") if isinstance(response.get("result"), dict) else {}

        requested = data.get("requested")
        if isinstance(requested, str) and requested:
            self._protocol_evidence["cliente"] = requested

        supported = data.get("supported")
        if isinstance(supported, list):
            versions = [v for v in supported if isinstance(v, str) and v]
            if versions:
                self._protocol_evidence["servidor"] = versions[0]
                self._protocol_evidence["servidor_soportadas"] = versions

        negotiated = result.get("protocolVersion")
        if isinstance(negotiated, str) and negotiated:
            self._protocol_evidence["servidor"] = negotiated

        if error.get("code") == -32022 or (
            isinstance(negotiated, str)
            and negotiated
            and negotiated not in self.SUPPORTED_PROTOCOL_VERSIONS
        ):
            self._protocol_evidence["incompatible"] = True
            self._protocol_evidence["negociacion"] = "fallida"
        elif isinstance(negotiated, str) and negotiated:
            self._protocol_evidence.pop("incompatible", None)
            self._protocol_evidence["negociacion"] = "aceptada"

    def _capture_stderr(self) -> None:
        """Drena stderr mientras el server vive.

        Un PIPE sin lector puede llenar el buffer del kernel y colgar al propio MCP. Por eso
        no alcanza con cambiar DEVNULL por PIPE: el drenaje es concurrente y el buffer que
        conservamos es una cola acotada de las últimas líneas, también acotada por bytes.
        """
        proc = self._proc
        stream = proc.stderr if proc else None
        if stream is None:
            return
        try:
            while True:
                raw = stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                size = len(line.encode("utf-8", "replace")) + 1
                with self._stderr_lock:
                    self._stderr_lines.append((line, size))
                    self._stderr_bytes += size
                    while (len(self._stderr_lines) > self.STDERR_MAX_LINES
                           or self._stderr_bytes > self.STDERR_MAX_BYTES):
                        _old, old_size = self._stderr_lines.popleft()
                        self._stderr_bytes -= old_size
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def diagnostico(self) -> dict:
        """Evidencia pública y acotada del último proceso.

        `exit_code=None` significa que el proceso seguía vivo cuando se tomó la muestra;
        nunca se convierte en un cero inventado.
        """
        proc = self._proc
        code = proc.poll() if proc is not None else self._last_exit_code
        if code is not None:
            self._last_exit_code = code
            t = self._stderr_thread
            if t and t.is_alive():
                t.join(timeout=0.25)
        with self._stderr_lock:
            stderr = "\n".join(line for line, _size in self._stderr_lines)
            lines = len(self._stderr_lines)
            size = self._stderr_bytes
        # Knob exclusivamente de calibración negativa: la vara frozen lo activa y exige
        # que SU aserción deje de pasar. Sin esto, una vara podría quedar verde por suerte
        # aunque nadie estuviera capturando stderr.
        if os.environ.get("ALEPH_DIAGNOSTICO_DESCARTAR_STDERR", "").strip() == "1":
            stderr = ""
        out = {
            "stderr": stderr,
            "exit_code": code,
            "stderr_lineas": lines,
            "stderr_bytes": size,
            "stderr_cap_bytes": self.STDERR_MAX_BYTES,
            "stderr_cap_lineas": self.STDERR_MAX_LINES,
            "command": self._cmd[0] if self._cmd else "",
        }
        if self._last_rpc_response is not None:
            out["respuesta"] = self._last_rpc_response
        if self._last_start_error:
            out["detail"] = self._last_start_error
        if self._protocol_evidence:
            out["protocolo"] = dict(self._protocol_evidence)
        return out

    @property
    def pid(self):
        """El pid del proceso MCP, o `None` si todavía no arrancó.

        ── POR QUÉ EXISTE (paso 6 · el arranque del cinturón) ────────────────────
        El dueño atribuye los pids de dos maneras: si el servidor SABE SU PID se lo
        pregunta; si no, los descubre por DIFF de sus hijos, y ese diff exige un lock
        global que —hasta esta obra— cubría `start()` ENTERO, o sea también el handshake.
        Con ocho piezas de cinturón eso anula el `ThreadPoolExecutor(8)` del restaurador y
        el arranque se hace EN FILA.

        MEDIDO con fixtures que duermen 1,5 s en su saludo (no con servers reales: la MISMA
        pieza real dio 7.738 ms en frío y ~300 ms en caliente, así que el veredicto lo
        decidiría el caché de uv y no el código):

            5 piezas × 1,5 s  ·  en fila 8,11 s  ·  con el pid propio ~1,5 s

        Este cliente SIEMPRE tuvo el `Popen` en la mano: el pid estaba y no lo exponía.
        No hacía falta un mecanismo nuevo — le faltaba el getter.
        """
        p = self._proc
        return getattr(p, "pid", None) if p is not None else None

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
            )
            self._stderr_thread = threading.Thread(
                target=self._capture_stderr,
                name=f"mcp-stderr-{self.name}",
                daemon=True,
            )
            self._stderr_thread.start()
            resp = self._rpc("initialize", {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "puppet-assembler", "version": "1.0"},
            }, timeout=self._rpc_timeout)
            self._record_protocol_response(resp)
            if resp and "result" in resp:
                negotiated = (resp.get("result") or {}).get("protocolVersion")
                if (
                    isinstance(negotiated, str)
                    and negotiated not in self.SUPPORTED_PROTOCOL_VERSIONS
                ):
                    self._last_start_error = (
                        f"el servidor respondió con una versión MCP no soportada: {negotiated}"
                    )
                    print(
                        f"[MCP] {self.name}: INIT FAILED — protocol "
                        f"{negotiated} fuera de "
                        f"{sorted(self.SUPPORTED_PROTOCOL_VERSIONS)}",
                        file=sys.stderr,
                    )
                    return False
                info = resp["result"].get("serverInfo", {})
                print(f"[MCP] {self.name}: INIT OK — {info.get('name','?')} {info.get('version','?')}", file=sys.stderr)
                self._notify("notifications/initialized", {})
                return True
            if isinstance(resp, dict) and resp.get("error"):
                self._last_start_error = (
                    "el servidor rechazó el saludo MCP: "
                    + json.dumps(resp["error"], ensure_ascii=False, sort_keys=True)
                )
            else:
                self._last_start_error = (
                    "el proceso arrancó pero no respondió al saludo initialize de MCP"
                )
            print(f"[MCP] {self.name}: INIT FAILED — {resp}", file=sys.stderr)
            return False
        except Exception as e:
            self._last_start_error = f"no pude iniciar el proceso MCP: {type(e).__name__}: {e}"
            print(f"[MCP] {self.name}: start error — {e}", file=sys.stderr)
            return False

    def list_tools(self) -> list:
        resp = self._rpc("tools/list", {}, timeout=self._rpc_timeout)
        if not resp or "result" not in resp:
            return []
        return resp["result"].get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        # ── [Gate 4 · F5 · 5.2 · D7] EL RELOJ DE LA TOOL ERA 30 s Y NADIE PODÍA MOVERLO ──
        # `_rpc` declara `timeout: float = 30.0` en su firma, y acá se lo llamaba SIN
        # pasarle nada: o sea que `self._rpc_timeout` —el que el constructor acepta, el que
        # el restaurador propaga, el que una receta podría subir— gobernaba el `initialize`
        # (:236) y el `tools/list` (:275) **y no gobernaba las tool-calls**, que son las
        # únicas que pueden tardar de verdad.
        #
        # El efecto medido: una tool que trabaja más de 30 s devuelve
        # `[MCP error: no response from …]` y el agente lo lee como un fallo del conector.
        # Con motores pesados (CFD, render, FEM) eso no es un borde: es el caso normal —
        # y era la mitad del «con motores pesados es crítico» que abrió esta obra.
        #
        # El default sigue siendo 30 s (`__init__:96`), así que sin tocar la config nada
        # cambia: lo que cambia es que ahora la perilla EXISTE de verdad.
        resp = self._rpc("tools/call", {"name": tool_name, "arguments": arguments},
                         timeout=self._rpc_timeout)
        if resp is None:
            return f"[MCP error: no response from {self.name}]"
        if "error" in resp:
            return f"[MCP error: {resp['error']}]"
        result = resp.get("result", {})
        is_err = result.get("isError", False)
        content = result.get("content", [])
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        raw = "\n".join(text_parts) if text_parts else json.dumps(result)
        return f"[tool error] {raw}" if is_err else raw

    def stop(self):
        if self._proc:
            proc = self._proc
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            self._last_exit_code = proc.poll()
            t = self._stderr_thread
            if t and t.is_alive():
                t.join(timeout=0.5)
            self._proc = None

    # ── internal ──

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _rpc(self, method: str, params: dict, timeout: float = 30.0) -> Optional[dict]:
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                return None
            req_id = self._next_id()
            msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            try:
                self._proc.stdin.write((msg + "\n").encode())
                self._proc.stdin.flush()
            except BrokenPipeError:
                return None
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self._readline(timeout=max(0.1, deadline - time.time()))
                if line is None:
                    break
                try:
                    obj = json.loads(line)
                    if obj.get("id") == req_id:
                        return obj
                    # notification — discard
                except json.JSONDecodeError:
                    continue
            return None

    def _notify(self, method: str, params: dict):
        if not self._proc or self._proc.poll() is not None:
            return
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        try:
            self._proc.stdin.write((msg + "\n").encode())
            self._proc.stdin.flush()
        except Exception:
            pass

    def _readline(self, timeout: float = 10.0) -> Optional[str]:
        if not self._proc or self._proc.poll() is not None:
            return None
        fd = self._proc.stdout.fileno()
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except Exception:
            return None
        if not ready:
            return None
        try:
            line = self._proc.stdout.readline()
            if not line:
                return None
            return line.decode(errors="replace").strip()
        except Exception:
            return None


# ── TOOL REGISTRY ─────────────────────────────────────────────────────────────

class ToolRegistry:
    """Aggregates tools from all MCP servers; applies per-server allow-lists from config."""

    def __init__(self, servers: list, tool_filters: dict,
                 tool_aliases: Optional[dict] = None):
        """
        servers      — list of started MCPServer instances
        tool_filters — dict[server_name, list[str] | None]
                       None / missing key = allow all tools for that server
        """
        self._servers: dict = {}
        self._raw_by_name: dict = {}
        self._schema: list = []
        pending = []
        requested_counts = {}
        for requested in (tool_filters or {}).values():
            if not isinstance(requested, list):
                continue
            for raw in requested:
                requested_counts[raw] = requested_counts.get(raw, 0) + 1
        aliases = tool_aliases or {}
        for srv in servers:
            tools = srv.list_tools()
            allowed = tool_filters.get(srv.name)  # None → no filter
            for tool in tools:
                tname = tool["name"]
                if allowed is not None and tname not in allowed:
                    continue
                pending.append((srv, tname, tool))
        surface_counts = {}
        for _, raw, _ in pending:
            surface_counts[raw] = surface_counts.get(raw, 0) + 1
        for srv, raw, tool in pending:
            prefix = "".join(c if c.isalnum() or c in "_-" else "_" for c in srv.name).strip("_") or "server"
            declared = (aliases.get(srv.name) or {}).get(raw)
            collides = requested_counts.get(raw, surface_counts.get(raw, 0)) > 1
            exposed = str(declared or (f"{prefix}__{raw}" if collides else raw))
            if exposed in self._servers:
                raise ValueError(f"tool alias collision: {exposed!r}")
            self._servers[exposed] = srv
            self._raw_by_name[exposed] = raw
            self._schema.append(self._to_openai(tool, exposed))
        print(
            f"[Registry] {len(self._schema)} tools registered: "
            f"{[t['function']['name'] for t in self._schema]}",
            file=sys.stderr,
        )

    def schema(self) -> list:
        return self._schema

    def call(self, tool_name: str, arguments: dict) -> str:
        srv = self._servers.get(tool_name)
        if not srv:
            return f"[error: unknown tool '{tool_name}']"
        print(f"[Tool→] {tool_name}({json.dumps(arguments)})", file=sys.stderr)
        result = srv.call_tool(self._raw_by_name.get(tool_name, tool_name), arguments)
        print(f"[Tool←] {tool_name}: {result}", file=sys.stderr)
        return result

    @staticmethod
    def _to_openai(tool: dict, exposed_name: Optional[str] = None) -> dict:
        schema = tool.get("inputSchema", {
            "type": "object", "properties": {}, "required": [],
        })
        return {
            "type": "function",
            "function": {
                "name": exposed_name or tool["name"],
                "description": tool.get("description", ""),
                "parameters": schema,
            },
        }


# ── RAG LOADER ────────────────────────────────────────────────────────────────

def _load_rag(rag_dir: Optional[str]) -> str:
    if not rag_dir:
        return ""
    rag_path = Path(rag_dir)
    if not rag_path.exists():
        return ""
    chunks = []
    for pat in ("*.md", "*.txt"):
        for fpath in sorted(rag_path.glob(pat)):
            if fpath.name == "README.md":
                continue
            text = fpath.read_text(errors="replace").strip()
            if text:
                chunks.append(f"# Material: {fpath.name}\n\n{text}")
    if not chunks:
        return ""
    combined = "\n\n---\n\n".join(chunks)
    return (
        "\n\n## Contexto cargado (RAG)\n\n"
        + combined
        + "\n\n---\n\nUsa este material como fuente de verdad."
    )


# ── FRAMING LOADER ────────────────────────────────────────────────────────────

def _load_framing(framing_path: Optional[str], fallback: str) -> str:
    if framing_path:
        p = Path(framing_path)
        if p.exists():
            return p.read_text(errors="replace").strip()
    return fallback


# ── CHAT CLIENT (urllib, no extra deps) ───────────────────────────────────────

def _is_cli_brain_endpoint(base_url: str) -> bool:
    """True si el base_url apunta al server BYO-CLI local (para el piso de timeout y para
    NO mandarle la key de cognición del dev). Reconoce el default y el override por env."""
    u = (base_url or "").rstrip("/").lower()
    cli_base = os.environ.get("PUPPET_CLI_BRAIN_BASE_URL", "http://127.0.0.1:8926/v1").rstrip("/").lower()
    return u == cli_base or ":8926/" in (u + "/")


# ── LA VÍA LiteLLM (Gate 2 · F4a · obra 3) ────────────────────────────────────
# EL ADAPTADOR DE F3 ENTRA EN PRODUCCIÓN, Y SÓLO POR EL CAMINO C/D. No es timidez: es que
# esos dos endpoints son los que ganan algo. El camino A/B (la cognición incluida y el
# server BYO-CLI `:8926`) son endpoints NUESTROS, con contratos que ya medimos y con un
# `_chat` de urllib que hace exactamente lo que tiene que hacer; meter una librería de 168
# MB en el medio agregaría superficie sin agregar verdad.
#
# Lo que sí ganan C y D:
#   C · OSS-DIRECTO (ollama)  — el `usage` honesto de F2c/F3: ollama a veces no lo manda, y
#       urllib no tiene cómo distinguir «no mandó» de «mandó cero». El adaptador sí.
#   D · OpenRouter            — un proveedor de terceros con errores propios; el traductor
#       vía `desde_litellm` lee su `status_code` y sus cabeceras sin que las parseemos acá.
#
# LA PERILLA: `PUPPET_LITELLM=0` → urllib, byte por byte, sin importar litellm. La vara lo
# exige comparando las dos vías lado a lado sobre el mismo stub.
_OSS_DIRECT_URL = os.environ.get("PUPPET_OSS_DIRECT_BASE_URL", "http://127.0.0.1:11434/v1")


def _litellm_prendido() -> bool:
    """La perilla, leída EN CADA TURNO y no una vez en el import.

    Cuesta un `os.environ.get` por llamada, y compra dos cosas que valen más que eso:
    una perilla de rollback que se puede mover **sin reiniciar el proceso** —que es lo
    que uno quiere de una perilla de rollback, justo cuando algo se está portando mal— y
    una vara que puede probar las dos vías en la misma corrida. Con la constante de
    import, «PUPPET_LITELLM=0 vuelve al camino urllib» era cierto sólo si te acordabas de
    ponerla antes de arrancar, y eso no es reversibilidad: es suerte.
    """
    return os.environ.get("PUPPET_LITELLM", "1").strip().lower() not in ("0", "false", "no")
_litellm_aviso_dado = False
#: Lo último que decidió `_usa_litellm`, para la vara y para el reporte. Sin estado que
#: cambie comportamiento: se escribe, no se lee para decidir.
_litellm_estado: dict = {"perilla": None, "disponible": None, "motivo": ""}


def _es_camino_cd(base_url: str) -> bool:
    """¿Este endpoint es del camino C (OSS-directo) o D (OpenRouter)?"""
    u = (base_url or "").rstrip("/").lower()
    return u == _OSS_DIRECT_URL.rstrip("/").lower() or "openrouter.ai" in u


def _usa_litellm(base_url: str) -> bool:
    """¿Este turno va por el adaptador? Perilla ON + camino C/D + litellm instalado.

    SI LITELLM NO ESTÁ, SE CAE A urllib **Y SE DICE**. Que la dependencia falte es
    perfectamente posible (un árbol sin instalar, un bundle que no la empaquetó) y la
    respuesta correcta no es reventar el turno: es correr por donde se corría ayer. Pero
    tampoco es callarse — un cambio de vía que nadie ve es la clase de cosa que después
    hace que dos máquinas den resultados distintos y nadie sepa por qué. Se avisa UNA vez
    por proceso y queda en `_litellm_estado`.
    """
    global _litellm_aviso_dado
    _on = _litellm_prendido()
    _litellm_estado["perilla"] = _on
    if not _on or not _es_camino_cd(base_url):
        return False
    try:
        from adaptador_litellm import disponible          # noqa: PLC0415 — sólo si hace falta
    except ImportError:                                    # pragma: no cover
        _litellm_estado.update(disponible=False, motivo="adaptador_litellm no está en el árbol")
        if not _litellm_aviso_dado:
            _litellm_aviso_dado = True
            print("[litellm] no está el adaptador — este turno va por urllib", file=sys.stderr)
        return False
    hay, motivo = disponible()
    _litellm_estado.update(disponible=hay, motivo=motivo)
    if not hay and not _litellm_aviso_dado:
        _litellm_aviso_dado = True
        print(f"[litellm] {motivo} — el camino C/D va por urllib", file=sys.stderr)
    return hay


def _mensaje_de_causa(causa: dict) -> str:
    """El string del error, con la MISMA forma que produce el camino urllib.

    No es cosmética: `recipe_assembler._parse_cli_brain_error` busca un `{` y json-decodea,
    `route_log` guarda este texto y hay varas que lo miran. Las dos vías tienen que dejar
    el mismo rastro para que «lado a lado» signifique algo.
    """
    st = (causa.get("evidencia") or {}).get("http_status")
    det = causa.get("detalle") or causa.get("causa") or "falló"
    return f"HTTP {st}: {det}" if st else f"transport: {det}"


def _error_tipado_de(causa: dict) -> RuntimeError:
    """`CausaModelo` serializada (la que trae el adaptador) → la excepción de siempre."""
    mensaje = _mensaje_de_causa(causa)
    if _traductor is None:                                 # pragma: no cover
        return RuntimeError(mensaje)
    try:
        return _traductor.ErrorDeModelo(
            _traductor.CausaModelo(
                causa=causa.get("causa") or _traductor.FALLO_DESCONOCIDO,
                estado=_traductor.ROTO,
                detalle=causa.get("detalle") or "",
                evidencia=causa.get("evidencia") or {},
                reintentable=bool(causa.get("reintentable")),
                retry_after_s=causa.get("retry_after_s"),
                fuente=causa.get("fuente") or _traductor.FUENTE_LITELLM),
            mensaje)
    except Exception:                                      # noqa: BLE001 — re-armar jamás rompe el turno
        return RuntimeError(mensaje)


def _chat_litellm(messages: list, tools: list, base_url: str, model: str, api_key: str,
                  max_tokens: int, temperature: float, timeout: float,
                  *, tool_choice: Optional[Any] = None) -> dict:
    """Un turno por el adaptador de F3, devuelto en la forma OpenAI de siempre.

    El contrato de SALIDA es el de `_chat`: el llamante no se entera de por dónde fue. Lo
    que cambia es lo que se puede afirmar sobre lo que devuelve:

      · `model` es el que reportó el PROVEEDOR (`response.model`), jamás el pedido ni
        `_hidden_params['litellm_model_name']` — que tras un fallback MIENTE (auditoría 1
        §P2.b). Si el proveedor no dijo nada, se cae al pedido, como urllib.
      · `usage` **se omite** cuando no hubo medición. Es el contrato de F2c y de
        `_accumulate_usage`: un dict con ceros contaría como llamada medida y el único
        contador de honestidad que tenemos (`calls_no_usage`) nunca se dispararía.
      · el error sale como `ErrorDeModelo` con la causa YA tipada por `desde_litellm` —
        el adaptador no tiene taxonomía propia, y por eso las dos vías dan la misma causa
        ante el mismo fallo (lo que la vara compara lado a lado).
      · los FALLBACKS de litellm van apagados, global y por llamada. El cascade es de
        `_route_chat`, que además lo narra (`degraded` + cost-event). Dos capas de
        sustitución y una sola de narración es exactamente cómo se pierde una degradación.
    """
    from adaptador_litellm import completar               # noqa: PLC0415

    extra: dict = {
        # El endpoint y la key los manda el LLAMANTE, no el registro de alias: `_chat`
        # recibe el `base_url` ya resuelto por `_route_chat` (que sabe del tier) y la key
        # que corresponde a ESE endpoint — la de OpenRouter, o ninguna para ollama.
        "api_base": base_url,
        "api_key": api_key or "sin-auth",
        "num_retries": 0,          # los reintentos los decide repair (§3 del DISEÑO-REPAIR)
    }
    if tools:
        extra["tools"] = tools
        # [B0-2] Misma regla que la vía urllib: default `"auto"`, byte-idéntico para runs.
        extra["tool_choice"] = tool_choice if tool_choice is not None else "auto"

    # [F7·A·bis] `tenia_key` con el MISMO criterio que la vía urllib (`bool(api_key)`, ver
    # `_tipado`). Va explícito y no lo infiere el adaptador: allá abajo la key ya viajó
    # normalizada al centinela `sin-auth`, que no distingue «este endpoint no lleva auth»
    # de «lleva y no teníamos». Acá esa distinción todavía existe, y es la que hace que las
    # dos vías contesten lo mismo ante el mismo 401.
    r = completar(model, messages, base_url_hint=base_url, max_tokens=max_tokens,
                  temperature=temperature, timeout=timeout, tenia_key=bool(api_key),
                  extra=extra)

    if not r.ok:
        raise _error_tipado_de(r.causa or {})

    # `content: null` cuando el turno es SÓLO tool-calls, que es lo que manda el proveedor
    # y lo que urllib deja pasar. Un `""` en su lugar no es cosmético: este mensaje vuelve
    # al proveedor en el turno siguiente (el loop hace `messages.append(msg)`), y hay
    # endpoints OpenAI-compat que rechazan un assistant con `content` vacío Y `tool_calls`.
    msg: dict = {"role": "assistant",
                 "content": r.texto if r.texto else (None if r.tool_calls else "")}
    if r.tool_calls:
        msg["tool_calls"] = r.tool_calls
    finish = r.finish_reason or ("tool_calls" if r.tool_calls else "stop")
    out: dict = {
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "model": r.model_final or model,
    }
    if r.tokens_medidos:
        pt = r.tokens.get("prompt_tokens") or 0
        ct = r.tokens.get("completion_tokens") or 0
        out["usage"] = {"prompt_tokens": pt, "completion_tokens": ct,
                        "total_tokens": pt + ct}
    # …y si NO se midió, `usage` NO va. Ver el docstring: la ausencia es el dato.
    return out


def _preparar_pedido(
    messages: list,
    tools: list,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
    cli_model: Optional[str] = None,
    effort: Optional[str] = None,
    tool_choice: Optional[Any] = None,
    stream: bool = False,
) -> tuple:
    """El pedido de un turno: `(req, timeout, endpoint)`.

    [B0-3 · fase A] Sale de adentro de `_chat` para que la vía que STREAMEA y la que no
    compartan EXACTAMENTE la misma resolución —payload, User-Agent, piso de timeout del
    BYO-CLI— y no puedan divergir. Con `stream=False` el payload es byte-idéntico al de
    antes de esta obra: lo único que agrega `stream=True` es la clave `"stream"`.
    """
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        # [B0-2] `"auto"` sigue siendo el default y por eso los runs quedan byte-idénticos:
        # el loop de agentes de Aleph NO pasa este parámetro, y no debe — Aleph es dueño de
        # ese loop y de su terminación, así que dejar que una receta pidiera `"required"`
        # cambiaría la economía de turnos (el modelo obligado a llamar tool en cada paso,
        # terminando sólo por `max_turns`). Quien sí lo pasa es el borde del workspace,
        # porque allá el dueño del loop es el harness y él sabe si su paso admite texto.
        payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"
    # ANNEX · SUB-MODELO POR PROVIDER (BYO-CLI): el sub-modelo DENTRO del provider viaja en
    # `cli_model` (distinto de `model`, que elige el provider en el server cli_brain :8926). SÓLO
    # lo pasa el caller cuando el endpoint es ese server → los runs no-CLI son byte-idénticos.
    if cli_model:
        payload["cli_model"] = cli_model
    # TICKET 27·3 · DIAL DE ESFUERZO (BYO-CLI): el effort del turno viaja al server cli_brain (:8926),
    # que lo baja al CLI como `--effort`. Sólo lo pasa el caller para ese endpoint → runs no-CLI intactos.
    if effort:
        payload["effort"] = effort

    if stream:
        payload["stream"] = True
    # LA CONVERSACIÓN, para el server BYO-CLI y para nadie más. Sin esta clave el server no
    # activa sesión (`server.py`: «sin clave no hay sesión… no se adivina cuál es la charla
    # a partir de los mensajes, porque adivinar mal significa contestar con el contexto de
    # otro»), así que cada turno de un workspace pagaba el prompt entero de nuevo.
    payload.update(_sobre_turno.campos_del_cuerpo(_is_cli_brain_endpoint(base_url)))

    data = json.dumps(payload).encode()
    endpoint = base_url.rstrip("/") + "/chat/completions"
    # User-Agent EXPLÍCITO: varios proveedores (Groq vía Cloudflare → error 1010) banean
    # el UA por defecto de urllib ('Python-urllib/3.x'). Sin esto, ir DIRECTO al proveedor
    # OSS (sin el gateway LiteLLM de por medio) da 403. Con un UA propio el endpoint OSS
    # responde normal. (Descubierto 2026-06-15 al forzar OSS-directo con el gateway caído.)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": os.environ.get("PUPPET_HTTP_UA", "puppet-ai/1.0"),
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # EL SOBRE DEL TURNO, sólo hacia el server BYO-CLI local. Es el salto que faltaba:
    # medido 2026-08-15, el mismo sobre entregado DIRECTO al `:8926` llegaba entero
    # (`remaining_s = 24,98`) y entregado POR EL BORDE llegaba inventado (`180,0`), o sea
    # que cada ejecución de un turno arrancaba un deadline nuevo. La guarda es el destino,
    # no el nombre del modelo: un proveedor remoto jamás recibe un id de intento nuestro.
    headers.update(_sobre_turno.cabeceras(_is_cli_brain_endpoint(base_url)))

    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    # CONFIABILIDAD: timeout ACOTADO y configurable. Un gateway caído o medio-abierto
    # JAMÁS debe colgar el loop esperando. urllib aplica el timeout tanto al connect
    # como a cada read; por defecto 60s (generoso para generación local lenta), bajalo
    # con PUPPET_HTTP_TIMEOUT.
    try:
        timeout = float(os.environ.get("PUPPET_HTTP_TIMEOUT", "60"))
    except ValueError:
        timeout = 60.0
    # BYO-CLI (review HIGH #21/#8): el server cli_brain :8926 spawnea `claude -p`/`codex exec`,
    # que pueden tardar 60-100s+ con prompt de belt+historial. Con PUPPET_HTTP_TIMEOUT default
    # (60s) el _chat abortaría y el cascade degradaría el FEATURE INSIGNIA a qwen quemando la
    # ventana del usuario en vano. Para el endpoint CLI ponemos un PISO alto (el propio timeout
    # del server + margen), sin tocar el timeout del resto de los providers.
    if _is_cli_brain_endpoint(base_url):
        try:
            _cli_to = float(os.environ.get("PUPPET_CLI_BRAIN_TIMEOUT", "180")) + 30.0
        except ValueError:
            _cli_to = 210.0
        timeout = max(timeout, _cli_to)

    return req, timeout, endpoint


def _chat(
    messages: list,
    tools: list,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
    cli_model: Optional[str] = None,
    effort: Optional[str] = None,
    tool_choice: Optional[Any] = None,
) -> dict:
    req, timeout, endpoint = _preparar_pedido(
        messages, tools, base_url, model, api_key, max_tokens, temperature,
        cli_model=cli_model, effort=effort, tool_choice=tool_choice, stream=False)
    # ── EL DESVÍO (F4a · obra 3) ─────────────────────────────────────────────
    # Va ACÁ y no antes a propósito: todo lo de arriba —el payload, el UA propio, el piso
    # de timeout del BYO-CLI— es la resolución del turno, y vale para las dos vías. Lo
    # único que cambia es QUIÉN hace el POST. Así el `timeout` que recibe litellm es
    # exactamente el mismo número que usaría urllib, y «lado a lado» compara vías, no
    # configuraciones distintas.
    if _usa_litellm(base_url):
        return _chat_litellm(messages, tools, base_url, model, api_key,
                             max_tokens, temperature, timeout,
                             tool_choice=tool_choice)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # ── [Gate 4 · F5 · 5.2] EL SOCKET DEL MODELO, ATADO A LA OBRA ─────────────
            # Mientras esto siga abierto el proveedor sigue generando y —en las vías con
            # costo— sigue cobrando (la tesis de `turnos_http:13-16`). Atarlo es lo que
            # hace que parar una obra sea parar de verdad y no dejar de dibujar.
            # Sin obra abierta en este hilo (una vara, el CLI, un sub-agente) es un no-op.
            _turnos_obra.atar_socket(resp)
            try:
                cuerpo = resp.read()
            except Exception as e:                 # noqa: BLE001 — el socket se cerró
                # Cerrar el socket despierta al lector con un error de red cualquiera,
                # indistinguible de un corte real. Quién causó el corte es parte del corte.
                if _turnos_obra.fue_detenido():
                    raise _detenido_por_el_usuario() from None
                raise
            finally:
                _turnos_obra.soltar_socket()
            return json.loads(cuerpo.decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # El body sigue yendo AL MENSAJE, como siempre. La CAUSA no lo toca: el traductor
        # lee `code` y `headers` del `HTTPError` (que `read()` no consume) y compone su
        # `detalle` con plantillas propias. O sea que el cuerpo crudo del proveedor viaja
        # por el canal de siempre y NO entra en lo que se le muestra a la persona.
        raise _tipado(e, endpoint, f"HTTP {e.code}: {body}", cuerpo=body,
                      cli_brain=_is_cli_brain_endpoint(base_url),
                      tenia_key=bool(api_key), con_tools=bool(tools))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # Conexión rechazada / DNS / timeout de socket. El mensaje sigue siendo el de
        # siempre para que `_route_chat` y `record["error"]` no cambien de forma; lo que
        # se agrega es la CAUSA TIPADA al lado (ver `_tipado`).
        reason = getattr(e, "reason", None) or e
        raise _tipado(e, endpoint, f"transport: {reason}")


def _chat_stream(
    messages: list,
    tools: list,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
    cli_model: Optional[str] = None,
    effort: Optional[str] = None,
    tool_choice: Optional[Any] = None,
):
    """[B0-3 · fase A] El MISMO turno que `_chat`, pero cediendo lo que llega cuando llega.

    Hermano de `_chat`, no reemplazo: `_chat` no se toca y los runs siguen por él,
    byte-idénticos. **Nadie llama a esta función todavía** — el cableado es de las fases
    siguientes. Acá sólo existe la capacidad.

    POR QUÉ HACE FALTA, y no es percepción. Medido el 2026-08-12 en el borde de workspace:
    cortando el cliente a los 8 s, el `claude` seguía vivo a los 25,7 s — **17,7 segundos
    generando una respuesta que ya nadie iba a leer**, contra la ventana de la suscripción
    del usuario. Un `complete()` bloqueante no puede enterarse de que el cliente se fue: no
    tiene dónde mirar. Un generador sí — cuando quien consume deja de pedir, el `finally`
    corre y el socket se cierra.

    Cede `(clase, carga)`:
      · `texto`         — un delta de contenido, tal como llegó
      · `razonamiento`  — un delta de pensamiento, si el proveedor lo emite
      · `tool_delta`    — el fragmento crudo de un `tool_calls` incremental
      · `model_final`   — el modelo que el proveedor DIJO estar usando (hecho, no intención)
      · `usage`         — el uso, si vino
      · `fin`           — el `finish_reason`

    LA VÍA **litellm** NO STREAMEA DE VERDAD, Y SE DICE EN VEZ DE REVENTAR. `_chat_litellm`
    devuelve el turno entero; darle streaming real sigue siendo otra obra. Lo que se hace acá
    es pedirlo entero y cederlo en un solo trozo, **declarándolo** con `("no_streameado", …)`
    para que nadie confunda un turno que llegó de una con uno que llegó por pedazos.

    POR QUÉ CAMBIÓ. Esto levantaba `RuntimeError` para «fallar fuerte en vez de fingir que
    streamea». La intención era buena y el efecto medido fue el peor de los dos mundos: como
    el tier `oss-direct` ES una vía litellm y es el ÚLTIMO del cascade,
    `recipe_assembler:1552` propagaba la excepción al generador del borde **con las cabeceras
    ya enviadas** — el cliente recibía 2 chunks, sin `finish_reason`, sin `usage` y sin
    `[DONE]`, y la telemetría lo anotaba `status=200`. Medido en Ciencia sobre el binario
    `363d7ceb…`: 6 apariciones de este RuntimeError y 3 de cada 4 turnos volviendo VACÍOS.
    Fallar fuerte adentro de un generador que ya empezó a emitir no es fallar fuerte: es
    fallar mudo.

    Ceder de una no es fingir mientras se declare. Lo que este borde vino a dejar de hacer es
    **mentir**, y un `("no_streameado", …)` en el cable es lo contrario de una mentira.
    """
    if _usa_litellm(base_url):
        # Se pide por la vía de siempre —misma función, mismo tipado de errores— y se cede
        # con la MISMA forma que el camino que sí streamea, para que quien consume no tenga
        # que saber por dónde vino.
        resp = _chat(messages, tools, base_url, model, api_key, max_tokens, temperature,
                     cli_model=cli_model, effort=effort, tool_choice=tool_choice)
        yield ("no_streameado", {"endpoint": base_url, "model": model,
                                 "porque": "la vía litellm devuelve el turno entero"})
        if isinstance(resp, dict):
            if resp.get("model"):
                yield ("model_final", str(resp["model"]))
            if isinstance(resp.get("usage"), dict):
                yield ("usage", resp["usage"])
            for choice in resp.get("choices") or []:
                msg = choice.get("message") or {}
                if msg.get("content"):
                    yield ("texto", msg["content"])
                for clave in ("reasoning_content", "reasoning", "thinking"):
                    if msg.get(clave):
                        yield ("razonamiento", msg[clave])
                        break
                # El `index` se agrega acá porque el sobre no-stream no lo trae y el
                # acumulador de aguas abajo lo usa para saber a cuál de varias tools
                # pertenece cada trozo (`workspace_brain._acumular`). Sin él, dos tool_calls
                # se pisarían en el índice 0.
                for i, tc in enumerate(msg.get("tool_calls") or []):
                    yield ("tool_delta", {**tc, "index": tc.get("index", i)})
                if choice.get("finish_reason"):
                    yield ("fin", choice["finish_reason"])
        return

    req, timeout, endpoint = _preparar_pedido(
        messages, tools, base_url, model, api_key, max_tokens, temperature,
        cli_model=cli_model, effort=effort, tool_choice=tool_choice, stream=True)

    # ── SE ABRE CON `http.client`, NO CON `urlopen`, Y ÉSA ES TODA LA OBRA ──────────────
    #
    # `urlopen` no devuelve hasta que llegan los HEADERS de respuesta. El server BYO-CLI no
    # manda headers hasta el primer delta —a propósito: mientras no salió nada el fallo
    # viaja como HTTP con su status, y abrir el stream antes lo convertiría en un 200 con
    # el error adentro—. Un turno de CLI no emite nada mientras piensa. Juntando las dos
    # cosas: **durante todo el turno el objeto respuesta todavía no existe**, así que no
    # había socket que atar y `detener` no tenía qué cerrar.
    #
    # MEDIDO el 2026-08-13, en el orden real del log: la cancelación del cliente llegaba a
    # los ~24 s y `atar_socket` recién corría a los 45 s, cuando el turno YA había muerto
    # por el watchdog de inactividad del propio `:8926`. La cadena de corte estaba entera y
    # bien —turno registrado, hilo correcto, `detener` devolviendo `turno_detenido`— y no
    # servía de nada, porque llegaba a atar un socket que existía veinte segundos tarde.
    #
    # Con `http.client` el objeto conexión existe ANTES de mandar. Se ata ahí, y entonces
    # `detener` puede hacerle `shutdown()` mientras todavía se está esperando la primera
    # línea. No cambia un byte del pedido: mismo cuerpo, mismos headers, mismo timeout.
    _p = urllib.parse.urlsplit(endpoint)
    _Conn = (http.client.HTTPSConnection if _p.scheme == "https"
             else http.client.HTTPConnection)
    conn = _Conn(_p.netloc, timeout=timeout)
    # ATAR ANTES DE MANDAR. Éste es el punto: mientras siga abierta, el proveedor sigue
    # generando —y cobrando—, así que pararlo tiene que poder cerrarla de verdad, y tiene
    # que poder hacerlo desde el primer instante y no desde el primer byte.
    _turnos_obra.atar_socket(conn)
    _ruta = _p.path + (("?" + _p.query) if _p.query else "")
    try:
        conn.request("POST", _ruta or "/", body=req.data, headers=dict(req.header_items()))
        resp = conn.getresponse()
    except (TimeoutError, OSError) as e:
        _turnos_obra.soltar_socket()
        try:
            conn.close()
        except Exception:                     # noqa: BLE001 — ya estaba cerrada
            pass
        if _turnos_obra.fue_detenido():
            raise _detenido_por_el_usuario() from None
        raise _tipado(e, endpoint, f"transport: {e}")

    if resp.status >= 400:
        # Se re-arma el `HTTPError` de siempre para que `_tipado` reciba EXACTAMENTE lo que
        # recibía con urlopen: cambiar el transporte no puede cambiar cómo se clasifica un
        # fallo, que es de lo que dependen las causas y su copy.
        cuerpo = resp.read().decode(errors="replace")
        e = urllib.error.HTTPError(endpoint, resp.status, resp.reason,
                                   resp.headers, None)
        _turnos_obra.soltar_socket()
        try:
            conn.close()
        except Exception:                     # noqa: BLE001 — ya estaba cerrada
            pass
        raise _tipado(e, endpoint, f"HTTP {resp.status}: {cuerpo}", cuerpo=cuerpo,
                      cli_brain=_is_cli_brain_endpoint(base_url),
                      tenia_key=bool(api_key), con_tools=bool(tools))

    try:
        for cruda in resp:
            linea = cruda.decode("utf-8", "replace").strip()
            if not linea.startswith("data:"):
                continue                      # `id:`/`event:` no los usa este contrato
            dato = linea[5:].strip()
            if not dato or dato == "[DONE]":
                continue
            try:
                ev = json.loads(dato)
            except ValueError:
                # Un frame ilegible NO se traga: es de la misma familia que el
                # `onMalformed` del lector de la Sala. Se cede y decide quien consume.
                yield ("frame_ilegible", dato[:200])
                continue
            if ev.get("model"):
                yield ("model_final", str(ev["model"]))
            if isinstance(ev.get("usage"), dict):
                # EL DESGLOSE DE CACHÉ CRUZA EL BORDE, NO SE QUEDA EN EL ANNEX.
                # El servidor de CLI ya publica `cache_read_tokens` / `cache_write_tokens`
                # en su annex `aleph_cli_brain`, pero acá sólo se cedía `usage` y el
                # desglose moría en este renglón: río abajo el ledger veía CUÁNTO y no A QUÉ
                # PRECIO, y son precios distintos —leer caché cuesta una fracción del input,
                # escribirlo cuesta más—. Con `prompt`/`completion` solos, una lane cacheada
                # y una que repaga el preámbulo entero se anotan igual.
                #
                # Los nombres no se inventan: `prompt_tokens_details.cached_tokens` es el
                # campo REAL de OpenAI para lo leído de caché, y `cache_creation_input_tokens`
                # es el de Anthropic para lo escrito. Se copian tal cual, así que un
                # consumidor que ya sepa leer cualquiera de los dos sobres los encuentra
                # donde espera; el que no, sigue viendo el `usage` de siempre.
                _u = dict(ev["usage"])
                _annex = ev.get("aleph_cli_brain")
                if isinstance(_annex, dict):
                    _leido = _annex.get("cache_read_tokens")
                    _escrito = _annex.get("cache_write_tokens")
                    if _leido is not None:
                        _det = dict(_u.get("prompt_tokens_details") or {})
                        _det.setdefault("cached_tokens", _leido)
                        _u["prompt_tokens_details"] = _det
                    if _escrito is not None:
                        _u.setdefault("cache_creation_input_tokens", _escrito)
                yield ("usage", _u)
            for choice in ev.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield ("texto", delta["content"])
                # Los proveedores no se pusieron de acuerdo en cómo se llama pensar.
                for clave in ("reasoning_content", "reasoning", "thinking"):
                    if delta.get(clave):
                        yield ("razonamiento", delta[clave])
                        break
                for tc in delta.get("tool_calls") or []:
                    yield ("tool_delta", tc)
                if choice.get("finish_reason"):
                    yield ("fin", choice["finish_reason"])
    except Exception as e:                    # noqa: BLE001 — se re-levanta tipado
        if _turnos_obra.fue_detenido():
            raise _detenido_por_el_usuario() from None
        raise
    finally:
        # Corre TAMBIÉN cuando quien consume abandona el generador: ahí está la diferencia
        # con `_chat`. Cerrar el socket es lo que le corta la generación al proveedor.
        _turnos_obra.soltar_socket()
        for _cerrable in (resp, conn):
            try:
                _cerrable.close()
            except Exception:                 # noqa: BLE001 — ya estaba cerrado
                pass


def _causa_del_cuerpo_cli_brain(cuerpo: str):
    """La `CausaModelo` que el server `:8926` YA mandó en su cuerpo, si la mandó.

    ── POR QUÉ SE PREFIERE AL STATUS ────────────────────────────────────────────
    El server BYO-CLI clasifica el fallo CON TODO A LA VISTA —el stderr del binario, su
    `result` event, sus slots, su store de sesiones— y publica el resultado en
    `error.causa`, ya tipado y ya redactado (`cli_brain/server.py`: `cuerpo["error"]
    ["causa"] = res.causa`). Del otro lado del cable, `desde_urllib` sólo ve un número.

    Y el número BORRA lo que el server sabía. Los tres casos, medidos:

        409 `turno_detenido`  → por status sale `error_upstream`, «el proveedor rechazó el
              pedido». El proveedor no rechazó nada: la persona apretó parar.
        409 `sesion_perdida`  → por status sale `error_upstream`, que **no escala** — así
              que un resume perdido MATABA el run en vez de dejar que el fallback
              contestara, teniendo el contexto completo a mano.
        429 por el techo de slots → por status sale `rate_limit`, «se agotó tu ventana»,
              cuando lo que pasó es que tu CLI está atendiendo otro turno.

    Sólo se acepta un cuerpo con la forma EXACTA de una `CausaModelo` y con una causa del
    vocabulario CERRADO: un proveedor cualquiera podría mandar un JSON con una clave
    `causa` y esto no es una puerta para que nos dicte el diagnóstico.
    """
    if _traductor is None or not cuerpo:
        return None
    try:
        obj = json.loads(cuerpo)
        c = ((obj or {}).get("error") or {}).get("causa")
        if not isinstance(c, dict) or c.get("causa") not in _traductor.CAUSAS:
            return None
        return _traductor.CausaModelo(
            causa=c["causa"], estado=_traductor.ROTO,
            detalle=str(c.get("detalle") or "")[:200],
            evidencia=c.get("evidencia") if isinstance(c.get("evidencia"), dict) else {},
            reintentable=bool(c.get("reintentable")),
            retry_after_s=c.get("retry_after_s"),
            fuente=c.get("fuente") if c.get("fuente") in _traductor.FUENTES
            else _traductor.FUENTE_CLI)
    except Exception:                                    # noqa: BLE001 — un cuerpo raro no rompe el turno
        return None


def _tipado(exc: Exception, url: str, mensaje: str, *, cuerpo: str = "",
            cli_brain: bool = False, tenia_key: bool = True,
            con_tools: bool = False) -> RuntimeError:
    """El arreglo del §P1.a de la auditoría 2, en cuatro líneas.

    LO QUE ESTABA MAL, medido: `_chat` fundía **401, 429 y DNS caído en un solo
    `RuntimeError` con un string**. El status vivía DENTRO del mensaje, así que el llamante
    tenía que re-parsear texto para saber si el problema era la llave del usuario, su
    cuota, o que no había internet — y ninguno lo hacía: `_route_chat` los trataba a los
    tres igual y escalaba al fallback. Un 401 con fallback deja de verse como «tu llave no
    sirve» y pasa a verse como «un modelo raro respondiendo».

    Acá el fallo sale CLASIFICADO por el traductor de F1, que ya sabe distinguir los cuatro
    casos medidos (401 · 429 con retry-after · Errno 8 DNS · Errno 61 refused). El mensaje
    NO cambia — ver `ErrorDeModelo` para el porqué.

    Si el traductor no está, se levanta el `RuntimeError` de siempre: la compatibilidad no
    depende de que la clasificación exista.
    """
    if _traductor is None:                               # pragma: no cover — árbol a medias
        return RuntimeError(mensaje)
    try:
        # El server BYO-CLI ya clasificó con todo a la vista; su veredicto gana al status.
        # Sólo para ESE endpoint: es el único del que sabemos que publica el contrato.
        # `cli_brain` lo decide el llamante con el `base_url`, NO se re-deriva de `url`:
        # acá `url` es el endpoint completo (`…/v1/chat/completions`) y
        # `_is_cli_brain_endpoint` compara contra el `base_url`. Derivarlo de nuevo acá
        # andaba de casualidad —por el substring `:8926/`— y fallaba en cuanto el server
        # corría en otro puerto (`PUPPET_CLI_BRAIN_BASE_URL`), que es el caso del bundle.
        causa = _causa_del_cuerpo_cli_brain(cuerpo) if cli_brain else None
        if causa is None:
            # [F7·A] `tenia_key` decide 401 → `key_invalida` vs `falta_key`. El dato sale de
            # `_chat`, que es quien pone (o no pone) el header Authorization.
            # [F5 · 5.1] `con_tools` sólo lo mira el 413: separa «tu texto no entra» de
            # «te mandamos el cinturón entero». Lo sabe `_chat`, que es quien arma el
            # payload y por lo tanto quien sabe si viajaron schemas.
            causa = _traductor.desde_urllib(exc, url=url, tenia_key=tenia_key,
                                            con_tools=con_tools)
        return _traductor.ErrorDeModelo(causa, mensaje)
    except Exception:                                    # noqa: BLE001 — traducir jamás rompe el turno
        return RuntimeError(mensaje)


# ── TOOL-USE LOOP ─────────────────────────────────────────────────────────────

def run_agent(
    prompt: str,
    cfg: dict,
    registry: ToolRegistry,
    api_key: str,
) -> str:
    framing = _load_framing(
        cfg.get("framing_path"),
        cfg.get("framing_fallback", "You are a helpful assistant."),
    )
    rag_ctx = _load_rag(cfg.get("rag_dir"))
    system_content = framing + rag_ctx

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": prompt},
    ]

    tools = registry.schema()
    base_url = cfg["base_url"]
    model = cfg["model"]
    max_turns = int(cfg.get("max_turns", 8))
    max_tokens = int(cfg.get("max_tokens", 2048))
    temperature = float(cfg.get("temperature", 0))

    for turn in range(1, max_turns + 1):
        print(f"\n[Turn {turn}/{max_turns}]", file=sys.stderr)
        resp = _chat(messages, tools, base_url, model, api_key, max_tokens, temperature)

        choice = resp["choices"][0]
        msg    = choice["message"]
        finish = choice.get("finish_reason", "")

        messages.append(msg)

        if finish == "tool_calls" or (msg.get("tool_calls") and finish != "stop"):
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                break
            for tc in tool_calls:
                tc_id   = tc["id"]
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}
                result_text = registry.call(fn_name, fn_args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "content":      result_text,
                })
        else:
            return msg.get("content", "")

    last = messages[-1]
    if last.get("role") == "assistant":
        return last.get("content", "[max turns reached without final answer]")
    return "[max turns reached without final answer]"


# ── API KEY RESOLUTION ────────────────────────────────────────────────────────

def _resolve_api_key(cfg: dict) -> str:
    """
    Resolve API key from config-specified sources (optional — Ollama needs none).
    Priority: env var named in config → file path named in config → empty string.
    Never prints or writes the key.
    """
    key_cfg = cfg.get("api_key", {})
    if not key_cfg:
        return ""

    # env var
    env_var = key_cfg.get("env_var")
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val

    # file path
    file_path = key_cfg.get("file_path")
    if file_path:
        p = Path(file_path)
        if p.exists():
            for line in p.read_text().splitlines():
                key_var = key_cfg.get("file_key", env_var or "API_KEY")
                if line.startswith(f"{key_var}="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val

    return ""


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python assembler.py <config.json> \"<prompt>\"", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    cfg = json.loads(config_path.read_text())
    prompt = sys.argv[2]

    print(f"\n=== Puppet AI — Generic Assembler ===", file=sys.stderr)
    print(f"Config : {config_path}", file=sys.stderr)
    print(f"Model  : {cfg.get('model','?')} @ {cfg.get('base_url','?')}", file=sys.stderr)
    print(f"Prompt : {prompt}", file=sys.stderr)

    api_key = _resolve_api_key(cfg)

    # parse belt .mcp.json
    belt_path = Path(cfg["belt_path"])
    if not belt_path.is_absolute():
        belt_path = Path(config_path).resolve().parent / belt_path
    if not belt_path.exists():
        print(f"[ERROR] Belt not found: {belt_path}", file=sys.stderr)
        sys.exit(2)

    mcp_cfg = json.loads(belt_path.read_text())
    servers_raw = mcp_cfg.get("mcpServers", {})

    # tool filters: dict[server_name -> list[str]] or empty
    tool_filters = cfg.get("tool_filters", {})

    # start MCP servers
    servers = []
    for sname, scfg in servers_raw.items():
        from recipe_assembler import _expand_server_cfg, _mcp_expansion_base, _puppet_run_env
        env = _puppet_run_env(Path(__file__).resolve().parents[2], _mcp_expansion_base())
        command, args, child_env = _expand_server_cfg(scfg, env)
        srv = MCPServer(sname, command, args, env=child_env)
        if srv.start():
            servers.append(srv)
        else:
            print(f"[WARN] {sname}: failed to start — skipping", file=sys.stderr)

    if not servers:
        print("[ERROR] No MCP servers started. Check belt installation.", file=sys.stderr)
        sys.exit(2)

    registry = ToolRegistry(
        servers,
        tool_filters,
        tool_aliases=cfg.get("tool_aliases") or {},
    )

    try:
        answer = run_agent(prompt, cfg, registry, api_key)
    finally:
        for srv in servers:
            srv.stop()

    print("\n" + "=" * 60)
    print(answer)
    print("=" * 60)


if __name__ == "__main__":
    main()
