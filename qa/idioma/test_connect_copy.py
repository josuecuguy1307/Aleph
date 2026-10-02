"""Actual connector fallback with an injected transport; no accounts or live LLM."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('owned_connect_engine', ROOT / 'platform/connectors/connect_engine.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ConnectCopyTests(unittest.TestCase):
    def test_empty_content_neutral_fallback_and_custom_copy_preserved(self):
        obj = {'auth': {}, 'validate': {'path': '/validate'}, 'requires_sharing': True,
               'content_probe': {'path': '/content', 'empty_when': 'results.length == 0'}}
        def transport(method, url, headers, params, body=None):
            return 200, {'results': []}
        result = module.connect(obj, {}, api_base='https://example.invalid', http=transport)
        self.assertEqual(result['state'], 'connected_empty')
        self.assertEqual(result['message'], 'Comparte algo para poder verlo.')
        obj['share_instruction'] = 'Copy propio del conector'
        self.assertEqual(module.connect(obj, {}, api_base='https://example.invalid', http=transport)['message'],
                         obj['share_instruction'])

    def test_census_catches_unaccented_enclitics(self):
        census_spec = importlib.util.spec_from_file_location('census', ROOT / 'qa/idioma/censo_global.py')
        census = importlib.util.module_from_spec(census_spec)
        census_spec.loader.exec_module(census)
        for text in ['Compartime algo', 'Escribime una línea', 'Abrilo', 'Traducilo',
                     'Convertilo a USD', 'Resumilo en 3 puntos', 'Elegile uno', 'Conseguila gratis']:
            self.assertTrue(census.tokens_es(text), text)
        self.assertFalse(census.tokens_es('Comparte algo para poder verlo.'))

if __name__ == '__main__':
    unittest.main()
