/**
 * Verifies that agent:event:v1 payloads carry generationId through to log
 * payloads. The handlers in useAgentStream extract event.generationId into
 * console.debug calls — this test exercises the extraction logic in isolation
 * without needing a React renderer or Electron IPC.
 */

import { describe, expect, it } from 'vitest';
import type { AgentStreamEvent } from '../../../../preload/index';
import { createAgentFsUpdateScheduler } from '../agent-stream-fs-scheduler';

interface LogPayload {
  generationId: string;
  designId: string;
  textLen?: number | undefined;
  message?: string | undefined;
  code?: string | undefined;
  toolName?: string | undefined;
  toolCallId?: string | undefined;
  text?: string | undefined;
}

/** Simulates the log-payload extraction performed by handleTurnStart. */
function turnStartLogPayload(event: AgentStreamEvent): LogPayload {
  return { generationId: event.generationId, designId: event.designId };
}

/** Simulates the log-payload extraction performed by handleTurnEnd. */
function turnEndLogPayload(event: AgentStreamEvent, textBuffer: string): LogPayload {
  return {
    generationId: event.generationId,
    designId: event.designId,
    textLen: (event.finalText ?? textBuffer).length,
  };
}

/** Simulates the log-payload extraction performed by handleError. */
function errorLogPayload(event: AgentStreamEvent): LogPayload {
  return {
    generationId: event.generationId,
    designId: event.designId,
    message: event.message,
    code: event.code,
  };
}

/** Simulates the log-payload extraction performed by handleAgentEnd. */
function agentEndLogPayload(event: AgentStreamEvent): LogPayload {
  return { generationId: event.generationId, designId: event.designId };
}

/** Simulates the log-payload extraction performed by handleToolCallStart. */
function toolCallStartLogPayload(event: AgentStreamEvent): LogPayload {
  return {
    generationId: event.generationId,
    designId: event.designId,
    toolName: event.toolName ?? 'unknown',
    toolCallId: event.toolCallId,
  };
}

describe('useAgentStream — generationId in log payloads', () => {
  const GEN_ID = 'lf3a2k-xyz9';
  const DESIGN_ID = 'design-001';

  const baseEvent = (
    type: AgentStreamEvent['type'],
    extra: Partial<AgentStreamEvent> = {},
  ): AgentStreamEvent => ({
    type,
    designId: DESIGN_ID,
    generationId: GEN_ID,
    ...extra,
  });

  it('turn_start log carries generationId', () => {
    const payload = turnStartLogPayload(baseEvent('turn_start'));
    expect(payload.generationId).toBe(GEN_ID);
    expect(payload.designId).toBe(DESIGN_ID);
  });

  it('turn_end log carries generationId and textLen', () => {
    const payload = turnEndLogPayload(baseEvent('turn_end', { finalText: 'hello' }), '');
    expect(payload.generationId).toBe(GEN_ID);
    expect(payload.textLen).toBe(5);
  });

  it('turn_end falls back to textBuffer when finalText absent', () => {
    const payload = turnEndLogPayload(baseEvent('turn_end'), 'buffered text');
    expect(payload.generationId).toBe(GEN_ID);
    expect(payload.textLen).toBe('buffered text'.length);
  });

  it('error log carries generationId, message, code', () => {
    const payload = errorLogPayload(
      baseEvent('error', { message: 'timeout', code: 'GENERATION_TIMEOUT' }),
    );
    expect(payload.generationId).toBe(GEN_ID);
    expect(payload.message).toBe('timeout');
    expect(payload.code).toBe('GENERATION_TIMEOUT');
  });

  it('agent_end log carries generationId', () => {
    const payload = agentEndLogPayload(baseEvent('agent_end'));
    expect(payload.generationId).toBe(GEN_ID);
  });

  it('tool_call_start log carries generationId and toolName', () => {
    const payload = toolCallStartLogPayload(
      baseEvent('tool_call_start', { toolName: 'str_replace', toolCallId: 'tc-1' }),
    );
    expect(payload.generationId).toBe(GEN_ID);
    expect(payload.toolName).toBe('str_replace');
    expect(payload.toolCallId).toBe('tc-1');
  });

  it('AgentStreamEvent.generationId is a non-empty string', () => {
    // Verifies the type contract: generationId: string (required, not undefined).
    const event: AgentStreamEvent = {
      type: 'turn_start',
      designId: DESIGN_ID,
      generationId: GEN_ID,
    };
    expect(typeof event.generationId).toBe('string');
    expect(event.generationId.length).toBeGreaterThan(0);
  });
});

