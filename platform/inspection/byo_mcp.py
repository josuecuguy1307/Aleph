"""
byo_mcp.py — la FORJA del BYO-MCP: "pegá tu MCP → Sumar" deja de ser teatro (FASE 1 · C3).

Toma lo que el usuario PEGA (una URL de MCP HTTP público, o un comando stdio-local) y hace
el camino real, NO la card falsa:

  1. VALIDAR (probe_mcp): conecta de verdad al MCP y le pide la lista de tools. Si no conecta
     o no expone tools → falla HONESTO (cero theater: no se forja una pieza fantasma).
  2. FORJAR (forge_byo_belt): escribe un belt `.mcp.json` equipable (misma forma del catálogo:
     `_meta.cards` por tool + `mcpServers` con el launcher real) bajo la carpeta DURABLE y
     por-usuario de synth_belts. Para HTTP el server del belt es el PUENTE byo_mcp_server.py
     (stdio↔HTTP); para stdio-local es el comando del propio usuario, tal cual.
  3. REGISTRAR (register_byo_into_puppet): agrega el belt a `recipe.belt.belt_refs[]` del puppet
     + sus tools a `tool_filters`, validando la receta antes de guardar (reusa registry.py).

Tras esto, el agente en la Sala equipa esas tools como CUALQUIER otra (assemble_and_run las
cablea por belt_refs[]) y las LLAMA de verdad — gateadas por el motor como todo lo demás.

Decoupled de `app`: reusa registry.py (que ya carga repo.py / recipe_validator.py por ruta).
Stdlib + urllib (no existe el paquete `mcp` acá).
"""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import re
import socket
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from inspection import registry
from inspection import traductor_errores as TR
from inspection import transporte as TP

# [integración tanda-b2] `Path(__file__).parents[2]` es EL idiom que `aleph_paths` existe para
# reemplazar (Casa 2 · Fase 4.1): bajo PyInstaller apunta FUERA del bundle. En el build PUBLIC
# `platform/inspection` no viaja como datos —sólo en el PYZ—, así que `__file__` es
# `<_MEIPASS>/inspection/byo_mcp.pyc` y `parents[2]` sobrepasa un nivel: `_ASSEMBLER_PY` caía en
# `<_MEIPASS>/../platform/assembler/assembler.py`, que no existe. Efecto medido en la .app: TODA
# prueba de un MCP stdio moría con `[Errno 2]` y se reportaba `error_upstream` — o sea, un archivo
# NUESTRO ausente facturado como culpa del proveedor, que es exactamente lo que §8 de FIX-P1B
# prohíbe. Fuera de frozen `resource_root()` devuelve la raíz del repo: comportamiento idéntico.
try:
    import aleph_paths as _ap  # platform/ ya está en sys.path (lo pone `from inspection import …`)
    _REPO_ROOT = _ap.resource_root().resolve()
except Exception:  # noqa: BLE001
    _REPO_ROOT = Path(__file__).resolve().parents[2]
_PROXY_SERVER = _REPO_ROOT / "platform" / "inspection" / "byo_mcp_server.py"
# Lo que se PERSISTE en el belt debe apuntar al bundle de cada arranque, no al
# ``sys._MEIPASS`` temporal del arranque que lo creó.
_PROXY_SERVER_REF = "${PUPPET_REPO}/platform/inspection/byo_mcp_server.py"
_ASSEMBLER_PY = _REPO_ROOT / "platform" / "assembler" / "assembler.py"
_GATES_DIR = _REPO_ROOT / "platform" / "gates"
_TOOL_RESULT_PY = _REPO_ROOT / "platform" / "assembler" / "tool_result.py"
_tool_result_spec = importlib.util.spec_from_file_location("puppet_byo_tool_result", _TOOL_RESULT_PY)
_tool_result_mod = importlib.util.module_from_spec(_tool_result_spec)
_tool_result_spec.loader.exec_module(_tool_result_mod)
es_error_de_tool = _tool_result_mod.es_error_de_tool

_READ_PREFIXES = ("get_", "read_", "search_", "list_", "fetch_", "lookup_", "find_",
                  "query_", "ask_", "describe_", "resolve_", "view_", "show_")

_NICHE = "byo"


