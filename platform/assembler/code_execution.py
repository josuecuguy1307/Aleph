#!/usr/bin/env python3
"""code_execution.py — las tools como FUNCIONES de un script, no como catálogo.

QUÉ CAMBIA. Hoy el cerebro ve el catálogo entero de tools en cada turno, llama una,
el resultado vuelve ENTERO al contexto, llama otra, vuelve otra vez. Acá el cerebro ve
UNA sola tool (`aleph_run_code`) y escribe UN script: los pasos intermedios ocurren
adentro del sandbox y sólo vuelve lo que el script imprime.

════════════════════════════════════════════════════════════════════════════════
LO QUE ESTE MÓDULO **NO** AHORRA — medido antes de escribirlo, y dicho acá para que
nadie le atribuya una ganancia que no tiene:

  El camino CLI ya comprime el esquema. `prompt_bridge._firma_params` rinde las 92
  tools de Finanzas en **6.390 tokens**; el JSON Schema crudo que manda el camino
  litellm son **26.749**. El «150k → 2k» de la nota de Anthropic se mide contra el
  crudo. Contra la firma compacta ese ahorro YA ESTÁ COBRADO.

  Entonces la superficie de acá cuesta aproximadamente lo mismo que el bloque que
  reemplaza. La ganancia real de code execution en esta casa es OTRA, y son dos:

    1. LAS ITERACIONES. Cada tool call es un turno más, y cada turno re-manda el
       prompt entero. Ocho tools encadenadas son ocho re-envíos; un script es uno.
    2. LAS SALIDAS INTERMEDIAS. Hoy cada resultado crudo entra al contexto y se
       RE-LEE en cada turno posterior (`prompt_bridge` lo rinde como
       `[Resultado de X]: …`). Adentro del script, el intermedio se queda adentro.

  Y en el camino litellm sí ahorra también el esquema: 26.749 → ~6.500.

  EL LÍMITE HONESTO: si el modelo necesita LEER el contenido para razonar sobre él
  (Legal con un contrato adelante), el dato entra al contexto igual y no se ahorra
  nada. Donde se ahorra es cuando el dato se MUEVE, se FILTRA o se CALCULA.

════════════════════════════════════════════════════════════════════════════════
LAS TRES RESTRICCIONES DEL SANDBOX — MEDIDAS, no supuestas (vara del 2026-08-22
contra el `_run_python` real de `product/belts/generalistas/pysandbox_server.py`):

  A · `python3 -I` **saca el directorio del script de `sys.path`**. Medido:
      `sys.path[0]` sale `/opt/miniconda3/lib/python313.zip` y `os.getcwd() in
      sys.path` da False. Un `aleph_tools.py` vecino NO se puede importar
      (`ModuleNotFoundError`). → EL PRELUDIO SE INYECTA EN EL TEXTO, no se importa.
      Y eso no cuesta tokens del modelo: el modelo nunca lo ve.

  B · El entorno del hijo es un dict FIJO (`PATH`/`HOME`/`LC_ALL`/`LANG`). Medido:
      una env var nueva NO cruza. Eso es a propósito — así el código del modelo
      nunca ve las llaves BYOK— y NO se toca. → EL PUERTO Y EL TOKEN DEL PUENTE
      VIAJAN INYECTADOS EN EL PRELUDIO, no por entorno. El aislamiento queda igual.

  C · El puente de vuelta SÍ funciona: medido, `urllib` de stdlib alcanza un
      127.0.0.1 local desde adentro del sandbox, con headers. Ése es el canal.

  Y una cuarta, de tiempo: `_MAX_TIMEOUT` de pysandbox es 30 s y recorta en silencio
  lo que se le pida por encima. Un script que encadena N tools lo pasa. Acá el techo
  es propio (`TECHO_S`) y el recorte se DECLARA.

════════════════════════════════════════════════════════════════════════════════
LO QUE NO SE NEGOCIA · **NINGUNA SEÑAL DEJA DE DECIRSE.**

  Hoy cada tool que corre emite su evento y La Sala lo pinta. Si las tools pasan a
  correr adentro del sandbox y nadie avisa, la superficie se queda MUDA y eso no es
  una optimización: es un verde mudo. Por eso el puente —que es el único que ve
  pasar cada llamada— emite EL MISMO evento por cada una. Un turno con code
  execution dice exactamente las mismas tools que diría sin él.

  Y el recorte de salida se ANUNCIA (pysandbox lo hacía mudo: pedías 40.000 chars y
  volvían 12.000 sin una marca). `null` se declara; jamás se rellena con 0.
"""
from __future__ import annotations

