import { type ReactNode } from 'react';

interface MarketplaceCardProps {
  title: string;
  description: string;
  icon: ReactNode;
  badge?: 'Free' | 'PRO';
  installed?: boolean;
  onClick?: () => void;
}

export function MarketplaceCard({
  title,
  description,
  icon,
  badge,
  installed = false,
  onClick
}: MarketplaceCardProps) {
  return (
    <div
      className="
        marketplace-item-mini
        bg-[var(--surface)] rounded-xl
        border border-white/8
        p-3
        flex items-center gap-3
        transition-all duration-300
        cursor-pointer
        hover:transform hover:-translate-y-0.5
        hover:border-[rgba(255,107,0,0.3)]
        hover:shadow-[0_4px_16px_rgba(0,0,0,0.2)]
      "
      onClick={onClick}
    >
      {/* Icon */}
      <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0">
        {icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <h4 className="text-sm font-semibold text-white truncate">
          {title}
        </h4>
        <p className="text-xs text-gray-500 truncate">
          {description}
        </p>
      </div>

      {/* Badge */}
      {badge && (
        <span
          className={`
            marketplace-badge flex-shrink-0
            inline-flex items-center gap-1
            px-2.5 py-1 rounded-xl
            text-[11px] font-semibold
            ${badge === 'Free'
              ? 'bg-[rgba(0,217,255,0.1)] text-[var(--accent)] border border-[rgba(0,217,255,0.2)]'
              : 'bg-[rgba(255,107,0,0.2)] text-orange-400 border border-[rgba(255,107,0,0.3)]'
            }
          `}
        >
          {badge === 'PRO' && (
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
              <path d="M247.31,124.76c-.35-.79-8.82-19.58-27.65-38.41C194.57,61.26,162.88,48,128,48S61.43,61.26,36.34,86.35C17.51,105.18,9,124,8.69,124.76a8,8,0,0,0,0,6.5c.35.79,8.82,19.57,27.65,38.4C61.43,194.74,93.12,208,128,208s66.57-13.26,91.66-38.34c18.83-18.83,27.3-37.61,27.65-38.4A8,8,0,0,0,247.31,124.76ZM128,192c-30.78,0-57.67-11.19-79.93-33.25A133.47,133.47,0,0,1,25,128,133.33,133.33,0,0,1,48.07,97.25C70.33,75.19,97.22,64,128,64s57.67,11.19,79.93,33.25A133.46,133.46,0,0,1,231.05,128C223.84,141.46,192.43,192,128,192Zm0-112a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160Z" />
            </svg>
          )}
          <span>{badge}</span>
        </span>
      )}

      {installed && (
        <span className="flex-shrink-0 text-xs px-2 py-1 bg-green-500/20 text-green-400 rounded-full font-semibold">
          Installed
        </span>
      )}
    </div>
  );
}
