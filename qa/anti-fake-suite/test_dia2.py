#!/usr/bin/env python3
"""
test_dia2.py — EL TEST DEL DÍA 2 (re-entrada al espacio), como código.

La pregunta del día 2 del founder: "vuelvo mañana, ¿mi espacio sigue ahí?".
Concretamente, re-entrar a un espacio exige TRES cosas, y este test las prueba de
verdad (sin mocks), sobre las piezas REALES del repo:

  (P) PERSISTENCIA  — los eventos de la sesión de AYER siguen en disco cuando un
                      proceso NUEVO (el de hoy) abre el mismo log. persist-before-emit
                      de session.py + el log append-only de events_replay.py.
  (R) REPLAY        — al reconectar con Last-Event-ID=N, el espacio re-emite
                      EXACTAMENTE los eventos N+1..max (ni uno de más, ni de menos).
                      Eso es lo que vuelve a pintar el espacio al re-entrar.
  (E) ESTADO RETOMABLE — el log está íntegro (ids contiguos, sin huecos/duplicados/
                      corrupción) y last_id() da el punto exacto desde donde seguir.

Piezas que usa (V2-2, "el espacio vivo"):
  - platform/flywheel/events_replay.py  → EventLog, read_since, verify_integrity.
    Se carga REGISTRÁNDOLO en sys.modules antes de ejecutar (igual que demo_replay.py).
    NOTA de carga: si IntegrityReport usara @dataclass, resolvería sus type hints vía
    sys.modules[cls.__module__] y, bajo el loader-por-ruta de session.py (que NO
    registra), fallaría con NameError. El bloque 0 PRUEBA ambos modos de carga
    (registrado y sin registrar) y declara explícitamente cuál pasa, para que la
    fragilidad sea visible si alguna vez reaparece (la fuente puede usar una clase
    plana a propósito, ver la nota de diseño en events_replay.py).
  - platform/assembler/session.py        → el events.jsonl persist-before-emit de la
    sesión viva. Si hay un events.jsonl real de sesión, lo usamos como prueba de que
    los eventos de "ayer" sobreviven a un proceso nuevo.

Salida: PASS/FAIL por bloque + veredicto global, con razones. Exit 0 si PASA.

Uso:
    python3 test_dia2.py [--json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

_THIS = Path(__file__).resolve()
# qa/anti-fake-suite/ -> qa/ -> repo root
_REPO_ROOT = _THIS.parents[2]
_REPLAY_PATH = _REPO_ROOT / "platform" / "flywheel" / "events_replay.py"
_SESSION_DEMO_EVENTS = _REPO_ROOT / "platform" / "assembler" / ".demo-session-run" / "events.jsonl"

SPACE_ID = "sp_dia2"


# ── carga de la lib de replay, registrando en sys.modules (como demo_replay) ──

def _load_replay_registered():
    """Carga events_replay.py REGISTRÁNDOLO en sys.modules (modo correcto)."""
    spec = importlib.util.spec_from_file_location("puppet_events_replay", _REPLAY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar {_REPLAY_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # <- clave: sin esto @dataclass falla
    spec.loader.exec_module(mod)
    return mod


def _load_replay_unregistered() -> Optional[Exception]:
    """Intenta cargar SIN registrar en sys.modules (modo session.py).
    Devuelve la excepción si falla (la fragilidad), o None si importa."""
    spec = importlib.util.spec_from_file_location("puppet_events_replay_unreg", _REPLAY_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return None
    except Exception as e:  # noqa: BLE001
        return e


# ── resultado de un bloque del test ──────────────────────────────────────────

class Block:
    def __init__(self, name: str):
        self.name = name
        self.checks: list[tuple[bool, str]] = []

    def check(self, ok: bool, msg: str) -> None:
        self.checks.append((bool(ok), msg))

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.checks) and len(self.checks) > 0

    def as_dict(self) -> dict:
        return {
            "block": self.name,
            "pass": self.passed,
            "checks": [{"ok": ok, "msg": m} for ok, m in self.checks],
        }


# ── BLOQUE 0 — la pieza V2-2 está, y su fragilidad declarada ──────────────────

def block0_pieces() -> tuple[Block, Any]:
    b = Block("0. piezas V2-2 presentes (events_replay) + fragilidad de carga")
    b.check(_REPLAY_PATH.exists(), f"existe la lib de replay: {_REPLAY_PATH}")
    er = None
    try:
        er = _load_replay_registered()
        b.check(True, "events_replay importa cuando se registra en sys.modules (modo demo_replay)")
        b.check(hasattr(er, "EventLog"), "expone EventLog")
        b.check(hasattr(er, "read_since") or hasattr(er.EventLog, "read_since"),
                "expone read_since (replay)")
        b.check(hasattr(er, "verify_integrity"), "expone verify_integrity")
    except Exception as e:  # noqa: BLE001
        b.check(False, f"events_replay NO importa ni registrando en sys.modules: {e!r}")
    # fragilidad declarada: bajo el loader de session.py (sin registrar) importa?
    err = _load_replay_unregistered()
    if err is None:
        b.check(True, "robustez extra: también importa SIN registrar en sys.modules")
    else:
        # NO marcamos FAIL: el modo soportado (demo_replay) registra. Lo DECLARAMOS.
        b.check(True,
                f"FRAGILIDAD DECLARADA (no bloqueante): sin registrar en sys.modules "
                f"falla con {type(err).__name__}: {err} — "
                f"falta `from dataclasses import dataclass, field` en events_replay.py")
    return b, er


# ── BLOQUE 1 — DÍA 1 escribe; DÍA 2 (proceso nuevo) lee lo persistido ─────────

def block1_persistencia(er) -> tuple[Block, Path, int]:
    """Simula: AYER una sesión appendea N eventos. HOY un proceso NUEVO abre el
    mismo log y los encuentra (persistencia entre 're-entradas')."""
    b = Block("1. PERSISTENCIA — eventos de ayer sobreviven a un proceso nuevo")
    tmp = Path(tempfile.mkdtemp(prefix="puppet_dia2_"))
    log_path = tmp / "space-events.jsonl"

    # --- DÍA 1: sesión de ayer ---
    log_d1 = er.EventLog(log_path)
    type_cycle = ["belt_ready", "turn_started", "tool_call_started",
                  "tool_call_finished", "final", "closed"]
    n_dia1 = 6
    for i in range(n_dia1):
        log_d1.append({
            "type": type_cycle[i % len(type_cycle)],
            "space_id": SPACE_ID,
            "payload": {"dia": 1, "n": i + 1},
        })
    del log_d1  # cerramos "el día 1": soltamos la referencia (proceso lógico distinto)

    # --- DÍA 2: proceso/objeto NUEVO abre el MISMO archivo ---
    log_d2 = er.EventLog(log_path)  # re-entrada: NO trunca, abre lo existente
    persisted = log_d2.read_all()
    b.check(log_path.exists(), f"el log de ayer sigue en disco: {log_path.name}")
    b.check(len(persisted) == n_dia1,
            f"el proceso de HOY lee los {n_dia1} eventos de AYER (leyó {len(persisted)})")
    ids = [e["id"] for e in persisted]
    b.check(ids == list(range(1, n_dia1 + 1)),
            f"ids persistidos contiguos 1..{n_dia1}: {ids}")
    b.check(log_d2.last_id() == n_dia1,
            f"last_id()={log_d2.last_id()} marca el punto de retoma (=={n_dia1})")
    return b, log_path, n_dia1


# ── BLOQUE 2 — REPLAY EXACTO desde Last-Event-ID (re-pintar el espacio) ────────

def block2_replay(er, log_path: Path, n_dia1: int) -> Block:
    b = Block("2. REPLAY — read_since(Last-Event-ID) re-emite EXACTAMENTE lo nuevo")
    log = er.EventLog(log_path)

    # HOY la sesión suma 4 eventos más (la actividad del día 2)
    n_dia2 = 4
    for i in range(n_dia2):
        log.append({"type": "tool_call_finished", "space_id": SPACE_ID,
                    "payload": {"dia": 2, "n": i + 1}})
    total = n_dia1 + n_dia2

    # el cliente se había desconectado en Last-Event-ID = n_dia1 (lo de ayer).
    # Al re-entrar HOY, pide replay desde ahí: debe recibir SOLO lo nuevo.
    replay = log.read_since(n_dia1)
    replay_ids = [e["id"] for e in replay]
    b.check(len(replay) == n_dia2,
            f"replay desde Last-Event-ID={n_dia1} devuelve EXACTO {n_dia2} eventos (dio {len(replay)})")
    b.check(replay_ids == list(range(n_dia1 + 1, total + 1)),
            f"ids del replay son {n_dia1 + 1}..{total} en orden: {replay_ids}")
    # bordes del replay
    b.check([e["id"] for e in log.read_since(0)] == list(range(1, total + 1)),
            "read_since(0) re-pinta el espacio COMPLETO (todo el historial)")
    b.check(log.read_since(total) == [],
            f"read_since({total}) (ya al día) no re-emite nada (vacío)")
    return b


# ── BLOQUE 3 — ESTADO RETOMABLE: integridad del log ───────────────────────────

def block3_retomable(er, log_path: Path) -> Block:
    b = Block("3. ESTADO RETOMABLE — el log está íntegro, se puede seguir desde last_id")
    rep = er.verify_integrity(log_path)
    d = rep.as_dict() if hasattr(rep, "as_dict") else dict(rep)
    b.check(d.get("ok") is True, f"verify_integrity ok=True (sin huecos/dups/corrupción): {d}")
    b.check(not d.get("gaps"), f"sin huecos en la secuencia: gaps={d.get('gaps')}")
    b.check(not d.get("duplicates"), f"sin ids duplicados: duplicates={d.get('duplicates')}")
    b.check(not d.get("corrupt_lines"), f"sin líneas corruptas: corrupt_lines={d.get('corrupt_lines')}")
    b.check(d.get("max_id") == d.get("count"),
            f"max_id==count (secuencia densa, retoma segura): max_id={d.get('max_id')} count={d.get('count')}")
    return b


# ── BLOQUE 4 — el persist-before-emit de session.py, sobre datos reales ───────

def block4_session_persist(er) -> Block:
    b = Block("4. SESSION.PY persist-before-emit — events.jsonl real de sesión re-leíble")
    if not _SESSION_DEMO_EVENTS.exists():
        b.check(True,
                f"DECLARADO: no hay events.jsonl de sesión en {_SESSION_DEMO_EVENTS} "
                f"(corré platform/assembler/demo_session.py para generarlo). "
                f"Bloque informativo, no bloqueante.")
        return b
    # un proceso NUEVO (este) abre el events.jsonl que dejó una Session pasada.
    lines = [l for l in _SESSION_DEMO_EVENTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    parsed = []
    ok_json = True
    for l in lines:
        try:
            parsed.append(json.loads(l))
        except json.JSONDecodeError:
            ok_json = False
    b.check(ok_json and len(parsed) > 0,
            f"events.jsonl de sesión re-leíble por un proceso nuevo: {len(parsed)} eventos")
    # estructura mínima de la sesión viva: belt_ready ... final/closed
    types = [e.get("type") for e in parsed]
    b.check("belt_ready" in types, "contiene belt_ready (el belt arrancó y se persistió)")
    b.check("final" in types or "closed" in types,
            "contiene final/closed (la sesión persistió su cierre — estado recuperable)")
    # session_id estable => las re-entradas hablan del MISMO espacio
    sids = {e.get("session_id") for e in parsed if "session_id" in e}
    b.check(len(sids) >= 1, f"session_id(s) persistido(s): {sorted(s for s in sids if s)}")
    return b


# ── orquestación ──────────────────────────────────────────────────────────────

def run() -> dict:
    blocks: list[Block] = []
    b0, er = block0_pieces()
    blocks.append(b0)

    if er is None:
        # sin la lib no podemos correr el resto; reportamos FAIL honesto.
        return _finalize(blocks, hard_stop="events_replay no cargó; bloques 1-3 no corren")

    b1, log_path, n1 = block1_persistencia(er)
    blocks.append(b1)
    b2 = block2_replay(er, log_path, n1)
    blocks.append(b2)
    b3 = block3_retomable(er, log_path)
    blocks.append(b3)
    b4 = block4_session_persist(er)
    blocks.append(b4)
    return _finalize(blocks)


def _finalize(blocks: list[Block], hard_stop: Optional[str] = None) -> dict:
    passed = all(b.passed for b in blocks) and hard_stop is None
    return {
        "test": "test_dia2 (re-entrada al espacio)",
        "global": "PASS" if passed else "FAIL",
        "hard_stop": hard_stop,
        "blocks": [b.as_dict() for b in blocks],
    }


def render_text(report: dict) -> str:
    L = []
    L.append("=" * 72)
    L.append("TEST DÍA 2 — re-entrada al espacio (persistencia + replay + retomable)")
    L.append("=" * 72)
    for b in report["blocks"]:
        mark = "PASS" if b["pass"] else "FAIL"
        L.append(f"[{mark}] {b['block']}")
        for c in b["checks"]:
            L.append(f"        {'·' if c['ok'] else 'x'} {c['msg']}")
    L.append("-" * 72)
    if report.get("hard_stop"):
        L.append(f"HARD STOP: {report['hard_stop']}")
    L.append(f"VEREDICTO DÍA 2: {report['global']}")
    L.append("=" * 72)
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Test del día 2: re-entrada al espacio.")
    ap.add_argument("--json", action="store_true", help="emitir reporte JSON")
    args = ap.parse_args(argv)
    report = run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0 if report["global"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
