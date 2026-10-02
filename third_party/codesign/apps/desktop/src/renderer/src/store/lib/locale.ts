import { i18n } from '@open-codesign/i18n';
import type { LocalInputFile, ModelRef } from '@open-codesign/shared';

export function tr(key: string, options?: Record<string, unknown>): string {
  return i18n.t(key, options ?? {}) as string;
}

export function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function modelRef(provider: string, modelId: string): ModelRef {
  return { provider, modelId };
}

export function normalizeReferenceUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : undefined;
}

export function uniqueFiles(files: LocalInputFile[]): LocalInputFile[] {
  const seen = new Set<string>();
  const result: LocalInputFile[] = [];
  for (const file of files) {
    if (seen.has(file.path)) continue;
    seen.add(file.path);
    result.push(file);
  }
  return result;
}
