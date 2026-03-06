import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Lightning, GitFork, Star, ShieldCheck, Users, GithubLogo } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { marketplaceApi } from '../../lib/api';
import toast from 'react-hot-toast';

export interface MarketplaceItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  category: string;
  item_type: 'agent' | 'base' | 'theme' | 'tool' | 'integration';
  mode?: string;
  agent_type?: string;
  model?: string;
  source_type: 'open' | 'closed' | 'git' | 'archive';
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
  creator_username?: string | null;
  creator_avatar_url?: string | null;
  created_by_user_id?: string;
  forked_by_user_id?: string;
  // Base-specific fields
  git_repo_url?: string;
  // Theme-specific fields
  theme_mode?: string;
  color_swatches?: {
    primary?: string;
    accent?: string;
    background?: string;
    surface?: string;
  };
}

interface AgentCardProps {
  item: MarketplaceItem;
  onInstall: (item: MarketplaceItem) => void;
  /** If false, shows "Sign Up" CTA instead of install button */
  isAuthenticated?: boolean;
}

// Parse owner/repo from a GitHub URL
// eslint-disable-next-line react-refresh/only-export-components
export function parseGitHubRepo(url: string): { owner: string; repo: string } | null {
  try {
    const match = url.match(/github\.com\/([^/]+)\/([^/.]+)/);
    if (match) return { owner: match[1], repo: match[2] };
  } catch { /* ignore */ }
  return null;
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

export function AgentCard({ item, onInstall, isAuthenticated = true }: AgentCardProps) {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [forking, setForking] = React.useState(false);

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

  const handleFork = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isAuthenticated || forking) return;

    setForking(true);
    try {
      if (item.item_type === 'theme') {
        await marketplaceApi.forkTheme(item.id);
        toast.success(`Forked "${item.name}" to your library!`);
        navigate('/library?tab=themes');
      } else {
        await marketplaceApi.forkAgent(item.id);
        toast.success(`Forked "${item.name}" to your library!`);
        navigate('/library?tab=agents');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || `Failed to fork ${item.item_type}`);
    } finally {
      setForking(false);
    }
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
        group relative flex flex-col p-4 rounded-xl border cursor-pointer
        transition-all duration-200 ease-out
        hover:-translate-y-0.5 hover:shadow-lg
        ${
          theme === 'light'
            ? 'bg-white border-black/10 hover:border-[var(--primary)]/40'
            : 'bg-[#1a1a1c] border-white/10 hover:border-[var(--primary)]/40'
        }
        ${!item.is_active ? 'opacity-60' : ''}
      `}
    >
      {/* Header: Icon + Name + Creator */}
      <div className="flex items-start gap-3 mb-2">
        {/* Icon / Theme Swatches */}
        <div className="flex-shrink-0">
          {item.item_type === 'theme' && item.color_swatches ? (
            <div className="flex gap-1">
              {(['primary', 'background', 'surface', 'accent'] as const).map((key) => (
                <div
                  key={key}
                  className="w-5 h-5 rounded-md border border-black/20"
                  style={{ backgroundColor: item.color_swatches?.[key] || '#333' }}
                  title={key.charAt(0).toUpperCase() + key.slice(1)}
                />
              ))}
            </div>
          ) : (
            <div
              className={`
              w-10 h-10 rounded-xl flex items-center justify-center overflow-hidden
              ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
            `}
            >
              {item.avatar_url ? (
                <img src={item.avatar_url} alt={item.name} className="w-full h-full object-cover" />
              ) : item.git_repo_url && parseGitHubRepo(item.git_repo_url) ? (
                <GithubLogo size={24} weight="fill" className={theme === 'light' ? 'text-black/70' : 'text-white/70'} />
              ) : (
                <img src="/favicon.svg" alt="Tesslate" className="w-6 h-6" />
              )}
            </div>
          )}
        </div>

        {/* Name + Creator */}
        <div className="min-w-0 flex-1">
          <h3
            className={`
            font-heading font-semibold text-sm sm:text-base leading-tight line-clamp-2
            group-hover:text-[var(--primary)] transition-colors
            ${theme === 'light' ? 'text-black' : 'text-white'}
          `}
          >
            {item.name}
          </h3>
          <button
            onClick={handleCreatorClick}
            className={`
              text-xs hover:text-[var(--primary)] transition-colors mt-0.5
              ${theme === 'light' ? 'text-black/50' : 'text-white/50'}
            `}
          >
            {item.creator_type === 'official'
              ? 'Tesslate'
              : item.creator_username
                ? `@${item.creator_username}`
                : item.creator_name || 'Unknown'}
          </button>
        </div>
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
              flex items-center gap-1.5 text-[11px] mb-3 w-fit
              hover:text-[var(--primary)] transition-colors
              ${theme === 'light' ? 'text-black/40' : 'text-white/40'}
            `}
          >
            <GithubLogo size={13} weight="bold" />
            <span className="truncate">{gh.owner}/{gh.repo}</span>
          </a>
        );
      })()}

      {/* Metadata Pills */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(item.source_type === 'open' || (item.source_type === 'git' && item.git_repo_url)) && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-green-500/15 text-green-500 text-[10px] rounded font-medium whitespace-nowrap">
            <GitFork size={10} weight="bold" />
            Open Source
          </span>
        )}
        {item.source_type === 'archive' && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-purple-500/15 text-purple-400 text-[10px] rounded font-medium whitespace-nowrap">
            Exported
          </span>
        )}
        {item.creator_type === 'community' && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-purple-500/15 text-purple-400 text-[10px] rounded font-medium whitespace-nowrap">
            <Users size={10} weight="bold" />
            Community
          </span>
        )}
        {item.creator_type === 'official' && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-blue-500/15 text-blue-400 text-[10px] rounded font-medium whitespace-nowrap">
            <ShieldCheck size={10} weight="bold" />
            Official
          </span>
        )}
        {item.item_type === 'theme' && item.theme_mode && (
          <span
            className={`px-1.5 py-0.5 text-[10px] rounded font-medium ${
              item.theme_mode === 'dark'
                ? 'bg-white/10 text-white/60'
                : 'bg-black/10 text-black/60'
            }`}
          >
            {item.theme_mode}
          </span>
        )}
        {item.rating > 0 && (
          <span
            className={`
            flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded font-medium whitespace-nowrap
            ${theme === 'light' ? 'bg-amber-500/10 text-amber-600' : 'bg-amber-500/10 text-amber-400'}
          `}
          >
            <Star size={10} weight="fill" />
            {item.rating.toFixed(1)}
          </span>
        )}
        <span
          className={`
          flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded font-medium whitespace-nowrap
          ${theme === 'light' ? 'bg-black/5 text-black/50' : 'bg-white/5 text-white/50'}
        `}
        >
          <Lightning size={10} weight="fill" />
          {formatInstalls(usageCount)}
        </span>
      </div>

      {/* Footer: Action Buttons */}
      <div className="mt-auto pt-3 border-t border-white/5">
        <div className="flex items-center justify-between">
          {item.pricing_type === 'free' && !item.is_purchased && (
            <span className={`text-xs ${theme === 'light' ? 'text-black/40' : 'text-white/40'}`}>
              Free
            </span>
          )}
          {(item.pricing_type !== 'free' || item.is_purchased) && <div />}

          <div className="flex items-center gap-1.5 ml-auto">
            {item.is_purchased &&
              isAuthenticated &&
              item.source_type === 'open' &&
              item.is_forkable && (
                <button
                  onClick={handleFork}
                  disabled={forking}
                  title="Fork & Customize"
                  className="flex items-center gap-1 px-2 py-1 bg-purple-500/15 text-purple-400 hover:bg-purple-500/25 rounded-lg text-xs font-medium transition-colors"
                >
                  <GitFork size={12} weight="bold" />
                  {forking ? '...' : 'Fork'}
                </button>
              )}
            {item.is_purchased && isAuthenticated ? (
              <span className="flex items-center gap-1 px-2.5 py-1 bg-green-500/15 text-green-500 rounded-lg text-xs font-medium">
                <Check size={12} weight="bold" />
                Installed
              </span>
            ) : !isAuthenticated ? (
              <button
                onClick={handleInstall}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-sm hover:shadow-md"
              >
                Sign Up
              </button>
            ) : (
              <button
                onClick={handleInstall}
                disabled={!item.is_active}
                className={`
                px-3 py-1.5 rounded-lg text-xs font-semibold transition-all
                ${
                  item.is_active
                    ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-sm hover:shadow-md'
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
                  : 'Soon'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AgentCard;
