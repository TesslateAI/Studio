import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  ArrowRight, Play, Check, Users, Zap, Shield, Code, 
  Database, Palette, Rocket, Building, Camera, Store,
  ChevronDown, ChevronUp, Star, Quote, ArrowUp, Pause,
  PlayCircle, Copy, ExternalLink, Github, Twitter, 
  Mail, MessageSquare, TrendingUp, Clock, DollarSign
} from 'lucide-react';
import toast from 'react-hot-toast';

interface AnimatedCounterProps {
  end: number;
  suffix?: string;
  duration?: number;
}

function AnimatedCounter({ end, suffix = '', duration = 2000 }: AnimatedCounterProps) {
  const [count, setCount] = useState(0);
  const [isVisible, setIsVisible] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
        }
      },
      { threshold: 0.1 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible) return;

    let start = 0;
    const increment = end / (duration / 16);
    const timer = setInterval(() => {
      start += increment;
      if (start >= end) {
        setCount(end);
        clearInterval(timer);
      } else {
        setCount(Math.floor(start));
      }
    }, 16);

    return () => clearInterval(timer);
  }, [isVisible, end, duration]);

  return (
    <span ref={ref} className="font-mono text-orange-600 font-bold">
      {count}{suffix}
    </span>
  );
}

interface FloatingOrbProps {
  delay: number;
  size: 'sm' | 'md' | 'lg';
  position: { x: string; y: string };
}

function FloatingOrb({ delay, size, position }: FloatingOrbProps) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8'
  };

  return (
    <div 
      className={`absolute ${sizeClasses[size]} bg-gradient-to-br from-orange-400 to-orange-600 rounded-full shadow-lg animate-pulse`}
      style={{
        left: position.x,
        top: position.y,
        animationDelay: `${delay}s`,
        animationDuration: '3s'
      }}
    >
      <div className="absolute inset-1 bg-white rounded-full opacity-30"></div>
    </div>
  );
}

function ThreeDGrid() {
  return (
    <div className="relative w-full h-96 overflow-hidden rounded-2xl bg-gradient-to-br from-orange-50 to-white border border-orange-200/30 shadow-2xl">
      {/* Grid Background */}
      <div className="absolute inset-0 opacity-10">
        <svg className="w-full h-full" viewBox="0 0 400 400">
          <defs>
            <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
              <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#f97316" strokeWidth="1"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      </div>
      
      {/* Floating Orbs */}
      <FloatingOrb delay={0} size="lg" position={{ x: '20%', y: '30%' }} />
      <FloatingOrb delay={1} size="md" position={{ x: '70%', y: '20%' }} />
      <FloatingOrb delay={2} size="sm" position={{ x: '60%', y: '70%' }} />
      <FloatingOrb delay={1.5} size="md" position={{ x: '30%', y: '80%' }} />
      <FloatingOrb delay={0.5} size="sm" position={{ x: '80%', y: '60%' }} />
      
      {/* Tessellated Cube Structure */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="relative transform rotate-12 hover:rotate-6 transition-transform duration-700">
          {/* Main Cube */}
          <div className="w-32 h-32 relative">
            {/* Cube faces with glassmorphism */}
            <div className="absolute inset-0 bg-white/80 backdrop-blur-sm rounded-lg border-2 border-orange-400/50 shadow-xl transform rotate-12"></div>
            <div className="absolute inset-0 bg-white/60 backdrop-blur-sm rounded-lg border-2 border-orange-400/30 shadow-lg transform -rotate-6 translate-x-2 translate-y-2"></div>
            <div className="absolute inset-0 bg-orange-100/80 backdrop-blur-sm rounded-lg border-2 border-orange-400/40 shadow-md transform rotate-3 translate-x-1 translate-y-1"></div>
          </div>
          
          {/* Connected nodes */}
          <div className="absolute -top-8 -left-8 w-4 h-4 bg-orange-500 rounded-full shadow-lg animate-ping"></div>
          <div className="absolute -top-4 -right-6 w-3 h-3 bg-orange-600 rounded-full shadow-md animate-pulse"></div>
          <div className="absolute -bottom-6 -right-4 w-5 h-5 bg-orange-400 rounded-full shadow-lg animate-bounce"></div>
          
          {/* Connection lines */}
          <svg className="absolute inset-0 w-full h-full pointer-events-none">
            <line x1="20%" y1="20%" x2="80%" y2="30%" stroke="#f97316" strokeWidth="2" className="animate-pulse" />
            <line x1="30%" y1="70%" x2="70%" y2="20%" stroke="#f97316" strokeWidth="1" className="animate-pulse" strokeDasharray="4,4" />
          </svg>
        </div>
      </div>
      
      {/* Agent Labels */}
      <div className="absolute top-4 left-4 px-3 py-1 bg-white/90 backdrop-blur-sm rounded-full text-xs font-medium text-orange-700 border border-orange-200/50 shadow-sm">
        UI Agent
      </div>
      <div className="absolute top-8 right-6 px-3 py-1 bg-white/90 backdrop-blur-sm rounded-full text-xs font-medium text-orange-700 border border-orange-200/50 shadow-sm">
        Backend Agent
      </div>
      <div className="absolute bottom-12 left-8 px-3 py-1 bg-white/90 backdrop-blur-sm rounded-full text-xs font-medium text-orange-700 border border-orange-200/50 shadow-sm">
        DB Agent
      </div>
    </div>
  );
}

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  accent?: React.ReactNode;
  delay?: number;
}

