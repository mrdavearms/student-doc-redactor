import { motion, AnimatePresence } from 'framer-motion';
import { Download, CheckCircle, AlertTriangle } from 'lucide-react';
import { useStore } from '../store';
import type { UpdateState } from '../hooks/useUpdater';

interface UpdateBannerProps {
  updateState: UpdateState;
  onRestart: () => void;
  onDismiss: () => void;
  onDownloadLatest: () => void;
}

export default function UpdateBanner({ updateState, onRestart, onDismiss, onDownloadLatest }: UpdateBannerProps) {
  // Restarting mid-run would abort the redaction and can leave the backend
  // holding its port as the new copy starts (see CLAUDE.md rule 55).
  const isProcessing = useStore((s) => s.isProcessing);
  const visible =
    updateState.status === 'available' ||
    updateState.status === 'downloading' ||
    updateState.status === 'ready' ||
    updateState.status === 'up-to-date' ||
    updateState.status === 'error';

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2 }}
          className={`mb-4 rounded-lg px-5 py-4 flex items-center justify-between gap-4 ${
            // "Up to date" stays quiet and small; everything actionable is loud.
            updateState.status === 'up-to-date'
              ? 'bg-emerald-50 border border-emerald-200 text-sm'
              : updateState.status === 'ready'
              ? 'bg-emerald-50 border-2 border-emerald-300 shadow-sm'
              : updateState.status === 'error'
              ? 'bg-amber-50 border-2 border-amber-300 shadow-sm'
              : 'bg-blue-50 border-2 border-blue-300 shadow-sm'
          }`}
        >
          <div className="flex items-center gap-3 min-w-0">
            {updateState.status === 'available' && (
              <Download size={22} className="text-blue-600 shrink-0" />
            )}
            {updateState.status === 'downloading' && (
              <Download size={22} className="text-blue-600 shrink-0" />
            )}
            {updateState.status === 'ready' && (
              <CheckCircle size={22} className="text-emerald-600 shrink-0" />
            )}
            {updateState.status === 'up-to-date' && (
              <CheckCircle size={15} className="text-emerald-500 shrink-0" />
            )}
            {updateState.status === 'error' && (
              <AlertTriangle size={22} className="text-amber-600 shrink-0" />
            )}

            <span className={`truncate ${
              updateState.status === 'up-to-date' ? 'text-emerald-700' :
              updateState.status === 'error' ? 'text-amber-900 font-semibold' :
              updateState.status === 'ready' ? 'text-emerald-900 font-semibold' :
              'text-blue-900 font-semibold'
            }`}>
              {updateState.status === 'available' &&
                `A new version${updateState.version ? ` (v${updateState.version})` : ''} is available.`}
              {updateState.status === 'downloading' &&
                `Downloading update${updateState.version ? ` v${updateState.version}` : ''}…${
                  updateState.percent > 0 ? ` ${updateState.percent}%` : ''
                }`}
              {updateState.status === 'ready' &&
                `Update ready${updateState.version ? ` — v${updateState.version}` : ''}. Restart the app to install it.`}
              {updateState.status === 'up-to-date' && "You're up to date."}
              {updateState.status === 'error' && updateState.message}
            </span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {updateState.status === 'ready' && (
              <button
                onClick={onRestart}
                disabled={isProcessing}
                title={isProcessing ? 'Finish the documents you’re working on first.' : undefined}
                className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors btn-press"
              >
                Restart &amp; install
              </button>
            )}
            {(updateState.status === 'available' || updateState.status === 'error') && (
              <button
                onClick={onDownloadLatest}
                className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors btn-press"
              >
                Download
              </button>
            )}
            {(updateState.status === 'ready' || updateState.status === 'available' || updateState.status === 'error') && (
              <button
                onClick={onDismiss}
                className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
              >
                {updateState.status === 'ready' ? 'Later' : 'Dismiss'}
              </button>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
