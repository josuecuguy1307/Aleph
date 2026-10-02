const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const i18n = read('product/app/design/i18n.js');
const html = read('product/app/design/Settings.dc.html');
const component = html.match(/class Component extends DCLogic[\s\S]*?(?=<\/script>)/)[0];
const table = read('product/app/design/espacios-tabla.js').replace(/\bexport /g, '');
const expected = {
  ciencia: ['Skills', 'Especialistas', 'Compute', 'Sandbox', 'Permisos'],
  educacion: ['Base de conocimiento', 'Co-Writer', 'Espacio de aprendizaje'],
  finanzas: ['Agente', 'Runtime', 'Programadas', 'Informes', 'Alpha Zoo', 'Matriz de correlación'],
  legal: ['Redacción', 'Investigación'], oficina: [], diseno: [],
};
for (const locale of ['es', 'en']) {
  const ctx = vm.createContext({window: {}, localStorage: {getItem: () => locale},
    document: {readyState: 'loading', documentElement: {setAttribute() {}}, addEventListener() {}},
    location: {reload() {}}, CustomEvent: function () {}, DCLogic: class {}, React: {createElement: () => ({})}});
  vm.runInContext(i18n, ctx);
  vm.runInContext(table + '; var rawSections = SECCIONES;', ctx);
  vm.runInContext(component + '; var settings = new Component();', ctx);
  const sections = {};
  for (const [ws, labels] of Object.entries(expected)) {
    const raw = ctx.rawSections[ws];
    const resolved = ctx.secciones(ws);
    assert.deepEqual(Array.from(resolved, sec => sec.rotulo), locale === 'es' ? labels : Array.from(raw, sec => sec.rotulo), ws);
    sections[ws] = resolved.map((sec, index) => {
      for (const key of ['id', 'ruta', 'panel', 'aqui']) assert.equal(sec[key], raw[index][key], 'protocol field unchanged: ' + key);
      assert.equal(ctx.hrefDeSeccion(ws, sec), ctx.hrefDeSeccion(ws, raw[index]), 'route unchanged');
      return {...sec, href: ctx.hrefDeSeccion(ws, sec)};
    });
  }
  ctx.settings.state.secciones = sections;
  let rendered = ctx.settings.renderVals();
  assert.equal(rendered.nom_pref, locale === 'es' ? 'Apariencia' : 'Appearance');
  assert.equal(rendered.nom_modelos, locale === 'es' ? 'Modelos' : 'Models');
  assert.equal(rendered.nom_perfil, locale === 'es' ? 'Perfil' : 'Profile');
  for (const group of rendered.grupos) {
    assert.deepEqual(Array.from(group.filas, fila => fila.rotulo), Array.from(sections[Object.keys(expected).find(ws => ctx.window.t('ws.' + ws + '.nombre').toUpperCase() === group.titulo)], sec => sec.rotulo));
  }
  ctx.settings.state.q = locale === 'es' ? 'apariencia' : 'appearance';
  rendered = ctx.settings.renderVals();
  assert.equal(rendered.ver_pref, true, 'search uses displayed language');
  assert.equal(rendered.ver_modelos, false);
  ctx.settings.state.q = '';
  ctx.settings.state.esp = 'legal';
  ctx.settings.state.aplican = ['legal_postura', 'legal_investigacion'];
  ctx.settings.state.declarados = {
    legal_postura: {lee_ws: ['legal'], grupo: 'Drafting', titulo: 'Postura', valores: ['balanced']},
    legal_investigacion: {lee_ws: ['legal'], grupo: 'Research', titulo: 'Investigación web', valores: ['official']},
  };
  rendered = ctx.settings.renderVals();
  assert.deepEqual(Array.from(rendered.gruposEspacio, group => group.titulo), locale === 'es' ? ['Redacción', 'Investigación'] : ['Drafting', 'Research']);
  assert.equal(rendered.gruposEspacio[0].filas[0].clave, 'legal_postura');
  assert.equal(rendered.gruposEspacio[0].filas[0].opciones[0].label, locale === 'es' ? 'Equilibrada' : 'Balanced');
  let saved;
  ctx.settings.setAjuste = (key, value) => { saved = {key, value}; };
  rendered.gruposEspacio[0].filas[0].opciones[0].pick();
  assert.deepEqual(saved, {key: 'legal_postura', value: 'balanced'}, 'stored protocol value unchanged');
}
console.log('Settings ES/EN: all 16 workspace labels, general labels, search and nested Legal groups; technical terms and routes preserved.');
