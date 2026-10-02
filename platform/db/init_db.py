"""
init_db.py — crea la base lógica `puppet_ai` DENTRO del Postgres existente
y aplica schema.sql. Idempotente: se puede correr varias veces.

Uso:
    python3 platform/db/init_db.py
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
from psycopg2 import sql

from db import DEFAULT_DB, conn_params, es_cliente, get_conn

_SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def ensure_database() -> bool:
    """Crea la base puppet_ai si no existe (conectándose a la base 'postgres').
    Devuelve True si la creó, False si ya existía.

    [Casa 2 · 2.2b] En el cliente NO HAY NADA QUE CREAR: en SQLite la base *es* el
    archivo, y `sqlite3.connect()` lo crea al abrirlo. `CREATE DATABASE` ni existe.
    """
    if es_cliente():
        return False
    params = conn_params(dbname="postgres")
    conn = psycopg2.connect(**params)
    conn.autocommit = True  # CREATE DATABASE no corre dentro de transacción
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (DEFAULT_DB,))
            if cur.fetchone():
                return False
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DEFAULT_DB)))
            return True
    finally:
        conn.close()


def apply_schema() -> None:
    """Aplica el schema del rol: `schema.sql` (Postgres) o `schema_sqlite.sql` (cliente).

    [Casa 2 · 2.2b] No es el mismo archivo ni el mismo subset: el del cliente tiene 20
    tablas (las de `role.tablas_del_cliente()`) y ninguna de plata. Ver el paso 2.1.
    """
    if es_cliente():
        from sqlite_db import crear_schema
        conn = get_conn()
        try:
            crear_schema(conn)
            conn.commit()
        finally:
            conn.close()
        return
    ddl = _SCHEMA.read_text(encoding="utf-8")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    created = ensure_database()
    print(f"[init_db] base '{DEFAULT_DB}': {'CREADA' if created else 'ya existía'}")
    apply_schema()
    print(f"[init_db] schema aplicado desde {_SCHEMA.name}")


if __name__ == "__main__":
    main()
