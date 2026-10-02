/**
 * Parar un turno tiene que parar TODAS sus llamadas, no sólo la del agente.
 *
 * Medido antes de este cambio, contra la `.app` instalada: la memoria del workspace y el
 * brief arrancan al terminar el turno y siguen pidiéndole al cerebro mucho después de que
 * el usuario recibió su respuesta — `[workspace-memory] summarize.fail ms: 159923`, dos
 * minutos y medio de UNA llamada, ocupando un slot del CLI que comparten los seis
 * workspaces. `complete()` acepta `signal` y `retry.ts` documenta que «any AbortSignal
 * abort short-circuits immediately, no retry»: la cañería estaba hecha y nunca le llegaba
 * una señal, porque estos tres helpers no la aceptaban ni la propagaban.
 *
 * Estas pruebas fallan contra el árbol anterior: sin `signal`, la llamada se completa y
 * `completeWithRetry` reintenta los fallos transitorios como si nadie hubiera parado nada.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const completeWithRetry = vi.hoisted(() => vi.fn());
vi.mock('@open-codesign/providers', () => ({ completeWithRetry, AUXILIARY_MAX_RETRIES: 1 }));

import { updateDesignSessionBrief } from './design-context.js';
import { updateUserMemory, updateWorkspaceMemory } from './memory.js';
import { routeRunPreferences } from './run-preferences.js';

const MODELO = { provider: 'aleph-brain', modelId: 'aleph-workspace' } as const;

/** Lo que `complete()` hace de verdad con una señal ya abortada. */
function respetaLaSenal() {
  return async (
    _model: unknown,
    _messages: unknown,
    opts: { signal?: AbortSignal },
  ): Promise<never> => {
    if (opts.signal?.aborted === true) {
      const err = new Error('aborted');
      err.name = 'AbortError';
      throw err;
    }
    throw new Error('la llamada salió: la señal no llegó hasta el proveedor');
  };
}

function comun(signal: AbortSignal) {
  return {
    model: MODELO,
    apiKey: 'k',
    baseUrl: 'http://127.0.0.1:8330/v1/workspaces/brain/openai',
    signal,
  } as const;
}

describe('la señal del turno llega a sus cuatro llamadas', () => {
  // Sin esto, `calls[0]` es la llamada de la PRIMERA prueba y todas las demás miran el
  // argumento equivocado. La primera versión de este archivo daba 4 rojas por eso.
  beforeEach(() => {
    completeWithRetry.mockReset();
    completeWithRetry.mockImplementation(respetaLaSenal());
  });

  it('el router de preferencias la recibe', async () => {
    const ctrl = new AbortController();
    ctrl.abort();

    // El router NO propaga el fallo: cae a las preferencias de respaldo a propósito.
    // Lo que se comprueba acá es que la señal CRUZÓ, mirando con qué la llamaron.
    await routeRunPreferences({
      ...comun(ctrl.signal),
      prompt: 'una tarjeta de precio',
      existingPreferences: null,
    });
    expect(completeWithRetry).toHaveBeenCalledTimes(1);
    expect(completeWithRetry.mock.calls[0]?.[2]?.signal).toBe(ctrl.signal);
  });

  it('la memoria del workspace la recibe, y se corta en vez de seguir', async () => {
    const ctrl = new AbortController();
    ctrl.abort();

    await expect(
      updateWorkspaceMemory({
        ...comun(ctrl.signal),
        existingMemory: null,
        conversationMessages: [],
        workspaceName: 'w',
        designId: 'd',
        designName: 'D',
        userMemory: null,
        designMdSummary: null,
      }),
    ).rejects.toThrow(/abort/i);
    expect(completeWithRetry.mock.calls[0]?.[2]?.signal).toBe(ctrl.signal);
  });

  it('la memoria del usuario la recibe', async () => {
    const ctrl = new AbortController();
    ctrl.abort();

    await expect(
      updateUserMemory({ ...comun(ctrl.signal), existingMemory: null, candidates: ['x'] }),
    ).rejects.toThrow(/abort/i);
    expect(completeWithRetry.mock.calls[0]?.[2]?.signal).toBe(ctrl.signal);
  });

  it('el brief de la sesión la recibe', async () => {
    const ctrl = new AbortController();
    ctrl.abort();

    await expect(
      updateDesignSessionBrief({
        ...comun(ctrl.signal),
        existingBrief: null,
        conversationMessages: [],
        designId: 'd',
        designName: 'D',
      }),
    ).rejects.toThrow(/abort/i);
    expect(completeWithRetry.mock.calls[0]?.[2]?.signal).toBe(ctrl.signal);
  });

  it('sin señal, la llamada sale igual — el cierre normal no se toca', async () => {
    // La otra mitad del contrato, y es la que evita el arreglo de más: estas llamadas
    // corren sueltas DESPUÉS del turno a propósito, porque su salida alimenta al turno
    // siguiente (medido: `briefChars: 871`). Cortarlas en el cierre normal cambiaría un
    // defecto ruidoso por uno mudo.
    await expect(
      updateWorkspaceMemory({
        model: MODELO,
        apiKey: 'k',
        existingMemory: null,
        conversationMessages: [],
        workspaceName: 'w',
        designId: 'd',
        designName: 'D',
        userMemory: null,
        designMdSummary: null,
      }),
    ).rejects.toThrow(/la señal no llegó/);
    expect(completeWithRetry.mock.calls[0]?.[2]?.signal).toBeUndefined();
  });
});


