import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { inspectWorkspaceAt } from './workspace-inspection';

describe('inspectWorkspaceAt', () => {
  it('builds a bounded workspace inspection from the bound workspace files', async () => {
    const root = await mkdtemp(path.join(tmpdir(), 'codesign-workspace-inspect-'));
    await mkdir(path.join(root, 'docs'), { recursive: true });
    await mkdir(path.join(root, 'assets'), { recursive: true });
    await mkdir(path.join(root, 'references'), { recursive: true });
    await writeFile(path.join(root, 'App.jsx'), 'function App() {}', 'utf8');
    await writeFile(path.join(root, 'DESIGN.md'), '---\nversion: alpha\n---', 'utf8');
    await writeFile(path.join(root, 'docs', 'brief.md'), '# Brief', 'utf8');
    await writeFile(path.join(root, 'assets', 'logo.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
    await writeFile(
      path.join(root, 'references', 'brief.pdf'),
      Buffer.from([0x25, 0x50, 0x44, 0x46]),
    );

    const inspection = await inspectWorkspaceAt(root);

    expect(inspection.entryCandidates).toEqual(['App.jsx']);
    expect(inspection.designDocs).toContain('DESIGN.md');
    expect(inspection.referenceDocs).toContain('docs/brief.md');
    expect(inspection.assets).toContain('assets/logo.png');
    expect(inspection.totalFiles).toBe(5);
  });
});
