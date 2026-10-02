import { CodesignError, ERROR_CODES } from '@open-codesign/shared';
import {
  collapseWhitespace,
  decodeHtmlEntities,
  removeHtmlElementBlocks,
  stripHtmlTags,
} from '@open-codesign/shared/html-utils';
import type { ExportResult } from './index';
import { buildExportHtmlDocument } from './rendered-html';

export interface ExportPptxOptions {
  /** Workspace-relative source path used to classify JSX vs TSX and anchor relative assets. */
  sourcePath?: string | undefined;
  /** Directory used to resolve relative HTML references. */
  assetBasePath?: string | undefined;
  /** Workspace/root directory used for root-relative references and containment. */
  assetRootPath?: string | undefined;
  /** Slide title shown in PowerPoint's outline view. */
  deckTitle?: string;
  /**
   * `image` preserves visual fidelity by rendering HTML with system Chrome.
   * `editable` keeps the legacy title/bullet extraction path.
   */
  renderMode?: 'image' | 'editable';
  /** Override the discovered Chrome binary path for image rendering. */
  chromePath?: string;
  /** setContent timeout in milliseconds. Defaults to 45 seconds. */
  renderTimeoutMs?: number;
  /** Viewport used when rasterizing slides. */
  viewport?: { width: number; height: number };
  /** CSS selector used to find slide-like containers when no <section> elements exist. */
  slideSelector?: string;
  /** Opt into Tailwind CDN for legacy sources; defaults to false like native previews. */
  injectTailwind?: boolean;
}

interface SlideContent {
  title: string;
  bullets: string[];
}

interface SlideScreenshot {
  bytes: Buffer;
  width: number;
  height: number;
}

const PRIMARY_SLIDE_SELECTOR: string = 'section';
const DEFAULT_FALLBACK_SLIDE_SELECTOR: string =
  '[data-slide], [data-pptx-slide], [data-slide-container], .slide';

/**
 * Render a design source artifact to PPTX using pptxgenjs.
 *
 * Default strategy: render the artifact with system Chrome and embed screenshots
 * so visual layout, images, tables, CSS, and JSX-rendered output survive the
 * PPTX export. The `editable` mode keeps the limited title/bullet extraction
 * path for simple HTML. We do NOT use
 * dom-to-pptx in tier 1 — the package is unmaintained and only adds
 * editability for pure-text slides we already cover.
 *
 * CJK fix: per research/04, the dom-to-pptx wrap bug is sidestepped by
 * keeping pptxgenjs' default `wrap=square` and explicitly enabling
 * `fit: 'shrink'` (emits `normAutofit`). Verified with PowerPoint Mac.
 */
