/**
 * Claude Code compatibility mode.
 *
 * Many community-run "Claude subscription → API" gateways (sub2api,
 * claude2api, anyrouter, …) sit behind a WAF that only admits requests
 * identifying themselves as Claude Code. They return "403 Your request
 * was blocked" to anyone whose User-Agent does not start with `claude-cli/`
 * and who does not carry the matching anthropic-beta / x-app headers.
 *
 * pi-ai emits those identity headers only when the API key looks like an
 * OAuth token (`sk-ant-oat*`). Users pasting a sub2api-issued key (often
 * an arbitrary opaque string) fall into the plain API-key branch and hit
 * 403 at the edge before any auth check runs.
 *
 * Fix: when a request targets a custom anthropic-wire base URL (anything
 * other than api.anthropic.com), inject the Claude Code identity headers
 * so the gateway WAF accepts us. User-supplied httpHeaders always win.
 */

import type { WireApi } from '@open-codesign/shared';

/** Matches pi-ai 0.67.68 so both paths present the same UA to gateways. */
const CLAUDE_CODE_VERSION = '2.1.75';

const CLAUDE_CODE_BETA = [
  'claude-code-20250219',
  'oauth-2025-04-20',
  'fine-grained-tool-streaming-2025-05-14',
  // Include every beta pi-ai would add for non-adaptive-thinking models,
  // so overwriting pi-ai's anthropic-beta via optionsHeaders is lossless.
  // Adaptive-thinking models (Opus 4.6+, Sonnet 4.6+) ignore this flag.
  'interleaved-thinking-2025-05-14',
].join(',');

/** True when the baseUrl points at api.anthropic.com (or is unset, which
 *  pi-ai treats as the default official endpoint). */
export function isOfficialAnthropicBaseUrl(baseUrl: string | undefined): boolean {
  if (baseUrl === undefined || baseUrl.length === 0) return true;
  let host: string;
  try {
    host = new URL(baseUrl).host.toLowerCase();
  } catch {
    return false;
  }
  // WHATWG URL strips the default port for the current scheme (https://
  // drops :443, http:// drops :80). Strip them again for cross-scheme typos
  // like `http://api.anthropic.com:443` so the official endpoint is
  // recognized regardless of how the user spells it. Non-default ports
  // (e.g. :8443) remain, correctly marking those as custom proxies.
  const normalized = host.replace(/:(?:80|443)$/, '');
  return normalized === 'api.anthropic.com' || normalized.endsWith('.anthropic.com');
}

/** Whether requests with this wire+baseUrl need CC identity headers to
 *  pass a sub2api / claude2api WAF. */
export function shouldForceClaudeCodeIdentity(
  wire: WireApi | undefined,
  baseUrl: string | undefined,
): boolean {
  return wire === 'anthropic' && !isOfficialAnthropicBaseUrl(baseUrl);
}

/** The CC identity header bag. Lowercase keys so they collide
 *  predictably with pi-ai's own lowercase defaults on merge. */
export function claudeCodeIdentityHeaders(): Record<string, string> {
  return {
    'user-agent': `claude-cli/${CLAUDE_CODE_VERSION}`,
    'x-app': 'cli',
    'anthropic-beta': CLAUDE_CODE_BETA,
  };
}

/** Matches pi-ai's sk-ant-oat heuristic. When true, pi-ai injects CC
 *  headers itself — callers going through pi-ai can skip this layer. */
export function looksLikeClaudeOAuthToken(apiKey: string): boolean {
  return apiKey.includes('sk-ant-oat');
}

/**
 * Merge CC identity headers with caller-supplied headers such that the
 * caller's values always win. Use for code paths that build the final
 * header bag we send on the wire (validate ping, connection test).
 */
export function withClaudeCodeIdentity(
  wire: WireApi | undefined,
  baseUrl: string | undefined,
  extraHeaders: Record<string, string> | undefined,
): Record<string, string> {
  if (!shouldForceClaudeCodeIdentity(wire, baseUrl)) {
    return { ...(extraHeaders ?? {}) };
  }
  return { ...claudeCodeIdentityHeaders(), ...(extraHeaders ?? {}) };
}
