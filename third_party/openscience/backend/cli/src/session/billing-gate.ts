/**
 * EXTIRPADO — el gate de facturación del proyecto de origen.
 *
 * La versión importada clasificaba cada llamada en "managed" (token `thk_*` del
 * proxy Atlas o secreto sincronizado desde el dashboard del fabricante), "byok" o
 * "oauth-free", y de esa clasificación colgaban tres decisiones: si hacía falta
 * saldo en la billetera prepaga, si el uso se reportaba al backend del fabricante,
 * y si la sesión se bloqueaba por créditos agotados.
 *
 * Aleph no tiene billetera ajena que debitar ni backend al que reportar: el cerebro
 * es propio (Ley 0). Así que no queda nada que clasificar — todo es BYOK y nada es
 * facturable. Se conserva la superficie exportada porque `session/processor.ts` y
 * `session/prompt.ts` la consultan en su camino caliente; abrirles el cuerpo para
 * borrar seis llamadas sería refactor, y la importación no refactoriza (Ley 5).
 */

export type CredentialSource = "byok" | "managed" | "oauth-free"
export type BillingMode = "managed" | "byok"

/** Sin modo gestionado no hay preferencia de facturación que leer. */
export async function llmBillingMode(): Promise<BillingMode | undefined> {
  return undefined
}

/** Siempre BYOK: la credencial es del dueño, no de un proxy alquilado. */
export async function computeBillingMode(): Promise<BillingMode> {
  return "byok"
}

/** El proveedor sintetizado de Codex salió con su camino; ya no existe. */
export function isCodexOAuthProvider(_providerID: string): boolean {
  return false
}

/** Toda credencial que llegue hasta acá es del dueño. */
export async function resolveCredentialSource(_providerID: string, _modelID: string): Promise<CredentialSource> {
  return "byok"
}

/** No hay billetera prepaga: ninguna llamada exige saldo. */
export function requiresWalletBalance(_source: CredentialSource): boolean {
  return false
}

/** No hay backend al que reportarle uso. */
export function shouldReportUsage(_source: CredentialSource): boolean {
  return false
}