export async function exportPptx(
  artifactSource: string,
  destinationPath: string,
  opts: ExportPptxOptions = {},
): Promise<ExportResult> {
  const fs = await import('node:fs/promises');
  const PptxGenJS = (await import('pptxgenjs')).default;

  try {
    const pres = new PptxGenJS();
    pres.layout = 'LAYOUT_WIDE';
    if (opts.deckTitle) pres.title = opts.deckTitle;

    if ((opts.renderMode ?? 'image') === 'image') {
      const screenshots = await renderSlideScreenshots(artifactSource, opts);
      // A report section can be taller than a widescreen slide. Keep one section
      // per slide, but size the deck to its content instead of stretching text.
      const slideWidth = 13.333;
      const slideHeight = Math.max(
        7.5,
        ...screenshots.map((image) => slideWidth * image.height / image.width),
      );
      pres.defineLayout({ name: 'ARTIFACT_CONTENT', width: slideWidth, height: slideHeight });
      pres.layout = 'ARTIFACT_CONTENT';
      for (const screenshot of screenshots) {
        const slide = pres.addSlide();
        slide.background = { color: 'FFFFFF' };
        const scale = Math.min(slideWidth / screenshot.width, slideHeight / screenshot.height);
        const imageWidth = screenshot.width * scale;
        const imageHeight = screenshot.height * scale;
        slide.addImage({
          data: `data:image/png;base64,${screenshot.bytes.toString('base64')}`,
          x: (slideWidth - imageWidth) / 2,
          y: 0,
          w: imageWidth,
          h: imageHeight,
        });
      }
    } else {
      const slides = extractSlides(artifactSource);
      for (const s of slides) {
        const slide = pres.addSlide();
        slide.background = { color: 'FFFFFF' };
        if (s.title) {
          slide.addText(s.title, {
            x: 0.5,
            y: 0.4,
            w: 12,
            h: 1,
            fontSize: 32,
            bold: true,
            color: '111111',
            fontFace: 'Helvetica',
            wrap: true,
            fit: 'shrink',
          });
        }
        if (s.bullets.length > 0) {
          slide.addText(
            s.bullets.map((b) => ({ text: b, options: { bullet: true } })),
            {
              x: 0.5,
              y: 1.6,
              w: 12,
              h: 5.5,
              fontSize: 18,
              color: '333333',
              fontFace: 'Helvetica',
              wrap: true,
              fit: 'shrink',
              valign: 'top',
              paraSpaceAfter: 8,
            },
          );
        }
      }
    }

    await pres.writeFile({ fileName: destinationPath });
    const stat = await fs.stat(destinationPath);
    return { bytes: stat.size, path: destinationPath };
  } catch (err) {
    throw new CodesignError(
      `PPTX export failed: ${err instanceof Error ? err.message : String(err)}`,
      ERROR_CODES.EXPORTER_PPTX_FAILED,
      { cause: err },
    );
  }
}

async function renderSlideScreenshots(
  artifactSource: string,
  opts: ExportPptxOptions,
): Promise<SlideScreenshot[]> {
  const { findSystemChrome } = await import('./chrome-discovery');
  const puppeteer = (await import('puppeteer-core')).default;

  const requestedViewport = opts.viewport ?? { width: 1280, height: 720 };
  const viewport = {
    width: Math.max(1, requestedViewport.width),
    height: Math.max(1, requestedViewport.height),
  };
  const executablePath = opts.chromePath ?? (await findSystemChrome());
  const html = await buildExportHtmlDocument(artifactSource, opts);
  const { mkdtemp, rm } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const userDataDir = await mkdtemp(join(tmpdir(), 'codesign-pptx-'));

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    userDataDir,
    args: [
      '--headless=new',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
    ],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ ...viewport, deviceScaleFactor: 2 });
    await page.setContent(html, {
      waitUntil: 'load',
      timeout: opts.renderTimeoutMs ?? 45_000,
    });
    await page.evaluate('document.fonts?.ready ?? Promise.resolve()');

    const screenshots: SlideScreenshot[] = [];
    let slideHandles = await page.$$(PRIMARY_SLIDE_SELECTOR);
    if (slideHandles.length === 0) {
      slideHandles = await page.$$(opts.slideSelector ?? DEFAULT_FALLBACK_SLIDE_SELECTOR);
    }

    if (slideHandles.length > 0) {
      for (const slideElement of slideHandles) {
        const box = await slideElement.boundingBox();
        if (!box || box.width <= 0 || box.height <= 0) continue;
        const image = await page.screenshot({
          type: 'png',
          clip: {
            x: Math.max(0, box.x),
            y: Math.max(0, box.y),
            width: Math.max(1, box.width),
            height: Math.max(1, box.height),
          },
        });
        screenshots.push({ bytes: Buffer.from(image), width: box.width, height: box.height });
      }
    }
    if (screenshots.length === 0) {
      const pagination = await page.evaluate((slideHeight: number) => {
        const readNumber = (target: object | null, key: string): number => {
          if (!target) return 0;
          const value = Reflect.get(target, key);
          return typeof value === 'number' && Number.isFinite(value) ? value : 0;
        };
        const setMinHeight = (target: object | null, height: number): void => {
          if (!target) return;
          const style = Reflect.get(target, 'style');
          if (style && typeof style === 'object') {
            Reflect.set(style, 'minHeight', `${height}px`);
          }
        };
        const documentValue = Reflect.get(globalThis, 'document');
        if (!documentValue || typeof documentValue !== 'object') return { pageCount: 1 };
        const rootValue = Reflect.get(documentValue, 'documentElement');
        if (!rootValue || typeof rootValue !== 'object') return { pageCount: 1 };
        const bodyValue = Reflect.get(documentValue, 'body');
        const root = rootValue;
        const body = bodyValue && typeof bodyValue === 'object' ? bodyValue : null;
        const scrollHeight = Math.max(
          readNumber(root, 'scrollHeight'),
          readNumber(root, 'offsetHeight'),
          readNumber(root, 'clientHeight'),
          readNumber(body, 'scrollHeight'),
          readNumber(body, 'offsetHeight'),
          readNumber(body, 'clientHeight'),
        );
        const pageCount = Math.max(1, Math.ceil(scrollHeight / slideHeight));
        const captureHeight = pageCount * slideHeight;
        setMinHeight(root, captureHeight);
        setMinHeight(body, captureHeight);
        return { pageCount };
      }, viewport.height);
      const pageCount = normalizePageCount(pagination);

      for (let pageIndex = 0; pageIndex < pageCount; pageIndex += 1) {
        const image = await page.screenshot({
          type: 'png',
          clip: {
            x: 0,
            y: pageIndex * viewport.height,
            width: viewport.width,
            height: viewport.height,
          },
        });
        screenshots.push({ bytes: Buffer.from(image), width: viewport.width, height: viewport.height });
      }
    }
    return screenshots;
  } finally {
    await browser.close();
    await rm(userDataDir, { recursive: true, force: true });
  }
}

