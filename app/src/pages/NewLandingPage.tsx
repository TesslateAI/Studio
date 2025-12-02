import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowUpIcon, Sparkles, X, Github, BookOpen, Code2, Boxes,
  Check, Star, Users, Zap, Globe, MessageSquare,
  TrendingUp, ChevronDown, PlayCircle, ArrowRight,
  Package, Settings, Share2, Shield
} from 'lucide-react';
import toast from 'react-hot-toast';
import { cn } from '../lib/utils';

export default function NewLandingPage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [showBanner, setShowBanner] = useState(true);
  const [expandedFAQ, setExpandedFAQ] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroRef = useRef<HTMLDivElement>(null);

  // Hyperspace Jump Effect
  useEffect(() => {
    const canvas = canvasRef.current;
    const heroContainer = heroRef.current;
    if (!canvas || !heroContainer) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    // Site color scheme - orange based
    const WARP_COLORS = [
      [249, 115, 22],  // Primary orange #f97316
      [234, 88, 12],   // Darker orange
      [251, 146, 60],  // Lighter orange
      [255, 255, 255], // White
      [253, 186, 116], // Pale orange
    ];

    const randomInRange = (min: number, max: number) =>
      Math.random() * (max - min) + min;

    class Star {
      x: number;
      y: number;
      z: number;
      prevZ: number;

      constructor(width: number, height: number) {
        this.x = randomInRange(-width / 2, width / 2);
        this.y = randomInRange(-height / 2, height / 2);
        // Distribute stars evenly across the depth - no stars too close
        this.z = randomInRange(width * 0.3, width);
        this.prevZ = this.z;
      }

      update(speed: number, width: number, height: number) {
        this.prevZ = this.z;
        this.z -= speed;

        // Reset star when it gets too close
        if (this.z < 1) {
          this.x = randomInRange(-width / 2, width / 2);
          this.y = randomInRange(-height / 2, height / 2);
          this.z = width;
          this.prevZ = this.z;
        }
      }

      draw(ctx: CanvasRenderingContext2D, width: number, height: number, jumping: boolean) {
        const sx = (this.x / this.z) * width + width / 2;
        const sy = (this.y / this.z) * height + height / 2;
        const px = (this.x / this.prevZ) * width + width / 2;
        const py = (this.y / this.prevZ) * height + height / 2;

        // More visible size
        const size = Math.max((1 - this.z / width) * 2, 0.5);

        // Better opacity - more visible throughout
        const depthRatio = this.z / width;
        const alpha = Math.max(1 - depthRatio * 0.7, 0.3);

        let color = `rgba(255, 255, 255, ${alpha})`;
        if (jumping) {
          const [r, g, b] = WARP_COLORS[Math.floor(Math.random() * WARP_COLORS.length)];
          color = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        }

        ctx.strokeStyle = color;
        ctx.lineWidth = size;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(sx, sy);
        ctx.stroke();
      }
    }

    const setup = () => {
      context.lineCap = 'round';

      // Get the hero section dimensions
      const parent = canvas.parentElement;
      if (parent) {
        const rect = parent.getBoundingClientRect();
        canvas.width = rect.width || window.innerWidth;
        canvas.height = rect.height || window.innerHeight;
      } else {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
      }

      console.log('Canvas setup:', canvas.width, 'x', canvas.height);
    };

    // Initial setup
    setup();

    // Progressive star loading for snappy initial load + rich experience
    const INITIAL_STARS = 50; // Minimal stars for instant page load (Lighthouse score)
    const TARGET_STARS = window.innerWidth < 768 ? 400 : 800; // Full count after lazy load
    const STARS_PER_BATCH = 50; // Add stars in batches

    const stars: Star[] = [];
    // Start with minimal stars for blazing fast initial page load
    for (let i = 0; i < INITIAL_STARS; i++) {
      stars.push(new Star(canvas.width || 1920, canvas.height || 1080));
    }

    let speed = 0.8; // Constant slow speed
    let targetSpeed = 0.8;
    let jumping = false;
    let isPressed = false;
    let pressStartTime = 0;
    let animationFrameId: number;
    let lastFrameTime = 0;
    const targetFPS = 60;
    const frameInterval = 1000 / targetFPS;

    // Lazy load more stars progressively after initial render
    let starsLoaded = INITIAL_STARS;
    const loadMoreStars = () => {
      if (starsLoaded >= TARGET_STARS) return;

      const batchSize = Math.min(STARS_PER_BATCH, TARGET_STARS - starsLoaded);
      for (let i = 0; i < batchSize; i++) {
        stars.push(new Star(canvas.width || 1920, canvas.height || 1080));
      }
      starsLoaded += batchSize;

      console.log(`Loaded ${starsLoaded}/${TARGET_STARS} stars`);

      if (starsLoaded < TARGET_STARS) {
        // Continue loading more stars every 100ms (smooth progressive loading)
        setTimeout(loadMoreStars, 100);
      }
    };

    // Start lazy loading stars after page is interactive (300ms delay)
    setTimeout(loadMoreStars, 300);

    const lerp = (start: number, end: number, amount: number) => {
      return start + (end - start) * amount;
    };

    const render = (timestamp: number = 0) => {
      // FPS throttling for consistent performance
      const elapsed = timestamp - lastFrameTime;
      if (elapsed < frameInterval) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }
      lastFrameTime = timestamp - (elapsed % frameInterval);

      // Semi-transparent clear for star trails (optimized opacity)
      context.fillStyle = 'rgba(0, 0, 0, 0.12)';
      context.fillRect(0, 0, canvas.width, canvas.height);

      // Only transition speed when user interacts
      if (isPressed || jumping) {
        speed = lerp(speed, targetSpeed, 0.08);
      } else {
        speed = 0.8; // Keep constant slow speed when not interacting
      }

      // Draw stars
      const starsLength = stars.length;
      for (let i = 0; i < starsLength; i++) {
        stars[i].update(speed, canvas.width, canvas.height);
        stars[i].draw(context, canvas.width, canvas.height, jumping);
      }

      animationFrameId = requestAnimationFrame(render);
    };

    const isInteractiveElement = (target: HTMLElement): boolean => {
      // Check if target or any parent is an interactive element
      let element: HTMLElement | null = target;
      while (element && element !== heroContainer) {
        const tagName = element.tagName;
        if (tagName === 'BUTTON' || tagName === 'A' || tagName === 'INPUT' ||
            tagName === 'TEXTAREA' || tagName === 'SELECT') {
          return true;
        }
        // Also check if element has click handlers
        if (element.onclick || element.getAttribute('role') === 'button') {
          return true;
        }
        element = element.parentElement;
      }
      return false;
    };

    const initiate = (e: Event) => {
      // Don't trigger on interactive elements
      const target = e.target as HTMLElement;
      if (isInteractiveElement(target)) {
        return;
      }

      if (jumping) return;

      isPressed = true;
      pressStartTime = Date.now();
      targetSpeed = 10; // Speed up when holding

      console.log('Initiate hyperspace - hold to jump!');
    };

    const release = (e: Event) => {
      // Don't trigger on interactive elements
      const target = e.target as HTMLElement;
      if (isInteractiveElement(target)) {
        return;
      }

      if (jumping || !isPressed) return;

      isPressed = false;
      const holdDuration = Date.now() - pressStartTime;

      console.log('Release - Hold duration:', holdDuration, 'ms');

      if (holdDuration > 500) {
        // Trigger hyperspace jump
        console.log('🚀 Jumping to hyperspace!');
        jumping = true;
        targetSpeed = 60;

        setTimeout(() => {
          jumping = false;
          targetSpeed = 0.8; // Return to slow speed
          console.log('✨ Returned from hyperspace');
        }, 2500);
      } else {
        // Quick click - just return to normal
        console.log('Quick click - hold longer for hyperspace jump');
        targetSpeed = 0.8;
      }
    };

    // Debounced resize handler for better performance
    let resizeTimeout: NodeJS.Timeout;
    const handleResize = () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        setup();
        const newTargetStars = window.innerWidth < 768 ? 400 : 800;
        stars.length = 0;
        starsLoaded = 0;

        // Start with minimal stars on resize too
        for (let i = 0; i < INITIAL_STARS; i++) {
          stars.push(new Star(canvas.width, canvas.height));
        }
        starsLoaded = INITIAL_STARS;

        // Lazy load the rest
        const loadAfterResize = () => {
          if (starsLoaded >= newTargetStars) return;
          const batchSize = Math.min(STARS_PER_BATCH, newTargetStars - starsLoaded);
          for (let i = 0; i < batchSize; i++) {
            stars.push(new Star(canvas.width, canvas.height));
          }
          starsLoaded += batchSize;
          if (starsLoaded < newTargetStars) {
            setTimeout(loadAfterResize, 100);
          }
        };
        setTimeout(loadAfterResize, 100);
      }, 150); // Debounce resize by 150ms
    };

    // Add event listeners to both canvas and hero container
    const addListeners = (element: HTMLElement) => {
      element.addEventListener('mousedown', initiate, { passive: true });
      element.addEventListener('touchstart', initiate, { passive: true });
      element.addEventListener('mouseup', release, { passive: true });
      element.addEventListener('touchend', release, { passive: true });
      element.addEventListener('mouseleave', release, { passive: true });
    };

    const removeListeners = (element: HTMLElement) => {
      element.removeEventListener('mousedown', initiate);
      element.removeEventListener('touchstart', initiate);
      element.removeEventListener('mouseup', release);
      element.removeEventListener('touchend', release);
      element.removeEventListener('mouseleave', release);
    };

    addListeners(canvas);
    addListeners(heroContainer);
    window.addEventListener('resize', handleResize, { passive: true });

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      clearTimeout(resizeTimeout);
      removeListeners(canvas);
      removeListeners(heroContainer);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const newHeight = Math.min(textarea.scrollHeight, 200);
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  const handleSubmit = useCallback(() => {
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
  }, [message, navigate]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const hasContent = message.trim() !== "";

  const faqs = [
    {
      question: "Is Tesslate really open source?",
      answer: "Yes! Tesslate is fully open-source under the Apache 2.0 license. You can view, modify, and fork our entire codebase on GitHub. Everything from the core platform to individual agents is transparent and community-driven."
    },
    {
      question: "Can I self-host?",
      answer: "Absolutely. Tesslate supports local hosting, VPC deployment, on-prem infrastructure, or cloud hosting. Run it on your laptop, GPU rig, or enterprise servers—you have complete control."
    },
    {
      question: "Can I use my own models?",
      answer: "Yes! Tesslate works with any LLM—OpenAI, Anthropic, Mistral, Llama, Qwen, or your custom fine-tuned models. You're not locked into any single provider."
    },
    {
      question: "Do I keep my code?",
      answer: "100%. All generated code is yours—no strings attached. Export to GitHub, Docker, Kubernetes, or any runtime. No vendor lock-in, no black boxes."
    },
    {
      question: "Is this safe for enterprises?",
      answer: "Yes. We offer private runners, full audit logs, RBAC, SSO integration, and ensure no data leaves your environment. Perfect for compliance-heavy industries."
    },
    {
      question: "How does monetization work?",
      answer: "Publish agents to the Tesslate Marketplace and earn recurring income. You can monetize them publicly or share them privately within your enterprise teams."
    }
  ];

  return (
    <div
        className="relative w-full min-h-screen flex flex-col items-center font-['DM_Sans'] overflow-x-hidden"
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
        @keyframes marquee {
          0% { transform: translateX(0%); }
          100% { transform: translateX(-100%); }
        }
        .marquee-container {
          -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,0) 0%, rgb(0,0,0) 12.5%, rgb(0,0,0) 87.5%, rgba(0,0,0,0) 100%);
          mask-image: linear-gradient(to right, rgba(0,0,0,0) 0%, rgb(0,0,0) 12.5%, rgb(0,0,0) 87.5%, rgba(0,0,0,0) 100%);
        }
        .marquee-content {
          animation: marquee 30s linear infinite;
        }
        .startup-logo img {
          height: 36px;
          filter: grayscale(100%) contrast(0%) brightness(1.5);
          opacity: 0.7;
          transition: all 0.3s ease-in-out;
        }
        .startup-logo a:hover img {
          filter: grayscale(0%);
          opacity: 1;
          transform: scale(1.1);
        }
      `}</style>

      {/* HERO SECTION - WITH HYPERSPACE JUMP EFFECT */}
      <div ref={heroRef} className="relative w-full bg-black overflow-hidden" style={{ minHeight: '100vh', cursor: 'pointer' }}>
        {/* Hyperspace canvas - ONLY IN HERO */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 z-0 w-full h-full"
          style={{
            cursor: 'pointer',
            display: 'block',
            touchAction: 'none',
            userSelect: 'none',
            willChange: 'contents',
            transform: 'translateZ(0)', // Force hardware acceleration
          }}
        />

        {/* Content layer */}
        <div className="relative z-10 w-full" style={{ pointerEvents: 'auto' }}>
          {/* GPT-5 Banner */}
          {showBanner && (
            <div className="fixed top-0 left-0 right-0 w-full bg-gradient-to-r from-[var(--primary-hover)] via-[var(--primary)] to-[var(--primary-hover)] text-white py-2 px-4 z-50">
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
              <svg className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" viewBox="0 0 161.9 126.66">
                <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
                <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
                <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
              </svg>
              <div>
                <h2 className="text-base sm:text-xl font-bold text-white drop-shadow-lg">Tesslate</h2>
                <p className="text-[10px] sm:text-xs text-gray-400">Build beyond limits</p>
              </div>
            </div>
          </div>

          {/* Login and GitHub buttons in top right */}
          <div className="fixed top-4 right-4 sm:top-8 sm:right-8 z-40 flex items-center gap-2 sm:gap-3" style={{ marginTop: showBanner ? '44px' : '0' }}>
            <a
              href="https://github.com/TesslateAI/Studio"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-full text-xs sm:text-sm font-semibold bg-white/10 hover:bg-white/20 text-white transition-colors backdrop-blur-sm border border-white/20"
            >
              <Github className="w-3 h-3 sm:w-4 sm:h-4" />
              <Star className="w-3 h-3 sm:w-4 sm:h-4" />
              <span className="hidden sm:inline">Star us</span>
            </a>
            <button
              onClick={() => navigate('/login')}
              className="px-4 sm:px-6 py-1.5 sm:py-2 rounded-full text-xs sm:text-sm font-semibold bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white transition-colors shadow-lg shadow-[rgba(var(--primary-rgb),0.3)]"
            >
              Sign In
            </button>
          </div>

          {/* Centered Title and Input Section */}
          <div className="flex-1 w-full flex flex-col items-center justify-center px-4 gap-3 sm:gap-5 md:gap-8 py-20 sm:py-6 md:py-8" style={{ paddingTop: showBanner ? '120px' : '100px', minHeight: '70vh' }}>
            <header className="text-center space-y-1.5 sm:space-y-3 md:space-y-4">
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
              <h1 className="mt-1.5 sm:mt-3 md:mt-4 text-sm sm:text-lg md:text-xl lg:text-2xl xl:text-3xl text-neutral-200 font-semibold max-w-4xl mx-auto leading-relaxed px-2">
                Your open source AI product team
              </h1>
              <p className="text-xs sm:text-base md:text-lg text-[var(--primary)] font-medium max-w-5xl mx-auto px-4">
                Build full-stack apps 10× faster with complete control—deploy locally or in your cloud, use any model, ensure data privacy, and enjoy zero vendor lock-in.
              </p>
            </header>

            {/* Input Box Section */}
            <div className="w-full max-w-4xl px-3 sm:px-4 md:px-6">
              <div
                className="flex flex-col rounded-[24px] sm:rounded-[32px] p-2 sm:p-2.5 shadow-2xl transition-all duration-300 cursor-text"
                style={{
                  backgroundColor: '#1a1a1a',
                  borderWidth: '2px',
                  borderStyle: 'solid',
                  borderColor: '#525252',
                  boxShadow: '0 10px 40px rgba(0, 0, 0, 0.5)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = '#f97316';
                  e.currentTarget.style.boxShadow = '0 15px 50px rgba(249, 115, 22, 0.3), 0 0 80px rgba(249, 115, 22, 0.15)';
                  e.currentTarget.style.transform = 'translateY(-2px)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = '#525252';
                  e.currentTarget.style.boxShadow = '0 10px 40px rgba(0, 0, 0, 0.5)';
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
                          backgroundColor: '#515151',
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

            {/* Links Section - GitHub & Docs - ORIGINAL 3 CARDS */}
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
                    border: '1px solid #525252',
                    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#f97316';
                    e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.2)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#525252';
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
                      <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-[var(--primary)] flex items-center justify-center">
                        <Code2 className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-[var(--primary)] transition-colors">
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

                {/* All Tesslate Apps */}
                <a
                  href="https://github.com/tesslateAI/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group relative overflow-hidden rounded-2xl transition-all duration-300 hover:scale-105"
                  style={{
                    backgroundColor: '#1a1a1a',
                    border: '1px solid #525252',
                    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#f97316';
                    e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.2)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#525252';
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
                      <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-[var(--primary)] flex items-center justify-center">
                        <Boxes className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-[var(--primary)] transition-colors">
                          All Tesslate Apps
                        </h3>
                        <p className="text-xs sm:text-sm text-gray-400 leading-tight">
                          Agent orchestration, Designer, Forge, Wise, and more open source frameworks
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
                    border: '1px solid #525252',
                    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#f97316';
                    e.currentTarget.style.boxShadow = '0 8px 30px rgba(249, 115, 22, 0.2)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#525252';
                    e.currentTarget.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.5)';
                  }}
                >
                  {/* Gradient background instead of image */}
                  <div className="relative w-full h-24 sm:h-32 md:h-40 overflow-hidden bg-gradient-to-br from-[var(--primary-hover)] via-[var(--primary)] to-[var(--primary)]">
                    <div className="absolute inset-0 flex items-center justify-center">
                      <BookOpen className="w-16 sm:w-20 h-16 sm:h-20 text-white opacity-20" />
                    </div>
                    <div className="absolute inset-0 bg-gradient-to-t from-[#1a1a1a] to-transparent"></div>
                  </div>

                  {/* Content */}
                  <div className="p-3 sm:p-4 md:p-5">
                    <div className="flex items-start gap-2 sm:gap-3 mb-2 sm:mb-3">
                      <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-[var(--primary)] flex items-center justify-center">
                        <BookOpen className="w-4 h-4 sm:w-5 sm:h-5 text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm sm:text-base md:text-lg font-bold text-white mb-0.5 sm:mb-1 group-hover:text-[var(--primary)] transition-colors">
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
                  className="text-[var(--primary)] hover:text-[var(--primary-hover)] transition-colors underline"
                >
                  Give us feedback
                </a>
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* REST OF THE PAGE - SOLID BLACK BACKGROUND WITH ORANGE THEME, NO STARS/DOTS */}
      <div className="w-full" style={{ backgroundColor: '#000000' }}>
        {/* POWERING INNOVATION SECTION */}
        <section className="py-12 sm:py-16" style={{ backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <p className="text-center text-xs sm:text-sm font-semibold text-gray-400 uppercase tracking-wider mb-8 sm:mb-10">
              Real Traction. Real Results.
            </p>

            {/* Main Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 sm:gap-10 mb-8">
              {/* HuggingFace VibeCoded Models */}
              <div className="text-center">
                <a href="https://huggingface.co/Tesslate" target="_blank" rel="noopener" className="block group">
                  <div className="inline-block mb-4 opacity-70 group-hover:opacity-100 transition-all group-hover:scale-105 brightness-0 invert">
                    <img src="https://huggingface.co/front/assets/huggingface_logo-noborder.svg" alt="Hugging Face" className="h-8 sm:h-10 mx-auto" />
                  </div>
                  <div className="mb-3">
                    <p className="text-3xl sm:text-4xl font-bold text-[var(--primary)] mb-1">60K+</p>
                    <p className="text-sm text-gray-300 font-semibold">Downloads on the models we've trained</p>
                  </div>
                  <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-[var(--primary)] text-white group-hover:bg-[var(--primary-hover)] transition-colors">
                    <span>Try Our Models</span>
                    <ArrowRight className="w-4 h-4" />
                  </div>
                </a>
              </div>

              {/* GitHub Community */}
              <div className="text-center">
                <a href="https://github.com/TesslateAI" target="_blank" rel="noopener" className="block group">
                  <div className="inline-block mb-4 opacity-70 group-hover:opacity-100 transition-all group-hover:scale-105">
                    <Github className="h-9 sm:h-11 w-9 sm:w-11 text-gray-300 mx-auto" />
                  </div>
                  <div className="mb-3">
                    <p className="text-3xl sm:text-4xl font-bold text-[var(--primary)] mb-1">1,000+</p>
                    <p className="text-sm text-gray-300 font-semibold">Developers Building with Tesslate</p>
                  </div>
                  <div className="flex items-center justify-center gap-1">
                    {[...Array(5)].map((_, i) => (
                      <Star key={i} className="w-4 h-4 fill-[var(--primary)] text-[var(--primary)]" />
                    ))}
                  </div>
                </a>
              </div>

              {/* KPMG Accelerator */}
              <div className="text-center">
                <a href="https://kpmg.com/us/en/media/news/introducing-launch-powered-by-kpmg.html" target="_blank" rel="noopener" className="block group">
                  <div className="inline-block mb-4 opacity-70 group-hover:opacity-100 transition-all group-hover:scale-105">
                    <img src="https://tesslate.com/images/kpmg.png" alt="KPMG Logo" className="h-9 sm:h-11 mx-auto brightness-0 invert" />
                  </div>
                  <div className="mb-3">
                    <p className="text-sm text-gray-300 font-semibold">Selected for</p>
                    <p className="text-lg sm:text-xl font-bold text-white">KPMG Launch-CH</p>
                    <p className="text-xs text-gray-400">Accelerator Program</p>
                  </div>
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* COMPANY LOGOS MARQUEE - FROM TESSLATE.COM */}
        <section className="py-8 sm:py-12">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <p className="text-center text-xs sm:text-sm font-semibold text-white uppercase tracking-wider mb-6 sm:mb-8">
              Proudly Part of Leading Startup Ecosystems
            </p>
            <div className="marquee-container w-full relative overflow-hidden">
              <div className="marquee-content flex flex-nowrap items-center">
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://www.nvidia.com/en-us/startups/" title="Nvidia Inception Program" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/nvidia.png" alt="Nvidia" className="h-8 sm:h-10" style={{ height: '40px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://startup.google.com/" title="Google for Startups" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/CloudforStartups-3.png" alt="Google for Startups" className="h-16 sm:h-20" style={{ height: '80px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://aws.amazon.com/activate/activate-landing/" title="AWS Activate" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/aws.png" alt="AWS Activate" className="h-8 sm:h-10" />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://www.microsoft.com/en-us/startups" title="Microsoft for Startups" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/microsoft.png" alt="Microsoft" className="h-10 sm:h-12" style={{ height: '50px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://community.ibm.com/community/user/groups/community-home?CommunityKey=4ddd8881-1445-4366-8d9f-01951486d421" title="IBM Build Partners" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/ibm.png" alt="IBM" className="h-8 sm:h-9" style={{ height: '35px' }} />
                  </a>
                </div>
                {/* Duplicate for seamless loop */}
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://www.nvidia.com/en-us/startups/" title="Nvidia Inception Program" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/nvidia.png" alt="Nvidia" className="h-8 sm:h-10" style={{ height: '40px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://startup.google.com/" title="Google for Startups" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/CloudforStartups-3.png" alt="Google for Startups" className="h-16 sm:h-20" style={{ height: '80px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://aws.amazon.com/activate/activate-landing/" title="AWS Activate" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/aws.png" alt="AWS Activate" className="h-8 sm:h-10" />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://www.microsoft.com/en-us/startups" title="Microsoft for Startups" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/microsoft.png" alt="Microsoft" className="h-10 sm:h-12" style={{ height: '50px' }} />
                  </a>
                </div>
                <div className="startup-logo flex-shrink-0 px-6 sm:px-8 py-2">
                  <a href="https://community.ibm.com/community/user/groups/community-home?CommunityKey=4ddd8881-1445-4366-8d9f-01951486d421" title="IBM Build Partners" target="_blank" rel="noreferrer">
                    <img src="https://tesslate.com/images/ibm.png" alt="IBM" className="h-8 sm:h-9" style={{ height: '35px' }} />
                  </a>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* SOCIAL PROOF STRIP */}
        <section className="py-12 sm:py-16 border-t" style={{ borderColor: '#1a1a1a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center">
              <h3 className="text-white text-lg sm:text-xl font-semibold mb-2">
                Trusted by 1,000+ developers and teams
              </h3>
              <p className="text-gray-400 text-sm">
                Building the future with open-source AI
              </p>
            </div>
          </div>
        </section>

        {/* INTEGRATIONS SECTION */}
        <section className="py-16 sm:py-24 border-t overflow-hidden" style={{ borderColor: '#1a1a1a', backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <p className="text-[var(--primary)] text-sm font-semibold uppercase tracking-wider mb-3">Integrations</p>
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Connect to Everything
              </h2>
              <p className="text-lg text-gray-400 max-w-2xl mx-auto">
                One-click integrations with 20+ databases, AI providers, and cloud services
              </p>
            </div>
          </div>

          {/* Logo Marquee - Row 1 */}
          <div className="relative mb-6">
            <div className="absolute left-0 top-0 bottom-0 w-32 bg-gradient-to-r from-[#0a0a0a] to-transparent z-10" />
            <div className="absolute right-0 top-0 bottom-0 w-32 bg-gradient-to-l from-[#0a0a0a] to-transparent z-10" />
            <div className="integration-marquee flex items-center gap-8" style={{ animation: 'scroll-left 40s linear infinite' }}>
              {/* PostgreSQL */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" alt="PostgreSQL" className="w-8 h-8" />
                  <span className="text-white font-medium">PostgreSQL</span>
                </div>
              </div>
              {/* Supabase */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/supabase/supabase-original.svg" alt="Supabase" className="w-8 h-8" />
                  <span className="text-white font-medium">Supabase</span>
                </div>
              </div>
              {/* OpenAI */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <svg className="w-8 h-8" viewBox="0 0 24 24" fill="white"><path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z"/></svg>
                  <span className="text-white font-medium">OpenAI</span>
                </div>
              </div>
              {/* Redis */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/redis/redis-original.svg" alt="Redis" className="w-8 h-8" />
                  <span className="text-white font-medium">Redis</span>
                </div>
              </div>
              {/* Stripe */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <svg className="w-8 h-8" viewBox="0 0 28 28" fill="none"><rect width="28" height="28" rx="6" fill="#635BFF"/><path fillRule="evenodd" clipRule="evenodd" d="M13.3 11.046c0-.632.52-.874 1.38-.874 1.233 0 2.79.373 4.023 1.04V7.54c-1.348-.534-2.68-.747-4.023-.747-3.29 0-5.477 1.717-5.477 4.586 0 4.476 6.163 3.763 6.163 5.695 0 .747-.65.988-1.558.988-1.348 0-3.07-.555-4.432-1.303v3.725c1.51.65 3.037.927 4.432.927 3.37 0 5.684-1.665 5.684-4.572-.016-4.83-6.192-3.975-6.192-5.792z" fill="#fff"/></svg>
                  <span className="text-white font-medium">Stripe</span>
                </div>
              </div>
              {/* MongoDB */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mongodb/mongodb-original.svg" alt="MongoDB" className="w-8 h-8" />
                  <span className="text-white font-medium">MongoDB</span>
                </div>
              </div>
              {/* Anthropic */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-[#D4A27F] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">A</span>
                  </div>
                  <span className="text-white font-medium">Anthropic</span>
                </div>
              </div>
              {/* Pinecone */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00D09C] to-[#006B5B] flex items-center justify-center">
                    <span className="text-white text-lg font-bold">P</span>
                  </div>
                  <span className="text-white font-medium">Pinecone</span>
                </div>
              </div>
              {/* Duplicate set for seamless loop */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" alt="PostgreSQL" className="w-8 h-8" />
                  <span className="text-white font-medium">PostgreSQL</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/supabase/supabase-original.svg" alt="Supabase" className="w-8 h-8" />
                  <span className="text-white font-medium">Supabase</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <svg className="w-8 h-8" viewBox="0 0 24 24" fill="white"><path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z"/></svg>
                  <span className="text-white font-medium">OpenAI</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/redis/redis-original.svg" alt="Redis" className="w-8 h-8" />
                  <span className="text-white font-medium">Redis</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <svg className="w-8 h-8" viewBox="0 0 28 28" fill="none"><rect width="28" height="28" rx="6" fill="#635BFF"/><path fillRule="evenodd" clipRule="evenodd" d="M13.3 11.046c0-.632.52-.874 1.38-.874 1.233 0 2.79.373 4.023 1.04V7.54c-1.348-.534-2.68-.747-4.023-.747-3.29 0-5.477 1.717-5.477 4.586 0 4.476 6.163 3.763 6.163 5.695 0 .747-.65.988-1.558.988-1.348 0-3.07-.555-4.432-1.303v3.725c1.51.65 3.037.927 4.432.927 3.37 0 5.684-1.665 5.684-4.572-.016-4.83-6.192-3.975-6.192-5.792z" fill="#fff"/></svg>
                  <span className="text-white font-medium">Stripe</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mongodb/mongodb-original.svg" alt="MongoDB" className="w-8 h-8" />
                  <span className="text-white font-medium">MongoDB</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-[#D4A27F] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">A</span>
                  </div>
                  <span className="text-white font-medium">Anthropic</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00D09C] to-[#006B5B] flex items-center justify-center">
                    <span className="text-white text-lg font-bold">P</span>
                  </div>
                  <span className="text-white font-medium">Pinecone</span>
                </div>
              </div>
            </div>
          </div>

          {/* Logo Marquee - Row 2 (reverse direction) */}
          <div className="relative">
            <div className="absolute left-0 top-0 bottom-0 w-32 bg-gradient-to-r from-[#0a0a0a] to-transparent z-10" />
            <div className="absolute right-0 top-0 bottom-0 w-32 bg-gradient-to-l from-[#0a0a0a] to-transparent z-10" />
            <div className="integration-marquee-reverse flex items-center gap-8" style={{ animation: 'scroll-right 40s linear infinite' }}>
              {/* Clerk */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#6C47FF] to-[#4F37C8] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">C</span>
                  </div>
                  <span className="text-white font-medium">Clerk</span>
                </div>
              </div>
              {/* MySQL */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mysql/mysql-original.svg" alt="MySQL" className="w-8 h-8" />
                  <span className="text-white font-medium">MySQL</span>
                </div>
              </div>
              {/* Neon */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00E599] to-[#00CC88] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">N</span>
                  </div>
                  <span className="text-white font-medium">Neon</span>
                </div>
              </div>
              {/* Grafana */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/grafana/grafana-original.svg" alt="Grafana" className="w-8 h-8" />
                  <span className="text-white font-medium">Grafana</span>
                </div>
              </div>
              {/* Upstash */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00E9A3] to-[#00C48C] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">U</span>
                  </div>
                  <span className="text-white font-medium">Upstash</span>
                </div>
              </div>
              {/* Turso */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#4FF8D2] to-[#00D4AA] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">T</span>
                  </div>
                  <span className="text-white font-medium">Turso</span>
                </div>
              </div>
              {/* Qdrant */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#DC244C] to-[#B01C3C] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">Q</span>
                  </div>
                  <span className="text-white font-medium">Qdrant</span>
                </div>
              </div>
              {/* Resend */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-black border border-white/20 flex items-center justify-center">
                    <span className="text-white text-sm font-bold">R</span>
                  </div>
                  <span className="text-white font-medium">Resend</span>
                </div>
              </div>
              {/* Duplicate for seamless loop */}
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#6C47FF] to-[#4F37C8] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">C</span>
                  </div>
                  <span className="text-white font-medium">Clerk</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/mysql/mysql-original.svg" alt="MySQL" className="w-8 h-8" />
                  <span className="text-white font-medium">MySQL</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00E599] to-[#00CC88] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">N</span>
                  </div>
                  <span className="text-white font-medium">Neon</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/grafana/grafana-original.svg" alt="Grafana" className="w-8 h-8" />
                  <span className="text-white font-medium">Grafana</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00E9A3] to-[#00C48C] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">U</span>
                  </div>
                  <span className="text-white font-medium">Upstash</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#4FF8D2] to-[#00D4AA] flex items-center justify-center">
                    <span className="text-black text-sm font-bold">T</span>
                  </div>
                  <span className="text-white font-medium">Turso</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#DC244C] to-[#B01C3C] flex items-center justify-center">
                    <span className="text-white text-sm font-bold">Q</span>
                  </div>
                  <span className="text-white font-medium">Qdrant</span>
                </div>
              </div>
              <div className="flex-shrink-0 group">
                <div className="flex items-center gap-3 px-6 py-4 rounded-xl bg-[#1a1a1a] border border-[#2a2a2a] group-hover:border-[var(--primary)]/50 transition-all">
                  <div className="w-8 h-8 rounded-lg bg-black border border-white/20 flex items-center justify-center">
                    <span className="text-white text-sm font-bold">R</span>
                  </div>
                  <span className="text-white font-medium">Resend</span>
                </div>
              </div>
            </div>
          </div>

          {/* CTA */}
          <div className="max-w-7xl mx-auto px-4 sm:px-6 mt-12 text-center">
            <p className="text-gray-500 text-sm mb-6">
              + Elasticsearch, RabbitMQ, SendGrid, Cloudinary, n8n, Vercel KV, Prometheus & more
            </p>
            <a href="/register" className="inline-flex items-center gap-2 px-8 py-4 rounded-xl text-base font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors shadow-lg shadow-[var(--primary)]/25">
              <span>Start Building for Free</span>
              <ArrowRight className="w-5 h-5" />
            </a>
          </div>

          {/* Animation Styles */}
          <style>{`
            @keyframes scroll-left {
              0% { transform: translateX(0); }
              100% { transform: translateX(-50%); }
            }
            @keyframes scroll-right {
              0% { transform: translateX(-50%); }
              100% { transform: translateX(0); }
            }
            .integration-marquee:hover,
            .integration-marquee-reverse:hover {
              animation-play-state: paused;
            }
          `}</style>
        </section>

        {/* FEATURE SECTION - TOP 3 FEATURES */}
        <section className="py-16 sm:py-24" aria-labelledby="features-heading">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 id="features-heading" className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Why Developers Choose Tesslate
              </h2>
            </div>

            <div className="grid md:grid-cols-3 gap-6 sm:gap-8">
              {/* Feature 1 */}
              <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 hover:transform hover:scale-105">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Code2 className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-4">
                  Full-Stack AI Builder (Open Source)
                </h3>
                <p className="text-gray-400 mb-4">
                  Generate production-ready frontend, backend, and database layers using open-source agents. Edit everything. Fork everything. Deploy anywhere.
                </p>
                <ul className="space-y-2">
                  {[
                    'Full code, no black boxes',
                    'React / Next.js / FastAPI / Node / Mongo / Postgres targets',
                    'Deterministic & auditable builds',
                    'Zero lock-in'
                  ].map((benefit, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-400">
                      <Check className="w-4 h-4 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                      <span>{benefit}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Feature 2 */}
              <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 hover:transform hover:scale-105">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Settings className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-4">
                  Customize How Your Agents Think
                </h3>
                <p className="text-gray-400 mb-4">
                  Every agent is fully inspectable and modifiable—system prompts, skills, tools, workflows, memory, architecture.
                </p>
                <ul className="space-y-2">
                  {[
                    'Tune agent behavior to your standards',
                    'Add custom tools and integrations',
                    'Use your own models (local or cloud)',
                    'Perfect for enterprise compliance'
                  ].map((benefit, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-400">
                      <Check className="w-4 h-4 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                      <span>{benefit}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Feature 3 */}
              <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 hover:transform hover:scale-105">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Share2 className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-4">
                  Sell and Share Your Agents
                </h3>
                <p className="text-gray-400 mb-4">
                  Publish agents you create to the Tesslate Marketplace. Monetize them or open-source them for the community.
                </p>
                <ul className="space-y-2">
                  {[
                    'Earn recurring income',
                    'Build a public portfolio',
                    'Distribute private agents internally',
                    'Enterprise teams can share agents across departments'
                  ].map((benefit, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-400">
                      <Check className="w-4 h-4 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                      <span>{benefit}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* TESSLATE ECOSYSTEM - OTHER PRODUCTS */}
        <section className="py-16 sm:py-24" style={{ backgroundColor: '#0a0a0a' }} aria-labelledby="ecosystem-heading">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 id="ecosystem-heading" className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                The Tesslate Ecosystem
              </h2>
              <p className="text-xl text-gray-400 max-w-3xl mx-auto">
                Powerful, modular tools to build, train, and deploy intelligent software
              </p>
            </div>

            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-8">
              {/* Agent Builder */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Boxes className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">Agent Builder</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Visual workflow builder to create and connect AI agents seamlessly. Deploy workflows as web apps.
                </p>
                <div className="flex gap-3">
                  <a href="https://github.com/TesslateAI/Agent-Builder" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold border-2 border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary)] hover:text-white transition-colors">
                    GitHub
                  </a>
                  <a href="https://agent.tesslate.com" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors">
                    Try It
                  </a>
                </div>
              </div>

              {/* Designer */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Package className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">Designer</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Instant canvas environment. Prompt AI agents to build decks, workflows, wireframes, and prototypes.
                </p>
                <div className="flex gap-3">
                  <a href="https://github.com/TesslateAI/Designer" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold border-2 border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary)] hover:text-white transition-colors">
                    GitHub
                  </a>
                  <a href="https://designer.tesslate.com" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors">
                    Try It
                  </a>
                </div>
              </div>

              {/* TframeX */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Code2 className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">TframeX Agents</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Open-source architecture powering Tesslate. Build modular, embeddable AI agents with local memory.
                </p>
                <div className="flex gap-3">
                  <a href="https://github.com/TesslateAI/TFrameX" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold border-2 border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary)] hover:text-white transition-colors">
                    GitHub
                  </a>
                  <a href="https://tframex.tesslate.com" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors">
                    Docs
                  </a>
                </div>
              </div>

              {/* UIGen Eval */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <TrendingUp className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">UIGen Eval</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Open benchmark for evaluating AI-generated UIs. Assess quality, prompt adherence, and responsive design.
                </p>
                <div className="flex gap-3">
                  <a href="https://uigeneval.tesslate.com" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-colors">
                    Leaderboards
                  </a>
                </div>
              </div>

              {/* Late */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 hover:border-[var(--primary)] transition-all duration-300 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Zap className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">Late</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Training library for AMD GPUs. Batch and train fine-tuned models with optimized performance.
                </p>
                <div className="flex gap-3">
                  <a href="https://github.com/TesslateAI/Late" target="_blank" rel="noopener noreferrer" className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold border-2 border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary)] hover:text-white transition-colors">
                    GitHub
                  </a>
                </div>
              </div>

              {/* Forge & Wise - Coming Soon */}
              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 sm:p-8 opacity-60 flex flex-col">
                <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center mb-6" style={{ backgroundColor: 'rgba(249, 115, 22, 0.1)' }}>
                  <Settings className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" />
                </div>
                <h3 className="text-xl sm:text-2xl font-bold text-white mb-3">Forge &amp; Wise</h3>
                <p className="text-gray-400 mb-4 flex-1">
                  Model training & context engine. Train custom models and provide real-time codebase understanding for agents.
                </p>
                <div className="flex gap-3">
                  <button disabled className="flex-1 text-center px-4 py-2 rounded-xl text-sm font-semibold bg-gray-700 text-gray-400 cursor-not-allowed">
                    Coming Soon
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* HOW IT WORKS - 4 STEPS */}
        <section className="py-16 sm:py-24" style={{ backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                How It Works
              </h2>
            </div>

            <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 sm:gap-8">
              {[
                {
                  step: '1',
                  title: 'Build an Agent',
                  description: 'Use Tesslate Studio to create coding agents with custom logic, tools, and models.',
                  icon: Package
                },
                {
                  step: '2',
                  title: 'Generate Full-Stack Apps',
                  description: 'Agents produce complete codebases that you can run, modify, or export.',
                  icon: Code2
                },
                {
                  step: '3',
                  title: 'Run Anywhere',
                  description: 'Local, VPC, self-hosted GPU, cloud, or on-prem.',
                  icon: Globe
                },
                {
                  step: '4',
                  title: 'Monetize or Deploy',
                  description: 'Publish agents to the marketplace or deploy their outputs to production.',
                  icon: TrendingUp
                }
              ].map((item, i) => (
                <div key={i} className="relative">
                  <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-2xl p-6 hover:border-[var(--primary)] transition-all duration-300">
                    <div className="flex items-center gap-4 mb-4">
                      <div className="w-12 h-12 rounded-full bg-[var(--primary)] flex items-center justify-center text-white font-bold text-xl">
                        {item.step}
                      </div>
                      <item.icon className="w-8 h-8 text-[var(--primary)]" />
                    </div>
                    <h3 className="text-xl font-bold text-white mb-3">{item.title}</h3>
                    <p className="text-gray-400 text-sm">{item.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* DEEP VALUE SECTION - ENTERPRISE */}
        <section className="py-16 sm:py-24">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div style={{ backgroundColor: '#0a0a0a', border: '1px solid #2a2a2a' }} className="rounded-3xl p-8 sm:p-12">
              <div className="grid lg:grid-cols-2 gap-8 sm:gap-12 items-center">
                <div>
                  <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-6">
                    For Enterprises
                  </h2>
                  <p className="text-xl text-gray-300 mb-8">
                    Your infrastructure. Your models. Your code.
                  </p>
                  <p className="text-gray-400 mb-8">
                    Tesslate gives engineering teams an AI-native way to build software 10× faster—without giving up control.
                  </p>
                  <button
                    onClick={() => navigate('/register')}
                    className="px-8 py-4 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white font-semibold rounded-xl transition-colors"
                  >
                    Request Enterprise Access
                  </button>
                </div>
                <div>
                  <ul className="space-y-4">
                    {[
                      'Self-hosted runners',
                      'Private models (Mistral, Llama, Qwen, custom finetunes)',
                      'Full audit logs & RBAC',
                      'No data leaves your environment',
                      'Export to GitHub, Docker, Kubernetes, or any runtime',
                      'Custom workflow automations',
                      'Build once → reuse across teams'
                    ].map((item, i) => (
                      <li key={i} className="flex items-start gap-3 text-gray-300">
                        <Shield className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-1" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* DEVELOPER-FIRST SECTION */}
        <section className="py-16 sm:py-24" style={{ backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                For Developers
              </h2>
              <p className="text-xl text-gray-400 max-w-3xl mx-auto">
                Open-source, forkable, hackable.
              </p>
            </div>

            <div className="grid md:grid-cols-2 gap-6 sm:gap-8 mb-12">
              {[
                {
                  title: 'Apache 2.0 license',
                  description: 'Fully open-source and free to use'
                },
                {
                  title: 'Modify every layer',
                  description: 'Prompts, tools, build targets'
                },
                {
                  title: 'Contribute agents or build your own',
                  description: 'Open ecosystem'
                },
                {
                  title: 'Active Discord & GitHub community',
                  description: 'Get help, share ideas'
                },
                {
                  title: 'Works on laptops or GPU rigs',
                  description: 'No cloud required'
                },
                {
                  title: 'Deploy locally or in your cloud',
                  description: 'Complete infrastructure control'
                }
              ].map((item, i) => (
                <div key={i} style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-xl p-6 hover:border-[var(--primary)] transition-all duration-300">
                  <h3 className="text-lg font-bold text-white mb-2">{item.title}</h3>
                  <p className="text-gray-400 text-sm">{item.description}</p>
                </div>
              ))}
            </div>

            <div className="text-center">
              <a
                href="https://github.com/TesslateAI"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-8 py-4 bg-white text-black font-semibold rounded-xl hover:bg-gray-200 transition-colors"
              >
                <Github className="w-5 h-5" />
                View on GitHub
              </a>
            </div>
          </div>
        </section>

        {/* MARKETPLACE SECTION */}
        <section className="py-16 sm:py-24">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Tesslate Marketplace
              </h2>
              <p className="text-xl text-gray-400 max-w-3xl mx-auto">
                Discover, install, and monetize open-source coding agents.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
              {[
                'Frontend builders',
                'Backend/API generators',
                'Database schema designers',
                'Workflow/automation agents',
                'UI/UX layout agents',
                'Data processing agents',
                'Infrastructure agents',
                'Finetune-ready model agents'
              ].map((category, i) => (
                <div key={i} style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-xl p-6 hover:border-[var(--primary)] transition-all duration-300 hover:transform hover:scale-105">
                  <Boxes className="w-8 h-8 text-[var(--primary)] mb-3" />
                  <h3 className="text-white font-semibold">{category}</h3>
                </div>
              ))}
            </div>

            <div className="text-center mt-12">
              <button
                onClick={() => navigate('/marketplace')}
                className="px-8 py-4 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white font-semibold rounded-xl transition-colors"
              >
                Browse Agents
              </button>
            </div>
          </div>
        </section>

        {/* DEMO PREVIEW */}
        <section className="py-16 sm:py-24" style={{ backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                See an agent build a full-stack app in 30 seconds
              </h2>
              <p className="text-gray-400 max-w-2xl mx-auto">
                This is open-source. You can run this entire workflow on your laptop.
              </p>
            </div>

            <div className="relative rounded-2xl overflow-hidden aspect-video max-w-5xl mx-auto" style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }}>
              <iframe
                src="https://www.youtube.com/embed/W-jgef-cdmg?controls=0&modestbranding=1&rel=0&autoplay=0"
                title="Tesslate Demo"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="absolute inset-0 w-full h-full"
                style={{ border: 'none' }}
              />
            </div>
          </div>
        </section>

        {/* PRICING */}
        <section className="py-16 sm:py-24">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Pricing
              </h2>
              <p className="text-xl text-gray-400 max-w-3xl mx-auto">
                Open-source core. Affordable advanced tools.
              </p>
            </div>

            <div className="grid md:grid-cols-3 gap-6 sm:gap-8 max-w-6xl mx-auto">
              {/* Free Plan */}
              <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-2xl p-8">
                <h3 className="text-2xl font-bold text-white mb-2">Free</h3>
                <p className="text-gray-400 mb-6">(Open Source)</p>
                <div className="text-4xl font-bold text-white mb-6">$0</div>
                <ul className="space-y-3 mb-8">
                  {[
                    'Full-stack generator',
                    'Agent builder & editor',
                    'Web interface access',
                    'Self-hosting',
                    'Community agents'
                  ].map((feature, i) => (
                    <li key={i} className="flex items-start gap-2 text-gray-300">
                      <Check className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => navigate('/register')}
                  className="w-full px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-gray-200 transition-colors"
                >
                  Start Free
                </button>
              </div>

              {/* Pro Plan */}
              <div className="rounded-2xl p-8 transform scale-105 relative" style={{ background: 'linear-gradient(135deg, #f97316, #ea580c)' }}>
                <div className="absolute top-0 right-0 bg-white text-black px-3 py-1 rounded-bl-xl rounded-tr-xl text-sm font-bold">
                  Popular
                </div>
                <h3 className="text-2xl font-bold text-white mb-2">Pro</h3>
                <p className="text-white/80 mb-6">For professionals and teams</p>
                <div className="text-4xl font-bold text-white mb-1">$5</div>
                <p className="text-white/80 mb-6">/month</p>
                <ul className="space-y-3 mb-8">
                  {[
                    'Advanced agents',
                    'Priority builds',
                    'GPU-accelerated workflows',
                    'Marketplace publishing',
                    'Collaborative projects'
                  ].map((feature, i) => (
                    <li key={i} className="flex items-start gap-2 text-white">
                      <Check className="w-5 h-5 flex-shrink-0 mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => navigate('/register')}
                  className="w-full px-6 py-3 bg-white text-[var(--primary)] font-semibold rounded-xl hover:bg-gray-100 transition-colors"
                >
                  Get Started
                </button>
              </div>

              {/* Enterprise Plan */}
              <div style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }} className="rounded-2xl p-8">
                <h3 className="text-2xl font-bold text-white mb-2">Enterprise</h3>
                <p className="text-gray-400 mb-6">Custom solutions</p>
                <div className="text-4xl font-bold text-white mb-6">Custom</div>
                <ul className="space-y-3 mb-8">
                  {[
                    'Private runners',
                    'Custom models',
                    'RBAC & audit logs',
                    'SSO & private agent repos',
                    'Dedicated support',
                    'On-prem deployment'
                  ].map((feature, i) => (
                    <li key={i} className="flex items-start gap-2 text-gray-300">
                      <Check className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => navigate('/register')}
                  style={{ border: '2px solid #f97316' }}
                  className="w-full px-6 py-3 text-[var(--primary)] font-semibold rounded-xl hover:bg-[var(--primary)] hover:text-white transition-colors"
                >
                  Request Pricing
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* COMMUNITY */}
        <section className="py-16 sm:py-24" style={{ backgroundColor: '#0a0a0a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Join the Tesslate Community
              </h2>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl mx-auto">
              <a
                href="https://github.com/TesslateAI"
                target="_blank"
                rel="noopener noreferrer"
                style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }}
                className="rounded-xl p-6 hover:border-[var(--primary)] transition-all duration-300 text-center"
              >
                <Github className="w-12 h-12 text-[var(--primary)] mx-auto mb-4" />
                <h3 className="text-white font-semibold mb-2">GitHub</h3>
                <p className="text-gray-400 text-sm">Star our repos</p>
              </a>

              <a
                href="https://discord.gg/WgXabcN2r2"
                target="_blank"
                rel="noopener noreferrer"
                style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }}
                className="rounded-xl p-6 hover:border-[var(--primary)] transition-all duration-300 text-center"
              >
                <MessageSquare className="w-12 h-12 text-[var(--primary)] mx-auto mb-4" />
                <h3 className="text-white font-semibold mb-2">Discord</h3>
                <p className="text-gray-400 text-sm">Join the conversation</p>
              </a>

              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-xl p-6 text-center">
                <Users className="w-12 h-12 text-[var(--primary)] mx-auto mb-4" />
                <h3 className="text-white font-semibold mb-2">Contributors</h3>
                <p className="text-gray-400 text-sm">Join the team</p>
              </div>

              <div style={{ backgroundColor: '#000000', border: '1px solid #2a2a2a' }} className="rounded-xl p-6 text-center">
                <BookOpen className="w-12 h-12 text-[var(--primary)] mx-auto mb-4" />
                <h3 className="text-white font-semibold mb-2">Updates</h3>
                <p className="text-gray-400 text-sm">Weekly releases</p>
              </div>
            </div>

            <div className="text-center mt-12">
              <a
                href="https://discord.gg/WgXabcN2r2"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-8 py-4 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white font-semibold rounded-xl transition-colors"
              >
                <MessageSquare className="w-5 h-5" />
                Join Discord
              </a>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section className="py-16 sm:py-24">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12 sm:mb-16">
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-4">
                Frequently Asked Questions
              </h2>
            </div>

            <div className="space-y-4">
              {faqs.map((faq, index) => (
                <div
                  key={index}
                  style={{ backgroundColor: '#1a1a1a', border: '1px solid #2a2a2a' }}
                  className="rounded-xl overflow-hidden hover:border-[var(--primary)] transition-all duration-300"
                >
                  <button
                    onClick={() => setExpandedFAQ(expandedFAQ === index ? null : index)}
                    style={{ backgroundColor: '#1a1a1a' }}
                    className="w-full px-6 py-4 text-left flex items-center justify-between hover:bg-black transition-colors"
                  >
                    <span className="font-semibold text-white">{faq.question}</span>
                    <ChevronDown
                      className={`w-5 h-5 text-[var(--primary)] transition-transform duration-200 ${
                        expandedFAQ === index ? 'transform rotate-180' : ''
                      }`}
                    />
                  </button>
                  {expandedFAQ === index && (
                    <div className="px-6 pb-4" style={{ borderTop: '1px solid #2a2a2a' }}>
                      <p className="text-gray-400 pt-4">{faq.answer}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FINAL CTA */}
        <section className="py-16 sm:py-24" style={{ background: 'linear-gradient(135deg, #f97316, #ea580c)' }}>
          <div className="max-w-4xl mx-auto px-4 sm:px-6 text-center">
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-6">
              Build your next app in minutes, not months
            </h2>
            <p className="text-xl text-white/90 mb-8 max-w-2xl mx-auto">
              Start free. See why teams choose Tesslate Studio.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <button
                onClick={() => navigate('/register')}
                className="px-8 py-4 bg-white text-[var(--primary)] font-bold rounded-xl hover:bg-gray-100 transition-colors flex items-center justify-center gap-2"
              >
                Start Free
                <ArrowRight className="w-5 h-5" />
              </button>
              <button
                onClick={() => navigate('/register')}
                style={{ border: '2px solid white' }}
                className="px-8 py-4 text-white font-bold rounded-xl hover:bg-white hover:text-[var(--primary)] transition-colors flex items-center justify-center gap-2"
              >
                <PlayCircle className="w-5 h-5" />
                See Demo
              </button>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-6 text-sm text-white/80 mt-8">
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4" />
                Free forever plan
              </div>
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4" />
                No credit card required
              </div>
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4" />
                Cancel anytime
              </div>
            </div>
          </div>
        </section>

        {/* FOOTER */}
        <footer className="py-16" style={{ borderTop: '1px solid #1a1a1a' }}>
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <div className="grid md:grid-cols-5 gap-8 mb-12">
              <div className="md:col-span-2">
                <div className="flex items-center gap-3 mb-4">
                  <svg className="w-8 h-8 text-[var(--primary)]" viewBox="0 0 161.9 126.66">
                    <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
                    <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
                    <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
                  </svg>
                  <div>
                    <h3 className="text-xl font-bold text-white">Tesslate</h3>
                    <p className="text-gray-400 text-sm">Open-Source AI Coding Agents Platform</p>
                  </div>
                </div>
                <p className="text-gray-400 text-sm mb-6">
                  Build full-stack apps from one prompt with AI-powered design tools.
                </p>
              </div>

              <div>
                <h4 className="font-bold text-white mb-4">Product</h4>
                <div className="space-y-2">
                  <a href="https://github.com/TesslateAI" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">GitHub</a>
                  <a href="https://docs.tesslate.com" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Docs</a>
                  <button onClick={() => navigate('/marketplace')} className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Marketplace</button>
                  <a href="https://discord.gg/WgXabcN2r2" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Community</a>
                </div>
              </div>

              <div>
                <h4 className="font-bold text-white mb-4">Resources</h4>
                <div className="space-y-2">
                  <a href="https://docs.tesslate.com" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Documentation</a>
                  <a href="https://github.com/TesslateAI/Studio" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Studio</a>
                  <a href="https://github.com/TesslateAI/Agent-Builder" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Agent Builder</a>
                  <a href="https://github.com/TesslateAI/Designer" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Designer</a>
                </div>
              </div>

              <div>
                <h4 className="font-bold text-white mb-4">Company</h4>
                <div className="space-y-2">
                  <a href="https://discord.gg/WgXabcN2r2" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Privacy</a>
                  <a href="https://discord.gg/WgXabcN2r2" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Terms</a>
                  <a href="https://discord.gg/WgXabcN2r2" target="_blank" rel="noopener noreferrer" className="block text-gray-400 hover:text-[var(--primary)] transition-colors">Careers</a>
                </div>
              </div>
            </div>

            <div style={{ borderTop: '1px solid #1a1a1a' }} className="pt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
              <p className="text-gray-400 text-sm">© 2025 Tesslate. All rights reserved.</p>
              <div className="flex items-center gap-4">
                <a href="https://github.com/TesslateAI" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-[var(--primary)] transition-colors">
                  <Github className="w-5 h-5" />
                </a>
                <a href="https://discord.gg/WgXabcN2r2" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-[var(--primary)] transition-colors">
                  <MessageSquare className="w-5 h-5" />
                </a>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
