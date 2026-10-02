#!/usr/bin/env python3
"""verify_nombres_suite.py — LA LEY DE NOMBRES DE LA SUITE. Vara PERMANENTE y bloqueante.

**Las varas del arnés se nombran por TIPO DE CONEXIÓN, jamás por servicio.** El conector
concreto es un parámetro del arnés —un ejemplar, un fixture— nunca parte del nombre del
archivo.

    qa/verify_oauth.py         ← todo OAuth          (hoy lo encarna onshape)
    qa/verify_llave_stdio.py   ← todo llave + stdio  (hoy fred)
    qa/verify_http.py          ← todo HTTP           (hoy exa)
    qa/verify_descarga.py      ← todo Descarga       (hoy freecad)

**LOS CUATRO SON PERMANENTES: son arquitectura, no una lista de tareas.** Cada conector que
exista o que llegue cae en uno de los cuatro, y su tipo siempre está ahí para probarlo. Lo
único que rota son los EJEMPLARES —hoy onshape encarna OAuth, mañana puede encarnarlo otro—
y los fixtures que se suman cuando un bug real enseña un caso nuevo.

POR QUÉ ES UNA LEY Y NO UNA PREFERENCIA. Un archivo por servicio parece inocente y hace dos
daños. El primero: **el arnés se fragmenta**, y lo que se prueba deja de ser «el camino
OAuth» para ser «lo que se le ocurrió probar a quien tocó onshape». El segundo, peor: cuando
llega el conector 29, **nadie sabe qué se le tiene que exigir**, porque el contrato del tipo
no está escrito en ningún lado — está repartido en N archivos que se parecen. Con un arnés
por tipo, sumar un conector es sumar un ejemplar, y lo que se le exige ya está decidido.

Y un corolario que también se vigila: **un bug de un conector concreto va como CASO del
arnés de su tipo, jamás como archivo propio.** Un bug es evidencia de que al tipo le faltaba
un caso; archivarlo aparte lo esconde del próximo conector que lo va a sufrir igual.

    product/backend/.venv/bin/python qa/verify_nombres_suite.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: LOS CUATRO ARNESES. Viven para siempre; se listan acá para que un renombre se vea en el
#: diff en vez de pasar como «un archivo que se movió».
ARNESES = {
    "oauth": "qa/verify_oauth.py",
    "llave_stdio": "qa/verify_llave_stdio.py",
    "http": "qa/verify_http.py",
    "descarga": "qa/verify_descarga.py",
}

#: QUIÉN ENCARNA CADA TIPO HOY. Esto SÍ rota, y por eso está en su propia tabla: cambiar un
#: ejemplar es una línea, no una refactorización. Cada uno tiene que existir en el catálogo.
EJEMPLARES = {
    "oauth": "onshape",
    "llave_stdio": "fred",
    "http": "exa",
    "descarga": "freecad",
}

#: LOS TRANSITORIOS, con su arnés destino. Cada entrada es una deuda con fecha de
#: vencimiento automática: en cuanto el arnés destino EXISTE, el transitorio tiene que haber
#: desaparecido y esta vara se pone roja hasta que se borre. Una excepción sin vencimiento
#: es una excepción para siempre.
#:
#: ✅ **VACÍA DESDE S3, Y ESO ES EL PUNTO.** Los dos que había vencieron el día que nació su
#: arnés (`qa/verify_oauth.py`) y se absorbieron como CASOS suyos:
#:
#:     qa/verify_onshape_oauth.py        → qa/lib/casos_oauth.py        (CASO A)
#:     qa/verify_onshape_lectura_real.py → qa/lib/caso_lectura_real.py  (CASO B)
#:
#: Los dos módulos siguen nombrados por CASO, no por servicio, y no son varas: no se corren
#: solos, no tienen veredicto propio, y su única entrada es `verify_oauth.py`. Un tipo, un
#: arnés, un verde. Dejar el dict vacío en vez de borrarlo es a propósito: el mecanismo de
#: vencimiento sigue armado para el próximo que haga falta.
TRANSITORIOS: dict = {}

FALLOS: list = []


def ok(cond, etiqueta, detalle=""):
    print(("  ✅ " if cond else "  ❌ ") + etiqueta + (f"\n       {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(etiqueta)
    return cond


def _conectores() -> list:
    """Los nombres de servicio salen del CATÁLOGO, no de una lista escrita a mano.

    Escribirlos acá haría que el conector 29 entrara sin que nadie lo mirara — que es
    exactamente el agujero que esta vara existe para tapar.

    ⚠️ Y SON DOS FUENTES, no una. La primera versión miraba sólo las fichas de
    `connectors/onboarding/` y se puso roja diciendo que `freecad` «ya no existe» — cuando
    freecad existe perfectamente: es un servidor declarado en `belt-ingenieria.mcp.json`.
    Las piezas de tipo **Descarga** no tienen ficha de onboarding porque no piden credencial
    sino una app instalada, así que un universo hecho sólo de fichas deja afuera a un tipo
    entero. También significa que `verify_freecad.py` violaría la ley igual, y con la lista
    angosta no lo habría cazado."""
    nombres = set()
    d = ROOT / "catalog" / "connectors" / "onboarding"
    nombres.update(p.stem for p in d.glob("*.json"))
    for belt in (ROOT / "catalog").rglob("*.mcp.json"):
        try:
            nombres.update(json.loads(belt.read_text(encoding="utf-8"))
                           .get("mcpServers", {}).keys())
        except Exception:                                  # noqa: BLE001
            continue
    return sorted(n for n in nombres if n)


def _nombra_un_servicio(stem: str, conectores: list):
    """El nombre del conector como TOKEN del nombre de archivo, no como substring.

    Por token a propósito: `verify_exa.py` viola la ley y `verify_context7_algo.py` también,
    pero `verify_extractor.py` no tiene por qué morir porque «exa» esté adentro de otra
    palabra. Un guard que caza de más enseña a ignorarlo."""
    nombre = stem[len("verify_"):] if stem.startswith("verify_") else stem
    for c in conectores:
        if re.search(r"(^|_)" + re.escape(c) + r"($|_)", nombre):
            return c
    return None


def main() -> int:
    print("══ LEY DE NOMBRES DE LA SUITE ══\n")
    conectores = _conectores()
    print(f"  ({len(conectores)} conectores en el catálogo — la lista sale de ahí, no de acá)\n")

    # ── 1 · ningún archivo nombrado por servicio, salvo los transitorios declarados ─────
    print("1 · ninguna vara se llama como un servicio")
    intrusos = []
    for p in sorted((ROOT / "qa").glob("verify_*.py")):
        rel = str(p.relative_to(ROOT))
        c = _nombra_un_servicio(p.stem, conectores)
        if c and rel not in TRANSITORIOS:
            intrusos.append((rel, c))
    ok(not intrusos, "cero varas nombradas por servicio fuera de los transitorios",
       "" if not intrusos else
       "\n       ".join(
           f"{rel} nombra al conector «{c}» → su contenido va a "
           f"{ARNESES.get('oauth', '(el arnés de su tipo)')} como un CASO, no como archivo"
           for rel, c in intrusos))

    # ── 2 · cada transitorio declara un destino REAL ────────────────────────────────────
    print("\n2 · cada transitorio declara a qué arnés se absorbe")
    malos = [f for f, (tipo, _m) in TRANSITORIOS.items() if tipo not in ARNESES]
    ok(not malos, "todos apuntan a uno de los cuatro arneses", str(malos) if malos else "")
    sin_motivo = [f for f, (_t, m) in TRANSITORIOS.items() if not (m or "").strip()]
    ok(not sin_motivo, "y todos dicen qué contienen", str(sin_motivo) if sin_motivo else "")

    # ── 3 · la excepción VENCE SOLA ────────────────────────────────────────────────────
    print("\n3 · el transitorio desaparece cuando su arnés existe")
    vencidos = []
    for f, (tipo, _m) in TRANSITORIOS.items():
        destino = ROOT / ARNESES[tipo]
        if destino.exists() and (ROOT / f).exists():
            vencidos.append(f"{f} sigue vivo y {ARNESES[tipo]} YA EXISTE")
    ok(not vencidos, "ningún transitorio sobrevivió a su arnés",
       "\n       ".join(vencidos) + ("\n       Absorbelo como caso y borralo." if vencidos else ""))
    faltan_declarados = [f for f in TRANSITORIOS if not (ROOT / f).exists()]
    ok(not faltan_declarados,
       "la lista de transitorios es un inventario, no una lista de deseos",
       f"declarados y ya inexistentes: {faltan_declarados} — sacalos de TRANSITORIOS"
       if faltan_declarados else "")

    # ── 4 · los ejemplares existen en el catálogo ───────────────────────────────────────
    print("\n4 · cada tipo tiene un ejemplar que existe")
    huerfanos = [f"{t}→{e}" for t, e in EJEMPLARES.items() if e not in conectores]
    ok(not huerfanos, "los cuatro ejemplares están en el catálogo",
       f"ya no existen: {huerfanos} — rotá el ejemplar, el arnés no se toca"
       if huerfanos else f"{EJEMPLARES}")
    sin_ejemplar = [t for t in ARNESES if t not in EJEMPLARES]
    ok(not sin_ejemplar, "los cuatro tipos tienen quién los encarne",
       str(sin_ejemplar) if sin_ejemplar else "")

    # ── 5 · los arneses que ya existan están donde dicen ────────────────────────────────
    print("\n5 · los cuatro arneses, cuando existan, están en su ruta canónica")
    existentes = {t: r for t, r in ARNESES.items() if (ROOT / r).exists()}
    print(f"  · construidos hasta ahora: {sorted(existentes) or 'ninguno (los construye S2/S3)'}")
    # Un arnés con nombre parecido pero fuera de la tabla es un renombre sin decidir.
    sospechosos = [str(p.relative_to(ROOT)) for p in (ROOT / "qa").glob("verify_*.py")
                   if p.stem[len("verify_"):] in {t.replace("_", "") for t in ARNESES}
                   and str(p.relative_to(ROOT)) not in ARNESES.values()]
    ok(not sospechosos, "ningún arnés con un nombre inventado",
       str(sospechosos) if sospechosos else "")

    print("\n" + ("══ ✅ LA LEY DE NOMBRES SE CUMPLE ══" if not FALLOS
                  else f"══ ❌ {len(FALLOS)} VIOLACIÓN(ES): {FALLOS} ══"))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
