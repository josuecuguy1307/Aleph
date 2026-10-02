import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// Load this browser ES module as a data URL so the check does not depend on the repo's
// package.json module mode.
const source = await readFile(new URL("./envelope.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { falloDeRun } = await import(moduleUrl);

const rawProviderError = JSON.stringify({
  status: 429,
  error: { message: "Earlier Claude Code rate limit", type: "throttled" },
  retry_after_s: 5615,
});
const result = falloDeRun({
  error: rawProviderError,
  causa: {
    causa: "rate_limit",
    detalle: "Claude Code was temporarily rate-limited earlier. Aleph is still observing the local retry window.",
    runtime_state: "local_cooldown_from_previous_limit",
    quota_availability: "unknown",
    evidencia: { provider_event: { reset_hint: "1 h 33 min", origin: "provider" } },
  },
});

assert.match(result.mensaje, /temporarily rate-limited earlier/);
assert.equal(result.diagnostico, rawProviderError);
assert.equal(result.quota_availability, "unknown");
assert.equal(result.provider_rate_limit_event.reset_hint, "1 h 33 min");

const localHttpFailure = falloDeRun({
  message: `HTTP 429: ${rawProviderError}`,
  detail: `HTTP 429: ${rawProviderError}`,
  causa: {
    detalle: "Claude Code was temporarily rate-limited earlier. Aleph is still observing the local retry window.",
    runtime_state: "local_cooldown_from_previous_limit",
    quota_availability: "unknown",
  },
});
assert.match(localHttpFailure.mensaje, /temporarily rate-limited earlier/);
assert.equal(localHttpFailure.diagnostico, `HTTP 429: ${rawProviderError}`);
console.log("✓ cooldown UI keeps safe copy separate from the raw diagnostic");
