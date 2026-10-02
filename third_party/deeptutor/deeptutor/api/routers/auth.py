"""Las CUATRO dependencias de autenticación que el resto de los routers importa.

[Aleph · 2026-08-11] POR QUÉ ESTE ARCHIVO EXISTE Y POR QUÉ NO ES EL DEL UPSTREAM
--------------------------------------------------------------------------------
Nueve routers del tutor (`settings`, `system`, `tools`, `skills`, `knowledge`,
`personas`, `space_mcp`, `mcp_settings`, `outputs`, `subagents`) importan de
`deeptutor.api.routers.auth` alguna de estas cuatro piezas: `require_auth`,
`require_admin`, `ws_require_auth` y `ws_auth_failed`. Sin ellas no se pueden montar,
y sin montarlos el backend publicaba TRES rutas: las 19 pantallas de `/settings/*`
morían con «Could not load settings — HTTP 404» y tres rutas caían en el error boundary
de Next. Eso es lo que este archivo viene a arreglar.

**No se copió el `auth.py` de HKUDS/DeepTutor@456f9c2, a propósito.** Aquel archivo son
871 líneas que, además de estas cuatro funciones, publican un `APIRouter` con `/login`,
`/register`, `/users`, `/users/{username}/role` y `/openai-codex/callback`; e importa
`deeptutor.services.auth` y `deeptutor.services.codex_auth`, dos módulos que esta
importación extirpó (Ley 2.bis y «OAuth Codex», ver EXTIRPACIONES.md). Copiarlo tal cual
reintroduciría cuentas, roles y un segundo camino de identidad/modelo — y ni siquiera
arrancaría, porque esos dos imports no resuelven en este árbol.

Así que acá viven **sólo las dependencias, sin `APIRouter`**: no se publica ningún
endpoint. `/login` y `/register` no existen en Aleph Educación, y no existen porque no
están escritos, no porque alguien los apague en runtime.

LA SEMÁNTICA NO ES INVENTADA: es la rama `AUTH_ENABLED=false` del upstream
------------------------------------------------------------------------------
El propio stack ya estaba escrito para correr sin cuentas, y su `auth.py` lo dice con
todas las letras: «When AUTH_ENABLED=false, all requests are treated as admin». En esa
rama `require_auth` instala el usuario local y devuelve `None`, `require_admin` devuelve
un payload sintético que espeja `local_admin_user()`, y `ws_require_auth` instala el
mismo usuario sin pedir token. Eso es exactamente lo que hay debajo.

Y esa rama es la única alcanzable acá: el launcher del pack
(`platform/workspaces/launchers/deeptutor`) exporta `DEEPTUTOR_AUTH_ENABLED="false"`, el
pack corre en loopback, y quién puede hacer qué lo resuelve Aleph afuera (sesión, dueño,
gates). Por eso no se lee ninguna variable de entorno para decidir: en esta importación
no hay un segundo modo que elegir. Si alguna vez lo hubiera, el cambio es acá y se ve.
"""

from __future__ import annotations

from contextvars import Token as _CtxToken
from dataclasses import dataclass

from fastapi import WebSocket

from deeptutor.multi_user.context import set_current_user
from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME
from deeptutor.multi_user.paths import local_admin_user


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """La forma mínima que los routers leen de un payload de auth.

    El upstream la importa de `deeptutor.services.auth` (extirpado) y trae además
    emisión y validación de JWT. Acá no hay token que decodificar, así que sólo queda
    el dato: quién es el que llama. Los tres campos son los que el código consumidor
    toca (`payload.role`, `payload.user_id`, `payload.username`).
    """

    username: str
    role: str
    user_id: str


def _local_admin_token_payload() -> TokenPayload:
    """El admin sintético, alineado con `local_admin_user()` de `multi_user/paths.py`.

    Mismos `LOCAL_ADMIN_ID` / `LOCAL_ADMIN_USERNAME` que usa el resto del paquete, para
    que las auditorías y las comprobaciones de «¿soy yo?» den lo mismo por los dos caminos.
    """
    return TokenPayload(
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        user_id=LOCAL_ADMIN_ID,
    )


def _install_current_user() -> _CtxToken:
    """Deja el usuario actual en el ContextVar y devuelve su token de reset.

    Punto único: HTTP y WebSocket producen el MISMO objeto de usuario. Saltárselo deja a
    `get_current_path_service()` resolviendo contra el default sin setear — el upstream
    marca ese olvido como la causa raíz de su issue #481, y la nota se conserva acá porque
    el modo de fallo no cambia por tener un solo usuario.
    """
    return set_current_user(local_admin_user())


async def require_auth() -> TokenPayload | None:
    """Dependencia FastAPI de «hay que estar autenticado».

    Instala el usuario local y devuelve `None`, que es lo que el upstream devuelve cuando
    no se exigió ningún JWT. Los consumidores ya contemplan ese `None`: su firma es
    `TokenPayload | None` justamente por esta rama.
    """
    _install_current_user()
    return None


async def require_admin() -> TokenPayload:
    """Dependencia FastAPI de «hay que ser admin».

    Sin cuentas no hay a quién negarle: el único usuario es el admin local. `async def`
    espeja a `require_auth` para que la cadena de dependencias siga en el event loop y el
    ContextVar quede visible para el endpoint.
    """
    _install_current_user()
    return _local_admin_token_payload()


class _WsAuthFailed:
    """Centinela: `ws_require_auth` falló y ya cerró el WebSocket."""


ws_auth_failed: _WsAuthFailed = _WsAuthFailed()


async def ws_require_auth(ws: WebSocket) -> _CtxToken | _WsAuthFailed:
    """Autentica un WebSocket y deja el usuario en el ContextVar.

    Se llama ANTES de `ws.accept()`. Devuelve el token de reset del ContextVar; el que
    llama debe hacer `reset_current_user(token)` en su `finally`, porque una conexión WS
    sobrevive a la tarea que resolvió la dependencia.

    Nunca devuelve `ws_auth_failed` en esta importación —no hay token que pueda faltar—,
    pero el centinela y el tipo de retorno se conservan porque los nueve routers ya están
    escritos contra ese contrato (`if user_token is ws_auth_failed: return`).
    """
    del ws  # sin cuentas no hay token que leer de la query ni de la cookie
    return _install_current_user()