import http.server
import json
import re
import secrets
import threading
import time
from typing import Callable, Optional

#: El techo de pared de UN script. No es el de pysandbox (30 s): un script que
#: encadena varias tools lo pasa, y ése es justamente el caso que este módulo
#: existe para habilitar. Se pasa explícito a `_run_python`, que igual lo recorta
#: a SU techo — por eso `ejecutar` DECLARA el recorte en vez de tragárselo.
TECHO_S = 240

#: Cuánto de stdout vuelve al contexto. Más allá se recorta Y SE DICE.
LIMITE_SALIDA = 24000

#: El nombre de la única tool que ve el cerebro.
NOMBRE_TOOL = "aleph_run_code"

#: La marca de fin, ya compilada.
_RE_FIN = re.compile(r"\n?__ALEPH_FIN__:(\d+)\n?\s*$")

#: ══ LA REGLA DE ACTIVACIÓN ═══════════════════════════════════════════════════════
#: NO es el número de tools. NO es tools×K. Es **CUÁNTAS VECES CRUZA EL CATÁLOGO**: un
#: paso sin tools no cruza y no cuesta nada.
#:
#: Medido contra turnos reales desde la pantalla, grabando en el punto único donde el
#: catálogo se rinde al modelo (`prompt_bridge._tools_block`). 6 de 7 superficies:
#:
#:   superficie  tools  pasos  cruces  turno   todo-codemode   adaptativo N=2
#:   finanzas       94      9       8  52.432  13.864 (−74 %)  26.972 (−49 %)
#:   ciencia        25      8       5   8.395   3.700 (−56 %)   7.058 (−16 %)
#:   sala           30      2       2   3.482   3.852 (+11 %)   3.482 ( 0 %)
#:   oficina        18      4       3   3.006   2.304 (−23 %)   4.308 (+43 %) ← ⚠️
#:   legal          12      3       2   1.654   1.246 (−25 %)   1.654 ( 0 %)
#:   educacion      11      2       1     679   1.616 (+138 %)    679 ( 0 %)
#:   diseno          —      —       —      —    [no medible · pack.py:200]
#:
#: ⚠️ **N=2 NO ES SEGURA.** Lo dije y estaba mal: lo había medido sobre superficies que
#: cruzan 1, 2, 5 y 8 veces, y ninguna cae en la ventana que rompe. **Oficina cruza 3**:
#: el umbral 2 la hace prender, y prender con pocas cruces por delante es peor que no
#: prender — paga 2 cruces caras Y las del script. Queda **43 % peor**.
#:
#: La cuenta: adaptativo = N×firma + 2×ce, y conviene sólo si `cruces > N + 2×(ce/firma)`.
#: Con ce/firma ≈ 1,1 eso es `cruces > N + 2,2`. Con N=2 prende desde 3 cruces pero recién
#: conviene desde 5: **la ventana 3-4 es donde se pierde**.
#:
#:   N=2 → finanzas −49 % · ciencia −16 % · **oficina +43 %** · resto 0 %
#:   N=3 → finanzas −36 % · **ciencia +4 %** · oficina 0 % · resto 0 %
#:
#: No hay N que gane en las dos. N=3 acota el peor caso a +4 % en vez de +43 %, a costa
#: de 13 puntos en Finanzas. **La decisión queda ABIERTA hasta que la Obra 1.b mida las
#: cruces REALES post-cambio** — el `2×ce` de arriba es un supuesto de modelo, no un dato.
#: Hasta entonces el default es el conservador.
#:
#: ══ K NO SE SABE ANTES DEL TURNO ══
#:   (a) por historial de la superficie — viable (el ledger ya guarda los pasos), pero
#:       falla en el primer turno y en los atípicos.
#:   (b) por tipo de tarea — descartada: no tengo evidencia de que un clasificador acierte.
#:   (c) **arrancar apagado y prender a la N-ésima llamada** — adoptada. No predice nada,
#:       y el mecanismo ya existe: `recipe_assembler` recalcula las tools de cada turno
#:       (`_budget.recortar`, :3301) y ya cuenta las llamadas hechas (`_usadas`, :3299).
UMBRAL_LLAMADAS = 3

