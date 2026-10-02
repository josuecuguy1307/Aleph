#!/usr/bin/env python3
"""verify_oauth.py — EL ARNÉS DEL TIPO «OAUTH». S3 de `DISEÑO-SUITE-v1.md`.

El cuarto y último de los arneses permanentes de la §3·bis. **Se nombra por TIPO, jamás por
servicio**: el conector es un parámetro. Hoy lo encarna `onshape`.

    product/backend/.venv/bin/python qa/verify_oauth.py
    product/backend/.venv/bin/python qa/verify_oauth.py --ejemplar onshape

──────────────────────────────────────────────────────────────────────────────────────
ACÁ SE ABSORBEN LOS DOS TRANSITORIOS, Y LA EXCEPCIÓN DE LA §3·bis VENCE HOY.

`verify_nombres_suite.py` los tenía declarados con vencimiento automático: **en cuanto este
archivo exista, los dos tienen que haber desaparecido.** Desaparecieron:

    qa/verify_onshape_oauth.py        →  qa/lib/casos_oauth.py        (CASO A)
    qa/verify_onshape_lectura_real.py →  qa/lib/caso_lectura_real.py  (CASO B)

**Por qué a `qa/lib/` y no pegados adentro de este archivo.** El daño que la ley persigue es
que el contrato del tipo quede repartido en N *varas* que se parecen: N entradas, N verdes,
y nadie sabe qué se le exige al conector 29. Eso muere acá — hay **una** vara del tipo OAuth,
una entrada, un veredicto, y los casos son su biblioteca. Pegar 700 líneas de calibraciones
de un IdP local dentro del arnés no lo haría más honesto, lo haría ilegible; y `qa/lib/` ya
es donde vive lo que las varas usan y no se corre solo. Los dos módulos siguen nombrados por
**caso**, no por servicio: `casos_oauth` es el ciclo del tipo, `caso_lectura_real` es «con
consentimiento dado, el tipo entrega datos».

LOS TRES NIVELES, que miden cosas distintas y por eso no se mezclan:

  1 · **replay** del ejemplar (sin red, sin llaves) — los verbos de conexión;
  2 · **CASO A**, determinista contra un IdP local: PKCE, loopback, vault cifrado, refresh
      rotativo, revocación, scope→superficie. **Es lo que hace certificable a `authorize`
      sin un humano**, y por eso este tipo es el único donde ese verbo no es NO_APLICA;
  3 · **CASO B**, la lectura real contra la cuenta. Sólo corre si persona usuaria ya dio el
      consentimiento; si no, se declara **DE_USUARIO** y NO se cuenta como verde (§6.8).

⚠️ LA SALVEDAD DEL EJEMPLAR, DICHA Y NO TAPADA (§3): el arquetipo OAuth corre hoy sobre un
secreto **de desarrollo**. El `loopback_verdict` de onshape dice que la distribución necesita
account broker — Onshape exige `client_secret` en el canje aun con PKCE S256, así que el
loopback de cliente público puro no le alcanza. El ciclo se midió de punta a punta y eso
certifica el verbo; el camino distribuible todavía no existe.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from arnes_suite import (Arnes, DELEGADO, DE_USUARIO, EJERCITADO,       # noqa: E402
                         NO_APLICA, ROOT, parser)

TIPO = "OAuth"

#: El ejemplar por default. Es un PARÁMETRO, no parte de la identidad del arnés.
EJEMPLAR_DEFECTO = "onshape"

VERBOS = [
    (1, "resolve", DELEGADO, "platform/inspection/selftest_resolver.py",
     "consulta al registry público, medido intermitente-lento: se replaya o el CI hereda "
     "esa flakiness"),
    (2, "prepare", EJERCITADO, None,
     "que el intérprete y el comando de la receta resuelvan en ESTA máquina"),
    (3, "authorize", EJERCITADO, None,
     "EL VERBO DE ESTE TIPO, y el único arnés que lo ejercita. El CASO A recorre el ciclo "
     "entero contra un IdP local: PKCE, loopback, canje, vault cifrado, refresh y "
     "revocación — sin necesitar el navegador de nadie"),
    (4, "connect", EJERCITADO, None, "levantar el server y que conteste"),
    (5, "initialize", EJERCITADO, None, "el saludo y la versión negociada, deterministas"),
    (6, "list_tools", DE_USUARIO, None,
     "la superficie de este tipo LA DECIDE EL GRANT: sin consentimiento el server arranca y "
     "publica CERO tools (`sin_tools` en el barrido). El scope→superficie sí se ejercita "
     "determinista en el CASO A; lo que falta acá es el grant real"),
    (7, "verify", DELEGADO, "product/backend/app/phase1/conexiones_verificador.py",
     "el motor midiendo; hoy mide `rota/sin_tools` sobre este ejemplar y tiene razón: sin "
     "token inyectado no hay superficie"),
    (8, "invoke", DE_USUARIO, None,
     "SÓLO LECTURA, y el CASO B lo tiene armado con lista blanca de dos tools comparadas "
     "por igualdad. Se dispara cuando el token existe; un robot no puede dar ese "
     "consentimiento sin fingir ser persona usuaria"),
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

#: LOS DOS CASOS ABSORBIDOS, con la ruta de su módulo. Si alguien los borra o los renombra,
#: este arnés se pone rojo diciendo cuál falta — la misma regla que los DELEGADO.
CASOS = {
    "A · el ciclo OAuth contra un IdP local": "qa/lib/casos_oauth.py",
    "B · la lectura real contra la cuenta": "qa/lib/caso_lectura_real.py",
}


def _caso_a(arn: Arnes):
    """El ciclo completo, determinista. Corre de verdad: no necesita red ni consentimiento."""
    print("\n2 · CASO A · el ciclo OAuth contra un IdP local (determinista)")
    import casos_oauth
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = casos_oauth.main()
    except SystemExit as e:                                            # noqa: PERF203
        rc = int(e.code or 0)
    except Exception as e:                                             # noqa: BLE001
        rc = 1
        buf.write(f"\nEXCEPCIÓN: {type(e).__name__}: {e}")
    salida = buf.getvalue()
    lineas = [l for l in salida.splitlines() if l.strip()]
    aciertos = sum(1 for l in lineas if l.lstrip().startswith(("✓", "✅")))
    arn.ok(rc == 0, "authorize · el ciclo entero (PKCE · loopback · vault · refresh · "
                    "revocación · scope→superficie)",
           f"{aciertos} calibraciones ✓")
    if rc != 0:
        for l in lineas[-25:]:
            print("     " + l)


def _caso_b(arn: Arnes):
    """La lectura real. Sólo si el consentimiento ya está dado; si no, se DECLARA."""
    print("\n3 · CASO B · la lectura real contra la cuenta (necesita consentimiento)")
    import caso_lectura_real
    buf = io.StringIO()
    rc = 0
    try:
        with redirect_stdout(buf):
            rc = caso_lectura_real.main()
    except SystemExit as e:
        rc = int(e.code or 0)
    except Exception as e:                                             # noqa: BLE001
        rc = 1
        buf.write(f"\nEXCEPCIÓN: {type(e).__name__}: {e}")
    salida = buf.getvalue()
    if rc == 2:
        # ⚠️ EXIT 2 NO ES UN FALLO Y NO PUEDE CONTARSE COMO VERDE. Es el paso humano que no
        # ocurrió (§6.8). Se declara y sigue: un arnés que se pusiera rojo por esto estaría
        # diciendo que el código está mal cuando lo que falta es una decisión de persona usuaria.
        motivo = next((l for l in salida.splitlines() if "⏸" in l), "sin consentimiento")
        arn.nota(f"invoke · NO disparado — {motivo.strip()}")
        arn.nota("es la tarea 3 de la lista de persona usuaria (§5.2): decidir qué se hace con Onshape")
        return
    arn.ok(rc == 0, "invoke · la lectura real contra la cuenta",
           next((l for l in salida.splitlines() if "whoami" in l), "").strip())
    if rc == 0:
        # ⚠️ HALLAZGO DE S3, y es un ROJO FALSO DEL BARRIDO, no de acá. La grabación de este
        # ejemplar salió `rota/sin_tools` y la lectura real publica SEIS tools y contesta.
        # No se contradicen: `conexiones_verificador` **no le inyecta el token del vault**
        # (arma el env desde la receta), así que mide un onshape sin credencial y concluye
        # que no publica nada. El camino de producción —`recipe_assembler._servidor_stdio`,
        # que es el que usa el run— sí lo inyecta. O sea: la card muestra roja una pieza que
        # anda. Se declara acá porque el arreglo es del verificador, no del arnés.
        arn.nota("el barrido mide este ejemplar `rota/sin_tools` y la lectura real ANDA: el "
                 "verificador no inyecta el token del vault. Rojo falso en la card")
    if rc != 0:
        for l in salida.splitlines()[-15:]:
            print("     " + l)


def main() -> int:
    a = parser(EJEMPLAR_DEFECTO).parse_args()
    arn = Arnes(TIPO, a.ejemplar, VERBOS)
    print(f"══ ARNÉS DEL TIPO «{TIPO}» · ejemplar: {arn.ejemplar} ══\n")

    grab = arn.grabacion()
    meta = grab["meta"]
    print(f"  grabación: {meta['grabado_en']} · huella {meta['huella_receta']} · "
          f"env_declarado={meta['env_declarado']}")

    arn.reparto()

    # Los dos casos absorbidos existen en disco, o esto es una promesa vacía.
    faltan = [f"{q} → {r}" for q, r in CASOS.items() if not (ROOT / r).exists()]
    arn.ok(not faltan, "los dos casos absorbidos están en disco",
           f"sin dueño: {faltan}" if faltan else ", ".join(CASOS.values()))

    # Sin consentimiento este ejemplar publica CERO tools: exigir superficie sería exigir
    # que persona usuaria haya hecho su parte.
    arn.replay(grab, espera_tools=False)
    _caso_a(arn)
    _caso_b(arn)
    arn.calibracion_roja()
    arn.ejemplar_es_parametro(__file__, EJEMPLAR_DEFECTO)
    return arn.cerrar()


if __name__ == "__main__":
    sys.exit(main())
