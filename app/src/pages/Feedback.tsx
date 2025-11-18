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
  CaretUp,
  Folder,
  Storefront,
  Books,
  Package,
  Sun,
  Moon,
  Gear,
  SignOut,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';

type FeedbackType = 'all' | 'bug' | 'suggestion';

interface FeedbackPost {
  id: string;
  user_id: string;
  user_name: string;
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
  }, [filter, sortBy]);

  const loadFeedback = async () => {
    try {
      setLoading(true);
      const params: any = { sort: sortBy };
      if (filter !== 'all') {
        params.type = filter;
      }

      const response = await feedbackApi.list(params);
      setFeedback(response.posts);
    } catch (error) {
      toast.error('Failed to load feedback');
    } finally {
      setLoading(false);
    }
  };

  const handleUpvote = async (feedbackId: string) => {
    try {
      const result = await feedbackApi.toggleUpvote(feedbackId);

      // Update local state
      setFeedback(prev => prev.map(item =>
        item.id === feedbackId
          ? { ...item, has_upvoted: result.upvoted, upvote_count: result.upvote_count }
          : item
      ));
    } catch (error) {
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
        onClick: () => navigate('/dashboard')
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace')
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library')
      },
      {
        icon: <ChatCircleDots className="w-5 h-5" weight="fill" />,
        title: 'Feedback',
        onClick: () => {},
        active: true
      },
      {
        icon: <Package className="w-5 h-5" weight="fill" />,
        title: 'Components',
        onClick: () => toast('Components library coming soon!')
      }
    ],
    right: [
      {
        icon: theme === 'dark' ? <Sun className="w-5 h-5" weight="fill" /> : <Moon className="w-5 h-5" weight="fill" />,
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => navigate('/settings')
      },
      {
        icon: <SignOut className="w-5 h-5" weight="fill" />,
        title: 'Logout',
        onClick: logout
      }
    ]
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
        {/* Top Bar */}
        <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center px-4 md:px-6 justify-between">
          <div className="flex items-center gap-4 md:gap-6">
            <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Feedback</h1>

            {/* Filter Tabs - Desktop */}
            <div className="hidden md:flex items-center gap-1">
              {[
                { key: 'all' as FeedbackType, label: 'All', icon: ChatCircleDots },
                { key: 'bug' as FeedbackType, label: 'Bugs', icon: Bug },
                { key: 'suggestion' as FeedbackType, label: 'Suggestions', icon: Lightbulb }
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setFilter(tab.key)}
                  className={`
                    flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-all
                    ${filter === tab.key
                      ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                      : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
                    }
                  `}
                >
                  <tab.icon size={14} weight="fill" />
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Sort Dropdown - Desktop */}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="hidden md:block text-xs bg-[var(--surface)] border border-white/10 text-[var(--text)] px-2 py-1 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            >
              <option value="upvotes">Most Upvoted</option>
              <option value="date">Most Recent</option>
              <option value="comments">Most Discussed</option>
            </select>
          </div>

          {/* New Feedback Button */}
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
          >
            <Plus size={16} weight="bold" />
            <span className="hidden md:inline">New Feedback</span>
          </button>
        </div>

        {/* Filter Tabs - Mobile */}
        <div className="md:hidden bg-[var(--surface)] border-b border-white/10 px-4 py-2 flex items-center gap-2 overflow-x-auto">
          {[
            { key: 'all' as FeedbackType, label: 'All', icon: ChatCircleDots },
            { key: 'bug' as FeedbackType, label: 'Bugs', icon: Bug },
            { key: 'suggestion' as FeedbackType, label: 'Suggestions', icon: Lightbulb }
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`
                flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-all whitespace-nowrap
                ${filter === tab.key
                  ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                  : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
                }
              `}
            >
              <tab.icon size={14} weight="fill" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-auto bg-[var(--bg)]">
          <div className="p-4 md:p-6">
            {/* Feedback Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {feedback.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedFeedback(item)}
                  className={`
                    group bg-[var(--surface)] rounded-2xl p-5 border-2 transition-all duration-300
                    hover:transform hover:-translate-y-1 text-left
                    ${item.type === 'bug'
                      ? 'border-red-500/30 hover:border-red-500/60 hover:shadow-lg hover:shadow-red-500/10'
                      : 'border-teal-500/30 hover:border-teal-500/60 hover:shadow-lg hover:shadow-teal-500/10'
                    }
                  `}
                >
                  {/* Type Badge */}
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className={`
                        inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold
                        ${item.type === 'bug'
                          ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                          : 'bg-teal-500/10 text-teal-400 border border-teal-500/20'
                        }
                      `}
                    >
                      {item.type === 'bug' ? (
                        <><Bug size={12} weight="fill" /> Bug</>
                      ) : (
                        <><Lightbulb size={12} weight="fill" /> Suggestion</>
                      )}
                    </span>

                    {/* Status Badge */}
                    {item.status !== 'open' && (
                      <span className="px-2 py-0.5 bg-white/10 text-[var(--text)]/60 text-xs rounded-md">
                        {item.status}
                      </span>
                    )}
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
                    {/* Upvote Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpvote(item.id);
                      }}
                      className={`
                        flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all
                        ${item.has_upvoted
                          ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                          : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                        }
                      `}
                    >
                      <Heart size={14} weight={item.has_upvoted ? 'fill' : 'regular'} />
                      {item.upvote_count}
                    </button>

                    {/* Comments Count */}
                    <div className="flex items-center gap-3 text-xs text-[var(--text)]/40">
                      <span className="flex items-center gap-1">
                        <ChatCircleDots size={14} />
                        {item.comment_count}
                      </span>
                      <span>{formatDate(item.created_at)}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {/* Empty State */}
            {feedback.length === 0 && (
              <div className="text-center py-16">
                <ChatCircleDots size={64} className="mx-auto text-[var(--text)]/20 mb-4" weight="thin" />
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