#: Un catálogo de una sola tool no tiene nada que encadenar: ahí el script es puro
#: sobrecosto por más que el turno cruce muchas veces.
MINIMO_TOOLS = 2


# ── LA SUPERFICIE QUE VE EL MODELO ────────────────────────────────────────────

#: Cuántas claves de un objeto anidado se muestran antes de cortar con «…». Seis alcanza
#: para las formas reales medidas (`set_todos` tiene dos) y pone un techo al costo.
_MAX_ANIDADO = 6


def _firma(esquema, hondo: int = 1) -> str:
    """La firma de los parámetros. GEMELA de `prompt_bridge._firma_params`.

    Está duplicada a propósito y no importada, por la misma razón que la de allá:
    `prompt_bridge` es del camino CLI y esto tiene que servir también al camino
    litellm, que no lo carga. Tres líneas de forma contra una dependencia cruzada.
    """
    props = (esquema or {}).get("properties") or {}
    if not isinstance(props, dict) or not props:
        return ""
    req = set((esquema or {}).get("required") or [])
    partes = []
    for clave, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        if "const" in spec:
            tipo = f'="{spec["const"]}"'
        elif isinstance(spec.get("enum"), list) and spec["enum"]:
            tipo = ": " + "|".join(str(x) for x in spec["enum"][:6])
        else:
            tipo = ": " + _tipo(spec, hondo)
        partes.append(f"{clave}{'' if clave in req else '?'}{tipo}")
    return ", ".join(partes)


def _tipo(spec: dict, hondo: int) -> str:
    """El tipo de UN parámetro, con la forma de adentro cuando la tiene.

    ⚠️ ESTO NO ES COSMÉTICA: SIN LA FORMA DE ADENTRO EL TURNO NO ENTREGA. Medido dos veces
    en Diseño el 2026-08-23, con la misma tarea y el mismo modelo. `set_todos` declara
    `items: array<{text: string, checked: boolean}>` y las dos caras lo aplanaban a
    **`items: object[]`**. El modelo —que no tiene otra fuente— inventó
    `{title, status}`, el stack lo rechazó («Call set_todos before editing… Then retry
    scaffold»), y como sus tools están ORDENADAS, se cayó todo lo que venía después:
    `scaffold` no corrió, `App.jsx` nunca existió, y el turno terminó con un plan en vez
    de un diseño. El catálogo NO tiene este problema —lleva el JSON Schema entero—, así
    que la superficie estaba perdiendo información que el camino normal sí entrega.

    Se expande UN nivel y a lo sumo `_MAX_ANIDADO` claves. El presupuesto está: la
    superficie viaja **una vez por turno**, contra un catálogo que viajaba cinco.
    """
    t = spec.get("type") or "any"
    if t == "array":
        it = spec.get("items") or {}
        # ⚠️ EL ARRAY NO GASTA NIVEL, y ese off-by-one costó la primera pasada: con
        # `hondo - 1` acá, `array<objeto>` llegaba al objeto con `hondo == 0` y volvía a
        # imprimir `object[]` — el mismo aplanado que esta función viene a arreglar, y en
        # silencio. Lo que anida es el OBJETO, no la lista que lo contiene.
        interior = _tipo(it, hondo) if isinstance(it, dict) else "any"
        return f"{interior}[]"
    if t == "object" and hondo > 0:
        props = spec.get("properties")
        if isinstance(props, dict) and props:
            req = set(spec.get("required") or [])
            campos = []
            for k, v in list(props.items())[:_MAX_ANIDADO]:
                v = v if isinstance(v, dict) else {}
                campos.append(f"{k}{'' if k in req else '?'}: {_tipo(v, hondo - 1)}")
            if len(props) > _MAX_ANIDADO:
                campos.append("…")
            return "{" + ", ".join(campos) + "}"
    return str(t)


