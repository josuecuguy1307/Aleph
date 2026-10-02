#!/usr/bin/env python3
"""verify_env_declarado.py — LA GUARDA DE §9.2, ANTES de tocar la huella.

La decisión sellada es: **la huella se calcula sobre el env DECLARADO en la receta, no
sobre el env completo del proceso.** Eso arregla el §6 (el calentador y el run dejarían de
partirse por `PUPPET_WORKDIR`) pero abre un riesgo NUEVO y peor:

    si un server LEE una variable que su receta NO declara, dos conexiones que difieren
    SÓLO en esa variable pasan a tener la MISMA huella — y comparten proceso.

Compartir de más ES la fuga (§2.1 del diseño: la BYOK cross-user). Por eso esta vara corre
ANTES: si encuentra un lector-sin-declarar, la huella NO se relaja. **Se arregla declarando
la variable en la receta**, que además es lo correcto por sí mismo: una receta que no dice
de qué depende su server es una receta incompleta.

Lo que mide, con el catálogo REAL:
  1. quién declara `${PUPPET_WORKDIR}`;
  2. quién LEE `os.environ[...]` de algo que su receta no declara — cualquier variable, no
     sólo el workdir, porque la regla nueva vale para todas.

    product/backend/.venv/bin/python platform/inspection/verify_env_declarado.py

⚠️ POR QUÉ ESTO LEE AST Y NO UN REGEX. La primera versión buscaba el nombre entre comillas
pegado a `environ.get(`. Eso NO ve la forma indirecta:

    for var in ("GMAIL_TOKEN", "GMAIL_ACCESS_TOKEN", "GMAIL_API_KEY"):
        val = (os.environ.get(var) or "").strip()

…que es exactamente como leen `gmail_draft_server.py:95` y `drive_server.py:100`. La vara
daba VERDE sobre ellos y escondía CINCO variables, las cinco credenciales, y de ésas el
broker inyecta cuatro de verdad (`_PROVIDER_ENV_ALIASES` + el canónico). O sea: el punto
ciego tapaba justo la clase que esta vara existe para cazar. Una vara que se puede poner
verde sin ver lo que busca es peor que no tenerla, porque habilita relajar la huella.

Con AST se resuelve el caso literal y el caso «Name que viene de un for sobre una tupla de
literales», y **lo que no se puede resolver se REPORTA y BLOQUEA** — nunca pasa mudo.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

from app.phase1 import conexiones_verificador as V   # noqa: E402
from app.phase1 import motor_verdad as MV            # noqa: E402

#: Forma de un nombre de variable de entorno. La prosa no entra: el AST sólo ve código, así
#: que los servers que EXPLICAN `${PUPPET_WORKDIR}` en su docstring sin leerlo nunca no
#: cuentan — que era el motivo original de no hacer esto con un `grep` a secas.
_NOMBRE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


class _Lecturas(ast.NodeVisitor):
    """Las env-vars que un archivo LEE. Resuelve dos formas y confiesa la tercera.

      · directa    `os.environ.get("X")` · `os.environ["X"]` · `os.getenv("X")`
      · indirecta  `for v in ("A","B"): os.environ.get(v)` — el Name se resuelve contra los
                   `for` que lo ligan a una tupla/lista de literales
      · opaca      cualquier otra cosa (un Name que viene de un argumento, un f-string, un
                   valor calculado). No se adivina: va a `opacas` y BLOQUEA. El modo de
                   fallo tiene que ser «no sé, entonces no relajes», nunca «no vi nada».
    """

    def __init__(self):
        self.vars: set[str] = set()
        self.opacas: list[str] = []
        self._ligados: dict[str, set[str]] = {}    # nombre de loop var → literales posibles

    # ── un `for v in ("A","B")` liga v a esos literales ──────────────────────────────
    def visit_For(self, node: ast.For):
        if isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
            lits = {e.value for e in node.iter.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if lits and len(lits) == len(node.iter.elts):
                self._ligados.setdefault(node.target.id, set()).update(lits)
        self.generic_visit(node)

    def _resolver(self, arg, donde: str):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if _NOMBRE.match(arg.value):
                self.vars.add(arg.value)
            return
        if isinstance(arg, ast.Name) and arg.id in self._ligados:
            self.vars.update(v for v in self._ligados[arg.id] if _NOMBRE.match(v))
            return
        self.opacas.append(f"{donde}:{getattr(arg, 'lineno', '?')}")

    def visit_Call(self, node: ast.Call):
        f = node.func
        es_environ_get = (isinstance(f, ast.Attribute) and f.attr == "get"
                          and isinstance(f.value, ast.Attribute) and f.value.attr == "environ")
        es_getenv = (isinstance(f, ast.Attribute) and f.attr == "getenv") or \
                    (isinstance(f, ast.Name) and f.id == "getenv")
        if (es_environ_get or es_getenv) and node.args:
            self._resolver(node.args[0], "environ.get" if es_environ_get else "getenv")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        v = node.value
        if isinstance(v, ast.Attribute) and v.attr == "environ":
            self._resolver(node.slice, "environ[]")
        self.generic_visit(node)

#: Ruido del intérprete y del SO. No entran en la huella hoy y no cambian de valor entre dos
#: conexiones del mismo usuario, así que no pueden producir un falso compartido.
_IGNORAR = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PWD", "SHELL",
            "USER", "LOGNAME", "TERM", "PYTHONPATH", "PYTHONUNBUFFERED", "DISPLAY"}

_fallos = 0
_bloqueos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def bloqueo(t):
    global _bloqueos
    _bloqueos += 1
    print(f"  ⛔ {t}")


def _lectores() -> dict:
    """`{nombre_de_archivo: (ruta, {VARS que lee}, [lecturas opacas])}` sobre NUESTROS
    servers. Un archivo que no parsea NO se saltea en silencio: entra con una opaca, porque
    «no lo pude leer» y «no lee nada» no son lo mismo."""
    fuera = {}
    for f in _RAIZ.rglob("*.py"):
        s = str(f)
        if any(x in s for x in (".venv", "node_modules", "/tests/", "test_")):
            continue
        if "/belts/" not in s and "/connectors/" not in s:
            continue
        rel = str(f.relative_to(_RAIZ))
        try:
            arbol = ast.parse(f.read_text(errors="replace"))
        except (OSError, SyntaxError) as e:                 # noqa: PERF203
            fuera[f.name] = (rel, set(), [f"no parsea: {type(e).__name__}"])
            continue
        vis = _Lecturas()
        vis.visit(arbol)
        v = vis.vars - _IGNORAR
        if v or vis.opacas:
            fuera[f.name] = (rel, v, vis.opacas)
    return fuera


def _declaradas(spec: dict) -> set:
    blob = json.dumps({k: spec.get(k) for k in ("command", "args", "env", "cwd")},
                      ensure_ascii=False)
    return (set(re.findall(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?", blob))
            | set((spec.get("env") or {}).keys()))


def main() -> int:
    lectores = _lectores()
    print(f"GUARDA DE §9.2 · {len(lectores)} archivo(s) de server nuestro leen alguna variable\n")

    entidades, sin_declarar, declaran_wd, opacas = [], [], [], []
    for belt, server in V._entradas():
        try:
            spec = MV._spec_de_belt(belt, server)
        except Exception:                                   # noqa: BLE001
            spec = None
        if not spec:
            continue
        entidades.append(server)
        decl = _declaradas(spec)
        if "PUPPET_WORKDIR" in decl:
            declaran_wd.append(server)
        for a in (spec.get("args") or []):
            for nombre, (ruta, vars_, sin_resolver) in lectores.items():
                if nombre in str(a):
                    faltan = sorted(vars_ - decl)
                    if faltan:
                        sin_declarar.append((server, ruta, faltan))
                    if sin_resolver:
                        opacas.append((server, ruta, sin_resolver))

    print(f"── 1 · ¿quién declara ${{PUPPET_WORKDIR}}? ──")
    print(f"   {len(declaran_wd)} de {len(entidades)} entidades del catálogo: "
          f"{', '.join(sorted(declaran_wd))}")
    ok(len(declaran_wd) > 0, "hay entidades que lo declaran (la variable se usa de verdad)")

    print(f"\n── 2 · ¿alguna LEE algo que su receta NO declara? ──")
    if not sin_declarar:
        ok(True, "NINGUNA: la huella se puede calcular sobre el env declarado")
    else:
        print(f"   {'entidad':<16} variables leídas y NO declaradas")
        for s, _r, faltan in sorted(sin_declarar):
            print(f"   {s:<16} {', '.join(faltan)}")
        credenciales = sorted({v for _s, _r, fs in sin_declarar for v in fs
                               if re.search(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)$", v)})
        bloqueo(f"{len(sin_declarar)} entidad(es) leen variables que su receta no declara. "
                f"LA HUELLA NO SE RELAJA.")
        print(f"   · Con la huella sobre el env declarado, dos conexiones que difieran SÓLO")
        print(f"     en una de esas variables compartirían proceso. Compartir de más ES la")
        print(f"     fuga (§2.1), y el arreglo es DECLARARLAS en la receta, no aflojar la regla.")
        if credenciales:
            print(f"   · ⚠️ y {len(credenciales)} de ellas son CREDENCIALES: "
                  f"{', '.join(credenciales)}")
            print(f"     Una receta que no declara la llave de la que depende su server ya es")
            print(f"     un bug hoy, antes de cualquier cambio de huella.")

    print(f"\n── 3 · ¿alguna lectura que no se pueda resolver leyendo el código? ──")
    if not opacas:
        ok(True, "NINGUNA: toda lectura de env de nuestros servers es resoluble")
    else:
        for s, r, sitios in sorted(opacas):
            print(f"   {s:<16} {r} → {', '.join(sitios)}")
        bloqueo(f"{len(opacas)} lectura(s) opaca(s): no se puede DEMOSTRAR qué variables "
                f"lee ese server.")
        print(f"   · Sin saber qué lee, no se puede saber qué falta declarar. El modo de")
        print(f"     fallo de esta vara es «no sé ⇒ no relajes», nunca «no vi nada».")

    if _bloqueos:
        # Y el TEXTO también dice rojo. Antes imprimía «TODO VERDE · 1 BLOQUEO(S)»: una
        # línea que se contradice a sí misma es una que alguien va a leer por la mitad.
        print(f"\nBLOQUEADA · {_bloqueos} BLOQUEO(S) — la huella NO se toca"
              + (f" · {_fallos} FALLO(S)" if _fallos else ""))
    else:
        print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
    # ⚠️ UN BLOQUEO TIENE QUE PONER LA VARA EN ROJO. La primera versión devolvía
    # `0 if _fallos == 0 else 1` y los bloqueos NO contaban: imprimía «TODO VERDE · 1
    # BLOQUEO(S)» y salía 0. Una vara-compuerta que no puede decir rojo por código de salida
    # no es una compuerta — cualquier runner la habría leído como aprobada mientras negaba
    # por escrito el permiso que se le estaba pidiendo.
    return 0 if (_fallos == 0 and _bloqueos == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
