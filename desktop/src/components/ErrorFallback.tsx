import { useState } from 'react';
import { AlertCircle, ChevronDown, ChevronUp, RotateCcw } from 'lucide-react';

interface Props {
  error: Error;
  onReset: () => void;
}

export default function ErrorFallback({ error, onReset }: Props) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8">
      <div className="max-w-md w-full bg-white rounded-xl border border-slate-200 p-8 text-center">
        <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
          <AlertCircle size={28} className="text-red-600" />
        </div>
        <h1 className="text-xl font-semibold text-slate-800 mb-2">Something went wrong</h1>
        <p className="text-sm text-slate-500 mb-6">
          The app hit an unexpected problem. Your files are unaffected. Click below to start over.
        </p>

        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all"
        >
          <RotateCcw size={16} /> Start over
        </button>

        <button
          onClick={() => setShowDetails((v) => !v)}
          className="mt-4 mx-auto flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600"
        >
          {showDetails ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          Technical details
        </button>

        {showDetails && (
          <pre className="mt-3 text-[11px] text-left bg-slate-50 rounded-lg p-3 overflow-x-auto text-slate-600 whitespace-pre-wrap">
            {error.message}
            {error.stack ? `\n\n${error.stack}` : ''}
          </pre>
        )}
      </div>
    </div>
  );
}
