/**
 * Electron Preload Script
 * Exposes minimal APIs to the renderer process.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
  getApiToken: () => ipcRenderer.invoke('get-api-token'),
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: () => ipcRenderer.invoke('select-file'),
  saveFileAs: (defaultPath, kind) => ipcRenderer.invoke('save-file-as', defaultPath, kind),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Returns a cleanup function — call it in useEffect's return to avoid listener buildup
  onUpdateAvailable: (cb) => {
    const handler = (_event, version) => cb(version);
    ipcRenderer.on('update-available', handler);
    return () => ipcRenderer.removeListener('update-available', handler);
  },
  onUpdateDownloaded: (cb) => {
    // The version must be forwarded: an update staged before a previous launch
    // reaches "ready" without ever passing through "downloading", so it is the
    // only place the renderer can learn which version is waiting.
    const handler = (_event, version) => cb(version);
    ipcRenderer.on('update-downloaded', handler);
    return () => ipcRenderer.removeListener('update-downloaded', handler);
  },
  onUpdateNotAvailable: (cb) => {
    const handler = () => cb();
    ipcRenderer.on('update-not-available', handler);
    return () => ipcRenderer.removeListener('update-not-available', handler);
  },
  onDownloadProgress: (cb) => {
    const handler = (_event, percent) => cb(percent);
    ipcRenderer.on('download-progress', handler);
    return () => ipcRenderer.removeListener('download-progress', handler);
  },
  onUpdateAvailableManual: (cb) => {
    const handler = (_event, version) => cb(version);
    ipcRenderer.on('update-available-manual', handler);
    return () => ipcRenderer.removeListener('update-available-manual', handler);
  },
  onUpdateError: (cb) => {
    const handler = (_event, message) => cb(message);
    ipcRenderer.on('update-error', handler);
    return () => ipcRenderer.removeListener('update-error', handler);
  },

  restartAndInstall: () => ipcRenderer.invoke('restart-and-install'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  logError: (payload) => ipcRenderer.invoke('log-error', payload),
});
