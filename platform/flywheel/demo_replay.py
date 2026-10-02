#!/usr/bin/env python3
"""
demo_replay.py — Prueba de fuego de events_replay.py (PRODUCT-V2-DESIGN).

BINARIO: corre y el replay es EXACTO, o falla con exit!=0.

Qué demuestra, de punta a punta y SIN mocks:
  1. CONCURRENCIA REAL: 2 writers en THREADS distintos appendean 20 eventos al
     MISMO log a la vez. Comprobamos que los ids salieron 1..20 contiguos, sin
     huecos ni duplicados (lock de archivo => no se corrompen entre sí).
  2. CORTE + REPLAY EXACTO: simulamos una reconexión con Last-Event-ID=12.
     read_since(12) debe devolver EXACTAMENTE 8 eventos (ids 13..20), ni uno más
     ni uno menos, y en orden.
  3. INTEGRIDAD OK: verify_integrity sobre el log sano => ok=True.
  4. CORRUPCIÓN DETECTADA: plantamos un archivo con un hueco, un duplicado, una
     línea no-JSON y un tipo inválido => verify_integrity => ok=False y los reporta.

stdlib only. Cero paths absolutos: todo vive en un tempdir efímero.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
from pathlib import Path

# ── Cargar la lib hermana por ruta de archivo (no asume paquete instalado) ─────
_THIS_DIR = Path(__file__).resolve().parent
_LIB_PATH = _THIS_DIR / "events_replay.py"

_spec = importlib.util.spec_from_file_location("events_replay_demo", _LIB_PATH)
assert _spec and _spec.loader, f"No se pudo cargar la lib en {_LIB_PATH}"
_er = importlib.util.module_from_spec(_spec)
# Registrar el módulo ANTES de ejecutarlo: dataclasses resuelve type hints vía
# sys.modules[cls.__module__]; sin esto, @dataclass falla al cargar por ruta.
sys.modules[_spec.name] = _er
_spec.loader.exec_module(_er)

EventLog = _er.EventLog
verify_integrity = _er.verify_integrity
EVENT_TYPES = _er.EVENT_TYPES

SPACE_ID = "sp_demo"
TOTAL = 20
CUT_AT = 12  # Last-Event-ID de la reconexión
EXPECTED_AFTER_CUT = TOTAL - CUT_AT  # 8

# Tipos reales de la taxonomía para que los eventos sean legítimos.
_TYPE_CYCLE = [
    "belt_ready", "turn_started", "tool_call_started", "tool_call_finished",
    "gate_waiting", "gate_resolved", "artifact_created", "equipment_changed",
    "final", "closed",
]


def _ok(label: str) -> None:
    print(f"  [OK]    {label}")


def _fail(label: str) -> None:
    print(f"  [FALLO] {label}")


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def writer(log: EventLog, writer_name: str, payloads: list, assigned: list,
           barrier: threading.Barrier) -> None:
    """Un writer concurrente: arranca al mismo tiempo que el otro y appendea."""
    barrier.wait()  # los dos hilos largan a la vez -> contención real sobre el lock
    for n in payloads:
        etype = _TYPE_CYCLE[(n - 1) % len(_TYPE_CYCLE)]
        ev = log.append({
            "type": etype,
            "space_id": SPACE_ID,
            "payload": {"writer": writer_name, "n": n},
        })
        assigned.append((writer_name, ev["id"]))


def main() -> int:
    failures = 0

    with tempfile.TemporaryDirectory(prefix="puppet_replay_demo_") as tmp:
        tmpdir = Path(tmp)
        log_path = tmpdir / "space-events.jsonl"
        print(f"Carpeta efímera : {tmpdir}")
        print(f"Log del espacio : {log_path.name}")
        print(f"Backend de lock : {_er._LOCK_BACKEND}")

        # ── 1) DOS WRITERS CONCURRENTES DE VERDAD (threads) ────────────────────
        section("1) CONCURRENCIA REAL — 2 writers, 20 eventos, mismo log")
        log = EventLog(log_path)

        # Repartimos los 20 "trabajos" entre dos hilos de forma intercalada,
        # para que ambos compitan por el lock durante toda la corrida.
        jobs_a = [n for n in range(1, TOTAL + 1) if n % 2 == 1]  # impares
        jobs_b = [n for n in range(1, TOTAL + 1) if n % 2 == 0]  # pares
        assigned_a: list = []
        assigned_b: list = []
        barrier = threading.Barrier(2)

        t_a = threading.Thread(target=writer, args=(log, "A", jobs_a, assigned_a, barrier))
        t_b = threading.Thread(target=writer, args=(log, "B", jobs_b, assigned_b, barrier))
        t_a.start(); t_b.start()
        t_a.join(); t_b.join()

        all_assigned = sorted(i for _, i in (assigned_a + assigned_b))
        print(f"  writer A appendeó {len(assigned_a)} eventos; "
              f"writer B appendeó {len(assigned_b)} eventos.")
        print(f"  ids asignados (ordenados): {all_assigned}")

        if all_assigned == list(range(1, TOTAL + 1)):
            _ok(f"los {TOTAL} ids son 1..{TOTAL} contiguos, sin huecos ni duplicados")
        else:
            _fail(f"ids esperados 1..{TOTAL}, se obtuvo {all_assigned}")
            failures += 1

        if len(set(all_assigned)) == TOTAL:
            _ok("cero ids duplicados pese a la contención de 2 hilos")
        else:
            _fail("hay ids duplicados — el lock no protegió la asignación")
            failures += 1

        # ── 2) CORTE + REPLAY EXACTO desde Last-Event-ID=12 ────────────────────
        section(f"2) RECONEXIÓN — corte en {CUT_AT}, replay desde Last-Event-ID={CUT_AT}")
        replay = log.read_since(CUT_AT)
        replay_ids = [e["id"] for e in replay]
        print(f"  read_since({CUT_AT}) devolvió {len(replay)} eventos: ids {replay_ids}")

        if len(replay) == EXPECTED_AFTER_CUT:
            _ok(f"replay devolvió EXACTAMENTE {EXPECTED_AFTER_CUT} eventos")
        else:
            _fail(f"replay debía devolver {EXPECTED_AFTER_CUT}, devolvió {len(replay)}")
            failures += 1

        if replay_ids == list(range(CUT_AT + 1, TOTAL + 1)):
            _ok(f"los ids del replay son {CUT_AT + 1}..{TOTAL}, en orden, exactos")
        else:
            _fail(f"ids del replay incorrectos: {replay_ids}")
            failures += 1

        # borde: read_since(0) == todo el log; read_since(TOTAL) == vacío
        if [e["id"] for e in log.read_since(0)] == list(range(1, TOTAL + 1)):
            _ok("read_since(0) reproduce el log completo")
        else:
            _fail("read_since(0) no reprodujo el log completo")
            failures += 1
        if log.read_since(TOTAL) == []:
            _ok(f"read_since({TOTAL}) (ya al día) devuelve vacío")
        else:
            _fail(f"read_since({TOTAL}) debía ser vacío")
            failures += 1

        # ── 3) INTEGRIDAD OK sobre el log sano ─────────────────────────────────
        section("3) INTEGRIDAD — log sano")
        rep = verify_integrity(log_path)
        print("  verify_integrity ->", json.dumps(rep.as_dict(), ensure_ascii=False))
        if rep.ok and rep.count == TOTAL and rep.max_id == TOTAL \
                and not rep.gaps and not rep.duplicates and not rep.corrupt_lines:
            _ok(f"verify_integrity OK: {TOTAL} eventos, max_id={TOTAL}, sin anomalías")
        else:
            _fail("verify_integrity reportó anomalías en un log que debía estar sano")
            failures += 1

        # ── 4) CORRUPCIÓN PLANTADA — debe ser DETECTADA ────────────────────────
        section("4) CORRUPCIÓN — archivo plantado, debe ser detectado")
        bad_path = tmpdir / "space-corrupt.jsonl"
        # id=3 ausente (HUECO), id=4 repetido (DUPLICADO), una línea NO-JSON,
        # y un tipo inexistente (TIPO INVÁLIDO).
        lines = [
            json.dumps({"id": 1, "ts": 1.0, "type": "belt_ready", "space_id": SPACE_ID, "payload": {}}),
            json.dumps({"id": 2, "ts": 2.0, "type": "turn_started", "space_id": SPACE_ID, "payload": {}}),
            # falta el id=3  -> HUECO
            json.dumps({"id": 4, "ts": 4.0, "type": "tool_call_started", "space_id": SPACE_ID, "payload": {}}),
            json.dumps({"id": 4, "ts": 4.1, "type": "tool_call_finished", "space_id": SPACE_ID, "payload": {}}),  # DUPLICADO
            "{ esto no es json válido ]",  # CORRUPCIÓN
            json.dumps({"id": 6, "ts": 6.0, "type": "no_existe_este_tipo", "space_id": SPACE_ID, "payload": {}}),  # TIPO INVÁLIDO
        ]
        bad_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  archivo corrupto plantado: {bad_path.name} ({len(lines)} líneas)")

        bad = verify_integrity(bad_path)
        print("  verify_integrity ->", json.dumps(bad.as_dict(), ensure_ascii=False))

        if not bad.ok:
            _ok("verify_integrity marcó ok=False sobre el archivo corrupto")
        else:
            _fail("verify_integrity NO detectó la corrupción")
            failures += 1
        if 3 in bad.gaps:
            _ok("hueco detectado: falta el id=3")
        else:
            _fail("no detectó el hueco del id=3")
            failures += 1
        if 4 in bad.duplicates:
            _ok("duplicado detectado: id=4 repetido")
        else:
            _fail("no detectó el id=4 duplicado")
            failures += 1
        if bad.corrupt_lines:
            _ok(f"corrupción detectada en línea(s): {bad.corrupt_lines}")
        else:
            _fail("no detectó la línea no-JSON ni el tipo inválido")
            failures += 1

    # ── veredicto BINARIO ──────────────────────────────────────────────────────
    section("VEREDICTO")
    if failures == 0:
        print("  RESULTADO: PASA — la lib corre y el replay es EXACTO.")
        return 0
    print(f"  RESULTADO: FALLA — {failures} aserción(es) rota(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
