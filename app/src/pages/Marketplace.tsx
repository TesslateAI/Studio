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
        <div className="max-w-7xl mx-auto px-6 py-6">
          <div className="flex items-center justify-between mb-8">
            <h1 className="text-2xl font-bold text-[var(--text)]">Tesslate Marketplace</h1>
            <button
              onClick={() => navigate('/library')}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors text-sm"
            >
              Library
            </button>
          </div>

          {/* Main Title Section */}
          <div className="text-center mb-8">
            <h2 className="text-3xl font-bold text-[var(--text)] mb-2">
              Discover Free, Community-Made AI Tools!
            </h2>
          </div>

          {/* Search Bar */}
          <div className="relative mb-8 max-w-2xl mx-auto">
            <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text)]/40" size={20} />
            <input
              type="text"
              placeholder="Search agents by name, category, or tags..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-12 pr-4 py-3.5 bg-white/5 border border-white/10 rounded-xl text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-orange-500/50"
            />
          </div>

          {/* Filter Section */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-4">
              <FunnelSimple size={18} className="text-[var(--text)]/60" />
              <span className="text-sm font-medium text-[var(--text)]/80">Filter by</span>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {/* Agents Category */}
              <div className="text-sm font-medium text-[var(--text)]/80">Agents</div>

              {/* Category Pills */}
              {categories.map(category => (
                <button
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  className={`px-3 py-1.5 rounded-full text-sm transition-all ${
                    selectedCategory === category.id
                      ? 'bg-[#C0C0C0] text-black font-medium'
                      : 'bg-[#C0C0C0]/20 text-[var(--text)]/70 hover:bg-[#C0C0C0]/30'
                  }`}
                >
                  {category.name}
                </button>
              ))}

              {/* Source Type Pills */}
              <button
                onClick={() => setSelectedCreatorType(selectedCreatorType === 'open' ? 'all' : 'open')}
                className={`px-3 py-1.5 rounded-full text-sm transition-all ${
                  selectedCreatorType === 'open'
                    ? 'bg-[#C0C0C0] text-black font-medium'
                    : 'bg-[#C0C0C0]/20 text-[var(--text)]/70 hover:bg-[#C0C0C0]/30'
                }`}
              >
                Builder
              </button>
              <button
                onClick={() => setSelectedPricing(selectedPricing === 'free' ? 'all' : 'free')}
                className={`px-3 py-1.5 rounded-full text-sm transition-all ${
                  selectedPricing === 'free'
                    ? 'bg-[#C0C0C0] text-black font-medium'
                    : 'bg-[#C0C0C0]/20 text-[var(--text)]/70 hover:bg-[#C0C0C0]/30'
                }`}
              >
                Frontend
              </button>
              <button
                className="px-3 py-1.5 rounded-full text-sm bg-[#C0C0C0]/20 text-[var(--text)]/70 hover:bg-[#C0C0C0]/30 transition-all"
              >
                Data & AI
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Items Grid */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Featured Agents Section */}
        {filteredItems.filter(item => item.is_featured).length > 0 && (
          <div className="mb-12">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold text-[var(--text)]">Featured Agents</h3>
              <button className="text-sm text-[var(--text)]/60 hover:text-[var(--text)] flex items-center gap-1">
                View all
                <span>→</span>
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {filteredItems.filter(item => item.is_featured).slice(0, 4).map(item => (
                <ItemCard
                  key={item.id}
                  item={item}
                  onPurchase={() => handlePurchase(item)}
                  onFork={() => handleFork(item)}
                  onViewDetails={() => setShowItemDetail(item)}
                />
              ))}
            </div>
          </div>
        )}

        {/* Open Source Agents Section */}
        {filteredItems.filter(item => item.source_type === 'open').length > 0 && (
          <div className="mb-12">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold text-[var(--text)]">Open Source Agents</h3>
              <button className="text-sm text-[var(--text)]/60 hover:text-[var(--text)] flex items-center gap-1">
                View all
                <span>→</span>
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {filteredItems.filter(item => item.source_type === 'open' && !item.is_featured).slice(0, 4).map(item => (
                <ItemCard
                  key={item.id}
                  item={item}
                  onPurchase={() => handlePurchase(item)}
                  onFork={() => handleFork(item)}
                  onViewDetails={() => setShowItemDetail(item)}
                />
              ))}
            </div>
          </div>
        )}

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
    <div className={`bg-[var(--surface)] rounded-xl p-5 border transition-all group relative ${
      item.is_active
        ? 'border-white/10 hover:border-orange-500/30 hover:shadow-lg'
        : 'border-white/5 opacity-60'
    }`}>
      {/* Badge - Top Right Corner */}
      <div className="absolute top-3 right-3">
        {item.source_type === 'open' ? (
          <span className="px-2.5 py-1 bg-white/10 text-white text-xs rounded-md font-medium">
            Open Source
          </span>
        ) : (
          <span className="px-2.5 py-1 bg-white/5 text-white/60 text-xs rounded-md font-medium">
            Closed Source
          </span>
        )}
      </div>

      {/* Icon - Large, centered placeholder */}
      <div className="w-full h-32 bg-[#808080] rounded-lg mb-4 flex items-center justify-center">
        <div className="text-5xl opacity-50">{item.icon}</div>
      </div>

      {/* Agent Name */}
      <h3 className="font-bold text-[var(--text)] mb-2 text-lg group-hover:text-orange-400 transition-colors pr-20">
        {item.name}
      </h3>

      {/* Description */}
      <p className="text-sm text-[var(--text)]/70 mb-4 line-clamp-2 min-h-[40px]">
        {item.description}
      </p>

      {/* Tags */}
      <div className="flex flex-wrap gap-2 mb-4">
        {item.tags?.slice(0, 3).map((tag, idx) => (
          <span
            key={idx}
            className="px-2 py-0.5 bg-white/5 rounded text-xs text-[var(--text)]/60"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Bottom Section */}
      <div className="flex items-center justify-between pt-4 border-t border-white/10">
        {/* Price/Type */}
        <div className="text-sm font-semibold text-[var(--text)]">
          {item.pricing_type === 'free' ? 'Price' : `$${item.price}`}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <button
            onClick={onViewDetails}
            className="px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-md text-xs text-[var(--text)]/80 transition-colors"
          >
            View Details
          </button>
          {item.is_purchased ? (
            <button
              disabled
              className="px-3 py-1.5 bg-green-500/20 text-green-400 rounded-md text-xs flex items-center gap-1.5"
            >
              <Check size={14} weight="bold" />
              Installed
            </button>
          ) : (
            <button
              onClick={onPurchase}
              disabled={!item.is_active}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                item.is_active
                  ? 'bg-white/90 hover:bg-white text-black'
                  : 'bg-white/5 text-[var(--text)]/40 cursor-not-allowed'
              }`}
            >
              {item.is_active ? 'Install' : 'Soon'}
            </button>
          )}
        </div>
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