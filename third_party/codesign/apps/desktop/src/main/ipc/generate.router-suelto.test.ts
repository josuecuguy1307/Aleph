import { mkdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import type { Design } from '@open-codesign/shared';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (event: unknown, raw: unknown) => unknown;

const handlers = vi.hoisted(() => new Map<string, Handler>());
const coreCalls = vi.hoisted(() => ({
  generateInputs: [] as unknown[],
  routeResults: [] as Array<{
    preferences: {
      schemaVersion: 1;
      tweaks: 'auto';
      bitmapAssets: 'auto';
      reusableSystem: 'auto';
    };
    needsClarification: boolean;
    clarificationRationale?: string;
    clarificationQuestions?: Array<
      | {
          id: string;
          type: 'text-options';
          prompt: string;
          options: string[];
        }
      | {
          id: string;
          type: 'freeform';
          prompt: string;
          placeholder?: string;
          multiline?: boolean;
        }
    >;
  }>,
}));

const routerControl = vi.hoisted(() => {
  let markStarted: (() => void) | null = null;
  let release: (() => void) | null = null;
  let started: Promise<void> | null = null;
  let released: Promise<void> | null = null;
  const reset = (): void => {
    started = new Promise<void>((r) => {
      markStarted = r;
    });
    released = new Promise<void>((r) => {
      release = r;
    });
  };
  reset();
  return {
    reset,
    markStarted: (): void => markStarted?.(),
    release: (): void => release?.(),
    waitUntilStarted: (): Promise<void> => started ?? Promise.resolve(),
    waitUntilReleased: (): Promise<void> => released ?? Promise.resolve(),
  };
});
const generateControl = vi.hoisted(() => {
  let markStarted: (() => void) | null = null;
  let release: (() => void) | null = null;
  let started: Promise<void>;
  let unblock: Promise<void>;
  return {
    reset(): void {
      started = new Promise((resolve) => {
        markStarted = resolve;
      });
      unblock = new Promise((resolve) => {
        release = resolve;
      });
    },
    get started(): Promise<void> {
      return started;
    },
    markStarted(): void {
      markStarted?.();
    },
    release(): void {
      release?.();
    },
    async waitUntilReleased(): Promise<void> {
      await unblock;
    },
  };
});
generateControl.reset();

vi.mock('../electron-runtime', () => ({
  app: {
    getPath: vi.fn(() => path.join(os.tmpdir(), 'open-codesign-generate-rename-tests')),
  },
  ipcMain: {
    handle: vi.fn((channel: string, handler: Handler) => {
      handlers.set(channel, handler);
    }),
  },
  dialog: {
    showOpenDialog: vi.fn(),
  },
}));

vi.mock('../logger', () => ({
  getLogger: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
}));

vi.mock('@open-codesign/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@open-codesign/core')>();
  return {
    ...actual,
    buildDesignContextPack: vi.fn(() => ({
      history: [],
      contextSections: [],
      trace: {
        briefChars: 0,
        historyChars: 0,
        selectedMessages: 0,
        droppedMessages: 0,
        contextBudgetChars: 0,
        sessionContextChars: 0,
      },
    })),
    generateViaAgent: vi.fn(async (input: unknown) => {
      coreCalls.generateInputs.push(input);
      generateControl.markStarted();
      await generateControl.waitUntilReleased();
      return { message: 'done', artifacts: [], inputTokens: 0, outputTokens: 0, costUsd: 0 };
    }),
    loadDesignSkills: vi.fn(async () => []),
    loadFrameTemplates: vi.fn(async () => []),
    // EL ROUTER, CONTROLABLE: no resuelve hasta que la prueba lo suelte. Es lo que
    // permite ver la diferencia entre «el turno lo espera» y «el turno sigue sin él».
    routeRunPreferences: vi.fn(async () => {
      routerControl.markStarted();
      await routerControl.waitUntilReleased();
      return (
        coreCalls.routeResults.shift() ?? {
          preferences: {
            schemaVersion: 1,
            tweaks: 'auto',
            bitmapAssets: 'auto',
            reusableSystem: 'auto',
          },
          needsClarification: false,
        }
      );
    }),
  };
});