function FeatureCard({ icon, title, description, accent, delay = 0 }: FeatureCardProps) {
  const [isVisible, setIsVisible] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
        }
      },
      { threshold: 0.1 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, [delay]);

  return (
    <div 
      ref={ref}
      className={`group bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-500 hover:ring-2 hover:ring-orange-400/20 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      <div className="relative mb-4">
        <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
          {icon}
        </div>
        {accent && (
          <div className="absolute -top-2 -right-2">
            {accent}
          </div>
        )}
      </div>
      <h3 className="text-lg font-bold text-gray-800 mb-2">{title}</h3>
      <p className="text-gray-600 text-sm leading-relaxed mb-4">{description}</p>
      <button className="text-orange-600 text-sm font-medium hover:text-orange-700 transition-colors group-hover:translate-x-1 duration-200 flex items-center gap-1">
        Learn more <ArrowRight size={12} />
      </button>
    </div>
  );
}

interface StepProps {
  number: number;
  title: string;
  description: string;
  demo: React.ReactNode;
  isActive: boolean;
}

function Step({ number, title, description, demo, isActive }: StepProps) {
  return (
    <div className={`flex items-center gap-8 p-6 rounded-2xl transition-all duration-500 ${isActive ? 'bg-orange-50/80 backdrop-blur-sm border border-orange-200/50 shadow-lg' : 'hover:bg-white/40'}`}>
      <div className="flex-shrink-0">
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg transition-all duration-300 ${isActive ? 'bg-orange-500 text-white shadow-lg scale-110' : 'bg-white/80 text-gray-600 border border-orange-200/30'}`}>
          {number}
        </div>
      </div>
      <div className="flex-1">
        <h3 className="text-xl font-bold text-gray-800 mb-2">{title}</h3>
        <p className="text-gray-600">{description}</p>
      </div>
      <div className="flex-shrink-0 w-48">
        {demo}
      </div>
    </div>
  );
}

function TypingDemo() {
  const [text, setText] = useState('');
  const fullText = 'Build a modern dashboard with charts';
  
  useEffect(() => {
    let i = 0;
    const timer = setInterval(() => {
      setText(fullText.slice(0, i));
      i++;
      if (i > fullText.length) {
        setTimeout(() => {
          setText('');
          i = 0;
        }, 2000);
      }
    }, 100);
    
    return () => clearInterval(timer);
  }, []);
  
  return (
    <div className="bg-white rounded-lg p-4 shadow-lg border border-orange-200/30">
      <div className="text-sm text-gray-600 mb-2">Describe what you want:</div>
      <div className="font-mono text-sm bg-gray-50 p-3 rounded border">
        {text}<span className="animate-pulse text-orange-500">|</span>
      </div>
    </div>
  );
}

