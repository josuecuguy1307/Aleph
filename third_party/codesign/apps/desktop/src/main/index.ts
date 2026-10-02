import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { BRAND } from '@open-codesign/shared';
import type { BrowserWindow as ElectronBrowserWindow } from 'electron';
import { registerAppMenu } from './app-menu';
import { registerAlephConfigIpc } from './aleph-config-ipc';
import { registerAskIpc } from './ask-ipc';
import { showBootDialog, writeBootErrorSync } from './boot-fallback';
import { configDir } from './config';
import { registerDiagnosticsIpc } from './diagnostics-ipc';
import { app, BrowserWindow, clipboard, dialog, shell } from './electron-runtime';
import { ensureUserTemplates, resolveBundledTemplatesDir } from './ensure-user-templates';
import { registerExporterIpc } from './exporter-ipc';
import {
  createHeadlessWindow,
  installHeadlessIpcCapture,
  startHeadlessBridge,
} from './headless-bridge';
import { maybeAbortIfRunningFromDmg } from './install-check';
import { registerIpcHandlers } from './ipc/register';
import { registerLocaleIpc } from './locale-ipc';
import { getLogger, initLogger } from './logger';
import { isTrustedMainWindowNavigationUrl } from './navigation-policy';
import { loadConfigOnBoot } from './onboarding/config-cache';
import { isAllowedExternalUrl } from './open-external';
import {
  applyProxyConfig,
  readPersisted as readPreferences,
  registerPreferencesIpc,
} from './preferences-ipc';
import { cleanupStaleTmps } from './reported-fingerprints';
import { type Database, getDesign, pruneDiagnosticEvents, safeInitSnapshotsDb } from './snapshots-db';
import {
  registerSnapshotsIpc,
  registerSnapshotsUnavailableIpc,
  registerWorkspaceIpc,
} from './snapshots-ipc';
import { initStorageSettings } from './storage-settings';
import { registerWorkspaceProtocolHandler, registerWorkspaceScheme } from './workspace-protocol';

// Re-exports kept for index.workspace.test.ts and any external callers.
export { createRuntimeTextEditorFs, resolveLocalAssetRefs } from './ipc/runtime-fs';

// ESM shim: package.json "type": "module" means the built bundle is ESM and
// __dirname/__filename don't exist. Derive them from import.meta.url so the
// existing join(__dirname, '../preload/...') calls keep working.
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

let mainWindow: ElectronBrowserWindow | null = null;
const getMainWindow = (): ElectronBrowserWindow | null => mainWindow;

const IS_VITEST = process.env['VITEST'] === 'true';
const IS_SMOKE_TEST =
  process.argv.includes('--smoke-test') || process.env['CODESIGN_SMOKE_TEST'] === '1';
const IS_ALEPH_HEADLESS = process.argv.includes('--aleph-headless');
const headlessPortArgument = process.argv.find((arg) => arg.startsWith('--aleph-port='));
const ALEPH_HEADLESS_PORT = headlessPortArgument
  ? Number.parseInt(headlessPortArgument.slice('--aleph-port='.length), 10)
  : Number.NaN;
if (IS_ALEPH_HEADLESS) installHeadlessIpcCapture();
const smokeUserDataDir = process.env['CODESIGN_SMOKE_USER_DATA_DIR'];
if (IS_SMOKE_TEST && smokeUserDataDir !== undefined && smokeUserDataDir.trim().length > 0) {
  mkdirSync(smokeUserDataDir, { recursive: true });
  app.setPath('userData', smokeUserDataDir);
}

const defaultUserDataDir = app.getPath('userData');
const storageLocations = initStorageSettings(defaultUserDataDir);
if (storageLocations.dataDir !== undefined) {
  mkdirSync(storageLocations.dataDir, { recursive: true });
  app.setPath('userData', storageLocations.dataDir);
}

type NavigationEvent = { preventDefault: () => void };

function handleMainWindowNavigation(
  event: NavigationEvent,
  url: string,
  trustedAppUrl: string,
): void {
  if (isTrustedMainWindowNavigationUrl(url, trustedAppUrl)) return;

  event.preventDefault();
}

function createWindow(): void {
  const rendererEntryPath = join(__dirname, '../renderer/index.html');
  const rendererUrlOverride = process.env['ELECTRON_RENDERER_URL'];
  const rendererEntryUrl = rendererUrlOverride || pathToFileURL(rendererEntryPath).href;

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    autoHideMenuBar: process.platform !== 'darwin',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: BRAND.backgroundColor,
    icon: join(__dirname, '../../resources/icon.png'),
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on('ready-to-show', () => mainWindow?.show());
  // Null the reference on close so stale IPC sends from async emitters
  // (autoUpdater, long-running generate runs) become clean no-ops rather
  // than throwing "Object has been destroyed" on a discarded webContents.
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }: { url: string }) => {
    // Gate `window.open(...)` through the same allowlist as
    // `codesign:v1:open-external`, otherwise any renderer path that triggers
    // a new-window event could coerce the main process into opening an
    // attacker-controlled URL.
    if (isAllowedExternalUrl(url)) {
      void shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event: NavigationEvent, url: string) => {
    handleMainWindowNavigation(event, url, rendererEntryUrl);
  });

  mainWindow.webContents.on(
    'will-redirect',
    (event: NavigationEvent, url: string, _isInPlace: boolean, isMainFrame: boolean) => {
      if (isMainFrame) handleMainWindowNavigation(event, url, rendererEntryUrl);
    },
  );

  if (rendererUrlOverride) {
    void mainWindow.loadURL(rendererEntryUrl);
  } else {
    void mainWindow.loadFile(rendererEntryPath);
  }
}

