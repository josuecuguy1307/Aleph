/**
 * Aleph Office deliberately has no managed-provider account.  Credentials are
 * supplied only by Aleph's per-user broker to the process that needs them.
 */
export function resetManagedProviderAuthCache(): void {}

export async function syncManagedProviderAuth(_input: unknown): Promise<void> {}