function normalizePageCount(pagination: unknown): number {
  if (!pagination || typeof pagination !== 'object' || !('pageCount' in pagination)) return 1;
  const pageCount = pagination.pageCount;
  return typeof pageCount === 'number' && Number.isFinite(pageCount) ? Math.max(1, pageCount) : 1;
}

const SECTION_RE = /<section\b[^>]*>([\s\S]*?)<\/section>/gi;
const HEADING_RE = /<h[1-3]\b[^>]*>([\s\S]*?)<\/h[1-3]>/i;
const LIST_ITEM_RE = /<li\b[^>]*>([\s\S]*?)<\/li>/gi;
const PARAGRAPH_RE = /<p\b[^>]*>([\s\S]*?)<\/p>/gi;

export function extractSlides(html: string): SlideContent[] {
  const sections: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = SECTION_RE.exec(html)) !== null) sections.push(m[1] ?? '');
  if (sections.length === 0) sections.push(html);
  return sections.map(parseSlide);
}

function parseSlide(fragment: string): SlideContent {
  const headingMatch = HEADING_RE.exec(fragment);
  const title = headingMatch ? stripHtml(headingMatch[1] ?? '') : '';

  const bullets: string[] = [];
  let li: RegExpExecArray | null;
  while ((li = LIST_ITEM_RE.exec(fragment)) !== null) {
    const text = stripHtml(li[1] ?? '');
    if (text) bullets.push(text);
  }
  if (bullets.length === 0) {
    let p: RegExpExecArray | null;
    while ((p = PARAGRAPH_RE.exec(fragment)) !== null) {
      const text = stripHtml(p[1] ?? '');
      if (text) bullets.push(text);
    }
  }
  if (bullets.length === 0 && !title) {
    const text = stripHtml(fragment);
    if (text) bullets.push(text);
  }
  return { title, bullets };
}

function stripHtml(s: string): string {
  const withoutScripts = removeHtmlElementBlocks(removeHtmlElementBlocks(s, 'style'), 'script');
  return collapseWhitespace(decodeHtmlEntities(stripHtmlTags(withoutScripts))).trim();
}
