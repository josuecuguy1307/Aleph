"""Capture actual alternate model boundaries; no live-model claim from these tests."""
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'platform/assembler'),str(ROOT/'platform'),str(ROOT/'product/backend')]
import recipe_assembler as ra
from app.phase1 import workspace_brain as wb, stream_chat as sc, method_brain as mb

class Reached(Exception):
    pass

class LanguageBoundaries(unittest.TestCase):
    def setUp(self):
        self.messages = [{'role':'system','content':'Keep the required JSON schema.'},
            {'role':'user','content':[{'type':'text','text':'Please answer in English.'},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,TEST'}}]},
            {'role':'assistant','content':None,'tool_calls':[{'id':'id_1'}]},
            {'role':'tool','tool_call_id':'id_1','content':'user-owned text'}]
        self.original = copy.deepcopy(self.messages)
    def test_copy_and_idempotence(self):
        out = ra._with_idioma_block(self.messages,'en')
        self.assertEqual(self.messages,self.original)
        self.assertEqual([m for m in out if m not in self.messages],
            [{'role':'system','content':ra._build_idioma_block('en').strip()}])
        self.assertEqual(ra._with_idioma_block(out,'en'),out)
        self.assertEqual(out[2:],self.messages[1:])
    def test_sync_and_stream_workspace(self):
        config = dict(a=ra,base_url='http://unused',primary='test',fallback=None,
            cli_model=None,effort=None,mt=64,tp=0,api_key='',is_byok=False,
            record={'model_route':[]})
        for stream in (False,True):
            captured=[]
            def capture(messages,*args,**kwargs):
                captured.extend(messages)
                raise Reached()
            with patch.object(wb,'_resolver_turno',return_value=config), \
                 patch.object(ra,'_route_chat_stream' if stream else '_route_chat',side_effect=capture):
                with self.assertRaises(Reached):
                    result=(wb.complete_stream if stream else wb.complete)(
                        {},self.messages,[],lang='en')
                    if stream: next(result)
            self.assertIn(ra._build_idioma_block('en').strip(),[m.get('content') for m in captured])
            self.assertEqual(self.messages,self.original)
    def test_legacy_stream_system(self):
        with patch.object(sc,'_asm',return_value=ra):
            text=sc._system_content({'framing':{'inline':'Marker'},'rag':{'enabled':False}},'en')
        self.assertIn(ra._build_idioma_block('en'),text)
        self.assertLess(text.index('Marker'),text.index('## Idioma, tono y registro'))
    def test_method_boundary(self):
        captured=[]
        def receive(req,**kwargs):
            captured.extend(json.loads(req.data)['messages'])
            raise Reached()
        with patch.object(mb,'_resolve_brain',return_value=('http://unused','test','')), \
             patch.object(sc,'_asm',return_value=ra),patch.object(mb.time,'sleep'), \
             patch.object(mb.urllib.request,'urlopen',side_effect=receive):
            with self.assertRaises(mb.MethodBrainError): mb._call_brain(self.messages,lang='en')
        self.assertIn(ra._build_idioma_block('en').strip(),[m.get('content') for m in captured])
        self.assertEqual(self.messages,self.original)
    def test_policy_disappears_when_disabled(self):
        with patch.object(ra,'_build_idioma_block',return_value=''):
            text=ra._with_idioma_block(self.messages,'en')
            self.assertNotIn('## Idioma, tono y registro',json.dumps(text))

if __name__=='__main__': unittest.main()
