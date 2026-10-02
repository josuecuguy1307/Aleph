import type { AgentMessage } from '@mariozechner/pi-agent-core';
import type {
  ChatMessageRow,
  ChatToolCallPayload,
  ModelRef,
  ResourceStateV1,
} from '@open-codesign/shared';
import { describe, expect, it, vi } from 'vitest';

const completeWithRetryMock = vi.fn();

vi.mock('@open-codesign/providers', async () => {
  const actual = await vi.importActual<typeof import('@open-codesign/providers')>(
    '@open-codesign/providers',
  );
  return {
    ...actual,
    completeWithRetry: (...args: unknown[]) => completeWithRetryMock(...args),
  };
});

import {
  buildDesignContextPack,
  type DesignSessionBriefV1,
  updateDesignSessionBrief,
} from './design-context.js';

const MODEL: ModelRef = { provider: 'anthropic', modelId: 'claude-sonnet-4-6' };

function baseBrief(overrides: Partial<DesignSessionBriefV1> = {}): DesignSessionBriefV1 {
  return {
    schemaVersion: 1,
    designId: 'design-1',
    designName: 'Fintech dashboard',
    updatedAt: '2026-05-05T00:00:00.000Z',
    goal: 'Create a polished fintech analytics dashboard.',
    artifactType: 'dashboard',
    audience: 'Finance operators',
    visualDirection: 'Dense, calm, professional.',
    stableDecisions: ['Use compact cards', 'Keep charts above the fold'],
    userPreferences: ['Prefer restrained color'],
    dislikes: ['No generic gradient blobs'],
    openTasks: ['Refine empty states'],
    currentFiles: ['App.jsx', 'DESIGN.md'],
    lastVerification: { status: 'ok', path: 'App.jsx', errorCount: 0 },
    lastUserIntent: 'Make the metrics easier to scan.',
    sourceUserMemoryHash: 'user-old',
    sourceWorkspaceMemoryHash: 'workspace-old',
    sourceMemoryUpdatedAt: '2026-05-05T00:00:00.000Z',
    ...overrides,
  };
}

function baseResourceState(): ResourceStateV1 {
  return {
    schemaVersion: 1,
    loadedSkills: ['chart-rendering'],
    loadedBrandRefs: [],
    scaffoldedFiles: [{ kind: 'dashboard-shell', destPath: 'App.jsx', bytes: 1200 }],
    lastDone: {
      status: 'ok',
      path: 'App.jsx',
      mutationSeq: 2,
      errorCount: 0,
      checkedAt: '2026-05-05T00:00:00.000Z',
    },
    mutationSeq: 2,
  };
}

function chatRow(seq: number, kind: ChatMessageRow['kind'], payload: unknown): ChatMessageRow {
  return {
    schemaVersion: 1,
    id: seq,
    designId: 'design-1',
    seq,
    kind,
    payload,
    snapshotId: null,
    createdAt: `2026-05-05T00:00:${String(seq).padStart(2, '0')}.000Z`,
  };
}

function userRow(seq: number, text: string): ChatMessageRow {
  return chatRow(seq, 'user', { text });
}

function assistantRow(seq: number, text: string): ChatMessageRow {
  return chatRow(seq, 'assistant_text', { text });
}

function agentUser(text: string): AgentMessage {
  return { role: 'user', content: [{ type: 'text', text }] } as unknown as AgentMessage;
}

