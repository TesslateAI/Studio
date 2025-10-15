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
  X
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';

interface MarketplaceAgent {
  id: number;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  category: string;
  mode: string;
  icon: string;
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  reviews_count: number;
  features: string[];
  tags: string[];
  is_featured: boolean;
  is_purchased: boolean;
}

export default function Marketplace() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<MarketplaceAgent[]>([]);
  const [filteredAgents, setFilteredAgents] = useState<MarketplaceAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedPricing, setSelectedPricing] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<string>('featured');
  const [showAgentDetail, setShowAgentDetail] = useState<MarketplaceAgent | null>(null);

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
    loadMarketplaceAgents();
  }, []);

  useEffect(() => {
    filterAgents();
  }, [agents, selectedCategory, selectedPricing, searchQuery, sortBy]);

  const loadMarketplaceAgents = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/marketplace/agents', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        throw new Error('Failed to load marketplace');
      }

      const data = await response.json();
      setAgents(data.agents);
    } catch (error) {
      console.error('Failed to load marketplace:', error);
      toast.error('Failed to load marketplace');
    } finally {
      setLoading(false);
    }
  };

  const filterAgents = () => {
    let filtered = [...agents];

    // Category filter
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(agent => agent.category === selectedCategory);
    }

    // Pricing filter
    if (selectedPricing !== 'all') {
      filtered = filtered.filter(agent => agent.pricing_type === selectedPricing);
    }

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(agent =>
        agent.name.toLowerCase().includes(query) ||
        agent.description.toLowerCase().includes(query) ||
        agent.tags.some(tag => tag.toLowerCase().includes(query))
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

    setFilteredAgents(filtered);
  };

  const handlePurchase = async (agent: MarketplaceAgent) => {
    if (agent.is_purchased) {
      toast.success('Agent already in your library');
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/marketplace/agents/${agent.id}/purchase`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error('Failed to purchase agent');
      }

      const data = await response.json();

      if (data.checkout_url) {
        // Redirect to Stripe checkout for paid agents
        window.location.href = data.checkout_url;
      } else {
        // Free agent added successfully
        toast.success(`${agent.name} added to your library!`);

        // Update local state
        setAgents(prev => prev.map(a =>
          a.id === agent.id ? { ...a, is_purchased: true } : a
        ));
      }
    } catch (error) {
      console.error('Failed to purchase agent:', error);
      toast.error('Failed to purchase agent');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 mx-auto mb-4 border-2 border-orange-500 border-t-transparent rounded-full" />
          <p className="text-[var(--text)]/60">Loading marketplace...</p>
        </div>
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
              <h1 className="text-3xl font-bold text-[var(--text)] mb-2">Agent Marketplace</h1>
              <p className="text-[var(--text)]/60">Discover and add powerful AI agents to enhance your projects</p>
            </div>
            <button
              onClick={() => navigate('/dashboard')}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
            >
              Back to Dashboard
            </button>
          </div>

          {/* Search Bar */}
          <div className="relative mb-6">
            <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text)]/40" size={20} />
            <input
              type="text"
              placeholder="Search agents by name, category, or tags..."
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
              {filteredAgents.length} agents found
            </div>
          </div>
        </div>
      </div>

      {/* Agent Grid */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredAgents.map(agent => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onPurchase={() => handlePurchase(agent)}
              onViewDetails={() => setShowAgentDetail(agent)}
            />
          ))}
        </div>

        {filteredAgents.length === 0 && (
          <div className="text-center py-16">
            <Package size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
            <p className="text-[var(--text)]/60">No agents found matching your criteria</p>
          </div>
        )}
      </div>

      {/* Agent Detail Modal */}
      {showAgentDetail && (
        <AgentDetailModal
          agent={showAgentDetail}
          onClose={() => setShowAgentDetail(null)}
          onPurchase={() => {
            handlePurchase(showAgentDetail);
            setShowAgentDetail(null);
          }}
        />
      )}
    </div>
  );
}

// Agent Card Component
function AgentCard({ agent, onPurchase, onViewDetails }: {
  agent: MarketplaceAgent;
  onPurchase: () => void;
  onViewDetails: () => void;
}) {
  return (
    <div className="bg-[var(--surface)] rounded-xl p-6 border border-white/10 hover:border-orange-500/30 transition-all group">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="text-3xl">{agent.icon}</div>
          <div>
            <h3 className="font-semibold text-[var(--text)] group-hover:text-orange-400 transition-colors">
              {agent.name}
            </h3>
            <span className="text-xs text-[var(--text)]/60 capitalize">{agent.category}</span>
          </div>
        </div>
        {agent.is_featured && (
          <span className="px-2 py-1 bg-orange-500/20 text-orange-400 text-xs rounded-full">
            Featured
          </span>
        )}
      </div>

      {/* Description */}
      <p className="text-sm text-[var(--text)]/80 mb-4 line-clamp-2">{agent.description}</p>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mb-4">
        {agent.features.slice(0, 3).map((feature, idx) => (
          <span
            key={idx}
            className="px-2 py-1 bg-white/5 rounded-lg text-xs text-[var(--text)]/70"
          >
            {feature}
          </span>
        ))}
        {agent.features.length > 3 && (
          <span className="px-2 py-1 text-xs text-[var(--text)]/50">
            +{agent.features.length - 3} more
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 mb-4 text-xs text-[var(--text)]/60">
        <span className="flex items-center gap-1">
          <Download size={12} />
          {agent.downloads}
        </span>
        <span className="flex items-center gap-1">
          <Star size={12} weight="fill" className="text-yellow-500" />
          {agent.rating} ({agent.reviews_count})
        </span>
        <span className="ml-auto capitalize">{agent.mode} mode</span>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={onViewDetails}
          className="flex-1 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm text-[var(--text)]/80 transition-colors"
        >
          View Details
        </button>
        {agent.is_purchased ? (
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
            className="flex-1 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
          >
            <ShoppingCart size={16} />
            {agent.pricing_type === 'free' ? 'Add Free' : `$${agent.price}/mo`}
          </button>
        )}
      </div>
    </div>
  );
}

// Agent Detail Modal
function AgentDetailModal({ agent, onClose, onPurchase }: {
  agent: MarketplaceAgent;
  onClose: () => void;
  onPurchase: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
      <div className="bg-[var(--surface)] rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-orange-500/20 to-purple-500/20 p-8 border-b border-white/10">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className="text-5xl">{agent.icon}</div>
              <div>
                <h2 className="text-2xl font-bold text-[var(--text)] mb-1">{agent.name}</h2>
                <p className="text-[var(--text)]/80">{agent.description}</p>
                <div className="flex items-center gap-4 mt-3 text-sm text-[var(--text)]/60">
                  <span className="capitalize">{agent.category}</span>
                  <span>•</span>
                  <span className="capitalize">{agent.mode} mode</span>
                  <span>•</span>
                  <span className="flex items-center gap-1">
                    <Star size={14} weight="fill" className="text-yellow-500" />
                    {agent.rating} ({agent.reviews_count} reviews)
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
          {agent.long_description && (
            <div className="mb-8">
              <h3 className="font-semibold text-[var(--text)] mb-3">About this Agent</h3>
              <p className="text-[var(--text)]/80 whitespace-pre-line">{agent.long_description}</p>
            </div>
          )}

          {/* Features */}
          <div className="mb-8">
            <h3 className="font-semibold text-[var(--text)] mb-4">Features</h3>
            <div className="grid grid-cols-2 gap-3">
              {agent.features.map((feature, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <Check size={16} className="text-green-500" weight="bold" />
                  <span className="text-sm text-[var(--text)]/80">{feature}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Tags */}
          {agent.tags.length > 0 && (
            <div className="mb-8">
              <h3 className="font-semibold text-[var(--text)] mb-3">Tags</h3>
              <div className="flex flex-wrap gap-2">
                {agent.tags.map((tag, idx) => (
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
              {agent.pricing_type === 'free' ? 'Free Agent' : 'Subscription'}
            </div>
            {agent.pricing_type !== 'free' && (
              <div className="text-2xl font-bold text-[var(--text)]">
                ${agent.price}<span className="text-sm font-normal text-[var(--text)]/60">/month</span>
              </div>
            )}
          </div>

          {agent.is_purchased ? (
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
              className="px-8 py-3 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-medium transition-colors flex items-center gap-2"
            >
              <ShoppingCart size={20} />
              {agent.pricing_type === 'free' ? 'Add to Library' : `Subscribe for $${agent.price}/mo`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}