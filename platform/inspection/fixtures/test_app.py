"""
fixtures/test_app.py — TARGET BENIGNO y CONTROLADO para el deliverable de FASE 1.

Un mini app que Aleph controla (cumple el guard: nada de sistemas de terceros).
Imita un software de "registro de asistencia": una pantalla con un form real y,
alrededor, el RUIDO típico de una web (logo, CSS/JS, analytics beacon, un feed
JSON y un poll cada 300ms). El submit dispara un fetch POST JSON a /api/attendance.

Sirve para demostrar que correlate AÍSLA la request real entre ~decenas de
llamadas de ruido. No persiste nada: el POST sólo devuelve un ok sintético.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def _page(drift: bool = False) -> str:
    """
    La pantalla del software. Con `drift=True` simula que el software CAMBIÓ bajo una
    tool ya sintetizada: el campo `codigo` se renombró a `matricula`, el endpoint se
    movió a `/api/attendance/v2` y se agregó `seccion`. La tool vieja se rompería
    silenciosa — eso es lo que el health-check de drift debe detectar.
    """
    second_field = (
        '<label>Matrícula <input id="matricula" name="matricula" type="text" required placeholder="2026-0000"></label>'
        if drift else
        '<label>Código <input id="codigo" name="codigo" type="text" required placeholder="A-0000"></label>'
    )
    endpoint = "/api/attendance/v2" if drift else "/api/attendance"
    submit_js = (
        """
    const alumno = document.getElementById('alumno').value;
    const matricula = document.getElementById('matricula').value;
    const r = await fetch('%s', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alumno, matricula, seccion: 'A', curso: 'FIS-101', presente: true })
    });""" % endpoint
        if drift else
        """
    const alumno = document.getElementById('alumno').value;
    const codigo = document.getElementById('codigo').value;
    const r = await fetch('%s', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alumno, codigo, curso: 'FIS-101', presente: true })
    });""" % endpoint
    )
    return """<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Asistencia · Curso FIS-101</title>
<link rel="stylesheet" href="/static/app.css">
<script src="/static/vendor.js"></script>
</head><body>
<img src="/static/logo.png" alt="logo">
<h1>Registrar asistencia</h1>
<form id="form-asistencia">
  <label>Alumno <input id="alumno" name="alumno" type="text" required placeholder="Nombre y apellido"></label>
  %s
  <button id="enviar" type="submit">Registrar</button>
</form>
<p id="resultado"></p>
<script>
  // RUIDO de carga: analytics + feed + poll periódico (simula las ~50 llamadas)
  fetch('/api/analytics/collect?e=pageview&t=' + Date.now());
  fetch('/api/feed').then(r => r.json());
  setInterval(() => fetch('/api/ping?ts=' + Date.now()), 300);

  // SEÑAL: el submit hace un POST JSON real a la API de asistencia
  document.getElementById('form-asistencia').addEventListener('submit', async (e) => {
    e.preventDefault();%s
    const d = await r.json();
    document.getElementById('resultado').textContent = 'OK ' + d.id;
  });
</script>
</body></html>""" % (second_field, submit_js)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # silencio

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            drift = bool(getattr(self.server, "drift", False))
            self._send(200, _page(drift).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/static/app.css":
            self._send(200, b"body{font-family:sans-serif}", "text/css")
        elif path == "/static/vendor.js":
            self._send(200, b"/* vendor */", "application/javascript")
        elif path == "/static/logo.png":
            self._send(200, b"\x89PNG\r\n", "image/png")
        elif path == "/api/analytics/collect":
            self._send(204, b"")
        elif path == "/api/feed":
            self._send(200, json.dumps({"items": [1, 2, 3]}).encode())
        elif path == "/api/ping":
            self._send(200, json.dumps({"ok": True}).encode())
        else:
            self._send(404, json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b""
        if path in ("/api/attendance", "/api/attendance/v2"):
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            # NO persiste: respuesta sintética (guard: sólo observar/sintetizar)
            self._send(200, json.dumps({"status": "ok", "id": "att_7f3a", "echo": data}).encode())
        else:
            self._send(404, json.dumps({"error": "not found"}).encode())


class BenignTestApp:
    """Arranca el app en un puerto efímero de localhost, en un thread daemon.

    `drift=True` sirve la variante con el software CAMBIADO (campo renombrado +
    endpoint movido): para probar que el health-check detecta la deriva."""

    def __init__(self, drift: bool = False):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.drift = drift   # lo lee el handler por request
        self.port = self._srv.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()
