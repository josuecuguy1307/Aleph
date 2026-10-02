r"""tool_budget.py — CUÁNTAS TOOLS ENTRAN EN ESTE PEDIDO, y qué queda afuera con nombre.

Gate 4 · Fase 5 · obra 5.1.

⚠️ POR QUÉ EXISTE.

El 2026-08-08 se midió: un agente con 5 piezas equipadas cablea **49 tools**, y con esas 49
Groq **rechaza el pedido entero** —HTTP 413— con `x-ratelimit-remaining-requests: 1000` en
la misma respuesta. O sea que no era la cuota: **el pedido no entraba**. El mismo cinturón
por OpenRouter pasó sin toser. El techo es del proveedor, no del cinturón.

Hasta hoy el cinturón entero viajaba SIEMPRE, en todos los turnos, sin que nadie mirara
cuánto pesaba. Con 9 workspaces y motores por venir eso no es una optimización pendiente:
es una arquitectura que no escala. El censo lo dejó escrito y sin código:
`grep -rn "tools_por_contexto\|max_tools\|tool_budget" product platform` → **0**.

──────────────────────────────────────────────────────────────────────────────────────
QUÉ ES Y QUÉ NO ES

**Es una política de la casa sobre el TAMAÑO DEL PEDIDO.** Nunca opina sobre el oficio: no
decide que una tool «no sirve» ni que «no viene al caso». Decide que **en este pedido no
entra**, elige cuál se demora con un orden declarado, y lo DICE.

**No es un filtro semántico.** No mira el prompt, no adivina intención, no llama a un
modelo para elegir tools. Eso sería otra obra, con otros riesgos, y no es la que el 413
pide.

──────────────────────────────────────────────────────────────────────────────────────
LAS DECISIONES, con su motivo

  1. **PURO. Cero red, cero estado, cero reloj.** Mismo patrón que `errores_modelo` y
     `tool_result`, y por el mismo motivo: una vara tiene que poder probarlo —y probarlo
     CAYENDO— sin levantar un server ni gastar un token. Todo lo que necesita entra por
     parámetro; el llamante resuelve el presupuesto y se lo pasa.

  2. **`None` ES «NO SÉ», JAMÁS «INFINITO».** Un proveedor sin techo declarado NO se
     recorta: se manda entero, exactamente como hoy. Es la misma regla que `_normalizar_uso`
     («`None` jamás cero»): inventar un techo para un proveedor que no medimos sería
     recortarle capacidades al agente por una corazonada. Sin dato → sin política → cero
     regresión.

  3. **EL PISO NO SE TOCA.** Las tools que el MÉTODO declaró en `steps[].executor` no se
     recortan nunca, ni aunque no entren. Si el dueño escribió que el paso 3 lo hace
     `sec-edgar#get_filings`, recortarla no ahorra un pedido: rompe el método y el arnés
     falla el paso por una razón que no tiene nada que ver con el oficio. Cuando el piso
     solo ya excede el techo, se manda el piso igual y se dice en la evidencia
     (`piso_excede_presupuesto`) — mentirle al método es peor que un 413 honesto.

  4. **NADA SE PIERDE: SE DEMORA.** Lo que no entra en este turno vuelve a estar disponible
     en el siguiente (el llamante amplía con `LazyToolRegistry.reveal_next()`). Por eso lo
     de afuera se llama `demoradas` y no `descartadas`: un recorte permanente sería
     amputarle una capacidad al agente sin que nadie lo decidiera.

  5. **SE MIDE EN BYTES DEL CUERPO SERIALIZADO, no en tokens estimados.** Los bytes son un
     HECHO —el mismo `json.dumps` que `assembler._chat:696` va a mandar— y los tokens
     serían una estimación nuestra sobre el tokenizador de otro. Cuando la unidad honesta y
     la unidad exacta no coinciden, se elige la que no hay que defender.

  6. **NO HAY RECORTE MUDO.** Toda tool que queda afuera sale con nombre y motivo en
     `demoradas`. Un techo que no se ve es una capacidad que desapareció sin causa, y la
     superficie mostraría un agente que «no sabe hacer» algo que sí sabe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

#: EL PISO POR WORKSPACE — las tools que NUNCA se demoran en un stack importado.
#:
#: POR QUÉ EXISTE. `recortar` y `repliegue` ya saben respetar un piso desde F5 · 5.1
#: (decisión 3), pero el borde de workspaces —`workspace_brain`, el proxy de los stacks
#: heredados— llamaba a `repliegue(tools)` **sin piso**. Sobre las 94 tools de Finanzas
#: eso deja a `financial_rigor` adentro por una sola razón: está en la posición 19 del
#: orden de registro, y 94 → 47 todavía la alcanza. Medido: con el catálogo reordenado
#: —lo mismo que haría registrar una tool nueva antes que ella— desaparece del pedido.
#:
#: `financial_rigor` no es una tool más: es el protocolo de auditoría del workspace
#: financiero, el que hace que todo número tenga procedencia. Un 413 dejaría al modelo
#: contestando sin la herramienta con la que se auditan los números, y el turno saldría
#: igual —sin alarma— porque el repliegue es una recuperación exitosa. La posición de
#: registro no es un protocolo de auditoría; el piso sí.
#:
#: Se declara por workspace y no se infiere: una entrada nueva es una decisión, igual que
#: una fila de `LIMITES_POR_HOST`. Un workspace que no está acá tiene piso VACÍO, que es
#: exactamente el comportamiento de hoy — cero regresión para los otros cinco.
PISO_POR_WORKSPACE: dict[str, frozenset] = {
    "finanzas": frozenset({"financial_rigor"}),
}


def piso_de_workspace(workspace) -> frozenset:
    """Las tools que no se demoran nunca en ese workspace. Desconocido → vacío.

    Tolera `None`, `""` y mayúsculas: el borde recibe el nombre por HTTP y un piso que
    se pierde por un rótulo con otra caja sería justamente el fallo mudo que esto evita.
    """
    if not isinstance(workspace, str):
        return frozenset()
    return PISO_POR_WORKSPACE.get(workspace.strip().casefold(), frozenset())


#: Motivos con los que una tool queda afuera. Cerrado a propósito: un motivo nuevo es una
#: decisión, no un string suelto.
POR_PRESUPUESTO = "presupuesto"        # no entraba en el techo del proveedor
POR_REPLIEGUE = "repliegue"            # el proveedor YA dijo 413 y se reintentó con menos
MOTIVOS = frozenset({POR_PRESUPUESTO, POR_REPLIEGUE})

#: La evidencia que el record publica cuando el piso del método no entra en el techo.
PISO_EXCEDE = "piso_excede_presupuesto"
#: …y cuando el que no entra es el HISTORIAL, y por lo tanto las tools no son el problema.
MENSAJES_EXCEDEN = "mensajes_exceden_presupuesto"


@dataclass(frozen=True)
class Presupuesto:
    """El techo de UN proveedor para UN pedido, con de dónde salió el número.

    `max_payload_bytes = None` significa **no sé** (decisión 2): el llamante no recorta.
    `fuente` viaja al record para que la evidencia diga si el techo es medido, declarado o
    puesto a mano por una vara — nunca se pierde de dónde salió.
    """

    max_payload_bytes: Optional[int] = None
    #: EL OTRO TECHO, y no es de tamaño: **cuántas tools acepta el proveedor, punto**.
    #: Medido contra Groq el 2026-08-09: con 400 tools contesta `400 invalid_request_error`
    #: — *"'tools' : maximum number of items is 128"*. No es un 413 y **ningún repliegue por
    #: bytes lo salva**: 128 schemas minúsculos siguen siendo 129 ítems. Se respeta antes
    #: que el de bytes porque es duro y no admite negociación.
    max_tools: Optional[int] = None
    fuente: str = "desconocido"

    @property
    def hay_techo(self) -> bool:
        return ((isinstance(self.max_payload_bytes, int) and self.max_payload_bytes > 0)
                or (isinstance(self.max_tools, int) and self.max_tools > 0))

    @property
    def hay_techo_bytes(self) -> bool:
        return isinstance(self.max_payload_bytes, int) and self.max_payload_bytes > 0

    @property
    def hay_techo_items(self) -> bool:
        return isinstance(self.max_tools, int) and self.max_tools > 0

    def como_dict(self) -> dict:
        return {"max_payload_bytes": self.max_payload_bytes,
                "max_tools": self.max_tools, "fuente": self.fuente}


SIN_TECHO = Presupuesto(None, "desconocido")


@dataclass(frozen=True)
class Recorte:
    """Qué se manda, qué se demora, y los dos tamaños — el pedido y lo que entró."""

    enviadas: list = field(default_factory=list)
    demoradas: list = field(default_factory=list)   # [{name, motivo}]
    bytes_enviados: int = 0
    bytes_pedidos: int = 0
    piso_excede: bool = False
    #: Los mensajes solos ya pasaban el techo: recortar tools no habría evitado nada, así
    #: que NO se recortó. El pedido va entero y la causa que vuelva dirá la verdad.
    mensajes_exceden: bool = False

    @property
    def recorto(self) -> bool:
        return bool(self.demoradas)

    def como_dict(self) -> dict:
        out = {
            "enviadas": len(self.enviadas),
            "demoradas": [dict(d) for d in self.demoradas],
            "bytes_enviados": self.bytes_enviados,
            "bytes_pedidos": self.bytes_pedidos,
        }
        if self.piso_excede:
            out["aviso"] = PISO_EXCEDE
        if self.mensajes_exceden:
            out["aviso"] = MENSAJES_EXCEDEN
        return out


# ── MEDIR ──────────────────────────────────────────────────────────────────────────

def nombre_de(tool: Any) -> str:
    """El nombre de una function-tool OpenAI, o `""` si el objeto no tiene forma."""
    if not isinstance(tool, dict):
        return ""
    fn = tool.get("function")
    if not isinstance(fn, dict):
        return ""
    return str(fn.get("name") or "")


def _bytes(obj: Any) -> int:
    """Bytes del objeto serializado. Nunca levanta: un schema que no serializa se cuenta
    por su `repr`, que es peor medida pero sigue siendo una medida (y el pedido con ese
    schema adentro tampoco iba a salir)."""
    try:
        return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:                              # noqa: BLE001 — medir jamás rompe el turno
        return len(repr(obj).encode("utf-8", "replace"))


def medir(messages: Any, tools: Any, *, reservado: int = 0) -> int:
    """Bytes del cuerpo que se va a mandar: mensajes + tools + un margen del llamante.

    `reservado` es para lo que el `_chat` agrega y acá no se ve (model, max_tokens,
    tool_choice, headers). Se pide explícito en vez de adivinarlo.
    """
    return _bytes(messages) + _bytes(tools) + max(0, int(reservado or 0))


# ── EL ORDEN DE RECORTE (declarado, jamás heurístico) ──────────────────────────────

def ordenar(tools: Sequence, *, piso: Iterable[str] = (), usadas: Iterable[str] = (),
            del_cliente: Iterable[str] = ()) -> list:
    """Las tools de más a menos derecho a viajar. **Estable**: dentro de un mismo rango se
    conserva el orden de registro, que ya es determinista (`LazyToolRegistry._order`).

    Los cuatro rangos, y por qué cada uno está donde está:

      0 · **el piso del método** — el dueño DECLARÓ que un paso lo hace esta tool. Es la
          señal de contexto más fuerte que existe en la casa y hasta hoy no la usaba nadie
          para esto.
      1 · **ya trabajó en este run** — una tool que se usó en el turno 2 y desaparece en el
          turno 3 deja al agente sin la mano con la que venía trabajando.
      2 · **el belt** — el equipamiento real del agente.
      3 · **las del cliente** — el propio motor las llama decoración: *«el belt es el
          equipamiento del agente; el cliente sólo decora»* (`recipe_assembler.py:2774`).
          Si algo se demora, que se demore lo que decora.
    """
    _piso = {str(x) for x in piso if x}
    _usadas = {str(x) for x in usadas if x}
    _cliente = {str(x) for x in del_cliente if x}

    def rango(t: Any) -> int:
        n = nombre_de(t)
        if n and n in _piso:
            return 0
        if n and n in _usadas:
            return 1
        if n and n in _cliente:
            return 3
        return 2

    return [t for _, t in sorted(enumerate(tools), key=lambda p: (rango(p[1]), p[0]))]


# ── RECORTAR ───────────────────────────────────────────────────────────────────────

def recortar(tools: Sequence, messages: Any, presupuesto: Presupuesto, *,
             piso: Iterable[str] = (), usadas: Iterable[str] = (),
             del_cliente: Iterable[str] = (), reservado: int = 0,
             motivo: str = POR_PRESUPUESTO) -> Recorte:
    """Las que entran en el techo, en el orden de `ordenar`. Sin techo → todas.

    El algoritmo es deliberadamente simple: se apilan en orden hasta que el cuerpo deja de
    entrar, y **se sigue probando con las que faltan** (una tool chica después de una
    grande sí entra). No se corta en la primera que no cabe: eso demoraría tools que sí
    entraban, sin ganar un byte.
    """
    _tools = list(tools or [])
    pedidos = medir(messages, _tools, reservado=reservado)
    if not presupuesto.hay_techo or not _tools:
        return Recorte(enviadas=_tools, demoradas=[], bytes_enviados=pedidos,
                       bytes_pedidos=pedidos)

    _piso_items = {str(x) for x in piso if x}
    demoradas_items: list = []

    # ── TECHO DURO POR CANTIDAD, ANTES QUE EL DE BYTES ────────────────────────────
    # Es una restricción de OTRA naturaleza: el proveedor rechaza el pedido por tener
    # demasiados ÍTEMS, con un 400 que ningún repliegue por tamaño puede evitar. Se aplica
    # primero y sin negociar; el de bytes trabaja después sobre lo que quedó.
    if presupuesto.hay_techo_items and len(_tools) > int(presupuesto.max_tools):  # type: ignore[arg-type]
        cupo = int(presupuesto.max_tools)                                          # type: ignore[arg-type]
        _ord = ordenar(_tools, piso=_piso_items, usadas=usadas, del_cliente=del_cliente)
        _quedan = {id(x) for x in _ord[:cupo]}
        demoradas_items = [{"name": nombre_de(x) or "(sin nombre)", "motivo": motivo}
                           for x in _ord[cupo:]]
        _tools = [x for x in _tools if id(x) in _quedan]
        pedidos = medir(messages, _tools, reservado=reservado)

    if not presupuesto.hay_techo_bytes:
        return Recorte(enviadas=_tools, demoradas=demoradas_items,
                       bytes_enviados=pedidos, bytes_pedidos=pedidos)

    techo = int(presupuesto.max_payload_bytes)      # type: ignore[arg-type]

    # ⚠️ SI LOS MENSAJES SOLOS NO ENTRAN, LAS TOOLS NO SON EL PROBLEMA — y recortarlas no
    # es «hacer lo que se puede»: es dejar al agente sin manos para nada.
    #
    # Lo destapó la vara (D1 pasaba con **0 de 6 tools enviadas** y el run «salía» sin
    # poder hacer nada). El razonamiento es aritmético: si `mensajes > techo`, el pedido
    # no entra ni con CERO tools, así que sacarlas no evita el 413 — sólo garantiza que si
    # por algún motivo el pedido sí sale, salga inútil.
    #
    # La verdad de ese caso es la otra: la conversación es demasiado larga. Se manda todo,
    # el proveedor habla, y la causa sale con `motivo: pedido_demasiado_grande`, que es
    # exactamente lo que pasó. Podar el contexto es trabajo de `_prune_history`, no de
    # este módulo, y fingir que lo resolvimos escondiendo las tools sería mentir dos veces.
    solo_mensajes = medir(messages, [], reservado=reservado)
    if solo_mensajes >= techo:
        return Recorte(enviadas=_tools, demoradas=demoradas_items, bytes_enviados=pedidos,
                       bytes_pedidos=pedidos, mensajes_exceden=True)

    _piso = _piso_items
    ordenadas = ordenar(_tools, piso=_piso, usadas=usadas, del_cliente=del_cliente)

    # El piso entra SIEMPRE y primero (decisión 3), aunque solo ya no entre.
    obligadas = [t for t in ordenadas if nombre_de(t) in _piso]
    opcionales = [t for t in ordenadas if nombre_de(t) not in _piso]

    enviadas = list(obligadas)
    actual = medir(messages, enviadas, reservado=reservado)
    piso_excede = bool(obligadas) and actual > techo

    demoradas: list = []
    for t in opcionales:
        candidato = enviadas + [t]
        tam = medir(messages, candidato, reservado=reservado)
        if tam <= techo:
            enviadas = candidato
            actual = tam
        else:
            demoradas.append({"name": nombre_de(t) or "(sin nombre)", "motivo": motivo})

    # El orden de registro se restituye: el modelo no tiene por qué ver nuestro ranking, y
    # un orden estable entre turnos es lo que hace que el prompt se pueda cachear.
    quedan = {id(t) for t in enviadas}
    enviadas = [t for t in _tools if id(t) in quedan]

    return Recorte(enviadas=enviadas, demoradas=demoradas_items + demoradas,
                   bytes_enviados=actual, bytes_pedidos=pedidos, piso_excede=piso_excede)


def repliegue(tools: Sequence, *, piso: Iterable[str] = (),
              usadas: Iterable[str] = (), del_cliente: Iterable[str] = ()) -> Recorte:
    """EL REPLIEGUE: el proveedor YA contestó 413. Se reintenta con **la mitad**.

    Por qué existe además del presupuesto: el techo declarado puede ser generoso o
    directamente desconocido (decisión 2), y en los dos casos el 413 llega igual. Sin esto,
    la obra del usuario se cae entera por un límite que ni siquiera es del modelo. Con
    esto, el peor caso es un turno más caro — no un turno perdido.

    **Una sola vez, y a la mitad.** No es un bucle de bisección: reintentar N veces contra
    un proveedor que ya dijo que no es gastarle la cuota a alguien para adivinar su techo.
    El piso del método sobrevive al repliegue por la misma razón de siempre.
    """
    _tools = list(tools or [])
    _piso = {str(x) for x in piso if x}
    if len(_tools) <= 1:
        return Recorte(enviadas=_tools, demoradas=[], bytes_enviados=0, bytes_pedidos=0)

    ordenadas = ordenar(_tools, piso=_piso, usadas=usadas, del_cliente=del_cliente)
    obligadas = [t for t in ordenadas if nombre_de(t) in _piso]
    opcionales = [t for t in ordenadas if nombre_de(t) not in _piso]

    # La mitad de las OPCIONALES (el piso no cuenta para el recorte y no se toca).
    cuantas = len(opcionales) // 2
    sobreviven = opcionales[:cuantas]
    cortadas = opcionales[cuantas:]

    quedan = {id(t) for t in obligadas + sobreviven}
    enviadas = [t for t in _tools if id(t) in quedan]
    demoradas = [{"name": nombre_de(t) or "(sin nombre)", "motivo": POR_REPLIEGUE}
                 for t in cortadas]
    return Recorte(enviadas=enviadas, demoradas=demoradas,
                   bytes_enviados=0, bytes_pedidos=0)


__all__ = [
    "POR_PRESUPUESTO", "POR_REPLIEGUE", "MOTIVOS", "PISO_EXCEDE", "MENSAJES_EXCEDEN",
    "Presupuesto", "SIN_TECHO", "Recorte",
    "PISO_POR_WORKSPACE", "piso_de_workspace",
    "nombre_de", "medir", "ordenar", "recortar", "repliegue",
]
