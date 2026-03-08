/**
 * Electron Main Process
 * Spawns the Python FastAPI backend and creates the app window.
 */

const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const BACKEND_PORT = 8765;
const DEV_SERVER = `http://localhost:5173`;
const isDev = !app.isPackaged;

let backendProcess = null;
let mainWindow = null;

/** Wait for the backend to respond on its port. */
function waitForBackend(port, retries = 30) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts++;
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else if (attempts < retries) {
          setTimeout(check, 500);
        } else {
          reject(new Error('Backend did not start'));
        }
      });
      req.on('error', () => {
        if (attempts < retries) {
          setTimeout(check, 500);
        } else {
          reject(new Error('Backend did not start'));
        }
      });
      req.end();
    };
    check();
  });
}

/** Start the Python FastAPI backend. */
function startBackend() {
  const projectRoot = isDev
    ? path.resolve(__dirname, '..')   // desktop/
    : path.resolve(process.resourcesPath, 'app');

  const appRoot = path.resolve(projectRoot, '..');  // redaction tool/

  // Find the Python executable
  const pythonPath = isDev
    ? path.join(appRoot, 'venv', 'bin', 'python3.13')
    : path.join(process.resourcesPath, 'python', 'bin', 'python3');

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

// ── App lifecycle ─────────────────────────────────────────────────────

app.on('ready', async () => {
  startBackend();

  try {
    await waitForBackend(BACKEND_PORT);
    console.log('Backend is ready');
  } catch (e) {
    console.error('Failed to start backend:', e);
  }

  createWindow();
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
