"""test_repair_boton.py — R4 · CADA PERMANENTE LLEGA CON SU BOTÓN, Y [FIJAR LA VERSIÓN].

Lo que se fija:

  1. **la tabla de la UI y la de repair no pueden separarse**: todo lo que
     `repair_clasificar` da por PERMANENTE tiene que estar en `CAUSAS_PERMANENTES` del
     semáforo, o la UI ofrecería [Reintentar] sobre algo que va a devolver el mismo rojo;
  2. cada causa permanente con botón llega con **su** botón, y ninguna con uno inventado;
  3. **[Fijar la versión]** en positivo y **en negativo**: sin versión conocida no propone
     nada, ya pineado no vuelve a proponer, y la versión que corre no se propone a sí misma;
  4. **sin confirmación no escribe**; y cuando escribe, es UPDATE a la fila del usuario —
     jamás al catálogo, jamás una fila nueva;
  5. la lápida gana: una entidad apagada no se repara.

    python3 -m pytest platform/inspection/test_repair_boton.py -q
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/inspection", _RAIZ / "platform/assembler",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import repair_clasificar as RC                              # noqa: E402
import repair_fijar_version as FV                           # noqa: E402

_SEMAFORO = _RAIZ / "product/app/design/cuarto/cuarto.semaforo.js"


def _js(expr: str):
    """Evalúa una expresión contra el semáforo REAL. Sin re-implementar la tabla en Python:
    dos copias de un diccionario causa→botón se separan, que es justo lo que esto vigila."""
    out = subprocess.run(
        ["node", "-e",
         f"import({json.dumps(str(_SEMAFORO))}).then(m=>{{"
         f"console.log(JSON.stringify((()=>{{const S=m;return {expr};}})()))}})"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LAS DOS TABLAS NO SE SEPARAN
# ══════════════════════════════════════════════════════════════════════════════════

def test_todo_permanente_de_repair_esta_en_CAUSAS_PERMANENTES_de_la_UI():
    """Si repair la da por permanente y la UI no, `caminoDe` ofrece [Reintentar] sobre algo
    que va a devolver el mismo rojo — y el usuario aprieta un botón que no puede funcionar.
    Es exactamente lo que pasaba con `cli_interactivo_colgado` antes de R4."""
    ui = set(_js("[...S.CAUSAS_PERMANENTES]"))
    faltan = []
    for causa in sorted(RC.CAUSAS_CUBIERTAS - RC.GRISES):
        if not RC.clasificar(causa).es_temporal and causa not in ui:
            faltan.append(causa)
    assert not faltan, (
        f"repair las da por PERMANENTES y la UI no: {faltan}. Agregalas a "
        f"`CAUSAS_PERMANENTES` en cuarto.semaforo.js o la UI ofrecerá un reintento imposible.")


def test_una_temporal_marcada_permanente_en_la_UI_conserva_un_camino_REAL():
    """La invariante NO es simétrica, y quererla simétrica era un error mío.

    Las dos listas responden preguntas distintas: la de repair es «¿repair reintenta solo?»
    y la de la UI es «¿tiene sentido ofrecerle al usuario un botón de reintentar?». Pueden
    diferir con razón — el caso medido es `sin_runtime`: repair sí reintenta (el runtime
    local puede levantar) y la UI, en vez de un [Reintentar] que no arregla nada, ofrece
    [Instalar el runtime], que es MEJOR.

    Lo que sí tiene que valer es que esa causa conserve un camino de verdad: si la UI la da
    por permanente y encima la deja sin botón, el usuario se queda mirando un rojo mientras
    repair reintenta por atrás sin que nadie lo sepa."""
    ui = set(_js("[...S.CAUSAS_PERMANENTES]"))
    sin_camino = []
    for c in sorted(RC.CAUSAS_CUBIERTAS - RC.GRISES):
        if not (RC.clasificar(c).es_temporal and c in ui):
            continue
        cam = _js(f"S.caminoDe({{estado:'roto',causa:{json.dumps(c)}}})")
        if cam.get("accion") == "ver_error":
            sin_camino.append(c)
    assert not sin_camino, (
        f"repair las reintenta, la UI las da por permanentes y encima no ofrece camino: "
        f"{sin_camino}")


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · CADA PERMANENTE, SU BOTÓN
# ══════════════════════════════════════════════════════════════════════════════════

#: causa → la acción que la tabla canónica tiene que devolver.
_ESPERADO = {
    "falta_key": "credencial", "key_invalida": "credencial", "sin_sesion": "login",
    "cli_no_instalado": "instalar", "cli_version_vieja": "instalar",
    "cli_sin_permisos": "centro", "plan_insuficiente": "premium",
    "sin_credito": "centro", "modelo_no_disponible": "centro",
    # LEY · LA CONFESIÓN ES INTERNA (2026-08-04). Era "reporte" → [Copiar el reporte]: le
    # anunciábamos una falla nuestra y encima le pedíamos que nos la reportara. El reporte
    # se sigue armando (`reporte_interno`), pero lo consume el [?], no el usuario.
    "falla_de_aleph": "no_disponible",
    # `servidor_incompatible` NO está: R5 lo sacó de los botones a propósito — la receta es
    # territorio de Aleph y repair la corrige solo. Ver `test_servidor_incompatible_*`.
}


@pytest.mark.parametrize("causa,accion", sorted(_ESPERADO.items()))
def test_cada_permanente_llega_con_su_boton(causa, accion):
    cam = _js(f"S.caminoDe({{estado:'roto',causa:{json.dumps(causa)}}})")
    assert cam and cam["accion"] == accion, f"{causa} → {cam}"
    assert cam.get("es"), "el botón tiene que tener rótulo"


def test_servidor_incompatible_NO_tiene_boton():
    """R5, sellado: **la receta es territorio de Aleph, no del usuario.** Repair vuelve solo
    a la última versión que anduvo; pedirle permiso al usuario para arreglar algo nuestro
    sería mandarle un trámite por un problema que no creó."""
    cam = _js("S.caminoDe({estado:'roto',causa:'servidor_incompatible'})")
    # La acción pasó de `ver_error` a `no_disponible`: [Ver error] llevaba a NUESTRA
    # evidencia, que para el usuario no es un camino sino una sala de espera con jerga. El
    # invariante que este test protege —que NO hay botón— sigue igual de vivo.
    assert cam["accion"] == "no_disponible" and cam.get("sin_boton") is True, cam
    assert "confirma" not in cam, "no hay botón que confirmar"


def test_servidor_incompatible_sigue_siendo_PERMANENTE():
    """Sin botón pero permanente: la UI no puede ofrecer un [Reintentar] que devolvería el
    mismo rojo. Cuando el usuario lo ve, el auto-ajuste ya falló."""
    assert "servidor_incompatible" in set(_js("[...S.CAUSAS_PERMANENTES]"))


def test_una_permanente_sin_boton_NO_se_marca_desconocida():
    """«sin botón» y «desconocida» son cosas distintas: la primera es una decisión, la
    segunda es una señal para quien mantiene el diccionario."""
    for causa in ("no_es_mcp", "sin_tools", "sin_tool_sondeable", "fallo_desconocido"):
        cam = _js(f"S.caminoDe({{estado:'roto',causa:{json.dumps(causa)}}})")
        assert cam["accion"] == "no_disponible", causa
        assert cam.get("sin_boton") is True, f"{causa}: {cam}"
        assert not cam.get("desconocida"), f"{causa} es conocida, no desconocida"


def test_una_causa_de_verdad_nueva_SI_se_marca_desconocida():
    cam = _js("S.caminoDe({estado:'roto',causa:'algo_que_nadie_vio'})")
    # `desconocida` sigue distinguiéndose de `sin_boton` —que es lo que este test cuida—
    # aunque las dos salgan hoy por la misma puerta visible.
    assert cam.get("desconocida") is True and cam["accion"] == "no_disponible"


def test_ninguna_permanente_ofrece_reintentar():
    for causa in sorted(RC.CAUSAS_CUBIERTAS - RC.GRISES):
        if RC.clasificar(causa).es_temporal:
            continue
        cam = _js(f"S.caminoDe({{estado:'roto',causa:{json.dumps(causa)}}})")
        assert cam["accion"] != "reintentar", f"{causa} es permanente y ofrece reintentar"


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · [FIJAR LA VERSIÓN] — POSITIVO
# ══════════════════════════════════════════════════════════════════════════════════

_FILA_NPX = {"entity_id": "coingecko", "command": "npx",
             "args": ["-y", "@coingecko/coingecko-mcp"]}
_FILA_UVX = {"entity_id": "pubmed", "command": "uvx", "args": ["mcp-simple-pubmed"]}


def test_propone_el_pin_npm():
    p = FV.proponer(_FILA_NPX, version_buena="1.4.0",
                    evidencia={"server_info": {"name": "cg", "version": "2.0.0"}})
    assert p.posible
    assert p.args_despues == ["-y", "@coingecko/coingecko-mcp@1.4.0"]
    assert p.version_corriendo == "2.0.0" and p.version_propuesta == "1.4.0"
    assert p.args_antes == _FILA_NPX["args"], "no muta los args del llamante"


def test_propone_el_pin_python():
    p = FV.proponer(_FILA_UVX, version_buena="0.3.1")
    assert p.posible and p.args_despues == ["mcp-simple-pubmed==0.3.1"]


def test_lee_la_version_del_saludo_mcp():
    assert FV.version_de({"server_info": {"version": "9.9.9"}}) == "9.9.9"
    assert FV.version_de({"version": "8.8.8"}) == "8.8.8"
    assert FV.version_de({"server_info": '{"version": "7.7.7"}'}) == "7.7.7"
    assert FV.version_de({}) is None and FV.version_de(None) is None


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · [FIJAR LA VERSIÓN] — LOS NEGATIVOS (lo que pasa cuando NO se puede)
# ══════════════════════════════════════════════════════════════════════════════════

def test_SIN_version_conocida_no_propone_nada():
    """El hallazgo de R4: `server_info` estaba vacío en las 42 filas. Pinear a la versión que
    corre sería congelar la rotura — el usuario apretaría un botón que fija el problema."""
    p = FV.proponer(_FILA_NPX, version_buena=None,
                    evidencia={"server_info": {"version": "2.0.0"}})
    assert not p.posible
    assert "a ciegas" in p.motivo and "congelar la rotura" in p.motivo
    assert p.version_propuesta is None


def test_YA_PINEADO_no_vuelve_a_proponer():
    """**El negativo que importa: ¿y si el pin propuesto TAMBIÉN falla?** Una vez pineado,
    esto deja de ofrecer pin. Volver a ofrecer el mismo no cambiaría nada, y ofrecer otro a
    ciegas sería adivinar. Un pin que falla es un caso de ESCALADA, no de otro pin."""
    fila = {"entity_id": "coingecko", "command": "npx",
            "args": ["-y", "@coingecko/coingecko-mcp@1.4.0"]}
    p = FV.proponer(fila, version_buena="1.3.0")
    assert not p.posible and p.version_corriendo == "1.4.0"
    assert "ya está fijado" in p.motivo and "no es la versión" in p.motivo


def test_ya_pineado_en_python_tampoco():
    fila = {"entity_id": "pubmed", "command": "uvx", "args": ["mcp-simple-pubmed==0.3.1"]}
    assert not FV.proponer(fila, version_buena="0.2.0").posible


def test_si_la_version_buena_ES_la_que_corre_no_propone():
    """Entonces el problema no es la versión, y proponer un pin sería mandar al usuario por
    un camino que no lleva a nada."""
    p = FV.proponer(_FILA_NPX, version_buena="2.0.0",
                    evidencia={"server_info": {"version": "2.0.0"}})
    assert not p.posible and "no es la versión" in p.motivo


def test_no_aplica_a_un_comando_que_no_es_npx_ni_uvx():
    fila = {"entity_id": "cad", "command": "python3", "args": ["/ruta/cad_server.py"]}
    p = FV.proponer(fila, version_buena="1.0.0")
    assert not p.posible and "no es npx ni uvx" in p.motivo


def test_no_confunde_un_flag_ni_una_url_con_el_paquete():
    fila = {"entity_id": "fred", "command": "npx",
            "args": ["-y", "mcp-remote", "https://x.test/mcp", "--header", "K:v"]}
    p = FV.proponer(fila, version_buena="1.1.0")
    assert p.posible and p.args_despues[1] == "mcp-remote@1.1.0"
    assert p.args_despues[2] == "https://x.test/mcp", "la URL no se toca"


def test_no_toca_un_arg_con_variable_sin_expandir():
    fila = {"entity_id": "filesystem", "command": "npx",
            "args": ["-y", "${PUPPET_PKG}", "${PUPPET_WORKDIR}"]}
    p = FV.proponer(fila, version_buena="1.0.0")
    assert not p.posible, "un ${VAR} sin expandir no es un paquete"


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · APLICAR: CONFIRMACIÓN, UPDATE, Y JAMÁS EL CATÁLOGO
# ══════════════════════════════════════════════════════════════════════════════════

class _RepoFalso:
    def __init__(self, conocidas=("coingecko",)):
        self._conocidas = list(conocidas)
        self.escrituras = []

    def listar_entidades(self, conn, user_id):
        return [{"entity_id": e} for e in self._conocidas]

    def upsert_entidad(self, conn, *, user_id, entity_id, commit=True, **campos):
        self.escrituras.append({"user_id": user_id, "entity_id": entity_id, **campos})
        return {"entity_id": entity_id}


def _propuesta_ok():
    return FV.proponer(_FILA_NPX, version_buena="1.4.0")


def test_SIN_confirmacion_no_escribe_NADA():
    repo = _RepoFalso()
    with pytest.raises(FV.SinConfirmar):
        FV.aplicar(None, user_id="u1", entity_id="coingecko",
                   propuesta=_propuesta_ok(), confirmado=False, repo=repo)
    assert repo.escrituras == [], "escribió sin confirmación"


def test_con_confirmacion_escribe_SOLO_los_args():
    repo = _RepoFalso()
    r = FV.aplicar(None, user_id="u1", entity_id="coingecko",
                   propuesta=_propuesta_ok(), confirmado=True, repo=repo)
    assert r["ok"] and r["huella_cambia"] is True
    assert len(repo.escrituras) == 1
    esc = repo.escrituras[0]
    assert set(esc) == {"user_id", "entity_id", "args", "commit"} or \
           set(esc) - {"commit"} == {"user_id", "entity_id", "args"}, esc
    assert esc["args"] == ["-y", "@coingecko/coingecko-mcp@1.4.0"]


def test_no_fabrica_una_fila_que_el_registro_no_conoce():
    """La misma regla que la persistencia del verificador: UPDATE sobre lo que ya existe."""
    repo = _RepoFalso(conocidas=("otra_cosa",))
    with pytest.raises(FV.SinConfirmar):
        FV.aplicar(None, user_id="u1", entity_id="coingecko",
                   propuesta=_propuesta_ok(), confirmado=True, repo=repo)
    assert repo.escrituras == []


def test_no_aplica_una_propuesta_imposible():
    repo = _RepoFalso()
    imposible = FV.proponer(_FILA_NPX, version_buena=None)
    with pytest.raises(FV.SinConfirmar):
        FV.aplicar(None, user_id="u1", entity_id="coingecko",
                   propuesta=imposible, confirmado=True, repo=repo)
    assert repo.escrituras == []


def test_el_modulo_JAMAS_escribe_en_el_catalogo():
    """Congelado: el catálogo es dato curado con autor. Un botón de UI que lo reescribe desde
    la máquina de un usuario convierte un dato auditado en uno mutable por accidente."""
    fuente = (_AQUI / "repair_fijar_version.py").read_text()
    # subcadenas, no regex: `open(` no es un patrón válido y el test se caía por eso en vez
    # de por lo que mide.
    for prohibido in ("catalog/", "write_text", ".mcp.json", "open(", "Path("):
        assert prohibido not in fuente, (
            f"`repair_fijar_version` toca {prohibido!r}: sólo puede escribir la FILA del "
            f"usuario, por el repo")


# ══════════════════════════════════════════════════════════════════════════════════
# 6 · LA LÁPIDA GANA (§4.4)
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_lapida_no_produce_un_boton():
    """Una entidad que el usuario desconectó no es un fallo: no hay nada que reparar."""
    v = RC.clasificar_muerte({"disparador": "LAPIDA", "entity_id": "github"})
    assert v.boton is None and v.señales.get("no_es_fallo") is True


def test_el_verificador_persiste_server_info_SOLO_si_la_conexion_esta_VIVA():
    """La versión de un server ROTO no es «la que anduvo». Guardarla como tal haría que
    [Fijar la versión] proponga volver exactamente a la rotura."""
    fuente = (_RAIZ / "product/backend/app/phase1/conexiones_verificador.py").read_text()
    assert 'estado") == VIVA and f.get("server_info")' in fuente, (
        "la persistencia de `server_info` dejó de estar condicionada al veredicto VIVO")
