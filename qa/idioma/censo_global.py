"""Read-only global census. Candidates require explicit classification, not replacement.

Tracks owned runtime sources and catalog/context; inventories upstream read-only
integration files/locales separately. Python f-string chunks and tool docstrings
are included, unlike the original line-level census. Output is machine-readable.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize
import sys

sys.path.insert(0, str(Path(__file__).parent))
import censo_voseo as old

ROOT = Path(__file__).resolve().parents[2]
EXTRA = re.compile(r"\b(?:bajá|animáte|animate|preguntale|preguntales|explicale|explicales|"
    r"(?:compart|escrib|abr|segu|eleg|repet|defin|describ|cumpl|divid|añad|inclu|"
    r"sustitu|imprim|transcrib|resum|constru|convert|conclu|consegu|descubr|reun|"
    r"distingu|exig|insist|invert|omit|admit|remit|discut|introduc|reduc|produc|"
    r"conduc|traduc)i(?:me|te|lo|la|los|las|le|les)|"
    r"facilitame|ayudame|ayudalo|ayudala|pasales|copialo|copiala|copialos|copialas|"
    r"corrélo|corréla|haceme|hacete|deciles|decinos|avisales|fijense|fijáte|"
    r"tenelo|tenela|leelos|leelas|usálo|usála|dejanos|dejanos|"
    r"[a-záéíóúñ]{3,}(?:és|ís)(?:lo|la|los|las|me|te|le|les)|"
    r"(?:prob|mir|peg|copi|toc|guard|borr|cerr|busc|explic|pregunt|avis|mand|cont|"
    r"mostr|revis|pas|dej|carg|agreg|sac|record|conect|registr|olvid|prepar|asegur)"
    r"a(?:me|te|lo|la|los|las|le|les)|"
    r"tengás|podás|querás|sepás|hagás|digás|vengás|pongás|seás|"
    r"tenes|podes|queres|decis|haceslo|necesitaslo|comentame|consultame|evaluame|"
    r"corregime|respondeme|devolveme|escribile|escribiles|traeme|traelo|traela|"
    r"ponete|haceles|manteneme|mantenelo|retenelo|sostenelo|repetilo|permitime|"
    r"soltalo|mandámelo|mostrámelo|contámelo|explicámelo|pasámelo)\b", re.I)
REGIONAL_ES = re.compile(r"\b(?:acá|recién|planilla|planillas|laburo|laburar|che|ché|copado|"
    r"pibe|piba|boludo|boluda|bancá|banca|dale|quilombo|destilda|destildá|destildar|tildá|tildar)\b", re.I)
SLANG_EN = re.compile(r"\b(?:gonna|wanna|gotta|y['’]all|ain['’]t|kinda|sorta|dunno|lemme|"
    r"gimme|dude|buddy|cheers|no worries|awesome|yeah|yep|nope|whoops|oops|"
    r"stuff|a bunch|heck|damn|crap|bloody|mate|guys|nah|meh|tons of|a ton|"
    r"no biggie|my bad|you bet|for sure|nuke|yikes|dang|geez|jeez|dodgy|whilst|"
    r"amongst|colour|favourite|organise|organisation|realise|behaviour|centre|"
    r"licence|programme|catalogue|analyse|cancelled|grey|flavour|honour|labour|"
    r"neighbour|apologise|recognise|customise|optimise|summarise|initialise|"
    r"synchronise|authorise|prioritise|utilise|minimise|maximise|judgement|"
    r"artefact|cheque|maths|learnt|untick|ticked|zero theater)\b", re.I)
CONTRACTIONS = re.compile(r"\b(?:don['’]t|can['’]t|won['’]t|it['’]s|you['’]re|"
    r"we['’]re|let['’]s|I['’]m|I['’]ll|you['’]ll|doesn['’]t|isn['’]t)\b", re.I)

def tokens_es(text):
    # The original scanner excluded two real imperatives; deliberately include
    # them as candidates here. Standard tuteo forms remain reviewable, not defects.
    return sorted(set(old.matches(text) + [m.group() for m in EXTRA.finditer(text)]))

def selected(path):
    p = Path(path)
    if p.suffix not in ('.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.html', '.json',
                        '.yaml', '.yml', '.txt', '.rs', '.sql', '.md'):
        return False
    if any(x in p.parts for x in ('node_modules', '.venv', 'dist', 'build', '.next', 'target',
                                 '__pycache__', 'screenshots', 'fixtures', 'deleg_fixtures',
                                 'tests', '__tests__', 'verify', 'evals', 'eval', 'runs')):
        return False
    if re.search(r'(?:^|/)(?:tests?[_-]|verify(?:[_.-]|$)|selftest[_-]|diag[_-]|smoke[_-]|run_e2e|seed_puppets)', path) or '_e2e.' in path:
        return False
    if path.startswith(('platform/sala/research/lib/', 'platform/sala/research/runtime/',
                        'platform/sala/busqueda/searxng/', 'data/', 'reports/', 'docs/',
                        'qa/', 'audit/', 'i18n/', '.claude/', 'spikes/')):
        return False
    if path.startswith(('product/app/_exploraciones/',
                        'deploy/fase4/aleph-shell/src-tauri/resources/PDFIUM-NOTICES/')) or path in (
            'platform/gates/DEMO-OUTPUT.txt', 'onboarding/seed_result.json',
            'platform/gates/demo_e2e.py', 'platform/inspection/demo_live.py',
            'product/app/design/sala/canvas-preview.html',
            'product/app/design/cuarto/frontera_d4_events.json'):
        return False
    if 'vendor' in p.parts and not p.name.startswith('aleph'):
        return False
    if path.startswith('third_party/'):
        # Read only: own Aleph integration code and already documented locales.
        return ('aleph' in p.name.lower() or
                path in ('third_party/deeptutor/services/prompt/language.py',
                         'third_party/vibetrading/agent/src/api/security.py',
                         'third_party/openscience/frontend/workspace/src/i18n/es.ts',
                         'third_party/openscience/frontend/workspace/src/i18n/en.ts',
                         'third_party/openscience/frontend/workspace/src/pages/session.tsx',
                         'third_party/openscience/frontend/workspace/src/components/prompt-input.tsx') or
                (path.startswith('third_party/deeptutor/deeptutor/') and
                 ('/prompts/' in path or '/tools/prompting/hints/' in path) and
                 ('/en/' in path or '/es/' in path) and path.endswith(('.yaml', '.yml', '.txt', '.md'))) or
                '/packages/i18n/src/locales/es.' in path or '/packages/i18n/src/locales/en.' in path or
                '/i18n/locales/es.' in path or '/i18n/locales/en.' in path or
                '/locales/es/' in path or '/locales/en/' in path or
                path.startswith('third_party/dochaus/apps/web/src/locales/'))
    if p.suffix == '.md':
        return (path.startswith(('catalog/templates/', 'catalog/agents/', 'platform/assembler/cli_brain/agents/',
                                 'platform/skills/', 'onboarding/')) and p.name not in ('README.md', 'EJEMPLO.md'))
    return path.startswith(('platform/', 'product/', 'catalog/', 'onboarding/', 'deploy/')) and p.suffix in (
        '.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.html', '.json', '.yaml', '.yml', '.txt', '.rs', '.sql')

def area(path):
    if path.startswith('catalog/connectors/onboarding/') or path.startswith('onboarding/'):
        return 'onboarding'
    if path.startswith(('catalog/templates/', 'catalog/agents/', 'platform/skills/')):
        return 'context'
    if '/cli_brain/agents/' in path:
        return 'context'
    if path.startswith('third_party/deeptutor/deeptutor/') and ('/prompts/' in path or '/tools/prompting/hints/' in path):
        return 'prompts'
    if path in ('third_party/deeptutor/services/prompt/language.py',
                'third_party/vibetrading/agent/src/api/security.py'):
        return 'system'
    if path.startswith(('product/app/', 'deploy/fase4/aleph-shell/')) or path.startswith('third_party/'):
        return 'UI'
    if path.startswith(('platform/assembler/', 'product/belts/')) or 'codemode' in path:
        return 'prompts'
    return 'system'

def segment_area(row):
    # Source-origin groups aid review; they do not prove runtime reachability.
    # In particular, backend errors and mixed builders need manual UI/system review.
    if row['kind'] in ('comment', 'internal-docstring'):
        return 'comments'
    if row['kind'] == 'tool-description':
        return 'prompts'
    return area(row['path'])

def py_segments(path, src):
    docs = {}
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                tool = any('tool' in ast.unparse(d).lower() for d in getattr(node, 'decorator_list', []))
                for ln in range(body[0].lineno, body[0].end_lineno + 1):
                    docs[ln] = 'tool-description' if tool else 'internal-docstring'
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out.append(dict(path=path, line=tok.start[0], kind='comment', text=tok.string))
        elif tok.type in (tokenize.STRING, getattr(tokenize, 'FSTRING_MIDDLE', -1)):
            text = tok.string
            if tok.type == tokenize.STRING:
                try: text = ast.literal_eval(text)
                except (ValueError, SyntaxError): pass
            if isinstance(text, str):
                out.append(dict(path=path, line=tok.start[0], endLine=tok.end[0], kind=docs.get(tok.start[0], 'string'), text=text))
    return out

class HTMLSegments(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path, self.out, self.block = path, [], None
    def add(self, text, kind='string'):
        self.out.append(dict(path=self.path, line=self.getpos()[0], endLine=self.getpos()[0]+text.count('\n'), kind=kind, text=text))
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.block = tag
        for key, value in attrs:
            if key in ('title', 'placeholder', 'aria-label', 'alt') and value: self.add(value)
    def handle_endtag(self, tag):
        if tag == self.block: self.block = None
    def handle_data(self, data):
        if not self.block and data.strip(): self.add(data)
    def handle_comment(self, data): self.add(data, 'comment')

def collect(paths):
    out, js, errors = [], [], []
    for path in paths:
        try:
            src = (ROOT / path).read_text(encoding='utf-8')
            suffix = Path(path).suffix
            if suffix == '.py': out.extend(py_segments(path, src))
            elif suffix in ('.js', '.mjs', '.cjs', '.ts', '.tsx'): js.append(dict(path=path))
            elif suffix == '.html':
                parser = HTMLSegments(path); parser.feed(src); out.extend(parser.out)
                for m in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script>', src, re.I):
                    js.append(dict(path=path, source=m.group(1), offset=src[:m.start(1)].count('\n')))
            else:
                for ln, text in enumerate(src.splitlines(), 1):
                    kind = 'comment' if text.lstrip().startswith(('#', '//', '--')) and suffix != '.md' else 'string'
                    out.append(dict(path=path, line=ln, kind=kind, text=text))
        except Exception as exc:
            errors.append(dict(path=path, error=str(exc)))
    proc = subprocess.run(['node', 'qa/idioma/extraer_js.cjs'], input=json.dumps(js), text=True,
                          cwd=ROOT, capture_output=True, check=True)
    out.extend(json.loads(proc.stdout))
    return out, errors

def census():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = sorted(p for p in tracked if p and selected(p))
    segments, errors = collect(paths)
    candidates = []
    counts = Counter()
    contractions = 0
    for row in segments:
        counts[segment_area(row)] += 1
        contractions += len(CONTRACTIONS.findall(row['text'])) if row['kind'] not in ('comment', 'internal-docstring') else 0
        for language, words in (('voseo', tokens_es(row['text'])),
                                ('regional-ES', REGIONAL_ES.findall(row['text'])),
                                ('EN', SLANG_EN.findall(row['text']))):
            if words:
                candidates.append({**row, 'area': segment_area(row), 'language': language, 'words': sorted(set(words))})
    return dict(files=len(paths), paths=paths, segments=dict(counts), candidates=candidates,
                contractions_neutral=contractions, extraction_errors=errors)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--area'); ap.add_argument('--comments', action='store_true')
    args = ap.parse_args()
    result = census()
    if args.area:
        result['candidates'] = [r for r in result['candidates'] if r['area'] == args.area]
    if not args.comments:
        result['candidates'] = [r for r in result['candidates'] if r['kind'] not in ('comment', 'internal-docstring')]
    print(json.dumps(result, ensure_ascii=False, indent=2))
