"""
traductor_errores.py — la taxonomía del SDK oficial → las causas tipadas de Aleph.

REGLA MADRE DE ESTA CAPA: **el diagnóstico no cambia de lógica, cambia de FUENTE.** Las
causas tipadas son las mismas, los veredictos son los mismos, los textos que el usuario lee
son los mismos. Lo único distinto es de dónde sale la señal de error: antes de una regex
sobre el texto que devolvía el cliente viejo, ahora de un código JSON-RPC que el SDK sí
tipa. Si un veredicto cambia de valor para el mismo servidor, es un bug de esta capa.

Es **PURA**: recibe hechos ya medidos y devuelve hechos normalizados. No importa `mcp`, no
abre procesos, no toca la red. Por eso sus pruebas corren en cualquier intérprete —con SDK
o sin él— y por eso puede calibrarse con el mismo input en backend, frozen y tests. Mismo
patrón que `diagnostico_conectores`, que es su consumidor principal.

── LOS TRES ACOPLAMIENTOS QUE ESTA CAPA EXISTE PARA CERRAR ─────────────────────────
Medidos en la sesión 1 y verificados acá con un test cada uno:

1. **`veredicto_conexion` daba VIVA a un server MUERTO.** El cliente viejo devolvía
   «[MCP error: no response from X]» y `_NO_CONTESTO` lo cazaba por la frase «no response».
   El SDK devuelve «[MCP error: {'code': -32000, 'message': 'Connection closed'}]», que NO
   matchea ninguna de esas palabras («connection reset» sí está en la regex; «connection
   closed» no) → el texto no estaba vacío → **se reportaba el server como vivo**. El peor
   error posible del recableo, y silencioso.

2. **`diagnostico_conectores` perdía `no_es_mcp`.** La regla busca literalmente «no
   respondió al saludo initialize de MCP» / «no completó el saludo por stdio». El puente
   dice «MCPError: Request 'initialize' timed out». Sin traducir, ese fallo caía a
   `desconocido` — el cubo que este árbol viene achicando hace meses.

3. **`_versiones_protocolo` inventaba una deriva.** Calcula
   `incompatible = cliente != servidor`. El SDK pide `2026-07-28` y negocia hacia abajo
   (exa: `2025-11-25`), así que TODA conexión por el puente tenía dos fechas distintas y
   cualquier fallo posterior se etiquetaba `deriva_protocolo`. Una negociación EXITOSA no
   es una deriva: es el protocolo funcionando. Ver `protocolo_de()`.

Referencia completa de lo medido: `platform/inspection/MAPA-ERRORES-SDK.md`.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Optional

# ── 1 · LOS CÓDIGOS DEL SDK (medidos en sesión 1, no leídos de la spec) ─────────────
#: `Request '<método>' timed out` — la request no volvió a tiempo. El server puede estar
#: vivo y lento.
TIMEOUT = -32001
#: `Connection closed` — el transporte se cayó. En stdio: el hijo murió. En HTTP: DNS que
#: no resuelve, puerto cerrado o corte a mitad, LOS TRES aplastados en este mismo código
#: (por eso el puente recupera el status y el motivo de red por su cuenta).
CONEXION_MUERTA = -32000
#: `Server returned an error response` — un HTTP no-2xx. El status verdadero lo pone el
#: puente en `http_status`; el SDK solo no lo tiene.
ERROR_INTERNO = -32603
#: `UnsupportedProtocolVersion` — el único caso en que hablar de deriva es honesto.
PROTOCOLO_NO_SOPORTADO = -32022

#: Nuestras causas tipadas de conexión. Se declaran por VALOR y no se importan de
#: `conexiones_verificador` a propósito: esta capa no puede depender del backend, porque
#: entonces no podría probarse ni usarse desde `platform/`. Los dos lados tienen un test
#: que verifica que no se separaron (`test_traductor_errores.py::test_las_causas_no_derivan`).
C_TIMEOUT = "timeout"
C_SIN_RESPUESTA = "sin_respuesta"
C_ARRANQUE = "arranque"
C_SIN_TOOLS = "sin_tools"

#: La frase EXACTA que `diagnostico_conectores._clasificar` busca para dar `no_es_mcp`.
#: Está copiada, no importada, por el mismo motivo que las causas — y hay un test que la
#: compara contra el clasificador real para que no se separen en silencio.
SALUDO_SIN_RESPUESTA = "el proceso arrancó pero no respondió al saludo initialize de MCP"
SALUDO_RECHAZADO = "el servidor rechazó el saludo MCP"
NO_ARRANCO = "no pude iniciar el proceso MCP"

#: Lo que el cliente VIEJO decía cuando el canal se cortó. Se conserva porque el traductor
#: tiene que entender las DOS taxonomías: durante la migración conviven, y después sigue
#: siendo lo que un registro viejo tiene persistido.
_VIEJO_NO_CONTESTO = re.compile(
    r"(timed out|timeout|no response|sin respuesta|broken pipe|connection reset"
    r"|no se pudo iniciar)", re.I)

_RE_CODIGO = re.compile(r"'code'\s*:\s*(-?\d+)")
_RE_MCP_ERROR = re.compile(r"^\[MCP error:\s*(.*)\]\s*$", re.S)


# ── 2 · LEER UN ERROR ───────────────────────────────────────────────────────────────

def codigo_de(texto: Any) -> Optional[int]:
    """El `code` JSON-RPC dentro de un `[MCP error: {...}]`, o `None`.

    Se lee con `ast.literal_eval` sobre el dict —que es como lo serializa el puente— y se
    cae a una regex si eso falla. Las dos leen lo mismo; la segunda existe porque un
    mensaje con comillas raras adentro no tiene por qué tumbar un diagnóstico.
    """
    s = str(texto or "")
    m = _RE_MCP_ERROR.match(s.strip())
    cuerpo = m.group(1) if m else s
    try:
        obj = ast.literal_eval(cuerpo.strip())
        if isinstance(obj, dict) and isinstance(obj.get("code"), int):
            return obj["code"]
    except Exception:                                      # noqa: BLE001 — cae a la regex
        pass
    m2 = _RE_CODIGO.search(s)
    if m2:
        try:
            return int(m2.group(1))
        except ValueError:                                 # pragma: no cover
            return None
    return None


def contesto(texto: Any) -> bool:
    """¿El servidor CONTESTÓ algo? `False` sólo si el canal se cortó o venció.

    Ésta es la función que arregla el acoplamiento #1. Un 401, un `Invalid params` o
    cualquier error DE APLICACIÓN son un «sí»: el mensaje viajó y el servicio respondió —
    la regla que separa las dos preguntas del registro (conexión ≠ credencial). Un timeout
    o una conexión muerta son un «no».
    """
    s = str(texto or "")
    codigo = codigo_de(s)
    if codigo in (TIMEOUT, CONEXION_MUERTA):
        return False
    if codigo is not None:
        return True                                        # error de aplicación: contestó
    if _VIEJO_NO_CONTESTO.search(s):
        return False                                       # taxonomía vieja
    return bool(s.strip())


def causa_de_corte(texto: Any) -> str:
    """`C_TIMEOUT` o `C_SIN_RESPUESTA` para algo que ya se sabe que no contestó.

    Con el SDK el código lo dice; con el cliente viejo hay que mirar el texto. Se prueba
    el código PRIMERO: un `Connection closed` cuyo mensaje mencionara la palabra «time»
    por casualidad se habría clasificado como timeout con la regla vieja.
    """
    s = str(texto or "")
    codigo = codigo_de(s)
    if codigo == TIMEOUT:
        return C_TIMEOUT
    if codigo == CONEXION_MUERTA:
        return C_SIN_RESPUESTA
    return C_TIMEOUT if re.search(r"time", s, re.I) else C_SIN_RESPUESTA


# ── 3 · EL PROTOCOLO ────────────────────────────────────────────────────────────────

def protocolo_de(*, negociada: Optional[str] = None, solicitada: Optional[str] = None,
                 incompatible: bool = False,
                 soportadas: Optional[list] = None) -> dict:
    """El bloque `protocolo` que `diagnostico_conectores._versiones_protocolo` lee.

    **UNA NEGOCIACIÓN EXITOSA NO ES UNA DERIVA.** El clasificador deduce incompatibilidad de
    `cliente != servidor`, y el SDK pide siempre la última revisión (`2026-07-28`) y baja a
    la que el servidor ofrezca. Reportar «pedí X, me dieron Y» sobre un handshake que
    funcionó hacía que cualquier fallo posterior —una tool rota, una llave vencida— saliera
    etiquetado `deriva_protocolo`. Por eso, cuando la negociación cierra bien, las dos
    puntas son la versión NEGOCIADA: es la que efectivamente se está hablando. Lo que se
    pidió se conserva aparte, en `solicitada`, que es evidencia y no entra en la deducción.

    La deriva se declara SÓLO cuando el servidor la declaró: `-32022`
    (`UnsupportedProtocolVersion`), que trae `requested` y `supported` normativos.
    """
    if incompatible:
        out = {"cliente": solicitada, "negociacion": "fallida", "incompatible": True}
        versiones = [v for v in (soportadas or []) if isinstance(v, str) and v]
        if versiones:
            out["servidor"] = versiones[0]
            out["servidor_soportadas"] = versiones
        elif negociada:
            out["servidor"] = negociada
        return {k: v for k, v in out.items() if v is not None}
    out = {"cliente": negociada, "servidor": negociada, "negociacion": "aceptada"}
    if solicitada and solicitada != negociada:
        out["solicitada"] = solicitada
    return {k: v for k, v in out.items() if v is not None}


# ── 4 · LA EVIDENCIA DE UN ARRANQUE FALLIDO ─────────────────────────────────────────

def detalle_de_arranque(bruto: Any) -> str:
    """El `detail` del cliente viejo a partir del mensaje crudo del SDK.

    No es maquillaje: es decir lo mismo con las palabras que el clasificador ya entiende.
    Las tres formas medidas del arranque, y a qué frase corresponde cada una:

        FileNotFoundError: [Errno 2] No such file...  →  se deja TAL CUAL: el clasificador
                                                         ya la caza («no such file or
                                                         directory» → `cli_no_instalado`)
        MCPError: Request 'initialize' timed out      →  el saludo sin respuesta
        MCPError: Connection closed                   →  el saludo sin respuesta
                                                         (el proceso arrancó y se murió
                                                          antes de contestar)

    El motivo crudo del SDK se CONSERVA entre paréntesis: la frase canónica dice qué
    categoría es, el crudo dice qué pasó exactamente, y perder el segundo sería cambiar un
    diagnóstico por una etiqueta.
    """
    s = str(bruto or "").strip()
    if not s:
        return SALUDO_SIN_RESPUESTA
    bajo = s.lower()
    # 1 · YA ESTÁ EN CANÓNICO — el cliente viejo, o un registro persistido por él. Se
    #     devuelve intacto: envolverlo otra vez metería la frase adentro de sí misma.
    #     ⚠️ `NO_ARRANCO` NO entra en esta lista: el puente lo usa como prefijo de TODAS
    #     sus fallas de arranque («no pude iniciar el proceso MCP por el SDK: …»), así que
    #     tratarlo como canónico dejaría sin traducir justo los dos casos que importan.
    #     Las dos frases de abajo sí son terminales: nombran la categoría, no el prefijo.
    for frase in (SALUDO_SIN_RESPUESTA, SALUDO_RECHAZADO):
        if frase.lower() in bajo:
            return s
    # 2 · el arranque que ni siquiera llegó a proceso: el clasificador ya tiene su regla
    #     («no such file or directory» → `cli_no_instalado`), así que sólo hay que no
    #     estorbarla.
    if any(w in bajo for w in ("no such file or directory", "enoent", "command not found",
                               "executable not found", "permission denied")):
        return s if NO_ARRANCO.lower() in bajo else f"{NO_ARRANCO}: {s}"
    # 3 · el proceso arrancó y el saludo no volvió — por vencimiento o porque se cayó
    if "timed out" in bajo or "connection closed" in bajo or "timeout" in bajo:
        return f"{SALUDO_SIN_RESPUESTA} ({s})"
    # 4 · un error JSON-RPC con código propio: el servidor CONTESTÓ y rechazó el saludo
    if codigo_de(s) not in (None, TIMEOUT, CONEXION_MUERTA):
        return f"{SALUDO_RECHAZADO}: {s}"
    return f"{SALUDO_SIN_RESPUESTA} ({s})"


def evidencia_de_arranque(diag: Optional[dict]) -> dict:
    """El `diagnostico()` del puente → la evidencia canónica que los tres consumidores leen.

    Lo que se preserva sin tocar: `stderr` y sus cuatro contadores, `command`, `protocolo`.
    Lo que se traduce: `detail` (ver arriba).
    Lo que NO se inventa NI SE TIRA: **el `exit_code` que el transporte haya podido medir se
    conserva**, y el que no se pudo medir queda en `None`. El puente del SDK nunca lo tiene
    (`stdio_client` no expone el `Process`) y lo acompaña de `exit_code_fuente` (por qué) y
    `murio` (lo único observable: el EOF del pipe de stderr). El cliente viejo sí lo tiene
    —medido: `exit_code: 3` cuando el hijo se muere en el handshake— y esta función **no se
    lo borra**: durante la migración los dos transportes conviven y degradar al que sí mide
    sería perder evidencia por prolijidad.

    El contrato de `MCPServer.diagnostico()` sigue mandando: `None` significa «seguía vivo /
    no medible» y jamás se convierte en un cero inventado.

    Verificado —y es mejor de lo que la sesión 1 temía— que perder `exit_code` **no cambia
    ningún veredicto**: sólo alimenta el texto humano de `diagnostico_conectores.crudo_de`,
    y ninguna regla del clasificador se bifurca por él
    (`test_el_exit_code_ausente_no_cambia_ningun_veredicto`).
    """
    d = dict(diag or {})
    out = dict(d)
    out["detail"] = detalle_de_arranque(d.get("detail") or d.get("stderr") or "")
    code = d.get("exit_code")
    out["exit_code"] = code if isinstance(code, int) else None
    if out["exit_code"] is None and d.get("exit_code_fuente"):
        out["exit_code_fuente"] = d["exit_code_fuente"]
    if "murio" in d:
        out["murio"] = bool(d["murio"])
    return out


__all__ = [
    "TIMEOUT", "CONEXION_MUERTA", "ERROR_INTERNO", "PROTOCOLO_NO_SOPORTADO",
    "C_TIMEOUT", "C_SIN_RESPUESTA", "C_ARRANQUE", "C_SIN_TOOLS",
    "SALUDO_SIN_RESPUESTA", "SALUDO_RECHAZADO", "NO_ARRANCO",
    "codigo_de", "contesto", "causa_de_corte", "protocolo_de",
    "detalle_de_arranque", "evidencia_de_arranque",
]
