#!/usr/bin/env python3
"""verify_hilo_andamiaje.py — EL HILO GUARDA EL TURNO HUMANO, NO EL ANDAMIAJE.

    python3 product/backend/app/phase1/verify_hilo_andamiaje.py

EL DEFECTO QUE MIDE. `turno_de` nació suponiendo que todas las llamadas de un turno
comparten el último `user`. Es cierto para un loop `modelo → tool → modelo` y **falso** en
cuanto el harness hace llamadas auxiliares. Medido en la `aleph.db` REAL el 2026-08-23,
con la identidad de Diseño ya recuperada: **3 turnos humanos dejaron 23 filas en el hilo**,
y ninguna de las 23 era el turno.

LOS TEXTOS DE ESTA VARA NO SON INVENTADOS: son copias VERBATIM de esas 23 filas. Un
fixture escrito de memoria mediría mi idea del harness de Diseño, no el harness.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.phase1 import hilo_workspace as HW                          # noqa: E402

MUTAR = "--caer" in sys.argv
_ROJAS = 0


def ok(cond: bool, titulo: str, detalle: str = "") -> None:
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {titulo}" + (f"   [{detalle}]" if detalle else ""))


# ── LO QUE DISEÑO MANDA DE VERDAD, copiado de `chat_messages` ────────────────────────
DECL = {"desde": "User request:", "hasta": "Use the following local context"}

LOOP = """Workspace context:
- Current design title: Hacé un banner de anuncio con un boton..
- No existing design source was found. Create App.jsx for visual/web work, or create the \
requested document/handoff file for document-first work.
- DESIGN.md: absent.
- AGENTS.md: absent
- .codesign/settings.json: absent
- Reference materials: attached file(s): 0; image file(s): 0; reference URL: no; linked \
design-system scan: no.
This is an empty workspace. For visual/web work, create App.jsx when the first pass is \
ready; for document-first work, create the requested document file. Use set_todos for \
multi-step work.

User request:
Hacé un banner de anuncio con un boton.

Use the following local context and references when making design decisions. Follow the \
design system closely when one is provided.

