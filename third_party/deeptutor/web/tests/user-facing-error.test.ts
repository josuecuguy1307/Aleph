import assert from "node:assert/strict";
import test from "node:test";
import { userFacingError } from "../lib/user-facing-error";

test("nested provider errors retain the explanation instead of JSON", () => {
  const message = "The model requires a newer version of Codex. Please upgrade.";
  const inner = JSON.stringify({ type: "error", error: { message } });
  const raw = "HTTP 502: " + JSON.stringify({ error: { message: "[Codex] " + inner + "\n" + inner } });
  assert.equal(userFacingError(raw, "Interrupted"), message);
});
test("truncated envelope keeps status but no internal fields", () => {
  assert.equal(userFacingError('HTTP 502: {"error":{"message":"partial', "Interrupted"), "Interrupted (HTTP 502)");
  assert.equal(userFacingError("Connection lost", "Interrupted"), "Connection lost");
});
