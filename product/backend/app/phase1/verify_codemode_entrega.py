#!/usr/bin/env python3
"""verify_codemode_entrega.py — los dos defectos que impedían que code execution ENTREGARA.

Los dos se diagnosticaron CAPTURANDO EL SCRIPT (`ALEPH_CODEMODE_DIAG`), no deduciéndolos
por los efectos, y son de familias distintas:

  A · EL STUB MATABA LOS POSICIONALES. `def f(**kw)` + una superficie que muestra
      `glob(pattern: string)` = invitación a un TypeError en la primera línea. Medido en
      Legal: tres líneas muertas, `ok=False`, CERO tools corridas.
  B · LA SUPERFICIE NO DECÍA QUE HAY UN SOLO TIRO. El modelo escribía un script de
      reconocimiento —`science_list_dbs()` y print— y paraba a mirar, que es lo correcto
      en un loop de tools. No hay vuelta siguiente, y nadie se lo había dicho.

Con `--caer` se muta el stub (vuelve a `**kw` puro) y las varas de A tienen que ponerse
rojas. Los esperados están escritos A MANO.
"""
from __future__ import annotations

import os
import sys

# ⚠️ EL BOOTSTRAP CONTABA `dirname` DE MENOS y la vara sólo corría desde
# `platform/assembler`. `__file__` está en `product/backend/app/phase1/`: hacen falta
# CINCO para llegar a la raíz del repo (phase1 → app → backend → product → repo), y
# había tres. Con tres, `RAIZ` salía `product/backend` y `RAIZ/../platform/assembler`
# apuntaba a `product/platform/assembler`, que no existe — `ModuleNotFoundError:
# code_execution` desde cualquier cwd que no fuera `platform/assembler`.
# Y hacen falta LAS DOS ramas: `code_execution` vive en `platform/assembler` y
# `app.phase1.codemode_borde` en `product/backend`.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
RAIZ = os.path.join(_REPO, "product", "backend")
sys.path.insert(0, os.path.join(_REPO, "platform", "assembler"))
sys.path.insert(0, RAIZ)

CAER = "--caer" in sys.argv
_OK = _MAL = 0


def ok(cond, etiqueta, detalle=""):
    global _OK, _MAL
    if cond:
        _OK += 1
        print(f"  🟢 {etiqueta}")
    else:
        _MAL += 1
        print(f"  🔴 {etiqueta}" + (f"  ← {detalle}" if detalle else ""))


import code_execution as CE  # noqa: E402

TOOLS = [{"type": "function", "function": {
    "name": "glob", "description": "busca archivos",
    "parameters": {"type": "object",
                   "properties": {"pattern": {"type": "string"},
                                  "limit": {"type": "number"}},
                   "required": ["pattern"]}}}]

src = CE.prelude(TOOLS, 1234, "tok", 30)
if CAER:
    # ⚠️ EL MUTANTE SE REESCRIBIÓ CON EL MERGE, Y TENÍA QUE HACERLO. Mutaba el stub de
    # `b8c3fff2` (`_o = [...]` + el `for enumerate` + `kw.setdefault`), que la
    # integración reemplazó por el de Diseño —`_aleph_args`, que además caza el argumento
    # repetido—. Contra el stub que quedó, ninguno de esos `replace` matcheaba: `--caer`
    # no mutaba NADA y la vara salía verde con el mutante puesto. Un mutante que no muta
    # es una vara que no mide.
    _viejo = ('def glob(*a, **kw):\n'
              '    return _aleph_llamar(\'glob\', '
              '**_aleph_args(\'glob\', (\'pattern\', \'limit\'), a, kw))\n')
    assert _viejo in src, "el mutante ya no reconoce el stub — revisar `prelude`"
    src = src.replace(_viejo, 'def glob(**kw):\n    return _aleph_llamar(\'glob\', **kw)\n')
    print("  ⚠️  MUTANTE: el stub vuelve a `**kw` puro")

