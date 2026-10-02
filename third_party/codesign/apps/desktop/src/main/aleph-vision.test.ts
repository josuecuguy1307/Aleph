import { describe, expect, it } from 'vitest';
import { alephPreviewVision, selectedVisionCapability } from './aleph-vision';

describe('actual selected preview capability', () => {
  const modelos = [
    { picker_id: 'codex_cli', model_use_capabilities: ['text', 'tool_calling'] },
    { picker_id: 'claude_cli', model_use_capabilities: ['text', 'tool_calling', 'vision'] },
  ];
  it('uses the selected model rather than another model or the wire protocol', () => {
    expect(selectedVisionCapability({ seleccion_id: 'codex_cli', modelos })).toBe(false);
    expect(selectedVisionCapability({ seleccion_id: 'claude_cli', modelos })).toBe(true);
    expect(() => selectedVisionCapability({ seleccion_id: 'unknown', modelos })).toThrow('capacidades');
  });
  it('does not forward local credentials to an unrelated host', async () => {
    await expect(alephPreviewVision({ provider: 'aleph-brain', baseUrl: 'https://example.com/v1/workspaces/brain/openai', requested: true })).rejects.toThrow('endpoint local');
    expect(await alephPreviewVision({ provider: 'openai', requested: true })).toBe(true);
    expect(await alephPreviewVision({ provider: 'aleph-brain', requested: false })).toBe(false);
  });
});
