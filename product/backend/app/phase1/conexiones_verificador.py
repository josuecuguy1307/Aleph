"""
conexiones_verificador.py — MIDE los conectores y llena el registro. Dos preguntas, dos
respuestas, dos columnas.

    conexion    ¿el camino Aleph → server → servicio funciona?
                Se mide en TODOS los que arrancan, con o sin llave.
                ⚠️ Un 401 es CONEXIÓN VIVA: el mensaje viajó y el servicio contestó. Que la
                credencial no sirva es la OTRA pregunta.
    credencial  ¿la llave del usuario sirve?
                Sólo se declara VERDE con la prueba DOBLE (llave real + basura).

Separarlas no es prolijidad: un 401 responde «sí» a la primera y «no» a la segunda, y
guardarlas en una sola columna obliga a elegir cuál de las dos verdades se pierde. Eso es
lo que hacía que un servidor con la llave vencida se viera igual que uno que no arranca.

⚠️ CERO EFECTO EXTERNO. Sólo se llaman tools de LECTURA, y la basura de credencial viaja
SIEMPRE en el `env` del proceso hijo — nunca se escribe al llavero. La selección de tools
excluye por SCHEMA lo que puede tener efecto aunque el servidor jure que no: el caso índice
es `coingecko.execute`, anunciada `readOnlyHint: true` con un parámetro
`code: "Code to execute"`. Las anotaciones del spec MCP son EVIDENCIA, jamás permiso.

Correr:
    python3 product/backend/app/phase1/conexiones_verificador.py            # DRY-RUN
    python3 product/backend/app/phase1/conexiones_verificador.py --aplicar  # persiste
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: Lo que se le manda a un servidor cuando la llave no importa (paso 2) o cuando se quiere
#: ver si la rechaza (paso 3). NUNCA toca el llavero: viaja en el env del hijo y muere con él.
BASURA = "clave-falsa-de-prueba-0000"

#: Cuántas tools se prueban por conector. Una alcanza para saber si el canal vive; tres es
#: el techo para que un servidor con 33 tools no cueste 33 llamadas.
MIN_TOOLS, MAX_TOOLS = 1, 3

#: Parámetros que hacen que una tool NO sirva para sondear, diga lo que diga su hint. No es
#: una lista de «tools peligrosas» sino de FORMAS: si lo que hay que llenar es código, SQL,
#: una ruta o un identificador exacto, inventarlo es inventar efecto.
_PARAM_PROHIBIDO = re.compile(
    r"^(code|sql|script|command|cmd|body|payload|path|file|filename|dir|directory"
    r"|url|uri|endpoint|.*_id|id)$", re.I)

#: Y el nombre/descripción que huele a escritura. El hint del servidor puede estar mal
#: —medido—, así que esto se aplica ADEMÁS del hint, nunca en su lugar.
_HUELE_A_ESCRITURA = re.compile(
    r"(send|create|delete|remove|post|publish|write|update|insert|upload|rename|move"
    r"|execute|run_|exec|drop|truncate|mail|issue|commit|merge|push|pay|order|buy|sell)",
    re.I)

#: Un `required` de tipo string que se puede llenar con algo inerte. Una búsqueda no tiene
#: efecto; un destinatario sí.
_PARAM_RELLENABLE = re.compile(r"^(query|q|search|term|texto|text|name|libraryname|keyword"
                               r"|topic|language|lang)$", re.I)
_RELLENO = {"query": "aleph", "q": "aleph", "search": "aleph", "term": "aleph",
            "texto": "aleph", "text": "aleph", "name": "aleph", "libraryname": "react",
            "keyword": "aleph", "topic": "aleph", "language": "python", "lang": "en"}

# ── estados ──────────────────────────────────────────────────────────────────────
VIVA, ROTA = "viva", "rota"
#: TERCER ESTADO, y hace falta: el server arrancó y publicó tools, pero ninguna se puede
#: llamar sin inventar un argumento con posible efecto (código, ruta, SQL, un id exacto).
#: No es ROTA — el canal nunca se ejercitó. Medido: 14 de 62 caen acá (pysandbox, pandoc,
#: chart, excel…), y llamarlos rotos sería reportar NUESTRA incapacidad de medir como una
#: falla del servidor, que es exactamente el error que este trabajo viene corrigiendo.
SIN_SONDEAR = "sin_sondear"
VERDE, RECHAZADA, CANDIDATA, NO_APLICA, SIN_MEDIR = (
    "verde", "rechazada", "candidata", "no_aplica", "sin_medir")

# ── causas tipadas ───────────────────────────────────────────────────────────────
C_ARRANQUE = "arranque"                  # el proceso no llegó a hablar MCP
C_SIN_TOOLS = "sin_tools"                # arrancó y no publica nada usable
C_SIN_CANDIDATA = "sin_tool_sondeable"   # publica tools pero ninguna se puede llamar a ciegas
C_TIMEOUT = "timeout"
C_SIN_RESPUESTA = "sin_respuesta"


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _corto(x: Any, n: int = 220) -> str:
    return " ".join(str(x or "").split())[:n]


# ── 1 · SELECCIÓN DE TOOLS ───────────────────────────────────────────────────────

def _rellenar(schema: dict) -> Optional[dict]:
    """Argumentos inertes para una tool, o `None` si no se puede llenar sin inventar.

    Devolver `None` es una respuesta legítima y frecuente: `massive.call_api` pide un
    `path` y `context7.query-docs` un `libraryId` exacto. Adivinarlos es adivinar efecto.
    """
    req = (schema or {}).get("required") or []
    props = (schema or {}).get("properties") or {}
    args: dict = {}
    for nombre in req:
        if _PARAM_PROHIBIDO.match(str(nombre)):
            return None
        tipo = (props.get(nombre) or {}).get("type")
        if _PARAM_RELLENABLE.match(str(nombre)) and tipo in (None, "string"):
            args[nombre] = _RELLENO.get(str(nombre).lower(), "aleph")
        else:
            return None                  # required que no sabemos llenar sin inventar
    return args


def elegir_tools(tools: list, declarada: Optional[dict] = None,
                 sonda: Optional[dict] = None) -> list:
    """Las tools que se van a llamar, en orden. Entre 0 y MAX_TOOLS.

    Orden de preferencia, y el primero corta:
      a. la que el catálogo YA declaró para probar credencial — esa, sola.
      b. la SONDA DECLARADA del catálogo (`tool_sonda`/`args_sonda`) — esa, sola.
      c. las de lectura que se puedan llamar sin inventar nada.

    ⚠️ (b) NO es una excepción a «el guard no inventa» (CLAUDE.md): es su contracara. El
    guard sigue sin fabricar un solo argumento — los de la sonda vienen DECLARADOS en la
    receta, con autor y motivo, y restringidos a territorio propio o constante neutra.
    Existe porque hay servidores sanos cuyas tools TODAS piden algo que no se puede
    adivinar: `git` publica 12 y las 12 quieren `repo_path`; `fetch` publica una y quiere
    `url`. Sin declaración quedaban «sin sondear» para siempre, que es honesto pero
    inútil.

    `readOnlyHint` ordena pero NO excluye: quince de los veinte servidores que arrancan no
    anotan nada (medido), así que exigirlo dejaría casi todo sin sondear. La exclusión dura
    la hace el SCHEMA, que no depende de que el servidor sea honesto.
    """
    por_nombre = {t.get("name"): t for t in (tools or []) if t.get("name")}
    if declarada and declarada.get("tool") in por_nombre:
        return [{"name": declarada["tool"], "args": dict(declarada.get("args") or {}),
                 "origen": "declarada"}]
    if sonda and sonda.get("tool") in por_nombre:
        return [{"name": sonda["tool"], "args": dict(sonda.get("args") or {}),
                 "origen": "sonda_declarada"}]

    candidatas = []
    for t in tools or []:
        nombre = t.get("name")
        if not nombre:
            continue
        if _HUELE_A_ESCRITURA.search(f"{nombre} {t.get('description') or ''}"):
            continue
        args = _rellenar(t.get("inputSchema") or {})
        if args is None:
            continue
        anot = t.get("annotations") or {}
        if anot.get("destructiveHint") is True:
            continue
        candidatas.append({
            "name": nombre, "args": args, "origen": "elegida",
            # sin args > con args; anotada read-only > sin anotar. Sólo ordena.
            "_orden": (0 if not args else 1, 0 if anot.get("readOnlyHint") is True else 1),
        })
    candidatas.sort(key=lambda c: c["_orden"])
    for c in candidatas:
        c.pop("_orden", None)
    return candidatas[:MAX_TOOLS]


# ── 2 · VEREDICTO DE CONEXIÓN ────────────────────────────────────────────────────

def _traductor():
    """`traductor_errores` — la capa que convierte la taxonomía del transporte en NUESTRAS
    causas tipadas. Perezoso y por nombre (no `spec_from_file_location`): `platform/inspection`
    ya está en `sys.path` desde el encabezado de este módulo, y compartir la instancia de
    `sys.modules` evita tener dos copias del traductor con dos criterios."""
    import traductor_errores                                # noqa: E402
    return traductor_errores


def veredicto_conexion(salidas: list) -> dict:
    """`{estado, causa, tool_usada, evidencia}` a partir de lo que devolvieron las tools.

    ⚠️ LA REGLA QUE SEPARA LAS DOS PREGUNTAS: un 401 es conexión **VIVA**. El proceso
    arrancó, habló MCP, el mensaje llegó al servicio y el servicio contestó — todo el camino
    funciona. Que la credencial no sirva es la otra medición, en la otra columna. Tratarlo
    como conexión rota haría que «tu llave venció» se viera igual que «este server no
    arranca», que son dos problemas con dos soluciones distintas.

    LA LÓGICA NO CAMBIÓ; CAMBIÓ LA FUENTE. Antes «¿contestó?» se decidía con dos regexes
    sobre el texto de la salida. Ahora lo decide `traductor_errores`, que lee el código
    JSON-RPC cuando el transporte lo tipa y cae a las mismas palabras cuando no —así un
    registro escrito por el cliente viejo se sigue leyendo igual. Los estados, las causas y
    el veredicto son exactamente los de antes.

    POR QUÉ HIZO FALTA, medido: el cliente viejo decía «[MCP error: no response from X]»
    ante un server muerto y la regex lo cazaba por «no response». El SDK dice «[MCP error:
    {'code': -32000, 'message': 'Connection closed'}]», que NO matchea ninguna de esas
    palabras («connection reset» estaba en la regex; «connection closed» no) → el texto no
    estaba vacío → **el server muerto se reportaba VIVO**. Silencioso y en la dirección
    peor. `test_traductor_errores.py::test_un_server_muerto_no_se_reporta_vivo` lo fija.

    (El viejo `_CONTESTO` —401|forbidden|quota|error…— se retiró: iba en un `or` detrás de
    `texto.strip()`, que ya es verdadero para todo texto no vacío, así que no decidía nada.
    Una regex que nunca cambia una respuesta sólo sirve para hacer creer que sí.)
    """
    if not salidas:
        return {"estado": SIN_SONDEAR, "causa": C_SIN_CANDIDATA, "tool_usada": None,
                "evidencia": "publica tools pero ninguna se puede llamar sin inventar "
                             "argumentos con posible efecto"}
    TR = _traductor()
    for s in salidas:
        texto = str(s.get("salida") or "")
        if not TR.contesto(texto):
            continue
        return {"estado": VIVA, "causa": None, "tool_usada": s["tool"],
                "evidencia": _corto(texto)}
    peor = salidas[0]
    texto = str(peor.get("salida") or "")
    return {"estado": ROTA, "causa": TR.causa_de_corte(texto), "tool_usada": peor["tool"],
            "evidencia": _corto(texto)}


# ── 3 · VEREDICTO DE CREDENCIAL ──────────────────────────────────────────────────

def veredicto_credencial(*, pide_llave: bool, hay_llave_real: bool,
                         con_real: Optional[dict] = None,
                         con_basura: Optional[dict] = None,
                         tool: Optional[str] = None) -> dict:
    """Las tres poblaciones del diseño. VERDE sólo por doble completa.

      A · con llave real   real da dato Y basura da rechazo → la tool CERTIFICA → verde.
                           Cualquier otra combinación → no se declara, y se dice por qué.
      B · sin llave real   sólo se puede correr la basura. Si rechaza, la tool queda
                           CANDIDATA (condición necesaria, no suficiente): no alcanza para
                           declarar porque no sabemos que responda bien con una llave buena,
                           y declararla produciría falsos rojos. Si ACEPTA la basura, queda
                           descartada — ésa sí es una conclusión firme.
      C · no pide llave    NO_APLICA. El verde de conexión es el verde total.
    """
    if not pide_llave:
        return {"estado": NO_APLICA, "tool_prueba": None, "ts": _ahora(),
                "evidencia": "este servidor no pide credencial"}

    rechaza_basura = bool(con_basura and con_basura.get("rechazada"))
    acepta_basura = bool(con_basura and con_basura.get("ok"))

    if hay_llave_real:
        real_ok = bool(con_real and con_real.get("ok"))
        if real_ok and rechaza_basura:
            return {"estado": VERDE, "tool_prueba": tool, "ts": _ahora(),
                    "evidencia": f"«{tool}» dio dato con tu llave y rechazo con basura"}
        if real_ok and acepta_basura:
            return {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                    "evidencia": f"«{tool}» devuelve lo mismo con llave buena y con basura: "
                                 f"no ejercita la credencial"}
        if con_real and not real_ok and (con_real or {}).get("rechazada"):
            return {"estado": RECHAZADA, "tool_prueba": tool, "ts": _ahora(),
                    "evidencia": _corto((con_real or {}).get("muestra"))}
        return {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                "evidencia": _corto((con_real or {}).get("detalle")
                                    or "la prueba doble no concluyó")}

    if acepta_basura:
        return {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                "evidencia": f"«{tool}» acepta una llave basura: descartada como sonda"}
    if rechaza_basura:
        return {"estado": CANDIDATA, "tool_prueba": tool, "ts": _ahora(),
                "evidencia": f"«{tool}» rechaza una llave basura — falta confirmar con una "
                             f"llave real que responda bien"}
    return {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
            "evidencia": "sin llave real y sin rechazo claro con basura"}


__all__ = [
    "elegir_tools", "veredicto_conexion", "veredicto_credencial",
    "BASURA", "VIVA", "ROTA", "SIN_SONDEAR", "VERDE", "RECHAZADA", "CANDIDATA", "NO_APLICA", "SIN_MEDIR",
    "C_ARRANQUE", "C_SIN_TOOLS", "C_SIN_CANDIDATA", "C_TIMEOUT", "C_SIN_RESPUESTA",
    "ERA_HANDSHAKE", "ERA_DISCOVER",
]


# ══════════════════════════════════════════════════════════════════════════════════
# EL CORREDOR — spawnea, mide y persiste
# ══════════════════════════════════════════════════════════════════════════════════

def _mv():
    from app.phase1 import motor_verdad
    return motor_verdad


def _entradas() -> list:
    """Los `(belt_ref, server)` del catálogo. Es la misma llave con la que el registro
    identifica una entidad (`entity_id` = nombre del server)."""
    import aleph_paths
    root = aleph_paths.resource_root()
    vistos, out = set(), []
    for base in ("catalog", "platform"):          # los dos roots que `_spec_de_belt` admite
        for p in sorted((root / base).rglob("*.mcp.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rel = str(p.relative_to(root))
            for n in (d.get("mcpServers") or {}):
                if n in vistos:                   # una entidad = una fila (§1)
                    continue
                vistos.add(n)
                out.append((rel, n))
    return out


def _pide_llave(spec: dict, entorno: dict) -> bool:
    """El `${VAR}` sin resolver del env ES la declaración de credencial (clase 2)."""
    if spec.get("needs_auth") or spec.get("header_name") or spec.get("package_env_var"):
        return True
    for v in (spec.get("env") or {}).values():
        m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(v).strip())
        if m and m.group(1) not in entorno:
            return True
    return False


class _PrestamoComoServer:
    """Un préstamo del dueño, con la forma que este verificador ya usa.

    El préstamo NO expone `stop()` a propósito (§6.1 del diseño: quien pide no mata), pero
    el verificador tiene cuatro `srv.stop()` que significan «terminé con esto». Traducir uno
    en el otro es exactamente lo que quiere decir: **`stop()` acá es `soltar()`**. Con la
    retención de D1 en cero, soltar cierra el proceso — o sea que el ciclo de vida queda
    idéntico al de hoy y este paso es puro cambio de dueño del spawn.
    """

    def __init__(self, prestamo):
        self._p = prestamo

    def list_tools(self):
        return self._p.list_tools()

    def call_tool(self, tool_name, arguments):
        return self._p.call_tool(tool_name, arguments)

    def diagnostico(self) -> dict:
        return self._p.diagnostico()

    def stop(self) -> None:
        self._p.soltar()


def _dueno():
    import dueno                                           # noqa: E402
    return dueno


_ra_mod = None


def _ra():
    """`recipe_assembler`, que es quien DEFINE cómo un `${VAR}` se convierte en provider.

    ⚠️ POR RUTA, NO POR `import` A SECAS — y la diferencia son 21,8 s de arranque y 12
    conectores que no se podían mirar.

    Esto hacía `sys.path.insert(_RAIZ/"platform"/"assembler")` + `import recipe_assembler`.
    Bajo PyInstaller el `FrozenImporter` del PYZ **precede a `sys.path`**, así que ganaba la
    copia congelada y su `__file__` quedaba en `<_MEIPASS>/recipe_assembler.py` — un archivo
    que no existe. Río abajo, `recipe_assembler.py:74` hace
    `_THIS_DIR = Path(__file__).resolve().parent` y `:91` `_THIS_DIR / "assembler.py"`, o sea
    `<_MEIPASS>/assembler.py`. MEDIDO contra la `.app` instalada `d80109bb…`, en el
    `[local] barrido de arranque` de cada boot:

        [local] ✗ gmail: FileNotFoundError: [Errno 2] .../_MEIxKTYKb/assembler.py
        (igual: zotero · alphavantage · coingecko · fred · massive · github ·
         huggingface · secedgar · materialsproject · context7 · exa)

    Doce piezas del usuario reportadas como no verificables por un archivo NUESTRO mal
    ubicado. La ruta correcta existe en el bundle:
    `<_MEIPASS>/platform/assembler/recipe_assembler.py`.

    EL REMEDIO NO ES NUEVO: es el de `platform/inspection/byo_mcp.py:42-55`, que documenta
    este mismo bug —`Path(__file__).parents[N]` bajo frozen apunta afuera— y lo cerró con
    `aleph_paths.resource_root()`. Se aplica ése, con el mismo `load_module_by_path` que ya
    usa `centro_conexiones.py:647` para cargar exactamente este módulo. Fuera de frozen
    `resource_root()` devuelve la raíz del repo: comportamiento idéntico al anterior.

    Se cachea porque `load_module_by_path` ejecuta el módulo: sin esto, un barrido de 35
    conectores lo ejecutaría 35 veces.
    """
    global _ra_mod
    if _ra_mod is None:
        import aleph_paths
        _ra_mod = aleph_paths.load_module_by_path(
            "puppet_recipe_assembler_conexiones_verificador",
            aleph_paths.resource_root() / "platform" / "assembler" / "recipe_assembler.py")
    return _ra_mod


def _providers_por_var(spec: dict) -> dict:
    """`{VAR: provider}` para cada credencial que la receta declara. **Sin tabla propia.**

    ⚠️ ESTE ES EL PUNTO DE TODO EL ARREGLO, así que vale decir por qué no hay un diccionario
    acá. El run YA sabe traducir `ONSHAPE_ACCESS_TOKEN → onshape` y
    `ONSHAPE_OAUTH_META → onshape__oauth`: es `_autofill_recipe_keys`
    (`recipe_assembler.py:804-821`), y esas reglas son por SUFIJO —`_API_KEY`,
    `_ACCESS_TOKEN`, `_OAUTH_META`— o sea genéricas para cualquier conector, presente o
    futuro. Copiarlas acá sería tener dos verdades sobre lo mismo y garantizar que un día
    disientan; y el verificador que mide otra cosa que la que el run inyecta es exactamente
    el bug que esto cierra. Se le pregunta a la fuente, una variable por vez.
    """
    RA = _ra()
    out = {}
    for v in (spec.get("env") or {}).values():
        m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(v).strip())
        if not m:
            continue
        var = m.group(1)
        try:
            provs = RA._autofill_recipe_keys({}, {"_": {"env": {"_": "${" + var + "}"}}})
        except Exception:                                 # noqa: BLE001 — frontera
            continue
        if provs:
            out[var] = next(iter(provs))
    return out


def _credenciales_por_var(spec: dict, owner: Optional[str], get_conn) -> dict:
    """`{VAR: valor}` resuelto del vault, con el MISMO resolver que usa un run.

    Antes de esto el verificador resolvía UNA sola credencial —`spec["connector"]`— y
    `_spawn` la copiaba en TODOS los `${VAR}` de la receta. Para una pieza con llave sola
    eso alcanzaba; para el tipo OAuth es directamente falso: `ONSHAPE_OAUTH_META` recibía
    el **access token** en vez de su JSON de estado y scopes, así que el server arrancaba,
    no reconocía ningún scope concedido y publicaba CERO tools. El barrido lo anotaba
    `rota/sin_tools` y la card lo mostraba rojo **mientras la pieza funcionaba** — medido:
    por el camino de producción publica 6 tools y `onshape_whoami` contesta.

    El resolver es el de producción (`make_user_resolver`), así que esto hereda gratis lo
    que ya sabe hacer: aislamiento por usuario, cuenta borrada que no re-resuelve, y el
    **refresh server-side** de un access_token vencido. Un verificador con su propia lectura
    del vault se habría quedado sin las tres.
    """
    if not owner or get_conn is None:
        return {}
    try:
        from app.phase1.credential_broker import make_user_resolver
        resolver = make_user_resolver(owner, get_conn=get_conn)
    except Exception:                                     # noqa: BLE001 — frontera
        return {}
    out = {}
    for var, provider in _providers_por_var(spec).items():
        try:
            val = resolver(provider) or ""
        except Exception:                                 # noqa: BLE001
            val = ""
        if val:
            out[var] = val
    return out


def _spawn(spec: dict, entorno: dict, llave: str, *,
           entity_id: str = "verificador", user_id: Optional[str] = None,
           efimero: bool = False, por_var: Optional[dict] = None):
    """Levanta el server con `llave` en cada `${VAR}` de credencial. Devuelve (srv, tools)
    o (None, motivo).

    `por_var` gana sobre `llave` variable por variable. Es lo que hace medible al tipo
    OAuth, donde las credenciales de una misma pieza **no son la misma cosa** (un token y su
    JSON de estado). Sin `por_var` el comportamiento es idéntico al de siempre — y la sonda
    de basura lo omite a propósito: si le pasáramos los valores reales, la prueba de
    credencial estaría comparando la llave real contra sí misma.

    QUIÉN SPAWNEA (D1 del dueño): con `ALEPH_DUENO=on` se le PIDE al dueño y él es el que
    posee el proceso; sin la perilla, se spawnea acá como siempre. Los dos caminos usan el
    MISMO transporte (`transporte.servidor_stdio()`) y devuelven la misma forma, así que el
    veredicto no puede cambiar — y eso es lo que mide `verify_migracion_stdio.py`.
    """
    MV = _mv()
    # EL TRANSPORTE LO ELIGE `transporte` (sesión 2): el puente al SDK por default, el
    # cliente viejo con ALEPH_TRANSPORTE=viejo. Misma firma, mismos métodos — el
    # verificador no puede notar cuál le tocó, y por eso la elección viaja en la evidencia.
    import transporte as TP                                # noqa: E402

    runtime_names = {"PUPPET_WORKDIR", "PUPPET_BELTS", "PUPPET_REPO",
                     "PUPPET_LANG", "PUPPET_PKG", "PUPPET_SHARED_MEMORY"}
    # _entorno_de_belts() includes the sidecar's ambient environment for older
    # diagnostics. It must never be the expansion source for an MCP child.
    sub = {k: v for k, v in entorno.items() if k in runtime_names}
    porv = por_var or {}
    credential_vars = set(_providers_por_var(spec)) | set(porv)
    for k, v in (spec.get("env") or {}).items():
        m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(v).strip())
        if m and m.group(1) in credential_vars and m.group(1) not in sub:
            sub[m.group(1)] = porv.get(m.group(1), llave)
    from inspection.transporte_sdk import entorno_hijo
    env = entorno_hijo(sub)
    env.update({k: MV._expandir(str(v), sub) for k, v in (spec.get("env") or {}).items()})
    declaradas = list((spec.get("env") or {}).keys())
    if spec.get("package_env_var"):
        env[spec["package_env_var"]] = llave
        # La var del paquete la mete la sonda, no la receta, pero el hijo la RECIBE y la
        # lee: si no entra en la huella, la sonda con llave real y la sonda con basura
        # tendrían la MISMA — y compartirían proceso. Cuenta como declarada.
        declaradas.append(spec["package_env_var"])

    comando = MV._expandir(spec.get("command") or "", env)
    args = [MV._expandir(str(a), env) for a in (spec.get("args") or [])]

    DU = _dueno()
    if DU.encendido():
        # §9.2 · la MISMA marca que pone el run (`_expand_server_cfg`). Que los dos caminos
        # marquen igual es la condición de que una pieza calentada por acá sea REUSABLE por
        # un run: si sólo uno marcara, las huellas seguirían sin encontrarse — que es
        # exactamente el §6 que esto viene a cerrar.
        env_marcado = getattr(DU, "EnvDelHijo", dict)(env, declaradas=declaradas) \
            if hasattr(DU, "EnvDelHijo") else env
        try:
            prestamo = DU.actual().pedir(
                entity_id, user_id=user_id, motivo="verificador", efimero=efimero,
                spec={"command": comando, "args": args, "env": env_marcado,
                      "cwd": spec.get("cwd"), "rpc_timeout": 45})
        except DU.DuenoError as e:
            return None, _corto(str(e), 300)
        except Exception as e:                    # noqa: BLE001 — frontera del verificador
            return None, f"{type(e).__name__}: {_corto(e, 200)}"
        srv = _PrestamoComoServer(prestamo)
        try:
            return srv, (srv.list_tools() or [])
        except Exception as e:                    # noqa: BLE001
            srv.stop()
            return None, f"{type(e).__name__}: {_corto(e, 200)}"

    srv = TP.servidor_stdio()("verificador", comando, args, env=env, rpc_timeout=45)
    try:
        if not srv.start():
            diag = srv.diagnostico() or {}
            try: srv.stop()
            except Exception: pass
            return None, _corto(diag.get("stderr") or diag.get("detail") or "no arrancó", 300)
        return srv, (srv.list_tools() or [])
    except Exception as e:                        # noqa: BLE001 — frontera del verificador
        try: srv.stop()
        except Exception: pass
        return None, f"{type(e).__name__}: {_corto(e, 200)}"


def _llamar(srv, elegidas: list) -> list:
    salidas = []
    for t in elegidas:
        try:
            salidas.append({"tool": t["name"], "args": t["args"],
                            "salida": str(srv.call_tool(t["name"], t["args"]))})
        except Exception as e:                    # noqa: BLE001
            salidas.append({"tool": t["name"], "args": t["args"],
                            "salida": f"[mcp error] {type(e).__name__}: {e}"})
    return salidas


def _clasificar(texto: str) -> dict:
    """Reusa EL MISMO detector del 4º requisito (clase 2), para no tener dos criterios de
    «esto es un rechazo de credencial» que puedan divergir."""
    import byo_mcp
    class _Uno:
        def __init__(s, t): s.t = t
        def call_tool(s, *_a, **_k): return s.t
    return byo_mcp._ejercitar_credencial(_Uno(texto), [{"name": "x"}],
                                         {"tool": "x", "args": {}}) or {}


def _sonda_expandida(spec: dict, entorno: dict) -> Optional[dict]:
    """`{tool, args}` de la sonda declarada, con los `${VAR}` YA resueltos.

    ⚠️ LA EXPANSIÓN NO ES UN DETALLE: sin ella la clase «territorio propio» de la ley no se
    puede declarar. Un `repo_path` literal funcionaría en la máquina del que lo escribió y
    en ninguna otra, que es exactamente lo que la ley prohíbe. Se expande contra el MISMO
    entorno con el que se spawnea el server (`_entorno_de_belts`), así que la sonda apunta
    al mismo territorio que el proceso — no a otro.
    """
    tool = str((spec.get("tool_sonda") or "")).strip()
    if not tool:
        return None
    MV = _mv()
    args = spec.get("args_sonda") if isinstance(spec.get("args_sonda"), dict) else {}
    return {"tool": tool,
            "args": {k: (MV._expandir(v, entorno) if isinstance(v, str) else v)
                     for k, v in args.items()}}


#: Las dos eras del protocolo MCP (§1). El cliente propio sólo habla la primera —
#: `server/discover` tiene cero implementación en el árbol— así que hoy la era medida es
#: siempre `handshake`. Se persiste igual: el día que exista la otra, la columna dice cuál
#: hablaba cada server y el restore no tiene que redescubrirlo.
ERA_HANDSHAKE = "handshake"          # initialize + notifications/initialized (pre 2026-07-28)
ERA_DISCOVER = "discover"            # server/discover (post 2026-07-28)


def _era_de(srv) -> dict:
    """`{era, version_negociada}` de un server que YA saludó. Vacío si no se pudo leer."""
    try:
        proto = (srv.diagnostico() or {}).get("protocolo") or {}
    except Exception:                              # noqa: BLE001 — evidencia, no veredicto
        return {}
    if not proto:
        return {}
    out = {"era": ERA_HANDSHAKE}
    v = proto.get("servidor") or proto.get("negociada") or proto.get("cliente")
    if v:
        out["version_negociada"] = str(v)
    return out


def _con_reserva_visible(fila: dict, *, owner: Optional[str], get_conn) -> dict:
    """Conserva el vocabulario de causas y añade el aviso que el usuario aceptó al traer.

    La reserva no convierte una conexión sana en rota. Sólo cuando el verificador ya midió
    una falla se adjunta al detalle, para que no parezca una sorpresa en vivo.
    """
    conexion = fila.get("conexion") if isinstance(fila.get("conexion"), dict) else {}
    # La evidencia cambia en cada sonda; la referencia durable vive en la medición misma
    # para que una fila traída siga siendo restaurable y re-verificable después.
    if fila.get("belt"):
        conexion.setdefault("belt_ref", fila["belt"])
    if conexion.get("estado") != ROTA or not owner or get_conn is None:
        return fila
    try:
        from app.phase1 import conexiones_repo as CR
        conn = get_conn()
        try:
            entidad = CR.leer_entidad(conn, owner, str(fila.get("server") or ""))
        finally:
            conn.close()
        reserva = (entidad or {}).get("reserva")
        texto = reserva.get("texto_1linea") if isinstance(reserva, dict) else None
        if texto:
            evidencia = str(conexion.get("evidencia") or "")
            conexion["evidencia"] = (f"{evidencia} · " if evidencia else "") + \
                                    f"Te avisamos al traerla: {texto}"
    except Exception:
        # Una reserva es explicación adicional; no puede ocultar ni cambiar el fallo medido.
        pass
    return fila


def verificar_uno(belt: str, server: str, *, owner: Optional[str], get_conn,
                  solo_conexion: bool = False) -> dict:
    """Los cuatro pasos sobre UNA entidad. Nunca levanta.

    `solo_conexion=True` corre la mitad BARATA: arranca, publica y prueba la conexión, y se
    saltea el segundo spawn de la prueba doble de credencial.

    ⚠️ POR QUÉ EXISTE ESA MITAD. El barrido de arranque re-verifica el catálogo local en
    frío, y la prueba doble cuesta **dos** spawns por pieza: sobre 42 piezas eso convierte
    «abrir Aleph» en una espera de minutos. La conexión es lo que cambia entre un arranque y
    el siguiente —un binario que se borró, un server que ya no levanta—; la credencial no se
    vuelve inválida sola por reiniciar la app.

    Y NO MIENTE: con `solo_conexion` la columna `credencial` se devuelve en `None`, o sea
    «esto no se midió», y quien persista NO la pisa. Escribir `sin_medir` sobre un `verde`
    que sigue siendo cierto sería borrar evidencia buena para ahorrar tiempo.
    """
    MV = _mv()
    fila = {"belt": belt, "server": server, "arranca": False,
            "conexion": None, "credencial": None, "tools_probadas": []}
    try:
        spec = MV._spec_de_belt(belt, server)
    except Exception as e:                        # noqa: BLE001
        fila["conexion"] = {"estado": ROTA, "causa": C_ARRANQUE, "tool_usada": None,
                            "evidencia": _corto(e), "ts": _ahora()}
        return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
    if not spec or spec.get("transport") == "http":
        fila["conexion"] = {"estado": ROTA, "causa": C_ARRANQUE, "tool_usada": None,
                            "evidencia": "transporte http: no cableado por este verificador",
                            "ts": _ahora()}
        return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)

    entorno = MV._entorno_de_belts()
    pide = _pide_llave(spec, entorno)
    real = ""
    if pide and owner and get_conn is not None:
        try:
            from app.phase1.credential_broker import make_user_resolver
            real = make_user_resolver(owner, get_conn=get_conn)(spec.get("connector") or server) or ""
        except Exception:                         # noqa: BLE001
            real = ""

    # LAS CREDENCIALES DE ESTA RECETA, UNA POR UNA. `real` sigue siendo el fallback (y el
    # que decide `hay_llave_real`); esto lo refina donde la receta declara MÁS DE UNA cosa,
    # que es lo normal en OAuth: token por un lado, estado y scopes por otro.
    por_var = _credenciales_por_var(spec, owner, get_conn) if pide else {}
    if por_var and not real:
        # Una pieza puede tener credencial en el vault sin que `spec["connector"]` la
        # nombre. Si la hay, el veredicto tiene que saberlo: sin esto, el paso 3 mediría
        # «población B» (sin llave real) sobre un spawn que SÍ la llevaba.
        real = next(iter(por_var.values()))

    # ── 0 · LO QUE SE SABE SIN SALIR A NINGÚN LADO ──────────────────────────────
    # [TANDA 2 · obra A] La receta PIDE una credencial y el vault NO la tiene. Eso no hay
    # que ir a averiguarlo: ya está respondido acá, en memoria. Esto spawneaba igual, con
    # `BASURA` de secreto, para descubrir un `401` que era predecible — y en un OAuth sin
    # registrar (gmail) el proceso arrancaba y salía a la red para nada.
    #
    # NO ES UN CRITERIO NUEVO: es exactamente el de `motor_verdad.prueba_mcp`
    # (`motor_verdad.py:925-930`, «si la necesita y no la tenemos → FALTA_KEY sin siquiera
    # conectar (honesto)»). El verificador rehacía el flujo y se lo salteaba.
    #
    # MEDIDO sobre el catálogo real de esta máquina: 5 de 47 piezas —coingecko, gmail,
    # massive, materialsproject, secedgar— caían acá. Cinco spawns por barrido, por nada.
    #
    # ⚠️ LA CAUSA LLEVA COPY: `falta_key` ya está en `MV.CAUSAS` y en `CAUSAS_HUMANAS`
    # (`cuarto/cuarto.semaforo.js`), que es el diccionario sellado del semáforo. No se
    # inventa una causa nueva; se usa la que la pantalla ya sabe decir.
    if pide and not real and not por_var:
        fila["conexion"] = {"estado": ROTA, "causa": MV.FALTA_KEY, "tool_usada": None,
                            "evidencia": "la receta pide credencial y no hay ninguna guardada: "
                                         "no se levantó el server",
                            "ts": _ahora()}
        # `sin_medir`, JAMÁS `roja`: la credencial no se probó — no existe. Rellenar esto
        # con un veredicto sería inventar una medición que nadie hizo.
        fila["credencial"] = {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                              "evidencia": "no hay credencial guardada que probar"}
        return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)

    # ── 1 · ARRANQUE ────────────────────────────────────────────────────────────
    srv, tools = _spawn(spec, entorno, real or BASURA,
                        entity_id=server, user_id=owner, por_var=por_var)
    if srv is None:
        fila["conexion"] = {"estado": ROTA, "causa": C_ARRANQUE, "tool_usada": None,
                            "evidencia": tools, "ts": _ahora()}
        fila["credencial"] = {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                              "evidencia": "el server no arrancó: nada que probar"}
        return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
    fila["arranca"] = True

    try:
        if not tools:
            fila["conexion"] = {"estado": ROTA, "causa": C_SIN_TOOLS, "tool_usada": None,
                                "evidencia": "arrancó y no publica tools usables", "ts": _ahora()}
            fila["credencial"] = {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                                  "evidencia": "sin tools no hay con qué probar"}
            return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)

        # ── 2 · CONEXIÓN ────────────────────────────────────────────────────────
        elegidas = elegir_tools(tools, declarada=spec.get("prueba_credencial"),
                                sonda=_sonda_expandida(spec, entorno))
        fila["tools_probadas"] = [e["name"] for e in elegidas]
        salidas = _llamar(srv, elegidas)
        con = veredicto_conexion(salidas)
        con["ts"] = _ahora()
        # ── ERA DEL PROTOCOLO (§1) — aditivo, no cambia ningún veredicto ────────────
        # `_protocol_evidence` del cliente ya guarda con qué versión se negoció, pero vivía
        # en memoria y moría con el proceso (el contrato lo decía: «se calcula pero se
        # pierde»). Se copia acá, en el MISMO spawn que ya está abierto: capturarla aparte
        # costaría un segundo arranque por pieza, y duplicar el spawn es cómo la prueba y la
        # ejecución terminan hablando de cosas distintas.
        con.update(_era_de(srv))
        # ── R4 · LA VERSIÓN QUE ESTÁ CORRIENDO ──────────────────────────────────────
        # El transporte ya la captura del `serverInfo` del saludo MCP y la publica en su
        # `diagnostico()`. **Nadie la persistía**: la columna `server_info` del registro
        # existía desde el contrato de conexiones y estaba VACÍA en las 42 filas, medido.
        # Sin este dato, [Fijar la versión] (§4.2.1) no tiene a qué versión volver, así que
        # el botón sería decorativo — y un botón decorativo es peor que ninguno.
        # Sólo se captura acá, en el MISMO spawn que ya está abierto: pedirla aparte
        # costaría un segundo arranque por pieza.
        try:
            _si = (srv.diagnostico() or {}).get("server_info") or {}
            if _si:
                fila["server_info"] = _si
        except Exception:                                 # noqa: BLE001 — nunca por evidencia
            pass
        fila["conexion"] = con

        # ── 3 · CREDENCIAL ──────────────────────────────────────────────────────
        if not pide:
            fila["credencial"] = veredicto_credencial(pide_llave=False, hay_llave_real=False)
            return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
        if not salidas:
            fila["credencial"] = {"estado": SIN_MEDIR, "tool_prueba": None, "ts": _ahora(),
                                  "evidencia": "ninguna tool sondeable"}
            return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
        primera = salidas[0]
        clas_1 = _clasificar(primera["salida"])
        # LA MITAD BARATA TERMINA ACÁ. La conexión ya se midió; la credencial no se toca y
        # se devuelve sin medir —`None`, no `sin_medir`— para que el persistidor la saltee.
        if solo_conexion:
            return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
        if not real:
            # población B: el spawn ya corrió CON basura
            fila["credencial"] = veredicto_credencial(
                pide_llave=True, hay_llave_real=False, tool=primera["tool"], con_basura=clas_1)
            return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
        # población A: falta el lado basura → segundo spawn
        # La prueba doble: MISMA entidad, OTRA llave → otro `env` → OTRA huella, o sea
        # otro proceso. Es lo correcto y es lo que pasa hoy: la basura no puede
        # compartir proceso con la llave real.
        #
        # Y ES EFÍMERA. Su `env` lleva `clave-falsa-de-prueba-0000`: ningún run va a pedir
        # jamás esa huella, así que sostenerla son 113 MB que nadie va a reusar. Medido: al
        # calentar 6 piezas del agente real, DOS de las siete conexiones sostenidas eran
        # esta sonda (exa y context7, las que tienen llave) — 226 MB de puro desperdicio.
        srv2, tools2 = _spawn(spec, entorno, BASURA,
                              entity_id=server, user_id=owner, efimero=True)
        clas_2 = {}
        if srv2 is not None:
            try:
                clas_2 = _clasificar(_llamar(srv2, [elegidas[0]])[0]["salida"])
            finally:
                try: srv2.stop()
                except Exception: pass
        fila["credencial"] = veredicto_credencial(
            pide_llave=True, hay_llave_real=True, tool=primera["tool"],
            con_real=clas_1, con_basura=clas_2)
        return _con_reserva_visible(fila, owner=owner, get_conn=get_conn)
    finally:
        try: srv.stop()
        except Exception: pass


def main() -> int:
    os.environ.setdefault("ALEPH_ROLE", "client")
    aplicar = "--aplicar" in sys.argv
    from app.phase1 import repo
    conn = repo.get_conn()
    owner = None
    try:
        with conn.cursor() as cur:
            # EL DUEÑO DEL REGISTRO ES EL QUE TIENE CONEXIONES, no el que tiene una
            # llave cualquiera. `SELECT user_id FROM keys LIMIT 1` aguantó mientras hubo un
            # solo usuario; hoy las varas y la suite crean usuarios de PRUEBA con llave
            # propia (broker-test-a/b, zotero-inject-a, cowork-approve-test), así que un
            # `LIMIT 1` sin ORDER BY devuelve cualquiera — y con un usuario de prueba esto
            # mide el catálogo entero contra un registro VACÍO. Determinista y no vacío.
            cur.execute("SELECT user_id FROM conexiones GROUP BY user_id "
                        "ORDER BY COUNT(*) DESC, user_id LIMIT 1")
            r = cur.fetchone()
            if r is None:                      # sin conexiones no hay registro que mirar;
                cur.execute("SELECT user_id FROM keys LIMIT 1")   # una cuenta suelta sirve
                r = cur.fetchone()
            owner = r[0] if r else None
    finally:
        conn.close()

    filas = []
    for belt, server in _entradas():
        f = verificar_uno(belt, server, owner=owner, get_conn=repo.get_conn)
        filas.append(f)
        print(f"{server:<20} arranca={str(f['arranca']):<5} "
              f"conexion={(f['conexion'] or {}).get('estado'):<5} "
              f"credencial={(f['credencial'] or {}).get('estado')}", flush=True)

    if aplicar:
        from app.phase1 import conexiones_repo as CR
        c = repo.get_conn()
        escritas, ajenas = 0, []
        try:
            # ⚠️ SOLO SE ACTUALIZA LO QUE EL REGISTRO YA CONOCE. Medir es barato y se hace
            # sobre TODO el catálogo; persistir es otra cosa. Un upsert le fabricaría filas
            # a servidores que el usuario no tiene equipados —medido: el registro pasaba de
            # 42 a 63— y el registro dejaría de ser «lo que este usuario tiene» para pasar a
            # ser «lo que existe». Es la misma regla que la lápida: un UPDATE, jamás un
            # upsert. Lo medido y no persistido se REPORTA, no se pierde en silencio.
            _previas = {e["entity_id"]: (e.get("conexion") or {})
                        for e in CR.listar_entidades(c, owner)}
            conocidas = set(_previas)
            for f in filas:
                if f["server"] not in conocidas:
                    ajenas.append(f["server"])
                    continue
                try:
                    # R4 · `server_info` SÓLO cuando la conexión salió VIVA: la versión
                    # de un server roto no es «la que anduvo», y guardarla como tal haría
                    # que [Fijar la versión] proponga volver a la rotura.
                    # [REPAIR · R5] LA NOTA DEL AUTO-AJUSTE SOBREVIVE AL BARRIDO. Vive
                    # dentro del veredicto de conexión (que es lo que la card ya lee) y este
                    # bloque REESCRIBE ese veredicto entero en cada medición — sin
                    # arrastrarla, el «se ajustó automáticamente el <fecha>» del [?] duraría
                    # hasta el próximo barrido y desaparecería sin que nadie lo borrara.
                    # No es un veredicto: es procedencia, y la procedencia no caduca porque
                    # se vuelva a medir.
                    _con = dict(f["conexion"] or {})
                    _nota = (_previas.get(f["server"]) or {}).get("ajuste_automatico")
                    if _nota and "ajuste_automatico" not in _con:
                        _con["ajuste_automatico"] = _nota
                    _campos = {"conexion": _con, "credencial": f["credencial"]}
                    if (f.get("conexion") or {}).get("estado") == VIVA and f.get("server_info"):
                        _campos["server_info"] = f["server_info"]
                    CR.upsert_entidad(c, user_id=owner, entity_id=f["server"], commit=False,
                                      **_campos)
                    escritas += 1
                except Exception as e:            # noqa: BLE001
                    print(f"  ERROR persistiendo {f['server']}: {type(e).__name__}: {e}")
            c.commit()
        finally:
            c.close()
        print(f"\npersistidas: {escritas}/{len(filas)}")
        if ajenas:
            print(f"medidas pero NO persistidas ({len(ajenas)}, no están en el registro "
                  f"de este usuario): {', '.join(sorted(ajenas))}")
    else:
        print(f"\n(DRY-RUN — {len(filas)} medidas, nada escrito. `--aplicar` para persistir.)")
    json.dump(filas, open(os.environ.get("ALEPH_VERIF_OUT", "/tmp/verificador.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
