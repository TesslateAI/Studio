import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Lightning, GitFork } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';

export interface MarketplaceItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  category: string;
  item_type: 'agent' | 'base' | 'tool' | 'integration';
  mode?: string;
  agent_type?: string;
  model?: string;
  source_type: 'open' | 'closed';
  is_forkable: boolean;
  is_active: boolean;
  icon: string;
  avatar_url?: string | null;
  preview_image?: string | null;
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  reviews_count: number;
  usage_count: number;
  features: string[];
  tags: string[];
  tools?: string[] | null;
  is_featured: boolean;
  is_purchased: boolean;
  creator_type?: 'official' | 'community';
  creator_name?: string;
  creator_avatar_url?: string | null;
  created_by_user_id?: string;
  forked_by_user_id?: string;
}

interface AgentCardProps {
  item: MarketplaceItem;
  onInstall: (item: MarketplaceItem) => void;
}

// Format install/download counts like Raycast (1.2k, 1.2M)
// eslint-disable-next-line react-refresh/only-export-components
export function formatInstalls(count: number): string {
  if (count >= 1000000) {
    return `${(count / 1000000).toFixed(1)}M`;
  }
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return count.toString();
}

export function AgentCard({ item, onInstall }: AgentCardProps) {
  const navigate = useNavigate();
  const { theme } = useTheme();

  const handleClick = () => {
    navigate(`/marketplace/${item.slug}`);
  };

  const handleInstall = (e: React.MouseEvent) => {
    e.stopPropagation();
    onInstall(item);
  };

  const creatorId = item.forked_by_user_id || item.created_by_user_id;

  const handleCreatorClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (creatorId) {
      navigate(`/marketplace/creator/${creatorId}`);
    }
  };

  const usageCount = item.usage_count || 0;

  return (
    <div
      onClick={handleClick}
      className={`
        group relative flex flex-col p-4 rounded-xl border cursor-pointer
        transition-all duration-200 ease-out
        hover:-translate-y-1 hover:shadow-xl
        ${theme === 'light'
          ? 'bg-white border-black/10 hover:border-[var(--primary)]/40'
          : 'bg-[#1a1a1c] border-white/10 hover:border-[var(--primary)]/40'
        }
        ${!item.is_active ? 'opacity-60' : ''}
      `}
    >
      {/* Icon */}
      <div className="mb-3">
        <div className={`
          w-12 h-12 rounded-xl flex items-center justify-center overflow-hidden
          ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
        `}>
          {item.avatar_url ? (
            <img
              src={item.avatar_url}
              alt={item.name}
              className="w-full h-full object-cover"
            />
          ) : (
            <img
              src="/favicon.svg"
              alt="Tesslate"
              className="w-8 h-8"
            />
          )}
        </div>
      </div>

      {/* Title & Badge Row */}
      <div className="flex items-start justify-between gap-2 mb-1">
        <h3 className={`
          font-heading font-semibold text-sm sm:text-base leading-tight
          group-hover:text-[var(--primary)] transition-colors
          ${theme === 'light' ? 'text-black' : 'text-white'}
        `}>
          {item.name}
        </h3>
        {item.source_type === 'open' && (
          <span className="flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 bg-green-500/15 text-green-500 text-[10px] rounded font-medium">
            <GitFork size={10} weight="bold" />
            Open
          </span>
        )}
      </div>

      {/* Description */}
      <p className={`
        text-xs sm:text-sm leading-relaxed line-clamp-2 mb-3 min-h-[32px] sm:min-h-[40px]
        ${theme === 'light' ? 'text-black/60' : 'text-white/60'}
      `}>
        {item.description}
      </p>

      {/* Footer */}
      <div className="mt-auto pt-3 border-t border-white/5">
        <div className="flex items-center justify-between">
          {/* Author & Stats */}
          <div className="flex items-center gap-3">
            {/* Creator Avatar */}
            <button
              onClick={handleCreatorClick}
              className={`
                flex items-center gap-1.5 text-xs hover:text-[var(--primary)] transition-colors
                ${theme === 'light' ? 'text-black/50' : 'text-white/50'}
              `}
            >
              <div className={`
                w-5 h-5 rounded-full overflow-hidden flex-shrink-0
                ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'}
              `}>
                {item.creator_avatar_url ? (
                  <img
                    src={item.creator_avatar_url}
                    alt={item.creator_name || 'Creator'}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-[10px] font-medium">
                    {item.creator_name?.charAt(0).toUpperCase() || 'T'}
                  </div>
                )}
              </div>
              <span className="truncate max-w-[60px] sm:max-w-[100px]">
                {item.creator_type === 'official' ? 'Tesslate' : item.creator_name || 'Unknown'}
              </span>
            </button>

            {/* Uses Count */}
            <div className={`
              flex items-center gap-1 text-xs
              ${theme === 'light' ? 'text-black/40' : 'text-white/40'}
            `}>
              <Lightning size={12} weight="fill" />
              <span>{formatInstalls(usageCount)} uses</span>
            </div>
          </div>

          {/* Install Button */}
          {item.is_purchased ? (
            <span className="flex items-center gap-1 px-2.5 py-1 bg-green-500/15 text-green-500 rounded-lg text-xs font-medium">
              <Check size={12} weight="bold" />
              Installed
            </span>
          ) : (
            <button
              onClick={handleInstall}
              disabled={!item.is_active}
              className={`
                px-3 py-1.5 rounded-lg text-xs font-semibold transition-all
                ${item.is_active
                  ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-sm hover:shadow-md'
                  : theme === 'light'
                    ? 'bg-black/5 text-black/40 cursor-not-allowed'
                    : 'bg-white/5 text-white/40 cursor-not-allowed'
                }
              `}
            >
              {item.is_active
                ? (item.pricing_type === 'free' ? 'Install' : `$${item.price}/mo`)
                : 'Soon'
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentCard;
