"""
transporte.py — QUIÉN habla MCP en el producto. Un solo lugar, con perilla de rollback.

Desde la sesión 2, el camino real es el **puente al SDK oficial**
(`transporte_sdk.ServidorSDK` / `ClienteSdkHttp`). El **cliente viejo**
(`assembler.MCPServer` / `mcp_http_client.MCPHttpClient`) **sigue en el árbol y sigue
funcionando**: su borrado es otra sesión, después de una regresión total. Mientras tanto es
el rollback, y un rollback que hay que ir a buscar editando código no es un rollback.

    ALEPH_TRANSPORTE=auto    (default) el puente si el SDK está; el viejo si no
    ALEPH_TRANSPORTE=sdk     el puente, y si el SDK falta REVIENTA — no degrada callado
    ALEPH_TRANSPORTE=viejo   el cliente viejo, aunque el SDK esté (LA PERILLA DE ROLLBACK)

**LA ELECCIÓN NUNCA ES INVISIBLE.** `elegido()` la publica y el puente la estampa en
`diagnostico()["transporte"]`. Un `auto` que se cae al viejo por una dependencia ausente
es una degradación declarada, no un fallo mudo (CLAUDE.md §1): la evidencia de cada medición
dice con qué transporte se midió, así que dos filas del registro nunca se pueden comparar
creyendo que salieron del mismo lugar cuando no.

Las dos clases exponen la MISMA interfaz sync —mismo constructor, mismos métodos, mismos
tipos de retorno— así que a este módulo lo consume quien spawnea, no quien diagnostica. La
traducción de errores vive aparte, en `traductor_errores`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
try:
    import aleph_paths as _ap                              # `platform/` ya está en sys.path
    _RAIZ = _ap.resource_root().resolve()
except Exception:                                          # noqa: BLE001
    _RAIZ = _AQUI.parents[1]
_ASSEMBLER_PY = _RAIZ / "platform" / "assembler" / "assembler.py"

AUTO, SDK, VIEJO = "auto", "sdk", "viejo"


def modo() -> str:
    """La perilla, leída en cada llamada a propósito: un test que la mueve con
    `monkeypatch.setenv` tiene que verla, y un operador que la cambia no debería reiniciar
    el sidecar para probar un rollback."""
    v = (os.environ.get("ALEPH_TRANSPORTE") or AUTO).strip().lower()
    return v if v in (AUTO, SDK, VIEJO) else AUTO


_asm_mod = None


def _asm():
    """`assembler.py` por ruta — el mismo patrón (y el mismo motivo) que `byo_mcp._asm`:
    bajo PyInstaller el árbol no está donde `__file__` lo dice, y `aleph_paths` es la
    fuente única del DÓNDE."""
    global _asm_mod
    if _asm_mod is None:
        spec = importlib.util.spec_from_file_location("puppet_assembler_transporte",
                                                      str(_ASSEMBLER_PY))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _asm_mod = m
    return _asm_mod


def _sdk():
    if str(_AQUI) not in sys.path:
        sys.path.append(str(_AQUI))
    import transporte_sdk                                  # noqa: E402
    return transporte_sdk


def _hay_sdk() -> tuple:
    try:
        return _sdk().sdk_disponible()
    except Exception as e:                                 # noqa: BLE001 — ni el módulo carga
        return False, f"{type(e).__name__}: {e}"


def elegido() -> dict:
    """`{transporte, motivo, modo}` — qué se va a usar y por qué. Se publica en la
    evidencia para que ninguna medición quede sin decir de dónde salió."""
    m = modo()
    hay, porque = _hay_sdk()
    if m == VIEJO:
        return {"transporte": "legacy", "modo": m,
                "motivo": "ALEPH_TRANSPORTE=viejo — rollback pedido explícitamente"}
    if m == SDK:
        return {"transporte": "sdk", "modo": m,
                "motivo": "ALEPH_TRANSPORTE=sdk — exigido; sin SDK esto revienta"}
    if hay:
        return {"transporte": "sdk", "modo": m, "motivo": "el SDK está disponible"}
    return {"transporte": "legacy", "modo": m,
            "motivo": f"el SDK no está disponible: {porque}"}


def _resolver(nombre_sdk: str, viejo):
    """La clase que corresponde, con el fallo VISIBLE cuando se exigió el SDK y no está."""
    m = modo()
    if m == VIEJO:
        return viejo()
    hay, porque = _hay_sdk()
    if not hay:
        if m == SDK:
            raise RuntimeError(
                f"ALEPH_TRANSPORTE=sdk pero el SDK de MCP no está disponible: {porque}. "
                f"No se degrada en silencio: o se instala `mcp==2.0.0`, o se pide "
                f"ALEPH_TRANSPORTE=viejo a propósito.")
        return viejo()
    return getattr(_sdk(), nombre_sdk)


def _grabador():
    """`grabador.py` — S1 de la suite. Perezoso y tolerante: si no está (árbol recortado,
    build raro), el transporte sigue siendo el de siempre."""
    try:
        if str(_AQUI) not in sys.path:
            sys.path.append(str(_AQUI))
        import grabador                                    # noqa: E402
        return grabador
    except Exception:                                      # noqa: BLE001 — frontera
        return None


def servidor_stdio():
    """La clase para hablar con un server MCP por stdio.

    Firma idéntica en las dos: `(name, command, args, env=None, rpc_timeout=30.0, cwd=None)`
    y los mismos métodos `start/list_tools/call_tool/stop/diagnostico`. El llamante no puede
    notar cuál le tocó — salvo mirando la evidencia, que es donde tiene que notarlo.

    [SUITE · S1] Y acá se decide también si esa clase queda ENVUELTA por el grabador. Es la
    DECISIÓN 1.A del diseño: se graba en la frontera del transporte, no en la del proceso,
    porque es el único lugar por donde pasan los dos clientes. `envolver()` devuelve la
    clase REAL TAL CUAL cuando `ALEPH_GRABAR`/`ALEPH_REPLAY` están apagadas —que es el
    default—, así que sin perilla el grabador no existe para el producto.
    """
    cls = _resolver("ServidorSDK", lambda: _asm().MCPServer)
    g = _grabador()
    return g.envolver(cls) if g is not None else cls


def cliente_http():
    """La clase para hablar con un MCP remoto por Streamable HTTP.

    `(url, headers=None, *, timeout=45.0, user_agent=...)` + `initialize/list_tools/
    call_tool/close`, iguales en las dos.
    """
    def _viejo():
        from inspection.mcp_http_client import MCPHttpClient
        return MCPHttpClient
    return _resolver("ClienteSdkHttp", _viejo)


def entorno_del_hijo(env: Optional[dict] = None) -> dict:
    """El entorno que el hijo va a recibir DE VERDAD, según el transporte que toque.

    SDK y legacy comparten ahora el mismo baseline mínimo; `None` jamás significa
    heredar credenciales ambientales del host. Quien compare dos pedidos (el dueño)
    debe comparar este valor, no el `env` incompleto que le pasaron.

    El caso que lo destapó: `ensure_user_path()` MUTA `os.environ["PATH"]` la primera vez
    que corre, así que dos `dict(os.environ)` tomados antes y después del primer spawn
    difieren en PATH — y dos pedidos idénticos se veían distintos.
    """
    return _sdk().entorno_hijo(env)


def error_http() -> tuple:
    """Las excepciones de transporte HTTP de AMBOS clientes, para un `except` que valga en
    los dos caminos. Devolver una tupla y no una clase es a propósito: durante la migración
    un mismo proceso puede haber hablado por los dos."""
    fuera: list = []
    try:
        from inspection.mcp_http_client import MCPHttpError
        fuera.append(MCPHttpError)
    except Exception:                                      # noqa: BLE001
        pass
    try:
        fuera.append(_sdk().TransporteSdkError)
    except Exception:                                      # noqa: BLE001
        pass
    return tuple(fuera) or (Exception,)


__all__ = ["AUTO", "SDK", "VIEJO", "modo", "elegido", "servidor_stdio", "cliente_http",
           "entorno_del_hijo", "error_http"]
