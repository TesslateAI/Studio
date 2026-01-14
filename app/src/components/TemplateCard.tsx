import { Plus, Check } from '@phosphor-icons/react';

interface MarketplaceBase {
  id: string;
  name: string;
  slug: string;
  description?: string;
  icon_url?: string;
  default_port?: number;
}

interface TemplateCardProps {
  base: MarketplaceBase;
  selected: boolean;
  onClick: () => void;
  inLibrary?: boolean;
}

// Map base slugs to framework icons/colors
const getFrameworkStyle = (slug: string) => {
  const styles: Record<string, { bg: string; text: string; icon: string }> = {
    'nextjs': { bg: 'bg-black', text: 'text-white', icon: '▲' },
    'vite': { bg: 'bg-purple-500/20', text: 'text-purple-400', icon: '⚡' },
    'react': { bg: 'bg-cyan-500/20', text: 'text-cyan-400', icon: '⚛' },
    'fastapi': { bg: 'bg-emerald-500/20', text: 'text-emerald-400', icon: '🚀' },
    'express': { bg: 'bg-gray-500/20', text: 'text-gray-300', icon: 'E' },
    'django': { bg: 'bg-green-600/20', text: 'text-green-400', icon: '🐍' },
    'flask': { bg: 'bg-gray-600/20', text: 'text-gray-300', icon: '🧪' },
  };
  return styles[slug.toLowerCase()] || { bg: 'bg-[var(--primary)]/20', text: 'text-[var(--primary)]', icon: '📦' };
};

export function TemplateCard({
  base,
  selected,
  onClick,
  inLibrary = false,
}: TemplateCardProps) {
  const style = getFrameworkStyle(base.slug);

  return (
    <button
      onClick={onClick}
      className={`
        relative flex-shrink-0 w-32 h-36 rounded-xl p-3
        flex flex-col items-center justify-center gap-2
        transition-all duration-200
        ${selected
          ? 'bg-[var(--primary)]/20 border-2 border-[var(--primary)] shadow-lg shadow-[var(--primary)]/20'
          : inLibrary
            ? 'bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20'
            : 'bg-white/[0.02] border border-dashed border-white/20 hover:bg-white/5 hover:border-white/30'
        }
      `}
    >
      {/* Framework Icon */}
      <div className={`w-12 h-12 ${style.bg} rounded-xl flex items-center justify-center ${!inLibrary && !selected ? 'opacity-70' : ''}`}>
        {base.icon_url ? (
          <img src={base.icon_url} alt={base.name} className="w-8 h-8 object-contain" />
        ) : (
          <span className={`text-2xl ${style.text}`}>{style.icon}</span>
        )}
      </div>

      {/* Name */}
      <span className={`text-sm font-medium text-center line-clamp-1 ${!inLibrary && !selected ? 'text-white/60' : 'text-[var(--text)]'}`}>
        {base.name}
      </span>

      {/* Top-right indicator */}
      {inLibrary ? (
        // In library - show checkmark
        <div className="absolute top-2 right-2 w-5 h-5 bg-emerald-500/20 rounded-full flex items-center justify-center">
          <Check size={12} className="text-emerald-400" weight="bold" />
        </div>
      ) : (
        // Not in library - show "+" to indicate clicking will add it
        <div className="absolute top-2 right-2 w-5 h-5 bg-white/10 rounded-full flex items-center justify-center">
          <Plus size={12} className="text-white/50" weight="bold" />
        </div>
      )}

      {/* Selected checkmark (bottom-right) */}
      {selected && (
        <div className="absolute bottom-2 right-2 w-5 h-5 bg-[var(--primary)] rounded-full flex items-center justify-center">
          <Check size={12} className="text-white" weight="bold" />
        </div>
      )}
    </button>
  );
}

// "Add More" card for navigating to marketplace
export function AddMoreCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="
        flex-shrink-0 w-32 h-36 rounded-xl p-3
        flex flex-col items-center justify-center gap-2
        bg-white/5 border border-dashed border-white/20
        hover:bg-white/10 hover:border-white/30
        transition-all duration-200
      "
    >
      <div className="w-12 h-12 bg-white/10 rounded-xl flex items-center justify-center">
        <Plus size={24} className="text-white/50" />
      </div>
      <span className="text-sm font-medium text-white/50 text-center">
        Browse more
      </span>
    </button>
  );
}