def superficie(tools: list) -> str:
    """El bloque de texto que reemplaza al catálogo: las tools COMO FUNCIONES."""
    lineas = [
        "",
        "HERRAMIENTAS — las tienes como FUNCIONES de Python, ya definidas y listas.",
        "NO las llamas una por una: escribes UN script que las use y lo mandas por "
        f"`{NOMBRE_TOOL}`. Los pasos intermedios se quedan adentro del script; sólo "
        "vuelve lo que imprimas con print().",
        "",
    ]
    for t in tools:
        fn = t.get("function", t)
        nombre = fn.get("name", "?")
        desc = (fn.get("description") or "").strip().replace("\n", " ")[:200]
        lineas.append(f"  {nombre}({_firma(fn.get('parameters'))}) -> dict   # {desc}")
    lineas += [
        "",
        "Cada función devuelve lo mismo que devolvía la herramienta (un dict o un str).",
        "Si una falla, levanta `AlephToolError` con el motivo — captúralo si quieres seguir.",
        # ⚠️ ESTA LÍNEA SE GANÓ MIDIENDO. Sin ella el modelo escribe Python plano
        # (`open(...)`, `urllib`) en vez de usar las funciones, el script no encuentra
        # nada, y el turno se salva por el camino de respaldo: sale bien y el mecanismo
        # nunca corre. Medido en Ciencia el 2026-08-22.
        "EL SCRIPT NO TIENE MUNDO PROPIO: corre aislado, sin acceso a los archivos, a la "
        "red ni a las credenciales. `open()`, `requests` y `subprocess` NO ven nada útil. "
        "TODO lo que toque el afuera tiene que pasar por las funciones de arriba — son el "
        "único puente.",
        "IMPRIME SÓLO LO QUE NECESITAS PARA RESPONDER: lo que no imprimes no cuesta nada, "
        "y lo que imprimes entra entero a la conversación.",
    ]
    return "\n".join(lineas)


def tool_unica(n_tools: int) -> dict:
    """El esquema de la ÚNICA tool que se declara en lugar del catálogo."""
    return {
        "type": "function",
        "function": {
            "name": NOMBRE_TOOL,
            "description": (
                f"Ejecuta un script de Python que puede usar las {n_tools} herramientas "
                "listadas arriba como funciones normales. Devuelve su stdout y stderr "
                "REALES. Úsalo para encadenar varios pasos en una sola llamada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string",
                             "description": "El script. Imprime el resultado con print()."},
                },
                "required": ["code"],
            },
        },
    }


# ── EL PUENTE DE VUELTA ───────────────────────────────────────────────────────

