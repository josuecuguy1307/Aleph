// Compare assets served by an actual installed Science process with the build.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const port = Number(process.argv[2]);
assert.ok(Number.isInteger(port) && port > 1024 && port < 65536, 'explicit loopback port required');
const dist = path.join(root, 'third_party/openscience/frontend/workspace/dist');
const files = ['index.html', 'aleph-picker-unico.js', 'aleph-model-chip.core.js'];
const index = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
for (const m of index.matchAll(/(?:src|href)="(\/assets\/[^"?#]+\.(?:js|css))"/g)) files.push(m[1].slice(1));
(async () => {
  for (const file of files) {
    const response = await fetch('http://127.0.0.1:' + port + '/' + file);
    assert.equal(response.status, 200, file);
    assert.ok(Buffer.from(await response.arrayBuffer()).equals(fs.readFileSync(path.join(dist, file))),
              'embedded asset differs from current build: ' + file);
  }
  console.log('Installed Science serves current build byte-exact: ' + files.length + ' entry/shared assets.');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
