import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import UpdateBanner from './components/UpdateBanner';
import { useStore } from './store';
import { useUpdater } from './hooks/useUpdater';
import { api, BackendUnreachableError } from './api';
import Setup from './pages/Setup';
import FolderSelection from './pages/FolderSelection';
import ConversionStatus from './pages/ConversionStatus';
import DocumentReview from './pages/DocumentReview';
import FinalConfirmation from './pages/FinalConfirmation';
import Completion from './pages/Completion';

function App() {
  const currentScreen = useStore((s) => s.currentScreen);
  const navigateTo = useStore((s) => s.navigateTo);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const { updateState, checkForUpdates, restartAndInstall, dismiss } = useUpdater();
  const [depsChecked, setDepsChecked] = useState(false);
  const backendReachable = useStore((s) => s.backendReachable);
  const setBackendReachable = useStore((s) => s.setBackendReachable);

  // On mount: check dependencies and redirect to setup if LibreOffice is missing
  useEffect(() => {
    api.checkDependencies()
      .then((deps) => {
        if (!deps.libreoffice_ok && currentScreen === 'folder_selection') {
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
      case 'folder_selection':   return <FolderSelection />;
      case 'conversion_status':  return <ConversionStatus />;
      case 'document_review':    return <DocumentReview />;
      case 'final_confirmation': return <FinalConfirmation />;
      case 'completion':         return <Completion />;
    }
  };

  // Don't render until dep check completes (avoids flash of folder_selection then redirect)
  if (!depsChecked) return null;

  return (
    <Layout updateState={updateState} onCheckForUpdates={checkForUpdates}>
      <UpdateBanner
        updateState={updateState}
        onRestart={restartAndInstall}
        onDismiss={dismiss}
      />

      {!backendReachable && (
        <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          <p className="text-sm text-amber-800">
            The redaction engine isn&apos;t responding. Please wait a moment, or restart the app if this persists.
          </p>
        </div>
      )}

      {/* Global error toast */}
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-start justify-between">
          <p className="text-sm text-red-700">{error}</p>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs ml-4">
            Dismiss
          </button>
        </div>
      )}
      {renderScreen()}
    </Layout>
  );
}

export default App;
