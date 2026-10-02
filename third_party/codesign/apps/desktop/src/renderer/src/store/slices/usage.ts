export interface UsageSnapshot {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export function isFiniteUsageNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0;
}

export function coerceUsageSnapshot(result: {
  inputTokens?: unknown;
  outputTokens?: unknown;
  costUsd?: unknown;
}): { usage: UsageSnapshot; rejected: string[] } {
  const rejected: string[] = [];
  const pick = (label: string, v: unknown): number => {
    if (v === undefined) return 0;
    if (isFiniteUsageNumber(v)) return v;
    rejected.push(label);
    return 0;
  };
  return {
    usage: {
      inputTokens: pick('inputTokens', result.inputTokens),
      outputTokens: pick('outputTokens', result.outputTokens),
      costUsd: pick('costUsd', result.costUsd),
    },
    rejected,
  };
}
