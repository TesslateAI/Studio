import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  Download,
  GitFork,
  Globe,
  File,
  FileText,
  FilePlus,
  Terminal,
  ListChecks,
  Pencil,
  Package,
  ChatCircle,
  Trash,
  X,
  ShieldCheck,
  Users,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import {
  StatsBar,
  type MarketplaceItem,
  AgentCard,
  ReviewCard,
  RatingPicker,
  type Review,
} from '../components/marketplace';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';
import {
  SEO,
  generateProductStructuredData,
  generateBreadcrumbStructuredData,
} from '../components/SEO';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

// Tool icons mapping
const toolIcons: Record<string, { icon: React.ReactNode; label: string }> = {
  read_file: { icon: <File size={14} weight="fill" />, label: 'Read File' },
  write_file: { icon: <FilePlus size={14} weight="fill" />, label: 'Write File' },
  patch_file: { icon: <Pencil size={14} weight="fill" />, label: 'Patch File' },
  multi_edit: { icon: <FileText size={14} weight="fill" />, label: 'Multi-Edit' },
  bash_exec: { icon: <Terminal size={14} weight="fill" />, label: 'Bash' },
  shell_open: { icon: <Terminal size={14} weight="fill" />, label: 'Shell Open' },
  shell_exec: { icon: <Terminal size={14} weight="fill" />, label: 'Shell' },
  shell_close: { icon: <Terminal size={14} weight="fill" />, label: 'Shell Close' },
  get_project_info: { icon: <Package size={14} weight="fill" />, label: 'Project Info' },
  todo_read: { icon: <ListChecks size={14} weight="fill" />, label: 'Todo Read' },
  todo_write: { icon: <ListChecks size={14} weight="fill" />, label: 'Todo Write' },
  web_fetch: { icon: <Globe size={14} weight="fill" />, label: 'Web Fetch' },
};

const ALL_TOOLS = Object.keys(toolIcons);

