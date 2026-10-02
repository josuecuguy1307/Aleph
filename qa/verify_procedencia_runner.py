#!/usr/bin/env python3
"""verify_procedencia_runner.py — EL ANTI-GRIFT, CABLEADO AL CARRIL DE VARAS.

[Gate 4 · Fase 2 · obra 2.5 — deuda D4 del contrato §10 · plan OSS 2.6]

EL AGUJERO QUE CIERRA, con su medición previa (censo §5 / PARTE IV.5):
`qa/anti-fake-suite/check_provenance.py` **existe y discrimina** —fixture falso: 4
señales; run real: AUTÉNTICO— y **no lo invocaba nadie**. El carril de varas
descubre `verify_*.py` (`qa/correr_varas.py:138`), y el auditor no se llama así.
Un detector que nadie corre no protege de nada: es documentación ejecutable que
nadie ejecuta. Este archivo ES el cable: se llama `verify_…`, así que el runner lo
descubre y lo corre en cada pasada, y adentro invoca al auditor como proceso —
mismo binario, mismos exit codes que usaría un CI.

QUÉ MIDE (todo por subprocess, sobre el auditor de verdad):
  A · discriminación: el registro REAL sale AUTÉNTICO (exit 0) y el fake plantado
      sale SOSPECHOSO (exit 1) con ≥2 señales. Si esto se rompe, el auditor dejó
      de servir y el resto de la vara no vale nada.
  B · S8, la señal de HECHO que agrega 2.5: un artefacto honesto (procedencia
      construida con el resolver del producto sobre un registro real) CRUZA; y
      cada falsificación —el modelo, el conteo de tools, el contenido editado
      dejando el hash viejo, y un `capture_quality: exact` sin evento terminal—
      lo hace SOSPECHOSO, nombrando el campo.
  C · el cable en sí: este archivo matchea el descubridor del runner, y el auditor
      conserva sus exit codes (0/1) — que es lo que lo vuelve un gate.

NO toca datos reales: todo pasa en un tmp propio y sobre fixtures del árbol.

    product/backend/.venv/bin/python qa/verify_procedencia_runner.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_AQUI / "lib"), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import veredicto as V             # noqa: E402
from artifacts import provenance as prov   # noqa: E402

_PY = sys.executable
_AUDITOR = _AQUI / "anti-fake-suite" / "check_provenance.py"
_REAL = _RAIZ / "platform" / "assembler" / ".demo-session-run" / "events.jsonl"
_FAKE = _AQUI / "anti-fake-suite" / "fixtures" / "events-faked.jsonl"

_fallos = 0
_salteados = 0
_criticos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))
    return bool(cond)


def saltear(nombre, motivo, critico=False):
    global _salteados, _criticos
    _salteados += 1
    if critico:
        _criticos += 1
    print(f"  ~ SALTEADO {nombre}  —  {motivo}" + ("   [DE SU OBJETO]" if critico else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def auditar(events: Path, artifact: Path | None = None) -> tuple[int, dict]:
    """Invoca el auditor COMO PROCESO (igual que lo haría un CI) → (exit, reporte)."""
    cmd = [_PY, str(_AUDITOR), str(events), "--json"]
    if artifact is not None:
        cmd += ["--artifact", str(artifact)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"_stdout": r.stdout[-500:], "_stderr": r.stderr[-500:]}


def señal(rep: dict, nombre: str) -> dict:
    for s in rep.get("signals", []):
        if s["name"].startswith(nombre):
            return s
    return {}


print("=" * 80)
print("VARA · EL ANTI-GRIFT CORRIDO POR EL RUNNER (Gate 4 · 2.5 · deuda D4)")
print("=" * 80)

# ══════════════════════════════════════════════════════════════════════════════
seccion("A · discriminación: el auditor sigue distinguiendo lo real de lo plantado")

if not _REAL.exists():
    saltear("A", f"no está el registro real del árbol ({_REAL.relative_to(_RAIZ)})", critico=True)
else:
    _e, _rep = auditar(_REAL)
    ok(_e == 0 and _rep.get("global") == "AUTÉNTICO",
       "registro REAL del árbol → AUTÉNTICO, exit 0",
       f"exit={_e} veredicto={_rep.get('global')} razones={_rep.get('global_reasons')}")
    ok(_rep.get("format") == "session" and _rep.get("n_tool_calls", 0) > 0,
       "…y se leyó como sesión con tool-calls de verdad",
       f"formato={_rep.get('format')} tool_calls={_rep.get('n_tool_calls')}")

if not _FAKE.exists():
    saltear("A · fake", "falta el fixture plantado", critico=True)
else:
    _e, _rep = auditar(_FAKE)
    ok(_e == 1 and _rep.get("global") == "SOSPECHOSO",
       "fake plantado → SOSPECHOSO, exit 1 (el gate corta)",
       f"exit={_e} veredicto={_rep.get('global')}")
    ok(_rep.get("n_suspicious_signals", 0) >= 2,
       "…con ≥2 señales en contra (la prueba de fuego del README)",
       str(_rep.get("n_suspicious_signals")))

# ══════════════════════════════════════════════════════════════════════════════
seccion("B · S8 · el artefacto se cruza contra el registro (la señal de HECHO de 2.5)")

_tmp = Path(tempfile.mkdtemp(prefix="vara-procedencia-"))
_espacio = _tmp / "sp_vara2b"
_espacio.mkdir(parents=True)
_ev = _espacio / "events.jsonl"

#: Un registro de sesión REAL en forma: started→finished con executed, final y closed.
#: Los ts llevan jitter de wall-clock a propósito (S3 mata la grilla perfecta) y el
#: session_id es hex-12 porque S2 lo exige — la primera pasada de esta vara usó
#: "vara2b" y el auditor la rechazó ANTES de llegar a S8. Bien rechazada: un fixture
#: que el auditor no aceptaría no sirve para probar al auditor.
_t0 = time.time()
_lineas = [
    {"ts": _t0 + 0.013, "session_id": "0f1e2d3c4b5a", "type": "belt_ready",
     "servers": ["calc"], "servers_skipped": [], "tools": ["suma"]},
    {"ts": _t0 + 0.041, "session_id": "0f1e2d3c4b5a", "type": "turn_started", "turn": 1},
    {"ts": _t0 + 1.207, "session_id": "0f1e2d3c4b5a", "type": "tool_call_started",
     "call_id": "a1b2c3d4e5f6", "tool": "calc", "args": "{\"a\": 2, \"b\": 3}"},
    {"ts": _t0 + 1.884, "session_id": "0f1e2d3c4b5a", "type": "tool_call_finished",
     "call_id": "a1b2c3d4e5f6", "tool": "calc", "executed": True, "result": "5"},
    {"ts": _t0 + 2.310, "session_id": "0f1e2d3c4b5a", "type": "final",
     "model_final": "claude-sonnet-5", "ok": True, "run_id": "run-vara2b"},
    {"ts": _t0 + 2.377, "session_id": "0f1e2d3c4b5a", "type": "closed",
     "model_final": "claude-sonnet-5", "ok": True, "degraded": None, "run_id": "run-vara2b"},
]
_ev.write_text("\n".join(json.dumps(x) for x in _lineas) + "\n", encoding="utf-8")

_contenido = "# Obra de la vara\n\nDos más tres son cinco.\n"


def _sesion_de_artefactos(prov_block: dict, contenido: str, sha: str | None = None) -> dict:
    return {"schema_version": 2, "session_id": "sid-vara2b", "artifacts": [{
        "id": "art_vara2b", "session_id": "sid-vara2b", "title": "Obra de la vara",
        "type": "informe", "content": contenido,
        "content_sha256": sha if sha is not None else hashlib.sha256(
            contenido.encode("utf-8")).hexdigest(),
        "provenance": prov_block, "versions": [],
    }]}


# el bloque HONESTO: construido por el resolver DEL PRODUCTO sobre ese registro
_honesto = prov.build({"space_id": "sp_vara2b", "run_id": "run-vara2b",
                       "produced_by": "run", "user_id": "u1", "agent_id": "ag1"}, _ev)
ok(_honesto["model_final"] == "claude-sonnet-5" and _honesto["tool_calls"] == 1
   and _honesto["capture_quality"] == "exact",
   "el resolver del producto resolvió el registro de la vara (modelo · 1 tool · exact)",
   json.dumps({k: _honesto[k] for k in ("model_final", "tool_calls", "capture_quality")}))

_art_ok = _tmp / "sesion-honesta.json"
_art_ok.write_text(json.dumps(_sesion_de_artefactos(_honesto, _contenido)), encoding="utf-8")
_e, _rep = auditar(_ev, _art_ok)
_s8 = señal(_rep, "S8")
ok(_e == 0 and _rep.get("global") == "AUTÉNTICO",
   "artefacto honesto + su registro → AUTÉNTICO, exit 0",
   f"exit={_e} razones={_rep.get('global_reasons')}")
ok(_s8.get("verdict") == "AUTÉNTICO",
   "S8 MIDIÓ (no salió N/A): el cruce artefacto↔registro se hizo de verdad",
   json.dumps(_s8, ensure_ascii=False)[:300])

#: Las falsificaciones, una por una. Cada una tiene que voltear S8 Y el veredicto
#: global, y nombrar el campo — un auditor que dice «sospechoso» sin decir de qué
#: obliga a confiar en él, que es lo contrario de lo que existe para hacer.
_casos = []

_m = json.loads(json.dumps(_honesto)); _m["model_final"] = "gpt-4o-inventado"
_casos.append(("modelo inventado", _sesion_de_artefactos(_m, _contenido), "model_final"))

_c = json.loads(json.dumps(_honesto)); _c["tool_calls"] = 7
_casos.append(("conteo de tools inflado", _sesion_de_artefactos(_c, _contenido), "tool_calls"))

_t = json.loads(json.dumps(_honesto)); _t["tools"] = ["freecad", "kicad"]
_casos.append(("nombres de tools inventados", _sesion_de_artefactos(_t, _contenido), "tools"))

_sesion_editada = _sesion_de_artefactos(_honesto, _contenido + "\n(párrafo agregado a mano)\n",
                                        sha=hashlib.sha256(_contenido.encode("utf-8")).hexdigest())
_casos.append(("contenido editado con el hash viejo", _sesion_editada, "content_sha256"))

_sin_cierre = _tmp / "sp_sincierre"
_sin_cierre.mkdir()
_ev2 = _sin_cierre / "events.jsonl"
_ev2.write_text("\n".join(json.dumps(x) for x in _lineas[:-1]) + "\n", encoding="utf-8")
_q = json.loads(json.dumps(_honesto)); _q["capture_quality"] = "exact"; _q["space_id"] = "sp_sincierre"

for _nombre, _sesion, _campo in _casos:
    _p = _tmp / ("falso-" + re.sub(r"\W+", "-", _nombre) + ".json")
    _p.write_text(json.dumps(_sesion), encoding="utf-8")
    _e, _rep = auditar(_ev, _p)
    _s8 = señal(_rep, "S8")
    _razones = " | ".join(_s8.get("reasons", []))
    ok(_e == 1 and _s8.get("verdict") == "SOSPECHOSO" and _campo in _razones,
       f"falsificación «{_nombre}» → SOSPECHOSO nombrando `{_campo}`",
       f"exit={_e} s8={_s8.get('verdict')} razones={_razones[:220]}")

_p = _tmp / "falso-exact-sin-cierre.json"
_p.write_text(json.dumps(_sesion_de_artefactos(_q, _contenido)), encoding="utf-8")
_e, _rep = auditar(_ev2, _p)
_s8 = señal(_rep, "S8")
ok(_e == 1 and _s8.get("verdict") == "SOSPECHOSO"
   and any("capture_quality=exact" in r for r in _s8.get("reasons", [])),
   "falsificación «capture_quality exact sin evento terminal» → SOSPECHOSO",
   json.dumps(_s8.get("reasons"), ensure_ascii=False)[:260])

# y la honestidad del legacy: `provenance: null` NO es sospechoso, es la confesión
_legacy = _tmp / "legacy.json"
_legacy.write_text(json.dumps(_sesion_de_artefactos(None, _contenido)), encoding="utf-8")
_e, _rep = auditar(_ev, _legacy)
ok(_e == 0 and señal(_rep, "S8").get("verdict") in ("AUTÉNTICO", "N/A"),
   "un artefacto legacy (provenance null) NO se acusa: omitir es honesto, fabricar no",
   json.dumps(señal(_rep, "S8"), ensure_ascii=False)[:240])

# ══════════════════════════════════════════════════════════════════════════════
seccion("C · el cable: el runner descubre esta vara y el auditor sigue siendo un gate")

_descubridor = re.compile(r"(^|/)verify_[^/]*\.py$")
ok(bool(_descubridor.search("qa/" + Path(__file__).name)),
   "esta vara matchea el descubridor de qa/correr_varas.py — el runner la corre sola")

_fuente_runner = (_AQUI / "correr_varas.py").read_text(encoding="utf-8")
_m = re.search(r'r"\(\^\|/\)verify_\[\^/\]\*\\\.py\$"', _fuente_runner)
ok(_m is not None,
   "…y el descubridor del runner sigue siendo el que esta vara asume",
   "cambió el regex de correr_varas.py:_varas()")

_e, _ = auditar(_FAKE)
ok(_e == 1, "el auditor conserva su exit code 1 ante lo falso (sirve de gate en CI)", f"exit={_e}")
_e, _ = auditar(_REAL)
ok(_e == 0, "…y exit 0 ante lo real (no bloquea lo bueno)", f"exit={_e}")

# higiene: la vara se lleva su propia basura (regla de la fase de higiene de Gate 3)
shutil.rmtree(_tmp, ignore_errors=True)
print(f"\n     [higiene] tmp de la vara borrado: {not _tmp.exists()}")

print("\n     [invocación única del chequeo completo]  "
      "product/backend/.venv/bin/python qa/correr_varas.py")
sys.exit(V.cerrar(_fallos, _salteados, _criticos))
