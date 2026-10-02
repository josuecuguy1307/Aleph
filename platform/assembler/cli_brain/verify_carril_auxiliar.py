#!/usr/bin/env python3
"""verify_carril_auxiliar.py — el hop AUXILIAR deja de bloquear al hop de OFICIO.

QUÉ MIDIÓ ESTO (paso 5, turnos desde la pantalla, `ALEPH_GRABAR_PROMPT` + `PUPPET_CLI_EVENTOS`):
los stacks piden su hop de oficio y sus hops auxiliares **a la vez**, y con el techo por
provider en 1 el auxiliar se lleva el único slot:

    Oficina   el TÍTULO pidió primero  → el oficio esperó 2,67 s
    Ciencia   2 de 3 hops son auxiliares → 5,69-8,14 s de cola
    Diseño    preferencias + título     → 2,73 s
    Finanzas  el título va DESPUÉS       → 0,00 s
    La Sala   sin auxiliares             → 0,00 s

  A · un AUXILIAR no espera detrás de un OFICIO — y entra YA
  B · el techo del OFICIO no se movió (lo que este arreglo NO puede hacer es subir la
      concurrencia contra la cuenta del usuario por la puerta de atrás)
  C · el carril tiene su propio techo: dos auxiliares no se acumulan
  D · el carril SE DICE en `estado()` — un turno que corre por otro carril y no aparece
      es exactamente la clase de cosa que deja de decirse
  E · `soltar` devuelve al carril correcto (si no, se filtra y el carril se tapa solo)
  F · la perilla `PUPPET_CLI_SLOTS_AUX=0` devuelve el comportamiento de antes
  G · EL CLASIFICADOR: `auxiliar` es «este pedido cruza SIN catálogo», leído del MISMO
      `tools` que va a cruzar — no de un nombre ni de una heurística

    python3 -m assembler.cli_brain.verify_carril_auxiliar
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assembler.cli_brain import slots as S                      # noqa: E402

_FALLOS, _OK = [], 0


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


def a_el_auxiliar_no_espera():
    print("\n[A] un AUXILIAR no espera detrás de un OFICIO")
    P = S.Slots(limite=2)
    P.pedir("claude_cli")                       # el oficio se lleva el slot del provider
    t0 = time.monotonic()
    entro = True
    try:
        # espera_s=0 a propósito: si tuviera que hacer cola, rebota y lo cazamos.
        P.pedir("claude_cli", auxiliar=True, espera_s=0)
    except S.SinSlot:
        entro = False
    ms = (time.monotonic() - t0) * 1000
    ok(entro, "A: el auxiliar entra con el oficio corriendo",
       "rebotó: sigue compartiendo el techo del oficio")
    ok(ms < 50, f"A: y entra YA ({ms:.1f} ms), no después", f"tardó {ms:.1f} ms")


def b_el_techo_del_oficio_no_se_movio():
    print("\n[B] el techo del OFICIO no se movió")
    P = S.Slots(limite=2)
    P.pedir("claude_cli")
    P.pedir("claude_cli", auxiliar=True, espera_s=0)
    reboto = False
    try:
        P.pedir("claude_cli", espera_s=0)
    except S.SinSlot as e:
        reboto = (e.motivo == S.PROVIDER_OCUPADO)
    ok(reboto, "B: un SEGUNDO oficio sigue rebotando con `provider_ocupado`",
       "el carril auxiliar subió la concurrencia del oficio por la puerta de atrás")
    est = P.estado()
    ok(est["activos"] == 1,
       "B: el auxiliar NO cuenta en `activos` (es otro carril, no un slot más)",
       str(est))


def c_el_carril_tiene_techo():
    print("\n[C] el carril auxiliar tiene su propio techo")
    P = S.Slots(limite=4)
    P.pedir("claude_cli", auxiliar=True, espera_s=0)
    reboto = False
    try:
        P.pedir("claude_cli", auxiliar=True, espera_s=0)
    except S.SinSlot:
        reboto = True
    ok(reboto, "C: dos auxiliares del mismo provider no se acumulan",
       "el carril no tiene techo: los títulos podrían apilarse contra la misma cuenta")
    P.soltar("claude_cli", auxiliar=True)
    entro = True
    try:
        P.pedir("claude_cli", auxiliar=True, espera_s=0)
    except S.SinSlot:
        entro = False
    ok(entro, "C: y se libera al soltarlo")


def d_el_carril_se_dice():
    print("\n[D] el carril SE DICE en `estado()`")
    P = S.Slots(limite=2)
    P.pedir("grok_cli", auxiliar=True, espera_s=0)
    est = P.estado()
    ok("aux_en_vuelo" in est and est["aux_en_vuelo"] == ["grok_cli"],
       "D: `aux_en_vuelo` nombra al provider que corre por el carril", str(est))
    ok(est.get("aux_por_provider", {}).get("grok_cli", {}).get("techo") is not None,
       "D: y publica su techo", str(est.get("aux_por_provider")))
    ok("grok_cli" not in est["en_vuelo"],
       "D: y NO se lo cuenta como turno de oficio (sería un número que miente)", str(est))


def e_soltar_devuelve_al_carril_correcto():
    print("\n[E] `soltar` devuelve al carril correcto")
    P = S.Slots(limite=2)
    P.pedir("claude_cli")
    P.pedir("claude_cli", auxiliar=True, espera_s=0)
    P.soltar("claude_cli", auxiliar=True)
    est = P.estado()
    ok(est["aux_en_vuelo"] == [] and est["en_vuelo"] == ["claude_cli"],
       "E: soltar el auxiliar no le suelta el slot al oficio", str(est))
    P.soltar("claude_cli")
    est = P.estado()
    ok(est["activos"] == 0 and est["en_vuelo"] == [] and est["aux_en_vuelo"] == [],
       "E: y soltar el oficio deja todo en cero", str(est))
    # el filtrado: soltar el auxiliar SIN la bandera dejaría el carril tapado para siempre
    P2 = S.Slots(limite=2)
    P2.pedir("claude_cli", auxiliar=True, espera_s=0)
    P2.soltar("claude_cli", auxiliar=True)
    entro = True
    try:
        P2.pedir("claude_cli", auxiliar=True, espera_s=0)
    except S.SinSlot:
        entro = False
    ok(entro, "E: el carril no se tapa solo después de un ciclo completo")


def f_la_perilla():
    print("\n[F] la perilla devuelve el comportamiento de antes")
    import importlib
    previo = os.environ.get("PUPPET_CLI_SLOTS_AUX")
    try:
        os.environ["PUPPET_CLI_SLOTS_AUX"] = "0"
        importlib.reload(S)
        P = S.Slots(limite=2)
        P.pedir("claude_cli")
        reboto = False
        try:
            P.pedir("claude_cli", auxiliar=True, espera_s=0)
        except S.SinSlot:
            reboto = True
        ok(reboto, "F: con `PUPPET_CLI_SLOTS_AUX=0` el auxiliar vuelve a hacer cola")
        # ⚠️ Y EL VACÍO TAMBIÉN APAGA, sin reventar. Es la regla de la casa
        # («ausente ⇒ default; presente-y-vacío ⇒ apagado») y el caso que un `or` o un
        # `int()` pelado rompen: con `""`, el `or` cae otra vez en el default y el `int()`
        # tira `ValueError` en el import. La primera versión de esta vara sólo probaba
        # `"0"` — y por eso un mutante con `or` le SOBREVIVIÓ.
        os.environ["PUPPET_CLI_SLOTS_AUX"] = ""
        exploto = False
        try:
            importlib.reload(S)
        except Exception as e:                              # noqa: BLE001
            exploto = repr(e)
        ok(exploto is False, "F: con la variable VACÍA el módulo no revienta al importarse",
           f"levantó {exploto}")
        if exploto is False:
            P2 = S.Slots(limite=2)
            P2.pedir("claude_cli")
            reboto2 = False
            try:
                P2.pedir("claude_cli", auxiliar=True, espera_s=0)
            except S.SinSlot:
                reboto2 = True
            ok(reboto2, "F: y con la variable VACÍA el carril queda APAGADO",
               "vacío no apagó: es el bug del `or`, que esta casa ya pagó")
        # y un valor basura no tumba el arranque
        os.environ["PUPPET_CLI_SLOTS_AUX"] = "no-soy-un-numero"
        basura_ok = True
        try:
            importlib.reload(S)
        except Exception:                                   # noqa: BLE001
            basura_ok = False
        ok(basura_ok, "F: y un valor basura NO tumba el arranque (avisa y usa el default)")
    finally:
        if previo is None:
            os.environ.pop("PUPPET_CLI_SLOTS_AUX", None)
        else:
            os.environ["PUPPET_CLI_SLOTS_AUX"] = previo
        importlib.reload(S)
    # y por default está PRENDIDO
    P = S.Slots(limite=2)
    P.pedir("claude_cli")
    entro = True
    try:
        P.pedir("claude_cli", auxiliar=True, espera_s=0)
    except S.SinSlot:
        entro = False
    ok(entro, "F: y por default el carril está prendido")


def g_el_clasificador():
    print("\n[G] el clasificador sale del `tools` que VA A CRUZAR, no de un nombre")
    fuente = (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
    ok(re.search(r"_es_auxiliar\s*=\s*not\s+_tools", fuente) is not None,
       "G: `server.py` clasifica con `not _tools` — el catálogo real del pedido",
       "si clasificara por nombre de agente o por heurística, un oficio podría colarse "
       "al carril auxiliar y saltarse el techo de la cuenta")
    ok(re.search(r"SLOTS\.pedir\([^)]*auxiliar=_es_auxiliar", fuente, re.S) is not None,
       "G: y se lo pasa a `pedir`")
    ok(len(re.findall(r"SLOTS\.soltar\([^)]*auxiliar=_es_auxiliar", fuente, re.S)) >= 2,
       "G: y a los DOS `soltar` (si uno se olvida, el carril se filtra)",
       str(len(re.findall(r"SLOTS\.soltar\(", fuente))))


CASOS = [a_el_auxiliar_no_espera, b_el_techo_del_oficio_no_se_movio,
         c_el_carril_tiene_techo, d_el_carril_se_dice,
         e_soltar_devuelve_al_carril_correcto, f_la_perilla, g_el_clasificador]


def main() -> int:
    print("=" * 74)
    print("VERIFY CARRIL AUXILIAR — el título deja de bloquear al turno de verdad")
    print("=" * 74)
    for c in CASOS:
        c()
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