class BYOValidationError(Exception):
    """El MCP pegado no validó (no conecta, no expone tools, URL insegura, config inválida)."""

    def __init__(self, message: str, *, evidencia: Optional[dict] = None):
        super().__init__(message)
        self.evidencia = dict(evidencia or {})


def _stdio_probe_env(declared: Optional[dict], scratch: str) -> dict[str, str]:
    """Fresh BYO child environment; the parent's credentials are never the baseline.

    The request's `env` block is the only source of MCP-specific variables. All
    six SDK default variables are present here so its merge cannot reintroduce
    the sidecar's HOME or identity. This does not itself confine filesystem or
    descendants; the execution boundary is separately required for release.
    """
    if declared is not None and not isinstance(declared, dict):
        raise BYOValidationError("el entorno declarado del MCP debe ser un objeto")
    runtime = {
        "PATH": os.environ.get("PATH") or os.defpath,
        "HOME": scratch,
        "TMPDIR": scratch,
        "XDG_CACHE_HOME": scratch,
        "LOGNAME": "aleph-mcp",
        "USER": "aleph-mcp",
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "LANG": "C.UTF-8",
    }
    for key, value in (declared or {}).items():
        if not isinstance(key, str) or not isinstance(value, str) or not key \
                or "=" in key or "\x00" in key or "\x00" in value:
            raise BYOValidationError("variable de entorno MCP inválida")
        runtime[key] = value
    return runtime


# ── carga perezosa de helpers por ruta (mismo patrón que registry/bridge) ───────
_asm_mod = None
_enf_mod = None


def _asm():
    global _asm_mod
    if _asm_mod is None:
        spec = importlib.util.spec_from_file_location("puppet_assembler_byo", _ASSEMBLER_PY)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); _asm_mod = m
    return _asm_mod


def _enf():
    global _enf_mod
    if _enf_mod is None:
        try:
            spec = importlib.util.spec_from_file_location(
                "puppet_enf_byo", _GATES_DIR / "recipe_enforcer.py")
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); _enf_mod = m
        except Exception:
            _enf_mod = False
    return _enf_mod or None


# ── anti-SSRF para el path HTTP (defense-in-depth; el endpoint también guarda) ──

def _guard_http_url(url: str) -> str:
    """Valida que una URL de MCP HTTP sea PÚBLICA y segura. Usa la capa de safety (T9) si
    está; si no, un guard mínimo propio. Levanta BYOValidationError si es insegura."""
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise BYOValidationError("la URL del MCP debe ser http(s)")
    if not parsed.hostname:
        raise BYOValidationError("la URL del MCP no tiene host")

    # 1) capa de safety del org (anti-SSRF curada), si está disponible
    try:
        import sys as _sys
        if str(_REPO_ROOT / "platform") not in _sys.path:
            _sys.path.insert(0, str(_REPO_ROOT / "platform"))
        from safety import url_guard  # type: ignore
        ok, reason = url_guard.is_safe(u)
        if not ok:
            # ⚠️ ESTA RAMA SE COMÍA EL DIAGNÓSTICO. Cuando la capa de safety está presente
            # —o sea SIEMPRE en producción— resuelve el host ella misma y vuelve con su
            # motivo, así que el `getaddrinfo` de más abajo no llega a correr nunca y el
            # `fallo: "dns"` tipado no se ponía. Efecto medido: un dominio inexistente salía
            # como «no pudimos precisar por qué» en vez de «esa dirección no existe».
            # `url_guard` YA distingue el caso (`dns-no-resuelve`); sólo había que no tirarlo.
            fallo = "dns" if str(reason or "").startswith("dns") else "url_bloqueada"
            raise BYOValidationError(
                f"URL rechazada por safety: {reason}",
                evidencia={"fallo": fallo, "host": parsed.hostname, "motivo_safety": reason})
        return u
    except BYOValidationError:
        raise
    except ImportError:
        pass  # safety ausente → guard mínimo abajo

    # 2) guard mínimo: el host no puede resolver a loopback/privado/link-local
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except OSError as e:
        # `fallo` TIPADO, no prosa. Quien levanta sabe qué pasó; el clasificador no tiene por
        # qué re-adivinarlo leyendo un mensaje en castellano que mañana se reescribe.
        raise BYOValidationError(f"no se pudo resolver el host del MCP ({host}): {e}",
                                 evidencia={"fallo": "dns", "host": host})
    for *_unused, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise BYOValidationError(
                f"la URL del MCP apunta a una dirección interna ({ip}); por seguridad solo "
                f"se aceptan MCPs públicos")
    return u


