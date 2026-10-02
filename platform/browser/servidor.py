"""servidor.py — EL MOTOR DE BROWSER USE, detrás de un puerto de loopback.
[Gate 4 · Fase 6 · §6.a]

QUÉ SIRVE
---------
    POST /manejar   NDJSON: el progreso paso a paso, y al final la obra
    POST /parar     corta el turno en curso
    GET  /health

UNA TOOL, NO VEINTE — decisión del dueño. El agente pide «hacé esto en el navegador»,
browser-use corre **su loop entero acá adentro**, y vuelve el resultado. No se desarma en
abrir/click/escribir: desarmarlo sería tirar justo lo que se fue a buscar — un loop que
aguanta decenas de pasos mirando una pantalla que cambia sola.

LA PLOMERÍA NO SE REESCRIBE. `platform/ndjson_http.py` ya trae leer/contestar/empujar
líneas y la distinción cable-roto vs error, extraída cuando se midió que las gemelas de
búsqueda y research **ya habían divergido** (23 líneas, y cada copia arreglaba la mitad que
la otra no). Éste habría sido el tercero.

LAS PERILLAS SALEN DEL CEREBRO, NO DE ACÁ. `platform/browser/perfil.py` deriva `use_vision`,
el techo por llamada y las dos válvulas del schema de la matriz que el cerebro DECLARA. Este
archivo no decide ninguna: las recibe.

EL LOOPBACK PASA POR EL GUARD DE LA CASA. `platform/browser/loopback.py` decide cada URL
antes de que el navegador la toque: allowlist por `(run_id, puerto)`, nunca por rango. Ver
`REGLA-LOOPBACK.md`.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
for _p in (str(_AQUI.parent), str(_AQUI.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ndjson_http import Cancelada, PlomeriaNDJSON            # noqa: E402
from browser import cerebro as COSTURA                        # noqa: E402
from browser import loopback as GUARD                         # noqa: E402
from browser import pinned_proxy as PINNED_PROXY               # noqa: E402
from browser import perfil as PERFIL                          # noqa: E402
from local_pack_auth import guard_post                        # noqa: E402

#: Ninguna causa llega a una superficie sin copy. Estas son las de ESTE motor; las del
#: cerebro (sin visión / cerebro lento) las trae `perfil.COPY` y no se copian acá.
COPY = {
    "cuerpo_invalido": "La Sala mandó un pedido que no se entiende.",
    "tarea_vacia": "Dime qué quieres que haga en el navegador.",
    "sin_cerebro": "Todavía no hay un cerebro configurado para manejar el navegador.",
    "navegador_ausente": "El navegador no viajó con esta instalación.",
    "url_bloqueada": "No puedo abrir esa dirección desde aquí.",
    "motor_roto": "El navegador se cortó a mitad del trabajo.",
    "parado": "Paraste el trabajo.",
}

_LOCK = threading.Lock()
_EN_CURSO: dict[str, Any] = {}          # turno_id -> el Agent, para poder pararlo


def _ruta_config():
    """La config que el pack escribió, leída de donde el pack la deja.

    ⚠️ ERA UN DEFECTO MÍO y lo destapó el build 6: yo leía `ALEPH_BROWSER_CONFIG` (una
    RUTA DE ARCHIVO que nadie exporta) mientras el registro declara `config_env:
    ALEPH_BROWSER_CONFIG_DIR` — un DIRECTORIO— y `config_file: browser.json`. El pack
    escribía la config perfecta (`baseURL` al borde, `X-Aleph-Workspace` y `X-Aleph-User`)
    y este archivo miraba una variable vacía: el turno moría en `sin_cerebro: base_url
    vacío`, con el pack sano y el `/health` en verde.

    Se lee el DIR + el nombre del archivo, que es el contrato del registro. La variable
    vieja queda como respaldo por si alguien apunta un archivo suelto en una prueba."""
    dir_cfg = os.environ.get("ALEPH_BROWSER_CONFIG_DIR", "")
    ruta = (Path(dir_cfg) / os.environ.get("ALEPH_BROWSER_CONFIG_FILE", "browser.json")
            if dir_cfg else Path(os.environ.get("ALEPH_BROWSER_CONFIG", "") or "/dev/null"))
    return ruta if ruta.is_file() else None


def _chromium() -> Optional[str]:
    """El binario que ya viaja. MEDIDO el 2026-08-18: `chrome-headless-shell` habla CDP 1.3
    y expone un target `page` navegable, así que **no hace falta un Chrome completo**.
    browser-use lo maneja por CDP (`cdp-use`), no por Playwright."""
    c = os.environ.get("ALEPH_BROWSER_CHROMIUM", "")
    return c if c and Path(c).is_file() else None


class _Handler(PlomeriaNDJSON, BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    COPY = COPY

    def do_GET(self) -> None:                                  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._json(200, {"ok": True, "servicio": "aleph-browser"})
        else:
            self._json(404, {"error": "ruta_desconocida", "copy": COPY["cuerpo_invalido"]})

    def do_POST(self) -> None:                                 # noqa: N802
        if not guard_post(self):
            return
        ruta = self.path.split("?", 1)[0].rstrip("/") or "/"
        cuerpo = self._leer_json()
        if cuerpo is None:
            return
        if ruta == "/parar":
            self._parar(cuerpo)
        elif ruta == "/manejar":
            self._manejar(cuerpo)
        else:
            self._json(404, {"error": "ruta_desconocida", "copy": COPY["cuerpo_invalido"]})

    # ── la obra ────────────────────────────────────────────────────────────────────
    def _manejar(self, cuerpo: dict) -> None:
        tarea = str(cuerpo.get("tarea") or "").strip()
        if not tarea:
            self._json(400, {"error": "tarea_vacia", "copy": COPY["tarea_vacia"]})
            return
        chrome = _chromium()
        if not chrome:
            self._json(503, {"error": "navegador_ausente", "copy": COPY["navegador_ausente"]})
            return
        ruta = _ruta_config()
        if ruta is None:
            self._json(503, {"error": "sin_cerebro", "copy": COPY["sin_cerebro"],
                             "detail": "el pack no dejó su archivo de config"})
            return
        try:
            # `desde_pack` = leer_pack + armar. ERA EL SEGUNDO DEFECTO: escribí `leer_pack`
            # para EXACTAMENTE la forma que el pack escribe y acá pedía una clave `cerebro`
            # que ese archivo no tiene. La función estaba; no la usaba.
            kw = COSTURA.desde_pack(ruta, space_id=cuerpo.get("space_id"))
        except COSTURA.CosturaError as e:
            self._json(503, {"error": "sin_cerebro", "copy": COPY["sin_cerebro"],
                             "detail": e.detalle})
            return
        # LAS CAPACIDADES LAS MANDA EL ROUTER, y es el único que puede: el pack no ve el
        # selector de modelos. Sin ellas, `perillas` no prende nada (fail-closed), que es
        # lo correcto — pero entonces el aviso diría «no ve» de un cerebro que quizá ve.
        perillas = PERFIL.perillas({"model_use_capabilities": cuerpo.get("capacidades")}
                                   if cuerpo.get("capacidades") is not None else None)
        turno = str(cuerpo.get("turno_id") or "").strip() or "turno"
        run_id = str(cuerpo.get("run_id") or turno)
        try:
            GUARD.importar_excepciones(run_id, cuerpo.get("loopback_grants", []))
        except ValueError:
            GUARD.desanotar(run_id)
            self._json(403, {"error": "loopback_grant_invalid", "copy": COPY["cuerpo_invalido"]})
            return
        with _LOCK:
            if _EN_CURSO:
                GUARD.desanotar(run_id)
                self._json(429, {"error": "capacidad_ocupada",
                                 "copy": "Ya hay una navegación activa. Espera o párala."})
                return
            _EN_CURSO[turno] = None

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            # EL AVISO VA PRIMERO: el usuario debe verlo antes del primer paso real.
            av = PERFIL.aviso({"model_use_capabilities": cuerpo.get("capacidades")}
                              if cuerpo.get("capacidades") is not None else None)
            if av:
                self._linea({"tipo": "aviso", **av})
            self._correr(tarea, kw, perillas, chrome, turno, run_id, cuerpo)
        except Cancelada:
            self._decir({"tipo": "fallo", "causa": "parado", "copy": COPY["parado"]})
        except BaseException as e:                              # noqa: BLE001
            self._decir({"tipo": "fallo", "causa": "motor_roto", "copy": COPY["motor_roto"],
                         "detalle": f"{type(e).__name__}: {e}"[:300]})
        finally:
            GUARD.desanotar(run_id)
            with _LOCK:
                _EN_CURSO.pop(turno, None)
            self._fin_chunked()

    def _correr(self, tarea, kw, perillas, chrome, turno, run_id, cuerpo) -> None:
        # The proxy owns the socket-level policy and its credentials live for
        # exactly this run. No proxy startup means no browser startup.
        with PINNED_PROXY.PinnedProxy(run_id) as proxy:
            self._correr_con_proxy(tarea, kw, perillas, chrome, turno, run_id, cuerpo, proxy)

    def _correr_con_proxy(self, tarea, kw, perillas, chrome, turno, run_id, cuerpo, proxy) -> None:
        import asyncio
        from browser_use import Agent, BrowserProfile
        from browser_use.browser.profile import ProxySettings
        from browser_use.llm.openai.chat import ChatOpenAI

        llm = ChatOpenAI(**kw,
                         dont_force_structured_output=perillas["dont_force_structured_output"],
                         add_schema_to_system_prompt=perillas["add_schema_to_system_prompt"],
                         temperature=0.0)
        # Browser-use's high-level navigation events do not cover redirects or
        # subresources.  The profile callback is enforced by CDP Fetch before every
        # request is sent; the house guard resolves every hostname and applies the
        # narrow per-run loopback exception.
        perfil = BrowserProfile(
            executable_path=chrome,
            headless=True,
            user_data_dir=os.environ.get("ALEPH_BROWSER_PROFILE_DIR") or None,
            args=["--disable-quic", "--disable-preconnect", "--dns-prefetch-disable",
                  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
            url_guard=lambda url: GUARD.permitir(url, run_id=run_id).ok,
            proxy=ProxySettings(server=proxy.server, bypass="<-loopback>",
                                username=proxy.username, password=proxy.password),
        )
        agente = Agent(task=tarea, llm=llm, browser_profile=perfil,
                       use_vision=perillas["use_vision"],
                       llm_timeout=perillas["llm_timeout"], max_actions_per_step=1)
        with _LOCK:
            _EN_CURSO[turno] = agente

        # ── EL PROGRESO, DESDE UN HECHO REAL Y NO DE UN RELOJ ──────────────────────
        # Regla madre de la Sala: «todo punto/estado/tilde viene de un evento REAL. Sin
        # evento → sin dibujo». Acá el evento es el paso que browser-use CERRÓ, con la
        # acción que ejecutó y la URL en la que quedó. Cero `setTimeout`, cero optimismo.
        paso = {"n": 0}

        async def _al_cerrar_paso(agent) -> None:
            paso["n"] += 1
            try:
                h = agent.history.history[-1]
                acciones = [next(iter(a.model_dump(exclude_none=True)), "?")
                            for a in (h.model_output.action if h.model_output else []) or []]
                url = (h.state.url if getattr(h, "state", None) else "") or ""
            except Exception:                                   # noqa: BLE001
                acciones, url = [], ""
            self._linea({"tipo": "estado", "etapa": "manejando", "paso": paso["n"],
                         "acciones": acciones, "url": url,
                         "texto": _texto_del_paso(paso["n"], acciones, url)})

        async def _run():
            max_steps = max(1, min(int(cuerpo.get("max_pasos") or 25), 100))
            return await agente.run(max_steps=max_steps,
                                    on_step_end=_al_cerrar_paso)

        hist = asyncio.run(_run())
        self._decir({"tipo": "obra", **_obra_de(hist, tarea, paso["n"])})

    def _parar(self, cuerpo: dict) -> None:
        turno = str(cuerpo.get("turno_id") or "").strip()
        with _LOCK:
            ag = _EN_CURSO.get(turno)
        if ag is None:
            self._json(404, {"error": "turno_desconocido", "copy": COPY["parado"]})
            return
        try:
            ag.stop()
        except Exception:                                       # noqa: BLE001
            pass
        self._json(200, {"ok": True, "parado": turno})


def _texto_del_paso(n: int, acciones: list, url: str) -> str:
    """El copy del paso. Deriva de la acción REAL, y si no la conoce lo dice —jamás
    inventa un verbo bonito para algo que no pasó."""
    verbo = {"navigate": "abriendo", "click": "tocando", "input": "escribiendo",
             "scroll": "bajando", "done": "terminando",
             "extract_structured_data": "leyendo"}.get(acciones[0] if acciones else "", "")
    corto = (url or "").replace("http://", "").replace("https://", "")[:60]
    if not verbo:
        return f"paso {n}" + (f" · {corto}" if corto else "")
    return f"paso {n} · {verbo}" + (f" en {corto}" if corto else "")


def _obra_de(hist, tarea: str, pasos: int) -> dict:
    """La obra del turno. `texto` es lo que el agente devolvió; **si no devolvió nada, no se
    inventa un resumen** — se dice que no hubo entregable."""
    texto, urls = "", []
    try:
        urls = [u for u in (hist.urls() or []) if u]
        final = hist.final_result()
        texto = final if isinstance(final, str) else ""
    except Exception:                                           # noqa: BLE001
        pass
    return {"pasos": pasos, "urls": sorted(set(urls)),
            "texto": texto, "hubo_entregable": bool(texto and texto.strip()),
            "titulo": tarea[:120]}


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    try:
        sidecar_port = int(os.environ.get("ALEPH_SIDECAR_PORT") or "0")
        if 1 <= sidecar_port <= 65535:
            GUARD.fijar_sidecar(sidecar_port)
    except ValueError:
        pass  # no trusted port declaration means all loopback fails closed
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), _Handler)
    print(f"Aleph Browser: escuchando en http://127.0.0.1:{srv.server_port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