class Puente:
    """Un HTTP local, efímero y con token, que ejecuta las tools de verdad.

    Es el ÚNICO que ve pasar cada llamada del script, así que es el único lugar donde
    las señales pueden seguir diciéndose. Por eso `on_event` es un parámetro y no un
    adorno: sin él, un turno con code execution sería mudo.

    Se ata a 127.0.0.1 en un puerto que elige el sistema, exige un token de un solo
    run en la cabecera, y muere con el script. Las llaves BYOK NO cruzan: el sandbox
    manda un nombre y unos argumentos, y es ESTE proceso —el de siempre— el que
    ejecuta con las credenciales que ya tenía.
    """

    def __init__(self, despachar: Callable[[str, dict], str],
                 permitidas: set, on_event: Optional[Callable] = None):
        self._despachar = despachar
        self._permitidas = set(permitidas)
        self._on_event = on_event
        self.token = secrets.token_urlsafe(24)
        self.llamadas: list = []          # el registro de lo que corrió, para el reporte
        puente = self

        class _H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                if self.headers.get("X-Aleph-Codemode") != puente.token:
                    # Sin token no se atiende. El sandbox es local pero no es el único
                    # proceso local: cualquier cosa en la máquina puede golpear el puerto.
                    self.send_response(403); self.end_headers(); return
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    pedido = json.loads(self.rfile.read(n).decode() or "{}")
                except Exception:
                    self._responder({"error": "cuerpo ilegible"}, 400); return
                nombre = str(pedido.get("tool") or "")
                args = pedido.get("args") if isinstance(pedido.get("args"), dict) else {}
                if nombre not in puente._permitidas:
                    # Una tool que no está en el belt de este run no se ejecuta aunque el
                    # script la nombre. El filtro del belt sigue siendo el que manda.
                    self._responder({"error": f"herramienta no disponible en este run: {nombre}"}, 200)
                    return
                t0 = time.monotonic()
                puente._avisar("tool_started", {"tool": nombre, "args": args, "via": "code_execution"})
                try:
                    salida = puente._despachar(nombre, args)
                    err = None
                except Exception as exc:                     # noqa: BLE001
                    salida, err = None, f"{type(exc).__name__}: {exc}"
                ms = int((time.monotonic() - t0) * 1000)
                puente.llamadas.append({"tool": nombre, "ms": ms, "error": err})
                puente._avisar("tool_finished",
                               {"tool": nombre, "ms": ms, "error": err, "via": "code_execution"})
                self._responder({"ok": err is None, "resultado": salida, "error": err}, 200)

            def _responder(self, obj, code):
                cuerpo = json.dumps(obj, ensure_ascii=False, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *a):    # el server de stdlib escribe a stderr por default
                pass

        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.puerto = self._srv.server_address[1]
        self._hilo = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def _avisar(self, evento, datos):
        if self._on_event is None:
            return
        try:
            self._on_event(evento, datos)
        except Exception:
            # Un consumidor de eventos que se rompe NO puede tumbar la tool que estaba
            # corriendo. Se traga acá y sólo acá.
            pass

    def __enter__(self):
        self._hilo.start(); return self

    def __exit__(self, *exc):
        self._srv.shutdown(); self._srv.server_close()


# ── EL PRELUDIO ───────────────────────────────────────────────────────────────

#: La marca que el preludio imprime al terminar. Si NO llega, la salida se cortó:
#: es la única forma de saberlo, porque pysandbox recorta a `_OUT_LIMIT` EN SILENCIO
#: (medido: se le piden 40.000 caracteres y vuelven 12.000 sin una marca).
MARCA_FIN = "__ALEPH_FIN__"

_PRELUDIO_BASE = '''\
import json as _json, urllib.request as _u, urllib.error as _ue
import sys as _sys, atexit as _atexit

class _AlephCuenta:
    """Cuenta lo que el script IMPRIME de verdad, para poder declarar el recorte."""
    def __init__(self, _b): self._b, self.n = _b, 0
    def write(self, _s): self.n += len(_s); return self._b.write(_s)
    def flush(self): return self._b.flush()
    def __getattr__(self, _a): return getattr(self._b, _a)

_sys.stdout = _AlephCuenta(_sys.stdout)
_atexit.register(lambda: (_sys.stdout.flush(),
                          _sys.stdout._b.write("\\n__ALEPH_FIN__:%d\\n" % _sys.stdout.n),
                          _sys.stdout._b.flush()))

class AlephToolError(RuntimeError):
    """Una herramienta corrió y falló. El motivo va adentro — no es un error de red."""

def _aleph_args(_nombre, _orden, _pos, _kw):
    """Los posicionales, puestos sobre los nombres que el schema declara.

    ⚠️ ESTO SE GANÓ MIDIENDO, y el modo de fallo era total: los stubs eran
    `def f(**kw)`, así que un `set_title("Landing")` —Python perfectamente
    razonable, y lo que el modelo escribe si le mostrás una firma— moría con
    `TypeError: takes 0 positional arguments`. Y muere el SCRIPT ENTERO, en su
    primera línea, con `tools_corridas: []`. Medido en Diseño el 2026-08-23 con
    una tarea de diseño real: cero tools por el puente y el turno «anduvo» igual
    por el camino de cierre. El verde mudo puro.
    No alcanzaba con pedírselo en la superficie: una instrucción no es una
    garantía — es la misma lección del marcador `<function=…>`.
    """
    if len(_pos) > len(_orden):
        raise AlephToolError(
            "%s() recibió %d argumentos y declara %d: %s"
            % (_nombre, len(_pos), len(_orden), ", ".join(_orden) or "ninguno"))
    _fuera = dict(_kw)
    for _n, _v in zip(_orden, _pos):
        if _n in _fuera:
            raise AlephToolError("%s() recibió `%s` dos veces" % (_nombre, _n))
        _fuera[_n] = _v
    return _fuera

def _aleph_llamar(_nombre, **kw):
    _cuerpo = _json.dumps({"tool": _nombre, "args": kw}).encode()
    _req = _u.Request(_ALEPH_URL, data=_cuerpo, method="POST", headers={
        "Content-Type": "application/json", "X-Aleph-Codemode": _ALEPH_TOKEN})
    try:
        _r = _json.loads(_u.urlopen(_req, timeout=_ALEPH_TIMEOUT).read().decode())
    except _ue.URLError as _e:
        raise AlephToolError("no se pudo alcanzar el puente de herramientas: %s" % _e)
    if not _r.get("ok"):
        raise AlephToolError("%s: %s" % (_nombre, _r.get("error")))
    _v = _r.get("resultado")
    if isinstance(_v, str):
        try: return _json.loads(_v)
        except Exception: return _v
    return _v
'''