# ── slug / zona ─────────────────────────────────────────────────────────────────

def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "mcp"


def _zone_for(tool_name: str) -> str:
    """fuentes (lee) · entrega (manda/toca plata) · mesa (procesa). Reusa el enforcer si está."""
    enf = _enf()
    if enf is not None:
        try:
            if enf.suggests_send(tool_name) or enf.suggests_money_touch(tool_name):
                return "entrega"
        except Exception:
            pass
    if any(tool_name.startswith(p) for p in _READ_PREFIXES):
        return "fuentes"
    return "mesa"


def _short(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ── 1) VALIDAR: conectar + listar tools ─────────────────────────────────────────

#: Marcas de que el servidor RECHAZÓ la credencial, no de que la tool falló por otra cosa.
#: Se buscan en el texto que devuelve la tool porque MCP no tiene un código de error de
#: auth: un 401 del proveedor llega envuelto en el texto del server.
_MARCAS_CREDENCIAL = (
    "401", "403", "unauthorized", "unauthorised", "forbidden",
    "invalid api key", "invalid_api_key", "invalid key", "api key not valid",
    "authentication failed", "authentication_error", "not authenticated",
    "bad credentials", "invalid token", "expired token", "permission denied",
)


def _ejercitar_credencial(cliente, tools, prueba: Optional[dict]) -> Optional[dict]:
    """Llama UNA tool declarada por el catálogo y decide si la credencial sirve.

    Devuelve `None` cuando no hay prueba declarada — que NO es lo mismo que fallar: es
    «no lo medí», y el caller lo traduce a amarillo, nunca a verde.

    GUARDA: sólo se llama lo que el catálogo declaró y el server publica. Si la tool
    declarada no está en `tools/list`, no se inventa otra — se reporta que la declaración
    quedó vieja, que es un problema del catálogo y no de la credencial del usuario.
    """
    if not isinstance(prueba, dict):
        return None
    tool = str(prueba.get("tool") or "").strip()
    if not tool:
        return None
    args = prueba.get("args")
    args = dict(args) if isinstance(args, dict) else {}

    publicadas = {(t or {}).get("name") for t in (tools or [])}
    if tool not in publicadas:
        return {"tool": tool, "ok": False, "declarada_no_existe": True,
                "detalle": f"el catálogo declara «{tool}» para probar la credencial, pero "
                           f"el servidor no la publica. La declaración quedó vieja: es un "
                           f"problema del catálogo, no de tu llave."}
    try:
        salida = cliente.call_tool(tool, args)
    except Exception as e:                       # noqa: BLE001 — frontera de la sonda
        return {"tool": tool, "ok": False,
                "detalle": f"la prueba de credencial no pudo correr: {type(e).__name__}: {e}"}

    # Los dos clientes NO devuelven lo mismo y hay que normalizarlo a mano: `MCPServer`
    # (stdio) devuelve un str con los errores prefijados «[mcp error …]»/«[tool error …]»,
    # y `MCPHttpClient` devuelve el dict crudo del resultado JSON-RPC, con `isError`.
    # Tratar los dos como texto suelto haría que un `isError` de HTTP pasara por bueno.
    if isinstance(salida, dict):
        contenido = salida.get("content") or []
        texto = "\n".join(str(c.get("text", "")) for c in contenido
                          if isinstance(c, dict)) or json.dumps(salida, ensure_ascii=False)
        fallo = bool(salida.get("isError"))
    else:
        texto = str(salida or "")
        fallo = es_error_de_tool(texto)
    bajo = texto.lower()
    # ⚠️ DÓNDE aparece la marca importa tanto como SI aparece. Dos casos REALES, medidos,
    # que una regla ingenua clasifica al revés:
    #
    #   coingecko.search_docs  respuesta EXITOSA de 5349 chars — documentación que incluye
    #                          la tabla «| 401 | AuthenticationError |». Buscar la marca en
    #                          cualquier parte la leía como rechazo. NO lo es: respondió
    #                          con datos.
    #   context7.resolve-library-id  respuesta EXITOSA de 95 chars cuyo CONTENIDO es
    #                          «Invalid API key. Please check your API key…». Exigir que la
    #                          llamada haya fallado la dejaba pasar como buena. SÍ lo es.
    #
    # Lo que los separa no es el largo ni el éxito: es que un servidor que rechaza pone el
    # rechazo AL PRINCIPIO —es su mensaje—, mientras que una mención incidental aparece
    # enterrada en el medio de otra cosa. Se mira el arranque de la respuesta.
    #
    # Sigue siendo una heurística, y por eso NO es la autoridad para declarar una tool: eso
    # lo decide la PRUEBA DOBLE (llave buena vs basura), que no necesita interpretar texto
    # —sólo que las dos respuestas difieran— y es robusta a los dos casos de arriba.
    _CABEZA = 200
    rechazo = any(m in bajo for m in _MARCAS_CREDENCIAL) if fallo \
        else any(m in bajo[:_CABEZA] for m in _MARCAS_CREDENCIAL)
    if rechazo:
        return {"tool": tool, "ok": False, "rechazada": True,
                "detalle": "el proveedor rechazó la credencial",
                "muestra": texto[:200]}
    if fallo:
        return {"tool": tool, "ok": False,
                "detalle": "la tool de prueba falló por algo que no es la credencial",
                "muestra": texto[:200]}
    return {"tool": tool, "ok": True,
            "detalle": f"«{tool}» respondió con datos usando tu credencial",
            "muestra": texto[:200]}


