#!/usr/bin/env python3
"""test_explicit_memory_db.py — Pieza 1 · la CAPTURA EXPLÍCITA es DETERMINISTA contra la DB real.

Llave B (forense, DB VIVA): prueba el seam completo del executor (detect_capture → add_memory
source='user' pinned → enforce_memory_caps) contra Postgres real, sobre un puppet DESECHABLE que
se borra al final (FK ON DELETE CASCADE limpia sus memorias). Prueba el contraste con el 17%:
6 pedidos "recordá esto: X_i" → 6/6 persistidos (vs ~1/6 del destilador probabilístico), todos
source='user', recuperables (pinned), y RETENIDOS por encima de lo destilado cuando el cap aprieta.

Skippea limpio (exit 0) si no hay Postgres — como el resto de los e2e de la campaña.
Corre:  PYTHONPATH=<wt>/product/backend python3 .../test_explicit_memory_db.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1.explicit_memory import detect_capture, detect_forget, detect_correction


def _load_env():
    envp = _REPO / "infra" / ".env"
    if envp.exists():
        for ln in envp.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"'))


def _run() -> int:
    _load_env()
    try:
        from app.phase1 import repo
        conn = repo.get_conn()
    except Exception as e:
        print(f"  [SKIP] sin Postgres ({type(e).__name__}) — el seam se prueba con test_explicit_memory.py")
        return 0

    NONCE = os.urandom(4).hex()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users LIMIT 1")
        row = cur.fetchone()
    if not row:
        print("  [SKIP] no hay usuarios en la DB")
        return 0
    owner = str(row[0])

    pid = repo.create_puppet(conn, owner_id=owner, name=f"TEST-piece1-{NONCE}",
                             nicho="cowork", config={"schema_version": "v1"})["id"]
    ok = 0; total = 0
    def check(label, cond):
        nonlocal ok, total
        total += 1; ok += bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    try:
        # ── 1) DETERMINISMO 6/6 (el contraste con el 17% del destilador) ──
        sentinels = [f"CENTINELA-{NONCE}-{i}" for i in range(6)]
        captured_all = True
        for s in sentinels:
            cap = detect_capture(f"Che, recordá esto: el código del caso es {s}")
            if cap != f"el código del caso es {s}":
                captured_all = False
                break
            repo.add_memory(conn, puppet_id=pid, content=cap, source="user",
                            pinned=True, meta={"explicit": True})
        check("6/6 pedidos explícitos → detectados+persistidos (vs ~1/6 del destilador)", captured_all)

        mems = repo.list_memories(conn, pid, pinned_only=True)
        user_contents = [m["content"] for m in mems if m["source"] == "user"]
        check("los 6 centinelas están en la memoria pineada (recall-ready)",
              all(any(s in c for c in user_contents) for s in sentinels))
        check("TODOS con source='user' (no 'agent'/destilado)",
              all(m["source"] == "user" for m in mems) and len(user_contents) == 6)

        # ── 1b) [ticket 24] BURIED-IN-CONTEXT: "recordá esto" ENTERRADO → source='user' VERBATIM ──
        # Antes del fix el detector era forward-only: el hecho que va ANTES del "recordá esto" (deixis
        # anafórica) daba detect=None → el hecho caía al DESTILADOR → source='agent' (se perdía la
        # doble-llave "vos me pediste recordar esto"). Ahora la captura anafórica lo aísla.
        buried = ("estuvimos toda la mañana con los grilletes. "
                  f"el grillete GY-24-004-{NONCE} quedó en cuarentena por óxido, no usarlo hasta nueva inspección. "
                  "recordá esto.")
        cap_b = detect_capture(buried)
        check("[24] anafórico enterrado detectado (no None → NO cae al destilador)", cap_b is not None)
        check("[24] aísla el HECHO verbatim, no el contexto conversacional de alrededor",
              cap_b is not None and f"GY-24-004-{NONCE}" in cap_b and "cuarentena" in cap_b
              and "toda la mañana" not in cap_b)
        if cap_b:
            repo.add_memory(conn, puppet_id=pid, content=cap_b, source="user",
                            pinned=True, meta={"explicit": True})
        row_b = [m for m in repo.list_memories(conn, pid, pinned_only=True)
                 if m["source"] == "user" and f"GY-24-004-{NONCE}" in (m.get("content") or "")]
        check("[24] Llave B DB: el hecho enterrado quedó con source='user' (NO 'agent')",
              len(row_b) == 1 and row_b[0]["source"] == "user")
        for m in row_b:
            repo.delete_memory(conn, m["id"])   # limpiar → las secciones de conteo siguen sobre los 6 base

        # ── 2) NEGATIVO: un pedido de RECALL no escribe nada ──
        before = repo.memory_usage(conn, pid)["entries"]
        neg = detect_capture(f"recordame el código del caso {NONCE}")
        check("un pedido de recall ('recordame …') NO captura (detect=None)", neg is None)
        # (no add_memory porque neg is None — el executor sólo escribe si detect≠None)
        after_neg = repo.memory_usage(conn, pid)["entries"]
        check("recall no agregó ninguna entrada", before == after_neg)

        # ── 3) RETENCIÓN: lo explícito (user) sobrevive al desalojo por encima de lo destilado ──
        for i in range(4):
            repo.add_memory(conn, puppet_id=pid, content=f"ruido-destilado-{NONCE}-{i}",
                            source="agent", pinned=True, meta={"run_id": "x"})
        # 6 user + 4 agent = 10 entradas; cap=6 → evicta las 4 'agent' (user se retiene primero)
        evicted = repo.enforce_memory_caps(conn, pid, max_entries=6, max_bytes=50_000_000)
        surv = repo.list_memories(conn, pid)
        surv_user = [m for m in surv if m["source"] == "user"]
        surv_agent = [m for m in surv if m["source"] == "agent"]
        check("cap apretado desalojó 4 (las destiladas)", evicted == 4)
        check("los 6 captures explícitos (user) SOBREVIVEN el desalojo", len(surv_user) == 6)
        check("las destiladas (agent) se evictan PRIMERO (0 sobreviven)", len(surv_agent) == 0)

        # ══════════════ PIEZA 2 · OLVIDO / CORRECCIÓN contra la DB real ══════════════
        # helper que replica el dispatch del executor (detect → repo ops) para probar el seam.
        CEIL = {"max_entries": 100, "max_bytes": 50_000_000}
        def _apply_forget(prompt):
            f = detect_forget(prompt)
            if not f: return None
            if f["mode"] == "all":
                return {"mode": "all", "count": repo.clear_memories(conn, pid)}
            tgt = f["target"].lower()
            allm = repo.list_memories(conn, pid)
            hits = [m for m in allm if tgt in (m.get("content") or "").lower()]
            if hits and not (len(hits) == len(allm) and len(allm) > 1):
                for m in hits: repo.delete_memory(conn, m["id"])
                return {"mode": "match", "deleted": len(hits)}
            elif hits:
                return {"mode": "skipped_generic", "would_match": len(hits)}
            return {"mode": "match", "deleted": 0}
        def _apply_correction(prompt):
            c = detect_correction(prompt)
            if not c: return None
            repo.add_memory(conn, puppet_id=pid, content=c["new"], source="user",
                            pinned=True, meta={"explicit": True, "correction": True})
            forgot = False
            if c.get("old"):
                o, nl = c["old"].lower(), c["new"].lower()
                for m in repo.list_memories(conn, pid):
                    cc = (m.get("content") or "").lower()
                    if o in cc and nl not in cc:
                        repo.delete_memory(conn, m["id"]); forgot = True
            return {"new": c["new"], "forgot_old": forgot}

        # limpiar y sembrar 3 hechos distintos
        repo.clear_memories(conn, pid)
        for c in ["el deadline es el 15 de mayo", "el cliente es Nordvik", "mi color favorito es violeta"]:
            repo.add_memory(conn, puppet_id=pid, content=c, source="user", pinned=True)
        # (1) OLVIDO CON BLANCO: 'olvidá lo del deadline' borra SÓLO esa
        r = _apply_forget("olvidá lo del deadline")
        rem = [m["content"] for m in repo.list_memories(conn, pid)]
        check("olvido-con-blanco borró SÓLO la del deadline (1 borrada, 2 quedan)",
              r and r.get("deleted") == 1 and len(rem) == 2
              and not any("deadline" in c for c in rem) and any("Nordvik" in c for c in rem))

        # (2) CAP anti-barrido: blanco genérico que matchea TODO → NO borra
        repo.clear_memories(conn, pid)
        for c in ["proyecto Fin del Mundo fase 1", "proyecto Fin del Mundo fase 2", "proyecto Fin del Mundo fase 3"]:
            repo.add_memory(conn, puppet_id=pid, content=c, source="user", pinned=True)
        r = _apply_forget("olvidá lo del proyecto")
        surv = repo.list_memories(conn, pid)
        check("CAP anti-barrido: blanco que matchea TODO → NO borra (las 3 sobreviven)",
              r and r.get("mode") == "skipped_generic" and len(surv) == 3)

        # (3) OLVIDO TOTAL explícito: 'olvidá todo' limpia
        r = _apply_forget("olvidá todo")
        check("olvido-total ('olvidá todo') limpió la memoria", len(repo.list_memories(conn, pid)) == 0)

        # (4) CORRECCIÓN: agrega el nuevo hecho y OLVIDA el viejo contradicho
        repo.add_memory(conn, puppet_id=pid, content="el cliente es Nordvik", source="user", pinned=True)
        r = _apply_correction("corregí: el cliente es Vestas, no Nordvik")
        cur_contents = [m["content"] for m in repo.list_memories(conn, pid)]
        check("corrección agregó el hecho nuevo (Vestas) y borró el viejo (Nordvik)",
              r and r.get("forgot_old") is True
              and any("Vestas" in c for c in cur_contents)
              and not any("Nordvik" in c for c in cur_contents))

        # (5) CORRECCIÓN sin 'no <viejo>': sólo agrega, no borra nada
        before = repo.memory_usage(conn, pid)["entries"]
        r = _apply_correction("corrección: el deadline ahora es el 20 de mayo")
        after = repo.memory_usage(conn, pid)["entries"]
        check("corrección sin 'no <viejo>' sólo AGREGA (no borra)",
              r and r.get("forgot_old") is False and after == before + 1)

    finally:
        # limpieza: borrar el puppet desechable → CASCADE borra sus memorias
        with conn.cursor() as cur:
            cur.execute("DELETE FROM puppets WHERE id = %s", (pid,))
        conn.commit()
        print(f"  (limpieza: puppet de prueba {pid[:8]}… borrado, memorias en cascada)")

    print(f"\n  {ok}/{total} verdes")
    return 0 if ok == total else 1


def test_explicit_capture_deterministic_against_db():
    assert _run() == 0


if __name__ == "__main__":
    raise SystemExit(_run())
