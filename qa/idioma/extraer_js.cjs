// AST extraction only: literals/JSX and comments are never conflated.
const fs = require('fs');
const ts = require('../../third_party/deeptutor/web/node_modules/typescript');
const files = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = [];
for (const item of files) {
  const source = item.source ?? fs.readFileSync(item.path, 'utf8');
  const tree = ts.createSourceFile(item.path, source, ts.ScriptTarget.Latest, true,
    item.path.endsWith('tsx') || item.path.endsWith('jsx') ? ts.ScriptKind.TSX : ts.ScriptKind.JS);
  const line = pos => tree.getLineAndCharacterOfPosition(pos).line + 1 + (item.offset || 0);
  function visit(node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ||
        ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node) ||
        ts.isJsxText(node)) {
      out.push({path: item.path, line: line(node.getStart(tree)), endLine:line(node.getEnd()), kind: 'string', text: node.text});
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, false, ts.LanguageVariant.Standard, source);
  for (let token = scanner.scan(); token !== ts.SyntaxKind.EndOfFileToken; token = scanner.scan()) {
    if (token === ts.SyntaxKind.SingleLineCommentTrivia || token === ts.SyntaxKind.MultiLineCommentTrivia) {
      out.push({path: item.path, line: line(scanner.getTokenPos()), kind: 'comment', text: scanner.getTokenText()});
    }
  }
}
process.stdout.write(JSON.stringify(out));
