import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumbs({ items, className = '' }: BreadcrumbsProps) {
  return (
    <nav className={`flex items-center gap-2 text-sm ${className}`}>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;

        return (
          <div key={index} className="flex items-center gap-2">
            {item.href && !isLast ? (
              <Link
                to={item.href}
                className="text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
              >
                {item.label}
              </Link>
            ) : (
              <span className={isLast ? 'text-[var(--text)] font-medium' : 'text-[var(--text)]/60'}>
                {item.label}
              </span>
            )}

            {!isLast && (
              <ChevronRight size={14} className="text-[var(--text)]/40" />
            )}
          </div>
        );
      })}
    </nav>
  );
}
