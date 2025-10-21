import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MagnifyingGlass,
  FunnelSimple,
  Star,
  Download,
  Check,
  ShoppingCart,
  Lightning,
  Rocket,
  Palette,
  Code,
  Sparkle,
  Package,
  X,
  GitFork,
  LockKey,
  Cpu,
  Wrench,
  Plug,
  LockSimpleOpen,
  User,
  Users,
  Globe
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';

interface MarketplaceItem {
  id: number;
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
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  reviews_count: number;
  usage_count: number;
  features: string[];
  tags: string[];
  is_featured: boolean;
  is_purchased: boolean;
  creator_type?: 'official' | 'community';
  creator_name?: string;
}

export default function Marketplace() {
  const navigate = useNavigate();
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItemType, setSelectedItemType] = useState<string>('agent');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedPricing, setSelectedPricing] = useState<string>('all');
  const [selectedCreatorType, setSelectedCreatorType] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<string>('featured');
  const [showItemDetail, setShowItemDetail] = useState<MarketplaceItem | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showForkModal, setShowForkModal] = useState<MarketplaceItem | null>(null);

  const itemTypes = [
    { id: 'agent', name: 'Agents', icon: <Cpu size={18} /> },
    { id: 'base', name: 'Bases', icon: <Package size={18} /> },
    { id: 'tool', name: 'Tools', icon: <Wrench size={18} /> },
    { id: 'integration', name: 'Integrations', icon: <Plug size={18} /> }
  ];

  const categories = [
    { id: 'all', name: 'All Agents', icon: <Sparkle size={16} /> },
    { id: 'builder', name: 'Builder', icon: <Rocket size={16} /> },
    { id: 'frontend', name: 'Frontend', icon: <Palette size={16} /> },
    { id: 'fullstack', name: 'Full Stack', icon: <Code size={16} /> },
    { id: 'data', name: 'Data & AI', icon: <Lightning size={16} /> }
  ];

  const pricingOptions = [
    { id: 'all', name: 'All Pricing' },
    { id: 'free', name: 'Free' },
    { id: 'monthly', name: 'Subscription' },
    { id: 'one_time', name: 'One-time' }
  ];

  useEffect(() => {
    loadMarketplaceItems();
  }, []);

  useEffect(() => {
    filterItems();
  }, [items, selectedItemType, selectedCategory, selectedPricing, selectedCreatorType, searchQuery, sortBy]);

  const loadMarketplaceItems = async () => {
    try {
      // Load both agents and bases
      const [agentsData, basesData] = await Promise.all([
        marketplaceApi.getAllAgents(),
        marketplaceApi.getAllBases()
      ]);

      const agents = (agentsData.agents || []).map((agent: any) => ({
        ...agent,
        item_type: 'agent'
      }));

      const bases = (basesData.bases || []).map((base: any) => ({
        ...base,
        item_type: 'base',
        mode: 'base', // Compatibility
        creator_type: 'official' // All bases are official for now
      }));

      // Combine both into a single items array
      setItems([...agents, ...bases]);
    } catch (error) {
      console.error('Failed to load marketplace:', error);
      toast.error('Failed to load marketplace');
    } finally {
      setLoading(false);
    }
  };

  const filterItems = () => {
    let filtered = [...items];

    // Item type filter
    filtered = filtered.filter(item => item.item_type === selectedItemType);

    // Category filter
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(item => item.category === selectedCategory);
    }

    // Pricing filter
    if (selectedPricing !== 'all') {
      filtered = filtered.filter(item => item.pricing_type === selectedPricing);
    }

    // Creator type filter
    if (selectedCreatorType !== 'all') {
      filtered = filtered.filter(item => item.creator_type === selectedCreatorType);
    }

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(item =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    // Sort
    switch (sortBy) {
      case 'featured':
        filtered.sort((a, b) => {
          if (a.is_featured === b.is_featured) {
            return b.downloads - a.downloads;
          }
          return a.is_featured ? -1 : 1;
        });
        break;
      case 'popular':
        filtered.sort((a, b) => b.downloads - a.downloads);
        break;
      case 'rating':
        filtered.sort((a, b) => b.rating - a.rating);
        break;
      case 'price_asc':
        filtered.sort((a, b) => a.price - b.price);
        break;
      case 'price_desc':
        filtered.sort((a, b) => b.price - a.price);
        break;
    }

    setFilteredItems(filtered);
  };

  const handlePurchase = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      toast.info('Coming soon!');
      return;
    }

    try {
      // Call appropriate API based on item type
      const data = item.item_type === 'base'
        ? await marketplaceApi.purchaseBase(item.id)
        : await marketplaceApi.purchaseAgent(item.id);

      if (data.checkout_url) {
        // Redirect to Stripe checkout for paid items
        window.location.href = data.checkout_url;
      } else {
        // Free item added successfully
        if (item.item_type === 'base') {
          toast.success(`${item.name} added to your library! Create a project to use it.`, {
            duration: 4000
          });
          // Redirect to dashboard after a moment
          setTimeout(() => navigate('/dashboard'), 2000);
        } else {
          toast.success(`${item.name} added to your library!`);
        }

        // Update local state
        setItems(prev => prev.map(i =>
          i.id === item.id ? { ...i, is_purchased: true } : i
        ));
      }
    } catch (error) {
      console.error('Failed to purchase:', error);
      toast.error('Failed to add to library');
    }
  };

  const handleFork = async (item: MarketplaceItem) => {
    if (!item.is_forkable) {
      toast.error('This agent cannot be forked');
      return;
    }

    setShowForkModal(item);
  };

  const submitFork = async (item: MarketplaceItem, customizations?: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
  }) => {
    try {
      const response = await marketplaceApi.forkAgent(item.id, customizations);
      toast.success('Agent forked successfully! Check your library.');
      setShowForkModal(null);
      loadMarketplaceItems(); // Reload to show the forked agent
    } catch (error: any) {
      console.error('Fork failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to fork agent');
    }
  };

  const handleCreateAgent = async (data: {
    name: string;
    description: string;
    system_prompt: string;
    mode: string;
    agent_type: string;
    model: string;
  }) => {
    try {
      const response = await marketplaceApi.createCustomAgent(data);
      toast.success('Custom agent created successfully!');
      setShowCreateModal(false);
      loadMarketplaceItems(); // Reload to show the new agent
    } catch (error: any) {
      console.error('Create failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to create agent');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <LoadingSpinner message="Loading marketplace..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Header */}
      <div className="border-b border-white/10 bg-[var(--surface)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-3xl font-bold text-[var(--text)] mb-2">Marketplace</h1>
              <p className="text-[var(--text)]/60">Discover agents, bases, tools, and integrations for your projects</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate('/library')}
                className="px-4 py-2 bg-purple-500 hover:bg-purple-600 rounded-lg text-white transition-colors flex items-center gap-2"
              >
                <Package size={18} />
                My Library
              </button>
              <button
                onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
              >
                <Sparkle size={18} />
                Create Agent
              </button>
              <button
                onClick={() => navigate('/dashboard')}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              >
                Back to Dashboard
              </button>
            </div>
          </div>

          {/* Item Type Tabs */}
          <div className="flex items-center gap-2 mb-6 p-1 bg-white/5 rounded-lg overflow-x-auto">
            {itemTypes.map(type => (
              <button
                key={type.id}
                onClick={() => {
                  setSelectedItemType(type.id);
                  setSelectedCategory('all'); // Reset category when changing type
                }}
                className={`flex items-center gap-2 px-6 py-3 rounded-lg transition-all whitespace-nowrap ${
                  selectedItemType === type.id
                    ? 'bg-orange-500 text-white'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)]'
                }`}
              >
                {type.icon}
                <span className="font-medium">{type.name}</span>
              </button>
            ))}
          </div>

          {/* Search Bar */}
          <div className="relative mb-6">
            <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text)]/40" size={20} />
            <input
              type="text"
              placeholder={`Search ${itemTypes.find(t => t.id === selectedItemType)?.name.toLowerCase()} by name, category, or tags...`}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-12 pr-4 py-3 bg-white/5 border border-white/10 rounded-xl text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-orange-500/50"
            />
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-4">
            {/* Category Tabs */}
            <div className="flex items-center gap-2 p-1 bg-white/5 rounded-lg">
              {categories.map(category => (
                <button
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                    selectedCategory === category.id
                      ? 'bg-orange-500 text-white'
                      : 'text-[var(--text)]/60 hover:text-[var(--text)]'
                  }`}
                >
                  {category.icon}
                  <span className="text-sm font-medium">{category.name}</span>
                </button>
              ))}
            </div>

            {/* Creator Type Filter */}
            <div className="flex items-center gap-2 p-1 bg-white/5 rounded-lg">
              <button
                onClick={() => setSelectedCreatorType('all')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                  selectedCreatorType === 'all'
                    ? 'bg-orange-500 text-white'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)]'
                }`}
              >
                <Globe size={16} />
                <span className="text-sm font-medium">All</span>
              </button>
              <button
                onClick={() => setSelectedCreatorType('official')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                  selectedCreatorType === 'official'
                    ? 'bg-orange-500 text-white'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)]'
                }`}
              >
                <Sparkle size={16} />
                <span className="text-sm font-medium">Official</span>
              </button>
              <button
                onClick={() => setSelectedCreatorType('community')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                  selectedCreatorType === 'community'
                    ? 'bg-orange-500 text-white'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)]'
                }`}
              >
                <Users size={16} />
                <span className="text-sm font-medium">Community</span>
              </button>
            </div>

            {/* Pricing Filter */}
            <select
              value={selectedPricing}
              onChange={(e) => setSelectedPricing(e.target.value)}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
            >
              {pricingOptions.map(option => (
                <option key={option.id} value={option.id}>{option.name}</option>
              ))}
            </select>

            {/* Sort */}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
            >
              <option value="featured">Featured</option>
              <option value="popular">Most Popular</option>
              <option value="rating">Highest Rated</option>
              <option value="price_asc">Price: Low to High</option>
              <option value="price_desc">Price: High to Low</option>
            </select>

            <div className="ml-auto text-sm text-[var(--text)]/60">
              {filteredItems.length} {filteredItems.length === 1 ? 'item' : 'items'} found
            </div>
          </div>
        </div>
      </div>

      {/* Items Grid */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredItems.map(item => (
            <ItemCard
              key={item.id}
              item={item}
              onPurchase={() => handlePurchase(item)}
              onFork={() => handleFork(item)}
              onViewDetails={() => setShowItemDetail(item)}
            />
          ))}
        </div>

        {filteredItems.length === 0 && (
          <div className="text-center py-16">
            <Package size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
            <p className="text-[var(--text)]/60">No items found matching your criteria</p>
          </div>
        )}
      </div>

      {/* Item Detail Modal */}
      {showItemDetail && (
        <ItemDetailModal
          item={showItemDetail}
          onClose={() => setShowItemDetail(null)}
          onPurchase={() => {
            handlePurchase(showItemDetail);
            setShowItemDetail(null);
          }}
          onFork={() => {
            handleFork(showItemDetail);
          }}
        />
      )}

      {/* Fork Agent Modal */}
      {showForkModal && (
        <ForkAgentModal
          agent={showForkModal}
          onClose={() => setShowForkModal(null)}
          onSubmit={(customizations) => submitFork(showForkModal, customizations)}
        />
      )}

      {/* Create Agent Modal */}
      {showCreateModal && (
        <CreateAgentModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateAgent}
        />
      )}
    </div>
  );
}

