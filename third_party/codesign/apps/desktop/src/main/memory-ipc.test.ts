import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let mockUserDataPath = '/tmp/test-memory-ipc';

vi.mock('./electron-runtime', () => ({
  app: { getPath: (name: string) => (name === 'userData' ? mockUserDataPath : '/tmp') },
  shell: { openPath: vi.fn(async () => '') },
}));

vi.mock('./logger', () => ({
  getLogger: () => ({ warn: vi.fn(), info: vi.fn(), error: vi.fn() }),
}));

vi.mock('@open-codesign/core', async () => {
  const actual = await vi.importActual<typeof import('@open-codesign/core')>('@open-codesign/core');
  return {
    ...actual,
    updateWorkspaceMemory: vi.fn(async () => ({
      content: '# Updated Workspace Memory',
      inputTokens: 100,
      outputTokens: 50,
      costUsd: 0.001,
    })),
    updateUserMemory: vi.fn(async () => ({
      content: '# Updated User Memory',
      inputTokens: 100,
      outputTokens: 50,
      costUsd: 0.001,
    })),
  };
});

import { updateUserMemory, updateWorkspaceMemory } from '@open-codesign/core';
import {
  loadMemoryContext,
  readUserMemoryFile,
  readWorkspaceMemoryFile,
  triggerUserMemoryCandidateCapture,
  triggerUserMemoryConsolidation,
  triggerWorkspaceMemoryUpdate,
  writeUserMemoryFileAtomic,
  writeWorkspaceMemoryFileAtomic,
} from './memory-ipc';

let tempDir: string;

beforeEach(async () => {
  tempDir = await mkdtemp(path.join(os.tmpdir(), 'memory-ipc-test-'));
  mockUserDataPath = tempDir;
});

afterEach(async () => {
  await rm(tempDir, { recursive: true, force: true });
  vi.clearAllMocks();
});

describe('workspace memory files', () => {
  it('prefers uppercase MEMORY.md and treats lowercase memory.md as legacy seed', async () => {
    await writeFile(path.join(tempDir, 'memory.md'), '# Legacy Memory', 'utf-8');
    expect(await readWorkspaceMemoryFile(tempDir)).toMatchObject({
      content: '# Legacy Memory',
      source: 'legacy',
    });

    await writeWorkspaceMemoryFileAtomic(tempDir, '# Workspace Memory');
    expect(await readFile(path.join(tempDir, 'MEMORY.md'), 'utf-8')).toBe('# Workspace Memory');
    expect(await readWorkspaceMemoryFile(tempDir)).toMatchObject({
      content: '# Workspace Memory',
      source: 'primary',
    });
  });

  it('loads user and workspace memory as separate prompt context sections', async () => {
    await writeUserMemoryFileAtomic('# User Memory');
    await writeWorkspaceMemoryFileAtomic(tempDir, '# Workspace Memory');

    const loaded = await loadMemoryContext(tempDir);

    expect(loaded?.sections.join('\n')).toContain('global_user_memory');
    expect(loaded?.sections.join('\n')).toContain('workspace_memory');
    expect(loaded?.userMemory?.content).toBe('# User Memory');
    expect(loaded?.workspaceMemory?.content).toBe('# Workspace Memory');
  });

  it('serializes concurrent updates by normalized workspace path', async () => {
    await Promise.all([
      triggerWorkspaceMemoryUpdate({
        workspacePath: tempDir,
        workspaceName: 'Shared',
        designId: 'design-a',
        designName: 'Design A',
        conversationMessages: [],
        userMemory: null,
        designMdSummary: null,
        model: { provider: 'anthropic', modelId: 'claude-sonnet-4-6' },
        apiKey: 'test-key',
      }),
      triggerWorkspaceMemoryUpdate({
        workspacePath: `${tempDir}${path.sep}.`,
        workspaceName: 'Shared',
        designId: 'design-b',
        designName: 'Design B',
        conversationMessages: [],
        userMemory: null,
        designMdSummary: null,
        model: { provider: 'anthropic', modelId: 'claude-sonnet-4-6' },
        apiKey: 'test-key',
      }),
    ]);

    expect(updateWorkspaceMemory).toHaveBeenCalledTimes(2);
    await expect(readFile(path.join(tempDir, 'MEMORY.md'), 'utf-8')).resolves.toBe(
      '# Updated Workspace Memory',
    );
  });

  it('does not overwrite a second user edit after the conflict retry is exhausted', async () => {
    await writeWorkspaceMemoryFileAtomic(tempDir, '# Initial');
    vi.mocked(updateWorkspaceMemory)
      .mockImplementationOnce(async () => {
        await writeFile(path.join(tempDir, 'MEMORY.md'), '# User Edited', 'utf-8');
        return {
          content: '# Draft One',
          inputTokens: 1,
          outputTokens: 1,
          costUsd: 0,
        };
      })
      .mockImplementationOnce(async () => {
        await writeFile(path.join(tempDir, 'MEMORY.md'), '# User Edited Again', 'utf-8');
        return { content: '# Draft Two', inputTokens: 1, outputTokens: 1, costUsd: 0 };
      });

    await triggerWorkspaceMemoryUpdate({
      workspacePath: tempDir,
      workspaceName: 'Conflict',
      designId: 'design-a',
      designName: 'Design A',
      conversationMessages: [],
      userMemory: null,
      designMdSummary: null,
      model: { provider: 'anthropic', modelId: 'claude-sonnet-4-6' },
      apiKey: 'test-key',
    });

    await expect(readFile(path.join(tempDir, 'MEMORY.md'), 'utf-8')).resolves.toBe(
      '# User Edited Again',
    );
  });
});

describe('global user memory', () => {
  it('stores global user memory under userData/memory/user.md', async () => {
    await writeUserMemoryFileAtomic('# User Design Memory');

    expect(await readUserMemoryFile()).toMatchObject({
      content: '# User Design Memory',
      path: path.join(tempDir, 'memory', 'user.md'),
    });
  });

  it('queues candidates and consumes them only after successful consolidation', async () => {
    await triggerUserMemoryCandidateCapture({
      designId: 'design-1',
      designName: 'Dashboard',
      userMessages: ['I usually prefer dense professional tools'],
    });

    const result = await triggerUserMemoryConsolidation({
      model: { provider: 'anthropic', modelId: 'claude-sonnet-4-6' },
      apiKey: 'test-key',
      force: true,
    });

    expect(result.updated).toBe(true);
    expect(updateUserMemory).toHaveBeenCalledOnce();
    await expect(readFile(path.join(tempDir, 'memory', 'user.md'), 'utf-8')).resolves.toBe(
      '# Updated User Memory',
    );
    await expect(
      readFile(path.join(tempDir, 'memory', 'user-candidates.jsonl'), 'utf-8'),
    ).rejects.toThrow();
  });
});
