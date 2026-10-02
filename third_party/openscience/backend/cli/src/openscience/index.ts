import path from "path"
import os from "os"
import fs from "fs/promises"
import { existsSync, readFileSync, writeFileSync, chmodSync } from "fs"
import { randomUUID, createHash } from "crypto"
import { Global } from "../global"
import { Log } from "../util/log"
import { Lock } from "../util/lock"
import { Env } from "../env"
import { Auth } from "../auth"
import {
  isSyncedEnvAllowed,
  BYOK_LLM_ENV_KEYS,
  SYNCED_SERVICE_ENV_KEYS,
  managedOpenRouterBaseURL,
} from "./synced-env-policy"
import { DEFAULT_MANAGED_API_BASE, MANAGED_API_BASE } from "../endpoints"

const log = Log.create({ service: "openscience" })

// Atlas is the unified backend for openscience-cli auth, BYOK, and billing. The
// base URL resolves through the shared endpoints module (neutral public
// default + SYNSC_API_BASE / MANAGED_API_BASE / ATLAS_BASE_URL override), so
// self-hosters and dev stacks can repoint the client without code changes.
const DEFAULT_API_BASE = DEFAULT_MANAGED_API_BASE
export const API_BASE = MANAGED_API_BASE

// (Acá había un banner que avisaba cuando el CLI hablaba con un backend que no era
// el de producción del fabricante, y VERIFICATION_PAGE, la página de aprobación de
// dispositivos. Salieron con la superficie de cuenta.)

const syncedSecretValues = new Map<string, string>()

