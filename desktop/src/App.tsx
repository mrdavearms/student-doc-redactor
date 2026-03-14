import Layout from './components/Layout';
import Walkthrough from './components/Walkthrough';
import { useStore } from './store';
import FolderSelection from './pages/FolderSelection';
import ConversionStatus from './pages/ConversionStatus';
import DocumentReview from './pages/DocumentReview';
import FinalConfirmation from './pages/FinalConfirmation';
import Completion from './pages/Completion';

function App() {
  const currentScreen = useStore((s) => s.currentScreen);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);

  const renderScreen = () => {
    switch (currentScreen) {
      case 'folder_selection':
        return <FolderSelection />;
      case 'conversion_status':
        return <ConversionStatus />;
      case 'document_review':
        return <DocumentReview />;
      case 'final_confirmation':
        return <FinalConfirmation />;
      case 'completion':
        return <Completion />;
    }
  };

  return (
    <Layout>
      <Walkthrough />
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
