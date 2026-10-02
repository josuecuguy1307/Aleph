const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const i18n = fs.readFileSync(path.join(root, 'product/app/design/i18n.js'), 'utf8');
const home = fs.readFileSync(path.join(root, 'product/app/design/Home.dc.html'), 'utf8');
const component = home.match(/class Component extends DCLogic[\s\S]*?(?=<\/script>)/)[0];
for (const locale of ['es', 'en']) {
  const ctx = vm.createContext({window: {}, localStorage: {getItem: () => locale},
    document: {readyState: 'loading', documentElement: {setAttribute() {}}, addEventListener() {}},
    location: {reload() {}}, CustomEvent: function () {}, DCLogic: class {}, React: {createElement: () => ({})}});
  vm.runInContext(i18n, ctx);
  vm.runInContext(component + '; var home = new Component();', ctx);
  const name = locale === 'en' ? 'The Room' : 'La Sala';
  for (const key of ['nav.sala', 'salav2.titulo', 'sala.sb.sala']) assert.equal(ctx.window.t(key), name, key);
  assert.equal(ctx.window.t('salav2.title'), name + ' · Aleph');
  const card = ctx.home.renderVals().espacios[0];
  assert.equal(card.nombre, name, 'actual Home renderer must localize the name');
  assert.equal(card.href, 'sala-v2/sala-v2.html', 'route unchanged');
  assert.equal(card.sub, locale === 'en' ? 'Conversations and general work' : 'Conversaciones y trabajo general');
  assert.equal(ctx.window.AlephI18n.text('Sala · adjuntar'), locale === 'en' ? 'The Room · attach' : 'Sala · adjuntar');
  assert.equal(ctx.window.AlephI18n.text('Mi conversación La Sala'), 'Mi conversación La Sala', 'unknown/user text unchanged');
}
console.log('Home renderer, navigation, heading, title and help: The Room EN / La Sala ES; route and unknown text preserved.');
