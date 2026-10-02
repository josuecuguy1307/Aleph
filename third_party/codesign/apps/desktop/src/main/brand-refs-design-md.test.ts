import { readdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateDesignMd } from '@open-codesign/shared/design-md';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '../../../..');
const brandRefsRoot = join(repoRoot, 'apps/desktop/resources/templates/brand-refs');

describe('built-in brand DESIGN.md references', () => {
  it('all bundled brand references are Google DESIGN.md compatible', async () => {
    const entries = await readdir(brandRefsRoot, { withFileTypes: true });
    const brandDirs = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
    expect(brandDirs.length).toBeGreaterThan(0);

    for (const brand of brandDirs) {
      const raw = await readFile(join(brandRefsRoot, brand, 'DESIGN.md'), 'utf8');
      const errors = validateDesignMd(raw).filter((finding) => finding.severity === 'error');
      expect(errors, `${brand}/DESIGN.md`).toEqual([]);
    }
  });
});
