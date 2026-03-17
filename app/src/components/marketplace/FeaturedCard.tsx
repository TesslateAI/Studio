import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Lightning, GitFork, Star, GithubLogo, ShieldCheck, Users } from '@phosphor-icons/react';
import { type MarketplaceItem, formatInstalls, parseGitHubRepo } from './AgentCard';
import { CardSurface, Badge } from '../cards';

interface FeaturedCardProps {
  item: MarketplaceItem;
  onInstall: (item: MarketplaceItem) => void;
  /** If false, shows "Sign Up" CTA instead of install button */
  isAuthenticated?: boolean;
}

export function FeaturedCard({ item, onInstall, isAuthenticated = true }: FeaturedCardProps) {
  const navigate = useNavigate();

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
    <CardSurface variant="featured" onClick={handleClick} isDisabled={!item.is_active} className="md:flex-row md:gap-6">
      {/* Featured Badge */}
      <Badge intent="primary" icon={<Star size={12} weight="fill" />} className="absolute top-3 right-3 sm:top-4 sm:right-4 z-10 rounded-full">
        Featured
      </Badge>

      {/* Large Icon */}
      <div className="flex-shrink-0">
        <div className="w-20 h-20 md:w-24 md:h-24 rounded-2xl flex items-center justify-center overflow-hidden bg-[var(--bg)] border border-[var(--border)]">
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
          <h3 className="font-heading font-bold text-base sm:text-lg leading-tight line-clamp-2 min-w-0 group-hover:text-[var(--primary)] transition-colors text-[var(--text)]">
            {item.name}
          </h3>
          <button
            onClick={handleCreatorClick}
            className="flex items-center gap-1.5 text-xs sm:text-sm hover:text-[var(--primary)] transition-colors mt-1 text-[var(--text-muted)]"
          >
            <div className="w-4 h-4 sm:w-5 sm:h-5 rounded-full overflow-hidden flex-shrink-0 bg-[var(--surface-hover)]">
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
        <p className="text-xs sm:text-sm leading-relaxed line-clamp-3 mb-3 text-[var(--text-muted)]">
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
              className="flex items-center gap-1.5 text-xs mb-3 w-fit hover:text-[var(--primary)] transition-colors text-[var(--text-subtle)]"
            >
              <GithubLogo size={14} weight="bold" />
              <span>{gh.owner}/{gh.repo}</span>
            </a>
          );
        })()}

        {/* Metadata Pills */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {(item.source_type === 'open' || (item.source_type === 'git' && item.git_repo_url)) && (
            <Badge intent="success" icon={<GitFork size={11} weight="bold" />}>Open Source</Badge>
          )}
          {item.creator_type === 'community' && (
            <Badge intent="purple" icon={<Users size={11} weight="bold" />}>Community</Badge>
          )}
          {item.creator_type === 'official' && (
            <Badge intent="info" icon={<ShieldCheck size={11} weight="bold" />}>Official</Badge>
          )}
          {item.rating > 0 && (
            <Badge intent="warning" icon={<Star size={11} weight="fill" />}>
              {item.rating.toFixed(1)}
              {item.reviews_count > 0 && (
                <span className="opacity-60">({item.reviews_count})</span>
              )}
            </Badge>
          )}
          <Badge intent="muted" icon={<Lightning size={11} weight="fill" />}>
            {formatInstalls(usageCount)} uses
          </Badge>
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
              className="px-5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all hover:scale-[1.02] bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-md hover:shadow-lg"
            >
              Sign Up to Install
            </button>
          ) : (
            <button
              onClick={handleInstall}
              disabled={!item.is_active}
              className={`
                px-5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all
                ${
                  item.is_active
                    ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-md hover:shadow-lg hover:scale-[1.02]'
                    : 'bg-[var(--surface-hover)] text-[var(--text-subtle)] cursor-not-allowed'
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
    </CardSurface>
  );
}

export default FeaturedCard;
