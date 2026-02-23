import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Lightning, GitFork, Star, GithubLogo, ShieldCheck, Users } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { type MarketplaceItem, formatInstalls, parseGitHubRepo } from './AgentCard';

interface FeaturedCardProps {
  item: MarketplaceItem;
  onInstall: (item: MarketplaceItem) => void;
  /** If false, shows "Sign Up" CTA instead of install button */
  isAuthenticated?: boolean;
}

export function FeaturedCard({ item, onInstall, isAuthenticated = true }: FeaturedCardProps) {
  const navigate = useNavigate();
  const { theme } = useTheme();

  const handleClick = () => {
    navigate(`/marketplace/${item.slug}`);
  };

  const handleInstall = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isAuthenticated) {
      // Redirect to register with return URL
      navigate(`/register?redirect=${encodeURIComponent(`/marketplace/${item.slug}`)}`);
      return;
    }
    onInstall(item);
  };

  const creatorId = item.forked_by_user_id || item.created_by_user_id;

  const handleCreatorClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (item.creator_username) {
      navigate(`/@${item.creator_username}`);
    } else if (creatorId) {
      navigate(`/marketplace/creator/${creatorId}`);
    }
  };

  const usageCount = item.usage_count || 0;

  return (
    <div
      onClick={handleClick}
      className={`
        group relative flex flex-col md:flex-row gap-4 md:gap-6 p-4 md:p-6 rounded-2xl border cursor-pointer
        transition-all duration-200 ease-out
        hover:-translate-y-0.5 hover:shadow-xl
        ${
          theme === 'light'
            ? 'bg-white border-black/10 hover:border-[var(--primary)]/40'
            : 'bg-[#1a1a1c] border-white/10 hover:border-[var(--primary)]/40'
        }
        ${!item.is_active ? 'opacity-60' : ''}
      `}
    >
      {/* Featured Badge */}
      <div className="absolute top-3 right-3 sm:top-4 sm:right-4 flex items-center gap-1 px-2 py-1 bg-[var(--primary)]/20 text-[var(--primary)] text-[10px] sm:text-xs rounded-full font-medium z-10">
        <Star size={12} weight="fill" />
        Featured
      </div>

      {/* Large Icon */}
      <div className="flex-shrink-0">
        <div
          className={`
          w-20 h-20 md:w-24 md:h-24 rounded-2xl flex items-center justify-center overflow-hidden
          ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
        `}
        >
          {item.avatar_url ? (
            <img src={item.avatar_url} alt={item.name} className="w-full h-full object-cover" />
          ) : (
            <img src="/favicon.svg" alt="Tesslate" className="w-12 h-12 md:w-16 md:h-16" />
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Title + Creator */}
        <div className="mb-2 pr-16 sm:pr-20">
          <h3
            className={`
            font-heading font-bold text-base sm:text-lg leading-tight line-clamp-2 min-w-0
            group-hover:text-[var(--primary)] transition-colors
            ${theme === 'light' ? 'text-black' : 'text-white'}
          `}
          >
            {item.name}
          </h3>
          <button
            onClick={handleCreatorClick}
            className={`
              flex items-center gap-1.5 text-xs sm:text-sm hover:text-[var(--primary)] transition-colors mt-1
              ${theme === 'light' ? 'text-black/50' : 'text-white/50'}
            `}
          >
            <div
              className={`
              w-4 h-4 sm:w-5 sm:h-5 rounded-full overflow-hidden flex-shrink-0
              ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'}
            `}
            >
              {item.creator_avatar_url ? (
                <img
                  src={item.creator_avatar_url}
                  alt={item.creator_name || 'Creator'}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-[9px] sm:text-[10px] font-medium">
                  {item.creator_name?.charAt(0).toUpperCase() || 'T'}
                </div>
              )}
            </div>
            <span>
              {item.creator_type === 'official'
                ? 'Tesslate'
                : item.creator_username
                  ? `@${item.creator_username}`
                  : item.creator_name || 'Unknown'}
            </span>
          </button>
        </div>

        {/* Description */}
        <p
          className={`
          text-xs sm:text-sm leading-relaxed line-clamp-2 mb-3
          ${theme === 'light' ? 'text-black/60' : 'text-white/60'}
        `}
        >
          {item.description}
        </p>

        {/* GitHub Source Badge */}
        {item.git_repo_url && (() => {
          const gh = parseGitHubRepo(item.git_repo_url);
          if (!gh) return null;
          return (
            <a
              href={item.git_repo_url.replace(/\.git$/, '')}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className={`
                flex items-center gap-1.5 text-xs mb-3 w-fit
                hover:text-[var(--primary)] transition-colors
                ${theme === 'light' ? 'text-black/40' : 'text-white/40'}
              `}
            >
              <GithubLogo size={14} weight="bold" />
              <span>{gh.owner}/{gh.repo}</span>
            </a>
          );
        })()}

        {/* Metadata Pills */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {(item.source_type === 'open' || (item.source_type === 'git' && item.git_repo_url)) && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-green-500/15 text-green-500 text-[10px] sm:text-xs rounded font-medium whitespace-nowrap">
              <GitFork size={11} weight="bold" />
              Open Source
            </span>
          )}
          {item.creator_type === 'community' && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-purple-500/15 text-purple-400 text-[10px] sm:text-xs rounded font-medium whitespace-nowrap">
              <Users size={11} weight="bold" />
              Community
            </span>
          )}
          {item.creator_type === 'official' && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-blue-500/15 text-blue-400 text-[10px] sm:text-xs rounded font-medium whitespace-nowrap">
              <ShieldCheck size={11} weight="bold" />
              Official
            </span>
          )}
          {item.rating > 0 && (
            <span
              className={`
              flex items-center gap-1 px-1.5 py-0.5 text-[10px] sm:text-xs rounded font-medium whitespace-nowrap
              ${theme === 'light' ? 'bg-amber-500/10 text-amber-600' : 'bg-amber-500/10 text-amber-400'}
            `}
            >
              <Star size={11} weight="fill" />
              {item.rating.toFixed(1)}
              {item.reviews_count > 0 && (
                <span className="opacity-60">({item.reviews_count})</span>
              )}
            </span>
          )}
          <span
            className={`
            flex items-center gap-1 px-1.5 py-0.5 text-[10px] sm:text-xs rounded font-medium whitespace-nowrap
            ${theme === 'light' ? 'bg-black/5 text-black/50' : 'bg-white/5 text-white/50'}
          `}
          >
            <Lightning size={11} weight="fill" />
            {formatInstalls(usageCount)} uses
          </span>
        </div>

        {/* Footer: Install Button */}
        <div className="flex items-center">
          {item.is_purchased && isAuthenticated ? (
            <span className="flex items-center gap-1.5 px-4 py-2 bg-green-500/15 text-green-500 rounded-xl text-sm font-medium">
              <Check size={16} weight="bold" />
              Installed
            </span>
          ) : !isAuthenticated ? (
            <button
              onClick={handleInstall}
              className="px-4 sm:px-5 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-md hover:shadow-lg"
            >
              Sign Up to Install
            </button>
          ) : (
            <button
              onClick={handleInstall}
              disabled={!item.is_active}
              className={`
                px-4 sm:px-5 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all
                ${
                  item.is_active
                    ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-md hover:shadow-lg'
                    : theme === 'light'
                      ? 'bg-black/5 text-black/40 cursor-not-allowed'
                      : 'bg-white/5 text-white/40 cursor-not-allowed'
                }
              `}
            >
              {item.is_active
                ? item.pricing_type === 'free'
                  ? 'Install'
                  : `$${item.price}/mo`
                : 'Coming Soon'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default FeaturedCard;
