import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useReferralTracking } from '../hooks/useReferralTracking';

// ANSI-shadow ASCII art for "Tesslate Studio"
const ASCII_ART = `
████████╗███████╗███████╗███████╗██╗      █████╗ ████████╗███████╗
╚══██╔══╝██╔════╝██╔════╝██╔════╝██║     ██╔══██╗╚══██╔══╝██╔════╝
   ██║   █████╗  ███████╗███████╗██║     ███████║   ██║   █████╗
   ██║   ██╔══╝  ╚════██║╚════██║██║     ██╔══██║   ██║   ██╔══╝
   ██║   ███████╗███████║███████║███████╗██║  ██║   ██║   ███████╗
   ╚═╝   ╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝

███████╗████████╗██╗   ██╗██████╗ ██╗ ██████╗
██╔════╝╚══██╔══╝██║   ██║██╔══██╗██║██╔═══██╗
███████╗   ██║   ██║   ██║██║  ██║██║██║   ██║
╚════██║   ██║   ██║   ██║██║  ██║██║██║   ██║
███████║   ██║   ╚██████╔╝██████╔╝██║╚██████╔╝
╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝
`;

interface ColorTheme {
  bg: string;
  text: string;
  accent: string;
  dim: string;
  name: string;
}

const ORANGE_THEME: ColorTheme = {
  name: 'Orange',
  bg: '#0a0a0a',
  text: '#ff9d00',
  accent: '#ff6b00',
  dim: '#b87400'
};

const COLOR_THEMES: ColorTheme[] = [
  ORANGE_THEME,
  { name: 'Matrix', bg: '#0d0208', text: '#00ff41', accent: '#008f11', dim: '#00aa1a' },
  { name: 'Amber', bg: '#000000', text: '#ffb000', accent: '#ff6600', dim: '#cc8800' },
  { name: 'Blue', bg: '#001f3f', text: '#7fdbff', accent: '#0074d9', dim: '#4da6ff' },
  { name: 'Purple', bg: '#1a0033', text: '#e0b0ff', accent: '#9d00ff', dim: '#b84dff' },
  { name: 'Cyan', bg: '#001a1a', text: '#00ffff', accent: '#00cccc', dim: '#00e6e6' },
  { name: 'Hacker', bg: '#0a0e27', text: '#00ff00', accent: '#39ff14', dim: '#00cc00' },
  { name: 'Dracula', bg: '#282a36', text: '#f8f8f2', accent: '#bd93f9', dim: '#ddbfff' },
];

type Section = 'boot' | 'welcome' | 'mission' | 'features' | 'architecture' | 'opensource' | 'prompt' | 'theme' | 'done';

const FEATURES = [
  { icon: '🤖', title: 'AI-Powered Development', desc: 'Natural language to full-stack code in seconds', command: 'ai.generate' },
  { icon: '👁️', title: 'Live Preview', desc: 'Instant visual feedback with Hot Module Replacement', command: 'preview.start' },
  { icon: '🐙', title: 'Git Integration', desc: 'Full GitHub OAuth, push, pull, and version control', command: 'git.connect' },
  { icon: '📦', title: 'Agent Marketplace', desc: 'Browse and install specialized AI coding agents', command: 'market.browse' },
  { icon: '🎨', title: 'In-Browser IDE', desc: 'Monaco editor with syntax highlighting and file tree', command: 'ide.launch' },
  { icon: '📊', title: 'Kanban Board', desc: 'Built-in project management for organized development', command: 'kanban.open' },
];

const ARCHITECTURE_POINTS = [
  { icon: '🐳', title: 'Docker + Kubernetes', desc: 'Local dev or production-scale deployment', status: '[READY]' },
  { icon: '🔒', title: 'Isolated Environments', desc: 'Each project runs in its own container/pod', status: '[ACTIVE]' },
  { icon: '⚡', title: 'FastAPI Backend', desc: 'High-performance Python orchestrator', status: '[ONLINE]' },
  { icon: '⚛️', title: 'React + Vite Frontend', desc: 'Lightning-fast modern web stack', status: '[LOADED]' },
];

const OPENSOURCE_BENEFITS = [
  '✓ Complete code ownership - No vendor lock-in',
  '✓ Self-host anywhere - Your infrastructure, your rules',
  '✓ Full transparency - See exactly how it works',
  '✓ Customize everything - Modify core platform freely',
];

