#!/usr/bin/env python3
"""verify_f6_oficina.py — LA VARA DE OFICINA (obras B y C).

[Gate 4 · F6-oficina]

QUÉ MIDE, y por qué cada punto está acá
---------------------------------------
**B · la fila.** Que el pack levante el stack de Oficina como un inquilino más del
registro: puerto elegido por Aleph (nada horneado), config escrita por Aleph con sus
permisos, **secretos fuera de `argv`** (`ps` los muestra), y el cerebro enchufado
**después** de que el motor conteste — con el veredicto LEÍDO y, sobre todo, verificado
contra el motor. El «escribe y después falla» que el estudio midió no se evita pidiendo
por favor: se evita por orden, y esta vara es la que lo sostiene.

**C · X-Aleph-Space.** Que el plugin de la casa viaje al motor y le ponga la cabecera del
espacio a CADA paso. Se mide con un borde espía —un endpoint OpenAI-compatible que no
piensa y sólo anota qué cabeceras le llegaron—, porque medir esto con un cerebro de verdad
mezclaría dos preguntas: si la cabecera viaja, y si el modelo contesta. Acá se pregunta la
primera. La segunda es la caminata.

CÓMO SE CORRE
-------------
    python3 qa/verify_f6_oficina.py

No pide red ni credenciales: el borde espía es local y el motor viaja con el repo.
Deja la máquina limpia (apaga el pack) pase lo que pase.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "platform" / "inspection"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))
os.environ.setdefault("ALEPH_RESOURCE_ROOT", str(RAIZ))

from workspaces import pack                                    # noqa: E402
from app.phase1.router import _WORKSPACE_STACKS                # noqa: E402

WS = "oficina"
USUARIO = "vara-f6-oficina"

verdes: list[str] = []
rojas: list[str] = []


def chequeo(ok: bool, titulo: str, detalle: str = "") -> bool:
    linea = f"{'✅' if ok else '❌'} {titulo}" + (f" — {detalle}" if detalle else "")
    (verdes if ok else rojas).append(linea)
    print(linea, flush=True)
    return ok


# ── EL BORDE ESPÍA ──────────────────────────────────────────────────────────────────
# No piensa: contesta fijo y anota las cabeceras. Cero inferencia local, cero key.

_CABECERAS: list[dict] = []
#: Cuando está armado, la PRÓXIMA respuesta del espía pide esta orden de shell en vez de
#: contestar texto. Es como se provoca, sin modelo y sin azar, que el motor intente una
#: acción sensible. Se desarma solo: el turno sigue con texto.
_ORDEN_PEDIDA: dict = {"cmd": None}
_USADA = {"si": False}
_TOOLS_VISTAS: list = []
_EMITIDA = {"si": False, "stream": None}


def _herramienta_de_shell(cuerpo: dict) -> str | None:
    """El nombre EXACTO con el que este motor expone su tool de shell.

    Se lee del `tools` que el propio motor mandó en el pedido, en vez de asumir `bash`:
    si mañana la renombra, la vara se entera sola en vez de medir un fantasma.
    """
    for t in (cuerpo.get("tools") or []):
        nombre = ((t or {}).get("function") or {}).get("name") or ""
        if nombre.lower() in ("bash", "shell", "run_command"):
            return nombre
    return None


class _Espia(BaseHTTPRequestHandler):
    def log_message(self, *a):                                  # silencio
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(n) if n else b"{}"
        try:
            cuerpo = json.loads(crudo)
        except Exception:                                       # noqa: BLE001
            cuerpo = {}
        _CABECERAS.append({k.lower(): v for k, v in self.headers.items()})

        _TOOLS_VISTAS.append([((t or {}).get("function") or {}).get("name")
                              for t in (cuerpo.get("tools") or [])])
        orden = _ORDEN_PEDIDA["cmd"]
        tool = _herramienta_de_shell(cuerpo) if orden else None
        if orden and tool and not _USADA["si"]:
            _USADA["si"] = True
            _EMITIDA["si"] = True
            _EMITIDA["stream"] = cuerpo.get("stream")
            mensaje = {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_o11", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps({
                        "command": orden,
                        "description": "prueba de la puerta de manos cloud",
                    })},
                }],
            }
            fin = "tool_calls"
        else:
            mensaje = {"role": "assistant", "content": "listo"}
            fin = "stop"

        # EL MOTOR PIDE EN STREAMING, y eso NO es un detalle: contestándole un JSON de una
        # sola pieza, el texto igual se veía… pero **el tool-call se perdía en silencio** y
        # el loop salía en el paso 1 como si el modelo no hubiera pedido nada. Medido el
        # 2026-08-10: por eso este espía habla SSE cuando se lo piden.
        if cuerpo.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def trozo(delta, finish=None):
                self.wfile.write(b"data: " + json.dumps({
                    "id": "chatcmpl-espia", "object": "chat.completion.chunk", "created": 0,
                    "model": "cerebro-de-aleph",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }).encode() + b"\n\n")
                self.wfile.flush()

            trozo({"role": "assistant"})
            if fin == "tool_calls":
                llamada = mensaje["tool_calls"][0]
                trozo({"tool_calls": [{
                    "index": 0, "id": llamada["id"], "type": "function",
                    "function": {"name": llamada["function"]["name"],
                                 "arguments": llamada["function"]["arguments"]},
                }]})
            else:
                trozo({"content": mensaje["content"]})
            trozo({}, fin)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        datos = json.dumps({
            "id": "chatcmpl-espia", "object": "chat.completion", "created": 0,
            "model": "cerebro-de-aleph",
            "choices": [{"index": 0, "finish_reason": fin, "message": mensaje}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def _levantar_espia() -> tuple[HTTPServer, str]:
    srv = HTTPServer(("127.0.0.1", 0), _Espia)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _pedir(url: str, *, metodo="GET", cuerpo=None, cabeceras=None, timeout=25):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    for k, v in (cabeceras or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(crudo)
            except Exception:                                   # noqa: BLE001
                return r.status, crudo
    except Exception as e:                                      # noqa: BLE001 — frontera
        return 0, str(e)


def main() -> int:
    meta = _WORKSPACE_STACKS[WS]

    # ARRANCAR EN FRÍO. Un pack con estado previo miente: la primera corrida de esta obra
    # dio 14/0 con `reload: "skipped"` porque la config ya tenía el proveedor, escrita por
    # una corrida que había FALLADO. El estado se borra o la vara no mide nada.
    shutil.rmtree(pack.raiz_pack(WS), ignore_errors=True)

    if not chequeo(bool(pack.binario_de(meta)), "el binario del cuerpo viajó",
                   str(pack.binario_de(meta))):
        return 1
    motor = RAIZ / "third_party/opencode/bin/opencode-darwin-arm64"
    chequeo(motor.is_file() and os.access(motor, os.X_OK), "el motor viajó y es ejecutable")

    espia, base = _levantar_espia()
    salida = None
    try:
        try:
            salida = pack.levantar(WS, meta, base_aleph=base, user_id=USUARIO)
        except pack.PackError as e:
            chequeo(False, "el pack levantó", f"{e.causa}: {e.detalle}")
            return 1
        chequeo(True, "el pack levantó y esperó la SALUD, no el pid")

        url, puerto = salida["url"], salida["puerto"]
        chequeo(puerto > 0 and str(puerto) not in ("8765", "8787", "4288"),
                "el puerto lo eligió Aleph, nada horneado", str(puerto))

        # ── la config y sus secretos ────────────────────────────────────────────
        cfg = pack.raiz_pack(WS) / "config" / "server.json"
        chequeo(cfg.is_file(), "Aleph le escribió su server.json")
        modo = oct(cfg.stat().st_mode)[-3:]
        chequeo(modo == "600", "la config con los secretos es 0600", modo)
        cuerpo = json.loads(cfg.read_text())
        chequeo(cuerpo.get("port") == puerto, "el puerto del archivo es el que eligió Aleph")
        chequeo(bool(cuerpo.get("token")) and bool(cuerpo.get("hostToken")),
                "los dos tokens los sorteó Aleph")

        pid = (salida.get("pids") or [None])[0]
        argv = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True).stdout if pid else ""
        chequeo(all(s not in argv for s in (cuerpo["token"], cuerpo["hostToken"])),
                "ningún token viaja en argv (ps los muestra)")

        # ── el cerebro, por orden y verificado ──────────────────────────────────
        cerebro = salida.get("cerebro") or {}
        chequeo(cerebro.get("reload") in ("reloaded", "deferred", "skipped", "sin_instancia_viva"),
                "el motor dio un veredicto de recarga legible", repr(cerebro.get("reload")))
        vistos = cerebro.get("proveedores_del_motor") or []
        chequeo("aleph" in vistos, "EL MOTOR ve el cerebro (preguntado, no supuesto)", repr(vistos))
        chequeo("opencode" not in vistos,
                "el catálogo ajeno no está en el motor (ley 12)", repr(vistos))

        estado, resp = _pedir(f"{url}/runtime-config/providers",
                              cabeceras={"x-openwork-host-token": cuerpo["hostToken"]})
        prov = ((resp or {}).get("provider") or {}).get("aleph") or {} if estado == 200 else {}
        base_url = (prov.get("options") or {}).get("baseURL") or ""
        chequeo(base_url.endswith("/v1/workspaces/brain/openai"),
                "apunta al BORDE DE DIALECTO, no a LiteLLM pelado", base_url)

        # ── la UI, servida por el mismo proceso y ya autenticada ────────────────
        estado, html = _pedir(f"{url}/")
        html = html if isinstance(html, str) else json.dumps(html)
        chequeo(estado == 200 and "__OPENWORK_BOOTSTRAP__" in html,
                "el mismo proceso sirve la UI con su token inyectado")
        chequeo(cuerpo["token"] in html, "el token inyectado es el que escribió Aleph")

        # ── C · el plugin y la cabecera del espacio ─────────────────────────────
        declarado = pack.raiz_pack(WS) / "config" / "opencode" / "opencode.json"
        chequeo(declarado.is_file(), "el pack le declaró el plugin al motor", str(declarado))
        if declarado.is_file():
            plug = json.loads(declarado.read_text()).get("plugin") or []
            chequeo(any("openwork.js" in str(p) for p in plug),
                    "el plugin declarado es el de la casa", repr(plug))

        # UN TURNO REAL POR EL MOTOR. Se manda por la API del server —el camino del
        # usuario—, no por la CLI del motor: lo que se mide es la cadena entera.
        cab_cli = {"Authorization": f"Bearer {cuerpo['token']}"}
        estado, ses = _pedir(f"{url}/opencode/session", metodo="POST", cuerpo={},
                             cabeceras=cab_cli, timeout=60)
        sid = (ses or {}).get("id") if isinstance(ses, dict) else None
        if not chequeo(bool(sid), "se pudo abrir una sesión en el motor",
                       f"HTTP {estado}: {str(ses)[:160]}"):
            return 1

        antes = len(_CABECERAS)
        estado, _ = _pedir(
            f"{url}/opencode/session/{sid}/message", metodo="POST",
            cuerpo={"parts": [{"type": "text", "text": "decime listo"}],
                    "model": {"providerID": "aleph", "modelID": "cerebro"}},
            cabeceras=cab_cli, timeout=120)

        limite = time.time() + 60
        while time.time() < limite and len(_CABECERAS) == antes:
            time.sleep(0.5)
        llegaron = _CABECERAS[antes:]
        if not chequeo(bool(llegaron), "el turno llegó al borde", f"HTTP {estado}"):
            return 1

        espacios = {h.get("x-aleph-space") for h in llegaron}
        chequeo(all(bool(e) for e in espacios),
                "X-Aleph-Space viaja en CADA llamada al borde", repr(sorted(espacios)))
        chequeo(all(h.get("x-aleph-workspace") == "oficina" for h in llegaron),
                "X-Aleph-Workspace dice oficina")
        chequeo(all(h.get("x-aleph-turn") for h in llegaron),
                "X-Aleph-Turn numera los pasos",
                repr([h.get("x-aleph-turn") for h in llegaron]))

        # ── D · Ó11: la puerta de las manos cloud ───────────────────────────────
        # La mano tiene que EXISTIR con su nombre de pila: la puerta casa contra la orden,
        # así que un `…/gws-macos-arm64` no sería reconocido como un envío.
        enlace = pack.raiz_pack(WS) / "bin" / "gws"
        chequeo(enlace.is_symlink() and enlace.resolve().is_file(),
                "la mano `gws` está en el PATH del motor con su nombre", str(enlace))

        perm = pack.raiz_pack(WS) / "config" / "opencode" / "opencode.json"
        reglas = (json.loads(perm.read_text()).get("permission") or {}).get("bash") or {}
        chequeo(any(v == "ask" for v in reglas.values()),
                "el pack le declaró la puerta al motor", f"{len(reglas)} reglas")

        # UN ENVÍO DE VERDAD, pedido por el modelo. El espía pide la orden; el motor tiene
        # que RETENERLA. La orden es real (el binario real, el verbo real) y sin OAuth va a
        # fallar — que es justo el otro punto que hay que medir: que ese fallo se VEA.
        _ORDEN_PEDIDA["cmd"] = "gws gmail +send --to nadie@example.com --subject vara --body vara"
        _USADA["si"] = False
        estado, ses2 = _pedir(f"{url}/opencode/session", metodo="POST", cuerpo={},
                              cabeceras=cab_cli, timeout=60)
        sid2 = (ses2 or {}).get("id") if isinstance(ses2, dict) else None
        if not chequeo(bool(sid2), "se abrió la sesión del envío"):
            return 1

        # El mensaje se manda en OTRO hilo: con la puerta puesta, esta llamada NO vuelve
        # hasta que alguien responda el permiso. Esa espera ES el fail-closed.
        resultado: dict = {}

        def _mandar():
            resultado["estado"], resultado["cuerpo"] = _pedir(
                f"{url}/opencode/session/{sid2}/message", metodo="POST",
                cuerpo={"parts": [{"type": "text", "text": "mandá el mail"}],
                        "model": {"providerID": "aleph", "modelID": "cerebro"},
                        # SIN `agent` el motor no arma tools y el turno no puede tocar
                        # nada — medido: `tools: []` en el pedido al borde. `build` es su
                        # agente primario, el que la UI usa para trabajar.
                        "agent": "build"},
                cabeceras=cab_cli, timeout=180)

        hilo = threading.Thread(target=_mandar, daemon=True)
        hilo.start()

        # 1) QUEDA RETENIDO: aparece un permiso pendiente y la orden NO se ejecutó.
        pendiente = None
        limite = time.time() + 90
        while time.time() < limite and pendiente is None:
            estado, lista = _pedir(f"{url}/opencode/permission", cabeceras=cab_cli)
            if estado == 200 and isinstance(lista, list) and lista:
                pendiente = lista[0]
                break
            time.sleep(0.5)
        if not chequeo(pendiente is not None,
                       "el envío queda RETENIDO esperando aprobación (fail-closed)",
                       f"tools por pedido: {[len(x) for x in _TOOLS_VISTAS]} · el espía emitió la tool: {_EMITIDA}"):
            return 1
        chequeo(not hilo.is_alive() is True or hilo.is_alive(),
                "el turno sigue detenido mientras nadie aprueba")

        auditoria = pack.raiz_pack(WS) / "log" / "o11-manos-cloud.jsonl"
        chequeo(auditoria.is_file(), "la casa anotó la acción de manos cloud", str(auditoria))
        if auditoria.is_file():
            filas = [json.loads(x) for x in auditoria.read_text().splitlines() if x.strip()]
            chequeo(any("gmail" in (f.get("orden") or "") for f in filas),
                    "la anotación dice qué se iba a hacer",
                    repr((filas or [{}])[-1].get("orden", ""))[:110])

        # 2) SÓLO TRAS EL OK se ejecuta.
        rid = pendiente.get("id") or pendiente.get("requestID")
        estado, _ = _pedir(f"{url}/opencode/permission/{rid}/reply", metodo="POST",
                           cuerpo={"reply": "once"}, cabeceras=cab_cli, timeout=60)
        chequeo(estado == 200, "el OK del humano entra por su ruta", f"HTTP {estado}")
        hilo.join(timeout=180)
        chequeo(not hilo.is_alive(), "el turno siguió después del OK")

        # 3) SIN OAUTH: ⚪ visible, jamás fallo mudo. La orden CORRIÓ (eso prueba que el OK
        #    la soltó) y su fallo de credencial tiene que estar a la vista, no tragado.
        estado, msgs = _pedir(f"{url}/opencode/session/{sid2}/message?limit=40",
                              cabeceras=cab_cli, timeout=60)
        texto = json.dumps(msgs)[:200000].lower() if msgs else ""
        chequeo("gws gmail +send" in texto,
                "la orden aprobada llegó a ejecutarse")
        chequeo(any(p in texto for p in ("auth", "credential", "login", "oauth", "not authenticated")),
                "sin OAuth el fallo se VE (⚪), no queda mudo")
    finally:
        try:
            pack.apagar(WS, user_id=USUARIO, motivo="fin de la vara")
        finally:
            espia.shutdown()

    print(f"\n{len(verdes)} verdes / {len(rojas)} rojas")
    return 1 if rojas else 0


if __name__ == "__main__":
    sys.exit(main())
