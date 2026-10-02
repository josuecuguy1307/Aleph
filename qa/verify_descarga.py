#!/usr/bin/env python3
"""verify_descarga.py — EL ARNÉS DEL TIPO «DESCARGA». S3 de `DISEÑO-SUITE-v1.md`.

Uno de los CUATRO arneses permanentes de la §3·bis. **Se nombra por TIPO, jamás por
servicio**: el conector es un parámetro. Hoy lo encarna `freecad`.

    product/backend/.venv/bin/python qa/verify_descarga.py
    product/backend/.venv/bin/python qa/verify_descarga.py --ejemplar freecad

Corre **sin red y sin llaves**: replaya `grabaciones/<ejemplar>/`. El molde de los 12 verbos
vive en `qa/lib/arnes_suite.py`.

──────────────────────────────────────────────────────────────────────────────────────
QUÉ HACE DISTINTO A ESTE TIPO, y por qué tiene una sección que los otros tres no tienen.

Una pieza de tipo **Descarga** no pide credencial: pide **una app instalada en la máquina**.
Eso mueve la frontera de lo humano de lugar — en `llave + stdio` lo humano es pegar una
llave, acá lo humano es **instalar algo y dejarlo corriendo**. Y tiene una consecuencia
medida que este arnés no tapa:

    el server MCP **bootea igual sin la app**. El `initialize` contesta, `tools/list`
    publica su superficie entera, y recién la PRIMERA llamada falla con
    `[Errno 61] Connection refused`.

O sea que las tres señales que alcanzan para certificar los otros tipos —arranca, saluda,
publica— **acá dan verde con la app apagada**. Por eso el verbo `invoke` está declarado
DE_USUARIO y no EJERCITADO: lo que el replay puede probar es que el server habla, no que el
CAD exista. Llamarlo verde sería el verde falso más caro de los cuatro.

Y por eso además está la sección `1·bis`, que mira la máquina de verdad: la app y su addon.
Es la única parte del arnés que NO es replay, y no puede serlo — una grabación no puede
decir si FreeCAD está instalado acá.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from arnes_suite import (Arnes, DELEGADO, DE_USUARIO, EJERCITADO,       # noqa: E402
                         NO_APLICA, ROOT, parser)

TIPO = "Descarga"

#: El ejemplar por default. Es un PARÁMETRO, no parte de la identidad del arnés.
EJEMPLAR_DEFECTO = "freecad"

VERBOS = [
    (1, "resolve", DELEGADO, "platform/inspection/selftest_resolver.py",
     "consulta al registry público, medido intermitente-lento: se replaya o el CI hereda "
     "esa flakiness"),
    (2, "prepare", EJERCITADO, None,
     "que el intérprete y el comando de la receta resuelvan en ESTA máquina — para este "
     "tipo `prepare` es LA mitad del verbo: la otra mitad es la app, y esa la mira 1·bis"),
    (3, "authorize", NO_APLICA, None,
     "una app local no da consentimiento: se instala. No hay proveedor al que pedirle "
     "permiso ni credencial que pegar (`credencial=no_aplica` en el barrido)"),
    (4, "connect", EJERCITADO, None, "levantar el server y que conteste"),
    (5, "initialize", EJERCITADO, None, "el saludo y la versión negociada, deterministas"),
    (6, "list_tools", EJERCITADO, None,
     "la superficie publicada — que este tipo publica ENTERA aunque la app esté apagada"),
    (7, "verify", DELEGADO, "product/backend/app/phase1/conexiones_verificador.py",
     "el motor midiendo; en el barrido esta pieza da `viva` con la app apagada, que es "
     "justo el matiz que este arnés declara"),
    (8, "invoke", DE_USUARIO, None,
     "exige FreeCAD ABIERTO con el RPC del addon vivo en 127.0.0.1:9875. Sin eso la "
     "llamada devuelve `[Errno 61] Connection refused` — el robot puede medir eso, no "
     "arreglarlo. Es la tarea 2 de la lista de persona usuaria (§5.2)"),
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

#: LO QUE LA MÁQUINA TIENE QUE TENER, sacado del belt y no escrito acá. La ruta exacta sale
#: del `requiere_app` de la receta: copiarla a mano acá haría que el día que el belt exija
#: otra versión de FreeCAD este arnés siguiera mirando la vieja y diera verde.
BELT_DESCARGA = "catalog/templates/ingenieria/belt-ingenieria.mcp.json"


def _requiere_app(ejemplar: str) -> str:
    import json
    try:
        d = json.loads((ROOT / BELT_DESCARGA).read_text(encoding="utf-8"))
        return (d.get("mcpServers", {}).get(ejemplar, {}) or {}).get("requiere_app") or ""
    except Exception:                                                  # noqa: BLE001
        return ""


def _mirar_maquina(arn: Arnes, ejemplar: str):
    """La única sección que NO es replay: una grabación no sabe qué hay instalado acá."""
    print("\n1·bis · la app local (lo que el replay no puede saber)")
    exige = _requiere_app(ejemplar)
    arn.ok(bool(exige), "el belt declara qué app exige esta pieza",
           exige[:110] if exige else f"`requiere_app` vacío en {BELT_DESCARGA}")
    if not exige:
        return

    # Las rutas se LEEN del texto del belt, no se escriben acá.
    import re
    # ⚠️ El `~/…` de este belt TIENE UN ESPACIO (`Application Support`), así que un `\S+`
    # lo corta en «~/Library/Application» y reporta AUSENTE una carpeta que existe — un
    # rojo inventado, que es peor que no mirar. Se corta por `)` o `,` o fin de línea.
    rutas = re.findall(r"(/Applications/[^\s)]+|~/[^),]+)", exige)
    rutas = [r.strip() for r in rutas]
    presentes, ausentes = [], []
    for r in rutas:
        p = Path(r).expanduser()
        (presentes if p.exists() else ausentes).append(str(p))
    for p in presentes:
        arn.nota(f"presente: {p}")
    for p in ausentes:
        arn.nota(f"AUSENTE: {p} — tarea de persona usuaria (§5.2), no un defecto del código")
    arn.ok(bool(rutas), "el `requiere_app` nombra rutas verificables",
           f"{len(presentes)}/{len(rutas)} presentes" if rutas else
           "no se pudo extraer ninguna ruta del texto: eso sí es un defecto de la receta")


def _mirar_invoke(arn: Arnes, srv, llamadas):
    """Qué contestó de verdad la llamada grabada. NO asierta: reporta.

    Asertar «la respuesta es un error de conexión» congelaría el bug como si fuera el
    contrato — el día que persona usuaria abra FreeCAD, ese assert se pondría rojo por haber
    ARREGLADO algo. Y asertar lo contrario sería exigirle a un test que persona usuaria esté
    presente. Un dato que ninguna de las dos direcciones puede asertar honestamente se
    REPORTA, y el veredicto del verbo lo lleva la tabla (DE_USUARIO)."""
    for g in llamadas:
        txt = str(g.get("respuesta"))
        nombre = g["peticion"]["args"].get("name")
        roto = "Connection refused" in txt or "Errno 61" in txt
        arn.nota(f"invoke `{nombre}` → " +
                 ("la app local NO estaba viva cuando se grabó (`Connection refused`)"
                  if roto else f"respondió: {txt[:90]}"))


def main() -> int:
    a = parser(EJEMPLAR_DEFECTO).parse_args()
    arn = Arnes(TIPO, a.ejemplar, VERBOS)
    print(f"══ ARNÉS DEL TIPO «{TIPO}» · ejemplar: {arn.ejemplar} ══\n")

    grab = arn.grabacion()
    meta = grab["meta"]
    print(f"  grabación: {meta['grabado_en']} · huella {meta['huella_receta']} · "
          f"env_declarado={meta['env_declarado']}")

    arn.reparto()
    arn.replay(grab, tool_extra=_mirar_invoke)
    _mirar_maquina(arn, arn.ejemplar)
    arn.calibracion_roja()
    arn.ejemplar_es_parametro(__file__, EJEMPLAR_DEFECTO)
    return arn.cerrar()


if __name__ == "__main__":
    sys.exit(main())
