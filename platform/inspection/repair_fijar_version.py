#!/usr/bin/env python3
"""repair_fijar_version.py — R4 · [FIJAR LA VERSIÓN], el botón que la clase 3 dejó pendiente.

Cuarta sesión de `DISEÑO-REPAIR-v1.md` (§4.2.1). El caso: un belt declara `npx -y @scope/pkg`
sin versión —el patrón de casi todo el catálogo— y el día que el paquete publica algo
incompatible el server arranca y revienta. `diagnostico_conectores` lo tipa bien como
`servidor_incompatible` («no es tu configuración») y **no hay nada que el usuario pueda
apretar**. Esto es ese algo.

──────────────────────────────────────────────────────────────────────────────────
⚠️ **LO QUE EL DISEÑO SUPONÍA Y NO ERA — medido antes de construir.**

El §4.2.1 decía que el pin propuesto sale del registro: «la última versión que dio veredicto
verde». Medido sobre el registro real de este usuario:

    server_info      VACÍO en las 42 filas
    ultimo_veredicto NULL  en las 42 filas

La columna existe desde el contrato de conexiones y **nadie la escribía**: el transporte SÍ
captura `serverInfo` del saludo MCP (`transporte_sdk.py:504`, publicado en `diagnostico()`),
pero `conexiones_verificador` sólo persistía `conexion` y `credencial`. O sea que el dato que
el botón necesita no existía.

Dos consecuencias, y las dos están acá:

  1. R4 **empieza a grabarlo**: al llegar a un veredicto VIVO se persiste `server_info`. Sin
     eso el botón sería decorativo, y un botón decorativo es peor que ningún botón.
  2. Mientras no haya una versión buena conocida, **esto NO propone un pin**. Pinear a la
     versión que está corriendo sería pinear la rotura — el usuario apretaría un botón que
     congela exactamente el problema que quería arreglar. `posible=False` con su motivo, y la
     card cae al camino honesto.

──────────────────────────────────────────────────────────────────────────────────
Y LO QUE SÍ ESTABA SELLADO SE RESPETA: **UPDATE a la fila del usuario, JAMÁS al catálogo.**
El catálogo es dato curado con autor (CLAUDE.md, «el guard no inventa; el catálogo declara»);
un botón de UI que lo reescribe desde la máquina de un usuario convierte un dato auditado en
uno mutable por accidente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Los dos lanzadores donde vive un paquete sin pin. El resto de los `command` son binarios
#: o intérpretes: ahí no hay versión que fijar y este botón no aplica.
_NPX = "npx"
_UVX = "uvx"

#: `@scope/pkg` · `pkg` — y su forma ya pineada, que es la que hay que reconocer para no
#: ofrecer un pin sobre algo que ya lo tiene.
_NPM_PIN = re.compile(r"^(?P<nombre>@[^/@\s]+/[^@\s]+|[^@\s][^@\s]*)@(?P<version>[^@\s]+)$")
_PY_PIN = re.compile(r"^(?P<nombre>[A-Za-z0-9._-]+)(?P<op>==|>=|~=)(?P<version>[^\s]+)$")

#: Lo que en un `args` NO es el paquete: flags y URLs.
_NO_ES_PAQUETE = ("-", "http://", "https://")


@dataclass(frozen=True)
class Propuesta:
    """El plan. **Congelada**: se muestra, se confirma, y recién ahí se aplica."""

    posible: bool
    motivo: str
    entity_id: str = ""
    lanzador: str = ""                    # npx | uvx
    paquete: Optional[str] = None
    version_corriendo: Optional[str] = None
    version_propuesta: Optional[str] = None
    args_antes: list = field(default_factory=list)
    args_despues: list = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"posible": self.posible, "motivo": self.motivo, "entity_id": self.entity_id,
                "lanzador": self.lanzador, "paquete": self.paquete,
                "version_corriendo": self.version_corriendo,
                "version_propuesta": self.version_propuesta,
                "args_antes": list(self.args_antes), "args_despues": list(self.args_despues)}


def _indice_del_paquete(args: list) -> int:
    """Dónde está el paquete dentro de `args`. `-1` si no hay ninguno reconocible."""
    for i, a in enumerate(args or []):
        s = str(a)
        if not s or s.startswith(_NO_ES_PAQUETE) or "${" in s:
            continue
        return i
    return -1


def _ya_pineado(spec: str, lanzador: str) -> Optional[str]:
    """La versión, si ese token ya la trae. `None` si no."""
    m = (_NPM_PIN if lanzador == _NPX else _PY_PIN).match(spec)
    return m.group("version") if m else None


def _pinear(spec: str, version: str, lanzador: str) -> str:
    return f"{spec}@{version}" if lanzador == _NPX else f"{spec}=={version}"


def version_de(evidencia: Any) -> Optional[str]:
    """La versión que está corriendo, del `serverInfo` del saludo MCP.

    Acepta el `diagnostico()` del transporte, el `server_info` pelado, o la fila del
    registro. No inventa: si no está, `None`.
    """
    if not isinstance(evidencia, dict):
        return None
    si = evidencia.get("server_info") or evidencia.get("serverInfo") or evidencia
    if isinstance(si, str):
        try:
            import json
            si = json.loads(si)
        except Exception:                                  # noqa: BLE001
            return None
    if not isinstance(si, dict):
        return None
    v = si.get("version")
    return str(v) if v else None


def proponer(fila: dict, *, version_buena: Optional[str] = None,
             evidencia: Optional[dict] = None) -> Propuesta:
    """El plan para una entidad rota por `servidor_incompatible`. **No escribe nada.**

    `version_buena` es la última versión que se vio andar (del registro). Sin ella no hay
    propuesta: ver el bloque de arriba.
    """
    entity_id = str((fila or {}).get("entity_id") or "")
    command = str((fila or {}).get("command") or "").strip()
    args = list((fila or {}).get("args") or [])
    lanzador = _NPX if command.endswith(_NPX) else (_UVX if command.endswith(_UVX) else "")

    if not lanzador:
        return Propuesta(False, f"«{command or 'sin comando'}» no es npx ni uvx: no hay "
                                f"paquete con versión que fijar", entity_id=entity_id)

    i = _indice_del_paquete(args)
    if i < 0:
        return Propuesta(False, "no encuentro un paquete en los args", entity_id=entity_id,
                         lanzador=lanzador, args_antes=args)

    paquete = str(args[i])
    ya = _ya_pineado(paquete, lanzador)
    if ya:
        # ⚠️ Y ES TAMBIÉN LA RESPUESTA AL «¿y si el pin propuesto TAMBIÉN falla?»: una vez
        # pineado, esto deja de ofrecer pin. Volver a ofrecer el mismo sería un botón que no
        # cambia nada, y ofrecer otro a ciegas sería adivinar. Un pin que falla es un caso
        # de ESCALADA (§5), no de otro pin.
        return Propuesta(False, f"ya está fijado en {ya}: si igual falla, no es la versión",
                         entity_id=entity_id, lanzador=lanzador, paquete=paquete,
                         version_corriendo=ya, args_antes=args)

    corriendo = version_de(evidencia) if evidencia else None
    if not version_buena:
        return Propuesta(False,
                         "no hay ninguna versión conocida que haya andado: no se propone un "
                         "pin a ciegas (pinear la que corre sería congelar la rotura)",
                         entity_id=entity_id, lanzador=lanzador, paquete=paquete,
                         version_corriendo=corriendo, args_antes=args)

    if corriendo and str(version_buena) == str(corriendo):
        return Propuesta(False,
                         f"la versión que anduvo ({version_buena}) es la que está corriendo: "
                         f"el problema no es la versión",
                         entity_id=entity_id, lanzador=lanzador, paquete=paquete,
                         version_corriendo=corriendo, args_antes=args)

    despues = list(args)
    despues[i] = _pinear(paquete, str(version_buena), lanzador)
    return Propuesta(True,
                     f"fijar {paquete} en {version_buena}, que es la última que anduvo",
                     entity_id=entity_id, lanzador=lanzador, paquete=paquete,
                     version_corriendo=corriendo, version_propuesta=str(version_buena),
                     args_antes=args, args_despues=despues)


class SinConfirmar(Exception):
    """Se intentó aplicar sin confirmación. **Reparar es cambiar el mundo.**"""


def aplicar(conn, *, user_id: str, entity_id: str, propuesta: Propuesta,
            confirmado: bool, repo) -> dict:
    """Escribe el pin en LA FILA DEL USUARIO. `repo` es `conexiones_repo` (inyectado para no
    atar `platform/` a `product/backend`).

    ⚠️ **QUIÉN AUTORIZA — corregido en R5, sellado.** `confirmado` NO es «el usuario apretó
    un botón»: es «hay una autoridad que lo autorizó», y para la RECETA esa autoridad es
    **Aleph**. La receta es territorio nuestro, no del usuario: cuando un paquete publica una
    versión incompatible, pedirle permiso para arreglarlo sería mandarle un trámite por un
    problema que no creó. Lo dispara `repair.ajustar_version()`, una sola vez.

    El guard sigue existiendo y sigue sirviendo: sin autorización no se escribe, una
    propuesta imposible no se aplica, y una fila que el registro no conoce no se fabrica.
    Lo que cambió es QUIÉN autoriza, no que se pueda escribir sin autorización.

    ⚠️ **UPDATE, JAMÁS UPSERT.** La fila existe —esto sólo se ofrece sobre algo que estuvo
    conectado— y `upsert_entidad` sólo pisa los campos que se le pasan
    (`conexiones_repo.py:270-271`). Crear una fila acá sería fabricarle al usuario una
    entidad que no equipó (CLAUDE.md §1).

    ⚠️ **Y JAMÁS AL CATÁLOGO.** Arregla la receta DE ESE USUARIO. Que el catálogo se pinee
    es una decisión de catálogo, con autor.
    """
    if not confirmado:
        raise SinConfirmar(
            "el ajuste de versión toca la receta: lo autoriza repair, no se escribe suelto")
    if not propuesta.posible:
        raise SinConfirmar(f"no hay nada que aplicar: {propuesta.motivo}")

    conocidas = {e["entity_id"] for e in repo.listar_entidades(conn, user_id)}
    if entity_id not in conocidas:
        # La misma regla que la persistencia del verificador: lo que el registro no conoce no
        # se fabrica. Se reporta.
        raise SinConfirmar(f"«{entity_id}» no está en el registro de este usuario")

    repo.upsert_entidad(conn, user_id=user_id, entity_id=entity_id, commit=True,
                        args=list(propuesta.args_despues))
    return {"ok": True, "entity_id": entity_id,
            "paquete": propuesta.paquete,
            "version_propuesta": propuesta.version_propuesta,
            "args": list(propuesta.args_despues),
            # La huella cambia sola porque cambian los args ⇒ el breaker viejo queda inerte
            # (§3.3(d)) y el próximo `pedir()` levanta un proceso nuevo con el pin. No hace
            # falta invalidar nada a mano.
            "huella_cambia": True}


__all__ = ["Propuesta", "SinConfirmar", "proponer", "aplicar", "version_de"]
