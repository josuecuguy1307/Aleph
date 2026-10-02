#!/usr/bin/env python3
"""Dev server de la app ALEPH — superficie de producto CANÓNICA.

Sirve las pantallas .dc.html de product/app/design/ y proxya /v1, /catalog, /health
al backend (uvicorn :8080). Reenvía TODOS los verbos mutantes: GET/POST/DELETE/PUT/PATCH
(vía el proxy genérico `_px`, que pasa método+body+Authorization+Accept). La raíz "/" sirve Home.

[ticket 31 · INVARIANTE DE OPS] La capa de serving DEBE reenviar PATCH (además de PUT/DELETE)
al backend: el panel de memoria (o6) reclasifica/edita con `PATCH /v1/puppets/{id}/memories/{mid}`
— si el serving de prod (este serve.py o cualquier gateway que lo reemplace) NO reenvía PATCH, el
botón ⇄/editar del panel devuelve 501 en la UI aunque el backend responda 200. Hoy no hay un
gateway prod separado en el repo (serve.py es el serving); si se agrega uno (nginx/caddy/…), debe
pasar PATCH sí o sí.

    python3 product/app/serve.py          # → http://localhost:8091/

Requisito: el backend corriendo en :8080
    cd product/backend && .venv/bin/python -m uvicorn app.main:app \
        --app-dir $(pwd) --host 127.0.0.1 --port 8080

NOTA: este es el stack vigente (app Aleph :8091 + backend :8080). El builder standalone
de product/workshop/ quedó RETIRADO como superficie servida (duplicaba builder+sala y
colisionaba en :8080); sus archivos siguen en el repo solo como histórico.
"""
import http.server, socketserver, urllib.request, urllib.error, urllib.parse, os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "design")
# [T6 §10] la explicación larga vive en <repo>/docs/guia — dos niveles arriba de product/app/.
GUIA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "guia")
PORT = int(os.environ.get("ALEPH_FRONT_PORT", "8091"))
BACK = os.environ.get("ALEPH_BACKEND", "http://127.0.0.1:8080")
PROXY = ("/v1/", "/catalog/", "/health")


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def _px(self, m):
        p = urllib.parse.urlparse(self.path).path
        if not any(p.startswith(x) for x in PROXY):
            return False
        def loopback(raw):
            try:
                u = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
                return (u.hostname or "").lower().rstrip(".") in ("127.0.0.1", "localhost", "::1")
            except (TypeError, ValueError):
                return False
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if not loopback(host) or (origin and not loopback(origin)):
            self.send_error(403, "local origin required")
            return True
        body = None
        l = int(self.headers.get("Content-Length", 0))
        if l:
            body = self.rfile.read(l)
        fwd = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        auth = self.headers.get("Authorization")   # reenviar el token de sesión (anti-IDOR)
        if auth:
            fwd["Authorization"] = auth
        acc = self.headers.get("Accept")            # SSE: dejar pasar el Accept
        if acc:
            fwd["Accept"] = acc
        # La frontera de sesión local valida estos valores en el backend. No dejar que
        # urllib los sustituya silenciosamente por el destino del proxy.
        fwd["Host"] = host
        if origin:
            fwd["Origin"] = origin
        launch = self.headers.get("X-Aleph-Launch")
        if launch:
            fwd["X-Aleph-Launch"] = launch
        try:
            req = urllib.request.Request(
                BACK + self.path, data=body, headers=fwd, method=m)
            r = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return True
        except Exception as e:
            self.send_response(503); self.end_headers(); self.wfile.write(str(e).encode()); return True
        ct = r.getheader("Content-Type", "application/json"); st = r.status
        # STREAMING passthrough (SSE): NO bufferear — escribir cada línea apenas llega del
        # backend (token-por-token). Un proxy que bufferea mata el "se arma en vivo".
        if "text/event-stream" in ct:
            # SIN Content-Length, el fin del cuerpo se señala cerrando la conexión. El
            # browser manda Connection: keep-alive → hay que forzar el cierre o el fetch
            # nunca recibe `done` (la obra queda "armando" para siempre).
            self.close_connection = True
            self.send_response(st); self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "no-cache"); self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for line in r:
                    self.wfile.write(line); self.wfile.flush()
            except Exception:
                pass
            finally:
                r.close()
            return True
        # respuesta normal: bufferear + Content-Length
        data = r.read(); r.close()
        self.send_response(st); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        return True

    def _guia(self, p):
        """[T6 §10] docs/guia servido desde la RAÍZ del repo (vive fuera de design/).
        Es la fuente única de la explicación larga: el Guía la inyecta como contexto y el
        [?] del Cuarto la lee por HTTP. En prod lo monta main.py; acá, el dev server."""
        if not p.startswith("/docs/guia/"):
            return False
        name = os.path.basename(p)                      # sin subdirs: la carpeta es plana
        f = os.path.join(GUIA, name)
        if not name.endswith(".md") or not os.path.isfile(f):
            self.send_error(404); return True
        data = open(f, "rb").read()
        self.send_response(200); self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        return True

    def do_GET(self):
        if self._px("GET"): return
        parsed = urllib.parse.urlparse(self.path)
        p, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        if self._guia(p): return
        # CUTOVER: el Cuarto CANÓNICO es el de INSPECCIÓN DINÁMICA (Pixi, cuarto.pixi.html):
        # apuntás a un software → se inspecciona → la capability NACE en la escena (build=use).
        # El builder/diorama viejo (cuarto.html) queda SOLO con ?builder=legacy (escape reversible).
        # /Cuarto.dc.html y /cuarto/cuarto.html caen en el Pixi sin editar cada pantalla; se
        # preserva el resto del query (p.ej. ?recon=<space> / ?puppet=<id>).
        if p in ("/Cuarto.dc.html", "/cuarto/cuarto.html") and "legacy" not in qs.get("builder", []):
            qs.pop("builder", None)
            newq = urllib.parse.urlencode({k: v[0] for k, v in qs.items()})
            loc = "/cuarto/cuarto.pixi.html" + (("?" + newq) if newq else "")
            self.send_response(302); self.send_header("Location", loc); self.end_headers()
            return
        if p in ("/", "/index.html"):      # la homepage = el hub (Home, con su launcher nav.js)
            self.path = "/Home.dc.html"
        super().do_GET()

    def do_POST(self):
        if self._px("POST"): return
        self.send_error(404)

    def do_DELETE(self):
        if self._px("DELETE"): return
        self.send_error(404)

    def do_PUT(self):
        if self._px("PUT"): return
        self.send_error(404)

    def do_PATCH(self):
        # el panel de memoria (o6) reclasifica/edita vía PATCH /v1/puppets/{id}/memories/{mid};
        # sin este método el dev-server devolvía 501 (BaseHTTPRequestHandler default) y el botón
        # ⇄ / editar fallaban en la UI aunque el backend responde 200. Espejo de do_PUT.
        if self._px("PATCH"): return
        self.send_error(404)

    def log_message(self, *a):
        pass


