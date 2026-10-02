/** Local-only replacement for the removed OpenWork control-plane synchronizer. */
export class CloudProviderSync {
  constructor(_input: unknown) {}
  setSession(_session: unknown): void {
    throw new Error("Managed cloud provider sessions are disabled in Aleph Office");
  }
  async clearSession(): Promise<void> {}
  async run(_reason?: string): Promise<{ enabled: false; reason: string }> {
    return { enabled: false, reason: "Managed cloud provider sync is disabled" };
  }
  status(): { enabled: false; reason: string } {
    return { enabled: false, reason: "Managed cloud provider sync is disabled" };
  }
  markReloadPending(): void {}
  /** [Aleph] Faltaba en el stub y `server.ts` la llama dos veces: en el `catch` del arranque
   *  y en el `stop()` del servidor, o sea en los dos caminos de apagado. Sin ella el
   *  typecheck del server no pasaba («Property 'stop' does not exist on type
   *  CloudProviderSync»). No hay nada que detener —el sincronizador de la nube fue
   *  amputado—, pero el apagado tiene que poder llamarla sin saber eso. */
  stop(): void {}
}

export function parseCloudProviderDenSession(_input: unknown): null {
  return null;
}
