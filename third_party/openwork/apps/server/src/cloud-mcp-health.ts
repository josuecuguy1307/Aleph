import type { ServerConfig, WorkspaceInfo } from "./types.js";

/** The proprietary OpenWork cloud MCP is intentionally absent. */
export type CloudMcpHealth = {
  desired: { present: boolean };
  usable: boolean;
  /** [Aleph] Faltaba, y `agent-context-diagnostics.ts:259` la lee para decidir la rama de
   *  Connect (`health.usableByCurrentModel !== false`). Es opcional porque el diagnóstico
   *  ya contempla que no venga: sin MCP de la nube, la rama cae en «cloud-disconnected»
   *  igual, que es lo correcto acá. */
  usableByCurrentModel?: boolean;
  /** [Aleph] Estaba tipado `null` a secas, pero sus consumidores le leen cuatro campos
   *  (`connect-state.ts:121` usa `.code`; `server.ts:4334-4337` los cuatro) y con `null`
   *  TypeScript los resuelve como `never`. Se declara la FORMA del fallo y se admite `null`
   *  para el caso normal de esta importación: sin MCP de nube nunca hay un primer fallo. */
  firstFailure: {
    code: string;
    stage?: string;
    retryable?: boolean;
    message?: string;
  } | null;
};

/** [Aleph] Las dos listas que el arnés de `connect-state.test.ts` sirve como catálogo de
 *  herramientas esperadas. La nube fue amputada, así que no hay nada que esperar: quedan
 *  VACÍAS y con su tipo, para que el test siga compilando y describa el estado real
 *  —ninguna herramienta de la nube— en vez de no compilar. */
export const OPENWORK_CLOUD_EXPECTED_TOOLS: readonly string[] = [];
export const OPENWORK_CLOUD_PLUGIN_CANARIES: readonly string[] = [];

export type CloudMcpProviderModelContext = { provider: string; model: string };
export type CloudMcpLiveStatusObserver = (...args: unknown[]) => void;
export type CloudMcpServerMetadata = Record<string, unknown>;

/** [Aleph] El segundo parámetro admite `null` además de `undefined`: quien la llama le pasa
 *  el resultado de `resolveOpencodeDirectory()`, que devuelve `string | null` cuando el
 *  workspace no tiene directorio de OpenCode. Declarar sólo `undefined` obligaba al llamador
 *  a normalizar un valor que este stub ni siquiera mira. */
export function markOpenworkCloudMcpStale(
  _workspace: unknown,
  _directory: string | null | undefined,
): void {}

/** [Aleph] Recibía `unknown`, y por eso las lambdas que `server.ts` le pasa en el mismo
 *  objeto (`registerRuntimeMcp`) perdían sus tipos: ocho «implicitly has an any type» entre
 *  sus dos llamadas. Declarar la forma no revive la nube —el cuerpo sigue devolviendo el
 *  estado deshabilitado—: sólo deja que el llamador siga siendo verificable. */
export interface ReconcileCloudMcpInput {
  registerRuntimeMcp?: (
    config: ServerConfig,
    workspace: WorkspaceInfo,
    onlyNames?: string[],
    options?: { throwOnFailure?: boolean; deferred?: boolean },
  ) => Promise<unknown>;
  refreshRegistrationFromLiveStatus?: (
    config: ServerConfig,
    workspace: WorkspaceInfo,
    name: string,
    mcpConfig: Record<string, unknown>,
    liveStatus: unknown,
    liveError?: unknown,
  ) => boolean;
  [key: string]: unknown;
}

export async function reconcilePersistedOpenworkCloudMcp(
  _input: ReconcileCloudMcpInput,
): Promise<CloudMcpHealth> {
  return { desired: { present: false }, usable: true, firstFailure: null };
}

/**
 * The vendor Connect catalogue is absent in Aleph Oficina.  Preserve the
 * server-facing diagnostic seam, but report an explicitly disabled, local
 * state without constructing a client or reaching a network endpoint.
 */
export async function readOpenworkCloudMcpHealth(_input: unknown): Promise<CloudMcpHealth> {
  return { desired: { present: false }, usable: false, firstFailure: null };
}
