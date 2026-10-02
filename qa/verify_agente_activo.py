#!/usr/bin/env python3
"""verify_agente_activo.py — QUE «LISTO» Y «BORRADOR» DIGAN ALGO. [rediseño · fase 2 · 2.2]

EL DEFECTO Nº12, CON NÚMERO
───────────────────────────
El mecanismo del estado de un agente estaba ENTERO y sin un solo llamante:

    schema.sql        puppets.status TEXT NOT NULL DEFAULT 'draft'  -- draft|active|archived
    repo.list_puppets filtra por status
    GET /v1/users/{id}/puppets  acepta ?status=
    repo.set_status   definida, exportada… y con CERO llamantes en todo el árbol

Contra la `aleph.db` real: **1.625 de 1.625 en `draft`**. Dibujar el filtro
«Todos / Listos / Borradores» sobre eso habría dado Listos = 0 para siempre. El botón se
veía perfecto y no hacía nada.

LA REGLA LA ELIGIÓ EL DUEÑO (2026-09-07), entre tres medidas contra la DB real:
    usado al menos una vez (≥1 run o chat) → 877 listos / 748 borradores   ← ÉSTA
    su receta tiene herramientas           → 1.284 / 341
    un botón explícito de publicar         → 0 / 1.625

QUÉ MIDE ESTA VARA
──────────────────
Contra una COPIA de la `aleph.db` REAL, no contra un fixture: un fixture con dos filas
inventadas no puede decir si la regla produce números creíbles sobre el historial de verdad.

  1. `marcar_usado` promueve draft→active
  2. …y es IDEMPOTENTE (la segunda llamada no escribe)
  3. …y **jamás resucita un `archived`** — el motivo de que no sea un `set_status` pelado
  4. `backfill_usados` promueve exactamente a los que tienen huella (runs ∪ chats)
  5. …y es idempotente
  6. `list_puppets` ordena por ÚLTIMO USO, con los nunca usados al final
  7. `create_run` llama a `marcar_usado` — el cable, no sólo la función

PROBADA CAYENDO
───────────────
    python3 qa/verify_agente_activo.py --mutante
parchea `repo.marcar_usado` a un no-op y exige que caigan las afirmaciones de estado.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for p in (RAIZ / "platform", RAIZ / "product" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REAL = Path.home() / "Library" / "Application Support" / "Aleph" / "aleph.db"
MUT = "--mutante" in sys.argv
fallos: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        fallos.append(msg)


def main() -> int:
    if not REAL.is_file():
        print(f"✗ no está la aleph.db real ({REAL}). Esta vara mide contra el historial de")
        print("  verdad a propósito: sin ella NO se puede afirmar nada, y eso es rojo, no verde.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="vara-activo-"))
    shutil.copy2(REAL, tmp / "aleph.db")
    for extra in ("aleph.db-wal", "aleph.db-shm"):
        if (REAL.parent / extra).exists():
            shutil.copy2(REAL.parent / extra, tmp / extra)
    os.environ["ALEPH_DATA_DIR"] = str(tmp)

    from app.phase1 import repo

    if MUT:
        # LOS DOS CABLES, cortados. Cortar sólo `marcar_usado` dejaba la vara en verde porque
        # la afirmación grande —la separación sobre todo el historial— la produce el backfill.
        # Una mutación que no toca lo que la vara afirma no prueba nada: probé eso y salió
        # «✓ 11 verdes» con el cable cortado, que es exactamente la vara que no quiero.
        repo.marcar_usado = lambda conn, pid: False
        repo.backfill_usados = lambda conn, owner: 0

    conn = repo.get_conn()
    cur = conn.cursor()

    def uno(sql, args=()):
        cur.execute(sql, args)
        r = cur.fetchone()
        return r[0] if r else None

    # EL DUEÑO CON MÁS HUELLA, no el que más agentes tiene. La primera versión de esta vara
    # elegía por cantidad de puppets y cayó: el dueño con más agentes (190) tiene CERO runs.
    # Los 877 con huella están repartidos entre varios dueños, y medir la separación del
    # filtro sobre uno sin huella sólo puede dar «0 listos» — un rojo que no es del cable.
    dueno = uno(
        "SELECT owner_id FROM puppets WHERE id IN ("
        "  SELECT puppet_id FROM runs  WHERE puppet_id IS NOT NULL UNION "
        "  SELECT puppet_id FROM chats WHERE puppet_id IS NOT NULL) "
        "GROUP BY owner_id ORDER BY COUNT(*) DESC LIMIT 1")
    total = uno("SELECT COUNT(*) FROM puppets WHERE owner_id = %s", (dueno,))
    con_huella = uno(
        "SELECT COUNT(*) FROM puppets WHERE owner_id = %s AND id IN ("
        "  SELECT puppet_id FROM runs  WHERE puppet_id IS NOT NULL UNION "
        "  SELECT puppet_id FROM chats WHERE puppet_id IS NOT NULL)", (dueno,))
    print(f"── contra una copia de la aleph.db REAL · dueño con {total} agentes, {con_huella} con huella ──")

    # 1-3 · marcar_usado
    victima = uno("SELECT id FROM puppets WHERE owner_id = %s AND status = 'draft' LIMIT 1", (dueno,))
    if victima is None:
        ok(False, "hace falta al menos un agente en 'draft' para medir la promoción")
    else:
        ok(repo.marcar_usado(conn, victima) is True or MUT, "marcar_usado promueve draft → active")
        ok(uno("SELECT status FROM puppets WHERE id = %s", (victima,)) == ("draft" if MUT else "active"),
           "…y queda escrito en la fila" if not MUT else "…(mutante: sigue en draft, como debe)")
        ok(repo.marcar_usado(conn, victima) is False, "…y es idempotente: la segunda vez no escribe")

    arch = uno("SELECT id FROM puppets WHERE owner_id = %s LIMIT 1", (dueno,))
    cur.execute("UPDATE puppets SET status = 'archived' WHERE id = %s", (arch,))
    conn.commit()
    repo.marcar_usado(conn, arch)
    ok(uno("SELECT status FROM puppets WHERE id = %s", (arch,)) == "archived",
       "JAMÁS resucita un 'archived' (por eso no es un set_status pelado)")

    # 4-5 · backfill
    cur.execute("UPDATE puppets SET status = 'draft' WHERE owner_id = %s", (dueno,))
    conn.commit()
    n1 = repo.backfill_usados(conn, dueno)
    activos = uno("SELECT COUNT(*) FROM puppets WHERE owner_id = %s AND status = 'active'", (dueno,))
    ok(n1 == con_huella and activos == con_huella,
       f"backfill_usados promueve exactamente los que tienen huella ({n1} escritos, {activos} activos, {con_huella} esperados)")
    ok(repo.backfill_usados(conn, dueno) == 0, "…y es idempotente: la segunda corrida escribe 0")

    # LA SEPARACIÓN SE MIDE GLOBAL, NO POR DUEÑO — y esto lo aprendí cayendo dos veces.
    # El dueño con más agentes (190) tiene CERO huella ⇒ 0 listos. El dueño con más huella
    # (41) los tiene TODOS usados ⇒ 0 borradores. Ninguno de los dos prueba que el filtro
    # separa: la afirmación es sobre el historial ENTERO, que es lo que ve el usuario.
    cur.execute("UPDATE puppets SET status = 'draft'")
    conn.commit()
    esperado = uno(
        "SELECT COUNT(*) FROM puppets WHERE id IN ("
        "  SELECT puppet_id FROM runs  WHERE puppet_id IS NOT NULL UNION "
        "  SELECT puppet_id FROM chats WHERE puppet_id IS NOT NULL)")
    cur.execute("SELECT DISTINCT owner_id FROM puppets")
    for (o,) in list(cur.fetchall()):
        repo.backfill_usados(conn, o)
    g_act = uno("SELECT COUNT(*) FROM puppets WHERE status = 'active'")
    g_bor = uno("SELECT COUNT(*) FROM puppets WHERE status = 'draft'")
    g_tot = uno("SELECT COUNT(*) FROM puppets")
    ok(g_act == esperado and g_act > 0 and g_bor > 0,
       f"el filtro SEPARA de verdad sobre TODO el historial: {g_act} listos · {g_bor} borradores "
       f"de {g_tot} (antes del cable: 0 y {g_tot})")

    # 6 · el orden
    filas = repo.list_puppets(conn, dueno)
    usados = [f.get("usado_at") for f in filas]
    ok("usado_at" in (filas[0] if filas else {}), "list_puppets devuelve `usado_at` para que la cara pueda decirlo")
    con = [u for u in usados if u]
    sin_pos = [i for i, u in enumerate(usados) if not u]
    ok(con == sorted(con, reverse=True), "los usados vienen del más reciente al más viejo")
    ok(not sin_pos or min(sin_pos) >= len(con), "los NUNCA usados quedan al final, no desaparecen")

    # 7 · el cable
    fuente = (RAIZ / "product/backend/app/phase1/repo.py").read_text()
    import re
    m = re.search(r"def create_run\(.*?\n(?=def )", fuente, re.S)
    ok(bool(m) and "marcar_usado(conn, puppet_id)" in m.group(0),
       "create_run —el choke point— llama a marcar_usado")

    print("")
    if MUT:
        if not fallos:
            print("✗ LA VARA ESTÁ ROTA: con marcar_usado cortada no cayó ninguna afirmación.")
            return 1
        print(f"✓ la vara puede dar rojo: {len(fallos)} afirmaciones cayeron con el cable cortado.")
        return 0
    if fallos:
        print(f"✗ {len(fallos)} rojas")
        return 1
    print("✓ el estado del agente se escribe, no se resucita, y el orden es por uso")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
