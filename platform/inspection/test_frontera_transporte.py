"""test_frontera_transporte.py — EL CLIENTE VIEJO YA NO ES ALCANZABLE.

Sesión 3 del SDK. El código viejo **no se borró** —es el rollback de un click hasta que la
certificación en la `.app` pase— pero dejó de ser un camino: nadie lo construye salvo el
switch, y el switch sólo lo devuelve con `ALEPH_TRANSPORTE=viejo`.

Esto es un grep congelado en un test, y esa es la diferencia: un grep se corre una vez y
miente al día siguiente. Lo que se fija:

  1. **UN SOLO switch.** `inspection/transporte.py` es el único lugar donde se decide quién
     habla MCP.
  2. **Cero consumidores directos** del cliente viejo fuera de él, con una allowlist
     EXPLÍCITA de los fallbacks declarados. Agregar uno nuevo obliga a tocar esta lista, o
     sea a tomar la decisión a la vista.
  3. **Los encabezados LEGACY están puestos** en los dos módulos viejos.
  4. La perilla existe y sus tres valores hacen lo que dicen.

    python3 -m pytest platform/inspection/test_frontera_transporte.py -q
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
if str(_RAIZ / "platform") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "platform"))

#: Los dos módulos que DEFINEN el cliente viejo, más el switch que los devuelve.
_LEGACY_Y_SWITCH = {
    "platform/assembler/assembler.py",
    "platform/inspection/mcp_http_client.py",
    "platform/inspection/transporte.py",
}

#: Lo que NO es código de producto: varas, tests, fixtures y demos. Se excluyen porque
#: probar el cliente viejo ES su trabajo — `verify_lado_a_lado_http.py` no podría comparar
#: los dos transportes si tuviera prohibido nombrar uno.
_NO_ES_PRODUCTO = ("test_", "tests_", "verify_", "selftest_", "smoke_", "demo_",
                   "fixtures/", "/tests/", "/.venv/", "node_modules", ".claude/")

#: LOS FALLBACKS DECLARADOS. Cada uno es un `_servidor_stdio()` que cae al cliente viejo
#: cuando el selector no se puede cargar (árbol incompleto, build raro). Ahí el fallback ES
#: el comportamiento conocido, no una degradación muda. Cualquier entrada NUEVA acá es una
#: decisión, no un descuido: por eso la lista es explícita y no un patrón.
_FALLBACKS_DECLARADOS = {
    "platform/assembler/recipe_assembler.py": "_servidor_stdio() del runtime de runs",
    "platform/assembler/session.py": "_servidor_stdio() de la Sesión VIVA",
    "platform/assembler/run_once.py": "_servidor_stdio() del runner de CLI",
}

#: Linaje APARTE: `product/belts/client/mcp_client.py` define su PROPIA clase `MCPServer`
#: para el lado del belt. No es la del assembler y no habla por nuestro transporte.
_OTRO_LINAJE = {"product/belts/client/mcp_client.py"}

_PATRON = re.compile(
    r"\bMCPServer\s*\(|\bMCPHttpClient\s*\(|\bimport\s+MCPServer\b|\bimport\s+MCPHttpClient\b"
    r"|\bMCPHttpError\b|\.MCPServer\b")


def _lineas_de_docstring(arbol: ast.AST) -> set:
    """Las líneas que son prosa, para no confundir una explicación con un uso."""
    fuera: set = set()
    for nodo in ast.walk(arbol):
        cuerpo = getattr(nodo, "body", None)
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                and cuerpo and isinstance(cuerpo[0], ast.Expr) \
                and isinstance(cuerpo[0].value, ast.Constant) \
                and isinstance(cuerpo[0].value.value, str):
            fuera.update(range(cuerpo[0].lineno, cuerpo[0].end_lineno + 1))
    return fuera


def _archivos_de_producto():
    for p in sorted(_RAIZ.rglob("*.py")):
        rel = str(p.relative_to(_RAIZ))
        if not rel.startswith(("platform/", "product/", "qa/", "catalog/", "deploy/", "eval/")):
            continue
        if any(x in rel for x in _NO_ES_PRODUCTO):
            continue
        if rel in _LEGACY_Y_SWITCH or rel in _OTRO_LINAJE:
            continue
        yield rel, p


def _usos_directos():
    """`[(archivo, linea, texto)]` de todo uso del cliente viejo en código de producto."""
    hallados = []
    for rel, p in _archivos_de_producto():
        try:
            fuente = p.read_text(errors="replace")
            prosa = _lineas_de_docstring(ast.parse(fuente))
        except SyntaxError:                                # pragma: no cover
            continue
        for i, linea in enumerate(fuente.splitlines(), 1):
            if i in prosa or linea.strip().startswith("#"):
                continue
            if _PATRON.search(linea):
                hallados.append((rel, i, linea.strip()))
    return hallados


# ══════════════════════════════════════════════════════════════════════════════════

def test_ningun_consumidor_de_producto_usa_el_cliente_viejo_directo():
    """EL GREP DE LA OBRA 1, congelado.

    Todo uso que quede tiene que estar en la allowlist de fallbacks declarados. Si aparece
    uno nuevo, este test lo nombra con archivo y línea — que es exactamente lo que un grep
    hecho a mano una vez no vuelve a hacer nunca."""
    intrusos = [(a, n, t) for a, n, t in _usos_directos() if a not in _FALLBACKS_DECLARADOS]
    assert not intrusos, (
        "consumidores del cliente viejo fuera del switch:\n  " +
        "\n  ".join(f"{a}:{n}: {t}" for a, n, t in intrusos) +
        "\n\nUsá `inspection.transporte` (servidor_stdio / cliente_http / error_http). "
        "Si de verdad hace falta un fallback nuevo, agregalo a _FALLBACKS_DECLARADOS con "
        "su motivo — y que se vea en el diff.")


def test_los_fallbacks_declarados_siguen_siendo_fallbacks():
    """No alcanza con estar en la lista: cada uno tiene que devolver el cliente viejo SÓLO
    dentro de su `_servidor_stdio()`, y ese helper tiene que consultar al selector."""
    for rel in _FALLBACKS_DECLARADOS:
        fuente = (_RAIZ / rel).read_text()
        # Se busca el `def` sin atarse a la FIRMA: `recipe_assembler` le agregó un `user_id`
        # en D4 y este guard se puso rojo por eso, no porque el fallback hubiera cambiado.
        # Un guard que se rompe cuando le agregás un parámetro a la función que vigila
        # enseña a ignorarlo.
        assert "def _servidor_stdio(" in fuente, f"{rel}: el helper del fallback no existe"
        assert "transporte.py" in fuente, (
            f"{rel}: el fallback no consulta al selector — entonces no es un fallback, "
            f"es el camino")


#: Un módulo que LEE la perilla, no uno que la nombre en un comentario. La diferencia
#: importa: media docena de archivos la explican, y explicarla es lo contrario de decidir
#: por su cuenta.
_LEE_LA_PERILLA = re.compile(r"(?:environ|getenv)[^\n]*ALEPH_TRANSPORTE")


def test_el_switch_vive_en_un_solo_lugar():
    """`ALEPH_TRANSPORTE` sólo se LEE en el selector. Si otro módulo la leyera, la decisión
    quedaría regada y dos partes del producto podrían elegir distinto en la misma corrida —
    que es exactamente el «dos verdades» que este árbol viene cerrando en todos lados."""
    lectores = [rel for rel, p in _archivos_de_producto()
                if _LEE_LA_PERILLA.search(p.read_text(errors="replace"))]
    assert lectores == [], (
        "leen ALEPH_TRANSPORTE fuera de inspection/transporte.py: " + ", ".join(lectores) +
        "\nLa perilla la lee el selector; los demás preguntan por `servidor_stdio()`.")


def test_los_modulos_viejos_estan_marcados():
    """El encabezado no es decoración: es lo que le dice al próximo que no agregue un
    consumidor, y lo que fija que el borrado es post-certificación."""
    for rel in ("platform/assembler/assembler.py", "platform/inspection/mcp_http_client.py"):
        cabeza = (_RAIZ / rel).read_text()[:4000]
        assert "LEGACY" in cabeza, f"{rel}: falta la marca LEGACY"
        assert "POST-CERTIFICACIÓN" in cabeza.upper(), f"{rel}: no dice cuándo se retira"
        assert "NO AGREGAR CONSUMIDORES" in cabeza.upper(), f"{rel}: no lo prohíbe"


def test_la_perilla_hace_lo_que_dice():
    """Los tres valores, y el que importa: `viejo` devuelve el cliente viejo AUNQUE el SDK
    esté. Sin eso el rollback no existiría."""
    from inspection import transporte as TP
    import os
    previo = os.environ.get("ALEPH_TRANSPORTE")
    try:
        os.environ["ALEPH_TRANSPORTE"] = "viejo"
        assert TP.modo() == TP.VIEJO
        assert TP.elegido()["transporte"] == "legacy"
        assert TP.servidor_stdio().__name__ == "MCPServer"

        os.environ.pop("ALEPH_TRANSPORTE", None)
        assert TP.modo() == TP.AUTO
        hay, _ = TP._hay_sdk()
        assert TP.elegido()["transporte"] == ("sdk" if hay else "legacy")

        os.environ["ALEPH_TRANSPORTE"] = "sdk"
        assert TP.modo() == TP.SDK
        if not hay:
            # FALLO VISIBLE: exigir el SDK sin SDK revienta, no degrada callado.
            with pytest.raises(RuntimeError, match="no está disponible"):
                TP.servidor_stdio()
        else:
            assert TP.servidor_stdio().__name__ == "ServidorSDK"

        os.environ["ALEPH_TRANSPORTE"] = "cualquier-cosa"
        assert TP.modo() == TP.AUTO, "un valor inválido cae a `auto`, no a un modo inventado"
    finally:
        if previo is None:
            os.environ.pop("ALEPH_TRANSPORTE", None)
        else:
            os.environ["ALEPH_TRANSPORTE"] = previo


# ══════════════════════════════════════════════════════════════════════════════════
# EL DUEÑO (D1) · su perilla también vive en UN solo lugar
# ══════════════════════════════════════════════════════════════════════════════════
_LEE_LA_PERILLA_DUENO = re.compile(r"(?:environ|getenv)[^\n]*ALEPH_DUENO\b")


def test_la_perilla_del_dueno_tambien_vive_en_un_solo_lugar():
    """Mismo invariante que `ALEPH_TRANSPORTE`, y por el mismo motivo: dos módulos que
    lean la perilla por su cuenta pueden elegir distinto en la misma corrida."""
    lectores = [rel for rel, p in _archivos_de_producto()
                if rel != "platform/inspection/dueno.py"
                and _LEE_LA_PERILLA_DUENO.search(p.read_text(errors="replace"))]
    assert lectores == [], (
        "la perilla del dueño se lee fuera de `dueno.py`: " + ", ".join(lectores) +
        "\nLos demás preguntan por `dueno.encendido()`.")
    # …y el dueño sí la declara: si la constante desapareciera, el test de arriba daría
    # verde por vacío — la trampa clásica de un guard que sólo mira lo que NO tiene que estar.
    fuente = (_RAIZ / "platform/inspection/dueno.py").read_text()
    assert '"ALEPH_DUENO"' in fuente, "`dueno.py` dejó de declarar su propia perilla"


# ══════════════════════════════════════════════════════════════════════════════════
# EL GRABADOR (S1 de la suite) · sus DOS perillas, con el mismo molde
# ══════════════════════════════════════════════════════════════════════════════════
_LEE_LAS_PERILLAS_GRABADOR = re.compile(
    r"(?:environ|getenv)[^\n]*ALEPH_(?:GRABAR|REPLAY)\b")


def test_las_perillas_del_grabador_tambien_viven_en_un_solo_lugar():
    """Mismo invariante que `ALEPH_TRANSPORTE` y `ALEPH_DUENO`, y por el mismo motivo: dos
    módulos que lean la perilla por su cuenta pueden elegir distinto en la misma corrida —
    uno grabando y el otro no— y la grabación saldría a medias sin que nadie se entere."""
    lectores = [rel for rel, p in _archivos_de_producto()
                if rel != "platform/inspection/grabador.py"
                and _LEE_LAS_PERILLAS_GRABADOR.search(p.read_text(errors="replace"))]
    assert lectores == [], (
        "leen ALEPH_GRABAR/ALEPH_REPLAY fuera de `grabador.py`: " + ", ".join(lectores) +
        "\nLos demás preguntan por `grabador.grabando()` / `grabador.replayando()`.")
    # …y el grabador SÍ las declara: si las constantes desaparecieran, el test de arriba
    # daría verde por vacío — la trampa clásica del guard que sólo mira lo que NO tiene que
    # estar (la misma que ya se anotó para `ALEPH_DUENO`).
    fuente = (_RAIZ / "platform/inspection/grabador.py").read_text()
    for perilla in ('"ALEPH_GRABAR"', '"ALEPH_REPLAY"'):
        assert perilla in fuente, f"`grabador.py` dejó de declarar {perilla}"


def test_sin_perilla_el_grabador_no_existe_para_el_producto():
    """El default tiene que ser la clase REAL, con su nombre y su identidad.

    Si `envolver()` devolviera un envoltorio siempre, cada spawn del producto pasaría por
    código de instrumentación que nadie pidió — y `elegido()`/la evidencia dejarían de poder
    nombrar el transporte que se usó."""
    import importlib
    import os as _os
    import sys as _sys
    _sys.path.insert(0, str(_RAIZ / "platform/inspection"))
    g = importlib.import_module("grabador")
    previos = {k: _os.environ.pop(k, None) for k in ("ALEPH_GRABAR", "ALEPH_REPLAY")}
    try:
        class _Falsa:
            pass
        assert g.envolver(_Falsa) is _Falsa, (
            "sin perilla, `envolver()` tiene que devolver la MISMA clase, no una copia")
        assert g.grabando() is None and g.replayando() is None
    finally:
        for k, v in previos.items():
            if v is not None:
                _os.environ[k] = v


def test_el_grabador_no_le_pide_la_clase_al_transporte():
    """ENVOLVER NO ES SPAWNEAR, y la diferencia la vigila `test_frontera_dueno.py`.

    `grabador.py` recibe la clase en `envolver(cls)`; si en cambio llamara a
    `servidor_stdio()`, sería un sitio de spawn nuevo —uno que el tope no cuenta y
    `apagar_todo()` no barre— y tendría que declararse en `_SITIOS`. Este test lo fija acá
    para que el motivo quede escrito donde se lee, no sólo como un rojo en el otro archivo."""
    fuente = (_RAIZ / "platform/inspection/grabador.py").read_text()
    llamadas = {
        n.func.attr for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "servidor_stdio" not in llamadas, (
        "`grabador.py` le pide la clase al transporte: dejó de ser un envoltorio y pasó a "
        "ser un sitio de spawn. Declaralo en `test_frontera_dueno._SITIOS` o volvé a "
        "recibir la clase por parámetro.")


def test_el_dueno_no_spawnea_por_fuera_del_transporte():
    """El dueño POSEE los procesos, pero no elige el transporte: eso sigue siendo de
    `transporte.py`. Si `dueno.py` construyera un cliente directo, habría dos lugares
    decidiendo con qué se habla MCP."""
    fuente = (_RAIZ / "platform/inspection/dueno.py").read_text()
    assert "servidor_stdio()" in fuente, "el dueño tiene que pedirle la clase al selector"
    # ⚠️ SOBRE EL CÓDIGO, NO SOBRE LA PROSA. Esto era un `"MCPServer" not in fuente` y se
    # rompió el día que un docstring del dueño explicó que su adaptador tiene «la forma de
    # MCPServer» — una frase, no una construcción. Un substring no distingue las dos cosas y
    # convierte en rojo a quien DOCUMENTA la frontera. El AST sólo ve código: si alguna vez
    # el dueño NOMBRA una clase de transporte concreta para instanciarla, esto la caza; si
    # sólo la menciona para explicarse, no. (Es la misma lección que
    # `verify_env_declarado.py` pagó con las lecturas indirectas de env.)
    nombres = {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, (ast.Name, ast.Attribute))
    }
    concretas = nombres & {"MCPServer", "ClienteSdkHttp", "ServidorSDK"}
    assert not concretas, (
        f"el dueño nombra una clase de transporte concreta EN CÓDIGO: {sorted(concretas)}. "
        f"Quién habla MCP lo decide `transporte.py` y nadie más.")


def test_las_constantes_del_ciclo_de_vida_son_las_del_diseno():
    """Las tres que deciden el ciclo de vida de TODO el producto. Cambiarlas de costado
    —sin una medición y sin la vara— es cambiarle la memoria y la latencia a cada usuario,
    así que se fijan acá con el valor que el diseño sostiene (§1.2 y §4.1).

    Si una sesión futura las mueve, que sea rompiendo este test a propósito."""
    import importlib
    import sys as _sys
    _sys.path.insert(0, str(_RAIZ / "platform/inspection"))
    d = importlib.import_module("dueno")
    assert d.OCIOSIDAD_S == 600, (
        f"OCIOSIDAD_S = {d.OCIOSIDAD_S}: el diseño §1.2 la fija en 600 s, declarada como "
        f"apuesta y configurable por `ALEPH_DUENO_OCIOSIDAD_S`.")
    assert d.MAX_VIVAS == 8, (
        f"MAX_VIVAS = {d.MAX_VIVAS}: el diseño §4.1 la fija en 8 (≈0,9 GB con los 113 MB "
        f"por conexión medidos).")
    assert d.RETENCION_S == d.OCIOSIDAD_S, "el alias histórico se separó de su fuente"


def test_la_perilla_sigue_apagada_por_default():
    """El dueño sostiene procesos: encenderlo es una decisión, no un default silencioso.
    Mientras `ALEPH_DUENO` no esté, cada consumidor spawnea como siempre."""
    import importlib
    import os as _os
    import sys as _sys
    _sys.path.insert(0, str(_RAIZ / "platform/inspection"))
    d = importlib.import_module("dueno")
    previo = _os.environ.pop("ALEPH_DUENO", None)
    try:
        assert d.encendido() is False
    finally:
        if previo is not None:
            _os.environ["ALEPH_DUENO"] = previo
