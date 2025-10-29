import React from 'react';
import { X, Video, MessageCircle, Calendar, Rocket } from 'lucide-react';

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function HelpModal({ isOpen, onClose }: HelpModalProps) {
  if (!isOpen) return null;

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/80 backdrop-blur-md z-[300] flex items-center justify-center p-6 animate-in fade-in duration-300"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-modal-title"
    >
      <div className="bg-gradient-to-br from-[var(--surface)] to-[var(--bg-dark)] border border-white/10 rounded-[var(--radius)] max-w-4xl w-full max-h-[90vh] overflow-hidden shadow-2xl animate-in fade-in slide-in-from-bottom duration-500">
        {/* Header */}
        <div className="px-6 py-5 border-b border-white/10 flex items-center justify-between">
          <h2 id="help-modal-title" className="font-heading text-2xl font-bold text-[var(--text)]">
            Get Realtime Help
          </h2>
          <button
            onClick={onClose}
            className="w-10 h-10 rounded-lg hover:bg-white/10 transition-all duration-300 flex items-center justify-center text-[var(--text)]/60 hover:text-[var(--text)]"
            aria-label="Close help modal"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
          {/* Video Container */}
          <div className="aspect-video bg-black/30 rounded-2xl mb-6 flex items-center justify-center border border-white/10">
            <div className="text-center text-[var(--text)]/40">
              <Video className="w-16 h-16 mx-auto mb-4" />
              <p>Video tutorial will play here</p>
            </div>
          </div>

          {/* Help Options */}
          <h3 className="font-heading text-xl font-bold text-[var(--text)] mb-4">
            Need Human Help?
          </h3>
          <p className="text-[var(--text)]/60 mb-6">
            Our experts can finish the last 20% of your app to perfection
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Live Chat Support */}
            <div className="bg-white/5 border border-white/10 rounded-2xl p-6 transition-all duration-300 hover:bg-white/10 hover:border-[var(--primary)] hover:-translate-y-1 cursor-pointer group">
              <MessageCircle className="w-10 h-10 text-[var(--primary)] mb-4 group-hover:scale-110 transition-transform duration-300" />
              <h4 className="font-heading text-lg font-bold text-[var(--text)] mb-2">
                Live Chat Support
              </h4>
              <p className="text-sm text-[var(--text)]/60 mb-4">
                Get instant answers from our support team
              </p>
              <button className="w-full py-2 bg-white/5 hover:bg-white/10 rounded-lg transition-all duration-300 text-[var(--text)] font-medium">
                Start Chat
              </button>
            </div>

            {/* Book an Expert */}
            <div className="bg-white/5 border border-white/10 rounded-2xl p-6 transition-all duration-300 hover:bg-white/10 hover:border-[var(--accent)] hover:-translate-y-1 cursor-pointer group">
              <Calendar className="w-10 h-10 text-[var(--accent)] mb-4 group-hover:scale-110 transition-transform duration-300" />
              <h4 className="font-heading text-lg font-bold text-[var(--text)] mb-2">
                Book an Expert
              </h4>
              <p className="text-sm text-[var(--text)]/60 mb-4">
                Schedule a 1-on-1 session with a developer
              </p>
              <button className="w-full py-2 bg-white/5 hover:bg-white/10 rounded-lg transition-all duration-300 text-[var(--text)] font-medium">
                Book Now
              </button>
            </div>

            {/* Done-For-You */}
            <div className="bg-gradient-to-br from-[var(--primary)]/10 to-orange-600/10 border border-[var(--primary)]/30 rounded-2xl p-6 transition-all duration-300 hover:border-[var(--primary)] hover:-translate-y-1 cursor-pointer group">
              <Rocket className="w-10 h-10 text-purple-400 mb-4 group-hover:scale-110 transition-transform duration-300" />
              <h4 className="font-heading text-lg font-bold text-[var(--text)] mb-2">
                Done-For-You
              </h4>
              <p className="text-sm text-[var(--text)]/60 mb-4">
                We'll complete your app from start to finish
              </p>
              <button className="w-full py-2 bg-gradient-to-r from-[var(--primary)] to-orange-600 hover:shadow-lg hover:shadow-[var(--primary)]/25 rounded-lg transition-all duration-300 text-white font-semibold">
                Get Started
              </button>
            </div>
          </div>

          {/* Additional Resources */}
          <div className="mt-8 pt-6 border-t border-white/10">
            <h4 className="font-heading text-lg font-bold text-[var(--text)] mb-4">
              Quick Resources
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <a
                href="#"
                className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all duration-300 text-[var(--text)] hover:text-[var(--primary)] flex items-center gap-3"
              >
                <span className="text-sm">📚 Documentation</span>
              </a>
              <a
                href="#"
                className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all duration-300 text-[var(--text)] hover:text-[var(--primary)] flex items-center gap-3"
              >
                <span className="text-sm">🎓 Video Tutorials</span>
              </a>
              <a
                href="#"
                className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all duration-300 text-[var(--text)] hover:text-[var(--primary)] flex items-center gap-3"
              >
                <span className="text-sm">💬 Community Forum</span>
              </a>
              <a
                href="#"
                className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all duration-300 text-[var(--text)] hover:text-[var(--primary)] flex items-center gap-3"
              >
                <span className="text-sm">❓ FAQ</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
