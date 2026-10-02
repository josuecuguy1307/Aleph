/**
 * Runtime OpenCode configuration injected via a server-managed config file
 * passed to the engine as OPENCODE_CONFIG.
 *
 * This is the single source of truth for the openwork agent definition,
 * plugins, and any other config that should be injected at runtime rather
 * than written to the user's own config files. Both cli.ts and embedded.ts
 * use this.
 *
 * The engine re-reads the OPENCODE_CONFIG file from disk on every instance
 * rebuild (e.g. /instance/dispose), so the file is synchronized on every
 * runtime-DB write — unlike the previous OPENCODE_CONFIG_CONTENT env var,
 * which was frozen at spawn and reverted MCP state on each dispose.
 */
import { join } from "node:path";
import { safeEnsureAbsoluteDir as mkdir, safeReadAbsoluteFile as readFile,
         safeWriteAbsoluteFile as writeFile } from "./safe-fs.js";
import {
  openworkAnthropicAdaptiveThinkingPluginPath,
  openworkAnthropicToolSchemaPluginPath,
  openworkOfficeAttachmentsPluginPath,
} from "./openwork-extensions-plugin-path.js";
import type { ServerConfig } from "./types.js";
import { runtimeStorageDir } from "./runtime-db.js";
import {
  onRuntimeOpencodeConfigWrite,
  isEngineGlobalRuntimeConfigId,
  readEffectiveRuntimeOpencodeConfig,
  runtimeDisabledProviderList,
  runtimeMcpMap,
  runtimeProviderMap,
  runtimePluginList,
  type RuntimeOpencodeConfig,
} from "./runtime-opencode-config-store.js";

const ALEPH_OFICINA_AGENT_PROMPT = `Eres Aleph Oficina.

Cuando la persona se refiere a "vos", se refiere al espacio de trabajo actual de Aleph Oficina.

Your job:
- Help the user work on files safely.
- Automate repeatable work.
- Keep behavior portable and reproducible.

## Memory

Two kinds:
1. Behavior memory (shareable, in git): .opencode/skills/**, .opencode/agents/**, repo docs
2. Private memory (never commit): tokens, credentials, local config, logs

Hard rule: never copy private memory into repo files. Store only redacted summaries, schemas, and stable pointers.

## Working style

- If required setup or credentials are missing, ask one targeted question and continue once provided.
- If you change code, run the smallest meaningful test.
- If steps repeat, factor them into a skill.
- Prefer clear, practical steps over abstract explanations.

## Artefactos de Oficina

Aleph Oficina puede previsualizar, editar y entregar artefactos estándar cuando los creás o actualizás en el workspace.

- Prefer standard output files for user-visible deliverables: Markdown (.md), CSV (.csv), Excel workbooks (.xlsx), PowerPoint decks (.pptx), and browser previews (index.html or a local http://localhost:<port> URL).
- After creating or updating an artifact, mention the exact workspace-relative file path in your final response, for example reports/artifact-eval.md or reports/artifact-eval.xlsx.
- Do not invent Workspace/<id>/... paths unless a tool returns them; prefer clean workspace-relative paths.
- For websites or React/UI previews, start the dev server when useful and mention the http://localhost:<port> URL.
- For spreadsheets, use .csv for simple tabular data and .xlsx when the user asks for Excel/XLS specifically.

## Memoria y credenciales

No persistas secretos, credenciales, API keys, tokens o PII sensible en archivos del workspace. No supongas que existen capacidades cloud ni herramientas de memoria: usá sólo herramientas que estén configuradas y visibles en esta sesión. Para acciones externas sensibles —enviar correo, borrar datos o crear/modificar eventos— pedí confirmación explícita antes de ejecutar.`;

export async function buildOpenworkRuntimeConfigObject(
  config?: ServerConfig,
  workspaceId?: string,
): Promise<Record<string, unknown>> {
  const runtimeConfig = config && workspaceId ? await readEffectiveRuntimeOpencodeConfig(config, workspaceId) : {};
  return buildOpenworkRuntimeConfigObjectFromSnapshot(runtimeConfig);
}