_PRELUDIO_SERIAL = '''\
def _aleph_llamar(_nombre, **kw):
    import socket as _socket
    _cuerpo = _json.dumps({"tool": _nombre, "args": kw}).encode()
    if len(_cuerpo) > 65535:
        raise AlephToolError("argumentos de herramienta demasiado grandes")
    try:
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as _s:
            _s.settimeout(_ALEPH_TIMEOUT)
            _s.connect("/tmp/aleph-run/bridge.sock")
            _s.sendall(_cuerpo + b"\\n")
            _r = b""
            while not _r.endswith(b"\\n") and len(_r) <= 65536:
                _piece = _s.recv(4096)
                if not _piece: break
                _r += _piece
            if len(_r) > 65536 or not _r.endswith(b"\\n"):
                raise AlephToolError("respuesta del puente incompleta")
            _r = _json.loads(_r)
    except (OSError, ValueError) as _e:
        raise AlephToolError("puente de herramientas no disponible: %s" % _e)
    if not _r.get("ok"):
        raise AlephToolError("%s: %s" % (_nombre, _r.get("error")))
    _v = _r.get("resultado")
    if isinstance(_v, str):
        try: return _json.loads(_v)
        except Exception: return _v
    return _v
'''


def prelude(tools: list, puerto: int, token: str, timeout_s: int, *,
            guest: bool = False) -> str:
    """El código que se antepone al script del modelo. EL MODELO NUNCA LO VE.

    Por eso puede ser todo lo explícito que haga falta: no cuesta un token de prompt.
    Va inyectado y no importado porque `-I` le saca el cwd al `sys.path` (medido).
    """
    cab = [
        f'_ALEPH_URL = "http://127.0.0.1:{puerto}/tool"',
        f'_ALEPH_TOKEN = {token!r}',
        f'_ALEPH_TIMEOUT = {int(timeout_s)}',
        _PRELUDIO_BASE,
    ]
    if guest:
        cab.append(_PRELUDIO_SERIAL)
    for t in tools:
        fn = t.get("function", t)
        nombre = fn.get("name")
        if not nombre or not nombre.isidentifier():
            # Un nombre que no es identificador de Python no puede ser una función. No se
            # inventa un alias en silencio: se omite del preludio Y de la superficie
            # (`funciones_validas` es la que manda en las dos).
            continue
        # ⚠️ LOS POSICIONALES MATABAN EL SCRIPT EN SU PRIMERA LÍNEA.
        # Era `def {nombre}(**kw)`, y la superficie muestra la firma como
        # `glob(pattern: string)` — o sea que INVITA a llamarla posicional. Medido DOS
        # VECES, en dos stacks distintos y por dos sesiones que no se hablaban:
        #   · Legal, capturando el script: las tres primeras líneas murieron con
        #     `glob() takes 0 positional arguments but 1 was given`, el script terminó
        #     `ok=False` con CERO tools corridas y el turno cerró con «no document
        #     found». El modelo había escrito el trabajo completo y bien; lo mató el stub.
        #   · Diseño, con una tarea de diseño real: cero tools por el puente y el turno
        #     «anduvo» igual por el camino de cierre. El verde mudo puro.
        #
        # ── INTEGRACIÓN · POR QUÉ QUEDA ESTA VERSIÓN Y NO LA OTRA ────────────────────
        # Las dos sesiones escribieron el arreglo y las dos mapean los posicionales sobre
        # los nombres DECLARADOS, en el orden del esquema. Queda la de Diseño porque hace
        # todo lo de la otra Y UNA COSA MÁS: `_aleph_args` detecta el argumento repetido
        # (`f("x", pattern="y")`), donde el `kw.setdefault` de la otra se comía el
        # posicional EN SILENCIO — el mismo modo de fallo mudo que esto viene a cerrar.
        # Además el error sale como `AlephToolError` con el nombre de la función, no como
        # un `TypeError` de Python que no explica nada.
        # EL ORDEN DE LOS PARÁMETROS, tal como el schema los declara. Es lo que
        # convierte un `f("x")` en `f(param="x")` sin que el modelo tenga que adivinar.
        _props = ((fn.get("parameters") or {}).get("properties") or {})
        _orden = tuple(_props) if isinstance(_props, dict) else ()
        cab.append(
            f"def {nombre}(*a, **kw):\n"
            f"    return _aleph_llamar({nombre!r}, "
            f"**_aleph_args({nombre!r}, {_orden!r}, a, kw))\n"
        )
    return "\n".join(cab)


