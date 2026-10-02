#!/usr/bin/env python3
"""verify_legal_permisos.py — la lista que Aleph contesta, atada a la config que Aleph escribe.

QUÉ PROTEGE. `dochaus.js` contesta automáticamente los pedidos de permiso del motor de
Legal, porque adentro de Aleph un `"ask"` no es una pregunta: es un `Deferred.await` sin
timeout y la tool queda colgada hasta que el watchdog mata el turno. Esa lista de
auto-aprobación es una decisión de seguridad, y una decisión de seguridad escrita en un
archivo y verificada en ninguno es una decisión que dura hasta el próximo que edite el otro
archivo.

LAS DOS FUENTES QUE TIENEN QUE SEGUIR DE ACUERDO:
  · `platform/workspaces/plugins/dochaus.js`  → `PERMISOS_DE_OBRA`, lo que se aprueba;
  · `third_party/dochaus/script/aleph-legal-config.ts` → el ruleset que ALEPH le escribe
    al motor, donde cada permiso dice `allow` · `ask` · `deny`.

LO QUE MIDE, y cada uno tiene su modo de fallo real:
  1. Todo lo que se aprueba está declarado `ask` allá. Si alguien lo pasara a `deny`, el
     motor cortaría antes de preguntar y esta lista estaría mintiendo sobre lo que hace.
  2. NADA destructivo entra. Un `delete-*` auto-aprobado borraría biblioteca del dueño sin
     que nadie lo viera: es exactamente el daño que la pantalla ausente no puede frenar.
  3. `edit`, `bash` y `websearch` siguen en `deny` allá. Son el suelo sobre el que se apoya
     el argumento de que aprobar las cinco de obra es acotado.
  4. Cada tool que produce artefacto tiene su permiso aprobado — si no, el artefacto no
     nace y volvemos al defecto que esta obra vino a cerrar.

Correr:  python3 platform/workspaces/verify_legal_permisos.py
"""
from __future__ import annotations

import os
import re
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PLUGIN = os.path.join(_RAIZ, "platform", "workspaces", "plugins", "dochaus.js")
_CONFIG = os.path.join(_RAIZ, "third_party", "dochaus", "script", "aleph-legal-config.ts")

_fallos = []


def ok(cond, etiqueta):
    print(f"  {'✓' if cond else '✗'} {etiqueta}")
    if not cond:
        _fallos.append(etiqueta)


def _bloque(texto: str, arranque: str) -> str:
    """El literal que sigue a `arranque`, hasta su cierre. Sin evaluar nada.

    ⚠️ EL CIERRE ES EL DE COLUMNA CERO, no la primera llave que aparezca — y esto lo
    destapó esta misma vara naciendo roja: `TOOLS_DE_OBRA` tiene un objeto por fila, así
    que cortar en el primer `}` leía UNA tool de cinco y la vara acusaba al plugin de algo
    que era suyo. Un parser flojo produce una roja falsa, que gasta el mismo crédito que
    una verde falsa.
    """
    i = texto.index(arranque)
    cierre = "\n])" if arranque.rstrip().endswith("([") else "\n}"
    j = texto.index(cierre, i)
    return texto[i:j]


plugin = open(_PLUGIN, encoding="utf-8").read()
config = open(_CONFIG, encoding="utf-8").read()

# ── LO QUE EL PLUGIN APRUEBA ────────────────────────────────────────────────────────
aprobados = set(re.findall(r'"([a-z0-9-]+)"', _bloque(plugin, "const PERMISOS_DE_OBRA = new Set([")))
produce = set(re.findall(r'^\s*"([a-z0-9-]+)":\s*\{\s*kind:', _bloque(plugin, "const TOOLS_DE_OBRA = {"),
                         re.MULTILINE))

# ── EL RULESET QUE ALEPH LE ESCRIBE AL MOTOR ────────────────────────────────────────
#: `"nombre": "accion"` y `nombre: "accion"` — el archivo usa las dos formas.
ruleset = dict(re.findall(r'"?([a-zA-Z0-9-]+)"?\s*:\s*"(allow|ask|deny)"', config))

print("\n── las dos fuentes se leyeron ───────────────────────────────────────────────")
ok(len(aprobados) == 5, f"el plugin aprueba 5 permisos (leídos: {len(aprobados)} → {sorted(aprobados)})")
ok(len(produce) == 5, f"y declara 5 tools que producen obra (leídas: {len(produce)})")
ok(len(ruleset) > 30, f"el ruleset de Aleph tiene sus reglas (leídas: {len(ruleset)})")

print("\n── 1 · lo aprobado está declarado `ask`, no `deny` ──────────────────────────")
for p in sorted(aprobados):
    ok(ruleset.get(p) == "ask",
       f"`{p}` sigue siendo `ask` en aleph-legal-config.ts (es: {ruleset.get(p)!r})")

print("\n── 2 · nada destructivo ni de biblioteca entra en la lista ──────────────────")
prohibidos = sorted(n for n in ruleset if n.startswith(("delete-", "create-", "update-")))
ok(prohibidos, f"hay {len(prohibidos)} permisos de biblioteca en el ruleset (si no, no se midió nada)")
for p in prohibidos:
    ok(p not in aprobados, f"`{p}` NO se auto-aprueba (es biblioteca del dueño, no obra del turno)")

print("\n── 3 · el suelo sobre el que se apoya el argumento sigue en `deny` ──────────")
for p in ("edit", "bash", "websearch"):
    ok(ruleset.get(p) == "deny",
       f"`{p}` sigue en `deny`, así que ni llega a preguntar (es: {ruleset.get(p)!r})")

print("\n── 4 · cada tool que produce artefacto tiene su permiso aprobado ────────────")
for t in sorted(produce):
    ok(t in aprobados,
       f"`{t}` produce artefacto y su permiso se contesta (si no, el artefacto no nace)")

print("\n── el plugin no se quedó a medio cablear ────────────────────────────────────")
ok('"permission.asked"' in plugin or "permission.asked" in plugin,
   "escucha el evento `permission.asked` (el hook `permission.ask` NO lo dispara el motor)")
ok('"tool.execute.after"' in plugin, "cosecha por el borde de la herramienta")
ok('"reject"' in plugin, "y el rechazo existe: no todo se aprueba")
ok("/permission/" in plugin and "/session/" in plugin,
   "contesta por la ruta vigente y deja el respaldo de la deprecada")

print()
if _fallos:
    print(f"✗ {len(_fallos)} fallo(s):")
    for f in _fallos:
        print(f"   · {f}")
    raise SystemExit(1)
print("PASS los permisos que Legal auto-contesta son los de obra, y nada más")