// Item Card Component
function ItemCard({ item, onPurchase, onFork, onViewDetails }: {
  item: MarketplaceItem;
  onPurchase: () => void;
  onFork: () => void;
  onViewDetails: () => void;
}) {
  return (
    <div className={`bg-[var(--surface)] rounded-xl p-6 border transition-all group ${
      item.is_active
        ? 'border-white/10 hover:border-orange-500/30'
        : 'border-white/5 opacity-60'
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="text-3xl">{item.icon}</div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h3 className="font-semibold text-[var(--text)] group-hover:text-orange-400 transition-colors">
                {item.name}
              </h3>
              {!item.is_active && (
                <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded">
                  Coming Soon
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 text-xs text-[var(--text)]/60">
                <svg width="12" height="12" viewBox="0 0 162 127" fill="currentColor" className="text-orange-500">
                  <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z"/>
                  <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z"/>
                  <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z"/>
                </svg>
                <span className="capitalize">{item.category}</span>
                <span className="text-[var(--text)]/40">by {item.creator_name || 'Tesslate'}</span>
              </span>
              {item.source_type === 'open' ? (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">
                  <LockSimpleOpen size={10} />
                  Open Source
                </span>
              ) : (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">
                  <LockKey size={10} />
                  Pro
                </span>
              )}
            </div>
          </div>
        </div>
        {item.is_featured && (
          <span className="px-2 py-1 bg-orange-500/20 text-orange-400 text-xs rounded-full">
            Featured
          </span>
        )}
      </div>

      {/* Model Badge (for agents only) */}
      {item.item_type === 'agent' && item.model && (
        <div className="mb-3 flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 border border-blue-500/20 rounded-lg">
          <Cpu size={14} className="text-blue-400" />
          <span className="text-xs text-blue-400 font-medium">{item.model.replace('cerebras/', '')}</span>
        </div>
      )}

      {/* Description */}
      <p className="text-sm text-[var(--text)]/80 mb-4 line-clamp-2">{item.description}</p>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mb-4">
        {item.features?.slice(0, 3).map((feature, idx) => (
          <span
            key={idx}
            className="px-2 py-1 bg-white/5 rounded-lg text-xs text-[var(--text)]/70"
          >
            {feature}
          </span>
        ))}
        {item.features?.length > 3 && (
          <span className="px-2 py-1 text-xs text-[var(--text)]/50">
            +{item.features.length - 3} more
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 mb-4 text-xs text-[var(--text)]/60">
        <span className="flex items-center gap-1">
          <Lightning size={12} weight="fill" className="text-orange-400" />
          {item.usage_count || 0} uses
        </span>
        {item.item_type === 'agent' && item.mode && (
          <span className="ml-auto capitalize">{item.mode} mode</span>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={onViewDetails}
          className="flex-1 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm text-[var(--text)]/80 transition-colors"
        >
          View Details
        </button>
        {item.is_purchased ? (
          <button
            disabled
            className="flex-1 py-2 bg-green-500/20 text-green-400 rounded-lg text-sm flex items-center justify-center gap-2"
          >
            <Check size={16} weight="bold" />
            In Library
          </button>
        ) : (
          <button
            onClick={onPurchase}
            disabled={!item.is_active}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
              item.is_active
                ? 'bg-orange-500 hover:bg-orange-600 text-white'
                : 'bg-white/5 text-[var(--text)]/40 cursor-not-allowed'
            }`}
          >
            <ShoppingCart size={16} />
            {item.is_active
              ? (item.pricing_type === 'free' ? 'Add Free' : `$${item.price}/mo`)
              : 'Soon'
            }
          </button>
        )}
        {item.is_forkable && item.is_active && (
          <button
            onClick={onFork}
            className="py-2 px-3 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400 rounded-lg text-sm transition-colors flex items-center gap-2"
            title="Fork and customize this agent"
          >
            <GitFork size={16} />
          </button>
        )}
      </div>
    </div>
  );
}

