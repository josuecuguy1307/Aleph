/**
 * Exporter entry point. Each format lives in its own subpath export and is
 * loaded lazily so the cold-start bundle stays lean (PRINCIPLES §1).
 *
 * Tier 1 ships HTML, PDF, PPTX, and ZIP — all four lazy-loaded so the heavy
 * runtime deps (`puppeteer-core`, `pptxgenjs`, `zip-lib`) only enter the
 * module graph the first time a user actually exports.
 */

import { CodesignError, ERROR_CODES } from '@open-codesign/shared';
import type { LocalAssetOptions } from './assets';

export const EXPORTER_FORMATS = ['html', 'pdf', 'pptx', 'zip', 'markdown'] as const;
export type ExporterFormat = (typeof EXPORTER_FORMATS)[number];

export type ExportOptions = LocalAssetOptions;

export interface ExportResult {
  bytes: number;
  path: string;
}

/**
 * Formats that need a system Chrome: PDF and PPTX both render through
 * `rendered-html` + `puppeteer-core`. HTML, Markdown and ZIP are pure Node.
 */
const NEEDS_CHROME: ReadonlySet<ExporterFormat> = new Set<ExporterFormat>(['pdf', 'pptx']);

/**
 * `null` = nobody asked yet. Deliberately tri-state: not-measured is NOT the same
 * as measured-and-absent, and collapsing them would trade one silent lie for another.
 */
let chromeAvailable: boolean | null = null;

/**
 * Resolve once whether this machine can render PDF/PPTX, and remember it.
 *
 * Call it at app startup. `findSystemChrome` shells out to `which` and stats a
 * handful of paths — fine once, unacceptable per render of a button, which is why
 * `isExporterReady` stays synchronous and reads this instead of probing.
 */
export async function primeExporterReadiness(
  deps?: import('./chrome-discovery').ChromeDiscoveryDeps,
): Promise<boolean> {
  const { findSystemChrome } = await import('./chrome-discovery');
  try {
    await findSystemChrome(deps);
    chromeAvailable = true;
  } catch {
    chromeAvailable = false;
  }
  return chromeAvailable;
}

/** Test seam — lets a caller set the answer without touching the filesystem. */
export function setExporterReadiness(available: boolean | null): void {
  chromeAvailable = available;
}

/**
 * Can this machine actually produce `format` right now?
 *
 * This used to be `return true` for every format, ignoring its argument — so the
 * one question a surface could ask before offering a button always answered yes,
 * and PDF failed *after* the user had already picked a save location.
 *
 * FALSE ONLY WHEN WE KNOW: an unprimed process answers `true` for Chrome formats,
 * because "we never looked" is not evidence of absence. Answering `false` there
 * would hide PDF on a machine that has Chrome, which is the same class of silent
 * wrong answer in the other direction. Unprimed simply means the old behaviour —
 * the export is attempted and fails loudly if Chrome is missing.
 */
export function isExporterReady(format: ExporterFormat): boolean {
  if (!NEEDS_CHROME.has(format)) return true;
  return chromeAvailable !== false;
}

export type { LocalAssetOptions } from './assets';
export { type ChromeDiscoveryDeps, findSystemChrome } from './chrome-discovery';
export type { ExportHtmlOptions } from './html';
export type { ExportMarkdownOptions, MarkdownMeta } from './markdown';
export { htmlToMarkdown } from './markdown';
export type { ExportPdfOptions } from './pdf';
export type { ExportPptxOptions } from './pptx';
export type { ExportZipOptions, ZipAsset } from './zip';

export async function exportHtml(
  artifactSource: string,
  destinationPath: string,
  opts?: import('./html').ExportHtmlOptions,
): Promise<ExportResult> {
  const mod = await import('./html');
  return mod.exportHtml(artifactSource, destinationPath, opts);
}

export async function exportArtifact(
  format: ExporterFormat,
  artifactSource: string,
  destinationPath: string,
  opts: ExportOptions = {},
): Promise<ExportResult> {
  if (format === 'html') {
    return exportHtml(artifactSource, destinationPath, opts);
  }
  if (format === 'pdf') {
    const mod = await import('./pdf');
    return mod.exportPdf(artifactSource, destinationPath, opts);
  }
  if (format === 'pptx') {
    const mod = await import('./pptx');
    return mod.exportPptx(artifactSource, destinationPath, opts);
  }
  if (format === 'zip') {
    const mod = await import('./zip');
    return mod.exportZip(artifactSource, destinationPath, opts);
  }
  if (format === 'markdown') {
    const mod = await import('./markdown');
    return mod.exportMarkdown(artifactSource, destinationPath, opts);
  }
  throw new CodesignError(
    `Unknown exporter format: ${format as string}`,
    ERROR_CODES.EXPORTER_UNKNOWN,
  );
}
