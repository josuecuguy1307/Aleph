/**
 * Aleph Oficina keeps the OpenWork plugin module addressable for the upstream
 * test surface, but does not register the proprietary remote catalogue.
 */
export async function OpenWorkExtensionsPreview() {
  return { tool: {} };
}
