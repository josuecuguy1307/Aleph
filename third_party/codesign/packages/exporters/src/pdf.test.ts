import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

const fakePdfBytes = Buffer.from('%PDF-1.4 fake');
const CHROME_TEST_TIMEOUT_MS = process.env['CI'] || process.platform === 'win32' ? 30_000 : 15_000;

const launchMock = vi.fn();
const newPageMock = vi.fn();
const setViewportMock = vi.fn();
const setContentMock = vi.fn();
const pdfMock = vi.fn();
const closeMock = vi.fn();
const evaluateMock = vi.fn();

vi.mock('puppeteer-core', () => ({
  default: { launch: launchMock },
}));

vi.mock('./chrome-discovery', () => ({
  findSystemChrome: vi.fn(
    async () => '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ),
}));

let tempDir = '';

beforeAll(() => {
  tempDir = mkdtempSync(join(tmpdir(), 'codesign-pdf-test-'));
  launchMock.mockResolvedValue({
    newPage: newPageMock,
    close: closeMock,
  });
  newPageMock.mockResolvedValue({
    setViewport: setViewportMock,
    setContent: setContentMock,
    pdf: pdfMock,
    evaluate: evaluateMock,
  });
  pdfMock.mockResolvedValue(fakePdfBytes);
  evaluateMock.mockResolvedValue(2400);
});

afterAll(() => {
  rmSync(tempDir, { recursive: true, force: true });
});

describe('exportPdf', () => {
  it(
    'writes a PDF via puppeteer-core against the discovered Chrome',
    async () => {
      const { exportPdf } = await import('./pdf');
      const dest = join(tempDir, 'out.pdf');
      const result = await exportPdf('<h1>hi</h1>', dest);

      expect(launchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          executablePath: expect.stringContaining('Chrome'),
          headless: true,
        }),
      );
      expect(setContentMock).toHaveBeenCalledWith(
        expect.stringContaining('<!doctype html>'),
        expect.objectContaining({ waitUntil: 'load' }),
      );
      expect(pdfMock).toHaveBeenCalled();
      expect(closeMock).toHaveBeenCalled();
      expect(result.path).toBe(dest);
      expect(result.bytes).toBe(fakePdfBytes.length);
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'wraps JSX source before rendering to PDF',
    async () => {
      setContentMock.mockClear();
      const { exportPdf } = await import('./pdf');
      await exportPdf(
        'function App() { return <main id="pdf-jsx">PDF</main>; }\nReactDOM.createRoot(document.getElementById("root")).render(<App/>);',
        join(tempDir, 'jsx.pdf'),
        { chromePath: '/tmp/fake-chrome' },
      );

      expect(setContentMock).toHaveBeenCalledWith(
        expect.stringContaining('CODESIGN_STANDALONE_RUNTIME'),
        expect.objectContaining({ waitUntil: 'load' }),
      );
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'preserves TSX transform options before rendering to PDF',
    async () => {
      setContentMock.mockClear();
      const { exportPdf } = await import('./pdf');
      await exportPdf(
        'type Props = { title: string };\nfunction App({ title }: Props) { return <main>{title}</main>; }\nReactDOM.createRoot(document.getElementById("root")).render(<App title="typed" />);',
        join(tempDir, 'tsx.pdf'),
        { chromePath: '/tmp/fake-chrome', sourcePath: 'screens/App.tsx' },
      );

      expect(setContentMock).toHaveBeenCalledWith(
        expect.stringContaining('"typescript"'),
        expect.objectContaining({ waitUntil: 'load' }),
      );
      expect(setContentMock).toHaveBeenCalledWith(
        expect.stringContaining('"filename":"artifact.tsx"'),
        expect.objectContaining({ waitUntil: 'load' }),
      );
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'respects a chromePath override (no discovery call needed)',
    async () => {
      launchMock.mockClear();
      const { exportPdf } = await import('./pdf');
      const dest = join(tempDir, 'override.pdf');
      await exportPdf('<p>x</p>', dest, { chromePath: '/tmp/fake-chrome' });
      expect(launchMock).toHaveBeenCalledWith(
        expect.objectContaining({ executablePath: '/tmp/fake-chrome' }),
      );
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'exports slide decks as one landscape PDF page per section by default',
    async () => {
      pdfMock.mockClear();
      evaluateMock.mockImplementation(async (script: unknown) => {
        if (typeof script === 'string' && script.includes('querySelectorAll')) {
          return { pageCount: 2, width: 1280, height: 720 };
        }
        return 2400;
      });
      const { exportPdf } = await import('./pdf');
      try {
        await exportPdf(
          '<section><h1>One</h1></section><section><h1>Two</h1></section>',
          join(tempDir, 'deck.pdf'),
          { chromePath: '/tmp/fake-chrome' },
        );

        expect(pdfMock).toHaveBeenCalledWith(
          expect.objectContaining({
            width: '1280px',
            height: '720px',
            margin: { top: '0', right: '0', bottom: '0', left: '0' },
            preferCSSPageSize: false,
          }),
        );
      } finally {
        evaluateMock.mockResolvedValue(2400);
      }
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'wraps puppeteer failures in EXPORTER_PDF_FAILED',
    async () => {
      pdfMock.mockRejectedValueOnce(new Error('boom'));
      const { exportPdf } = await import('./pdf');
      await expect(exportPdf('<p>x</p>', join(tempDir, 'fail.pdf'))).rejects.toMatchObject({
        code: 'EXPORTER_PDF_FAILED',
      });
    },
    CHROME_TEST_TIMEOUT_MS,
  );

  it(
    'passes header and footer options through to Chrome PDF rendering',
    async () => {
      pdfMock.mockClear();
      const { exportPdf } = await import('./pdf');
      await exportPdf('<p>x</p>', join(tempDir, 'header.pdf'), {
        chromePath: '/tmp/fake-chrome',
        headerTemplate: '<span class="title">Title</span>',
        footerTemplate: '<span class="pageNumber"></span>',
      });

      expect(pdfMock).toHaveBeenCalledWith(
        expect.objectContaining({
          displayHeaderFooter: true,
          headerTemplate: '<span class="title">Title</span>',
          footerTemplate: '<span class="pageNumber"></span>',
        }),
      );
    },
    CHROME_TEST_TIMEOUT_MS,
  );
});
