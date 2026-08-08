/**
 * Electron Main Process
 * Spawns the Python FastAPI backend and creates the app window.
 */

const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const { autoUpdater } = require('electron-updater');
const crypto = require('crypto');
const { pathToFileURL } = require('url');
const { isAllowedNavigation } = require('./navigation.cjs');

// Per-session shared secret between the renderer and the Python backend.
// Passed to the backend via env and handed to the renderer over IPC (NOT via
// additionalArguments, which would expose it in `ps` output on a shared machine).
const API_TOKEN = crypto.randomBytes(32).toString('hex');

const BACKEND_PORT = 8765;
const DEV_SERVER = `http://localhost:5173`;
const isDev = !app.isPackaged;

// How often to re-check for updates while the app stays open (24 hours).
const DAILY_UPDATE_CHECK_MS = 24 * 60 * 60 * 1000;

let backendProcess = null;
let mainWindow = null;
let updateCheckInterval = null;
// Set once the health check has passed and the window is being created. Before
// that, a backend exit is a STARTUP failure and is reported by waitForBackend
// with a more useful message than the generic "engine stopped" dialog.
let backendReady = false;
// Why our own backend died during startup, if it did.
let backendFailure = null;

const PORT_IN_USE_MESSAGE =
  'Another copy of the redaction engine is already running on this computer.\n\n' +
  'Close any other copy of this app and try again. If you have just force-quit ' +
  'the app, restarting your computer will clear it.';

/** Wait for the backend to respond on its port (30-second wall-clock timeout). */
function waitForBackend(port, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const check = () => {
      // Our backend dying is terminal, and a healthy port does NOT prove
      // otherwise: an orphaned backend from a force-quit, or a second copy of
      // the app, answers on the same port with a DIFFERENT api token. Trusting
      // that check would open a window whose every request 401s.
      if (backendFailure) {
        reject(new Error(backendFailure));
        return;
      }
      if (Date.now() > deadline) {
        reject(new Error('Backend did not start within 30 seconds'));
        return;
      }
      // `settled` stops one request from scheduling two follow-up polls when
      // destroy() also emits 'error' — otherwise the poll loop forks on itself.
      let settled = false;
      const retry = () => {
        if (settled) return;
        settled = true;
        setTimeout(check, 500);
      };

      const req = http.get(
        {
          host: '127.0.0.1',
          port,
          path: '/api/health',
          // Proves identity, not permission: /api/health is unauthenticated,
          // and answers instance_match=false rather than 401 on a mismatch.
          headers: { 'X-Api-Token': API_TOKEN },
        },
        (res) => {
          if (res.statusCode !== 200) {
            res.resume();
            retry();
            return;
          }
          let body = '';
          res.setEncoding('utf8');
          res.on('data', (chunk) => { body += chunk; });
          res.on('end', () => {
            let ours = false;
            try {
              // Absent field = an older backend; treat as not ours rather than
              // assume, since assuming is the bug this exists to fix.
              ours = JSON.parse(body).instance_match === true;
            } catch {
              ours = false;
            }
            if (settled) return;
            if (ours) {
              settled = true;
              resolve();
            } else {
              // Someone else is on our port. Keep polling: our own backend is
              // about to exit on "address already in use", and that sets
              // backendFailure, which the next tick reports properly.
              retry();
            }
          });
          res.on('error', retry);
        },
      );
      req.on('error', retry);
      req.setTimeout(1000, () => { req.destroy(); retry(); });
      req.end();
    };

    check();
  });
}

/** Show a native error dialog and quit. */
function showErrorWindow(title, message) {
  dialog.showErrorBox(title, message);
  app.quit();
}

