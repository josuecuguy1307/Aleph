"""servidor.py — EL MOTOR DE DEEP RESEARCH, SIN SU CARA.
[Gate 4 · Fase 6 · §6.f]

QUÉ ES ESTO, Y QUÉ NO ES
------------------------
Es **código de Aleph**, no de terceros: por eso vive en `platform/` y no en `third_party/`.
Es la cáscara mínima que le da al motor de Local Deep Research la forma que el pack de la
casa sabe levantar y que la Sala sabe pintar:

    --port <n>            el pack elige el puerto (`platform/workspaces/pack.py:474`)
    GET  /health          la señal de salud que el pack sondea (`pack.py:122-127`)
    POST /research        NDJSON: los estados en vivo, y al final el informe
    POST /cancelar        la cancelación cooperativa

**No es un servidor web de investigación.** No tiene cuentas, ni sesiones, ni base, ni
pantalla. Escucha en loopback, lo levanta el pack al entrar y lo mata al salir.

POR QUÉ HAY QUE ESCRIBIRLO (y no usar su MCP)
----------------------------------------------
LDR **ya trae** un servidor MCP con 8 tools (`third_party/ldr/src/local_deep_research/
mcp/server.py`). No sirve para este trabajo, por dos hechos medidos:

1. **Es stdio, no HTTP.** `mcp/server.py:1053` → `mcp.run(transport="stdio")`. El pack de
   la casa levanta procesos que contestan una señal de salud HTTP en un puerto que él
   elige; un servidor stdio no encaja en ese contrato.
2. **Es ciego al progreso.** Su propio docstring lo dice (`mcp/server.py:367-368`):
   «IMPORTANT: This is a synchronous operation that typically takes 1-5 minutes to
   complete». Devuelve el resultado, no el camino. Y §6.f pide exactamente el camino:
   «planificando → buscando → leyendo 4/20 → sintetizando».

El MCP **queda igual** y se censa como lo que es (`platform/workspaces/sources.py`): es una
puerta legítima para que un agente lo use como tool. Simplemente no es la puerta de la Sala.

CERO CUENTA, CERO BASE — y es la costura de ellos
--------------------------------------------------
`programmatic_mode=True` (default de `api/research_functions.py:49`) «disables database
operations and metrics tracking» (`:74`), y el decorador `@no_db_settings`
(`utilities/db_utils.py:179-204`) apaga la lectura de settings desde la base: «Settings can
only be read from environment variables or the defaults file». Ése es el **flag nativo de
no-auth** que la ley 2.bis manda usar PRIMERO. No se automatiza un login: no se enciende
ninguno.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))
if str(_AQUI.parents[1]) not in sys.path:
    sys.path.insert(0, str(_AQUI.parents[1]))

from local_pack_auth import guard_post  # noqa: E402

import cerebro as _cerebro          # noqa: E402
import etapas as _etapas            # noqa: E402

#: Copy de cada causa. Regla sellada: ninguna causa llega a una superficie sin copy.
_COPY = {
    "cerebro_sin_config": "El modo de investigación no recibió su configuración.",
    "cerebro_config_ilegible": "La configuración del modo de investigación está rota.",
    "cerebro_config_incompleta": "La configuración del modo de investigación está incompleta.",
    "cerebro_sin_sdk": "Este build no trae el motor de investigación.",
    "motor_no_instalado": "El motor de investigación no viajó con esta instalación.",
    "sin_buscador": "El modo de investigación no tiene buscador configurado.",
    "consulta_vacia": "Hace falta una consulta para investigar.",
    "obra_cancelada": "Investigación cancelada.",
    "motor_fallo": "La investigación falló.",
    # ── EL VERDE MUDO, con nombre ─────────────────────────────────────────────
    # Las dos formas en que este modo puede terminar en 200 sin haber investigado. No son
    # errores del motor —el motor contesta y contesta bien formado—: son informes que no
    # se ganaron el nombre. `arranque.sh:70-73` ya declaraba el miedo por escrito («la
    # Sala pintaría progreso y entregaría un informe sin fuentes con cara de éxito»);
    # acá deja de ser un miedo y pasa a ser una causa tipada.
    "informe_sin_fuentes": "La investigación terminó sin una sola fuente verificable.",
    # `investigacion_sin_busqueda` ya no se levanta: el motor no anuncia sus búsquedas, así
    # que la aserción rechazaba obras buenas (ver `_investigar`). La entrada QUEDA —y su
    # copy en `causas-catalogo.js` también— porque el vocabulario de causas no se achica en
    # silencio: si alguna versión del motor volviera a emitirla, tiene que tener texto.
    "investigacion_sin_busqueda": "La investigación nunca llegó a buscar.",
    # Estas dos son de protocolo: sólo pueden pasar si quien llama está mal escrito, no si
    # el usuario hizo algo. Igual llevan copy, porque la regla no admite excepciones por
    # improbabilidad: si alguna vez llegan a una pantalla, un slug crudo sería peor.
    "cuerpo_invalido": "La Sala mandó un pedido que no se entiende.",
    "ruta_desconocida": "Ese camino no existe en el modo de investigación.",
}

#: Obras vivas: `obra_id -> {"cancelar": bool}`. Muere con el proceso, a propósito: una
#: obra no sobrevive al pack, y el pack no sobrevive a salir del modo.
_OBRAS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ── el sobre que viaja por el cable ───────────────────────────────────────────
#
# NDJSON: una línea = un objeto JSON completo. Es el mismo formato que ya habla el otro
# motor de la Sala (Vane, `/api/chat`), así que la Sala tiene un solo lector.
#
#   {"tipo":"abre",    "obra_id":…, "espacio":…}
#   {"tipo":"estado",  …el sobre de etapas.traducir()…}
#   {"tipo":"informe", "texto":…, "fuentes":[…], "sha256":…, "iteraciones":…}
#   {"tipo":"fallo",   "causa":…, "copy":…, "detalle":…}
#   {"tipo":"cierra",  "obra_id":…, "ms":…}
#
# `estado` es el único que se repite. Los demás salen una vez.


def _espacio_nuevo(obra_id: str) -> str:
    """Un espacio por obra, con el mismo patrón que el plugin de Ciencia.

    `platform/workspaces/plugins/openscience.js:82` lo arma así para el workspace; acá se
    hace igual para que los eventos de este modo sean legibles con las mismas reglas.
    Debe matchear `^[A-Za-z0-9._:-]{1,120}$` (`platform/artifacts/provenance.py:53`).
    """
    return f"space-sala-research-{obra_id}"


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 para poder mandar chunked; sin esto una respuesta sin Content-Length
    # obliga a cerrar la conexión y el cliente no sabe si terminó o se cortó.
    protocol_version = "HTTP/1.1"
    server_version = "AlephSalaResearch/1"

    # El log por defecto de BaseHTTPRequestHandler escribe a stderr una línea por pedido.
    # El stderr de este proceso va al `pack.log`; una línea por latido lo inunda.
    def log_message(self, formato: str, *args: Any) -> None:      # noqa: A002
        if os.environ.get("ALEPH_RESEARCH_DEBUG"):
            super().log_message(formato, *args)

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                                     # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._json(200, {"ok": True, "motor": "local-deep-research"})
            return
        self._json(404, {"error": "ruta_desconocida", "detail": self.path})

    # ── POST ──────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:                                    # noqa: N802
        if not guard_post(self):
            return
        ruta = self.path.split("?")[0]
        # `_Cancelada` hereda de `BaseException` (a propósito, ver su docstring), así que
        # el `except Exception` de `socketserver.ThreadingMixIn.process_request_thread`
        # NO la atrapa: escaparía como traceback crudo al `pack.log` en vez de pasar por
        # `handle_error()`. Se corta acá, que es su frontera natural: el cliente se fue,
        # no hay nada que informar.
        try:
            cuerpo = self._leer_json()
            if cuerpo is None:
                return
            if ruta == "/research":
                self._research(cuerpo)
            elif ruta == "/cancelar":
                self._cancelar(cuerpo)
            else:
                self._json(404, {"error": "ruta_desconocida", "detail": ruta})
        except _Cancelada:
            return

    # ── la obra ───────────────────────────────────────────────────────────────
    def _research(self, cuerpo: dict) -> None:
        consulta = str(cuerpo.get("query") or cuerpo.get("consulta") or "").strip()
        if not consulta:
            self._json(400, {"error": "consulta_vacia", "copy": _COPY["consulta_vacia"]})
            return

        obra_id = uuid.uuid4().hex[:16]
        espacio = _espacio_nuevo(obra_id)
        arranque = time.monotonic()
        with _LOCK:
            if _OBRAS:
                self._json(429, {"error": "capacidad_ocupada",
                                 "copy": "Ya hay una investigación activa. Espera o cancélala."})
                return
            _OBRAS[obra_id] = {"cancelar": False}

        # TODO LO QUE SIGUE VA ADENTRO DEL `try`, y no es cosmético: escribir cabeceras o
        # la primera línea puede levantar `BrokenPipeError` si la Sala abortó el fetch
        # (cambió de pantalla, doble-submit). Si eso pasara fuera del `try`, el `finally`
        # con el `pop` no correría y la obra quedaría **de por vida** en `_OBRAS`, en un
        # proceso que dura lo que dura el modo. Un fósil por cada aborto.
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._linea({"tipo": "abre", "obra_id": obra_id, "espacio": espacio})
            salida = _investigar(
                consulta=consulta,
                obra_id=obra_id,
                espacio=espacio,
                modo=str(cuerpo.get("modo") or "resumen"),
                estrategia=cuerpo.get("estrategia"),
                iteraciones=cuerpo.get("iteraciones"),
                emitir=self._linea,
            )
        except _Cancelada:
            self._decir({"tipo": "fallo", "causa": "obra_cancelada",
                         "copy": _COPY["obra_cancelada"], "detalle": ""})
        except _cerebro.CosturaError as e:
            self._decir({"tipo": "fallo", "causa": e.causa,
                         "copy": _COPY.get(e.causa, e.causa), "detalle": e.detalle})
        except _InformeMudo as e:
            # El fallo LLEVA el sobre: texto, etapas corridas y fuentes crudas. La Sala
            # decide si muestra el borrador; lo que no puede es creer que investigó.
            self._decir({"tipo": "fallo", "causa": e.causa,
                         "copy": _COPY[e.causa], "detalle": "", **e.salida})
        except Exception as e:                                    # noqa: BLE001
            # Fallo visible, jamás mudo (ley técnica 9). Y ANTES de aplanar: el borde de
            # la casa ya devuelve causas tipadas CON SU COPY (`missing_recipe`,
            # `modelo_no_conectado`, `over_budget`, `brain_unavailable`…). Colapsarlas
            # todas en «La investigación falló.» sería tirar el trabajo que el borde ya
            # hizo y dejar al usuario sin saber que le falta elegir un modelo.
            causa, copy, detalle = _causa_del_borde(e)
            self._decir({"tipo": "fallo", "causa": causa, "copy": copy, "detalle": detalle})
        else:
            self._decir({"tipo": "informe", **salida})
        finally:
            with _LOCK:
                _OBRAS.pop(obra_id, None)
            # El cierre no puede volver a romper: si el que escuchaba ya se fue, escribir
            # desde un `finally` **reemplazaría la causa original** y el usuario vería «se
            # cortó» en vez de por qué falló de verdad. `_decir` es `_linea` que se traga
            # su propio fallo, y por eso se usa en TODAS las salidas del turno: cuando ya
            # estamos contando el final, el cable roto no es una causa nueva.
            self._decir({"tipo": "cierra", "obra_id": obra_id,
                         "ms": int((time.monotonic() - arranque) * 1000)})
            self._fin_chunked()

    def _cancelar(self, cuerpo: dict) -> None:
        obra_id = str(cuerpo.get("obra_id") or "").strip()
        with _LOCK:
            obra = _OBRAS.get(obra_id)
            if obra is not None:
                obra["cancelar"] = True
        # Honesto: decimos si había algo que cancelar. Un 200 sobre una obra que ya
        # terminó no es un error, pero tampoco es lo mismo que haberla parado.
        self._json(200, {"obra_id": obra_id, "encontrada": obra is not None})

    # ── plomería ──────────────────────────────────────────────────────────────
    def _leer_json(self) -> Optional[dict]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        crudo = self.rfile.read(n) if n > 0 else b""
        if not crudo:
            return {}
        try:
            cuerpo = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            self._json(400, {"error": "cuerpo_invalido", "detail": str(e)})
            return None
        if not isinstance(cuerpo, dict):
            self._json(400, {"error": "cuerpo_invalido", "detail": "se esperaba un objeto"})
            return None
        return cuerpo

    def _json(self, codigo: int, cuerpo: dict) -> None:
        crudo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def _linea(self, obj: dict) -> None:
        """Una línea NDJSON, en un chunk propio, empujada al cable."""
        crudo = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(b"%x\r\n" % len(crudo))
            self.wfile.write(crudo)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # El que escuchaba se fue. No es un error del motor: es el usuario cerrando.
            raise _Cancelada() from None

    def _decir(self, obj: dict) -> None:
        """`_linea` para las salidas del turno: si el cable ya está roto, no es una causa.

        Se usa en el desenlace (informe · fallo · cierra), donde levantar `_Cancelada`
        taparía la causa real o dejaría el terminador chunked sin escribir. Durante el
        turno se usa `_linea`, que SÍ debe levantar: ahí un cable roto es la señal de que
        el usuario se fue y hay que parar el motor.
        """
        try:
            self._linea(obj)
        except _Cancelada:
            pass
        except OSError:
            # Cualquier otro fallo del socket en el desenlace: el cliente ya no está.
            pass

    def _fin_chunked(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def _causa_del_borde(e: Exception) -> tuple[str, str, str]:
    """Si el fallo vino del borde, se devuelve SU causa y SU copy; si no, la genérica.

    El SDK de OpenAI envuelve los errores HTTP en excepciones que traen el cuerpo. El
    borde de Aleph contesta `{"detail": {"error"|"causa": …, "copy": …}}`
    (`product/backend/app/phase1/router.py`), o sea que la causa buena ya viajó: sólo hay
    que no pisarla.
    """
    cuerpo = getattr(e, "body", None) or getattr(e, "response", None)
    if hasattr(cuerpo, "json"):
        try:
            cuerpo = cuerpo.json()
        except Exception:                                          # noqa: BLE001
            cuerpo = None
    if isinstance(cuerpo, dict):
        det = cuerpo.get("detail") if isinstance(cuerpo.get("detail"), dict) else cuerpo
        if isinstance(det, dict):
            causa = str(det.get("causa") or det.get("error") or "").strip()
            copy = str(det.get("copy") or "").strip()
            if causa and copy:
                return causa, copy, str(det.get("detail") or "")
    return "motor_fallo", _COPY["motor_fallo"], f"{type(e).__name__}: {e}"


class _InformeMudo(Exception):
    """El motor contestó 200 y bien formado, y lo que trajo no es una investigación.

    **No se levanta para tirar el trabajo, se levanta para no disfrazarlo.** El texto que
    el modelo produjo viaja adentro (`salida`), igual que las etapas que sí corrieron y el
    número crudo de fuentes que el motor dijo tener: quien pinta esto tiene que poder
    mostrar lo que hay Y decir que no alcanza. Un `informe` con cero fuentes sería el 200
    cortés sobre el vacío que la búsqueda web pagó hoy en su propio modo.
    """

    def __init__(self, causa: str, salida: dict):
        self.causa = causa
        self.salida = salida
        super().__init__(causa)


class _Cancelada(BaseException):
    """La obra se paró: la pidió el usuario o se fue el que escuchaba.

    **Hereda de `BaseException` a propósito, y por la misma razón que ellos.** Esta
    excepción se levanta DESDE ADENTRO del `progress_callback`, o sea desde adentro del
    pipeline del motor — y ese pipeline está lleno de `except Exception` que se la comerían,
    dejando la obra corriendo y gastando con el cliente ya desconectado. El propio LDR tomó
    esta decisión antes que nosotros para su `ResearchTerminatedException`
    (`third_party/ldr/src/local_deep_research/exceptions.py:4`, con el motivo escrito en
    `web/services/research_service.py:592-594`). Copiar el hierarchy no es capricho: es la
    condición para que parar signifique parar.
    """


def _investigar(*, consulta: str, obra_id: str, espacio: str, modo: str,
                estrategia: Optional[str], iteraciones: Optional[int],
                emitir) -> dict:
    """Corre una obra de LDR y va emitiendo sus etapas traducidas.

    Devuelve el informe con sus fuentes — la materia prima del artefacto y del pasaporte.
    """
    try:
        from local_deep_research.api import (      # noqa: PLC0415 — perezoso a propósito
            detailed_research as _detallada,
            quick_summary as _resumen,
        )
        from local_deep_research.api.settings_utils import create_settings_snapshot
        from local_deep_research.exceptions import ResearchTerminatedException
    except ImportError as e:                       # noqa: BLE001
        raise _cerebro.CosturaError(
            "motor_no_instalado", f"no se pudo importar local_deep_research ({e})"
        ) from None

    config = _cerebro.leer_config(_ruta_config())
    llm = _cerebro.construir(config, space_id=espacio, turno=1)

    # EL TOTAL DEL «N de M» LO SABE ESTE SERVIDOR, NO EL MOTOR. Medido: el motor emite
    # `iteration` (en `source_based_strategy.py:454`, la estrategia por default) pero
    # **nunca junto a un total** — `max_iterations` sale una sola vez, en la metadata de
    # `phase:"init"`, que no lleva `iteration`. Un adaptador que espere las dos claves en
    # el mismo dict devuelve `(None, None)` siempre, y el «leyendo N de M» que §6.f pide
    # por nombre no se pinta nunca. Como el tope lo fijamos nosotros dos líneas más abajo,
    # se lo inyectamos al latido: es el único que lo tiene.
    #: Las etapas GRUESAS que el motor emitió de verdad, en este turno. Se llena desde el
    #: callback y se lee en el desenlace; es un `set` porque lo que importa es si la etapa
    #: ocurrió, no cuántas veces.
    corridas: set[str] = set()

    # ⚠️ `None` CUANDO NO LO FIJAMOS NOSOTROS, y ésa es la corrección importante.
    #
    # Esto arrancaba en `1`, y el resultado se vio en pantalla: la línea de razonamiento
    # decía **«Buscando… (1 de 1)»** en una obra de tres iteraciones. El razonamiento roto
    # era: «el tope lo fijamos nosotros dos líneas más abajo». Sólo lo fijamos **si el que
    # llama mandó `iteraciones`** — `comun["iterations"] = tope` está adentro de un `if`.
    # Sin eso, el motor usa SU default y nosotros le contábamos al usuario un total que
    # nadie impuso.
    #
    # Un total inventado es peor que ningún total: «1 de 1» dice «ya casi» sobre una obra
    # que recién empieza. Es la misma disciplina que `etapas.py` aplica al `pct` — un dato
    # que no se midió no se rellena — sólo que acá se estaba violando.
    tope = None
    if iteraciones:
        try:
            tope = max(1, min(10, int(iteraciones)))
        except (TypeError, ValueError):
            tope = None

    def _progreso(mensaje: str, pct, metadata) -> None:
        # LA CANCELACIÓN, por la costura que ellos dejaron: el callback levanta
        # `ResearchTerminatedException`, que hereda de BaseException **a propósito** para
        # que ningún `except Exception` del pipeline se la coma
        # (`third_party/ldr/src/local_deep_research/exceptions.py:4`, y la razón escrita en
        # `web/services/research_service.py:592-594`). Los puntos de chequeo ya están
        # sembrados: `base_strategy.py:99-131 check_termination()`.
        with _LOCK:
            parar = bool(_OBRAS.get(obra_id, {}).get("cancelar"))
        if parar:
            raise ResearchTerminatedException("la paró el usuario")

        meta = dict(metadata or {})
        if (tope is not None and "iteration" in meta
                and not any(k in meta for k in ("max_iterations", "iterations"))):
            meta["max_iterations"] = tope
        sobre = _etapas.traducir(mensaje, pct, meta)
        if sobre is None:                          # fase de control: no se pinta
            return
        # LA CONTABILIDAD DE LO QUE PASÓ DE VERDAD. El informe final va a declarar las
        # etapas corridas, y la única fuente honesta de ese dato son los latidos que el
        # motor emitió — no el `iterations` que devuelve al final, que es lo que él CREE
        # haber hecho. Ésa es justo la diferencia que §6.f manda atrapar: «menos etapas de
        # las que dice haber corrido».
        if sobre.get("etapa"):
            corridas.add(str(sobre["etapa"]))
        emitir({"tipo": "estado", "obra_id": obra_id, **sobre})

    # EL CEREBRO SE ELIGE EN EL SNAPSHOT, NO EN EL PARÁMETRO `provider=`, y esto es una
    # trampa medida que cuesta caro entender tarde:
    #
    #   `quick_summary(provider=…)` sólo se usa para ARMAR un snapshot, y sólo
    #   `if "settings_snapshot" not in kwargs` (`api/research_functions.py:227-252`).
    #   Como nosotros SÍ pasamos snapshot, ese parámetro se descarta entero — y nunca
    #   llega a `_init_search_system`, que arma `init_kwargs` desde `**kwargs` (`:307`),
    #   donde `provider` no está porque es un parámetro nombrado.
    #
    # Resultado si se hiciera de la forma obvia: `get_llm` leería `llm.provider` del
    # snapshot, que por default es **`ollama`** — o sea que el modo saldría a buscar un
    # modelo local en vez de usar el cerebro de la casa. Eso no es un bug de rendimiento:
    # es la LEY 12 rota en silencio.
    #
    # `{"llm.provider": …}` es el mecanismo que ellos documentan para esto
    # (`api/settings_utils.py:274-292`: «overrides: … e.g. {"llm.provider": "openai"}»), y
    # es lo que hace que `get_llm` entre por su rama de registro
    # (`config/llm_config.py:222-225`: `if provider and is_llm_registered(provider)`).
    # EL BUSCADOR DEL MODO LARGO. §6.f: «depende de 6.a.bis — por dentro él también busca;
    # si la base no está curada, hereda basura». El default del motor es su propio SearXNG
    # en `localhost:8080` (`defaults/default_settings.json`), que en esta casa **no lo
    # levanta nadie** y además es el puerto del server de diseño: buscar ahí devolvería
    # HTML de Aleph tratado como resultados. Se apunta al mismo metabuscador que levanta la
    # búsqueda base, y si no hay ninguno declarado se dice, en vez de investigar contra el
    # vacío y devolver un informe sin fuentes con cara de éxito.
    searxng = os.environ.get("ALEPH_SEARXNG_URL", "").strip()
    if not searxng:
        raise _cerebro.CosturaError(
            "sin_buscador",
            "el modo largo necesita el mismo SearXNG que la búsqueda base: decláralo en "
            "ALEPH_SEARXNG_URL")

    nombre = _cerebro.nombre_de(obra_id)
    ajustes = create_settings_snapshot({
        "llm.provider": nombre,
        "search.tool": "searxng",
        "search.engine.web.searxng.default_params.instance_url": searxng.rstrip("/"),
    })

    comun: dict[str, Any] = {
        "llms": {nombre: llm},
        "progress_callback": _progreso,
        "settings_snapshot": ajustes,
        # `programmatic_mode` ya viene True por default (`research_functions.py:49`); se
        # declara igual porque es la línea que apaga base, métricas e identidad, y una
        # cosa así no se deja implícita.
        "programmatic_mode": True,
    }
    if estrategia:
        comun["search_strategy"] = str(estrategia)
    if tope is not None:
        comun["iterations"] = tope

    cierre_ok = False
    cuerpo = ""
    try:
        try:
            if modo == "informe":
                crudo = _detallada(consulta, **comun)
            else:
                crudo = _resumen(consulta, **comun)
        except ResearchTerminatedException:
            raise _Cancelada() from None

        crudo = crudo or {}
        texto = str(crudo.get("summary") or "")
        formateado = str(crudo.get("formatted_findings") or "")
        cuerpo = formateado or texto
        brutas = crudo.get("sources")
        fuentes = _fuentes(brutas)
        salida = {
            "obra_id": obra_id,
            "espacio": espacio,
            "texto": cuerpo,
            # Las FUENTES son lo que hace del informe un artefacto con pasaporte: refs
            # re-verificables. `sources` es `all_links_of_system` del motor
            # (`api/research_functions.py:326-334`).
            "fuentes": fuentes,
            # CUÁNTAS DIJO EL MOTOR, además de cuántas sobrevivieron. Sin este número,
            # «no encontró nada» y «encontró diez cosas ilegibles» se ven idénticos desde
            # afuera, y son dos bugs distintos: el primero es del buscador, el segundo de
            # la normalización. `_fuentes()` descarta en silencio a propósito (no inventa
            # una url); el silencio deja de ser mudo acá.
            "fuentes_crudas": len(brutas) if isinstance(brutas, (list, tuple)) else 0,
            # LAS ETAPAS QUE CORRIERON DE VERDAD, contadas de los latidos, no del
            # `iterations` que el motor se auto-reporta.
            "etapas": sorted(corridas),
            "iteraciones": _entero(crudo.get("iterations")),
            # El sha256 del cuerpo, para que el artefacto tenga identidad desde que nace.
            "sha256": hashlib.sha256(cuerpo.encode("utf-8")).hexdigest(),
        }

        # ── LA PUERTA DEL VERDE MUDO ──────────────────────────────────────────────
        #
        # Está acá, DESPUÉS de armar el sobre y ANTES de `cierre_ok = True`, y las dos
        # cosas importan: el sobre completo viaja adentro del fallo (no se tira el trabajo
        # del modelo), y el espacio se cierra como lo que fue —una obra que no llegó—, que
        # es lo que lee el anti-grift.
        #
        # ⚠️⚠️ ACÁ HABÍA DOS PUERTAS Y LA PRIMERA RECHAZABA INVESTIGACIONES BUENAS.
        #
        # Decía: «si el motor nunca emitió una etapa BUSCANDO, escribió de memoria». Suena
        # bien y es falso, y lo destapó correr el motor de verdad contra un SearXNG de
        # verdad — no una vara. Medido sobre dos obras reales (`resumen` e `informe`), las
        # ÚNICAS fases que el motor emite por su callback son:
        #
        #     setup · init · question_generation · final_filtering ·
        #     filtering_complete · synthesis
        #
        # **Ninguna cae en BUSCANDO.** El motor busca sin anunciarlo: la obra volvió con
        # **30 fuentes reales** y la puerta la rechazó igual, con `etapas` =
        # `["leyendo","planificando","sintetizando"]`. O sea que el modo largo fallaba
        # SIEMPRE, en el camino feliz, por una aserción mía.
        #
        # POR QUÉ LA VARA NO LO VIO, que es la parte que hay que recordar: su motor doblado
        # emitía `search` —yo lo escribí— así que el fixture traía una pista que el motor
        # real no da. Es el mismo error que ya tiene nombre en esta casa: un fixture que
        # sabe la respuesta no mide nada. La vara quedó corregida para emitir el
        # vocabulario REAL, medido, y no el que yo suponía.
        #
        # QUÉ QUEDA. `etapas` sigue viajando en el sobre porque es un dato honesto —lo que
        # el motor emitió, contado de los latidos—, pero **no es un veredicto**: con este
        # motor no puede serlo. El hecho que sí distingue una investigación de un texto
        # escrito de memoria es el que quedó: si volvió sin una sola fuente verificable, no
        # es un informe. Ése se mide directo y no depende de que el motor anuncie nada.
        if not fuentes:
            raise _InformeMudo("informe_sin_fuentes", salida)

        cierre_ok = True
        return salida
    finally:
        # El registro de LDR es global al proceso y no se limpia solo. Sin esto, una
        # sesión larga acumula un cliente por obra —cada uno con la sesión de Aleph
        # adentro de sus cabeceras— en un dict que vive lo que vive el pack.
        try:
            from local_deep_research.llm import unregister_llm
            unregister_llm(nombre)
        except Exception:                          # noqa: BLE001 — limpiar no puede fallar
            pass

        # CERRAR EL ESPACIO INCLUSO SI EL MOTOR FALLA. Cada obra abre uno
        # (`X-Aleph-Space`) y el borde tiene su puerta de cierre; si el cierre viviera
        # sólo después del resultado, cualquier error del modelo dejaría lo producido
        # como `partial` con la referencia colgando (`workspace_brain.py:371-378`).
        # El cierre es best-effort: perder auditoría no debe reemplazar la causa original.
        # Es el mismo cierre que el plugin de Ciencia hace antes de cruzar su artefacto
        # (`plugins/openscience.js:225-227`).
        try:
            _cerrar_espacio(config, espacio, ok=cierre_ok, answer=cuerpo,
                            turns=(tope or 0))
        except Exception:                          # noqa: BLE001 — cierre nunca reemplaza la causa
            pass


def _cerrar_espacio(config: dict, espacio: str, *, ok: bool = True,
                    answer: str = "", turns: int = 0) -> None:
    """Le avisa al borde que este espacio terminó. Nunca rompe la obra.

    Si el cierre falla, el usuario pierde la calidad de la procedencia de ese turno, no el
    turno: es el mismo patrón sellado en los dos plugins de la casa («si Aleph no contesta,
    el usuario pierde la auditoría de ese turno, no el turno», `plugins/openscience.js:46`).
    """
    import urllib.error
    import urllib.request
    base = config["base_url"].rsplit("/v1/", 1)[0] if "/v1/" in config["base_url"] else ""
    if not base:
        return
    cuerpo = json.dumps({
        "space_id": espacio,
        "workspace": "sala_research",
        "answer": str(answer or "")[:20000],
        "ok": bool(ok),
        "turns": max(0, int(turns or 0)),
    }).encode()
    pedido = urllib.request.Request(
        f"{base}/v1/workspaces/brain/close", data=cuerpo, method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {config['api_key']}"} if config.get("api_key") else {})})
    try:
        with urllib.request.urlopen(pedido, timeout=5):
            pass
    except Exception:                                              # noqa: BLE001
        pass


def _fuentes(crudo: Any) -> list[dict]:
    """Normaliza las fuentes a `{url, titulo}` sin inventar ninguna.

    Lo que no se puede leer se descarta con su forma a la vista, jamás se rellena.
    """
    salida: list[dict] = []
    vistas: set[str] = set()
    for f in (crudo or []):
        if isinstance(f, str):
            url, titulo = f, ""
        elif isinstance(f, dict):
            url = str(f.get("url") or f.get("link") or "")
            titulo = str(f.get("title") or f.get("titulo") or "")
        else:
            continue
        url = url.strip()
        if not url or url in vistas:
            continue
        vistas.add(url)
        salida.append({"url": url, "titulo": titulo.strip()})
    return salida


def _entero(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ruta_config() -> Path:
    """Dónde el pack dejó la config del cerebro.

    El pack pasa el DIRECTORIO por la env var que la fila declara (`config_env`), y el
    nombre del archivo por `config_file`. Acá se reconstruye la misma ruta.
    """
    dir_config = os.environ.get("ALEPH_RESEARCH_CONFIG_DIR", "")
    nombre = os.environ.get("ALEPH_RESEARCH_CONFIG_FILE", "aleph-cerebro.json")
    if not dir_config:
        # Camino de respaldo declarado: `ALEPH_PACK_CONFIG` apunta a `aleph-pack.json` en
        # el mismo directorio (`platform/workspaces/pack.py:481`). Sirve para correr esto a
        # mano en dev sin declarar dos variables.
        pack = os.environ.get("ALEPH_PACK_CONFIG", "")
        if pack:
            return Path(pack).parent / nombre
        raise _cerebro.CosturaError(
            "cerebro_sin_config", "ni ALEPH_RESEARCH_CONFIG_DIR ni ALEPH_PACK_CONFIG")
    return Path(dir_config) / nombre


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="aleph-sala-research", add_help=True)
    # El pack SIEMPRE manda `--port` (`platform/workspaces/pack.py:474`). Sin puerto no se
    # arranca en un default: se sale con código, como hace el launcher de Legal.
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    servidor = ThreadingHTTPServer((args.host, args.port), _Handler)
    servidor.daemon_threads = True
    print(f"Aleph · Deep Research: escuchando en {args.host}:{args.port}", flush=True)
    try:
        servidor.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
