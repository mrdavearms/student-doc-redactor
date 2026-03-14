/**
 * Electron Preload Script
 * Exposes minimal APIs to the renderer process.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Returns a cleanup function — call it in useEffect's return to avoid listener buildup
  onUpdateAvailable: (cb) => {
    const handler = (_event, version) => cb(version);
    ipcRenderer.on('update-available', handler);
    return () => ipcRenderer.removeListener('update-available', handler);
  },
  onUpdateDownloaded: (cb) => {
    const handler = () => cb();
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

  restartAndInstall: () => ipcRenderer.invoke('restart-and-install'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
});
