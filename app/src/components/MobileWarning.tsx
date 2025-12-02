import { useState, useEffect } from 'react';
import { X, DeviceMobile, Info } from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';

export function MobileWarning() {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Check if user has dismissed the warning before
    const dismissed = localStorage.getItem('mobile-warning-dismissed');

    // Show warning on mobile devices (width < 768px) if not dismissed
    if (!dismissed && window.innerWidth < 768) {
      // Delay showing banner slightly for smoother UX
      const timer = setTimeout(() => setIsVisible(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

  const handleDismiss = () => {
    localStorage.setItem('mobile-warning-dismissed', 'true');
    setIsVisible(false);
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ y: -100, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -100, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          className="md:hidden fixed top-0 left-0 right-0 z-[100] safe-area-inset-top"
        >
          <div className="bg-gradient-to-r from-[var(--primary)] to-orange-600 px-4 py-2.5 shadow-lg">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 min-w-0">
                <DeviceMobile size={18} weight="fill" className="text-white/90 flex-shrink-0" />
                <p className="text-white text-xs font-medium truncate">
                  Mobile view active • Some features work best on desktop
                </p>
              </div>
              <button
                onClick={handleDismiss}
                className="flex-shrink-0 p-1.5 rounded-full bg-white/10 hover:bg-white/20 active:bg-white/30 transition-colors"
                aria-label="Dismiss"
              >
                <X size={14} weight="bold" className="text-white" />
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
