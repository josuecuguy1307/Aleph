"""
restaurador.py — EL PRIMER LECTOR DEL REGISTRO (CONTRACT-CONEXION-v1 §1, §6).

Hasta ahora el registro se escribía y no lo leía nadie. Esto lo lee: toma la fila de una
entidad, ejecuta su receta (command · args · env) y levanta la conexión.

⚠️ FALLBACK ESCALONADO — el registro es el PRIMER lector, no el único todavía:

    lee del registro
    si la fila FALTA, está INCOMPLETA, o su recipe_version es DESCONOCIDA
        → CAE a la fuente vieja (el bloque del .mcp.json)
        → y lo REPORTA, jamás en silencio

Recién cuando esté probado se corta el fallback, y eso es otra sesión. Cortarlo ahora
dejaría al usuario sin un conector por cualquier fila que el backfill haya poblado mal.
La prueba de que se respetó: **vaciar la tabla y que todo siga funcionando por el camino
viejo.**

⚠️ QUÉ HACE INCOMPLETA A UNA FILA — y qué NO. El backfill dejó cuatro campos vacíos A
PROPÓSITO (`cwd`, `timeout_ms`, `era`, `version_negociada`): son datos que ninguna fuente
de hoy tiene. **Un `cwd` vacío no es una fila incompleta: es una receta que no declara
cwd, y se ejecuta sin él.** Lo que sí la hace incompleta está en `_por_que_no_sirve()`,
en un solo lugar y con nombre.

INYECCIÓN, no import. Este módulo vive en `platform/assembler/` y NO importa
`product/backend`: el lector de entidades, el expansor de `${VAR}` y la clase del cliente
MCP entran por parámetro. Así el assembler sigue sin depender del backend, y los tests
corren sin DB.

⚠️ LA LÁPIDA (§4) NO ES UN FALLBACK MÁS. Una fila con `habilitado = false` se SALTEA:
no se levanta por el registro y TAMPOCO cae al `.mcp.json`. La distinción es la sección
entera — si cayera al camino viejo, la pieza revivría por el catálogo en el run siguiente
y desconectar no serviría de nada. El fallback existe para que nada se pierda; aplicado a
una lápida sería justo lo que la rompe.

    _por_que_no_sirve()   «no PUEDO ejecutar esta fila»   → cae al camino viejo
    _esta_apagada()       «no DEBO ejecutar esta fila»    → no se ejecuta, y punto

Una pieza apagada no cuenta como caída, no entra al pool y viaja con su propia etiqueta
(`fuente="lapida"`, `apagada=True`) hasta el parte de daños, para que nadie confunda una
decisión del usuario con un fallo.

Lo que NO hace, a propósito:
  · NO reintenta, no hace backoff, no repara (§3 del contrato es otra sesión).
  · NO cambia CUÁNDO se levantan las conexiones (§6): sigue siendo dentro del run.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Callable, Optional

# ⚠️ NADA DE @dataclass EN ESTE ARCHIVO. `recipe_assembler` lo carga con
# `aleph_paths.load_module_by_path`, que NO registra el módulo en `sys.modules`; con
# `from __future__ import annotations`, `@dataclass` resuelve sus anotaciones con
# `sys.modules.get(cls.__module__).__dict__` (`dataclasses.py:757`, sin guard) y revienta
# con un AttributeError sobre None — al IMPORTAR, o sea antes de que corra una línea útil.
# Ningún otro módulo cargado por ruta del árbol usa dataclass (assembler.py,
# recipe_enforcer.py, tier_gate.py, scrubber.py: cero). Clases planas.
# La regla general vive en `aleph_paths.load_module_by_path` (regla 1), que es donde se
# elige este loader; acá queda la instancia.

#: Tope de hilos para levantar en paralelo. El costo real de una pieza es esperar el
#: `initialize` del server (I/O), no CPU: un pool chico ya solapa casi todo, y uno grande
#: solo multiplica procesos peleando por el disco en el arranque.
_MAX_PARALELO = 8

#: `recipe_version` que este binario sabe ejecutar. Espeja
#: `conexiones_repo.RECIPE_VERSIONS_CONOCIDAS`, pero se declara acá porque el assembler no
#: importa el backend. Si divergieran, el efecto es una caída al fallback — nunca ejecutar
#: una receta que no se entiende.
RECIPE_VERSIONS_EJECUTABLES = frozenset({"v1"})

#: Motivos de caída al fallback. Vocabulario CERRADO: el reporte los cuenta por nombre.
SIN_REGISTRO = "sin_registro"                    # no se inyectó lector (o falló al leer)
FILA_AUSENTE = "fila_ausente"                    # el registro no tiene esa entidad
VERSION_DESCONOCIDA = "recipe_version_desconocida"
SIN_COMANDO = "sin_comando"                      # stdio sin command: no hay qué ejecutar
TRANSPORTE_INDEFINIDO = "transporte_indefinido"  # ni stdio ni http declarado
HTTP_POR_PUENTE_NO_CABLEADO = "http_por_puente_stdio_no_cableado"

#: ⚠️ APAGADA NO ES UN MOTIVO DE FALLBACK, y por eso está fuera de esa lista.
#:
#: Los de arriba dicen «no PUDE ejecutar la fila» y su consecuencia correcta es caer al
#: `.mcp.json`. Éste dice «no DEBO»: es la lápida del §4, una decisión del usuario. Si
#: cayera al camino viejo, la pieza revivría por el catálogo en el run siguiente y apagar
#: no serviría absolutamente de nada — el fallback, que existe para que nada se pierda,
#: sería justo lo que rompe la única función de la lápida.
#:
#: Por eso una pieza apagada no entra al pool, no cuenta como caída, y viaja con su propia
#: etiqueta hasta el parte de daños.
APAGADA = "apagada_por_el_usuario"
FUENTE_LAPIDA = "lapida"


class PiezaRestaurada:
    """El parte de UNA pieza. Es lo que se le muestra al usuario y lo que se loguea."""

    __slots__ = ("nombre", "fuente", "motivo_fallback", "arrancado", "ms",
                 "error", "stderr", "exit_code", "servidor", "apagada")

    def __init__(self, nombre, fuente, motivo_fallback=None, apagada=False):
        self.nombre = nombre
        self.fuente = fuente              # "registro" | "fallback" | "lapida"
        self.motivo_fallback = motivo_fallback
        self.apagada = apagada            # §4: el usuario la desconectó. NO es un fallo.
        self.arrancado = False
        self.ms = 0
        self.error = None
        self.stderr = ""                  # el stderr REAL del hijo — sin esto "no arrancó" no dice nada
        self.exit_code = None
        self.servidor = None              # el MCPServer vivo, si arrancó

    def resumen(self) -> dict:
        """Sin el objeto vivo: seguro para loguear, serializar y mostrar."""
        d = {"nombre": self.nombre, "fuente": self.fuente, "arrancado": self.arrancado,
             "ms": self.ms}
        if self.apagada:
            # NO lleva `error`: no falló nada. El usuario la apagó y esto lo dice así.
            d["apagada"] = True
            d["motivo"] = APAGADA
            return d
        if self.motivo_fallback:
            d["motivo_fallback"] = self.motivo_fallback
        if not self.arrancado:
            d["error"] = self.error or "no arrancó"
            if self.stderr:
                d["stderr"] = self.stderr
            if self.exit_code is not None:
                d["exit_code"] = self.exit_code
        return d


class Restauracion:
    """El parte de daños completo."""

    __slots__ = ("piezas",)

    def __init__(self, piezas=None):
        self.piezas: list = list(piezas or [])

    @property
    def arrancadas(self) -> list:
        return [p.servidor for p in self.piezas if p.arrancado and p.servidor is not None]

    @property
    def caidas(self) -> list[PiezaRestaurada]:
        """Las que NO arrancaron habiendo tenido que arrancar.

        ⚠️ Las apagadas quedan afuera a propósito. El caller usa esta lista para decir «no
        arrancaron: …», y nombrar ahí una pieza que el usuario desconectó a mano sería
        reportarle su propia decisión como un fallo."""
        return [p for p in self.piezas if not p.arrancado and not p.apagada]

    @property
    def apagadas(self) -> list[PiezaRestaurada]:
        """Las que la lápida salteó (§4). Ni arrancadas ni caídas: un tercer estado."""
        return [p for p in self.piezas if p.apagada]

    def parte(self) -> dict:
        """El resumen que va al record del run y al log. NOMBRES y causas, jamás valores."""
        del_registro = [p.nombre for p in self.piezas if p.fuente == "registro"]
        por_motivo: dict[str, list[str]] = {}
        for p in self.piezas:
            if p.motivo_fallback:
                por_motivo.setdefault(p.motivo_fallback, []).append(p.nombre)
        parte = {
            "total": len(self.piezas),
            "arrancadas": sorted(p.nombre for p in self.piezas if p.arrancado),
            "caidas": sorted(p.nombre for p in self.caidas),
            "del_registro": sorted(del_registro),
            "fallback_por_motivo": {k: sorted(v) for k, v in sorted(por_motivo.items())},
            "detalle": [p.resumen() for p in self.piezas],
        }
        # Clave propia, y sólo cuando hay: leer el parte de un run normal no debería tener
        # que aprender el vocabulario de la lápida para descartarlo.
        if self.apagadas:
            parte["apagadas"] = sorted(p.nombre for p in self.apagadas)
        return parte


def _esta_apagada(fila: Optional[dict]) -> bool:
    """¿El usuario desconectó esta entidad? (§4)

    Pregunta SEPARADA de `_por_que_no_sirve`, y separada a propósito: una es «¿puedo?» y
    la otra es «¿debo?». Mezclarlas haría que apagar una pieza la mandara al fallback, o
    sea que revivera por el `.mcp.json` — exactamente lo contrario de una lápida.

    Sin fila no hay lápida: una entidad que el registro no conoce nunca se apagó. Cae al
    camino viejo como siempre, con motivo `fila_ausente`.

    `habilitado` llega ya convertido a bool por `conexiones_repo._de_columna`; el `is False`
    no serviría acá porque un lector crudo puede traer el `0` del INTEGER. Se pregunta por
    la falsedad del valor SÓLO cuando la clave existe: una fila vieja sin la columna no
    está apagada, está sin migrar.
    """
    if not fila or "habilitado" not in fila:
        return False
    return not fila.get("habilitado")


def _por_que_no_sirve(fila: Optional[dict]) -> Optional[str]:
    """El motivo por el que esta fila NO se puede ejecutar, o `None` si sirve.

    Un solo lugar decide qué es «incompleta», para que no haya dos criterios. Lo que
    **no** la hace incompleta: `cwd`, `timeout_ms`, `era` y `version_negociada` vacíos —
    son los cuatro que el backfill dejó vacíos a propósito porque ninguna fuente de hoy
    los tiene. Vacío por diseño ≠ falta un dato.
    """
    if not fila:
        return FILA_AUSENTE

    if fila.get("recipe_version") not in RECIPE_VERSIONS_EJECUTABLES:
        # La creó un Aleph más nuevo (§1): ni se levanta ni se descarta. Acá "no se
        # levanta" significa caer al camino viejo, que sí sabemos ejecutar.
        return VERSION_DESCONOCIDA

    transporte = fila.get("transporte")
    if transporte == "stdio":
        if not (fila.get("command") or "").strip():
            return SIN_COMANDO
        # `cwd` YA se honra: `MCPServer` lo acepta y lo pasa a Popen (v4). Antes esto caía
        # al fallback porque el ejecutor no podía ejecutar lo que el registro declaraba.
        return None

    if transporte == "http":
        # El registro YA guarda la receta HTTP (url + headers_template/publico, v4). Lo que
        # falta es EJECUTARLA: en Aleph un MCP por HTTP corre como PUENTE STDIO
        # (`byo_mcp_server.py <manifest.json>`), así que restaurarlo pide regenerar ese
        # manifest y spawnear el puente — plomería que no está cableada acá. Cae al camino
        # viejo, que sí sabe hacerlo, y el motivo lo dice.
        return HTTP_POR_PUENTE_NO_CABLEADO

    return TRANSPORTE_INDEFINIDO


def _cfg_desde_fila(fila: dict, env_efectivo: Callable[[dict], dict]) -> dict:
    """Fila del registro → el mismo dict-forma-.mcp.json que consume el expansor.

    Pasar por la MISMA función de expansión que el camino viejo es deliberado: garantiza
    que `${PUPPET_BELTS}` y compañía se resuelvan igual por los dos caminos. Si se
    expandiera acá a mano, los dos caminos podrían divergir sin que nadie lo note.
    """
    return {
        "command": fila.get("command") or "",
        "args": list(fila.get("args") or []),
        # env_efectivo junta env_publico + env_template (§2). Los `${VAR}` salen SIN
        # resolver: los resuelve el expansor contra base_env, que ya trae las credenciales
        # del run. El registro nunca toca un secreto.
        "env": env_efectivo(fila),
    }


def _timeout_de(fila: Optional[dict], default_s: float) -> float:
    """`timeout_ms` de la fila → segundos. Vacío (lo normal hoy) → el default de siempre."""
    if not fila:
        return default_s
    ms = fila.get("timeout_ms")
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return default_s
    return ms / 1000.0 if ms > 0 else default_s


def _levantar_una(nombre: str, scfg_viejo: dict, base_env: dict, *,
                  fila: Optional[dict],
                  motivo_fallback: Optional[str],
                  expandir: Callable[[dict, dict], tuple],
                  env_efectivo: Callable[[dict], dict],
                  mcp_server_cls: Any,
                  rpc_timeout_default: float) -> PiezaRestaurada:
    """Levanta UNA pieza. Nunca lanza: todo fallo vuelve como parte, con su stderr."""
    t0 = time.monotonic()
    usa_registro = motivo_fallback is None and fila is not None
    pieza = PiezaRestaurada(nombre=nombre,
                            fuente="registro" if usa_registro else "fallback",
                            motivo_fallback=motivo_fallback)
    try:
        cfg = _cfg_desde_fila(fila, env_efectivo) if usa_registro else scfg_viejo
        command, args, srv_env = expandir(cfg, base_env)
        # `cwd` sale de la fila y SOLO de la fila: el bloque viejo del .mcp.json no lo
        # declara (el formato no lo tiene), así que por el camino de fallback es None.
        srv = mcp_server_cls(nombre, command, args, env=srv_env,
                             rpc_timeout=_timeout_de(fila if usa_registro else None,
                                                     rpc_timeout_default),
                             cwd=((fila.get("cwd") or None) if usa_registro else None))
        arrancado = srv.start()
        pieza.arrancado = bool(arrancado)
        if arrancado:
            pieza.servidor = srv
        else:
            # EL PUNTO: sin el stderr del hijo, «no arrancó» no dice nada en la máquina de
            # un usuario. `MCPServer.diagnostico()` ya lo captura con caps — se usa, no se
            # reescribe.
            diag = {}
            try:
                diag = srv.diagnostico() or {}
            except Exception:                      # noqa: BLE001 — frontera del parte
                pass
            pieza.stderr = str(diag.get("stderr") or "")
            pieza.exit_code = diag.get("exit_code")
            pieza.error = str(diag.get("detail") or "") or "el servidor no completó el saludo MCP"
    except Exception as e:                          # noqa: BLE001 — una pieza no tumba al resto
        pieza.arrancado = False
        pieza.error = f"{type(e).__name__}: {e}"
    pieza.ms = int((time.monotonic() - t0) * 1000)
    return pieza


def restaurar_servers(servers_raw: dict, base_env: dict, *,
                      expandir: Callable[[dict, dict], tuple],
                      mcp_server_cls: Any,
                      leer_entidad: Optional[Callable[[str], Optional[dict]]] = None,
                      env_efectivo: Optional[Callable[[dict], dict]] = None,
                      rpc_timeout_default: float = 30.0,
                      max_paralelo: int = _MAX_PARALELO) -> Restauracion:
    """Levanta todas las piezas EN PARALELO, best-effort, con parte por pieza.

    Args:
        servers_raw: `{nombre: cfg}` del belt — la fuente VIEJA, que sigue siendo el
            fallback de cada pieza.
        base_env: el entorno del run contra el que se expanden los `${VAR}`.
        expandir: `_expand_server_cfg` — la MISMA para los dos caminos.
        mcp_server_cls: la clase del cliente (inyectada para poder testear sin spawnear).
        leer_entidad: `(entity_id) -> fila | None`. `None` = sin registro → todo fallback.
        env_efectivo: `conexiones_repo.env_efectivo` — junta env_publico + env_template.

    Una pieza que falla NO tumba a las otras: cada una vuelve con su veredicto.
    """
    nombres = list(servers_raw.keys())
    if not nombres:
        return Restauracion()

    # Fase 1 — decidir la fuente de cada pieza. Barato y secuencial: es leer la DB.
    # Se hace ANTES del pool para que el parte diga qué se leyó del registro aunque una
    # pieza no llegue a arrancar.
    res = Restauracion()
    plan: dict[str, tuple[Optional[dict], Optional[str]]] = {}
    for nombre in nombres:
        if leer_entidad is None or env_efectivo is None:
            plan[nombre] = (None, SIN_REGISTRO)
            continue
        try:
            fila = leer_entidad(nombre)
        except Exception:                           # noqa: BLE001 — el registro no puede
            plan[nombre] = (None, SIN_REGISTRO)     # tumbar el arranque: cae al camino viejo
            continue
        # LA LÁPIDA (§4) se resuelve ACÁ, antes que nada. La pieza queda con su parte y
        # NUNCA entra al pool: no se levanta ni por el registro ni por el `.mcp.json`.
        if _esta_apagada(fila):
            res.piezas.append(PiezaRestaurada(nombre, FUENTE_LAPIDA, apagada=True))
            continue
        plan[nombre] = (fila, _por_que_no_sirve(fila))

    # Fase 2 — levantar EN PARALELO. El costo de una pieza es esperar su `initialize`.
    # Sólo las que sobrevivieron la lápida: `plan` ya no las tiene.
    if plan:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(max_paralelo, len(plan)),
                thread_name_prefix="restaurar") as ex:
            futuros = {
                ex.submit(_levantar_una, nombre, servers_raw[nombre], base_env,
                          fila=plan[nombre][0], motivo_fallback=plan[nombre][1],
                          expandir=expandir, env_efectivo=env_efectivo,
                          mcp_server_cls=mcp_server_cls,
                          rpc_timeout_default=rpc_timeout_default): nombre
                for nombre in plan
            }
            for fut in concurrent.futures.as_completed(futuros):
                res.piezas.append(fut.result())

    res.piezas.sort(key=lambda p: p.nombre)
    return res


__all__ = [
    "restaurar_servers", "Restauracion", "PiezaRestaurada",
    "RECIPE_VERSIONS_EJECUTABLES",
    "SIN_REGISTRO", "FILA_AUSENTE", "VERSION_DESCONOCIDA", "SIN_COMANDO",
    "TRANSPORTE_INDEFINIDO", "HTTP_POR_PUENTE_NO_CABLEADO",
    "APAGADA", "FUENTE_LAPIDA",
]
