import { motion } from 'framer-motion';
import { Check, FolderOpen, RefreshCw, Search, ShieldCheck, PartyPopper } from 'lucide-react';
import { useStore } from '../store';
import { SCREENS, type Screen } from '../types';

const ICONS: Record<Screen, React.ReactNode> = {
  folder_selection: <FolderOpen size={18} />,
  conversion_status: <RefreshCw size={18} />,
  document_review: <Search size={18} />,
  final_confirmation: <ShieldCheck size={18} />,
  completion: <PartyPopper size={18} />,
};

export default function Sidebar() {
  const currentScreen = useStore((s) => s.currentScreen);
  const currentIdx = SCREENS.findIndex((s) => s.key === currentScreen);

  return (
    <aside className="w-64 min-h-full bg-white border-r border-slate-200 flex flex-col">
      {/* Logo / Title */}
      <div className="px-6 py-6 border-b border-slate-100">
        <h1 className="text-lg font-semibold text-slate-800 tracking-tight">
          Redaction Tool
        </h1>
        <p className="text-xs text-slate-400 mt-0.5">PII Detection & Redaction</p>
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
      <div className="px-6 py-4 border-t border-slate-100">
        <p className="text-[10px] text-slate-300 uppercase tracking-widest">v2.0</p>
      </div>
    </aside>
  );
}