class ThreadingHTTP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True            # un SSE largo no bloquea otras requests
    allow_reuse_address = True


if __name__ == "__main__":
    # ⛔ BIND A LOOPBACK, NO A TODAS LAS INTERFACES.
    # Estaba `("", PORT)`, que es 0.0.0.0: cualquiera en la misma wifi llegaba a este
    # servidor. Y no es sólo el front — esto PROXEA /v1 al backend del usuario, o sea el
    # vault, las credenciales BYOK y la sesión, sin auth y sin CORS de por medio. Encima
    # no hay ningún index.html en design/, así que SimpleHTTPRequestHandler genera
    # listado de directorio y el árbol queda navegable.
    #
    # Aleph corre en la máquina del usuario: nadie más tiene por qué alcanzarlo. Quien
    # de verdad quiera exponerlo (probar desde el teléfono, una demo en la LAN) lo pide
    # EXPLÍCITO con ALEPH_BIND; el default no puede ser "abierto a la red".
    BIND = os.environ.get("ALEPH_BIND", "127.0.0.1").strip() or "127.0.0.1"
    if BIND not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠️  ALEPH_BIND={BIND} — este servidor queda alcanzable desde la red, "
              f"y proxea /v1 a tu backend (vault, credenciales, sesión). Sólo en una red "
              f"en la que confíes.")
    print(f"ALEPH dev server → http://localhost:{PORT}/  (Home/hub · proxy /v1 → {BACK})")
    with ThreadingHTTP((BIND, PORT), H) as s:
        s.serve_forever()
