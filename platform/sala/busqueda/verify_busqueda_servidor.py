#!/usr/bin/env python3
"""verify_busqueda_servidor.py — la vara de `servidor.py`. [Gate 4 · Fase 6 · §6.a.bis]

EL ROJO QUE ESTA VARA EXISTE PARA ATRAPAR
------------------------------------------
No es un fallo: es un **verde mudo**. Si `servidor.py` deja de mandar `sources: ["web"]`,
el motor arma cero herramientas de búsqueda, el modelo no busca, y el turno **igual
termina bien**: 200, `messageEnd`, y una respuesta cortés sobre resultados vacíos. Sin
error, sin fuentes, sin una sola señal. Una sesión entera se fue detrás de eso.

Por eso el caso B **parchea `_SOURCES` a `[]` y exige que la vara CAIGA**. Una vara que
no puede dar rojo no mide nada, y acá el rojo hay que provocarlo a propósito porque el
sistema no lo produce solo.

EL MOTOR ES UN STUB GUIONADO, y no es pereza: contra el Vane real esta vara dependería de
la red, del cerebro y de la cuota, y tardaría minutos. El stub reproduce **el cable real
capturado** (`qa/fixtures/vane_cable_web.ndjson`, un turno con Claude y SearXNG de
verdad) y además **replica la condición que importa**: si el body no trae `sources`
con `web`, contesta el cable SIN búsqueda y SIN fuentes, con 200, como hace el de verdad.

    python3 verify_busqueda_servidor.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[2]
_FIXTURE = _RAIZ / "qa" / "fixtures" / "vane_cable_web.ndjson"

_FALLOS: list[str] = []


def ok(cond: bool, texto: str) -> bool:
    print(f"  {'✓' if cond else '✗'} {texto}")
    if not cond:
        _FALLOS.append(texto)
    return cond


def puerto_libre() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


# ── el motor guionado ─────────────────────────────────────────────────────────
class _Vane(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    cuerpos_vistos: list[dict] = []

    def log_message(self, *a):  # silencio
        pass

    def do_GET(self):
        if self.path.startswith("/api/providers"):
            self._json({"providers": [
                {"id": "prov-chat", "name": "Cerebro de Aleph",
                 "chatModels": [{"name": "Cerebro", "key": "aleph/cerebro"}],
                 "embeddingModels": []},
                {"id": "prov-emb", "name": "Embeddings locales", "chatModels": [],
                 "embeddingModels": [{"name": "MiniLM", "key": "Xenova/all-MiniLM-L6-v2"}]},
            ]})
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        _Vane.cuerpos_vistos.append(cuerpo)
        # ⚠️ LA CONDICIÓN QUE REPLICA EL DEFECTO REAL (`webSearch.ts:84-86`).
        busca = "web" in (cuerpo.get("sources") or [])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for linea in (self._cable_real() if busca else self._cable_cortes()):
            crudo = (linea + "\n").encode()
            self.wfile.write(b"%x\r\n" % len(crudo)); self.wfile.write(crudo)
            self.wfile.write(b"\r\n")
        self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()

    @staticmethod
    def _cable_real():
        return [l.rstrip("\n") for l in _FIXTURE.read_text().splitlines() if l.strip()]

    @staticmethod
    def _cable_cortes():
        """Lo que el motor contesta SIN `sources`: 200, texto, cero fuentes, cero búsqueda."""
        return [
            json.dumps({"type": "block", "block": {"id": "r1", "type": "research",
                                                   "data": {"subSteps": []}}}),
            json.dumps({"type": "block", "block": {"id": "s1", "type": "source", "data": []}}),
            json.dumps({"type": "researchComplete"}),
            json.dumps({"type": "block", "block": {"id": "t1", "type": "text", "data": ""}}),
            json.dumps({"type": "updateBlock", "blockId": "t1", "patch": [
                {"op": "replace", "path": "/data",
                 "value": "Hmm, sorry I could not find any relevant information on this topic."}]}),
            json.dumps({"type": "messageEnd"}),
        ]

    def _json(self, o):
        c = json.dumps(o).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(c)))
        self.end_headers(); self.wfile.write(c)


def buscar(puerto: int, consulta: str) -> list[dict]:
    pedido = urllib.request.Request(f"http://127.0.0.1:{puerto}/buscar",
                                    data=json.dumps({"query": consulta}).encode(),
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=60) as r:
        return [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]


def correr(sources_vacio: bool) -> tuple[list[dict], subprocess.Popen]:
    """Levanta un `servidor.py` — con `_SOURCES` intacto, o saboteado a `[]`."""
    p_vane = puerto_libre()
    srv = ThreadingHTTPServer(("127.0.0.1", p_vane), _Vane)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    entorno = {**os.environ, "ALEPH_VANE_URL": f"http://127.0.0.1:{p_vane}"}
    if sources_vacio:
        # El sabotaje entra por `sitecustomize`, sin tocar el archivo: la vara mide el
        # servidor REAL, no una copia editada que podría divergir de él.
        sabotaje = _AQUI / ".vara_sabotaje"
        sabotaje.mkdir(exist_ok=True)
        (sabotaje / "sitecustomize.py").write_text(
            "import atexit, sys\n"
            "def _romper():\n"
            "    m = sys.modules.get('__main__')\n"
            "    if m is not None and hasattr(m, '_SOURCES'): m._SOURCES = []\n"
            "import threading; threading.Timer(0.35, _romper).start()\n")
        entorno["PYTHONPATH"] = f"{sabotaje}:{entorno.get('PYTHONPATH','')}"

    p_srv = puerto_libre()
    proc = subprocess.Popen([sys.executable, str(_AQUI / "servidor.py"), "--port", str(p_srv)],
                            env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p_srv}/health", timeout=1):
                break
        except Exception:                                          # noqa: BLE001
            time.sleep(0.2)
    time.sleep(0.5)      # que el sabotaje llegue antes del primer turno
    try:
        return buscar(p_srv, "who maintains SearXNG"), proc
    finally:
        srv.shutdown()


def main() -> int:
    if not _FIXTURE.exists():
        print(f"FALTA el fixture: {_FIXTURE}")
        return 2
    print("── A · con `sources: [\"web\"]` (como está el código) ──")
    lineas, proc = correr(sources_vacio=False)
    proc.terminate()
    tipos = [l.get("tipo") for l in lineas]
    estados = [l for l in lineas if l.get("tipo") == "estado"]
    resp = next((l for l in lineas if l.get("tipo") == "respuesta"), {})

    ok(tipos[:1] == ["abre"], "el turno abre con su espacio")
    ok("cierra" in tipos, "y cierra")
    ok(any(e.get("etapa") == "buscando" for e in estados), "hay etapa «buscando»")
    ok(any(e.get("etapa") == "leyendo" for e in estados), "hay etapa «leyendo»")
    ok(any("resultados" in (e.get("texto") or "") for e in estados),
       "la línea de razonamiento dice cuántos resultados")
    n_fuentes = len(resp.get("fuentes") or [])
    ok(n_fuentes >= 10, f"la respuesta trae fuentes citadas (fueron {n_fuentes})")
    ok(all(f.get("url", "").startswith("http") for f in (resp.get("fuentes") or [])),
       "todas las fuentes tienen URL")
    ok(len(resp.get("texto") or "") > 500, "y trae la respuesta redactada")
    ok(bool(resp.get("sha256")), "con su sha256 para el pasaporte")
    ok("web" in ((_Vane.cuerpos_vistos or [{}])[-1].get("sources") or []),
       "al motor le llegó sources=[web]")

    print("\n── B · EL ROJO: el mismo servidor con `_SOURCES = []` ──")
    print("   (el motor contesta 200 igual — es un verde mudo, no un fallo)")
    _Vane.cuerpos_vistos = []
    lineas_b, proc_b = correr(sources_vacio=True)
    proc_b.terminate()
    resp_b = next((l for l in lineas_b if l.get("tipo") == "respuesta"), {})
    estados_b = [l for l in lineas_b if l.get("tipo") == "estado"]
    cuerpo_b = (_Vane.cuerpos_vistos or [{}])[-1]

    saboteado = "web" not in (cuerpo_b.get("sources") or [])
    if not saboteado:
        print("  ! el sabotaje no llegó a aplicarse — el caso B no midió nada")
        _FALLOS.append("[no medible] el caso B no pudo sabotear _SOURCES")
    else:
        ok(bool(lineas_b) and any(l.get("tipo") == "respuesta" for l in lineas_b),
           "el turno TERMINA BIEN igual (esto es lo peligroso)")
        ok(not any(l.get("tipo") == "fallo" for l in lineas_b),
           "y no reporta ningún fallo")
        ok(len(resp_b.get("fuentes") or []) == 0, "pero se queda SIN fuentes")
        ok(not any(e.get("etapa") == "buscando" for e in estados_b),
           "y sin etapa «buscando» en la línea de razonamiento")
        ok(resp_b.get("aviso") == "sin_fuentes",
           "→ y el servidor LO DICE: aviso «sin_fuentes» con su copy")

    print()
    if _FALLOS:
        print(f"FAIL · {len(_FALLOS)} comprobación(es) en rojo:")
        for f in _FALLOS:
            print(f"   · {f}")
        return 1
    print("PASS · la búsqueda trae fuentes, y el verde mudo queda atrapado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
