import { createHash, randomUUID } from "node:crypto";
import { safeEnsureAbsoluteDir, safeExistsAbsolute, safeReadAbsoluteFile } from "./safe-fs.js";

export async function exists(path: string): Promise<boolean> {
  return safeExistsAbsolute(path);
}

export async function ensureDir(path: string): Promise<void> {
  await safeEnsureAbsoluteDir(path);
}

export async function readJsonFile<T>(path: string): Promise<T | null> {
  try {
    const raw = await safeReadAbsoluteFile(path, "utf8");
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function shortId(): string {
  return randomUUID();
}

export function parseList(input: string | undefined): string[] {
  if (!input) return [];
  const trimmed = input.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item)).filter(Boolean);
      }
    } catch {
      return [];
    }
  }
  return trimmed
    .split(/[,;]/)
    .map((value) => value.trim())
    .filter(Boolean);
}
