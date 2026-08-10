import { motion } from 'framer-motion';
import { Download, CheckCircle, AlertTriangle, RefreshCw } from 'lucide-react';
import { useStore } from '../store';
import type { UpdateState } from '../hooks/useUpdater';

interface UpdateCardProps {
  updateState: UpdateState;
  onRestart: () => void;
  onDismiss: () => void;
  onDownloadLatest: () => void;
}

/**
 * The prominent update panel on the home screen.
 *
 * The thin banner was easy to scroll past, so people stayed several versions
 * behind without realising. This is deliberately large and sits above the
 * pathway choice — the first thing on the first screen.
 *
 * Only ACTIONABLE states appear here. "You're up to date" is left to the
 * banner: making that loud would train people to ignore this spot.
 */
export default function UpdateCard({
  updateState,
  onRestart,
  onDismiss,
  onDownloadLatest,
}: UpdateCardProps) {
  // Restarting mid-run would abort the redaction and can leave the backend
  // holding its port as the new copy starts (see CLAUDE.md rule 55).
  const isProcessing = useStore((s) => s.isProcessing);

  const { status } = updateState;
  if (status !== 'available' && status !== 'downloading' && status !== 'ready' && status !== 'error') {
    return null;
  }

  const tone =
    status === 'ready'
      ? { bg: 'bg-emerald-50', border: 'border-emerald-300', icon: 'text-emerald-600', head: 'text-emerald-900', body: 'text-emerald-800' }
      : status === 'error'
      ? { bg: 'bg-amber-50', border: 'border-amber-300', icon: 'text-amber-600', head: 'text-amber-900', body: 'text-amber-800' }
      : { bg: 'bg-blue-50', border: 'border-blue-300', icon: 'text-blue-600', head: 'text-blue-900', body: 'text-blue-800' };

  const version = 'version' in updateState && updateState.version ? updateState.version : null;

  const heading =
    status === 'ready'
      ? `Version ${version ?? ''} is ready to install`.replace('  ', ' ')
      : status === 'downloading'
      ? `Getting version ${version ?? ''} ready…`.replace('  ', ' ')
      : status === 'available'
      ? `A new version${version ? ` (${version})` : ''} is available`
      : 'Update couldn’t be installed';

  const detail =
    status === 'ready'
      ? 'The update is downloaded. Restarting takes a few seconds and reopens the app for you.'
      : status === 'downloading'
      ? 'You can keep working — we’ll let you know the moment it’s ready to install.'
      : status === 'available'
      ? 'Keeping up to date means the latest detection improvements and fixes.'
      : updateState.message;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`mb-6 rounded-xl border-2 ${tone.border} ${tone.bg} px-6 py-5 shadow-sm`}
    >
      <div className="flex items-start gap-4">
        <div className={`shrink-0 mt-0.5 ${tone.icon}`}>
          {status === 'ready' && <CheckCircle size={28} />}
          {status === 'downloading' && <RefreshCw size={28} className="animate-spin" />}
          {status === 'available' && <Download size={28} />}
          {status === 'error' && <AlertTriangle size={28} />}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className={`text-lg font-bold tracking-tight ${tone.head}`}>{heading}</h3>
          <p className={`mt-1 text-sm ${tone.body}`}>{detail}</p>

          {status === 'downloading' && (
            <div className="mt-3">
              <div className="h-2 w-full rounded-full bg-blue-100 overflow-hidden">
                <motion.div
                  className="h-full rounded-full bg-blue-500"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.max(updateState.percent, 2)}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="mt-1.5 text-xs text-blue-700">{updateState.percent}% complete</p>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            {status === 'ready' && (
              <>
                <button
                  onClick={onRestart}
                  disabled={isProcessing}
                  className="px-5 py-2.5 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors btn-press"
                >
                  Restart &amp; install now
                </button>
                <button
                  onClick={onDismiss}
                  className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
                >
                  Not now
                </button>
                {isProcessing && (
                  <span className="text-xs text-slate-500">
                    Finish the documents you’re working on first.
                  </span>
                )}
              </>
            )}

            {(status === 'available' || status === 'error') && (
              <>
                <button
                  onClick={onDownloadLatest}
                  className="px-5 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors btn-press"
                >
                  Download the update
                </button>
                <button
                  onClick={onDismiss}
                  className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
                >
                  Not now
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
