#!/usr/bin/env python3
"""verify_busqueda_tiene_cara.py — ¿LA BÚSQUEDA EN LO PROPIO LLEGA A UNA PANTALLA?

[convergencia · superficie 5 · F.5 y F.6]

⚠️ NO ES LA BÚSQUEDA WEB. Acá se busca en lo del usuario —sus hilos, sus mensajes, sus
artefactos—. El agente saliendo a internet es otra superficie y otro motor.

LO QUE MEDÍA ANTES: el índice interno estaba mergeado y montado (`GET /v1/busqueda`,
`platform/busqueda/indice.py`) y tenía **cero consumidores** en `product/app/design/`. La
Sala buscaba con `/v1/chats/search`, que sólo sabe de mensajes, y aplanaba sus hits a una
lista de hilos; Historial filtraba en memoria los últimos 50 runs. O sea: un artefacto
propio era inencontrable, y una conversación más vieja que los últimos 50 runs también —
sin que ninguna pantalla dijera que no la había buscado.

LAS CUATRO ASERCIONES:
  1. una consulta devuelve los TRES grupos —hilos · mensajes · artefactos— y no uno;
  2. el scope es del DUEÑO: lo de otra cuenta no aparece, ni siquiera buscando su texto
     exacto (y esto no es un filtro que la pantalla agrega: el índice exige el dueño como
     token del match, así que sin él la búsqueda LEVANTA en vez de devolver de más);
  3. La Sala pide `/v1/busqueda` y no `/v1/chats/search`;
  4. Historial también, y sus resultados llegan a lo que la pantalla pinta.

Las dos primeras corren el índice y el endpoint DE VERDAD contra una base nueva en un
temporal. Las dos últimas corren el código de las pantallas con el `fetch` interceptado, o
sea que miden a quién le pide cada una, no lo que su fuente dice.

Probala cayendo:
    ALEPH_VARA_ROMPER=ungrupo   el índice devuelve sólo hilos          → rojo por (1)
    ALEPH_VARA_ROMPER=ajeno     la búsqueda se hace con el dueño ajeno → rojo por (2)
    ALEPH_VARA_ROMPER=viejo     la Sala vuelve a `/v1/chats/search`    → rojo por (3)

    <venv>/bin/python qa/verify_busqueda_tiene_cara.py
      0 → el índice tiene cara · 1 → no · 2 → no se pudo medir (NO cuenta como verde)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "product" / "app" / "design"
ROMPER = (os.environ.get("ALEPH_VARA_ROMPER") or "").strip().lower()


def no_medible(motivo: str):
    print(f"[no medible] {motivo}")
    sys.exit(2)


# ── el aislamiento, antes de importar nada (ver qa/DEUDA-VARAS-QUE-ESCRIBEN…) ─────────
TMP = Path(tempfile.mkdtemp(prefix="vara-busqueda-"))
os.environ["ALEPH_ROLE"] = "client"
os.environ["ALEPH_DATA_DIR"] = str(TMP / "datos")
os.environ["XDG_DATA_HOME"] = str(TMP / "datos")
os.environ["PUPPET_SQLITE_PATH"] = str(TMP / "datos" / "aleph.db")
(TMP / "datos").mkdir(parents=True, exist_ok=True)

for _p in (ROOT / "product" / "backend", ROOT / "platform" / "db", ROOT / "platform"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import sqlite_db                                    # noqa: E402
    from app.phase1 import artifact_store, repo         # noqa: E402
    from busqueda import indice                         # noqa: E402
except Exception as exc:                                # noqa: BLE001
    no_medible(f"no se pudo importar el árbol: {exc}")

if TMP.resolve() not in Path(sqlite_db.ruta_db()).resolve().parents:
    no_medible("el .db resuelto no está en el temporal; no escribo en el real")
if TMP.resolve() not in Path(indice.ruta_indice()).resolve().parents:
    no_medible("el índice resuelto no está en el temporal; no escribo en el real")

DB = str(TMP / "datos" / "aleph.db")
FRASE_MIA = "quetzal ornitorrinco"
FRASE_AJENA = "narval basilisco"


def sembrar(email: str, frase: str) -> str:
    """Un dueño con un hilo, un mensaje y un artefacto, todos con la misma frase rara."""
    sqlite_db.asegurar_schema(DB)
    conn = sqlite_db.conectar(DB)
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", (email,))
            uid = str(cur.fetchone()[0])
            cur.execute("INSERT INTO chats (user_id, title) VALUES (%s,%s) RETURNING id",
                        (uid, f"Hilo de {frase}"))
            cid = str(cur.fetchone()[0])
            cur.execute("INSERT INTO chat_messages (chat_id, role, kind, content) "
                        "VALUES (%s,'user','chat',%s)", (cid, f"un mensaje sobre {frase}"))
        conn.commit()
    finally:
        conn.close()
    sid = "sid-" + uid[:8]
    artifact_store.claim_owner(sid, uid)
    # El bloque de procedencia es OBLIGATORIO al escribir (`_validate_provenance`): un
    # artefacto sin su evidencia no se puede construir. Se pone el mínimo estructural que el
    # almacén exige — no se afloja la validación para que la vara entre.
    artifact_store.create_artifact(
        sid, f"Informe de {frase}", "informe", f"cuerpo con {frase} adentro",
        {"schema": "artifact-provenance/v1", "captured_at": "2026-08-18T00:00:00Z",
         "produced_by": "manual", "capture_quality": "declared", "user_id": uid})
    conn = sqlite_db.conectar(DB)
    try:
        indice.reconstruir(conn, uid)
    finally:
        conn.close()
    return uid


def front_pide(ruta: Path, gancho: str) -> str:
    """A qué URL le pide una pantalla cuando el usuario escribe. Corre su código."""
    sonda = ROOT / "qa" / "lib" / "sonda_busqueda_front.mjs"
    out = subprocess.run(["node", str(sonda), str(ruta), gancho],
                         capture_output=True, text=True, cwd=str(ROOT), timeout=90)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-300:] or "la sonda del front falló")
    return json.loads(out.stdout or "{}").get("url") or ""


def main() -> int:
    try:
        mio = sembrar("mio@local.test", FRASE_MIA)
        ajeno = sembrar("ajeno@local.test", FRASE_AJENA)
    except Exception as exc:                            # noqa: BLE001
        no_medible(f"no se pudo sembrar: {exc}")

    filas = []

    # 1 · los tres grupos
    try:
        r = indice.buscar(mio, FRASE_MIA)
        if ROMPER == "ungrupo":
            r = {**r, "mensajes": [], "artefactos": []}
        vacios = [g for g in ("hilos", "mensajes", "artefactos") if not r.get(g)]
        filas.append(("los tres grupos", not vacios,
                      f"hilos {len(r.get('hilos',[]))} · mensajes {len(r.get('mensajes',[]))} · "
                      f"artefactos {len(r.get('artefactos',[]))}"
                      + (f" — vacíos: {', '.join(vacios)}" if vacios else "")))
    except Exception as exc:                            # noqa: BLE001
        no_medible(f"la búsqueda se rompió: {exc}")

    # 2 · el scope del dueño: buscando la frase del OTRO con MI dueño no puede salir nada.
    #     `ROMPER=ajeno` busca con el dueño ajeno —que SÍ la tiene— así que la fila cae.
    try:
        quien = ajeno if ROMPER == "ajeno" else mio
        fuga = indice.buscar(quien, FRASE_AJENA)
        filas.append(("nada de otra cuenta", fuga["total"] == 0,
                      f"{fuga['total']} resultado(s) buscando «{FRASE_AJENA}»"))
    except Exception as exc:                            # noqa: BLE001
        no_medible(f"el scope no se pudo medir: {exc}")

    # 3 y 4 · las dos caras
    for nombre, ruta, gancho in (
            ("La Sala pide el índice", DESIGN / "sala-v2" / "sala-v2.js", "sala"),
            ("Historial pide el índice", DESIGN / "Historial.dc.html", "historial")):
        try:
            url = front_pide(ruta, gancho)
        except Exception as exc:                        # noqa: BLE001
            no_medible(f"{nombre}: {exc}")
        ok = url.startswith("/v1/busqueda")
        filas.append((nombre, ok, url or "no pidió nada"))

    ancho = max(len(n) for n, _, _ in filas)
    print("¿LA BÚSQUEDA EN LO PROPIO LLEGA A UNA PANTALLA?\n")
    for n, ok, det in filas:
        print(f"  {'✅' if ok else '❌'}  {n.ljust(ancho)}  {det}")
    malas = [n for n, ok, _ in filas if not ok]
    print()
    if malas:
        print(f"ROJO — {', '.join(malas)}")
        return 1
    print("VERDE — tres grupos, scope del dueño, y las dos pantallas la llaman.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                            # noqa: BLE001
        no_medible(f"la vara se rompió: {exc}")