function AssemblyDemo() {
  const [step, setStep] = useState(0);
  const blocks = ['UI', 'API', 'DB', 'Auth'];
  
  useEffect(() => {
    const timer = setInterval(() => {
      setStep(s => (s + 1) % 5);
    }, 800);
    return () => clearInterval(timer);
  }, []);
  
  return (
    <div className="bg-white rounded-lg p-4 shadow-lg border border-orange-200/30">
      <div className="text-sm text-gray-600 mb-3">Assembling stack...</div>
      <div className="flex gap-2">
        {blocks.map((block, i) => (
          <div 
            key={block}
            className={`w-12 h-8 rounded text-xs flex items-center justify-center font-medium transition-all duration-500 ${
              i < step ? 'bg-orange-500 text-white shadow-md' : 'bg-gray-100 text-gray-400'
            }`}
          >
            {block}
          </div>
        ))}
      </div>
    </div>
  );
}

function ThemeDemo() {
  const [theme, setTheme] = useState('light');
  
  useEffect(() => {
    const timer = setInterval(() => {
      setTheme(t => t === 'light' ? 'orange' : 'light');
    }, 1500);
    return () => clearInterval(timer);
  }, []);
  
  return (
    <div className="bg-white rounded-lg p-4 shadow-lg border border-orange-200/30">
      <div className="text-sm text-gray-600 mb-3">Customizing theme...</div>
      <div className={`p-3 rounded transition-all duration-500 ${
        theme === 'orange' ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-800'
      }`}>
        <div className="text-xs font-medium mb-1">Button</div>
        <div className="text-xs opacity-75">Click me</div>
      </div>
    </div>
  );
}

