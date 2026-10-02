import path_module from 'node:path';
import {
  type AgentEvent,
  type AskInput,
  applyRunPreferenceAnswers,
  buildApplyCommentUserPrompt,
  buildDesignContextPack,
  buildRunProtocolPreflight,
  type CoreLogger,
  composeSystemPrompt,
  type DesignSessionBriefV1,
  formatRunProtocolPreflightAnswers,
  generateTitle,
  generateViaAgent,
  inspectWorkspaceFiles,
  loadDesignSkills,
  loadFrameTemplates,
  routeRunPreferences,
  updateDesignSessionBrief,
} from '@open-codesign/core';
import { complete, detectProviderFromKey } from '@open-codesign/providers';
import {
  ApplyCommentPayload,
  CancelGenerationPayloadV1,
  CodesignError,
  type Config,
  deriveResourceStateFromChatRows,
  GeneratePayloadV1,
} from '@open-codesign/shared';
import { computeFingerprint } from '@open-codesign/shared/fingerprint';
import type { BrowserWindow as ElectronBrowserWindow } from 'electron';
import type { AgentStreamEvent } from '../../preload/index';
import { requestAsk } from '../ask-ipc';
import { alephPreviewVision } from '../aleph-vision';
import { makeRuntimeVerifier } from '../done-verify';
import { app, ipcMain } from '../electron-runtime';
import {
  acquireInFlightWorkspaceGeneration,
  armGenerationTimeout,
  cancelGenerationRequest,
  extractGenerationTimeoutError,
  listInFlightGenerations,
  withInFlightGenerationForDesign,
} from '../generation-ipc';
import { resolveGenerationWorkspaceRoot } from '../generation-workspace';
import { makeJudgeVisualParity } from '../judge-visual-parity';
import { getLogger } from '../logger';
import {
  loadMemoryContext,
  triggerUserMemoryCandidateCapture,
  triggerUserMemoryConsolidation,
  triggerWorkspaceMemoryUpdate,
  workspaceNameFromPath,
} from '../memory-ipc';
import { getApiKeyForProvider, getCachedConfig, hasApiKeyForProvider } from '../onboarding-ipc';
import { readPersisted as readPreferences } from '../preferences-ipc';
import { runPreview } from '../preview-runtime';
import { preparePromptContext } from '../prompt-context';
import { createProviderContextStore } from '../provider-context';
import { resolveActiveModel } from '../provider-settings';
import { makeUiKitRenderer } from '../render-ui-kit';
import { resolveCredentialForProvider } from '../resolve-api-key';
import { withRun } from '../runContext';
import {
  appendSessionDesignBrief,
  appendSessionRunPreferences,
  listSessionChatMessages,
  readSessionDesignBrief,
  readSessionRunPreferences,
  type SessionChatStoreOptions,
} from '../session-chat';
import { type Database, getDesign, recordDiagnosticEvent } from '../snapshots-db';
import { withTlsBypass } from '../tls-override';
import { withStableWorkspacePath } from '../workspace-path-lock';
import { listWorkspaceFilesAt, readWorkspaceFilesAt } from '../workspace-reader';
import { finalAssistantTextForTurn } from './assistant-text';
import { allocateAssetPath, createRuntimeTextEditorFs, resolveLocalAssetRefs } from './runtime-fs';
import { summarizeToolResultForStream, toolExecutionStatusForStream } from './tool-log';

const DEFAULT_CONTEXT_WINDOW_FOR_CONTEXT_PACK = 200_000;

export function contextWindowForContextPack(model: unknown): number {
  const value = (model as { contextWindow?: unknown } | null)?.contextWindow;
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value
    : DEFAULT_CONTEXT_WINDOW_FOR_CONTEXT_PACK;
}

/**
 * Whether outbound pi-ai requests for the given provider should bypass TLS
 * certificate verification. True only for non-built-in providers whose
 * persisted entry opts in via `tlsRejectUnauthorized: true`. Built-in
 * providers force-ignore the flag (security floor — see issue #229).
 */
function resolveTlsBypassFor(cfg: Config, providerId: string): boolean {
  const entry = cfg.providers?.[providerId];
  return entry !== undefined && entry.builtin !== true && entry.tlsRejectUnauthorized === true;
}

export function shouldRunUserMemoryCandidateCapture(prefs: {
  memoryEnabled: boolean;
  userMemoryAutoUpdate: boolean;
}): boolean {
  return prefs.memoryEnabled === true && prefs.userMemoryAutoUpdate === true;
}

export function buildRunPreferenceAskInput(
  questions: AskInput['questions'],
  rationale?: string | undefined,
): AskInput {
  return {
    ...(rationale !== undefined && rationale.trim().length > 0
      ? { rationale: rationale.trim() }
      : {}),
    questions,
  };
}

function recentHistoryForRunPreferenceRouter(
  chatRows: ReturnType<typeof listSessionChatMessages>,
): string {
  return chatRows
    .slice(-12)
    .map((row) => {
      if (row.kind !== 'user' && row.kind !== 'assistant_text') return null;
      const text =
        typeof (row.payload as { text?: unknown }).text === 'string'
          ? (row.payload as { text: string }).text
          : '';
      return text.trim().length > 0 ? `[${row.kind}] ${text.trim().slice(0, 800)}` : null;
    })
    .filter((line): line is string => line !== null)
    .join('\n');
}

function chatRowText(row: ReturnType<typeof listSessionChatMessages>[number]): string {
  const payload = row.payload as { text?: unknown };
  return typeof payload.text === 'string' ? payload.text : '';
}

function comparablePromptText(text: string): string {
  return text.trim().replace(/\s+/g, ' ');
}

function isCurrentPromptEcho(
  row: ReturnType<typeof listSessionChatMessages>[number],
  currentPrompt: string,
): boolean {
  if (row.kind !== 'user') return false;
  const rowText = comparablePromptText(chatRowText(row));
  if (rowText.length === 0) return false;
  const promptText = comparablePromptText(currentPrompt);
  return promptText === rowText || promptText.endsWith(rowText);
}

export function dropCurrentPromptEchoFromChatRows(
  chatRows: ReturnType<typeof listSessionChatMessages>,
  currentPrompt: string,
): ReturnType<typeof listSessionChatMessages> {
  const last = chatRows.at(-1);
  if (last === undefined || !isCurrentPromptEcho(last, currentPrompt)) return chatRows;
  return chatRows.slice(0, -1);
}

function sendPreflightAskEvent(
  getMainWindow: () => ElectronBrowserWindow | null,
  event: AgentStreamEvent,
): void {
  getMainWindow()?.webContents.send('agent:event:v1', event satisfies AgentStreamEvent);
}

function designMdSummaryForMemory(
  projectContext: Awaited<ReturnType<typeof preparePromptContext>>['projectContext'],
): string | null {
  const raw = projectContext.designMd ?? projectContext.invalidDesignMd?.raw ?? null;
  if (raw === null || raw.trim().length === 0) return null;
  const headings = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => /^#{1,3}\s+\S/.test(line))
    .slice(0, 24);
  if (headings.length === 0) {
    return projectContext.invalidDesignMd
      ? 'DESIGN.md exists but currently fails validation.'
      : 'DESIGN.md exists and should remain the authoritative design-system source.';
  }
  return [
    projectContext.invalidDesignMd
      ? 'DESIGN.md exists but currently fails validation.'
      : 'DESIGN.md exists and should remain the authoritative design-system source.',
    'Headings:',
    ...headings.map((heading) => `- ${heading.replace(/^#+\s*/, '')}`),
  ].join('\n');
}