# ⚠️ UN SOLO DICT, COMO EN PRODUCCIÓN. Con `exec(src, globals, locals)` las funciones
# que nacen adentro se llevan `globals` como su `__globals__`, así que `glob()` no veía
# `_aleph_args` —que el preludio define, pero en `locals`—. En producción el script corre
# como MÓDULO en un subproceso (`pysandbox_server._run_python`), o sea un espacio de
# nombres único. Medir con dos era medir un escenario que no existe.
ns = {}
exec(src, ns)
# ⚠️ Y EL TRANSPORTE SE PISA DESPUÉS, no con un `replace` sobre el texto. Renombrar
# `_aleph_llamar` → `_fake` en el fuente renombraba TAMBIÉN su `def`, así que el preludio
# real volvía a tapar al doble y los stubs terminaban pegándole al puente de verdad
# (`AlephToolError: Unexpected endpoint`). Los stubs resuelven el nombre en el momento de
# la llamada, así que reemplazarlo en el namespace YA ejecutado alcanza — y deja el
# preludio corriendo tal cual sale de `prelude()`, que es lo que la vara viene a medir.
ns["_aleph_llamar"] = lambda n, **kw: (n, kw)
glob = ns["glob"]

print("── A · el stub acepta como el modelo escribe ──")
try:
    r = glob("**/MSA-ACME.txt")
    ok(r == ("glob", {"pattern": "**/MSA-ACME.txt"}),
       "A1 · POSICIONAL, que es como lo escribió Legal y como lo invita la firma", str(r))
except TypeError as e:
    ok(False, "A1 · POSICIONAL", f"{e}")
ok(glob(pattern="x") == ("glob", {"pattern": "x"}), "A2 · con nombre sigue andando")
try:
    r = glob("x", limit=5)
    ok(r[1] == {"limit": 5, "pattern": "x"}, "A3 · mixto", str(r))
except TypeError as e:
    ok(False, "A3 · mixto", str(e))
try:
    glob("a", "b", "c")
    ok(False, "A4 · de más ⇒ error con NOMBRES, no un TypeError pelado")
except Exception as e:
    # ⚠️ EL TIPO DE LA EXCEPCIÓN CAMBIÓ CON LA INTEGRACIÓN, y la aserción tenía que
    # seguirlo: el stub que quedó levanta `AlephToolError` (con el nombre de la función
    # adentro) donde el anterior levantaba `TypeError`. Se cachan las DOS a propósito —
    # lo que A4 protege no es la clase, es que el error DIGA los nombres en vez de ser un
    # `takes 0 positional arguments` que no explica nada. Cachar sólo `TypeError` dejaba
    # escapar la nueva y mataba la vara entera en vez de medirla.
    ok("pattern" in str(e) and "glob" in str(e),
       f"A4 · de más ⇒ error útil: {e}", str(e))

print("── B · la superficie dice que hay UN SOLO TIRO ──")
from app.phase1 import codemode_borde as CB  # noqa: E402
msgs = CB._con_superficie([{"role": "system", "content": "sos un agente"}], TOOLS)
sup = msgs[0]["content"]
ok("UN SOLO TIRO" in sup, "B1 · la regla está en el system")
# ⚠️ la primera afirmación la escribí mal: buscaba «no vas a ver su salida» en
# minúscula y el texto dice «NO vas a ver». Comparar sin distinguir mayúsculas es lo
# correcto acá: lo que se prueba es que la ADVERTENCIA esté, no su tipografía.
for frase, que in (("no vas a ver su salida", "avisa que no verá el resultado"),
                   ("adentro del script", "manda encadenar adentro"),
                   ("las dos ramas", "manda programar las ramas en vez de mirar")):
    ok(frase in sup.lower(), f"B2 · {que}")
ok(len(CB._UN_SOLO_TIRO) < 900,
   f"B3 · y cuesta poco: {len(CB._UN_SOLO_TIRO)} chars (~{len(CB._UN_SOLO_TIRO)//4} tok)")

print("── C · sin superficie no se inventa nada ──")
vacio = CB._con_superficie([{"role": "system", "content": "x"}], [])
ok("UN SOLO TIRO" in vacio[0]["content"],
   "C1 · la regla va igual aunque no haya tools (el bloque lo decide el llamante)")

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