if (!IS_VITEST) {
  registerWorkspaceScheme();

  void app.whenReady().then(async () => {
    // Extracted so the outer try/catch AND post-init listeners (whose callbacks
    // fire outside this block) can route failures through the same boot-fallback
    // path. Without this, a later createWindow() throw from app.on('activate')
    // would bypass writeBootErrorSync and leave the user with nothing to attach.
    const handleBootFailure = (err: unknown, title: string, message: string): void => {
      let logsDir: string;
      try {
        logsDir = app.getPath('logs');
      } catch {
        logsDir = app.getPath('temp');
      }
      const bootLogPath = writeBootErrorSync({
        error: err,
        logsDir,
        appVersion: app.getVersion(),
        platform: process.platform,
        electronVersion: process.versions.electron ?? 'unknown',
        nodeVersion: process.versions.node,
      });
      const choice = showBootDialog(app, dialog, {
        type: 'error',
        title,
        message,
        detail: `Error: ${err instanceof Error ? err.message : String(err)}\n\nDiagnostic log: ${bootLogPath}`,
        buttons: ['Copy diagnostic path', 'Open log folder', 'Quit'],
        defaultId: 2,
        cancelId: 2,
      });
      if (choice === 0) clipboard.writeText(bootLogPath);
      if (choice === 1) shell.showItemInFolder(bootLogPath);
    };

    try {
      initLogger();
      // Single-instance lock. Two simultaneous Electron instances would race
      // `cleanupStaleTmps` vs `writeAtomic` (B's cleanup unlinks A's in-flight
      // tmp → ENOENT rename) and collide on local JSON writes. macOS usually
      // enforces this at the OS level, but `open -n` defeats that — so we
      // acquire the lock explicitly before touching any shared files.
      const gotLock = app.requestSingleInstanceLock();
      if (!gotLock) {
        app.quit();
        return;
      }
      app.on('second-instance', () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.focus();
        }
      });
      // Show a blocking dialog if the user launched from the DMG mount. If
      // they accept the remedy, we quit here before touching safeStorage / the
      // snapshots DB so nothing half-initialises against a bad install.
      const aborted = await maybeAbortIfRunningFromDmg();
      if (aborted) return;
      await loadConfigOnBoot();
      // Apply any user-configured outbound proxy to Chromium + Node before
      // anything reaches out to provider endpoints or the update feed.
      try {
        const prefs = await readPreferences();
        await applyProxyConfig(prefs.proxyUrl);
      } catch (err) {
        getLogger('main:boot').warn('preferences.proxy.apply.boot.fail', {
          message: err instanceof Error ? err.message : String(err),
        });
      }
      // Seed `<userData>/templates/` from the bundled resources if it does
      // not already exist. After the first boot the user owns the tree —
      // edits to scaffolds, skills, brand-refs, frames, or design-skills
      // survive upgrades, and deleting the folder re-seeds on next launch.
      const bootLog = getLogger('main:boot');
      const templatesSource = resolveBundledTemplatesDir(process.resourcesPath);
      const seeded = await ensureUserTemplates(app.getPath('userData'), templatesSource);
      bootLog.info('templates.ensure', { ...seeded });
      // Best-effort sweep of leftover `<file>.tmp.<pid>` siblings from previous
      // crashes. pid changes across restarts so without this the config dir
      // accumulates 0o600 litter forever.
      cleanupStaleTmps(join(configDir(), 'reported-fingerprints.json'));
      // Design metadata persistence is best-effort at boot — a failure here
      // (corrupt JSON, permission denied) must NOT block the BrowserWindow
      // from opening. Surface it via an error dialog and skip registering the
      // snapshots IPC channels; the rest of the app stays usable.
      const bridgeWindow = IS_ALEPH_HEADLESS ? createHeadlessWindow() : null;
      const getBridgeWindow = (() => bridgeWindow ?? getMainWindow) as unknown as () =>
        ElectronBrowserWindow | null;
      const dbResult = safeInitSnapshotsDb(join(app.getPath('userData'), 'design-store.json'));
      const diagnosticsDb: Database | null = dbResult.ok ? dbResult.db : null;
      if (dbResult.ok) {
        registerSnapshotsIpc(dbResult.db);
        registerWorkspaceIpc(dbResult.db, getBridgeWindow);
        registerWorkspaceProtocolHandler({
          db: dbResult.db,
          logger: getLogger('workspace-protocol'),
        });
        try {
          pruneDiagnosticEvents(dbResult.db, 500);
        } catch (err) {
          getLogger('main:boot').warn('diagnosticEvents.prune.fail', {
            message: err instanceof Error ? err.message : String(err),
          });
        }
      } else {
        bootLog.error('snapshotsDb.init.fail', {
          message: dbResult.error.message,
          stack: dbResult.error.stack,
        });
        if (IS_SMOKE_TEST) throw dbResult.error;
        // Install stub handlers so renderer-side calls reject with a typed
        // SNAPSHOTS_UNAVAILABLE CodesignError instead of Electron's opaque
        // "No handler registered" rejection — see snapshots-ipc.ts.
        registerSnapshotsUnavailableIpc(dbResult.error.message);
        dialog.showErrorBox(
          'Design history unavailable',
          `Could not open the local design store. Version history will be disabled for this session.\n\n${dbResult.error.message}`,
        );
      }
      const teardownIpc = registerIpcHandlers(diagnosticsDb, getBridgeWindow);
      app.on('before-quit', teardownIpc);
      registerLocaleIpc();
      registerAlephConfigIpc();
      registerPreferencesIpc();
      // Export dialogs have no parent in webview mode; Electron's main process still owns
      // the filesystem/export implementation, but never opens an application window.
      registerExporterIpc(IS_ALEPH_HEADLESS ? getMainWindow : getMainWindow, diagnosticsDb);
      registerDiagnosticsIpc(diagnosticsDb);
      registerAskIpc();
      if (IS_SMOKE_TEST) {
        bootLog.info('smoke.ok', { arch: process.arch, platform: process.platform });
        process.stdout.write(
          `codesign smoke.ok arch=${process.arch} platform=${process.platform}\n`,
        );
        app.quit();
        return;
      }
      if (IS_ALEPH_HEADLESS) {
        if (!Number.isInteger(ALEPH_HEADLESS_PORT) || ALEPH_HEADLESS_PORT < 1) {
          throw new Error('--aleph-headless requires a valid --aleph-port');
        }
        // [Aleph] FUERA DEL DOCK Y DE cmd-Tab.
        //
        // En este modo no se crea ninguna ventana —la superficie es la webview de Aleph—,
        // pero el proceso sigue siendo una app de macOS: aparecía su ícono en el Dock, como
        // si Diseño fuera un programa aparte que el usuario puede traer al frente. No lo es:
        // acá es el MOTOR de un workspace, y su cara vive dentro de Aleph.
        //
        // Los otros workspaces no tienen este problema porque son servidores (Bun, Node,
        // Python) y macOS no los registra como aplicaciones. Diseño corre sobre Electron,
        // que es un navegador empaquetado COMO app de escritorio, así que hay que pedirle
        // explícitamente que se comporte como proceso de fondo. `app.dock.hide()` es la API
        // de Electron para eso —la misma que usan las utilidades de la barra de menús—, no
        // un truco: sin ventana y sin dock, el proceso deja de anunciarse como aplicación.
        // `dock` sólo existe en macOS, de ahí el opcional.
        app.dock?.hide();
        // [Aleph] FUERA DEL DOCK. En este modo no se crea ninguna ventana —la superficie es
        // la webview de Aleph—, pero el proceso sigue siendo una app de macOS: aparecía su
        // ícono en el Dock y en cmd-Tab, como si Diseño fuera un programa aparte que el
        // usuario puede traer al frente. No lo es: acá es el motor de un workspace, y su
        // cara vive dentro de Aleph. `dock` sólo existe en macOS, de ahí el opcional.
        app.dock?.hide();
        const server = startHeadlessBridge({
          port: ALEPH_HEADLESS_PORT,
          rendererRoot: join(__dirname, '../renderer'),
          webContents: bridgeWindow!.webContents,
          resolveWorkspacePath: (designId) => diagnosticsDb ? getDesign(diagnosticsDb, designId)?.workspacePath ?? null : null,
        });
        app.on('before-quit', () => server.close());
        return;
      }
      registerAppMenu();
      createWindow();

      app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
          try {
            createWindow();
          } catch (err) {
            handleBootFailure(err, 'Cannot reopen window', 'Window failed to open.');
          }
        }
      });
    } catch (err) {
      if (IS_SMOKE_TEST) {
        process.stderr.write(
          `codesign smoke.fail ${err instanceof Error ? err.stack || err.message : String(err)}\n`,
        );
        app.exit(1);
        return;
      }
      // Last-resort boot-phase handler. Reached when something before
      // `initLogger()` finishes (or during the first few setup calls)
      // throws — our electron-log sink might not exist yet, so write a
      // best-effort sync log and show a native three-button dialog.
      handleBootFailure(
        err,
        'Diseño no pudo iniciar',
        'A startup error prevented the app from loading.',
      );
      app.quit();
    }
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
}
