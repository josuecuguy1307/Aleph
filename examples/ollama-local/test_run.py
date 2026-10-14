"""Prevent an unverified result or off-device connection from passing this example."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ollama_example', Path(__file__).with_name('run.py'))
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.result = {'ok': True, 'model_identity': {'actual_model': 'qwen3:8b', 'fallback_used': False},
                       'answer': 'Total: 56.', 'tool_calls': [{'tool': 'mul', 'executed': True,
                                                            'args': '{"a":7,"b":8}', 'result': '56.0'}]}

    def test_measured_result_passes(self):
        self.assertTrue(example.verified_result(self.result))

    def test_guessed_held_wrong_input_unknown_and_fallback_fail(self):
        for change in ('guessed', 'held', 'wrong-input', 'unknown', 'fallback'):
            with self.subTest(change=change):
                result = copy.deepcopy(self.result)
                if change == 'guessed': result['tool_calls'] = []
                elif change == 'held': result['tool_calls'][0]['executed'] = False
                elif change == 'wrong-input': result['tool_calls'][0]['args'] = '{"a":56,"b":1}'
                elif change == 'unknown': result['model_identity']['actual_model'] = None
                elif change == 'fallback': result['model_identity']['fallback_used'] = True
                self.assertFalse(example.verified_result(result))

    def test_approval_is_limited_to_the_sample(self):
        self.assertTrue(example.approve_sample('calc', 'mul', {'requiere_ok':True}))
        self.assertFalse(example.approve_sample('other', 'mul', {'requiere_ok':True}))
        self.assertFalse(example.approve_sample('calc', 'mul', {'requiere_ok':False}))

    def test_remote_socket_and_dns_refused(self):
        for event, args in [('socket.connect', (None, ('192.0.2.1', 443))),
                            ('socket.getaddrinfo', ('example.com', 443))]:
            with self.assertRaises(PermissionError): example.loopback_only(event, args)
        example.loopback_only('socket.connect', (None, ('127.0.0.1', 11434)))


if __name__ == '__main__':
    unittest.main()
