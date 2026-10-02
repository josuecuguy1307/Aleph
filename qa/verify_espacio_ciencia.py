#!/usr/bin/env python3
"""verify_espacio_ciencia.py — EL TURNO DEL WORKSPACE, CON ESPACIO Y CON PROCEDENCIA.
[Gate 4 · Fase 4 · obra O2 · deuda 6 de la caminata de F3 · H6 de la auditoría]

QUÉ AFIRMA
----------
Que un turno hecho ADENTRO del workspace deja rastro auditable en la casa:

  1. el stack manda **`X-Aleph-Space`** en CADA paso del harness — la cabecera que el borde
     aceptaba desde el día uno y que nadie le mandaba
  2. el espacio es el MISMO durante todo el turno, y el `X-Aleph-Turn` cuenta los pasos
  3. el id del espacio pasa el filtro de la casa (`provenance.safe_ref`)
  4. al terminar, el turno **se cierra** contra ese mismo espacio (`/workspaces/brain/close`)
  5. lo que el stack produjo **cruza el puente** (`/workspaces/artifacts`) y gana identidad
  6. el hilo del workspace y la Biblioteca son los de la casa (`chat_id` y `sid` viajan)

CÓMO SE MIDE, Y QUÉ NO SE FINGE
-------------------------------
El proxy de esta vara hace UNA sola cosa: se hace pasar por el **paso al modelo**
(`/v1/workspaces/brain/openai/chat/completions`) para poder LEER LAS CABECERAS que el stack
manda, y contesta un sobre OpenAI válido. **Todo lo demás lo reenvía al backend real**, así
que el cierre del turno y el cruce del artefacto se escriben de verdad, contra el almacén
de verdad.

Se finge el paso al modelo porque la alternativa sería correr un modelo, y esta casa no
corre inferencia local ni usa una llave para una vara. **Lo que esta vara NO afirma, y hay
que decirlo:** que el borde escriba el `workspace_step` en el espacio que recibe. Eso es
del borde (territorio de F5) y está certificado aparte —`qa/verify_borde_dialecto.mjs`,
24/0—. Acá se certifica **la costura**: que la cabecera salga, y salga bien.

PROBADA CAYENDO
---------------
`--caer sin-plugin`   → se levanta el pack sin declarar el plugin: los pasos 1-6 caen.
`--caer sin-cerrar`   → se ignora el `close`: cae el paso 4.

    python3 qa/verify_espacio_ciencia.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "platform/inspection"))

CAER = ""
for i, a in enumerate(sys.argv):
    if a == "--caer" and i + 1 < len(sys.argv):
        CAER = sys.argv[i + 1]

fallos: list[str] = []
#: Lo que el proxy vio pasar. Es la evidencia cruda de la vara.
VISTO: dict = {"modelo": [], "cerrar": [], "artefactos": []}
#: El gancho para que el arnés produzca un artefacto A MITAD del turno (lo llena `main`).
ARTEFACTO: dict = {}


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {etiqueta}{('  ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallos.append(etiqueta)


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def python_del_backend() -> str:
    for c in [RAIZ / "product/backend/.venv/bin/python"]:
        if c.is_file():
            return str(c)
    print("✗ no encontré el venv del backend", file=sys.stderr)
    sys.exit(2)


def _hacer_proxy(destino: str):
    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):                          # noqa: D102 — silencio
            pass

        def _leer(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _responder(self, codigo: int, cuerpo: bytes, tipo="application/json"):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _sse(self, texto: str):
            ident, creado = "chatcmpl-vara", int(time.time())

            def trozo(delta, fin=None):
                return ("data: " + json.dumps({
                    "id": ident, "object": "chat.completion.chunk", "created": creado,
                    "model": "vara/cerebro",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
                }) + "\n\n").encode()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(trozo({"role": "assistant", "content": ""}))
            self.wfile.write(trozo({"content": texto}))
            self.wfile.write(trozo({}, "stop"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True

        def do_GET(self):                                   # noqa: N802
            self._reenviar(b"", "GET")

        def do_POST(self):                                  # noqa: N802
            cuerpo = self._leer()
            ruta = self.path
            if ruta.endswith("/chat/completions"):
                # EL ÚNICO FINGIDO: el paso al modelo. Se anota TODO lo que llegó.
                pedido = json.loads(cuerpo or b"{}")
                VISTO["modelo"].append({
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": pedido,
                })
                texto = "listo: 3 secuencias revisadas."
                # A MITAD DEL TURNO, EL STACK PRODUCE ALGO — que es cuando pasa de verdad:
                # el modelo pide una tool, la tool escribe un archivo y lo anota en el grafo
                # de procedencia del propio stack. Acá se hace por su MISMA ruta pública
                # (`POST /provenance/nodes`), no metiendo mano en su almacén.
                if len(VISTO["modelo"]) == 1 and ARTEFACTO.get("crear"):
                    try:
                        ARTEFACTO["crear"]()
                    except Exception as e:                  # noqa: BLE001
                        ARTEFACTO["error"] = str(e)
                if pedido.get("stream"):
                    # SSE, COMO LO HACE EL BORDE DE VERDAD (`router.py`, `_chunk`). No es
                    # un detalle: el cliente OpenAI del stack pide `stream:true`, y un
                    # falso que contestara JSON pelado devolvería un turno SIN TEXTO. Lo
                    # cazó esta misma vara —el `answer` salía vacío— y el defecto era del
                    # arnés, no del plugin. Un arnés que no habla el dialecto del sujeto
                    # mide su propia limitación.
                    return self._sse(texto)
                respuesta = {
                    "id": "chatcmpl-vara", "object": "chat.completion",
                    "created": int(time.time()), "model": "vara/cerebro",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": texto}}],
                }
                return self._responder(200, json.dumps(respuesta).encode())
            if "/workspaces/brain/close" in ruta:
                VISTO["cerrar"].append(json.loads(cuerpo or b"{}"))
                if CAER == "sin-cerrar":
                    return self._responder(200, b'{"ignorado":true}')
            if "/workspaces/artifacts" in ruta:
                VISTO["artefactos"].append(json.loads(cuerpo or b"{}"))
            return self._reenviar(cuerpo, "POST")

        def _reenviar(self, cuerpo: bytes, metodo: str):
            req = urllib.request.Request(destino + self.path, data=cuerpo or None,
                                         method=metodo)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length", "connection"):
                    req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return self._responder(r.status, r.read(),
                                           r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                return self._responder(e.code, e.read() or b"{}")
            except Exception as e:                          # noqa: BLE001
                return self._responder(502, json.dumps({"proxy": str(e)}).encode())

    return Proxy


def pedir(url: str, metodo="GET", cuerpo=None, timeout=90.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read()
            try:
                return r.status, json.loads(crudo or b"null")
            except Exception:                               # noqa: BLE001
                return r.status, crudo.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", "replace")


def main() -> int:
    from workspaces import pack as ws_pack

    datos = Path(tempfile.mkdtemp(prefix="f4-espacio-"))
    os.environ["ALEPH_DATA_DIR"] = str(datos)
    os.environ["ALEPH_ROLE"] = "client"

    meta = {
        "health": "/global/health",
        "bin": ["third_party/openscience/bin/openscience",
                "third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience"],
        "serve_args": ["serve"],
        "config_env": "OPENSCIENCE_CONFIG_DIR", "data_env": "OPENSCIENCE_DATA_DIR",
        "config_file": "openscience.json",
        "brain_path": "/v1/workspaces/brain/openai", "cerebro_label": "Cerebro de Aleph",
        "plugin": "platform/workspaces/plugins/openscience.js",
    }
    if CAER == "sin-plugin":
        meta.pop("plugin")

    p_backend, p_proxy = puerto_libre(), puerto_libre()
    backend = subprocess.Popen(
        [python_del_backend(), "-m", "uvicorn", "app.main:app",
         "--app-dir", str(RAIZ / "product/backend"),
         "--host", "127.0.0.1", "--port", str(p_backend)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "ALEPH_ENV": "dev", "PUPPET_ALLOW_ANON_V1": "1"})
    srv = ThreadingHTTPServer(("127.0.0.1", p_proxy), _hacer_proxy(f"http://127.0.0.1:{p_backend}"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pids: list[int] = []
    try:
        vivo = False
        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{p_backend}/health", timeout=2)
                vivo = True
                break
            except Exception:                               # noqa: BLE001
                pass
        ok(vivo, "el backend real de la vara está en pie")
        if not vivo:
            return 1

        # ── EL PACK, APUNTADO AL PROXY ──────────────────────────────────────────────
        v = ws_pack.levantar("ciencia", meta, base_aleph=f"http://127.0.0.1:{p_proxy}",
                             user_id=None, token="tok-vara", puppet_id=None,
                             chat_id="chat-de-la-vara", sid="sid-de-la-vara")
        pids = list(v["pids"])
        stack = v["url"]
        ok(bool(pids), "el pack está vivo", stack)

        cfg = json.loads((datos / "workspaces/ciencia/config/openscience.json").read_text())
        tiene = bool(cfg.get("plugin"))
        ok(tiene == (CAER != "sin-plugin"),
           "la config declara el plugin de la casa por file://",
           str(cfg.get("plugin", []))[:110])

        # ── UN TURNO DE VERDAD ADENTRO DEL STACK ────────────────────────────────────
        # EL ARCHIVO QUE EL TURNO VA A PRODUCIR. Es un informe real (markdown de verdad, no
        # un placeholder): el puente sólo entrega el tipo rico cuando hay DATO, así que un
        # archivo vacío mediría la ficha en vez del informe.
        obra = datos / "informe-de-la-vara.md"
        obra.write_text("# Secuencias revisadas\n\nTP53 · P04637 · 393 aa\n", encoding="utf-8")
        ARTEFACTO["crear"] = lambda: pedir(stack + "/provenance/nodes", "POST", {
            "kind": "artifact", "label": "informe-de-la-vara.md",
            "artifact_type": "report", "path": str(obra), "size": obra.stat().st_size})

        st, ses = pedir(stack + "/session", "POST", {"title": "vara del espacio"})
        sid_stack = (ses or {}).get("id") if isinstance(ses, dict) else None
        ok(bool(sid_stack), "se creó una sesión en el stack", str(sid_stack))
        if not sid_stack:
            return 1
        st, _ = pedir(f"{stack}/session/{sid_stack}/message", "POST", {
            "model": {"providerID": "aleph", "modelID": "cerebro"},
            "parts": [{"type": "text", "text": "contá las secuencias del proyecto"}]})
        ok(st == 200, "el turno corrió adentro del stack", f"({st})")

        for _ in range(40):                                 # el `session.idle` es asíncrono
            if VISTO["cerrar"]:
                break
            time.sleep(0.5)

        # ── 1-3 · LA CABECERA QUE FALTABA ───────────────────────────────────────────
        pasos = VISTO["modelo"]
        ok(bool(pasos), f"el stack le pidió al cerebro de la casa ({len(pasos)} paso/s)")
        espacios = {p["headers"].get("x-aleph-space") for p in pasos}
        ok(pasos and all(p["headers"].get("x-aleph-space") for p in pasos),
           "TODO paso lleva `X-Aleph-Space`", str(espacios)[:90])
        ok(len(espacios) == 1, "y es el MISMO espacio durante todo el turno")
        import re
        espacio = next(iter(espacios)) if espacios else ""
        ok(bool(espacio) and bool(re.match(r"^[A-Za-z0-9._:-]{1,120}$", espacio or "")),
           "el id del espacio pasa el filtro de `provenance.safe_ref`", espacio or "—")
        turnos = [p["headers"].get("x-aleph-turn") for p in pasos]
        ok(turnos == [str(i + 1) for i in range(len(pasos))],
           "`X-Aleph-Turn` cuenta los pasos del harness", str(turnos))
        ok(pasos and all(p["headers"].get("x-aleph-chat") == "chat-de-la-vara" for p in pasos),
           "el hilo del workspace viaja en cada paso")
        ok(pasos and all(p["headers"].get("x-aleph-workspace") == "ciencia" for p in pasos),
           "y la cabecera de workspace de la config sigue llegando")
        ok(pasos and all((p["headers"].get("authorization") or "").endswith("tok-vara")
                         for p in pasos),
           "la sesión de Aleph viaja como Bearer, no como una llave del stack")

        # ── 4 · EL CIERRE ───────────────────────────────────────────────────────────
        ok(bool(VISTO["cerrar"]), f"el turno se CIERRA ({len(VISTO['cerrar'])})")
        if VISTO["cerrar"]:
            c = VISTO["cerrar"][-1]
            ok(c.get("space_id") == espacio,
               "y se cierra contra el MISMO espacio de los pasos", str(c.get("space_id")))
            ok(c.get("workspace") == "ciencia", "declarando de qué workspace es el turno")
            ok(bool(c.get("answer")), "con la respuesta real del turno adentro",
               str(c.get("answer"))[:60])
            ok(c.get("chat_id") == "chat-de-la-vara",
               "y contra el hilo del workspace, no el de La Sala")

        # ── 6 · LA BIBLIOTECA ES UNA SOLA ───────────────────────────────────────────
        ajustes = json.loads((datos / "workspaces/ciencia/config/aleph-pack.json").read_text())
        ok(ajustes.get("sid") == "sid-de-la-vara" and ajustes.get("chat_id") == "chat-de-la-vara",
           "el pack le pasó al plugin el hilo y la Biblioteca de la casa")
        modo = oct((datos / "workspaces/ciencia/config/aleph-pack.json").stat().st_mode)[-3:]
        ok(modo == "600", "y sus ajustes (con la sesión adentro) son 0600", modo)

        # ── 5 · EL PUENTE, CRUZADO DE VERDAD ────────────────────────────────────────
        ok(not ARTEFACTO.get("error"),
           "el arnés pudo anotar el artefacto por la ruta del stack",
           str(ARTEFACTO.get("error") or ""))
        cruces = VISTO["artefactos"]
        ok(len(cruces) == 1, f"lo que el turno produjo CRUZÓ el puente ({len(cruces)})")
        if cruces:
            a = cruces[0]
            ok(a.get("kind") == "report" and a.get("workspace") == "ciencia",
               "cruzó con el `kind` del stack y su workspace", f"{a.get('kind')}")
            ok(a.get("space_id") == espacio,
               "atado AL MISMO espacio del turno que lo produjo — que es el punto de todo esto")
            ok(a.get("sid") == "sid-de-la-vara",
               "y a la Biblioteca de la casa, no a una segunda mitad invisible")
            ok("Secuencias revisadas" in json.dumps(a.get("data") or {}),
               "con el DATO adentro, no sólo la referencia (el puente entrega el tipo rico)")
        # Y el backend REAL lo guardó: el proxy reenvió el POST, así que esto es el almacén
        # de verdad contestando, no el recuerdo del proxy.
        st, lib = pedir(f"http://127.0.0.1:{p_backend}/v1/sessions/sid-de-la-vara/artifacts")
        obras = (lib or {}).get("artifacts", []) if isinstance(lib, dict) else []
        ok(any(o.get("type") == "informe" for o in obras),
           f"y el almacén REAL lo tiene, con el tipo canónico de la casa ({len(obras)} obra/s)",
           ", ".join(o.get("type", "?") for o in obras[:3]))
        # La procedencia NO viene en el listado —`list_artifacts` devuelve resúmenes para
        # la Biblioteca, sin lo pesado— así que se pide LA OBRA. (Lo aprendió esta vara:
        # afirmar sobre un resumen es afirmar sobre lo que el resumen decidió no traer.)
        aid = next((o.get("id") for o in obras if o.get("type") == "informe"), None)
        st, una = pedir(f"http://127.0.0.1:{p_backend}/v1/sessions/sid-de-la-vara/artifacts/{aid}")
        prov = ((una or {}).get("artifact") or una or {}).get("provenance") or {}
        ok(prov.get("produced_by") == "workspace" and prov.get("capture_quality") == "declared",
           "con la procedencia honesta: `workspace` ⇒ `declared`, jamás `exact`",
           f"{prov.get('produced_by')}/{prov.get('capture_quality')}")
        ok(prov.get("space_id") == espacio,
           "y con el espacio adentro: S8 ya tiene por dónde auditar este turno")

        bitacora = (datos / "workspaces/ciencia/log/pack.log")
        texto = bitacora.read_text() if bitacora.exists() else ""
        ok("plugin cargado" in texto or CAER == "sin-plugin",
           "el plugin dejó su rastro en la bitácora del pack",
           texto.splitlines()[0][:90] if texto else "—")
        ok("turno cerrado" in texto or CAER in ("sin-plugin", "sin-cerrar"),
           "y anotó el cierre con su cuenta de pasos y artefactos",
           next((l for l in texto.splitlines() if "turno cerrado" in l), "—")[:110])
    finally:
        try:
            ws_pack.apagar("ciencia", motivo="fin de la vara")
        except Exception:                                   # noqa: BLE001
            pass
        for p in pids:
            subprocess.run(["kill", "-9", str(p)], capture_output=True)
        srv.shutdown()
        try:
            os.killpg(os.getpgid(backend.pid), 15)
            backend.wait(timeout=8)
        except Exception:                                   # noqa: BLE001
            pass
        shutil.rmtree(datos, ignore_errors=True)

    print(f"\n{'VERDE' if not fallos else 'ROJAS: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