function extractUserMessagesForMemory(messages: DesignBriefConversationMessages): string[] {
  const out: string[] = [];
  for (const msg of messages) {
    if (msg.role !== 'user') continue;
    const content = (msg as { content?: unknown }).content;
    if (typeof content === 'string') {
      const trimmed = content.trim();
      if (trimmed.length > 0) out.push(trimmed);
      continue;
    }
    if (!Array.isArray(content)) continue;
    const text = content
      .map((part) => {
        if (typeof part !== 'object' || part === null) return '';
        const record = part as Record<string, unknown>;
        return record['type'] === 'text' && typeof record['text'] === 'string'
          ? record['text']
          : '';
      })
      .join('\n')
      .trim();
    if (text.length > 0) out.push(text);
  }
  return out;
}

/**
 * Pull an HTTP status code out of a caught provider error. Mirrors
 * `packages/providers/src/retry.ts::extractStatus` intentionally — we don't
 * import from retry.ts to avoid coupling main to a retry-internal helper
 * that might get reshaped. Used by the generate catch block to tag the
 * thrown err with `upstream_status` so the renderer's diagnose pipeline
 * can pick up a hypothesis.
 */
function extractUpstreamHttpStatus(err: unknown): number | undefined {
  if (typeof err !== 'object' || err === null) return undefined;
  const candidates: unknown[] = [
    (err as { status?: unknown }).status,
    (err as { statusCode?: unknown }).statusCode,
    (err as { upstream_status?: unknown }).upstream_status,
    (err as { response?: { status?: unknown } }).response?.status,
  ];
  for (const c of candidates) {
    if (typeof c === 'number' && Number.isFinite(c) && c >= 100 && c < 600) return c;
  }
  if (err instanceof Error) {
    const m = /\b(\d{3})\b/.exec(err.message);
    if (m?.[1]) {
      const n = Number(m[1]);
      if (n >= 400 && n < 600) return n;
    }
  }
  return undefined;
}

function normalizeGenerationFailure(opts: {
  err: unknown;
  signal: AbortSignal;
  provider: string;
  modelId: string;
  baseUrl: string | undefined;
  wire: string | undefined;
}): { error: unknown; upstreamStatus: number | undefined } {
  const upstreamStatus = extractUpstreamHttpStatus(opts.err);
  if (opts.err !== null && typeof opts.err === 'object') {
    const errAsRec = opts.err as Record<string, unknown>;
    if (upstreamStatus !== undefined && errAsRec['upstream_status'] === undefined) {
      errAsRec['upstream_status'] = upstreamStatus;
    }
    if (errAsRec['upstream_provider'] === undefined) {
      errAsRec['upstream_provider'] = opts.provider;
    }
    if (errAsRec['upstream_model_id'] === undefined) {
      errAsRec['upstream_model_id'] = opts.modelId;
    }
    if (errAsRec['upstream_baseurl'] === undefined && opts.baseUrl !== undefined) {
      errAsRec['upstream_baseurl'] = opts.baseUrl;
    }
    if (errAsRec['upstream_wire'] === undefined && opts.wire !== undefined) {
      errAsRec['upstream_wire'] = opts.wire;
    }
  }
  return {
    error: extractGenerationTimeoutError(opts.signal) ?? opts.err,
    upstreamStatus,
  };
}

function resolveApiKeyForActive(providerId: string, allowKeyless: boolean): Promise<string> {
  return resolveCredentialForProvider(providerId, allowKeyless, {
    getApiKeyForProvider,
    hasApiKeyForProvider,
  });
}

export interface RegisterGenerateIpcDeps {
  db: Database | null;
  getMainWindow: () => ElectronBrowserWindow | null;
}

type DesignBriefConversationMessages = Parameters<
  typeof updateDesignSessionBrief
>[0]['conversationMessages'];

/**
 * Registers the agent-loop IPC handlers (generate / apply-comment / title /
 * cancel / detect-provider / done:verify). Returns a teardown closure that
 * aborts every in-flight generation — call from the app `before-quit` hook.
 */
