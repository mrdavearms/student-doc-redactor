/**
 * Electron Main Process
 * Spawns the Python FastAPI backend and creates the app window.
 */

const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const { autoUpdater } = require('electron-updater');

const BACKEND_PORT = 8765;
const DEV_SERVER = `http://localhost:5173`;
const isDev = !app.isPackaged;

let backendProcess = null;
let mainWindow = null;

/** Wait for the backend to respond on its port (30-second wall-clock timeout). */
function waitForBackend(port, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const check = () => {
      if (Date.now() > deadline) {
        reject(new Error('Backend did not start within 30 seconds'));
        return;
      }
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          setTimeout(check, 500);
        }
      });
      req.on('error', () => setTimeout(check, 500));
      req.setTimeout(1000, () => { req.destroy(); setTimeout(check, 500); });
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
    ? path.resolve(__dirname, '..', '..')   // redaction tool/ in dev
    : process.resourcesPath;

  const appRoot = isDev
    ? resourcesPath                          // redaction tool/
    : path.join(resourcesPath, 'app');

  // Find the Python executable
  const pythonPath = isDev
    ? path.join(appRoot, 'venv', 'bin', 'python3.13')
    : path.join(resourcesPath, 'bundled-python', 'bin', 'python3');

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
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  backendProcess.stdout.on('data', (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.on('exit', (code) => {
    console.log(`Backend exited with code ${code}`);
  });
}

/** Create the main application window. */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL(DEV_SERVER);
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Auto-updater ──────────────────────────────────────────────────────

function setupAutoUpdater() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    console.log(`Update available: ${info.version}`);
    if (mainWindow) {
      mainWindow.webContents.send('update-available', info.version);
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
  });

  // Check for updates after a short delay to avoid blocking startup
  setTimeout(() => autoUpdater.checkForUpdates().catch(() => {}), 10000);
}

// ── App lifecycle ─────────────────────────────────────────────────────

app.on('ready', async () => {
  startBackend();

  try {
    await waitForBackend(BACKEND_PORT);
    console.log('Backend is ready');
    createWindow();
    if (!isDev) {
      setupAutoUpdater();
    }
  } catch (e) {
    console.error('Failed to start backend:', e);
    showErrorWindow(
      'Failed to Start',
      `The redaction tool backend could not be started.\n\n${e.message}\n\nPlease reinstall the application.`
    );
  }
});

app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  app.quit();
});

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
