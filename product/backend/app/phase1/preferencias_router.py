"""preferencias_router.py — los ajustes de la casa, por dueño. [Convergencia · Superficie 3 · Fase 2]

  GET /v1/preferencias?ambito=casa|<workspace>    los ajustes RESUELTOS + el vocabulario
  PUT /v1/preferencias                            merge de {cambios} en un ámbito

AUTHZ: dueño obligatorio en los dos, por `authz_http.owner_or_401` —el mismo guardián que
usan chats, instrucciones y búsqueda; no hay una cuarta copia. El PUT además está cerrado
por el middleware `_require_session_by_default` (toda mutación /v1 exige sesión salvo lista
blanca explícita), así que el 401 del PUT tiene dos candados y ninguno depende de que este
archivo se acuerde. El GET **no** lo cubre el middleware —sólo mira mutaciones—, y por eso
el suyo es el que de verdad hace falta acá.

EL ÁMBITO. Un ajuste es de toda la casa (`casa`) o de un espacio. La resolución es
espacio > casa > default declarado, que es la precedencia que
`AUDITORIA-IMPACTO-CONVERGENCIA-Y-MAPA-CABLEADO.md §5.2` ya recomienda en sus puntos 4 y 5.
Esto es lo que la fase 3 va a rotular `TODA LA CASA` / `SÓLO <workspace>` —los dos rótulos
que se toman de Oficina—: el contrato entra ahora para que la cara sea dos strings y no una
migración.

QUÉ HAY ADENTRO HOY, Y QUÉ NO. Tres ejes, los tres transversales y los tres **sin casa hoy**:
tamaño de texto (de Legal), idioma de salida del modelo (de Educación) y tema de bloques de
código (de Educación). `tema` e `idioma` NO están: hoy los escribe `localStorage`
(`theme.js`, `i18n.js`) y agregarlos antes de darles la vuelta al escritor dejaría dos
escritores del mismo valor. Entran en la fase 1, el mismo día que se mueve el escritor.

ADVERTENCIA HONESTA, escrita acá para que nadie la descubra tarde: **hoy nadie CONSUME estos
tres ajustes**. Guardarlos es correcto —un endpoint que persiste lo que le mandan no miente—,
pero dibujar un control para ellos antes de que exista quien los lea sería exactamente la
perilla pintada que esta superficie acaba de extirpar de Ajustes. La cara va en la fase 3, y
va junto con su lector.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.phase1.authz_http import owner_or_401

_DETALLE = "Inicia sesión para ver tus preferencias."
_COPY = "Inicia sesión para ver tus preferencias."


class PreferenciasRequest(BaseModel):
    ambito: Optional[str] = None
    #: `{clave: valor}`. Un valor `None` devuelve ese ajuste a su default — es explícito,
    #: no es «me olvidé de mandarlo»: lo que no viene en el dict no se toca (merge).
    cambios: Dict[str, Any] = {}


def _memoria():
    from workspaces import memoria
    return memoria


def _http_de(err: Exception) -> HTTPException:
    """Traduce la causa TIPADA del almacén a HTTP, con su copy. La causa no se inventa acá:
    sale de `memoria.CAUSAS`, que es donde vive el copy de cada una."""
    memoria = _memoria()
    causa = getattr(err, "causa", "") or "error"
    detalle = getattr(err, "detalle", "") or str(err)
    copy = memoria.CAUSAS.get(causa) or "No pude guardar ese ajuste."
    estado = 401 if causa == "sin_dueno" else 400
    return HTTPException(status_code=estado, detail={
        "error": causa, "detail": detalle, "copy": copy})


#: Los ajustes que NO valen en todos lados, con la condición que los hace valer. Lo que no
#: está acá es transversal y aplica siempre.
def _forma_de(ws: str) -> Optional[str]:
    """La `config_shape` declarada para ese espacio, o `None` si no se pudo saber.

    ⚠️ EL `None` NO ES «no aplica»: es «no sé». Se separa del veredicto a propósito — la
    primera versión de esto se comía la excepción y devolvía `None`, y con eso el control
    desaparecía TAMBIÉN en Oficina, que es donde sí gobierna. Un fallo de lectura no puede
    convertirse en silencio en un «no».
    """
    try:
        from app.phase1.router import _WORKSPACE_STACKS
    except Exception:
        return None
    meta = _WORKSPACE_STACKS.get(ws)
    return (meta or {}).get("config_shape")


def _url_del_pack(ws: str, owner: Optional[str]) -> Optional[str]:
    """La URL del pack de ese espacio si está CORRIENDO, o `None`.

    Se pregunta por `(dueño, workspace)` porque el pack corre por dueño: una cuenta no
    tiene por qué proyectarle un ajuste al proceso de otra.
    """
    try:
        from app.phase1.router import _WORKSPACE_STACKS
        from workspaces import pack as ws_pack
    except Exception:
        return None
    meta = _WORKSPACE_STACKS.get(ws)
    if not meta:
        return None
    try:
        vivo = ws_pack.vivo(ws, meta, user_id=owner)
    except Exception:  # noqa: BLE001 — no saber si corre no puede tumbar un guardado
        return None
    if not vivo or not vivo.get("atiende"):
        return None
    return vivo.get("url") or None


def _proyectar_al_stack(owner: Optional[str], ambito: Optional[str], resueltos: dict) -> dict:
    """Lleva los ajustes recién guardados hasta el stack que los lee. Nunca levanta."""
    memoria = _memoria()
    ws = (ambito or "").strip().lower()
    if not ws or ws == memoria.CASA:
        return {"ws": "", "intentado": False, "ok": False, "causa": "ambito_casa"}
    try:
        from workspaces import puentes
        return puentes.proyectar(ws, _url_del_pack(ws, owner), resueltos, memoria.declarados())
    except Exception as e:  # noqa: BLE001
        return {"ws": ws, "intentado": False, "ok": False, "causa": f"error:{e}"}


def _aplican_en(ambito: Optional[str]) -> list:
    """Las claves que en ESTE ámbito tienen un lector de verdad.

    `compactacion` la escribe `pack.py::_declarar_plugin_al_motor` en el `opencode.json` que
    genera al entrar, y ese escritor corre **sólo** para la forma `openwork_server` — que
    hoy declara únicamente Oficina (`router.py`, fila `oficina`). Se pregunta por la FORMA y
    no por el id del espacio: el día que un segundo stack use el mismo motor, aparece solo.
    """
    memoria = _memoria()
    claves = list(memoria.AJUSTES.keys())
    ws = (ambito or "").strip().lower()
    if ws and ws != memoria.CASA:
        forma = _forma_de(ws)
        if forma != "openwork_server":
            claves = [k for k in claves if k != "compactacion"]
    else:
        # En la casa no hay motor que la lea: es un ajuste DE ESPACIO.
        claves = [k for k in claves if k != "compactacion"]

    # [rediseño · fase 4] LO MISMO, PERO DECLARADO EN LA TABLA. `compactacion` pregunta por
    # la FORMA del motor (arriba) porque el día que un segundo stack use OpenWork tiene que
    # aparecer solo. Los ajustes de un oficio concreto no son así: los lee UN stack y su
    # tabla lo dice con `lee_ws`. Con esto, agregar la fila de otro espacio cuesta una
    # entrada en `memoria.AJUSTES` y cero líneas acá.
    #
    # ⚠️ Y SI NO HAY PUENTE, NO APLICA. Que un stack LEA un ajuste no alcanza: hace falta
    # que la casa pueda escribírselo. Un control cuyo valor no puede llegar al lector es la
    # perilla pintada de siempre, ahora con más pasos.
    from workspaces import puentes
    for k, meta in memoria.AJUSTES.items():
        lee = meta.get("lee_ws")
        if not lee:
            continue
        if ws not in lee or ws not in puentes.PUENTES:
            claves = [c for c in claves if c != k]
    return claves


def build_preferencias_router() -> APIRouter:
    router = APIRouter(prefix="/v1/preferencias", tags=["preferencias"])

    @router.get("")
    def leer(ambito: Optional[str] = Query(default=None, max_length=60),
             authorization: Optional[str] = Header(default=None)):
        owner = owner_or_401(authorization, detail=_DETALLE, copy=_COPY)
        memoria = _memoria()
        try:
            return {
                "ambito": ambito or memoria.CASA,
                "ajustes": memoria.ajustes(owner, ambito),
                # El vocabulario viaja CON los valores para que la pantalla dibuje las
                # opciones desde acá. Una lista de opciones escrita en el front es una
                # lista que se desincroniza el día que se agrega un valor.
                "declarados": memoria.declarados(),
                # QUIÉN LO LEE, POR ÁMBITO. Que un ajuste EXISTA no quiere decir que en este
                # espacio alguien lo consuma: `compactacion` sólo la lee el motor de Oficina.
                # Sin este campo, la pantalla dibujaba el control en los seis y en cinco no
                # gobernaba nada — la perilla pintada que esta casa extirpa desde la fase 0.
                # Va acá y no en el front por lo mismo que `declarados`: una lista escrita en
                # la cara se desincroniza el día que un segundo motor lo lea.
                "aplican": _aplican_en(ambito),
            }
        except memoria.MemoriaError as e:
            raise _http_de(e)

    @router.put("")
    def guardar(body: PreferenciasRequest,
                authorization: Optional[str] = Header(default=None)):
        owner = owner_or_401(authorization, detail=_DETALLE, copy=_COPY)
        memoria = _memoria()
        try:
            resueltos = memoria.ajustar(owner, body.ambito, body.cambios or {})
        except memoria.MemoriaError as e:
            raise _http_de(e)

        # [rediseño · fase 4] Y ACÁ SE CRUZA AL STACK. Guardarlo en la casa no es que
        # gobierne: el que obedece es el motor del workspace, que lee otra cosa en otro
        # momento. `puentes.proyectar` lo lleva hasta ahí — por la costura que el propio
        # stack expone, nunca escribiéndole un archivo por atrás.
        #
        # EL PARTE VIAJA EN LA RESPUESTA, y eso es deliberado: si el pack está apagado la
        # pantalla tiene que poder DECIRLO en vez de mostrar un tilde. Un puente que falla
        # en silencio es indistinguible de uno que no existe.
        parte = _proyectar_al_stack(owner, body.ambito, resueltos)
        return {"ok": True, "ambito": body.ambito or memoria.CASA, "ajustes": resueltos,
                "puente": parte}

    return router
