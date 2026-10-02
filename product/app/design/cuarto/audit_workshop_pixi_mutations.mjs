#!/usr/bin/env node
// Read-only inventory. Uses the parser already bundled with the browser harness;
// no dependency installation, app execution, account access, or source mutation.
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname, relative, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url);
const { babelParse, traverse } = require(join(dirname(require.resolve("playwright/package.json")), "lib/transform/babelBundle.js"));
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const entry = join(root, "cuarto/cuarto.pixi.html");
const seen = new Set(), queue = [], documents = [];
function add(file) {
  if (!file.startsWith(root + "/") || seen.has(file) || !existsSync(file) || /\/vendor\/|\.min\.js$/.test(file)) return;
  seen.add(file); queue.push(file);
}
add(entry);
while (queue.length) {
  const file = queue.shift(), source = readFileSync(file, "utf8"), parts = [];
  if (file.endsWith(".html")) {
    for (const match of source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      const external = match[1].match(/src=["']([^"']+)/);
      if (external) { add(resolve(dirname(file), external[1].split("?")[0])); continue; }
      if (match[2].trim()) parts.push({ file, source: match[2], offset:
        source.slice(0, match.index + match[0].indexOf(">") + 1).split("\n").length - 1 });
    }
  } else parts.push({ file, source, offset: 0 });
  documents.push(...parts);
  for (const part of parts) {
    for (const match of part.source.matchAll(/(?:from\s*|import\s*\(\s*|import\s*)["'](\.[^"']+)["']/g))
      add(resolve(dirname(file), match[1].split("?")[0]));
  }
}
const markers = {};
for (const file of seen) {
  for (const match of readFileSync(file, "utf8").matchAll(/<[^>]+\bid=["']([^"']+)["'][^>]*>/g)) {
    const attributes = Object.fromEntries([...match[0].matchAll(/(data-i18n(?:-[\w-]+)?)=["']([^"']+)["']/g)]
      .map((m) => [m[1], m[2]]));
    if (Object.keys(attributes).length) (markers["#" + match[1]] ||= []).push(attributes);
  }
}
let locale = "es";
const runtime = { window: {}, document: { readyState: "loading", documentElement: { setAttribute() {} }, addEventListener() {} },
  localStorage: { getItem: () => locale }, sessionStorage: { getItem: () => null } };
runInNewContext(readFileSync(join(root, "i18n.js"), "utf8"), runtime);
const i18n = runtime.window.AlephI18n, mutations = [], missingKeys = [];
const keyPattern = /["']((?:workshop|brain|cuarto|nav|sala|chat)\.[^"']+)["']/g;
const contracts = {
  "#ikind": ["workshop.item.core", "workshop.item.connection", "workshop.item.knowledge", "workshop.item.gate", "workshop.item.agent", "workshop.item.memory", "workshop.item.tool"],
  "#iprimary": ["workshop.action.view_connection", "workshop.action.view_connection_external", "workshop.action.connection_destination", "workshop.action.choose_model", "workshop.action.edit", "workshop.action.adjust"],
  "#modoState": ["workshop.view.mcp_mode", "workshop.view.work_mode", "workshop.view.work_mode_one"],
  "#modoBtn": ["workshop.view.mode_mcp_title", "workshop.view.mode_work_title"],
  "#multiModeState": ["workshop.view.multi_none", "workshop.view.chain", "workshop.view.orchestration", "workshop.view.office", "workshop.view.fan"],
  "#saveBtn": ["workshop.action.save", "workshop.agent.save_busy"],
  "#gateOk": ["workshop.gate.approve", "workshop.gate.blocked"],
};
for (const part of documents) {
  const ast = babelParse(part.source, part.file, true);
  function syntax(p) { return p?.node ? part.source.slice(p.node.start, p.node.end) : ""; }
  function target(p, depth = 0) {
    if (!p?.node || depth > 7) return "unresolved: " + syntax(p);
    const n = p.node;
    if (n.type === "Identifier") {
      const binding = p.scope.getBinding(n.name);
      if (binding?.path.isVariableDeclarator() && binding.path.node.init) return target(binding.path.get("init"), depth + 1);
      if (binding) for (const ref of binding.referencePaths) {
        const member = ref.parentPath, assignment = member?.parentPath;
        if (member?.isMemberExpression() && member.node.property.name === "id" && assignment?.isAssignmentExpression()
          && assignment.node.right.type === "StringLiteral") return "#" + assignment.node.right.value;
      }
      return "alias: " + n.name;
    }
    if (n.type === "CallExpression") {
      const callee = n.callee, arg = n.arguments[0];
      if (arg?.type === "StringLiteral") {
        if (callee.type === "Identifier" && callee.name === "$") return "#" + arg.value;
        if (callee.type === "MemberExpression") {
          if (callee.property.name === "getElementById") return "#" + arg.value;
          if (["querySelector", "querySelectorAll", "closest"].includes(callee.property.name))
            return target(p.get("callee").get("object"), depth + 1) + " " + arg.value;
        }
      }
    }
    return syntax(p);
  }
  function record(p, object, operation, value) {
    const parentFunction = p.findParent((x) => x.isFunction());
    const functionName = parentFunction ? parentFunction.node.id?.name || parentFunction.parentPath.node.id?.name || "anonymous" : "top-level";
    let node = target(object), owner = "local renderer";
    const file = relative(root, part.file);
    if (file === "brain-status.js" && functionName === "render" && node.startsWith("alias: el")) {
      node = node.replace("alias: el", "#cuartoBrainDock"); owner = "AlephBrain.render (caller-owned fixed markers forbidden)";
    }
    if (file === "cuarto/cuarto.semaforo.js" && functionName === "pintarBadge" && node === "alias: el") {
      node = "#guideSemMount / #pieceSemMount / runtime .sem-mount"; owner = "Sem.pintarBadge; ESTADOS/CAUSAS/CAMINOS bilingual tables + AlephI18n";
    }
    if (file === "conexiones/cuarto.hook.js" && node === "alias: prim") node = "#iprimary";
    const expression = syntax(value);
    const initialKeys = markers[node] || [];
    const refs = new Set([...expression.matchAll(keyPattern)].map((m) => m[1]));
    for (const attributes of initialKeys) for (const key of Object.values(attributes)) refs.add(key);
    for (const key of contracts[node] || []) refs.add(key);
    // For renderer-owned composed attributes include every key in that function.
    if (owner !== "local renderer") for (const match of syntax(parentFunction).matchAll(keyPattern)) refs.add(match[1]);
    const translations = {};
    for (const key of refs) {
      if (key.endsWith(".")) continue;
      const translated = {};
      for (const lang of ["es", "en"]) { locale = lang; translated[lang] = i18n.t(key); }
      translations[key] = translated;
      if (translated.es === key || translated.en === key) missingKeys.push({ file, line: p.node.loc.start.line + part.offset, key });
    }
    mutations.push({ file, line: p.node.loc.start.line + part.offset, function: functionName, node, operation,
      expression, initialRootKeys: initialKeys, correctKeyContract: contracts[node] ||
        (owner !== "local renderer" ? "composed by owner; no static key on root" :
          (initialKeys.length ? "unchanged unrelated attribute or renderer-maintained key; see expression" :
            "no fixed root key; generated children / existing translator / runtime data")),
      owner, translations });
  }
  traverse(ast, {
    AssignmentExpression(p) {
      const left = p.get("left"); if (!left.isMemberExpression()) return;
      const property = left.node.property.name || left.node.property.value;
      if (["textContent", "innerText", "innerHTML", "title", "ariaLabel", "nodeValue"].includes(property))
        record(p, left.get("object"), p.node.operator + " " + property, p.get("right"));
      if (left.node.object.type === "MemberExpression" && left.node.object.property.name === "dataset" && /i18n/.test(property || ""))
        record(p, left.get("object").get("object"), "dataset." + property, p.get("right"));
    },
    CallExpression(p) {
      const callee = p.get("callee"); if (!callee.isMemberExpression()) return;
      const method = callee.node.property.name, attr = p.node.arguments[0]?.value;
      if (["setAttribute", "removeAttribute"].includes(method) &&
        (attr === undefined || ["title", "aria-label"].includes(attr) || /^data-i18n/.test(attr || "")))
        record(p, callee.get("object"), method + " " + (attr ?? "[dynamic: " + syntax(p.get("arguments")[0]) + "]"), p.get("arguments")[1]);
      if (method === "insertAdjacentHTML") record(p, callee.get("object"), method, p.get("arguments")[1]);
    },
  });
}
console.log(JSON.stringify({ entry: relative(root, entry), files: [...seen].map((f) => relative(root, f)),
  scope: "First-party static/dynamic relative imports; DOM writes, attribute writes, template replacement and insertion. Vendor code excluded. Alias targets are explicitly retained, not invented selectors.",
  mutations, missingKeys }, null, 2));
if (missingKeys.length) process.exitCode = 1;
