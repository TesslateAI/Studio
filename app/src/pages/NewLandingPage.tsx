import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, ChevronDown, Check, Mail, LogIn } from 'lucide-react';
import toast from 'react-hot-toast';
import axios from 'axios';

// New, minimal landing built fresh (no reuse of old components)
// Theme: black background with gold accents inspired by usetool.bar

const API_URL = import.meta.env.VITE_API_URL || '';

export default function NewLandingPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [faqOpen, setFaqOpen] = useState<number | null>(0);
  const [quickLoginUsername, setQuickLoginUsername] = useState('');

  // Page-scoped CSS variables so we don't depend on global theme file
  const vars = useMemo(() => ({
    // Core palette
    ['--primary' as any]: '#D4AF37',      // base gold for icons/text
    ['--gold1' as any]: '#FFE27A',        // bright gold (start)
    ['--gold2' as any]: '#D4AF37',        // rich gold (end)
    ['--goldShadow' as any]: 'rgba(255, 226, 122, 0.35)',
    ['--text' as any]: '#E6E6E6',
    ['--muted' as any]: 'rgba(230,230,230,0.65)',
    ['--bg' as any]: '#0a0a0a',
    ['--surface' as any]: '#121212',
    ['--border' as any]: 'rgba(212,175,55,0.18)'
  }), []);

  const handleGetStarted = () => {
    const token = localStorage.getItem('token');
    if (token) navigate('/dashboard');
    else navigate('/login');
  };

  const handleQuickLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickLoginUsername.trim()) return;

    try {
      const response = await axios.post(`${API_URL}/api/auth/login`, {
        username: quickLoginUsername.trim(),
        password: quickLoginUsername.trim(),
      });

      const { access_token, refresh_token } = response.data;
      localStorage.setItem('token', access_token);
      if (refresh_token) {
        localStorage.setItem('refreshToken', refresh_token);
      }

      toast.success('Logged in successfully!');
      navigate('/dashboard');
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Login failed');
    }
  };

  const onSubscribe = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    toast.success("Subscribed! You'll receive updates soon.");
    setEmail('');
  };

  const faqs = [
    {
      q: 'How does UIGEN-X compare to Claude for design quality?',
      a: 'UIGEN-X delivers Claude-level design quality through advanced AI models optimized specifically for UI generation, at a fraction of the cost through efficient processing and caching.'
    },
    {
      q: 'Can I export clean code?',
      a: 'Yes! Tesslate Studio generates production-ready React/TypeScript code with Tailwind CSS that you can export, modify, and deploy anywhere.'
    },
    {
      q: 'How does Studio handle auth & databases?',
      a: 'Studio automatically generates complete authentication flows and database schemas, with support for popular providers like Supabase, Firebase, and custom solutions.'
    },
    {
      q: "What's the deployment path?",
      a: 'One-click deployment to Vercel, Netlify, or your own infrastructure. Studio handles build optimization and environment configuration automatically.'
    },
    {
      q: 'Can teams collaborate live?',
      a: 'Yes! Real-time collaboration with live cursors, comments, and version control. Perfect for design reviews and pair programming sessions.'
    }
  ];

  return (
    <div style={vars as React.CSSProperties} className="min-h-screen" >
      {/* NAVBAR */}
      <header className="sticky top-0 z-40 border-b" style={{ background: 'rgba(10,10,10,0.85)', backdropFilter: 'blur(10px)', borderColor: 'var(--border)' }}>
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <a href="#top" className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: 'var(--primary)' }} />
            <span className="text-sm tracking-widest" style={{ color: 'var(--muted)' }}>TESSLATE</span>
          </a>
          <nav className="hidden md:flex items-center gap-8 text-sm" style={{ color: 'var(--muted)' }}>
            <a href="#features" className="hover:opacity-100 opacity-70">Features</a>
            <a href="#how" className="hover:opacity-100 opacity-70">How it Works</a>
            <a href="#pricing" className="hover:opacity-100 opacity-70">Pricing</a>
            <a href="#faq" className="hover:opacity-100 opacity-70">FAQ</a>
          </nav>
          <div className="flex items-center gap-3">
            {/* Quick Login */}
            <form onSubmit={handleQuickLogin} className="hidden sm:flex items-stretch">
              <input
                value={quickLoginUsername}
                onChange={(e) => setQuickLoginUsername(e.target.value)}
                placeholder="Quick login..."
                className="px-3 py-2 text-sm outline-none w-32"
                style={{ background: 'var(--surface)', color: 'var(--text)', border: `1px solid var(--border)`, borderRadius: '999px 0 0 999px' }}
              />
              <button type="submit" className="px-3 py-2 text-sm flex items-center gap-1" style={{ background: 'var(--surface)', color: 'var(--muted)', border: `1px solid var(--border)`, borderLeft: 'none', borderRadius: '0 999px 999px 0' }}>
                <LogIn size={14} />
              </button>
            </form>
            <button onClick={() => navigate('/login')} className="px-3 py-2 text-sm rounded-full hover:opacity-100 opacity-80" style={{ color: 'var(--muted)' }}>Sign in</button>
            <button onClick={handleGetStarted} className="px-4 py-2 rounded-full text-sm font-semibold flex items-center gap-2 shadow-md" style={{ background: 'linear-gradient(135deg, var(--gold1), var(--gold2))', color: '#0a0a0a', boxShadow: '0 6px 24px var(--goldShadow)' }}>
              Get started <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section id="top" className="relative">
        <div className="mx-auto max-w-5xl px-6 pt-28 pb-10 text-center">
          <h1 className="mx-auto font-extrabold leading-[1.05] tracking-tight" style={{ color: 'var(--text)', fontSize: 'clamp(40px,7vw,84px)' }}>
            Build full‑stack apps from one prompt
          </h1>
          <p className="mt-6 max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>
            Track, design, and ship directly in your browser with an AI toolkit that assembles UI, API, data and auth—fast.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <button onClick={handleGetStarted} className="px-6 py-3 rounded-full font-semibold flex items-center gap-2 shadow-lg" style={{ background: 'linear-gradient(135deg, var(--gold1), var(--gold2))', color: '#0a0a0a', boxShadow: '0 10px 28px var(--goldShadow)' }}>
              Start free <ArrowRight size={18} />
            </button>
            <form onSubmit={onSubscribe} className="flex items-stretch w-full sm:w-auto">
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="px-4 py-3 rounded-l-full text-sm w-64 outline-none"
                style={{ background: 'var(--surface)', color: 'var(--text)', border: `1px solid var(--border)` }}
              />
              <button type="submit" className="px-4 py-3 rounded-r-full text-sm font-medium flex items-center gap-2" style={{ background: 'var(--surface)', color: 'var(--muted)', border: `1px solid var(--border)`, borderLeft: 'none' }}>
                <Mail size={16} /> Subscribe
              </button>
            </form>
          </div>
          <div className="mt-4 text-xs" style={{ color: 'var(--muted)' }}>
            <span className="inline-flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--primary)' }} /> 4.9/5 From people that create cool stuff</span>
          </div>
        </div>
      </section>

      {/* FEATURES - minimal three blurbs with icon on top (no borders, no titles) */}
      <section id="features" className="py-16">
        <div className="mx-auto max-w-5xl px-6">
          <div className="grid md:grid-cols-3 gap-10 text-center">
            {/* Blurb 1 */}
            <div className="px-6">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mx-auto mb-4 opacity-70"
                style={{ color: 'rgba(230,230,230,0.65)' }}
              >
                <rect x="4" y="4" width="16" height="16" rx="2"/>
                <path d="M4 8h16"/>
                <rect x="7" y="11" width="4" height="6" rx="1"/>
                <rect x="13" y="11" width="4" height="6" rx="1"/>
              </svg>
              <p className="leading-relaxed" style={{ color: 'var(--muted)' }}>
                Generate production‑ready UIs from a single prompt—beautiful, responsive, and consistent.
              </p>
            </div>

            {/* Blurb 2 */}
            <div className="px-6">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mx-auto mb-4 opacity-70"
                style={{ color: 'rgba(230,230,230,0.65)' }}
              >
                <rect x="5" y="5" width="14" height="4" rx="1"/>
                <rect x="5" y="10" width="14" height="4" rx="1"/>
                <rect x="5" y="15" width="14" height="4" rx="1"/>
                <path d="M19 7h1.5"/>
                <path d="M19 12h1.5"/>
                <path d="M19 17h1.5"/>
              </svg>
              <p className="leading-relaxed" style={{ color: 'var(--muted)' }}>
                Auto‑assemble UI, API, database, and auth from one prompt—full‑stack, wired end‑to‑end.
              </p>
            </div>

            {/* Blurb 3 */}
            <div className="px-6">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mx-auto mb-4 opacity-70"
                style={{ color: 'rgba(230,230,230,0.65)' }}
              >
                <path d="M8 8l-4 4 4 4"/>
                <path d="M16 8l4 4-4 4"/>
                <path d="M12 12l6-6"/>
                <path d="M14 6h4v4"/>
              </svg>
              <p className="leading-relaxed" style={{ color: 'var(--muted)' }}>
                Export clean React + TypeScript code or one‑click deploy to your infrastructure.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* WHY TESSLATE STUDIO – four cards */}
      <section id="why" className="py-20">
        <div className="mx-auto max-w-6xl px-6 text-center">
          <h2 className="text-3xl font-semibold" style={{ color: 'var(--text)' }}>Get 10x more done, fast.</h2>
          <p className="mt-2" style={{ color: 'var(--muted)' }}>
            Experience the future of full‑stack development with AI‑powered tools that understand your vision.
          </p>
        </div>
        <div className="mx-auto max-w-5xl px-6 mt-10">
          <div className="space-y-6">
            {/* Card 1 */}
            <div className="p-10 md:p-12 rounded-[32px] relative overflow-hidden" style={{ background: 'var(--surface)', border: `1px solid var(--border)`, boxShadow: '0 20px 60px rgba(0,0,0,0.35)' }}>
              <div className="absolute inset-0 opacity-[.35] pointer-events-none" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)', backgroundSize: '30px 30px' }} />
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(1200px 200px at 40% -20%, rgba(255,255,255,0.05), transparent 60%)' }} />
              <div className="relative grid md:grid-cols-2 gap-8 items-center">
                <div>
                  <div className="text-[26px] md:text-[28px] font-medium leading-snug" style={{ color: 'var(--text)' }}>Claude-like design, 1/10th the cost</div>
                  <p className="text-sm md:text-[15px] mt-3" style={{ color: 'var(--muted)' }}>
                    Premium design quality powered by UIGEN-X at a fraction of traditional costs.
                  </p>
                </div>
                <div className="hidden md:block relative">
                  <div className="h-[220px] rounded-[20px]" style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid var(--border)` }} />
                  <div className="absolute right-6 top-6 w-[260px] rounded-2xl p-3" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))', border: `1px solid var(--border)`, boxShadow: '0 6px 20px rgba(0,0,0,0.35)' }}>
                    {[
                      ['Viewport', '1823x1200'],
                      ['Browser', 'Chrome'],
                      ['Device', 'iPhone'],
                      ['Operating System', 'iOS'],
                    ].map(([k,v]) => (
                      <div key={k as string} className="flex items-center justify-between py-1.5 text-[12px]">
                        <span style={{ color: 'var(--muted)' }}>{k as string}</span>
                        <span style={{ color: 'var(--text)' }}>{v as string}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Card 2 */}
            <div className="p-10 md:p-12 rounded-[32px] relative overflow-hidden" style={{ background: 'var(--surface)', border: `1px solid var(--border)`, boxShadow: '0 20px 60px rgba(0,0,0,0.35)' }}>
              <div className="absolute inset-0 opacity-[.35] pointer-events-none" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)', backgroundSize: '30px 30px' }} />
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(1200px 200px at 60% -20%, rgba(255,255,255,0.05), transparent 60%)' }} />
              <div className="relative grid md:grid-cols-2 gap-8 items-center">
                <div>
                  <div className="text-[26px] md:text-[28px] font-semibold leading-snug" style={{ color: 'var(--text)' }}>Full‑stack, not just front‑end</div>
                  <p className="text-sm md:text-[15px] mt-3" style={{ color: 'var(--muted)' }}>
                    Generate UI, API, database, and authentication together—wired end‑to‑end from one prompt.
                  </p>
                </div>
                <div className="hidden md:block relative">
                  <div className="h-[220px] rounded-[20px]" style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid var(--border)` }} />
                  <div className="absolute right-6 top-6 w-[260px] rounded-2xl p-3" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))', border: `1px solid var(--border)`, boxShadow: '0 6px 20px rgba(0,0,0,0.35)' }}>
                    {[
                      ['Realtime', '23ms'],
                      ['Sync', 'Always'],
                      ['Cursors', 'Live'],
                      ['Comments', 'Threaded'],
                    ].map(([k,v]) => (
                      <div key={k as string} className="flex items-center justify-between py-1.5 text-[12px]">
                        <span style={{ color: 'var(--muted)' }}>{k as string}</span>
                        <span style={{ color: 'var(--text)' }}>{v as string}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Card 3 */}
            <div className="p-10 md:p-12 rounded-[32px] relative overflow-hidden" style={{ background: 'var(--surface)', border: `1px solid var(--border)`, boxShadow: '0 20px 60px rgba(0,0,0,0.35)' }}>
              <div className="absolute inset-0 opacity-[.35] pointer-events-none" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)', backgroundSize: '30px 30px' }} />
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(1200px 200px at 40% -20%, rgba(255,255,255,0.05), transparent 60%)' }} />
              <div className="relative grid md:grid-cols-2 gap-8 items-center">
                <div>
                  <div className="text-[26px] md:text-[28px] font-semibold leading-snug" style={{ color: 'var(--text)' }}>Collaborative & real‑time</div>
                  <p className="text-sm md:text-[15px] mt-3" style={{ color: 'var(--muted)' }}>
                    Work together with live cursors, comments, and instant synchronization across your team.
                  </p>
                </div>
                <div className="hidden md:block relative">
                  <div className="h-[220px] rounded-[20px]" style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid var(--border)` }} />
                  <div className="absolute right-6 top-6 w-[240px] rounded-2xl p-2.5" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))', border: `1px solid var(--border)`, boxShadow: '0 6px 20px rgba(0,0,0,0.35)' }}>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="w-2 h-2 rounded-full" style={{ background: '#22c55e' }} />
                      <span style={{ color: 'var(--text)' }}>Realtime</span>
                      <span className="ml-auto px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--muted)' }}>23ms</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Card 4 */}
            <div className="p-10 md:p-12 rounded-[32px] relative overflow-hidden" style={{ background: 'var(--surface)', border: `1px solid var(--border)`, boxShadow: '0 20px 60px rgba(0,0,0,0.35)' }}>
              <span className="absolute right-6 top-6 w-5 h-5 rounded-full grid place-items-center text-[10px]" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>✔</span>
              <div className="absolute inset-0 opacity-[.35] pointer-events-none" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)', backgroundSize: '30px 30px' }} />
              <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(1200px 200px at 60% -20%, rgba(255,255,255,0.05), transparent 60%)' }} />
              <div className="relative grid md:grid-cols-2 gap-8 items-center">
                <div>
                  <div className="text-[26px] md:text-[28px] font-semibold leading-snug" style={{ color: 'var(--text)' }}>Enterprise‑grade output</div>
                  <p className="text-sm md:text-[15px] mt-3" style={{ color: 'var(--muted)' }}>
                    Production‑ready code with security best practices, testing, and scalability built‑in.
                  </p>
                </div>
                <div className="hidden md:block relative">
                  <div className="h-[220px] rounded-[20px]" style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid var(--border)` }} />
                  <div className="absolute right-6 top-6 w-[220px] rounded-2xl p-2.5" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))', border: `1px solid var(--border)`, boxShadow: '0 6px 20px rgba(0,0,0,0.35)' }}>
                    <div className="text-[11px]" style={{ color: 'var(--text)' }}>Checks</div>
                    <div className="mt-1 space-y-1.5">
                      {['Security', 'Tests', 'Scalability'].map((k) => (
                        <div key={k} className="flex items-center gap-2 text-[11px]">
                          <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#22c55e' }} />
                          <span style={{ color: 'var(--muted)' }}>{k}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="text-3xl font-bold mb-8" style={{ color: 'var(--text)' }}>How it works</h2>
          <ol className="space-y-4">
            {[ 'Prompt', 'Assemble', 'Refine', 'Deploy' ].map((step, i) => (
              <li key={step} className="p-5 rounded-[18px] flex items-start gap-4" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
                <div className="w-8 h-8 rounded-full grid place-items-center text-sm font-bold" style={{ background: 'rgba(255, 226, 122, 0.2)', color: 'var(--primary)' }}>{i+1}</div>
                <div>
                  <div className="font-semibold" style={{ color: 'var(--text)' }}>{step}</div>
                  <p className="text-sm mt-1" style={{ color: 'var(--muted)' }}>
                    {step === 'Prompt' && 'Describe what you want to build in plain English.'}
                    {step === 'Assemble' && 'We generate UI, API, DB and auth scaffolding—wired together.'}
                    {step === 'Refine' && 'Tune styles and logic with instant preview.'}
                    {step === 'Deploy' && 'Ship to your infra or export clean code.'}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="text-3xl font-bold mb-8" style={{ color: 'var(--text)' }}>Simple, Transparent Pricing</h2>
          <p className="mb-6 text-lg" style={{ color: 'var(--muted)' }}>Claude-like designs at 1/10th the cost—thanks to UIGEN-X.</p>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="p-6 rounded-[22px]" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="text-sm mb-2" style={{ color: 'var(--muted)' }}>Traditional build</div>
              <div className="text-2xl font-bold" style={{ color: 'var(--text)' }}>$50k–$200k</div>
              <ul className="mt-4 space-y-2 text-sm" style={{ color: 'var(--muted)' }}>
                <li className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--primary)' }} /> 6–12 months</li>
                <li className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--primary)' }} /> 5–10 developers</li>
              </ul>
            </div>
            <div className="p-6 rounded-[22px] relative" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="text-sm mb-2" style={{ color: 'var(--muted)' }}>Tesslate Studio</div>
              <div className="text-2xl font-bold" style={{ color: 'var(--text)' }}>$99–$499 / mo</div>
              <ul className="mt-4 space-y-2 text-sm" style={{ color: 'var(--muted)' }}>
                <li className="flex items-center gap-2"><Check size={14} style={{ color: 'var(--primary)' }} /> Days to weeks</li>
                <li className="flex items-center gap-2"><Check size={14} style={{ color: 'var(--primary)' }} /> AI‑powered team</li>
              </ul>
              <button onClick={handleGetStarted} className="mt-6 px-5 py-3 rounded-full font-semibold shadow-md" style={{ background: 'linear-gradient(135deg, var(--gold1), var(--gold2))', color: '#0a0a0a', boxShadow: '0 8px 24px var(--goldShadow)' }}>Start free today</button>
            </div>
          </div>
        </div>
      </section>

      {/* WHO IT'S FOR */}
      <section id="who" className="py-20">
        <div className="mx-auto max-w-6xl px-6 text-center">
          <h2 className="text-3xl font-bold" style={{ color: 'var(--text)' }}>Who It's For</h2>
          <p className="mt-2" style={{ color: 'var(--muted)' }}>Perfect for teams and individuals who want to build faster.</p>
        </div>
        <div className="mx-auto max-w-6xl px-6 mt-10">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* Startups */}
            <div className="p-6 rounded-[22px]" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="font-semibold" style={{ color: 'var(--text)' }}>Startups</div>
              <p className="text-sm mt-2" style={{ color: 'var(--muted)' }}>Launch your MVP fast and iterate quickly with professional‑grade designs.</p>
            </div>
            {/* Designers */}
            <div className="p-6 rounded-[22px]" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="font-semibold" style={{ color: 'var(--text)' }}>Designers</div>
              <p className="text-sm mt-2" style={{ color: 'var(--muted)' }}>Turn your designs into working applications without learning to code.</p>
            </div>
            {/* Enterprises */}
            <div className="p-6 rounded-[22px]" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="font-semibold" style={{ color: 'var(--text)' }}>Enterprises</div>
              <p className="text-sm mt-2" style={{ color: 'var(--muted)' }}>Scale your development team with AI‑powered tools and enterprise security.</p>
            </div>
            {/* Creators */}
            <div className="p-6 rounded-[22px]" style={{ background: 'var(--surface)', border: `1px solid var(--border)` }}>
              <div className="font-semibold" style={{ color: 'var(--text)' }}>Creators</div>
              <p className="text-sm mt-2" style={{ color: 'var(--muted)' }}>Build and monetize your ideas with professional tools and seamless workflows.</p>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-20">
        <div className="mx-auto max-w-4xl px-6">
          <h2 className="text-3xl font-bold mb-6" style={{ color: 'var(--text)' }}>Frequently asked questions</h2>
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {faqs.map((f, i) => (
              <div key={i}>
                <button onClick={() => setFaqOpen(faqOpen === i ? null : i)} className="w-full py-4 flex items-center justify-between">
                  <span className="text-left font-medium" style={{ color: 'var(--text)' }}>{f.q}</span>
                  <ChevronDown size={18} className={`transition-transform ${faqOpen===i? 'rotate-180':''}`} style={{ color: 'var(--muted)' }} />
                </button>
                <div className="pb-4 text-sm" style={{ color: 'var(--muted)', display: faqOpen===i? 'block':'none' }}>{f.a}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section id="cta-final" className="py-20 relative overflow-hidden">
        <div className="absolute inset-0 opacity-[.12] pointer-events-none" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)', backgroundSize: '30px 30px' }} />
        <div className="mx-auto max-w-4xl px-6 text-center relative">
          <h2 className="text-4xl font-bold" style={{ color: 'var(--text)' }}>Build your next app in minutes, not months</h2>
          <p className="mt-3 text-lg" style={{ color: 'var(--muted)' }}>Start free. See why teams choose Tesslate Studio.</p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <button onClick={handleGetStarted} className="px-6 py-3 rounded-full font-semibold shadow-lg" style={{ background: 'linear-gradient(135deg, var(--gold1), var(--gold2))', color: '#0a0a0a', boxShadow: '0 10px 30px var(--goldShadow)' }}>Start Free</button>
            <button className="px-6 py-3 rounded-full font-semibold" style={{ background: 'transparent', color: 'var(--primary)', border: '1px solid var(--border)' }}>See Demo</button>
          </div>
          <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-6 text-sm" style={{ color: 'var(--muted)' }}>
            <div className="flex items-center gap-2"><Check size={14} style={{ color: 'var(--primary)' }} /> Free forever plan</div>
            <div className="flex items-center gap-2"><Check size={14} style={{ color: 'var(--primary)' }} /> No credit card required</div>
            <div className="flex items-center gap-2"><Check size={14} style={{ color: 'var(--primary)' }} /> Cancel anytime</div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="mx-auto max-w-6xl px-6 py-10">
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-10 flex-wrap">
            <div className="min-w-[260px]">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: 'var(--primary)' }} />
                <span className="text-sm tracking-widest" style={{ color: 'var(--muted)' }}>TESSLATE</span>
              </div>
              <p className="mt-3 max-w-sm text-sm" style={{ color: 'var(--muted)' }}>
                Build full‑stack apps from one prompt with AI‑powered design tools.
              </p>
            </div>
            <form onSubmit={onSubscribe} className="flex items-stretch">
              <input
                value={email}
                onChange={(e)=>setEmail(e.target.value)}
                placeholder="Enter your email"
                className="px-4 py-3 rounded-l-full text-sm w-64 outline-none"
                style={{ background: 'var(--surface)', color: 'var(--text)', border: `1px solid var(--border)` }}
              />
              <button type="submit" className="px-4 py-3 rounded-r-full text-sm font-medium shadow-md" style={{ background: 'linear-gradient(135deg, var(--gold1), var(--gold2))', color: '#0a0a0a', boxShadow: '0 6px 20px var(--goldShadow)' }}>Subscribe</button>
            </form>

            {/* Footer link columns */}
            <div className="grid grid-cols-2 gap-10 w-full md:w-auto">
              <div>
                <div className="text-base font-semibold mb-3" style={{ color: 'var(--text)' }}>Resources</div>
                <ul className="space-y-2 text-sm">
                  {['Blog', 'Guides', 'Templates', 'Community'].map((item) => (
                    <li key={item}><a href="#resources" className="hover:opacity-100 opacity-80" style={{ color: 'var(--muted)' }}>{item}</a></li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="text-base font-semibold mb-3" style={{ color: 'var(--text)' }}>Company</div>
                <ul className="space-y-2 text-sm">
                  {['About', 'Careers', 'Contact', 'Privacy'].map((item) => (
                    <li key={item}><a href="#company" className="hover:opacity-100 opacity-80" style={{ color: 'var(--muted)' }}>{item}</a></li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
          <div className="mt-8 text-xs flex items-center gap-6 flex-wrap" style={{ color: 'var(--muted)' }}>
            <a href="#features">Features</a>
            <a href="#how">How it Works</a>
            <a href="#pricing">Pricing</a>
            <a href="#resources">Resources</a>
            <a href="#company">Company</a>
            <a href="#faq">FAQ</a>
            <span className="opacity-60">© {new Date().getFullYear()} Tesslate Studio</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
