import { useState, useEffect, useCallback } from 'react';
import { DollarSign, CreditCard, TrendingUp, Users, ChevronLeft, ChevronRight } from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface BillingOverview {
  summary: {
    subscription_mrr_cents: number;
    credit_revenue_cents: number;
    marketplace_revenue_cents: number;
    total_revenue_cents: number;
    total_revenue_dollars: number;
  };
  subscriptions: {
    by_tier: Record<string, number>;
    revenue_by_tier: Record<string, number>;
    total_subscribers: number;
  };
  credits: {
    total_purchases: number;
    revenue_cents: number;
  };
  marketplace: {
    revenue_cents: number;
  };
  timeline: Array<{
    date: string;
    credits: number;
    total: number;
  }>;
  period: string;
}

interface CreditPurchase {
  id: string;
  user_id: string | null;
  user_email: string | null;
  user_username: string | null;
  amount_cents: number;
  credits_amount: number;
  status: string;
  stripe_payment_intent: string;
  created_at: string | null;
  completed_at: string | null;
}

interface Creator {
  id: string;
  username: string;
  email: string;
  stripe_account_id: string | null;
  agent_count: number;
  total_earnings_cents: number;
  created_at: string | null;
}

const TIER_COLORS: Record<string, string> = {
  free: 'bg-zinc-700',
  basic: 'bg-blue-600',
  pro: 'bg-purple-600',
  ultra: 'bg-yellow-600',
};

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-500/20 text-green-400',
  pending: 'bg-yellow-500/20 text-yellow-400',
  failed: 'bg-red-500/20 text-red-400',
  refunded: 'bg-blue-500/20 text-blue-400',
};

