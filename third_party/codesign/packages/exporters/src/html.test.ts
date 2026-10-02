import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { buildHtmlDocument, exportHtml } from './html';

let tempDir = '';

beforeAll(() => {
  tempDir = mkdtempSync(join(tmpdir(), 'codesign-html-test-'));
  mkdirSync(join(tempDir, 'assets'), { recursive: true });
  writeFileSync(join(tempDir, 'assets', 'logo.svg'), '<svg></svg>');
});

afterAll(() => {
  rmSync(tempDir, { recursive: true, force: true });
});

describe('buildHtmlDocument', () => {
  it('exports JSX source as browser-openable HTML with the standalone runtime', () => {
    const out = buildHtmlDocument(
      'function App() { return <div className="p-4">hi</div>; }\nReactDOM.createRoot(document.getElementById("root")).render(<App/>);',
      { prettify: false },
    );

    expect(out).toContain('CODESIGN_STANDALONE_RUNTIME');
    expect(out).toContain('window.Babel.transform');
    expect(out).not.toContain('https://cdn.tailwindcss.com');
    expect(out).not.toContain('CODESIGN_OVERLAY_SCRIPT');
  });

  it('can inject Tailwind CDN when explicitly requested', () => {
    const out = buildHtmlDocument('function App() { return <main />; }', {
      injectTailwind: true,
      prettify: false,
    });

    expect(out).toContain('https://cdn.tailwindcss.com');
  });

  it('uses sourcePath to preserve TSX transform options during export', () => {
    const out = buildHtmlDocument(
      'type Props = { title: string };\nfunction App({ title }: Props) { return <main>{title}</main>; }\nReactDOM.createRoot(document.getElementById("root")).render(<App title="hi" />);',
      { prettify: false, sourcePath: 'screens/App.tsx' },
    );

    expect(out).toContain('"typescript"');
    expect(out).toContain('"isTSX":true');
    expect(out).toContain('artifact.tsx');
  });

  it('keeps legacy HTML fragments as HTML when no sourcePath is provided', () => {
    const out = buildHtmlDocument('<main id="legacy-html">hi</main>', { prettify: false });

    expect(out).toContain('<main id="legacy-html">hi</main>');
    expect(out).not.toContain('CODESIGN_STANDALONE_RUNTIME');
  });

  it('does not mutate script string literals while prettifying standalone JSX exports', () => {
    const out = buildHtmlDocument(
      'const svg = "<svg><path d=\\"M0 0\\" /></svg>";\nfunction App() { return <main>{svg}</main>; }\nReactDOM.createRoot(document.getElementById("root")).render(<App/>);',
    );

    expect(out).toContain('const svg =');
    expect(out).toContain('M0 0');
    expect(out).not.toContain('<svg>\n<path');
  });

  it('writes a self-contained HTML file with local assets inlined', async () => {
    const dest = join(tempDir, 'out.html');
    await exportHtml('<img src="assets/logo.svg">', dest, {
      assetBasePath: tempDir,
      assetRootPath: tempDir,
      prettify: false,
    });

    const out = readFileSync(dest, 'utf8');
    expect(out).toContain('src="data:image/svg+xml;charset=utf-8,');
    expect(out).not.toContain('src="assets/logo.svg"');
  });
});
