import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpIcon, Sparkles, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { Textarea } from '../components/ui/textarea';
import { Button } from '../components/ui/button';
import { cn } from '../lib/utils';

interface AutoResizeProps {
  minHeight: number;
  maxHeight?: number;
}

function useAutoResizeTextarea({ minHeight, maxHeight }: AutoResizeProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      if (reset) {
        textarea.style.height = `${minHeight}px`;
        return;
      }

      textarea.style.height = `${minHeight}px`;
      const newHeight = Math.max(
        minHeight,
        Math.min(textarea.scrollHeight, maxHeight ?? Infinity)
      );
      textarea.style.height = `${newHeight}px`;
    },
    [minHeight, maxHeight]
  );

  useEffect(() => {
    if (textareaRef.current) textareaRef.current.style.height = `${minHeight}px`;
  }, [minHeight]);

  return { textareaRef, adjustHeight };
}

export default function NewLandingPage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [showBanner, setShowBanner] = useState(true);
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({
    minHeight: 48,
    maxHeight: 150,
  });

  const handleSubmit = () => {
    if (!message.trim()) {
      toast.error('Please enter a prompt first');
      return;
    }

    // Store the prompt in localStorage
    localStorage.setItem('landingPrompt', message.trim());

    // Check if user is logged in
    const token = localStorage.getItem('token');
    if (token) {
      navigate('/dashboard');
    } else {
      navigate('/register');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div
      className="relative w-full min-h-screen flex flex-col items-center font-['DM_Sans']"
      style={{
        background: 'linear-gradient(135deg, #1a0f00 0%, #0a0500 50%, #000000 100%)',
      }}
    >
      {/* GPT-5 Banner */}
      {showBanner && (
        <div className="w-full bg-gradient-to-r from-orange-600 via-orange-500 to-orange-600 text-white py-3 px-4 relative z-50">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-2 flex-1 justify-center">
              <Sparkles className="w-4 h-4" />
              <span className="text-sm font-semibold">
                🎉 GPT-5 Free for a Limited Time! Get started now →
              </span>
            </div>
            <button
              onClick={() => setShowBanner(false)}
              className="hover:bg-white/20 rounded-full p-1 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Tesslate Logo in top left */}
      <div className="absolute top-8 left-8 z-40">
        <div className="flex items-center gap-3">
          <svg className="w-8 h-8 text-orange-500" viewBox="0 0 161.9 126.66">
            <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
            <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
            <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
          </svg>
          <div>
            <h2 className="text-xl font-bold text-white">Tesslate</h2>
            <p className="text-xs text-orange-400">Build beyond limits</p>
          </div>
        </div>
      </div>

      {/* Login button in top right */}
      <div className="absolute top-8 right-8 z-40">
        <button
          onClick={() => navigate('/login')}
          className="px-6 py-2 rounded-full text-sm font-semibold bg-orange-500 hover:bg-orange-600 text-white transition-colors"
        >
          Sign In
        </button>
      </div>

      {/* Main Content - Centered */}
      <div className="flex-1 w-full flex flex-col items-center justify-center px-4">
        <div className="text-center mb-12">
          <h1 className="text-5xl md:text-7xl font-bold text-white drop-shadow-lg mb-4">
            Tesslate
          </h1>
          <p className="text-xl md:text-2xl text-orange-300 font-semibold">
            Build beyond limits
          </p>
          <p className="mt-4 text-gray-400 max-w-2xl mx-auto">
            Describe your app idea and watch it come to life. Full-stack development powered by AI.
          </p>
        </div>

        {/* Input Box Section */}
        <div className="w-full max-w-3xl">
          <div className="relative bg-black/60 backdrop-blur-md rounded-xl border border-orange-500/30">
            <Textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => {
                setMessage(e.target.value);
                adjustHeight();
              }}
              onKeyDown={handleKeyDown}
              placeholder="Describe what you want to build..."
              className={cn(
                "w-full px-4 py-3 resize-none border-none",
                "bg-transparent text-white text-base",
                "focus-visible:ring-0 focus-visible:ring-offset-0",
                "placeholder:text-gray-500 min-h-[48px]"
              )}
              style={{ overflow: "hidden" }}
            />

            {/* Footer Buttons */}
            <div className="flex items-center justify-between p-3 border-t border-orange-500/20">
              <div className="text-xs text-gray-500">
                Press Enter to submit, Shift+Enter for new line
              </div>

              <div className="flex items-center gap-2">
                <Button
                  onClick={handleSubmit}
                  disabled={!message.trim()}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg font-semibold transition-all",
                    message.trim()
                      ? "bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white shadow-lg shadow-orange-500/50"
                      : "bg-gray-700 text-gray-400 cursor-not-allowed"
                  )}
                >
                  Get Started
                  <ArrowUpIcon className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </div>

          {/* Info text */}
          <p className="text-center text-sm text-gray-500 mt-4">
            No credit card required • Start building in seconds
          </p>
        </div>
      </div>

      {/* Footer */}
      <footer className="w-full py-6 mt-auto">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-gray-500">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5 text-orange-500" viewBox="0 0 161.9 126.66">
                <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
                <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
                <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
              </svg>
              <span className="font-semibold text-white">Tesslate Studio</span>
              <span className="hidden md:inline">•</span>
              <span className="text-orange-400">Build beyond limits</span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-4">
              <a href="#" className="hover:text-orange-400 transition-colors">Features</a>
              <a href="#" className="hover:text-orange-400 transition-colors">Pricing</a>
              <a href="#" className="hover:text-orange-400 transition-colors">Docs</a>
              <a href="#" className="hover:text-orange-400 transition-colors">Support</a>
            </div>
            <div className="text-xs">
              © {new Date().getFullYear()} Tesslate. All rights reserved.
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
