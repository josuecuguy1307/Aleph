"""destino.py — EL APLICADOR ÚNICO DE LAS TRES SEÑALES.
[Gate 4 · Fase 4 · obra O5 · ley de producto 6 · obras 4.4 y 4.5]

LA VARA DE ESTA FASE, EN UNA LÍNEA
----------------------------------
«Las tres señales —cinturón · artefacto · preferencia— terminan en el MISMO aplicador.»

Este archivo es ese aplicador. No existía: la elegibilidad la calculaba el registro, la
preferencia no existía, y el artefacto no llevaba a ningún lado. Tres señales sin un lugar
donde encontrarse son tres pantallas decidiendo distinto sobre lo mismo — que es la forma
exacta en que este repo ya se equivocó cuatro veces con los vocabularios de tipo.

LAS TRES SEÑALES Y SU PESO — ley 6, tal como está sellada
---------------------------------------------------------
1. **STACK DISPONIBLE** — no elige: **filtra**. Un workspace cuyo stack no viajó con esta
   instalación no existe para el usuario (ni gris, ni con candado). Es el único veto.
2. **PREFERENCIA GRABADA** — manda. «Preferencia grabada → auto» (4.5). Si el usuario ya
   dijo dónde van sus informes, no se le vuelve a preguntar.
3. **ARTEFACTO** — el tipo que el trabajo produjo, cruzado contra lo que cada workspace
   DECLARA aceptar (`bridge.accepts`, ley 7: compatibilidad por artefacto, no por MCP).

Y el **CINTURÓN SUGIERE, JAMÁS CONDICIONA** (enmienda 2026-08-08 a la ley 6): con la ley 0
un stack vale entero sin un solo conector de Aleph, así que el cinturón sólo puede ORDENAR
candidatos — nunca sacar uno de la lista. Acá eso es literal: entra como `sugerencia` y toca
el orden, no el conjunto.

LO QUE PASA CUANDO NO ALCANZA
-----------------------------
· **Nadie lo reclama** → cae al suelo (La Sala). Ley 4: lo no reclamado no es un estado
  roto, es la base. `destino = None` con motivo `nadie_lo_reclama`.
· **Más de uno lo reclama y no hay preferencia** → **ambigüedad**, y la ley 6 dice qué
  hacer: *pregunta del agente en el chat, una línea. Jamás galería obligatoria.* Este
  módulo devuelve esa línea ya redactada y los candidatos; quien la muestre no inventa copy.

LO QUE ESTE MÓDULO NO HACE: no lee el disco ni pide HTTP. Recibe los hechos ya medidos y
decide. Así la misma decisión se puede probar con una tabla, y la vara no necesita levantar
medio producto para afirmar que la precedencia es la que dice la ley.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: Los motivos posibles, con su copy. Ninguna causa llega a una superficie sin copy.
MOTIVOS = {
    "preferencia": "Vas a {label} porque lo elegiste para esto.",
    "artefacto": "Esto lo abre {label}.",
    "unico_disponible": "{label} es el único workspace que puede abrir esto.",
    "ambiguo": "Hay más de un lugar donde esto puede vivir.",
    "nadie_lo_reclama": "Esto se queda en La Sala, que es donde vive todo lo demás.",
    "sin_workspaces": "Todavía no hay ningún workspace instalado.",
}


def _label(ws: dict) -> str:
    return str(ws.get("label") or ws.get("id") or "")


def decidir(*, disponibles: Iterable[dict], tipo: Optional[str] = None,
            preferencias: Optional[dict] = None,
            sugerencias: Optional[Iterable[str]] = None) -> dict:
    """A dónde va este trabajo.

    `disponibles` — las filas de `GET /v1/workspaces` YA FILTRADAS por `installed` (la señal
                    1 ya se aplicó: acá no entra lo que no existe).
    `tipo`         — el tipo canónico del artefacto que se produjo, si hubo uno.
    `preferencias` — `{tipo: workspace}` del dueño (señal 3).
    `sugerencias`  — ids que el cinturón sugiere (señal del cinturón). **Ordena, no filtra.**

    Devuelve:
        {destino, motivo, copy, candidatos:[{id,label,por_que}], pregunta}
    """
    filas = [w for w in (disponibles or []) if isinstance(w, dict) and w.get("id")]
    prefs = dict(preferencias or {})
    sug = list(sugerencias or [])

    if not filas:
        return {"destino": None, "motivo": "sin_workspaces",
                "copy": MOTIVOS["sin_workspaces"], "candidatos": [], "pregunta": None}

    porId = {str(w["id"]): w for w in filas}

    # ── SEÑAL 3 · LA PREFERENCIA MANDA ──────────────────────────────────────────────
    # Antes que el artefacto a propósito: el usuario YA decidió esto una vez. Volver a
    # preguntarle —o peor, mandarlo a otro lado «porque el tipo encaja mejor»— es tratar su
    # decisión como una sugerencia nuestra.
    if tipo and prefs.get(tipo) in porId:
        elegido = porId[prefs[tipo]]
        return {"destino": elegido["id"], "motivo": "preferencia",
                "copy": MOTIVOS["preferencia"].format(label=_label(elegido)),
                "candidatos": [{"id": elegido["id"], "label": _label(elegido),
                                "por_que": "lo elegiste para esto"}],
                "pregunta": None}

    # ── SEÑAL 2 · EL ARTEFACTO, CONTRA LO QUE CADA UNO DECLARA ACEPTAR ──────────────
    if tipo:
        reclaman = [w for w in filas if tipo in list(w.get("accepts") or [])]
        if not reclaman:
            # Ley 4: el suelo. No es un error, es el lugar de lo que nadie reclamó.
            return {"destino": None, "motivo": "nadie_lo_reclama",
                    "copy": MOTIVOS["nadie_lo_reclama"], "candidatos": [], "pregunta": None}
        # El cinturón ORDENA lo que ya está adentro. Jamás saca a nadie de la lista.
        reclaman.sort(key=lambda w: (0 if str(w["id"]) in sug else 1, _label(w)))
        candidatos = [{"id": w["id"], "label": _label(w),
                       "por_que": ("tu cinturón ya trabaja con esto" if str(w["id"]) in sug
                                   else f"acepta {tipo}")}
                      for w in reclaman]
        if len(reclaman) == 1:
            uno = reclaman[0]
            return {"destino": uno["id"], "motivo": "artefacto",
                    "copy": MOTIVOS["artefacto"].format(label=_label(uno)),
                    "candidatos": candidatos, "pregunta": None}
        # AMBIGÜEDAD → una línea en el chat, jamás una galería (ley 6).
        nombres = " o ".join(_label(w) for w in reclaman[:3])
        return {"destino": None, "motivo": "ambiguo", "copy": MOTIVOS["ambiguo"],
                "candidatos": candidatos,
                "pregunta": f"Esto lo puedo abrir en {nombres}. ¿Dónde lo quieres?"}

    # ── SIN ARTEFACTO: la transición no tiene de qué agarrarse todavía ──────────────
    # Con un solo workspace instalado la respuesta es obvia y se dice; con varios NO se
    # elige por nosotros: sin señal, elegir es adivinar.
    if len(filas) == 1:
        uno = filas[0]
        return {"destino": uno["id"], "motivo": "unico_disponible",
                "copy": MOTIVOS["unico_disponible"].format(label=_label(uno)),
                "candidatos": [{"id": uno["id"], "label": _label(uno),
                                "por_que": "es el único instalado"}],
                "pregunta": None}
    ordenadas = sorted(filas, key=lambda w: (0 if str(w["id"]) in sug else 1, _label(w)))
    return {"destino": None, "motivo": "ambiguo", "copy": MOTIVOS["ambiguo"],
            "candidatos": [{"id": w["id"], "label": _label(w),
                            "por_que": ("tu cinturón ya trabaja con esto"
                                        if str(w["id"]) in sug else "está instalado")}
                           for w in ordenadas],
            "pregunta": "¿En qué workspace quieres trabajar?"}
