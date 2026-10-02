import { mkdir } from 'node:fs/promises';
import path_module from 'node:path';
import { CodesignError } from '@open-codesign/shared';
import { app, ipcMain, shell } from '../electron-runtime';
import { getLogPath } from '../logger';
import { isAllowedExternalUrl } from '../open-external';

export function registerShellIpc(): void {
  ipcMain.handle('codesign:open-log-folder', async () => {
    await shell.openPath(getLogPath());
  });

  ipcMain.handle('codesign:v1:open-templates-folder', async () => {
    const dir = path_module.join(app.getPath('userData'), 'templates');
    await mkdir(dir, { recursive: true });
    await shell.openPath(dir);
  });

  ipcMain.handle('codesign:v1:open-external', async (_e, url: unknown) => {
    if (typeof url !== 'string') {
      throw new CodesignError('codesign:v1:open-external requires a string url', 'IPC_BAD_INPUT');
    }
    if (!isAllowedExternalUrl(url)) {
      throw new CodesignError('URL not allowed', 'IPC_BAD_INPUT');
    }
    await shell.openExternal(url);
  });
}