// User-owned (BYOK) secret values — api keys from auth.json and provider env
// vars the user set in their own shell. Cached synchronously so redactSecrets()
// (a hot path in bash output streaming) can mask them without an async read.
const byokSecretValues = new Set<string>()
const TOKEN_SECRET_PATTERNS = [
  /\b(?:thk_|sk-|sk_|gsk_|hf_|nvapi-|ghp_|gho_|ghu_|ghs_|github_pat_|xox[baprs]-)[A-Za-z0-9._-]{8,}\b/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
]
const QUOTED_SECRET =
  /(\b(?:[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)\b\s*[:=]\s*)(["'])(.*?)\2/gi
const BARE_SECRET =
  /(\b(?:[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)\b\s*[:=]\s*)((?!Bearer\b)[^\s"'[,;}\]]{4,})/gi
const BEARER_SECRET = /(\bBearer\s+)[A-Za-z0-9._~+/-]{4,}=*/gi
const SECRET_FIELD =
  /(^|[_-])(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|credential|authorization)($|[_-])|^(apiKey|accessToken|refreshToken|authToken|clientSecret|secretKey)$/i

function isManagedAtlasKey(value: string): boolean {
  return value.startsWith("thk_")
}

function getSyncedConfigDir(): string {
  const config = process.env.OPENSCIENCE_CONFIG_DIR?.trim()
  if (config) return path.resolve(config)
  // Use XDG config dir (user-writable) for synced config from dashboard
  // This avoids needing root/admin permissions unlike /Library/Application Support
  const xdg = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config")
  return path.join(xdg, "openscience")
}

const syncedGcpFilename = "atlas-gcp-service-account.json"

// Seed the synced-secret set from the on-disk snapshot at import. preload-env.ts
// replays synced-env.json into process.env at boot but never seeded this set, so
// on a fresh process where no in-process sync runs (the common steady state, when
// the dashboard version is unchanged) the set stayed empty — and a disk-replayed
// synced secret that isn't a thk_ value was neither stripped from subprocess env
// nor masked by redactSecrets(). Synchronous + best-effort so the hot sync paths
// (redactSecrets) have the values available without an async read.
;(() => {
  try {
    const raw = readFileSync(path.join(getSyncedConfigDir(), "synced-env.json"), "utf-8")
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === "string" && value) syncedSecretValues.set(key, value)
      }
    }
  } catch {
    /* no snapshot on disk — nothing to seed */
  }
})()

/** Env vars that are safe to pass to subprocesses */
const SAFE_ENV_PREFIXES = ["PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_", "TMPDIR", "XDG_", "EDITOR", "VISUAL"]
const KERNEL_RUNTIME_KEYS = new Set([
  "TMP",
  "TEMP",
  "PYTHONPATH",
  "PYTHONHOME",
  "VIRTUAL_ENV",
  "CONDA_PREFIX",
  "CONDA_DEFAULT_ENV",
  "R_HOME",
  "R_LIBS",
  "R_LIBS_USER",
  "LD_LIBRARY_PATH",
  "DYLD_LIBRARY_PATH",
  "SYSTEMROOT",
  "WINDIR",
  "PATHEXT",
  "COMSPEC",
])
const SAFE_SYNCED_KEYS = new Set([
  ...BYOK_LLM_ENV_KEYS,
  ...SYNCED_SERVICE_ENV_KEYS,
  // Misc CLI runtime markers
  "OPENSCIENCE_RUNTIME",
])

// Modal credentials belong to its trusted adapter and never enter
// agent-controlled shells, including when supplied by an explicit export.
const CONTROL_PLANE_ENV_KEYS = new Set(["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"])

/**
 * Persistent CLI auth session.
 *
 * Holds the long-lived ``thk_*`` API key issued by the Atlas device-code
 * flow. Atlas API keys carry a 1-year TTL and are revoked by deletion
 * rather than expiry, so we don't track refresh tokens or expiry locally
 * — a 401 on any request signals "key revoked or expired, re-auth".
 */
interface OpenScienceSession {
  /** Atlas-issued ``thk_<uuid>.<secret>`` Bearer token. */
  api_key: string
  /** Atlas user_id (UUID). Stored for diagnostics; not used for auth. */
  user_id: string
  /** Friendly device label this session was registered under. */
  device_name?: string
  /** Last-seen ``/api/cli/sync/version`` value. Background refresh fires
   *  when the server returns a higher value. */
  cached_v?: number
  /** Epoch-ms timestamp of the last version probe. Used to gate rapid-
   *  fire probes to at most once per VERSION_PROBE_TTL_MS. */
  last_check_ts?: number
}

type SyncedServiceReason =
  | "missing_key"
  | "no_credits"
  | "ineligible_plan"
  | "proxy_disabled"
  | "managed_key_unconfigured"
  | "managed_via_openrouter"

interface SyncedService {
  connected: boolean
  /** Present only when `connected` is false. Explains why the provider
   *  could not be connected so the CLI can print an actionable message. */
  reason?: SyncedServiceReason
  env?: Record<string, string>
  metadata?: Record<string, string>
}

interface SyncResponse {
  user: {
    user_id?: string
    email?: string | null
    display_name?: string | null
    github_username?: string | null
    subscription_status?: string | null
    subscription_plan?: string | null
  }
  services: Record<string, SyncedService>
  config?: {
    enabled_providers?: string[]
    provider?: Record<string, { whitelist?: string[] }>
    model?: string
  }
}

/**
 * Returns an actionable one-liner for a disconnected provider based on the
 * reason code returned by the backend sync endpoint.
 */
function describeReason(provider: string, reason: SyncedServiceReason | undefined): string {
  switch (reason) {
    case "missing_key":
      return `${provider}: no key set — add one in the dashboard or top up credits.`
    case "no_credits":
      return `${provider}: Credits are empty - top up at https://app.syntheticsciences.ai/billing.`
    case "ineligible_plan":
      return `${provider}: refresh Atlas and reconnect the key — BYOK is available on every plan.`
    case "proxy_disabled":
      return `${provider}: Atlas managed mode is disabled on this deployment — BYOK only.`
    case "managed_key_unconfigured":
      return `${provider}: Atlas managed mode unavailable on this deployment — ask the admin.`
    case "managed_via_openrouter":
      return `${provider}: wallet access to ${provider} models routes through the openrouter provider — pick them there, or add your own ${provider} key for direct access.`
    default:
      return `${provider}: not connected.`
  }
}

/**
 * Thrown when the backend rejects a usage report because the user is
 * out of credits (managed mode) or has no active subscription. Halts
 * the session so the agent loop doesn't keep racking up calls the
 * user can't pay for. Caught at the session boundary; surfaced to the
 * user as "Insufficient credits - top up at app.syntheticsciences.ai/billing".
 */
export class InsufficientCreditsError extends Error {
  constructor(
    message: string = "Credits are empty. Top up at app.syntheticsciences.ai/billing or switch back to your own keys.",
  ) {
    super(message)
    this.name = "InsufficientCreditsError"
  }
}

// ── Bundled atlas CLI resolution ─────────────────────────────────────────
// The @synsci/atlas package ships as a dependency; its `atlas` binary lives in
// node_modules. The agent shells out to native `atlas` commands (the research
// prompts drive the map + managed-compute path through it), so the
// binary must be on the subprocess PATH without requiring a separate global
// install. We resolve the package, prefer the npm-generated `.bin/atlas` shim,
// and otherwise synthesize a tiny launcher in the openscience data dir that runs the
// package's declared bin entry via node. Result is cached; every step is
// best-effort and never throws — if atlas can't be found the agent's
// `atlas doctor` gate degrades gracefully.
let atlasBinDirCache: string | null | undefined

/** Resolve (and cache) the directory that should be prepended to a subprocess
 *  PATH so `atlas` resolves to the bundled CLI. Returns null when the package
 *  can't be located (e.g. a standalone compiled binary with no node_modules) —
 *  callers treat that as "atlas unavailable" and continue. */
function ensureAtlasBinDir(): string | null {
  // Siempre null: el CLI companion `atlas` venía del paquete @synsci/atlas, que sale
  // del repo PRIVADO synthetic-sciences/thesis y no entra al árbol de Aleph. Los
  // llamadores ya tratan null como "atlas no disponible" y siguen.
  return null
}

/** Prepend the bundled atlas CLI's directory to a subprocess PATH so the agent
 *  can run native `atlas` commands without a separate global install. No-op
 *  when the CLI can't be located or is already on PATH. */
function withAtlasOnPath(env: Record<string, string>): Record<string, string> {
  const dir = ensureAtlasBinDir()
  if (!dir) return env
  const sep = process.platform === "win32" ? ";" : ":"
  const key = Object.keys(env).find((k) => k.toUpperCase() === "PATH") ?? "PATH"
  const parts = (env[key] ?? "").split(sep).filter(Boolean)
  if (parts.includes(dir)) return env
  return { ...env, [key]: [dir, ...parts].join(sep) }
}

export namespace OpenScience {
  const filepath = path.join(Global.Path.data, "openscience-session.json")

  /** Friendly device label sent to the backend. Surfaced in the
   *  user's Devices list so they can identify which machine each row
   *  belongs to. */
  export function deviceName(): string {
    const host = (() => {
      try {
        return os.hostname().split(".")[0]
      } catch {
        return "device"
      }
    })()
    return `openscience · ${process.platform} · ${host}`
  }

  // Bound every Atlas client call. A slow/unresponsive backend must never hang
  // the caller: the per-command sync-version probe and `openscience project init`
  // both go through Atlas fetches, and with the agent's bash tool also unbounded a
  // hang wedged whole sessions for >60 min. Overridable via OPENSCIENCE_ATLAS_TIMEOUT_MS.
  const ATLAS_FETCH_TIMEOUT_MS = Number(process.env["OPENSCIENCE_ATLAS_TIMEOUT_MS"]) || 60_000
  // Skill index/content fetches run on the GET /skill request path, and each only
  // *enriches* a list that also comes from disk cache + bundled skills. A slow or
  // unreachable backend must degrade fast (fall back to cached/empty) instead of
  // wedging the request for the full Atlas timeout — the reporter in #138 saw a
  // single /skill take 62s because these inherited the 60s default. Bound tighter.
  const SKILL_FETCH_TIMEOUT_MS = Number(process.env["OPENSCIENCE_SKILL_TIMEOUT_MS"]) || 8_000
  // (Acá vivía atlasFetch(): el único fetch del módulo hacia el backend del
  // fabricante, con su timeout. Sin superficie Atlas no queda a quién llamar.)

  export async function getSession(): Promise<OpenScienceSession | null> {
    return null
  }

  export async function saveSession(session: OpenScienceSession) {
    return
  }

  /**
   * Seed the bundled `atlas` CLI's own config (`~/.config/atlas-cli/config.json`)
   * from the OpenScience session so the agent can run native `atlas` commands. The
   * key lives in atlas's on-disk config (file-based auth, like the OpenScience
   * session file itself) — it is never put in the agent's shell env, so the
   * `thk_`-stripping boundary in filterEnvForSubprocess stays intact. Pinned to
   * the same backend the OpenScience key is issued for. Best-effort; never throws.
   */
  export async function ensureAtlasCliConfig(session?: OpenScienceSession | null): Promise<void> {
    return
  }

  /** Merge-update the persisted session. Fetches current session, spreads
   *  the patch on top, and writes back. No-ops when unauthenticated. Serialized
   *  under a lock so two concurrent patches (e.g. an interactive last_check_ts
   *  update racing a background cached_v update) can't lose each other's field
   *  in the read-modify-write. */
  async function updateSession(patch: Partial<OpenScienceSession>): Promise<void> {
    using _ = await Lock.write(filepath)
    const session = await getSession()
    if (!session) return
    await saveSession({ ...session, ...patch })
  }

  /** TTL gate for the cheap version probe. */
  const VERSION_PROBE_TTL_MS = 10_000

  /**
   * Fire-and-forget BYOK refresh triggered at most once per
   * VERSION_PROBE_TTL_MS per process. When the server-side sync version
   * has changed since the last probe, runs `syncServices()` in the
   * background so the new env vars land for the NEXT user message while
   * the current one continues with the existing provider config.
   */
  export async function refreshIfStale(): Promise<void> {
    return
  }

  /** Read the on-disk synced-env snapshot (what preload-env.ts replayed into
   *  process.env at boot). Returns an empty map when missing or corrupt. */
  async function readSyncedSnapshot(): Promise<Map<string, string>> {
    const result = new Map<string, string>()
    try {
      const raw = await fs.readFile(path.join(getSyncedConfigDir(), "synced-env.json"), "utf-8")
      const parsed: unknown = JSON.parse(raw)
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return result
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === "string") result.set(key, value)
      }
    } catch {}
    return result
  }

  /** Drop a synced env var from the live process, but only when its current
   *  value is still the one sync injected — an explicit shell export wins. */
  function unsetSyncedVar(key: string, value: string) {
    if (process.env[key] !== value) return
    delete process.env[key]
    try {
      Env.remove(key)
    } catch {
      /* Instance not initialized — process.env delete is enough */
    }
  }

  /** Clear the api_key this CLI seeded into the bundled atlas CLI's config
   *  (see ensureAtlasCliConfig). Only removes the key when it is the one the
   *  session seeded (or, with no readable session, when the profile points at
   *  our backend), so a hand-configured atlas profile survives. Best-effort. */
  // (Acá vivía clearAtlasCliConfig(): limpiaba la config del CLI companion Atlas.
  // Salió con la cuenta.)

  /** Delete queued usage rows. They were produced under the signed-out
   *  account's key; flushing them after a different account logs in would
   *  bill that account for someone else's usage. */
  async function dropUsageQueue(): Promise<void> {
    try {
      const raw = await fs.readFile(pendingQueuePath, "utf-8")
      const rows = raw.split("\n").filter(Boolean).length
      await fs.unlink(pendingQueuePath)
      if (rows) log.info("dropped queued usage on sign-out so it cannot bill a different account", { rows })
    } catch {
      /* no queue — nothing to drop */
    }
  }

  /**
   * Sign out locally: remove the session file and every credential artifact
   * the sync path created. Without this, `synced-env.json` is replayed into
   * process.env on every boot (preload-env.ts) and the still-valid managed
   * key keeps debiting the signed-out account's wallet. Covers both explicit
   * logout and the 401-triggered clear. Best-effort; never throws.
   */
  export async function clearSession() {
    return
  }

  /**
   * Best-effort server-side revocation of THIS device's key, for logout paths.
   * The session stores only the raw api_key (never its key_id), so the device
   * is identified by a unique `key_prefix` match against the devices list —
   * when zero or several devices match, we skip rather than guess. Call
   * BEFORE clearSession(); returns whether the key was revoked.
   */
  export async function revokeCurrentDevice(): Promise<boolean> {
    return false
  }

  export async function isAuthenticated(): Promise<boolean> {
    return false
  }

  /** User-facing dashboard page where keys + billing live. Printed as the
   *  fallback when a browser/loopback login can't be used (headless/CI). */
  export function authPageUrl(): string {
    return ""
  }

  /** Minimal pages shown in the browser after it redirects back to our
   *  loopback callback. Inlined so login carries no asset dependencies. */
  const CALLBACK_SUCCESS_HTML =
    "<!doctype html><meta charset=utf-8><title>OpenScience</title>" +
    '<body style="font-family:system-ui,sans-serif;background:#0b0b12;color:#eee;display:grid;place-items:center;height:100vh;margin:0">' +
    "<div style=text-align:center><h1 style=color:#4ade80>Login complete</h1>" +
    "<p style=color:#9aa>You're signed in to the OpenScience CLI. You can close this tab.</p></div>" +
    "<script>setTimeout(()=>window.close(),1500)</script>"

  const CALLBACK_ERROR_HTML =
    "<!doctype html><meta charset=utf-8><title>OpenScience</title>" +
    '<body style="font-family:system-ui,sans-serif;background:#0b0b12;color:#eee;display:grid;place-items:center;height:100vh;margin:0">' +
    "<div style=text-align:center><h1 style=color:#f87171>Login failed</h1>" +
    "<p style=color:#9aa>The callback could not be verified. Return to your terminal and try again.</p></div>"

  /** Spin up an ephemeral loopback server that waits for the browser to
   *  redirect back with the approved exchange token. Mirrors the
   *  @synsci/atlas reference client: random port, ``/callback`` path, and
   *  a strict ``state`` check to defeat CSRF. */
  // (Acá vivía startCallbackServer(): el servidor de loopback que capturaba el
  // redirect del login por navegador. Salió con la cuenta.)

  /** Build a readable error from a failed login HTTP call. The retired
   *  endpoints answer 426 — translate that into an upgrade nudge. */
  async function loginError(res: Response, phase: string): Promise<string> {
    if (res.status === 426) {
      return "This OpenScience version is out of date. Run `openscience upgrade` (or `npm i -g @synsci/openscience@latest`) and try again."
    }
    const detail = await res.text().catch(() => "")
    const trimmed = detail.trim().slice(0, 200)
    return `Login ${phase} failed: HTTP ${res.status}${trimmed ? ` — ${trimmed}` : ""}`
  }

  /** Browser login: open the approval URL, capture the redirect on a
   *  loopback server, then exchange it for a long-lived ``thk_`` key.
   *  Endpoints: ``POST /api/v1/auth/cli/browser/{start,redeem}``. */
  export async function browserLogin(_opts?: {
    onApprovalUrl?: (url: string) => void
    timeoutMs?: number
  }): Promise<OpenScienceSession> {
    throw new Error("La cuenta del proyecto de origen salió con la extirpación")
  }

  /** Headless / CI login: validate a pasted ``thk_`` key and persist it.
   *  Used when no local browser + loopback callback is available. */
  export async function loginWithKey(rawKey: string): Promise<OpenScienceSession> {
    throw new Error("La cuenta del proyecto de origen salió con la extirpación")
  }

  /** Write a file atomically (temp + rename) so a crash mid-write can never
   *  leave a torn file — a torn synced-env.json silently drops managed keys, and
   *  a torn openscience-synced.json throws during config load and bricks the CLI
   *  until it's removed by hand. */
  async function atomicWrite(filepath: string, content: string, options?: { mode?: number }): Promise<void> {
    // Unique per call (not just per PID): two concurrent syncs in the SAME
    // process (e.g. a per-request /sync and the processor's background sync)
    // would otherwise write the identical temp path, interleave, and publish a
    // torn file or fail the rename.
    const tmp = `${filepath}.${process.pid}.${randomUUID()}.tmp`
    await Bun.write(tmp, content, options)
    if (options?.mode !== undefined && process.platform !== "win32") await fs.chmod(tmp, options.mode)
    await fs.rename(tmp, filepath)
  }

  /** Fetch all connected service credentials and inject as env vars */
  export async function syncServices(): Promise<{
    user: SyncResponse["user"]
    credentials: number
  } | null> {
    return null
  }

  /** Provider env var names whose values are user-owned secrets worth masking
   *  when they leak into command output. Shares the single BYOK-provider source
   *  of truth with the sync blocklist (synced-env-policy.ts) so a key the user
   *  exported in their shell is redacted the same as a synced one. */
  const BYOK_ENV_KEYS = BYOK_LLM_ENV_KEYS

  /** Populate the BYOK secret cache from auth.json (api-type keys) and the
   *  user's provider env vars. Best-effort + idempotent; safe to call often.
   *  Managed thk_* values are excluded (they are already redacted via the
   *  synced set and are never the user's own credential). */
  export async function refreshByokSecrets(env: NodeJS.ProcessEnv = process.env): Promise<void> {
    return
  }

  /** Register externally-sourced secret values (e.g. the decrypted service
   *  credentials from settings ▸ Credentials) so they are masked in subprocess
   *  output exactly like BYOK/managed keys. Short and managed (thk_*) values are
   *  ignored. Idempotent — safe to call on every credential save. */
  export function registerSecretValues(values: Iterable<string>): void {
    for (const value of values) {
      if (!value || value.length < 4 || isManagedAtlasKey(value)) continue
      byokSecretValues.add(value)
    }
  }

  /** Mask every known managed + BYOK secret value in arbitrary text. Sync so it
   *  can run inline on streamed subprocess output. Call refreshByokSecrets()
   *  ahead of a subprocess run to seed the BYOK cache. */
  export function redactSecrets(text: string): string {
    let result = text
    for (const value of syncedSecretValues.values()) {
      if (value.length < 4) continue
      result = result.replaceAll(value, "[REDACTED]")
    }
    for (const value of byokSecretValues) {
      if (value.length < 4) continue
      result = result.replaceAll(value, "[REDACTED]")
    }
    for (const pattern of TOKEN_SECRET_PATTERNS) result = result.replace(pattern, "[REDACTED]")
    result = result.replace(BEARER_SECRET, "$1[REDACTED]")
    result = result.replace(QUOTED_SECRET, "$1$2[REDACTED]$2")
    result = result.replace(BARE_SECRET, "$1[REDACTED]")
    return result
  }

  /** Redact a JSON-shaped value, including plain values stored under credential-
   *  shaped keys, using the currently seeded secret cache. */
  export function redactSensitive<T>(value: T): T {
    const visit = (item: unknown, key?: string): unknown => {
      if (typeof item === "string") return key && SECRET_FIELD.test(key) ? "[REDACTED]" : redactSecrets(item)
      if (Array.isArray(item)) return item.map((entry) => visit(entry))
      if (!item || typeof item !== "object") return item
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>).map(([name, entry]) => [name, visit(entry, name)]),
      )
    }
    return visit(value) as T
  }

  /** Refresh known BYOK values, then redact a JSON-shaped value. Persistence
   *  boundaries should use this entry point before serializing. */
  export async function scrubSecrets<T>(value: T): Promise<T> {
    await refreshByokSecrets()
    return redactSensitive(value)
  }

  /** Whether a value is a managed Atlas proxy token (thk_*). Managed calls are
   *  the only ones that debit Credits. */
  export function isManagedKeyValue(value: string | undefined): boolean {
    return typeof value === "string" && isManagedAtlasKey(value)
  }

  /** Whether an env var name was populated by the dashboard sync (managed). */
  export function isSyncedSecretKey(key: string): boolean {
    return syncedSecretValues.has(key)
  }

  /** Whether a value matches a dashboard-synced (managed) secret. */
  export function isSyncedSecretValue(value: string | undefined): boolean {
    if (!value) return false
    for (const v of syncedSecretValues.values()) if (v === value) return true
    return false
  }

  /** Filter env vars for subprocesses — exclude managed Atlas proxy tokens. */
  export function filterEnvForSubprocess(env: NodeJS.ProcessEnv): Record<string, string> {
    const result: Record<string, string> = {}
    for (const [key, value] of Object.entries(env)) {
      if (!value) continue
      if (CONTROL_PLANE_ENV_KEYS.has(key)) continue
      if (isManagedAtlasKey(value)) continue
      // Entries ending in `_` (LC_, XDG_) are true prefixes; the rest are exact
      // names. Treating all as prefixes let HOME match HOMEBREW_GITHUB_API_TOKEN,
      // USER match USERPROFILE, etc. — over-broad passthrough.
      const isSafe =
        SAFE_ENV_PREFIXES.some((p) => (p.endsWith("_") ? key.startsWith(p) : key === p)) || SAFE_SYNCED_KEYS.has(key)
      if (isSafe || !syncedSecretValues.has(key)) {
        result[key] = value
      }
    }
    return result
  }

  /** Minimal environment for arbitrary notebook/R code. Kernels need language
   * runtime discovery and locale/temp configuration, not the user's shell
   * credentials. Provider, Atlas, cloud, and ad-hoc secret vars stay on the
   * OpenScience host and can only enter a kernel through an explicit start env. */
  export function filterEnvForKernel(env: NodeJS.ProcessEnv): Record<string, string> {
    const result: Record<string, string> = {}
    for (const [key, value] of Object.entries(env)) {
      if (!value) continue
      const runtime =
        SAFE_ENV_PREFIXES.some((prefix) => (prefix.endsWith("_") ? key.startsWith(prefix) : key === prefix)) ||
        KERNEL_RUNTIME_KEYS.has(key)
      if (runtime) result[key] = value
    }
    return result
  }

  export function kernelEnv(env: NodeJS.ProcessEnv = process.env) {
    return filterEnvForKernel(env)
  }

  /** Host credential files that an OS-sandboxed kernel must not read. Atlas
   * access is intentionally provided by the native host broker instead. */
  export function kernelSensitivePaths() {
    return [
      filepath,
      path.join(Global.Path.data, "auth.json"),
      path.join(Global.Path.data, "credentials.json"),
      path.join(Global.Path.data, "mcp-auth.json"),
      path.join(getSyncedConfigDir(), "synced-env.json"),
      process.env.ATLAS_CLI_CONFIG_PATH || path.join(os.homedir(), ".config", "atlas-cli", "config.json"),
    ]
  }

  /** Provider IDs (as stored in auth.json) whose user-owned BYOK keys are safe
   *  to expose to skill subprocesses, mapped to the env var(s) the scripts
   *  read. These are keys the user explicitly added with `openscience login` —
   *  unlike the shared managed keys, which stay stripped. */
  const BYOK_SUBPROCESS_PROVIDERS: Record<string, { keys: string[]; baseUrl?: string; publicBaseUrl?: string }> = {
    openai: {
      keys: ["OPENAI_API_KEY"],
      baseUrl: "OPENAI_BASE_URL",
      publicBaseUrl: "https://api.openai.com/v1",
    },
    anthropic: {
      keys: ["ANTHROPIC_API_KEY"],
      baseUrl: "ANTHROPIC_BASE_URL",
      publicBaseUrl: "https://api.anthropic.com/v1",
    },
    google: {
      keys: ["GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"],
      baseUrl: "GOOGLE_GENERATIVE_AI_BASE_URL",
      publicBaseUrl: "https://generativelanguage.googleapis.com/v1beta",
    },
    xai: {
      keys: ["XAI_API_KEY"],
      baseUrl: "XAI_BASE_URL",
      publicBaseUrl: "https://api.x.ai/v1",
    },
    meta: { keys: ["META_MODEL_API_KEY"] },
    openrouter: {
      keys: ["OPENROUTER_API_KEY"],
      baseUrl: "OPENROUTER_BASE_URL",
      publicBaseUrl: "https://openrouter.ai/api/v1",
    },
    togetherai: {
      keys: ["TOGETHER_API_KEY"],
      baseUrl: "TOGETHER_BASE_URL",
      publicBaseUrl: "https://api.together.xyz/v1",
    },
    together: {
      keys: ["TOGETHER_API_KEY"],
      baseUrl: "TOGETHER_BASE_URL",
      publicBaseUrl: "https://api.together.xyz/v1",
    },
    groq: {
      keys: ["GROQ_API_KEY"],
      baseUrl: "GROQ_BASE_URL",
      publicBaseUrl: "https://api.groq.com/openai/v1",
    },
    "fireworks-ai": {
      keys: ["FIREWORKS_API_KEY"],
      baseUrl: "FIREWORKS_BASE_URL",
      publicBaseUrl: "https://api.fireworks.ai/inference/v1",
    },
    fireworks: {
      keys: ["FIREWORKS_API_KEY"],
      baseUrl: "FIREWORKS_BASE_URL",
      publicBaseUrl: "https://api.fireworks.ai/inference/v1",
    },
    mistral: {
      keys: ["MISTRAL_API_KEY"],
      baseUrl: "MISTRAL_BASE_URL",
      publicBaseUrl: "https://api.mistral.ai/v1",
    },
    deepseek: {
      keys: ["DEEPSEEK_API_KEY"],
      baseUrl: "DEEPSEEK_BASE_URL",
      publicBaseUrl: "https://api.deepseek.com",
    },
    cerebras: {
      keys: ["CEREBRAS_API_KEY"],
      baseUrl: "CEREBRAS_BASE_URL",
      publicBaseUrl: "https://api.cerebras.ai/v1",
    },
    perplexity: {
      keys: ["PERPLEXITY_API_KEY"],
      baseUrl: "PERPLEXITY_BASE_URL",
      publicBaseUrl: "https://api.perplexity.ai",
    },
  }

  /** Merge user-owned (BYOK) provider keys from auth.json into a subprocess env.
   *  Pure + synchronous so it stays unit-testable. Skips managed `thk_*` keys
   *  and never overrides a value already present (shell export or synced var).
   *  When a BYOK key is injected for a provider with a base-url var, the base
   *  url is pinned to the public endpoint so the key authenticates against the
   *  right host rather than a managed proxy. */
  export function mergeByokEnv(base: Record<string, string>, auth: Record<string, Auth.Info>): Record<string, string> {
    const result = { ...base }
    for (const [providerID, info] of Object.entries(auth)) {
      if (info.type !== "api") continue
      if (isManagedAtlasKey(info.key)) continue
      const spec = BYOK_SUBPROCESS_PROVIDERS[providerID]
      if (!spec) continue
      if (spec.keys.some((key) => result[key])) continue
      for (const key of spec.keys) result[key] = info.key
      if (spec.baseUrl && spec.publicBaseUrl) result[spec.baseUrl] = spec.publicBaseUrl
    }
    return result
  }

  /** Subprocess env = sanitized base env + any user-owned BYOK provider keys
   *  from auth.json. Lets skill scripts (e.g. nano-banana image generation)
   *  use a key the user connected with `openscience login`, without leaking the
   *  shared managed keys. */
  export async function subprocessEnv(env: NodeJS.ProcessEnv = process.env): Promise<Record<string, string>> {
    const base = filterEnvForSubprocess(env)
    const auth = await Auth.all().catch(() => ({}) as Record<string, Auth.Info>)
    // Prepend the bundled atlas CLI to PATH so the agent's native `atlas`
    // commands resolve without a separate global install.
    return withAtlasOnPath(mergeByokEnv(base, auth))
  }

  // Default thread/worker caps for scientific Python kernels. Without these,
  // BLAS (OpenBLAS/MKL/Accelerate), numba, and joblib/loky each fan out to one
  // worker PER CORE by default. On a large dataset a single densifying op (e.g.
  // scanpy regress_out with n_jobs=-1) then spawns N full-dataset copies at once,
  // each tens of GB — the machine swaps to death (#102). Cap each to a small,
  // safe default and only fill a var the user/agent hasn't already set, so an
  // explicit override still wins.
  export function pythonThreadCapEnv(env: NodeJS.ProcessEnv = process.env): Record<string, string> {
    const cap = String(Math.max(1, Math.min(4, os.cpus().length)))
    const vars = [
      "OMP_NUM_THREADS",
      "OPENBLAS_NUM_THREADS",
      "MKL_NUM_THREADS",
      "VECLIB_MAXIMUM_THREADS",
      "NUMEXPR_NUM_THREADS",
      "NUMBA_NUM_THREADS",
      "LOKY_MAX_CPU_COUNT",
    ]
    return Object.fromEntries(vars.filter((v) => !env[v]).map((v) => [v, cap]))
  }

  /** Credit balance cache */
  let cachedBalance: { value: number; at: number } | null = null
  const BALANCE_CACHE_TTL = 30 * 1000

  /** Drop the cached balance so the next getBalance() refetches. Called when
   *  the wallet gate blocks, so a top-up is visible on the next attempt
   *  instead of after the cache TTL. */
  export function invalidateBalance() {
    return
  }

  /** Get current credit balance (cached for 30s).
   *  Returns the balance in USD, or null when it can't be determined (no
   *  session, API failure). null is distinct from a real negative balance —
   *  the old -1 sentinel collided with an overdraft of exactly -$1. */
  export async function getBalance(): Promise<number | null> {
    return null
  }

  /** Invalidate balance cache (call after usage report) */
  export function invalidateBalanceCache() {
    return
  }

  type UsageParams = {
    service: string
    event_type: string
    model?: string
    tokens_used: number
    metadata?: Record<string, unknown>
  }

  const pendingQueuePath = path.join(Global.Path.data, "usage-queue.jsonl")

  /** Stable per-account tag stored with a queued usage row so a later flush can't
   *  bill a DIFFERENT account for it. user_id when known, else a short hash of the
   *  api_key (never the raw key, which must not sit in the queue file). */
  function accountTag(session: OpenScienceSession): string {
    if (session.user_id) return session.user_id
    return "k:" + createHash("sha256").update(session.api_key).digest("hex").slice(0, 16)
  }

  /** Whether a queued row tagged `rowAccount` may be flushed under `currentAccount`.
   *  A row with no tag is legacy/accountless → best-effort send under the current
   *  account; a row tagged for a DIFFERENT account is never sent (kept until that
   *  account is active). Pure + exported for tests. */
  export function shouldFlushForAccount(rowAccount: string | undefined, currentAccount: string): boolean {
    return false
  }

  async function persistToQueue(params: UsageParams, account?: string) {
    try {
      // Serialize against flushPendingUsage so an append can't land between
      // the flusher's read and its final rewrite (which would delete it).
      using _ = await Lock.write(pendingQueuePath)
      const row = account ? { ...params, __account: account } : params
      await fs.appendFile(pendingQueuePath, JSON.stringify(row) + "\n")
      log.info("usage queued for retry", { service: params.service })
    } catch (e) {
      log.warn("failed to persist usage to queue", { error: e instanceof Error ? e.message : String(e) })
    }
  }

  // (Acá vivía sendReport(): el POST de uso a /api/cli/usage del backend del
  // fabricante. Salió con la contabilidad de la billetera ajena.)

  /** Report service usage for billing (called after training jobs complete).
   *  On transient failure, persists to a local queue for retry on next startup. */
  export async function reportUsage(
    params: UsageParams,
  ): Promise<{ recorded: boolean; event_id?: string; estimated_cost_usd?: number; modelBlocked?: boolean } | null> {
    return null
  }

  /** Retry any queued usage reports from previous failures (called at startup).
   *  Holds the queue lock across the whole read → send → rewrite cycle so a
   *  concurrent flush in this process can't double-send, and the rewrite
   *  drops only the lines actually read so an append landing mid-flush
   *  survives. Best-effort: never throws. */
  export async function flushPendingUsage(): Promise<void> {
    return
  }

  // Legacy skill exports are read exactly once by SkillMigration after a
  // successful Atlas login. Skills are otherwise entirely local.
  export interface LegacyLearnedSkillEntry {
    name: string
    description: string
    agent?: string
    score?: number
  }

  export async function fetchLegacyLearnedSkills(): Promise<LegacyLearnedSkillEntry[] | null> {
    return null
  }

  export async function fetchLegacyLearnedSkillContent(name: string): Promise<string | null> {
    return null
  }

  // === Devices ===

  export interface DeviceInfo {
    key_id: string
    name: string
    key_prefix: string
    created_at: string
    last_used_at: string | null
    expires_at: string | null
  }

  /** List authenticated devices for the current user. */
  export async function listDevices(): Promise<DeviceInfo[] | null> {
    return null
  }

  /** Revoke a device (its api_key is revoked server-side). */
  export async function revokeDevice(keyId: string): Promise<boolean> {
    return false
  }

  // === Wallet / credits ===

  export interface Credits {
    balanceUsd: number
    balanceCents: number
    /** @deprecated Use balanceCents. */
    cliBalanceCents: number
    cycleCreditsRemainingCents: number
    lifetimeSpentCents: number
  }

  /** Resolve the canonical wallet while accepting older Atlas responses. */
  export function walletCents(d: {
    cli_balance_cents?: number
    unified_balance_cents?: number
    balance_cents?: number
  }): number {
    return d.balance_cents ?? d.cli_balance_cents ?? d.unified_balance_cents ?? 0
  }

  export async function getCredits(): Promise<Credits | null> {
    return null
  }

  export interface Transaction {
    id: string
    amountCents: number
    source: string
    description: string
    createdAt: string
  }

  export async function getTransactions(limit = 20): Promise<Transaction[] | null> {
    return null
  }

  /** Version of the bundled @synsci/atlas companion CLI, or null if unresolved. */
  export async function atlasCliVersion(): Promise<string | null> {
    return null
  }

  // === Billing mode (BYOK ↔ managed) ===

  export interface BillingMode {
    mode: "byok" | "managed"
    balance_cents: number
    balance_usd: number
    managed_supported: boolean
  }

  export async function getBillingMode(): Promise<BillingMode | null> {
    return null
  }

  export async function setBillingMode(mode: "byok" | "managed"): Promise<BillingMode | null> {
    return null
  }

  export interface LegacyInstalledSkillEntry {
    id: string
    namespace: string
    name: string
    description: string
    repo_url: string
    pinned_sha: string
    review_verdict: string
    review_meta: string | null
    installed_at: string
  }

  export async function fetchLegacyInstalledSkills(): Promise<LegacyInstalledSkillEntry[] | null> {
    return null
  }
}
