"""
dispatch/liveness.py — el CANDADO verify-from-environment de los paths que tocan el mundo.
MONTA sobre piezas existentes, CERO validación nueva:

  1. §9 SSRF guard ANTES de conectar (defense-in-depth: probe_mcp YA guarda el path http por
     dentro vía _guard_http_url → safety.url_guard; acá el SEAM dueña su propio check con un
     guard INYECTABLE — el draft viene de un registro, un entry malicioso podría apuntar el
     probe a una URL interna).
  2. byo_mcp.probe_mcp = el ÁRBITRO: conecta + tools/list → los tools REALES con su inputSchema.
     Lo que el borrador reclama y el server NO lista = PHANTOM → dropeado. (allowed_tools filtra
     al subset reclamado; el diff reclamado − listado son los phantom.)
  3. tools/call de liveness OPCIONAL sobre los reads listados: responde → vivo; falla DURO
     (transporte/protocolo/sin-respuesta) → "caído" → dropeado. CONSERVADOR: un error de
     ARGUMENTOS (el tool existe pero pidió params) NO lo cae — el tool está vivo. Los WRITES
     no se llaman (§7: un write no se ejecuta "probando").

probe_mcp es el árbitro (§0 verify-from-environment); si el MCP no conecta / no lista tools,
levanta BYOValidationError y el caller hace fall-through a la cascada (auto-sana).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import byo_mcp, contracts as C          # noqa: E402  (read-only)
from inspection.loop.guard import PublicHTTPGuard       # noqa: E402  (§9 SSRF guard)
# EL TRANSPORTE LO ELIGE `transporte` (sesión 3): puente al SDK por default, cliente
# viejo con ALEPH_TRANSPORTE=viejo. La liveness hoy sólo la alcanza el dispatcher, que
# no está cableado a ninguna ruta — se migra igual para que el grep de «consumidores del
# viejo» pueda dar CERO sin asteriscos, y para que el día que se cablee no arrastre el
# transporte de 2024.
from inspection import transporte as _TP                # noqa: E402

_REPO_ROOT = _PLATFORM.parent
_ASSEMBLER_PY = _REPO_ROOT / "platform" / "assembler" / "assembler.py"

#: heurística read/write LOCAL (no importamos la privada de byo_mcp). Un read se llama
#: para liveness; un write NO (§7).
_READ_PREFIXES = ("get_", "read_", "search_", "list_", "fetch_", "lookup_", "find_",
                  "query_", "ask_", "describe_", "resolve_", "view_", "show_")


class GuardDenied(Exception):
    """El §9 guard rechazó la URL del MCP ANTES de conectar (fail-closed)."""


def _fill(template: str, value: str) -> str:
    return re.sub(r"\{[^}]*\}", value, template or "")


def _is_read(name: str) -> bool:
    return any((name or "").startswith(p) for p in _READ_PREFIXES)


# ── carga del MCPServer stdio del assembler (no es archivo protegido) ────────────
_asm_mod = None


def _asm():
    global _asm_mod
    if _asm_mod is None:
        spec = importlib.util.spec_from_file_location("dispatch_assembler", _ASSEMBLER_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _asm_mod = m
    return _asm_mod


# ── 1+2 · guard + probe (tools/list = árbitro) ───────────────────────────────────
def probe(spec: dict, secret: Optional[str], *, guard: Optional[C.SSRFGuard] = None,
          allowed_tools: Optional[list[str]] = None, timeout: float = 45.0) -> dict:
    """§9 guard (http) → byo_mcp.probe_mcp. Devuelve el probe dict
    {transport, url|command, server_info, tools:[{name,description,inputSchema}], ...}.
    Levanta GuardDenied si el guard rechaza, o byo_mcp.BYOValidationError si el MCP no valida."""
    g = guard or PublicHTTPGuard()
    transport = (spec.get("transport") or "").lower()
    if transport == "http":
        url = spec.get("url") or ""
        verdict = g.check(url)
        if not verdict:
            raise GuardDenied(f"§9 rechazó {url}: {getattr(verdict, 'reason', 'denegada')}")
        headers = ({spec["header_name"]: _fill(spec["header_template"], secret)}
                   if secret else {})
        return byo_mcp.probe_mcp(transport="http", url=url, headers=headers,
                                 allowed_tools=allowed_tools, timeout=timeout)
    # stdio: no hay URL que guardar (el riesgo es ejecución de comando; ver dispatcher).
    env = ({spec["package_env_var"]: secret}
           if secret and spec.get("package_env_var") else {})
    return byo_mcp.probe_mcp(transport="stdio", command=spec.get("command"),
                             args=spec.get("args"), env=env,
                             allowed_tools=allowed_tools, timeout=timeout)


# ── 3 · tools/call liveness OPCIONAL (conservador: solo dropea fallas DURAS) ──────
def _call_http(spec: dict, secret: Optional[str], names: list[str]) -> tuple[set, set]:
    url = spec.get("url") or ""
    headers = ({spec["header_name"]: _fill(spec["header_template"], secret)} if secret else {})
    alive: set[str] = set()
    dead: set[str] = set()
    client = _TP.cliente_http()(url, headers, timeout=30.0)
    try:
        client.initialize()
        for n in names:
            try:
                res = client.call_tool(n, {})
                # respondió (aunque sea isError por args faltantes) → VIVO
                _ = res
                alive.add(n)
            except _TP.error_http():
                dead.add(n)                      # falla de transporte/protocolo → caído
    except _TP.error_http():
        dead.update(names)                        # ni el handshake → todos caídos
    finally:
        client.close()
    return alive, dead


def _call_stdio(spec: dict, secret: Optional[str], names: list[str]) -> tuple[set, set]:
    env = ({spec["package_env_var"]: secret} if secret and spec.get("package_env_var") else {})
    srv = _TP.servidor_stdio()("dispatch-liveness", spec.get("command"),
                               list(spec.get("args") or []), env=env if env else None)
    alive: set[str] = set()
    dead: set[str] = set()
    if not srv.start():
        return alive, set(names)                  # no arrancó → todos caídos
    try:
        for n in names:
            out = srv.call_tool(n, {})            # str: "[MCP error: ...]" si falló duro
            if isinstance(out, str) and out.startswith("[MCP error"):
                dead.add(n)                        # sin respuesta / error de protocolo → caído
            else:
                alive.add(n)                       # respondió (incluso "[tool error]" = vivo)
    finally:
        srv.stop()
    return alive, dead


def call_liveness(spec: dict, secret: Optional[str], tool_names: list[str]) -> tuple[set, set]:
    """Best-effort. Llama SOLO los reads (§7: writes no se ejecutan). Devuelve (vivos, caídos).
    Conservador: un error de args NO cae el tool (existe y respondió); solo cae la falla dura."""
    reads = [n for n in tool_names if _is_read(n)]
    if not reads:
        return set(tool_names), set()             # nada que llamar → todos quedan (presencia)
    transport = (spec.get("transport") or "").lower()
    alive, dead = (_call_http(spec, secret, reads) if transport == "http"
                   else _call_stdio(spec, secret, reads))
    # los writes (no llamados) quedan por presencia
    writes = [n for n in tool_names if not _is_read(n)]
    return (alive | set(writes)), dead


__all__ = ["probe", "call_liveness", "GuardDenied"]
