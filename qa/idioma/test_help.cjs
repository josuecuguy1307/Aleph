const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const root = path.resolve(__dirname, '../..');
const i18n = fs.readFileSync(path.join(root, 'product/app/design/i18n.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'product/app/design/Ayuda.dc.html'), 'utf8');
const component = html.match(/class Component extends DCLogic[\s\S]*?(?=<\/script>)/)[0];
for (const locale of ['es', 'en']) {
  const ctx = vm.createContext({window:{}, localStorage:{getItem:()=>locale},
    document:{readyState:'loading',documentElement:{setAttribute(){}},addEventListener(){}},
    location:{reload(){}},CustomEvent:function(){}, DCLogic:class {}, React:{createElement:()=>({})}});
  vm.runInContext(i18n, ctx);
  vm.runInContext(component+'; var help = new Component();', ctx);
  const help = ctx.help;
  for (const [es,en] of [['🔒 Pide tu OK para enviar el correo','🔒 Asks for your approval before sending the email'],
    ['Aprobar','Approve'],['Rechazar','Reject'],['activa','active'],
    ['Idioma','Language'],['Compacto','Compact'],['Estándar','Standard'],['Grande','Large'],
    ['Conviértelo a USD','Convert it to USD'],['Resúmelo en 3 puntos','Summarize it in 3 points']]) {
    assert.equal(ctx.window.AlephI18n.text(es),locale==='en'?en:es,'article mini-capture copy');
  }
  help.state.query = locale === 'en' ? 'spreadsheet' : 'hojas';
  assert.ok(help.renderVals().results.length > 0, 'search must index rendered locale');
  for (const article of help.allArticles()) {
    assert.equal(article.id.length, 2, 'article ID unchanged');
    if (locale === 'en') assert.ok(!/Empezar|Armar|Conectar|Aprobar|Usar|Retomar|frenó|permisos/.test(article.title+' '+article.cat));
  }
  for (const data of Object.values(help.articleData)) {
    const fields = [data.cat,data.read,data.title,data.intro,...data.steps.flatMap(s=>[s.title,s.body,s.shotLabel])];
    for (const raw of fields) {
      const rendered = ctx.window.AlephI18n.text(raw);
      if (locale === 'es') assert.equal(rendered, raw);
      else if (raw !== 'Settings · API keys') assert.notEqual(rendered,raw,'missing article translation: '+raw);
    }
  }
  help.state.chatMsgs = [{from:'user',text:'Conectores'},
    {from:'bot',text:'Para todo lo que sale al mundo (enviar, gastar, borrar) el Aleph te pide OK primero. Aquí lo explico:'}];
  const messages = help.renderVals().chatMsgs;
  assert.equal(messages[0].text,'Conectores','user content unchanged');
  assert.equal(messages[1].text, ctx.window.AlephI18n.text(help.state.chatMsgs[1].text));
  assert.equal(ctx.window.AlephI18n.text('sesión activa hace 2s'),locale==='en'?'active session 2s ago':'sesión activa hace 2s');
  assert.equal(ctx.window.AlephI18n.text('sesión activa (grok.com)'),locale==='en'?'active session (grok.com)':'sesión activa (grok.com)');
  assert.equal(ctx.window.AlephI18n.text('sesión activa (max)'),locale==='en'?'active session (max)':'sesión activa (max)');
  assert.equal(ctx.window.AlephI18n.text('tier técnico: frontier'),locale==='en'?'technical tier: frontier':'tier técnico: frontier');
  assert.equal(ctx.window.AlephI18n.text('Disco y RAM'),locale==='en'?'Disk & RAM':'Disco y RAM');
  assert.equal(ctx.window.AlephI18n.text('Volver a la lista'),locale==='en'?'Back to list':'Volver a la lista');
  assert.equal(ctx.window.AlephI18n.text('probado · sesión activa (ChatGPT) · hace 2s'),locale==='en'?'tested · active session (ChatGPT) · 2s ago':'probado · sesión activa (ChatGPT) · hace 2s');
  assert.equal(ctx.window.t('biblioteca.produced_one'),locale==='en'?'thing produced':'cosa producida');
}
assert.match(html,/<span data-no-tm>\{\{ m.text \}\}<\/span>/);
const dir = path.join(root,'catalog/connectors/onboarding');
for (const file of fs.readdirSync(dir).filter(f=>f.endsWith('.json'))) {
  const record = JSON.parse(fs.readFileSync(path.join(dir,file),'utf8'));
  assert.ok(record.en, 'missing English onboarding: '+file);
  if (record.en.credential_fields) assert.deepEqual(record.en.credential_fields.map(f=>f.key),record.credential_fields.map(f=>f.key),'credential IDs unchanged');
}
console.log('Help renderer/search/user-content, dynamic statuses and 29 English onboarding records passed.');
const surface = fs.readFileSync(path.join(root,'product/app/design/conectores/superficie.js'),'utf8');
const reserve = surface.slice(surface.indexOf('export function bloqueReserva'),surface.indexOf('/** EL PANEL')).replace('export ','');
for (const locale of ['es','en']) {
  const ctx = vm.createContext({L:(es,en)=>locale==='en'?en:es,esc:s=>s});
  vm.runInContext(reserve,ctx);
  const notice = 'No se pudo confirmar la identidad del namespace que publicó esta pieza.';
  const rendered = ctx.bloqueReserva({entityId:'unchanged-id',reserva:{texto_1linea:notice,detalle:'Señal del matcher: 0.338.'}});
  assert.ok(rendered.includes(locale==='en'?'Could not verify the identity':notice));
  assert.ok(rendered.includes(locale==='en'?'Matcher score: 0.338.':'Señal del matcher: 0.338.'));
  assert.ok(ctx.bloqueReserva({entityId:'unchanged-id',reserva:{texto_1linea:'Mi texto intacto'}}).includes('Mi texto intacto'));
}
console.log('Known import notices localized; IDs, numeric evidence and unknown text preserved.');
