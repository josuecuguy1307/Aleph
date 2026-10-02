#!/usr/bin/env python3
"""verify_sesion_prefijo.py — LA COLA SÓLO SE MANDA SI EL PRINCIPIO SIGUE SIENDO EL MISMO.

    python3 platform/assembler/cli_brain/verify_sesion_prefijo.py
    python3 …/verify_sesion_prefijo.py --caer     # la prueba de caída

QUÉ MIDE. `_armar_prompt` decidía la cola con `mensajes[enviados:]` comparando sólo
LARGOS. Medido en Diseño el 2026-08-23, conversación real de 4 turnos desde la pantalla:
de **14 roturas de prefijo, la guarda por largo atrapa 5 y se le escapan 9**, porque el
`context-prune` del stack reescribe mensajes viejos y el historial crece igual.

DOS COSAS QUE ESTA VARA EVITA A PROPÓSITO, porque ya dejaron ciegas a otras dos:

  · **No calcula lo esperado con la función bajo prueba.** No hay un solo `huella_de` del
    lado del `assert`: se afirma sobre CONDUCTA — si mandó cola o mandó todo, si el id se
    renovó, cuánto pesa el prompt. Una vara que arma su expectativa con la misma función
    que mide se queda verde para siempre.
  · **Trae el caso REAL, no sólo casos de forma.** El bloque B es la reescritura EXACTA
    que graba el `context-prune` de Diseño (`[tool result dropped — use view() …]`) con la
    lista creciendo — que es el caso que la guarda por largo no ve. Sin él, una versión que
    no arregla nada podría pasar todo lo demás.
"""
from __future__ import annotations

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from cli_brain import sesiones as SES                                # noqa: E402
from cli_brain.server import _armar_prompt                           # noqa: E402

MUTAR = "--caer" in sys.argv
RES = []


def chk(titulo, cond, detalle=""):
    RES.append((titulo, bool(cond)))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {titulo}" + (f"  · {detalle}" if detalle else ""))


class _SesionFalsa:
    """Lo que `_armar_prompt` toca de una sesión, y nada más."""

    def __init__(self, enviados=0, huella=None, restaurada=False):
        self.id = "id-viejo"
        self.turnos = 1
        self.enviados = enviados
        self.huella = list(huella or [])
        self.restaurada = restaurada
        self.renovada = 0

    @property
    def fresca(self):
        return self.turnos == 0 and not self.restaurada

    def renovar_id(self):
        self.id = "id-nuevo-%d" % self.renovada
        self.renovada += 1
        self.enviados = 0
        self.huella = []
        return self.id


def _msg(rol, txt, **extra):
    d = {"role": rol, "content": txt}
    d.update(extra)
    return d


# ── EL HISTORIAL REAL DE DISEÑO, copiado de la grabación ────────────────────────────
SYSTEM = _msg("system", "You are Diseño, the design workspace of Aleph — " + "x" * 2000)
U1 = _msg("user", "Workspace context:\n…\nUser request:\nHace una landing simple.")
A1 = _msg("assistant", '<function=scaffold>{"kind": "landing-hero"}</function>')
T1 = _msg("tool", "Scaffolded landing-hero -> App.jsx (3221 bytes)", tool_call_id="c1")
A2 = _msg("assistant", "Reemplazo el scaffold con la landing completa: " + "y" * 9000)
T2 = _msg("tool", "Created App.jsx", tool_call_id="c2")
A3 = _msg("assistant", '<function=preview>{"path": "App.jsx"}</function>')
T3 = _msg("tool", "preview ok: 58 nodes, 0 console errors", tool_call_id="c3")

#: LA REESCRITURA QUE HACE EL STACK. Verbatim de `context-prune.ts` v3, tal como la grabó
#: el instrumento: el mensaje viejo se REEMPLAZA por un stub, y la lista SIGUE CRECIENDO.
A2_PODADO = _msg("assistant",
                 '[prior assistant output dropped — 10116B, head: "Reemplazo el scaffold '
                 'con la landing completa: tokens propios, hero y…"]')

TOOLS = [{"type": "function",
          "function": {"name": "scaffold", "description": "copia un starter",
                       "parameters": {"type": "object",
                                      "properties": {"kind": {"type": "string"}},
                                      "required": ["kind"]}}}]


