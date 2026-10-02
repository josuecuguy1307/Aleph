const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../../third_party/deeptutor/web/node_modules/typescript');
const root = require('node:path').resolve(__dirname, '../..');
const read = file => fs.readFileSync(require('node:path').join(root, file), 'utf8');
function office(locale) {
  const text = read('third_party/openwork/apps/app/src/i18n/locales/' + locale + '.ts');
  const tree = ts.createSourceFile('locale.ts', text, ts.ScriptTarget.Latest, true);
  let node = tree.statements.find(ts.isExportAssignment).expression;
  if (ts.isAsExpression(node)) node = node.expression;
  const keys = node.properties.map(p => p.name.text);
  assert.equal(keys.length, new Set(keys).size, 'no duplicate translation keys');
  return vm.runInNewContext('(' + node.getText(tree) + ')');
}
const es = office('es'), en = office('en');
for (const [key, spanish, english] of [
  ['new_chat', 'Nuevo chat', 'New chat'], ['search', 'Buscar', 'Search'],
  ['library', 'Biblioteca', 'Library'], ['recent_sessions', 'SESIONES RECIENTES', 'RECENT SESSIONS'],
  ['home', 'Inicio', 'Home'], ['settings', 'Ajustes', 'Settings'],
]) {
  assert.equal(es['aleph.frame.' + key], spanish);
  assert.equal(en['aleph.frame.' + key], english);
}
const files = ['openwork/apps/app', 'deeptutor/web', 'vibetrading/frontend',
  'openscience/frontend/workspace', 'codesign/apps/desktop/src/renderer', 'dochaus/apps/web'];
const hosts = files.map(file => read('third_party/' + file + '/public/aleph-piel.js'));
for (const source of hosts) assert.equal(source, hosts[0], 'shared fallback stays identical in six stacks');
const helper = hosts[0].match(/function copy\(es, en\) \{[^]*?\n  \}/)[0];
for (const locale of ['es', 'en']) {
  const ctx = vm.createContext({IDIOMA: locale, document: {documentElement: {lang: 'opposite-unused'}}});
  vm.runInContext(helper, ctx);
  assert.equal(ctx.copy('Ajustes', 'Settings'), locale === 'es' ? 'Ajustes' : 'Settings');
  assert.equal(ctx.copy('Skills', 'Skills'), 'Skills');
  assert.equal(ctx.copy('Compute', 'Compute'), 'Compute');
}
for (const locale of ['es', 'en']) {
  const dict = JSON.parse(read('third_party/codesign/packages/i18n/src/locales/' + locale + '.json'));
  assert.equal(dict.alephFrame.settings, locale === 'es' ? 'Ajustes' : 'Settings');
  assert.equal(dict.alephFrame.search, locale === 'es' ? 'Buscar' : 'Search');
}
for (const key of ['session_management.pin_session', 'session_management.archive_session']) assert.ok(es[key] && es[key] !== en[key]);
console.log('Office/Design common vocabulary ES/EN, tooltips and six fallback hosts; technical Skills/Compute preserved.');
