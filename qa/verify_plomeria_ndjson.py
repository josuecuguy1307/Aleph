#!/usr/bin/env python3
"""verify_plomeria_ndjson.py — la plomería NDJSON extraída (§6.a · gatillo de 6.b).

MIDE LA UNIÓN: que la pieza extraída tenga las DOS mitades que las gemelas tenían por
separado — el cuerpo vacío y el UnicodeDecodeError de research, y el `copy` de búsqueda.
Cada caso puede dar rojo, y el caso 3 es el que destapa la regresión que motivó todo esto:
una causa llegando a una superficie SIN copy.
"""
import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platform"))
from ndjson_http import PlomeriaNDJSON, Cancelada                           # noqa: E402

_f = []
def ok(c, d, extra=""):
    print(("  ✓ " if c else "  ✗ ") + d + (f"   {extra}" if extra and not c else ""))
    if not c: _f.append(d)

class _Roto(io.BytesIO):
    def write(self, b): raise BrokenPipeError("cable cortado")

class H(PlomeriaNDJSON):
    """Handler falso: sólo lo que la plomería toca. Nada se siembra de más."""
    def __init__(self, cuerpo=b"", roto=False):
        self.headers = {"Content-Length": str(len(cuerpo))}
        self.rfile = io.BytesIO(cuerpo)
        self.wfile = _Roto() if roto else io.BytesIO()
        self.enviado = []
    def send_response(self, c): self.enviado.append(("status", c))
    def send_header(self, k, v): self.enviado.append(("hdr", k, v))
    def end_headers(self): pass
    def _leido(self):
        try: return json.loads(self.wfile.getvalue().decode("utf-8"))
        except Exception: return None

print("PLOMERÍA NDJSON EXTRAÍDA — la unión de las dos gemelas\n")

h = H(b""); ok(h._leer_json() == {}, "[1] cuerpo vacío → {} (la mitad de research)")

h = H(b'\xff\xfe no es utf-8'); r = h._leer_json(); c = h._leido() or {}
ok(r is None, "[2] bytes no-utf8 → 400 (la mitad de research)")
ok(c.get("copy"), "[3] …y CON copy — la regresión que motivó la extracción", json.dumps(c))
ok(c.get("detail"), "[4] …y con detail para quien depura", json.dumps(c))

h = H(b'[1,2]'); r = h._leer_json(); c = h._leido() or {}
ok(r is None and c.get("copy") and c.get("error") == "cuerpo_invalido",
   "[5] cuerpo que no es objeto → 400 con causa tipada y copy", json.dumps(c))

h = H(b'{"a":1}'); ok(h._leer_json() == {"a": 1}, "[6] cuerpo válido pasa tal cual")

h = H(roto=True)
try:
    h._linea({"x": 1}); ok(False, "[7] _linea con el cable roto levanta Cancelada", "no levantó")
except Cancelada: ok(True, "[7] _linea con el cable roto levanta Cancelada")
except BaseException as e: ok(False, "[7] _linea con el cable roto levanta Cancelada", type(e).__name__)

h = H(roto=True)
try:
    h._decir({"x": 1}); ok(True, "[8] _decir con el cable roto NO levanta (es el desenlace)")
except BaseException as e: ok(False, "[8] _decir con el cable roto NO levanta", type(e).__name__)

ok(issubclass(Cancelada, BaseException) and not issubclass(Cancelada, Exception),
   "[9] Cancelada NO es Exception — si no, ThreadingMixIn se la come y el motor sigue solo")

# ── prueba de caída: la pieza sin la mitad de búsqueda ────────────────────────────────
print("\nPRUEBA DE CAÍDA — la misma pieza sin el `copy` (la copia de research tal cual)")
class SinCopy(H):
    def _mal_cuerpo(self, detalle):                 # exactamente research/servidor.py:237
        self._json(400, {"error": "cuerpo_invalido", "detail": detalle})
h = SinCopy(b'\xff\xfe'); h._leer_json(); c = h._leido() or {}
rojo = not c.get("copy")
print(("  ✓ " if rojo else "  ✗ ") + "el caso [3] da ROJO contra la copia sin `copy`")
if not rojo: _f.append("LA VARA NO MIDE: la copia sin copy no da rojo")

print("\n" + ("PASS" if not _f else "FAIL: " + " · ".join(_f)))
sys.exit(1 if _f else 0)