def funciones_validas(tools: list) -> list:
    """Las tools que PUEDEN ser funciones. Las que no, quedan afuera de las dos caras."""
    ok = []
    for t in tools:
        nombre = (t.get("function", t) or {}).get("name") or ""
        if nombre.isidentifier():
            ok.append(t)
    return ok


class PuenteSerial:
    """Host-side authorization for requests arriving over VM serial IPC."""

    def __init__(self, despachar, permitidas, on_event):
        self._despachar = despachar
        self._permitidas = permitidas
        self._on_event = on_event
        self.llamadas = []

    def llamar(self, nombre, args):
        if nombre not in self._permitidas:
            return {"ok": False, "error": f"herramienta no disponible en este run: {nombre}"}
        t0 = time.monotonic()
        if self._on_event is not None:
            try:
                self._on_event("tool_started", {"tool": nombre, "args": args,
                                                "via": "code_execution"})
            except Exception:
                pass
        try:
            salida, err = self._despachar(nombre, args), None
        except Exception as exc:
            salida, err = None, f"{type(exc).__name__}: {exc}"
        ms = int((time.monotonic() - t0) * 1000)
        self.llamadas.append({"tool": nombre, "ms": ms, "error": err})
        if self._on_event is not None:
            try:
                self._on_event("tool_finished", {"tool": nombre, "ms": ms,
                                                 "error": err, "via": "code_execution"})
            except Exception:
                pass
        return {"ok": err is None, "resultado": salida, "error": err}


# ── LA EJECUCIÓN ──────────────────────────────────────────────────────────────

