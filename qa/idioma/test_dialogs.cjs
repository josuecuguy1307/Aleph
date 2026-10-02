const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').resolve(__dirname,'../../product/app/design/i18n.js'),'utf8');
for(const lang of ['es','en']){
  const calls=[];const window={};
  for(const name of ['alert','confirm','prompt'])window[name]=(...args)=>{calls.push([name,...args]);return name==='confirm'?false:null};
  const context={window,localStorage:{getItem:()=>lang},document:{readyState:'loading',
    documentElement:{setAttribute(){}},addEventListener(){}},location:{reload(){}},CustomEvent:function(){}};
  vm.runInNewContext(source,context);
  window.prompt('Editar recuerdo:','Sos el usuario: contenido intacto');
  assert.equal(calls[0][1],lang==='en'?'Edit memory:':'Editar recuerdo:');
  assert.equal(calls[0][2],'Sos el usuario: contenido intacto');
  assert.equal(window.confirm('¿Quitar la key de "provider-id"?'),false);
  assert.equal(calls[1][1],lang==='en'?'Remove the key for "provider-id"?':'¿Quitar la key de "provider-id"?');
  window.alert('No se pudo guardar la key (401).');
  assert.equal(calls[2][1],lang==='en'?'Could not save the key (401).':'No se pudo guardar la key (401).');
  const group=window.t('set.grupo.vacio.sub',{nombre:lang==='en'?'Office':'Oficina'});
  assert.ok(group.includes(lang==='en'?'Office':'Oficina'));assert.ok(!group.includes('{nombre}'));
  assert.equal(window.t('biblioteca.day_none'),lang==='en'?'no activity':'sin actividad');
  assert.equal(window.t('biblioteca.day_many',{n:3}),lang==='en'?'3 items':'3 cosas');
  assert.equal(window.t('biblioteca.outputs_period',{n:18}),lang==='en'?'outputs · latest 18 weeks':'resultados · últimas 18 semanas');
  assert.equal(window.t('biblioteca.day_outputs',{n:3}),lang==='en'?'3 outputs · all Alephs':'3 resultados · todos los Aleph');
  assert.equal(window.t('biblioteca.output_count',{n:3}),lang==='en'?'3 outputs':'3 resultados');
  assert.equal(window.t('inspect.args_ph'),lang==='en'?'-y\n@your/mcp-server':'-y\n@tu/mcp-server');
  assert.equal(window.t('ws.connectors.aria'),lang==='en'?'Connectors for this workspace':'Conectores de este espacio');
  assert.equal(window.t('ws.office.approval_title'),lang==='en'?'Save file':'Guardar archivo');
}
console.log('Locale/dialog and dynamic shell assertions per language: passed');
