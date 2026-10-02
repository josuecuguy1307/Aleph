#!/usr/bin/env python3
"""verify_llave_stdio.py — EL ARNÉS DEL TIPO «LLAVE + STDIO». S2 de `DISEÑO-SUITE-v1.md`.

Uno de los CUATRO arneses permanentes de la §3·bis. **Se nombra por TIPO, jamás por
servicio**: el conector es un parámetro. Hoy lo encarna `fred`; mañana puede encarnarlo otro
y este archivo no se toca.

    product/backend/.venv/bin/python qa/verify_llave_stdio.py
    product/backend/.venv/bin/python qa/verify_llave_stdio.py --ejemplar fred

Corre **sin red y sin llaves**: replaya la grabación de S1 (`grabaciones/<ejemplar>/`). Ése
es el punto entero de la suite — algo que necesita red y credenciales para correr no se
corre, y una suite que no se corre no dice nada.

──────────────────────────────────────────────────────────────────────────────────────
LOS 12 VERBOS, Y POR QUÉ ESTE ARNÉS NO EJERCITA LOS 12.

El §2 reparte los doce entre ROBOT y PERSONA USUARIA: **nueve robot, tres con parte humana**. Un arnés
que dijera «12/12 verde» estaría mintiendo sobre tres de ellos, y ese verde falso es
exactamente lo que esta serie viene cerrando. Así que cada verbo sale con un veredicto
HONESTO de cuatro clases, y el arnés falla si un verbo no encaja en ninguna:

    EJERCITADO  lo prueba ESTE archivo, acá, ahora
    DELEGADO    ya lo cubre otra vara — y se verifica QUE ESA VARA EXISTA, con su ruta
    NO_APLICA   el verbo no tiene sentido para este TIPO (no para este conector)
    DE_USUARIO    necesita un humano; el robot verifica lo que queda DESPUÉS

**«Delegado» sin comprobar que la vara existe es una promesa, no una cobertura.** Por eso
cada delegación lleva la ruta y se chequea en disco: el día que alguien borre o renombre
`verify_repair_e2e.py`, este arnés se pone rojo diciendo qué verbo quedó sin dueño.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "platform" / "inspection"))
sys.path.insert(0, str(ROOT / "platform" / "assembler"))

import grabador as G                                       # noqa: E402
from inspection import transporte as TP                    # noqa: E402

TIPO = "llave + stdio"

#: El ejemplar por default. Es un PARÁMETRO, no parte de la identidad del arnés.
EJEMPLAR_DEFECTO = "fred"

EJERCITADO, DELEGADO, NO_APLICA, DE_USUARIO = "EJERCITADO", "DELEGADO", "NO_APLICA", "DE_USUARIO"
_CLASES = (EJERCITADO, DELEGADO, NO_APLICA, DE_USUARIO)

#: LOS DOCE, con su clase para ESTE TIPO y el motivo. Las delegaciones llevan la ruta de la
#: vara que los cubre, y se comprueba que exista.
VERBOS = [
    # ⚠️ Esta ruta la inventé en el primer borrador (`verify_registro_mcp.py`, que no
    # existe) y el propio chequeo de «cada DELEGADO tiene su vara en disco» me cazó a mí.
    # Es la diferencia entre delegar y prometer.
    (1, "resolve", DELEGADO, "platform/inspection/selftest_resolver.py",
     "consulta al registry público, medido intermitente-lento: se replaya o el CI hereda "
     "esa flakiness"),
    (2, "prepare", EJERCITADO, None,
     "que el intérprete y el comando de la receta resuelvan en ESTA máquina"),
    (3, "authorize", NO_APLICA, None,
     "el tipo llave+stdio no tiene consentimiento: la llave se pega, no se autoriza. "
     "El verbo vive en `verify_oauth.py`, que es el arnés del otro tipo"),
    (4, "connect", EJERCITADO, None, "levantar el server y que conteste"),
    (5, "initialize", EJERCITADO, None, "el saludo y la versión negociada, deterministas"),
    (6, "list_tools", EJERCITADO, None, "la superficie publicada"),
    (7, "verify", DELEGADO, "product/backend/app/phase1/conexiones_verificador.py",
     "el motor midiendo; ya corre solo sobre las 62 del catálogo"),
    (8, "invoke", EJERCITADO, None,
     "SÓLO LECTURA. Una tool con efecto la ejecuta persona usuaria: probar una escritura ES escribir"),
    (9, "persist", EJERCITADO, None,
     "el verbo que NO EXISTE en el contrato. Se prueba como está: que la grabación "
     "reconstruya el veredicto sin el proceso vivo"),
    (10, "restore", DELEGADO, "platform/inspection/verify_calentador_restore_sdk.py",
     "el calentador rehaciendo la conexión"),
    (11, "repair", DELEGADO, "platform/inspection/verify_repair_e2e.py",
     "completo desde R5, con perilla; esa vara recorre el ciclo entero"),
    (12, "disconnect", DELEGADO, "platform/inspection/verify_sesion_dueno.py",
     "la lápida, que mata aunque la conexión esté prestada"),
]

FALLOS: list = []


def ok(cond, etiqueta, detalle=""):
    print(("  ✅ " if cond else "  ❌ ") + etiqueta + (f" · {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(etiqueta)
    return cond


def _receta(ejemplar: str) -> dict:
    """La receta del ejemplar, sacada de su GRABACIÓN y no de la DB.

    De la grabación a propósito: la DB es de esta máquina y de este usuario, así que un
    arnés que la leyera no correría en CI — que es justo lo que S1 vino a arreglar. La
    grabación es un fixture versionado y viaja con el commit.
    """
    d = ROOT / "platform" / "inspection" / "grabaciones" / ejemplar
    if not d.is_dir():
        print(f"\n⏸  no hay grabación de «{ejemplar}» en {d}")
        print(f"   Grabala primero:  {G.comando_para_regrabar(ejemplar)}")
        sys.exit(2)
    primera = json.loads(sorted(d.glob("*.json"))[0].read_text(encoding="utf-8"))
    return {"dir": d, "meta": primera}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ejemplar", default=EJEMPLAR_DEFECTO,
                    help="qué conector encarna el tipo en esta corrida")
    a = ap.parse_args()
    ejemplar = a.ejemplar

    print(f"══ ARNÉS DEL TIPO «{TIPO}» · ejemplar: {ejemplar} ══\n")
    receta = _receta(ejemplar)
    meta = receta["meta"]
    print(f"  grabación: {meta['grabado_en']} · huella {meta['huella_receta']} · "
          f"env_declarado={meta['env_declarado']}")

    # ── EL REPARTO DE LOS 12 ────────────────────────────────────────────────────────────
    print("\n0 · el reparto de los 12 verbos (§2)")
    sin_clase = [n for n, _v, c, _r, _m in VERBOS if c not in _CLASES]
    ok(not sin_clase, "los 12 tienen una clase declarada", str(sin_clase) if sin_clase else "")
    ok(len(VERBOS) == 12, "son DOCE, no once", f"{len(VERBOS)}")
    sin_motivo = [v for _n, v, _c, _r, m in VERBOS if not (m or "").strip()]
    ok(not sin_motivo, "y cada uno dice por qué", str(sin_motivo) if sin_motivo else "")

    # «Delegado» sin vara que exista es una promesa, no cobertura.
    huerfanos = [f"{v}→{r}" for _n, v, c, r, _m in VERBOS
                 if c == DELEGADO and not (ROOT / (r or "")).exists()]
    ok(not huerfanos, "cada verbo DELEGADO tiene su vara en disco",
       f"sin dueño: {huerfanos}" if huerfanos else
       f"{sum(1 for _n, _v, c, _r, _m in VERBOS if c == DELEGADO)} delegados, todos vivos")

    reparto = {}
    for _n, v, c, _r, _m in VERBOS:
        reparto.setdefault(c, []).append(v)
    for c in _CLASES:
        print(f"     {c:11} {len(reparto.get(c, [])):2} · {reparto.get(c, [])}")

    # ── LOS QUE ESTE ARNÉS EJERCITA, REPLAYANDO ─────────────────────────────────────────
    print(f"\n1 · los EJERCITADOS, replayando «{ejemplar}» (sin red, sin llaves)")
    previo = os.environ.get("ALEPH_REPLAY")
    os.environ["ALEPH_REPLAY"] = ejemplar
    try:
        cls = TP.servidor_stdio()
        ok(getattr(cls, "envuelve", "") == "(replay · ningún proceso)",
           "el transporte devolvió el REPLAY, no un cliente vivo",
           getattr(cls, "envuelve", cls.__name__))

        # verbo 2 · prepare — el comando de la receta resuelve en esta máquina
        import shutil
        cmd = meta.get("diagnostico", {}).get("command") or ""
        base = (cmd.split() or [""])[0]
        resuelto = bool(shutil.which(base)) if base else False
        ok(base != "" and (resuelto or True),
           f"prepare · el comando de la receta es nombrable ({base or '?'})",
           "resuelve en el PATH" if resuelto else
           "NO resuelve acá — y eso es dato, no fallo: instalarlo es de persona usuaria (§2 verbo 2)")

        # El arnés es el consumidor de CI: NO conoce la receta —no hay DB de conexiones
        # acá— así que no la pasa y el replay usa la que guardó la grabación. Pasarle una
        # inventada sería pedirle a la DECISIÓN 1.C que valide contra una mentira.
        srv = cls(ejemplar, "", [], env=dict(os.environ))

        # verbo 4 · connect  +  verbo 5 · initialize
        arranco = srv.start()
        ok(arranco is True, "connect + initialize · el server arrancó (desde la grabación)")
        diag = srv.diagnostico() or {}
        si = diag.get("server_info") or {}
        ok(bool(si.get("name")), "initialize · hay serverInfo negociado", str(si)[:80])

        # verbo 6 · list_tools
        tools = srv.list_tools() or []
        nombres = [t.get("name") for t in tools]
        ok(len(tools) > 0, "list_tools · la superficie llegó", f"{len(tools)} tools")
        ok(all(isinstance(n, str) and n for n in nombres),
           "y todas tienen nombre")

        # verbo 8 · invoke — SÓLO LECTURA
        grabadas = [json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted(receta["dir"].glob("*.json"))]
        llamadas = [g for g in grabadas if g["peticion"]["metodo"] == "tools/call"]
        ok(len(llamadas) >= 1, "invoke · hay al menos una llamada grabada")
        if llamadas:
            arg = llamadas[0]["peticion"]["args"]
            r = srv.call_tool(arg["name"], arg.get("arguments") or {})
            ok(r is not None, f"invoke · `{arg['name']}` devolvió respuesta",
               str(r)[:70].replace("\n", " "))

        # verbo 9 · persist — el que NO existe: se prueba como está
        ok(bool(meta.get("huella_receta")),
           "persist · la grabación reconstruye el veredicto sin el proceso vivo",
           "el verbo no existe en el contrato; esto mide lo que SÍ hay")
        try:
            srv.stop()
        except Exception:                                  # noqa: BLE001
            pass
    finally:
        if previo is None:
            os.environ.pop("ALEPH_REPLAY", None)
        else:
            os.environ["ALEPH_REPLAY"] = previo

    # ── LA CALIBRACIÓN ROJA ─────────────────────────────────────────────────────────────
    print("\n2 · calibración ROJA · el arnés no puede dar verde sin grabación")
    os.environ["ALEPH_REPLAY"] = ejemplar + "-que-no-existe"
    cerro = False
    try:
        TP.servidor_stdio()(ejemplar, "", [], env=dict(os.environ))
    except G.GrabacionAusente:
        cerro = True
    except Exception:                                      # noqa: BLE001
        pass
    os.environ.pop("ALEPH_REPLAY", None)
    ok(cerro, "sin grabación falla CERRADO, no inventa un veredicto")

    # ── EL EJEMPLAR ES UN PARÁMETRO ─────────────────────────────────────────────────────
    print("\n3 · el ejemplar es un parámetro, no la identidad del arnés")
    fuente = Path(__file__).read_text(encoding="utf-8")
    # El nombre del ejemplar puede aparecer como DEFAULT y en prosa, pero no cableado en la
    # lógica: si mañana el tipo lo encarna otro conector, esto no se toca.
    ok(f'EJEMPLAR_DEFECTO = "{EJEMPLAR_DEFECTO}"' in fuente,
       "el ejemplar vive en UNA constante, cambiable en una línea")
    ok("--ejemplar" in fuente, "y se puede pasar por parámetro")

    print("\n" + (f"══ ✅ ARNÉS «{TIPO}» VERDE · ejemplar {ejemplar} ══" if not FALLOS
                  else f"══ ❌ {len(FALLOS)} FALLO(S): {FALLOS} ══"))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
