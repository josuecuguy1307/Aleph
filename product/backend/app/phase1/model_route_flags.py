"""Feature flags por workspace/clase para migrar sin big-bang.

La fuente inicial es entorno porque no requiere migración de DB. Default seguro: legacy.
Formato:

    ALEPH_MODEL_ROUTE_DEFAULT=legacy
    ALEPH_MODEL_ROUTE_CIENCIA_MAIN_AGENT=shadow
    ALEPH_MODEL_ROUTE_CIENCIA=aleph_v2

Precedencia: workspace+call_class > workspace > default.
"""
from __future__ import annotations

import os
import re
from enum import Enum
from typing import Mapping, Optional


class RouteMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ALEPH_V2 = "aleph_v2"


def _segment(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _mode(value: Optional[str]) -> Optional[RouteMode]:
    try:
        return RouteMode(str(value or "").strip().casefold())
    except ValueError:
        return None


def route_mode(workspace_id: str, call_class: str,
               *, environ: Optional[Mapping[str, str]] = None) -> RouteMode:
    env = environ if environ is not None else os.environ
    ws = _segment(workspace_id)
    cc = _segment(call_class)
    keys = [
        f"ALEPH_MODEL_ROUTE_{ws}_{cc}" if ws and cc else "",
        f"ALEPH_MODEL_ROUTE_{ws}" if ws else "",
        "ALEPH_MODEL_ROUTE_DEFAULT",
    ]
    for key in keys:
        mode = _mode(env.get(key)) if key else None
        if mode is not None:
            return mode
    return _DEFAULT


#: EL DEFAULT ES `aleph_v2`: EL CONTRATO ESTÁ PRENDIDO.
#:
#: Nació en `legacy` porque un contrato a medio construir no puede mover tráfico real. Ya
#: no está a medias —B0-1 a B0-5 cerrados— y dejarlo apagado tenía un costo que no se veía:
#: todo lo construido quedaba dormido, y lo dormido se pudre sin que nadie se entere.
#:
#: MEDIDO antes de prenderlo, mismo turno por el borde de workspace:
#:   · camino feliz IDÉNTICO — 200, mismo modelo, misma respuesta, en los dos modos
#:   · con una selección que no existe:
#:       legacy   → 422 `missing_recipe` («elegí un modelo en el selector»)
#:       aleph_v2 → 404 `selection_not_found` («no existe en el catálogo canónico de este
#:                  dueño») — que es la verdad, y la otra no: el usuario SÍ había elegido.
#:
#: Volver atrás es una variable de entorno, no un deploy: `ALEPH_MODEL_ROUTE_DEFAULT=legacy`
#: (o por workspace/clase, con la precedencia de arriba). Se deja explícito acá y no
#: implícito en el `return` porque apagar el contrato tiene que ser un acto deliberado y
#: con nombre, no el efecto colateral de tocar un `if`.
_DEFAULT = RouteMode.ALEPH_V2




#: [B0-3 · fase D] Cómo streamea el borde de workspace, por workspace.
#:
#:     ALEPH_BRAIN_STREAM_DEFAULT=emulado
#:     ALEPH_BRAIN_STREAM_CIENCIA=real
#:
#: `emulado` espera la respuesta entera y recién ahí fabrica los chunks. Es SSE válido, pero
#: el primer chunk llega junto con el último — medido 3 veces: 14,61/14,61 · 7,31/7,31 ·
#: 7,52/7,52. `real` retransmite conforme llega.
class ModoStream(str, Enum):
    EMULADO = "emulado"
    REAL = "real"


#: EL DEFAULT ES `real`. [2026-08-29]
#:
#: LA FIRMA DEL ACUMULADOR, MEDIDA CONTRA LA INSTALADA. Con `emulado` el borde no es «SSE
#: con los chunks fabricados al final»: es una llamada BLOQUEANTE. `workspace_brain_complete`
#: devuelve el paso entero y recién después se arma el `StreamingResponse`, así que ni
#: siquiera el 200 con las cabeceras puede salir antes. Medido con `qa/verify_primer_texto.py`
#: contra `/Applications/Aleph.app` (sidecar `5554124f`, main `a316b737`), 10 corridas:
#:
#:     workspace    t_cabeceras   t_1er_texto   t_fin      Δ(fin − 1er texto)
#:     ciencia      5,26-7,00 s   = t_fin       igual      0,00 s
#:     legal        5,29-6,35 s   = t_fin       igual      0,00 s
#:     oficina      5,58-5,66 s   = t_fin       igual      0,00 s
#:     educacion    7,17-7,91 s   = t_fin       igual      0,00 s
#:     finanzas     6,48-6,51 s   = t_fin       igual      0,00 s
#:
#: Los cuatro relojes en el mismo instante, 10 de 10. El usuario mira un spinner el turno
#: entero y después aparece todo junto.
#:
#: EL A/B QUE LO CAMBIA, aislado de verdad: el MISMO proceso levantado dos veces, misma
#: máquina, mismo minuto, mismas cabeceras y mismo cerebro, cambiando SÓLO esta bandera —
#: no dev contra frozen, que sería comparar dos cosas a la vez (la columna `emulado` de
#: dev reprodujo a la instalada clavada, 10/10 acumulado, y por eso el dev sirve acá):
#:
#:     modo       t_1er_texto (10 corridas)   bajo 2 s   finish   [DONE]   turno vacío
#:     emulado    4,38 – 8,56 s               0 / 10     stop     sí       0
#:     real       1,27 – 2,98 s               7 / 10     stop     sí       0
#:
#: LO QUE APAGÓ ESTA BANDERA EN 2026-08-14 YA NO PASA, y se midió antes de moverla en vez
#: de confiar en que se hubiera arreglado solo. Los tres sospechosos que quedaron anotados
#: sin aislar, uno por uno:
#:   · el turno volvía VACÍO (`finish=unknown`, sin part de texto) → 0 de 20 turnos vacíos
#:     hoy; su causa era el preflight adentro del generador, y ya está IZADO.
#:   · no viajaba el chunk de `usage` → viaja, y con el modelo honesto adentro.
#:   · el `model` vacío en todos los chunks → era real y seguía vivo; se arregló en el
#:     commit anterior (el eslabón `model_final` que `_consumir` no cedía). No se prende
#:     esta bandera antes que aquello: sin ese arreglo, prenderla cambiaría «no hay
#:     streaming» por «`model_final: null`», que es cambiar un defecto por otro.
#:
#: DE REGALO, Y NO ES MENOR: el desglose de caché SÓLO cruza en `real`. Con `emulado` el
#: sobre `usage` sale `{prompt_tokens, completion_tokens, total_tokens}` y nada más; con
#: `real` trae `prompt_tokens_details.cached_tokens`. O sea que hasta hoy los workspaces no
#: tenían cómo ver si su prefijo se reusaba (`qa/verify_turno_dos.py`: 5/5 reusado).
#:
#: ── lo de 2026-08-14, conservado, porque explica por qué se apagó ──────────────────
#: Obra 4 prendió `real` para los seis (todo el bloque de abajo sigue siendo cierto y por
#: eso se conserva entero). Lo que faltaba era una vara del turno COMPLETO: se midió que
#: los chunks salen separados, no que el stack los sepa leer. No los sabía.
#:
#: MEDIDO — A/B sobre el MISMO binario instalado (sha256 `d59961821d65533f…`), mismo
#: workspace, mismo turno («¿Cuánto es 17 por 23?»), cambiando SÓLO esta bandera:
#:
#:     real     → finish="unknown" · tokens input=0 · parts=[step-start, step-finish]
#:                · SIN part de texto — el turno vuelve VACÍO
#:     emulado  → finish="stop"    · tokens input=17.319 · parts=[…, text, …] · «391»
#:
#: Y el contenido SÍ está en el cable: capturado crudo, la rama `real` emite
#: `delta.content = "391"` y cierra con `finish_reason: "stop"`. O sea el borde manda bien
#: y el stack no lo levanta. Las tres diferencias contra `emulado` son: un chunk inicial con
#: `choices: []` + la extensión `aleph`, el campo `model` VACÍO en todos los chunks
#: (`_chunk_real` arma `x_aleph_model or equiv.model or ""`, y el borde ignora el `model` del
#: body a propósito), y que NO viaja el chunk de `usage`. Las dos últimas explican por sí
#: solas el `model_final: null` y los tokens en cero que ya había reportado la auditoría de
#: Ciencia como defecto #4.
#:
#: CUÁL DE LAS TRES ES, NO ESTÁ AISLADO, y se dice en vez de suponerse: el fallo es
#: INTERMITENTE (mismo pedido, mismo carril, ✅✅✗ en tres corridas), así que una muestra por
#: variante no distingue causa de casualidad — el primer intento de aislarlo lo hizo y dio un
#: culpable falso. Sospecha viva y sin cerrar: la intermitencia coincide con la concurrencia
#: de `cli_ocupado`, o sea que podría depender de QUÉ CARRIL atendió el turno y no del stream.
#:
#: Por eso esto NO revierte obra 4: la rama `real` queda entera y se prende con
#: `ALEPH_BRAIN_STREAM_DEFAULT=real` o por workspace. Lo que cambia es cuál de las dos es la
#: que le toca a alguien que no declaró nada — y ésa tiene que ser la que entrega el turno.
#: Un stream que llega antes no sirve de nada si lo que llega no se ve.
#:
#: ── lo de obra 4, conservado ────────────────────────────────────────────────────────
#: Misma historia que `_DEFAULT` de arriba, y el mismo remate. La bandera nació por
#: workspace para «encender uno y mirarlo antes de mover el resto» — y esa fase terminó sin
#: que nadie la encendiera: medido el 2026-08-13, `ALEPH_BRAIN_STREAM_EDUCACION` y
#: `ALEPH_BRAIN_STREAM_DEFAULT` no estaban declaradas **en ningún archivo del árbol** ni en
#: el entorno del sidecar instalado. O sea: el streaming de verdad se construyó, se mergeó y
#: se quedó dormido. Es exactamente el costo que el comentario de arriba dice que no se ve.
#:
#: Por qué GLOBAL y no una variable por workspace: el defecto no era de ningún stack, era
#: del borde, y el borde es uno solo para los seis. Dejarlo por workspace obliga a acordarse
#: seis veces de algo que ya está medido, y el que se olvide se queda mudo sin enterarse.
#:
#: MEDIDO antes de prenderlo, con el pack de Educación contra un sumidero que manda 7 trozos
#: a uno por segundo:
#:   · aguas abajo del borde está SANO — el stack emitió 7 eventos `content`, uno por
#:     segundo (+1,18 … +7,19 s). No había nada más que arreglar ahí.
#:   · con `emulado`, en turnos reales, `content` y `done` llegan en el MISMO instante:
#:     chat +8,70/+8,70 s · deep_solve +12,51/+12,51 s. Ésa era la firma.
#:
#: Volver atrás es una variable de entorno, no un deploy: `ALEPH_BRAIN_STREAM_DEFAULT=emulado`
#: (o por workspace). Se deja explícito acá y no implícito en el `return` por la misma razón
#: que arriba: apagar el streaming tiene que ser un acto deliberado y con nombre.
_DEFAULT_STREAM = ModoStream.REAL


def modo_stream(workspace_id: str, *, environ: Optional[Mapping[str, str]] = None) -> ModoStream:
    """El modo de este workspace. Lo no declarado o inválido cae en `_DEFAULT_STREAM`.

    Misma forma y misma precedencia que `route_mode`.
    """
    env = environ if environ is not None else os.environ
    ws = _segment(workspace_id)
    for key in (f"ALEPH_BRAIN_STREAM_{ws}" if ws else "", "ALEPH_BRAIN_STREAM_DEFAULT"):
        if not key:
            continue
        try:
            return ModoStream(str(env.get(key) or "").strip().casefold())
        except ValueError:
            continue
    return _DEFAULT_STREAM


__all__ = ["RouteMode", "route_mode", "ModoStream", "modo_stream"]
