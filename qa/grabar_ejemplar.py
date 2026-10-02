#!/usr/bin/env python3
"""grabar_ejemplar.py — GRABA el ejemplar de un tipo, una vez, para que los arneses replayen.

    product/backend/.venv/bin/python qa/grabar_ejemplar.py exa
    product/backend/.venv/bin/python qa/grabar_ejemplar.py freecad --slug freecad

S1 dejó las dos perillas y el formato, pero el `comando_para_regrabar()` devuelve literalmente
«ALEPH_GRABAR=<slug> <el comando que ejercita esa pieza>» — o sea, un hueco. Ese comando no
puede ser cualquiera: la grabación tiene que salir del MISMO camino que produce un veredicto,
si no se graba una cosa y se replaya otra. El camino es `conexiones_verificador.verificar_uno`,
que es el motor que ya mide las 62.

**Esto NO es un arnés y por eso no se llama `verify_…`**: no tiene veredicto, corre CON red y
CON llaves, y se ejecuta a mano cuando una grabación envejece (DECISIÓN 1.C). Los arneses son
los que replayan.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "platform/gates", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("server", help="el nombre de la entidad en el catálogo (exa, freecad, …)")
    ap.add_argument("--slug", default=None,
                    help="carpeta de la grabación; por defecto, el nombre del server")
    a = ap.parse_args()
    slug = a.slug or a.server

    from app.phase1 import conexiones_verificador as CV
    from app.phase1 import repo

    entradas = [(b, s) for b, s in CV._entradas() if s == a.server]
    if not entradas:
        print(f"❌ «{a.server}» no está en el catálogo")
        return 2
    belt, server = entradas[0]
    print(f"══ GRABANDO «{server}» → grabaciones/{slug}/ ══")
    print(f"  belt: {belt}")

    # El dueño del registro, con la misma regla que el barrido: el que TIENE conexiones.
    owner = None
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM conexiones GROUP BY user_id "
                        "ORDER BY COUNT(*) DESC, user_id LIMIT 1")
            r = cur.fetchone()
            owner = r[0] if r else None
    finally:
        conn.close()

    destino = _RAIZ / "platform" / "inspection" / "grabaciones" / slug
    os.environ["ALEPH_GRABAR"] = slug
    try:
        fila = CV.verificar_uno(belt, server, owner=owner, get_conn=repo.get_conn)
    finally:
        os.environ.pop("ALEPH_GRABAR", None)

    con = fila.get("conexion") or {}
    print(f"  arranca={fila['arranca']} · conexion={con.get('estado')} "
          f"· causa={con.get('causa')} · credencial={(fila.get('credencial') or {}).get('estado')}")
    if con.get("evidencia"):
        print(f"  evidencia: {str(con['evidencia'])[:200]}")

    hechos = sorted(p.name for p in destino.glob("*.json")) if destino.is_dir() else []
    print(f"  archivos: {hechos or 'NINGUNO'}")
    if not hechos:
        print("  ⚠️ sin archivos: la pieza no llegó a hablar por el transporte. "
              "Un arnés sobre esto sería un verde falso — declaralo PENDIENTE.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