const BOOT_SEQUENCE = [
  'BIOS v2.4.1 - Initializing...',
  'CPU: AI Orchestrator Core [OK]',
  'Memory: Project Isolation Manager [OK]',
  'Storage: Docker Volume System [OK]',
  'Network: Kubernetes Mesh [OK]',
  'Loading Tesslate Studio...',
  'Mounting /dev/creativity...',
  'Starting AI agents...',
  'System ready.',
];

export default function TerminalLandingPage() {
  useReferralTracking();

  const navigate = useNavigate();
  const [section, setSection] = useState<Section>('boot');
  const [selectedTheme, setSelectedTheme] = useState<ColorTheme>(ORANGE_THEME);
  const [prompt, setPrompt] = useState('');
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showContent, setShowContent] = useState(false);
  const [bootLines, setBootLines] = useState<string[]>([]);
  const [showHelp, setShowHelp] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Load saved preferences
  useEffect(() => {
    const savedTheme = sessionStorage.getItem('terminal_theme');
    const savedPrompt = sessionStorage.getItem('project_prompt');

    if (savedTheme) {
      const theme = COLOR_THEMES.find(t => t.name === savedTheme);
      if (theme) setSelectedTheme(theme);
    }
    if (savedPrompt) setPrompt(savedPrompt);
  }, []);

  // Boot sequence animation
  useEffect(() => {
    if (section === 'boot') {
      let currentLine = 0;
      const bootInterval = setInterval(() => {
        if (currentLine < BOOT_SEQUENCE.length) {
          setBootLines(prev => [...prev, BOOT_SEQUENCE[currentLine]]);
          currentLine++;
        } else {
          clearInterval(bootInterval);
          setTimeout(() => {
            setSection('welcome');
          }, 500);
        }
      }, 150);

      return () => clearInterval(bootInterval);
    }
  }, [section]);

  // Typing animation
  const typeText = (text: string, callback?: () => void) => {
    setIsTyping(true);
    setDisplayedText('');
    let i = 0;
    const interval = setInterval(() => {
      if (i < text.length) {
        setDisplayedText(text.substring(0, i + 1));
        i++;
      } else {
        clearInterval(interval);
        setIsTyping(false);
        if (callback) callback();
      }
    }, 20);
  };

  useEffect(() => {
    if (section === 'welcome') {
      typeText('Welcome to Tesslate Studio', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'mission') {
      setShowContent(false);
      typeText('tesslate --info mission', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'features') {
      setShowContent(false);
      typeText('tesslate --list features', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'architecture') {
      setShowContent(false);
      typeText('tesslate --describe architecture', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'opensource') {
      setShowContent(false);
      typeText('tesslate --status opensource', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'prompt') {
      setShowContent(false);
      typeText('tesslate --create project', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    } else if (section === 'theme') {
      setShowContent(false);
      typeText('tesslate --config theme', () => {
        setTimeout(() => setShowContent(true), 300);
      });
    }
  }, [section]);

  const handleNext = (nextSection: Section) => {
    setShowContent(false);
    setTimeout(() => setSection(nextSection), 300);
  };

  const handlePromptSubmit = () => {
    if (prompt.trim()) {
      sessionStorage.setItem('project_prompt', prompt.trim());
      sessionStorage.setItem('terminal_theme', selectedTheme.name);
      setSection('done');
      typeText('Initializing workspace...', () => {
        setTimeout(() => {
          const token = localStorage.getItem('token');
          if (token) {
            navigate('/dashboard');
          } else {
            navigate('/register');
          }
        }, 500);
      });
    }
  };

  const handleSkip = () => {
    const token = localStorage.getItem('token');
    if (token) {
      navigate('/dashboard');
    } else {
      navigate('/register');
    }
  };

  const theme = selectedTheme;

  if (section === 'boot') {
    return (
      <div
        style={{
          backgroundColor: '#000',
          color: '#00ff00',
          minHeight: '100vh',
          width: '100vw',
          fontFamily: "'Courier New', Courier, monospace",
          padding: '1rem',
          overflow: 'auto',
          position: 'relative',
        }}
      >
        <div style={{ maxWidth: '800px', margin: '0 auto', padding: '1rem' }}>
          {bootLines.map((line, idx) => (
            <div
              key={idx}
              style={{
                marginBottom: '0.5rem',
                fontSize: 'clamp(0.75rem, 2vw, 0.9rem)',
                animation: 'fadeIn 0.3s',
              }}
            >
              {line}
            </div>
          ))}
          <div style={{ marginTop: '1rem' }}>
            <span style={{ animation: 'blink 1s infinite' }}>▊</span>
          </div>
        </div>

        <style>{`
          @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
          }
          @keyframes blink {
            0%, 49% { opacity: 1; }
            50%, 100% { opacity: 0; }
          }
        `}</style>
      </div>
    );
  }

  return (
    <div
      style={{
        backgroundColor: theme.bg,
        color: theme.text,
        minHeight: '100vh',
        width: '100vw',
        fontFamily: "'Courier New', Courier, monospace",
        padding: '1rem',
        overflow: 'auto',
        position: 'relative',
      }}
    >
      {/* CRT Scanline effect */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          background: `repeating-linear-gradient(
            0deg,
            rgba(0, 0, 0, 0.15),
            rgba(0, 0, 0, 0.15) 1px,
            transparent 1px,
            transparent 2px
          )`,
          pointerEvents: 'none',
          zIndex: 100,
          animation: 'scanline 8s linear infinite',
        }}
      />

      {/* CRT Glow effect */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          boxShadow: `inset 0 0 100px ${theme.accent}33`,
          pointerEvents: 'none',
          zIndex: 99,
        }}
      />

      {/* Help and Skip buttons - floating in top-right */}
      <div
        style={{
          position: 'fixed',
          top: '1rem',
          right: '1rem',
          display: 'flex',
          gap: '0.5rem',
          zIndex: 101,
        }}
      >
        <button
          onClick={() => setShowHelp(!showHelp)}
          style={{
            background: 'transparent',
            border: `1px solid ${theme.accent}`,
            color: theme.accent,
            padding: '0.5rem 1rem',
            cursor: 'pointer',
            fontFamily: "'Courier New', Courier, monospace",
            fontSize: 'clamp(0.75rem, 2vw, 0.9rem)',
            borderRadius: '4px',
            boxShadow: `0 0 15px ${theme.accent}44`,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = theme.accent;
            e.currentTarget.style.color = theme.bg;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent';
            e.currentTarget.style.color = theme.accent;
          }}
        >
          HELP
        </button>
        <button
          onClick={handleSkip}
          style={{
            background: 'transparent',
            border: `1px solid ${theme.accent}`,
            color: theme.accent,
            padding: '0.5rem 1rem',
            cursor: 'pointer',
            fontFamily: "'Courier New', Courier, monospace",
            fontSize: 'clamp(0.75rem, 2vw, 0.9rem)',
            borderRadius: '4px',
            boxShadow: `0 0 15px ${theme.accent}44`,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = theme.accent;
            e.currentTarget.style.color = theme.bg;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent';
            e.currentTarget.style.color = theme.accent;
          }}
        >
          SKIP
        </button>
      </div>

      {/* Help Panel */}
      {showHelp && (
        <div
          style={{
            position: 'fixed',
            top: '4rem',
            right: '1rem',
            maxWidth: '90vw',
            width: '350px',
            background: `${theme.bg}f5`,
            border: `2px solid ${theme.accent}`,
            borderRadius: '8px',
            padding: '1rem',
            zIndex: 102,
            backdropFilter: 'blur(10px)',
            boxShadow: `0 8px 32px ${theme.accent}33`,
            fontSize: 'clamp(0.75rem, 2vw, 0.9rem)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem', alignItems: 'center' }}>
            <h3 style={{ margin: 0, color: theme.accent, fontSize: 'clamp(1rem, 3vw, 1.2rem)' }}>Help & Navigation</h3>
            <button
              onClick={() => setShowHelp(false)}
              style={{
                background: 'transparent',
                border: 'none',
                color: theme.accent,
                cursor: 'pointer',
                fontSize: '1.5rem',
                lineHeight: '1',
                padding: '0',
              }}
            >
              ×
            </button>
          </div>
          <div style={{ color: theme.dim, lineHeight: '1.6' }}>
            <p style={{ marginBottom: '0.75rem' }}>
              <strong style={{ color: theme.text }}>What is this?</strong><br />
              An interactive terminal showcasing Tesslate Studio - an open-source AI development platform.
            </p>
            <p style={{ marginBottom: '0.75rem' }}>
              <strong style={{ color: theme.text }}>How to use:</strong><br />
              • Click buttons to navigate sections<br />
              • Customize your terminal theme<br />
              • Enter your project idea at the end<br />
              • Or skip to dashboard anytime
            </p>
            <p style={{ marginBottom: '0' }}>
              <strong style={{ color: theme.text }}>For non-developers:</strong><br />
              Don't worry! This is just a visual experience. Click through to learn about building apps with AI.
            </p>
          </div>
        </div>
      )}

      <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '1rem', position: 'relative', zIndex: 2 }}>
        {/* ASCII Art Logo with gradient animation */}
        <pre
          style={{
            color: theme.accent,
            fontSize: 'clamp(0.25rem, 1vw, 0.8rem)',
            lineHeight: '1.2',
            marginBottom: '1.5rem',
            textAlign: 'center',
            whiteSpace: 'pre',
            overflow: 'auto',
            textShadow: `0 0 10px ${theme.accent}88, 0 0 20px ${theme.accent}44`,
            animation: 'pulse 4s ease-in-out infinite',
          }}
        >
          {ASCII_ART}
        </pre>

        {/* Terminal Prompt Line */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ marginBottom: '1rem', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ color: theme.accent, textShadow: `0 0 5px ${theme.accent}`, fontSize: 'clamp(0.8rem, 2vw, 1rem)' }}>
              user@tesslate:~$
            </span>
            <span style={{ flex: '1', minWidth: '150px', fontSize: 'clamp(0.8rem, 2vw, 1rem)' }}>{displayedText}</span>
            {isTyping && (
              <span
                style={{
                  animation: 'blink 1s infinite',
                  marginLeft: '2px',
                  textShadow: `0 0 5px ${theme.text}`,
                }}
              >
                ▊
              </span>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div
          ref={contentRef}
          style={{
            marginTop: '1.5rem',
            opacity: showContent ? 1 : 0,
            transition: 'opacity 0.5s',
          }}
        >
          {section === 'welcome' && (
            <div>
              <div style={{ fontSize: 'clamp(0.9rem, 2.5vw, 1.1rem)', lineHeight: '1.8', marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1rem', color: theme.text, textShadow: `0 0 10px ${theme.text}44` }}>
                  <span style={{ color: theme.accent, fontWeight: 'bold' }}>&gt;</span> Open Source AI-Powered Development Platform
                </p>
                <p style={{ marginBottom: '1rem', color: theme.dim }}>
                  Transform ideas into production-ready applications using natural language.
                  <br />
                  Self-hosted. No vendor lock-in. Complete control.
                </p>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                <button
                  onClick={() => handleNext('mission')}
                  style={{
                    background: theme.accent,
                    color: theme.bg,
                    border: 'none',
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    fontWeight: 'bold',
                    boxShadow: `0 0 20px ${theme.accent}88`,
                    transition: 'all 0.3s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.boxShadow = `0 5px 30px ${theme.accent}`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.boxShadow = `0 0 20px ${theme.accent}88`;
                  }}
                >
                  [ LEARN MORE ]
                </button>
                <button
                  onClick={() => handleNext('prompt')}
                  style={{
                    background: 'transparent',
                    color: theme.accent,
                    border: `2px solid ${theme.accent}`,
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    fontWeight: 'bold',
                    boxShadow: `0 0 15px ${theme.accent}44`,
                    transition: 'all 0.3s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = theme.accent;
                    e.currentTarget.style.color = theme.bg;
                    e.currentTarget.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = theme.accent;
                    e.currentTarget.style.transform = 'translateY(0)';
                  }}
                >
                  [ GET STARTED ]
                </button>
              </div>
            </div>
          )}

          {section === 'mission' && (
            <div>
              <div style={{ fontSize: 'clamp(0.85rem, 2vw, 1rem)', lineHeight: '1.8', marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1.5rem', color: theme.text }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>OUTPUT:</span>
                </p>
                <div
                  style={{
                    paddingLeft: '1rem',
                    borderLeft: `3px solid ${theme.accent}`,
                    marginBottom: '1.5rem',
                    boxShadow: `-5px 0 15px ${theme.accent}22`,
                  }}
                >
                  <p style={{ marginBottom: '1rem', color: theme.text }}>
                    Tesslate Studio is built on a simple belief:{' '}
                    <span style={{ color: theme.accent, fontWeight: 'bold', textShadow: `0 0 10px ${theme.accent}` }}>
                      developers should own their tools
                    </span>
                    .
                  </p>
                  <p style={{ marginBottom: '1rem', color: theme.dim }}>
                    While commercial platforms lock you into subscriptions and proprietary systems, Tesslate Studio gives you a
                    complete, open-source AI development environment that you can host anywhere, customize freely, and use without
                    limits.
                  </p>
                  <p style={{ color: theme.text }}>
                    From local Docker containers to production Kubernetes clusters, Tesslate Studio scales with your needs while
                    keeping you in control.
                  </p>
                </div>
              </div>
              <button
                onClick={() => handleNext('features')}
                style={{
                  background: theme.accent,
                  color: theme.bg,
                  border: 'none',
                  padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                  cursor: 'pointer',
                  fontFamily: "'Courier New', Courier, monospace",
                  fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                  fontWeight: 'bold',
                  boxShadow: `0 0 20px ${theme.accent}88`,
                }}
              >
                [ CONTINUE ]
              </button>
            </div>
          )}

          {section === 'features' && (
            <div>
              <div style={{ marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1.5rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>OUTPUT:</span> Core Features
                </p>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 250px), 1fr))',
                    gap: '1rem',
                  }}
                >
                  {FEATURES.map((feature, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: `linear-gradient(135deg, ${theme.bg} 0%, ${theme.accent}11 100%)`,
                        border: `1px solid ${theme.accent}`,
                        padding: '1.25rem',
                        borderRadius: '8px',
                        boxShadow: `0 0 20px ${theme.accent}22`,
                        transition: 'all 0.3s',
                        cursor: 'pointer',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'translateY(-5px)';
                        e.currentTarget.style.boxShadow = `0 5px 30px ${theme.accent}44`;
                        e.currentTarget.style.borderColor = theme.text;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'translateY(0)';
                        e.currentTarget.style.boxShadow = `0 0 20px ${theme.accent}22`;
                        e.currentTarget.style.borderColor = theme.accent;
                      }}
                    >
                      <div style={{ fontSize: 'clamp(2rem, 5vw, 2.5rem)', marginBottom: '0.5rem' }}>{feature.icon}</div>
                      <div
                        style={{
                          fontSize: 'clamp(0.9rem, 2vw, 1rem)',
                          fontWeight: 'bold',
                          marginBottom: '0.5rem',
                          color: theme.accent,
                          textShadow: `0 0 10px ${theme.accent}66`,
                        }}
                      >
                        {feature.title}
                      </div>
                      <div style={{ fontSize: 'clamp(0.8rem, 1.8vw, 0.9rem)', color: theme.dim, marginBottom: '0.75rem' }}>
                        {feature.desc}
                      </div>
                      <div
                        style={{
                          fontSize: 'clamp(0.7rem, 1.5vw, 0.75rem)',
                          color: theme.dim,
                          fontFamily: "'Courier New', Courier, monospace",
                          opacity: 0.6,
                        }}
                      >
                        $ {feature.command}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <button
                onClick={() => handleNext('architecture')}
                style={{
                  background: theme.accent,
                  color: theme.bg,
                  border: 'none',
                  padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                  cursor: 'pointer',
                  fontFamily: "'Courier New', Courier, monospace",
                  fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                  fontWeight: 'bold',
                  boxShadow: `0 0 20px ${theme.accent}88`,
                }}
              >
                [ CONTINUE ]
              </button>
            </div>
          )}

          {section === 'architecture' && (
            <div>
              <div style={{ marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1.5rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>OUTPUT:</span> Production-Ready
                  Architecture
                </p>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))',
                    gap: '1rem',
                    marginBottom: '1.5rem',
                  }}
                >
                  {ARCHITECTURE_POINTS.map((point, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: `linear-gradient(135deg, ${theme.bg} 0%, ${theme.accent}11 100%)`,
                        border: `1px solid ${theme.accent}`,
                        padding: '1.25rem',
                        borderRadius: '8px',
                        boxShadow: `0 0 20px ${theme.accent}22`,
                        position: 'relative',
                        overflow: 'hidden',
                      }}
                    >
                      {/* Status indicator */}
                      <div
                        style={{
                          position: 'absolute',
                          top: '0.5rem',
                          right: '0.5rem',
                          fontSize: 'clamp(0.6rem, 1.5vw, 0.7rem)',
                          color: theme.accent,
                          textShadow: `0 0 10px ${theme.accent}`,
                          animation: 'pulse 2s ease-in-out infinite',
                        }}
                      >
                        {point.status}
                      </div>
                      <div style={{ fontSize: 'clamp(2rem, 5vw, 2.5rem)', marginBottom: '0.5rem' }}>{point.icon}</div>
                      <div
                        style={{
                          fontSize: 'clamp(0.9rem, 2vw, 1rem)',
                          fontWeight: 'bold',
                          marginBottom: '0.5rem',
                          color: theme.accent,
                          textShadow: `0 0 10px ${theme.accent}66`,
                        }}
                      >
                        {point.title}
                      </div>
                      <div style={{ fontSize: 'clamp(0.8rem, 1.8vw, 0.9rem)', color: theme.dim }}>{point.desc}</div>
                    </div>
                  ))}
                </div>
                <div
                  style={{
                    paddingLeft: '1rem',
                    borderLeft: `3px solid ${theme.accent}`,
                    boxShadow: `-5px 0 15px ${theme.accent}22`,
                  }}
                >
                  <p style={{ color: theme.dim, fontSize: 'clamp(0.85rem, 2vw, 0.95rem)' }}>
                    Every project runs in an isolated environment with its own dependencies. Deploy locally with Docker or scale to
                    production with Kubernetes. Built-in Traefik routing for development, NGINX Ingress for production.
                  </p>
                </div>
              </div>
              <button
                onClick={() => handleNext('opensource')}
                style={{
                  background: theme.accent,
                  color: theme.bg,
                  border: 'none',
                  padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                  cursor: 'pointer',
                  fontFamily: "'Courier New', Courier, monospace",
                  fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                  fontWeight: 'bold',
                  boxShadow: `0 0 20px ${theme.accent}88`,
                }}
              >
                [ CONTINUE ]
              </button>
            </div>
          )}

          {section === 'opensource' && (
            <div>
              <div style={{ marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1.5rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>OUTPUT:</span> Why Open Source
                  Matters
                </p>
                <div
                  style={{
                    paddingLeft: '1rem',
                    borderLeft: `3px solid ${theme.accent}`,
                    marginBottom: '1.5rem',
                    boxShadow: `-5px 0 15px ${theme.accent}22`,
                  }}
                >
                  {OPENSOURCE_BENEFITS.map((benefit, idx) => (
                    <p
                      key={idx}
                      style={{
                        marginBottom: '0.8rem',
                        color: theme.text,
                        fontSize: 'clamp(0.85rem, 2vw, 1rem)',
                        textShadow: `0 0 5px ${theme.text}33`,
                      }}
                    >
                      {benefit}
                    </p>
                  ))}
                </div>
                <div
                  style={{
                    background: `linear-gradient(135deg, ${theme.bg} 0%, ${theme.accent}22 100%)`,
                    border: `2px solid ${theme.accent}`,
                    padding: '1.25rem',
                    borderRadius: '8px',
                    marginTop: '1.5rem',
                    boxShadow: `0 0 30px ${theme.accent}33`,
                  }}
                >
                  <p style={{ color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)', marginBottom: '0.5rem' }}>
                    <span style={{ color: theme.accent, fontWeight: 'bold', textShadow: `0 0 10px ${theme.accent}` }}>
                      The Bottom Line:
                    </span>
                  </p>
                  <p style={{ color: theme.dim, fontSize: 'clamp(0.85rem, 2vw, 0.95rem)' }}>
                    Tesslate Studio gives you complete ownership of your development environment. Perfect for startups, enterprises,
                    and developers who value freedom and control.
                  </p>
                </div>

                {/* External Links Section */}
                <div style={{ marginTop: '2rem' }}>
                  <p style={{ marginBottom: '1rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                    <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>RESOURCES:</span>
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))', gap: '1rem' }}>
                    {[
                      { label: '📚 Documentation', url: 'https://docs.tesslate.com', desc: 'Learn & Build' },
                      { label: '🌐 Website', url: 'https://tesslate.com', desc: 'Explore More' },
                      { label: '💻 GitHub', url: 'https://github.com/TesslateAI', desc: 'Star & Contribute' },
                      { label: '🤗 HuggingFace', url: 'https://huggingface.co/Tesslate', desc: 'Models & Datasets' },
                    ].map((link, idx) => (
                      <a
                        key={idx}
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'block',
                          textDecoration: 'none',
                          background: `linear-gradient(135deg, ${theme.bg} 0%, ${theme.accent}11 100%)`,
                          border: `1px solid ${theme.accent}`,
                          padding: '0.75rem',
                          borderRadius: '8px',
                          boxShadow: `0 0 15px ${theme.accent}22`,
                          transition: 'all 0.3s',
                          cursor: 'pointer',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.transform = 'translateY(-3px)';
                          e.currentTarget.style.boxShadow = `0 5px 25px ${theme.accent}44`;
                          e.currentTarget.style.borderColor = theme.text;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.transform = 'translateY(0)';
                          e.currentTarget.style.boxShadow = `0 0 15px ${theme.accent}22`;
                          e.currentTarget.style.borderColor = theme.accent;
                        }}
                      >
                        <div style={{ fontSize: 'clamp(0.85rem, 2vw, 0.95rem)', color: theme.text, fontWeight: 'bold', marginBottom: '0.25rem', textShadow: `0 0 8px ${theme.text}44` }}>
                          {link.label}
                        </div>
                        <div style={{ fontSize: 'clamp(0.7rem, 1.8vw, 0.8rem)', color: theme.dim }}>
                          {link.desc}
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '2rem' }}>
                <button
                  onClick={() => handleNext('prompt')}
                  style={{
                    background: theme.accent,
                    color: theme.bg,
                    border: 'none',
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    fontWeight: 'bold',
                    boxShadow: `0 0 20px ${theme.accent}88`,
                  }}
                >
                  [ GET STARTED ]
                </button>
                <button
                  onClick={() => handleNext('theme')}
                  style={{
                    background: 'transparent',
                    color: theme.accent,
                    border: `2px solid ${theme.accent}`,
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    fontWeight: 'bold',
                    boxShadow: `0 0 15px ${theme.accent}44`,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = theme.accent;
                    e.currentTarget.style.color = theme.bg;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = theme.accent;
                  }}
                >
                  [ CUSTOMIZE THEME ]
                </button>
              </div>
            </div>
          )}

          {section === 'theme' && (
            <div>
              <div style={{ marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1.5rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>OUTPUT:</span> Available Themes
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 150px), 1fr))', gap: '1rem' }}>
                  {COLOR_THEMES.map((t, idx) => (
                    <button
                      key={t.name}
                      onClick={() => {
                        setSelectedTheme(t);
                        sessionStorage.setItem('terminal_theme', t.name);
                      }}
                      style={{
                        background: `linear-gradient(135deg, ${t.bg} 0%, ${t.accent}22 100%)`,
                        color: t.text,
                        border: `3px solid ${selectedTheme.name === t.name ? t.accent : t.dim}`,
                        padding: '1rem 0.75rem',
                        cursor: 'pointer',
                        fontFamily: "'Courier New', Courier, monospace",
                        transition: 'all 0.3s',
                        textAlign: 'left',
                        position: 'relative',
                        borderRadius: '8px',
                        boxShadow:
                          selectedTheme.name === t.name
                            ? `0 0 30px ${t.accent}88, inset 0 0 20px ${t.accent}33`
                            : `0 0 15px ${t.accent}22`,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = t.accent;
                        e.currentTarget.style.transform = 'scale(1.05) translateY(-5px)';
                        e.currentTarget.style.boxShadow = `0 5px 40px ${t.accent}66`;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = selectedTheme.name === t.name ? t.accent : t.dim;
                        e.currentTarget.style.transform = 'scale(1) translateY(0)';
                        e.currentTarget.style.boxShadow =
                          selectedTheme.name === t.name
                            ? `0 0 30px ${t.accent}88, inset 0 0 20px ${t.accent}33`
                            : `0 0 15px ${t.accent}22`;
                      }}
                    >
                      {selectedTheme.name === t.name && (
                        <div
                          style={{
                            position: 'absolute',
                            top: '0.5rem',
                            right: '0.5rem',
                            color: t.accent,
                            fontSize: 'clamp(1.2rem, 3vw, 1.5rem)',
                            textShadow: `0 0 10px ${t.accent}`,
                          }}
                        >
                          ✓
                        </div>
                      )}
                      <div style={{ fontSize: 'clamp(0.85rem, 2vw, 0.95rem)', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                        [{idx + 1}] {t.name}
                      </div>
                      <div style={{ fontSize: 'clamp(0.7rem, 1.8vw, 0.75rem)', opacity: 0.7 }}>██ {t.accent}</div>
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={() => handleNext('prompt')}
                style={{
                  background: theme.accent,
                  color: theme.bg,
                  border: 'none',
                  padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                  cursor: 'pointer',
                  fontFamily: "'Courier New', Courier, monospace",
                  fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                  fontWeight: 'bold',
                  boxShadow: `0 0 20px ${theme.accent}88`,
                }}
              >
                [ CONTINUE ]
              </button>
            </div>
          )}

          {section === 'prompt' && (
            <div>
              <div style={{ marginBottom: '2rem' }}>
                <p style={{ marginBottom: '1rem', color: theme.text, fontSize: 'clamp(0.9rem, 2vw, 1rem)' }}>
                  <span style={{ color: theme.accent, textShadow: `0 0 10px ${theme.accent}` }}>INPUT REQUIRED:</span>
                </p>
                <p style={{ marginBottom: '1.5rem', color: theme.dim, fontSize: 'clamp(0.85rem, 2vw, 0.95rem)' }}>
                  Tell us what you want to build. Your prompt will be ready in your first project's chat interface.
                </p>
                <textarea
                  ref={inputRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Example: A real-time chat app with user authentication and message history..."
                  style={{
                    width: '100%',
                    minHeight: '120px',
                    background: 'rgba(0,0,0,0.5)',
                    color: theme.text,
                    border: `2px solid ${theme.accent}`,
                    padding: '1rem',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.85rem, 2vw, 1rem)',
                    outline: 'none',
                    resize: 'vertical',
                    borderRadius: '8px',
                    boxShadow: `0 0 20px ${theme.accent}33, inset 0 0 20px ${theme.accent}11`,
                    textShadow: `0 0 5px ${theme.text}66`,
                  }}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.ctrlKey) {
                      handlePromptSubmit();
                    }
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.boxShadow = `0 0 30px ${theme.accent}66, inset 0 0 30px ${theme.accent}22`;
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.boxShadow = `0 0 20px ${theme.accent}33, inset 0 0 20px ${theme.accent}11`;
                  }}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  onClick={handlePromptSubmit}
                  style={{
                    background: theme.accent,
                    color: theme.bg,
                    border: 'none',
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    fontWeight: 'bold',
                    boxShadow: `0 0 30px ${theme.accent}`,
                    transition: 'all 0.3s',
                  }}
                  disabled={!prompt.trim()}
                  onMouseEnter={(e) => {
                    if (prompt.trim()) {
                      e.currentTarget.style.transform = 'scale(1.05)';
                      e.currentTarget.style.boxShadow = `0 5px 40px ${theme.accent}`;
                    }
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'scale(1)';
                    e.currentTarget.style.boxShadow = `0 0 30px ${theme.accent}`;
                  }}
                >
                  [ START BUILDING ]
                </button>
                <button
                  onClick={() => handleNext('theme')}
                  style={{
                    background: 'transparent',
                    color: theme.accent,
                    border: `1px solid ${theme.accent}`,
                    padding: 'clamp(0.6rem, 2vw, 0.75rem) clamp(1.5rem, 4vw, 2rem)',
                    cursor: 'pointer',
                    fontFamily: "'Courier New', Courier, monospace",
                    fontSize: 'clamp(0.8rem, 2vw, 1rem)',
                    boxShadow: `0 0 15px ${theme.accent}44`,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = theme.accent;
                    e.currentTarget.style.color = theme.bg;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = theme.accent;
                  }}
                >
                  [ CHANGE THEME ]
                </button>
              </div>
              <div style={{ marginTop: '1rem', fontSize: 'clamp(0.75rem, 1.8vw, 0.85rem)', color: theme.dim }}>
                Your prompt will appear in your project's AI chat when you're ready to build.
              </div>
            </div>
          )}

          {section === 'done' && (
            <div>
              <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
                <div style={{ fontSize: 'clamp(2rem, 5vw, 3rem)', marginBottom: '1rem', animation: 'pulse 1s ease-in-out infinite' }}>⚡</div>
                <p style={{ color: theme.text, fontSize: 'clamp(1rem, 3vw, 1.2rem)', textShadow: `0 0 10px ${theme.text}` }}>
                  System ready. Redirecting...
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* CSS Animations */}
      <style>{`
        @keyframes blink {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(1.02); }
        }
        @keyframes scanline {
          0% { transform: translateY(0); }
          100% { transform: translateY(100%); }
        }

        /* Smooth scrolling */
        html {
          scroll-behavior: smooth;
        }

        /* Custom scrollbar */
        ::-webkit-scrollbar {
          width: 10px;
        }
        ::-webkit-scrollbar-track {
          background: ${theme.bg};
        }
        ::-webkit-scrollbar-thumb {
          background: ${theme.accent};
          border-radius: 5px;
        }
        ::-webkit-scrollbar-thumb:hover {
          background: ${theme.text};
        }

        /* Mobile viewport fix */
        @media (max-width: 768px) {
          body {
            overflow-x: hidden;
          }
        }
      `}</style>
    </div>
  );
}
