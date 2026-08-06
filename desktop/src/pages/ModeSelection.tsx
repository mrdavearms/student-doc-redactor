import { motion } from 'framer-motion';
import { ArrowLeft, ArrowRight, Bot, ShieldCheck } from 'lucide-react';
import { useStore } from '../store';
import type { WorkflowMode } from '../types';

const OPTIONS: {
  mode: WorkflowMode;
  title: string;
  blurb: string;
  detail: string;
  example: string;
  icon: React.ReactNode;
}[] = [
  {
    mode: 'redact',
    title: 'Redact documents',
    blurb: 'Black out personal information.',
    detail:
      'Produces redacted PDFs you can share or keep on file. Names, contact details and other personal information are covered with solid black boxes and removed from the file underneath.',
    example: 'Billy Bob is in Year 3.  →  ██████████ is in Year 3.',
    icon: <ShieldCheck size={22} />,
  },
  {
    mode: 'deidentify',
    title: 'De-identify for AI',
    blurb: 'Replace personal information with labels.',
    detail:
      'Produces plain text files that are safe to paste into an AI tool. Each person becomes a label, and a private key file is saved with your originals so you can turn the labels back into names afterwards.',
    example: 'Billy Bob is in Year 3.  →  [Student] is in Year 3.',
    icon: <Bot size={22} />,
  },
];

export default function ModeSelection() {
  const workflowMode = useStore((s) => s.workflowMode);
  const setWorkflowMode = useStore((s) => s.setWorkflowMode);
  const navigateTo = useStore((s) => s.navigateTo);
  // Reached via the sidebar's "change" link mid-wizard? Offer a way back, so
  // peeking at the other option isn't a one-way trip through the whole flow.
  const canGoBack = useStore((s) => s.detectionResults !== null);

  const choose = (mode: WorkflowMode) => {
    setWorkflowMode(mode);
    navigateTo('folder_selection');
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
          What would you like to do?
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Both options work on the same documents and find the same personal
          information. They differ only in what you get at the end.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {OPTIONS.map((option, i) => (
          <motion.button
            key={option.mode}
            type="button"
            onClick={() => choose(option.mode)}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className={`
              group text-left bg-white rounded-xl border p-5 flex flex-col gap-3
              transition-all btn-press
              ${workflowMode === option.mode
                ? 'border-primary-300 ring-1 ring-primary-100'
                : 'border-slate-200 hover:border-primary-200 hover:shadow-sm'}
            `}
          >
            <div className="flex items-center gap-2.5">
              <span className="text-primary-500">{option.icon}</span>
              <h3 className="text-base font-semibold text-slate-800">{option.title}</h3>
            </div>

            <p className="text-sm text-slate-600 font-medium">{option.blurb}</p>
            <p className="text-xs text-slate-400 leading-relaxed flex-1">{option.detail}</p>

            <code className="text-[11px] bg-slate-50 text-slate-500 rounded-lg px-3 py-2 block">
              {option.example}
            </code>

            <span className="flex items-center gap-1.5 text-sm font-medium text-primary-600 mt-1">
              Choose this
              <ArrowRight
                size={14}
                className="transition-transform group-hover:translate-x-0.5"
              />
            </span>
          </motion.button>
        ))}
      </div>

      <div className="flex items-start gap-3 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
        <ShieldCheck size={18} className="text-slate-400 shrink-0 mt-0.5" />
        <p className="text-sm text-slate-500">
          Either way, everything happens on this computer. Nothing is uploaded,
          and your original files are never changed.
        </p>
      </div>

      {canGoBack && (
        <button
          onClick={() => navigateTo('document_review')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-500
                     hover:bg-slate-100 transition-colors btn-press"
        >
          <ArrowLeft size={16} /> Never mind — go back
        </button>
      )}
    </div>
  );
}
