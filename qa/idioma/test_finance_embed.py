"""Read the actual owned embedding predicate without importing the trading stack."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
tree = ast.parse((ROOT / 'third_party/vibetrading/agent/src/api/security.py').read_text())
names = {'_ALEPH_EMBED_ENV', '_ALEPH_EMBED_WORKSPACE', '_ALEPH_EMBED_DOCUMENT_PATHS'}
nodes = [node for node in tree.body if
    (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)) or
    (isinstance(node, ast.FunctionDef) and node.name == '_is_aleph_embedded_document')]
scope = {'os': os, 'Request': object}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<actual-embedding-predicate>', 'exec'), scope)
predicate = scope['_is_aleph_embedded_document']

class EmbeddingBoundary(unittest.TestCase):
    def request(self, path, workspace='finanzas'):
        return SimpleNamespace(url=SimpleNamespace(path=path), query_params={'aleph_ws':workspace})

    def test_settings_spa_entries_require_both_existing_markers(self):
        for path in scope['_ALEPH_EMBED_DOCUMENT_PATHS']:
            with self.subTest(path=path):
                with patch.dict(os.environ, {'ALEPH_WORKSPACE_EMBED':'1'}):
                    self.assertTrue(predicate(self.request(path)))
                    self.assertFalse(predicate(self.request(path, '')))
                    self.assertFalse(predicate(self.request(path, 'oficina')))
                with patch.dict(os.environ, {'ALEPH_WORKSPACE_EMBED':''}):
                    self.assertFalse(predicate(self.request(path)))

    def test_no_api_static_or_arbitrary_path_exception(self):
        with patch.dict(os.environ, {'ALEPH_WORKSPACE_EMBED':'1'}):
            for path in ('/health','/docs','/api/sessions','/assets/a.js','/fonts/a.woff2',
                         '/alpha-zoo/../../health','/unknown','/alpha-zoo/unknown-id'):
                with self.subTest(path=path):
                    self.assertFalse(predicate(self.request(path)))

if __name__ == '__main__':
    unittest.main()
