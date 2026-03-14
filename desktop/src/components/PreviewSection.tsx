import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Eye } from 'lucide-react';
import { api } from '../api';

interface PreviewSectionProps {
  /** Array of { originalPath, redactedPath, filename } */
  documents: { originalPath: string; redactedPath: string; filename: string }[];
}

export default function PreviewSection({ documents }: PreviewSectionProps) {
  const [expanded, setExpanded] = useState(true);
  const [docIndex, setDocIndex] = useState(0);
  const [pageNum, setPageNum] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [originalImg, setOriginalImg] = useState<string | null>(null);
  const [redactedImg, setRedactedImg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const doc = documents[docIndex];

  const loadPage = useCallback(async (dIdx: number, pNum: number) => {
    const d = documents[dIdx];
    if (!d) return;
    setLoading(true);
    setOriginalImg(null);
    setRedactedImg(null);
    try {
      const [orig, redacted] = await Promise.all([
        api.previewPage(d.originalPath, pNum),
        api.previewPage(d.redactedPath, pNum),
      ]);
      setOriginalImg(`data:image/png;base64,${orig.image_base64}`);
      setRedactedImg(`data:image/png;base64,${redacted.image_base64}`);
      setTotalPages(orig.total_pages);
    } catch {
      // Preview failed — not critical
    } finally {
      setLoading(false);
    }
  }, [documents]);

  useEffect(() => {
    if (expanded && documents.length > 0) {
      loadPage(docIndex, pageNum);
    }
  }, [expanded, docIndex, pageNum, loadPage, documents.length]);

  if (documents.length === 0) return null;

  return (
    <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:bg-slate-50 transition-colors"
      >
        <Eye size={14} className="text-primary-500" />
        <span className="flex-1 text-left font-medium">Before & After Preview</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 space-y-4">
              {/* Document tabs */}
              <div className="flex gap-1 overflow-x-auto pb-1">
                {documents.map((d, i) => (
                  <button
                    key={d.filename}
                    onClick={() => { setDocIndex(i); setPageNum(0); }}
                    className={`px-3 py-1.5 text-xs rounded-md whitespace-nowrap shrink-0 transition-colors ${
                      i === docIndex
                        ? 'bg-primary-50 text-primary-700 font-medium'
                        : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {d.filename}
                  </button>
                ))}
              </div>

              {/* Split view */}
              <div className="grid grid-cols-2 gap-3" style={{ maxHeight: '500px' }}>
                <div className="border border-slate-200 rounded-lg overflow-hidden">
                  <div className="bg-slate-50 px-3 py-1.5 text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-200">
                    Original
                  </div>
                  <div className="p-2 flex items-center justify-center min-h-[200px]">
                    {loading ? (
                      <div className="skeleton w-full h-48" />
                    ) : originalImg ? (
                      <img src={originalImg} alt="Original page" className="max-w-full max-h-[440px] object-contain" />
                    ) : (
                      <p className="text-xs text-slate-300">No preview</p>
                    )}
                  </div>
                </div>
                <div className="border border-emerald-200 rounded-lg overflow-hidden">
                  <div className="bg-emerald-50/50 px-3 py-1.5 text-[10px] uppercase tracking-widest text-emerald-500 border-b border-emerald-200">
                    Redacted
                  </div>
                  <div className="p-2 flex items-center justify-center min-h-[200px]">
                    {loading ? (
                      <div className="skeleton w-full h-48" />
                    ) : redactedImg ? (
                      <img src={redactedImg} alt="Redacted page" className="max-w-full max-h-[440px] object-contain" />
                    ) : (
                      <p className="text-xs text-slate-300">No preview</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Page navigation */}
              {totalPages > 0 && (
                <div className="flex items-center justify-center gap-3">
                  <button
                    onClick={() => setPageNum((p) => Math.max(0, p - 1))}
                    disabled={pageNum === 0}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 disabled:opacity-30 transition-colors"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-xs text-slate-500">
                    Page {pageNum + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPageNum((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={pageNum >= totalPages - 1}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 disabled:opacity-30 transition-colors"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
