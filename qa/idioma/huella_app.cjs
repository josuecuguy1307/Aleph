// Read-only deterministic content manifest: paths, types, modes, file bytes and symlinks.
// No mtimes/xattrs, no symlink traversal and no file contents printed.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(process.argv[2] || '/Applications/Aleph.app');
if (!root.endsWith('/Aleph.app')) throw Error('An explicit Aleph.app is required');
const entries = [];
function walk(dir, relative = '') {
  for (const name of fs.readdirSync(dir).sort()) {
    const rel = relative ? relative + '/' + name : name;
    const absolute = path.join(dir, name), st = fs.lstatSync(absolute);
    const entry = {path: rel, mode: st.mode & 0o777};
    if (st.isSymbolicLink()) entries.push({...entry, type: 'link', target: fs.readlinkSync(absolute)});
    else if (st.isDirectory()) { entries.push({...entry, type: 'dir'}); walk(absolute, rel); }
    else if (st.isFile()) entries.push({...entry, type: 'file', size: st.size});
    else throw Error('Unsupported file type: ' + rel);
  }
}
walk(root);
entries.sort((a,b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
async function fileHash(entry) {
  const absolute = path.join(root, entry.path), before = fs.statSync(absolute);
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(absolute)) digest.update(chunk);
  const after = fs.statSync(absolute);
  if (before.size !== after.size || before.mtimeMs !== after.mtimeMs)
    throw Error('File changed while hashing: ' + entry.path);
  entry.sha256 = digest.digest('hex');
}
(async () => {
  let cursor = 0;
  await Promise.all(Array.from({length: 4}, async () => {
    for (;;) {
      const entry = entries[cursor++];
      if (!entry) return;
      if (entry.type === 'file') await fileHash(entry);
    }
  }));
  const digest = crypto.createHash('sha256');
  for (const entry of entries) digest.update(JSON.stringify(entry) + '\n');
  const files = entries.filter(e => e.type === 'file');
  console.log(JSON.stringify({algorithm: 'aleph-content-manifest-v1', root,
    sha256: digest.digest('hex'), files: files.length,
    bytes: files.reduce((n,e) => n + e.size, 0),
    symlinks: entries.filter(e => e.type === 'link').length,
    directories: entries.filter(e => e.type === 'dir').length}, null, 2));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