describe('buildDesignContextPack', () => {
  it('selects recent history by budget instead of a fixed 12-message cap', () => {
    const rows: ChatMessageRow[] = [];
    for (let i = 0; i < 30; i++) {
      rows.push(userRow(i * 2, `user turn ${i} ${'x'.repeat(80)}`));
      rows.push(assistantRow(i * 2 + 1, `assistant turn ${i} ${'y'.repeat(80)}`));
    }

    const pack = buildDesignContextPack({
      chatRows: rows,
      brief: baseBrief(),
      resourceState: baseResourceState(),
      workspaceState: { sourcePath: 'App.jsx', hasSource: true, hasDesignMd: true },
      historyBudgetChars: 1_800,
    });

    expect(pack.history.length).toBeGreaterThan(12);
    expect(pack.history.at(-1)?.content).toContain('assistant turn 29');
    expect(pack.trace.droppedMessages).toBeGreaterThan(0);
    expect(pack.trace.historyChars).toBeLessThanOrEqual(pack.trace.contextBudgetChars);
  });

  it('keeps the most recent two user turns when budget allows', () => {
    const rows = [
      userRow(0, 'first request'),
      assistantRow(1, 'first answer'),
      userRow(2, 'second request'),
      assistantRow(3, 'second answer'),
      userRow(4, 'third request'),
      assistantRow(5, 'third answer'),
    ];

    const pack = buildDesignContextPack({
      chatRows: rows,
      brief: baseBrief(),
      resourceState: baseResourceState(),
      workspaceState: { sourcePath: 'App.jsx', hasSource: true },
      historyBudgetChars: 500,
    });

    expect(pack.history.map((m) => m.content)).toContain('second request');
    expect(pack.history.map((m) => m.content)).toContain('third request');
  });

  it('drops old chat rows while still injecting the design session brief', () => {
    const pack = buildDesignContextPack({
      chatRows: [
        userRow(0, `old request ${'x'.repeat(1000)}`),
        assistantRow(1, `old answer ${'y'.repeat(1000)}`),
        userRow(2, 'latest request'),
      ],
      brief: baseBrief({ goal: 'Preserve the calm finance dashboard direction.' }),
      resourceState: baseResourceState(),
      workspaceState: { sourcePath: 'App.jsx', hasSource: true },
      historyBudgetChars: 80,
    });

    expect(pack.history.map((m) => m.content)).toEqual(['latest request']);
    expect(pack.contextSections.join('\n')).toContain(
      'Preserve the calm finance dashboard direction.',
    );
  });

  it('filters tool, artifact, and error rows out of model history', () => {
    const toolPayload: ChatToolCallPayload = {
      toolName: 'preview',
      args: {},
      status: 'done',
      startedAt: '2026-05-05T00:00:00.000Z',
      verbGroup: 'Preview',
    };
    const pack = buildDesignContextPack({
      chatRows: [
        userRow(0, 'make a dashboard'),
        chatRow(1, 'tool_call', toolPayload),
        chatRow(2, 'artifact_delivered', { createdAt: 'now' }),
        chatRow(3, 'error', { message: 'boom' }),
        assistantRow(4, 'done'),
      ],
      brief: null,
      resourceState: baseResourceState(),
      workspaceState: { sourcePath: 'App.jsx', hasSource: true },
      historyBudgetChars: 500,
    });

    expect(pack.history).toEqual([
      { role: 'user', content: 'make a dashboard' },
      { role: 'assistant', content: 'done' },
    ]);
  });

  it('injects durable run preferences into the design context pack', () => {
    const pack = buildDesignContextPack({
      chatRows: [
        userRow(0, 'make a dashboard'),
        chatRow(1, 'tool_call', {
          toolName: 'ask',
          args: {},
          status: 'done',
          result: { answers: [{ questionId: 'tweaks', value: 'no' }] },
          startedAt: '2026-05-05T00:00:00.000Z',
          verbGroup: 'Ask',
        }),
      ],
      runPreferences: {
        schemaVersion: 1,
        tweaks: 'no',
        bitmapAssets: 'auto',
        reusableSystem: 'yes',
        visualDirection: 'professional',
      },
      historyBudgetChars: 500,
    });

    expect(pack.history).toEqual([{ role: 'user', content: 'make a dashboard' }]);
    const context = pack.contextSections.join('\n');
    expect(context).toContain('Run preferences:');
    expect(context).toContain('- tweaks: no');
    expect(context).toContain('- bitmapAssets: auto');
    expect(context).toContain('- reusableSystem: yes');
    expect(context).toContain('- visualDirection: professional');
  });

  it('uses model context window only to reduce small-model history budgets', () => {
    const largeModel = buildDesignContextPack({
      chatRows: [userRow(0, 'request')],
      modelContextWindow: 1_000_000,
    });
    const smallModel = buildDesignContextPack({
      chatRows: [userRow(0, 'request')],
      modelContextWindow: 80_000,
    });

    expect(largeModel.trace.contextBudgetChars).toBe(12_000);
    expect(smallModel.trace.contextBudgetChars).toBe(4_800);
  });
});

describe('updateDesignSessionBrief', () => {
  it('parses model JSON into a normalized design session brief', async () => {
    completeWithRetryMock.mockResolvedValueOnce({
      content: JSON.stringify({
        goal: 'Refine onboarding screens',
        artifactType: 'mobile-app',
        audience: 'New users',
        visualDirection: 'Friendly, clean',
        stableDecisions: ['Use green accent'],
        userPreferences: ['More whitespace'],
        dislikes: ['No stock photos'],
        openTasks: ['Add empty state'],
        currentFiles: ['App.jsx'],
        lastVerification: { status: 'ok', path: 'App.jsx', errorCount: 0 },
        lastUserIntent: 'Make it warmer',
        sourceUserMemoryHash: 'user-new',
        sourceWorkspaceMemoryHash: 'workspace-new',
        sourceMemoryUpdatedAt: '2026-05-05T01:00:00.000Z',
      }),
      inputTokens: 1,
      outputTokens: 1,
      costUsd: 0,
    });

    const result = await updateDesignSessionBrief({
      existingBrief: baseBrief(),
      conversationMessages: [agentUser('Make it warmer')],
      designId: 'design-1',
      designName: 'Onboarding',
      model: MODEL,
      apiKey: 'sk-test',
      userMemory: '# User Design Memory\n- Prefer dense tools',
      workspaceMemory: '# Project Memory\n- Onboarding prototype',
      sourceUserMemoryHash: 'user-new',
      sourceWorkspaceMemoryHash: 'workspace-new',
      sourceMemoryUpdatedAt: '2026-05-05T01:00:00.000Z',
    });

    expect(result.brief).toMatchObject({
      schemaVersion: 1,
      designId: 'design-1',
      designName: 'Onboarding',
      goal: 'Refine onboarding screens',
      artifactType: 'mobile-app',
      lastUserIntent: 'Make it warmer',
      sourceUserMemoryHash: 'user-new',
      sourceWorkspaceMemoryHash: 'workspace-new',
      sourceMemoryUpdatedAt: '2026-05-05T01:00:00.000Z',
    });
    expect(completeWithRetryMock.mock.calls[0]?.[1][1].content).toContain('## Global User Memory');
    expect(completeWithRetryMock.mock.calls[0]?.[1][1].content).toContain('## Workspace MEMORY.md');
  });

  it('rejects invalid JSON so callers keep the previous brief', async () => {
    completeWithRetryMock.mockResolvedValueOnce({
      content: 'not json',
      inputTokens: 1,
      outputTokens: 1,
      costUsd: 0,
    });

    await expect(
      updateDesignSessionBrief({
        existingBrief: baseBrief(),
        conversationMessages: [agentUser('Make it warmer')],
        designId: 'design-1',
        designName: 'Onboarding',
        model: MODEL,
        apiKey: 'sk-test',
      }),
    ).rejects.toThrow(/valid JSON/);
  });
});
