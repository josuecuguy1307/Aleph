// Own frame/selector regression, not a live-model test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../third_party/deeptutor/web/node_modules/typescript');
const root = path.resolve(__dirname, '../..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const base = 'third_party/openscience/frontend/workspace/';
const dictionaries = {};
for (const locale of ['es', 'en']) {
  const source = read(base + 'src/i18n/' + locale + '.ts');
  const tree = ts.createSourceFile('locale.ts', source, ts.ScriptTarget.Latest, true);
  const visit = node => {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'dict')
      dictionaries[locale] = vm.runInNewContext('(' + node.initializer.getText(tree) + ')');
    ts.forEachChild(node, visit);
  };
  visit(tree);
}
const keys = Object.keys(dictionaries.en).filter(k => k.startsWith('aleph.frame.'));
assert.equal(keys.length, 24);
assert.deepEqual(keys.sort(), Object.keys(dictionaries.es).filter(k => k.startsWith('aleph.frame.')).sort());
for (const file of ['src/pages/aleph-frame.tsx', 'src/pages/session.tsx', 'src/components/prompt-input.tsx']) {
  const source = read(base + file);
  for (const m of source.matchAll(/"(aleph\.frame\.[^"]+)"/g)) {
    assert.ok(dictionaries.es[m[1]] && dictionaries.en[m[1]], file + ':' + m[1]);
  }
}
assert.equal(dictionaries.en['aleph.frame.composerHint'], 'Enter to send · Shift+Enter for a new line');
assert.equal(dictionaries.es['aleph.frame.settings'], 'Ajustes');
assert.equal(dictionaries.en['session.rename.hint'], 'Double-click to rename');
assert.equal(dictionaries.es['session.rename.hint'], 'Haga doble clic para cambiar el nombre');
assert.match(read(base + 'src/pages/aleph-frame.tsx'), /aria-label=\{language\.t\("aleph.frame.collapse"\)\}/);
assert.equal((read(base + 'src/pages/session.tsx').match(/language\.t\("session\.rename\.hint"\)/g) || []).length, 2);
const stacks = ['openwork/apps/app', 'deeptutor/web', 'vibetrading/frontend',
  'openscience/frontend/workspace', 'codesign/apps/desktop/src/renderer', 'dochaus/apps/web'];
const sources = stacks.map(stack => read('third_party/' + stack + '/public/aleph-picker-unico.js'));
for (const source of sources) assert.equal(source, sources[0], 'one identical shared selector host');
const signature = sources[0].match(/function firma\(\) \{[^]*?\n  \}/)[0];
assert.match(sources[0], /if \(faltaAlgo\(\) \|\| \(catalogoOk && pintado !== firma\(\)\)\) pintar\(\);/);
const ctx = vm.createContext({window: {}, document: {documentElement: {lang: 'es'}},
  ultimo: {selectedRef: 'codex_cli', choices: [{selection_ref: 'codex_cli'}]}});
vm.runInContext(signature, ctx);
const before = vm.runInContext('firma()', ctx);
ctx.document.documentElement.lang = 'en';
assert.notEqual(vm.runInContext('firma()', ctx), before, 'resolved workspace locale triggers repaint');
console.log('Owned frame: 24 ES/EN keys; selector repaint on existing locale; six copies identical.');