def ejecutar(code: str, tools: list, despachar: Callable[[str, dict], str], *,
             on_event: Optional[Callable] = None,
             correr_python: Optional[Callable] = None,
             techo_s: int = TECHO_S) -> dict:
    """Corre el script del modelo con las tools colgadas, y devuelve qué pasó.

    `correr_python` es el `_run_python` de pysandbox — se inyecta para que la vara
    pueda medir esta pieza sin levantar el belt entero.
    """
    guest = correr_python is None
    if guest:
        from importlib import util as _iu
        from pathlib import Path as _Path
        _p = _Path(__file__).resolve().parents[2] / "product/belts/generalistas/guest_execution.py"
        _s = _iu.spec_from_file_location("aleph_guest_execution", _p)
        if _s is None or _s.loader is None:
            raise RuntimeError("guest execution module unavailable")
        _m = _iu.module_from_spec(_s)
        _s.loader.exec_module(_m)
        execute_python = _m.execute_python
        correr_python = execute_python

    utiles = funciones_validas(tools)
    if guest:
        puente = PuenteSerial(despachar,
            {(_t.get("function", _t) or {}).get("name") for _t in utiles}, on_event)
        completo = prelude(utiles, 0, "", techo_s, guest=True) + "\n\n" + (code or "")
        t0 = time.monotonic()
        crudo = correr_python(completo, timeout_s=techo_s, on_tool=puente.llamar)
        ms = int((time.monotonic() - t0) * 1000)
        llamadas = list(puente.llamadas)
    else:
        # The injected runner path exists solely for deterministic historical unit
        # tests. Production never opens a host loopback listener for untrusted code.
        with Puente(despachar, {(_t.get("function", _t) or {}).get("name") for _t in utiles},
                    on_event=on_event) as puente:
            completo = prelude(utiles, puente.puerto, puente.token, techo_s) + "\n\n" + (code or "")
            t0 = time.monotonic()
            crudo = correr_python(completo, timeout_s=techo_s)
            ms = int((time.monotonic() - t0) * 1000)
            llamadas = list(puente.llamadas)

    salida = crudo.get("stdout") or ""

    # ── EL RECORTE SE DECLARA ─────────────────────────────────────────────────
    # No alcanza con comparar contra un límite propio: pysandbox ya recortó a SU
    # `_OUT_LIMIT` antes de devolver, y en silencio. Un límite propio más alto que el
    # suyo NUNCA se dispara y deja `recortada=False` sobre una salida truncada — un
    # verde mudo, que es peor que un rojo que habla. (Lo encontró la vara F, sobre
    # esta misma pieza, en su primera corrida.)
    #
    # Por eso la señal es POSITIVA: el preludio imprime `__ALEPH_FIN__:<n>` al salir.
    # Si la marca llegó, la salida está entera y `n` dice cuánto se imprimió. Si NO
    # llegó, se cortó — y el tamaño real se perdió CON el corte, así que se declara
    # `total_impreso: None`. Nunca 0: 0 sería decir «no imprimió nada», que es falso.
    total_impreso = None
    _m = _RE_FIN.search(salida)
    if _m:
        total_impreso = int(_m.group(1))
        salida = salida[:_m.start()].rstrip("\n")
        recortada = False
    else:
        # Sin marca hay dos causas posibles y las dos terminan en recorte para el lector:
        # o pysandbox cortó, o el proceso murió antes del `atexit` (timeout / kill).
        recortada = not crudo.get("timed_out")
    if recortada or len(salida) > LIMITE_SALIDA:
        recortada = True
        salida = (salida[:LIMITE_SALIDA] +
                  "\n\n[…RECORTADO: la salida del script no entró entera y se cortó. "
                  "El total impreso se perdió con el corte. Imprime menos, o filtra "
                  "adentro del script.]")

    # `techo_efectivo` es None —no 0— cuando no se pudo saber cuánto recortó pysandbox.
    return {
        "ok": bool(crudo.get("ok")),
        "stdout": salida,
        "stderr": crudo.get("stderr") or "",
        "returncode": crudo.get("returncode"),
        "timed_out": bool(crudo.get("timed_out")),
        "recortada": recortada,
        # None —jamás 0— cuando el corte se llevó el dato.
        "total_impreso": total_impreso,
        "ms": ms,
        "tools_corridas": llamadas,
        "n_tools_corridas": len(llamadas),
    }


def conviene(tools: list, *, llamadas_hechas: int, umbral: int = UMBRAL_LLAMADAS) -> bool:
    """¿Corresponde encender code execution EN ESTE PASO?

    `llamadas_hechas` son las tools que este turno YA ejecutó. No se predice nada: el
    turno arranca por el camino normal y recién cuando demostró que encadena se cambia
    de forma. Ver el bloque de UMBRAL_LLAMADAS para por qué esta es la única de las tres
    estrategias que no puede empeorar ninguna superficie.
    """
    if len(funciones_validas(tools)) < MINIMO_TOOLS:
        return False
    return int(llamadas_hechas or 0) >= int(umbral)