vi.mock('@open-codesign/providers', () => ({
  detectProviderFromKey: vi.fn(() => 'mock'),
  generateImage: vi.fn(),
}));

vi.mock('../provider-settings', () => ({
  resolveActiveModel: vi.fn((_cfg: unknown, model: { provider: string; modelId: string }) => ({
    model,
    allowKeyless: false,
    overridden: false,
    wire: 'anthropic',
  })),
}));

vi.mock('../onboarding-ipc', () => ({
  getApiKeyForProvider: vi.fn(() => 'sk-test'),
  getCachedConfig: vi.fn(() => ({
    provider: 'mock-provider',
    modelPrimary: 'mock-model',
    designSystem: null,
  })),
  hasApiKeyForProvider: vi.fn(() => true),
}));

vi.mock('../resolve-api-key', () => ({
  resolveActiveApiKey: vi.fn(async () => 'sk-test'),
  resolveCredentialForProvider: vi.fn(async () => 'sk-test'),
}));

vi.mock('../preferences-ipc', () => ({
  readPersisted: vi.fn(async () => ({
    generationTimeoutSec: 0,
    memoryEnabled: false,
    workspaceMemoryAutoUpdate: false,
    userMemoryAutoUpdate: false,
  })),
}));

vi.mock('../prompt-context', () => ({
  preparePromptContext: vi.fn(
    async (input?: { attachments?: Array<{ path: string; name: string; size: number }> }) => ({
      attachments:
        input?.attachments?.map((file) => ({
          ...file,
          ...(file.name.toLowerCase().endsWith('.png') ? { mediaType: 'image/png' } : {}),
        })) ?? [],
      referenceUrl: null,
      designSystem: null,
      projectContext: {},
    }),
  ),
}));

vi.mock('../memory-ipc', () => ({
  loadMemoryContext: vi.fn(async () => undefined),
  triggerUserMemoryCandidateCapture: vi.fn(async () => undefined),
  triggerUserMemoryConsolidation: vi.fn(async () => undefined),
  triggerWorkspaceMemoryUpdate: vi.fn(async () => null),
  workspaceNameFromPath: vi.fn((workspacePath: string) => path.basename(workspacePath)),
}));

vi.mock('../done-verify', () => ({
  makeRuntimeVerifier: vi.fn(() => async () => []),
}));

vi.mock('../preview-runtime', () => ({
  runPreview: vi.fn(async () => ({ errors: [] })),
}));

vi.mock('../ask-ipc', () => ({
  requestAsk: vi.fn(async () => ({ status: 'answered', answers: [] })),
}));

import { routeRunPreferences } from '@open-codesign/core';
import { requestAsk } from '../ask-ipc';
import {
  appendSessionRunPreferences,
  readSessionRunPreferences,
} from '../session-chat';
import { createDesign, initInMemoryDb, updateDesignWorkspace } from '../snapshots-db';
import { registerSnapshotsIpc } from '../snapshots-ipc';
import { normalizeWorkspacePath } from '../workspace-path';
import { registerGenerateIpc } from './generate';

function getHandler(channel: string): Handler {
  const handler = handlers.get(channel);
  if (!handler) throw new Error(`Missing IPC handler: ${channel}`);
  return handler;
}

/**
 * EL ROUTER SE ESPERA SÓLO LA PRIMERA VEZ.
 *
 * Medido antes de esta obra (`.app` 13b44230, 2026-08-15): el tramo `generate` →
 * `generate.context` —que es este router— cuesta 8,1-8,8 s de los 16,1 s que el usuario
 * aguarda. Con el mismo prompt y el mismo cerebro, Ciencia (que no tiene el paso) contesta
 * en 9,4 s. Y sobre 35 llamadas en dos diseños el router devolvió 17/17 y 18/18 valores
 * IDÉNTICOS dentro de cada diseño: el valor se fija en el primer turno y no se mueve.
 *
 * Estas pruebas caen contra `main`, donde el turno espera al router SIEMPRE.
 */
