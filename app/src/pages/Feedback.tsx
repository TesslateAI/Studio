import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { feedbackApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import { MobileMenu } from '../components/ui';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { CreateFeedbackModal } from '../components/modals/CreateFeedbackModal';
import { FeedbackModal } from '../components/modals/FeedbackModal';
import {
  ChatCircleDots,
  Heart,
  Bug,
  Lightbulb,
  Plus,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  Article,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';

type FeedbackType = 'all' | 'bug' | 'suggestion';

interface FeedbackPost {
  id: string;
  user_id: string;
  user_name: string;
  username: string | null;
  avatar_url: string | null;
  type: string;
  title: string;
  description: string;
  status: string;
  upvote_count: number;
  has_upvoted: boolean;
  comment_count: number;
  created_at: string;
  updated_at: string;
}

export default function Feedback() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [feedback, setFeedback] = useState<FeedbackPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FeedbackType>('all');
  const [sortBy, setSortBy] = useState<'upvotes' | 'date' | 'comments'>('upvotes');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackPost | null>(null);

  useEffect(() => {
    loadFeedback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, sortBy]);

  const loadFeedback = async () => {
    try {
      setLoading(true);
      const params: Record<string, string> = { sort: sortBy };
      if (filter !== 'all') {
        params.type = filter;
      }

      const response = await feedbackApi.list(params);
      setFeedback(response.posts);
    } catch {
      toast.error('Failed to load feedback');
    } finally {
      setLoading(false);
    }
  };

  const handleUpvote = async (feedbackId: string) => {
    try {
      const result = await feedbackApi.toggleUpvote(feedbackId);

      // Update local state
      setFeedback((prev) =>
        prev.map((item) =>
          item.id === feedbackId
            ? { ...item, has_upvoted: result.upvoted, upvote_count: result.upvote_count }
            : item
        )
      );
    } catch {
      toast.error('Failed to update upvote');
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    if (diffMins < 10080) return `${Math.floor(diffMins / 1440)}d ago`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Mobile menu items
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => navigate('/dashboard'),
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace'),
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library'),
      },
      {
        icon: <ChatCircleDots className="w-5 h-5" weight="fill" />,
        title: 'Feedback',
        onClick: () => {},
        active: true,
      },
      {
        icon: <Article className="w-5 h-5" weight="fill" />,
        title: 'Documentation',
        onClick: () => window.open('https://docs.tesslate.com', '_blank'),
      },
    ],
    right: [
      {
        icon:
          theme === 'dark' ? (
            <Sun className="w-5 h-5" weight="fill" />
          ) : (
            <Moon className="w-5 h-5" weight="fill" />
          ),
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme,
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => navigate('/settings'),
      },
      {
        icon: <SignOut className="w-5 h-5" weight="fill" />,
        title: 'Logout',
        onClick: logout,
      },
    ],
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner message="Loading feedback..." size={80} />
      </div>
    );
  }

  return (
    <>
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      {/* Header */}
      <div className="flex-shrink-0">
        {/* Title Row */}
        <div className="h-10 flex items-center justify-between gap-[6px]" style={{ paddingLeft: '18px', paddingRight: '4px', borderBottom: 'var(--border-width) solid var(--border)' }}>
          <button
            onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
            className="mobile-only btn btn-icon mr-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <h2 className="text-xs font-semibold text-[var(--text)] flex-1">Feedback</h2>

          {/* New Feedback + Sort */}
          <div className="flex items-center gap-2">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'upvotes' | 'date' | 'comments')}
              className="hidden md:block btn text-xs"
              style={{ appearance: 'auto', paddingRight: '24px' }}
            >
              <option value="upvotes">Most Upvoted</option>
              <option value="date">Most Recent</option>
              <option value="comments">Most Discussed</option>
            </select>
            <button
              onClick={() => setShowCreateModal(true)}
              className="btn btn-filled"
            >
              <Plus size={16} />
              <span className="hidden md:inline">New Feedback</span>
            </button>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="h-10 flex items-center gap-2" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
          {[
            { key: 'all' as FeedbackType, label: 'All', icon: ChatCircleDots },
            { key: 'bug' as FeedbackType, label: 'Bugs', icon: Bug },
            { key: 'suggestion' as FeedbackType, label: 'Suggestions', icon: Lightbulb },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`btn ${filter === tab.key ? 'btn-tab-active' : 'btn-tab'}`}
            >
              <tab.icon size={16} weight="fill" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-auto">
        <div className="p-4 md:p-5">
          {/* Feedback Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {feedback.map((item) => (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedFeedback(item)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setSelectedFeedback(item);
                  }
                }}
                className={`
                    group bg-[var(--surface)] rounded-2xl p-5 border-2 transition-all duration-300 cursor-pointer
                    hover:transform hover:-translate-y-1 text-left
                    ${
                      item.type === 'bug'
                        ? 'border-red-500/30 hover:border-red-500/60 hover:shadow-lg hover:shadow-red-500/10'
                        : 'border-teal-500/30 hover:border-teal-500/60 hover:shadow-lg hover:shadow-teal-500/10'
                    }
                  `}
              >
                {/* Type Badge & User */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`
                          inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold
                          ${
                            item.type === 'bug'
                              ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                              : 'bg-teal-500/10 text-teal-400 border border-teal-500/20'
                          }
                        `}
                    >
                      {item.type === 'bug' ? (
                        <>
                          <Bug size={12} weight="fill" /> Bug
                        </>
                      ) : (
                        <>
                          <Lightbulb size={12} weight="fill" /> Suggestion
                        </>
                      )}
                    </span>

                    {/* Status Badge */}
                    {item.status !== 'open' && (
                      <span className="px-2 py-0.5 bg-white/10 text-[var(--text)]/60 text-xs rounded-md">
                        {item.status}
                      </span>
                    )}
                  </div>
                </div>

                {/* Title */}
                <h3 className="font-heading text-base font-bold text-[var(--text)] mb-2 line-clamp-2 group-hover:text-[var(--primary)] transition-colors">
                  {item.title}
                </h3>

                {/* Description Preview */}
                <p className="text-sm text-[var(--text)]/60 mb-4 line-clamp-2">
                  {item.description}
                </p>

                {/* Footer */}
                <div className="flex items-center justify-between pt-3 border-t border-white/10">
                  <div className="flex items-center gap-3">
                    {/* Upvote Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpvote(item.id);
                      }}
                      className={`
                          flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all
                          ${
                            item.has_upvoted
                              ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                              : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                          }
                        `}
                    >
                      <Heart size={14} weight={item.has_upvoted ? 'fill' : 'regular'} />
                      {item.upvote_count}
                    </button>

                    {/* Comments Count */}
                    <span className="flex items-center gap-1 text-xs text-[var(--text)]/40">
                      <ChatCircleDots size={14} />
                      {item.comment_count}
                    </span>
                  </div>

                  {/* User Info */}
                  <div className="flex items-center gap-2">
                    {item.avatar_url ? (
                      <img
                        src={item.avatar_url}
                        alt={item.user_name}
                        className="w-5 h-5 rounded-full object-cover"
                      />
                    ) : (
                      <div className="w-5 h-5 rounded-full bg-[var(--primary)]/20 flex items-center justify-center text-[var(--primary)] text-[10px] font-bold">
                        {item.user_name.charAt(0).toUpperCase()}
                      </div>
                    )}
                    <span className="text-xs text-[var(--text)]/50 truncate max-w-[100px]">
                      {item.username ? `@${item.username}` : item.user_name}
                    </span>
                    <span className="text-xs text-[var(--text)]/30">
                      {formatDate(item.created_at)}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Empty State */}
          {feedback.length === 0 && (
            <div className="text-center py-16">
              <ChatCircleDots
                size={64}
                className="mx-auto text-[var(--text)]/20 mb-4"
                weight="thin"
              />
              <p className="text-[var(--text)]/40 text-sm mb-4">No feedback found</p>
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white px-4 py-2 rounded-lg text-sm font-semibold transition-all"
              >
                <Plus size={16} weight="bold" />
                Create First Feedback
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Create Feedback Modal */}
      <CreateFeedbackModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSuccess={() => loadFeedback()}
      />

      {/* View Feedback Details Modal */}
      <FeedbackModal
        isOpen={!!selectedFeedback}
        feedbackId={selectedFeedback?.id || null}
        onClose={() => setSelectedFeedback(null)}
        onUpdate={() => loadFeedback()}
      />
    </>
  );
}
