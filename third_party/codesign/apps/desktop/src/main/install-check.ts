import { app, dialog, shell } from './electron-runtime';
import { getLogger } from './logger';

/**
 * Installation sanity checks that run before anything else at boot.
 *
 * The main case we care about: on macOS, users frequently double-click the
 * app icon inside the mounted DMG instead of dragging it to /Applications
 * first. That launches the binary from `/Volumes/Open CoDesign/...` — a
 * read-only mount whose identity Electron can't use to establish a stable
 * keychain entry, so `safeStorage.isEncryptionAvailable()` returns false
 * and every "save API key" / "decrypt API key" path fails hard.
 *
 * Rather than let the user hit that wall minutes later with a cryptic
 * error, we detect the condition at startup and offer a one-click fix:
 * open the Applications folder, quit, and let them drag-install properly.
 */

const log = getLogger('install-check');

function isRunningFromDmgMount(): boolean {
  if (process.platform !== 'darwin') return false;
  // Apps launched from a mounted DMG always have an exec path somewhere
  // under /Volumes/. Apps dragged to /Applications live under
  // /Applications/... and never match. Dev builds from pnpm run from
  // node_modules/electron/dist and also don't match.
  return process.execPath.startsWith('/Volumes/');
}

/**
 * If the app is running from a DMG mount, show an explanatory dialog.
 * When the user clicks the primary action we open Finder at the
 * Applications folder and quit the app — they can then drag the app
 * across and relaunch from the correct location.
 *
 * Returns true when the app should stop booting (user chose to quit),
 * false to continue normally.
 */
export async function maybeAbortIfRunningFromDmg(): Promise<boolean> {
  if (!isRunningFromDmgMount()) return false;
  log.warn('boot.blocked', { reason: 'running_from_dmg', execPath: process.execPath });

  const { response } = await dialog.showMessageBox({
    type: 'warning',
    title: 'Open CoDesign 还没安装完成',
    message: '请先把 Open CoDesign 拖到「应用程序」文件夹',
    detail: [
      '当前是从 DMG 直接运行的。这样 macOS 无法为 Open CoDesign 建立钥匙串条目，',
      '你的 API key 会无法加密保存，导入配置也会失败。',
      '',
      '正确步骤：',
      '1. 点下面的「打开「应用程序」文件夹」',
      '2. 把 Finder 里的 Open CoDesign.app 拖进去',
      '3. 从「应用程序」文件夹双击启动',
      '',
      '首次从「应用程序」启动时 macOS 会弹「来自网络的 app」确认框，点「打开」即可。',
    ].join('\n'),
    buttons: ['打开「应用程序」文件夹并退出', '仍要从 DMG 运行（不推荐）'],
    defaultId: 0,
    cancelId: 1,
  });

  if (response === 0) {
    try {
      await shell.openPath('/Applications');
    } catch (err) {
      log.warn('openPath.applications.fail', {
        message: err instanceof Error ? err.message : String(err),
      });
    }
    app.quit();
    return true;
  }

  log.warn('boot.continued_from_dmg_despite_warning');
  return false;
}