def _huella(msgs):
    """La huella que el server habría guardado. Se usa SÓLO para ARMAR el escenario —
    nunca para calcular lo que se espera."""
    return SES.huella_de(msgs)


def main() -> int:
    print("═" * 78)
    print("LA COLA SÓLO SE MANDA SI EL PRINCIPIO SIGUE SIENDO EL MISMO")
    print("═" * 78)

    # ── A · `prefijo_vivo` ───────────────────────────────────────────────────────────
    print("\nA · el guardián")
    hist = [SYSTEM, U1, A1, T1]
    chk("A1 · sin nada enviado no hay prefijo que reconocer (fail-closed)",
        SES.prefijo_vivo(_SesionFalsa(enviados=0), hist) is False)
    chk("A2 · con `enviados` pero SIN huella tampoco (fail-closed)",
        SES.prefijo_vivo(_SesionFalsa(enviados=4, huella=[]), hist) is False)
    s = _SesionFalsa(enviados=4, huella=_huella(hist))
    chk("A3 · el mismo principio, intacto → vivo",
        SES.prefijo_vivo(s, hist + [A2, T2]) is True)
    chk("A4 · el historial se ACORTÓ → no vivo",
        SES.prefijo_vivo(s, hist[:2]) is False)
    chk("A5 · un mensaje del medio CAMBIÓ → no vivo",
        SES.prefijo_vivo(s, [SYSTEM, U1, _msg("assistant", "otra cosa"), T1, A2]) is False)

    # ── B · EL CASO REAL: el `context-prune` reescribe Y la lista crece ──────────────
    # Es el caso que la guarda por largo NO ve: len(6) > enviados(6)… y el contenido de
    # A2 ya no es el que el CLI leyó.
    print("\nB · el caso REAL — el `context-prune` del stack (9 de 14 roturas medidas)")
    hist6 = [SYSTEM, U1, A1, T1, A2, T2]
    s6 = _SesionFalsa(enviados=6, huella=_huella(hist6))
    hist8_podado = [SYSTEM, U1, A1, T1, A2_PODADO, T2, A3, T3]
    chk("B1 · el largo CRECIÓ (6→8), así que la guarda vieja habría mandado la cola",
        len(hist8_podado) > s6.enviados)
    chk("B2 · pero el prefijo está reescrito → NO vivo",
        SES.prefijo_vivo(s6, hist8_podado) is False)

    p, inc = _armar_prompt(s6, hist8_podado, TOOLS)
    chk("B3 · `_armar_prompt` manda TODO, no la cola", inc is False)
    chk("B4 · y renueva el id: el CLI viejo tiene otra conversación",
        s6.renovada == 1, f"id={s6.id}")
    # ⚠️ CORRECCIÓN PROPIA: acá había un umbral de TAMAÑO (`len(p) > 8000`) y estaba mal.
    # El historial podado es legítimamente MÁS CHICO —el stub reemplazó 10 KB— así que el
    # umbral medía el peso del stub, no si el render fue completo. Lo que prueba «mandó
    # todo» es la FORMA: el system más los OCHO mensajes, no una cola de dos.
    chk("B5 · el prompt completo trae el system y los 8 mensajes (no una cola)",
        "You are Diseño" in p and "Scaffolded landing-hero" in p
        and "preview ok" in p and "dropped" in p,
        f"{len(p)} chars")

    # ── C · EL AHORRO, cuando el prefijo SÍ sobrevive ────────────────────────────────
    print("\nC · el ahorro — cuando el principio sigue igual")
    s7 = _SesionFalsa(enviados=6, huella=_huella(hist6))
    p_inc, inc2 = _armar_prompt(s7, hist6 + [A3, T3], TOOLS)
    chk("C1 · con el prefijo vivo, manda SÓLO lo nuevo", inc2 is True)
    chk("C2 · y no renueva el id (la conversación sigue)", s7.renovada == 0)
    chk("C3 · el system NO viaja de nuevo — que es el 61,9 % del prompt de Diseño",
        "You are Diseño" not in p_inc, f"{len(p_inc)} chars")

    s8 = _SesionFalsa(enviados=6, huella=_huella(hist6))
    p_full, _ = _armar_prompt(_SesionFalsa(enviados=0), hist6 + [A3, T3], TOOLS)
    chk("C4 · y pesa MUCHO menos que el completo",
        len(p_inc) < len(p_full) / 2, f"{len(p_inc)} vs {len(p_full)} chars")

    # ── F · SÓLO LOS CLI QUE SABEN CONTINUAR ────────────────────────────────────────
    # La lista blanca es lo que hace que la perilla pueda estar PRENDIDA: con Grok, honrar
    # la clave rompía la entrega (`⟲ resume perdido → ✗ timeout → ✗ exit 1`).
    print("\nF · la lista blanca de resume (medida contra los binarios)")
    chk("F1 · claude_cli, que es el único con el resume probado",
        SES.resume_probado("claude_cli") is True)
    chk("F2 · grok_cli NO — rompía la entrega", SES.resume_probado("grok_cli") is False)
    chk("F3 · codex_cli NO — sigue con `--ephemeral` por dos pruebas de seguridad",
        SES.resume_probado("codex_cli") is False)
    chk("F4 · y un CLI que nadie midió tampoco (lista BLANCA, fail-closed)",
        SES.resume_probado("un_cli_nuevo") is False and SES.resume_probado(None) is False)

    # ── E · EL CAMINO DE ESCRITURA ──────────────────────────────────────────────────
    # ⚠️ ESTE BLOQUE EXISTE PORQUE LA VARA TENÍA UN PUNTO CIEGO Y EL MUTANTE LO ENCONTRÓ:
    # con «la huella no se guarda» la vara quedaba 18/18, porque armaba las sesiones a
    # mano. Todo lo de arriba mide al LECTOR; nadie medía al ESCRITOR. Por eso el avance
    # se extrajo a `sesiones.avanzar` — para que exista algo que mirar.
    print("\nE · el que ESCRIBE la huella (el punto ciego que encontró el mutante)")
    se = _SesionFalsa(enviados=0)
    SES.avanzar(se, hist6)
    chk("E1 · avanzar deja el contador en lo que se mandó", se.enviados == len(hist6))
    chk("E2 · y NUNCA lo deja sin huella — es el invariante entero",
        len(se.huella) == se.enviados and se.enviados > 0, f"huella={len(se.huella)}")
    chk("E3 · y con eso el lector reconoce su propio prefijo",
        SES.prefijo_vivo(se, hist6 + [A3, T3]) is True)
    chk("E4 · pero NO reconoce uno reescrito",
        SES.prefijo_vivo(se, hist8_podado) is False)
    se2 = _SesionFalsa(enviados=0)
    SES.avanzar(se2, [])
    chk("E5 · sin mensajes no finge un prefijo",
        se2.enviados == 0 and SES.prefijo_vivo(se2, hist6) is False)

    # ── D · LO QUE NO SE ROMPE ──────────────────────────────────────────────────────
    print("\nD · lo de siempre sigue igual")
    chk("D1 · sin sesión, render completo (byte por byte lo de hoy)",
        _armar_prompt(None, hist6, TOOLS)[1] is False)
    fresca = _SesionFalsa(enviados=0)
    fresca.turnos = 0
    chk("D2 · una sesión fresca también", _armar_prompt(fresca, hist6, TOOLS)[1] is False)
    rest = _SesionFalsa(enviados=0, restaurada=True)
    rest.turnos = 0
    chk("D3 · una RESTAURADA manda todo y lo reporta como no-incremental",
        _armar_prompt(rest, hist6, TOOLS)[1] is False)
    s9 = _SesionFalsa(enviados=6, huella=_huella(hist6))
    chk("D4 · sin nada nuevo, se renueva y se manda todo (no una cola vacía)",
        _armar_prompt(s9, hist6, TOOLS)[1] is False and s9.renovada == 1)

    print("\n" + "═" * 78)
    v = sum(1 for _, o in RES if o)
    print(f"VERDES {v} / {len(RES)}")
    rojas = [n for n, o in RES if not o]
    for n in rojas:
        print(f"  ROJO · {n}")
    if MUTAR:
        ok = len(rojas) > 0
        print("\nPRUEBA DE CAÍDA: " + ("la vara SE PUSO ROJA con la pieza mutada — mide"
                                       if ok else
                                       "la vara siguió VERDE con la pieza rota — NO MIDE"))
        return 0 if ok else 1
    return 1 if rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
