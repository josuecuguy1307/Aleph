import { afterEach, expect, it, vi } from 'vitest';
import { workspaceBrowserUrl } from './workspace-browser-url';
afterEach(() => vi.unstubAllGlobals());
it('translates workspace resources only for the local Aleph webview', () => {
  vi.stubGlobal('window', { location: { protocol: 'http:', hostname: '127.0.0.1', origin: 'http://127.0.0.1:8331' } });
  expect(workspaceBrowserUrl('workspace://own-design/figuras/gr%C3%A1fico.png')).toBe('http://127.0.0.1:8331/.aleph/workspace/own-design/figuras/gr%C3%A1fico.png');
});
it('keeps native Electron resources and remote browser origins unchanged', () => {
  for (const location of [{ protocol: 'file:', hostname: '', origin: 'null' },
    { protocol: 'https:', hostname: 'example.com', origin: 'https://example.com' }]) {
    vi.stubGlobal('window', { location });
    expect(workspaceBrowserUrl('workspace://own-design/index.html')).toBe('workspace://own-design/index.html');
  }
});
