import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, RefreshCw, CheckCircle, ArrowRight, FileText } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import type { DependencyStatus } from '../types';

export default function Setup() {
  const navigateTo = useStore((s) => s.navigateTo);
  const [checking, setChecking] = useState(false);
  const [deps, setDeps] = useState<DependencyStatus | null>(null);
  const [allReady, setAllReady] = useState(false);

  const handleCheckAgain = async () => {
    setChecking(true);
    try {
      const result = await api.checkDependencies();
      setDeps(result);
      if (result.libreoffice_ok) {
        setAllReady(true);
        // Auto-advance after 2 seconds
        setTimeout(() => navigateTo('folder_selection'), 2000);
      }
    } catch {
      // Silently fail — the Check Again button stays available
    } finally {
      setChecking(false);
    }
  };

  const handleDownload = () => {
    window.electronAPI?.openExternal('https://www.libreoffice.org/download/download-libreoffice/');
  };

  if (allReady) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center justify-center min-h-[400px] space-y-6"
      >
        <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center">
          <CheckCircle size={32} className="text-emerald-600" />
        </div>
        <div className="text-center">
          <h2 className="text-2xl font-bold text-slate-800">You're All Set</h2>
          <p className="text-sm text-slate-400 mt-1">Everything is ready to go.</p>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2 text-emerald-700">
            <CheckCircle size={16} /> LibreOffice — Installed
          </div>
          <div className="flex items-center gap-2 text-emerald-700">
            <CheckCircle size={16} /> Tesseract OCR — Built-in
          </div>
        </div>
        <button
          onClick={() => navigateTo('folder_selection')}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow transition-all btn-press"
        >
          Get Started <ArrowRight size={16} />
        </button>
      </motion.div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Almost Ready</h2>
        <p className="text-sm text-slate-400 mt-1">One quick setup step before you start.</p>
      </div>

      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-amber-50 border border-amber-200 rounded-xl p-6 space-y-4"
      >
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
            <FileText size={20} className="text-amber-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-amber-900">Install LibreOffice</h3>
            <p className="text-sm text-amber-800 mt-1 leading-relaxed">
              LibreOffice is a free app that lets this tool read Word documents
              (.doc and .docx files). It takes a couple of minutes to install.
            </p>
          </div>
        </div>

        <button
          onClick={handleDownload}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium
                     bg-amber-600 text-white hover:bg-amber-700 shadow-sm hover:shadow transition-all btn-press"
        >
          <Download size={16} /> Download LibreOffice
        </button>

        <p className="text-xs text-amber-700">
          After installing, click <span className="font-medium">Check Again</span> below — no need to restart this app.
        </p>
      </motion.section>

      {/* Status after checking */}
      <AnimatePresence>
        {deps && !deps.libreoffice_ok && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700"
          >
            LibreOffice was not detected. Make sure the installation is complete, then try again.
          </motion.div>
        )}
      </AnimatePresence>

      {/* Actions */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={() => navigateTo('folder_selection')}
          className="text-sm text-slate-400 hover:text-slate-600 transition-colors"
        >
          Skip for now — I only have PDFs
        </button>

        <button
          onClick={handleCheckAgain}
          disabled={checking}
          className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                     bg-primary-600 text-white hover:bg-primary-700 disabled:bg-slate-300
                     disabled:cursor-not-allowed shadow-sm hover:shadow transition-all btn-press"
        >
          <RefreshCw size={16} className={checking ? 'animate-spin' : ''} />
          {checking ? 'Checking...' : 'Check Again'}
        </button>
      </div>

      <p className="text-xs text-slate-400 text-center">
        LibreOffice is only needed for Word documents. If you only work with PDFs, you can skip this step.
      </p>
    </div>
  );
}
