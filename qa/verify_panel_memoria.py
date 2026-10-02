"""verify_panel_memoria.py — EL PANEL DE MEMORIA: ver lo que Aleph recuerda, y poder sacarlo.

EL AGUJERO QUE CIERRA. La memoria funcionaba desde hace rato: el executor la inyecta en el
system prompt de CADA turno, en tres sitios (cuenta `:1047`, agente `:1119`, compartida
`:1258`). Y `executor.py:811` ya le decía al usuario «(+N recuerdo(s) más en tu panel de
memoria)». **Ese panel no existía.** Aleph se acordaba de cosas del usuario y el usuario no
tenía cómo verlas ni cómo sacarlas: memoria invisible y no removible.

CASI TODO ESTABA (séptima vez en este ciclo): `GET`/`DELETE` por agente, el `_mem_gate`
anti-IDOR, el repo entero. Lo único que faltaba era **la vista por DUEÑO** — sin ella el
panel serían 190 pedidos, uno por agente, porque el `puppet_id` de la Sala sale de
`?puppet=` y por defecto es `null`, así que cada corrida acuñó el suyo y los recuerdos
reales quedaron repartidos en decenas de agentes.

QUÉ MIDE, contra la DB de verdad y sin servidor:
  R1  el agregado por dueño existe y devuelve lo del dueño
  R2  y SÓLO lo del dueño (el join contra `puppets` es el único scope posible:
      `agent_memories` no tiene columna de dueño)
  R3  cada fila trae `puppet_id`, que es lo que el panel necesita para borrar
  R4  y trae `puppet_name`, para que el usuario sepa de qué agente es cada recuerdo
  R5  el DELETE que ya existía saca la fila de verdad
  R6  el panel NO inventa un segundo DELETE: usa el de por-agente

Correr:  product/backend/.venv/bin/python qa/verify_panel_memoria.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_ROOT, "product", "backend"))
sys.path.insert(0, os.path.join(_ROOT, "platform"))   # `aleph_paths`, que repo carga
from app.phase1 import repo                                          # noqa: E402

_V, _R, _F = "\033[32m", "\033[31m", "\033[0m"
_filas = []
_nomed: list = []


def _a(n, ok, det):
    _filas.append((n, ok))
    print(f"  [{(_V+'VERDE'+_F) if ok else (_R+'ROJA'+_F)}] {n} — {det}")


def main() -> int:
    print("\n  el panel de memoria: ver lo que recuerda, y poder sacarlo\n\nMEDICIÓN")
    conn = repo.get_conn()

    # DOS dueños, para que el aislamiento se pruebe y no se declare.
    uA = repo.get_or_create_user(conn, "panel-mem-A@test.local", tier="free")["id"]
    uB = repo.get_or_create_user(conn, "panel-mem-B@test.local", tier="free")["id"]
    pA = repo.create_puppet(conn, owner_id=uA, name="Agente de A", nicho="general", config={})["id"]
    pB = repo.create_puppet(conn, owner_id=uB, name="Agente de B", nicho="general", config={})["id"]
    mA = repo.add_memory(conn, puppet_id=pA, content="A recuerda esto", source="user")
    repo.add_memory(conn, puppet_id=pB, content="B recuerda lo suyo", source="user")

    # ⚠️ SI EL AGREGADO NO EXISTE, R1 ES ROJA Y EL RESTO NO TIENE SUJETO — pero la vara NO
    # se muere acá. Antes era un `repo.list_owner_memories(...)` pelado y contra el árbol
    # sin el panel tiraba `AttributeError` en la línea 57: R2, R3, R4, R5 y R6 no se medían
    # nunca, justo en el árbol que tiene el agujero. Es la tercera vez en esta sesión que
    # una vara mía se cae a mitad y esconde el resto de lo que iba a decir.
    if not hasattr(repo, "list_owner_memories"):
        _a("R1 · el agregado por dueño trae lo mío", False,
           "`repo.list_owner_memories` no existe: sin vista por dueño el panel serían "
           "190 pedidos, uno por agente")
        for _n in ("R2 · y SÓLO lo mío", "R3 · cada fila trae su puppet_id",
                   "R4 · y el nombre del agente", "R5 · borrar la saca de verdad"):
            _nomed.append(_n)
            print(f"  [NO MEDIBLE] {_n} — sin el agregado no hay filas que mirar (lo dice R1)")
        filas = []
    else:
        filas = repo.list_owner_memories(conn, uA)
        mios = [m for m in filas if m["id"] == mA["id"]]
        _a("R1 · el agregado por dueño trae lo mío", len(mios) == 1,
           f"{len(filas)} fila(s) del dueño A, la sembrada entre ellas")

    if hasattr(repo, "list_owner_memories"):
     ajenas = [m for m in filas if "B recuerda" in (m.get("content") or "")]
     _a("R2 · y SÓLO lo mío", not ajenas,
        "cero filas del otro dueño" if not ajenas
        else f"{len(ajenas)} FUGA: el join no está scopeando")
     _a("R3 · cada fila trae su puppet_id", all(m.get("puppet_id") for m in filas),
        "el panel puede borrar: el DELETE es por agente")
     _a("R4 · y el nombre del agente", any(m.get("puppet_name") == "Agente de A" for m in filas),
        "el usuario ve de qué agente es cada recuerdo")
     # R5 · el DELETE que YA existía. No se prueba el endpoint HTTP acá (eso es el panel en
     # pantalla): se prueba que la operación de repo que el endpoint llama saca la fila.
     repo.delete_memory(conn, mA["id"])
     despues = repo.list_owner_memories(conn, uA)
     _a("R5 · borrar la saca de verdad", all(m["id"] != mA["id"] for m in despues),
        f"{len(filas)} → {len(despues)}")

    print("\nPROBADA CAYENDO")
    # R6 · el panel no puede inventar una segunda vía de borrar: una segunda vía es una
    # segunda forma de equivocarse (y de saltearse el `_mem_gate`).
    tpl = open(os.path.join(_ROOT, "product/app/design/Settings.dc.html"),
               encoding="utf-8").read()
    usa_el_de_agente = "/v1/puppets/" in tpl and "/memories/" in tpl
    inventa = bool(re.search(r"method:\s*'DELETE'[^}]{0,120}/v1/users/[^}]{0,60}/memories", tpl))
    # El motivo tiene que decir CUÁL de los dos pasó: «no hay panel» y «hay dos vías de
    # borrar» son hallazgos distintos y una misma frase para los dos manda a buscar mal.
    if usa_el_de_agente and not inventa:
        _motivo = "DELETE /v1/puppets/{pid}/memories/{mid}, con su _mem_gate"
    elif inventa:
        _motivo = "apareció una SEGUNDA vía de borrar, que es una segunda forma de saltearse el gate"
    else:
        _motivo = "el panel no llama a NINGÚN delete de memoria: no se puede sacar lo que recuerda"
    _a("R6 · usa el DELETE que ya existía", usa_el_de_agente and not inventa, _motivo)

    # limpieza: esta vara siembra y se lleva lo suyo.
    repo.clear_memories(conn, pA)
    repo.clear_memories(conn, pB)

    verde = all(ok for _n, ok in _filas) and not _nomed
    print("\n" + "=" * 70)
    print(f"{(_V+'VERDE'+_F) if verde else (_R+'ROJA'+_F)} · "
          + ("lo que recuerda se ve y se puede sacar" if verde
             else ", ".join([n for n, ok in _filas if not ok]
                            + [f"{n} (no medible)" for n in _nomed])))
    print("=" * 70)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