export default function MarketplaceDetail() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const { isAuthenticated } = useMarketplaceAuth();
  const [item, setItem] = useState<MarketplaceItem | null>(null);
  const [relatedItems, setRelatedItems] = useState<MarketplaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const [forking, setForking] = useState(false);

  // Review state
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loadingReviews, setLoadingReviews] = useState(false);
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewComment, setReviewComment] = useState('');
  const [submittingReview, setSubmittingReview] = useState(false);
  const [editingReview, setEditingReview] = useState(false);

  useEffect(() => {
    if (slug) {
      setLoading(true);
      loadItemDetails();
    }
  }, [slug]);

  // Reload agent details when returning to this page (e.g., after removing from Library)
  useEffect(() => {
    const handleFocus = () => {
      if (slug && item) {
        loadItemDetails();
      }
    };
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, [slug, item?.id]);

  const loadItemDetails = async () => {
    try {
      // Try to get agent details first
      const data = await marketplaceApi.getAgentDetails(slug!);
      setItem({ ...data, item_type: 'agent' });

      // Load related items using recommendations API (co-install based)
      try {
        const related = await marketplaceApi.getRelatedAgents(slug!, 4);
        setRelatedItems(
          related.map((a: Record<string, unknown>) => ({ ...a, item_type: 'agent' }))
        );
      } catch {
        // Fallback to same category if recommendations fail
        const allAgents = await marketplaceApi.getAllAgents();
        const related = (allAgents.agents || [])
          .filter((a: Record<string, unknown>) => a.slug !== slug && a.category === data.category)
          .slice(0, 4)
          .map((a: Record<string, unknown>) => ({ ...a, item_type: 'agent' }));
        setRelatedItems(related);
      }
    } catch {
      // Try base if agent not found
      try {
        const bases = await marketplaceApi.getAllBases();
        const base = (bases.bases || []).find((b: Record<string, unknown>) => b.slug === slug);
        if (base) {
          setItem({ ...base, item_type: 'base' });
          const related = (bases.bases || [])
            .filter((b: Record<string, unknown>) => b.slug !== slug)
            .slice(0, 4)
            .map((b: Record<string, unknown>) => ({ ...b, item_type: 'base' }));
          setRelatedItems(related);
        } else {
          toast.error('Extension not found');
          navigate('/marketplace');
        }
      } catch {
        toast.error('Failed to load extension');
        navigate('/marketplace');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleInstall = async () => {
    if (!item) return;

    // Redirect unauthenticated users to sign up
    if (!isAuthenticated) {
      navigate(`/register?redirect=${encodeURIComponent(`/marketplace/${item.slug}`)}`);
      return;
    }

    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      // Button already shows "Coming Soon" - no toast needed
      return;
    }

    setInstalling(true);
    try {
      const data =
        item.item_type === 'base'
          ? await marketplaceApi.purchaseBase(item.id)
          : await marketplaceApi.purchaseAgent(item.id);

      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        toast.success(`${item.name} added to your library!`);
        setItem({ ...item, is_purchased: true });
      }
    } catch (error) {
      console.error('Failed to install:', error);
      toast.error('Failed to add to library');
    } finally {
      setInstalling(false);
    }
  };

  const handleUninstall = async () => {
    if (!item) return;

    setUninstalling(true);
    try {
      await marketplaceApi.removeFromLibrary(item.id);
      toast.success(`${item.name} removed from your library`);
      setItem({ ...item, is_purchased: false });
    } catch (error) {
      console.error('Failed to uninstall:', error);
      toast.error('Failed to remove from library');
    } finally {
      setUninstalling(false);
    }
  };

  const handleRelatedInstall = async (relatedItem: MarketplaceItem) => {
    // Redirect unauthenticated users to sign up
    if (!isAuthenticated) {
      navigate(`/register?redirect=${encodeURIComponent(`/marketplace/${relatedItem.slug}`)}`);
      return;
    }

    if (relatedItem.is_purchased) {
      toast.success(`${relatedItem.name} already in your library`);
      return;
    }

    try {
      const data =
        relatedItem.item_type === 'base'
          ? await marketplaceApi.purchaseBase(relatedItem.id)
          : await marketplaceApi.purchaseAgent(relatedItem.id);

      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        toast.success(`${relatedItem.name} added to your library!`);
        setRelatedItems((prev) =>
          prev.map((i) => (i.id === relatedItem.id ? { ...i, is_purchased: true } : i))
        );
      }
    } catch {
      toast.error('Failed to add to library');
    }
  };

  const handleFork = async () => {
    if (!item || !isAuthenticated) return;

    setForking(true);
    try {
      await marketplaceApi.forkAgent(item.id);
      toast.success(`Forked "${item.name}" to your library! You can now customize it.`);
      navigate('/library?tab=agents');
    } catch (error: unknown) {
      console.error('Fork failed:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to fork agent');
    } finally {
      setForking(false);
    }
  };

  // Load reviews for the agent
  const loadReviews = async () => {
    if (!item?.id || (item.item_type !== 'agent' && item.item_type !== 'base')) return;

    setLoadingReviews(true);
    try {
      const data =
        item.item_type === 'agent'
          ? await marketplaceApi.getAgentReviews(item.id)
          : await marketplaceApi.getBaseReviews(item.id);
      setReviews(data.reviews || []);

      // Check if user has already reviewed - pre-fill form if so
      const userReview = data.reviews?.find((r: Review) => r.is_own_review);
      if (userReview) {
        setReviewRating(userReview.rating);
        setReviewComment(userReview.comment || '');
        setEditingReview(true);
      }
    } catch (error) {
      console.error('Failed to load reviews:', error);
    } finally {
      setLoadingReviews(false);
    }
  };

  // Submit or update review
  const handleSubmitReview = async () => {
    if (!item?.id) return;

    setSubmittingReview(true);
    try {
      if (item.item_type === 'agent') {
        await marketplaceApi.createAgentReview(item.id, reviewRating, reviewComment || undefined);
      } else {
        await marketplaceApi.createBaseReview(item.id, reviewRating, reviewComment || undefined);
      }
      toast.success(editingReview ? 'Review updated!' : 'Review submitted!');
      setShowReviewForm(false);
      setEditingReview(true);
      loadReviews(); // Reload reviews
    } catch (error: unknown) {
      console.error('Failed to submit review:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to submit review');
    } finally {
      setSubmittingReview(false);
    }
  };

  // Delete review
  const handleDeleteReview = async () => {
    if (!item?.id) return;

    if (!confirm('Are you sure you want to delete your review?')) return;

    try {
      if (item.item_type === 'agent') {
        await marketplaceApi.deleteAgentReview(item.id);
      } else {
        await marketplaceApi.deleteBaseReview(item.id);
      }
      toast.success('Review deleted');
      setReviewRating(5);
      setReviewComment('');
      setEditingReview(false);
      loadReviews(); // Reload reviews
    } catch (error: unknown) {
      console.error('Failed to delete review:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to delete review');
    }
  };

  // Load reviews when item loads
  useEffect(() => {
    if (item?.id && (item.item_type === 'agent' || item.item_type === 'base')) {
      loadReviews();
    }
  }, [item?.id]);

  const creatorId = item?.forked_by_user_id || item?.created_by_user_id;

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading extension..." size={80} />
      </div>
    );
  }

  if (!item) {
    return null;
  }

  // Generate SEO structured data
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';
  const productStructuredData = generateProductStructuredData({
    name: item.name,
    description: item.description,
    slug: item.slug,
    price: item.price || 0,
    pricing_type: item.pricing_type,
    rating: item.rating,
    review_count: item.review_count,
    creator_name: item.creator_name,
    avatar_url: item.avatar_url,
    category: item.category,
  });

  const breadcrumbData = generateBreadcrumbStructuredData([
    { name: 'Marketplace', url: `${baseUrl}/marketplace` },
    {
      name: item.category || 'Agents',
      url: `${baseUrl}/marketplace/browse/agent?category=${item.category || 'builder'}`,
    },
    { name: item.name, url: `${baseUrl}/marketplace/${item.slug}` },
  ]);

  return (
    <>
      <SEO
        title={`${item.name} - AI ${item.item_type === 'base' ? 'Template' : 'Agent'}`}
        description={
          item.description ||
          `${item.name} is an AI-powered ${item.item_type === 'base' ? 'project template' : 'coding agent'} on Tesslate Marketplace.`
        }
        keywords={[
          item.name,
          item.category || '',
          item.item_type || 'agent',
          'AI agent',
          'Tesslate',
          ...(item.tags || []),
        ].filter(Boolean)}
        image={item.avatar_url || item.preview_image}
        url={`${baseUrl}/marketplace/${item.slug}`}
        type="product"
        author={item.creator_name}
        structuredData={{
          '@context': 'https://schema.org',
          '@graph': [productStructuredData, breadcrumbData],
        }}
      />
      <div
        className={`h-screen overflow-y-auto ${theme === 'light' ? 'bg-white' : 'bg-[var(--bg)]'}`}
      >
        {/* Header */}
        <div
          className={`border-b ${theme === 'light' ? 'border-black/10' : 'border-white/10'} sticky top-0 z-40 backdrop-blur-xl ${theme === 'light' ? 'bg-white/80' : 'bg-[#0a0a0a]/80'}`}
        >
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

        {/* Hero Section */}
        <div className="max-w-5xl mx-auto px-6 md:px-12 py-12">
          <div className="flex flex-col md:flex-row gap-8">
            {/* Icon */}
            <div className="flex-shrink-0">
              <div
                className={`
              w-24 h-24 md:w-32 md:h-32 rounded-3xl flex items-center justify-center overflow-hidden
              ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
            `}
              >
                {item.avatar_url ? (
                  <img
                    src={item.avatar_url}
                    alt={item.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <img src="/favicon.svg" alt="Tesslate" className="w-16 h-16 md:w-20 md:h-20" />
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1">
              {/* Title Row */}
              <div className="flex flex-wrap items-start gap-2 sm:gap-3 mb-3">
                <h1
                  className={`font-heading text-2xl sm:text-3xl md:text-4xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                >
                  {item.name}
                </h1>
                <div className="flex items-center gap-2 flex-wrap">
                  {item.source_type === 'open' && (
                    <span className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/15 text-green-500 text-xs sm:text-sm rounded-lg font-medium whitespace-nowrap">
                      <GitFork size={14} weight="bold" />
                      Open Source
                    </span>
                  )}
                  {item.creator_type === 'community' && (
                    <span className="flex items-center gap-1.5 px-2.5 py-1 bg-purple-500/15 text-purple-400 text-xs sm:text-sm rounded-lg font-medium whitespace-nowrap">
                      <Users size={14} weight="bold" />
                      Community
                    </span>
                  )}
                  {item.creator_type === 'official' && (
                    <span className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/15 text-blue-400 text-xs sm:text-sm rounded-lg font-medium whitespace-nowrap">
                      <ShieldCheck size={14} weight="bold" />
                      Official
                    </span>
                  )}
                </div>
              </div>

              {/* Description */}
              <p
                className={`text-lg mb-4 ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
              >
                {item.description}
              </p>

              {/* Author */}
              <div className="flex items-center gap-4 mb-6">
                {creatorId || item.creator_username ? (
                  <Link
                    to={
                      item.creator_username
                        ? `/@${item.creator_username}`
                        : `/marketplace/creator/${creatorId}`
                    }
                    className={`
                    flex items-center gap-2 text-sm hover:text-[var(--primary)] transition-colors
                    ${theme === 'light' ? 'text-black/60' : 'text-white/60'}
                  `}
                  >
                    <div
                      className={`
                    w-6 h-6 rounded-full overflow-hidden flex-shrink-0
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
                        <div className="w-full h-full flex items-center justify-center text-xs font-medium">
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
                  </Link>
                ) : (
                  <span
                    className={`text-sm ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}
                  >
                    By Tesslate
                  </span>
                )}
              </div>

              {/* Install Button */}
              <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                {item.is_purchased ? (
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-2 px-6 py-3 bg-green-500/15 text-green-500 rounded-xl text-sm font-semibold">
                      <Check size={18} weight="bold" />
                      Installed
                    </span>
                    {item.item_type === 'agent' && (
                      <button
                        onClick={handleUninstall}
                        disabled={uninstalling}
                        className={`
                          flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold transition-all
                          ${
                            theme === 'light'
                              ? 'bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-500/20'
                              : 'bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20'
                          }
                        `}
                      >
                        {uninstalling ? (
                          <>
                            <div className="w-4 h-4 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                            Removing...
                          </>
                        ) : (
                          <>
                            <Trash size={18} weight="bold" />
                            Uninstall
                          </>
                        )}
                      </button>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={handleInstall}
                    disabled={!item.is_active || installing}
                    className={`
                    flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold transition-all
                    ${
                      item.is_active
                        ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white shadow-lg hover:shadow-xl'
                        : theme === 'light'
                          ? 'bg-black/5 text-black/40 cursor-not-allowed'
                          : 'bg-white/5 text-white/40 cursor-not-allowed'
                    }
                  `}
                  >
                    {installing ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Installing...
                      </>
                    ) : !isAuthenticated ? (
                      <>
                        <Download size={18} weight="bold" />
                        Sign Up to Install
                      </>
                    ) : item.is_active ? (
                      <>
                        <Download size={18} weight="bold" />
                        {item.pricing_type === 'free'
                          ? 'Install Extension'
                          : `Subscribe for $${item.price}/mo`}
                      </>
                    ) : (
                      'Coming Soon'
                    )}
                  </button>
                )}

                {/* Fork Button - for installed open-source agents */}
                {item.is_purchased &&
                  isAuthenticated &&
                  item.source_type === 'open' &&
                  item.is_forkable && (
                    <button
                      onClick={handleFork}
                      disabled={forking}
                      className={`
                    flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold transition-all
                    ${
                      theme === 'light'
                        ? 'bg-purple-500/10 hover:bg-purple-500/20 text-purple-600 border border-purple-500/20'
                        : 'bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 border border-purple-500/20'
                    }
                  `}
                    >
                      {forking ? (
                        <>
                          <div className="w-4 h-4 border-2 border-purple-400/30 border-t-purple-400 rounded-full animate-spin" />
                          Forking...
                        </>
                      ) : (
                        <>
                          <GitFork size={18} weight="bold" />
                          Fork &amp; Customize
                        </>
                      )}
                    </button>
                  )}

                {/* Price Badge */}
                {item.pricing_type === 'free' && (
                  <span
                    className={`text-sm font-medium ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                  >
                    Free
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Stats Bar */}
        <div className="max-w-5xl mx-auto px-6 md:px-12 mb-12">
          <StatsBar usageCount={item.usage_count || 0} category={item.category} />
        </div>

        {/* Content Sections */}
        <div className="max-w-5xl mx-auto px-6 md:px-12 pb-16">
          {/* Long Description */}
          {item.long_description && (
            <section className="mb-12">
              <h2
                className={`font-heading text-xl font-bold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                About
              </h2>
              <div
                className={`prose max-w-none ${theme === 'light' ? 'prose-gray' : 'prose-invert'}`}
              >
                <p
                  className={`text-base leading-relaxed ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
                >
                  {item.long_description}
                </p>
              </div>
            </section>
          )}

          {/* Features */}
          {item.features && item.features.length > 0 && (
            <section className="mb-12">
              <h2
                className={`font-heading text-xl font-bold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                Features
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {item.features.map((feature, idx) => (
                  <div key={idx} className="flex items-center gap-3">
                    <Check size={18} className="text-green-500 flex-shrink-0" weight="bold" />
                    <span
                      className={`text-sm ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
                    >
                      {feature}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Tools (for agents) */}
          {item.item_type === 'agent' && (
            <section className="mb-12">
              <h2
                className={`font-heading text-xl font-bold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                Available Tools
              </h2>
              <div className="flex flex-wrap gap-2">
                {(item.tools && item.tools.length > 0 ? item.tools : ALL_TOOLS).map(
                  (toolName, idx) => {
                    const tool = toolIcons[toolName];
                    if (!tool) return null;
                    return (
                      <div
                        key={idx}
                        className={`
                      flex items-center gap-2 px-3 py-2 rounded-lg text-sm
                      ${
                        theme === 'light'
                          ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                          : 'bg-[var(--primary)]/20 text-[var(--primary)]'
                      }
                    `}
                      >
                        {tool.icon}
                        <span className="font-medium">{tool.label}</span>
                      </div>
                    );
                  }
                )}
              </div>
            </section>
          )}

          {/* Tags */}
          {item.tags && item.tags.length > 0 && (
            <section className="mb-12">
              <h2
                className={`font-heading text-xl font-bold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                Tags
              </h2>
              <div className="flex flex-wrap gap-2">
                {item.tags.map((tag, idx) => (
                  <button
                    key={idx}
                    onClick={() => navigate(`/marketplace?search=${encodeURIComponent(tag)}`)}
                    className={`
                    px-3 py-1.5 rounded-lg text-sm transition-colors cursor-pointer
                    ${
                      theme === 'light'
                        ? 'bg-black/5 text-black/60 hover:bg-[var(--primary)]/10 hover:text-[var(--primary)]'
                        : 'bg-white/5 text-white/60 hover:bg-[var(--primary)]/20 hover:text-[var(--primary)]'
                    }
                  `}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Reviews Section (Agents and Bases) */}
          {(item.item_type === 'agent' || item.item_type === 'base') && (
            <section className="mb-12">
              <div className="flex items-center justify-between mb-6">
                <h2
                  className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                >
                  Reviews
                </h2>
                {item.is_purchased && !showReviewForm && (
                  <button
                    onClick={() => setShowReviewForm(true)}
                    className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                    ${
                      theme === 'light'
                        ? 'bg-black/5 hover:bg-black/10 text-black/70'
                        : 'bg-white/5 hover:bg-white/10 text-white/70'
                    }
                  `}
                  >
                    <ChatCircle size={16} weight="fill" />
                    {editingReview ? 'Edit Review' : 'Write a Review'}
                  </button>
                )}
              </div>

              {/* Review Form */}
              {showReviewForm && (
                <div
                  className={`
                p-6 rounded-xl mb-6
                ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
              `}
                >
                  <div className="flex items-center justify-between mb-4">
                    <h3
                      className={`font-semibold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                    >
                      {editingReview ? 'Edit Your Review' : 'Write a Review'}
                    </h3>
                    <button
                      onClick={() => setShowReviewForm(false)}
                      className={`p-1 rounded-lg transition-colors ${theme === 'light' ? 'hover:bg-black/10' : 'hover:bg-white/10'}`}
                    >
                      <X
                        size={18}
                        className={theme === 'light' ? 'text-black/50' : 'text-white/50'}
                      />
                    </button>
                  </div>

                  <div className="mb-4">
                    <label
                      className={`block text-sm font-medium mb-2 ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
                    >
                      Rating
                    </label>
                    <RatingPicker value={reviewRating} onChange={setReviewRating} />
                  </div>

                  <div className="mb-4">
                    <label
                      className={`block text-sm font-medium mb-2 ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
                    >
                      Comment (optional)
                    </label>
                    <textarea
                      value={reviewComment}
                      onChange={(e) => setReviewComment(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleSubmitReview();
                        }
                      }}
                      placeholder="Share your experience with this extension... (Press Enter to submit, Shift+Enter for new line)"
                      rows={4}
                      className={`
                      w-full px-4 py-3 rounded-lg text-sm resize-none
                      ${
                        theme === 'light'
                          ? 'bg-white border border-black/10 text-black placeholder:text-black/40'
                          : 'bg-white/5 border border-white/10 text-white placeholder:text-white/40'
                      }
                      focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/50
                    `}
                    />
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleSubmitReview}
                      disabled={submittingReview}
                      className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                    >
                      {submittingReview ? (
                        <>
                          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Submitting...
                        </>
                      ) : (
                        <>
                          <Check size={16} weight="bold" />
                          {editingReview ? 'Update Review' : 'Submit Review'}
                        </>
                      )}
                    </button>
                    {editingReview && (
                      <button
                        onClick={handleDeleteReview}
                        className={`
                        flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                        ${
                          theme === 'light'
                            ? 'bg-red-500/10 text-red-600 hover:bg-red-500/20'
                            : 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                        }
                      `}
                      >
                        <Trash size={16} weight="bold" />
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Reviews List */}
              {loadingReviews ? (
                <div
                  className={`text-center py-8 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                >
                  <div className="w-6 h-6 border-2 border-current border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                  Loading reviews...
                </div>
              ) : reviews.length > 0 ? (
                <div className="space-y-4">
                  {reviews.map((review) => (
                    <ReviewCard
                      key={review.id}
                      review={review}
                      onEdit={review.is_own_review ? () => setShowReviewForm(true) : undefined}
                      onDelete={review.is_own_review ? handleDeleteReview : undefined}
                    />
                  ))}
                </div>
              ) : (
                <div
                  className={`
                text-center py-12 rounded-xl
                ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
              `}
                >
                  <ChatCircle
                    size={40}
                    weight="duotone"
                    className={`mx-auto mb-3 ${theme === 'light' ? 'text-black/20' : 'text-white/20'}`}
                  />
                  <p className={`text-sm ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                    No reviews yet. {item.is_purchased && 'Be the first to review!'}
                  </p>
                </div>
              )}
            </section>
          )}

          {/* Related Items */}
          {relatedItems.length > 0 && (
            <section>
              <h2
                className={`font-heading text-xl font-bold mb-6 ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                People also like
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {relatedItems.map((relatedItem) => (
                  <AgentCard
                    key={relatedItem.id}
                    item={relatedItem}
                    onInstall={handleRelatedInstall}
                    isAuthenticated={isAuthenticated}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
