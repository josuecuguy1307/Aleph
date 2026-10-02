"""Timing milestones and timeout origin without live provider access."""
import subprocess
import sys
import time
import unittest

from cli_brain.base import _run_streaming, _timing_summary


class TimingTests(unittest.TestCase):
    def test_process_and_first_output_are_distinct(self):
        timing = {"request_received_mono": time.monotonic()}
        result, stats = _run_streaming(
            [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(.02)"],
            timeout=2, timing=timing)
        summary = _timing_summary(timing)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(stats.lineas, 1)
        self.assertLessEqual(summary["process_started_s"], summary["first_output_s"])
        self.assertLessEqual(summary["first_output_s"], summary["completion_s"])
        self.assertIsNone(summary["timeout_layer"])

    def test_deadline_is_classified_at_process_layer(self):
        timing = {"request_received_mono": time.monotonic()}
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_streaming([sys.executable, "-c", "import time; time.sleep(2)"],
                           timeout=.15, chunk_timeout=.05, timing=timing)
        self.assertEqual(_timing_summary(timing)["timeout_layer"], "cli_deadline")


if __name__ == "__main__":
    unittest.main()
