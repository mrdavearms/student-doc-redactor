import { motion } from 'framer-motion';
import { Check, FolderOpen, RefreshCw, Search, ShieldCheck, PartyPopper, ExternalLink, Info, BookOpen } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useStore } from '../store';
import { SCREENS, type Screen } from '../types';
import AboutModal from './AboutModal';
import Walkthrough from './Walkthrough';
import type { UpdateState } from '../hooks/useUpdater';

const WALKTHROUGH_STORAGE_KEY = 'walkthrough_dismissed';

const ICONS: Record<Screen, React.ReactNode> = {
  setup: <RefreshCw size={18} />,
  folder_selection: <FolderOpen size={18} />,
  conversion_status: <RefreshCw size={18} />,
  document_review: <Search size={18} />,
  final_confirmation: <ShieldCheck size={18} />,
  completion: <PartyPopper size={18} />,
};

interface SidebarProps {
  updateState: UpdateState;
  onCheckForUpdates: () => void;
}

export default function Sidebar({ updateState, onCheckForUpdates }: SidebarProps) {
  const currentScreen = useStore((s) => s.currentScreen);
  const currentIdx = SCREENS.findIndex((s) => s.key === currentScreen);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [walkthroughOpen, setWalkthroughOpen] = useState(false);
  const [appVersion, setAppVersion] = useState('');

  // First-run check: show walkthrough on initial mount only (Sidebar never remounts)
  useEffect(() => {
    const dismissed = localStorage.getItem(WALKTHROUGH_STORAGE_KEY);
    if (!dismissed) {
      setWalkthroughOpen(true);
    }
    window.electronAPI?.getAppVersion().then(setAppVersion).catch(() => {});
  }, []);

  return (
    <aside className="w-64 min-h-full bg-white border-r border-slate-200 flex flex-col">
      {/* Logo / Title */}
      <div className="px-6 py-6 border-b border-slate-100">
        <h1 className="text-lg tracking-tight">
          <span className="font-bold text-primary-600">Redact</span>
          <span className="text-slate-300 mx-1.5 font-light">|</span>
          <span className="font-light text-slate-400">Tool</span>
        </h1>
        <p className="text-[10px] text-slate-400 mt-1 tracking-widest uppercase">Protect student privacy</p>
      </div>

      {/* Steps */}
      <nav className="flex-1 px-4 py-6">
        <ul className="space-y-1">
          {SCREENS.map((screen, idx) => {
            const isActive = screen.key === currentScreen;
            const isCompleted = idx < currentIdx;
            const isFuture = idx > currentIdx;

            return (
              <li key={screen.key} className="relative">
                {/* Active highlight */}
                {isActive && (
                  <motion.div
                    layoutId="activeStep"
                    className="absolute inset-0 bg-primary-50 rounded-lg"
                    transition={{ type: 'spring', stiffness: 350, damping: 30 }}
                  />
                )}

                <div
                  className={`
                    relative flex items-center gap-3 px-3 py-2.5 rounded-lg
                    transition-colors duration-150
                    ${isActive ? 'text-primary-700 font-medium' : ''}
                    ${isCompleted ? 'text-slate-600' : ''}
                    ${isFuture ? 'text-slate-300' : ''}
                  `}
                >
                  {/* Step indicator */}
                  <div
                    className={`
                      w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold
                      transition-all duration-200 shrink-0
                      ${isActive ? 'bg-primary-600 text-white shadow-sm' : ''}
                      ${isCompleted ? 'bg-emerald-500 text-white' : ''}
                      ${isFuture ? 'bg-slate-100 text-slate-300 border border-slate-200' : ''}
                    `}
                  >
                    {isCompleted ? <Check size={14} strokeWidth={3} /> : screen.step}
                  </div>

                  {/* Label + icon */}
                  <span className="flex-1 text-sm">{screen.label}</span>
                  <span className={`${isFuture ? 'opacity-30' : 'opacity-60'}`}>
                    {ICONS[screen.key]}
                  </span>
                </div>

                {/* Connector line */}
                {idx < SCREENS.length - 1 && (
                  <div className="ml-[22px] w-px h-2 my-0.5">
                    <div
                      className={`w-full h-full ${
                        isCompleted ? 'bg-emerald-300' : 'bg-slate-200'
                      }`}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-slate-100 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-slate-300 uppercase tracking-widest font-medium">{appVersion ? `v${appVersion}` : 'v—'}</p>
          <button
            onClick={() => setAboutOpen(true)}
            className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-primary-500 transition-colors btn-press"
          >
            <Info size={12} />
            About
          </button>
        </div>
        <button
          onClick={() => setWalkthroughOpen(true)}
          className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-primary-500 transition-colors btn-press"
        >
          <BookOpen size={10} />
          Quick Guide
        </button>
        <button
          onClick={() => window.electronAPI?.openExternal('https://github.com/mrdavearms/student-doc-redactor')}
          className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-primary-500 transition-colors btn-press"
        >
          <ExternalLink size={10} />
          Report issues on GitHub
        </button>
      </div>

      <AboutModal
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
        onShowWalkthrough={() => {
          setAboutOpen(false);
          setWalkthroughOpen(true);
        }}
        updateState={updateState}
        onCheckForUpdates={onCheckForUpdates}
      />
      {walkthroughOpen && (
        <Walkthrough forceOpen onClose={() => setWalkthroughOpen(false)} />
      )}
    </aside>
  );
}