def probe_mcp(
    *,
    transport: str,
    url: Optional[str] = None,
    headers: Optional[dict] = None,
    command: Optional[str] = None,
    args: Optional[list] = None,
    env: Optional[dict] = None,
    allowed_tools: Optional[list[str]] = None,
    timeout: float = 45.0,
    prueba_credencial: Optional[dict] = None,
) -> dict:
    """Conecta al MCP pegado y devuelve sus tools REALES (cero theater).

    transport: "http" (url) | "stdio" (command/args/env). Devuelve:
      {transport, url|command, server_info, tools:[{name,description,inputSchema}], ...}
    Levanta BYOValidationError si no conecta o no hay tools.

    ⚠️ `prueba_credencial` — `{"tool": str, "args": dict}` — EJERCITA LA CREDENCIAL.

    Listar tools NO prueba la llave: un server arranca y publica su catálogo igual con una
    credencial basura, porque la llave recién viaja cuando se LLAMA una tool. Medido: con
    `clave-falsa-de-prueba-0000` siete conectores quedaban 🟢 con tools completas, y el
    fallo aparecía en medio de una tarea del usuario.

    Corre en el MISMO spawn, entre `tools/list` y el `stop`: una llamada JSON-RPC más, sin
    proceso extra.

    ⚠️ LA TOOL LA ELIGE EL CATÁLOGO Y TIENE QUE SER DE LECTURA. Este código no puede saber
    si una tool escribe — `create_item` y `whoami` son indistinguibles desde acá. Lo sabe
    quien curó el conector, y por eso la declaración vive en el belt. Probar una escritura
    ES escribir: manda el mail, crea el issue, borra el archivo. Lo único que este código
    puede garantizar, y garantiza, es que **sólo se llama lo declarado, con los argumentos
    declarados**: nada que venga del usuario llega acá, y una tool que el server no publica
    no se invoca.

    Devuelve `credencial: {tool, ok, detalle}` — o nada, si no se declaró prueba.
    """
    transport = (transport or "").strip().lower()
    stdio_evidencia: dict = {}
    if transport == "http":
        if not url:
            raise BYOValidationError("falta la URL del MCP (transport=http)")
        safe_url = _guard_http_url(url)
        # EL TRANSPORTE LO ELIGE `transporte` (sesión 2): el puente al SDK por default, el
        # cliente viejo con ALEPH_TRANSPORTE=viejo. La interfaz es la misma; el `except`
        # tiene que valer para los dos porque durante la migración conviven.
        client = TP.cliente_http()(safe_url, headers or {}, timeout=timeout)
        cred_resultado = None
        try:
            client.initialize()
            tools = client.list_tools()
            cred_resultado = _ejercitar_credencial(client, tools, prueba_credencial)
        except TP.error_http() as e:
            raise BYOValidationError(
                f"el MCP no validó: {e}",
                # ⚠️ ACÁ NO SE DECIDE SI LA PIEZA «DECLARA CREDENCIAL». Se intentó con
                # `bool(headers)` y estaba mal de raíz: en la PRIMERA sonda nunca se mandan
                # headers —todavía no hay llave que mandar—, así que todo 401 parecía una
                # pieza que pide algo no declarado. Lo cazó `verify_entrar::6_401_visible`.
                # Quién declara la credencial lo dice el SPEC resuelto, y eso lo sabe el
                # router, no este archivo. Acá viaja sólo lo que acá se midió.
                evidencia={**(getattr(e, "evidencia", None) or {}), **TP.elegido(),
                           "transporte_probado": "http"},
            )
        finally:
            client.close()
        server_info = client.server_info
        ident = {"transport": "http", "url": safe_url, "headers": dict(headers or {})}
    elif transport == "stdio":
        if not command:
            raise BYOValidationError("falta el comando del MCP (transport=stdio)")
        scratch = tempfile.TemporaryDirectory(prefix="aleph-byo-mcp-")
        srv = None
        try:
            child_env = _stdio_probe_env(env, scratch.name)
            srv = TP.servidor_stdio()("byo-probe", command, list(args or []),
                                      env=child_env, rpc_timeout=timeout)
            started = srv.start()
        except BaseException:
            try:
                if srv is not None:
                    srv.stop()
            finally:
                scratch.cleanup()
            raise
        if not started:
            # El texto del hijo es el diagnóstico primario. El mensaje genérico queda sólo
            # como envoltorio estructural para callers legacy; nunca reemplaza la traza.
            # `TR.evidencia_de_arranque` traduce el motivo del transporte a la frase que el
            # clasificador entiende (§2 del recableo) SIN tocar el stderr ni inventar un
            # exit code; para el cliente viejo es la identidad.
            stdio_evidencia = TR.evidencia_de_arranque(srv.diagnostico())
            try:
                srv.stop()
                final = TR.evidencia_de_arranque(srv.diagnostico())
            finally:
                scratch.cleanup()
            # Si seguía vivo y lo terminamos nosotros, conservar `exit_code=None`: -15 habla
            # de nuestro cleanup, no de la causa original.
            if stdio_evidencia.get("exit_code") is None:
                final["exit_code"] = None
                final["terminado_por_aleph"] = True
            stdio_evidencia = {**stdio_evidencia, **final, **TP.elegido()}
            raise BYOValidationError(
                "el proceso local no completó el saludo por stdio",
                evidencia=stdio_evidencia,
            )
        cred_resultado = None
        try:
            tools = srv.list_tools()
            server_info = {}
            # LA CREDENCIAL, en el MISMO spawn: una llamada JSON-RPC más, cero procesos extra.
            cred_resultado = _ejercitar_credencial(srv, tools, prueba_credencial)
        finally:
            try:
                srv.stop()
                stdio_evidencia = TR.evidencia_de_arranque(srv.diagnostico())
            finally:
                scratch.cleanup()
        ident = {"transport": "stdio", "command": command, "args": list(args or []),
                 "env": dict(env or {})}
    else:
        raise BYOValidationError(f"transport no soportado: {transport!r} (usa 'http' o 'stdio')")

    # normalizar + filtrar al subset pedido (si vino)
    norm: list[dict] = []
    seen: set = set()
    allow = set(allowed_tools) if allowed_tools else None
    for t in tools or []:
        name = (t or {}).get("name")
        if not name or name in seen:
            continue
        if allow is not None and name not in allow:
            continue
        seen.add(name)
        fila = {
            "name": name,
            "description": (t.get("description") or "").strip(),
            "inputSchema": t.get("inputSchema") or t.get("input_schema") or {},
        }
        # Las ANOTACIONES del spec MCP (`readOnlyHint`, `destructiveHint`, …) se venían
        # tirando en esta normalización. Son la única pista que el servidor da sobre si una
        # tool lee o escribe, y sin ellas no hay forma de filtrar candidatas a prueba de
        # credencial. Son HINTS, no contratos —el propio spec lo dice—, así que viajan como
        # evidencia para que alguien decida, nunca como permiso automático.
        anot = t.get("annotations") or t.get("_meta", {}).get("annotations")
        if isinstance(anot, dict) and anot:
            fila["annotations"] = anot
        norm.append(fila)
    if not norm:
        # ARRANCÓ Y NO OFRECE NADA. No es un fallo de la pieza ni de su ficha: es una pieza
        # que no sirve para nada todavía, y decirlo así es lo único honesto.
        raise BYOValidationError(
            "el proceso arrancó pero no expone herramientas MCP usables",
            evidencia={**stdio_evidencia, "fallo": "sin_herramientas",
                       "tools_publicadas": len(tools or [])},
        )
    salida = {**ident, "server_info": server_info, "tools": norm}
    if cred_resultado is not None:
        salida["credencial"] = cred_resultado
    return salida