export function buildOpenworkRuntimeConfigObjectFromSnapshot(
  runtimeConfig: RuntimeOpencodeConfig,
): Record<string, unknown> {
  const disabledProviders = runtimeDisabledProviderList(runtimeConfig);
  const provider = runtimeProviderMap(runtimeConfig);
  return {
    ...runtimeConfig,
    default_agent: runtimeConfig.default_agent ?? "openwork",
    agent: {
      openwork: {
        description: "Agente principal de Aleph Oficina",
        mode: "primary",
        temperature: 0.2,
        prompt: ALEPH_OFICINA_AGENT_PROMPT,
        permission: {
          skill: {
            // OpenWork supplies its own current skill routing and no longer
            // supports these engine or legacy workspace skills.
            "customize-opencode": "deny",
            "get-started": "deny",
            "command-creator": "deny",
            "agent-creator": "deny",
            "plugin-creator": "deny",
          },
        },
      },
    },
    plugin: [
      "opencode-chrome-devtools",
      openworkOfficeAttachmentsPluginPath(),
      openworkAnthropicAdaptiveThinkingPluginPath(),
      openworkAnthropicToolSchemaPluginPath(),
      ...runtimePluginList(runtimeConfig),
    ],
    ...(disabledProviders.length ? { disabled_providers: disabledProviders } : {}),
    mcp: runtimeMcpMap(runtimeConfig),
    ...(Object.keys(provider).length ? { provider } : {}),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableJsonValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, stableJsonValue(value[key])]),
  );
}

function stableStringify(value: unknown): string {
  return JSON.stringify(stableJsonValue(value));
}

export async function buildOpenworkRuntimeConfig(config?: ServerConfig, workspaceId?: string): Promise<string> {
  return stableStringify(await buildOpenworkRuntimeConfigObject(config, workspaceId));
}

export function openworkRuntimeConfigFilePath(config: ServerConfig): string {
  return join(runtimeStorageDir(config), "runtime-opencode-config.json");
}

// Serialize file writes per path so a slow older write can never land after
// (and clobber) a newer one. Content is built inside the queued job so each
// job reads the latest runtime-DB state.
export interface OpenworkRuntimeConfigWriteResult {
  path: string;
  changed: boolean;
}

const fileWriteQueue = new Map<string, Promise<OpenworkRuntimeConfigWriteResult>>();

/**
 * Rebuild the engine-visible runtime config file from the runtime DB.
 * Atomic (temp file + rename) so the engine never reads a partial file
 * mid-dispose.
 */
export async function writeOpenworkRuntimeConfigFile(
  config: ServerConfig,
  workspaceId: string,
): Promise<OpenworkRuntimeConfigWriteResult> {
  const path = openworkRuntimeConfigFilePath(config);
  const job = async () => {
    const content = await buildOpenworkRuntimeConfig(config, workspaceId);
    const current = await readFile(path, "utf8").catch(() => undefined);
    if (current === content) return { path, changed: false };
    await mkdir(runtimeStorageDir(config));
    await writeFile(path, content);
    return { path, changed: true };
  };
  const previous = fileWriteQueue.get(path) ?? Promise.resolve();
  const next = previous.then(job, job);
  fileWriteQueue.set(path, next);
  return await next;
}

/**
 * Keep the runtime config file in sync with the runtime DB so every engine
 * instance rebuild reads fresh state instead of a spawn-time snapshot.
 * Returns an unsubscribe function.
 */
export function keepOpenworkRuntimeConfigFileFresh(config: ServerConfig, workspaceId: string): () => void {
  return onRuntimeOpencodeConfigWrite((writeConfig, writtenWorkspaceId) => {
    if (writtenWorkspaceId !== workspaceId && !isEngineGlobalRuntimeConfigId(writtenWorkspaceId)) return;
    void writeOpenworkRuntimeConfigFile(writeConfig, workspaceId).catch(() => undefined);
  });
}
