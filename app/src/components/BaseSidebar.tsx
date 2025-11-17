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
    <div className="w-80 h-full bg-white border-r border-gray-200 flex flex-col">
      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Bases</h2>
        <div className="relative">
          <MagnifyingGlass
            size={20}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
          />
          <input
            type="text"
            placeholder="Search bases..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
        </div>
      </div>

      {/* Base list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          </div>
        ) : filteredBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <Package size={48} className="text-gray-300 mb-3" />
            <p className="text-sm text-gray-500 mb-2">
              {searchQuery ? 'No bases found' : 'No bases in your library'}
            </p>
            <a
              href="/marketplace"
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
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
                className="group cursor-move bg-white border border-gray-200 rounded-lg p-3 hover:border-blue-500 hover:shadow-md transition-all"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg">
                    <span className="text-2xl">{base.icon}</span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 truncate group-hover:text-blue-600 transition-colors">
                      {base.name}
                    </h3>
                    <p className="text-xs text-gray-500 line-clamp-2 mt-1">
                      {base.description}
                    </p>

                    {base.tech_stack && base.tech_stack.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {base.tech_stack.slice(0, 2).map((tech, index) => (
                          <span
                            key={index}
                            className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-700 rounded"
                          >
                            {tech}
                          </span>
                        ))}
                        {base.tech_stack.length > 2 && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                            +{base.tech_stack.length - 2}
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Plus size={20} className="text-blue-600" weight="bold" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
        <p className="text-xs text-gray-500 text-center">
          Drag and drop bases onto the canvas to add them to your project
        </p>
      </div>
    </div>
  );
};
