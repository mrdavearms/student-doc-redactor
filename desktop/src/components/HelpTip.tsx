import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle } from 'lucide-react';

interface HelpTipProps {
  text: string;
  className?: string;
}

export default function HelpTip({ text, className = '' }: HelpTipProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-0.5 rounded-full text-slate-300 hover:text-slate-500 transition-colors"
        aria-label="Help"
      >
        <HelpCircle size={14} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 top-full mt-1.5 z-40 w-[280px] bg-white rounded-lg shadow-lg
                       border border-slate-200 px-3.5 py-3"
          >
            <p className="text-xs text-slate-500 leading-relaxed">{text}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
