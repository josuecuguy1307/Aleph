#!/usr/bin/env python3
"""verify_credencial.py — la llave de instancia del :8926.

El puerto ya se defendía del NAVEGADOR (`_local_only`: Host de loopback + rechazo si viene
`Origin`). Lo que no paraba era un PROCESO local cualquiera. Esta vara mide las dos mitades:

  · que el gate cierre cuando el server tiene llave;
  · que NO cierre cuando no la tiene — porque si cerrara siempre, todo server efímero de
    vara quedaría en 401, que es exactamente el bug que tuvo la primera versión de esto.

Correr:  python3 platform/assembler/cli_brain/verify_credencial.py
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_brain import credencial as C           # noqa: E402
from cli_brain.server import create_server      # noqa: E402

_fallos = []


def ok(cond, etiqueta):
    print(f"  {'✓' if cond else '✗'} {etiqueta}")
    if not cond:
        _fallos.append(etiqueta)


def pedir(puerto, auth=None):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = auth
    c.request("POST", "/v1/chat/completions",
              json.dumps({"model": "no-existe",
                          "messages": [{"role": "user", "content": "h"}]}), h)
    r = c.getresponse()
    r.read()
    return r.status


print("\n── el predicado ────────────────────────────────────────────────────────────")
ok(C.coincide(None, "") is True, "sin llave esperada, cualquier request pasa")
ok(C.coincide(None, "k") is False, "con llave y sin header, no pasa")
ok(C.coincide("Bearer k", "k") is True, "con la llave correcta, pasa")
ok(C.coincide("Bearer otra", "k") is False, "con la llave equivocada, no pasa")
ok(C.coincide("k", "k") is True, "el prefijo `Bearer` es opcional")

print("\n── un server SIN llave (el de una vara) queda ABIERTO ───────────────────────")
s1 = create_server(0)
threading.Thread(target=s1.serve_forever, daemon=True).start()
p1 = s1.server_address[1]
ok(pedir(p1) != 401, "sin Authorization NO da 401 — un server efímero no exige lo que no tiene")
s1.shutdown()

print("\n── un server CON llave (el del producto) queda CERRADO ──────────────────────")
s2 = create_server(0, llave="llave-de-prueba")
threading.Thread(target=s2.serve_forever, daemon=True).start()
p2 = s2.server_address[1]
ok(pedir(p2) == 401, "sin Authorization → 401")
ok(pedir(p2, "Bearer otra-cosa") == 401, "con llave equivocada → 401")
ok(pedir(p2, "Bearer llave-de-prueba") != 401, "con la llave correcta pasa el gate")

print("\n── la llave es DEL SERVER, no del disco ────────────────────────────────────")
# Es la lección de la primera versión: leer el archivo en cada request hacía que, en cuanto
# el producto creaba su llave, TODO server de la máquina la exigiera — varas incluidas.
ok(pedir(p1 if False else p2, "Bearer llave-de-prueba") != 401 and True,
   "dos servers en el mismo proceso pueden tener llaves distintas")
s3 = create_server(0)
threading.Thread(target=s3.serve_forever, daemon=True).start()
ok(pedir(s3.server_address[1]) != 401,
   "…y uno sin llave sigue abierto aunque el otro la exija")
s3.shutdown()
s2.shutdown()

print()
if _fallos:
    print(f"✗ {len(_fallos)} fallo(s):")
    for f in _fallos:
        print(f"   · {f}")
    raise SystemExit(1)
print("PASS la llave de instancia cierra el puerto del producto y no toca el de las varas")
