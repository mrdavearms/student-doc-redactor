import { motion, AnimatePresence } from 'framer-motion';
import { Download, CheckCircle, AlertTriangle } from 'lucide-react';
import type { UpdateState } from '../hooks/useUpdater';

interface UpdateBannerProps {
  updateState: UpdateState;
  onRestart: () => void;
  onDismiss: () => void;
}

export default function UpdateBanner({ updateState, onRestart, onDismiss }: UpdateBannerProps) {
  const visible =
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
          className={`mb-4 rounded-lg px-4 py-3 flex items-center justify-between gap-4 text-sm ${
            updateState.status === 'ready'
              ? 'bg-emerald-50 border border-emerald-200'
              : updateState.status === 'up-to-date'
              ? 'bg-emerald-50 border border-emerald-200'
              : updateState.status === 'error'
              ? 'bg-amber-50 border border-amber-200'
              : 'bg-blue-50 border border-blue-200'
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            {updateState.status === 'downloading' && (
              <Download size={15} className="text-blue-500 shrink-0" />
            )}
            {updateState.status === 'ready' && (
              <CheckCircle size={15} className="text-emerald-500 shrink-0" />
            )}
            {updateState.status === 'up-to-date' && (
              <CheckCircle size={15} className="text-emerald-500 shrink-0" />
            )}
            {updateState.status === 'error' && (
              <AlertTriangle size={15} className="text-amber-500 shrink-0" />
            )}

            <span className={`truncate ${
              updateState.status === 'error' ? 'text-amber-700' :
              updateState.status === 'downloading' ? 'text-blue-700' : 'text-emerald-700'
            }`}>
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

          <div className="flex items-center gap-2 shrink-0">
            {updateState.status === 'ready' && (
              <button
                onClick={onRestart}
                className="px-3 py-1 rounded-md bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-colors"
              >
                Restart Now
              </button>
            )}
            {(updateState.status === 'ready' || updateState.status === 'error') && (
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