/**
 * EL PRESUPUESTO DE REINTENTOS DE LO QUE NADIE ESPERA.
 *
 * MEDIDO sobre 6 llamadas (`.app` 13b44230, 2026-08-15): 5 agotaban los 3 intentos y
 * morían a 98,9 · 101,3 · 102,7 · 103,4 · 105,3 s; la única que escribió `MEMORY.md`
 * acertó en el SEGUNDO intento (65,8 s). El tercero no salvó a ninguna.
 *
 * Por eso 1 y no 0: con 0 se perdía el caso que hoy se salva. Y por eso el ROUTER queda
 * como está — a ése el turno SÍ lo espera, así que su presupuesto no es el mismo.
 */
describe('el presupuesto de reintentos separa lo que se espera de lo que no', () => {
  beforeEach(() => {
    completeWithRetry.mockReset();
    completeWithRetry.mockResolvedValue({ content: '{}', inputTokens: 1, outputTokens: 1, costUsd: 0 });
  });

  const base = { model: MODELO, apiKey: 'k' } as const;

  it('la memoria del workspace reintenta UNA vez, no tres', async () => {
    await updateWorkspaceMemory({
      ...base, existingMemory: null, conversationMessages: [], workspaceName: 'w',
      designId: 'd', designName: 'D', userMemory: null, designMdSummary: null,
    }).catch(() => undefined);
    expect(completeWithRetry.mock.calls[0]?.[3]?.maxRetries).toBe(1);
  });

  it('la memoria del usuario también', async () => {
    await updateUserMemory({ ...base, existingMemory: null, candidates: ['x'] }).catch(() => undefined);
    expect(completeWithRetry.mock.calls[0]?.[3]?.maxRetries).toBe(1);
  });

  it('el brief de la sesión también', async () => {
    await updateDesignSessionBrief({
      ...base, existingBrief: null, conversationMessages: [], designId: 'd', designName: 'D',
    }).catch(() => undefined);
    expect(completeWithRetry.mock.calls[0]?.[3]?.maxRetries).toBe(1);
  });

  it('el router NO se toca: el turno lo espera, así que conserva el presupuesto de la casa', async () => {
    await routeRunPreferences({ ...base, prompt: 'una tarjeta', existingPreferences: null });
    expect(completeWithRetry.mock.calls[0]?.[3]?.maxRetries).toBeUndefined();
  });
});
