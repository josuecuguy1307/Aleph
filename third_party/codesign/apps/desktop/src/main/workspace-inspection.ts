import { inspectWorkspaceFiles, type WorkspaceInspection } from '@open-codesign/core';
import { listWorkspaceFilesAt } from './workspace-reader';

export async function inspectWorkspaceAt(workspaceRoot: string): Promise<WorkspaceInspection> {
  const files = await listWorkspaceFilesAt(workspaceRoot);
  return inspectWorkspaceFiles(files.map((file) => ({ file: file.path })));
}
