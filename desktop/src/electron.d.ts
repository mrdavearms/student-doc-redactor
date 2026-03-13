export {};

declare global {
  interface Window {
    electronAPI?: {
      platform: string;
      isElectron: boolean;
      selectFolder: () => Promise<string | null>;
      openExternal: (url: string) => Promise<void>;
      onUpdateAvailable: (cb: (version: string) => void) => void;
      onUpdateDownloaded: (cb: () => void) => void;
    };
  }
}