describe('el router bloquea el primer turno y corre suelto en los siguientes', () => {
  const documentsRoot = path.join(os.tmpdir(), 'open-codesign-router-suelto-tests');
  const defaultWorkspaceRoot = path.join(documentsRoot, 'CoDesign');

  function initTestDb() {
    return {
      ...initInMemoryDb(),
      dataDir: path.join(documentsRoot, 'data'),
      sessionDir: path.join(documentsRoot, 'sessions'),
    };
  }

  async function montar(): Promise<{ db: ReturnType<typeof initTestDb>; design: Design }> {
    const db = initTestDb();
    const design = createDesign(db, 'Untitled design 1');
    const ws = path.join(defaultWorkspaceRoot, 'Untitled-design-1');
    await mkdir(ws, { recursive: true });
    await writeFile(path.join(ws, 'App.jsx'), 'function App() { return null; }', 'utf8');
    updateDesignWorkspace(db, design.id, ws);
    registerSnapshotsIpc(db);
    registerGenerateIpc({ db, getMainWindow: () => null });
    return { db, design };
  }

  function pedir(designId: string, id: string): Promise<unknown> {
    return Promise.resolve(
      getHandler('codesign:v1:generate')(null, {
        schemaVersion: 1,
        prompt: 'Hacé una tarjeta de precio',
        history: [],
        model: { provider: 'mock-provider', modelId: 'mock-model' },
        attachments: [],
        generationId: id,
        designId,
      }),
    );
  }

  /**
   * ¿Ya terminó, sin esperarla? Con una bandera y no con `Promise.race` contra un
   * `Promise.resolve`: ése gana la carrera aunque la otra ya esté cumplida, y la primera
   * versión de esta prueba daba rojo por eso, no por el código.
   */
  function vigilar(p: Promise<unknown>): () => Promise<boolean> {
    let lista = false;
    p.then(
      () => {
        lista = true;
      },
      () => {
        lista = true;
      },
    );
    return async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve();
      await new Promise((r) => setTimeout(r, 0));
      return lista;
    };
  }

  beforeEach(async () => {
    vi.clearAllMocks();
    handlers.clear();
    coreCalls.generateInputs.length = 0;
    coreCalls.routeResults.length = 0;
    generateControl.reset();
    routerControl.reset();
    await rm(documentsRoot, { recursive: true, force: true });
    await mkdir(defaultWorkspaceRoot, { recursive: true });
  });

  afterEach(async () => {
    generateControl.release();
    routerControl.release();
    await rm(documentsRoot, { recursive: true, force: true });
  });

  it('turno 1 (sin preferencias guardadas): el turno ESPERA al router', async () => {
    const { design } = await montar();
    const turno = pedir(design.id, 'gen-1');
    turno.catch(() => undefined);
    const yaEsta = vigilar(turno);

    await routerControl.waitUntilStarted();
    generateControl.release(); // el agente ya podría contestar…
    await new Promise((r) => setTimeout(r, 30));

    // …y sin embargo el turno sigue pendiente, porque el router no soltó.
    expect(await yaEsta()).toBe(false);

    routerControl.release();
    await turno.catch(() => undefined);
    expect(await yaEsta()).toBe(true);
  });

  it('turno 2 (con preferencias guardadas): el turno NO espera al router', async () => {
    const { db, design } = await montar();
    appendSessionRunPreferences({ db, sessionDir: db.sessionDir }, design.id, {
      schemaVersion: 1,
      tweaks: 'auto',
      bitmapAssets: 'no',
      reusableSystem: 'no',
    });

    const turno = pedir(design.id, 'gen-2');
    turno.catch(() => undefined);
    const yaEsta = vigilar(turno);
    generateControl.release();
    await turno.catch(() => undefined);

    // El router quedó corriendo detrás: el turno terminó sin él.
    expect(await yaEsta()).toBe(true);
    expect(vi.mocked(routeRunPreferences)).toHaveBeenCalled();
    routerControl.release();
  });

  it('el router suelto NO es invisible: aparece en `trailing`', async () => {
    // La obra anterior hizo visible el trabajo suelto de después del turno. Si este
    // router quedara fuera del registro, acabaríamos de crear otra auxiliar invisible,
    // que es exactamente lo que esa obra arregló.
    const { db, design } = await montar();
    appendSessionRunPreferences({ db, sessionDir: db.sessionDir }, design.id, {
      schemaVersion: 1,
      tweaks: 'auto',
      bitmapAssets: 'auto',
      reusableSystem: 'auto',
    });

    const turno = pedir(design.id, 'gen-trailing');
    turno.catch(() => undefined);
    generateControl.release();
    await turno.catch(() => undefined);

    // El turno terminó y el router sigue corriendo: tiene que estar en el ledger.
    const estado = getHandler('codesign:v1:generation-status')(null, undefined) as {
      running: Array<{ generationId: string }>;
      trailing: Array<{ generationId: string; designId: string }>;
    };
    expect(estado.running).toHaveLength(0);
    expect(estado.trailing.map((t) => t.generationId)).toContain('gen-trailing');
    expect(estado.trailing[0]?.designId).toBe(design.id);

    routerControl.release();
  });

  it('si pararon el turno, el refresco NO persiste el respaldo como si fuera fresco', async () => {
    // `routeRunPreferences` se traga el abort y devuelve el respaldo con la misma forma
    // que un acierto (`run-preferences.ts:338`). Sin el chequeo de `signal.aborted`, el
    // refresco escribía ese respaldo encima del valor guardado y lo anotaba `refresh.ok`.
    const { db, design } = await montar();
    const guardadas = {
      schemaVersion: 1 as const,
      tweaks: 'no' as const,
      bitmapAssets: 'no' as const,
      reusableSystem: 'no' as const,
    };
    appendSessionRunPreferences({ db, sessionDir: db.sessionDir }, design.id, guardadas);

    const turno = pedir(design.id, 'gen-abortado');
    turno.catch(() => undefined);

    // SE CANCELA CON EL TURNO TODAVÍA EN VUELO, y no después: `cancelGenerationRequest`
    // busca el controller en `inFlight`, y ese mapa se vacía en el `finally` del turno.
    // La primera versión de esta prueba cancelaba después de `await turno` y el cancel era
    // un no-op — daba rojo por el escenario, no por el código.
    await routerControl.waitUntilStarted();
    getHandler('codesign:v1:cancel-generation')(null, {
      schemaVersion: 1,
      generationId: 'gen-abortado',
    });
    generateControl.release();
    routerControl.release();
    await turno.catch(() => undefined);
    await new Promise((r) => setTimeout(r, 30));

    const leido = readSessionRunPreferences({ db, sessionDir: db.sessionDir }, design.id);
    expect(leido).toMatchObject({ tweaks: 'no', bitmapAssets: 'no', reusableSystem: 'no' });
  });

  it('y el valor guardado es el que gobierna ese turno', async () => {
    const { db, design } = await montar();
    appendSessionRunPreferences({ db, sessionDir: db.sessionDir }, design.id, {
      schemaVersion: 1,
      tweaks: 'no',
      bitmapAssets: 'no',
      reusableSystem: 'no',
    });

    const turno = pedir(design.id, 'gen-3');
    turno.catch(() => undefined);
    generateControl.release();
    await turno.catch(() => undefined);
    routerControl.release();

    const leido = readSessionRunPreferences(
      { db, sessionDir: db.sessionDir },
      design.id,
    );
    expect(leido?.tweaks).toBe('no');
  });
});
