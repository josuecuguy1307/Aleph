// Read-only catalogue inventory. Missing/same entries are candidates, not measured UI defects.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../third_party/deeptutor/web/node_modules/typescript');
const root = path.resolve(__dirname, '../..');
const pairs = {
  oficina: 'third_party/openwork/apps/app/src/i18n/locales/{locale}.ts',
  ciencia: 'third_party/openscience/frontend/workspace/src/i18n/{locale}.ts',
  educacion: 'third_party/deeptutor/web/locales/{locale}/app.json',
  finanzas: 'third_party/vibetrading/frontend/src/i18n/locales/{locale}.json',
  legal: 'third_party/dochaus/apps/web/src/locales/{locale}.json',
  diseno: 'third_party/codesign/packages/i18n/src/locales/{locale}.json',
};
function load(file) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  if (file.endsWith('.json')) return JSON.parse(source);
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  let expression;
  const visit = node => {
    if (ts.isExportAssignment(node)) expression = node.expression;
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'dict') expression = node.initializer;
    ts.forEachChild(node, visit);
  };
  visit(ast);
  if (ts.isAsExpression(expression)) expression = expression.expression;
  return vm.runInNewContext('(' + expression.getText(ast) + ')');
}
function flatten(value, prefix = '', result = {}) {
  for (const [key, text] of Object.entries(value)) {
    const id = prefix ? prefix + '.' + key : key;
    if (typeof text === 'string') result[id] = text;
    else if (text && typeof text === 'object') flatten(text, id, result);
  }
  return result;
}
module.exports = {root, pairs, load, flatten};
if (require.main === module) {
const stack = process.argv[2];
const offset = Number(process.argv[3] || 0), limit = Number(process.argv[4] || 80);
const mode = process.argv[5] === 'same' ? 'same' : 'missing';
const results = {};
for (const [name, template] of Object.entries(pairs)) {
  if (stack && stack !== name) continue;
  const es = flatten(load(template.replace('{locale}', 'es')));
  const en = flatten(load(template.replace('{locale}', 'en')));
  const missing = Object.keys(en).filter(key => !(key in es));
  const same = Object.keys(en).filter(key => key in es && es[key] === en[key]);
  results[name] = {es: Object.keys(es).length, en: Object.keys(en).length,
    missing: missing.length, identical: same.length,
    ...(stack ? {mode, candidates: (mode === 'same' ? same : missing).slice(offset, offset + limit).map(key => ({key, en: en[key]}))} : {})};
}
console.log(JSON.stringify(results, null, 2));
}
