"""Unit del armed_executor (TICKET 36) — guards puros, sin red.
El disparo real se verifica LIVE (approve → PO real en InvenTree, doble llave del examen).
Correr: cd platform && python3 inspection/loop/test_armed_executor.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from inspection.loop.armed_executor import fire_armed_request

_fail = []
def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c: _fail.append(label)

print("== armed_executor · guards (no toca red si el armed es inválido) ==")
r = fire_armed_request({"method": "GET", "url": "http://x/y"}, {})
ok(not r["ok"] and "sólo dispara writes" in (r.get("error") or ""),
   "un GET NO se dispara acá (los reads no pasan por el ejecutor de writes)")

r = fire_armed_request({"method": "POST", "url": ""}, {})
ok(not r["ok"] and "sin url" in (r.get("error") or ""), "POST sin url → rechazo, no dispara")

r = fire_armed_request({"method": "DELETE"}, {})
ok(not r["ok"], "DELETE sin url → rechazo (fail-safe)")

# método no-mutante raro → tampoco (solo POST/PUT/PATCH/DELETE)
r = fire_armed_request({"method": "OPTIONS", "url": "http://x"}, {})
ok(not r["ok"] and "sólo dispara writes" in (r.get("error") or ""), "OPTIONS no es write → no dispara")

print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
sys.exit(1 if _fail else 0)
