import { useNavigate } from 'react-router-dom';

/**
 * Public Marketplace Footer
 * Clean, minimal, dark — matches Tesslate's design system.
 * SEO-friendly with proper navigation links.
 */
export function PublicMarketplaceFooter() {
  const navigate = useNavigate();

  const columns = [
    {
      title: 'Marketplace',
      links: [
        { label: 'AI Agents', href: '/marketplace/browse/agent' },
        { label: 'Project Templates', href: '/marketplace/browse/base' },
        { label: 'Skills', href: '/marketplace/browse/skill' },
        { label: 'MCP Servers', href: '/marketplace/browse/mcp_server' },
      ],
    },
    {
      title: 'Categories',
      links: [
        { label: 'Builder', href: '/marketplace/browse/agent?category=builder' },
        { label: 'Frontend', href: '/marketplace/browse/agent?category=frontend' },
        { label: 'Fullstack', href: '/marketplace/browse/agent?category=fullstack' },
        { label: 'Backend', href: '/marketplace/browse/agent?category=backend' },
        { label: 'Data & ML', href: '/marketplace/browse/agent?category=data' },
        { label: 'DevOps', href: '/marketplace/browse/agent?category=devops' },
      ],
    },
    {
      title: 'Company',
      links: [
        { label: 'About', href: '/' },
        { label: 'Documentation', href: 'https://docs.tesslate.com', external: true },
        { label: 'Sign Up', href: '/register' },
        { label: 'Sign In', href: '/login' },
      ],
    },
  ];

  return (
    <footer className="border-t border-[var(--border)] mt-16">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {columns.map((col) => (
            <div key={col.title}>
              <h3 className="text-[11px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-4">
                {col.title}
              </h3>
              <ul className="space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {link.external ? (
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <a
                        href={link.href}
                        className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                      >
                        {link.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {/* Get Started */}
          <div>
            <h3 className="text-[11px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-4">
              Get Started
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              Build faster with AI-powered coding agents and pre-built templates.
            </p>
            <button
              onClick={() => navigate('/register')}
              className="btn btn-filled"
            >
              Start Building Free
            </button>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-12 pt-6 border-t border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <svg className="w-4 h-4 text-[var(--text-subtle)]" viewBox="0 0 161.9 126.66">
              <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor" />
              <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor" />
              <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor" />
            </svg>
            <span className="text-[11px] text-[var(--text-subtle)]">
              &copy; {new Date().getFullYear()} Tesslate
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}

export default PublicMarketplaceFooter;
