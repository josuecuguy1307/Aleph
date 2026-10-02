"""Real POSIX group deadline when the web reaper is absent."""
import os
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class InspectWatchdogTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX process groups required")
    def test_web_worker_crash_recovers_durable_capacity_after_kill(self):
        with tempfile.TemporaryDirectory(prefix="aleph-inspect-crash-") as temp:
            database = Path(temp) / "quota.db"
            marker = Path(temp) / "escaped"
            sys.path[:0] = [str(ROOT / "product" / "backend"), str(ROOT / "platform"),
                            str(ROOT / "platform" / "db")]
            import sqlite_db
            from app.phase1 import inspect_quota
            sqlite_db.asegurar_schema(str(database))
            descendant = ("import pathlib,time;time.sleep(7);"
                          f"pathlib.Path({str(marker)!r}).write_text('bad')")
            runner = (
                "import os,subprocess,sys,time; "
                f"sys.path.insert(0,{str(ROOT / 'platform')!r}); "
                "from inspection.inspect_run import _arm_hard_deadline; "
                "_arm_hard_deadline(); "
                f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
                "time.sleep(30)"
            )
            web = (
                "import os,subprocess,sys,json; "
                f"sys.path[:0]={[str(ROOT / 'product' / 'backend'), str(ROOT / 'platform' / 'db')]!r}; "
                "from app.phase1 import inspect_quota; import sqlite_db; "
                f"connect=lambda:sqlite_db.conectar({str(database)!r}); "
                "lease=inspect_quota.reserve('owner',1,1,5,connect=connect); "
                f"p=subprocess.Popen([sys.executable,'-c',{runner!r}],"
                "env={**os.environ,'ALEPH_INSPECT_HARD_TIMEOUT_S':'2'},start_new_session=True); "
                "inspect_quota.mark_running(lease,p.pid,connect=connect); "
                "print(json.dumps({'lease':lease,'pid':p.pid}),flush=True); os._exit(0)"
            )
            worker = subprocess.run([sys.executable, "-c", web], capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(worker.returncode, 0, worker.stderr)
            started = json.loads(worker.stdout)
            connect = lambda: sqlite_db.conectar(str(database))
            with self.assertRaises(inspect_quota.CapacityFull):
                inspect_quota.reserve("other", 1, 1, 5, connect=connect)
            time.sleep(5.5)
            recovered = inspect_quota.reserve("other", 1, 1, 5, connect=connect)
            self.assertTrue(recovered)
            self.assertFalse(marker.exists())
            inspect_quota.release(recovered, connect=connect)

    @unittest.skipUnless(os.name == "posix", "POSIX process groups required")
    def test_stuck_runner_and_descendant_die_before_db_lease_expires(self):
        with tempfile.TemporaryDirectory(prefix="aleph-inspect-watchdog-") as temp:
            marker = Path(temp) / "descendant-survived"
            child_code = f"import time,pathlib; time.sleep(4); pathlib.Path({str(marker)!r}).write_text('bad')"
            code = (
                "import os,subprocess,sys,time; "
                f"sys.path.insert(0,{str(ROOT / 'platform')!r}); "
                "from inspection.inspect_run import _arm_hard_deadline; "
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
                "_arm_hard_deadline(); time.sleep(10)"
            )
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    env={**os.environ, "ALEPH_INSPECT_HARD_TIMEOUT_S": "2"},
                                    start_new_session=True)
            started = time.monotonic()
            self.assertEqual(proc.wait(timeout=6), -9)
            self.assertLess(time.monotonic() - started, 4)
            time.sleep(2.5)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
