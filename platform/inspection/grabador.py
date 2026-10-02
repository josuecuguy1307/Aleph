"""grabador.py — GRABAR Y REPLAYAR una conexión MCP. S1 de `DISEÑO-SUITE-v1.md`.

Una suite de certificación que necesita red y llaves para correr no se corre. Grabar una vez
y replayar después convierte «probar las 62 piezas» en algo que pasa en CI, en un avión y en
la máquina de alguien que no tiene las credenciales de persona usuaria.

    ALEPH_GRABAR=<slug>   graba lo que pase por el transporte, en disco
    ALEPH_REPLAY=<slug>   NO spawnea nada: responde desde el disco
    ninguna de las dos    todo corre exactamente como hoy (el default)

──────────────────────────────────────────────────────────────────────────────────────
DECISIÓN 1.A · SE GRABA EN LA FRONTERA DEL TRANSPORTE, NO EN LA DEL PROCESO.

El punto es `transporte.servidor_stdio()`: el único lugar por donde pasan los dos clientes,
y `test_frontera_transporte.py` ya lo congela. Este módulo NO le pide la clase a nadie —la
RECIBE en `envolver(cls)`— y ese detalle no es estilo: si acá adentro hubiera una llamada a
`servidor_stdio()`, `test_frontera_dueno.py` lo contaría como un sitio de spawn nuevo y
tendría razón. Envolver no es spawnear.

Descartado: grabar los bytes crudos del pipe. Más fiel, pero los ids del JSON-RPC cambian
entre corridas (habría que normalizarlos para comparar) y no captura `diagnostico()` —el
stderr, `murio`, `t_eof`, los timeouts de R1— que es justo lo que hace útil una grabación
cuando algo falla. Se graba el nivel donde ya está el significado.

DECISIÓN 1.B · LAS GRABACIONES VIVEN EN EL REPO, VERSIONADAS.

`platform/inspection/grabaciones/<arquetipo>/<NN>-<paso>.json`. Una grabación **es un
fixture, no un dato del usuario**: tiene que viajar con el commit que la hizo válida, y en
CI —donde no hay `Application Support`— no existiría. Estar en el repo además las hace
revisables en el diff, que es donde se nota si una trae algo que no debería.

DECISIÓN 1.C · UNA GRABACIÓN VIEJA AVISA Y FALLA. NO SE REGRABA SOLA.

Al replayar se compara la `huella_receta` guardada con la de la receta viva. Si difieren,
esto levanta `GrabacionVieja` con el comando exacto para regrabar. Regrabar automáticamente
es cómodo y es exactamente cómo una suite deja de significar algo: la grabación se
actualizaría sola contra el comportamiento nuevo —incluido el que rompió algo— y el verde de
mañana ya no diría lo mismo que el de hoy. Regrabar es una decisión con autor.

⚠️ NINGUNA GRABACIÓN GUARDA UNA CREDENCIAL. El env NO se graba: entra sólo como `huella`, un
digest de 12 hex del que no sale ningún valor. Todo texto grabado pasa por el
`OutputScrubber`, y con la lección de R5 escrita en el código: `.scrub()` devuelve un
`ScrubReport`, **no un string** — guardar el objeto tal cual dejaba un repr sin la llave, o
sea un test de fuga en verde sin que nada se hubiera redactado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent

#: LAS DOS PERILLAS, y se leen ACÁ Y EN NINGÚN OTRO LADO. Mismo molde y mismo motivo que
#: `ALEPH_DUENO` (`dueno.encendido`) y `ALEPH_TRANSPORTE` (`transporte.modo`): dos módulos
#: que lean la misma perilla por su cuenta pueden elegir distinto en la misma corrida, que
#: es el «dos verdades» que este árbol viene cerrando en todos lados. Lo fija
#: `test_frontera_grabador.py`.
_ENV_GRABAR = "ALEPH_GRABAR"
_ENV_REPLAY = "ALEPH_REPLAY"

#: Los pasos que se graban. No es «todo lo que el objeto sabe hacer»: es lo que tiene
#: significado para un veredicto.
INICIALIZAR, LISTAR, LLAMAR = "initialize", "list_tools", "call_tool"


class GrabadorError(RuntimeError):
    """Falla del grabador/replay. Se levanta; no se traga: un replay que degrada a vivo
    sería una suite que dice «sin red» y usa la red."""


class GrabacionVieja(GrabadorError):
    """La receta cambió desde que se grabó (DECISIÓN 1.C)."""


class GrabacionAusente(GrabadorError):
    """Se pidió un paso que no está grabado. Falla cerrado: inventar una respuesta acá es
    fabricar un veredicto."""


# ── LAS PERILLAS ────────────────────────────────────────────────────────────────────────

def _slug(nombre: str) -> Optional[str]:
    v = (os.environ.get(nombre) or "").strip()
    return v or None


def grabando() -> Optional[str]:
    """El slug que se está grabando, o None. Se lee en cada llamada a propósito: un test que
    la mueve con `monkeypatch.setenv` tiene que verla."""
    return _slug(_ENV_GRABAR)


def replayando() -> Optional[str]:
    """El slug que se está replayando, o None. Idem."""
    return _slug(_ENV_REPLAY)


def _raiz() -> Path:
    """`platform/inspection/grabaciones/`, resuelto contra ESTE archivo.

    Contra el archivo y no contra un `cwd` ni una ruta literal: una ruta absoluta a un
    worktree funciona en la máquina del que la escribió y en ninguna otra — es el modo de
    fallo que `verify_citas_diseno_suite.py` pagó (daba verde midiendo un árbol ajeno).
    """
    return _AQUI / "grabaciones"


def ruta_paso(arquetipo: str, orden: int, paso: str) -> Path:
    return _raiz() / arquetipo / f"{orden:02d}-{paso}.json"


# ── LO QUE NO PUEDE VIAJAR ──────────────────────────────────────────────────────────────

def _scrub_texto(txt: str) -> tuple:
    """(texto_limpio, n_hallazgos). Si el scrubber no carga, el texto se RECORTA A NADA:
    perder una grabación es malo, filtrar una llave es peor."""
    if not txt:
        return "", 0
    try:
        import sys as _sys
        _g = _AQUI.parents[1] / "platform" / "gates"
        if not _g.exists():                                # árbol instalado distinto
            _g = _AQUI.parent / "gates"
        if str(_g) not in _sys.path:
            _sys.path.insert(0, str(_g))
        from scrubber import OutputScrubber                # type: ignore
        # ⚠️ R5 · `.scrub()` devuelve un ScrubReport, NO un string. El texto limpio está en
        # `.clean_text`; guardar el objeto deja un repr que no contiene la llave y hace pasar
        # el test de fuga sin haber redactado nada.
        rep = OutputScrubber().scrub(txt)
        return getattr(rep, "clean_text", ""), len(getattr(rep, "findings", []))
    except Exception:                                      # noqa: BLE001 — frontera
        return "", -1                                      # -1 = el scrubber no estaba


#: Nombres de env-var que llevan credencial. No es una heurística de contenido —esa es la
#: del scrubber— sino de NOMBRE, que es lo único que se puede afirmar sin mirar el valor.
_NOMBRE_SENSIBLE = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|BEARER|COOKIE|SESSION)", re.I)


def valores_prohibidos(env: Optional[dict]) -> set:
    """Los VALORES del env del hijo que no pueden aparecer en una grabación, jamás.

    ⚠️ ESTA DEFENSA NO ES REDUNDANTE CON EL SCRUBBER, y se midió por qué. Al grabar `fred`
    —cuya receta mete la llave en los args (`--header X-API-Key:…`)— `mcp-remote` imprime
    por stderr `Using custom headers: {"X-API-Key":"…"}`. El scrubber NO lo neutralizó,
    porque su patrón busca cosas que PARECEN secretos y la llave-basura del verificador es
    texto legible en castellano. Con una llave real, que el secreto sobreviva dependería de
    que el patrón la reconozca — o sea de la suerte.

    Acá no hay suerte: lo que estaba en el env del hijo se redacta por IGUALDAD DE VALOR,
    reconozca el patrón o no. Se toman las claves declaradas por la receta (§9.2) y las de
    nombre sensible; se ignoran los valores cortos (`1`, `on`, `true`), que aparecerían por
    todos lados y no son secretos de nadie.

    Y NO REEMPLAZA la convención de grabar con la llave-basura: un server puede imprimir
    algo derivado —un hash, un prefijo, la mitad— que ninguna comparación de igualdad va a
    cazar. Las dos defensas cubren cosas distintas y las dos hacen falta.
    """
    if not env:
        return set()
    declaradas = getattr(env, "declaradas", None) or set()
    fuera = set()
    for k, v in env.items():
        v = str(v or "")
        if len(v) < 6:
            continue
        if k in declaradas or _NOMBRE_SENSIBLE.search(str(k)):
            fuera.add(v)
    return fuera


#: Campos de `diagnostico()` que describen LA MÁQUINA, no la conexión. Se omiten enteros.
_AMBIENTE = ("entorno",)


def _sin_ambiente(diag: dict) -> dict:
    """Saca del diagnóstico lo que es de la máquina y no del veredicto.

    ⚠️ MEDIDO SOBRE LA PRIMERA GRABACIÓN DE `fred`. `diagnostico()["entorno"]` trae
    `path_de_aleph`, o sea el `PATH` completo del equipo: `<user-toolchain>/…`,
    miniconda, macports, la versión de postgres instalada. Nada de eso es una credencial,
    y por eso ninguna de las dos defensas lo tocaba — pero una grabación es un **fixture
    versionado** (DECISIÓN 1.B), así que eso significaba meter la disposición de la máquina
    de una persona adentro del repo, y hacer que cada regrabación ensuciara el diff con
    ruido que no dice nada de la conexión.

    (Además el scrubber le picoteaba tramos de alta entropía y lo dejaba mangled: un PATH a
    medio redactar no sirve ni para diagnosticar ni para comparar.)

    Se omite ENTERO y se deja dicho, en vez de borrarlo callado: quien lea la grabación
    tiene que poder distinguir «acá no había nada» de «acá había algo y se sacó».
    """
    fuera = dict(diag or {})
    for k in _AMBIENTE:
        if k in fuera:
            fuera[k] = {"omitido": "ambiente de la máquina, no del veredicto"}
    return fuera


def _sin_maquina(txt: str) -> str:
    """El home del que grabó se vuelve `${HOME}`.

    ⚠️ Guardar la receta trajo de vuelta el problema que se le había sacado a
    `diagnostico()["entorno"]`: una receta con `/Users/<alguien>/…` mete la disposición de
    una máquina en un fixture versionado, y —peor— hace que la grabación NO SE PUEDA
    REPLAYAR en otra máquina, que es literalmente su razón de existir.

    Se normaliza en las dos puntas (al grabar y al validar), así que la huella es la misma
    acá y en CI. Es lo mismo que CLAUDE.md le exige al catálogo: territorio propio resuelto
    en runtime, jamás una ruta literal de una máquina."""
    h = str(Path.home())
    return txt.replace(h, "${HOME}") if h and h in txt else txt


def _redactar(txt: str, prohibidos: set) -> tuple:
    n = 0
    for v in prohibidos:
        if v and v in txt:
            txt = txt.replace(v, "[valor-del-env-redactado]")
            n += 1
    return txt, n


def _limpiar(valor: Any, prohibidos: Optional[set] = None) -> tuple:
    """Pasa TODO string por el scrubber Y por la redacción de valores del env.

    El orden importa: primero la redacción por igualdad (determinista, no depende de
    patrones) y después el scrubber (heurístico, caza lo que no sabíamos que era secreto).
    """
    prohibidos = prohibidos or set()
    total = 0
    if isinstance(valor, str):
        txt, n0 = _redactar(valor, prohibidos)
        txt, n = _scrub_texto(txt)
        return txt, n0 + (0 if n < 0 else n)
    if isinstance(valor, dict):
        fuera = {}
        for k, v in valor.items():
            fuera[k], n = _limpiar(v, prohibidos)
            total += n
        return fuera, total
    if isinstance(valor, (list, tuple)):
        fuera = []
        for v in valor:
            lv, n = _limpiar(v, prohibidos)
            fuera.append(lv)
            total += n
        return fuera, total
    return valor, 0


# ── LA HUELLA DE LA RECETA ──────────────────────────────────────────────────────────────

def huella_receta(command: str, args, env, cwd) -> tuple:
    """`(huella_12hex, env_declarado: bool)` — la huella de la RECETA, no del proceso.

    ⚠️ ACÁ HUBO UN BUG DE DISEÑO Y LO CAZÓ LA PRIMERA GRABACIÓN REAL. La versión inicial
    delegaba en `dueno.huella(...)` sin más. Para el DUEÑO eso está bien: hashea el env
    completo cuando nadie marcó nada, y su modo de fallo es «se comparte de menos, nunca de
    más» — un proceso extra, 113 MB, ningún riesgo.

    Para una GRABACIÓN el mismo comportamiento es fatal, porque una grabación se compara
    **entre procesos distintos**, y el env completo no es estable entre procesos: la propia
    docstring de `dueno.huella` lo dice — `ensure_user_path()` MUTA `os.environ["PATH"]` en
    el primer spawn. Medido: grabar `fred` dio `e8978e1ebf1d` y replayarlo en otro proceso
    calculó `d1b6dec057e7`, así que la grabación nacía inservible y `GrabacionVieja` se
    disparaba por una diferencia que no era de la receta.

    Lo que el §1.4 pide es «la huella sobre el env DECLARADO desde §9.2», y eso es lo que
    esto hace:

      · con la marca `EnvDelHijo` → se delega en `dueno.huella`, que filtra a lo declarado.
        Es el camino de producción (`_expand_server_cfg` y `_spawn` la ponen) y el bueno.
      · sin la marca → se hashea **command + args + cwd y NADA de env**, y la grabación lo
        declara con `env_declarado: false`.

    Sin marca NO se cae al env completo a propósito: sería cambiar «la receta cambió» por
    «el proceso es otro», que es un rojo que nadie puede accionar. Que la grabación diga que
    su huella es la débil es preferible a una huella fuerte que miente.
    """
    try:
        import sys as _sys
        if str(_AQUI) not in _sys.path:
            _sys.path.append(str(_AQUI))
        import dueno as _d                                 # noqa: E402
        if getattr(env, "declaradas", None) is not None:
            return _d.huella(command, args, env, cwd), True
        # ⚠️ SIN MARCA NO SE DELEGA, Y ACÁ ESTÁ EL PORQUÉ (medido, segunda vuelta).
        # Pasarle `env=None` a `dueno.huella` NO excluye el entorno: adentro llama a
        # `transporte.entorno_del_hijo(None)`, que justamente devuelve `dict(os.environ)`
        # entero. O sea que el intento de «hashear sin env» hasheaba TODO el env — el
        # mismo bug, disfrazado. Se vio en la segunda grabación de `fred`: `d21ae04756fe`
        # al grabar contra `d9bbd9763906` al replayar, con la receta sin tocar.
        # Se calcula acá, con el MISMO material que el dueño pero con `env` vacío, para que
        # las dos huellas sean del mismo formato y se lean igual en el JSON.
        material = json.dumps({
            "command": str(command or ""),
            "args": [str(a) for a in (args or [])],
            "env": {},
            "cwd": str(cwd or ""),
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12], False
    except Exception as e:                                 # noqa: BLE001
        raise GrabadorError(
            f"no pude calcular la huella de la receta: {type(e).__name__}: {e}. "
            f"Sin huella una grabación no se puede validar, y validar de menos es "
            f"exactamente lo que la DECISIÓN 1.C prohíbe.") from e


def _clave(metodo: str, args: Any) -> str:
    """Identidad de una petición, estable entre corridas."""
    return metodo + "::" + json.dumps(args or {}, sort_keys=True, ensure_ascii=False,
                                      default=str)


def comando_para_regrabar(arquetipo: str) -> str:
    return f"ALEPH_GRABAR={arquetipo} <el comando que ejercita esa pieza>"


# ── EL GRABADOR ─────────────────────────────────────────────────────────────────────────

def _fabricar_grabador(cls_real, arquetipo: str):
    """Una clase con la MISMA firma que la real, que anota lo que pasa y delega."""

    class ServidorGrabador:
        """Envuelve al servidor real y escribe un JSON por paso.

        No cambia una coma del comportamiento: delega todo y devuelve lo que el real
        devolvió. Si escribir la grabación falla, **el paso sigue**: grabar es una
        instrumentación, no una condición para que el producto funcione. Lo que NO se hace
        es tragarse el error en silencio — se anota en `errores_de_grabacion`.
        """

        #: Deja el nombre del real a la vista: `elegido()` publica el transporte y la
        #: evidencia de cada medición dice de dónde salió; un envoltorio que borra ese
        #: nombre convierte dos filas del registro en incomparables.
        envuelve = getattr(cls_real, "__name__", str(cls_real))

        def __init__(self, name, command, args=None, env=None, rpc_timeout=30.0, cwd=None):
            self._real = cls_real(name, command, args, env=env,
                                  rpc_timeout=rpc_timeout, cwd=cwd)
            self._arquetipo = arquetipo
            self._orden = 0
            self._name = name
            self._prohibidos_tmp = valores_prohibidos(env)
            # ⚠️ HUECO DE S1 QUE DESTAPÓ S2. La grabación guardaba la HUELLA de la receta
            # pero no la receta, así que un replay no era autocontenido: el consumidor tenía
            # que saber de antemano el comando y los args. En CI —donde no está la DB de
            # conexiones de este usuario— eso es imposible, y CI era la razón de existir de
            # todo esto.
            #
            # Se guarda la receta, REDACTADA (los args de `fred` llevan la llave adentro:
            # `--header X-API-Key:…`), y la huella se calcula sobre ESA MISMA receta
            # redactada. Es una desviación consciente del §1.4 —que dice «la huella del
            # dueño»— y el motivo es que las dos huellas responden preguntas distintas: la
            # del dueño decide si dos procesos pueden compartirse, y ahí un secreto distinto
            # SÍ los separa; la de una grabación decide si sigue describiendo la misma
            # receta, y una que dependa de un secreto no es compartible — o sea, no es una
            # grabación.
            # ⚠️ LA RECETA PASA POR LA REDACCIÓN, **NO** POR EL SCRUBBER, y se midió por
            # qué: el scrubber neutraliza fórmulas anteponiendo `'` a lo que empieza con `-`
            # (defensa CSV, correcta para TEXTO que va a un usuario). Sobre una línea de
            # comando eso escribe `'-y` y `'--header`, o sea CORROMPE la receta — y una
            # receta corrupta hace fallar el replay por una razón que no existe.
            # El scrubber es para texto; una receta es estructura.
            self._receta = {
                "command": _sin_maquina(_redactar(str(command or ""), self._prohibidos_tmp)[0]),
                "args": [_sin_maquina(_redactar(str(x), self._prohibidos_tmp)[0])
                         for x in (args or [])],
                "cwd": _sin_maquina(_redactar(str(cwd or ""), self._prohibidos_tmp)[0]),
            }
            self._huella, self._env_declarado = huella_receta(
                self._receta["command"], self._receta["args"], env, self._receta["cwd"])
            #: Se calcula UNA vez, al construir: el env del hijo no cambia después, y
            #: recalcularlo por paso sólo daría más chances de que se pierda la marca.
            self._prohibidos = valores_prohibidos(env)
            self.errores_de_grabacion: list = []

        # ── delegación pura ────────────────────────────────────────────────────────────
        def __getattr__(self, item):
            return getattr(self._real, item)

        def _anotar(self, paso: str, peticion: dict, respuesta: Any) -> None:
            self._orden += 1
            try:
                diag = {}
                try:
                    diag = self._real.diagnostico() or {}
                except Exception:                          # noqa: BLE001
                    diag = {}
                diag = _sin_ambiente(diag)
                resp_limpia, n1 = _limpiar(respuesta, self._prohibidos)
                diag_limpio, n2 = _limpiar(diag, self._prohibidos)
                fila = {
                    "arquetipo": self._arquetipo,
                    "paso": paso,
                    "transporte": "stdio",
                    "servidor": self._name,
                    "grabado_en": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "huella_receta": self._huella,
                    "env_declarado": self._env_declarado,
                    "receta": self._receta,
                    "peticion": peticion,
                    "respuesta": resp_limpia,
                    "diagnostico": diag_limpio,
                    "scrubber": {"hallazgos_neutralizados": n1 + n2},
                }
                p = ruta_paso(self._arquetipo, self._orden, paso)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(fila, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
            except Exception as e:                         # noqa: BLE001
                self.errores_de_grabacion.append(f"{paso}: {type(e).__name__}: {e}")

        # ── la interfaz del transporte ─────────────────────────────────────────────────
        def start(self):
            r = self._real.start()
            self._anotar(INICIALIZAR, {"metodo": "initialize", "args": {}}, {"ok": bool(r)})
            return r

        def list_tools(self):
            r = self._real.list_tools()
            self._anotar(LISTAR, {"metodo": "tools/list", "args": {}}, r)
            return r

        def call_tool(self, tool_name, arguments=None):
            r = self._real.call_tool(tool_name, arguments)
            self._anotar(LLAMAR,
                         {"metodo": "tools/call",
                          "args": {"name": tool_name, "arguments": arguments or {}}}, r)
            return r

        def stop(self):
            return self._real.stop()

        def diagnostico(self):
            return self._real.diagnostico()

    return ServidorGrabador


# ── EL REPLAY ───────────────────────────────────────────────────────────────────────────

def _fabricar_replay(arquetipo: str):
    """Una clase con la MISMA firma que la real que NO SPAWNEA NADA."""

    class ServidorReplay:
        """Responde desde el disco. Nunca abre un proceso ni toca la red.

        Que no spawnee no es una optimización: es la propiedad que hace que la suite
        signifique «sin red y sin llaves». Un replay que cayera al camino vivo cuando le
        falta un paso sería una suite que miente sobre su propio aislamiento — por eso
        `GrabacionAusente` se levanta y no se degrada.
        """

        envuelve = "(replay · ningún proceso)"

        def __init__(self, name, command, args=None, env=None, rpc_timeout=30.0, cwd=None):
            self._name = name
            self._arquetipo = arquetipo
            self._pedida = (command, args, cwd)
            self._por_clave: dict = {}
            self._pasos: list = []
            d = _raiz() / arquetipo
            if not d.is_dir():
                raise GrabacionAusente(
                    f"no hay grabaciones para «{arquetipo}» en {d}. "
                    f"Graba primero:  {comando_para_regrabar(arquetipo)}")
            for p in sorted(d.glob("*.json")):
                fila = json.loads(p.read_text(encoding="utf-8"))
                self._pasos.append(fila)
                self._por_clave[_clave(fila["peticion"]["metodo"],
                                       fila["peticion"].get("args"))] = fila
            if not self._pasos:
                raise GrabacionAusente(f"la carpeta {d} está vacía")
            # ⚠️ DOS PROPIEDADES QUE TIENEN QUE CONVIVIR, y la primera versión de esto
            # mató a la segunda sin querer.
            #
            #   (a) EL REPLAY ES AUTOCONTENIDO — en CI nadie conoce la receta, así que si el
            #       llamante no la pasa se usa la GUARDADA.
            #   (b) DECISIÓN 1.C — una receta cambiada pone la grabación en ROJO.
            #
            # Validar siempre la guardada contra sí misma satisface (a) y convierte (b) en
            # una TAUTOLOGÍA: el chequeo nunca podría dar rojo, y una suite con un guard que
            # no puede fallar es peor que sin guard, porque parece que cubre.
            #
            # Entonces: si el llamante pasó una receta, MANDA LA SUYA y se compara; si no
            # pasó nada, se usa la guardada. La del llamante se redacta con los mismos
            # valores prohibidos antes de hashear — si no, una llave viva contra una
            # grabación hecha con la llave-basura daría «receta cambiada» cuando la receta
            # es idéntica.
            guardada = self._pasos[0].get("receta") or {}
            prohibidos = valores_prohibidos(env)
            pedido_cmd, pedido_args, pedido_cwd = self._pedida
            if str(pedido_cmd or "").strip():
                ref_cmd = _sin_maquina(_redactar(str(pedido_cmd), prohibidos)[0])
                ref_args = [_sin_maquina(_redactar(str(x), prohibidos)[0])
                            for x in (pedido_args or [])]
                ref_cwd = _sin_maquina(_redactar(str(pedido_cwd or ""), prohibidos)[0])
            else:
                ref_cmd = guardada.get("command", "")
                ref_args = guardada.get("args") or []
                ref_cwd = guardada.get("cwd", "")
            self._viva, self._env_declarado = huella_receta(ref_cmd, ref_args, env, ref_cwd)
            grabada = self._pasos[0].get("huella_receta")
            if grabada != self._viva:
                # DECISIÓN 1.C — avisa y falla, con el comando exacto.
                raise GrabacionVieja(
                    f"la grabación de «{arquetipo}» no corresponde a la receta viva.\n"
                    f"  huella grabada: {grabada}\n"
                    f"  huella viva   : {self._viva}\n"
                    f"La receta cambió desde que se grabó, así que replayarla daría un verde "
                    f"sobre algo que ya no existe. Vuelve a grabar a propósito:\n"
                    f"  {comando_para_regrabar(arquetipo)}")

        def _buscar(self, metodo: str, args: Any):
            f = self._por_clave.get(_clave(metodo, args))
            if f is None:
                raise GrabacionAusente(
                    f"«{self._arquetipo}» no tiene grabado {metodo} con esos argumentos. "
                    f"No se inventa una respuesta: eso fabricaría un veredicto. "
                    f"Vuelve a grabar:  {comando_para_regrabar(self._arquetipo)}")
            return f

        def start(self):
            return bool(self._buscar("initialize", {})["respuesta"].get("ok"))

        def list_tools(self):
            return self._buscar("tools/list", {})["respuesta"]

        def call_tool(self, tool_name, arguments=None):
            return self._buscar("tools/call",
                                {"name": tool_name, "arguments": arguments or {}})["respuesta"]

        def stop(self):
            return None

        def diagnostico(self):
            # El del último paso grabado: es el que corresponde al estado final.
            return dict(self._pasos[-1].get("diagnostico") or {})

    return ServidorReplay


# ── LA FRONTERA ─────────────────────────────────────────────────────────────────────────

def envolver(cls_real):
    """La clase que el transporte tiene que devolver, según las perillas.

    Con las dos apagadas devuelve **la clase real tal cual** —misma identidad, mismo
    `__name__`—: sin perilla, este módulo no existe para el producto. Es lo que deja intacto
    a `test_la_perilla_hace_lo_que_dice`, que exige ver `ServidorSDK` / `MCPServer`.

    `ALEPH_REPLAY` gana sobre `ALEPH_GRABAR` si alguien pone las dos: grabar mientras se
    replaya grabaría el replay, que es una grabación de una grabación y no significa nada.
    """
    slug_replay = replayando()
    if slug_replay:
        return _fabricar_replay(slug_replay)
    slug_grabar = grabando()
    if slug_grabar:
        return _fabricar_grabador(cls_real, slug_grabar)
    return cls_real


__all__ = ["grabando", "replayando", "envolver", "huella_receta", "ruta_paso",
           "comando_para_regrabar", "GrabadorError", "GrabacionVieja", "GrabacionAusente",
           "INICIALIZAR", "LISTAR", "LLAMAR"]
