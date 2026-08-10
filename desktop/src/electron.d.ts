export {};

declare global {
  interface Window {
    electronAPI?: {
      platform: string;
      isElectron: boolean;
      getApiToken?: () => Promise<string>;
      selectFolder: () => Promise<string | null>;
      selectFile?: () => Promise<string | null>;
      saveFileAs?: (defaultPath?: string, kind?: 'pdf' | 'txt') => Promise<string | null>;
      openExternal: (url: string) => Promise<void>;

      // Each returns a cleanup function for useEffect
      onUpdateAvailable: (cb: (version: string) => void) => () => void;
      onUpdateAvailableManual: (cb: (version: string) => void) => () => void;
      onUpdateDownloaded: (cb: (version?: string) => void) => () => void;
      onUpdateNotAvailable: (cb: () => void) => () => void;
      onDownloadProgress: (cb: (percent: number) => void) => () => void;
      onUpdateError: (cb: (message: string) => void) => () => void;

      restartAndInstall: () => Promise<void>;
      checkForUpdates: () => Promise<void>;
      getAppVersion: () => Promise<string>;
      logError: (payload: {
        message: string;
        stack?: string;
        componentStack?: string;
        timestamp: string;
      }) => Promise<void>;
    };
  }
}