# ── 2) FORJAR: belt equipable + manifiesto ──────────────────────────────────────

class SecretoNoGuardado(RuntimeError):
    """No se pudo poner el header en el llavero, así que NO se escribió nada en disco.

    Es a propósito que esto sea ruidoso: la alternativa —seguir y dejar el token en claro—
    es el bug que S4 vino a cerrar, y un fallback silencioso lo reabre en el primer entorno
    donde el vault no esté."""


def _provider_de(slug: str) -> str:
    """El nombre con el que el llavero conoce a este BYO. `byo-mi-mcp` → `byo_mi_mcp`."""
    return re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")


def _var_de(slug: str) -> str:
    """La env var que el hijo va a recibir. El sufijo `_API_KEY` NO es cosmético:
    `_autofill_recipe_keys` deriva el provider justamente de ese sufijo
    (`recipe_assembler.py:811`), así que cambiarlo rompe la inyección en el run."""
    return _provider_de(slug).upper() + "_API_KEY"


def _headers_seguros(slug: str, headers: dict) -> tuple:
    """(headers_con_placeholder, valores_a_guardar, var). Nada de esto toca disco.

    Un header cuyo valor ya CONTIENE `${VAR}` se deja como está: tanto `${TOKEN}` como
    `Bearer ${TOKEN}` son referencias, no secretos pegados. Es la misma regla que usa el
    registro para `headers_template`.
    """
    var = _var_de(slug)
    seguros, secretos = {}, {}
    for nombre, valor in (headers or {}).items():
        v = str(valor)
        if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", v):
            seguros[nombre] = v
            continue
        seguros[nombre] = "${" + var + ":" + nombre + "}"
        secretos[nombre] = v
    return seguros, secretos, var


