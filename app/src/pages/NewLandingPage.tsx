import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpIcon, Sparkles, X, Github, BookOpen, Code2, Boxes } from 'lucide-react';
import toast from 'react-hot-toast';
import { cn } from '../lib/utils';
import { DottedSurface } from '../components/DottedSurface';

export default function NewLandingPage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [showBanner, setShowBanner] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Generate star positions once
  const stars = Array.from({ length: 700 }, (_, i) => ({
    id: i,
    left: `${Math.random() * 100}%`,
    top: `${Math.random() * 100}%`,
    size: Math.random() > 0.7 ? 2 : 1,
    opacity: 0.3 + Math.random() * 0.7,
    animationDelay: `${Math.random() * 3}s`,
  }));

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
    <div
      className="relative w-full min-h-screen flex flex-col items-center font-['DM_Sans'] overflow-x-hidden overflow-y-auto bg-black"
      style={{
        scrollbarWidth: 'none',
        msOverflowStyle: 'none',
        WebkitOverflowScrolling: 'touch'
      }}
    >
      <style>{`
        .relative.w-full.min-h-screen::-webkit-scrollbar {
          display: none;
        }
      `}</style>
      {/* Starry background effect */}
      <div className="absolute inset-0 z-0">
        {stars.map((star) => (
          <div
            key={star.id}
            className="absolute rounded-full bg-white animate-pulse"
            style={{
              left: star.left,
              top: star.top,
              width: `${star.size}px`,
              height: `${star.size}px`,
              opacity: star.opacity,
              animationDelay: star.animationDelay,
              animationDuration: '3s',
            }}
          />
        ))}
      </div>

      {/* Dotted Surface Background (Sea) */}
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
        <div className="fixed top-4 left-4 sm:top-8 sm:left-8 z-40" style={{ marginTop: showBanner ? '44px' : '0' }}>
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
        <div className="fixed top-4 right-4 sm:top-8 sm:right-8 z-40" style={{ marginTop: showBanner ? '44px' : '0' }}>
          <button
            onClick={() => navigate('/login')}
            className="px-4 sm:px-6 py-1.5 sm:py-2 rounded-full text-xs sm:text-sm font-semibold bg-orange-500 hover:bg-orange-600 text-white transition-colors shadow-lg shadow-orange-500/30"
          >
            Sign In
          </button>
        </div>

        {/* Centered Title and Input Section */}
        <div className="flex-1 w-full flex flex-col items-center justify-center px-4 gap-3 sm:gap-5 md:gap-8 py-20 sm:py-6 md:py-8" style={{ paddingTop: showBanner ? '120px' : '100px' }}>
          <div className="text-center space-y-1.5 sm:space-y-3 md:space-y-4">
            <pre
              className="text-[8px] sm:text-xs md:text-sm lg:text-base xl:text-lg leading-tight overflow-x-auto"
              style={{
                color: '#f97316',
                fontFamily: 'monospace',
                fontWeight: 'bold'
              }}
            >
{`████████╗███████╗███████╗███████╗██╗      █████╗ ████████╗███████╗
╚══██╔══╝██╔════╝██╔════╝██╔════╝██║     ██╔══██╗╚══██╔══╝██╔════╝
   ██║   █████╗  ███████╗███████╗██║     ███████║   ██║   █████╗
   ██║   ██╔══╝  ╚════██║╚════██║██║     ██╔══██║   ██║   ██╔══╝
   ██║   ███████╗███████║███████║███████╗██║  ██║   ██║   ███████╗
   ╚═╝   ╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝`}
            </pre>
            <p className="mt-1.5 sm:mt-3 md:mt-4 text-sm sm:text-lg md:text-xl lg:text-2xl xl:text-3xl text-neutral-200 font-semibold max-w-4xl mx-auto leading-relaxed px-2">
              Make full stack apps. Change your system prompts.
            </p>
            <p className="text-xs sm:text-base md:text-lg lg:text-xl text-orange-400 font-medium">
              Sell your coding agents.
            </p>
          </div>

          {/* Input Box Section - Enhanced PromptBox */}
          <div className="w-full max-w-4xl px-3 sm:px-4 md:px-6">
            <div
              className="flex flex-col rounded-[24px] sm:rounded-[32px] p-2 sm:p-2.5 shadow-2xl transition-all duration-300 cursor-text backdrop-blur-sm"
              style={{
                backgroundColor: 'rgba(0, 0, 0, 0.6)',
                borderWidth: '2px',
                borderStyle: 'solid',
                borderColor: 'rgb(249, 115, 22)',
                boxShadow: '0 10px 40px rgba(249, 115, 22, 0.4), 0 0 80px rgba(249, 115, 22, 0.2)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = '0 15px 50px rgba(249, 115, 22, 0.5), 0 0 100px rgba(249, 115, 22, 0.3)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = '0 10px 40px rgba(249, 115, 22, 0.4), 0 0 80px rgba(249, 115, 22, 0.2)';
                e.currentTarget.style.transform = 'translateY(0)';
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
                  "w-full resize-none border-0 bg-transparent p-3 sm:p-4 text-base sm:text-lg text-white",
                  "placeholder:text-gray-400 focus:ring-0 focus:outline-none focus-visible:outline-none focus:border-0 min-h-14"
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
                        "flex h-10 w-10 sm:h-11 sm:w-11 items-center justify-center rounded-full text-sm font-medium transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none touch-manipulation",
                        hasContent
                          ? "text-white scale-100 hover:scale-110"
                          : "text-gray-400"
                      )}
                      style={hasContent ? {
                        backgroundColor: 'rgb(249, 115, 22)',
                        boxShadow: '0 4px 20px rgba(249, 115, 22, 0.6)',
                      } : {
                        backgroundColor: 'rgba(81, 81, 81, 0.4)',
                      }}
                      onMouseEnter={(e) => {
                        if (hasContent) {
                          e.currentTarget.style.backgroundColor = 'rgb(234, 88, 12)';
                          e.currentTarget.style.boxShadow = '0 6px 25px rgba(249, 115, 22, 0.7)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (hasContent) {
                          e.currentTarget.style.backgroundColor = 'rgb(249, 115, 22)';
                          e.currentTarget.style.boxShadow = '0 4px 20px rgba(249, 115, 22, 0.6)';
                        }
                      }}
                    >
                      <ArrowUpIcon className="h-5 w-5 sm:h-6 sm:w-6" />
                      <span className="sr-only">Send message</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Links Section - GitHub & Docs */}
          <div className="w-full max-w-5xl px-3 sm:px-4 md:px-6 mt-4 sm:mt-6 md:mt-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 sm:gap-4 md:gap-6">
              {/* Studio Open Source */}
              <a
                href="https://github.com/tesslateAI/Studio"
                target="_blank"
                rel="noopener noreferrer"
                className="group relative overflow-hidden rounded-2xl transition-all duration-300 hover:scale-105"
                style={{
                  backgroundColor: '#1a1a1a',
                  border: '1px solid rgba(255, 107, 0, 0.2)',
                  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(249, 115, 22, 0.5)';
                  e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.3)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 107, 0, 0.2)';
                  e.currentTarget.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.5)';
                }}
              >
                {/* Image */}
                <div className="relative w-full h-24 sm:h-32 md:h-40 overflow-hidden">
                  <img
                    src="https://github.com/TesslateAI/Studio/raw/main/images/Banner.png"
                    alt="Studio Banner"
                    className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-[#1a1a1a] to-transparent"></div>
                </div>

                {/* Content */}
                <div className="p-3 sm:p-4 md:p-5">
                  <div className="flex items-start gap-2 sm:gap-3 mb-2 sm:mb-3">
                    <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-orange-500 flex items-center justify-center">
                      <Code2 className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-orange-400 transition-colors">
                        Studio Open Source
                      </h3>
                      <p className="text-xs sm:text-sm text-gray-400 leading-tight">
                        This app, fully open source
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 sm:gap-2 text-xs text-gray-500">
                    <Github className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                    <span>View on GitHub</span>
                  </div>
                </div>
              </a>

              {/* Multi-Agent Orchestration */}
              <a
                href="https://github.com/tesslateAI/"
                target="_blank"
                rel="noopener noreferrer"
                className="group relative overflow-hidden rounded-2xl transition-all duration-300 hover:scale-105"
                style={{
                  backgroundColor: '#1a1a1a',
                  border: '1px solid rgba(255, 107, 0, 0.2)',
                  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(249, 115, 22, 0.5)';
                  e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.3)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 107, 0, 0.2)';
                  e.currentTarget.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.5)';
                }}
              >
                {/* Image */}
                <div className="relative w-full h-24 sm:h-32 md:h-40 overflow-hidden">
                  <img
                    src="https://github.com/TesslateAI/Agent-Builder/raw/main/docs/assets/images/banner.jpeg"
                    alt="Agent Builder Banner"
                    className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-[#1a1a1a] to-transparent"></div>
                </div>

                {/* Content */}
                <div className="p-3 sm:p-4 md:p-5">
                  <div className="flex items-start gap-2 sm:gap-3 mb-2 sm:mb-3">
                    <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-orange-500 flex items-center justify-center">
                      <Boxes className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-orange-400 transition-colors">
                        Multi-Agent Orchestration
                      </h3>
                      <p className="text-xs sm:text-sm text-gray-400 leading-tight">
                        n8n but better, AI workflow automation
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 sm:gap-2 text-xs text-gray-500">
                    <Github className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                    <span>Explore All Apps</span>
                  </div>
                </div>
              </a>

              {/* Documentation */}
              <a
                href="https://docs.tesslate.com"
                target="_blank"
                rel="noopener noreferrer"
                className="group relative overflow-hidden rounded-2xl transition-all duration-300 hover:scale-105"
                style={{
                  backgroundColor: '#1a1a1a',
                  border: '1px solid rgba(255, 107, 0, 0.2)',
                  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(249, 115, 22, 0.5)';
                  e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.3)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 107, 0, 0.2)';
                  e.currentTarget.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.5)';
                }}
              >
                {/* Gradient background instead of image */}
                <div className="relative w-full h-24 sm:h-32 md:h-40 overflow-hidden bg-gradient-to-br from-orange-600 via-orange-500 to-orange-400">
                  <div className="absolute inset-0 flex items-center justify-center">
                    <BookOpen className="w-16 sm:w-20 h-16 sm:h-20 text-white opacity-20" />
                  </div>
                  <div className="absolute inset-0 bg-gradient-to-t from-[#1a1a1a] to-transparent"></div>
                </div>

                {/* Content */}
                <div className="p-3 sm:p-4 md:p-5">
                  <div className="flex items-start gap-2 sm:gap-3 mb-2 sm:mb-3">
                    <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-orange-500 flex items-center justify-center">
                      <BookOpen className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-orange-400 transition-colors">
                        Documentation
                      </h3>
                      <p className="text-xs sm:text-sm text-gray-400 leading-tight">
                        Learn how to use Tesslate
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 sm:gap-2 text-xs text-gray-500">
                    <BookOpen className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                    <span>Read the Docs</span>
                  </div>
                </div>
              </a>
            </div>
          </div>

          {/* Additional tagline */}
          <div className="text-center mt-2 sm:mt-4 pb-4 sm:pb-6">
            <p className="text-xs sm:text-sm text-gray-500">
              Open source • Community driven •{' '}
              <a
                href="https://discord.gg/WgXabcN2r2"
                target="_blank"
                rel="noopener noreferrer"
                className="text-orange-400 hover:text-orange-500 transition-colors underline"
              >
                Give us feedback
              </a>
            </p>
          </div>
        </div>
      </div>

    </div>
  );
}
