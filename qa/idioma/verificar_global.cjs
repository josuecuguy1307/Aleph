// Static locale coverage: no browser, no user content, no runtime mutation.
const fs = require('fs');
const cp = require('child_process');
const vm = require('vm');
const ts = require('../../third_party/deeptutor/web/node_modules/typescript');
const root = require('path').resolve(__dirname, '../..');
process.chdir(root);
const source = fs.readFileSync('product/app/design/i18n.js', 'utf8');
const tree = ts.createSourceFile('i18n.js', source, ts.ScriptTarget.Latest, true);
let dict;
function find(n) {
  if (ts.isVariableDeclaration(n) && n.name.getText(tree) === 'DICT')
    dict = vm.runInNewContext('(' + n.initializer.getText(tree) + ')');
  ts.forEachChild(n, find);
}
find(tree);
const prefixes = new Set(Object.keys(dict.es).map(k=>k.split('.')[0]));
const paths = cp.execFileSync('git', ['ls-files', '-z', 'product/app/design'], {encoding:'utf8',maxBuffer:8*1024*1024}).split('\0')
  .filter(p => p.startsWith('product/app/design/') && /\.(html|js|mjs)$/.test(p)
    && !/\/screenshots\/|\/verify|\/vendor\//.test(p));
const refs = [];
function parse(path, text, offset=0) {
  const ast = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  function visit(n) {
    // Runtime tables pass their first tuple member to the existing translator.
    if (ts.isArrayLiteralExpression(n)) {
      const a = n.elements[0];
      if (a && ts.isStringLiteral(a) && /^[a-z][a-z0-9_]*\.[a-z0-9_.]+$/.test(a.text)
          && prefixes.has(a.text.split('.')[0]) && !a.text.endsWith('.js'))
        refs.push({path,line:ast.getLineAndCharacterOfPosition(a.getStart(ast)).line+1+offset,key:a.text,
          fallback:n.elements[1]?.getText(ast)});
    }
    if (ts.isCallExpression(n)) {
      const a = n.arguments[0];
      if (a && ts.isStringLiteral(a) && /^[a-z][a-z0-9_]*\.[a-z0-9_.]+$/.test(a.text)
          && prefixes.has(a.text.split('.')[0]) && !a.text.endsWith('.js'))
        refs.push({path, line:ast.getLineAndCharacterOfPosition(a.getStart(ast)).line+1+offset, key:a.text,
          fallback:n.arguments[1]?.getText(ast)});
    }
    if (ts.isPropertyAssignment(n) && n.name.getText(ast) === 'key' && ts.isStringLiteral(n.initializer)
        && /^nav\./.test(n.initializer.text))
      refs.push({path,line:ast.getLineAndCharacterOfPosition(n.getStart(ast)).line+1+offset,key:n.initializer.text});
    ts.forEachChild(n, visit);
  }
  visit(ast);
}
for (const path of paths) {
  const text = fs.readFileSync(path, 'utf8');
  if (path.endsWith('.html')) {
    const clean = text.replace(/<!--[\s\S]*?-->/g, m => m.replace(/[^\n]/g, ' '));
    for (const m of clean.matchAll(/data-i18n(?:-ph|-title|-aria)?=["']([^"']+)["']/g))
      refs.push({path,line:clean.slice(0,m.index).split('\n').length,key:m[1]});
    for (const m of clean.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))
      parse(path, m[1], clean.slice(0,m.index+ m[0].indexOf(m[1])).split('\n').length-1);
  } else parse(path,text);
}
const missing = refs.filter(r => !(r.key in dict.es) || !(r.key in dict.en));
const parity = [...new Set([...Object.keys(dict.es),...Object.keys(dict.en)])]
  .filter(k => !(k in dict.es) || !(k in dict.en));
console.log(JSON.stringify({files:paths.length, es:Object.keys(dict.es).length,
  en:Object.keys(dict.en).length, references:refs.length, parity, missing}, null,2));
if (missing.length || parity.length) process.exitCode=1;
