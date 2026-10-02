/** Aleph Oficina never configures vendor telemetry. */
export const DEFAULT_POSTHOG_KEY = "";

export function resolvePosthogKey(_raw: unknown, _isDev: boolean): string {
  return "";
}
