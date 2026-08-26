import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import UpdateBanner from './components/UpdateBanner';
import UpdateCard from './components/UpdateCard';
import { useStore } from './store';
import { useUpdater } from './hooks/useUpdater';
import { api, BackendUnreachableError } from './api';
import { buildFaultReportUrl } from './lib/faultReport';
import Setup from './pages/Setup';
import ModeSelection from './pages/ModeSelection';
import FolderSelection from './pages/FolderSelection';
import ConversionStatus from './pages/ConversionStatus';
import TextScan from './pages/TextScan';
import DocumentReview from './pages/DocumentReview';
import FinalConfirmation from './pages/FinalConfirmation';
import Completion from './pages/Completion';
import DeidentifyCompletion from './pages/DeidentifyCompletion';
import PasteCompletion from './pages/PasteCompletion';
import NoPiiFound from './pages/NoPiiFound';
import PeopleReview from './pages/PeopleReview';

function App() {
  const currentScreen = useStore((s) => s.currentScreen);
  const navigateTo = useStore((s) => s.navigateTo);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const { updateState, checkForUpdates, restartAndInstall, downloadLatest, dismiss } = useUpdater();
  const [depsChecked, setDepsChecked] = useState(false);
  const backendReachable = useStore((s) => s.backendReachable);
  const setBackendReachable = useStore((s) => s.setBackendReachable);
  const workflowMode = useStore((s) => s.workflowMode);
  const inputMode = useStore((s) => s.inputMode);
  const [appVersion, setAppVersion] = useState('');

  useEffect(() => {
    window.electronAPI?.getAppVersion?.().then(setAppVersion).catch(() => {});
  }, []);

  const reportFault = (friendlyMessage: string) => {
    window.electronAPI?.openExternal(buildFaultReportUrl({
      appVersion,
      screen: currentScreen,
      workflowMode,
      friendlyMessage,
    }));
  };

  // On mount: check dependencies and redirect to setup if LibreOffice is missing
  useEffect(() => {
    api.checkDependencies()
      .then((deps) => {
        if (!deps.libreoffice_ok
            && (currentScreen === 'mode_selection' || currentScreen === 'folder_selection')) {
          navigateTo('setup');
        }
      })
      .catch((err) => {
        if (err instanceof BackendUnreachableError) {
          setBackendReachable(false);
        } else {
          console.warn('Dep check failed:', err.message);
        }
      })
      .finally(() => setDepsChecked(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll /api/health every 5s while the backend is unreachable; clear flag on recovery.
  useEffect(() => {
    if (backendReachable) return;
    const interval = setInterval(async () => {
      try {
        await api.health();
        setBackendReachable(true);
      } catch {
        // Still down; keep polling
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [backendReachable, setBackendReachable]);

  const renderScreen = () => {
    switch (currentScreen) {
      case 'setup':              return <Setup />;
      case 'mode_selection':     return <ModeSelection />;
      case 'folder_selection':   return <FolderSelection />;
      case 'conversion_status':  return <ConversionStatus />;
      case 'text_scan':          return <TextScan />;
      case 'document_review':    return <DocumentReview />;
      case 'no_pii_found':       return <NoPiiFound />;
      case 'people_review':      return <PeopleReview />;
      case 'final_confirmation': return <FinalConfirmation />;
      case 'completion':
        if (inputMode === 'paste') return <PasteCompletion />;
        return workflowMode === 'deidentify' ? <DeidentifyCompletion /> : <Completion />;
    }
  };

  // Don't render until dep check completes (avoids flash of folder_selection then redirect)
  if (!depsChecked) return null;

  return (
    <Layout updateState={updateState} onCheckForUpdates={checkForUpdates}>
      {/* On the landing screen the update gets a full card, so it can't be
          scrolled past; everywhere else it's the banner. Never both — two
          notices for one update reads as two updates. */}
      {currentScreen === 'mode_selection' ? (
        <UpdateCard
          updateState={updateState}
          onRestart={restartAndInstall}
          onDismiss={dismiss}
          onDownloadLatest={downloadLatest}
        />
      ) : (
        <UpdateBanner
          updateState={updateState}
          onRestart={restartAndInstall}
          onDismiss={dismiss}
          onDownloadLatest={downloadLatest}
        />
      )}

      {!backendReachable && (
        <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          <p className="text-sm text-amber-800">
            The redaction engine isn&apos;t responding. Please wait a moment, or restart the app if this persists.{' '}
            <button
              onClick={() => reportFault("The redaction engine isn't responding.")}
              className="underline text-amber-700 hover:text-amber-900"
            >
              Report this problem
            </button>
          </p>
        </div>
      )}

      {/* Global error toast */}
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-start justify-between">
          <p className="text-sm text-red-700">{error}</p>
          <span className="flex items-center gap-3 ml-4 shrink-0">
            <button
              onClick={() => reportFault(error)}
              className="text-xs text-red-500 hover:text-red-700 underline"
            >
              Report this problem
            </button>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs">
              Dismiss
            </button>
          </span>
        </div>
      )}
      {renderScreen()}
    </Layout>
  );
}

export default App;
