/**
 * useUpdater — manages auto-update state for the lifetime of the app.
 *
 * State machine:
 *   idle → checking → up-to-date   (no update found)
 *          checking → downloading  (update found, autoDownload=true)
 *                     downloading → ready  (downloaded, awaiting restart)
 *
 * All transitions are driven by IPC events from the main process.
 * The manual checkForUpdates() call can move idle → checking at any time.
 */

import { useState, useEffect, useCallback } from 'react';

export type UpdateState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'up-to-date' }
  | { status: 'downloading'; version: string; percent: number }
  | { status: 'ready'; version: string }
  | { status: 'error'; message: string };

export function useUpdater() {
  const [updateState, setUpdateState] = useState<UpdateState>({ status: 'idle' });
  const isElectron = !!window.electronAPI;

  useEffect(() => {
    if (!isElectron) return;

    const cleanupAvailable = window.electronAPI!.onUpdateAvailable((version) => {
      setUpdateState({ status: 'downloading', version, percent: 0 });
    });

    const cleanupProgress = window.electronAPI!.onDownloadProgress((percent) => {
      setUpdateState((prev) =>
        prev.status === 'downloading' ? { ...prev, percent } : prev
      );
    });

    const cleanupDownloaded = window.electronAPI!.onUpdateDownloaded(() => {
      setUpdateState((prev) =>
        prev.status === 'downloading'
          ? { status: 'ready', version: prev.version }
          : { status: 'ready', version: '' }
      );
    });

    const cleanupNotAvailable = window.electronAPI!.onUpdateNotAvailable(() => {
      setUpdateState({ status: 'up-to-date' });
      // Reset to idle after 5 seconds so the "up to date" message fades away
      setTimeout(() => setUpdateState({ status: 'idle' }), 5000);
    });

    return () => {
      cleanupAvailable();
      cleanupProgress();
      cleanupDownloaded();
      cleanupNotAvailable();
    };
  }, [isElectron]);

  const checkForUpdates = useCallback(async () => {
    if (!isElectron) return;
    setUpdateState({ status: 'checking' });
    try {
      await window.electronAPI!.checkForUpdates();
      // State transitions from here are driven by IPC events above.
      // If no event fires within 8 seconds, assume network error.
      setTimeout(() => {
        setUpdateState((prev) => {
          if (prev.status === 'checking') {
            return { status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" };
          }
          return prev;
        });
      }, 8000);
    } catch {
      setUpdateState({ status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" });
    }
  }, [isElectron]);

  const restartAndInstall = useCallback(() => {
    window.electronAPI?.restartAndInstall();
  }, []);

  const dismiss = useCallback(() => {
    setUpdateState({ status: 'idle' });
  }, []);

  return { updateState, checkForUpdates, restartAndInstall, dismiss };
}
