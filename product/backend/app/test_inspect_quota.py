"""Synthetic cross-process quota adversaries; only temporary databases are touched."""
from __future__ import annotations

import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "platform" / "db"))

from app.phase1 import inspect_quota
import sqlite_db


def _race_worker(path: str, ready, start, results) -> None:
    ready.put(1)
    if not start.wait(10):
        results.put("timeout")
        return
    try:
        lease = inspect_quota.reserve("same-owner", 2, 2, 120,
                                    connect=lambda: sqlite_db.conectar(path))
        results.put(lease)
    except inspect_quota.CapacityFull:
        results.put("full")
    except Exception as exc:
        results.put(f"error:{type(exc).__name__}")


class InspectQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aleph-inspect-quota-")
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "quota.db")
        sqlite_db.asegurar_schema(self.path)
        self.connect = lambda: sqlite_db.conectar(self.path)

    def test_legitimate_release_and_limits(self):
        one = inspect_quota.reserve("a", 1, 2, 120, connect=self.connect)
        two = inspect_quota.reserve("b", 1, 2, 120, connect=self.connect)
        with self.assertRaises(inspect_quota.CapacityFull):
            inspect_quota.reserve("a", 1, 2, 120, connect=self.connect)
        with self.assertRaises(inspect_quota.CapacityFull):
            inspect_quota.reserve("c", 1, 2, 120, connect=self.connect)
        self.assertTrue(inspect_quota.mark_running(one, 1234, connect=self.connect))
        self.assertFalse(inspect_quota.mark_running(one, 1234, connect=self.connect))
        self.assertTrue(inspect_quota.release(one, connect=self.connect))
        self.assertFalse(inspect_quota.release(one, connect=self.connect))
        three = inspect_quota.reserve("a", 1, 2, 120, connect=self.connect)
        inspect_quota.release(two, connect=self.connect)
        inspect_quota.release(three, connect=self.connect)
        conn = self.connect()
        try:
            self.assertEqual(conn.raw.execute("SELECT status FROM inspect_leases WHERE id = ?", (one,)).fetchone()[0],
                             "finished")
        finally:
            conn.close()

    def test_concurrent_processes_cannot_exceed_capacity(self):
        ctx = multiprocessing.get_context("spawn")
        ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
        workers = [ctx.Process(target=_race_worker, args=(self.path, ready, start, results))
                   for _ in range(6)]
        for worker in workers:
            worker.start()
        for _ in workers:
            ready.get(timeout=15)
        start.set()
        responses = [results.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(responses.count("full"), 4, responses)
        leases = [r for r in responses if r != "full"]
        self.assertEqual(len(leases), 2, responses)
        for lease in leases:
            inspect_quota.release(lease, connect=self.connect)

    def test_missing_schema_fails_closed(self):
        bare = str(Path(self.temp.name) / "bare.db")
        with self.assertRaises(Exception):
            inspect_quota.reserve("a", 1, 1, 120,
                                  connect=lambda: sqlite_db.conectar(bare))

    def test_existing_v9_database_gains_durable_states(self):
        conn = self.connect()
        try:
            conn.raw.execute("DROP TABLE inspect_leases")
            conn.raw.execute("CREATE TABLE inspect_leases (id TEXT PRIMARY KEY, "
                             "owner_id TEXT NOT NULL, expires_at INTEGER NOT NULL)")
            conn.raw.execute("PRAGMA user_version = 9")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(sqlite_db.asegurar_schema(self.path)["version"], 10)
        lease = inspect_quota.reserve("migrated", 1, 1, 120, connect=self.connect)
        self.assertTrue(inspect_quota.mark_running(lease, 9876, connect=self.connect))
        self.assertTrue(inspect_quota.release(lease, status="cancelled", connect=self.connect))
        conn = self.connect()
        try:
            self.assertEqual(tuple(conn.raw.execute("SELECT status, pid FROM inspect_leases WHERE id = ?",
                                                    (lease,)).fetchone()), ("cancelled", 9876))
        finally:
            conn.close()

    def test_expiry_recovered_and_unexpired_not_reaped(self):
        one = inspect_quota.reserve("a", 1, 1, 120, connect=self.connect)
        with self.assertRaises(inspect_quota.CapacityFull):
            inspect_quota.reserve("b", 1, 1, 120, connect=self.connect)
        conn = self.connect()
        try:
            conn.raw.execute("UPDATE inspect_leases SET expires_at = 0 WHERE id = ?", (one,))
            conn.commit()
        finally:
            conn.close()
        two = inspect_quota.reserve("b", 1, 1, 120, connect=self.connect)
        self.assertFalse(inspect_quota.renew(one, 120, connect=self.connect))
        conn = self.connect()
        try:
            self.assertEqual(conn.raw.execute("SELECT status FROM inspect_leases WHERE id = ?", (one,)).fetchone()[0],
                             "failed")
        finally:
            conn.close()
        self.assertTrue(inspect_quota.renew(two, 120, connect=self.connect))
        inspect_quota.release(two, connect=self.connect)


if __name__ == "__main__":
    unittest.main()
