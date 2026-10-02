/**
 * Hard-blocked bash patterns. These never reach the user's "Allow / Deny"
 * dialog — `tool_call` hook returns `{ block: true, reason: ... }`
 * immediately and surfaces a one-line warning in the agent log.
 *
 * Rationale: the patterns below are either always-destructive ("rm -rf /")
 * or operate on a scope outside what a design agent ever needs (sudo,
 * package publishing, pipe-to-shell). Allowing them via "always allow"
 * would let a single typo or model error wipe the user's home dir; the
 * UX cost of "this command is just refused" is far smaller than the
 * blast radius.
 */

const BLOCKED_PATTERNS: readonly RegExp[] = [
  /\brm\s+(?:-[rRf]+\s+)+\/(?=\s|$)/, // rm -rf /
  /\brm\s+(?:-[rRf]+\s+)+~(?=\s|$)/, // rm -rf ~
  /\brm\s+(?:-[rRf]+\s+)+\$HOME(?=\s|$)/, // rm -rf $HOME
  /\bsudo\b/, // any sudo
  /\|\s*(?:sh|bash|zsh|fish)\s*$/, // curl ... | sh
  /\|\s*(?:sh|bash|zsh|fish)\s*[<>&;]/, // pipe-to-shell mid-pipeline
  /\bnpm\s+publish\b/,
  /\bpnpm\s+publish\b/,
  /\byarn\s+publish\b/,
  /\bcargo\s+publish\b/,
  /\bgem\s+push\b/,
  /\bcurl\s+[^|]*\|\s*(?:sh|bash)\b/, // canonical pipe-to-shell
  /\bwget\s+[^|]*\|\s*(?:sh|bash)\b/,
  /:\s*\(\s*\)\s*\{\s*:\s*\|\s*:/, // fork bomb prefix
];

export interface BlockResult {
  blocked: boolean;
  pattern?: string;
}

export function checkBashBlocklist(command: string): BlockResult {
  const trimmed = command.trim();
  if (!trimmed) return { blocked: false };
  for (const pattern of BLOCKED_PATTERNS) {
    if (pattern.test(trimmed)) {
      return { blocked: true, pattern: pattern.source };
    }
  }
  return { blocked: false };
}

export function describeBlock(command: string): string {
  const r = checkBashBlocklist(command);
  return r.blocked
    ? `Command refused by hard blocklist (matches /${r.pattern}/). v0.2 never escalates these — see security/bash-blocklist.ts.`
    : 'Command not blocked.';
}
