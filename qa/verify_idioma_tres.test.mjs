import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");
const flatten = (value, prefix = "") => Object.fromEntries(
  Object.entries(value).flatMap(([key, item]) => {
    const full = prefix ? `${prefix}.${key}` : key;
    return item && typeof item === "object"
      ? Object.entries(flatten(item, full)) : [[full, item]];
  }),
);

const sources = {
  education: ["third_party/deeptutor/web/locales/en/app.json", "third_party/deeptutor/web/locales/es/app.json"],
  educationCommon: ["third_party/deeptutor/web/locales/en/common.json", "third_party/deeptutor/web/locales/es/common.json"],
  finance: ["third_party/vibetrading/frontend/src/i18n/locales/en.json", "third_party/vibetrading/frontend/src/i18n/locales/es.json"],
  legal: ["third_party/dochaus/apps/web/src/locales/en.json", "third_party/dochaus/apps/web/src/locales/es.json"],
};
const locales = Object.fromEntries(Object.entries(sources).map(([name, files]) =>
  [name, files.map((file) => flatten(JSON.parse(read(file))))],
));
const tokens = (value, pattern) => [...value.matchAll(pattern)].map((match) => match[0]).sort();
const brands = /\b(?:Codex|Claude Code|Volcengine|Seedream|Seedance|Perplexity|PageIndex|Brave|HuggingFace|LlamaIndex|MinerU|Docling|markitdown|OpenAI|OpenRouter|SiliconFlow|Groq|Qwen|Ollama|Tavily|SearXNG|AKShare|TradingView|Microsoft)\b/g;
const identifiers = /\b(?:[a-z][a-z0-9]+(?:_[a-z0-9]+)+|[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b/g;
const paths = /(?:\/(?:api|images)\/[A-Za-z0-9_./-]+|data\/user\/[A-Za-z0-9_./-]+)/g;

for (const [name, [en, es]] of Object.entries(locales)) {
  test(`${name}: complete key and interpolation parity`, () => {
    assert.deepEqual(Object.keys(es).sort(), Object.keys(en).sort());
    for (const [key, value] of Object.entries(en)) {
      assert.equal(typeof es[key], "string", key);
      assert.ok(es[key].trim(), key);
      assert.doesNotMatch(es[key], /(Co-){3,}/, key);
      assert.deepEqual(tokens(es[key], /\{\{[^}]+\}\}/g), tokens(value, /\{\{[^}]+\}\}/g), key);
    }
  });
  test(`${name}: preserve tool IDs, API paths, code literals and brands`, () => {
    const errors = [];
    for (const [key, value] of Object.entries(en)) {
      for (const pattern of [brands, identifiers, paths]) {
        for (const token of tokens(value, pattern)) {
          // A sentence-ending period is not part of a path.
          const literal = pattern === paths ? token.replace(/\.$/, "") : token;
          if (!es[key].includes(literal)) errors.push(`${key}: ${literal}`);
        }
      }
      // Match complete Markdown delimiters, including double/triple backticks.
      // A single-backtick regex also captures prose between double delimiters.
      for (const match of value.matchAll(/(?<!`)(`+)([^`]+)\1(?!`)/g)) {
        if (!es[key].includes(match[0])) errors.push(`${key}: ${match[0]}`);
      }
      if (/^[mM]\d|^rotate\(/.test(value)) assert.equal(es[key], value, key);
      for (const token of tokens(value, /\/(?:resume|delete)\b/g)) assert.ok(es[key].includes(token), `${key}: ${token}`);
    }
    assert.deepEqual(errors, []);
  });
  test(`${name}: no regional voseo in Spanish UI copy`, () => {
    for (const [key, value] of Object.entries(es)) {
      assert.doesNotMatch(value, /\b(?:vos|sos|tenés|podés|querés|hacés|decime|contame|fijate|hacelo|ponelo|mostrame|mirá|probá|pegá|copiá|tocá|poné|hacé|corré|respondé|elegí|abrí)\b/iu, key);
    }
  });
}

test("education: editor, memory and indexing labels are translated", () => {
  const [en, es] = locales.education;
  assert.equal(es["Co-Writer"], "Editor colaborativo");
  assert.equal(es["Play aloud"], "Leer en voz alta");
  assert.equal(es["Show {{count}} more"], "Mostrar {{count}} más");
  assert.match(read("third_party/deeptutor/web/components/sidebar/SidebarShell.tsx"), /t\("Show \{\{count\}\} more"/);
  for (const key of ["AI Edit Assistant", "AI Mark", "Podcast Audio", "Strikethrough", "Blockquote", "Round {{n}}", "Tour", "Re-index", "Quiz", "AI Judge", "Dedup", "Demote", "Pinned"]) {
    assert.notEqual(es[key], en[key], key);
  }
});

test("education: all source translation keys and bilingual labels have English/Spanish entries", () => {
  const web = path.join(root, "third_party/deeptutor/web");
  const ts = createRequire(path.join(web, "package.json"))("typescript");
  const dictionaries = [0, 1].map((i) => ({ ...locales.education[i], ...locales.educationCommon[i] }));
  const missing = new Set();
  const check = (node, filename) => {
    if (!node || !ts.isStringLiteralLike(node)) return;
    for (const [i, dict] of dictionaries.entries()) {
      if (!Object.hasOwn(dict, node.text)) missing.add(`${i === 0 ? "en" : "es"}: ${node.text} (${path.relative(web, filename)})`);
    }
  };
  const scan = (dir) => {
    for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
      const filename = path.join(dir, item.name);
      if (item.isDirectory()) {
        if (!["node_modules", ".next", "__tests__"].includes(item.name)) scan(filename);
      } else if (/\.[jt]sx?$/.test(filename) && !/\.(?:test|spec)\./.test(filename)) {
        const source = ts.createSourceFile(filename, fs.readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true);
        const visit = (node) => {
          if (ts.isCallExpression(node)) {
            const name = ts.isIdentifier(node.expression) ? node.expression.text
              : ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text : "";
            if (name === "t") check(node.arguments[0], filename);
            if (name === "tr" && node.arguments.length === 2) check(node.arguments[1], filename);
          }
          if (ts.isPropertyAssignment(node) && node.name.getText(source) === "en") check(node.initializer, filename);
          ts.forEachChild(node, visit);
        };
        visit(source);
      }
    }
  };
  for (const dir of ["app", "components", "src", "lib"]) {
    if (fs.existsSync(path.join(web, dir))) scan(path.join(web, dir));
  }
  assert.deepEqual([...missing].sort(), []);
  for (const file of ["settings/SettingsBreadcrumb", "settings/SettingsHub", "settings/SettingsSectionGrid", "settings/SubagentSettingsEditor", "agents/ConnectedAgents", "space/SpaceDashboard"]) {
    assert.match(read(`third_party/deeptutor/web/components/${file}.tsx`), /zh \? l\.zh : t\(l\.en\)/, file);
  }
});

test("education: tool catalog display prose is localized without changing schemas", () => {
  const catalog = JSON.parse(read("qa/fixtures/education_tool_catalog.json"));
  assert.equal(catalog.length, 40);
  for (const tool of catalog) for (const key of tool.keys) {
    assert.ok(locales.education[0][key], key);
    assert.ok(locales.education[1][key], key);
    assert.notEqual(locales.education[1][key], locales.education[0][key], key);
  }
  const page = read("third_party/deeptutor/web/app/(utility)/settings/tools/page.tsx");
  assert.ok(page.includes('t(`toolHints.${tool.name}.${field}`'));
  assert.ok(page.includes('t(`toolParams.${tool.name}.${p.name}`'));
  assert.ok(page.includes('{tool.name}'));
  assert.ok(page.includes('{p.name}'));
});

test("finance: technical UI labels and terminology are translated", () => {
  const [en, es] = locales.finance;
  for (const key of ["settings.apiAuthKey", "settings.maxRetries", "settings.scheduler", "runDetail.maxDrawdown", "runDetail.rebalanceCount", "runDetail.totalPnl", "validation.bootstrap", "validation.avgSharpe", "runnerStatus.runner", "home.featureAgent"]) {
    assert.notEqual(es[key], en[key], key);
  }
  assert.equal(es["compare.sharpeRatio"], "Ratio de Sharpe");
  assert.equal(es["pineViewer.pineScript"], "Pine Script v6");
  const frame = read("third_party/vibetrading/frontend/src/components/layout/aleph-frame.tsx");
  assert.match(frame, /t\("layout.home"\)/);
  assert.match(frame, /t\("layout.settings"\)/);
  const layout = read("third_party/vibetrading/frontend/src/components/layout/Layout.tsx");
  assert.match(layout, /texto=\{t\("layout.recentSessions"\)\}/);
  assert.match(layout, /t\("layout.moreIn"/);
  assert.match(layout, /t\("runDetail.showMore"/);
  assert.doesNotMatch(layout, /aria-label="Select language"/);
});

test("legal: bilingual frame, formal upload copy and protected document content", () => {
  assert.equal(locales.legal[1]["⌘⇧F"], locales.legal[0]["⌘⇧F"]);
  assert.equal(locales.legal[1]["concise"], "conciso");
  assert.match(read("third_party/dochaus/apps/web/src/components/Settings.tsx"), /<option key=\{x\} value=\{x\}>\{t\(x\)\}/);
  assert.ok(read("third_party/dochaus/apps/web/src/i18n.tsx").includes('window.parent !== window ? window.sessionStorage.getItem("aleph.aleph_lang") : null'));
  assert.equal(locales.legal[0]["‹ Home"], "‹ Home");
  assert.equal(locales.legal[1]["‹ Home"], "‹ Inicio");
  assert.match(read("third_party/dochaus/apps/web/src/components/aleph-frame.tsx"), /t\("‹ Home"\)/);
  assert.match(read("third_party/dochaus/apps/web/src/components/DocumentUpload.tsx"), /useLanguage/);
  assert.match(read("third_party/dochaus/apps/web/src/i18n.tsx"), /element\.closest\("\.msg, \.docx-render, \[data-no-translate\]"\)\) continue/);
  for (const [key, value] of Object.entries(locales.legal[1])) {
    assert.doesNotMatch(value, /\b(?:puedes|tienes|estás|arrastra|haz clic)\b/iu, key);
  }
});
