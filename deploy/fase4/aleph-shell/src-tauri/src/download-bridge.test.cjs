const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/download-bridge.js', 'utf8');

function harness(fetcher) {
  const calls = [], messages = [], notices = [];
  class Anchor {
    constructor(href, download) { this.href = href; this.download = download; }
    hasAttribute(name) { return name === 'download'; }
    click() { calls.push('browser-download'); }
  }
  class LocalURL extends URL {}
  LocalURL.createObjectURL = () => 'blob:http://127.0.0.1:8330/test';
  LocalURL.revokeObjectURL = () => {};
  const frame = { src: 'http://127.0.0.1:9000', contentWindow: { postMessage: (m) => messages.push(m) } };
  const window = { addEventListener: (name, fn) => { window[name] = fn; }, __TAURI__: { core: {
    invoke: async (...args) => { calls.push(args); return '/Downloads/test.md'; },
  } } };
  window.top = window;
  const context = {
    location: new URL('http://127.0.0.1:8330'), window, URL: LocalURL,
    HTMLAnchorElement: Anchor, Blob, Uint8Array, btoa, atob, TextEncoder, fetch: fetcher,
    setTimeout: (fn, ms) => { const timer = setTimeout(fn, ms); timer.unref(); return timer; }, clearTimeout,
    document: {
      querySelectorAll: () => [frame], addEventListener: () => {},
      createElement: () => ({ style: {}, setAttribute() {}, remove() {} }),
      body: { appendChild: (node) => notices.push(node.textContent) },
    },
  };
  vm.runInNewContext(source, context);
  return { calls, messages, notices, frame, window, Anchor, URL: LocalURL };
}

test('retains an exported Blob after immediate revocation, with Unicode intact', async () => {
  const h = harness();
  const original = '# Cuaderno del agua\nFórmula: μ = 83.\n';
  const url = h.URL.createObjectURL(new Blob([original]));
  new h.Anchor(url, 'cuaderno.md').click();
  h.URL.revokeObjectURL(url);
  await new Promise(setImmediate);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0][0], 'download_artifact');
  assert.equal(Buffer.from(h.calls[0][1].contentsBase64, 'base64').toString(), original);
  assert.match(h.notices[0], /Archivo guardado/);
});

test('accepts only the registered local iframe and its exact origin', async () => {
  const h = harness();
  const data = { type: 'aleph-download-request', id: '1', name: 'test.md', contentsBase64: 'eA==' };
  await h.window.message({ data, origin: 'https://untrusted.example', source: h.frame.contentWindow });
  await h.window.message({ data, origin: 'http://127.0.0.1:9000', source: {} });
  assert.equal(h.calls.length, 0);
  await h.window.message({ data, origin: 'http://127.0.0.1:9000', source: h.frame.contentWindow });
  assert.equal(h.calls.length, 1);
  assert.equal(h.messages[0].path, '/Downloads/test.md');
});

test('downloads same-origin files and rejects HTTP error bodies', async () => {
  const h = harness(async () => ({ ok: true, blob: async () => new Blob(['<svg/>']) }));
  new h.Anchor('http://127.0.0.1:8330/api/outputs/figure.svg', 'figure.svg').click();
  await new Promise(setImmediate);
  assert.equal(h.calls[0][0], 'download_artifact');
  const failed = harness(async () => ({ ok: false, status: 404 }));
  new failed.Anchor('http://127.0.0.1:8330/missing.svg', 'figure.svg').click();
  await new Promise(setImmediate);
  assert.equal(failed.calls.length, 0);
  assert.match(failed.notices[0], /HTTP 404/);
});

test('decodes exported PNG and Unicode SVG data without a CSP-dependent fetch', async () => {
  const h = harness(() => { throw new Error('data fetch must not run'); });
  const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  new h.Anchor('data:image/png;base64,' + png.toString('base64'), 'chart.png').click();
  await new Promise(setImmediate);
  assert.deepEqual(Buffer.from(h.calls[0][1].contentsBase64, 'base64'), png);
  const svg = '<svg><text>Lluvia · μ</text></svg>';
  new h.Anchor('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg), 'chart.svg').click();
  await new Promise(setImmediate);
  assert.equal(Buffer.from(h.calls[1][1].contentsBase64, 'base64').toString(), svg);
});