<untrusted_scanned_content type="design_context_pack">
Run preferences:
- tweaks: auto
</untrusted_scanned_content>"""

#: El MISMO turno, un paso después: el `Design Context Pack` cambió. Si la semilla del id
#: se calculara con el crudo, este paso abriría un turno nuevo.
LOOP_PASO2 = LOOP.replace("- tweaks: auto", "- tweaks: no\n- loadedSkills: responsive-layout")

#: Las cinco auxiliares. Ninguna trae la marca, y las cinco llegan con `tools=[]`.
AUXILIARES = {
    "extractor de preferencias": "## Current prompt\nHacé un banner de anuncio con un "
                                 "boton.\n\n## Existing run preferences\nnull\n\n"
                                 "## Workspace state\n{}\n\nReturn JSON now.",
    "bautizador del diseño": "Summarize this design prompt as a short title:\n\n"
                             "Hacé un banner de anuncio con un boton.",
    "escritor de memoria": "## Existing Workspace MEMORY.md\n(none)\n## Global User "
                           "Memory\n(none)\n## Conversation Context\n[user]\nWorkspace "
                           "context:\n- Current design title: …",
    "escritor del brief": "## Existing Brief\n(none)\n\n## Workspace MEMORY.md\n---\n"
                          "schemaVersion: 1\n---\n\n# Project Memory",
    "resultado de tool como user": "Attached image(s) from tool result:",
}

HUMANO = "Hacé un banner de anuncio con un boton."


def _msgs(texto: str, n_user: int = 1) -> list:
    fuera = [{"role": "system", "content": "sos un agente"}]
    for i in range(n_user - 1):
        fuera += [{"role": "user", "content": f"previo {i}"},
                  {"role": "assistant", "content": "ok"}]
    return fuera + [{"role": "user", "content": texto}]


TOOLS13 = [{"type": "function", "function": {"name": f"t{i}"}} for i in range(13)]


def main() -> int:
    print("═" * 78)
    print("EL HILO GUARDA EL TURNO HUMANO, NO EL ANDAMIAJE")
    print("═" * 78)

    # ── A · LA MARCA DECLARADA ───────────────────────────────────────────────────────
    print("\nA · LA MARCA DECLARADA — el pedido humano sale de la plantilla del harness")
    t = HW.turno_de(_msgs(LOOP), decl=DECL)
    ok(t is not None and t[1] == HUMANO,
       "A1 · del prompt del loop (1.434 chars) queda EXACTAMENTE lo que el humano escribió",
       repr(t[1])[:70] if t else "None")

    ok(HW.turno_de(_msgs(LOOP)) is not None
       and HW.turno_de(_msgs(LOOP))[1].startswith("Workspace context:"),
       "A2 · SIN declaración el texto va entero — nadie que hoy habla se queda mudo")

    for nombre, texto in AUXILIARES.items():
        ok(HW.turno_de(_msgs(texto), decl=DECL) is None,
           f"A3 · «{nombre}» NO es un turno (no trae la marca)")

    # LA DEGRADACIÓN: plantilla cambiada → no se recorta, pero tampoco se inventa.
    otra = LOOP.replace("User request:", "Petición del usuario:")
    ok(HW.turno_de(_msgs(otra), decl=DECL) is None,
       "A4 · si el harness cambia su plantilla el paso deja de contar — jamás un recorte "
       "inventado")

    _vacio = "User request:\n\nUse the following local context and references."
    ok(HW.pedido_humano(_vacio, DECL) == _vacio,
       "A5 · un recorte que se come el pedido entero devuelve la plantilla ENTERA, no una "
       "fila vacía (que en la pantalla se lee «el usuario no dijo nada»)",
       repr(HW.pedido_humano(_vacio, DECL))[:60])

    ok(HW.pedido_humano("User request:\n" + HUMANO, {"desde": "User request:"}) == HUMANO,
       "A6 · `hasta` es opcional: sin él se toma hasta el final")

    # ── B · EL ID ES ESTABLE DENTRO DEL TURNO ────────────────────────────────────────
    print("\nB · EL MISMO TURNO NO SE ANOTA DOS VECES")
    a = HW.turno_de(_msgs(LOOP), decl=DECL)
    b = HW.turno_de(_msgs(LOOP_PASO2), decl=DECL)
    ok(a and b and a[0] == b[0],
       "B1 · dos pasos del MISMO turno con la plantilla cambiada dan el MISMO id",
       f"{a[0][:18]}… vs {b[0][:18]}…" if a and b else "")

    c = HW.turno_de(_msgs(LOOP.replace(HUMANO, "Hacé otra cosa distinta.")), decl=DECL)
    ok(a and c and a[0] != c[0], "B2 · otro pedido humano da OTRO id")

    # ── C · EL FILTRO GENERAL, PARA EL QUE NO DECLARA NADA ───────────────────────────
    print("\nC · EL FILTRO POR CATÁLOGO — general, y fail-open")
    HW._CON_CATALOGO.clear()
    ok(HW.es_el_loop_del_agente("chat-nuevo", []),
       "C1 · FAIL-OPEN: en un chat que nunca mostró catálogo, todo paso cuenta (hoy)")
    HW.marcar_catalogo("chat-nuevo", TOOLS13)
    ok(HW.es_el_loop_del_agente("chat-nuevo", TOOLS13),
       "C2 · el paso que trae el catálogo del stack es el loop del agente")
    ok(not HW.es_el_loop_del_agente("chat-nuevo", []),
       "C3 · en un chat que YA mostró catálogo, un paso sin catálogo es andamiaje")
    ok(HW.es_el_loop_del_agente("otro-chat", []),
       "C4 · y la marca es POR CHAT: el chat de al lado sigue fail-open")
    ok(not HW.marcar_catalogo("chat-nuevo", []) and HW.es_el_loop_del_agente("otro-chat", []),
       "C5 · marcar con catálogo vacío no marca nada")

    # ── D · LA RESPUESTA NO SE PIERDE ────────────────────────────────────────────────
    print("\nD · EL PASO QUE NO TRAE PEDIDO IGUAL CUELGA DEL TURNO ABIERTO")
    HW._ABIERTO.clear()
    t1, trae1 = HW.turno_del_paso("chat-D", _msgs(LOOP), decl=DECL)
    ok(t1 is not None and trae1 is True,
       "D1 · el paso con la marca ABRE el turno y trae el pedido")
    t2, trae2 = HW.turno_del_paso(
        "chat-D", _msgs(AUXILIARES["resultado de tool como user"], n_user=2), decl=DECL)
    ok(t2 is not None and t2[0] == t1[0] and trae2 is False,
       "D2 · el paso siguiente (el resultado de la tool llega como `user`) NO re-anota el "
       "pedido pero SÍ cuelga del MISMO turno — si no, el hilo se queda sin la respuesta "
       "final")
    t3, _ = HW.turno_del_paso("chat-sin-abrir", _msgs("cualquier cosa"), decl=DECL)
    ok(t3 is None,
       "D3 · sin turno abierto y sin marca no se cuelga de nada")

    print("\n" + "─" * 78)
    print(f"ROJAS: {_ROJAS}")
    return 1 if _ROJAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
