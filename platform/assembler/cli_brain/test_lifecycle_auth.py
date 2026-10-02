"""Production lifecycle never opens an unauthenticated CLI listener."""
import unittest
import socket
import os
import tempfile
from unittest.mock import patch

class LifecycleAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aleph-cli-lifecycle-test-")
        self.addCleanup(self.temp.cleanup)
        isolated = patch.dict(os.environ, {"ALEPH_DATA_DIR": self.temp.name})
        isolated.start()
        self.addCleanup(isolated.stop)
        from cli_brain.lifecycle import CliBrainLifecycle
        self.Lifecycle = CliBrainLifecycle

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_empty_instance_key_fails_closed(self):
        owner = self.Lifecycle(port=0)
        with patch("cli_brain.lifecycle._credencial.asegurar", return_value=""), \
             patch("cli_brain.lifecycle.create_server") as create, \
             patch("cli_brain.lifecycle.probe_service", return_value=False):
            status = owner.start()
        create.assert_not_called()
        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["mode"], "failed")
        self.assertIn("llave de instancia", status["detail"])

    def test_key_exception_fails_closed(self):
        owner = self.Lifecycle(port=0)
        with patch("cli_brain.lifecycle._credencial.asegurar", side_effect=OSError("private")), \
             patch("cli_brain.lifecycle.create_server") as create, \
             patch("cli_brain.lifecycle.probe_service", return_value=False):
            status = owner.start()
        create.assert_not_called()
        self.assertNotIn("private", status["detail"])

    def test_owned_service_starts_and_stops(self):
        owner = self.Lifecycle(port=self.free_port())
        with patch("cli_brain.lifecycle._credencial.asegurar", return_value="test-instance-key"):
            status = owner.start()
            try:
                self.assertEqual(status["state"], "ready")
                self.assertEqual(status["mode"], "managed")
                self.assertEqual(owner.start()["mode"], "managed")
            finally:
                owner.stop()
        self.assertEqual(owner.status()["state"], "unavailable")

    def test_foreign_port_is_not_claimed(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            owner = self.Lifecycle(port=occupied.getsockname()[1])
            with patch("cli_brain.lifecycle._credencial.asegurar", return_value="test-key"):
                result = owner.start()
            self.assertEqual(result["state"], "unavailable")
            self.assertEqual(result["mode"], "failed")
            self.assertIn("ocupado", result["detail"])

    def test_dead_owned_listener_can_restart(self):
        owner = self.Lifecycle(port=self.free_port())
        with patch("cli_brain.lifecycle._credencial.asegurar", return_value="test-instance-key"):
            self.assertEqual(owner.start()["state"], "ready")
            try:
                owner._server.shutdown()
                owner._thread.join(timeout=2)
                self.assertEqual(owner.status()["state"], "unavailable")
                self.assertEqual(owner.start()["state"], "ready")
            finally:
                owner.stop()


if __name__ == "__main__":
    unittest.main()
