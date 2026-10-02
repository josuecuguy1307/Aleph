"""Veredicto único y estructurado para conexiones.

Este módulo es deliberadamente puro: recibe hechos ya medidos y devuelve el único objeto
que las superficies deben pintar. No ejecuta probes, no consulta la red y no escribe el
catálogo. Así el clasificador se puede calibrar con el mismo input en backend, frozen y UI.

Contrato público ``veredicto`` (v1):

    {
      version, estado, causa, escalon, corrio,
      patron: {codigo, reconocido, mensaje},
      evidencia: {stderr, exit_code, http_status, respuesta, red, ...},
      camino: {estado:"ejecutable", ...} | {estado:"ausente_declarado", ...},
      presentacion: {plantilla:"diagnostico"|"conexion", titulo, detalle}
    }

``escalon`` es cerrado. El porqué puede quedar desconocido; el lugar nunca. La invariante
más importante vive al final de :func:`producir`: si una sonda declara
``red.consultada:false``, el resultado no puede salir como ``red`` ni ``proveedor`` aunque
una regla anterior o un caller legacy lo hayan pedido.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

VERSION = 1

LOCAL = "local"
RED = "red"
CREDENCIAL = "credencial"
PROVEEDOR = "proveedor"
PLAN = "plan"
NUESTRO = "nuestro"
ESCALONES = frozenset({LOCAL, RED, CREDENCIAL, PROVEEDOR, PLAN, NUESTRO})

SERVIDOR_INCOMPATIBLE = "servidor_incompatible"
DERIVA_PROTOCOLO = "deriva_protocolo"
NO_ES_MCP = "no_es_mcp"
FALLO_DESCONOCIDO = "fallo_desconocido"

_RAW_CAP = 32 * 1024
_VERSION_PROTOCOLO = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _texto(value: Any, cap: int = _RAW_CAP) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        out = value
    else:
        try:
            out = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            out = str(value)
    return out[-cap:]


def _evidencia_publica(ev: Optional[dict]) -> dict:
    src = dict(ev or {})
    out: dict[str, Any] = {}
    # El stderr completo DENTRO DEL CAP es primario. No se resume a la última línea.
    for key in (
        "stderr", "exit_code", "stderr_lineas", "stderr_bytes", "stderr_cap_bytes",
        "stderr_cap_lineas", "terminado_por_aleph", "http_status", "http", "respuesta",
        "snippet", "detail", "transport", "destino", "command", "args", "red",
        "latencia_ms", "provider", "connector", "programa", "paquete", "buscado",
        "como", "url", "motivo",
    ):
        if key not in src or src[key] is None:
            continue
        out[key] = _texto(src[key]) if key in {"stderr", "respuesta", "snippet", "detail"} else src[key]
    # No perder evidencia nueva: se incorpora sólo si es JSON-safe y no es un secreto
    # declarado. Los valores de env/headers nunca entran al veredicto.
    for key, value in src.items():
        if key in out or key.lower() in {"secret", "token", "credential", "headers", "env"}:
            continue
        try:
            json.dumps(value)
        except Exception:
            continue
        out[key] = value
    return out


def crudo_de(evidencia: dict) -> str:
    """El texto primario para clasificar y mostrar, sin descartar ninguna fuente medida."""
    partes = []
    for key in ("stderr", "respuesta", "snippet", "detail"):
        value = _texto(evidencia.get(key))
        if value and value not in partes:
            partes.append(value)
    code = evidencia.get("exit_code")
    if code is not None:
        partes.append(f"exit code: {code}")
    status = evidencia.get("http_status", evidencia.get("http"))
    if status is not None:
        partes.append(f"HTTP {status}")
    return "\n".join(partes)[-_RAW_CAP:]


def _patron(codigo: str, mensaje: str, *, reconocido: bool = True) -> dict:
    return {"codigo": codigo, "reconocido": bool(reconocido), "mensaje": mensaje}


def _versiones_protocolo(evidencia: dict) -> tuple[Optional[str], Optional[str], bool]:
    """Extrae las dos revisiones sólo de campos de negociación medidos.

    No alcanza con encontrar dos fechas en un traceback: para atribuir cada lado hace falta
    el objeto ``protocolo`` del probe o el payload normativo ``requested/supported`` de
    UnsupportedProtocolVersion. Sin esa atribución, el fallo queda desconocido.
    """
    proto = evidencia.get("protocolo")
    proto = proto if isinstance(proto, dict) else {}
    cliente = proto.get("cliente")
    servidor = proto.get("servidor")
    incompatible = proto.get("incompatible") is True

    respuesta = evidencia.get("respuesta")
    if isinstance(respuesta, str):
        try:
            respuesta = json.loads(respuesta)
        except (TypeError, ValueError):
            respuesta = None
    if isinstance(respuesta, dict):
        error = respuesta.get("error") if isinstance(respuesta.get("error"), dict) else {}
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        result = respuesta.get("result") if isinstance(respuesta.get("result"), dict) else {}
        requested = data.get("requested")
        supported = data.get("supported")
        negotiated = result.get("protocolVersion")
        if not cliente and isinstance(requested, str):
            cliente = requested
        if not servidor and isinstance(supported, list):
            servidor = next((v for v in supported if isinstance(v, str) and v), None)
        if not servidor and isinstance(negotiated, str):
            servidor = negotiated
        incompatible = incompatible or error.get("code") == -32022

    cliente = cliente if isinstance(cliente, str) and _VERSION_PROTOCOLO.fullmatch(cliente) else None
    servidor = servidor if isinstance(servidor, str) and _VERSION_PROTOCOLO.fullmatch(servidor) else None
    incompatible = incompatible or bool(cliente and servidor and cliente != servidor)
    return cliente, servidor, incompatible


def camino_ausente(motivo: str, *, fuente: Optional[str] = None) -> dict:
    out = {"estado": "ausente_declarado", "motivo": motivo}
    if fuente:
        out["fuente"] = fuente
    return out


def normalizar_camino(camino: Optional[dict], *, evidencia: dict,
                      escalon: str, estado: str) -> dict:
    """Impide que una frase suelta se disfrace de camino.

    Un camino ejecutable tiene una mano verificable: endpoint, comando, URL, widget o
    acción local conocida. Todo lo demás se vuelve ausencia declarada.
    """
    c = dict(camino or {})
    if c.get("estado") == "ejecutable":
        tiene_mano = any(c.get(k) for k in (
            "endpoint", "comando", "url", "widget", "accion",
        ))
        if tiene_mano:
            return c
    if c.get("estado") == "ausente_declarado" and c.get("motivo"):
        return c
    if estado == "probado":
        return camino_ausente("no hace falta un arreglo")
    if escalon == CREDENCIAL:
        connector = evidencia.get("connector") or evidencia.get("provider")
        return {
            "estado": "ejecutable",
            "accion": "credencial",
            "label": "Conectar",
            "widget": "conexion_inline",
            "connector": connector,
        }
    if escalon in {RED, PROVEEDOR}:
        return {
            "estado": "ejecutable",
            "accion": "probar",
            "label": "Probar de nuevo",
            "endpoint": "/v1/motor/probar",
            "method": "POST",
        }
    if escalon == PLAN:
        return {
            "estado": "ejecutable", "accion": "premium",
            "label": "Ver los planes", "url": "/#premium",
        }
    if escalon == NUESTRO:
        return {
            "estado": "ejecutable", "accion": "copiar_evidencia",
            "label": "Copiar evidencia",
        }
    # LEY · CERO DEAD-ENDS. Esto era la peor combinación: un camino AUSENTE cuyo motivo era
    # una confesión («no encontré un arreglo comprobable»). El usuario quedaba sin salida y
    # con nuestra duda encima. El motivo sigue viajando —lo lee el [?] y la escalada— pero
    # el camino ahora es la tercera salida declarada de la ley.
    return camino_ausente("sin arreglo comprobable para esta causa (interno)")


def _clasificar(*, resultado: dict, evidencia: dict, destino: str) -> tuple[str, dict, str]:
    """Devuelve ``(escalon, patron, causa)``.

    El orden es parte del contrato: trazas del server antes que texto de transporte, HTTP
    autenticado antes que genéricos y desconocido como rama explícita final.
    """
    estado = str(resultado.get("estado") or "")
    causa = str(resultado.get("causa") or "")
    tipo = str(resultado.get("tipo") or "")
    raw = crudo_de(evidencia)
    low = raw.lower()
    status = evidencia.get("http_status", evidencia.get("http"))
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    red = evidencia.get("red") if isinstance(evidencia.get("red"), dict) else {}
    local = (
        tipo in {"mcp", "cli"}
        and (evidencia.get("transport") == "stdio" or not str(destino).startswith(("http://", "https://")))
    ) or evidencia.get("local") is True
    protocolo_cliente, protocolo_servidor, deriva_protocolo = _versiones_protocolo(evidencia)

    if estado == "probado":
        return (LOCAL if local else PROVEEDOR,
                _patron("ok", "La prueba respondió con evidencia."), "")

    if causa in {"falta_key"} or estado == "no_configurado" and tipo == "key":
        return CREDENCIAL, _patron(
            "credencial_ausente", "Falta la credencial para conectar."
        ), "falta_key" if estado == "roto" else causa

    if causa == "oauth_revocado":
        nombre = str(evidencia.get("provider") or destino or "el proveedor")
        nombre = nombre[:1].upper() + nombre[1:]
        return CREDENCIAL, _patron(
            "oauth_revocado", f"Revocaste el acceso desde {nombre}."
        ), causa

    # Knob de calibración: sólo se usa en la vara negativa. No cambia el DÓNDE; apaga
    # exclusivamente el reconocimiento del porqué.
    neutralizado = os.environ.get("ALEPH_DIAGNOSTICO_NEUTRALIZAR", "").strip() == "1"
    if not neutralizado:
        if deriva_protocolo and protocolo_cliente and protocolo_servidor:
            return LOCAL if local else NUESTRO, _patron(
                "deriva_protocolo", "No disponible por ahora.",
            ), DERIVA_PROTOCOLO

        traceback = "traceback" in low or bool(re.search(r'file ".+?", line \d+', low))
        if traceback and re.search(
            r"\b(?:modulenotfounderror|importerror|attributeerror)\b", low
        ):
            # LEY · LA CONFESIÓN ES INTERNA. Decía «Este servidor está roto o es
            # incompatible — no es tu configuración»: dos cosas que el usuario no puede usar
            # («servidor» es vocabulario nuestro) y una disculpa. La causa técnica
            # —`SERVIDOR_INCOMPATIBLE`— viaja igual y la lee el [?], repair y la escalada.
            return LOCAL, _patron(
                "server_roto_o_incompatible", "No disponible por ahora.",
            ), SERVIDOR_INCOMPATIBLE

        if re.search(
            r"\b(?:enoent|command not found|executable not found|no such file or directory)\b",
            low,
        ):
            return LOCAL, _patron(
                "runtime_ausente", "Falta un programa en tu equipo."
            ), "cli_no_instalado"

        if causa == "cli_no_instalado":
            return LOCAL, _patron(
                "runtime_ausente", "Falta un programa en tu equipo."
            ), causa

        if (
            "no completó el saludo por stdio" in low
            or "no completo el saludo por stdio" in low
            or "no respondió al saludo initialize de mcp" in low
            or "no respondio al saludo initialize de mcp" in low
            or ("stdio" in low and any(x in low for x in ("no respondió", "no respondio", "sin respuesta")))
        ):
            return LOCAL, _patron(
                "no_habla_mcp", "No disponible por ahora."
            ), NO_ES_MCP

        if status in (401, 403):
            return CREDENCIAL, _patron(
                "credencial_rechazada", "El servicio rechazó la credencial."
            ), "key_invalida"

        if causa in {"key_invalida"}:
            return CREDENCIAL, _patron(
                "credencial_rechazada", "El servicio rechazó la credencial."
            ), causa

        if causa == "sin_sesion":
            return CREDENCIAL, _patron(
                "sesion_ausente", "Falta iniciar sesión para usar esta conexión."
            ), causa

        if causa in {"plan_insuficiente", "modelo_no_disponible", "sin_credito"}:
            return PLAN, _patron(
                "limite_de_plan", "La conexión respondió, pero tu plan o saldo no cubre esto."
            ), causa

        if causa in {"falla_de_aleph"}:
            return NUESTRO, _patron(
                "defecto_de_aleph", "No disponible por ahora."
            ), causa

        if red.get("consultada") is True and red.get("online") is False:
            return RED, _patron(
                "red_sin_salida", "Tu equipo no tiene salida a internet."
            ), "sin_red"

        if status is not None:
            if 500 <= status <= 599:
                return PROVEEDOR, _patron(
                    "respuesta_5xx", f"El servicio respondió HTTP {status}."
                ), "proveedor_caido"
            return PROVEEDOR, _patron(
                "respuesta_http", "El servicio respondió con un error."
            ), causa or "error_upstream"

        if causa in {"proveedor_caido", "rate_limit"} and red.get("consultada") is not False:
            return PROVEEDOR, _patron(
                causa, "El fallo está en el servicio remoto y la evidencia de red lo sostiene."
            ), causa

        if causa == "sin_red" and red.get("consultada") is True:
            return RED, _patron(
                "red_sin_salida", "Tu equipo no tiene salida a internet."
            ), causa

    # DESCONOCIDO ES PRIMERA CLASE. No se cae al cubo conocido más parecido.
    escalon = LOCAL if local else NUESTRO
    return escalon, _patron(
        "desconocido", "No disponible por ahora.", reconocido=False
    ), FALLO_DESCONOCIDO if estado == "roto" else causa


def producir(resultado: dict, *, destino: Optional[str] = None,
             camino: Optional[dict] = None) -> dict:
    """Produce el único veredicto que deben pintar las superficies."""
    evidencia = _evidencia_publica(resultado.get("evidencia") or {})
    destino_real = str(destino or evidencia.get("destino") or resultado.get("ref") or "")
    evidencia.setdefault("destino", destino_real)
    escalon, patron, causa = _clasificar(
        resultado=resultado, evidencia=evidencia, destino=destino_real
    )

    red = evidencia.get("red") if isinstance(evidencia.get("red"), dict) else {}
    if red.get("consultada") is False and escalon in {RED, PROVEEDOR}:
        # Invariante de construcción, no una convención de callers.
        es_local = evidencia.get("transport") == "stdio" or not destino_real.startswith(
            ("http://", "https://")
        )
        escalon = LOCAL if es_local else NUESTRO
        patron = _patron("desconocido", "No disponible por ahora.", reconocido=False)
        causa = FALLO_DESCONOCIDO if resultado.get("estado") == "roto" else causa

    if escalon not in ESCALONES:  # defensa contra una futura regla mal escrita
        raise AssertionError(f"escalón fuera del contrato: {escalon!r}")

    estado = str(resultado.get("estado") or "detectado")
    corrio = estado in {"probado", "roto"}
    presentacion = {
        "plantilla": (
            "conexion"
            if escalon == CREDENCIAL and estado in {"roto", "no_configurado", "detectado"}
            else "diagnostico"
        ),
        "titulo": patron["mensaje"],
        "detalle": crudo_de(evidencia),
    }
    return {
        "version": VERSION,
        "estado": estado,
        "causa": causa if estado == "roto" else None,
        "escalon": escalon,
        "corrio": corrio,
        "patron": patron,
        "evidencia": evidencia,
        "camino": normalizar_camino(
            camino, evidencia=evidencia, escalon=escalon, estado=estado
        ),
        "presentacion": presentacion,
    }


def aplicar(resultado: dict, *, destino: Optional[str] = None,
            camino: Optional[dict] = None) -> dict:
    """Adjunta el veredicto y alinea los campos legacy con él.

    Los campos legacy siguen viajando para clientes viejos, pero ya no son otra decisión:
    salen del mismo objeto.
    """
    base = dict(resultado)
    verdict = producir(base, destino=destino, camino=camino)
    base["estado"] = verdict["estado"]
    base["causa"] = verdict["causa"]
    base["evidencia"] = verdict["evidencia"]
    base["veredicto"] = verdict
    return base


__all__ = [
    "VERSION", "ESCALONES", "LOCAL", "RED", "CREDENCIAL", "PROVEEDOR", "PLAN",
    "NUESTRO", "SERVIDOR_INCOMPATIBLE", "DERIVA_PROTOCOLO", "NO_ES_MCP",
    "FALLO_DESCONOCIDO",
    "crudo_de", "camino_ausente", "normalizar_camino", "producir", "aplicar",
]
