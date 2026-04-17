import { useState, useEffect, useCallback } from 'react';
import { Zap, AlertTriangle, Users, DollarSign, RefreshCw } from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface ModelUsage {
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_cents: number;
  requests: number;
}

interface UserUsage {
  user_id: string;
  username: string;
  email: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_cents: number;
}

interface TierUsage {
  tier: string;
  tokens_in: number;
  tokens_out: number;
  cost_cents: number;
  users: number;
}

interface TimelineEntry {
  date: string;
  tokens_in: number;
  tokens_out: number;
  cost_cents: number;
}

interface Anomaly {
  user_id: string;
  username: string;
  email: string | null;
  cost_cents: number;
  request_count: number;
  deviation: number;
  severity: 'medium' | 'high';
}

interface TokenAnalyticsData {
  summary: {
    tokens_in: number;
    tokens_out: number;
    tokens_total: number;
    cost_cents: number;
    cost_dollars: number;
    active_users: number;
    projected_monthly_cents: number;
    projected_monthly_dollars: number;
  };
  by_model: ModelUsage[];
  by_user: UserUsage[];
  by_tier: TierUsage[];
  timeline: TimelineEntry[];
  period: string;
}

interface AnomaliesData {
  anomalies: Anomaly[];
  threshold: number;
  mean_cost_cents: number;
  std_cost_cents: number;
  period: string;
}

