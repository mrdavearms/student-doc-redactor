import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import UpdateBanner from './components/UpdateBanner';
import { useStore } from './store';
import { useUpdater } from './hooks/useUpdater';
import { api } from './api';
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

  // On mount: check dependencies and redirect to setup if LibreOffice is missing
  useEffect(() => {
    api.checkDependencies()
      .then((deps) => {
        if (!deps.libreoffice_ok && currentScreen === 'folder_selection') {
          navigateTo('setup');
        }
      })
      .catch(() => {
        // Backend not ready yet — don't redirect, let the app load normally
      })
      .finally(() => setDepsChecked(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
