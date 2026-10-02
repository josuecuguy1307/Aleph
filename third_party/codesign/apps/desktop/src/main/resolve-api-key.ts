import { CodesignError, ERROR_CODES } from '@open-codesign/shared';

/**
 * Abstract dependencies of `resolveActiveApiKey` so unit tests can stub the
 * codex token store and the onboarding API-key reader without pulling in the
 * full main-process singleton graph (electron, logger, local storage, ...).
 */
export interface ResolveActiveApiKeyDeps {
  /** Returns the stored API key for the given provider. Throws when missing. */
  getApiKeyForProvider: (providerId: string) => string;
}

export interface ResolveCredentialForProviderDeps extends ResolveActiveApiKeyDeps {
  /** True when config has a persisted secret row for this provider. */
  hasApiKeyForProvider: (providerId: string) => boolean;
}

/**
 * Resolve the bearer credential for the active provider.
 *
 * Reads the stored API key and propagates any
 * underlying error as a `CodesignError(PROVIDER_AUTH_MISSING)` with the
 * original attached as `cause`. Keyless endpoints are handled by
 * `resolveCredentialForProvider`; this helper never suppresses a failure.
 */
export async function resolveActiveApiKey(
  providerId: string,
  deps: ResolveActiveApiKeyDeps,
): Promise<string> {
  try {
    return deps.getApiKeyForProvider(providerId);
  } catch (err) {
    if (err instanceof CodesignError) throw err;
    throw new CodesignError(
      err instanceof Error ? err.message : `Failed to read API key for provider "${providerId}"`,
      ERROR_CODES.PROVIDER_AUTH_MISSING,
      { cause: err },
    );
  }
}

/**
 * Resolve the bearer credential for an IPC handler.
 *
 * Keyless mode is explicit: providers with `requiresApiKey: false` may run
 * with an empty bearer only when there is no persisted secret row. If a secret
 * row exists, read it so keychain/plaintext corruption still surfaces.
 */
export async function resolveCredentialForProvider(
  providerId: string,
  allowKeyless: boolean,
  deps: ResolveCredentialForProviderDeps,
): Promise<string> {
  if (allowKeyless && !deps.hasApiKeyForProvider(providerId)) {
    return '';
  }
  return resolveActiveApiKey(providerId, deps);
}
