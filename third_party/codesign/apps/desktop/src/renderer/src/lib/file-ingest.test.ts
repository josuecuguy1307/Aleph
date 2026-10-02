import { describe, expect, it, vi } from 'vitest';
import { clipboardFilesToWorkspaceBlobs, dataTransferFilesToWorkspaceFiles } from './file-ingest';

describe('file ingest helpers', () => {
  it('extracts local filesystem paths from dropped files', () => {
    const file = { name: 'brief.md', size: 12, path: '/tmp/brief.md' } as File & { path: string };
    const transfer = { files: [file] } as unknown as DataTransfer;

    expect(dataTransferFilesToWorkspaceFiles(transfer)).toEqual([
      { path: '/tmp/brief.md', name: 'brief.md', size: 12 },
    ]);
  });

  it('ignores plain text paste with no file payload', async () => {
    const clipboard = { files: [] } as unknown as DataTransfer;
    await expect(clipboardFilesToWorkspaceBlobs(clipboard)).resolves.toEqual({
      files: [],
      blobs: [],
    });
  });

  it('turns pasted screenshot files into base64 workspace blobs', async () => {
    const file = new File([new Uint8Array([1, 2, 3])], 'image.png', { type: 'image/png' });
    const clipboard = { files: [file] } as unknown as DataTransfer;
    vi.stubGlobal('btoa', (input: string) => Buffer.from(input, 'binary').toString('base64'));

    await expect(clipboardFilesToWorkspaceBlobs(clipboard)).resolves.toEqual({
      files: [],
      blobs: [{ name: 'image.png', mediaType: 'image/png', dataBase64: 'AQID' }],
    });
  });
});