export default function TokenAnalytics() {
  const [data, setData] = useState<TokenAnalyticsData | null>(null);
  const [anomalies, setAnomalies] = useState<AnomaliesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState('30d');
  const [refreshing, setRefreshing] = useState(false);

  const loadAnalytics = useCallback(async () => {
    try {
      const response = await fetch(`/api/admin/analytics/tokens?period=${period}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load token analytics');

      const analyticsData: TokenAnalyticsData = await response.json();
      setData(analyticsData);
    } catch (error) {
      console.error('Failed to load analytics:', error);
      toast.error('Failed to load token analytics');
    }
  }, [period]);

  const loadAnomalies = useCallback(async () => {
    try {
      const response = await fetch(`/api/admin/analytics/tokens/anomalies?period=${period}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load anomalies');

      const anomalyData: AnomaliesData = await response.json();
      setAnomalies(anomalyData);
    } catch (error) {
      console.error('Failed to load anomalies:', error);
    }
  }, [period]);

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([loadAnalytics(), loadAnomalies()]);
      setLoading(false);
    };
    loadAll();
  }, [loadAnalytics, loadAnomalies]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadAnalytics(), loadAnomalies()]);
    setRefreshing(false);
    toast.success('Analytics refreshed');
  };

  const formatNumber = (num: number) => {
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'K';
    }
    return num.toLocaleString();
  };

  const formatCurrency = (cents: number) => {
    return '$' + (cents / 100).toFixed(2);
  };

  const getTierColor = (tier: string) => {
    const colors: Record<string, string> = {
      free: '#6B7280',
      basic: '#3B82F6',
      pro: '#8B5CF6',
      ultra: '#F59E0B',
    };
    return colors[tier] || colors.free;
  };

  const chartColors = [
    '#3B82F6',
    '#10B981',
    '#F59E0B',
    '#EF4444',
    '#8B5CF6',
    '#EC4899',
    '#06B6D4',
    '#84CC16',
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner message="Loading token analytics..." size={60} />
      </div>
    );
  }

  if (!data) {
    return <div className="text-center py-12 text-gray-400">Failed to load analytics data</div>;
  }

  const maxTimelineValue = Math.max(...data.timeline.map((t) => t.cost_cents), 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Zap className="text-yellow-500" size={24} />
          <h2 className="text-2xl font-bold text-white">Token Usage Analytics</h2>
        </div>
        <div className="flex items-center space-x-4">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700"
          >
            <option value="1h">Last Hour</option>
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="90d">Last 90 Days</option>
          </select>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg flex items-center space-x-2 text-sm"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Total Tokens</span>
            <Zap className="text-yellow-500" size={20} />
          </div>
          <div className="text-2xl font-bold text-white">
            {formatNumber(data.summary.tokens_total)}
          </div>
          <div className="text-gray-500 text-sm mt-1">
            {formatNumber(data.summary.tokens_in)} in / {formatNumber(data.summary.tokens_out)} out
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Total Cost</span>
            <DollarSign className="text-green-500" size={20} />
          </div>
          <div className="text-2xl font-bold text-white">
            {formatCurrency(data.summary.cost_cents)}
          </div>
          <div className="text-gray-500 text-sm mt-1">
            Projected: {formatCurrency(data.summary.projected_monthly_cents)}/mo
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Active Users</span>
            <Users className="text-blue-500" size={20} />
          </div>
          <div className="text-2xl font-bold text-white">{data.summary.active_users}</div>
          <div className="text-gray-500 text-sm mt-1">
            Avg: {formatCurrency(data.summary.cost_cents / Math.max(data.summary.active_users, 1))}
            /user
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">Anomalies</span>
            <AlertTriangle
              className={
                anomalies && anomalies.anomalies.length > 0 ? 'text-red-500' : 'text-gray-500'
              }
              size={20}
            />
          </div>
          <div className="text-2xl font-bold text-white">{anomalies?.anomalies.length || 0}</div>
          <div className="text-gray-500 text-sm mt-1">
            {anomalies && anomalies.anomalies.filter((a) => a.severity === 'high').length} high
            severity
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Usage Timeline */}
        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <h3 className="text-lg font-semibold text-white mb-4">Cost Over Time</h3>
          <div className="h-48 flex items-end space-x-1">
            {data.timeline.map((entry, idx) => (
              <div key={idx} className="flex-1 flex flex-col items-center group relative">
                <div
                  className="w-full bg-blue-500 rounded-t transition-all hover:bg-blue-400"
                  style={{
                    height: `${(entry.cost_cents / maxTimelineValue) * 100}%`,
                    minHeight: entry.cost_cents > 0 ? '4px' : '2px',
                  }}
                />
                {/* Tooltip */}
                <div className="absolute bottom-full mb-2 hidden group-hover:block bg-gray-900 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
                  {new Date(entry.date).toLocaleDateString()}: {formatCurrency(entry.cost_cents)}
                </div>
              </div>
            ))}
          </div>
          <div className="flex justify-between mt-2 text-xs text-gray-500">
            <span>
              {data.timeline[0]?.date ? new Date(data.timeline[0].date).toLocaleDateString() : ''}
            </span>
            <span>
              {data.timeline[data.timeline.length - 1]?.date
                ? new Date(data.timeline[data.timeline.length - 1].date).toLocaleDateString()
                : ''}
            </span>
          </div>
        </div>

        {/* Usage by Model */}
        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <h3 className="text-lg font-semibold text-white mb-4">Cost by Model</h3>
          <div className="space-y-3">
            {data.by_model.slice(0, 6).map((model, idx) => {
              const totalCost = data.by_model.reduce((sum, m) => sum + m.cost_cents, 0);
              const percentage =
                totalCost > 0 ? ((model.cost_cents / totalCost) * 100).toFixed(1) : 0;
              return (
                <div key={model.model} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-300 truncate max-w-[200px]" title={model.model}>
                      {model.model}
                    </span>
                    <span className="text-gray-400">
                      {formatCurrency(model.cost_cents)} ({percentage}%)
                    </span>
                  </div>
                  <div className="w-full bg-gray-700 rounded-full h-2">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${percentage}%`,
                        backgroundColor: chartColors[idx % chartColors.length],
                      }}
                    />
                  </div>
                </div>
              );
            })}
            {data.by_model.length === 0 && (
              <p className="text-gray-400 text-sm">No model usage data</p>
            )}
          </div>
        </div>
      </div>

      {/* Usage by Tier and Top Users */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Usage by Tier */}
        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <h3 className="text-lg font-semibold text-white mb-4">Usage by Subscription Tier</h3>
          <div className="space-y-4">
            {data.by_tier.map((tier) => {
              const totalCost = data.by_tier.reduce((sum, t) => sum + t.cost_cents, 0);
              const percentage =
                totalCost > 0 ? ((tier.cost_cents / totalCost) * 100).toFixed(1) : 0;
              return (
                <div key={tier.tier} className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: getTierColor(tier.tier) }}
                    />
                    <div>
                      <span className="text-white capitalize">{tier.tier}</span>
                      <span className="text-gray-500 text-sm ml-2">({tier.users} users)</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-white">{formatCurrency(tier.cost_cents)}</div>
                    <div className="text-gray-500 text-sm">{percentage}%</div>
                  </div>
                </div>
              );
            })}
            {data.by_tier.length === 0 && (
              <p className="text-gray-400 text-sm">No tier usage data</p>
            )}
          </div>
        </div>

        {/* Top Users */}
        <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
          <h3 className="text-lg font-semibold text-white mb-4">Top Users by Spend</h3>
          <div className="space-y-3">
            {data.by_user.slice(0, 8).map((user, idx) => (
              <div key={user.user_id} className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className="text-gray-500 w-6 text-right">{idx + 1}.</span>
                  <div>
                    <div className="text-white">@{user.username}</div>
                    {user.email && <div className="text-gray-500 text-xs">{user.email}</div>}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-white font-medium">{formatCurrency(user.cost_cents)}</div>
                  <div className="text-gray-500 text-xs">
                    {formatNumber(user.tokens_in + user.tokens_out)} tokens
                  </div>
                </div>
              </div>
            ))}
            {data.by_user.length === 0 && (
              <p className="text-gray-400 text-sm">No user usage data</p>
            )}
          </div>
        </div>
      </div>

      {/* Anomaly Alerts */}
      {anomalies && anomalies.anomalies.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15">
          <div className="p-4 border-b border-[var(--text)]/15 flex items-center space-x-3">
            <AlertTriangle className="text-red-500" size={20} />
            <h3 className="text-lg font-semibold text-white">Anomaly Alerts</h3>
            <span className="text-gray-500 text-sm">
              Users with usage &gt;{anomalies.threshold}σ above average
            </span>
          </div>
          <div className="divide-y divide-gray-700">
            {anomalies.anomalies.map((anomaly) => (
              <div key={anomaly.user_id} className="p-4 flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      anomaly.severity === 'high' ? 'bg-red-500' : 'bg-yellow-500'
                    }`}
                  />
                  <div>
                    <div className="text-white">@{anomaly.username}</div>
                    {anomaly.email && <div className="text-gray-500 text-xs">{anomaly.email}</div>}
                  </div>
                </div>
                <div className="flex items-center space-x-6">
                  <div className="text-right">
                    <div className="text-white font-medium">
                      {formatCurrency(anomaly.cost_cents)}
                    </div>
                    <div className="text-gray-500 text-xs">{anomaly.request_count} requests</div>
                  </div>
                  <div
                    className={`px-3 py-1 rounded text-sm ${
                      anomaly.severity === 'high'
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-yellow-500/20 text-yellow-400'
                    }`}
                  >
                    {anomaly.deviation}σ
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="p-4 border-t border-[var(--text)]/15 text-gray-500 text-sm">
            Baseline: Mean {formatCurrency(anomalies.mean_cost_cents)}, Std Dev{' '}
            {formatCurrency(anomalies.std_cost_cents)}
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
        <h3 className="text-lg font-semibold text-white mb-4">Period Summary</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <div className="text-gray-400 text-sm">Input Tokens</div>
            <div className="text-white text-xl font-bold">
              {formatNumber(data.summary.tokens_in)}
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm">Output Tokens</div>
            <div className="text-white text-xl font-bold">
              {formatNumber(data.summary.tokens_out)}
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm">Models Used</div>
            <div className="text-white text-xl font-bold">{data.by_model.length}</div>
          </div>
          <div>
            <div className="text-gray-400 text-sm">Avg Cost/User</div>
            <div className="text-white text-xl font-bold">
              {formatCurrency(data.summary.cost_cents / Math.max(data.summary.active_users, 1))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