function DeployDemo() {
  const [progress, setProgress] = useState(0);
  const [showConfetti, setShowConfetti] = useState(false);
  
  useEffect(() => {
    const timer = setInterval(() => {
      setProgress(p => {
        if (p >= 100) {
          setShowConfetti(true);
          setTimeout(() => {
            setShowConfetti(false);
            return 0;
          }, 1000);
          return 0;
        }
        return p + 5;
      });
    }, 100);
    return () => clearInterval(timer);
  }, []);
  
  return (
    <div className="bg-white rounded-lg p-4 shadow-lg border border-orange-200/30 relative">
      <div className="text-sm text-gray-600 mb-3">Deploying...</div>
      <div className="bg-gray-100 rounded-full h-2 mb-2">
        <div 
          className="bg-orange-500 h-2 rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        ></div>
      </div>
      <div className="text-xs text-gray-500">{progress}%</div>
      {showConfetti && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-2xl animate-bounce">🎉</div>
        </div>
      )}
    </div>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const [activeStep, setActiveStep] = useState(0);
  const [animationsPaused, setAnimationsPaused] = useState(false);
  const [expandedFAQ, setExpandedFAQ] = useState<number | null>(null);
  const [email, setEmail] = useState('');

  const steps = [
    {
      title: "Prompt",
      description: "Describe what you want to build in natural language.",
      demo: <TypingDemo />
    },
    {
      title: "Assemble", 
      description: "Studio assembles your full-stack architecture automatically.",
      demo: <AssemblyDemo />
    },
    {
      title: "Refine",
      description: "Customize and theme your application with live preview.",
      demo: <ThemeDemo />
    },
    {
      title: "Deploy",
      description: "Ship your application with one click to production.",
      demo: <DeployDemo />
    }
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      if (!animationsPaused) {
        setActiveStep(s => (s + 1) % steps.length);
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [animationsPaused, steps.length]);

  const handleGetStarted = () => {
    const token = localStorage.getItem('token');
    if (token) {
      navigate('/dashboard');
    } else {
      navigate('/login');
    }
  };

  const handleNewsletterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim()) {
      toast.success("You're in! 🎉", {
        icon: '📧',
        style: {
          background: '#fff',
          color: '#f97316',
          border: '1px solid #fed7aa'
        }
      });
      setEmail('');
    }
  };

  const faqs = [
    {
      question: "How does UIGEN-X compare to Claude for design quality?",
      answer: "UIGEN-X delivers Claude-level design quality through advanced AI models optimized specifically for UI generation, at a fraction of the cost through efficient processing and caching."
    },
    {
      question: "Can I export clean code?", 
      answer: "Yes! Tesslate Studio generates production-ready React/TypeScript code with Tailwind CSS that you can export, modify, and deploy anywhere."
    },
    {
      question: "How does Studio handle auth & databases?",
      answer: "Studio automatically generates complete authentication flows and database schemas, with support for popular providers like Supabase, Firebase, and custom solutions."
    },
    {
      question: "What's the deployment path?",
      answer: "One-click deployment to Vercel, Netlify, or your own infrastructure. Studio handles build optimization and environment configuration automatically."
    },
    {
      question: "Can teams collaborate live?",
      answer: "Yes! Real-time collaboration with live cursors, comments, and version control. Perfect for design reviews and pair programming sessions."
    }
  ];

  return (
    <div className={`min-h-screen bg-gradient-to-br from-orange-50 via-white to-orange-50/30 ${animationsPaused ? 'pause-animations' : ''}`}>
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-lg border-b border-orange-200/30 shadow-sm">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-orange-500/90 backdrop-blur-sm rounded-xl flex items-center justify-center shadow-lg ring-1 ring-orange-200/50">
                <Code size={20} className="text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-800">Tesslate Studio</h1>
              </div>
            </div>
            
            <nav className="hidden md:flex items-center gap-8">
              <a href="#features" className="text-gray-600 hover:text-orange-600 transition-colors text-sm font-medium">Features</a>
              <a href="#how-it-works" className="text-gray-600 hover:text-orange-600 transition-colors text-sm font-medium">How it Works</a>
              <a href="#pricing" className="text-gray-600 hover:text-orange-600 transition-colors text-sm font-medium">Pricing</a>
              <a href="#faq" className="text-gray-600 hover:text-orange-600 transition-colors text-sm font-medium">FAQ</a>
            </nav>
            
            <div className="flex items-center gap-3">
              <button
                onClick={() => setAnimationsPaused(!animationsPaused)}
                className="p-2 text-gray-400 hover:text-orange-600 transition-colors"
                title={animationsPaused ? 'Resume Animations' : 'Pause Animations'}
              >
                {animationsPaused ? <Play size={16} /> : <Pause size={16} />}
              </button>
              <button
                onClick={() => navigate('/login')}
                className="text-gray-600 hover:text-orange-600 transition-colors text-sm font-medium"
              >
                Sign In
              </button>
              <button
                onClick={handleGetStarted}
                className="bg-orange-500/90 hover:bg-orange-600/90 text-white px-4 py-2 rounded-xl font-medium transition-all hover:shadow-lg hover:scale-105 text-sm"
              >
                Get Started
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="py-20 lg:py-32 relative overflow-hidden">
        <div className="container mx-auto px-6">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div className="space-y-8">
              <div className="space-y-4">
                <h1 className="text-5xl lg:text-6xl font-bold text-gray-900 leading-tight">
                  Build full-stack apps from{' '}
                  <span className="text-orange-600">one prompt</span>
                </h1>
                <p className="text-xl text-gray-600 leading-relaxed max-w-2xl">
                  Tesslate Studio uses UIGEN-X to deliver{' '}
                  <span className="font-semibold text-gray-800">Claude-level design quality</span>{' '}
                  at <span className="font-semibold text-orange-600">1/10th the cost</span>.
                </p>
              </div>
              
              <div className="flex flex-col sm:flex-row gap-4">
                <button
                  onClick={handleGetStarted}
                  className="group bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white px-8 py-4 rounded-2xl font-bold text-lg transition-all hover:shadow-xl hover:scale-105 flex items-center justify-center gap-2"
                >
                  Start Free
                  <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                </button>
                <button className="border-2 border-orange-500 text-orange-600 hover:bg-orange-50 px-8 py-4 rounded-2xl font-bold text-lg transition-all hover:shadow-lg flex items-center justify-center gap-2">
                  <PlayCircle className="w-5 h-5" />
                  See Demo
                </button>
              </div>
              
              <div className="flex items-center gap-6 text-sm text-gray-500">
                <div className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" />
                  No credit card required
                </div>
                <div className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" />
                  Free forever plan
                </div>
              </div>
            </div>
            
            <div className="relative">
              <ThreeDGrid />
            </div>
          </div>
        </div>
        
        {/* Background decoration */}
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-radial from-orange-100 to-transparent opacity-50 -z-10"></div>
      </section>

      {/* Value Props */}
      <section id="features" className="py-20 bg-white/40 backdrop-blur-sm">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Why Tesslate Studio</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">Experience the future of full-stack development with AI-powered tools that understand your vision.</p>
          </div>
          
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <FeatureCard
              icon={<DollarSign className="w-8 h-8 text-orange-600" />}
              title="Claude-like design, 1/10th the cost"
              description="Premium design quality powered by UIGEN-X at a fraction of traditional costs."
              accent={
                <div className="bg-green-100 text-green-700 px-2 py-1 rounded-full text-xs font-medium animate-pulse">
                  90% savings
                </div>
              }
              delay={0}
            />
            
            <FeatureCard
              icon={
                <div className="relative">
                  <div className="w-8 h-2 bg-orange-600 rounded mb-1"></div>
                  <div className="w-8 h-2 bg-orange-500 rounded mb-1"></div>
                  <div className="w-8 h-2 bg-orange-400 rounded mb-1"></div>
                  <div className="w-8 h-2 bg-orange-300 rounded"></div>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-1 h-6 bg-orange-800 rounded-full animate-pulse"></div>
                  </div>
                </div>
              }
              title="Full-stack, not just front-end"
              description="Complete applications with UI, API, database, and authentication generated together."
              delay={200}
            />
            
            <FeatureCard
              icon={
                <div className="relative">
                  <Users className="w-8 h-8 text-orange-600" />
                  <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-400 rounded-full animate-ping"></div>
                </div>
              }
              title="Collaborative & real-time"
              description="Work together with live cursors, comments, and instant synchronization across your team."
              delay={400}
            />
            
            <FeatureCard
              icon={<Shield className="w-8 h-8 text-orange-600" />}
              title="Enterprise-grade output"
              description="Production-ready code with security best practices, testing, and scalability built-in."
              accent={
                <div className="w-4 h-4 bg-green-500 rounded-full flex items-center justify-center">
                  <Check className="w-2 h-2 text-white" />
                </div>
              }
              delay={600}
            />
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-20">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">How It Works</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">From idea to production in four simple steps.</p>
          </div>
          
          <div className="space-y-6">
            {steps.map((step, index) => (
              <Step
                key={index}
                number={index + 1}
                title={step.title}
                description={step.description}
                demo={step.demo}
                isActive={activeStep === index}
              />
            ))}
          </div>
          
          {/* Progress indicator */}
          <div className="mt-12 flex justify-center">
            <div className="flex gap-2">
              {steps.map((_, index) => (
                <button
                  key={index}
                  onClick={() => setActiveStep(index)}
                  className={`w-3 h-3 rounded-full transition-all duration-300 ${
                    activeStep === index ? 'bg-orange-500 scale-125' : 'bg-orange-200'
                  }`}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Product Demo */}
      <section className="py-20 bg-white/40 backdrop-blur-sm">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">See Studio in Action</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">
              From prompt to production: design, code, data, and agents—cohesively generated.
            </p>
          </div>
          
          <div className="bg-white/80 backdrop-blur-lg rounded-3xl shadow-2xl border border-orange-200/30 overflow-hidden">
            {/* Browser chrome */}
            <div className="bg-gray-100 px-6 py-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-red-400"></div>
                <div className="w-3 h-3 rounded-full bg-yellow-400"></div>
                <div className="w-3 h-3 rounded-full bg-green-400"></div>
                <div className="ml-4 bg-white rounded px-4 py-1 text-sm text-gray-600 flex items-center gap-2 flex-1">
                  <span className="text-green-600">🔒</span>
                  tesslate.studio/demo
                </div>
              </div>
            </div>
            
            {/* Demo content */}
            <div className="p-8">
              <div className="grid lg:grid-cols-3 gap-8">
                <div className="space-y-4">
                  <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
                    <Palette className="w-5 h-5 text-orange-600" />
                    Design
                  </h3>
                  <div className="bg-orange-50 rounded-lg p-4 border border-orange-200/50">
                    <div className="grid grid-cols-4 gap-2 mb-3">
                      {[...Array(8)].map((_, i) => (
                        <div key={i} className="aspect-square bg-white rounded border border-orange-200 flex items-center justify-center text-xs text-gray-400">
                          {i + 1}
                        </div>
                      ))}
                    </div>
                    <div className="text-xs text-gray-600">8pt Grid System</div>
                  </div>
                </div>
                
                <div className="space-y-4">
                  <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
                    <Code className="w-5 h-5 text-orange-600" />
                    Code
                  </h3>
                  <div className="bg-gray-900 rounded-lg p-4 text-sm text-green-400 font-mono">
                    <div>function App() &#123;</div>
                    <div className="ml-2">return (</div>
                    <div className="ml-4 text-blue-400">&lt;div className=&quot;...&quot;&gt;</div>
                    <div className="ml-6 text-white">Dashboard</div>
                    <div className="ml-4 text-blue-400">&lt;/div&gt;</div>
                    <div className="ml-2">)</div>
                    <div>&#125;</div>
                    <div className="mt-2 text-orange-400 animate-pulse">● Live Preview</div>
                  </div>
                </div>
                
                <div className="space-y-4">
                  <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2">
                    <Database className="w-5 h-5 text-orange-600" />
                    Data
                  </h3>
                  <div className="bg-blue-50 rounded-lg p-4 border border-blue-200/50">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-sm">
                        <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                        <span className="font-mono">users</span>
                      </div>
                      <div className="flex items-center gap-2 text-sm ml-4">
                        <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                        <span className="font-mono">projects</span>
                      </div>
                      <div className="flex items-center gap-2 text-sm ml-4">
                        <div className="w-2 h-2 bg-purple-500 rounded-full"></div>
                        <span className="font-mono">files</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="mt-8 flex justify-center">
                <button className="bg-orange-500 hover:bg-orange-600 text-white px-6 py-3 rounded-xl font-medium transition-all hover:shadow-lg flex items-center gap-2">
                  <Copy className="w-4 h-4" />
                  Copy Code
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Social Proof */}
      <section className="py-20">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Trusted by Teams Worldwide</h2>
          </div>
          
          {/* Metrics */}
          <div className="grid md:grid-cols-3 gap-8 mb-16">
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600 mb-2 font-mono">
                <AnimatedCounter end={10} suffix="×" />
              </div>
              <div className="text-gray-600">Faster prototyping</div>
            </div>
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600 mb-2 font-mono">
                <AnimatedCounter end={90} suffix="%" />
              </div>
              <div className="text-gray-600">Cost savings</div>
            </div>
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600 mb-2 font-mono">
                <AnimatedCounter end={50000} suffix="+" />
              </div>
              <div className="text-gray-600">Projects created</div>
            </div>
          </div>
          
          {/* Testimonials */}
          <div className="grid md:grid-cols-2 gap-8">
            <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg">
              <div className="flex items-center gap-4 mb-4">
                <div className="w-12 h-12 bg-orange-500 rounded-full flex items-center justify-center text-white font-bold">
                  S
                </div>
                <div>
                  <div className="font-bold text-gray-800">Sarah Chen</div>
                  <div className="text-sm text-gray-600">Lead Designer at TechCorp</div>
                </div>
              </div>
              <Quote className="w-6 h-6 text-orange-400 mb-2" />
              <p className="text-gray-700 italic">
                "Tesslate Studio transformed our design process. What used to take weeks now happens in hours, and the quality is incredible."
              </p>
              <div className="flex text-orange-400 mt-3">
                {[...Array(5)].map((_, i) => <Star key={i} className="w-4 h-4 fill-current" />)}
              </div>
            </div>
            
            <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg">
              <div className="flex items-center gap-4 mb-4">
                <div className="w-12 h-12 bg-blue-500 rounded-full flex items-center justify-center text-white font-bold">
                  M
                </div>
                <div>
                  <div className="font-bold text-gray-800">Marcus Rodriguez</div>
                  <div className="text-sm text-gray-600">CTO at StartupXYZ</div>
                </div>
              </div>
              <Quote className="w-6 h-6 text-orange-400 mb-2" />
              <p className="text-gray-700 italic">
                "The full-stack generation is game-changing. We shipped our MVP in days instead of months."
              </p>
              <div className="flex text-orange-400 mt-3">
                {[...Array(5)].map((_, i) => <Star key={i} className="w-4 h-4 fill-current" />)}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Who It's For */}
      <section className="py-20 bg-white/40 backdrop-blur-sm">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Who It's For</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">Perfect for teams and individuals who want to build faster.</p>
          </div>
          
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="group bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-300 hover:bg-orange-50/80">
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
                <Rocket className="w-8 h-8 text-orange-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-800 mb-2">Startups</h3>
              <p className="text-gray-600 text-sm">Launch your MVP fast and iterate quickly with professional-grade designs.</p>
            </div>
            
            <div className="group bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-300 hover:bg-orange-50/80">
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
                <Palette className="w-8 h-8 text-orange-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-800 mb-2">Designers</h3>
              <p className="text-gray-600 text-sm">Turn your designs into working applications without learning to code.</p>
            </div>
            
            <div className="group bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-300 hover:bg-orange-50/80">
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
                <Building className="w-8 h-8 text-orange-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-800 mb-2">Enterprises</h3>
              <p className="text-gray-600 text-sm">Scale your development team with AI-powered tools and enterprise security.</p>
            </div>
            
            <div className="group bg-white/80 backdrop-blur-lg rounded-2xl p-6 border border-orange-200/30 shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-300 hover:bg-orange-50/80">
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300">
                <Camera className="w-8 h-8 text-orange-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-800 mb-2">Creators</h3>
              <p className="text-gray-600 text-sm">Build and monetize your ideas with professional tools and seamless workflows.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing Teaser */}
      <section id="pricing" className="py-20">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Simple, Transparent Pricing</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">Claude-like designs at 1/10th the cost—thanks to UIGEN-X.</p>
          </div>
          
          <div className="max-w-4xl mx-auto">
            <div className="bg-white/80 backdrop-blur-lg rounded-3xl p-8 border border-orange-200/30 shadow-2xl">
              <div className="grid md:grid-cols-2 gap-8 items-center">
                <div>
                  <h3 className="text-2xl font-bold text-gray-900 mb-4">Traditional Build</h3>
                  <div className="space-y-2 text-gray-600">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4" />
                      <span>6-12 months</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <DollarSign className="w-4 h-4" />
                      <span>$50,000 - $200,000</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Users className="w-4 h-4" />
                      <span>5-10 developers</span>
                    </div>
                  </div>
                </div>
                
                <div className="relative">
                  <div className="bg-gradient-to-r from-orange-500 to-orange-600 rounded-2xl p-6 text-white">
                    <h3 className="text-2xl font-bold mb-4">Tesslate Studio</h3>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <TrendingUp className="w-4 h-4" />
                        <span>Days to weeks</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <DollarSign className="w-4 h-4" />
                        <span>$99 - $499/month</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Zap className="w-4 h-4" />
                        <span>AI-powered team</span>
                      </div>
                    </div>
                  </div>
                  <div className="absolute -top-3 -right-3 bg-green-500 text-white px-3 py-1 rounded-full text-sm font-bold animate-pulse">
                    90% savings
                  </div>
                </div>
              </div>
              
              <div className="mt-8 text-center">
                <button
                  onClick={handleGetStarted}
                  className="bg-orange-500 hover:bg-orange-600 text-white px-8 py-4 rounded-2xl font-bold text-lg transition-all hover:shadow-xl hover:scale-105"
                >
                  Start Free Today
                </button>
                <p className="text-sm text-gray-500 mt-2">No credit card required • Cancel anytime</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQs */}
      <section id="faq" className="py-20 bg-white/40 backdrop-blur-sm">
        <div className="container mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">Frequently Asked Questions</h2>
            <p className="text-xl text-gray-600 max-w-3xl mx-auto">Everything you need to know about Tesslate Studio.</p>
          </div>
          
          <div className="max-w-3xl mx-auto space-y-4">
            {faqs.map((faq, index) => (
              <div key={index} className="bg-white/80 backdrop-blur-lg rounded-2xl border border-orange-200/30 shadow-lg overflow-hidden">
                <button
                  onClick={() => setExpandedFAQ(expandedFAQ === index ? null : index)}
                  className="w-full px-6 py-4 text-left flex items-center justify-between hover:bg-orange-50/50 transition-colors"
                >
                  <span className="font-semibold text-gray-800">{faq.question}</span>
                  <div className={`transform transition-transform duration-200 ${expandedFAQ === index ? 'rotate-180' : ''}`}>
                    <ChevronDown className="w-5 h-5 text-orange-600" />
                  </div>
                </button>
                <div className={`px-6 transition-all duration-300 ease-in-out overflow-hidden ${
                  expandedFAQ === index ? 'pb-4 max-h-96' : 'max-h-0'
                }`}>
                  <div className="border-t border-orange-200/30 pt-4">
                    <p className="text-gray-600 leading-relaxed">{faq.answer}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-20 bg-gradient-to-r from-orange-500 to-orange-600 text-white relative overflow-hidden">
        <div className="absolute inset-0 bg-black/10"></div>
        <div className="absolute inset-0">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-white/30 to-transparent animate-pulse"></div>
        </div>
        
        <div className="container mx-auto px-6 relative z-10">
          <div className="text-center max-w-4xl mx-auto">
            <h2 className="text-5xl font-bold mb-6">Build your next app in minutes, not months</h2>
            <p className="text-xl text-orange-100 mb-8 max-w-2xl mx-auto">
              Start free. See why teams choose Tesslate Studio.
            </p>
            
            <div className="flex flex-col sm:flex-row gap-4 justify-center mb-8">
              <button
                onClick={handleGetStarted}
                className="bg-white text-orange-600 px-8 py-4 rounded-2xl font-bold text-lg transition-all hover:shadow-xl hover:scale-105 flex items-center justify-center gap-2"
              >
                Start Free
                <ArrowRight className="w-5 h-5" />
              </button>
              <button className="border-2 border-white text-white hover:bg-white hover:text-orange-600 px-8 py-4 rounded-2xl font-bold text-lg transition-all flex items-center justify-center gap-2">
                <PlayCircle className="w-5 h-5" />
                See Demo
              </button>
            </div>
            
            <div className="flex items-center justify-center gap-6 text-sm text-orange-100">
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
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-white py-16">
        <div className="container mx-auto px-6">
          <div className="grid md:grid-cols-4 gap-8 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-orange-500 rounded-xl flex items-center justify-center">
                  <Code size={20} className="text-white" />
                </div>
                <span className="text-xl font-bold">Tesslate Studio</span>
              </div>
              <p className="text-gray-400 mb-6">Build full-stack apps from one prompt with AI-powered design tools.</p>
              
              {/* Newsletter */}
              <form onSubmit={handleNewsletterSubmit} className="space-y-3">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter your email"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-orange-500 text-sm"
                />
                <button
                  type="submit"
                  className="w-full bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded-lg font-medium transition-all text-sm"
                >
                  Subscribe to Updates
                </button>
              </form>
            </div>
            
            <div>
              <h4 className="font-bold mb-4">Product</h4>
              <div className="space-y-2 text-gray-400">
                <a href="#features" className="block hover:text-orange-400 transition-colors">Features</a>
                <a href="#pricing" className="block hover:text-orange-400 transition-colors">Pricing</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">API</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Documentation</a>
              </div>
            </div>
            
            <div>
              <h4 className="font-bold mb-4">Resources</h4>
              <div className="space-y-2 text-gray-400">
                <a href="#" className="block hover:text-orange-400 transition-colors">Blog</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Guides</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Templates</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Community</a>
              </div>
            </div>
            
            <div>
              <h4 className="font-bold mb-4">Company</h4>
              <div className="space-y-2 text-gray-400">
                <a href="#" className="block hover:text-orange-400 transition-colors">About</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Careers</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Contact</a>
                <a href="#" className="block hover:text-orange-400 transition-colors">Privacy</a>
              </div>
            </div>
          </div>
          
          <div className="border-t border-gray-800 pt-8 flex flex-col md:flex-row items-center justify-between">
            <div className="text-gray-400 text-sm mb-4 md:mb-0">
              © 2024 Tesslate Studio. All rights reserved.
            </div>
            
            <div className="flex items-center gap-4">
              <a href="#" className="text-gray-400 hover:text-orange-400 transition-colors">
                <Twitter size={20} />
              </a>
              <a href="#" className="text-gray-400 hover:text-orange-400 transition-colors">
                <Github size={20} />
              </a>
              <a href="#" className="text-gray-400 hover:text-orange-400 transition-colors">
                <Mail size={20} />
              </a>
              <a href="#" className="text-gray-400 hover:text-orange-400 transition-colors">
                <MessageSquare size={20} />
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}