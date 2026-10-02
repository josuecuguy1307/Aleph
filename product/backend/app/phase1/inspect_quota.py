"""Atomic cross-process admission for inspection work.

The role's existing SQLite/Postgres database is the authority. A missing schema or
database error denies admission; there is deliberately no process-local fallback.
"""
from __future__ import annotations

import uuid
from typing import Callable


class CapacityFull(Exception):
    pass


def reserve(owner: str, per_owner: int, global_max: int, lease_seconds: int,
            *, connect: Callable | None = None) -> str:
    if not owner or min(per_owner, global_max, lease_seconds) < 1:
        raise ValueError("invalid inspection quota")
    if connect is None:
        from app.phase1 import repo
        connect = repo.get_conn
    lease_id = str(uuid.uuid4())
    conn = connect()
    try:
        sqlite = hasattr(conn, "raw")
        if sqlite:
            # One SQLite writer at a time, including across unrelated processes.
            conn.raw.execute("BEGIN IMMEDIATE")
            cur = conn.raw.cursor()
            cur.execute("UPDATE inspect_leases SET status = 'failed', "
                        "finished_at = CAST(strftime('%s','now') AS INTEGER) "
                        "WHERE status IN ('start','running') "
                        "AND expires_at <= CAST(strftime('%s','now') AS INTEGER)")
            cur.execute("DELETE FROM inspect_leases WHERE status NOT IN ('start','running') "
                        "AND finished_at < CAST(strftime('%s','now') AS INTEGER) - 604800")
        else:
            cur = conn.cursor()
            # A common transaction-scoped lock across all web workers/hosts of this DB.
            cur.execute("SELECT pg_advisory_xact_lock(22617, 20260921)")
            cur.execute("UPDATE inspect_leases SET status = 'failed', "
                        "finished_at = EXTRACT(EPOCH FROM clock_timestamp())::bigint "
                        "WHERE status IN ('start','running') "
                        "AND expires_at <= EXTRACT(EPOCH FROM clock_timestamp())::bigint")
            cur.execute("DELETE FROM inspect_leases WHERE status NOT IN ('start','running') "
                        "AND finished_at < EXTRACT(EPOCH FROM clock_timestamp())::bigint - 604800")
        cur.execute("SELECT COUNT(*) FROM inspect_leases WHERE status IN ('start','running')")
        active = cur.fetchone()[0]
        if active >= global_max:
            raise CapacityFull()
        if sqlite:
            cur.execute("SELECT COUNT(*) FROM inspect_leases WHERE owner_id = ? "
                        "AND status IN ('start','running')", (owner,))
        else:
            cur.execute("SELECT COUNT(*) FROM inspect_leases WHERE owner_id = %s "
                        "AND status IN ('start','running')", (owner,))
        if cur.fetchone()[0] >= per_owner:
            raise CapacityFull()
        if sqlite:
            cur.execute("INSERT INTO inspect_leases(id, owner_id, expires_at, status) "
                        "VALUES (?, ?, CAST(strftime('%s','now') AS INTEGER) + ?, 'start')",
                        (lease_id, owner, lease_seconds))
        else:
            cur.execute("INSERT INTO inspect_leases(id, owner_id, expires_at, status) "
                        "VALUES (%s, %s, EXTRACT(EPOCH FROM clock_timestamp())::bigint + %s, 'start')",
                        (lease_id, owner, lease_seconds))
        conn.commit()
        return lease_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_running(lease_id: str, pid: int | None = None, *, connect: Callable | None = None) -> bool:
    if pid is not None and pid <= 0:
        raise ValueError("invalid inspection pid")
    if connect is None:
        from app.phase1 import repo
        connect = repo.get_conn
    conn = connect()
    try:
        if hasattr(conn, "raw"):
            cur = conn.raw.execute("UPDATE inspect_leases SET status = 'running', pid = ? "
                                   "WHERE id = ? AND status = 'start' "
                                   "AND expires_at > CAST(strftime('%s','now') AS INTEGER)",
                                   (pid, lease_id))
        else:
            cur = conn.cursor()
            cur.execute("UPDATE inspect_leases SET status = 'running', pid = %s "
                        "WHERE id = %s AND status = 'start' "
                        "AND expires_at > EXTRACT(EPOCH FROM clock_timestamp())::bigint",
                        (pid, lease_id))
        success = cur.rowcount == 1
        conn.commit()
        return success
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def release(lease_id: str, *, status: str = "finished", connect: Callable | None = None) -> bool:
    if status not in ("finished", "failed", "cancelled"):
        raise ValueError("invalid inspection completion state")
    if connect is None:
        from app.phase1 import repo
        connect = repo.get_conn
    conn = connect()
    try:
        if hasattr(conn, "raw"):
            cur = conn.raw.execute("UPDATE inspect_leases SET status = ?, "
                                   "finished_at = CAST(strftime('%s','now') AS INTEGER) "
                                   "WHERE id = ? AND status IN ('start','running')",
                                   (status, lease_id))
        else:
            cur = conn.cursor()
            cur.execute("UPDATE inspect_leases SET status = %s, "
                        "finished_at = EXTRACT(EPOCH FROM clock_timestamp())::bigint "
                        "WHERE id = %s AND status IN ('start','running')", (status, lease_id))
        changed = cur.rowcount == 1
        conn.commit()
        return changed
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def renew(lease_id: str, lease_seconds: int, *, connect: Callable | None = None) -> bool:
    """Keep a synchronous reservation alive; a dead worker stops renewing it."""
    if lease_seconds < 1:
        raise ValueError("invalid inspection lease")
    if connect is None:
        from app.phase1 import repo
        connect = repo.get_conn
    conn = connect()
    try:
        if hasattr(conn, "raw"):
            cur = conn.raw.execute("UPDATE inspect_leases SET expires_at = "
                                   "CAST(strftime('%s','now') AS INTEGER) + ? "
                                   "WHERE id = ? AND status IN ('start','running') "
                                   "AND expires_at > CAST(strftime('%s','now') AS INTEGER)",
                                   (lease_seconds, lease_id))
        else:
            cur = conn.cursor()
            cur.execute("UPDATE inspect_leases SET expires_at = "
                        "EXTRACT(EPOCH FROM clock_timestamp())::bigint + %s "
                        "WHERE id = %s AND status IN ('start','running') "
                        "AND expires_at > EXTRACT(EPOCH FROM clock_timestamp())::bigint",
                        (lease_seconds, lease_id))
        alive = cur.rowcount == 1
        conn.commit()
        return alive
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
