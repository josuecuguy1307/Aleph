import { describe, expect, it, vi } from 'vitest';
import {
  persistTweakTokensToWorkspace,
  resolveTweakWriteTarget,
  type WorkspacePreviewWrite,
} from './tweak-persistence';
import type { WorkspacePreviewRead } from './workspace-source';

const jsxSource = 'const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{"accent":"#000000"}/*EDITMODE-END*/;';

describe('resolveTweakWriteTarget', () => {
  it('uses App.jsx as the default tweak source file', async () => {
    const read = vi.fn<WorkspacePreviewRead>(async (_designId, path) => ({
      path,
      content: jsxSource,
    }));

    await expect(
      resolveTweakWriteTarget({ designId: 'd1', previewSource: jsxSource, read }),
    ).resolves.toEqual({ path: 'App.jsx', content: jsxSource });
  });

  it('resolves an index.html source-reference placeholder to the referenced JSX file', async () => {
    const read = vi.fn<WorkspacePreviewRead>(async (_designId, path) => {
      if (path === 'App.jsx') throw new Error('missing default source');
      return {
        path,
        content:
          path === 'index.html'
            ? '<!doctype html><body><!-- artifact source lives in index.jsx --></body>'
            : jsxSource,
      };
    });

    await expect(
      resolveTweakWriteTarget({ designId: 'd1', previewSource: jsxSource, read }),
    ).resolves.toEqual({ path: 'index.jsx', content: jsxSource });
  });
});

describe('persistTweakTokensToWorkspace', () => {
  it('writes the rewritten EDITMODE block to the resolved workspace source file', async () => {
    const read = vi.fn<WorkspacePreviewRead>(async (_designId, path) => ({
      path,
      content: jsxSource,
    }));
    const write = vi.fn<WorkspacePreviewWrite>(async (_designId, path, content) => ({
      path,
      content,
    }));

    const result = await persistTweakTokensToWorkspace({
      designId: 'd1',
      previewSource: jsxSource,
      tokens: { accent: '#f97316' },
      read,
      write,
    });

    expect(result).toMatchObject({ path: 'App.jsx', wrote: true });
    expect(result.content).toContain('"accent": "#f97316"');
    expect(write).toHaveBeenCalledWith('d1', 'App.jsx', expect.stringContaining('#f97316'));
  });

  it('falls back to renderer-only content when no write API is available', async () => {
    const result = await persistTweakTokensToWorkspace({
      designId: 'd1',
      previewSource: jsxSource,
      tokens: { accent: '#22c55e' },
    });

    expect(result).toMatchObject({ path: 'App.jsx', wrote: false });
    expect(result.content).toContain('"accent": "#22c55e"');
  });
});
