/* Exercise the actual shared renderer, with only transport/locale dependencies injected. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../product/app/design/conectores/recomendados.js'), 'utf8')
  .replace(/^import .*;$/gm, '').replace(/^export \{.*;$/gm, '').replace(/export function /g, 'function ');
for (const locale of ['es', 'en']) {
  const context = vm.createContext({
    L: (es, en) => locale === 'en' ? en : es, lang: () => locale,
    ORDEN_ETIQUETA: {ciencia: 'Ciencia'},
    window: {AlephI18n: {t: () => locale === 'en' ? 'Science' : 'Ciencia'}},
    CAUSAS_HUMANAS: {key_invalida: {es: 'Credencial inválida', en: 'Invalid credential'}},
  });
  vm.runInContext(source, context);
  const call = (text) => vm.runInContext(text, context);
  assert.equal(call('estado({tiene_llave:true,verificado:true}).txt'), locale === 'en' ? 'Tested' : 'Probada');
  assert.equal(call('estado({tiene_llave:true}).txt'), locale === 'en' ? 'Saved' : 'Guardada');
  assert.equal(call('estado({tiene_llave:false}).txt'), locale === 'en' ? 'Not configured' : 'Sin configurar');
  assert.equal(call('estado({tiene_llave:null}).listo'), '?');
  assert.equal(call("estado({tiene_llave:true,verificado:false,verificado_falla:'key_invalida'}).txt"), locale === 'en' ? 'Invalid credential' : 'Credencial inválida');
  assert.equal(call("capacidad({es:'Listo — ya puedo buscar.',en:'Done — I can now search.'},false)"), locale === 'en' ? 'Can search.' : 'Puede buscar.');
  assert.match(call("selloDe({listo:'si',cuando:'2026-09-11',con:'provider_id'})"), /2026-09-11.*provider_id/);
  assert.equal(call("nombreEspacio('ciencia')"), locale === 'en' ? 'Science' : 'Ciencia');
  const selector = {innerHTML: ''};
  context.nodes = {selector, filas: {}};
  call("montarRecomendados(nodes,{workspaces:['ciencia']})");
  assert.match(selector.innerHTML, /value="ciencia"/);
  assert.match(selector.innerHTML, locale === 'en' ? />Science</ : />Ciencia</);
}
console.log('Shared connector renderer: ES/EN passed; status facts, IDs and dates preserved.');
