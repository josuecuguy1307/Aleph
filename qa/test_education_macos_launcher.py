"""Exercise the shipped Education launcher with only macOS system shell tools."""
import os
import signal
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "platform/workspaces/launchers/deeptutor"


class EducationMacOSLauncherTest(unittest.TestCase):
    def test_backend_and_web_survive_first_launch_and_relaunch_without_wait_n(self):
        with tempfile.TemporaryDirectory(prefix="aleph-edu-bash3-") as temp:
            root = Path(temp) / "tree"
            launcher = root / "platform/workspaces/launchers/deeptutor"
            launcher.parent.mkdir(parents=True)
            shutil.copy2(SOURCE, launcher)
            stack = root / "third_party/deeptutor/web/.next/standalone"
            stack.mkdir(parents=True)
            (stack / "server.js").write_text("// test server\n")
            backend = root / "backend/deeptutor_backend"
            backend.parent.mkdir()
            backend.write_text("#!/bin/sh\nprintf 'backend\\n' >> \"$ALEPH_TEST_STARTS\"\nexec /bin/sleep 30\n")
            backend.chmod(0o755)
            node = root / "node"
            node.write_text("#!/bin/sh\nprintf 'web\\n' >> \"$ALEPH_TEST_STARTS\"\nexec /bin/sleep 30\n")
            node.chmod(0o755)
            runtime = root / "runtime"
            starts = root / "starts.txt"
            env = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(root / "home"),
                "DEEPTUTOR_HOME": str(runtime),
                "ALEPH_PACK_PORT": "58997",
                "ALEPH_DEEPTUTOR_BACKEND": str(backend.parent),
                "ALEPH_DEEPTUTOR_NODE": str(node),
                "ALEPH_EDUCACION_PYTHON": "/usr/bin/python3",
                "ALEPH_TEST_STARTS": str(starts),
            }
            Path(env["HOME"]).mkdir()
            for attempt in (1, 2):
                stderr_path = root / f"launch-{attempt}.stderr"
                stderr_file = stderr_path.open("w")
                proc = subprocess.Popen(["/bin/bash", str(launcher)], env=env,
                                        stdout=subprocess.DEVNULL, stderr=stderr_file,
                                        start_new_session=True)
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        lines = starts.read_text().splitlines() if starts.exists() else []
                        if len(lines) >= 2 * attempt:
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    self.assertIsNone(proc.poll(), "launcher exited during startup")
                    self.assertEqual(set(lines[-2:]), {"backend", "web"})
                    time.sleep(1)
                    self.assertIsNone(proc.poll(), "launcher must keep both children running")
                finally:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    stderr_file.close()
                self.assertNotIn("wait: -n: invalid option", stderr_path.read_text())


if __name__ == "__main__":
    unittest.main()
