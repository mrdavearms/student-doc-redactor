export {};

declare global {
  interface Window {
    electronAPI?: {
      platform: string;
      isElectron: boolean;
      selectFolder: () => Promise<string | null>;
      openExternal: (url: string) => Promise<void>;

      // Each returns a cleanup function for useEffect
      onUpdateAvailable: (cb: (version: string) => void) => () => void;
      onUpdateDownloaded: (cb: () => void) => () => void;
      onUpdateNotAvailable: (cb: () => void) => () => void;
      onDownloadProgress: (cb: (percent: number) => void) => () => void;

      restartAndInstall: () => Promise<void>;
      checkForUpdates: () => Promise<void>;
      getAppVersion: () => Promise<string>;
    };
  }
}
