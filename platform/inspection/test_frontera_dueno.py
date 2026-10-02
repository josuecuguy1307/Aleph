"""test_frontera_dueno.py — TODOS LOS CONSUMIDORES PASAN POR EL DUEÑO.

D5, el cierre de la migración del §7. Con los cinco consumidores migrados, lo que hay que
proteger ya no es construir el dueño: es que **nadie spawnee por fuera de él**. Un solo
`_servidor_stdio()` que no le pregunte al dueño alcanza para reabrir el agujero que costó
9 GB — porque un proceso levantado a mano no está en la tabla, no lo cuenta el tope, no lo
barre `apagar_todo()` y no lo mata la lápida.

Es el mismo molde que `test_frontera_transporte.py`, por la misma razón: **un grep se corre
una vez y miente al día siguiente**. Congelado en un test, agregar un sitio de spawn nuevo
obliga a tocar esta lista — o sea, a tomar la decisión a la vista.

Lo que se fija:
  1. los CINCO consumidores existen y cada uno llega al dueño;
  2. **cero fábricas de servers** en código de producto fuera de la allowlist explícita;
  3. toda fábrica declarada consulta la perilla ANTES de caer al transporte;
  4. el adaptador es UNO SOLO y vive en el dueño;
  5. la lápida del producto apaga procesos, no sólo el permiso.

    python3 -m pytest platform/inspection/test_frontera_dueno.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
if str(_RAIZ / "platform") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "platform"))

#: LOS CINCO CONSUMIDORES del §7, con el archivo:símbolo que los ata al dueño. La sonda del
#: verificador y el calentador son EL MISMO camino (`calentar_cinturon` llama a
#: `verificar_uno`, que llama a `_spawn`): se listan aparte porque son dos consumidores del
#: diseño, no dos spawns.
_CONSUMIDORES = {
    "verificador":
        ("product/backend/app/phase1/conexiones_verificador.py", "DU.encendido()"),
    "calentador":
        ("product/backend/app/phase1/calentar_cinturon.py", "verificar_uno"),
    "run":
        ("platform/assembler/recipe_assembler.py", "DU.encendido()"),
    "sesión":
        ("platform/assembler/session.py", "DU.encendido()"),
    "lifespan":
        ("product/backend/app/main.py", "apagar_todo"),
}

#: EL INVENTARIO COMPLETO de sitios que le piden la clase al transporte (`servidor_stdio()`)
#: en código de producto. La llave es `archivo::función`; el valor es `(pasa_por_el_dueño,
#: motivo)`. No se detectan por NOMBRE de función —`conexiones_verificador` no tiene ninguna
#: `_servidor_stdio`, pide la clase en línea dentro de `_spawn`— sino por lo que hacen.
_SITIOS = {
    # ── LOS QUE SOSTIENEN: pasan por el dueño ────────────────────────────────────────
    "product/backend/app/phase1/conexiones_verificador.py::_spawn":
        (True, "la sonda del verificador Y el calentador (D3): `calentar_cinturon` llama a "
               "`verificar_uno`, que llama acá. Son dos consumidores del §7, un solo spawn."),
    "platform/assembler/recipe_assembler.py::_servidor_stdio":
        (True, "el pool del run (D4)"),
    "platform/assembler/session.py::_servidor_stdio":
        (True, "la Sesión VIVA (D5)"),

    # ── EL DUEÑO MISMO ───────────────────────────────────────────────────────────────
    "platform/inspection/dueno.py::_cls":
        (True, "el dueño pidiéndole la clase al selector — es el que spawnea de verdad. "
               "Que NO elija transporte propio lo fija `test_frontera_transporte.py`."),

    # ── MEDIR-Y-CERRAR y CLI: NO pasan por el dueño, y acá está por qué ──────────────
    # ⚠️ Ninguno SOSTIENE: abren, preguntan y cierran en el mismo aliento, o viven en un
    # proceso de CLI que se muere entero al terminar. Por eso no dejan un huérfano que
    # sobreviva a nadie, y por eso no urgía migrarlos. Pero mientras estén en `False` son
    # caminos que el tope, la lápida y `apagar_todo()` NO ven: si uno se olvida un `stop()`,
    # nadie lo barre. El día que alguno pase a sostener, migrarlo deja de ser opcional.
    "platform/inspection/byo_mcp.py::probe_mcp":
        (False, "sonda del BYO-MCP que pega el usuario: mide y cierra, como el verificador "
                "antes de D3"),
    "platform/inspection/dispatch/liveness.py::_call_stdio":
        (False, "sonda de liveness: arranca, pregunta, cierra"),
    "platform/inspection/inspect_run.py::_load_mcpserver_cls":
        (False, "runner de CLI para inspeccionar una tool con el cliente de producción"),
    "platform/assembler/run_once.py::_servidor_stdio":
        (False, "runner de CLI: un proceso por invocación, se muere entero al terminar"),
}

#: Las que además tienen que consultar la perilla ANTES de caer al transporte.
_MIGRADOS = sorted(k for k, (v, _m) in _SITIOS.items() if v)

#: No es código de producto: varas, tests, fixtures y demos pueden construir lo que quieran
#: —probar el camino sin dueño ES su trabajo—.
_NO_ES_PRODUCTO = ("test_", "tests_", "verify_", "selftest_", "smoke_", "demo_",
                   "fixtures/", "/tests/", "/.venv/", "node_modules", ".claude/")


def _es_producto(p: Path) -> bool:
    s = str(p.relative_to(_RAIZ))
    return not any(x in s for x in _NO_ES_PRODUCTO)


def _fuentes_de_producto():
    for p in sorted(_RAIZ.rglob("*.py")):
        s = str(p)
        if "/.venv/" in s or "node_modules" in s:
            continue
        if not (s.startswith(str(_RAIZ / "platform")) or
                s.startswith(str(_RAIZ / "product/backend"))):
            continue
        if _es_producto(p):
            yield p


@pytest.mark.parametrize("consumidor", sorted(_CONSUMIDORES))
def test_cada_consumidor_llega_al_dueno(consumidor):
    """Los CINCO del §7. Si uno deja de nombrar su ancla, o se migró mal o se desmigró."""
    ruta, ancla = _CONSUMIDORES[consumidor]
    f = _RAIZ / ruta
    assert f.exists(), f"{consumidor}: {ruta} no existe"
    assert ancla in f.read_text(encoding="utf-8"), (
        f"«{consumidor}» ({ruta}) ya no contiene {ancla!r}: o dejó de pasar por el dueño, "
        f"o el ancla cambió de nombre y esta frontera quedó mirando al vacío.")


def _sitios_reales() -> dict:
    """`{archivo::función: nodo}` de TODA función de producto que le pide la clase al
    transporte. Es el inventario medido, contra el que se compara la lista declarada."""
    fuera = {}
    for p in _fuentes_de_producto():
        try:
            arbol = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = str(p.relative_to(_RAIZ))
        for fn in [n for n in ast.walk(arbol)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "servidor_stdio" for n in ast.walk(fn)):
                fuera[f"{rel}::{fn.name}"] = fn
    return fuera


def test_no_hay_sitios_de_spawn_sin_declarar():
    """CERO sitios que pidan la clase al transporte fuera del inventario.

    Es el corazón de la frontera: cada sitio es un lugar donde puede nacer un proceso MCP.
    Mientras estén todos listados se sabe cuáles ve el dueño y cuáles no; uno sin declarar es
    un proceso que el tope no cuenta, `apagar_todo()` no barre y la lápida no mata."""
    reales = set(_sitios_reales())
    nuevos = reales - set(_SITIOS)
    assert not nuevos, (
        f"sitio(s) de spawn sin declarar: {sorted(nuevos)}. Agregalos a `_SITIOS` con "
        f"`(True, motivo)` si pasan por el dueño o `(False, motivo)` si no — y en ese caso "
        f"el motivo tiene que decir por qué está bien que el dueño no los vea.")
    faltan = set(_SITIOS) - reales
    assert not faltan, (
        f"declarados pero ya no existen: {sorted(faltan)}. Sacalos de `_SITIOS` para que la "
        f"lista siga siendo el inventario y no una lista de deseos.")


def test_todo_sitio_declarado_tiene_motivo_escrito():
    """Un `False` sin motivo es un olvido disfrazado de decisión."""
    sin_motivo = [k for k, (_v, m) in _SITIOS.items() if not (m or "").strip()]
    assert not sin_motivo, f"sitios sin motivo escrito: {sin_motivo}"


@pytest.mark.parametrize("sitio", _MIGRADOS)
def test_el_sitio_migrado_pregunta_por_la_perilla_antes_del_transporte(sitio):
    """Un sitio migrado tiene que consultar `encendido()` **antes** de pedir la clase del
    transporte. Si el orden se invirtiera, la perilla no haría nada: el transporte ganaría
    siempre y el dueño no vería un solo proceso."""
    if sitio.startswith("platform/inspection/dueno.py"):
        pytest.skip("el dueño ES el dueño: no se pregunta a sí mismo si está encendido")
    fn = _sitios_reales().get(sitio)
    assert fn is not None, f"{sitio} desapareció"
    linea_perilla = min(
        (n.lineno for n in ast.walk(fn)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "encendido"), default=None)
    linea_transporte = min(
        (n.lineno for n in ast.walk(fn)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "servidor_stdio"), default=None)
    assert linea_perilla is not None, f"{sitio}: no consulta `encendido()`"
    assert linea_transporte is not None, f"{sitio}: no llama al transporte"
    assert linea_perilla < linea_transporte, (
        f"{sitio}: la perilla se consulta en la línea {linea_perilla}, DESPUÉS del transporte "
        f"({linea_transporte}). Con ese orden `ALEPH_DUENO=on` no hace nada.")


def test_el_adaptador_del_prestamo_es_UNO_SOLO_y_vive_en_el_dueno():
    """`ServidorPrestado` es el puente préstamo→forma-de-MCPServer. Vivía en
    `recipe_assembler` mientras el run era su único consumidor; con dos (run y Sesión) una
    copia se desincroniza en silencio — y una de sus reglas (el `call_tool` que NO deja
    escapar la excepción de la lápida) costó una vara descubrirla."""
    assert "class ServidorPrestado" in (
        _RAIZ / "platform/inspection/dueno.py").read_text(encoding="utf-8"), (
        "el adaptador ya no vive en `dueno.py`")
    definiciones = []
    for p in _fuentes_de_producto():
        try:
            arbol = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ClassDef) and nodo.name in (
                    "ServidorPrestado", "_ServidorDelDueno"):
                definiciones.append(str(p.relative_to(_RAIZ)))
    assert definiciones == ["platform/inspection/dueno.py"], (
        f"el adaptador está definido en {definiciones}: tiene que haber UNO y en el dueño.")


def test_la_lapida_apaga_procesos_y_no_solo_el_permiso():
    """`desconectar()` marca `habilitado=false` y nada más — es la capa de la tabla. Quien
    tiene que matar el proceso es la acción de producto. Desde que el dueño SOSTIENE, una
    lápida que sólo escribe en la DB deja andando un server con la credencial adentro."""
    fuente = (_RAIZ / "product/backend/app/phase1/centro_conexiones.py").read_text(
        encoding="utf-8")
    assert "apagar_entidad" in fuente, (
        "la lápida del centro de conexiones no llama a `apagar_entidad`: desconectar volvió "
        "a ser sólo un permiso, y el proceso queda vivo hasta que venza la ociosidad.")


def test_el_dueno_manda_por_encima_del_refcount_en_la_lapida():
    """La lápida no puede esperar a que otro suelte. Es §1.1 del diseño y la razón de que
    `apagar_entidad` exista aparte de `soltar`."""
    fuente = (_RAIZ / "platform/inspection/dueno.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    fn = next((n for n in ast.walk(arbol)
               if isinstance(n, ast.FunctionDef) and n.name == "apagar_entidad"), None)
    assert fn is not None, "`apagar_entidad` desapareció del dueño"
    cuerpo = ast.get_source_segment(fuente, fn) or ""
    assert "refcount" not in cuerpo, (
        "`apagar_entidad` mira el refcount: la lápida dejó de mandar por encima de los "
        "préstamos y un usuario que desconecta queda esperando a que otro agente suelte.")
