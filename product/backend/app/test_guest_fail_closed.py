"""Host code execution remains closed until a verified isolated guest ships."""
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "platform" / "assembler"))
sys.path.insert(0, str(ROOT / "product" / "belts" / "generalistas"))


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuestFailClosed(unittest.TestCase):
    def test_all_untrusted_host_execution_entrypoints_deny(self):
        sandbox = _load("pysandbox_boundary", "product/belts/generalistas/pysandbox_server.py")
        scripts = _load("script_runner_boundary", "product/belts/gaps/script_runner_mcp.py")
        workers = _load("workers_boundary", "platform/assembler/workers.py")
        with tempfile.TemporaryDirectory(prefix="aleph-host-denial-") as temp:
            outside = Path(temp) / "outside"
            payload = f"open({str(outside)!r}, 'w').write('escaped')"
            self.assertFalse(sandbox._run_python(payload)["ok"])
            self.assertFalse(scripts.tool_run_python({"code": payload})["ok"])
            self.assertFalse(scripts.tool_run_shell({"command": ["python3", "-c", payload]})["ok"])
            self.assertFalse(workers._run_guion_code(payload, temp)["ok"])
            self.assertFalse(outside.exists())

    def test_genuine_guest_work_and_missing_asset_fail_closed(self):
        sandbox = _load("pysandbox_verified", "product/belts/generalistas/pysandbox_server.py")
        self.assertEqual(sandbox._run_python("print(6*7)")["stdout"], "42\n")
        scripts = _load("script_runner_verified", "product/belts/gaps/script_runner_mcp.py")
        self.assertIn("git version", scripts.tool_run_shell({"command": ["git", "--version"]})["stdout"])
        import guest_execution
        with tempfile.TemporaryDirectory(prefix="aleph-no-guest-") as temp:
            with patch.object(guest_execution, "_RUNTIME", Path(temp)):
                denied = sandbox._run_python("print(6*7)")
                self.assertTrue(denied["blocked"])
                self.assertEqual(denied["stdout"], "")
                self.assertTrue(scripts.tool_run_shell({"command": ["git", "--version"]})["blocked"])


if __name__ == "__main__":
    unittest.main()
