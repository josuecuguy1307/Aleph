#!/usr/bin/env python3
"""verify_onshape_lectura_real.py — LA LECTURA REAL contra la cuenta de Onshape.

Pendiente 3 de `ESTADO-ONSHAPE.md`. Todo lo demás de onshape está medido contra un IdP
local; esto es lo único que toca la cuenta de verdad, y por eso **no corre solo**: exige un
token que sólo existe después de que **persona usuaria** dé el consentimiento OAuth en un navegador.
Un robot no puede hacer ese paso sin fingir ser él, así que este archivo queda ARMADO y se
dispara cuando él esté presente.

    # 1) persona usuaria conecta Onshape desde la card (o POST /v1/connectors/onshape/oauth/start)
    # 2) recién entonces:
    python3 qa/verify_onshape_lectura_real.py

SÓLO LECTURAS, y el candado es de este archivo, no una promesa:

  · la lista blanca `_LECTURAS` tiene DOS nombres y se compara por igualdad exacta;
  · antes de llamar, se verifica contra `_meta.action_classes` del belt que la tool esté
    declarada `read` — si el belt cambiara la clase de una de las dos, esto aborta;
  · si `tools/list` publica una tool de escritura (porque el grant la incluía), se REPORTA
    y no se toca. Las cuatro peligrosas frenan igual en B4 por diseño; acá ni se rozan.

EL CAMINO ES EL DE PRODUCCIÓN. El server no se levanta con un `Popen` de este archivo: se
pide con `recipe_assembler._servidor_stdio(user_id)`, el mismo helper que usa el run. Así
esta vara mide lo que el usuario va a correr —dueño cuando `ALEPH_DUENO=on`, puente al SDK
si no— en vez de un camino paralelo que sólo existe acá. Es también la razón de que no
aparezca en `test_frontera_dueno.py`: no spawnea nada por su cuenta.

Salida: exit 0 con la identidad y el conteo de documentos; exit 2 si falta el
consentimiento (no es un fallo del código, es un paso humano que no ocurrió); exit 1 si
Onshape rechazó o el belt no respondió.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "platform" / "assembler"))
sys.path.insert(0, str(ROOT / "product" / "backend"))

PROVEEDOR = "onshape"
BELT = ROOT / "catalog" / "templates" / "ingenieria" / "belt-onshape.mcp.json"

#: Las ÚNICAS dos que este archivo puede nombrar. No es un filtro por prefijo ni por
#: heurística de nombre: son dos strings, y se comparan por igualdad.
_LECTURAS = ("onshape_whoami", "onshape_list_documents")


def _falta_consentimiento(motivo: str) -> None:
    print(f"\n⏸  LECTURA REAL NO DISPARADA — {motivo}")
    print("   Es el pendiente 2 de ESTADO-ONSHAPE.md y es de persona usuaria: hace falta que")
    print("   conecte Onshape en un navegador. El código está listo; no hay nada que")
    print("   arreglar acá. Cuando el token exista, este mismo comando corre solo.")
    sys.exit(2)


def _vault_path() -> Path:
    return (Path.home() / "Library" / "Application Support" / "Aleph" / "aleph.db")


def _conectar():
    """La conexión ENVUELTA de producción — jamás `sqlite3.connect()` a secas.

    ⚠️ ACÁ ESTUVO EL BUG, y la lección vale más que el arreglo. Esta vara abría el vault
    con `sqlite3.connect()` crudo y se lo pasaba a `repo.get_key`, que revienta con

        TypeError: 'sqlite3.Cursor' object does not support the context manager protocol

    Es fácil leer eso como «repo.py tiene un bug de Postgres-vs-SQLite», y NO lo es:
    `with conn.cursor() as cur` es la convención de TODO el backend (~290 usos, 90 sólo en
    `repo.py`) y el wrapper de `platform/db/sqlite_db.py` es quien aporta `__enter__`/
    `__exit__` y traduce los `%s`. Si el patrón estuviera roto no arrancaría nada.

    O sea: el contrato de `repo.py` es «recibí una conexión envuelta». Una vara que abre la
    DB por su cuenta se sale de ese contrato y produce un error que ACUSA al código de
    producción. Por eso esto pasa por `sqlite_db.conectar()`: para medir el camino real.
    """
    db = _vault_path()
    if not db.exists():
        _falta_consentimiento(f"no existe el vault ({db})")
    # ⚠️ NO `from db import sqlite_db`, y el motivo lo destapó S3 al absorber este archivo
    # como CASO de `verify_oauth.py`. Ese import asume que `db` resuelve al PAQUETE
    # `platform/db/`; pero `platform/db` está en el sys.path de producción, así que en cuanto
    # ALGUIEN importó `db.py` como módulo top-level —y el arnés lo hace, porque corre el CASO
    # A antes— `db` ya está en `sys.modules` como MÓDULO y el import muere con
    # `cannot import name 'sqlite_db' from 'db'`. Corriendo solo nunca se veía.
    # `db._sqlite()` es el cargador perezoso de producción (`platform/db/db.py:87`), que
    # justamente no asume el sys.path. Camino real, y además el que no se rompe.
    import db as _db
    return _db._sqlite().conectar(str(db))


def _credenciales() -> tuple[str, str, dict]:
    """(user_id, access_token, companion) del dueño de la credencial de Onshape.

    Lee por el broker real —así el refresh server-side entra en juego igual que en un run—
    y NO imprime jamás el token: sólo su longitud.
    """
    from app.phase1 import credential_broker, repo
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM keys WHERE provider = %s LIMIT 1", (PROVEEDOR,))
            filas = cur.fetchall()
        if not filas:
            _falta_consentimiento("no hay ninguna credencial de Onshape en el vault")
        user_id = str(filas[0][0])

        token = repo.get_key(conn, user_id, PROVEEDOR) or ""
        # El MISMO camino del runtime: si venció, refresca ahora y re-persiste.
        token = credential_broker._maybe_refresh_oauth(conn, user_id, PROVEEDOR, token)
        try:
            companion = json.loads(repo.get_key(conn, user_id, f"{PROVEEDOR}__oauth") or "{}")
        except (TypeError, json.JSONDecodeError):
            companion = {}
    finally:
        conn.close()

    if not token:
        estado = companion.get("state") or "desconocido"
        _falta_consentimiento(f"el vault tiene la fila pero el token está vacío (state={estado})")
    return user_id, token, companion


def _clases_declaradas() -> dict:
    belt = json.loads(BELT.read_text(encoding="utf-8"))
    return (belt.get("_meta", {}).get("action_classes", {}).get("onshape", {}))


def main() -> int:
    print("══ ONSHAPE · LECTURA REAL (sólo lecturas) ══\n")

    clases = _clases_declaradas()
    for tool in _LECTURAS:
        declarada = clases.get(tool)
        if declarada != "read":
            print(f"✗ ABORTADO: el belt declara `{tool}` como «{declarada}», no «read».")
            print("  Esta vara sólo puede ejecutar lecturas declaradas. Si la clase cambió")
            print("  a propósito, hay que decidirlo a la vista, no dejar que este archivo")
            print("  siga llamando algo que ya no es una lectura.")
            return 1
    print(f"✓ las dos tools están declaradas `read` en el belt")

    user_id, token, companion = _credenciales()
    granted = companion.get("granted_scopes") or []
    print(f"✓ credencial encontrada · user_id={user_id[:8]}… · token de {len(token)} chars")
    print(f"  scopes concedidos: {granted or '(el proveedor no informó — superficie cerrada)'}")

    # ── el server, por el camino de PRODUCCIÓN ────────────────────────────────────
    import recipe_assembler as RA
    cls = RA._servidor_stdio(user_id)
    print(f"✓ transporte elegido por el producto: {getattr(cls, '__name__', cls)}")

    belt = json.loads(BELT.read_text(encoding="utf-8"))
    cfg = belt["mcpServers"]["onshape"]
    env = dict(os.environ)
    env.update({
        "ONSHAPE_ACCESS_TOKEN": token,
        "ONSHAPE_OAUTH_META": json.dumps({
            "state": companion.get("state") or "connected",
            "granted_scopes": granted,
        }),
        "ONSHAPE_API_BASE": cfg["env"]["ONSHAPE_API_BASE"],
    })
    args = [a.replace("${PUPPET_BELTS}", str(ROOT / "product" / "belts")) for a in cfg["args"]]

    srv = cls("onshape", cfg["command"], args, env=env)
    fallo = 0
    try:
        srv.start()
        publicadas = [t.get("name") for t in (srv.list_tools() or [])]
        print(f"✓ tools/list publicó: {publicadas}")

        escrituras = [t for t in publicadas if t not in _LECTURAS]
        if escrituras:
            print(f"  ⚠️  el grant incluye {escrituras} — NO se tocan desde acá (frenan en B4)")

        for tool in _LECTURAS:
            if tool not in publicadas:
                print(f"  ·  {tool}: no publicada (su scope no fue concedido) — se omite")
                continue
            args_tool = {"limit": 5} if tool == "onshape_list_documents" else {}
            crudo = srv.call_tool(tool, args_tool)
            texto = crudo
            if isinstance(crudo, dict):
                partes = crudo.get("content") or []
                if partes and isinstance(partes[0], dict):
                    texto = partes[0].get("text", "")
            try:
                res = json.loads(texto) if isinstance(texto, str) else texto
            except json.JSONDecodeError:
                res = {"ok": False, "detail": str(texto)[:200]}

            if not (isinstance(res, dict) and res.get("ok")):
                print(f"✗ {tool} falló: {res}")
                fallo = 1
                continue
            if tool == "onshape_whoami":
                print(f"✓ onshape_whoami → id={res.get('id')} · name={res.get('name')}")
            else:
                docs = res.get("documents") or []
                print(f"✓ onshape_list_documents → {res.get('count')} documento(s)")
                for d in docs[:5]:
                    print(f"    · {d.get('name')}  ({d.get('id')})")
    finally:
        try:
            srv.stop()
        except Exception:                                    # noqa: BLE001
            pass

    print("\n" + ("══ ✅ LECTURA REAL OK ══" if not fallo else "══ ✗ LA LECTURA REAL FALLÓ ══"))
    return fallo


if __name__ == "__main__":
    sys.exit(main())
