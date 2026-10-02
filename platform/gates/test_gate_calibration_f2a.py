#!/usr/bin/env python3
"""test_gate_calibration_f2a.py — CALIBRACIÓN EN ROJO del gate F2a (diferencial REAL).

Un test de gate que no puede fallar no mide nada. Por cada pieza que cambia de candado este
test prueba que en el commit **BASE** el predicado daba un valor y en **HEAD** da el OTRO.

**El lado BASE no se reconstruye: se CORRE.** Una reconstrucción a mano ("volvé a meter los
hints que sacamos") es una teoría sobre el pasado que puede mentir; acá se materializa el árbol
de `86574d4` con `git archive` y se ejecuta **su** `atoms_router._gate_for` sobre **su**
`recipe_enforcer` y **sus** cards. Cada lado corre en su PROPIO proceso: si compartieran uno,
`aleph_paths` quedaría cacheado en `sys.modules` y el BASE terminaría cargando el enforcer de
HEAD — el test daría verde midiendo dos veces lo mismo.

Cubre las 7 calibraciones + la barrida EXHAUSTIVA (ninguna otra card se movió) + que el
override declarado de `github` sea LOAD-BEARING (sin él, la regla `write` nueva lo gatearía).

Corre standalone (stdlib) o bajo pytest:  python3 platform/gates/test_gate_calibration_f2a.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# El commit BASE del que sale F2a: `_gate_for(tools)` money/send con "wire"/"transfer" desnudos.
_BASE_COMMIT = "86574d4"
# Lo mínimo que el probe necesita para importar atoms_router y leer el catálogo (~0.5 MB).
_BASE_PATHS = ["platform/aleph_paths.py", "platform/gates", "catalog/templates",
               "product/backend/app/phase1/atoms_router.py"]

# Runner: importa el atoms_router del árbol que le pasen y evalúa el gate de CADA card.
# Se adapta a la firma del commit (BASE toma sólo `tools`; HEAD toma `tools, card, auth`).
_RUNNER = r'''
import importlib.util, inspect as _i, json, sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "platform"))
_s = importlib.util.spec_from_file_location(
    "ar_probe", ROOT / "product" / "backend" / "app" / "phase1" / "atoms_router.py")
_ar = importlib.util.module_from_spec(_s)
_s.loader.exec_module(_ar)

cards = {}
for p in sorted((ROOT / "catalog" / "templates").rglob("*.mcp.json")):
    belt = json.loads(p.read_text(encoding="utf-8"))
    for c in (belt.get("_meta") or {}).get("cards") or []:
        cards.setdefault(c.get("id"), c)   # de-dup como collect_atoms: gana la primera

n = len(_i.signature(_ar._gate_for).parameters)
out = {}
for cid, c in cards.items():
    tools, auth = c.get("tools") or [], c.get("auth", "keyless")
    if n >= 3:                                   # HEAD: _gate_for(tools, card, auth)
        g = _ar._gate_for(tools, c, auth)
        naked = {k: v for k, v in c.items() if k != "gate"}
        gn = _ar._gate_for(tools, naked, auth)   # el mismo, SIN el override declarado
    else:                                        # BASE: _gate_for(tools)
        g = gn = _ar._gate_for(tools)
    out[cid] = {"gate": g, "gate_no_override": gn, "tools": tools, "auth": auth, "params": n}
print(json.dumps(out, ensure_ascii=False))
'''


def _probe(root: Path) -> dict:
    """Corre el runner contra un árbol, en su propio proceso. Falla RUIDOSO."""
    fd, runner = tempfile.mkstemp(suffix=".py", prefix="gate_probe_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_RUNNER)
    try:
        p = subprocess.run([sys.executable, runner, str(root)],
                           capture_output=True, text=True, timeout=180)
    finally:
        os.unlink(runner)
    if p.returncode != 0:
        raise RuntimeError(f"el probe del gate NO corrió sobre {root}:\n{p.stderr[-2000:]}")
    return json.loads(p.stdout)


def _base_probe() -> dict:
    """Materializa `86574d4` en un tmp y corre SU `_gate_for`. Falla RUIDOSO si no está."""
    ar = subprocess.run(["git", "-C", str(_REPO), "archive", _BASE_COMMIT, *_BASE_PATHS],
                        capture_output=True)
    if ar.returncode != 0:
        raise RuntimeError(
            f"no pude materializar el commit BASE {_BASE_COMMIT} desde {_REPO}. "
            f"Sin el BASE real este test no mide nada — NO se degrada a una reconstrucción.\n"
            f"{ar.stderr.decode('utf-8', 'replace')[-800:]}")
    tmp = Path(tempfile.mkdtemp(prefix=f"base_{_BASE_COMMIT}_"))
    try:
        tar = subprocess.run(["tar", "-x", "-C", str(tmp)], input=ar.stdout, capture_output=True)
        if tar.returncode != 0:
            raise RuntimeError(f"tar falló extrayendo el BASE: "
                               f"{tar.stderr.decode('utf-8', 'replace')[-800:]}")
        return _probe(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_CACHE = {}


def _sides() -> tuple:
    """(BASE, HEAD) — memoizado: pytest corre 4 tests, el árbol se extrae UNA vez."""
    if not _CACHE:
        _CACHE["base"], _CACHE["head"] = _base_probe(), _probe(_REPO)
        # Guardia anti-falso-verde: si los dos lados dieran la MISMA firma, uno de los dos
        # árboles no es el que creemos (p.ej. el BASE cargó el atoms_router de HEAD).
        pb = next(iter(_CACHE["base"].values()))["params"]
        ph = next(iter(_CACHE["head"].values()))["params"]
        assert (pb, ph) == (1, 3), (
            f"los dos lados no son distintos: _gate_for BASE toma {pb} params y HEAD {ph} "
            f"(esperado 1 y 3) — el diferencial estaría comparando el mismo código consigo mismo")
    return _CACHE["base"], _CACHE["head"]


# (id, gated en BASE 86574d4, gated en HEAD, nivel en HEAD) — las 7 que cambian de candado
CALIBRATIONS = [
    ("pysandbox",     False, True,  "exec"),
    ("script-runner", False, True,  "exec"),
    ("jupyter",       False, True,  "exec"),
    ("cad-script",    False, True,  "exec"),
    ("zotero",        False, True,  "write"),
    ("kicad-sch",     True,  False, None),
    ("cfd",           True,  False, None),
]

# no-regresión: se quedan como estaban (github read-only por override; workdir keyless sin gate)
NO_REGRESSION = ["github", "files", "sqlite", "excel", "datatools", "cad-headless",
                 "gmail-draft", "premium-report", "calc"]


def test_gate_calibrations_flip():
    """Las 7: BASE da un valor, HEAD da el otro, y son DISTINTOS."""
    base, head = _sides()
    for cid, before, after, level in CALIBRATIONS:
        assert cid in base and cid in head, f"{cid}: la card no existe en los dos lados"
        old, new = base[cid]["gate"], head[cid]["gate"]
        assert old["gated"] is before, f"{cid}: en {_BASE_COMMIT} esperaba gated={before}, dio {old}"
        assert new["gated"] is after,  f"{cid}: en HEAD esperaba gated={after}, dio {new}"
        assert old["gated"] != new["gated"], f"{cid}: el candado NO cambió — el test no mide nada"
        if after:
            assert new["level"] == level, f"{cid}: nivel {new['level']} != {level}"


def test_solo_las_7_cambian():
    """Barrida EXHAUSTIVA: ninguna card fuera de las 7 se movió de candado."""
    base, head = _sides()
    assert set(base) == set(head), f"el set de cards cambió: {set(base) ^ set(head)}"
    movidas = {cid for cid in base if base[cid]["gate"] != head[cid]["gate"]}
    esperadas = {c[0] for c in CALIBRATIONS}
    assert movidas == esperadas, (
        f"cambiaron cards que no debían: +{sorted(movidas - esperadas)} "
        f"−{sorted(esperadas - movidas)}")


def test_no_regression():
    """Los correctos siguen correctos: los writers keyless al workdir sin gate; send/money intactos."""
    _, head = _sides()
    for cid in ["github", "files", "sqlite", "excel", "datatools", "cad-headless", "calc"]:
        assert head[cid]["gate"]["gated"] is False, f"{cid}: REGRESIÓN — no debía gatear"
    assert head["gmail-draft"]["gate"]["level"] == "send"
    assert head["premium-report"]["gate"]["level"] == "money"


def test_override_de_github_es_load_bearing():
    """El override declarado NO es decorativo: sin él, la regla `write` nueva gatearía a github
    (`github_list_commits` matchea el hint "commit" y su auth es personal_token)."""
    _, head = _sides()
    g = head["github"]
    assert g["gate"]["gated"] is False, "github debía quedar read-only (override declarado)"
    assert g["gate_no_override"]["gated"] is True, (
        "sin override github NO se gatearía → el override no está haciendo nada y el test "
        "de no-regresión de github no mide nada")
    assert g["gate_no_override"]["level"] == "write"


if __name__ == "__main__":
    base, head = _sides()
    print(f"=== CALIBRACIÓN EN ROJO · F2a gate — BASE {_BASE_COMMIT} (corrido, no reconstruido) ===")
    print(f"{'pieza':16} {'BASE ' + _BASE_COMMIT:>22}  →  {'HEAD':<22} flip")
    ok = True
    for cid, before, after, level in CALIBRATIONS:
        old, new = base[cid]["gate"], head[cid]["gate"]
        flip = old["gated"] != new["gated"]
        good = (old["gated"] is before) and (new["gated"] is after) and flip
        ok = ok and good
        ob = f"gated={old['gated']}({old['level']})"
        nb = f"gated={new['gated']}({new['level']})"
        print(f"{cid:16} {ob:>22}  →  {nb:<22} {'✓' if flip else '✗ NO-FLIP'}"
              f"{'' if good else '  ← FALLA'}")

    print("\n=== barrida exhaustiva: TODA card que cambió de candado ===")
    for cid in sorted(base):
        if base[cid]["gate"] != head[cid]["gate"]:
            print(f"  {cid:16} {base[cid]['gate']} → {head[cid]['gate']}")

    print("\n=== ¿quién causa el flip: el cambio de hints o el override declarado? ===")
    for cid in sorted({c[0] for c in CALIBRATIONS} | {"github"}):
        h = head[cid]
        causa = "override declarado" if h["gate"] != h["gate_no_override"] else "cambio de hints/reglas"
        print(f"  {cid:16} {str(h['gate']):>34}  ({causa})")

    print("\n=== no-regresión ===")
    for cid in NO_REGRESSION:
        print(f"  {cid:16} {head[cid]['gate']}")

    test_gate_calibrations_flip()
    test_solo_las_7_cambian()
    test_no_regression()
    test_override_de_github_es_load_bearing()
    print("\n" + ("TODAS LAS CALIBRACIONES PASAN ✓" if ok else "HAY FALLAS ✗"))
