#!/usr/bin/env python3
"""verify_default_proveedor.py — EL TURNO NO SE TIRA, PERO EL FALLO NO SE TAPA.

    python3 product/backend/app/phase1/verify_default_proveedor.py
    python3 …/verify_default_proveedor.py --caer     (la prueba de caída)

DECISIÓN DEL DUEÑO: cuando el resolver no puede decidir qué modelo atiende el turno, cae a
un default DEL PROVEEDOR ELEGIDO en vez de tirarlo.

LAS DOS MITADES SE MIDEN JUNTAS, y por eso esta vara existe:

  · que CAIGA — `selection_not_found` y `model_unresolved` entregan igual;
  · que NO TAPE — el reemplazo queda anotado en `fallback_chain`, el `selection_ref` del
    snapshot pasa a ser **el que atendió de verdad** (para que el ledger no mienta), y
    `model_not_connected` **NUNCA** cae: si falta la llave, no hay default que valga.

Una vara que midiera sólo la primera mitad daría verde sobre la versión que tapa el fallo,
que es exactamente lo que esta casa no acepta.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.phase1 import model_use_resolver as R                       # noqa: E402
from app.phase1.model_use_contract import ModelUse                   # noqa: E402

MUTAR = "--caer" in sys.argv
RES = []


def chk(titulo, cond, det=""):
    RES.append((titulo, bool(cond)))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {titulo}" + (f"  · {det}" if det else ""))


def fila(pid, *, model="m-1", prov="claude_cli", conectado=True, caps=None):
    f = {"picker_id": pid, "model": model, "brain_provider": prov,
         "conectado": conectado, "label": pid}
    if caps is not None:
        f["model_use_capabilities"] = list(caps)
    return f


def catalogo(filas, default_id=""):
    return {"modelos": list(filas), "default_id": default_id}


def pedido(selection_ref, *, required=None):
    return ModelUse(
        call_id="c1", idempotency_key="c1", workspace_id="diseno", call_class="chat",
        selection_ref=selection_ref, selection_scope="default",
        capabilities={"required": list(required or []), "preferred": []},
    )


def resolver(req, cat):
    return R.resolve_model_use(req, owner_id="u1", read_catalog=lambda _o: cat)


CLAUDE_A = fila("claude_cli", model="claude-code-cli", prov="claude_cli")
CLAUDE_B = fila("claude_otro", model="claude-2", prov="claude_cli")
CODEX = fila("codex_cli", model="codex-cli", prov="codex_cli")


def main() -> int:
    print("═" * 78)
    print("EL TURNO NO SE TIRA, PERO EL FALLO NO SE TAPA")
    print("═" * 78)

    # ── A · CAE, Y AL PROVEEDOR ELEGIDO ─────────────────────────────────────────────
    # ⚠️ EL FIXTURE ES `model_unresolved`, NO `selection_not_found`, Y NO ES CAPRICHO: ahí
    # la fila EXISTE, así que `brain_provider` se lee de ella y el «mismo proveedor» es un
    # hecho, no una inferencia. Es el caso donde el requisito del dueño se puede probar.
    print("\nA · cae al default DEL PROVEEDOR, no a cualquiera")
    roto_claude = fila("claude_roto", model="", prov="claude_cli")   # existe y no resuelve
    cat = catalogo([roto_claude, CLAUDE_A, CODEX], default_id="codex_cli")
    snap = resolver(pedido("claude_roto"), cat)
    chk("A1 · una selección que no resuelve ya no tira el turno", snap is not None)
    chk("A2 · y la atiende una fila del MISMO proveedor",
        snap.selection_ref == "claude_cli", f"atendió {snap.selection_ref}")
    chk("A3 · aunque el Default del dueño sea de OTRO proveedor (codex)",
        snap.selection_ref != "codex_cli")

    # ── B · Y NO LO TAPA ────────────────────────────────────────────────────────────
    print("\nB · el rastro — la mitad que impide que esto sea un parche")
    chk("B1 · `fallback_chain` dice QUÉ se pidió", snap.fallback_chain == ["claude_roto"],
        str(snap.fallback_chain))
    chk("B2 · y `selection_ref` es el que atendió DE VERDAD (el ledger no miente)",
        snap.selection_ref == "claude_cli" and snap.selection_ref not in snap.fallback_chain)
    chk("B3 · `resolved_model` también es el del que atendió",
        snap.resolved_model == "claude-code-cli", snap.resolved_model)
    normal = resolver(pedido("claude_cli"), cat)
    chk("B4 · y un turno SIN sustitución deja la cadena VACÍA (no se anota de más)",
        normal.fallback_chain == [], str(normal.fallback_chain))

    # ── B2 · CUANDO LA FILA NO EXISTE, EL PROVEEDOR SE LEE DEL REF… O NO SE LEE ──────
    # `api:<x>` y `<x>_cli` son las dos formas que el catálogo garantiza. Cualquier otra
    # NO se adivina: cae al Default del dueño, que es una elección suya, y se declara igual.
    print("\nB' · con la fila ausente: se lee el ref, y si no se puede se DICE")
    # La fila `api:anthropic` YA NO ESTÁ (se borró del catálogo), pero queda otra del
    # MISMO proveedor. El ref roto todavía dice quién era: `api:<proveedor>`.
    api_b = fila("api:anthropic-2", model="claude-y", prov="anthropic")
    catB = catalogo([api_b, CODEX], default_id="codex_cli")
    sB = resolver(pedido("api:anthropic"), catB)
    chk("B'1 · de un `api:<proveedor>` roto se lee el proveedor y se queda en él",
        R.proveedor_de({}, "api:anthropic") == "anthropic"
        and sB.selection_ref == "api:anthropic-2", sB.selection_ref)
    catC = catalogo([CLAUDE_A, CODEX], default_id="codex_cli")
    sC = resolver(pedido("un_ref_cualquiera"), catC)
    chk("B'2 · de un ref ILEGIBLE no se inventa proveedor: va al Default del dueño",
        R.proveedor_de({}, "un_ref_cualquiera") == "" and sC.selection_ref == "codex_cli",
        sC.selection_ref)
    chk("B'3 · y esa sustitución se declara igual", sC.fallback_chain == ["un_ref_cualquiera"],
        str(sC.fallback_chain))

    # ── C · 🔴 NUNCA PARA `model_not_connected` ─────────────────────────────────────
    print("\nC · 🔴 si falta la llave, NO hay default que valga")
    desconectado = fila("api:anthropic", model="claude-x", prov="anthropic", conectado=False)
    cat2 = catalogo([desconectado, CLAUDE_A], default_id="claude_cli")
    try:
        resolver(pedido("api:anthropic"), cat2)
        chk("C1 · un modelo sin conectar NO se sustituye: el usuario tiene que enterarse",
            False, "sustituyó — el fallo quedó tapado")
    except R.ResolutionFailure as exc:
        chk("C1 · un modelo sin conectar NO se sustituye: el usuario tiene que enterarse",
            exc.code == "model_not_connected", exc.code)

    # ── D · SI NO HAY CON QUÉ, LA CAUSA ORIGINAL SIGUE LLEGANDO ─────────────────────
    print("\nD · sin reemplazo posible, vuelve la causa de siempre (con su copy)")
    solo_roto = catalogo([fila("x", model="", prov="p")], default_id="")
    try:
        resolver(pedido("x"), solo_roto)
        chk("D1 · sin candidato NO se inventa uno", False, "devolvió algo")
    except R.ResolutionFailure as exc:
        chk("D1 · sin candidato NO se inventa uno: vuelve `model_unresolved`",
            exc.code == "model_unresolved", exc.code)
    vacio = catalogo([], default_id="")
    try:
        resolver(pedido("no_existe"), vacio)
        chk("D2 · con el catálogo vacío tampoco", False, "devolvió algo")
    except R.ResolutionFailure as exc:
        chk("D2 · con el catálogo vacío tampoco: vuelve `selection_not_found`",
            exc.code == "selection_not_found", exc.code)

    # ── E · EL REEMPLAZO PASA LAS MISMAS PUERTAS ────────────────────────────────────
    # Un fallback que se saltea la matriz entrega un turno que el gate habría rechazado.
    print("\nE · el reemplazo cumple lo que el pedido exige, o no es reemplazo")
    ciego = fila("claude_ciego", model="c-1", prov="claude_cli", caps=["text"])
    vidente = fila("claude_ve", model="c-2", prov="claude_cli",
                   caps=["text", "vision"])
    # ⚠️ `roto3` DECLARA su matriz aunque no tenga modelo, y hace falta: las puertas de
    # capacidad corren ANTES que `model_unresolved`, así que una fila sin matriz muere en
    # `capability_unknown` y no llega nunca al reemplazo. Eso es CORRECTO —las causas de
    # capacidad no están en `CAUSAS_CON_DEFAULT`— pero para medir el reemplazo hay que
    # llegar hasta él.
    roto3 = fila("roto3", model="", prov="claude_cli", caps=["text", "vision"])
    cat3 = catalogo([roto3, ciego, vidente], default_id="claude_ciego")
    snap3 = resolver(pedido("roto3", required=["vision"]), cat3)
    chk("E1 · con `vision` exigida, el reemplazo es el que la declara",
        snap3.selection_ref == "claude_ve", snap3.selection_ref)
    chk("E2 · aunque el Default del dueño sea el que NO la declara",
        snap3.selection_ref != "claude_ciego")
    cat4 = catalogo([roto3, ciego], default_id="claude_ciego")
    try:
        resolver(pedido("roto3", required=["vision"]), cat4)
        chk("E3 · y si NINGUNO la declara, no se sustituye", False, "sustituyó igual")
    except R.ResolutionFailure as exc:
        chk("E3 · y si NINGUNO la declara, no se sustituye", True, exc.code)

    # ── F · NUNCA SE ELIGE A SÍ MISMO ───────────────────────────────────────────────
    # ⚠️ ESTE BLOQUE MIDE EL HELPER, NO EL CAMINO ENTERO, Y UN MUTANTE ES LA RAZÓN.
    # Con la vara pasando por `resolve_model_use`, sacar el `!= excluir` NO daba rojo: por
    # el camino de arriba la fila que falla **nunca puede servir** —`selection_not_found`
    # no tiene fila, y `model_unresolved` tiene la fila con `model` vacío, que `_sirve`
    # rechaza— así que la guarda es HOY INALCANZABLE desde el resolver. Se conserva porque
    # cuesta una comparación y porque una causa nueva podría alcanzarla, pero se mide donde
    # sí se puede disparar. Una guarda sin disparador no se declara verde.
    print("\nF · el que falló no puede ser su propio reemplazo (medido en el helper)")
    yo = fila("yo", model="ok", prov="claude_cli")      # sirve perfectamente…
    otro = fila("otro", model="ok2", prov="claude_cli")
    elegido = R.elegir_reemplazo([yo, otro], pedido("yo"), proveedor="claude_cli",
                                 excluir="yo", default_id="yo")
    chk("F1 · una fila que SÍ sirve queda excluida si es la que falló",
        elegido is not None and elegido.get("picker_id") == "otro",
        str((elegido or {}).get("picker_id")))
    solo_yo = R.elegir_reemplazo([yo], pedido("yo"), proveedor="claude_cli",
                                 excluir="yo", default_id="yo")
    chk("F2 · y si era la única, no hay reemplazo (no se devuelve a sí misma)",
        solo_yo is None, str(solo_yo))

    print("\n" + "═" * 78)
    v = sum(1 for _, o in RES if o)
    print(f"VERDES {v} / {len(RES)}")
    rojas = [n for n, o in RES if not o]
    for n in rojas:
        print(f"  ROJO · {n}")
    if MUTAR:
        print("\nPRUEBA DE CAÍDA: " + ("la vara SE PUSO ROJA con la pieza mutada — mide"
                                       if rojas else
                                       "la vara siguió VERDE con la pieza rota — NO MIDE"))
        return 0 if rojas else 1
    return 1 if rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
