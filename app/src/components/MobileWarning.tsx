import { useState, useEffect } from 'react';
import { X, Desktop } from '@phosphor-icons/react';

export function MobileWarning() {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Check if user has dismissed the warning before
    const dismissed = localStorage.getItem('mobile-warning-dismissed');

    // Show warning on mobile devices (width < 768px) if not dismissed
    if (!dismissed && window.innerWidth < 768) {
      setIsVisible(true);
    }
  }, []);

  const handleDismiss = () => {
    localStorage.setItem('mobile-warning-dismissed', 'true');
    setIsVisible(false);
  };

  if (!isVisible) return null;

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-[100] flex items-center justify-center p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-3xl max-w-md w-full shadow-2xl relative overflow-hidden">
        {/* Close Button */}
        <button
          onClick={handleDismiss}
          className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-[var(--text)] z-10"
        >
          <X size={24} weight="bold" />
        </button>

        {/* Content */}
        <div className="p-8 text-center">
          {/* Icon */}
          <div className="mb-6">
            <div className="w-20 h-20 mx-auto bg-gradient-to-br from-orange-500/20 to-orange-600/20 rounded-2xl flex items-center justify-center">
              <Desktop size={48} weight="duotone" className="text-[var(--primary)]" />
            </div>
          </div>

          {/* Title */}
          <h2 className="font-heading text-2xl font-bold text-[var(--text)] mb-4">
            Best Experienced on Desktop
          </h2>

          {/* Message */}
          <p className="text-[var(--text)]/70 text-base leading-relaxed mb-6">
            Tesslate Studio is optimized for desktop and computer environments.
            For the best experience with all features, please access from a larger screen.
          </p>

          {/* Dismiss Button */}
          <button
            onClick={handleDismiss}
            className="w-full bg-gradient-to-r from-[var(--primary)] to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white font-semibold py-3 px-6 rounded-xl transition-all hover:shadow-lg"
          >
            Continue Anyway
          </button>
        </div>

        {/* Decorative gradient */}
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-orange-500 via-orange-600 to-orange-500" />
      </div>
    </div>
  );
}
