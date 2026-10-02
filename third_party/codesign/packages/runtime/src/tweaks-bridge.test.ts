import { afterEach, describe, expect, it, vi } from 'vitest';
import { TWEAKS_BRIDGE_LISTENER, TWEAKS_BRIDGE_SETUP } from './tweaks-bridge';

type MessageListener = (event: { data: unknown }) => void;

function installTweaksBridge() {
  const listeners = new Map<string, MessageListener>();
  const setProperty = vi.fn();
  const transform = vi.fn();
  const fakeWindow = {
    Babel: { transform },
    ReactDOM: {
      createRoot: vi.fn(() => ({ render: vi.fn() })),
    },
    addEventListener: vi.fn((type: string, listener: MessageListener) => {
      listeners.set(type, listener);
    }),
    requestAnimationFrame: vi.fn((callback: () => void) => {
      callback();
      return 1;
    }),
  };
  const fakeDocument = {
    documentElement: {
      style: { setProperty },
    },
  };
  vi.stubGlobal('window', fakeWindow);
  vi.stubGlobal('document', fakeDocument);

  new Function(TWEAKS_BRIDGE_SETUP)();
  new Function(TWEAKS_BRIDGE_LISTENER)();

  return {
    listeners,
    setProperty,
    transform,
    window: fakeWindow as typeof fakeWindow & {
      __codesign_tweaks__: {
        applyInitial: (source: string) => void;
        registerRunner: (runner: () => void) => void;
      };
    },
  };
}

describe('tweaks bridge', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('hydrates initial EDITMODE tokens into canonical CSS custom properties', () => {
    const bridge = installTweaksBridge();

    bridge.window.__codesign_tweaks__.applyInitial(
      'const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{"accentColor":"#f97316","density":1.25,"darkMode":false}/*EDITMODE-END*/;',
    );

    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-accent-color', '#f97316');
    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-density', '1.25');
    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-dark-mode', '0');
  });

  it('applies live updates without invoking Babel', () => {
    const bridge = installTweaksBridge();
    const listener = bridge.listeners.get('message');
    const runner = vi.fn();
    bridge.window.__codesign_tweaks__.registerRunner(runner);
    expect(listener).toBeDefined();

    listener?.({
      data: {
        type: 'codesign:tweaks:update',
        tokens: { accentColor: '#0ea5e9', radiusBase: '12px', enabled: true },
      },
    });

    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-accent-color', '#0ea5e9');
    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-radius-base', '12px');
    expect(bridge.setProperty).toHaveBeenCalledWith('--ocd-tweak-enabled', '1');
    expect(runner).toHaveBeenCalledOnce();
    expect(bridge.transform).not.toHaveBeenCalled();
  });
});
