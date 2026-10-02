const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const chip = fs.readFileSync(path.join(root, 'product/app/design/ui/model-chip.core.js'), 'utf8');
for (const locale of ['es', 'en']) {
  for (const house of [true, false]) {
    const ctx = vm.createContext({window: house ? {AlephI18n: {lang: () => locale}} : {},
      document: {documentElement: {lang: house ? 'opposite-unused' : locale}}});
    vm.runInContext(chip, ctx);
    assert.equal(vm.runInContext("copy('Modelo','Model')", ctx), locale === 'en' ? 'Model' : 'Modelo');
    assert.match(vm.runInContext('detalle({cost:{free:true}})', ctx), locale === 'en' ? /free/ : /gratis/);
  }
}
const nav = fs.readFileSync(path.join(root, 'product/app/design/nav.js'), 'utf8');
const href = nav.match(/function href\(id\)\s*\{[^]*?\n  \}/)[0];
for (const assetBase of ['http://127.0.0.1:8330/', 'file:///app/design/']) {
  const ctx = vm.createContext({assetBase, up: '', _pup: 'user ref/1', _CARRY: {'Cuarto.dc.html':1}});
  vm.runInContext(href, ctx);
  assert.equal(vm.runInContext("href('Settings.dc.html')", ctx), assetBase+'Settings.dc.html');
  assert.equal(vm.runInContext("href('Cuarto.dc.html')", ctx), assetBase+'Cuarto.dc.html?puppet=user%20ref%2F1');
}
const brain = fs.readFileSync(path.join(root, 'product/app/design/brain-status.js'), 'utf8');
const settings = fs.readFileSync(path.join(root,'product/app/design/Settings.dc.html'),'utf8');
const formatNumber = settings.match(/const _num=\(n\)=> [^;]+;/)[0];
for (const locale of ['es','en']) {
  const ctx = vm.createContext({_curLang:locale,s:{lang:locale==='en'?'es':'en'}});
  vm.runInContext(formatNumber + '; var renderedNumber = _num(2.8);',ctx);
  assert.equal(ctx.renderedNumber,locale==='en'?'2.8':'2,8');
}
assert.equal((brain.match(/label: t\("brain.action.cuarto", "Elegir o reparar el modelo"\)/g) || []).length, 2,
  'normal and fallback compact status must both use the existing translated key');
const render = brain.slice(brain.indexOf('  function render('), brain.indexOf('  function mount('));
for (const locale of ['es', 'en']) {
  const nodes = {};
  const el = {dataset: {}, setAttribute() {}, querySelector(selector) {
    return nodes[selector] || (nodes[selector] = {setAttribute() {}});
  }};
  const ctx = vm.createContext({installCss() {}, stateClass: () => 'ok', stateLabel: () => 'connected',
    POWER: {}, t: (_key, fallback) => fallback, location: {}, el,
    status: {id: 'codex_cli', active: 'codex_cli', label: 'Codex', action: {
      label: locale === 'en' ? 'Connect a model' : 'Conectar modelo', href: '/Settings.dc.html'}}});
  vm.runInContext(render + '\nrender(el, status, {});', ctx);
  assert.equal(nodes['.aleph-brain-action'].textContent,
    locale === 'en' ? 'Connect a model' : 'Conectar modelo');
  assert.ok(!el.innerHTML.includes('>Conectar modelo<'), 'compact action must use the resolved status copy');
}
console.log('Actual shared UI helpers: house/workspace locale and nested navigation passed.');