export default function BillingAdmin() {
  const [activeTab, setActiveTab] = useState<'overview' | 'purchases' | 'creators'>('overview');
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState('30d');

  // Overview data
  const [overview, setOverview] = useState<BillingOverview | null>(null);

  // Purchases data
  const [purchases, setPurchases] = useState<CreditPurchase[]>([]);
  const [purchasesTotal, setPurchasesTotal] = useState(0);
  const [purchasesPage, setPurchasesPage] = useState(1);
  const [purchasesPages, setPurchasesPages] = useState(0);

  // Creators data
  const [creators, setCreators] = useState<Creator[]>([]);

  const loadOverview = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/billing/overview?period=${period}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load billing overview');

      const data: BillingOverview = await response.json();
      setOverview(data);
    } catch (error) {
      console.error('Failed to load billing overview:', error);
      toast.error('Failed to load billing overview');
    } finally {
      setLoading(false);
    }
  }, [period]);

  const loadPurchases = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      params.append('page', purchasesPage.toString());
      params.append('page_size', '25');

      const response = await fetch(`/api/admin/billing/credit-purchases?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load credit purchases');

      const data = await response.json();
      setPurchases(data.purchases);
      setPurchasesTotal(data.total);
      setPurchasesPages(data.pages);
    } catch (error) {
      console.error('Failed to load credit purchases:', error);
      toast.error('Failed to load credit purchases');
    } finally {
      setLoading(false);
    }
  }, [purchasesPage]);

  const loadCreators = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/admin/billing/creator-payouts', {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load creators');

      const data = await response.json();
      setCreators(data.creators);
    } catch (error) {
      console.error('Failed to load creators:', error);
      toast.error('Failed to load creators');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'overview') {
      loadOverview();
    } else if (activeTab === 'purchases') {
      loadPurchases();
    } else if (activeTab === 'creators') {
      loadCreators();
    }
  }, [activeTab, loadOverview, loadPurchases, loadCreators]);

  const formatCurrency = (cents: number) => {
    return `$${(cents / 100).toFixed(2)}`;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString();
  };

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  // Calculate max value for timeline chart
  const maxTimelineValue = overview?.timeline
    ? Math.max(...overview.timeline.map((t) => t.total), 1)
    : 1;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-zinc-400" />
          <h2 className="text-lg font-semibold text-white">Billing Administration</h2>
        </div>
        {activeTab === 'overview' && (
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="px-3 py-1.5 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none"
          >
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
          </select>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-zinc-900 rounded-lg w-fit">
        {(['overview', 'purchases', 'creators'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size={32} />
        </div>
      ) : activeTab === 'overview' && overview ? (
        <div className="space-y-6">
          {/* Summary Cards */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <TrendingUp className="h-4 w-4" />
                <span className="text-sm">Total Revenue</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(overview.summary.total_revenue_cents)}
              </p>
              <p className="text-xs text-zinc-500 mt-1">This period</p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <Users className="h-4 w-4" />
                <span className="text-sm">Subscription MRR</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(overview.summary.subscription_mrr_cents)}
              </p>
              <p className="text-xs text-zinc-500 mt-1">
                {overview.subscriptions.total_subscribers} subscribers
              </p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <CreditCard className="h-4 w-4" />
                <span className="text-sm">Credit Purchases</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(overview.summary.credit_revenue_cents)}
              </p>
              <p className="text-xs text-zinc-500 mt-1">
                {overview.credits.total_purchases} purchases
              </p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <DollarSign className="h-4 w-4" />
                <span className="text-sm">Marketplace</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {formatCurrency(overview.summary.marketplace_revenue_cents)}
              </p>
              <p className="text-xs text-zinc-500 mt-1">Agent sales</p>
            </div>
          </div>

          {/* Subscriptions by Tier */}
          <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
            <h3 className="text-sm font-medium text-zinc-400 mb-4">Subscriptions by Tier</h3>
            <div className="grid grid-cols-4 gap-4">
              {Object.entries(overview.subscriptions.by_tier).map(([tier, count]) => (
                <div key={tier} className="text-center">
                  <div
                    className={`w-full h-2 rounded-full mb-2 ${TIER_COLORS[tier] || 'bg-zinc-600'}`}
                  />
                  <p className="text-white font-semibold capitalize">{tier}</p>
                  <p className="text-2xl font-bold text-white">{count}</p>
                  <p className="text-xs text-zinc-500">
                    {formatCurrency(overview.subscriptions.revenue_by_tier[tier] || 0)}/mo
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Revenue Timeline */}
          <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
            <h3 className="text-sm font-medium text-zinc-400 mb-4">Daily Revenue</h3>
            <div className="h-48 flex items-end gap-1">
              {overview.timeline.map((day, idx) => (
                <div
                  key={idx}
                  className="flex-1 bg-green-600 rounded-t hover:bg-green-500 transition-colors"
                  style={{
                    height: `${(day.total / maxTimelineValue) * 100}%`,
                    minHeight: day.total > 0 ? '4px' : '0',
                  }}
                  title={`${new Date(day.date).toLocaleDateString()}: ${formatCurrency(day.total)}`}
                />
              ))}
            </div>
            <div className="flex justify-between text-xs text-zinc-500 mt-2">
              <span>
                {overview.timeline.length > 0 ? formatDate(overview.timeline[0].date) : ''}
              </span>
              <span>
                {overview.timeline.length > 0
                  ? formatDate(overview.timeline[overview.timeline.length - 1].date)
                  : ''}
              </span>
            </div>
          </div>
        </div>
      ) : activeTab === 'purchases' ? (
        <div className="space-y-4">
          {purchases.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">No credit purchases found</div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-500 border-b border-zinc-800">
                      <th className="pb-3 font-medium">User</th>
                      <th className="pb-3 font-medium">Amount</th>
                      <th className="pb-3 font-medium">Credits</th>
                      <th className="pb-3 font-medium">Status</th>
                      <th className="pb-3 font-medium">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {purchases.map((purchase) => (
                      <tr
                        key={purchase.id}
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                      >
                        <td className="py-3">
                          <div>
                            <p className="text-white">@{purchase.user_username || '-'}</p>
                            <p className="text-xs text-zinc-500">{purchase.user_email || ''}</p>
                          </div>
                        </td>
                        <td className="py-3 text-white font-medium">
                          {formatCurrency(purchase.amount_cents)}
                        </td>
                        <td className="py-3 text-zinc-400">
                          {purchase.credits_amount.toLocaleString()}
                        </td>
                        <td className="py-3">
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[purchase.status] || 'bg-zinc-700'}`}
                          >
                            {purchase.status}
                          </span>
                        </td>
                        <td className="py-3 text-zinc-400">
                          {formatDateTime(purchase.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {purchasesPages > 1 && (
                <div className="flex items-center justify-between pt-4">
                  <span className="text-sm text-zinc-500">
                    Showing {(purchasesPage - 1) * 25 + 1} -{' '}
                    {Math.min(purchasesPage * 25, purchasesTotal)} of {purchasesTotal}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPurchasesPage((p) => Math.max(1, p - 1))}
                      disabled={purchasesPage === 1}
                      className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50"
                    >
                      <ChevronLeft className="h-4 w-4 text-zinc-400" />
                    </button>
                    <span className="text-sm text-zinc-400">
                      Page {purchasesPage} of {purchasesPages}
                    </span>
                    <button
                      onClick={() => setPurchasesPage((p) => Math.min(purchasesPages, p + 1))}
                      disabled={purchasesPage === purchasesPages}
                      className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50"
                    >
                      <ChevronRight className="h-4 w-4 text-zinc-400" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      ) : activeTab === 'creators' ? (
        <div className="space-y-4">
          {creators.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">
              No creators with payout accounts found
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-zinc-500 border-b border-zinc-800">
                    <th className="pb-3 font-medium">Creator</th>
                    <th className="pb-3 font-medium">Stripe Account</th>
                    <th className="pb-3 font-medium">Agents</th>
                    <th className="pb-3 font-medium">Total Earnings</th>
                    <th className="pb-3 font-medium">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {creators.map((creator) => (
                    <tr
                      key={creator.id}
                      className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                    >
                      <td className="py-3">
                        <div>
                          <p className="text-white">@{creator.username}</p>
                          <p className="text-xs text-zinc-500">{creator.email}</p>
                        </div>
                      </td>
                      <td className="py-3 text-zinc-400 font-mono text-xs">
                        {creator.stripe_account_id?.slice(0, 20)}...
                      </td>
                      <td className="py-3 text-zinc-400">{creator.agent_count}</td>
                      <td className="py-3 text-green-400 font-medium">
                        {formatCurrency(creator.total_earnings_cents)}
                      </td>
                      <td className="py-3 text-zinc-400">{formatDate(creator.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
