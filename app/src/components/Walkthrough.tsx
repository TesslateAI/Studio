import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ArrowRight, Check, HandPointing } from '@phosphor-icons/react';
import { useNavigate, useLocation } from 'react-router-dom';

interface WalkthroughStep {
  id: string;
  title: string;
  description: string;
  targetElement?: string;
  position: 'top' | 'bottom' | 'left' | 'right' | 'center';
  action?: string;
  route?: string;
  showContinueButton?: boolean;
}

const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to Tesslate Studio! 👋',
    description: 'Hey there! I\'m excited to show you around. Tesslate Studio is where you build software with AI agents. Let me give you a quick tour!',
    position: 'center',
    showContinueButton: true
  },
  {
    id: 'navigate-marketplace',
    title: 'Step 1: Get an AI Agent',
    description: 'First, click the Marketplace button to browse AI agents. These agents will help you build your projects!',
    targetElement: '[data-tour="marketplace-link"]',
    position: 'right',
    action: 'Click Marketplace →'
  },
  {
    id: 'marketplace-agents',
    title: 'Pick a Stream Builder Agent',
    description: 'Here in Tesslate Studio, you can pick or make your own agents! Look for a "Stream Builder" type agent - try the "Full Stack Agent" (it\'s free). Click "Install" to add it to your library.',
    position: 'center',
    route: '/marketplace',
    showContinueButton: true
  },
  {
    id: 'marketplace-bases-tab',
    title: 'Step 2: Now Get a Base Template',
    description: 'Great! Now click the "Bases" tab at the top to see project templates. Bases give you a head start on your projects.',
    position: 'center',
    route: '/marketplace',
    showContinueButton: true
  },
  {
    id: 'marketplace-bases',
    title: 'Pick a Base Template',
    description: 'Perfect! Pick any base you like and click "Install" - we recommend the Next.js base for modern web apps!',
    position: 'center',
    route: '/marketplace',
    showContinueButton: true
  },
  {
    id: 'navigate-library',
    title: 'Step 3: Go to Your Library',
    description: 'Awesome! Now click the Library button to manage your agents.',
    targetElement: '[data-tour="library-link"]',
    position: 'bottom',
    route: '/marketplace'
  },
  {
    id: 'library-enable-agent',
    title: 'Enable Your Agent',
    description: 'This is your library! Find the agent you added and make sure it\'s "Active" (green badge). Click "Enable" if it shows as "Disabled". Active agents can be used in your projects!',
    position: 'center',
    route: '/library',
    showContinueButton: true
  },
  {
    id: 'navigate-dashboard',
    title: 'Step 4: Create a Project',
    description: 'Perfect! Now let\'s head back to the Dashboard to create your first project. Click the Back button.',
    targetElement: '[data-tour="dashboard-link"]',
    position: 'bottom',
    route: '/library'
  },
  {
    id: 'create-project-intro',
    title: 'Create Your First Project',
    description: 'Almost there! Click the "New Project" button. You\'ll choose your enabled agent and base to start building!',
    targetElement: '[data-tour="create-project"]',
    position: 'bottom',
    route: '/'
  },
  {
    id: 'complete',
    title: 'You\'re Ready to Build! 🎉',
    description: 'That\'s it! Create a project, chat with your AI agent in the project page, and watch your ideas come to life. Need help? Click the Discord button anytime. Happy building!',
    position: 'center',
    showContinueButton: true
  }
];

interface WalkthroughProps {
  onComplete: () => void;
  onSkip: () => void;
}

