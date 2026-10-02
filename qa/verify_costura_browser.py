#!/usr/bin/env python3
"""verify_costura_browser.py — la costura de browser-use al borde de dialecto (§6.a).

MIDE EL DATO QUE CRUZA, CAMPO POR CAMPO — no que el archivo exista («el commit es
declaración, no estado»). Cada caso puede dar rojo: si alguien tira las cabeceras, si el
`base_url` deja de ser el borde, o si un pack incompleto pasa en silencio.
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platform"))
from browser import cerebro as C                                            # noqa: E402

_f = []
def ok(c, d, extra=""):
    print(("  ✓ " if c else "  ✗ ") + d + (f"   {extra}" if extra and not c else ""))
    if not c: _f.append(d)

BORDE = "http://127.0.0.1:8788/v1/workspaces/brain/openai"
PACK = {"provider": {"aleph": {"options": {
    "baseURL": BORDE + "/",                       # con barra: se normaliza
    "apiKey": "sess-abc",
    "headers": {"X-Aleph-Workspace": "sala", "X-Aleph-User": "u1", "X-Aleph-Puppet": "p1"}}}}}

d = tempfile.mkdtemp(prefix="costura-browser-")
p = os.path.join(d, "pack.json"); open(p, "w").write(json.dumps(PACK))

print("COSTURA browser-use → borde de dialecto\n")
k = C.desde_pack(p, space_id="space-42")
ok(k["base_url"] == BORDE, "el base_url es EL BORDE y se le saca la barra final", k["base_url"])
ok(k["api_key"] == "sess-abc", "la sesión viaja como api_key", k["api_key"])
ok(k["model"] == C.MODELO_DECLARADO, "se declara un modelo no vacío (el borde lo ignora)", k["model"])

h = k["default_headers"] or {}
for cab in ("X-Aleph-Workspace", "X-Aleph-User", "X-Aleph-Puppet"):
    ok(h.get(cab) is not None, f"la cabecera {cab} NO se tira", str(h))
ok(h.get("X-Aleph-Space") == "space-42",
   "X-Aleph-Space viaja — sin él S8 queda ciego a todo lo que este modo produce", str(h))

# sin space_id NO se inventa uno
k2 = C.desde_pack(p)
ok("X-Aleph-Space" not in (k2["default_headers"] or {}),
   "sin space_id no se fabrica un espacio (jamás se inventa dato)")

# sin sesión: clave coherente, no vacío
k3 = C.armar({"base_url": BORDE, "api_key": "", "headers": {}})
ok(k3["api_key"] == C.API_KEY_SIN_SESION, "sin sesión, una clave coherente y no un vacío")

# fail-closed tipado
for cuerpo, causa, desc in (
    ({}, "cerebro_config_incompleta", "pack sin provider → causa tipada"),
    ({"provider": {"aleph": {"options": {"baseURL": ""}}}}, "cerebro_config_incompleta",
     "baseURL vacío → causa tipada")):
    q = os.path.join(d, "malo.json"); open(q, "w").write(json.dumps(cuerpo))
    try:
        C.desde_pack(q); ok(False, desc, "no levantó")
    except C.CosturaError as e:
        ok(e.causa == causa, desc, e.causa)
try:
    C.desde_pack(os.path.join(d, "no-existe.json")); ok(False, "pack ausente → causa tipada", "no levantó")
except C.CosturaError as e:
    ok(e.causa == "cerebro_sin_config", "pack ausente → causa tipada", e.causa)

# la prueba de que la vara puede caer: una costura que tira las cabeceras
print("\nPRUEBA DE CAÍDA — una costura que tira las cabeceras")
malo = dict(C.armar({"base_url": BORDE, "api_key": "x", "headers": {"X-Aleph-User": "u"}},
                    space_id="s")); malo["default_headers"] = None
rojo = (malo["default_headers"] or {}).get("X-Aleph-Space") != "s"
print(("  ✓ " if rojo else "  ✗ ") + "el caso de X-Aleph-Space da ROJO si se tiran las cabeceras")
if not rojo: _f.append("LA VARA NO MIDE: tirar las cabeceras no da rojo")

print("\n" + ("PASS" if not _f else "FAIL: " + " · ".join(_f)))
sys.exit(1 if _f else 0)
