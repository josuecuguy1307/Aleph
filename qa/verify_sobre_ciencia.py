"""
verify_sobre_ciencia.py — VARA del pasaporte ajeno que se estaba tirando.
[Convergencia · superficie 7 · punto 2]

EL AGUJERO, MEDIDO ANTES DE TAPARLO
------------------------------------
Ciencia (OpenScience) trae su PROPIA procedencia: el nodo `artifact` de su grafo
declara `contentHash` —sha256 de los bytes— y un `provenance` entero con el commit
del código y el id de la corrida adentro (`science/provenance/store.ts:38-48`,
`provenance/envelope.ts:27-56`).

`openscience.js:139` lee ese grafo… y lo usaba como ÍNDICE, no como pasaporte:
copiaba `label`, `path`, `format` y `bytes`, y dejaba los otros dos atrás. Un archivo
que el stack SÍ ejecutó y SÍ hasheó llegaba a la casa sin ninguna forma de volver.

LO QUE **NO** CAMBIA, Y ES LA MITAD DEL PUNTO
----------------------------------------------
El grado. `capture_quality` se sigue topando en `declared` para todo lo que produce
un workspace, porque Aleph midió el modelo y no ejecutó el kernel. Un sobre ajeno que
se declare `exact` **no compra credibilidad acá**. Esta vara mide las dos cosas a la
vez: que la referencia llegue, y que no mueva el grado ni un milímetro.

Es la regla que `provenance.py:216` ya tenía escrita —«la referencia queda, así
cualquiera puede re-derivar después»— y que en este borde no se estaba cumpliendo.

    product/backend/.venv/bin/python qa/verify_sobre_ciencia.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_RAIZ / "product" / "backend"), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("PUPPET_MOTOR_PERSISTE", "0")
_TMP = Path(tempfile.mkdtemp(prefix="vara-sobre-"))
os.environ["ALEPH_DATA_DIR"] = str(_TMP / "data")

from artifacts import provenance as prov               # noqa: E402

_fallos = 0
_PLUGIN = _RAIZ / "platform" / "workspaces" / "plugins" / "openscience.js"

#: Un nodo `artifact` con la forma EXACTA del almacén de OpenScience, sobre incluido.
#: Los `{status,value}` no son adorno: así envuelve `field()` cada campo del sobre
#: (`provenance/envelope.ts:18-26`), y un campo ausente viene `{status:"unavailable"}`
#: SIN clave `value` — que es justo lo que el segundo caso mide.
_SHA = "a" * 64
NODO_COMPLETO = {
    "id": "nodo1", "kind": "artifact", "label": "synthetic_top10.png",
    "artifactType": "figure", "path": "/proy/fig.png", "size": 1024,
    "recordedAt": "2026-01-01T12:00:00.000Z",
    "contentHash": _SHA,
    "meta": {"format": "png"},
    "provenance": {
        "format": "openscience.provenance.v1", "kind": "local_compute",
        "identity": {
            "project_id": {"status": "available", "value": "proy-1"},
            "session_id": {"status": "available", "value": "ses-1"},
            "run_id": {"status": "available", "value": "run-abc123"},
        },
        "input": {
            "code": {"status": "available", "value": "print(1)"},
            "cwd": {"status": "available", "value": "/proy"},
            "code_state": {"status": "available", "value": {
                "repository": {"status": "available", "value": "git@x:y.git"},
                "branch": {"status": "available", "value": "main"},
                "commit": {"status": "available", "value": "deadbeefcafe"},
                "dirty": {"status": "available", "value": False},
            }},
        },
    },
}
#: El MISMO nodo con el sobre a medio llenar — el caso real de una corrida sin git.
NODO_PARCIAL = {
    **NODO_COMPLETO, "id": "nodo2", "contentHash": None,
    "provenance": {
        "format": "openscience.provenance.v1", "kind": "kernel",
        "identity": {"run_id": {"status": "available", "value": "run-solo"}},
        "input": {"code_state": {"status": "unavailable", "reason": "not_versioned"}},
    },
}


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))
    return bool(cond)


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA · EL SOBRE DE CIENCIA COMO REFERENCIA  [Convergencia · superficie 7]")
print("=" * 80)

# ── 1 · el plugin EXTRAE las tres, y se mide el plugin, no una copia ─────────
seccion("1 · el plugin extrae las tres referencias del nodo (medido en node)")
# CAÍDA: sin las tres líneas `source_*` en openscience.js, el regex de abajo no
# encuentra nada y el bloque entero queda rojo.
#
# Se EVALÚAN las expresiones sacadas del archivo, no copias escritas acá: una vara que
# reimplementa lo que mide no mide nada (la lección de `check_provenance`).

_fuente = _PLUGIN.read_text(encoding="utf-8")
_exprs = dict(re.findall(r"^\s*(source_\w+):\s*(n\.[^,\n]+),\s*$", _fuente, re.M))
ok(set(_exprs) == {"source_sha256", "source_run_ref", "source_commit"},
   "las tres expresiones están en openscience.js", str(sorted(_exprs)))

if _exprs:
    _js = (
        "const nodos = " + json.dumps([NODO_COMPLETO, NODO_PARCIAL]) + ";\n"
        "const out = nodos.map((n) => ({\n"
        + "".join(f"  {k}: {v},\n" for k, v in _exprs.items())
        + "}));\n"
        "console.log(JSON.stringify(out));\n"
    )
    _r = subprocess.run(["node", "-e", _js], capture_output=True, text=True, timeout=60)
    if _r.returncode != 0:
        ok(False, "las expresiones del plugin evalúan", (_r.stderr or "")[:200])
        _sacado = [{}, {}]
    else:
        _sacado = json.loads(_r.stdout)
        ok(_sacado[0].get("source_sha256") == _SHA, "sha256 de los bytes, del nodo")
        ok(_sacado[0].get("source_run_ref") == "run-abc123", "run_id, de adentro del sobre")
        ok(_sacado[0].get("source_commit") == "deadbeefcafe", "commit, de `code_state.value`")
        # Sin sobre completo NO se inventa: `{status:"unavailable"}` no tiene `value`.
        ok(_sacado[1].get("source_commit") is None,
           "sobre a medio llenar → el commit viaja ausente, jamás fabricado",
           str(_sacado[1].get("source_commit")))
        ok(_sacado[1].get("source_run_ref") == "run-solo",
           "…y lo que SÍ está sigue viajando (ausente ≠ todo o nada)")

# ── 2 · el bloque las guarda, saneadas ───────────────────────────────────────
seccion("2 · `provenance.build` las guarda como referencias, saneadas")
# CAÍDA: sin las tres en `_REF_FIELDS`, `build()` no las copia y quedan en None.

_b = prov.build({"space_id": "space-1", "produced_by": "workspace", "workspace": "ciencia",
                 "source_sha256": _SHA, "source_run_ref": "run-abc123",
                 "source_commit": "deadbeefcafe"}, None)
ok(_b["source_sha256"] == _SHA, "el sha256 queda en el bloque", str(_b.get("source_sha256")))
ok(_b["source_run_ref"] == "run-abc123", "el run del sobre queda", str(_b.get("source_run_ref")))
ok(_b["source_commit"] == "deadbeefcafe", "el commit queda", str(_b.get("source_commit")))

# Son referencias: pasan por el MISMO filtro que las demás, no por uno nuevo.
_sucio = prov.build({"space_id": "space-1", "produced_by": "workspace",
                     "source_sha256": "../../etc/passwd", "source_commit": "a b c"}, None)
ok(_sucio["source_sha256"] is None, "una ref con `/` se DESCARTA (safe_ref), no se guarda",
   str(_sucio.get("source_sha256")))
ok(_sucio["source_commit"] is None, "una ref con espacios también", str(_sucio.get("source_commit")))
# Y descartar no rompe el guardado: el artefacto es el trabajo del usuario.
ok(_sucio["capture_quality"] in prov.QUALITY, "…y el bloque se construye igual, sin excepción")

# ── 3 · EL GRADO NO SE MUEVE — la mitad que importa ─────────────────────────
seccion("3 · el sobre NO compra grado: `declared` sigue siendo el techo")
# CAÍDA: si `_cap_workspace` mirara las refs, este bloque daría `exact` y el
# anti-grift quedaría comprado con un dato que Aleph no midió.

_esp = _TMP / "espacios" / "space-x"
_esp.mkdir(parents=True, exist_ok=True)
(_esp / "events.jsonl").write_text(
    json.dumps({"type": "final", "model_final": "m1", "ok": True, "run_id": "r1"}) + "\n"
    + json.dumps({"type": "closed", "ok": True}) + "\n", encoding="utf-8")

_con = prov.build({"space_id": "space-x", "produced_by": "workspace", "workspace": "ciencia",
                   "source_sha256": _SHA, "source_run_ref": "run-abc123",
                   "source_commit": "deadbeefcafe"}, _esp / "events.jsonl")
_sin = prov.build({"space_id": "space-x", "produced_by": "workspace", "workspace": "ciencia"},
                  _esp / "events.jsonl")
ok(_con["capture_quality"] == "declared",
   "espacio CERRADO limpio + sobre completo → sigue `declared`", _con["capture_quality"])
ok(_con["capture_quality"] == _sin["capture_quality"],
   "el grado con sobre y sin sobre es IDÉNTICO — la referencia es inerte",
   f"{_con['capture_quality']} vs {_sin['capture_quality']}")
# Los hechos los sigue poniendo el evento firmado, no el sobre.
ok(_con["model_final"] == "m1" and _con["resolved_from"] == "events",
   "los HECHOS siguen saliendo del events.jsonl, no del sobre")
# Un sobre que se declarara `exact` tampoco cambia nada: no hay campo que lo lea.
ok("capture_quality" not in str(prov._REF_FIELDS),
   "ninguna referencia se llama como un campo de calidad — no hay puerta que forzar")

# ── 4 · el borde HTTP las acepta y las persiste ─────────────────────────────
seccion("4 · el borde HTTP: entran por el body y salen en el artefacto")
# CAÍDA: sin los tres campos en `WorkspaceArtifactRequest`, pydantic los ignora y el
# artefacto nace con las tres en None aunque el plugin las mande.

from fastapi import FastAPI                                  # noqa: E402
from fastapi.testclient import TestClient                    # noqa: E402
from app.phase1 import repo, artifact_store                  # noqa: E402
from app.phase1.router import build_phase1_router            # noqa: E402

_OWNER = "44444444-4444-4444-8444-444444444444"


class _Conn:
    raw = None

    def __init__(self):
        self.raw = self

    def execute(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


repo.session_owner = lambda token: _OWNER
artifact_store.get_owner = lambda sid: _OWNER
_app = FastAPI()
_app.include_router(build_phase1_router(get_conn=lambda: _Conn(), events_dir=lambda: _TMP / "espacios"))
_c = TestClient(_app)

# EL `try` NO ES ADORNO. Sin él, un `body` al que le falte un campo revienta con
# AttributeError adentro de `_Refs` y **mata la vara a mitad de esta sección**: los
# checks que siguen no se corren y su ausencia se lee como silencio, no como rojo. Es
# literalmente la lección de Gate 3 · obra C — tres defectos quedaron invisibles porque
# la vara crasheaba antes de llegar a ellos. Una vara tiene que poder REPROBAR; morirse
# no es reprobar.
_r = None
try:
    _r = _c.post("/v1/workspaces/artifacts", json={
        "sid": "s-vara", "workspace": "ciencia", "kind": "report", "name": "hallazgos.md",
        "data": {"name": "hallazgos.md", "content": "# hola", "format": "md"},
        "user_id": _OWNER, "space_id": "space-x", "chat_id": "c1",
        "source_sha256": _SHA, "source_run_ref": "run-abc123", "source_commit": "deadbeefcafe",
    }, headers={"Authorization": "Bearer t"})
except Exception as _exc:                                    # noqa: BLE001
    ok(False, "el borde atiende el pedido sin reventar", f"{type(_exc).__name__}: {_exc}"[:140])

ok(_r is not None and _r.status_code == 201, "el artefacto se crea",
   str(_r.status_code) if _r is not None else "no hubo respuesta")
if _r is not None and _r.status_code == 201:
    _p = _r.json()["artifact"]["provenance"]
    ok(_p.get("source_sha256") == _SHA, "el sha viaja hasta el artefacto persistido")
    ok(_p.get("source_run_ref") == "run-abc123", "…y el run del sobre")
    ok(_p.get("source_commit") == "deadbeefcafe", "…y el commit")
    ok(_p.get("produced_by") == "workspace", "sigue naciendo `produced_by: workspace`")
    ok(_p.get("capture_quality") == "declared",
       "y su grado sigue siendo `declared` — Aleph midió el modelo, no el kernel",
       str(_p.get("capture_quality")))
else:
    # Que los checks de adentro NO se hayan corrido tiene que CONTARSE, o la vara
    # reporta menos fallos de los que hay y el verde de mañana significa menos.
    for _q in ("sha", "run", "commit", "produced_by", "capture_quality"):
        ok(False, f"[no se pudo medir] {_q} en el artefacto persistido",
           "el borde no devolvió 201")

print()
print("=" * 80)
print("TODO VERDE" if _fallos == 0 else f"{_fallos} FALLO(S)")
print("=" * 80)
sys.exit(1 if _fallos else 0)