def _guardar_secreto(user_id: Optional[str], provider: str, secreto: str) -> None:
    """Al vault cifrado (Fernet), por el MISMO camino que cualquier otra credencial BYOK.

    El import es perezoso y adentro de la función a propósito: `platform/` no depende de
    `product/backend` en su superficie estática (misma regla que R2), y este es el único
    punto de todo el módulo que necesita el llavero."""
    if not user_id:
        raise SecretoNoGuardado("no hay user_id: sin dueño no hay llavero donde guardarlo")
    try:
        # Sin asumir el sys.path, por el mismo motivo que `db._sqlite()`: quien forja un BYO
        # no siempre es el proceso del backend (también el CLI y las varas), y un import que
        # sólo resuelve adentro de uvicorn haría que el camino seguro fallara justo en los
        # entornos donde nadie lo está mirando.
        import sys as _sys
        _bk = str(_REPO_ROOT / "product" / "backend")
        if _bk not in _sys.path:
            _sys.path.insert(0, _bk)
        from app.phase1 import repo                       # noqa: PLC0415 — a propósito
        conn = repo.get_conn()
    except Exception as e:                                # noqa: BLE001
        raise SecretoNoGuardado(f"el llavero no está disponible: {type(e).__name__}: {e}")
    try:
        repo.upsert_key(conn, user_id=user_id, provider=provider, secret=secreto)
    except Exception as e:                                # noqa: BLE001
        raise SecretoNoGuardado(f"no se pudo escribir la credencial: {type(e).__name__}: {e}")
    finally:
        try:
            conn.close()
        except Exception:                                 # noqa: BLE001
            pass


