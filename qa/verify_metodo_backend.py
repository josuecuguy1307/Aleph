#!/usr/bin/env python3
"""verify_metodo_backend.py — CERTIFICACIÓN de la pieza MÉTODO (carril backend).

Suite escalada (patrón de la casa):
  1 · los 6 módulos de test de la pieza, como subprocesos (determinista →
      in-process con cerebro guionado → executor+Postgres). Los tests §9 del
      ORDEN viven ahí: arnés no avanza sin evidencia · checkpoint bloquea ·
      fallo pausa a los 3 · saltar queda en auditoría · import re-inspeccionado ·
      referencia (no copia) al equipar · free fail-closed en export total/bóveda.
  2 · HTTP VIVO best-effort contra BASE (default :8080): CRUD + equipar + match
      + export .aleph/PDF por el server real. Skip honesto si está caído.

Corre:  BASE=http://127.0.0.1:8080 python3 qa/verify_metodo_backend.py
Requisitos: Postgres puppet_ai (los módulos con DB lo exigen; skip honesto si no).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

_THIS = Path(__file__).resolve()
REPO_ROOT = _THIS.parents[1]
BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
PY = str(REPO_ROOT / "product" / "backend" / ".venv" / "bin" / "python")
if not Path(PY).exists():
    PY = sys.executable

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


MODULES = [
    ("repo/normalización/match", "product/backend/app/phase1/test_methods_repo.py"),
    ("router CRUD + equipar por referencia", "product/backend/app/phase1/test_methods_router.py"),
    ("cerebro structure/propose/from_run/match", "product/backend/app/phase1/test_method_brain.py"),
    ("ARNÉS (verificador grounded + checkpoint + §5)", "platform/assembler/test_method_harness.py"),
    ("ARNÉS · hardening (repros del review adversarial)", "platform/assembler/test_method_hardening.py"),
    ("control (approve sentinela + pause/resume/remedy + continuación)",
     "product/backend/app/phase1/test_method_control.py"),
    ("export .aleph + muro premium + import", "product/backend/app/phase1/test_method_export.py"),
]


def section_1_modules():
    print("\n── 1 · MÓDULOS DE LA PIEZA (suite completa por subproceso) ──")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "product" / "backend")
    env["PUPPET_METHOD_SYNC_RESUME"] = "1"
    for label, rel in MODULES:
        p = subprocess.run([PY, str(REPO_ROOT / rel)], capture_output=True, text=True,
                           env=env, cwd=str(REPO_ROOT), timeout=600)
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        check(f"{label}: {tail[0]}", p.returncode == 0,
              "" if p.returncode == 0 else (p.stdout + p.stderr)[-400:])


def _req(method: str, path: str, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json",
                                          **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        try:
            return r.status, json.loads(raw)
        except Exception:
            return r.status, raw


def section_2_live():
    print(f"\n── 2 · HTTP VIVO best-effort ({BASE}) ──")
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=5) as r:
            r.read()
    except Exception as e:
        print(f"  [SKIP] server no responde ({e}) — sección viva no certificada")
        return
    email = f"metodo-live-{uuid.uuid4().hex[:8]}@test.local"
    try:
        st, reg = _req("POST", "/v1/auth/register",
                       {"email": email, "password": "metodo-live-123"})
        tok = reg.get("session_token")
        uid = (reg.get("user") or {}).get("id")
        check("2a registro vivo", st in (200, 201) and bool(tok), str(reg)[:150])

        st, m = _req("POST", "/v1/methods",
                     {"name": "Método vivo", "steps": [{"text": "paso real"}]}, tok)
        check("2b POST /v1/methods vivo (201 + id)", st == 201 and bool(m.get("id")))
        mid = m["id"]
        st, ls = _req("GET", "/v1/methods", None, tok)
        check("2c GET lista vivo", st == 200 and len(ls.get("methods") or []) == 1)
        st, mt = _req("POST", "/v1/methods/match",
                      {"puppet_id": None, "prompt": "cualquier cosa"}, tok)
        check("2d match fail-open vivo → {match:null}", st == 200 and mt.get("match") is None)
        st, al = _req("GET", f"/v1/methods/{mid}/export?format=aleph", None, tok)
        check("2e export .aleph vivo", st == 200 and al.get("type") == "method")
        try:
            req = urllib.request.Request(BASE + f"/v1/methods/{mid}/export?format=pdf",
                                         headers={"authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                pdf = r.read()
            check("2f export PDF vivo", pdf.startswith(b"%PDF"))
        except Exception as e:
            check("2f export PDF vivo", False, str(e))
        # los eventos method_* están registrados en el contrato del espinazo
        sys.path.insert(0, str(REPO_ROOT / "platform"))
        from flywheel.events_replay import EVENT_TYPES
        need = {"method_started", "method_step_started", "method_step_done",
                "method_checkpoint_waiting", "method_step_failed",
                "method_paused", "method_resumed"}
        check("2g EVENT_TYPES registra los 7 method_*", need <= EVENT_TYPES)
    except Exception as e:
        check("2 · sección viva", False, f"excepción: {e}")


def main() -> int:
    section_1_modules()
    section_2_live()
    print(f"\n════ RESULTADO: {_passed} PASS / {_failed} FAIL ════")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
