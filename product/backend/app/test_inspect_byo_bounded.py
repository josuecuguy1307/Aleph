"""Synthetic BYO quota/runner boundary; no user database or MCP service."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "product" / "backend"), str(ROOT / "platform")]
_test_data_root = tempfile.TemporaryDirectory(prefix="aleph-byo-data-")
os.environ["ALEPH_DATA_DIR"] = _test_data_root.name
os.environ["ALEPH_ROLE"] = "client"

from app.phase1 import inspect_router


class BoundedByoTests(unittest.TestCase):
    def test_byo_stdio_environment_excludes_undeclared_sentinels(self):
        from inspection import byo_mcp
        sentinels = {name: "synthetic-" + name for name in (
            "FAKE_DB_SECRET", "FAKE_JWT_SECRET", "FAKE_STRIPE_SECRET",
            "FAKE_OTHER_PROVIDER_SECRET")}
        with tempfile.TemporaryDirectory(prefix="aleph-mcp-env-") as scratch, \
             patch.dict(os.environ, sentinels):
            child = byo_mcp._stdio_probe_env({"FAKE_DB_SECRET": "declared-only"}, scratch)
            self.assertEqual(child["FAKE_DB_SECRET"], "declared-only")
            for name in set(sentinels) - {"FAKE_DB_SECRET"}:
                self.assertNotIn(name, child)
            self.assertEqual(child["HOME"], scratch)
            self.assertEqual(child["TMPDIR"], scratch)

    def test_real_mcp_sees_only_its_declared_synthetic_secret(self):
        from inspection import byo_mcp
        names = ("FAKE_DB_SECRET", "FAKE_JWT_SECRET", "FAKE_STRIPE_SECRET",
                 "FAKE_OTHER_PROVIDER_SECRET")
        sentinels = {name: "synthetic-" + name for name in names}
        with tempfile.TemporaryDirectory(prefix="aleph-mcp-env-real-") as temp:
            server = Path(temp) / "env_probe.py"
            server.write_text(
                "import os\nfrom mcp.server import MCPServer\n"
                "app=MCPServer('env-probe')\n"
                "@app.tool()\ndef env_probe() -> str:\n"
                f"    names={names!r}\n"
                "    return ';'.join(os.environ[n] for n in names if n in os.environ)\n"
                "app.run('stdio')\n"
            )
            with patch.dict(os.environ, sentinels):
                result = byo_mcp.probe_mcp(
                    transport="stdio", command=sys.executable, args=[str(server)],
                    env={"FAKE_DB_SECRET": "declared-only"},
                    prueba_credencial={"tool": "env_probe", "args": {}},
                )
            sample = result["credencial"]["muestra"]
            self.assertIn("declared-only", sample)
            for name in names:
                self.assertNotIn(sentinels[name], sample)

    @unittest.skipUnless(os.name == "posix", "requires process groups")
    def test_pinned_sdk_stdio_spawn_stays_in_watchdog_group(self):
        with tempfile.TemporaryDirectory(prefix="aleph-byo-sdk-group-") as temp:
            marker = Path(temp) / "survived"
            child = ("import os,pathlib,time; print(os.getpgrp(),flush=True); "
                     f"time.sleep(3); pathlib.Path({str(marker)!r}).write_text('bad')")
            code = (
                "import anyio,os,sys; "
                "from inspection.grouped_stdio import install; install(); "
                "from mcp.client import stdio\n"
                "async def run():\n"
                f" p=await stdio._create_platform_compatible_process(sys.executable,['-c',{child!r}]);\n"
                " print((await p.stdout.receive()).decode().strip(),flush=True);\n"
                " await anyio.sleep(20)\n"
                "anyio.run(run)"
            )
            proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True,
                                    env={**os.environ, "PYTHONPATH": str(ROOT / "platform")})
            try:
                self.assertIsNotNone(proc.stdout)
                group = int(proc.stdout.readline().decode().strip())
                self.assertEqual(group, proc.pid)
            finally:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate(timeout=5)
            time.sleep(2.5)
            self.assertFalse(marker.exists())

    def test_unauthenticated_stdio_command_denied_before_admission(self):
        endpoint = next(route.endpoint for route in inspect_router.build_inspect_router().routes
                        if route.path == "/v1/inspect/byo")
        with patch.object(inspect_router, "_session_user", return_value=None), \
             patch.object(inspect_router, "_reserve", side_effect=AssertionError("admitted")):
            with self.assertRaises(HTTPException) as result:
                endpoint(inspect_router.ByoRequest(transport="stdio", command="/bin/sh"),
                         authorization=None)
        self.assertEqual(result.exception.status_code, 401)

    def test_valid_child_result_and_lease_pid(self):
        with tempfile.TemporaryDirectory(prefix="aleph-byo-bound-") as temp:
            runner = Path(temp) / "runner.py"
            runner.write_text(
                "import json,sys; data=json.load(sys.stdin); "
                "print(json.dumps({'kind':'ok','result':{'validated':True,'transport':data['transport']}}))"
            )
            seen = []
            with patch.object(inspect_router, "_RUNNER", runner), \
                 patch.object(inspect_router.inspect_quota, "mark_running",
                              side_effect=lambda lease, pid: seen.append((lease, pid)) or True):
                result = inspect_router._run_byo_bounded(
                    inspect_router.ByoRequest(transport="http"), None, "test-lease")
            self.assertEqual(result, {"validated": True, "transport": "http"})
            self.assertEqual(seen[0][0], "test-lease")
            self.assertGreater(seen[0][1], 0)

    def test_real_sdk_stdio_mcp_forges_with_temporary_data_root(self):
        with tempfile.TemporaryDirectory(prefix="aleph-byo-mcp-") as temp:
            server = Path(temp) / "fixture_mcp.py"
            server.write_text(
                "from mcp.server import MCPServer\n"
                "app=MCPServer('synthetic-mcp')\n"
                "@app.tool()\n"
                "def ping() -> str:\n"
                "    return 'pong'\n"
                "app.run('stdio')\n"
            )
            env = {"ALEPH_ROLE": "client", "ALEPH_DATA_DIR": str(Path(temp) / "data")}
            with patch.dict(os.environ, env), \
                 patch.object(inspect_router.inspect_quota, "mark_running", return_value=True):
                result = inspect_router._run_byo_bounded(
                    inspect_router.ByoRequest(transport="stdio", command=sys.executable,
                                              args=[str(server)], label="synthetic-mcp"),
                    "synthetic-owner", "synthetic-lease")
            self.assertTrue(result["validated"])
            self.assertIn("ping", result["tools"])
            self.assertEqual(result["inspection_transport"], "sdk_group_supervised")
            self.assertTrue((Path(temp) / "data" / "synth_belts").exists())

    @unittest.skipUnless(os.name == "posix", "requires process groups")
    def test_timeout_kills_descendant_before_capacity_release(self):
        with tempfile.TemporaryDirectory(prefix="aleph-byo-bound-") as temp:
            runner = Path(temp) / "runner.py"
            marker = Path(temp) / "escaped"
            grandchild = (
                "import pathlib,time;time.sleep(3);"
                f"pathlib.Path({str(marker)!r}).write_text('bad')"
            )
            runner.write_text(
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
                "time.sleep(20)"
            )
            with patch.object(inspect_router, "_RUNNER", runner), \
                 patch.object(inspect_router, "_timeout", return_value=1), \
                 patch.object(inspect_router.inspect_quota, "mark_running", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "hard deadline"):
                    inspect_router._run_byo_bounded(
                        inspect_router.ByoRequest(transport="http"), None, "test-lease")
            time.sleep(2.5)
            self.assertFalse(marker.exists())

    @unittest.expectedFailure
    @unittest.skipUnless(os.name == "posix", "requires POSIX sessions")
    def test_detached_mcp_descendant_cannot_escape_watchdog(self):
        """Known open boundary: setsid detaches from the runner's killpg."""
        with tempfile.TemporaryDirectory(prefix="aleph-byo-detach-" ) as temp:
            runner = Path(temp) / "runner.py"
            marker = Path(temp) / "escaped"
            pidfile = Path(temp) / "pid"
            detached = (
                "import os,pathlib,time;"
                f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                "time.sleep(2.5);"
                f"pathlib.Path({str(marker)!r}).write_text('escaped')"
            )
            runner.write_text(
                "import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{detached!r}],start_new_session=True);"
                "time.sleep(20)"
            )
            try:
                with patch.object(inspect_router, "_RUNNER", runner), \
                     patch.object(inspect_router, "_timeout", return_value=1), \
                     patch.object(inspect_router.inspect_quota, "mark_running", return_value=True):
                    with self.assertRaisesRegex(RuntimeError, "hard deadline"):
                        inspect_router._run_byo_bounded(
                            inspect_router.ByoRequest(transport="http"), None, "detached-lease")
                time.sleep(2.8)
                self.assertFalse(marker.exists(), "detached MCP remained outside killpg")
            finally:
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except (OSError, ValueError): pass


if __name__ == "__main__":
    unittest.main()


def tearDownModule():
    _test_data_root.cleanup()