def forge_byo_belt(probe: dict, *, user_id: Optional[str], label: Optional[str] = None) -> dict:
    """Escribe el belt (+ manifest.json para el puente HTTP) bajo synth_belts/<user>/<slug>/
    y devuelve el registro listo para componer (belt_ref relativo, server_name, tools)."""
    transport = probe["transport"]
    server_info = probe.get("server_info") or {}
    tools = probe["tools"]
    tool_names = [t["name"] for t in tools]

    # nombre legible + slug estable
    if transport == "http":
        host = urlparse(probe["url"]).hostname or "mcp"
        nice = label or server_info.get("name") or host
    else:
        nice = label or server_info.get("name") or Path(probe["command"]).name or "mcp"
    slug = "byo-" + _slug(nice)
    server_name = slug  # clave en mcpServers + backed_by de cada card

    out_dir = registry.belt_dir_for(user_id, slug)
    out_dir.mkdir(parents=True, exist_ok=True)

    if transport == "http":
        # ── S4 · LOS HEADERS VAN AL LLAVERO; EL MANIFEST GUARDA NOMBRES ────────────────
        # Antes de esto, el `Authorization: Bearer …` que el usuario pega se escribía
        # VERBATIM acá, en un archivo `-rw-r--r--`. Era el único camino del producto que
        # esquivaba la regla que el resto sí cumple (`conexiones_repo._sin_secretos`: el
        # registro guarda nombres, jamás valores). Ahora el BYO-HTTP la cumple igual:
        # el valor va cifrado al vault y el manifest queda con un `${VAR}` — que es
        # exactamente lo que el puente ya sabía expandir (`byo_mcp_server._expand_env`).
        crudos = probe.get("headers") or {}
        has_secret = bool(crudos)
        seguros, secretos, var = _headers_seguros(slug, crudos)
        if secretos:
            # FALLA CERRADO. Si el llavero no está, NO se escribe el manifest: un BYO que
            # se registra dejando el token en claro es peor que uno que no se registra, y
            # el usuario puede volver a pegarlo. Guardar «por las dudas» es cómo un
            # agujero cerrado vuelve a abrirse en el primer entorno raro.
            _guardar_secreto(user_id, _provider_de(slug), json.dumps(secretos))
        manifest = {
            "url": probe["url"],
            "headers": seguros,
            "allowed_tools": tool_names,
            "label": nice,
        }
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        # 0600 SIEMPRE, tenga o no headers: la URL de un MCP privado también es del usuario,
        # y un permiso que depende de si hoy hay secreto se olvida el día que lo haya.
        try:
            manifest_path.chmod(0o600)
        except OSError:                                   # noqa: PERF203 — FS sin permisos
            pass
        server_cfg = {
            "command": "python3",
            "args": [_PROXY_SERVER_REF, str(manifest_path)],
            "caso": 1, "bucket": "B1", "nichos": [_NICHE],
            "credenciales": "header" if has_secret else "ninguna",
            "atomica": False,
            "description": f"MCP propio (HTTP): {nice}",
            "byo": {"transport": "http", "url": probe["url"]},
        }
        if secretos:
            # El `${VAR}` SIN RESOLVER en el bloque `env` es la declaración de credencial
            # de todo el árbol: `_pide_llave` la lee así y `_autofill_recipe_keys` deriva
            # el provider del nombre (`BYO_X_API_KEY` → `byo_x`), así que el run inyecta
            # el valor sin una línea de plomería nueva.
            server_cfg["env"] = {var: "${" + var + "}"}
            server_cfg["connector"] = _provider_de(slug)
    else:  # stdio-local: el comando del propio usuario, tal cual
        manifest_path = None
        server_cfg = {
            "command": probe["command"],
            "args": list(probe.get("args") or []),
            "env": dict(probe.get("env") or {}),
            "caso": 1, "bucket": "B1", "nichos": [_NICHE],
            "credenciales": "ninguna",
            "atomica": False,
            "description": f"MCP propio (local): {nice}",
            "byo": {"transport": "stdio", "command": probe["command"]},
        }

    cards = []
    for t in tools:
        name = t["name"]
        cards.append({
            "id": f"{server_name}.{name}",
            "label": name.replace("_", " "),
            "sub": _short(t.get("description") or f"tool de tu MCP: {nice}"),
            "auth": "keyless",
            "armario": "apps",
            "backed_by": server_name,
            "tools": [name],
            "zone": _zone_for(name),
            "byo": True,
        })

    belt = {
        "_meta": {
            "belt": slug, "slug": slug,
            "que_es": f"MCP propio del usuario: {nice}",
            "byo": True,
            "source": {"transport": transport,
                       "ref": probe.get("url") or probe.get("command")},
            "cards": cards,
        },
        "mcpServers": {server_name: server_cfg},
    }
    belt_path = out_dir / f"belt-{slug}.mcp.json"
    belt_path.write_text(json.dumps(belt, ensure_ascii=False, indent=2), encoding="utf-8")
    belt_ref = registry.durable_belt_ref(belt_path)

    return {
        "belt_ref": belt_ref,
        "belt_path": str(belt_path),
        "manifest_path": str(manifest_path) if manifest_path else None,
        "server_name": server_name,
        "tools": tool_names,
        "cards": cards,
        "slug": slug,
        "label": nice,
        "transport": transport,
        "belt": belt,
    }


