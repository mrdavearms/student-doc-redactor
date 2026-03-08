import { AnimatePresence, motion } from 'framer-motion';
import Sidebar from './Sidebar';
import { useStore } from '../store';

const pageVariants = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -12 },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  const currentScreen = useStore((s) => s.currentScreen);
  const loading = useStore((s) => s.loading);
  const loadingMessage = useStore((s) => s.loadingMessage);

  return (
    <div className="flex h-full">
      <Sidebar />

      <main className="flex-1 overflow-y-auto relative">
        {/* Loading overlay */}
        <AnimatePresence>
          {loading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 z-50 bg-white/80 backdrop-blur-sm flex items-center justify-center"
            >
              <div className="flex flex-col items-center gap-3">
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
                  className="w-8 h-8 border-3 border-primary-200 border-t-primary-600 rounded-full"
                />
                <p className="text-sm text-slate-500">{loadingMessage}</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Page content with animated transitions */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentScreen}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="p-8 max-w-4xl mx-auto"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
