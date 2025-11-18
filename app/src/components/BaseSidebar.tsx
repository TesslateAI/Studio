import { useState, useEffect } from 'react';
import { MagnifyingGlass, Package, Plus } from '@phosphor-icons/react';
import api from '../lib/api';

interface Base {
  id: string;
  name: string;
  slug: string;
  description: string;
  icon: string;
  tech_stack: string[];
  category: string;
}

interface BaseSidebarProps {
  onSelectBase?: (base: Base) => void;
}

export const BaseSidebar = ({ onSelectBase }: BaseSidebarProps) => {
  const [bases, setBases] = useState<Base[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBases();
  }, []);

  const fetchBases = async () => {
    try {
      // Fetch user's purchased bases
      const response = await api.get('/api/marketplace/my-bases');
      setBases(response.data.bases || []);
    } catch (error) {
      console.error('Failed to fetch bases:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredBases = bases.filter(base =>
    base.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    base.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    base.tech_stack?.some(tech => tech.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const onDragStart = (event: React.DragEvent, base: Base) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/reactflow', 'containerNode');
    event.dataTransfer.setData('base', JSON.stringify(base));
  };

  return (
    <div className="w-80 h-full bg-[var(--surface)] border-r border-[var(--sidebar-border)] flex flex-col">
      {/* Header */}
      <div className="px-4 py-4 border-b border-[var(--sidebar-border)]">
        <h2 className="text-lg font-semibold text-[var(--text)] mb-3">Bases</h2>
        <div className="relative">
          <MagnifyingGlass
            size={20}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text)]/40"
          />
          <input
            type="text"
            placeholder="Search bases..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-[var(--border-color)] bg-[var(--bg)] text-[var(--text)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] text-sm placeholder:text-[var(--text)]/40"
          />
        </div>
      </div>

      {/* Base list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--primary)]"></div>
          </div>
        ) : filteredBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <Package size={48} className="text-[var(--text)]/20 mb-3" />
            <p className="text-sm text-[var(--text)]/60 mb-2">
              {searchQuery ? 'No bases found' : 'No bases in your library'}
            </p>
            <a
              href="/marketplace"
              className="text-sm text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium"
            >
              Browse Marketplace →
            </a>
          </div>
        ) : (
          <div className="p-3 space-y-2">
            {filteredBases.map((base) => (
              <div
                key={base.id}
                draggable
                onDragStart={(e) => onDragStart(e, base)}
                onClick={() => onSelectBase?.(base)}
                className="group cursor-move bg-[var(--bg)] border border-[var(--border-color)] rounded-lg p-3 hover:border-[var(--primary)] hover:shadow-md transition-all"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center bg-[var(--primary)]/10 rounded-lg">
                    <span className="text-2xl">{base.icon}</span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-[var(--text)] truncate group-hover:text-[var(--primary)] transition-colors">
                      {base.name}
                    </h3>
                    <p className="text-xs text-[var(--text)]/60 line-clamp-2 mt-1">
                      {base.description}
                    </p>

                    {base.tech_stack && base.tech_stack.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {base.tech_stack.slice(0, 2).map((tech, index) => (
                          <span
                            key={index}
                            className="px-2 py-0.5 text-xs font-medium bg-[var(--sidebar-hover)] text-[var(--text)] rounded"
                          >
                            {tech}
                          </span>
                        ))}
                        {base.tech_stack.length > 2 && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-[var(--sidebar-hover)] text-[var(--text)]/70 rounded">
                            +{base.tech_stack.length - 2}
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Plus size={20} className="text-[var(--primary)]" weight="bold" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="px-4 py-3 border-t border-[var(--sidebar-border)] bg-[var(--sidebar-hover)]">
        <p className="text-xs text-[var(--text)]/60 text-center">
          Drag and drop bases onto the canvas to add them to your project
        </p>
      </div>
    </div>
  );
};
