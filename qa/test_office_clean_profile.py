"""Real OpenWork process: clean first launch, auth rejection, and same-profile relaunch."""
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


BIN = Path(__file__).resolve().parents[1] / "third_party/openwork/bin/openwork-server"


def request(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


class OfficeCleanProfileTest(unittest.TestCase):
    def test_first_launch_and_relaunch_use_only_current_file_capabilities(self):
        with tempfile.TemporaryDirectory(prefix="aleph-office-clean-") as temp:
            root = Path(temp).resolve()
            for name in ("home", "config", "data", "cache", "workspace"):
                (root / name).mkdir()
            config_path = root / "server.json"
            env = dict(os.environ)
            env.update({
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "OPENWORK_SERVER_CONFIG": str(config_path),
                "OPENCODE_CONFIG_DIR": str(root / "config/opencode"),
                "OPENCODE_DATA_DIR": str(root / "data/opencode"),
            })
            env.pop("OPENWORK_TOKEN", None)
            env.pop("OPENWORK_HOST_TOKEN", None)
            old_client = old_host = None
            for attempt in (1, 2):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                client = f"clean-client-{attempt}-{os.urandom(12).hex()}"
                host = f"clean-host-{attempt}-{os.urandom(12).hex()}"
                config_path.write_text(json.dumps({
                    "host": "127.0.0.1", "port": port,
                    "token": client, "hostToken": host,
                    "workspaces": [{"path": str(root / "workspace")}],
                }))
                config_path.chmod(0o600)
                with (root / f"launch-{attempt}.log").open("w+") as log:
                    proc = subprocess.Popen([str(BIN), "--config", str(config_path)],
                                            env=env, stdout=log, stderr=subprocess.STDOUT)
                    try:
                        base = f"http://127.0.0.1:{port}"
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            if proc.poll() is not None:
                                break
                            try:
                                if request(base + "/health") == 200:
                                    break
                            except OSError:
                                pass
                            time.sleep(0.1)
                        self.assertIsNone(proc.poll(), "server exited during clean launch")
                        self.assertEqual(request(base + "/health"), 200)
                        self.assertEqual(request(base + "/workspaces", {
                            "Authorization": "Bearer " + client}), 200)
                        self.assertEqual(request(base + "/workspaces", {
                            "Authorization": "Bearer stale-client"}), 401)
                        self.assertEqual(request(base + "/env/status", {
                            "x-openwork-host-token": host}), 200)
                        self.assertEqual(request(base + "/env/status", {
                            "x-openwork-host-token": "stale-host"}), 401)
                        if old_client:
                            self.assertEqual(request(base + "/workspaces", {
                                "Authorization": "Bearer " + old_client}), 401)
                            self.assertEqual(request(base + "/env/status", {
                                "x-openwork-host-token": old_host}), 401)
                        old_client, old_host = client, host
                    finally:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
