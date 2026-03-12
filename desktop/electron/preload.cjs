/**
 * Electron Preload Script
 * Exposes minimal APIs to the renderer process.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
  onUpdateAvailable: (cb) => ipcRenderer.on('update-available', (_event, version) => cb(version)),
  onUpdateDownloaded: (cb) => ipcRenderer.on('update-downloaded', () => cb()),
});
