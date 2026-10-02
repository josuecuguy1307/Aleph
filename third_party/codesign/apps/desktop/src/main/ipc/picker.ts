import { stat } from 'node:fs/promises';
import { basename } from 'node:path';
import type { BrowserWindow as ElectronBrowserWindow } from 'electron';
import { scanDesignSystem } from '../design-system';
import { dialog, ipcMain } from '../electron-runtime';
import { getLogger } from '../logger';
import { getOnboardingState, setDesignSystem } from '../onboarding-ipc';

export function registerPickerIpc(getMainWindow: () => ElectronBrowserWindow | null): void {
  const logIpc = getLogger('main:ipc');

  ipcMain.handle('codesign:pick-input-files', async () => {
    const win = getMainWindow();
    const result = win
      ? await dialog.showOpenDialog(win, {
          properties: ['openFile', 'multiSelections'],
        })
      : await dialog.showOpenDialog({
          properties: ['openFile', 'multiSelections'],
        });
    if (result.canceled || result.filePaths.length === 0) return [];
    return Promise.all(
      result.filePaths.map(async (path) => {
        try {
          const info = await stat(path);
          return { path, name: basename(path), size: info.size };
        } catch {
          return { path, name: basename(path), size: 0 };
        }
      }),
    );
  });

  ipcMain.handle('codesign:pick-design-system-directory', async () => {
    const win = getMainWindow();
    const result = win
      ? await dialog.showOpenDialog(win, { properties: ['openDirectory'] })
      : await dialog.showOpenDialog({ properties: ['openDirectory'] });
    if (result.canceled || result.filePaths.length === 0) return getOnboardingState();
    const rootPath = result.filePaths[0];
    if (!rootPath) return getOnboardingState();
    logIpc.info('designSystem.scan.start', { rootPath });
    const snapshot = await scanDesignSystem(rootPath);
    const nextState = await setDesignSystem(snapshot);
    logIpc.info('designSystem.scan.ok', {
      rootPath,
      sourceFiles: snapshot.sourceFiles.length,
      colors: snapshot.colors.length,
      fonts: snapshot.fonts.length,
    });
    return nextState;
  });

  ipcMain.handle('codesign:clear-design-system', async () => {
    const nextState = await setDesignSystem(null);
    logIpc.info('designSystem.clear');
    return nextState;
  });
}
