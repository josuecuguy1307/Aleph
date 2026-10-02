"""etapas.py — EL ADAPTADOR: las etapas de Local Deep Research → los estados en vivo de LA SALA.
[Gate 4 · Fase 6 · §6.f]

POR QUÉ EXISTE
--------------
El plan sella que el modo Deep Research **no tiene cara propia**: «la UI del deep research
YA está construida — es la Sala + el canvas». El motor corre minutos y por dentro planifica,
busca, lee N de M fuentes y sintetiza. Todo eso tiene que verse **en la línea de razonamiento
de la Sala**, no en una pantalla ajena.

Este archivo es la única traducción entre los dos vocabularios, y es **puro**: recibe lo que
el motor emite y devuelve lo que la Sala pinta. No hace red, no toca disco, no importa el
motor. Se puede leer y razonar sin levantar nada.

LOS DOS VOCABULARIOS, medidos (no recordados)
---------------------------------------------
**Origen** — LDR emite por un callback plano
`progress_callback(mensaje: str, pct: int | None, metadata: dict)`
declarado en `third_party/ldr/src/local_deep_research/api/research_functions.py:37` y
propagado a cada estrategia en
`third_party/ldr/src/local_deep_research/advanced_search_system/strategies/base_strategy.py:93-96`,
que lo dispara en `:132-138`. La clave que importa es `metadata["phase"]`: **38 valores
distintos** medidos sobre el árbol importado.

**Destino** — `ESTADO` de la Sala v2, congelado en
`product/app/design/sala-v2/agui/estados.js:27-37`:
`quieto · pensando · preparando · esperando_ok · ejecutando · recibiendo · interpretando ·
final · fallo`.

LA REGLA QUE GOBIERNA ESTA TABLA
--------------------------------
Regla sellada del repo: **ninguna causa llega a una superficie sin copy**, y
`estados.js:43-46` extiende la misma disciplina a los estados de progreso. Acá se cumple de
la forma más dura posible: `traducir()` **no tiene rama por defecto silenciosa**. Una fase
que el motor invente mañana no se pinta como «Pensando…» ni desaparece: sale marcada
`desconocida=True` con su nombre crudo a la vista, para que se vea que es una fase nueva sin
copy. Un vocabulario que crece en silencio es un vocabulario que miente.

LO QUE ESTE ARCHIVO NO HACE
---------------------------
No decide si el modo se ofrece, ni a quién. **Deep Research jamás llega a un vertical por
default** (plan §6.f, regla sellada): eso se cumple en el registro —`sala_research` no es un
workspace del menú— y no acá.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Los estados de la Sala, copiados de estados.js:27-37 ──────────────────────
#: Se replican como constantes en vez de importarse porque el original es JS del frontend
#: y esto es Python del pack. Si un día divergen, la vara de la fase lo tiene que ver: el
#: par (acá, `estados.js`) es un contrato en dos lugares, y está declarado como tal.
QUIETO = "quieto"
PENSANDO = "pensando"
PREPARANDO = "preparando"
ESPERANDO_OK = "esperando_ok"
EJECUTANDO = "ejecutando"
RECIBIENDO = "recibiendo"
INTERPRETANDO = "interpretando"
FINAL = "final"
FALLO = "fallo"

ESTADOS = frozenset({
    QUIETO, PENSANDO, PREPARANDO, ESPERANDO_OK, EJECUTANDO,
    RECIBIENDO, INTERPRETANDO, FINAL, FALLO,
})

# ── Las cuatro etapas que el usuario ve, en el orden en que el plan las nombra ─
#: §6.f: «progreso por etapas en los estados en vivo (planificando → buscando →
#: leyendo 4/20 → sintetizando)». Son la agrupación GRUESA: 38 fases del motor no se le
#: cuentan a nadie una por una. La fase cruda viaja igual en el payload, para el detalle.
PLANIFICANDO = "planificando"
BUSCANDO = "buscando"
LEYENDO = "leyendo"
SINTETIZANDO = "sintetizando"
TERMINANDO = "terminando"
FALLANDO = "fallando"

#: fase del motor → (etapa gruesa, estado de la Sala, copy en español)
#:
#: Las 38 filas salen de medir el árbol importado, no de la documentación del proyecto:
#:     grep -rhoE '"phase":\s*"[a-z_]+"' third_party/ldr/src/local_deep_research
#: Si el grep da una fase que no está acá, `traducir()` la marca desconocida.
TABLA: dict[str, tuple[str, str, str]] = {
    # ── arranque ──────────────────────────────────────────────────────────────
    "init":                    (PLANIFICANDO, PENSANDO,       "Preparando la investigación…"),
    "setup":                   (PLANIFICANDO, PENSANDO,       "Preparando la investigación…"),
    "validation":              (PLANIFICANDO, PENSANDO,       "Revisando la consulta…"),
    # ── planificar ────────────────────────────────────────────────────────────
    "question_generation":     (PLANIFICANDO, PENSANDO,       "Armando las preguntas de la investigación…"),
    "topic_extraction":        (PLANIFICANDO, PENSANDO,       "Separando los temas…"),
    "context_analysis":        (PLANIFICANDO, PENSANDO,       "Analizando el contexto…"),
    "context_preparation":     (PLANIFICANDO, PENSANDO,       "Preparando el contexto…"),
    "agent_thinking":          (PLANIFICANDO, PENSANDO,       "Pensando el próximo paso…"),
    "agent_reasoning":         (PLANIFICANDO, PENSANDO,       "Razonando sobre lo encontrado…"),
    "refinement":              (PLANIFICANDO, PENSANDO,       "Afinando la búsqueda…"),
    "sub_research":            (PLANIFICANDO, PENSANDO,       "Abriendo una línea de investigación…"),
    "delegate_handover":       (PLANIFICANDO, PENSANDO,       "Pasando el trabajo a otra estrategia…"),
    # ── buscar ────────────────────────────────────────────────────────────────
    "search":                  (BUSCANDO,     EJECUTANDO,     "Buscando…"),
    "parallel_search":         (BUSCANDO,     EJECUTANDO,     "Buscando en varias fuentes a la vez…"),
    "tool_call":               (BUSCANDO,     PREPARANDO,     "Usando una herramienta…"),
    "source_gathering":        (BUSCANDO,     RECIBIENDO,     "Juntando las fuentes…"),
    # ── leer / filtrar ────────────────────────────────────────────────────────
    "observation":             (LEYENDO,      RECIBIENDO,     "Leyendo lo que volvió…"),
    "relevance_filtering":     (LEYENDO,      INTERPRETANDO,  "Descartando lo que no viene al caso…"),
    "source_filtering":        (LEYENDO,      INTERPRETANDO,  "Filtrando las fuentes…"),
    "final_filtering":         (LEYENDO,      INTERPRETANDO,  "Última pasada sobre las fuentes…"),
    "filtering_complete":      (LEYENDO,      INTERPRETANDO,  "Fuentes filtradas."),
    "relationship_mapping":    (LEYENDO,      INTERPRETANDO,  "Cruzando lo que dicen las fuentes…"),
    # ── sintetizar / escribir ─────────────────────────────────────────────────
    "synthesis":               (SINTETIZANDO, INTERPRETANDO,  "Sintetizando…"),
    "synthesis_fallback":      (SINTETIZANDO, INTERPRETANDO,  "Sintetizando por el camino de respaldo…"),
    "text_generation":         (SINTETIZANDO, INTERPRETANDO,  "Escribiendo…"),
    "report_structure":        (SINTETIZANDO, INTERPRETANDO,  "Armando la estructura del informe…"),
    "report_section_research": (SINTETIZANDO, EJECUTANDO,     "Investigando una sección del informe…"),
    "report_generation":       (SINTETIZANDO, INTERPRETANDO,  "Redactando el informe…"),
    "report_formatting":       (SINTETIZANDO, INTERPRETANDO,  "Dando formato al informe…"),
    "output_generation":       (SINTETIZANDO, INTERPRETANDO,  "Preparando la salida…"),
    # ── cerrar ────────────────────────────────────────────────────────────────
    "finalizing":              (TERMINANDO,   INTERPRETANDO,  "Cerrando…"),
    #: `termination` **ya no tiene emisor en el árbol**: lo emitía uno de los módulos que
    #: la extirpación de la Ley 2.bis se llevó (`third_party/ldr/EXTIRPACIONES.md` §1). La
    #: fila queda a propósito —la fase sigue siendo del vocabulario del motor y sólo
    #: nuestro corte la dejó sin disparador—, pero se marca acá para que nadie la lea como
    #: una fila viva. Si volviera, se pinta bien; si no, no molesta.
    "termination":             (TERMINANDO,   INTERPRETANDO,  "Cerrando…"),
    "report_complete":         (TERMINANDO,   FINAL,          "Informe listo."),
    "complete":                (TERMINANDO,   FINAL,          "Investigación terminada."),
    # ── fallas ────────────────────────────────────────────────────────────────
    "error":                   (FALLANDO,     FALLO,          "La investigación falló."),
    "synthesis_error":         (FALLANDO,     FALLO,          "Falló al sintetizar."),
    # ── ruido de control, NO se pinta ─────────────────────────────────────────
    #: `termination_check` es el latido de cancelación: el motor pregunta «¿me pararon?»
    #: en cada punto de chequeo (`base_strategy.py:99-131`). Pintarlo sería llenar la línea
    #: de razonamiento con una pregunta que el usuario no hizo. Se traga a propósito, y se
    #: declara acá para que se vea que se traga a propósito.
    "termination_check":       (None, None, None),            # type: ignore[dict-item]
    #: `benchmark_progress` sólo lo emite su suite de benchmarks, que no viaja en el camino
    #: de la Sala. Si aparece, es que algo llamó a un camino que no es el nuestro.
    "benchmark_progress":      (None, None, None),            # type: ignore[dict-item]
}

#: Las fases que se tragan a propósito (valor `(None, None, None)` en la tabla).
MUDAS = frozenset(f for f, v in TABLA.items() if v[0] is None)


def traducir(mensaje: str, pct: Optional[int], metadata: Optional[dict]) -> Optional[dict]:
    """Traduce un latido del motor al sobre que la Sala pinta.

    Devuelve `None` cuando la fase es de control y no se pinta (ver `MUDAS`) — el llamador
    debe tratar `None` como «no hay nada que mostrar», jamás como error.

    El sobre que devuelve:

        {
          "etapa":       una de PLANIFICANDO/BUSCANDO/LEYENDO/SINTETIZANDO/TERMINANDO/FALLANDO,
          "estado":      uno de ESTADOS — lo que la máquina de la Sala entiende,
          "texto":       el copy en español, ya resuelto,
          "fase":        la fase CRUDA del motor, sin traducir ni normalizar,
          "pct":         0..100 o None — nunca un 0 inventado,
          "leidas":      int o None   ┐ el «N de M» de §6.f: ITERACIONES, que es la unidad
          "total":       int o None   ┘ de progreso que este motor sí sabe contar
          "fuentes":     int o None   — fuentes acumuladas, sin total (el motor no lo sabe)
          "mensaje":     el texto crudo del motor (queda para el detalle, no para la línea),
          "desconocida": True si la fase no está en TABLA,
        }

    Sobre `pct`: se pasa tal cual si es un entero en rango. Un `None` **se conserva** —
    la disciplina de la casa es que un dato que no se midió no se inventa (ley técnica 7:
    lo que no gobierna, se declara; y jamás un cero fabricado).
    """
    meta = metadata or {}
    fase = str(meta.get("phase") or "").strip()

    if fase in MUDAS:
        return None

    fila = TABLA.get(fase)
    if fila is None:
        # FASE NUEVA SIN COPY. No se disfraza: se muestra con su nombre crudo y la marca.
        etapa, estado, texto, desconocida = PLANIFICANDO, PENSANDO, (mensaje or fase or "…"), True
    else:
        etapa, estado, texto = fila
        desconocida = False

    # EL FALLO QUE VIAJA EN `type`, NO EN `phase`. Hay un caso —y es el de la estrategia
    # que este pack corre por default— donde el motor avisa que fracasó **sin cambiar la
    # fase**: `advanced_search_system/strategies/source_based_strategy.py:492` emite
    # «No sources found — answer cannot be generated» con
    # `{"phase": "synthesis", "type": "error"}`. Mirando sólo `phase`, la Sala pintaría
    # «Sintetizando…» y después entregaría un informe vacío con un cierre limpio: fallo
    # mudo, ley técnica 9. Acá el `type` manda sobre la tabla, y el texto que se muestra
    # es el del motor —que dice qué pasó— en vez de un copy que no sabe.
    if str(meta.get("type") or "").strip().lower() == "error":
        etapa, estado = FALLANDO, FALLO
        texto = (mensaje or "").strip() or "La investigación falló."

    leidas, total = _progreso_de_fuentes(meta)

    return {
        "etapa": etapa,
        "estado": estado,
        "texto": texto,
        "fase": fase,
        "pct": _pct(pct),
        "leidas": leidas,
        "total": total,
        # Fuentes acumuladas hasta acá. Sin total, porque el motor no lo sabe: se muestra
        # «12 fuentes», jamás «12 de N» con un N fabricado.
        "fuentes": _primer_entero(meta, _CLAVES_FUENTES),
        "mensaje": mensaje or "",
        "desconocida": desconocida,
    }


def _pct(pct: Any) -> Optional[int]:
    """0..100, o None. Nunca un cero inventado ni un número fuera de rango."""
    if pct is None:
        return None
    try:
        v = int(pct)
    except (TypeError, ValueError):
        return None
    if v < 0 or v > 100:
        return None
    return v


#: EL «N de M», con las claves que el motor **de verdad emite**.
#:
#: Esto se corrigió tras una revisión adversarial, y la corrección importa más que el
#: código: la primera versión declaraba ocho claves (`completed_queries`, `sources_read`,
#: `processed`, `total_queries`, …) que **no existen en ninguna parte del motor**. El
#: resultado no era un error visible: `traducir()` devolvía `(None, None)` en el 100% de
#: los latidos y la etapa «leyendo 4/20» que §6.f pide por nombre no se pintaba nunca.
#: Código inalcanzable que una vara podría dar por verde sin medir nada.
#:
#: Lo que el motor cuenta, medido sobre `advanced_search_system/strategies/*.py`, es:
#:   · **iteraciones** — `iteration` y `max_iterations`: el N de M honesto de este motor,
#:     porque su unidad de progreso es el CICLO de investigación, no el documento.
#:   · **fuentes acumuladas** — `links_count` · `accumulated_sources` · `source_count`:
#:     un conteo SIN total, porque el motor no sabe de antemano cuántas va a encontrar.
#:
#: Se exponen las dos cosas por separado y con su nombre: un total inventado para que la
#: barra quede linda sería exactamente el dato fabricado que esta casa prohíbe.
_CLAVES_ITERACION = ("iteration",)
_CLAVES_ITERACIONES_TOTAL = ("max_iterations", "iterations")
_CLAVES_FUENTES = ("links_count", "accumulated_sources", "source_count", "new_sources")


def _progreso_de_fuentes(meta: dict) -> tuple[Optional[int], Optional[int]]:
    """El «N de M» de las iteraciones. `(None, None)` si el motor no lo dijo."""
    n = _primer_entero(meta, _CLAVES_ITERACION)
    total = _primer_entero(meta, _CLAVES_ITERACIONES_TOTAL)
    if n is None or total is None or total <= 0:
        return (None, None)
    if n > total:                           # el motor se pasó de la cuenta: no se corrige,
        return (None, None)                 # se apaga — un contador que miente es peor que no tenerlo
    return (n, total)


def _primer_entero(meta: dict, claves: tuple[str, ...]) -> Optional[int]:
    for k in claves:
        if k in meta:
            try:
                return int(meta[k])
            except (TypeError, ValueError):
                return None
    return None
