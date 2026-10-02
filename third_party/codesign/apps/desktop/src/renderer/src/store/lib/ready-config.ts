import type { OnboardingState } from '@open-codesign/shared';

interface ReadyConfig extends OnboardingState {
  hasKey: true;
  provider: string;
  modelPrimary: string;
}

export function isReadyConfig(cfg: OnboardingState | null): cfg is ReadyConfig {
  if (cfg === null) return false;
  return cfg.hasKey && cfg.provider !== null && cfg.modelPrimary !== null;
}

/** Apply `update` only if the generation that produced it is still the
 *  active run — any later generation (or a cancel) snaps the branch shut. */
export function finishIfCurrent<S extends { activeGenerationId: string | null }>(
  set: (updater: (state: S) => Partial<S> | object) => void,
  generationId: string,
  update: (state: S) => Partial<S>,
): void {
  set((state) => (state.activeGenerationId === generationId ? update(state) : {}));
}