/** Start the Python FastAPI backend. */
function startBackend() {
  const resourcesPath = isDev
    ? path.resolve(__dirname, '..', '..')   // repo root in dev
    : process.resourcesPath;

  const appRoot = isDev
    ? resourcesPath
    : path.join(resourcesPath, 'app');

  const isWin = process.platform === 'win32';

  // Find the Python executable (platform-aware)
  let pythonPath;
  if (isDev) {
    pythonPath = isWin
      ? path.join(appRoot, 'venv', 'Scripts', 'python.exe')
      : path.join(appRoot, 'venv', 'bin', 'python3.13');
  } else {
    pythonPath = isWin
      ? path.join(resourcesPath, 'bundled-python', 'python.exe')
      : path.join(resourcesPath, 'bundled-python', 'bin', 'python3');
  }

  console.log(`Starting backend: ${pythonPath} -m uvicorn backend.main:app --port ${BACKEND_PORT}`);

  backendProcess = spawn(pythonPath, [
    '-m', 'uvicorn', 'backend.main:app',
    '--port', String(BACKEND_PORT),
    '--host', '127.0.0.1',
  ], {
    cwd: appRoot,
    env: {
      ...process.env,
      PYTHONPATH: path.join(appRoot, 'src', 'core'),
      RESOURCES_PATH: resourcesPath,
      TESSDATA_PREFIX: path.join(resourcesPath, 'bundled-tesseract', 'tessdata'),
      REDACTION_API_TOKEN: API_TOKEN,
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.on('exit', (code, signal) => {
    console.log(`Backend exited with code ${code}, signal ${signal}`);
    if (app.isQuitting) return;
    backendProcess = null;

    if (!backendReady) {
      // Died before we ever served a request. Overwhelmingly this is the port
      // already being held by an orphan or a second copy — uvicorn exits 1 on
      // "address already in use". Hand it to waitForBackend rather than racing
      // it with a second, vaguer dialog.
      backendFailure = PORT_IN_USE_MESSAGE;
      return;
    }

    // Crashed mid-session. The UI cannot recover without a restart.
    dialog.showErrorBox(
      'Redaction Engine Stopped',
      'The redaction engine stopped unexpectedly. The app will now close — please reopen it to continue.',
    );
    app.quit();
  });

  backendProcess.on('error', (err) => {
    // The process could not be spawned at all (bad path, permissions, etc.).
    console.error('Failed to spawn backend:', err);
    if (app.isQuitting) return;
    backendProcess = null;

    if (!backendReady) {
      backendFailure =
        `The redaction engine could not be started.\n\n${err.message}\n\nPlease reinstall the application.`;
      return;
    }

    dialog.showErrorBox(
      'Failed to Start',
      `The redaction engine could not be started.\n\n${err.message}\n\nPlease reinstall the application.`,
    );
    app.quit();
  });
}

/** Create the main application window. */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 900,
    minHeight: 600,
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset' } : {}),
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const indexPath = path.join(__dirname, '..', 'dist', 'index.html');
  const appUrl = isDev ? DEV_SERVER : pathToFileURL(indexPath).href;

  // Defence in depth. This window renders only its own content, so it has no
  // legitimate reason to open a second window or navigate anywhere else.
  // Denying both closes the entire class of popup/navigation escapes — the
  // class GHSA-9f4c-93c8-jc8g sits in — independently of the Electron version
  // underneath, which is what makes this worth having on its own.
  //
  // Deliberate external links are unaffected: they go through
  // shell.openExternal via the 'open-external' IPC handler. The page itself
  // never opens a window and never navigates.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    console.warn(`Blocked attempt to open a window: ${url}`);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    // Reloads (and dev-server reloads) resolve to the app's own URL.
    if (isAllowedNavigation(url, appUrl)) return;
    console.warn(`Blocked navigation to: ${url}`);
    event.preventDefault();
  });

  if (isDev) {
    mainWindow.loadURL(DEV_SERVER);
  } else {
    mainWindow.loadFile(indexPath);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Auto-updater ──────────────────────────────────────────────────────

function setupAutoUpdater() {
  // macOS auto-update requires a code-signed app AND a .zip artifact (Squirrel
  // cannot apply a .dmg). Until the Mac build is signed/notarised, attempting an
  // auto-download just fails — so on macOS we only DETECT updates and let the
  // user download manually. Windows (NSIS) auto-updates fine without signing.
  const canAutoUpdate = process.platform === 'win32';
  autoUpdater.autoDownload = canAutoUpdate;
  autoUpdater.autoInstallOnAppQuit = canAutoUpdate;

  autoUpdater.on('update-available', (info) => {
    console.log(`Update available: ${info.version}`);
    if (!mainWindow) return;
    if (canAutoUpdate) {
      mainWindow.webContents.send('update-available', info.version);
    } else {
      // Notify only — the renderer prompts a manual download.
      mainWindow.webContents.send('update-available-manual', info.version);
    }
  });

  autoUpdater.on('update-downloaded', () => {
    console.log('Update downloaded — will install on quit');
    if (mainWindow) {
      mainWindow.webContents.send('update-downloaded');
    }
  });

  autoUpdater.on('error', (err) => {
    console.error('Auto-updater error:', err.message);
    // Surface the failure to the UI so it never hangs on "Downloading…".
    if (mainWindow) {
      mainWindow.webContents.send('update-error', err.message);
    }
  });

  autoUpdater.on('update-not-available', () => {
    console.log('No update available');
    if (mainWindow) {
      mainWindow.webContents.send('update-not-available');
    }
  });

  autoUpdater.on('download-progress', (progress) => {
    if (mainWindow) {
      mainWindow.webContents.send('download-progress', Math.round(progress.percent));
    }
  });

  // NOTE: For updates to work, the GitHub repo must be public, or GH_TOKEN must be
  // set in the environment. See package.json "publish" config for repo details.
  // Check for updates after a short delay to avoid blocking startup...
  setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 10000);

  // ...then re-check once a day so a teacher who leaves the app open for days
  // still picks up new releases without restarting.
  updateCheckInterval = setInterval(
    () => autoUpdater.checkForUpdates().catch(() => {}),
    DAILY_UPDATE_CHECK_MS
  );
}

// ── IPC handlers ─────────────────────────────────────────────────────

ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Document Folder',
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle('select-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    title: 'Select Document',
    filters: [
      { name: 'Documents', extensions: ['pdf', 'doc', 'docx'] },
      { name: 'PDF', extensions: ['pdf'] },
      { name: 'Word', extensions: ['doc', 'docx'] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle('save-file-as', async (_event, defaultPath, kind) => {
  // De-identify mode writes plain text. A PDF-only filter here would rewrite
  // the .txt name the renderer suggested back to .pdf, contradicting the label
  // the user just read on screen.
  const isText = kind === 'txt';
  const result = await dialog.showSaveDialog(mainWindow, {
    title: isText ? 'Save De-identified Text As' : 'Save Redacted Document As',
    defaultPath: defaultPath || undefined,
    filters: isText
      ? [{ name: 'Text', extensions: ['txt'] }]
      : [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (result.canceled || !result.filePath) return null;
  return result.filePath;
});

ipcMain.handle('open-external', async (_event, url) => {
  await shell.openExternal(url);
});

ipcMain.handle('get-api-token', () => API_TOKEN);

ipcMain.handle('restart-and-install', () => {
  // isSilent=true, isForceRunAfter=true: install the update silently (no NSIS
  // wizard for the assisted oneClick:false installer) and relaunch the app
  // afterwards — a smooth, hands-off update for non-technical users (Windows).
  autoUpdater.quitAndInstall(true, true);
});

ipcMain.handle('check-for-updates', async () => {
  // In dev, autoUpdater is not set up — ignore silently
  if (isDev) return;
  await autoUpdater.checkForUpdates().catch(() => {});
});

ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.handle('log-error', async (_event, payload) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const logPath = path.join(app.getPath('userData'), 'error.log');
    const line = JSON.stringify({ ...payload, recordedAt: new Date().toISOString() }) + '\n';
    fs.appendFileSync(logPath, line, 'utf8');
  } catch (err) {
    console.error('Failed to write error log:', err);
  }
});

// ── App lifecycle ─────────────────────────────────────────────────────

// Only one copy of the app may run at a time. A second copy would spawn a
// second backend that cannot bind port 8765, and its renderer would hold an api
// token the already-running backend rejects — a window where nothing works.
// Double-clicking the icon twice is an easy thing for anyone to do.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    // Someone tried to open a second copy: surface the one already running.
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.on('ready', async () => {
    startBackend();

    try {
      await waitForBackend(BACKEND_PORT);
      console.log('Backend is ready');
      backendReady = true;
      createWindow();
      if (!isDev) {
        setupAutoUpdater();
      }
    } catch (e) {
      console.error('Failed to start backend:', e);
      showErrorWindow('Failed to Start', e.message);
    }
  });
}

app.on('window-all-closed', () => {
  app.isQuitting = true;
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  app.quit();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (updateCheckInterval) {
    clearInterval(updateCheckInterval);
    updateCheckInterval = null;
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
