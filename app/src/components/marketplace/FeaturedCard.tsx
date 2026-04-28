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
    <CardSurface variant="featured" onClick={handleClick} isDisabled={!item.is_active} className="sm:flex-row sm:gap-5">
      {/* Top row: Icon + Title + Install (mobile-first) */}
      <div className="flex items-start gap-3 sm:contents">
        {/* Icon */}
        <div className="flex-shrink-0">
          <div className="w-14 h-14 sm:w-20 sm:h-20 md:w-24 md:h-24 rounded-[var(--radius)] flex items-center justify-center overflow-hidden bg-[var(--bg)] border border-[var(--border)]">
            {item.avatar_url ? (
              <img src={item.avatar_url} alt={item.name} className="w-full h-full object-cover" />
            ) : (
              <img src="/favicon.svg" alt="Tesslate" className="w-8 h-8 sm:w-12 sm:h-12" />
            )}
          </div>
        </div>

        {/* Content — stacks on mobile, fills on desktop */}
        <div className="flex-1 min-w-0">
          {/* Title + Creator */}
          <div className="mb-1.5">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm sm:text-base font-bold leading-tight line-clamp-2 min-w-0 transition-colors text-[var(--text)]">
                {item.name}
              </h3>
              {/* Featured badge — inline on mobile */}
              <Badge intent="primary" icon={<Star size={10} weight="fill" />} className="shrink-0 rounded-full">
                Featured
              </Badge>
            </div>
            <button
              onClick={handleCreatorClick}
              className="flex items-center gap-1.5 text-[11px] hover:text-[var(--primary)] transition-colors mt-0.5 text-[var(--text-muted)]"
            >
              <div className="w-4 h-4 rounded-full overflow-hidden flex-shrink-0 bg-[var(--surface-hover)]">
                {item.creator_avatar_url ? (
                  <img src={item.creator_avatar_url} alt={item.creator_name || 'Creator'} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-[9px] font-medium">
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
          <p className="text-xs leading-relaxed line-clamp-2 sm:line-clamp-3 mb-2 text-[var(--text-muted)]">
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
                className="flex items-center gap-1.5 text-[11px] mb-2 w-fit hover:text-[var(--primary)] transition-colors text-[var(--text-subtle)]"
              >
                <GithubLogo size={13} weight="bold" />
                <span>{gh.owner}/{gh.repo}</span>
              </a>
            );
          })()}

          {/* Metadata Pills */}
          <div className="flex flex-wrap gap-1 mb-3">
            {(item.source_type === 'open' || (item.source_type === 'git' && item.git_repo_url)) && (
              <Badge intent="success" icon={<GitFork size={10} weight="bold" />}>Open Source</Badge>
            )}
            {item.creator_type === 'community' && (
              <Badge intent="purple" icon={<Users size={10} weight="bold" />}>Community</Badge>
            )}
            {item.creator_type === 'official' && (
              <Badge intent="info" icon={<ShieldCheck size={10} weight="bold" />}>Official</Badge>
            )}
            {item.rating > 0 && (
              <Badge intent="warning" icon={<Star size={10} weight="fill" />}>
                {item.rating.toFixed(1)}
              </Badge>
            )}
            <Badge intent="muted" icon={<Lightning size={10} weight="fill" />}>
              {formatInstalls(usageCount)}
            </Badge>
          </div>

          {/* Install Button — always tappable */}
          <div className="flex items-center">
            {item.is_purchased && isAuthenticated ? (
              <span className="btn" style={{ color: 'var(--status-success)', background: 'rgba(var(--status-green-rgb), 0.1)', borderColor: 'rgba(var(--status-green-rgb), 0.3)' }}>
                <Check size={14} weight="bold" />
                Installed
              </span>
            ) : !isAuthenticated ? (
              <button onClick={handleInstall} className="btn btn-filled">
                Sign Up to Install
              </button>
            ) : (
              <button
                onClick={handleInstall}
                disabled={!item.is_active}
                className={`btn ${item.is_active ? 'btn-filled' : ''}`}
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
    </CardSurface>
  );
}

export default FeaturedCard;