# ── 3) REGISTRAR: el belt → recipe.belt_refs[] del puppet (additivo + validado) ──

def register_byo_into_puppet(puppet_id: str, belt_ref: str, server_name: str,
                             tool_names: list[str], *, conn=None,
                             repo_root: Path = _REPO_ROOT) -> dict:
    """Agrega el belt (y TODAS sus tools) a la receta del puppet en UNA sola escritura
    validada. Reusa las primitivas de registry.py (merge additivo + re-validación +
    rollback si nuestro cambio rompe una receta antes válida)."""
    r = registry.repo()
    own = conn is None
    conn = conn or r.get_conn()
    try:
        puppet = r.get_puppet(conn, puppet_id)
        if puppet is None:
            raise ValueError(f"puppet '{puppet_id}' no existe")
        config = puppet["config"] if isinstance(puppet.get("config"), dict) else {}
        new_config = config
        already_all = True
        for tn in (tool_names or []):
            new_config, already = registry._merge_belt_into_config(
                new_config, belt_ref, server_name, tn)
            already_all = already_all and already
        validation = registry._validate_change(config, new_config, repo_root)
        updated = r.update_config(conn, puppet_id, new_config)
        belt = (updated or {}).get("config", {}).get("belt", {}) if updated else new_config.get("belt", {})
        return {
            "registered": True,
            "already_present": already_all,
            "puppet_id": puppet_id,
            "belt_ref": belt_ref,
            "belt_refs": belt.get("belt_refs", []),
            "tool_filters": belt.get("tool_filters", {}),
            "validation": validation,
        }
    finally:
        if own:
            conn.close()


# ── orquestación: validar → forjar → (registrar) ────────────────────────────────

def forge_byo(
    *,
    transport: str,
    user_id: Optional[str] = None,
    puppet_id: Optional[str] = None,
    url: Optional[str] = None,
    headers: Optional[dict] = None,
    command: Optional[str] = None,
    args: Optional[list] = None,
    env: Optional[dict] = None,
    label: Optional[str] = None,
    allowed_tools: Optional[list[str]] = None,
    conn=None,
) -> dict:
    """El acto completo del BYO: probe (validar) → forge (belt) → register (si hay puppet).
    Devuelve un dict con el resultado real. Levanta BYOValidationError si no valida."""
    probe = probe_mcp(transport=transport, url=url, headers=headers, command=command,
                      args=args, env=env, allowed_tools=allowed_tools)
    forged = forge_byo_belt(probe, user_id=user_id, label=label)
    out = {
        "ok": True,
        "validated": True,
        "transport": forged["transport"],
        "server": forged["server_name"],
        "label": forged["label"],
        "belt_ref": forged["belt_ref"],
        "tools": forged["tools"],
        "cards": forged["cards"],
        "registered": False,
    }
    if puppet_id:
        reg = register_byo_into_puppet(puppet_id, forged["belt_ref"], forged["server_name"],
                                       forged["tools"], conn=conn)
        out["registered"] = True
        out["puppet_id"] = puppet_id
        out["belt_refs"] = reg["belt_refs"]
        out["tool_filters"] = reg["tool_filters"]
        out["already_present"] = reg["already_present"]
        out["validation"] = reg["validation"]
    return out


__all__ = [
    "BYOValidationError",
    "probe_mcp",
    "forge_byo_belt",
    "register_byo_into_puppet",
    "forge_byo",
]
