import { describe, expect, it, vi } from 'vitest';
import { createCodesignApi } from './index';

vi.mock('electron', () => ({ contextBridge: { __alephStub: true }, ipcRenderer: {} }));

describe('shared permission facade', () => {
  it('delivers the actual request and sends only the chosen decision through IPC', async () => {
    const invoke = vi.fn(async () => undefined);
    const on = vi.fn();
    const removeListener = vi.fn();
    const api = createCodesignApi({ invoke, on, removeListener });
    const received = vi.fn();
    const off = api.permission.onRequest(received);
    const request = { requestId: 'perm-e2e', sessionId: 'design-e2e', command: 'python3 validate.py' };
    on.mock.calls[0]?.[1](undefined, request);
    expect(received).toHaveBeenCalledWith(request);
    await api.permission.resolve(request.requestId, 'deny');
    expect(invoke).toHaveBeenCalledWith('permission:resolve', { requestId: 'perm-e2e', scope: 'deny' });
    off();
    expect(removeListener).toHaveBeenCalledWith('permission:request', on.mock.calls[0]?.[1]);
  });
});
