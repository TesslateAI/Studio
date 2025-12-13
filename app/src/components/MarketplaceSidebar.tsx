import { useState, useEffect } from 'react';
import { MagnifyingGlass, Package, Plus, Cloud, Database, HardDrive, FlowArrow, Cube, Browser } from '@phosphor-icons/react';
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
  // Service-specific fields
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
  // Determine badge based on item type
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

export const MarketplaceSidebar = ({ onSelectItem }: MarketplaceSidebarProps) => {
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMarketplaceItems();
  }, []);

  const fetchMarketplaceItems = async () => {
    try {
      // Fetch all marketplace items (bases, services, workflows)
      const response = await api.get('/api/marketplace/my-items');
      setItems(response.data.items || []);
    } catch (error) {
      console.error('Failed to fetch marketplace items:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredItems = items.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.tech_stack?.some(tech => tech.toLowerCase().includes(searchQuery.toLowerCase()))
  );

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
    <div className="w-full md:w-80 h-full bg-[var(--surface)] border-r border-[var(--sidebar-border)] flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-3 md:px-4 py-3 md:py-4 border-b border-[var(--sidebar-border)] flex-shrink-0">
        <h2 className="text-base md:text-lg font-semibold text-[var(--text)] mb-2 md:mb-3">Marketplace</h2>
        <div className="relative">
          <MagnifyingGlass
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text)]/40"
          />
          <input
            type="text"
            placeholder="Search components..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 md:py-2 border border-[var(--border-color)] bg-[var(--bg)] text-[var(--text)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] text-sm placeholder:text-[var(--text)]/40"
          />
        </div>
      </div>

      {/* Tools section */}
      <div className="px-2 md:px-3 py-2 border-b border-[var(--sidebar-border)]">
        <p className="text-[10px] uppercase tracking-wider text-[var(--text)]/40 font-medium mb-2 px-1">Tools</p>
        <div
          draggable
          onDragStart={onBrowserDragStart}
          className="group cursor-move bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 rounded-lg p-2 md:p-2.5 hover:border-purple-400 hover:shadow-md transition-all"
        >
          <div className="flex items-center gap-2 md:gap-3">
            <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center bg-purple-500/20 rounded-lg">
              <Browser size={18} weight="fill" className="text-purple-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-sm text-[var(--text)] group-hover:text-purple-400 transition-colors">
                Browser Preview
              </h3>
              <p className="text-[10px] text-[var(--text)]/50">
                Preview running containers
              </p>
            </div>
            <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
              <Plus size={16} className="text-purple-400" weight="bold" />
            </div>
          </div>
        </div>
      </div>

      {/* Component list */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-8 md:py-12">
            <div className="animate-spin rounded-full h-6 w-6 md:h-8 md:w-8 border-b-2 border-[var(--primary)]"></div>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 md:py-12 px-3 md:px-4 text-center">
            <Package size={40} className="text-[var(--text)]/20 mb-2 md:mb-3" />
            <p className="text-xs md:text-sm text-[var(--text)]/60 mb-2">
              {searchQuery ? 'No components found' : 'No components in your library'}
            </p>
            <a
              href="/marketplace"
              className="text-xs md:text-sm text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium"
            >
              Browse Marketplace →
            </a>
          </div>
        ) : (
          <div className="p-2 md:p-3 space-y-2">
            {filteredItems.map((item) => (
              <div
                key={item.id}
                draggable
                onDragStart={(e) => onDragStart(e, item)}
                onClick={() => onSelectItem?.(item)}
                className="group cursor-move bg-[var(--bg)] border border-[var(--border-color)] rounded-lg p-2 md:p-3 hover:border-[var(--primary)] hover:shadow-md transition-all overflow-hidden"
              >
                <div className="flex items-start gap-2 md:gap-3 min-w-0">
                  <div className="flex-shrink-0 w-8 h-8 md:w-10 md:h-10 flex items-center justify-center bg-[var(--primary)]/10 rounded-lg text-[var(--primary)]">
                    <MainTechIcon
                      techStack={item.tech_stack || []}
                      itemName={item.name}
                      fallbackEmoji={item.icon}
                      size={20}
                    />
                  </div>

                  <div className="flex-1 min-w-0 overflow-hidden">
                    <h3 className="font-medium text-sm md:text-base text-[var(--text)] truncate group-hover:text-[var(--primary)] transition-colors">
                      {item.name}
                    </h3>
                    <p className="text-xs text-[var(--text)]/60 line-clamp-2 mt-0.5 md:mt-1 break-words">
                      {item.description}
                    </p>

                    {/* Item type badge */}
                    <div className="mt-1.5">
                      <ItemTypeBadge item={item} />
                    </div>

                    {item.tech_stack && item.tech_stack.length > 0 && (
                      <div className="flex items-center gap-1 mt-1.5 md:mt-2">
                        <TechStackIcons
                          techStack={item.tech_stack}
                          maxIcons={4}
                          size={14}
                          className="text-[var(--text)]/70"
                          iconClassName="hover:text-[var(--primary)] transition-colors"
                        />
                        {item.tech_stack.length > 4 && (
                          <span className="text-xs text-[var(--text)]/50 ml-0.5">
                            +{item.tech_stack.length - 4}
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity hidden md:block">
                    <Plus size={18} className="text-[var(--primary)]" weight="bold" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="px-3 md:px-4 py-2 md:py-3 border-t border-[var(--sidebar-border)] bg-[var(--sidebar-hover)] flex-shrink-0">
        <p className="text-xs text-[var(--text)]/60 text-center break-words">
          Drag and drop components onto the canvas to add them to your project
        </p>
      </div>
    </div>
  );
};