export function registerGenerateIpc({ db, getMainWindow }: RegisterGenerateIpcDeps): () => void {
  const logIpc = getLogger('main:ipc');

  // Cache of the last NormalizedProviderError seen per run, so recordFinalError
  // can attach it to the final (non-transient) row. Without this, the row the
  // user actually reports lacks upstream_request_id / status — those fields
  // lived only on the hidden transient sibling row emitted by retry.ts.
  // Implementation + LRU eviction lives in ../provider-context.ts.
  const providerContext = createProviderContextStore(50);

  const recordFinalError = (scope: string, runId: string, err: unknown): void => {
    if (db === null) return;
    const code = err instanceof CodesignError ? (err.code as string) : 'PROVIDER_UPSTREAM_ERROR';
    const stack = err instanceof Error ? err.stack : undefined;
    const message = err instanceof Error ? err.message : String(err);
    const context = providerContext.consume(runId);
    recordDiagnosticEvent(db, {
      level: 'error',
      code,
      scope,
      runId,
      fingerprint: computeFingerprint({ errorCode: code, stack, message }),
      message,
      stack,
      transient: false,
      ...(context !== undefined ? { context } : {}),
    });
  };

  /** Adapter so `core` can log step events through the same scoped electron-log
   * sink the IPC handler uses. Keeps a single timeline per generation in the
   * log file without forcing `core` to depend on electron-log.
   *
   * Only `provider.error` (retry in flight, transient=true) is persisted from
   * this adapter; the `provider.error.final` event is NOT recorded because the
   * outer handler's catch block calls `recordFinalError` — recording both
   * would double-count the same failure with two distinct fingerprints. */
  const coreLoggerFor = (id: string): CoreLogger => ({
    info: (event, data) => logIpc.info(event, { generationId: id, ...(data ?? {}) }),
    warn: (event, data) => {
      logIpc.warn(event, { generationId: id, ...(data ?? {}) });
      if (event === 'provider.error' && db !== null) {
        const code = 'PROVIDER_UPSTREAM_ERROR';
        const upstream =
          data !== undefined && typeof data['upstream_message'] === 'string'
            ? (data['upstream_message'] as string)
            : event;
        // Fingerprint basis: errorCode + synthetic frame containing the two
        // fields that truly differentiate provider errors — upstream_status
        // and upstream_code. JSON-stringifying `data` and passing it as
        // `stack` would produce an identical 8-hex for every provider error
        // because `extractTopFrames` requires lines starting with "at ".
        const status =
          typeof data?.['upstream_status'] === 'number' ? data['upstream_status'] : '?';
        const upstreamCode =
          typeof data?.['upstream_code'] === 'string' ? data['upstream_code'] : 'unknown';
        const syntheticFrame = `    at provider (${status}:${upstreamCode})`;
        if (data !== undefined) providerContext.remember(id, data);
        recordDiagnosticEvent(db, {
          level: 'warn',
          code,
          scope: 'provider',
          runId: id,
          fingerprint: computeFingerprint({
            errorCode: code,
            stack: syntheticFrame,
            message: upstream,
          }),
          message: upstream,
          stack: undefined,
          transient: true,
          ...(data !== undefined ? { context: data } : {}),
        });
      }
    },
    error: (event, data) => logIpc.error(event, { generationId: id, ...(data ?? {}) }),
  });

  const requireWorkspaceRootForDesign = (
    designId: string | undefined,
  ): { designId: string; workspaceRoot: string } => resolveGenerationWorkspaceRoot(db, designId);

  const chatStoreOptions = (): SessionChatStoreOptions | null => {
    if (db === null) return null;
    return {
      db,
      sessionDir: db.sessionDir,
    };
  };

  const chatRowsForDesign = (designId: string): ReturnType<typeof listSessionChatMessages> => {
    const opts = chatStoreOptions();
    if (opts === null) return [];
    return listSessionChatMessages(opts, designId);
  };

  const briefForDesign = (designId: string): DesignSessionBriefV1 | null => {
    const opts = chatStoreOptions();
    if (opts === null) return null;
    return readSessionDesignBrief(opts, designId);
  };

  const sendHostActivity = (
    event: Omit<AgentStreamEvent, 'type'> & {
      type?: never;
      toolName: string;
      status: 'done' | 'error';
    },
  ): void => {
    getMainWindow()?.webContents.send('agent:event:v1', {
      ...event,
      type: 'tool_call_start',
    } satisfies AgentStreamEvent);
  };

  /**
   * Dispatches a generate request through the agent runtime. Forwards
   * normalized `AgentEvent`s to the renderer via `agent:event:v1` so the
   * sidebar chat can render incremental output.
   */
  const runGenerate = async (
    input: Parameters<typeof generateViaAgent>[0],
    id: string,
    designId: string,
    previousSource: string | null,
    workspaceRoot: string,
    attachmentsForRuntimeFs?: Parameters<typeof createRuntimeTextEditorFs>[0]['attachments'],
    memoryCallbacks?: {
      onAggressivePrune?: () => void;
      onComplete?: (messages: DesignBriefConversationMessages) => void;
    },
  ): ReturnType<typeof generateViaAgent> => {
    const sendEvent = (event: AgentStreamEvent) => {
      getMainWindow()?.webContents.send('agent:event:v1', event);
    };
    const baseCtx = { designId, generationId: id } as const;
    const toolStartedAt = new Map<string, number>();
    const runtimeVerify = makeRuntimeVerifier();
    const templatesRoot = path_module.join(app.getPath('userData'), 'templates');
    const currentWorkspaceRoot = () => requireWorkspaceRootForDesign(designId).workspaceRoot;
    const [frames, designSkills, initialWorkspaceFiles] = await Promise.all([
      loadFrameTemplates(path_module.join(templatesRoot, 'frames')),
      loadDesignSkills(path_module.join(templatesRoot, 'design-skills')),
      withStableWorkspacePath(designId, () => readWorkspaceFilesAt(currentWorkspaceRoot())),
    ]);
    const { fs, fsMap, syncWorkspaceTextFile } = createRuntimeTextEditorFs({
      db,
      designId,
      generationId: id,
      logger: logIpc,
      previousSource,
      initialFiles: initialWorkspaceFiles,
      attachments: attachmentsForRuntimeFs ?? input.attachments,
      sendEvent,
      frames,
      designSkills,
    });
    let deltaCount = 0;
    let turnTextBuffer = '';
    let toolCount = 0;
    const renderUiKit = makeUiKitRenderer();
    const judgeVisualParity = makeJudgeVisualParity(
      async ({ systemPrompt, userText, userImages, maxTokens, signal: judgeSignal }) => {
        const judgeMessages = [
          { role: 'system' as const, content: systemPrompt },
          { role: 'user' as const, content: userText },
        ];
        const judgeOpts: Parameters<typeof complete>[2] = {
          apiKey: input.apiKey ?? '',
          maxTokens,
          userImages,
          ...(input.baseUrl ? { baseUrl: input.baseUrl } : {}),
          ...(input.wire ? { wire: input.wire } : {}),
          ...(input.httpHeaders ? { httpHeaders: input.httpHeaders } : {}),
          ...(judgeSignal ? { signal: judgeSignal } : {}),
        };
        const result = await complete(input.model, judgeMessages, judgeOpts);
        return { content: result.content, costUsd: result.costUsd };
      },
    );

    return generateViaAgent(
      {
        ...input,
        templatesRoot,
        askBridge: (askInput) => requestAsk(id, askInput, () => getMainWindow()),
        workspaceRoot,
        getWorkspaceRoot: currentWorkspaceRoot,
        onScaffolded: async (details) => {
          await syncWorkspaceTextFile(details.destPath, details.written);
        },
        inspectWorkspace: async () =>
          withStableWorkspacePath(designId, async () => {
            const files = await listWorkspaceFilesAt(currentWorkspaceRoot());
            return inspectWorkspaceFiles(files.map((file) => ({ file: file.path })));
          }),
        readWorkspaceFiles: (patterns) =>
          withStableWorkspacePath(designId, () =>
            readWorkspaceFilesAt(currentWorkspaceRoot(), patterns),
          ),
        runPreview: ({ path, vision }) =>
          withStableWorkspacePath(designId, async () =>
            runPreview({ path, vision: await alephPreviewVision({ provider: input.model.provider,
              baseUrl: input.baseUrl, httpHeaders: input.httpHeaders, requested: vision }),
              workspaceRoot: currentWorkspaceRoot() }),
          ),
      },
      {
        fs,
        runtimeVerify,
        renderUiKit,
        judgeVisualParity,
        ...(memoryCallbacks?.onAggressivePrune !== undefined
          ? { onAggressivePrune: memoryCallbacks.onAggressivePrune }
          : {}),
        ...(memoryCallbacks?.onComplete !== undefined
          ? { onComplete: memoryCallbacks.onComplete }
          : {}),
        onEvent: (event: AgentEvent) => {
          if (event.type === 'turn_start') {
            deltaCount = 0;
            turnTextBuffer = '';
            toolCount = 0;
            logIpc.info('agent.turn_start', { generationId: id });
          } else if (event.type === 'message_update') {
            const ame = event.assistantMessageEvent;
            if (ame.type === 'text_delta') {
              deltaCount += 1;
              if (typeof ame.delta === 'string') turnTextBuffer += ame.delta;
            }
          } else if (event.type === 'tool_execution_start') {
            toolCount += 1;
            logIpc.info('agent.tool_start', { generationId: id, tool: event.toolName });
          } else if (event.type === 'tool_execution_end') {
            const streamedResult = summarizeToolResultForStream(event.toolName, event.result);
            const streamStatus = toolExecutionStatusForStream({
              ...event,
              result: streamedResult,
            });
            logIpc.info('agent.tool_end', {
              generationId: id,
              tool: event.toolName,
              isError: streamStatus.status === 'error',
              status: streamStatus.status,
            });
          } else if (event.type === 'turn_end') {
            logIpc.info('agent.turn_end', {
              generationId: id,
              deltas: deltaCount,
              tools: toolCount,
            });
          } else if (event.type === 'agent_end') {
            logIpc.info('agent.end', { generationId: id });
          }
          if (designId === null) return;
          if (event.type === 'turn_start') {
            sendEvent({ ...baseCtx, type: 'turn_start' });
            return;
          }
          if (event.type === 'message_update') {
            const ame = event.assistantMessageEvent;
            if (ame.type === 'text_delta' && typeof ame.delta === 'string') {
              sendEvent({ ...baseCtx, type: 'text_delta', delta: ame.delta });
            }
            return;
          }
          if (event.type === 'tool_execution_start') {
            toolStartedAt.set(event.toolCallId, Date.now());
            const argsObj =
              typeof event.args === 'object' && event.args !== null
                ? (event.args as Record<string, unknown>)
                : {};
            const command =
              typeof argsObj['command'] === 'string' ? (argsObj['command'] as string) : undefined;
            sendEvent({
              ...baseCtx,
              type: 'tool_call_start',
              toolName: event.toolName,
              toolCallId: event.toolCallId,
              args: argsObj,
              ...(command ? { command } : {}),
            });
            return;
          }
          if (event.type === 'tool_execution_end') {
            const startedAt = toolStartedAt.get(event.toolCallId) ?? Date.now();
            toolStartedAt.delete(event.toolCallId);
            const streamedResult = summarizeToolResultForStream(event.toolName, event.result);
            const streamStatus = toolExecutionStatusForStream({
              ...event,
              result: streamedResult,
            });
            sendEvent({
              ...baseCtx,
              type: 'tool_call_result',
              toolName: event.toolName,
              toolCallId: event.toolCallId,
              result: streamedResult,
              durationMs: Date.now() - startedAt,
              status: streamStatus.status,
              ...(streamStatus.errorMessage !== undefined
                ? { message: streamStatus.errorMessage }
                : {}),
            });
            return;
          }
          if (event.type === 'turn_end') {
            const msg = event.message as { content?: Array<{ type: string; text?: string }> };
            const rawText = (msg.content ?? [])
              .filter(
                (c): c is { type: 'text'; text: string } =>
                  c.type === 'text' && typeof c.text === 'string',
              )
              .map((c) => c.text)
              .join('');
            // Strip <artifact ...>...</artifact> blocks — artifact content is
            // delivered via fs_updated / artifact_delivered, not the chat text.
            // The second pattern catches the cancel-mid-stream case where only
            // the opening tag has landed.
            const finalText = finalAssistantTextForTurn(rawText, turnTextBuffer);
            sendEvent({ ...baseCtx, type: 'turn_end', finalText });
            return;
          }
          if (event.type === 'agent_end') {
            sendEvent({ ...baseCtx, type: 'agent_end' });
            return;
          }
        },
      },
    ).then((result) => ({
      ...result,
      artifacts: result.artifacts.map((artifact) => ({
        ...artifact,
        content: resolveLocalAssetRefs(artifact.content, fsMap),
      })),
    }));
  };

  /** In-flight requests: generationId → AbortController */
  const inFlight = new Map<string, AbortController>();
  const inFlightByDesign = new Map<string, { generationId: string; startedAt: number }>();
  const inFlightByWorkspace = new Map<string, { generationId: string; startedAt: number }>();
  // EL TRABAJO SUELTO DE UN TURNO QUE YA CONTESTÓ.
  //
  // La memoria del workspace y el brief arrancan al terminar el turno y NO se esperan:
  // su salida alimenta al turno siguiente, así que cortarlas en el cierre normal
  // degradaría la conversación en silencio. Pero siguen pidiéndole al cerebro después de
  // que el usuario recibió su respuesta — medido: `[workspace-memory] summarize.fail
  // ms: 159923`, dos minutos y medio de una sola llamada.
  //
  // `inFlight` no sirve para alcanzarlas: su `finally` borra el controller cuando el
  // cuerpo del handler devuelve, que es ANTES de que estas terminen. Así que el
  // `before-quit` recorría un mapa vacío y no abortaba nada; lo único que las paraba era
  // la muerte del proceso. Este mapa las mantiene alcanzables hasta que se apagan solas.
  //
  // POR QUÉ NO VAN EN `inFlightByDesign`, que sería lo obvio: ese mapa es el CANDADO del
  // diseño (`withInFlightGenerationForDesign` rechaza con `GENERATION_ALREADY_RUNNING` un
  // segundo turno sobre el mismo diseño mientras tenga entrada). Meter ahí el trabajo
  // suelto dejaría el compositor bloqueado hasta que termine la memoria — medido: hasta
  // 160 s. Cambiaría «invisible» por «no podés escribir», que es peor. Por eso viajan por
  // su propio campo en `generation-status`: visibles para quien mide, sin tomar el candado.
  const sueltos = new Map<
    string,
    { controller: AbortController; designId: string; generationId: string; startedAt: number }
  >();

  const armTimeout = (id: string, controller: AbortController) =>
    armGenerationTimeout(
      id,
      controller,
      async () => (await readPreferences()).generationTimeoutSec,
      logIpc,
    );

  ipcMain.handle('codesign:detect-provider', (_e, key: unknown) => {
    if (typeof key !== 'string') {
      throw new CodesignError('detect-provider expects a string key', 'IPC_BAD_INPUT');
    }
    return detectProviderFromKey(key);
  });

  // Standalone runtime-verify IPC. Renderer / debug callers can invoke this
  // directly to dry-run an artifact without going through the agent loop.
  const sharedRuntimeVerifier = makeRuntimeVerifier();
  ipcMain.handle('done:verify:v1', async (_e, raw: unknown) => {
    if (
      typeof raw !== 'object' ||
      raw === null ||
      typeof (raw as { artifact?: unknown }).artifact !== 'string'
    ) {
      throw new CodesignError('done:verify:v1 expects { artifact: string }', 'IPC_BAD_INPUT');
    }
    const errors = await sharedRuntimeVerifier((raw as { artifact: string }).artifact);
    return { errors };
  });

  ipcMain.handle('codesign:v1:generate', async (_e, raw: unknown) => {
    const payload = GeneratePayloadV1.parse(raw);
    const id = payload.generationId;
    return withRun(id, async () => {
      const controller = new AbortController();
      return withInFlightGenerationForDesign(
        id,
        payload.designId,
        inFlight,
        inFlightByDesign,
        controller,
        async () => {
          const coreLogger = coreLoggerFor(id);

          coreLogger.info('[generate] step=load_config');
          const loadStart = Date.now();
          const cfg = getCachedConfig();
          if (cfg === null) {
            throw new CodesignError(
              'No configuration found. Complete onboarding first.',
              'CONFIG_MISSING',
            );
          }
          const active = resolveActiveModel(cfg, payload.model);
          const allowKeyless = active.allowKeyless;
          const apiKey = await resolveApiKeyForActive(active.model.provider, allowKeyless);
          // Once we've snapped to the canonical active provider, the renderer-supplied
          // baseUrl can no longer be trusted — it may belong to a different (stale)
          // provider. Always use the per-provider baseUrl from cached config.
          const baseUrl = active.baseUrl ?? undefined;
          if (active.overridden) {
            payload.baseUrl = baseUrl;
          }
          coreLogger.info('[generate] step=load_config.ok', {
            ms: Date.now() - loadStart,
            hasApiKey: apiKey.length > 0,
            baseUrl: baseUrl ?? '<default>',
          });

          if (active.overridden) {
            coreLogger.info('[generate] step=resolve_active.override', {
              requested: payload.model.provider,
              requestedModelId: payload.model.modelId,
              active: active.model.provider,
              activeModelId: active.model.modelId,
            });
          }

          const stepCtx = {
            generationId: id,
            provider: active.model.provider,
            modelId: active.model.modelId,
          };
          coreLogger.info('[generate] step=validate_provider', stepCtx);
          if (apiKey.length === 0 && !allowKeyless) {
            coreLogger.error('[generate] step=validate_provider.fail', {
              provider: active.model.provider,
              reason: 'missing_api_key',
            });
            throw new CodesignError(
              `No API key configured for provider "${active.model.provider}". Open Settings to add one.`,
              'PROVIDER_AUTH_MISSING',
            );
          }
          coreLogger.info('[generate] step=validate_provider.ok', {
            provider: active.model.provider,
          });
          const tlsBypass = resolveTlsBypassFor(cfg, active.model.provider);

          const prefs = await readPreferences();
          const { designId, workspaceRoot, promptContext, memoryContext, memoryLoadWarning } =
            await withStableWorkspacePath(payload.designId, async () => {
              const { designId, workspaceRoot } = requireWorkspaceRootForDesign(payload.designId);
              const promptContext = await preparePromptContext({
                attachments: payload.attachments,
                referenceUrl: payload.referenceUrl,
                designSystem: cfg.designSystem ?? null,
                workspaceRoot,
              });
              let memoryContext: Awaited<ReturnType<typeof loadMemoryContext>> | undefined;
              let memoryLoadWarning: string | undefined;
              if (prefs.memoryEnabled) {
                try {
                  memoryContext = await loadMemoryContext(workspaceRoot);
                } catch (err) {
                  memoryLoadWarning = `Project memory unavailable: ${err instanceof Error ? err.message : String(err)}`;
                  logIpc.warn('memory.load.fail', {
                    generationId: id,
                    message: err instanceof Error ? err.message : String(err),
                  });
                }
              }
              return { designId, workspaceRoot, promptContext, memoryContext, memoryLoadWarning };
            });
          const currentDesignName =
            db !== null ? (getDesign(db, designId)?.name ?? undefined) : undefined;

          logIpc.info('generate', {
            generationId: id,
            provider: active.model.provider,
            modelId: active.model.modelId,
            ...(active.overridden
              ? {
                  requestedProvider: payload.model.provider,
                  requestedModelId: payload.model.modelId,
                }
              : {}),
            promptLen: payload.prompt.length,
            historyLen: payload.history.length,
            attachmentCount: payload.attachments.length,
            hasReferenceUrl: payload.referenceUrl !== undefined,
            hasDesignSystem: promptContext.designSystem !== null,
            baseUrl: baseUrl ?? '<default>',
          });

          const t0 = Date.now();
          let clearTimeoutGuard: () => void = () => {};
          let releaseWorkspaceGeneration: () => void = () => {};
          try {
            releaseWorkspaceGeneration = acquireInFlightWorkspaceGeneration(
              id,
              workspaceRoot,
              inFlightByWorkspace,
            );
            clearTimeoutGuard = await armTimeout(id, controller);
            let capturedMessages: DesignBriefConversationMessages | null = null;
            let aggressivePruneDetected = false;
            const rawChatRows = chatRowsForDesign(designId);
            const chatRows = dropCurrentPromptEchoFromChatRows(rawChatRows, payload.prompt);
            if (chatRows.length !== rawChatRows.length) {
              logIpc.info('generate.current_prompt_echo.drop', {
                generationId: id,
                designId,
                rawRows: rawChatRows.length,
                planningRows: chatRows.length,
              });
            }
            const resourceState = deriveResourceStateFromChatRows(chatRows);
            const existingBrief = prefs.memoryEnabled ? briefForDesign(designId) : null;
            const runPreferenceStoreOptions = chatStoreOptions();
            const existingRunPreferences =
              runPreferenceStoreOptions !== null
                ? readSessionRunPreferences(runPreferenceStoreOptions, designId)
                : null;
            const workspaceState = {
              sourcePath: payload.previousSource ? 'App.jsx' : null,
              hasSource: Boolean(payload.previousSource?.trim()),
              hasDesignMd: Boolean(promptContext.projectContext.designMd?.trim()),
              hasAgentsMd: Boolean(promptContext.projectContext.agentsMd?.trim()),
              hasSettingsJson: Boolean(promptContext.projectContext.settingsJson?.trim()),
              attachmentCount: promptContext.attachments.length,
              imageAttachmentCount: promptContext.attachments.filter((file) =>
                file.mediaType?.startsWith('image/'),
              ).length,
              hasReferenceUrl: promptContext.referenceUrl !== null,
              hasDesignSystem: promptContext.designSystem !== null,
            };
            const rutear = (): Promise<Awaited<ReturnType<typeof routeRunPreferences>>> =>
              withTlsBypass(tlsBypass, () =>
                routeRunPreferences({
                  prompt: payload.prompt,
                  existingPreferences: existingRunPreferences,
                  recentHistory: recentHistoryForRunPreferenceRouter(chatRows),
                  workspaceState,
                  designBrief: existingBrief ? JSON.stringify(existingBrief) : null,
                  userMemory: memoryContext?.userMemory?.content ?? null,
                  workspaceMemory: memoryContext?.workspaceMemory?.content ?? null,
                  model: active.model,
                  apiKey,
                  ...(baseUrl !== undefined ? { baseUrl } : {}),
                  wire: active.wire,
                  ...(active.httpHeaders !== undefined
                    ? { httpHeaders: active.httpHeaders }
                    : {}),
                  ...(active.reasoningLevel !== undefined
                    ? { reasoningLevel: active.reasoningLevel }
                    : {}),
                  ...(allowKeyless ? { allowKeyless: true } : {}),
                  // Parar el turno para TODAS sus llamadas, no sólo la del agente.
                  signal: controller.signal,
                  logger: coreLogger,
                }),
              );

            // EL ROUTER SE ESPERA SÓLO LA PRIMERA VEZ.
            //
            // Es una llamada al modelo, y el turno la espera: medido entre `generate` y
            // `generate.context`, 8,1-8,8 s de los 16,1 s que el usuario aguarda — el 46 %.
            // Con el mismo prompt y el mismo cerebro, Ciencia (que no tiene este paso)
            // contesta en 9,4 s.
            //
            // QUÉ DECIDE, Y POR QUÉ SE PUEDE DIFERIR. Devuelve tres modos
            // (`tweaks`/`bitmapAssets`/`reusableSystem`), una dirección visual opcional, y
            // si conviene preguntarle algo al usuario. MEDIDO sobre 35 llamadas en dos
            // diseños, con prompts de todos los tamaños: 17/17 y 18/18 valores IDÉNTICOS
            // dentro de cada diseño, `visualDirection` null las 35 veces, y procedencia
            // `default`/`inferred` — nunca `explicit`. El valor se fija en el primer turno
            // del diseño y no se movió más. Los dos diseños SÍ difieren entre sí, así que
            // no es una constante global: es una decisión por diseño que ya está tomada.
            //
            // ⚠️ EL LÍMITE DE ESE DATO, y hay que decirlo: prueba que no aportó para esos
            // prompts, no que no aporte nunca. Por eso el router no se borra ni se saltea:
            // se corre igual, sólo que sin que nadie lo espere. Si un prompt mueve una
            // preferencia, la mueve para el turno SIGUIENTE — ése es el costo, y es el
            // motivo por el que el primer turno de un diseño lo sigue esperando: ahí es
            // donde el valor todavía no existe y hay que establecerlo.
            //
            // NO SE INVENTA UN MECANISMO NUEVO. El respaldo ya existe —el propio
            // `routeRunPreferences` cae a `existingPreferences ?? defaults` cuando falla, y
            // lo vi funcionar en un turno largo real— y la forma de soltar trabajo sin
            // esperarlo también: `ensureTitle` de Ciencia (`prompt.ts:457`, disparado en
            // `step === 1`, sin `await`).
            const routedPreferences =
              existingRunPreferences === null
                ? await rutear()
                : {
                    preferences: existingRunPreferences,
                    // Sin resultado fresco no se le pregunta nada al usuario: preguntar con
                    // el análisis del turno anterior sería inventar una duda que nadie tuvo.
                    needsClarification: false,
                  };
            if (existingRunPreferences !== null) {
              // TRABAJO SUELTO ES TRABAJO SUELTO: entra al mismo registro que la memoria y
              // el brief, para no crear otra auxiliar invisible — que es justo lo que la
              // obra anterior arregló. Clave propia (`#router`) porque el trabajo de
              // después del turno usa `id` y se pisarían: el que terminara primero borraría
              // al otro del ledger.
              const claveRouter = `${id}#router`;
              sueltos.set(claveRouter, { controller, designId, generationId: id, startedAt: Date.now() });
              void rutear()
                .then((fresco) => {
                  // UN RESULTADO ABORTADO NO ES UN RESULTADO, Y ACÁ NO SE NOTABA.
                  //
                  // `routeRunPreferences` se traga cualquier fallo y devuelve el respaldo
                  // (`run-preferences.ts:338`), así que un abort le llega a este `.then`
                  // con la MISMA forma que un acierto. Sin este chequeo, parar el turno
                  // hacía que el refresco persistiera las preferencias de respaldo como si
                  // fueran frescas, y lo anotara `refresh.ok`.
                  //
                  // MEDIDO: cancelando a los 2,0 s —con el router, que tarda ~7 s, todavía
                  // en vuelo— el refresco terminaba en ese mismo instante y escribía
                  // `refresh.ok`. La señal SÍ lo alcanzaba; lo que mentía era el registro.
                  if (controller.signal.aborted) {
                    logIpc.info('run-preferences.refresh.abortado', { generationId: id });
                    return;
                  }
                  if (runPreferenceStoreOptions !== null) {
                    appendSessionRunPreferences(
                      runPreferenceStoreOptions,
                      designId,
                      fresco.preferences,
                    );
                  }
                  logIpc.info('run-preferences.refresh.ok', { generationId: id });
                })
                .catch((err) => {
                  logIpc.warn('run-preferences.refresh.fail', {
                    generationId: id,
                    message: err instanceof Error ? err.message : String(err),
                  });
                })
                .finally(() => {
                  sueltos.delete(claveRouter);
                });
            }
            let runPreferences = routedPreferences.preferences;
            const runProtocolPreflight = buildRunProtocolPreflight({
              prompt: payload.prompt,
              historyCount: chatRows.filter((row) => row.kind === 'user').length,
              workspaceState: { hasSource: Boolean(payload.previousSource?.trim()) },
              runPreferences,
              routerQuestions: routedPreferences.needsClarification
                ? routedPreferences.clarificationQuestions
                : undefined,
              attachmentCount: promptContext.attachments.length,
              hasReferenceUrl: promptContext.referenceUrl !== null,
              hasDesignSystem: promptContext.designSystem !== null,
            });
            let preflightAnswers: Array<{
              questionId: string;
              value: string | number | string[] | null;
            }> = [];
            if (runProtocolPreflight.requiresClarification) {
              const askInput = buildRunPreferenceAskInput(
                runProtocolPreflight.clarificationQuestions,
                routedPreferences.clarificationRationale,
              );
              const toolCallId = `host-preflight-ask-${id}`;
              const askStartedAt = Date.now();
              sendPreflightAskEvent(getMainWindow, {
                designId,
                generationId: id,
                type: 'turn_start',
              });
              logIpc.info('agent.tool_start', {
                generationId: id,
                tool: 'ask',
                source: 'preflight',
              });
              sendPreflightAskEvent(getMainWindow, {
                designId,
                generationId: id,
                type: 'tool_call_start',
                toolName: 'ask',
                toolCallId,
                args: { questions: askInput.questions, rationale: askInput.rationale },
                verbGroup: 'Clarifying',
              });
              try {
                const askResult = await requestAsk(id, askInput, () => getMainWindow());
                preflightAnswers = askResult.status === 'answered' ? askResult.answers : [];
                runPreferences = applyRunPreferenceAnswers(runPreferences, preflightAnswers);
                logIpc.info('agent.tool_end', {
                  generationId: id,
                  tool: 'ask',
                  source: 'preflight',
                  status: 'done',
                  answers: preflightAnswers.length,
                });
                sendPreflightAskEvent(getMainWindow, {
                  designId,
                  generationId: id,
                  type: 'tool_call_result',
                  toolName: 'ask',
                  toolCallId,
                  durationMs: Date.now() - askStartedAt,
                  status: 'done',
                  result: {
                    content: [
                      {
                        type: 'text',
                        text:
                          askResult.status === 'answered'
                            ? `user answered ${preflightAnswers.length} question(s)`
                            : 'user cancelled',
                      },
                    ],
                    details: { status: askResult.status, answerCount: preflightAnswers.length },
                  },
                });
              } catch (err) {
                const message = err instanceof Error ? err.message : String(err);
                logIpc.warn('agent.tool_end', {
                  generationId: id,
                  tool: 'ask',
                  source: 'preflight',
                  status: 'error',
                  message,
                });
                sendPreflightAskEvent(getMainWindow, {
                  designId,
                  generationId: id,
                  type: 'tool_call_result',
                  toolName: 'ask',
                  toolCallId,
                  durationMs: Date.now() - askStartedAt,
                  status: 'error',
                  message,
                });
                throw err;
              }
            }
            // Sólo persiste el turno que las CALCULÓ. En los turnos 2+ este valor es el que
            // acabamos de leer del disco, y el refresco suelto va a escribir el fresco unos
            // segundos después: dejar los dos escribiendo es una carrera cuyo perdedor
            // silencioso sería el refresco, y la obra parecería hecha sin estarlo.
            if (runPreferenceStoreOptions !== null && existingRunPreferences === null) {
              appendSessionRunPreferences(runPreferenceStoreOptions, designId, runPreferences);
            }
            const contextPack = buildDesignContextPack({
              chatRows,
              brief: existingBrief,
              runPreferences,
              resourceState,
              modelContextWindow: contextWindowForContextPack(active.model),
              workspaceState: {
                sourcePath: payload.previousSource ? 'App.jsx' : null,
                hasSource: Boolean(payload.previousSource?.trim()),
                hasDesignMd: Boolean(promptContext.projectContext.designMd?.trim()),
                hasAgentsMd: Boolean(promptContext.projectContext.agentsMd?.trim()),
                hasSettingsJson: Boolean(promptContext.projectContext.settingsJson?.trim()),
              },
            });
            logIpc.info('generate.context', {
              generationId: id,
              ...contextPack.trace,
            });
            const result = await withTlsBypass(tlsBypass, () =>
              runGenerate(
                {
                  prompt: payload.prompt,
                  history: contextPack.history,
                  model: active.model,
                  apiKey,
                  attachments: promptContext.attachments,
                  referenceUrl: promptContext.referenceUrl,
                  designSystem: promptContext.designSystem ?? null,
                  sessionContext: [
                    ...contextPack.contextSections,
                    ...formatRunProtocolPreflightAnswers(preflightAnswers),
                  ],
                  ...(memoryContext !== undefined ? { memoryContext: memoryContext.sections } : {}),
                  projectContext: promptContext.projectContext,
                  currentDesignName,
                  initialResourceState: resourceState,
                  runPreferences,
                  ...(baseUrl !== undefined ? { baseUrl } : {}),
                  wire: active.wire,
                  ...(active.httpHeaders !== undefined ? { httpHeaders: active.httpHeaders } : {}),
                  ...(active.reasoningLevel !== undefined
                    ? { reasoningLevel: active.reasoningLevel }
                    : {}),
                  ...(allowKeyless ? { allowKeyless: true } : {}),
                  signal: controller.signal,
                  logger: coreLogger,
                },
                id,
                designId,
                payload.previousSource ?? null,
                workspaceRoot,
                promptContext.attachments,
                {
                  onAggressivePrune: () => {
                    aggressivePruneDetected = true;
                  },
                  onComplete: (messages) => {
                    capturedMessages = messages;
                  },
                },
              ),
            );
            logIpc.info('generate.ok', {
              generationId: id,
              ms: Date.now() - t0,
              artifacts: result.artifacts.length,
              cost: result.costUsd,
            });
            if (capturedMessages !== null) {
              const messagesForMemory = capturedMessages;
              const design = db !== null ? getDesign(db, designId) : null;
              let memoryWorkspaceRoot = workspaceRoot;
              try {
                memoryWorkspaceRoot = requireWorkspaceRootForDesign(designId).workspaceRoot;
              } catch (err) {
                logIpc.warn('memory.workspace.resolve.fail', {
                  generationId: id,
                  message: err instanceof Error ? err.message : String(err),
                });
              }
              const designName = design?.name ?? 'Untitled';
              const previousWorkspaceMemoryHash = memoryContext?.workspaceMemory?.hash ?? null;
              const workspaceMemoryUpdate =
                prefs.memoryEnabled === true && prefs.workspaceMemoryAutoUpdate === true
                  ? (() => {
                      const startedAt = Date.now();
                      return withTlsBypass(tlsBypass, () =>
                        triggerWorkspaceMemoryUpdate({
                          workspacePath: memoryWorkspaceRoot,
                          workspaceName: workspaceNameFromPath(memoryWorkspaceRoot),
                          designId,
                          designName,
                          conversationMessages: messagesForMemory,
                          userMemory: memoryContext?.userMemory?.content ?? null,
                          designMdSummary: designMdSummaryForMemory(promptContext.projectContext),
                          model: active.model,
                          apiKey,
                          ...(baseUrl !== undefined ? { baseUrl } : {}),
                          wire: active.wire,
                          ...(active.httpHeaders !== undefined
                            ? { httpHeaders: active.httpHeaders }
                            : {}),
                          ...(active.reasoningLevel !== undefined
                            ? { reasoningLevel: active.reasoningLevel }
                            : {}),
                          ...(allowKeyless ? { allowKeyless: true } : {}),
                          // Corre suelta DESPUÉS del turno a propósito —su salida
                          // alimenta al turno siguiente— pero sigue siendo del turno:
                          // si alguien lo para, para con él.
                          signal: controller.signal,
                        }),
                      )
                        .then((workspaceMemory) => {
                          if (
                            workspaceMemory !== null &&
                            workspaceMemory.hash !== previousWorkspaceMemoryHash
                          ) {
                            const command =
                              previousWorkspaceMemoryHash === null ? 'create' : 'update';
                            sendHostActivity({
                              designId,
                              generationId: id,
                              toolName: 'workspace_memory',
                              command,
                              args: { path: 'MEMORY.md' },
                              status: 'done',
                              durationMs: Date.now() - startedAt,
                              verbGroup: 'Memory',
                              result: {
                                content: [
                                  {
                                    type: 'text',
                                    text: `${command === 'create' ? 'Created' : 'Updated'} workspace memory at MEMORY.md.`,
                                  },
                                ],
                                details: {
                                  path: 'MEMORY.md',
                                  bytes: workspaceMemory.content.length,
                                  source: workspaceMemory.source,
                                  status: command === 'create' ? 'created' : 'updated',
                                },
                              },
                            });
                          }
                          return workspaceMemory;
                        })
                        .catch((err) => {
                          const message = err instanceof Error ? err.message : String(err);
                          sendHostActivity({
                            designId,
                            generationId: id,
                            toolName: 'workspace_memory',
                            command: 'update',
                            args: { path: 'MEMORY.md' },
                            status: 'error',
                            durationMs: Date.now() - startedAt,
                            verbGroup: 'Memory',
                            message,
                            result: {
                              content: [{ type: 'text', text: message }],
                              details: { path: 'MEMORY.md', status: 'error' },
                            },
                          });
                          throw err;
                        });
                    })().catch((err) => {
                      logIpc.warn('workspace-memory.update.fail', {
                        generationId: id,
                        message: err instanceof Error ? err.message : String(err),
                      });
                      return memoryContext?.workspaceMemory ?? null;
                    })
                  : Promise.resolve(memoryContext?.workspaceMemory ?? null);

              const briefUpdate = prefs.memoryEnabled
                ? workspaceMemoryUpdate
                    .then((workspaceMemory) =>
                      withTlsBypass(tlsBypass, () =>
                        updateDesignSessionBrief({
                          existingBrief,
                          conversationMessages: messagesForMemory,
                          designId,
                          designName,
                          userMemory: memoryContext?.userMemory?.content ?? null,
                          workspaceMemory: workspaceMemory?.content ?? null,
                          sourceUserMemoryHash: memoryContext?.userMemory?.hash,
                          sourceWorkspaceMemoryHash: workspaceMemory?.hash,
                          sourceMemoryUpdatedAt:
                            workspaceMemory?.updatedAt ?? memoryContext?.userMemory?.updatedAt,
                          model: active.model,
                          apiKey,
                          ...(baseUrl !== undefined ? { baseUrl } : {}),
                          wire: active.wire,
                          ...(active.httpHeaders !== undefined
                            ? { httpHeaders: active.httpHeaders }
                            : {}),
                          ...(active.reasoningLevel !== undefined
                            ? { reasoningLevel: active.reasoningLevel }
                            : {}),
                          ...(allowKeyless ? { allowKeyless: true } : {}),
                          signal: controller.signal,
                        }),
                      ),
                    )
                    .then((briefResult) => {
                      const opts = chatStoreOptions();
                      if (opts !== null)
                        appendSessionDesignBrief(opts, designId, briefResult.brief);
                      logIpc.info('design-brief.update.ok', {
                        generationId: id,
                        outputLen: JSON.stringify(briefResult.brief).length,
                      });
                    })
                    .catch((err) => {
                      logIpc.warn('design-brief.update.fail', {
                        generationId: id,
                        message: err instanceof Error ? err.message : String(err),
                      });
                    })
                : Promise.resolve();
              const userMemoryMaintenance = shouldRunUserMemoryCandidateCapture(prefs)
                ? triggerUserMemoryCandidateCapture({
                    designId,
                    designName,
                    userMessages: extractUserMessagesForMemory(messagesForMemory),
                  })
                    .then(() => {
                      return withTlsBypass(tlsBypass, () =>
                        triggerUserMemoryConsolidation({
                          model: active.model,
                          apiKey,
                          ...(baseUrl !== undefined ? { baseUrl } : {}),
                          wire: active.wire,
                          ...(active.httpHeaders !== undefined
                            ? { httpHeaders: active.httpHeaders }
                            : {}),
                          ...(active.reasoningLevel !== undefined
                            ? { reasoningLevel: active.reasoningLevel }
                            : {}),
                          ...(allowKeyless ? { allowKeyless: true } : {}),
                          signal: controller.signal,
                        }),
                      );
                    })
                    .catch((err) => {
                      logIpc.warn('user-memory.maintenance.fail', {
                        generationId: id,
                        message: err instanceof Error ? err.message : String(err),
                      });
                    })
                : Promise.resolve();
              // Alcanzables hasta que se apaguen solas. No cambia a quién se espera:
              // esto sólo las deja registradas para que el `before-quit` las aborte y
              // para que `generation-status` no diga que no hay nada corriendo.
              // `allSettled` resuelve en los DOS caminos —terminaron o fallaron—, así que
              // la entrada sale también en el camino feliz y el mapa no crece.
              sueltos.set(id, { controller, designId, generationId: id, startedAt: t0 });
              void Promise.allSettled([briefUpdate, userMemoryMaintenance]).then(() => {
                sueltos.delete(id);
              });
              if (aggressivePruneDetected) {
                await Promise.all([briefUpdate, userMemoryMaintenance]);
              }
            }
            if (memoryLoadWarning !== undefined) {
              return {
                ...result,
                warnings: [...(result.warnings ?? []), memoryLoadWarning],
              };
            }
            return result;
          } catch (err) {
            // Attach upstream metadata so the renderer's diagnostic pipeline can
            // map this failure to a hypothesis (status, baseUrl, wire, provider).
            const failure = normalizeGenerationFailure({
              err,
              signal: controller.signal,
              provider: active.model.provider,
              modelId: active.model.modelId,
              baseUrl,
              wire: active.wire,
            });
            const rethrow = failure.error;
            logIpc.error('generate.fail', {
              generationId: id,
              ms: Date.now() - t0,
              provider: active.model.provider,
              modelId: active.model.modelId,
              baseUrl: baseUrl ?? '<default>',
              status: failure.upstreamStatus,
              message: rethrow instanceof Error ? rethrow.message : String(rethrow),
              code: rethrow instanceof CodesignError ? rethrow.code : undefined,
            });
            recordFinalError('generate', id, rethrow);
            throw rethrow;
          } finally {
            clearTimeoutGuard();
            releaseWorkspaceGeneration();
          }
        },
      );
    });
  });

  ipcMain.handle('codesign:v1:cancel-generation', (_e, raw: unknown) => {
    const { generationId } = CancelGenerationPayloadV1.parse(raw);
    cancelGenerationRequest(generationId, inFlight, logIpc, inFlightByDesign, inFlightByWorkspace);
  });

  ipcMain.handle('codesign:v1:generation-status', () => ({
    schemaVersion: 1 as const,
    running: listInFlightGenerations(inFlightByDesign),
    // EL TRABAJO SUELTO DE TURNOS QUE YA CONTESTARON. Va en su propio campo y no dentro
    // de `running` a propósito: `running` es «hay un turno en curso» y lo usa el frente
    // para reconciliar su estado. Lo que sigue pidiéndole al cerebro después de contestar
    // no es un turno en curso, pero tampoco es nada — y decir `running: []` mientras pasa
    // es lo que ensució una medición de esta misma auditoría.
    // El id que viaja es el DEL TURNO, no la clave interna del mapa: un turno puede tener
    // más de un trabajo suelto (el router y la memoria) y la clave los distingue adentro,
    // pero afuera lo que importa es de qué turno son. La prueba encontró que se estaba
    // filtrando `gen-x#router` al payload.
    trailing: [...sueltos.values()]
      .map((s) => ({
        designId: s.designId,
        generationId: s.generationId,
        startedAt: s.startedAt,
      }))
      .sort((a, b) => a.generationId.localeCompare(b.generationId)),
  }));

  ipcMain.handle('codesign:apply-comment', async (_e, raw: unknown) => {
    const payload = ApplyCommentPayload.parse(raw);
    const id = payload.generationId;
    return withRun(id, async () => {
      const controller = new AbortController();
      return withInFlightGenerationForDesign(
        id,
        payload.designId,
        inFlight,
        inFlightByDesign,
        controller,
        async () => {
          const coreLogger = coreLoggerFor(id);

          const cfg = getCachedConfig();
          if (cfg === null) {
            throw new CodesignError(
              'No configuration found. Complete onboarding first.',
              'CONFIG_MISSING',
            );
          }
          // Inline-comment edits don't need to be tied to whatever provider was
          // pinned in the original generate; resolve fresh against the canonical
          // active provider so a switch in Settings takes effect immediately.
          const hint = payload.model ?? { provider: cfg.provider, modelId: cfg.modelPrimary };
          const active = resolveActiveModel(cfg, hint);
          const allowKeyless = active.allowKeyless;
          const apiKey = await resolveApiKeyForActive(active.model.provider, allowKeyless);
          const baseUrl = active.baseUrl ?? undefined;
          const tlsBypass = resolveTlsBypassFor(cfg, active.model.provider);

          const { workspaceRoot, promptContext } = await withStableWorkspacePath(
            payload.designId,
            async () => {
              const { workspaceRoot } = requireWorkspaceRootForDesign(payload.designId);
              const promptContext = await preparePromptContext({
                attachments: payload.attachments,
                referenceUrl: payload.referenceUrl,
                designSystem: cfg.designSystem ?? null,
                workspaceRoot,
              });
              return { workspaceRoot, promptContext };
            },
          );

          logIpc.info('applyComment', {
            generationId: id,
            designId: payload.designId,
            provider: active.model.provider,
            modelId: active.model.modelId,
            ...(active.overridden
              ? { requestedProvider: hint.provider, requestedModelId: hint.modelId }
              : {}),
            selector: payload.selection.selector,
            attachmentCount: payload.attachments.length,
            hasReferenceUrl: payload.referenceUrl !== undefined,
            hasDesignSystem: promptContext.designSystem !== null,
            baseUrl: baseUrl ?? '<default>',
          });

          const systemPrompt = composeSystemPrompt({ mode: 'revise' });
          const userPrompt = buildApplyCommentUserPrompt({
            comment: payload.comment,
            selection: payload.selection,
          });

          const t0 = Date.now();
          let clearTimeoutGuard: () => void = () => {};
          let releaseWorkspaceGeneration: () => void = () => {};
          try {
            releaseWorkspaceGeneration = acquireInFlightWorkspaceGeneration(
              id,
              workspaceRoot,
              inFlightByWorkspace,
            );
            clearTimeoutGuard = await armTimeout(id, controller);
            const result = await withTlsBypass(tlsBypass, () =>
              runGenerate(
                {
                  prompt: userPrompt,
                  systemPrompt,
                  history: [],
                  model: active.model,
                  apiKey,
                  attachments: promptContext.attachments,
                  referenceUrl: promptContext.referenceUrl,
                  designSystem: promptContext.designSystem ?? null,
                  projectContext: promptContext.projectContext,
                  initialResourceState: deriveResourceStateFromChatRows(
                    chatRowsForDesign(payload.designId),
                  ),
                  ...(baseUrl !== undefined ? { baseUrl } : {}),
                  wire: active.wire,
                  ...(active.httpHeaders !== undefined ? { httpHeaders: active.httpHeaders } : {}),
                  ...(active.reasoningLevel !== undefined
                    ? { reasoningLevel: active.reasoningLevel }
                    : {}),
                  ...(allowKeyless ? { allowKeyless: true } : {}),
                  signal: controller.signal,
                  logger: coreLogger,
                },
                id,
                payload.designId,
                payload.artifactSource,
                workspaceRoot,
                promptContext.attachments,
              ),
            );
            logIpc.info('applyComment.ok', {
              generationId: id,
              ms: Date.now() - t0,
              artifacts: result.artifacts.length,
              cost: result.costUsd,
            });
            return result;
          } catch (err) {
            const failure = normalizeGenerationFailure({
              err,
              signal: controller.signal,
              provider: active.model.provider,
              modelId: active.model.modelId,
              baseUrl,
              wire: active.wire,
            });
            const rethrow = failure.error;
            logIpc.error('applyComment.fail', {
              generationId: id,
              ms: Date.now() - t0,
              provider: active.model.provider,
              modelId: active.model.modelId,
              baseUrl: baseUrl ?? '<default>',
              status: failure.upstreamStatus,
              selector: payload.selection.selector,
              message: rethrow instanceof Error ? rethrow.message : String(rethrow),
              code: rethrow instanceof CodesignError ? rethrow.code : undefined,
            });
            recordFinalError('apply-comment', id, rethrow);
            throw rethrow;
          } finally {
            clearTimeoutGuard();
            releaseWorkspaceGeneration();
          }
        },
      );
    });
  });

  ipcMain.handle('codesign:v1:generate-title', async (_e, raw: unknown): Promise<string> => {
    const runId = crypto.randomUUID();
    return withRun(runId, async () => {
      if (typeof raw !== 'object' || raw === null) {
        throw new CodesignError('generate-title expects an object payload', 'IPC_BAD_INPUT');
      }
      const prompt = (raw as { prompt?: unknown }).prompt;
      if (typeof prompt !== 'string' || prompt.trim().length === 0) {
        throw new CodesignError('generate-title requires a non-empty prompt', 'IPC_BAD_INPUT');
      }
      const cfg = getCachedConfig();
      if (cfg === null) throw new CodesignError('No configuration', 'CONFIG_MISSING');
      const active = resolveActiveModel(cfg, {
        provider: cfg.activeProvider,
        modelId: cfg.activeModel,
      });
      const allowKeyless = active.allowKeyless;
      const apiKey = await resolveApiKeyForActive(active.model.provider, allowKeyless);
      const baseUrl = active.baseUrl ?? undefined;
      const tlsBypass = resolveTlsBypassFor(cfg, active.model.provider);
      const titleLogger: CoreLogger = {
        info: (event, data) => logIpc.info(event, data),
        warn: (event, data) => logIpc.warn(event, data),
        error: (event, data) => logIpc.error(event, data),
      };
      try {
        return await withTlsBypass(tlsBypass, () =>
          generateTitle({
            prompt,
            model: active.model,
            apiKey,
            ...(baseUrl !== undefined ? { baseUrl } : {}),
            wire: active.wire,
            ...(active.httpHeaders !== undefined ? { httpHeaders: active.httpHeaders } : {}),
            ...(active.reasoningLevel !== undefined
              ? { reasoningLevel: active.reasoningLevel }
              : {}),
            ...(allowKeyless ? { allowKeyless: true } : {}),
            logger: titleLogger,
          }),
        );
      } catch (err) {
        logIpc.error('[title] generate-title.fail', {
          provider: active.model.provider,
          modelId: active.model.modelId,
          baseUrl,
          message: err instanceof Error ? err.message : String(err),
          code: err instanceof CodesignError ? err.code : undefined,
        });
        recordFinalError('title', runId, err);
        throw err;
      }
    });
  });

  return () => {
    // Los turnos vivos Y el trabajo suelto de los que ya contestaron: apagar el pack
    // tiene que soltar el slot del cerebro, no dejarlo tomado hasta que muera el proceso.
    const paraApagar = [
      ...inFlight.values(),
      ...[...sueltos.values()].map((s) => s.controller),
    ];
    for (const controller of paraApagar) {
      try {
        controller.abort();
      } catch {
        // controller may already be settled
      }
    }
    inFlight.clear();
    sueltos.clear();
    inFlightByDesign.clear();
    inFlightByWorkspace.clear();
  };
}
