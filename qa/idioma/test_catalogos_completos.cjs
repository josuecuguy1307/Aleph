const assert = require('node:assert/strict');
const {pairs, load, flatten} = require('./censo_vocabulario.cjs');
const markers = text => Array.from(text.matchAll(/\{\{?([\w.]+)\}?\}/g), match => match[0]).sort();
for (const [name, template] of Object.entries(pairs)) {
  const es = flatten(load(template.replace('{locale}', 'es')));
  const en = flatten(load(template.replace('{locale}', 'en')));
  assert.deepEqual(Object.keys(en).filter(key => !(key in es)), [], name + ': missing Spanish keys');
  for (const key of Object.keys(en)) {
    assert.deepEqual(markers(es[key]), markers(en[key]), name + ': interpolation markers: ' + key);
  }
  console.log(name + ': ' + Object.keys(en).length + ' English keys covered; interpolation preserved');
}
const office = load(pairs.oficina.replace('{locale}', 'es'));
assert.equal(office['settings.environment.add_button'], 'Añadir variable');
assert.equal(office['models.title'], 'Modelos');
assert.equal(office['settings.nuke_confirmation_placeholder'], 'Escribe NUKE');
assert.equal(office['skills.title'], 'Skills');
const education = load(pairs.educacion.replace('{locale}', 'es'));
assert.equal(education.Skills, 'Skills');
assert.equal(education['contextBudget.segment.skills'], 'Skills');
assert.equal(education['No KB'], 'Sin KB');