// Item Detail Modal
function ItemDetailModal({ item, onClose, onPurchase, onFork }: {
  item: MarketplaceItem;
  onClose: () => void;
  onPurchase: () => void;
  onFork: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={onClose}>
      <div className="bg-[var(--surface)] rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="bg-gradient-to-r from-orange-500/20 to-purple-500/20 p-8 border-b border-white/10">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className="text-5xl">{item.icon}</div>
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <h2 className="text-2xl font-bold text-[var(--text)]">{item.name}</h2>
                  {!item.is_active && (
                    <span className="px-3 py-1 bg-blue-500/20 text-blue-400 text-sm rounded">
                      Coming Soon
                    </span>
                  )}
                  {item.source_type === 'open' ? (
                    <span className="flex items-center gap-1.5 px-3 py-1 bg-green-500/20 text-green-400 text-sm rounded">
                      <LockSimpleOpen size={14} />
                      Open Source
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5 px-3 py-1 bg-purple-500/20 text-purple-400 text-sm rounded">
                      <LockKey size={14} />
                      Pro
                    </span>
                  )}
                </div>
                <p className="text-[var(--text)]/80 mb-3">{item.description}</p>
                <div className="flex items-center gap-4 text-sm text-[var(--text)]/60 flex-wrap">
                  <span className="capitalize">{item.category}</span>
                  {item.item_type === 'agent' && item.mode && (
                    <>
                      <span>•</span>
                      <span className="capitalize">{item.mode} mode</span>
                    </>
                  )}
                  {item.item_type === 'agent' && item.model && (
                    <>
                      <span>•</span>
                      <span className="flex items-center gap-1.5 px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                        <Cpu size={12} />
                        {item.model.replace('cerebras/', '')}
                      </span>
                    </>
                  )}
                  <span>•</span>
                  <span className="flex items-center gap-1">
                    <Lightning size={14} weight="fill" className="text-orange-400" />
                    {item.usage_count || 0} uses
                  </span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-8 overflow-y-auto max-h-[60vh]">
          {/* Long Description */}
          {item.long_description && (
            <div className="mb-8">
              <h3 className="font-semibold text-[var(--text)] mb-3">
                About this {item.item_type === 'agent' ? 'Agent' : item.item_type === 'base' ? 'Base' : item.item_type === 'tool' ? 'Tool' : 'Integration'}
              </h3>
              <p className="text-[var(--text)]/80 whitespace-pre-line">{item.long_description}</p>
            </div>
          )}

          {/* Features */}
          {item.features && item.features.length > 0 && (
            <div className="mb-8">
              <h3 className="font-semibold text-[var(--text)] mb-4">Features</h3>
              <div className="grid grid-cols-2 gap-3">
                {item.features.map((feature, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <Check size={16} className="text-green-500" weight="bold" />
                    <span className="text-sm text-[var(--text)]/80">{feature}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          {item.tags && item.tags.length > 0 && (
            <div className="mb-8">
              <h3 className="font-semibold text-[var(--text)] mb-3">Tags</h3>
              <div className="flex flex-wrap gap-2">
                {item.tags.map((tag, idx) => (
                  <span
                    key={idx}
                    className="px-3 py-1 bg-white/5 rounded-full text-sm text-[var(--text)]/70"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-8 border-t border-white/10 flex items-center justify-between">
          <div>
            <div className="text-sm text-[var(--text)]/60 mb-1">
              {item.pricing_type === 'free' ? `Free ${item.item_type}` : 'Subscription'}
            </div>
            {item.pricing_type !== 'free' && (
              <div className="text-2xl font-bold text-[var(--text)]">
                ${item.price}<span className="text-sm font-normal text-[var(--text)]/60">/month</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {item.is_forkable && item.is_active && !item.is_purchased && (
              <button
                onClick={onFork}
                className="px-6 py-3 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400 rounded-lg font-medium transition-colors flex items-center gap-2"
              >
                <GitFork size={20} />
                Fork Agent
              </button>
            )}
            {item.is_purchased ? (
              <button
                disabled
                className="px-8 py-3 bg-green-500/20 text-green-400 rounded-lg font-medium flex items-center gap-2"
              >
                <Check size={20} weight="bold" />
                Already in Library
              </button>
            ) : (
              <button
                onClick={onPurchase}
                disabled={!item.is_active}
                className={`px-8 py-3 rounded-lg font-medium transition-colors flex items-center gap-2 ${
                  item.is_active
                    ? 'bg-orange-500 hover:bg-orange-600 text-white'
                    : 'bg-white/5 text-[var(--text)]/40 cursor-not-allowed'
                }`}
              >
                <ShoppingCart size={20} />
                {item.is_active
                  ? (item.pricing_type === 'free' ? 'Add to Library' : `Subscribe for $${item.price}/mo`)
                  : 'Coming Soon'
                }
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Fork Agent Modal Component
function ForkAgentModal({
  agent,
  onClose,
  onSubmit
}: {
  agent: MarketplaceItem;
  onClose: () => void;
  onSubmit: (customizations: any) => void;
}) {
  const [name, setName] = useState(`${agent.name} (My Fork)`);
  const [description, setDescription] = useState(agent.description);
  const [systemPrompt, setSystemPrompt] = useState('');
  const [model, setModel] = useState(agent.model || 'cerebras/qwen-3-coder-480b');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch the full agent details including system prompt
    const fetchDetails = async () => {
      try {
        const details = await marketplaceApi.getAgentDetails(agent.slug);
        setSystemPrompt(details.system_prompt || '');
      } catch (error) {
        console.error('Failed to load agent details:', error);
        toast.error('Failed to load agent details');
      } finally {
        setLoading(false);
      }
    };
    fetchDetails();
  }, [agent.slug]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      description,
      system_prompt: systemPrompt,
      model
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-4xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <GitFork size={24} />
            Fork & Customize Agent
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors"
          >
            <X size={20} className="text-[var(--text)]/60" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <LoadingSpinner message="Loading agent details..." size={40} />
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg mb-6">
              <p className="text-sm text-blue-400">
                <Check size={16} className="inline mr-2" />
                Forking <strong>{agent.name}</strong> - Customize it before adding to your library
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Agent Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Description
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Model
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              >
                <option value="cerebras/qwen-3-coder-480b">Cerebras Qwen 3 Coder (480B)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                System Prompt
              </label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={12}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm resize-y"
                required
              />
              <p className="mt-1 text-xs text-[var(--text)]/40">
                Customize the system prompt to change how your agent behaves
              </p>
            </div>

            <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-6 py-2 bg-green-500 hover:bg-green-600 rounded-lg text-white transition-colors flex items-center gap-2"
              >
                <GitFork size={18} />
                Fork Agent
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// Create Agent Modal Component
function CreateAgentModal({
  onClose,
  onSubmit
}: {
  onClose: () => void;
  onSubmit: (data: any) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [agentType, setAgentType] = useState('StreamAgent');
  const [model, setModel] = useState('cerebras/qwen-3-coder-480b');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!name || !description || !systemPrompt) {
      toast.error('Please fill in all required fields');
      return;
    }

    // Derive mode from agent type
    const mode = agentType === 'StreamAgent' ? 'stream' : 'agent';

    onSubmit({
      name,
      description,
      system_prompt: systemPrompt,
      mode,
      agent_type: agentType,
      model
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Sparkle size={24} />
            Create Custom Agent
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors"
          >
            <X size={20} className="text-[var(--text)]/60" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Agent Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Custom Agent"
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Description <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of what your agent does"
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              System Prompt <span className="text-red-400">*</span>
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Enter the system prompt that defines your agent's behavior and capabilities..."
              rows={8}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-orange-500/50 font-mono text-sm resize-y"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              This prompt defines how your agent behaves and responds
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Agent Type
              </label>
              <select
                value={agentType}
                onChange={(e) => setAgentType(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              >
                <option value="StreamAgent">Stream Agent</option>
                <option value="IterativeAgent">Iterative Agent</option>
              </select>
              <p className="mt-1 text-xs text-[var(--text)]/40">
                Stream agents generate code in real-time, Iterative agents use tools
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Model
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              >
                <option value="cerebras/qwen-3-coder-480b">Cerebras Qwen 3 Coder (480B)</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
            >
              <Sparkle size={18} />
              Create Agent
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}