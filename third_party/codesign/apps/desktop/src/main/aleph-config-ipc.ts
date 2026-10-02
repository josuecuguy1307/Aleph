/** Configuración de Diseño administrada por Aleph: se lee, no se edita aquí. */
import { ipcMain } from './electron-runtime';
import { getCachedConfig, toState } from './onboarding/config-cache';

export function registerAlephConfigIpc(): void {
  ipcMain.handle('onboarding:get-state', () => toState(getCachedConfig()));
}
