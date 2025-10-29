import { useState } from 'react';
import { Lock, LockOpen } from 'lucide-react';

interface MarketplacePanelProps {
  projectId: string;
  onLockToggle?: (locked: boolean) => void;
}

type MarketplaceTab = 'bases' | 'apis' | 'agents' | 'components';

interface MarketplaceItem {
  id: string;
  title: string;
  description: string;
  price?: string;
  badge?: string;
  gradient: string;
}

export function MarketplacePanel({ projectId, onLockToggle }: MarketplacePanelProps) {
  const [activeTab, setActiveTab] = useState<MarketplaceTab>('bases');
  const [searchQuery, setSearchQuery] = useState('');
  const [locked, setLocked] = useState(false);

  const handleLockToggle = () => {
    const newLocked = !locked;
    setLocked(newLocked);
    onLockToggle?.(newLocked);
  };

  const marketplaceItems: Record<MarketplaceTab, MarketplaceItem[]> = {
    bases: [
      {
        id: 1,
        title: 'SaaS Starter',
        description: 'Full auth, billing, dashboard',
        price: '$49',
        badge: 'Owned',
        gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
      },
      {
        id: 2,
        title: 'E-commerce Kit',
        description: 'Cart, checkout, products',
        price: '$79',
        gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)'
      }
    ],
    apis: [
      {
        id: 1,
        title: 'Google APIs',
        description: 'Drive, Calendar, Gmail',
        price: 'Free',
        badge: 'Installed',
        gradient: 'linear-gradient(135deg, #4285f4 0%, #34a853 100%)'
      },
      {
        id: 2,
        title: 'Stripe',
        description: 'Payments & billing',
        price: 'Free',
        gradient: 'linear-gradient(135deg, #635bff 0%, #1a1f71 100%)'
      }
    ],
    agents: [
      {
        id: 1,
        title: 'Security Scan',
        description: 'Pro agent • $9/mo',
        price: 'Subscription',
        gradient: 'linear-gradient(135deg, rgba(255,107,0,0.3), rgba(255,107,0,0.1))'
      },
      {
        id: 2,
        title: 'DB Optimizer',
        description: 'Open source • Free',
        price: 'Free',
        badge: 'Active',
        gradient: 'linear-gradient(135deg, rgba(0,217,255,0.3), rgba(0,217,255,0.1))'
      }
    ],
    components: [
      {
        id: 1,
        title: 'Dashboard UI',
        description: '20+ components',
        price: '$29',
        badge: 'In Library',
        gradient: 'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)'
      },
      {
        id: 2,
        title: 'Form Builder',
        description: '15+ form components',
        price: '$19',
        gradient: 'linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%)'
      }
    ]
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* Search and Tabs */}
      <div className="panel-section p-6 border-b border-white/5">
        <input
          type="text"
          placeholder="Search marketplace..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-sm outline-none focus:border-[var(--primary)] text-white mb-4"
        />
        <div className="flex gap-2 overflow-x-auto pb-2">
          {(['bases', 'apis', 'agents', 'components'] as MarketplaceTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                activeTab === tab
                  ? 'bg-[rgba(255,107,0,0.2)] border border-[rgba(255,107,0,0.3)] text-white'
                  : 'bg-white/5 border border-white/10 text-gray-400 hover:bg-white/8'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Marketplace Grid */}
      <div className="marketplace-grid grid grid-cols-2 gap-4 p-6">
        {marketplaceItems[activeTab].map((item) => (
          <div
            key={item.id}
            className="marketplace-item bg-white/3 border border-white/8 rounded-2xl p-4 transition-all hover:bg-white/5 hover:border-[var(--primary)] hover:-translate-y-0.5 cursor-pointer"
          >
            <div
              style={{ background: item.gradient }}
              className="h-[120px] rounded-xl mb-3"
            />
            <div className="font-semibold text-sm text-white mb-1">{item.title}</div>
            <div className="text-xs text-gray-500 mb-2">{item.description}</div>
            <div className="flex items-center justify-between">
              {item.price && <span className="text-xs text-gray-500">{item.price}</span>}
              {item.badge && (
                <span className="text-xs px-2 py-1 bg-green-500/20 text-green-400 rounded">
                  {item.badge}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Lock Button */}
      <div className="panel-section p-6 border-t border-white/5">
        <button
          onClick={handleLockToggle}
          className="w-full py-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          {locked ? <Lock className="w-4 h-4" /> : <LockOpen className="w-4 h-4" />}
          {locked ? 'Panel Locked' : 'Lock Panel'}
        </button>
      </div>
    </div>
  );
}
