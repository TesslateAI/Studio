import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpIcon, Sparkles, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { cn } from '../lib/utils';
import { DottedSurface } from '../components/DottedSurface';

export default function NewLandingPage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [showBanner, setShowBanner] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const newHeight = Math.min(textarea.scrollHeight, 200);
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  const handleSubmit = () => {
    if (!message.trim()) {
      toast.error('Please enter a prompt first');
      return;
    }

    localStorage.setItem('landingPrompt', message.trim());
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

  const hasContent = message.trim() !== "";

  return (
    <div className="relative w-full min-h-screen h-screen flex flex-col items-center font-['DM_Sans'] overflow-x-hidden bg-black">
      {/* Dotted Surface Background */}
      <DottedSurface />

      {/* Content layer */}
      <div className="relative z-10 w-full h-full flex flex-col items-center">
        {/* GPT-5 Banner */}
        {showBanner && (
          <div className="fixed top-0 left-0 right-0 w-full bg-gradient-to-r from-orange-600 via-orange-500 to-orange-600 text-white py-2 px-4 z-50">
            <div className="max-w-7xl mx-auto flex items-center justify-between">
              <div className="flex items-center gap-2 flex-1 justify-center">
                <Sparkles className="w-3.5 h-3.5" />
                <span className="text-xs sm:text-sm font-semibold">
                  GPT-5 Free for a Limited Time! Get started now
                </span>
              </div>
              <button
                onClick={() => setShowBanner(false)}
                className="hover:bg-white/20 rounded-full p-1 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* Tesslate Logo in top left */}
        <div className="fixed top-4 left-4 sm:top-8 sm:left-8 z-40" style={{ marginTop: showBanner ? '36px' : '0' }}>
          <div className="flex items-center gap-2 sm:gap-3">
            <svg className="w-6 h-6 sm:w-8 sm:h-8 text-orange-500" viewBox="0 0 161.9 126.66">
              <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
              <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
              <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
            </svg>
            <div>
              <h2 className="text-base sm:text-xl font-bold text-white drop-shadow-lg">Tesslate</h2>
              <p className="text-[10px] sm:text-xs text-orange-400">Build beyond limits</p>
            </div>
          </div>
        </div>

        {/* Login button in top right */}
        <div className="fixed top-4 right-4 sm:top-8 sm:right-8 z-40" style={{ marginTop: showBanner ? '36px' : '0' }}>
          <button
            onClick={() => navigate('/login')}
            className="px-4 sm:px-6 py-1.5 sm:py-2 rounded-full text-xs sm:text-sm font-semibold bg-orange-500 hover:bg-orange-600 text-white transition-colors shadow-lg shadow-orange-500/30"
          >
            Sign In
          </button>
        </div>

        {/* Centered Title and Input Section */}
        <div className="flex-1 w-full flex flex-col items-center justify-center px-4 gap-8 sm:gap-12">
          <div className="text-center">
            <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold text-white drop-shadow-lg">
              Tesslate
            </h1>
            <p className="mt-2 sm:mt-3 text-lg sm:text-xl md:text-2xl text-neutral-200 font-medium">
              Make full stack apps. Change your system prompts. Sell your coding agents.
            </p>
          </div>

          {/* Input Box Section - PromptBox styled */}
          <div className="w-full max-w-3xl px-4 sm:px-6">
          <div
            className="flex flex-col rounded-[20px] sm:rounded-[28px] p-1.5 sm:p-2 shadow-sm transition-colors cursor-text"
            style={{
              backgroundColor: '#000000',
              borderWidth: '1px',
              borderStyle: 'solid',
              borderColor: 'rgb(249, 115, 22)',
              boxShadow: '0 8px 30px rgba(249, 115, 22, 0.3)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = '0 12px 40px rgba(249, 115, 22, 0.4)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.3)';
            }}
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe what you want to build..."
              className={cn(
                "w-full resize-none border-0 bg-transparent p-2.5 sm:p-3 text-sm sm:text-base text-white",
                "placeholder:text-gray-400 focus:ring-0 focus:outline-none focus-visible:outline-none focus:border-0 min-h-12"
              )}
              style={{
                scrollbarWidth: 'thin',
                scrollbarColor: '#444444 transparent',
                outline: 'none',
                boxShadow: 'none',
              }}
            />

            <div className="mt-0.5 p-1 pt-0">
              <div className="flex items-center gap-2">
                <div className="ml-auto flex items-center gap-2">
                  <button
                    type="submit"
                    onClick={handleSubmit}
                    disabled={!hasContent}
                    className={cn(
                      "flex h-9 w-9 sm:h-8 sm:w-8 items-center justify-center rounded-full text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none touch-manipulation",
                      hasContent
                        ? "text-white"
                        : "text-gray-400"
                    )}
                    style={hasContent ? {
                      backgroundColor: 'rgb(249, 115, 22)',
                      boxShadow: '0 4px 14px rgba(249, 115, 22, 0.5)',
                    } : {
                      backgroundColor: 'rgba(81, 81, 81, 0.4)',
                    }}
                    onMouseEnter={(e) => {
                      if (hasContent) {
                        e.currentTarget.style.backgroundColor = 'rgb(234, 88, 12)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (hasContent) {
                        e.currentTarget.style.backgroundColor = 'rgb(249, 115, 22)';
                      }
                    }}
                  >
                    <ArrowUpIcon className="h-5 w-5" />
                    <span className="sr-only">Send message</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
