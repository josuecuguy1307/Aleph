import { describe, expect, it } from 'vitest';
import { buildExportHtmlDocument } from './rendered-html';

describe('exported document styling', () => {
  const report = '<!doctype html><html><body><h1>Estación y evidencia</h1><ol><li>Revisar</li><li>Comparar</li></ol><ul><li>Fuente ficticia</li></ul></body></html>';
  it('preserves native list styling without silently loading an external reset', async () => {
    const html = await buildExportHtmlDocument(report, { sourcePath: 'informe.html' });
    expect(html).toContain('<ol><li>Revisar</li><li>Comparar</li></ol>');
    expect(html).toContain('<ul><li>Fuente ficticia</li></ul>');
    expect(html).not.toContain('<script src="https://cdn.tailwindcss.com');
  });
  it('retains the explicit legacy Tailwind opt-in', async () => {
    const html = await buildExportHtmlDocument(report, { sourcePath: 'informe.html', injectTailwind: true });
    expect(html).toContain('<script src="https://cdn.tailwindcss.com');
  });
});
