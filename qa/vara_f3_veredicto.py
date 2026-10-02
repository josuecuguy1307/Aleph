#!/usr/bin/env python3
"""VARA · F3 — «Probada» significa algo: la fusión de LOS DOS registros de veredicto.

QUÉ CUIDA, Y POR QUÉ EXISTE. La cara decía «Listo» sobre cualquier llave que estuviera en el
vault. Medido en el vault real del dueño: `exa` tenía llave y CERO veredicto; `zotero` tenía
`{"estado":"verde","tool_prueba":"whoami"}`. Los dos se pintaban igual. Es el mismo
`connected = len(set) > 0` que Fase 0 midió en Ciencia, repetido por omisión.

Y el arreglo tenía una trampa propia, que esta vara es la que la agarra: **hay DOS puertas de
guardado y no escriben en el mismo registro**.
  · `POST /v1/conexiones/key`             → `verificar_uno` → `conexiones.credencial`
  · `POST /v1/connectors/<slug>/connect`  → `MV.probar`     → el registro del motor
Leer uno solo deja en «Guardada» para siempre a toda llave puesta por la otra puerta, aunque
al guardarla se haya probado de verdad.

LAS TRES DISTINCIONES QUE NO SE PUEDEN PERDER:
  `None`  = nadie probó (o no hay sesión para saberlo)   ≠
  `False` = se probó y NO pasó, y `falla` dice por qué   ≠
  `True`  = veredicto verde, con SU fecha y SU evidencia.

    python3 qa/vara_f3_veredicto.py
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

_RAIZ = Path(os.environ.get("ALEPH_VARA_RAIZ") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(_RAIZ / "product" / "backend"))
sys.path.insert(0, str(_RAIZ / "platform"))

_verdes: list[str] = []
_rojas: list[str] = []


def _ok(nombre: str, cond: bool, detalle: str = "") -> None:
    (_verdes if cond else _rojas).append(nombre)
    print(f"  {'✅' if cond else '❌'} {nombre}" + (f"  — {detalle}" if detalle and not cond else ""))


def main() -> int:
    try:
        from app.phase1.connectors_router import _dos_hechos
    except Exception as e:                          # noqa: BLE001
        # ASÍ CAE CONTRA UN ÁRBOL SIN LA OBRA: no se concluye nada, se dice que no hay qué medir.
        print(f"❌ no pude importar `_dos_hechos`: {type(e).__name__}: {e}")
        print("   ¿estás en un árbol sin la obra de F3?")
        return 1

    VERDE_CX = {"probada": True, "cuando": "2026-07-31T10:00:00", "con": "whoami"}
    VERDE_MV = {"probada": True, "cuando": "2026-08-17T20:00:00", "con": "una llamada autenticada"}
    ROJO_MV = {"probada": False, "falla": "key_invalida", "cuando": "2026-08-17T20:00:00", "con": None}
    # ⚠️ ESTE CASO TIENE DATO EN LOS DOS A PROPÓSITO. La primera versión de esta vara usaba
    # un `cx` con los campos en `None`, y entonces mezclar registros daba el mismo resultado
    # que no mezclarlos: el chequeo no podía ponerse rojo. Probado mutando la fusión a
    # `cx.get("con") or mv.get("con")` — 15 verdes, 0 rojas. Un chequeo que no cae no mide.
    RECHAZADA_CX = {"probada": False, "estado": "rechazada",
                    "cuando": "2026-06-01T09:00:00", "con": "list_items"}

    print("\n── SIN SESIÓN NO SE AFIRMA NADA ──────────────────────────────────────")
    r = _dos_hechos("exa", {"exa": VERDE_CX}, {"exa": VERDE_MV}, None)
    _ok("sin dueño, `verificado` es None aunque haya veredictos", r["verificado"] is None, repr(r))

    print("\n── NADIE PROBÓ ≠ FALLÓ ───────────────────────────────────────────────")
    r = _dos_hechos("exa", {}, {}, "u1")
    _ok("sin veredicto en ningún registro → None (no False)", r["verificado"] is None, repr(r))
    _ok("sin veredicto, la fecha también es None", r["verificado_cuando"] is None, repr(r))

    print("\n── UNA FILA SIN VEREDICTO NO ES UN VEREDICTO ────────────────────────")
    # EL CASO QUE FALTABA, Y POR ESO EL DEFECTO PASÓ. Todos mis fixtures traían `estado`, así
    # que el chequeo de «None ≠ False» sólo probaba el caso SIN FILA. Medido contra el vault
    # real: `exa` tiene fila en `conexiones` con `credencial: null` —existe porque la pieza
    # está en el registro, no porque alguien la probara— y salía `verificado: False`.
    MUDA_CX = {"probada": False, "estado": None, "cuando": None, "con": None}
    r = _dos_hechos("exa", {"exa": MUDA_CX}, {}, "u1")
    _ok("fila en `conexiones` sin veredicto → None, no False", r["verificado"] is None, repr(r))
    _ok("y sin fecha inventada", r["verificado_cuando"] is None, repr(r))
    # Y NO PUEDE TAPAR AL OTRO: si el motor sí probó, la fila muda no puede robarle el turno.
    r = _dos_hechos("exa", {"exa": MUDA_CX}, {"exa": VERDE_MV}, "u1")
    _ok("una fila muda no le gana a un verde del motor", r["verificado"] is True, repr(r))
    _ok("ni le presta su fecha vacía", r["verificado_cuando"] == VERDE_MV["cuando"], repr(r))
    r = _dos_hechos("exa", {"exa": MUDA_CX}, {"exa": ROJO_MV}, "u1")
    _ok("ni tapa un rechazo medido", r["verificado"] is False and r["verificado_falla"] == "key_invalida", repr(r))

    print("\n── UN VERDE EN CUALQUIERA DE LOS DOS MANDA ───────────────────────────")
    r = _dos_hechos("exa", {}, {"exa": VERDE_MV}, "u1")
    _ok("verde SÓLO en el motor → True", r["verificado"] is True, repr(r))
    _ok("y viaja SU fecha, no la del otro", r["verificado_cuando"] == VERDE_MV["cuando"], repr(r))
    r = _dos_hechos("zotero", {"zotero": VERDE_CX}, {}, "u1")
    _ok("verde SÓLO en conexiones → True", r["verificado"] is True, repr(r))
    _ok("y viaja SU evidencia (`whoami`)", r["verificado_con"] == "whoami", repr(r))

    print("\n── LA FECHA Y LA EVIDENCIA NO SE MEZCLAN ENTRE REGISTROS ─────────────")
    # Fabricar un veredicto que nadie emitió —la fecha de uno con la evidencia del otro— es
    # exactamente la clase de mentira que esta obra vino a matar.
    r = _dos_hechos("exa", {"exa": RECHAZADA_CX}, {"exa": VERDE_MV}, "u1")
    _ok("gana el verde entero: fecha Y evidencia del MISMO registro",
        r["verificado_cuando"] == VERDE_MV["cuando"] and r["verificado_con"] == VERDE_MV["con"], repr(r))
    _ok("y no se cuela la evidencia del registro perdedor",
        r["verificado_con"] != RECHAZADA_CX["con"], repr(r))
    _ok("ni su fecha", r["verificado_cuando"] != RECHAZADA_CX["cuando"], repr(r))

    print("\n── SE PROBÓ Y NO PASÓ: EL TERCER ESTADO ──────────────────────────────")
    r = _dos_hechos("exa", {}, {"exa": ROJO_MV}, "u1")
    _ok("rechazada → False, no None", r["verificado"] is False, repr(r))
    _ok("y la causa viaja CRUDA para que la cara la traduzca",
        r["verificado_falla"] == "key_invalida", repr(r))
    r = _dos_hechos("exa", {}, {"exa": VERDE_MV}, "u1")
    _ok("un verde NO trae causa de falla", r["verificado_falla"] is None, repr(r))

    print("\n── LA CAUSA TIENE COPY (regla sellada) ───────────────────────────────")
    # Una causa que llega a una superficie sin copy es un código crudo en la cara del usuario.
    sem = (_RAIZ / "product" / "app" / "design" / "cuarto" / "cuarto.semaforo.js").read_text(encoding="utf-8")
    faltan = [c for c in ("key_invalida", "sin_credito", "rate_limit", "sin_red", "timeout")
              if f"\n  {c}:" not in sem and f"\n  {c} " not in sem]
    _ok("las causas que el motor emite están en el diccionario del semáforo",
        not faltan, f"sin copy: {faltan}")

    print("\n── LA CARA NO ESCRIBE SU PROPIA COPY ─────────────────────────────────")
    reco = (_RAIZ / "product" / "app" / "design" / "conectores" / "recomendados.js").read_text(encoding="utf-8")
    _ok("`recomendados.js` importa CAUSAS_HUMANAS en vez de redactar",
        "CAUSAS_HUMANAS" in reco, "no la importa: hay una segunda tabla de copy")
    panel = (_RAIZ / "product" / "app" / "design" / "workspaces" / "conectores-del-espacio.js").read_text(encoding="utf-8")
    _ok("el panel del canvas LLAMA al derivador, no lo copia",
        "estadoDe" in panel and "selloDe" in panel and '"Probada" : "Guardada"' not in panel,
        "el panel volvió a tener su propia copia de la decisión")

    print("\n── LAS CAPAS NO SE PISAN (la ley de `3541f7c3`) ─────────────────────")
    # La vista se escribió con sus lecturas, sus clicks y su guardado adentro: un archivo
    # haciendo los cuatro trabajos que esa obra separó cuando demolió 4.592 líneas por
    # exactamente eso. Y el guardado propio le costó al dueño un rojo falso sobre una llave
    # buena. Esta vara es lo que impide que vuelva sin que nadie lo note.
    d = _RAIZ / "product" / "app" / "design"
    for rel in ("conectores/recomendados.js", "workspaces/conectores-del-espacio.js"):
        txt = (d / rel).read_text(encoding="utf-8")
        _ok(f"{rel.split('/')[-1]} no habla con la red por su cuenta",
            "fetch(" not in txt, "volvió a tener su propio fetch: la capa LEE es `recomendaciones.js`")
    # LOS CLICKS SON DE `montaje.js`. La vista se ataba los suyos —cumpliendo la delegación,
    # pero en el piso equivocado—: dos lugares que deciden qué hace un click es cómo el mismo
    # botón termina haciendo cosas distintas según qué archivo se tocó último.
    reco_vivo = "\n".join(l for l in (d / "conectores" / "recomendados.js")
                          .read_text(encoding="utf-8").split("\n")
                          if not l.strip().startswith(("*", "//", "/*")))
    _ok("la vista no se ata sus propios eventos",
        "addEventListener" not in reco_vivo,
        "volvió a atarse sola: los nodos y los clicks son de `montaje.js`")
    mont = (_RAIZ / "product" / "app" / "design" / "conectores" / "montaje.js").read_text(encoding="utf-8")
    _ok("montaje ata los tres eventos de la cuarta vista",
        all(x in mont for x in ("RECO.alClick", "RECO.alSubmit", "RECO.alCambiarEspacio")),
        "montaje no los ata: la vista quedaría muda")
    html = (_RAIZ / "product" / "app" / "design" / "Conectores.dc.html").read_text(encoding="utf-8")
    html_vivo = "\n".join(l for l in html.split("\n") if not l.strip().startswith(("*", "//", "/*")))
    _ok("la pantalla entrega nodos y no monta la vista por su cuenta",
        "montarRecomendados" not in html_vivo and "recoFilas" in html_vivo,
        "la pantalla volvió a montar la cuarta vista aparte")

    fte = (d / "conectores" / "recomendaciones.js").read_text(encoding="utf-8")
    _ok("la capa LEE usa las cabeceras de la casa",
        "cabeceras" in fte and "Authorization" not in fte,
        "arma su propia autorizacion en vez de `fuentes.cabeceras()`")
    reco_txt = (d / "conectores" / "recomendados.js").read_text(encoding="utf-8")
    # ⚠️ MIRA CÓDIGO, NO PROSA. La primera versión buscaba «/connect» en todo el archivo y se
    # puso roja por el COMENTARIO que explica el defecto — un chequeo que castiga documentar
    # lo que pasó. Se descartan las líneas de comentario antes de buscar.
    vivo = "\n".join(l for l in reco_txt.split("\n")
                     if not l.strip().startswith(("*", "//", "/*")))
    # ⚠️ Y BUSCA EL ENDPOINT, NO LA SUBCADENA: «/v1/connectors» CONTIENE «/connect», así que
    # un `in` pelado se pone rojo con cualquier lectura del catálogo. Lo agarré midiendo, con
    # un arnés que gritó «tocó el wizard» sobre una llamada a `/oauth/start`.
    import re as _re
    wizard = _re.search(r"/v1/connectors/[^/\s\"'`]+/connect\b", vivo)
    _ok("guardar va por la puerta de la casa, no por el wizard",
        "guardarLlave" in vivo and not wizard,
        "volvio a `POST /v1/connectors/<slug>/connect`: ese camino no hace strip, no guarda "
        "sin validador y aplana las causas")

    print("\n── EL ENDPOINT SIRVE LOS CUATRO CAMPOS ───────────────────────────────")
    router = (_RAIZ / "product" / "backend" / "app" / "phase1" / "connectors_router.py").read_text(encoding="utf-8")
    _ok("lee el registro del motor con `estado` y NO con `probar`",
        "_MV.estado(_MV.KEY" in router and "_MV.probar(" not in router,
        "pintar la lista dispararía 29 pruebas reales contra proveedores")

    print("\n" + "─" * 70)
    print(f"VERDES {len(_verdes)} · ROJAS {len(_rojas)}")
    if _rojas:
        print("rojas: " + ", ".join(_rojas))
    return 1 if _rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
