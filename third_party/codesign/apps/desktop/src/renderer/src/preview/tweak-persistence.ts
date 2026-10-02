import {
  DEFAULT_SOURCE_ENTRY,
  type EditmodeTokens,
  LEGACY_SOURCE_ENTRY,
  replaceEditmodeBlock,
} from '@open-codesign/shared';
import {
  resolveWorkspacePreviewSource,
  type WorkspacePreviewRead,
  type WorkspacePreviewReadResult,
} from './workspace-source';

export type WorkspacePreviewWrite = (
  designId: string,
  path: string,
  content: string,
) => Promise<WorkspacePreviewReadResult>;

export interface PersistTweakTokensResult {
  content: string;
  path: string;
  wrote: boolean;
}

export async function resolveTweakWriteTarget(input: {
  designId: string;
  previewSource: string;
  read?: WorkspacePreviewRead | undefined;
}): Promise<WorkspacePreviewReadResult> {
  if (!input.read) return { content: input.previewSource, path: DEFAULT_SOURCE_ENTRY };
  let index: WorkspacePreviewReadResult;
  try {
    index = await input.read(input.designId, DEFAULT_SOURCE_ENTRY);
  } catch {
    index = await input.read(input.designId, LEGACY_SOURCE_ENTRY);
  }
  return await resolveWorkspacePreviewSource({
    designId: input.designId,
    source: index.content,
    path: index.path,
    read: input.read,
  });
}

export async function persistTweakTokensToWorkspace(input: {
  designId: string | null;
  previewSource: string;
  tokens: EditmodeTokens;
  read?: WorkspacePreviewRead | undefined;
  write?: WorkspacePreviewWrite | undefined;
}): Promise<PersistTweakTokensResult> {
  const fallbackContent = replaceEditmodeBlock(input.previewSource, input.tokens);
  if (!input.designId || !input.write) {
    return { content: fallbackContent, path: DEFAULT_SOURCE_ENTRY, wrote: false };
  }

  const target = await resolveTweakWriteTarget({
    designId: input.designId,
    previewSource: input.previewSource,
    read: input.read,
  });
  const nextContent = replaceEditmodeBlock(target.content, input.tokens);
  await input.write(input.designId, target.path, nextContent);
  return { content: nextContent, path: target.path, wrote: true };
}
