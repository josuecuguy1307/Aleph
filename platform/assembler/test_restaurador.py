"""
test_restaurador.py — unit del PRIMER LECTOR del registro (CONTRACT-CONEXION-v1 §1, §6).

Verde = efecto real, nunca narración. El cliente MCP se INYECTA (un doble que registra qué
recibió y decide si arranca), así que estos tests no spawnean procesos: lo que se prueba es
la DECISIÓN —de qué fuente sale cada pieza y por qué— y el PARTE, que es lo que ve el
usuario cuando algo no levanta.

Lo que se cubre, en orden de consecuencia:

  1. FALLBACK ESCALONADO — la fila manda cuando sirve; si falta, si su recipe_version es
     desconocida, o si está incompleta, se cae al .mcp.json Y SE REPORTA con motivo.
  2. VACÍO POR DISEÑO ≠ INCOMPLETA — una fila sin cwd/timeout_ms/era/version_negociada
     SÍ se ejecuta. Es el error que el prompt marcó y el que más fácil se cuela.
  3. LA PRUEBA DE LA CONVIVENCIA — con el registro vacío, TODAS las piezas salen por el
     camino viejo y arrancan igual.
  4. BEST-EFFORT — una pieza que falla (o que revienta con excepción) no tumba a las otras.
  5. EL STDERR DEL HIJO llega al parte. Sin eso, "no arrancó" no dice nada.
  6. Los dos caminos usan el MISMO expansor (si divergieran, `${PUPPET_BELTS}` se
     resolvería distinto según de dónde salió la receta y nadie lo notaría).
  7. §2 — el entorno que recibe el hijo es env_publico + env_template.

Correr:  PYTHONPATH=platform:platform/assembler pytest platform/assembler/test_restaurador.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
for _p in (_AQUI, _AQUI.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import restaurador as R  # noqa: E402


# ── dobles ───────────────────────────────────────────────────────────────────────

class ServidorDoble:
    """Doble del MCPServer: registra lo que recibió y arranca o no según `FALLAN`."""

    FALLAN: set = set()
    REVIENTAN: set = set()
    creados: dict = {}

    def __init__(self, name, command, args, env=None, rpc_timeout=30.0, cwd=None):
        self.name, self.command, self.args = name, command, args
        self.env, self.rpc_timeout, self.cwd = env or {}, rpc_timeout, cwd
        ServidorDoble.creados[name] = self

    def start(self):
        if self.name in ServidorDoble.REVIENTAN:
            raise RuntimeError("spawn explotó")
        return self.name not in ServidorDoble.FALLAN

    def diagnostico(self):
        return {"stderr": f"[{self.name}] ModuleNotFoundError: no such module",
                "exit_code": 1, "detail": "el proceso murió antes del saludo"}


def expandir(cfg, base_env):
    """Expansor de mentira PERO con la misma firma y semántica: `${VAR}` contra base_env."""
    def sub(v):
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            return base_env.get(v[2:-1], v)
        return v
    env = dict(base_env)
    env.update({k: sub(v) for k, v in (cfg.get("env") or {}).items()})
    return sub(cfg.get("command", "")), [sub(a) for a in (cfg.get("args") or [])], env


def env_efectivo(fila):
    out = dict(fila.get("env_publico") or {})
    out.update(fila.get("env_template") or {})
    return out


SERVERS_VIEJOS = {
    "exa":      {"command": "npx", "args": ["-y", "exa-mcp-server"],
                 "env": {"EXA_API_KEY": "${EXA_API_KEY}"}},
    "secedgar": {"command": "uvx", "args": ["sec-edgar-mcp"],
                 "env": {"SEC_EDGAR_USER_AGENT": "Aleph (contact@aleph.app)"}},
}
BASE_ENV = {"EXA_API_KEY": "clave-resuelta-del-llavero", "PUPPET_BELTS": "/belts"}


def fila(entity_id, **kw):
    base = {"entity_id": entity_id, "recipe_version": "v1", "transporte": "stdio",
            "command": "uvx", "args": [f"{entity_id}-desde-el-registro"],
            "env_template": None, "env_publico": None, "cwd": None, "timeout_ms": None}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _limpiar():
    ServidorDoble.FALLAN, ServidorDoble.REVIENTAN, ServidorDoble.creados = set(), set(), {}
    yield


def restaurar(lector=None, servers=None, **kw):
    return R.restaurar_servers(
        servers if servers is not None else SERVERS_VIEJOS, BASE_ENV,
        expandir=expandir, mcp_server_cls=ServidorDoble,
        leer_entidad=lector, env_efectivo=env_efectivo if lector else None, **kw)


# ── 1 · el fallback escalonado ───────────────────────────────────────────────────

def test_la_fila_manda_cuando_sirve():
    res = restaurar(lambda e: fila(e))
    assert [p.fuente for p in res.piezas] == ["registro", "registro"]
    assert ServidorDoble.creados["exa"].args == ["exa-desde-el-registro"]


def test_fila_ausente_cae_al_viejo_y_lo_reporta():
    res = restaurar(lambda e: fila(e) if e == "exa" else None)
    por = {p.nombre: p for p in res.piezas}
    assert por["exa"].fuente == "registro"
    assert por["secedgar"].fuente == "fallback"
    assert por["secedgar"].motivo_fallback == R.FILA_AUSENTE
    assert ServidorDoble.creados["secedgar"].args == ["sec-edgar-mcp"], "usó el .mcp.json"


def test_recipe_version_desconocida_cae_al_viejo():
    """§1: ni se levanta ni se descarta — acá «no se levanta» es caer al camino que sí
    sabemos ejecutar, y el motivo queda escrito."""
    res = restaurar(lambda e: fila(e, recipe_version="v9"))
    assert {p.motivo_fallback for p in res.piezas} == {R.VERSION_DESCONOCIDA}
    assert all(p.arrancado for p in res.piezas), "cae al viejo, pero ARRANCA"


def test_stdio_sin_command_cae_al_viejo():
    res = restaurar(lambda e: fila(e, command=""))
    assert {p.motivo_fallback for p in res.piezas} == {R.SIN_COMANDO}


def test_transporte_indefinido_cae_al_viejo():
    res = restaurar(lambda e: fila(e, transporte=None))
    assert {p.motivo_fallback for p in res.piezas} == {R.TRANSPORTE_INDEFINIDO}


def test_http_cae_al_viejo_porque_el_puente_stdio_no_esta_cableado():
    """El registro YA guarda la receta HTTP (url + headers, v4). Lo que falta es ejecutarla:
    un MCP por HTTP corre como puente stdio y armar ese manifest no está cableado acá."""
    res = restaurar(lambda e: fila(e, transporte="http", command=None))
    assert {p.motivo_fallback for p in res.piezas} == {R.HTTP_POR_PUENTE_NO_CABLEADO}


def test_cwd_declarado_YA_SE_EJECUTA_y_llega_a_Popen():
    """Antes caía al fallback porque `MCPServer` no aceptaba cwd. Ahora lo acepta (v4):
    la fila con cwd se ejecuta DESDE EL REGISTRO y el cwd llega al proceso."""
    res = restaurar(lambda e: fila(e, cwd="/algun/dir"))
    assert all(p.fuente == "registro" for p in res.piezas), "ya no cae al fallback"
    assert all(p.motivo_fallback is None for p in res.piezas)
    assert ServidorDoble.creados["exa"].cwd == "/algun/dir"


def test_por_el_camino_viejo_el_cwd_es_None():
    """El bloque del .mcp.json no declara cwd (el formato no lo tiene), así que el
    fallback no puede inventarlo."""
    restaurar(lambda _e: None)
    assert ServidorDoble.creados["exa"].cwd is None


def test_un_lector_que_revienta_no_rompe_el_run():
    def lector(_e):
        raise RuntimeError("la DB se cayó")
    res = restaurar(lector)
    assert {p.motivo_fallback for p in res.piezas} == {R.SIN_REGISTRO}
    assert all(p.arrancado for p in res.piezas)


# ── 2 · vacío por diseño ≠ incompleta ────────────────────────────────────────────

def test_los_cuatro_vacios_por_diseno_NO_hacen_incompleta_a_la_fila():
    """cwd/timeout_ms/era/version_negociada vacíos son lo que el backfill dejó a propósito.
    Confundirlos con «falta un dato» mandaría TODO al fallback y el registro no serviría
    para nada."""
    f = fila("exa", cwd=None, timeout_ms=None, era=None, version_negociada=None)
    assert R._por_que_no_sirve(f) is None
    res = restaurar(lambda e: fila(e, cwd=None, timeout_ms=None))
    assert all(p.fuente == "registro" for p in res.piezas)


def test_timeout_ms_se_usa_si_está_y_si_no_el_default():
    restaurar(lambda e: fila(e, timeout_ms=5000))
    assert ServidorDoble.creados["exa"].rpc_timeout == 5.0
    ServidorDoble.creados = {}
    restaurar(lambda e: fila(e), rpc_timeout_default=30.0)
    assert ServidorDoble.creados["exa"].rpc_timeout == 30.0


# ── 3 · LA PRUEBA DE LA CONVIVENCIA ──────────────────────────────────────────────

def test_con_el_registro_vacio_todo_sale_por_el_camino_viejo_y_arranca():
    """Vaciar la tabla no puede cambiar el comportamiento. Es LA prueba de la sesión."""
    res = restaurar(lambda _e: None)
    assert all(p.fuente == "fallback" for p in res.piezas)
    assert all(p.motivo_fallback == R.FILA_AUSENTE for p in res.piezas)
    assert all(p.arrancado for p in res.piezas)
    assert ServidorDoble.creados["exa"].args == ["-y", "exa-mcp-server"]


def test_sin_lector_inyectado_es_el_comportamiento_de_antes():
    res = restaurar(None)
    assert all(p.fuente == "fallback" and p.motivo_fallback == R.SIN_REGISTRO
               for p in res.piezas)
    assert len(res.arrancadas) == 2


# ── 4 · best-effort ──────────────────────────────────────────────────────────────

def test_una_pieza_que_falla_no_tumba_a_las_otras():
    ServidorDoble.FALLAN = {"secedgar"}
    res = restaurar(lambda e: fila(e))
    assert [p.nombre for p in res.caidas] == ["secedgar"]
    assert len(res.arrancadas) == 1


def test_una_pieza_que_REVIENTA_tampoco_tumba_a_las_otras():
    ServidorDoble.REVIENTAN = {"exa"}
    res = restaurar(lambda e: fila(e))
    por = {p.nombre: p for p in res.piezas}
    assert por["exa"].arrancado is False
    assert "RuntimeError" in por["exa"].error
    assert por["secedgar"].arrancado is True


# ── 5 · el stderr del hijo llega al parte ────────────────────────────────────────

def test_el_stderr_del_hijo_muerto_llega_al_parte():
    """EL PUNTO: en la máquina de un usuario, «no arrancó» sin stderr no dice nada."""
    ServidorDoble.FALLAN = {"exa"}
    res = restaurar(lambda e: fila(e))
    caida = res.caidas[0]
    assert "ModuleNotFoundError" in caida.stderr
    assert caida.exit_code == 1
    assert "stderr" in caida.resumen() and "ModuleNotFoundError" in caida.resumen()["stderr"]


def test_el_parte_cuenta_fuentes_y_motivos():
    ServidorDoble.FALLAN = {"secedgar"}
    parte = restaurar(lambda e: fila(e) if e == "exa" else None).parte()
    assert parte["total"] == 2
    assert parte["arrancadas"] == ["exa"]
    assert parte["caidas"] == ["secedgar"]
    assert parte["del_registro"] == ["exa"]
    assert parte["fallback_por_motivo"] == {R.FILA_AUSENTE: ["secedgar"]}


def test_el_parte_no_lleva_el_objeto_vivo():
    """`parte()` se loguea y se serializa: no puede arrastrar un proceso vivo."""
    import json
    json.dumps(restaurar(lambda e: fila(e)).parte())   # no lanza


# ── 6 · un solo expansor para los dos caminos ────────────────────────────────────

def test_los_dos_caminos_expanden_igual():
    """Si divergieran, `${PUPPET_BELTS}` se resolvería distinto según de dónde salió la
    receta, y nadie lo notaría hasta que un belt no bootee en un solo camino."""
    servers = {"x": {"command": "${PUPPET_BELTS}", "args": [], "env": {}}}
    viejo = restaurar(None, servers=servers)
    ServidorDoble.creados = {}
    nuevo = restaurar(lambda e: fila(e, command="${PUPPET_BELTS}", args=[]), servers=servers)
    assert viejo.piezas[0].fuente == "fallback" and nuevo.piezas[0].fuente == "registro"
    assert ServidorDoble.creados["x"].command == "/belts"


# ── 7 · §2 · el entorno del hijo ─────────────────────────────────────────────────

def test_el_hijo_recibe_env_publico_mas_env_template_resuelto():
    res = restaurar(lambda e: fila(
        e, env_template={"EXA_API_KEY": "${EXA_API_KEY}"},
        env_publico={"SEC_EDGAR_USER_AGENT": "Aleph (contact@aleph.app)"}))
    assert all(p.fuente == "registro" for p in res.piezas)
    env = ServidorDoble.creados["exa"].env
    assert env["EXA_API_KEY"] == "clave-resuelta-del-llavero", "el ${VAR} se resolvió"
    assert env["SEC_EDGAR_USER_AGENT"] == "Aleph (contact@aleph.app)", "el literal viajó tal cual"


# ── 8 · LA LÁPIDA (§4) ───────────────────────────────────────────────────────────
#
# El riesgo entero de esta sección es que «apagada» se trate como un motivo de fallback
# más. Si eso pasa, la pieza cae al `.mcp.json`, arranca igual, y desconectar no hace
# NADA — con el agravante de que el parte diría que todo salió bien. Los tests de acá
# están escritos contra ese fallo, no contra la implementación.

def test_una_fila_apagada_NO_SE_LEVANTA():
    res = restaurar(lambda e: fila(e, habilitado=False))
    assert res.arrancadas == [], "una entidad desconectada no debe dejar servidor vivo"
    assert ServidorDoble.creados == {}, "no se llegó ni a construir el cliente MCP"


def test_una_fila_apagada_NO_CAE_AL_CAMINO_VIEJO():
    """EL TEST QUE IMPORTA. Caer al fallback la revivría por el catálogo y la lápida no
    serviría de nada: el usuario apaga, y al run siguiente vuelve sola."""
    res = restaurar(lambda e: fila(e, habilitado=False))
    assert [p.fuente for p in res.piezas] == ["lapida", "lapida"]
    assert all(p.motivo_fallback is None for p in res.piezas), "no es un fallback"
    assert res.parte()["fallback_por_motivo"] == {}, "no ensucia el vocabulario de fallback"


def test_una_apagada_NO_CUENTA_COMO_CAIDA():
    """`caidas` alimenta el «no arrancaron: …» que ve el usuario. Nombrar ahí algo que él
    mismo desconectó es devolverle su decisión como un fallo."""
    res = restaurar(lambda e: fila(e, habilitado=e == "exa"))
    apagadas = [p.nombre for p in res.apagadas]
    assert apagadas == ["secedgar"]
    assert [p.nombre for p in res.caidas] == [], "ninguna FALLÓ"
    parte = res.parte()
    assert parte["apagadas"] == ["secedgar"]
    assert parte["caidas"] == []
    assert parte["arrancadas"] == ["exa"]


def test_el_resumen_de_una_apagada_no_dice_error():
    res = restaurar(lambda e: fila(e, habilitado=False))
    d = res.piezas[0].resumen()
    assert d["apagada"] is True and d["motivo"] == R.APAGADA
    assert "error" not in d and "stderr" not in d, "no falló nada: no hay nada que reportar"


def test_apagar_UNA_no_toca_a_las_otras():
    res = restaurar(lambda e: fila(e, habilitado=e != "exa"))
    assert sorted(s.name for s in res.arrancadas) == ["secedgar"]
    assert "exa" not in ServidorDoble.creados


def test_el_parte_NO_trae_la_clave_apagadas_cuando_no_hay_ninguna():
    """Leer el parte de un run normal no debería obligar a aprender el vocabulario de la
    lápida para descartarlo."""
    assert "apagadas" not in restaurar(lambda e: fila(e)).parte()


def test_habilitado_true_se_levanta_como_siempre():
    res = restaurar(lambda e: fila(e, habilitado=True))
    assert [p.fuente for p in res.piezas] == ["registro", "registro"]


def test_una_fila_SIN_la_columna_habilitado_no_esta_apagada():
    """Una fila vieja sin migrar no es una fila apagada. Confundirlas dejaría al usuario
    sin conectores después de una migración incompleta."""
    f = fila("exa")
    assert "habilitado" not in f
    assert R._esta_apagada(f) is False
    assert restaurar(lambda e: fila(e)).piezas[0].fuente == "registro"


def test_sin_fila_no_hay_lapida():
    """Una entidad que el registro no conoce nunca se apagó: cae al camino viejo como
    siempre, con su motivo. Tratarla como apagada la haría desaparecer sin que nadie la
    haya desconectado."""
    assert R._esta_apagada(None) is False
    res = restaurar(lambda e: None)
    assert [p.fuente for p in res.piezas] == ["fallback", "fallback"]
    assert res.piezas[0].motivo_fallback == R.FILA_AUSENTE


def test_el_cero_del_INTEGER_tambien_apaga():
    """SQLite guarda el bool como INTEGER. Un lector crudo trae 0, no False."""
    assert R._esta_apagada({"habilitado": 0}) is True
    assert R._esta_apagada({"habilitado": 1}) is False


def test_apagar_TODO_no_deja_piezas_caidas():
    """El caso que decide el mensaje de error del assembler: sin servers porque el usuario
    los apagó ≠ sin servers porque fallaron."""
    res = restaurar(lambda e: fila(e, habilitado=False))
    assert res.arrancadas == [] and res.caidas == []
    assert len(res.apagadas) == 2
