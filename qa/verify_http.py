#!/usr/bin/env python3
"""verify_http.py — EL ARNÉS DEL TIPO «HTTP». S3 de `DISEÑO-SUITE-v1.md`.

Uno de los CUATRO arneses permanentes de la §3·bis. **Se nombra por TIPO, jamás por
servicio**: el conector es un parámetro. Hoy lo encarna `exa`; mañana puede encarnarlo otro
y este archivo no se toca.

    product/backend/.venv/bin/python qa/verify_http.py
    product/backend/.venv/bin/python qa/verify_http.py --ejemplar exa

Corre **sin red y sin llaves**: replaya `grabaciones/<ejemplar>/`. El molde de los 12 verbos
vive en `qa/lib/arnes_suite.py` y es el mismo para los cuatro tipos.

──────────────────────────────────────────────────────────────────────────────────────
⚠️ LA LIMITACIÓN DE ESTE TIPO, DICHA ARRIBA Y NO EN LETRA CHICA (§6.2 del diseño).

**El ejemplar de HTTP no habla HTTP.** `exa` es el arquetipo más sano de los cuatro —es el
único con `credencial=verde`, o sea la única credencial PROBADA contra su proveedor— pero
corre por **stdio**: el verificador declara que el transporte http «no está cableado»
(`conexiones_verificador.py:509-512`). El único HTTP vivo del producto es el camino **BYO**,
y ése se certifica en `verify_byo_headers.py` (§4) + `verify_byo_cli.py`.

Así que este arnés hace dos cosas distintas y las separa a la vista:
  · **ejercita** los verbos del tipo sobre el ejemplar, replayando (lo que sí se puede);
  · **declara** que el transporte HTTP real está cubierto por otro lado, con la ruta de esa
    vara verificada en disco — igual que cualquier otro DELEGADO.

Un arnés que dijera «HTTP verde» sin esa separación estaría certificando un transporte que
nunca corrió.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from arnes_suite import (Arnes, DELEGADO, DE_USUARIO, EJERCITADO,       # noqa: E402
                         NO_APLICA, parser)

TIPO = "HTTP"

#: El ejemplar por default. Es un PARÁMETRO, no parte de la identidad del arnés.
EJEMPLAR_DEFECTO = "exa"

VERBOS = [
    (1, "resolve", DELEGADO, "platform/inspection/selftest_resolver.py",
     "consulta al registry público, medido intermitente-lento: se replaya o el CI hereda "
     "esa flakiness"),
    (2, "prepare", EJERCITADO, None,
     "que el intérprete y el comando de la receta resuelvan en ESTA máquina"),
    (3, "authorize", NO_APLICA, None,
     "el tipo HTTP del catálogo es BYOK: la llave se PEGA, no se autoriza. El consentimiento "
     "vive en `verify_oauth.py`, que es el arnés del otro tipo"),
    (4, "connect", EJERCITADO, None, "levantar el server y que conteste"),
    (5, "initialize", EJERCITADO, None, "el saludo y la versión negociada, deterministas"),
    (6, "list_tools", EJERCITADO, None, "la superficie publicada"),
    (7, "verify", DELEGADO, "product/backend/app/phase1/conexiones_verificador.py",
     "el motor midiendo; `exa` es la ÚNICA de las 62 con `credencial=verde` — la única "
     "credencial probada de verdad contra su proveedor"),
    (8, "invoke", EJERCITADO, None,
     "SÓLO LECTURA. Una búsqueda no escribe nada; una tool con efecto la ejecuta persona usuaria"),
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

#: EL TRANSPORTE HTTP DE VERDAD, y quién lo cubre. Se chequea en disco como un DELEGADO más:
#: prometer que «lo cubre el BYO» sin que esa vara exista es la misma promesa vacía que la
#: §3·bis persigue en los verbos.
HTTP_REAL = {
    "qa/verify_byo_headers.py": "el check de seguridad del manifest BYO (§4)",
    "qa/verify_byo_cli.py": "el alta de un BYO-HTTP por CLI, de punta a punta",
}


def main() -> int:
    a = parser(EJEMPLAR_DEFECTO).parse_args()
    arn = Arnes(TIPO, a.ejemplar, VERBOS)
    print(f"══ ARNÉS DEL TIPO «{TIPO}» · ejemplar: {arn.ejemplar} ══\n")

    grab = arn.grabacion()
    meta = grab["meta"]
    print(f"  grabación: {meta['grabado_en']} · huella {meta['huella_receta']} · "
          f"env_declarado={meta['env_declarado']}")

    arn.reparto()
    arn.replay(grab)

    # ── EL HUECO DEL TIPO, DECLARADO ────────────────────────────────────────────────
    print("\n1·bis · el transporte HTTP real (§6.2): no lo corre este arnés")
    from arnes_suite import ROOT
    faltan = [f"{r} ({q})" for r, q in HTTP_REAL.items() if not (ROOT / r).exists()]
    arn.ok(not faltan, "las varas que SÍ corren HTTP existen en disco",
           f"sin dueño: {faltan}" if faltan else ", ".join(HTTP_REAL))
    arn.nota("el ejemplar corre por stdio: `conexiones_verificador.py:509-512` declara el "
             "transporte http no cableado. Lo de arriba mide el TIPO, no el protocolo")

    arn.calibracion_roja()
    arn.ejemplar_es_parametro(__file__, EJEMPLAR_DEFECTO)
    return arn.cerrar()


if __name__ == "__main__":
    sys.exit(main())
