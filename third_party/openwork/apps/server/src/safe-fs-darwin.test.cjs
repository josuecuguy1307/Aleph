const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const safe = require('./safe-fs-darwin.node');

const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'aleph-safe-fs-test-')));
const root = path.join(temp, 'workspace');
const outside = path.join(temp, 'outside.txt');
fs.mkdirSync(root);
fs.writeFileSync(outside, 'SENTINEL');
try {
  safe.mkdir(root, 'normal/sub');
  safe.writeFile(root, 'normal/sub/inside.txt', Buffer.from('inside'));
  safe.createFile(root, 'normal/sub/exclusive.txt', Buffer.from('exclusive'));
  assert.equal(fs.readFileSync(path.join(root, 'normal/sub/exclusive.txt'), 'utf8'), 'exclusive');
  assert.throws(() => safe.createFile(root, 'normal/sub/exclusive.txt', Buffer.from('replace')));
  let fd = safe.openFile(root, 'normal/sub/inside.txt');
  assert.equal(fs.readFileSync(fd, 'utf8'), 'inside');
  fs.closeSync(fd);
  safe.rename(root, 'normal/sub/inside.txt', 'normal/moved.txt');
  fd = safe.openFile(root, 'normal/moved.txt');
  assert.equal(fs.readFileSync(fd, 'utf8'), 'inside');
  fs.closeSync(fd);
  safe.remove(root, 'normal/moved.txt', false);

  fs.symlinkSync(outside, path.join(root, 'file-link'));
  fs.symlinkSync(temp, path.join(root, 'dir-link'));
  for (const [op, relative] of [
    [() => safe.openFile(root, 'file-link'), 'file-link'],
    [() => safe.writeFile(root, 'file-link', Buffer.from('ESCAPED')), 'write-file-link'],
    [() => safe.createFile(root, 'file-link', Buffer.from('ESCAPED')), 'create-file-link'],
    [() => safe.openFile(root, 'dir-link/outside.txt'), 'dir-link/outside.txt'],
    [() => safe.writeFile(root, 'dir-link/outside.txt', Buffer.from('ESCAPED')), 'write'],
    [() => safe.rename(root, 'normal/sub', 'dir-link/renamed'), 'rename'],
    [() => safe.remove(root, 'dir-link/outside.txt', false), 'delete'],
    [() => safe.openFile(root, '../outside.txt'), 'traversal'],
  ]) assert.throws(op, undefined, relative);

  // Synthetic race: adversary swaps an ancestor repeatedly while each operation
  // walks it; the descriptor boundary may reject, but never touches outside.
  const swap = path.join(root, 'race');
  fs.mkdirSync(swap);
  for (let i = 0; i < 250; i++) {
    if (fs.existsSync(swap)) fs.rmSync(swap, { recursive: true });
    fs.symlinkSync(temp, swap);
    assert.throws(() => safe.writeFile(root, 'race/outside.txt', Buffer.from('ESCAPED')));
    fs.unlinkSync(swap);
    fs.mkdirSync(swap);
    safe.writeFile(root, 'race/inside.txt', Buffer.from('ok'));
  }
  assert.equal(fs.readFileSync(outside, 'utf8'), 'SENTINEL');
  console.log('PASS native descriptor-relative read/write/mkdir/rename/delete and symlink race');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
