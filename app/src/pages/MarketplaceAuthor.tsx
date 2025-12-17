import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Lightning,
  Package,
  TwitterLogo,
  GithubLogo,
  Globe,
  CalendarBlank
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { AgentCard, MarketplaceItem, formatInstalls } from '../components/marketplace';
import { creatorsApi, marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';

interface CreatorProfile {
  id: string;
  name: string;
  username: string;
  avatar_url?: string | null;
  bio?: string | null;
  twitter_handle?: string | null;
  github_username?: string | null;
  website_url?: string | null;
  joined_at?: string | null;
  stats: {
    extensions_count: number;
    total_downloads: number;
    average_rating: number;
  };
  extensions: MarketplaceItem[];
}

export default function MarketplaceAuthor() {
  const { userId } = useParams<{ userId: string }>();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [creator, setCreator] = useState<CreatorProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (userId) {
      loadCreatorProfile();
    }
  }, [userId]);

  const loadCreatorProfile = async () => {
    try {
      const data = await creatorsApi.getProfile(userId!);
      // Ensure extensions have item_type
      const extensions = (data.extensions || []).map((ext: Record<string, unknown>) => ({
        ...ext,
        item_type: ext.item_type || 'agent'
      }));
      setCreator({ ...data, extensions });
    } catch (error) {
      console.error('Failed to load creator:', error);
      toast.error('Creator not found');
      navigate('/marketplace');
    } finally {
      setLoading(false);
    }
  };

  const handleInstall = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    try {
      const data = item.item_type === 'base'
        ? await marketplaceApi.purchaseBase(item.id)
        : await marketplaceApi.purchaseAgent(item.id);

      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        toast.success(`${item.name} added to your library!`);
        setCreator(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            extensions: prev.extensions.map(e =>
              e.id === item.id ? { ...e, is_purchased: true } : e
            )
          };
        });
      }
    } catch {
      toast.error('Failed to add to library');
    }
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading creator profile..." size={80} />
      </div>
    );
  }

  if (!creator) {
    return null;
  }

  return (
    <div className={`h-screen overflow-y-auto ${theme === 'light' ? 'bg-white' : 'bg-[var(--bg)]'}`}>
      {/* Header */}
      <div className={`border-b ${theme === 'light' ? 'border-black/10' : 'border-white/10'} sticky top-0 z-40 backdrop-blur-xl ${theme === 'light' ? 'bg-white/80' : 'bg-[#0a0a0a]/80'}`}>
        <div className="max-w-5xl mx-auto px-6 md:px-12">
          <div className="h-14 flex items-center gap-4">
            <button
              onClick={() => navigate('/marketplace')}
              className={`
                flex items-center gap-2 text-sm font-medium transition-colors
                ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}
              `}
            >
              <ArrowLeft size={18} />
              <span>Marketplace</span>
            </button>
          </div>
        </div>
      </div>

      {/* Profile Header */}
      <div className="max-w-5xl mx-auto px-6 md:px-12 py-12">
        <div className="flex flex-col md:flex-row gap-8 items-start">
          {/* Avatar */}
          <div className="flex-shrink-0">
            <div className={`
              w-24 h-24 md:w-32 md:h-32 rounded-full flex items-center justify-center overflow-hidden
              ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
            `}>
              {creator.avatar_url ? (
                <img
                  src={creator.avatar_url}
                  alt={creator.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className={`text-4xl md:text-5xl font-bold ${theme === 'light' ? 'text-black/20' : 'text-white/20'}`}>
                  {creator.name?.charAt(0).toUpperCase() || '?'}
                </span>
              )}
            </div>
          </div>

          {/* Info */}
          <div className="flex-1">
            {/* Name */}
            <h1 className={`font-heading text-3xl md:text-4xl font-bold mb-2 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              {creator.name}
            </h1>

            {/* Username */}
            <p className={`text-lg mb-4 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
              @{creator.username}
            </p>

            {/* Bio */}
            {creator.bio && (
              <p className={`text-base mb-6 max-w-2xl ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}>
                {creator.bio}
              </p>
            )}

            {/* Social Links */}
            <div className="flex flex-wrap items-center gap-4">
              {creator.twitter_handle && (
                <a
                  href={`https://twitter.com/${creator.twitter_handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`
                    flex items-center gap-2 text-sm transition-colors
                    ${theme === 'light' ? 'text-black/50 hover:text-[#1DA1F2]' : 'text-white/50 hover:text-[#1DA1F2]'}
                  `}
                >
                  <TwitterLogo size={18} weight="fill" />
                  <span>@{creator.twitter_handle}</span>
                </a>
              )}
              {creator.github_username && (
                <a
                  href={`https://github.com/${creator.github_username}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`
                    flex items-center gap-2 text-sm transition-colors
                    ${theme === 'light' ? 'text-black/50 hover:text-black' : 'text-white/50 hover:text-white'}
                  `}
                >
                  <GithubLogo size={18} weight="fill" />
                  <span>{creator.github_username}</span>
                </a>
              )}
              {creator.website_url && (
                <a
                  href={creator.website_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`
                    flex items-center gap-2 text-sm transition-colors
                    ${theme === 'light' ? 'text-black/50 hover:text-[var(--primary)]' : 'text-white/50 hover:text-[var(--primary)]'}
                  `}
                >
                  <Globe size={18} weight="bold" />
                  <span>Website</span>
                </a>
              )}
              {creator.joined_at && (
                <div className={`flex items-center gap-2 text-sm ${theme === 'light' ? 'text-black/40' : 'text-white/40'}`}>
                  <CalendarBlank size={18} />
                  <span>Joined {formatDate(creator.joined_at)}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Stats Bar */}
      <div className="max-w-5xl mx-auto px-6 md:px-12 mb-12">
        <div className={`
          flex flex-wrap items-center gap-8 py-6 px-8 rounded-2xl
          ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
        `}>
          {/* Extensions Count */}
          <div className="flex items-center gap-3">
            <Package size={24} className="text-[var(--primary)]" weight="fill" />
            <div>
              <div className={`text-2xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}>
                {creator.stats.extensions_count}
              </div>
              <div className={`text-sm ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                Extensions
              </div>
            </div>
          </div>

          {/* Divider */}
          <div className={`w-px h-12 ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'}`} />

          {/* Total Uses */}
          <div className="flex items-center gap-3">
            <Lightning size={24} className="text-[var(--primary)]" weight="fill" />
            <div>
              <div className={`text-2xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}>
                {formatInstalls(creator.stats.total_downloads)}
              </div>
              <div className={`text-sm ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                Total Uses
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Extensions Grid */}
      <div className="max-w-5xl mx-auto px-6 md:px-12 pb-16">
        <h2 className={`font-heading text-xl font-bold mb-6 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
          Extensions by {creator.name}
        </h2>

        {creator.extensions.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {creator.extensions.map(item => (
              <AgentCard
                key={item.id}
                item={item}
                onInstall={handleInstall}
              />
            ))}
          </div>
        ) : (
          <div className={`
            text-center py-16 rounded-2xl
            ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
          `}>
            <Package size={48} className={`mx-auto mb-4 ${theme === 'light' ? 'text-black/20' : 'text-white/20'}`} />
            <p className={theme === 'light' ? 'text-black/40' : 'text-white/40'}>
              No extensions published yet
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
