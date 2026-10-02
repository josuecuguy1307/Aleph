#!/usr/bin/env python3
"""salidas_diferidas.py — una salida de tool se manda ENTERA una vez; después, PLEGADA.

════════════════════════════════════════════════════════════════════════════════
EL NÚMERO QUE JUSTIFICA ESTA PIEZA — medido, no supuesto (2026-08-22, turnos
reales desde la pantalla, 3 turnos por stack, `analizar_prompt.py`):

    stack     cruces   prompt total   catálogo   SALIDAS   resto    re-leído
    legal       10        45.145        12,8 %    16,2 %   71,0 %    ×4,04
    ciencia     11        42.587        19,7 %    10,3 %   70,0 %    ×2,48
    oficina      9        70.757        11,3 %  **73,3 %** 15,3 %    ×6,92

  En Oficina UNA sola salida —el `read` de un CSV de 12,7 KB, **7.358 tokens**— se
  re-mandó **7 veces**: 51.506 tokens pagados por 7.358 de información. Es la pieza
  más grande del turno, más grande que el catálogo por 6×, y nadie la había medido.

  POR QUÉ PASA. Los seis workspaces cruzan con `sesion=None`
  (`workspace_brain.py` no menciona `sesion` ni una vez), así que
  `server._armar_prompt` cae SIEMPRE en `render_prompt(mensajes, …)` — el render
  COMPLETO. Cada salida que ya está en el historial se re-manda entera en cada paso
  posterior y en cada turno posterior de la misma conversación.

  QUÉ **NO** ARREGLA ESTO. La primera vez que una salida cruza, cruza entera: si el
  modelo necesita leer el contenido para razonar sobre él, lo lee. Lo que se saca es
  la REPETICIÓN — mandarle otra vez lo que ya vio y ya usó.

════════════════════════════════════════════════════════════════════════════════
LO QUE NO SE NEGOCIA · **NADA SE RECORTA EN SILENCIO.**

  El pliegue NO es un resumen. Un resumen hecho por un modelo es una interpretación
  y puede mentir; acá el pliegue es DETERMINISTA: la cabeza literal del texto, más
  un encabezado y un pie que dicen exactamente cuánto se recortó y **cómo pedir el
  resto**. El crudo no se destruye: queda en el índice y el modelo lo alcanza con
  `aleph_leer_salida(id, desde)`, que contesta ALEPH — el stack nunca ve esa tool ni
  esa llamada.

  Y hay una regla que hace al pliegue seguro: **la salida más nueva jamás se pliega.**
  Se pliega sólo lo que ya cruzó entero al menos una vez, o sea lo que el modelo YA
  LEYÓ. Plegar algo que nunca vio sería esconderle información — el verde mudo que
  esta casa persigue, con otro disfraz.

════════════════════════════════════════════════════════════════════════════════
LEY 0. Vive entera del lado de Aleph. El stack manda sus `messages` y sus `tools`
como siempre y recibe sus `tool_calls` como siempre; lo único que cambia es lo que
Aleph le manda AL MODELO. La tool del lector no se le declara al stack ni le llega
nunca. Sin la perilla (`ALEPH_SALIDAS_DIFERIDAS_WS=<ws>,<ws>`) esto devuelve los
mensajes tal cual, byte por byte.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional

#: Piso de pliegue. Por debajo de esto el encabezado + el pie cuestan más que lo que
#: se ahorra, así que plegar sería gastar tokens para no ahorrar ninguno. Medido en
#: caracteres porque es lo que se puede contar sin tokenizar en el camino del turno.
PISO_CHARS = 1_600

#: Cuánto de la cabeza literal sobrevive al pliegue. No es un resumen: es el principio
#: del texto tal cual, para que el modelo reconozca DE QUÉ salida se trata.
CABEZA_CHARS = 400

#: Techo de lecturas por paso. Un modelo que entra en bucle pidiendo pedazos no puede
#: colgar el turno; al tocar el techo se le dice y se sigue.
MAX_LECTURAS = 6

#: Cuánto devuelve una lectura si no se pide otra cosa.
TROZO_CHARS = 4_000

NOMBRE_LECTOR = "aleph_leer_salida"


#: EL PLEGADO SE ENVÍA APAGADO, Y ESTO ES UNA DECISIÓN CON DATOS — no una prudencia.
#:
#: ⚠️ SI VINISTE A PRENDERLO, LEÉ ESTO PRIMERO. Está apagado a propósito y por medición;
#: prenderlo sin datos NUEVOS es deshacer una decisión, no configurar.
#:
#: 1 · EN LEGAL, CIENCIA Y OFICINA ESTÁ SUBSUMIDO POR LA SESIÓN DEL CLI. Con la sesión
#:     viva, `server._armar_prompt` manda **sólo la cola**: los mensajes viejos no vuelven
#:     a cruzar. El plegado reescribe salidas QUE YA NO SE ESTABAN MANDANDO — ahorra chars
#:     que no iban a viajar. Lo único que sí cruza es su costo: +73 tok por declarar el
#:     lector en el catálogo. Medido: control 11.794 · plegado 11.830 (**+0,3 %**).
#:     No es que ahorre poco: es que cobra.
#:
#: 2 · DONDE SÍ VALÍA ERA EN LA SALA (−58,6 % en el mundo sin sesión) — y **la Sala no
#:     tiene sesión**. Pero lo que la Sala cobró de verdad no es el plegado: es el
#:     TRUNCADO CON VÍA DE RECUPERACIÓN, y ése **ya está vivo sin esta perilla**. La
#:     cadena `recipe_assembler._bound_tool_result` → `registrar()` → `tool_lector()` no
#:     pasa por `encendido_para`; se dispara con que una salida se cape. Verificado.
#:
#: O sea: prender esto hoy no destraba nada y suma catálogo. Lo que lo volvería a poner
#: sobre la mesa es que la sesión del CLI deje de aplicar en un stack (ahí los mensajes
#: viejos vuelven a cruzar) — y eso es un dato nuevo, con su medición.
POR_DEFECTO = ""


def workspaces_encendidos() -> set:
    """Los workspaces con la perilla puesta. **Por stack, jamás global.**

    Vacío de fábrica: ver `POR_DEFECTO` arriba para por qué, y qué haría falta para
    cambiarlo. `registrar`/`leer` —la vía de recuperación del truncado— NO dependen de
    esto y siguen vivos con la perilla apagada.
    """
    crudo = (os.environ.get("ALEPH_SALIDAS_DIFERIDAS_WS", POR_DEFECTO)).strip()
    return {x.strip().lower() for x in crudo.split(",") if x.strip()}


def encendido_para(workspace: str) -> bool:
    return (workspace or "").strip().lower() in workspaces_encendidos()


# ── EL ÍNDICE ────────────────────────────────────────────────────────────────────
# Vive en el proceso y cuelga de la conversación. Guarda el CRUDO de cada salida que
# alguna vez cruzó, para poder devolverlo cuando el modelo lo pida. Se limpia por
# ociosidad: un índice que crece para siempre es una fuga, no una caché.

_LOCK = threading.Lock()
_INDICES: dict = {}
_OCIOSIDAD_S = 1_800


class Indice:
    def __init__(self, clave: str):
        self.clave = clave
        self.por_id: dict = {}        # sid → {"name", "texto"}
        self.vistas: set = set()      # huellas de salidas que YA cruzaron enteras
        self.tocado = time.time()

    def sid(self, i: int) -> str:
        return "s%d" % i


def _indice(clave: str) -> Indice:
    with _LOCK:
        ahora = time.time()
        for k in [k for k, v in _INDICES.items() if ahora - v.tocado > _OCIOSIDAD_S]:
            _INDICES.pop(k, None)
        ix = _INDICES.get(clave)
        if ix is None:
            ix = _INDICES[clave] = Indice(clave)
        ix.tocado = ahora
        return ix


def _huella(nombre: str, texto: str) -> str:
    return "%s::%d::%s" % (nombre, len(texto), texto[:120])


def tool_lector() -> dict:
    """La ÚNICA tool que Aleph agrega. El stack no la ve nunca."""
    return {"type": "function", "function": {
        "name": NOMBRE_LECTOR,
        "description": (
            "Devuelve el texto COMPLETO de una salida de herramienta que Aleph plegó "
            "para no re-mandarla entera. Úsala cuando necesites una parte que no está "
            "en el fragmento que ves. El `id` es el que dice el pie del fragmento."),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                       "description": "el id que aparece en el pie del fragmento, ej. s3"},
                "desde": {"type": "integer",
                          "description": "carácter desde el que leer (0 = el principio)"},
                "cuanto": {"type": "integer",
                           "description": "cuántos caracteres devolver"},
            },
            "required": ["id"]}}}


def _pliegue(sid: str, nombre: str, texto: str) -> str:
    """El texto plegado. TODO lo que se recorta se dice, y se dice cómo recuperarlo."""
    cabeza = texto[:CABEZA_CHARS]
    recortado = len(texto) - len(cabeza)
    return (
        f"[Aleph plegó esta salida de `{nombre}` porque ya te la mandó entera antes. "
        f"Original: {len(texto)} caracteres. Aquí van los primeros {len(cabeza)}.]\n"
        f"{cabeza}\n"
        f"[… se recortaron {recortado} caracteres. NO están perdidos: pídelos con "
        f"`{NOMBRE_LECTOR}` con id=\"{sid}\" y `desde` en el carácter que quieras. "
        f"Si necesitas el texto completo para contestar, pídelo — no adivines.]")


def plegar(messages: list, workspace: str, clave: str) -> tuple:
    """(mensajes_para_el_modelo, tools_extra, informe).

    Apagado o sin nada que plegar, devuelve los MISMOS mensajes (identidad de objeto
    cuando no se tocó ninguno) y `tools_extra` vacío: el camino de siempre, byte por byte.
    """
    informe = {"plegadas": 0, "chars_ahorrados": 0, "detalle": []}
    if not encendido_para(workspace):
        return messages, [], informe

    ix = _indice(clave)
    msgs = list(messages or [])

    # ── LA MÁS NUEVA NUNCA SE PLIEGA ─────────────────────────────────────────────
    # El modelo todavía no la vio. Plegar lo que no se leyó no es diferir: es esconder.
    ultimo_tool = -1
    for i, m in enumerate(msgs):
        if (m or {}).get("role") == "tool":
            ultimo_tool = i

    salida = []
    n = 0
    for i, m in enumerate(msgs):
        m = m if isinstance(m, dict) else {}
        if m.get("role") != "tool":
            salida.append(m)
            continue
        n += 1
        texto = m.get("content")
        texto = texto if isinstance(texto, str) else json.dumps(texto, ensure_ascii=False,
                                                               default=str)
        nombre = m.get("name") or "herramienta"
        sid = ix.sid(n)
        ix.por_id[sid] = {"name": nombre, "texto": texto}
        h = _huella(nombre, texto)
        if i == ultimo_tool or len(texto) < PISO_CHARS or h not in ix.vistas:
            # Cruza ENTERA. Y queda anotada como vista: la próxima vez sí se pliega.
            ix.vistas.add(h)
            salida.append(m)
            continue
        doblada = _pliegue(sid, nombre, texto)
        if len(doblada) >= len(texto):        # plegar no ahorraría: no se pliega
            salida.append(m)
            continue
        nuevo = dict(m)
        nuevo["content"] = doblada
        salida.append(nuevo)
        informe["plegadas"] += 1
        informe["chars_ahorrados"] += len(texto) - len(doblada)
        informe["detalle"].append({"id": sid, "name": nombre,
                                   "de": len(texto), "a": len(doblada)})

    if not informe["plegadas"]:
        return messages, [], informe
    return salida, [tool_lector()], informe


def _leer(clave: str, args: dict) -> str:
    ix = _indice(clave)
    sid = str((args or {}).get("id") or "").strip()
    fila = ix.por_id.get(sid)
    if fila is None:
        return (f"[Aleph] no existe una salida con id=\"{sid}\". Los ids disponibles "
                f"son: {', '.join(sorted(ix.por_id)) or '(ninguno)'}.")
    texto = fila["texto"]
    try:
        desde = max(0, int((args or {}).get("desde") or 0))
    except (TypeError, ValueError):
        desde = 0
    try:
        cuanto = int((args or {}).get("cuanto") or TROZO_CHARS)
    except (TypeError, ValueError):
        cuanto = TROZO_CHARS
    cuanto = max(1, min(cuanto, 40_000))
    trozo = texto[desde:desde + cuanto]
    fin = desde + len(trozo)
    cola = ("" if fin >= len(texto) else
            f"\n[… quedan {len(texto) - fin} caracteres. Continúa con "
            f"`{NOMBRE_LECTOR}` id=\"{sid}\" desde={fin}.]")
    return (f"[Aleph · salida `{fila['name']}` id=\"{sid}\", caracteres "
            f"{desde}–{fin} de {len(texto)}]\n{trozo}{cola}")


# ── EL ÍNDICE, ABIERTO A QUIEN RECORTE ──────────────────────────────────────────
# El pliegue no es el único que corta. `recipe_assembler._bound_tool_result` CAPA la
# salida más nueva a 3.800 chars —justo la que el pliegue nunca toca a propósito— y
# hasta hoy su pie decía CUÁNTO se recortó y no CÓMO recuperarlo: media regla. Medido
# en la Sala (2026-08-23, dos brazos con grok): 10 de 15 salidas capadas, 124.570 chars
# omitidos, el modelo diciendo cuatro veces «quedó truncado» y los dos brazos cerrando
# sin entregar nada.
#
# En vez de que el capador se arme su propio índice y su propio lector —dos mecanismos
# para la misma regla— se le abre ÉSTE. `registrar` guarda el crudo y devuelve el id;
# `leer` es el mismo `_leer` que ya sirve al pliegue, con su paginado y su cola.
#
# IDS CON PREFIJO `t`, no `s`: `plegar()` numera POSICIONALMENTE (`ix.sid(n)`, el n-ésimo
# mensaje `tool` de la lista) y reescribe `por_id` en cada pasada. Un contador propio con
# el mismo prefijo pisaría esas filas en cuanto las dos vías convivan en un workspace.


def registrar(clave: str, nombre: str, texto: str) -> str:
    """Guarda el CRUDO de una salida y devuelve su id, para que quien la recorte pueda
    decir cómo recuperarla. Es el ÚNICO agregado que necesitó el capador."""
    ix = _indice(clave)
    with _LOCK:
        ix.n_reg = getattr(ix, "n_reg", 0) + 1
        sid = "t%d" % ix.n_reg
        ix.por_id[sid] = {"name": nombre or "herramienta", "texto": texto or ""}
    return sid


def leer(clave: str, args: dict) -> str:
    """El lector, en público. Mismo cuerpo que sirve al pliegue: un segundo lector sería
    una segunda opinión sobre qué es «el resto»."""
    return _leer(clave, args)


def paso(clave: str, workspace: str, messages: list, tools: list,
         llamar_modelo: Callable, on_event: Optional[Callable] = None) -> Optional[dict]:
    """El paso con las salidas diferidas. `None` = no aplica, seguí por el camino normal.

    El bucle es de Aleph y NO se le cuenta al stack: si el modelo pide releer una
    salida, Aleph le contesta y vuelve a preguntar. Lo que sale de acá es siempre una
    jugada que el stack entiende — texto o `tool_calls` de SUS tools.
    """
    plegados, extra, informe = plegar(messages, workspace, clave)
    if not extra:
        return None                     # nada plegado ⇒ camino de siempre, sin desvío

    if on_event:
        try:
            on_event({"type": "aleph_salidas_diferidas", "kind": "aleph",
                      "workspace": workspace, **informe})
        except Exception:               # noqa: BLE001 — avisar no puede tumbar el turno
            pass

    tools_al_modelo = list(tools or []) + extra
    lecturas = 0
    cortado = False
    while True:
        out = llamar_modelo(plegados, tools_al_modelo)
        # ⚠️ DOS FORMAS DE `tool_calls` EN LA MISMA CASA, y confundirlas rompe en silencio.
        # `complete()` devuelve PLANO — `{"id","name","arguments"}` (ver `_openai_message`
        # en router.py, que es quien lo anida para el sobre de OpenAI). Los `messages`,
        # en cambio, viajan ANIDADOS — `{"function":{"name","arguments"}}`, que es lo que
        # `prompt_bridge.render_prompt` lee. Lo que sale de `out` se lee plano; lo que se
        # agrega a `plegados` se escribe anidado.
        calls = (out or {}).get("tool_calls") or []
        lector = [c for c in calls if c.get("name") == NOMBRE_LECTOR]
        if not lector:
            return out                  # jugada del stack: sale tal cual, intacta
        if cortado:
            # ⚠️ EL TECHO TIENE QUE CORTAR DE VERDAD, no sólo sacar la tool.
            # La vara F3 cazó esto: al tocar el techo se le quitaba el lector del
            # catálogo y se seguía en el `while`. Un modelo que igual pide el marcador
            # —cosa que en el camino CLI pasa, porque las tools viajan como TEXTO y el
            # modelo puede repetir el formato que acaba de usar— dejaba el bucle
            # girando para siempre, con el turno colgado y sin una sola señal.
            # Ahora, después del aviso, la llamada al lector se DESCARTA y sale lo que
            # haya: si no hay más que eso, sale el texto; nunca una tool que el stack
            # no tiene.
            restantes = [c for c in calls if c.get("name") != NOMBRE_LECTOR]
            salida = dict(out or {})
            salida["tool_calls"] = restantes
            if not restantes and not (salida.get("content") or "").strip():
                salida["content"] = (
                    "[Aleph] no pude completar este paso: el modelo siguió pidiendo "
                    "releer salidas después del techo de lecturas y no dio una "
                    "respuesta. No se inventó nada.")
            salida["finish_reason"] = ("tool_calls" if restantes else "stop")
            return salida
        if lecturas >= MAX_LECTURAS:
            # Se DICE, no se traga: el modelo tiene que saber por qué dejó de poder leer.
            plegados = plegados + [{
                "role": "user",
                "content": (f"[Aleph] llegaste al techo de {MAX_LECTURAS} lecturas en "
                            f"este paso. Responde con lo que tengas, o di qué te falta "
                            f"— no inventes el contenido que no pudiste leer.")}]
            tools_al_modelo = list(tools or [])
            cortado = True
            continue
        # SÓLO las del lector entran en el mensaje que se agrega. Si el modelo mezcló una
        # tool del stack en el mismo paso, esa llamada NO se arrastra: un `tool_call` sin
        # su `tool` de respuesta deja el historial cojo, y el modelo la vuelve a pedir en
        # la vuelta siguiente ya con el texto que fue a buscar.
        plegados = plegados + [{
            "role": "assistant", "content": out.get("content") or "",
            "tool_calls": [{"id": c.get("id") or ("call_%d" % k), "type": "function",
                            "function": {"name": c.get("name"),
                                         "arguments": c.get("arguments") or "{}"}}
                           for k, c in enumerate(lector)]}]
        for c in lector:
            try:
                args = json.loads(c.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            plegados = plegados + [{"role": "tool", "tool_call_id": c.get("id"),
                                    "name": NOMBRE_LECTOR,
                                    "content": _leer(clave, args)}]
            lecturas += 1
