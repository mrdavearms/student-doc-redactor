/**
 * useUpdater — manages auto-update state for the lifetime of the app.
 *
 * State machine:
 *   idle → checking → up-to-date              (no update found)
 *          checking → available               (update found, manual download — e.g. unsigned macOS)
 *          checking → downloading → ready      (update found and auto-downloaded — e.g. Windows)
 *   any   → error                             (the updater failed, or a download stalled)
 *
 * Transitions are driven by IPC events from the main process. A watchdog guards
 * the `downloading` state so a stalled or failed download can NEVER leave the UI
 * stuck on "Downloading…" — it falls back to an error with a manual-download path.
 */

import { useState, useEffect, useCallback } from 'react';

export const RELEASES_URL =
  'https://github.com/mrdavearms/student-doc-redactor/releases/latest';

export type UpdateState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'up-to-date' }
  | { status: 'available'; version: string }
  | { status: 'downloading'; version: string; percent: number }
  | { status: 'ready'; version: string }
  | { status: 'error'; message: string };

// If a download reports no progress for this long, treat it as stalled.
const DOWNLOAD_STALL_MS = 90_000;

export function useUpdater() {
  const [updateState, setUpdateState] = useState<UpdateState>({ status: 'idle' });
  const isElectron = !!window.electronAPI;

  useEffect(() => {
    if (!isElectron) return;

    const cleanups = [
      window.electronAPI!.onUpdateAvailable((version) => {
        setUpdateState({ status: 'downloading', version, percent: 0 });
      }),
      window.electronAPI!.onUpdateAvailableManual((version) => {
        // Update found, but the app can't install it itself (e.g. an unsigned
        // macOS build) — prompt a manual download rather than a fake spinner.
        setUpdateState({ status: 'available', version });
      }),
      window.electronAPI!.onDownloadProgress((percent) => {
        setUpdateState((prev) =>
          prev.status === 'downloading' ? { ...prev, percent } : prev
        );
      }),
      window.electronAPI!.onUpdateDownloaded(() => {
        setUpdateState((prev) =>
          prev.status === 'downloading'
            ? { status: 'ready', version: prev.version }
            : { status: 'ready', version: '' }
        );
      }),
      window.electronAPI!.onUpdateNotAvailable(() => {
        setUpdateState({ status: 'up-to-date' });
        // Fade the "up to date" message back to idle after a few seconds.
        setTimeout(
          () => setUpdateState((prev) => (prev.status === 'up-to-date' ? { status: 'idle' } : prev)),
          5000
        );
      }),
      window.electronAPI!.onUpdateError(() => {
        setUpdateState({
          status: 'error',
          message: "Couldn't update automatically. Download the latest version to update.",
        });
      }),
    ];

    return () => cleanups.forEach((c) => c());
  }, [isElectron]);

  // Watchdog for the download step. Resets each time progress advances; if the
  // percent doesn't move for DOWNLOAD_STALL_MS, surface an error with a manual
  // download path instead of spinning forever.
  const isDownloading = updateState.status === 'downloading';
  const downloadingPercent = updateState.status === 'downloading' ? updateState.percent : -1;
  useEffect(() => {
    if (!isDownloading) return;
    const t = setTimeout(() => {
      setUpdateState((prev) =>
        prev.status === 'downloading'
          ? { status: 'error', message: 'The update is taking too long. Download the latest version to update.' }
          : prev
      );
    }, DOWNLOAD_STALL_MS);
    return () => clearTimeout(t);
  }, [isDownloading, downloadingPercent]);

  const checkForUpdates = useCallback(async () => {
    if (!isElectron) return;
    setUpdateState({ status: 'checking' });
    try {
      await window.electronAPI!.checkForUpdates();
      // Transitions from here are driven by the IPC events above.
      // If nothing fires within 8 seconds, assume a network/check failure.
      setTimeout(() => {
        setUpdateState((prev) =>
          prev.status === 'checking'
            ? { status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" }
            : prev
        );
      }, 8000);
    } catch {
      setUpdateState({ status: 'error', message: "Couldn't check for updates. Are you connected to the internet?" });
    }
  }, [isElectron]);

  const restartAndInstall = useCallback(() => {
    window.electronAPI?.restartAndInstall();
  }, []);

  const downloadLatest = useCallback(() => {
    window.electronAPI?.openExternal(RELEASES_URL);
  }, []);

  const dismiss = useCallback(() => {
    setUpdateState({ status: 'idle' });
  }, []);

  return { updateState, checkForUpdates, restartAndInstall, downloadLatest, dismiss };
}