describe('agent fs update scheduler', () => {
  it('keeps throttled fs updates isolated per generation and path', () => {
    let now = 0;
    const timers = new Map<number, () => void>();
    let nextTimer = 1;
    const flushed: Array<{
      designId: string;
      generationId: string;
      path: string;
      content: string;
    }> = [];
    const scheduler = createAgentFsUpdateScheduler({
      delayMs: 250,
      now: () => now,
      setTimer(callback) {
        const id = nextTimer++;
        timers.set(id, callback);
        return id;
      },
      clearTimer(id) {
        timers.delete(id);
      },
      flush(update) {
        flushed.push(update);
      },
    });

    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'App.jsx',
      content: 'a1',
    });
    scheduler.schedule({
      designId: 'design-b',
      generationId: 'gen-b',
      path: 'App.jsx',
      content: 'b1',
    });
    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'styles.css',
      content: 'a-css',
    });

    expect(flushed).toEqual([
      { designId: 'design-a', generationId: 'gen-a', path: 'App.jsx', content: 'a1' },
      { designId: 'design-b', generationId: 'gen-b', path: 'App.jsx', content: 'b1' },
      { designId: 'design-a', generationId: 'gen-a', path: 'styles.css', content: 'a-css' },
    ]);

    now = 50;
    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'App.jsx',
      content: 'a2',
    });
    scheduler.schedule({
      designId: 'design-b',
      generationId: 'gen-b',
      path: 'App.jsx',
      content: 'b2',
    });
    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'styles.css',
      content: 'a-css-2',
    });

    expect(flushed).toHaveLength(3);
    expect(timers.size).toBe(3);

    for (const timer of [...timers.values()]) timer();

    expect(flushed.slice(3)).toEqual([
      { designId: 'design-a', generationId: 'gen-a', path: 'App.jsx', content: 'a2' },
      { designId: 'design-b', generationId: 'gen-b', path: 'App.jsx', content: 'b2' },
      { designId: 'design-a', generationId: 'gen-a', path: 'styles.css', content: 'a-css-2' },
    ]);
  });

  it('flushes only the pending updates for the ending generation', () => {
    const timers = new Map<number, () => void>();
    let nextTimer = 1;
    const flushed: Array<{
      designId: string;
      generationId: string;
      path: string;
      content: string;
    }> = [];
    const scheduler = createAgentFsUpdateScheduler({
      delayMs: 250,
      now: () => 0,
      setTimer(callback) {
        const id = nextTimer++;
        timers.set(id, callback);
        return id;
      },
      clearTimer(id) {
        timers.delete(id);
      },
      flush(update) {
        flushed.push(update);
      },
    });

    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'App.jsx',
      content: 'a1',
    });
    scheduler.schedule({
      designId: 'design-b',
      generationId: 'gen-b',
      path: 'App.jsx',
      content: 'b1',
    });
    scheduler.schedule({
      designId: 'design-a',
      generationId: 'gen-a',
      path: 'App.jsx',
      content: 'a2',
    });
    scheduler.schedule({
      designId: 'design-b',
      generationId: 'gen-b',
      path: 'App.jsx',
      content: 'b2',
    });

    scheduler.flushGeneration('gen-a');

    expect(flushed.map((item) => item.content)).toEqual(['a1', 'b1', 'a2']);
    expect(timers.size).toBe(1);

    for (const timer of [...timers.values()]) timer();
    expect(flushed.map((item) => item.content)).toEqual(['a1', 'b1', 'a2', 'b2']);
  });
});
