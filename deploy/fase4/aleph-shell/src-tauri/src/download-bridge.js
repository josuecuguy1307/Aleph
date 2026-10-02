// Generated downloads use the existing native Downloads writer. WKDownload can
// block the main thread while issuing its sandbox extension on macOS.
(() => {
  if (!['http:', 'https:', 'tauri:'].includes(location.protocol)) return;
  if (location.protocol !== 'tauri:' && !['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname)) return;
  const MAX_BYTES = 64 * 1024 * 1024;
  const pending = new Map();
  const blobs = new Map();
  const create = URL.createObjectURL.bind(URL);
  const revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = (blob) => { const url = create(blob); blobs.set(url, blob); return url; };
  URL.revokeObjectURL = (url) => { blobs.delete(url); revoke(url); };
  function notice(message) {
    const node = document.createElement('div');
    node.setAttribute('role', 'status');
    node.textContent = message;
    node.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:2147483647;max-width:70vw;padding:14px 18px;border-radius:10px;background:#20242a;color:white;white-space:pre-wrap;overflow-wrap:anywhere;font:14px system-ui;box-shadow:0 4px 20px #0004';
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 12000);
  }
  async function nativeSave(name, contentsBase64) {
    const invoke = window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
    if (!invoke) throw new Error('El guardado nativo no está disponible.');
    return invoke('download_artifact', { name, contentsBase64 });
  }
  window.addEventListener('message', async (event) => {
    const data = event.data;
    if (!data || typeof data !== 'object') return;
    if (window === window.top && data.type === 'aleph-download-request') {
      // A workspace can request the same Downloads operation as an anchor, but
      // arbitrary windows and remote origins never acquire native authority.
      const frame = [...document.querySelectorAll('iframe')].find((f) => f.contentWindow === event.source);
      if (!frame) return;
      let origin;
      try { origin = new URL(frame.src, location.href).origin; } catch { return; }
      if (event.origin !== origin || !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$/.test(origin)) return;
      if (typeof data.name !== 'string' || typeof data.contentsBase64 !== 'string' || data.contentsBase64.length > MAX_BYTES * 1.4) return;
      try {
        const path = await nativeSave(data.name, data.contentsBase64);
        event.source.postMessage({ type: 'aleph-download-result', id: data.id, path }, origin);
      } catch (error) {
        event.source.postMessage({ type: 'aleph-download-result', id: data.id, error: String(error) }, origin);
      }
    } else if (window !== window.top && event.source === window.parent && data.type === 'aleph-download-result') {
      const request = pending.get(data.id);
      if (!request) return;
      pending.delete(data.id);
      clearTimeout(request.timer);
      data.error ? request.reject(new Error(data.error)) : request.resolve(data.path);
    }
  });
  async function save(anchor, capturedBlob) {
    try {
      let blob = capturedBlob;
      if (!blob && anchor.href.startsWith('data:')) {
        // WKWebView may reject fetch(data:) under the workspace CSP. Decode
        // the exported bytes directly without acquiring any network authority.
        const match = anchor.href.match(/^data:([^,]*),(.*)$/s);
        if (!match || match[2].length > MAX_BYTES * 1.4) throw new Error('La imagen exportada no es válida o supera el límite.');
        const base64 = /;base64$/i.test(match[1]);
        const bytes = base64
          ? Uint8Array.from(atob(match[2]), (character) => character.charCodeAt(0))
          : new TextEncoder().encode(decodeURIComponent(match[2]));
        blob = new Blob([bytes], { type: match[1].replace(/;base64$/i, '') || 'text/plain' });
      }
      if (!blob) {
        const response = await fetch(anchor.href);
        if (!response.ok) throw new Error('La descarga respondió HTTP ' + response.status + '.');
        blob = await response.blob();
      }
      if (blob.size > MAX_BYTES) throw new Error('El archivo supera el límite de descarga de 64 MB.');
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      const contentsBase64 = btoa(binary);
      let path;
      if (window === window.top) path = await nativeSave(anchor.download, contentsBase64);
      else {
        const id = crypto.randomUUID();
        path = await new Promise((resolve, reject) => {
          const timer = setTimeout(() => { pending.delete(id); reject(new Error('No llegó la confirmación de guardado.')); }, 20000);
          pending.set(id, { resolve, reject, timer });
          window.parent.postMessage({ type: 'aleph-download-request', id, name: anchor.download, contentsBase64 }, '*');
        });
      }
      notice('Archivo guardado en ' + path);
    } catch (error) { notice('No se pudo guardar: ' + error.message); }
  }
  const eligible = (a) => {
    if (!(a instanceof HTMLAnchorElement) || !a.hasAttribute('download')) return false;
    if (/^(blob:|data:)/.test(a.href)) return true;
    try { return new URL(a.href, location.href).origin === location.origin; }
    catch { return false; }
  };
  const click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    // Capture the Blob synchronously: several exporters revoke its URL directly
    // after click(), before an asynchronous read could otherwise retain it.
    if (eligible(this)) { void save(this, blobs.get(this.href)); return; }
    return click.call(this);
  };
  document.addEventListener('click', (event) => {
    const anchor = event.target?.closest?.('a[download]');
    if (!eligible(anchor)) return;
    event.preventDefault();
    void save(anchor, blobs.get(anchor.href));
  }, true);
})();
