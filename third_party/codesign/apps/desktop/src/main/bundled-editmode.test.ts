import { readdir, readFile } from 'node:fs/promises';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEditmodeBlock } from '@open-codesign/shared';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '../../../..');
const templatesRoot = join(repoRoot, 'apps/desktop/resources/templates');
const EDITMODE_EXTENSIONS = new Set(['.css', '.html', '.js', '.jsx', '.tsx']);

async function collectTemplateFiles(dir: string): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const filePath = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await collectTemplateFiles(filePath)));
      continue;
    }
    if (entry.isFile() && EDITMODE_EXTENSIONS.has(extname(entry.name))) {
      out.push(filePath);
    }
  }
  return out;
}

describe('bundled template EDITMODE blocks', () => {
  it('all bundled tweak blocks are canonical JSON', async () => {
    const files = await collectTemplateFiles(templatesRoot);
    const failures: string[] = [];
    let checked = 0;

    for (const file of files) {
      const raw = await readFile(file, 'utf8');
      if (!raw.includes('EDITMODE-BEGIN')) continue;
      checked += 1;
      try {
        parseEditmodeBlock(raw);
      } catch (err) {
        failures.push(`${file}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }

    expect(checked).toBeGreaterThan(0);
    expect(failures).toEqual([]);
  });
});
