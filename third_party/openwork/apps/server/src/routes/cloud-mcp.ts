import type { ServerConfig, WorkspaceInfo } from "../types.js";

/** No remote OpenWork cloud MCP routes are exposed by Aleph Office.
 *
 * [Aleph] El stub recibía `_input: unknown`, y eso tenía un costo que no se ve hasta que
 * se corre el typecheck: `server.ts` le pasa un objeto con lambdas —`registerRuntimeMcp`,
 * `refreshRegistrationFromLiveStatus`— y sin una forma declarada TypeScript no puede
 * inferir los parámetros de esas funciones. Salían ocho «implicitly has an any type», que
 * no son un problema del stub sino de quien lo llama.
 *
 * Declarar la forma no reintroduce nada: el cuerpo sigue vacío y no hay ruta de nube. Lo
 * que hace es que el contrato siga siendo verificable desde el llamador. */
export interface RegisterCloudMcpRoutesOptions {
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

export function registerCloudMcpRoutes(_input: RegisterCloudMcpRoutesOptions): void {}
