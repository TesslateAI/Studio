import { useState, useEffect, useRef } from 'react';
import {
  MagnifyingGlass,
  Package,
  Plus,
  Cloud,
  Database,
  HardDrive,
  FlowArrow,
  Cube,
  Browser,
  CaretDown,
  CaretRight,
  X,
  Question,
  TreeStructure,
  Sliders,
} from '@phosphor-icons/react';
import api from '../lib/api';
import { MainTechIcon, TechStackIcons } from './ui/TechStackIcons';

interface CredentialField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  placeholder: string;
  help_text: string;
}

interface MarketplaceItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  icon: string;
  tech_stack: string[];
  category: string;
  type?: 'base' | 'service' | 'workflow';
  service_type?: 'container' | 'external' | 'hybrid';
  credential_fields?: CredentialField[];
  auth_type?: string;
  docs_url?: string;
  connection_template?: Record<string, string>;
  outputs?: Record<string, string>;
}

interface MarketplaceSidebarProps {
  onSelectItem?: (item: MarketplaceItem) => void;
}

// Helper to render item type badge
const ItemTypeBadge = ({ item }: { item: MarketplaceItem }) => {
  let badge: { icon: React.ReactNode; label: string; color: string } | null = null;

  if (item.type === 'workflow') {
    badge = {
      icon: <FlowArrow size={12} weight="fill" />,
      label: 'Workflow',
      color: 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    };
  } else if (item.type === 'service' && item.service_type) {
    const serviceBadges: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
      container: {
        icon: <HardDrive size={12} weight="fill" />,
        label: 'Container',
        color: 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      },
      external: {
        icon: <Cloud size={12} weight="fill" />,
        label: 'External',
        color: 'bg-purple-500/20 text-purple-400 border-purple-500/30'
      },
      hybrid: {
        icon: <Database size={12} weight="fill" />,
        label: 'Hybrid',
        color: 'bg-green-500/20 text-green-400 border-green-500/30'
      }
    };
    badge = serviceBadges[item.service_type] || null;
  } else if (item.type === 'base') {
    badge = {
      icon: <Cube size={12} weight="fill" />,
      label: 'Base',
      color: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
    };
  }

  if (!badge) return null;

  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border ${badge.color}`}>
      {badge.icon}
      {badge.label}
    </span>
  );
};

// Category config based on item.type
const CATEGORIES = [
  { id: 'base', label: 'Bases', icon: <Cube size={16} weight="fill" /> },
  { id: 'service', label: 'Services', icon: <Cloud size={16} weight="fill" /> },
  { id: 'workflow', label: 'Workflows', icon: <FlowArrow size={16} weight="fill" /> },
];

export const MarketplaceSidebar = ({ onSelectItem }: MarketplaceSidebarProps) => {
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [isOpen, setIsOpen] = useState(false);
  const [isAutoOpen, setIsAutoOpen] = useState(false);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['base', 'service', 'workflow']));
  const dropdownRef = useRef<HTMLDivElement>(null);
  const autoRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchMarketplaceItems();
  }, []);

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
      if (autoRef.current && !autoRef.current.contains(event.target as Node)) {
        setIsAutoOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const fetchMarketplaceItems = async () => {
    try {
      const response = await api.get('/api/marketplace/my-items');
      setItems(response.data.items || []);
    } catch (error) {
      console.error('Failed to fetch marketplace items:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleCategory = (categoryId: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(categoryId)) {
        next.delete(categoryId);
      } else {
        next.add(categoryId);
      }
      return next;
    });
  };

  const filteredItems = items.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.tech_stack?.some(tech => tech.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  // Group items by their actual type
  const itemsByType = filteredItems.reduce((acc, item) => {
    const type = item.type || 'base';
    if (!acc[type]) acc[type] = [];
    acc[type].push(item);
    return acc;
  }, {} as Record<string, MarketplaceItem[]>);

  const onDragStart = (event: React.DragEvent, item: MarketplaceItem) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/reactflow', 'containerNode');
    event.dataTransfer.setData('base', JSON.stringify(item));
  };

  const onBrowserDragStart = (event: React.DragEvent) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/reactflow', 'browserPreview');
    event.dataTransfer.setData('base', JSON.stringify({ type: 'browser', name: 'Browser Preview' }));
  };

  return (
    <div className="absolute top-3 left-3 flex items-center gap-2 z-40">
      {/* Drag Components Dropdown */}
      <div ref={dropdownRef} className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 px-3 py-2 bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-lg shadow-lg hover:bg-[var(--sidebar-hover)] transition-colors"
        >
          <Package size={16} className="text-[var(--primary)]" weight="fill" />
          <span className="text-sm font-medium text-[var(--text)] hidden sm:inline">Components</span>
          <CaretDown
            size={14}
            className={`text-[var(--text)]/60 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        </button>

        {/* Components Dropdown Panel */}
        {isOpen && (
          <div className="absolute top-full left-0 mt-2 w-72 sm:w-80 max-h-[60vh] bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-xl shadow-2xl overflow-hidden flex flex-col">
            {/* Search */}
            <div className="p-3 border-b border-[var(--sidebar-border)]">
              <div className="relative">
                <MagnifyingGlass
                  size={16}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text)]/40"
                />
                <input
                  type="text"
                  placeholder="Search components..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-8 py-2 border border-[var(--border-color)] bg-[var(--bg)] text-[var(--text)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] text-sm placeholder:text-[var(--text)]/40"
                  autoFocus
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text)]/40 hover:text-[var(--text)]"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[var(--primary)]"></div>
                </div>
              ) : (
                <>
                  {/* Browser Preview Tool */}
                  <div className="px-3 py-2 border-b border-[var(--sidebar-border)]">
                    <p className="text-[10px] uppercase tracking-wider text-[var(--text)]/40 font-medium mb-2">Tools</p>
                    <div
                      draggable
                      onDragStart={onBrowserDragStart}
                      className="flex items-center gap-2 px-2 py-2 rounded-lg cursor-move bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 hover:border-purple-400 transition-colors"
                    >
                      <Browser size={18} weight="fill" className="text-purple-400" />
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium text-[var(--text)]">Browser Preview</span>
                        <p className="text-[10px] text-[var(--text)]/50">Preview running containers</p>
                      </div>
                      <Plus size={14} className="text-purple-400" weight="bold" />
                    </div>
                  </div>

                  {/* Category List */}
                  <div className="py-2">
                    {CATEGORIES.map((category) => {
                      const categoryItems = itemsByType[category.id] || [];
                      const isExpanded = expandedCategories.has(category.id);

                      return (
                        <div key={category.id}>
                          {/* Category Header */}
                          <button
                            onClick={() => toggleCategory(category.id)}
                            className="w-full flex items-center gap-2 px-3 py-2 hover:bg-[var(--sidebar-hover)] transition-colors"
                          >
                            <span className="text-[var(--text)]/60">
                              {isExpanded ? <CaretDown size={14} /> : <CaretRight size={14} />}
                            </span>
                            <span className="text-[var(--primary)]">{category.icon}</span>
                            <span className="text-sm font-medium text-[var(--text)] flex-1 text-left">
                              {category.label}
                            </span>
                            <span className="text-xs text-[var(--text)]/40 bg-[var(--bg)] px-1.5 py-0.5 rounded">
                              {categoryItems.length}
                            </span>
                          </button>

                          {/* Category Items */}
                          {isExpanded && categoryItems.length > 0 && (
                            <div className="px-3 pb-2 space-y-1">
                              {categoryItems.map((item) => (
                                <div
                                  key={item.id}
                                  draggable
                                  onDragStart={(e) => onDragStart(e, item)}
                                  onClick={() => {
                                    onSelectItem?.(item);
                                    setIsOpen(false);
                                  }}
                                  className="group cursor-move bg-[var(--bg)] border border-[var(--border-color)] rounded-lg p-2 hover:border-[var(--primary)] hover:shadow-md transition-all"
                                >
                                  <div className="flex items-start gap-2">
                                    <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center bg-[var(--primary)]/10 rounded-lg text-[var(--primary)]">
                                      <MainTechIcon
                                        techStack={item.tech_stack || []}
                                        itemName={item.name}
                                        fallbackEmoji={item.icon}
                                        size={18}
                                      />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <h3 className="font-medium text-sm text-[var(--text)] truncate group-hover:text-[var(--primary)] transition-colors">
                                        {item.name}
                                      </h3>
                                      <p className="text-[10px] text-[var(--text)]/60 line-clamp-1">
                                        {item.description}
                                      </p>
                                      <div className="flex items-center gap-2 mt-1">
                                        <ItemTypeBadge item={item} />
                                        {item.tech_stack && item.tech_stack.length > 0 && (
                                          <TechStackIcons
                                            techStack={item.tech_stack}
                                            maxIcons={3}
                                            size={12}
                                            className="text-[var(--text)]/70"
                                          />
                                        )}
                                      </div>
                                    </div>
                                    <Plus size={14} className="text-[var(--text)]/40 opacity-0 group-hover:opacity-100 transition-opacity" weight="bold" />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}

                          {isExpanded && categoryItems.length === 0 && (
                            <div className="px-6 py-2 text-xs text-[var(--text)]/40">
                              No {category.label.toLowerCase()} in library
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Empty state */}
                  {filteredItems.length === 0 && !loading && (
                    <div className="flex flex-col items-center justify-center py-6 px-4 text-center">
                      <Package size={32} className="text-[var(--text)]/20 mb-2" />
                      <p className="text-sm text-[var(--text)]/60 mb-2">
                        {searchQuery ? 'No components found' : 'No components in library'}
                      </p>
                      <a
                        href="/marketplace"
                        className="text-sm text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium"
                      >
                        Browse Marketplace
                      </a>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Footer */}
            <div className="px-3 py-2 border-t border-[var(--sidebar-border)] bg-[var(--bg)]">
              <div className="flex items-center gap-2 text-xs text-[var(--text)]/50">
                <Question size={14} />
                <span>Drag items onto canvas</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Auto Layout Dropdown */}
      <div ref={autoRef} className="relative">
        <button
          onClick={() => setIsAutoOpen(!isAutoOpen)}
          className="flex items-center gap-2 px-3 py-2 bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-lg shadow-lg hover:bg-[var(--sidebar-hover)] transition-colors"
        >
          <TreeStructure size={16} className="text-[var(--text)]/70" />
          <span className="text-sm font-medium text-[var(--text)]">Auto</span>
          <CaretDown
            size={14}
            className={`text-[var(--text)]/60 transition-transform ${isAutoOpen ? 'rotate-180' : ''}`}
          />
        </button>

        {/* Auto Layout Dropdown Panel */}
        {isAutoOpen && (
          <div className="absolute top-full left-0 mt-2 w-56 bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-xl shadow-2xl overflow-hidden">
            <div className="p-3 border-b border-[var(--sidebar-border)]">
              <div className="flex items-center gap-2">
                <Sliders size={16} className="text-[var(--primary)]" />
                <span className="text-sm font-medium text-[var(--text)]">Auto Layout</span>
              </div>
            </div>
            <div className="p-2 space-y-1">
              <button className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-[var(--sidebar-hover)] transition-colors text-left">
                <span className="text-sm text-[var(--text)]">Horizontal</span>
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-[var(--sidebar-hover)] transition-colors text-left">
                <span className="text-sm text-[var(--text)]">Vertical</span>
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-[var(--sidebar-hover)] transition-colors text-left">
                <span className="text-sm text-[var(--text)]">Grid</span>
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-[var(--sidebar-hover)] transition-colors text-left">
                <span className="text-sm text-[var(--text)]">Radial</span>
              </button>
            </div>
            <div className="px-3 py-2 border-t border-[var(--sidebar-border)] bg-[var(--bg)]">
              <p className="text-[10px] text-[var(--text)]/50">Arrange nodes automatically</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
