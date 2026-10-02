#!/usr/bin/env python3
"""verify_clave_en_obra.py — ¿la clave de conversación llega al borde de CLIs por el camino
de OBRA (el de La Sala), y no sólo por el de workspaces?

EL AGUJERO QUE CIERRA, medido el 2026-08-26 con la perilla del broker PRENDIDA:

    [broker] codex_cli → cae al camino de hoy · motivo=sin_clave_de_conversacion
    codex_cli: atendidos=0 · caidas={'sin_clave_de_conversacion': 1}

`sobre_turno.poner()` se llamaba en DOS lugares y los dos vivían dentro de
`POST /v1/workspaces/brain/openai/chat/completions`. La Sala va por `/v1/puppets/run` →
`executor.run_puppet_e2e`, así que nadie ponía el sobre: `actual()` daba `(None,None,None)`,
`campos_del_cuerpo()` daba `{}` y el turno salía SIN `sesion`. **El broker no podía entrar
desde La Sala ni prendido, y el `--resume` de claude tampoco.**

SE PRUEBA CONTRA LOS MÓDULOS REALES, no contra dobles — es la lección del último punto
ciego: una vara pasaba en verde porque medía que el evento SE EMITE y no que LLEGA, con un
`on_event` de mentira. Acá se usan `sobre_turno` y `vocabulario` de verdad.

  A · sin sobre puesto, el cuerpo NO lleva `sesion` (el estado que teníamos)
  B · con el sobre puesto, el cuerpo SÍ lo lleva
  C · la clave que arma el camino de obra tiene la FORMA que el broker sabe parsear,
      y el dueño que sale es el usuario — no un dueño-basura
  D · dos chats del mismo usuario NO comparten dueño-de-conversación
  E · el `sacar` deja el contexto limpio (un sobre pegado presta la charla al turno siguiente)

    python3 platform/assembler/verify_clave_en_obra.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI / "cli_brain"))

import sobre_turno as ST                                            # noqa: E402
from cli_brain.broker.vocabulario import dueno_de_clave             # noqa: E402

_F, _OK = [], 0


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1; print(f"  ✅ {t}")
    else:
        _F.append(t); print(f"  ❌ {t}" + (f" — {d}" if d else ""))


#: La clave EXACTA que arma el camino de obra (`router.py`, endpoint /v1/puppets/run).
#: Se escribe acá A MANO: leerla del router sería preguntarle al acusado.
def clave_de_obra(user_id, chat_id):
    return ("%s:%s:chat:%s" % ("sala", (user_id or "-"), chat_id)) if chat_id else None


def main():
    print("=" * 78)
    print("verify_clave_en_obra — ¿la clave llega al borde por el camino de OBRA?")
    print("=" * 78)

    # ── A · el estado de antes ────────────────────────────────────────────────
    print("\n[A] sin sobre puesto, el cuerpo va SIN `sesion`")
    cuerpo = ST.campos_del_cuerpo(True)
    ok(cuerpo == {}, f"A1 sin sobre → cuerpo vacío ({cuerpo})")

    # ── B · con el sobre ──────────────────────────────────────────────────────
    print("\n[B] con el sobre puesto, el cuerpo SÍ lleva la clave")
    clave = clave_de_obra("u-42", "chat-abc")
    tok = ST.poner(None, None, clave)
    try:
        cuerpo = ST.campos_del_cuerpo(True)
        ok(cuerpo.get("sesion") == clave,
           f"B1 el cuerpo lleva `sesion` = la clave ({cuerpo})")
        # Y NO se lo manda a un borde que no es de CLIs: ahí sería un campo de más.
        ok(ST.campos_del_cuerpo(False) == {},
           "B2 y a un borde que NO es de CLIs no le manda nada")
    finally:
        ST.sacar(tok)

    # ── C · la forma, y el dueño ──────────────────────────────────────────────
    print("\n[C] la clave tiene la forma que el broker parsea, y el dueño es el usuario")
    ok(len(clave.split(":")) >= 4, f"C1 cuatro campos ({clave})")
    d = dueno_de_clave(clave)
    ok(d == "u-42", f"C2 el dueño que sale es el usuario, no basura ({d})")
    # Fail-closed: sin usuario NO puede caer en un dueño compartido.
    d_sin = dueno_de_clave(clave_de_obra(None, "chat-abc"))
    ok(d_sin != "u-42" and d_sin, f"C3 sin usuario NO hereda el dueño de otro ({d_sin})")

    # ── D · dos chats no se cruzan ────────────────────────────────────────────
    print("\n[D] dos chats del mismo usuario son conversaciones DISTINTAS")
    k1, k2 = clave_de_obra("u-42", "chat-A"), clave_de_obra("u-42", "chat-B")
    ok(k1 != k2, "D1 claves distintas por chat")
    ok(dueno_de_clave(k1) == dueno_de_clave(k2) == "u-42",
       "D2 y sin embargo el DUEÑO es el mismo (el pool separa por clave, no por dueño)")

    # ── E · el sobre no se pega ───────────────────────────────────────────────
    print("\n[E] el `sacar` deja el contexto limpio")
    tok2 = ST.poner(None, None, clave_de_obra("u-99", "chat-Z"))
    ST.sacar(tok2)
    ok(ST.campos_del_cuerpo(True) == {},
       f"E1 después del sacar el cuerpo vuelve a ir vacío ({ST.campos_del_cuerpo(True)})")

    print("\n" + "-" * 78)
    print(f"{_OK} verdes · {len(_F)} rojas")
    for f in _F:
        print(f"   ❌ {f}")
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
