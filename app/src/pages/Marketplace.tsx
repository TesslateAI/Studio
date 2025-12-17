import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MagnifyingGlass,
  Cpu,
  Package,
  Wrench,
  Plug,
  CaretDown,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  Command
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileMenu } from '../components/ui';
import { AgentCard, FeaturedCard, MarketplaceItem } from '../components/marketplace';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';

type ItemType = 'agent' | 'base' | 'tool' | 'integration';
type SortOption = 'featured' | 'popular' | 'newest' | 'name';

export default function Marketplace() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItemType, setSelectedItemType] = useState<ItemType>('agent');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('featured');
  const [showSortDropdown, setShowSortDropdown] = useState(false);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Mobile menu items
  const mobileMenuItems = {
    left: [
      { icon: <Folder className="w-5 h-5" weight="fill" />, title: 'Projects', onClick: () => navigate('/dashboard') },
      { icon: <Storefront className="w-5 h-5" weight="fill" />, title: 'Marketplace', onClick: () => {}, active: true },
      { icon: <Books className="w-5 h-5" weight="fill" />, title: 'Library', onClick: () => navigate('/library') },
      { icon: <Package className="w-5 h-5" weight="fill" />, title: 'Components', onClick: () => toast('Components library coming soon!') }
    ],
    right: [
      { icon: theme === 'dark' ? <Sun className="w-5 h-5" weight="fill" /> : <Moon className="w-5 h-5" weight="fill" />, title: theme === 'dark' ? 'Light Mode' : 'Dark Mode', onClick: toggleTheme },
      { icon: <Gear className="w-5 h-5" weight="fill" />, title: 'Settings', onClick: () => navigate('/settings') },
      { icon: <SignOut className="w-5 h-5" weight="fill" />, title: 'Logout', onClick: logout }
    ]
  };

  const itemTypes: { id: ItemType; label: string; icon: React.ReactNode }[] = [
    { id: 'agent', label: 'Agents', icon: <Cpu size={16} /> },
    { id: 'base', label: 'Bases', icon: <Package size={16} /> },
    { id: 'tool', label: 'Tools', icon: <Wrench size={16} /> },
    { id: 'integration', label: 'Integrations', icon: <Plug size={16} /> }
  ];

  const sortOptions: { id: SortOption; label: string }[] = [
    { id: 'featured', label: 'Featured' },
    { id: 'popular', label: 'Most Popular' },
    { id: 'newest', label: 'Recently Added' },
    { id: 'name', label: 'Name A-Z' }
  ];

  useEffect(() => {
    loadMarketplaceItems();
  }, []);

  useEffect(() => {
    filterAndSortItems();
  }, [items, selectedItemType, searchQuery, sortBy]);

  const loadMarketplaceItems = async () => {
    try {
      const [agentsData, basesData] = await Promise.all([
        marketplaceApi.getAllAgents(),
        marketplaceApi.getAllBases()
      ]);

      const agents = (agentsData.agents || []).map((agent: Record<string, unknown>) => ({
        ...agent,
        item_type: 'agent' as ItemType
      }));

      const bases = (basesData.bases || []).map((base: Record<string, unknown>) => ({
        ...base,
        item_type: 'base' as ItemType
      }));

      setItems([...agents, ...bases]);
    } catch (error) {
      console.error('Failed to load marketplace:', error);
      toast.error('Failed to load marketplace');
    } finally {
      setLoading(false);
    }
  };

  const filterAndSortItems = () => {
    let filtered = [...items];

    // Filter by item type
    filtered = filtered.filter(item => item.item_type === selectedItemType);

    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(item =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.tags?.some(tag => tag.toLowerCase().includes(query))
      );
    }

    // Sort items
    switch (sortBy) {
      case 'featured':
        filtered.sort((a, b) => (b.is_featured ? 1 : 0) - (a.is_featured ? 1 : 0));
        break;
      case 'popular':
        filtered.sort((a, b) => (b.downloads || b.usage_count || 0) - (a.downloads || a.usage_count || 0));
        break;
      case 'newest':
        // Assuming newer items have higher IDs or we'd need created_at
        filtered.sort((a, b) => b.id.localeCompare(a.id));
        break;
      case 'name':
        filtered.sort((a, b) => a.name.localeCompare(b.name));
        break;
    }

    setFilteredItems(filtered);
  };

  const handleInstall = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      // Button already shows "Soon" - no toast needed
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
        setItems(prev => prev.map(i =>
          i.id === item.id ? { ...i, is_purchased: true } : i
        ));
      }
    } catch (error) {
      console.error('Failed to install:', error);
      toast.error('Failed to add to library');
    }
  };

  const featuredItems = filteredItems.filter(item => item.is_featured);
  const regularItems = filteredItems.filter(item => !item.is_featured);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading marketplace..." size={80} />
      </div>
    );
  }

  return (
    <>
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      <div className="h-screen overflow-y-auto bg-[var(--bg)]">
        {/* Header */}
        <div className={`border-b ${theme === 'light' ? 'border-black/10 bg-white/80' : 'border-white/10 bg-[#0a0a0a]/80'} backdrop-blur-xl sticky top-0 z-40`}>
          <div className="max-w-6xl mx-auto px-6 md:px-12">
            {/* Top Bar */}
            <div className="h-14 flex items-center justify-between">
              <h1 className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}>
                Marketplace
              </h1>

              {/* Mobile hamburger */}
              <button
                onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
                className="md:hidden p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors"
              >
                <svg className="w-6 h-6 text-[var(--text)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            </div>

            {/* Search Bar - Raycast Style */}
            <div className="py-6">
              <div className={`
                relative max-w-2xl mx-auto flex items-center gap-3 px-4 py-3 rounded-xl border
                ${theme === 'light'
                  ? 'bg-black/5 border-black/10 focus-within:border-[var(--primary)] focus-within:bg-white'
                  : 'bg-white/5 border-white/10 focus-within:border-[var(--primary)] focus-within:bg-white/10'
                }
                transition-all
              `}>
                <MagnifyingGlass size={20} className={theme === 'light' ? 'text-black/40' : 'text-white/40'} />
                <input
                  type="text"
                  placeholder="Search extensions..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className={`
                    flex-1 bg-transparent outline-none text-sm
                    ${theme === 'light' ? 'text-black placeholder-black/40' : 'text-white placeholder-white/40'}
                  `}
                />
                <div className={`
                  hidden sm:flex items-center gap-1 px-2 py-1 rounded text-xs
                  ${theme === 'light' ? 'bg-black/10 text-black/50' : 'bg-white/10 text-white/50'}
                `}>
                  <Command size={12} />
                  <span>K</span>
                </div>
              </div>
            </div>

            {/* Tab Navigation */}
            <div className="flex items-center justify-between pb-4">
              {/* Item Type Tabs */}
              <div className="flex items-center gap-1">
                {itemTypes.map(type => (
                  <button
                    key={type.id}
                    onClick={() => setSelectedItemType(type.id)}
                    className={`
                      flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all
                      ${selectedItemType === type.id
                        ? 'bg-[var(--primary)] text-white'
                        : theme === 'light'
                          ? 'text-black/60 hover:text-black hover:bg-black/5'
                          : 'text-white/60 hover:text-white hover:bg-white/5'
                      }
                    `}
                  >
                    {type.icon}
                    <span className="hidden sm:inline">{type.label}</span>
                  </button>
                ))}
              </div>

              {/* Sort Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowSortDropdown(!showSortDropdown)}
                  className={`
                    flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all
                    ${theme === 'light'
                      ? 'text-black/60 hover:text-black hover:bg-black/5'
                      : 'text-white/60 hover:text-white hover:bg-white/5'
                    }
                  `}
                >
                  <span>{sortOptions.find(o => o.id === sortBy)?.label}</span>
                  <CaretDown size={14} />
                </button>

                {showSortDropdown && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowSortDropdown(false)}
                    />
                    <div className={`
                      absolute right-0 top-full mt-2 py-2 rounded-xl border shadow-xl z-50 min-w-[160px]
                      ${theme === 'light'
                        ? 'bg-white border-black/10'
                        : 'bg-[#1a1a1c] border-white/10'
                      }
                    `}>
                      {sortOptions.map(option => (
                        <button
                          key={option.id}
                          onClick={() => {
                            setSortBy(option.id);
                            setShowSortDropdown(false);
                          }}
                          className={`
                            w-full px-4 py-2 text-left text-sm transition-colors
                            ${sortBy === option.id
                              ? 'text-[var(--primary)]'
                              : theme === 'light'
                                ? 'text-black/70 hover:bg-black/5'
                                : 'text-white/70 hover:bg-white/5'
                            }
                          `}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-8">
          {/* Featured Section */}
          {featuredItems.length > 0 && (
            <section className="mb-12">
              <h2 className={`font-heading text-xl font-bold mb-6 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
                Featured
              </h2>
              <div className="space-y-4">
                {featuredItems.slice(0, 3).map(item => (
                  <FeaturedCard
                    key={item.id}
                    item={item}
                    onInstall={handleInstall}
                  />
                ))}
              </div>
            </section>
          )}

          {/* All Extensions Section */}
          <section>
            <h2 className={`font-heading text-xl font-bold mb-6 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              All {itemTypes.find(t => t.id === selectedItemType)?.label}
            </h2>

            {regularItems.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {regularItems.map(item => (
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
                  {searchQuery
                    ? `No ${selectedItemType}s found matching "${searchQuery}"`
                    : `No ${selectedItemType}s available yet`
                  }
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