export function Walkthrough({ onComplete, onSkip }: WalkthroughProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [isVisible, setIsVisible] = useState(true);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const step = WALKTHROUGH_STEPS[currentStep];

  // Update target element position when step changes
  useEffect(() => {
    if (step.targetElement) {
      const updateTargetRect = () => {
        const element = document.querySelector(step.targetElement!);
        if (element) {
          // Scroll element into view with more centering
          element.scrollIntoView({
            behavior: 'smooth',
            block: 'center',
            inline: 'center'
          });

          // Also scroll to center if needed
          setTimeout(() => {
            const rect = element.getBoundingClientRect();
            const absoluteTop = window.pageYOffset + rect.top;
            const middle = absoluteTop - (window.innerHeight / 2) + (rect.height / 2);

            window.scrollTo({
              top: middle,
              behavior: 'smooth'
            });
          }, 100);

          // Wait for scroll to complete, then get position
          setTimeout(() => {
            const rect = element.getBoundingClientRect();
            setTargetRect(rect);
          }, 600);
        } else {
          setTargetRect(null);
        }
      };

      // Wait for navigation and DOM to settle
      const timer = setTimeout(updateTargetRect, 400);

      window.addEventListener('resize', updateTargetRect);
      return () => {
        clearTimeout(timer);
        window.removeEventListener('resize', updateTargetRect);
      };
    } else {
      setTargetRect(null);
    }
  }, [step, location.pathname, currentStep]);

  // Navigate to route when step changes
  useEffect(() => {
    if (step.route && location.pathname !== step.route) {
      navigate(step.route);
    }
  }, [step, location.pathname, navigate]);

  // Manage back button permissions based on current step
  useEffect(() => {
    if (step.id === 'navigate-dashboard') {
      // Allow clicking the back button on this specific step
      window.dispatchEvent(new Event('walkthroughAllowBackButton'));
    } else {
      // Disallow clicking the back button on all other steps
      window.dispatchEvent(new Event('walkthroughDisallowBackButton'));
    }
  }, [step.id]);

  // Listen for clicks on target element
  useEffect(() => {
    if (step.targetElement && !step.showContinueButton) {
      const handleClick = (e: MouseEvent) => {
        const target = e.target as Element;
        const element = document.querySelector(step.targetElement!);
        if (element && (element === target || element.contains(target))) {
          setTimeout(() => {
            handleNext();
          }, 300);
        }
      };

      document.addEventListener('click', handleClick, true);
      return () => document.removeEventListener('click', handleClick, true);
    }
  }, [step, currentStep]);

  const handleNext = () => {
    if (currentStep < WALKTHROUGH_STEPS.length - 1) {
      setCurrentStep(prev => prev + 1);
    } else {
      handleComplete();
    }
  };

  const handleComplete = () => {
    setIsVisible(false);
    setTimeout(onComplete, 300);
  };

  const handleSkipTour = () => {
    setIsVisible(false);
    setTimeout(onSkip, 300);
  };

  // Calculate tooltip position based on target element
  const getTooltipStyle = () => {
    if (step.position === 'center' || !targetRect) {
      return {
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)'
      };
    }

    const padding = 24;
    const style: React.CSSProperties = { position: 'fixed' };

    // For mobile, always center
    if (window.innerWidth < 768) {
      return {
        bottom: '24px',
        left: '16px',
        right: '16px',
        transform: 'none'
      };
    }

    switch (step.position) {
      case 'right':
        style.left = `${Math.min(targetRect.right + padding, window.innerWidth - 450)}px`;
        style.top = `${targetRect.top + targetRect.height / 2}px`;
        style.transform = 'translateY(-50%)';
        break;
      case 'left':
        style.right = `${Math.min(window.innerWidth - targetRect.left + padding, window.innerWidth - 450)}px`;
        style.top = `${targetRect.top + targetRect.height / 2}px`;
        style.transform = 'translateY(-50%)';
        break;
      case 'top':
        style.bottom = `${Math.min(window.innerHeight - targetRect.top + padding, window.innerHeight - 250)}px`;
        style.left = '50%';
        style.transform = 'translateX(-50%)';
        break;
      case 'bottom':
        style.top = `${Math.min(targetRect.bottom + padding, window.innerHeight - 250)}px`;
        style.left = '50%';
        style.transform = 'translateX(-50%)';
        break;
    }

    return style;
  };

  // Get arrow position for pointer
  const getArrowStyle = () => {
    if (!targetRect || step.position === 'center') return null;

    const isMobile = window.innerWidth < 768;
    if (isMobile) {
      // Point from bottom of screen to target
      return {
        bottom: '220px',
        left: `${targetRect.left + targetRect.width / 2}px`,
        transform: 'translateX(-50%) rotate(180deg)'
      };
    }

    const style: React.CSSProperties = { position: 'fixed' };

    switch (step.position) {
      case 'right':
        style.left = `${targetRect.right + 8}px`;
        style.top = `${targetRect.top + targetRect.height / 2}px`;
        style.transform = 'translateY(-50%) rotate(-90deg)';
        break;
      case 'left':
        style.right = `${window.innerWidth - targetRect.left + 8}px`;
        style.top = `${targetRect.top + targetRect.height / 2}px`;
        style.transform = 'translateY(-50%) rotate(90deg)';
        break;
      case 'top':
        style.bottom = `${window.innerHeight - targetRect.top + 8}px`;
        style.left = `${targetRect.left + targetRect.width / 2}px`;
        style.transform = 'translateX(-50%) rotate(0deg)';
        break;
      case 'bottom':
        style.top = `${targetRect.bottom + 8}px`;
        style.left = `${targetRect.left + targetRect.width / 2}px`;
        style.transform = 'translateX(-50%) rotate(180deg)';
        break;
    }

    return style;
  };

  const progress = ((currentStep + 1) / WALKTHROUGH_STEPS.length) * 100;
  const arrowStyle = getArrowStyle();

  return (
    <AnimatePresence>
      {isVisible && (
        <>
          {/* Dark overlay to focus attention */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 pointer-events-none"
          />

          {/* Spotlight ring around target - elevated above overlay */}
          {targetRect && (
            <>
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="fixed rounded-xl pointer-events-none z-50"
                style={{
                  left: targetRect.left - 8,
                  top: targetRect.top - 8,
                  width: targetRect.width + 16,
                  height: targetRect.height + 16,
                  border: '4px solid var(--primary)',
                  boxShadow: '0 0 0 4px rgba(255, 107, 53, 0.3), 0 0 40px rgba(255, 107, 53, 0.6)'
                }}
              />

              {/* Pulsing ring */}
              <motion.div
                className="fixed rounded-xl pointer-events-none z-50"
                style={{
                  left: targetRect.left - 8,
                  top: targetRect.top - 8,
                  width: targetRect.width + 16,
                  height: targetRect.height + 16,
                  border: '3px solid var(--primary)'
                }}
                animate={{
                  opacity: [0.3, 0.8, 0.3],
                  scale: [1, 1.08, 1]
                }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                  ease: 'easeInOut'
                }}
              />
            </>
          )}

          {/* Animated arrow pointer */}
          {arrowStyle && (
            <motion.div
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0 }}
              className="fixed z-[60] pointer-events-none"
              style={arrowStyle}
            >
              <motion.div
                animate={{
                  y: [-4, 4, -4]
                }}
                transition={{
                  duration: 1.5,
                  repeat: Infinity,
                  ease: 'easeInOut'
                }}
              >
                <HandPointing
                  className="w-12 h-12 md:w-16 md:h-16 text-[var(--primary)] drop-shadow-[0_0_12px_rgba(255,107,53,0.8)]"
                  weight="fill"
                />
              </motion.div>
            </motion.div>
          )}

          {/* Walkthrough card */}
          <motion.div
            key={currentStep}
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: -20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            style={getTooltipStyle()}
            className="fixed z-[60] max-w-lg w-full pointer-events-auto px-4 md:px-0"
          >
            <div className="bg-gradient-to-br from-[#1f1f1f] to-[#1a1a1a] rounded-2xl border-2 border-[var(--primary)] shadow-2xl overflow-hidden">
              {/* Progress bar */}
              <div className="h-2 bg-white/10">
                <motion.div
                  className="h-full bg-gradient-to-r from-[var(--primary)] to-orange-600"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                />
              </div>

              {/* Content */}
              <div className="p-6 md:p-8">
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1 pr-4">
                    <motion.h3
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="font-heading text-2xl md:text-3xl font-bold text-white mb-3 leading-tight"
                    >
                      {step.title}
                    </motion.h3>
                    <motion.p
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.1 }}
                      className="text-gray-200 text-base md:text-lg leading-relaxed"
                    >
                      {step.description}
                    </motion.p>
                  </div>
                  <button
                    onClick={handleSkipTour}
                    className="text-gray-400 hover:text-white transition-colors flex-shrink-0"
                    aria-label="Skip tour"
                  >
                    <X className="w-6 h-6" weight="bold" />
                  </button>
                </div>

                {/* Actions */}
                <div className="flex items-center justify-between mt-8">
                  {/* Step counter */}
                  <div className="flex items-center gap-2">
                    {WALKTHROUGH_STEPS.map((_, index) => (
                      <motion.div
                        key={index}
                        className={`h-2 rounded-full transition-all ${
                          index === currentStep
                            ? 'bg-[var(--primary)]'
                            : index < currentStep
                            ? 'bg-[var(--primary)]/60'
                            : 'bg-white/20'
                        }`}
                        initial={false}
                        animate={{
                          width: index === currentStep ? 48 : 8
                        }}
                      />
                    ))}
                  </div>

                  {/* Next/Skip buttons */}
                  <div className="flex items-center gap-3">
                    {currentStep > 0 && currentStep < WALKTHROUGH_STEPS.length - 1 && (
                      <button
                        onClick={handleSkipTour}
                        className="text-sm text-gray-400 hover:text-white transition-colors font-medium"
                      >
                        Skip
                      </button>
                    )}
                    {step.showContinueButton && (
                      <motion.button
                        onClick={handleNext}
                        className="
                          bg-gradient-to-r from-[var(--primary)] to-orange-600
                          hover:from-orange-600 hover:to-[var(--primary)]
                          text-white font-bold px-6 py-3 rounded-xl
                          flex items-center gap-2
                          shadow-lg shadow-orange-500/40
                          hover:shadow-xl hover:shadow-orange-500/60
                          transition-all duration-200
                        "
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                      >
                        <span>
                          {currentStep === WALKTHROUGH_STEPS.length - 1
                            ? "Let's Go!"
                            : 'Continue'}
                        </span>
                        {currentStep === WALKTHROUGH_STEPS.length - 1 ? (
                          <Check className="w-5 h-5" weight="bold" />
                        ) : (
                          <ArrowRight className="w-5 h-5" weight="bold" />
                        )}
                      </motion.button>
                    )}
                  </div>
                </div>

                {/* Step indicator text */}
                <div className="mt-4 text-center text-sm text-gray-500">
                  Step {currentStep + 1} of {WALKTHROUGH_STEPS.length}
                </div>
              </div>
            </div>

            {/* Decorative glow */}
            <motion.div
              className="absolute -inset-4 bg-[var(--primary)]/15 rounded-3xl blur-2xl -z-10"
              animate={{
                opacity: [0.3, 0.5, 0.3],
                scale: [0.95, 1.05, 0.95]
              }}
              transition={{
                duration: 3,
                repeat: Infinity,
                ease: 'easeInOut'
              }}
            />
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
