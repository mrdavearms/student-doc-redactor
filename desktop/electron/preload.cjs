/**
 * Electron Preload Script
 * Exposes minimal APIs to the renderer process.
 */

const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
});
