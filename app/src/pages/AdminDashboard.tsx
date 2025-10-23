import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3,
  Users,
  Zap,
  Package,
  TrendingUp,
  TrendingDown,
  Coins,
  Timer,
  Activity,
  ShoppingCart,
  Database,
  ArrowUp,
  ArrowDown,
  Calendar,
  Download,
  RefreshCw
} from 'lucide-react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import toast from 'react-hot-toast';
// Using simple chart placeholders for now
// Will integrate charts later

interface MetricsSummary {
  users: {
    total: number;
    dau: number;
    mau: number;
    growth_rate: number;
  };
  projects: {
    total: number;
    new_this_week: number;
    avg_per_user: number;
  };
  sessions: {
    total_this_week: number;
    avg_per_user: number;
    avg_duration: number;
  };
  tokens: {
    total_this_week: number;
    total_cost: number;
    avg_per_user: number;
  };
  marketplace: {
    total_items: number;
    total_agents: number;
    total_bases: number;
    total_revenue: number;
    recent_purchases: number;
  };
}

interface DetailedMetrics {
  users?: any;
  projects?: any;
  sessions?: any;
  tokens?: any;
  marketplace?: any;
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [detailedMetrics, setDetailedMetrics] = useState<DetailedMetrics>({});
  const [selectedPeriod, setSelectedPeriod] = useState(7); // Days
  const [activeTab, setActiveTab] = useState('overview');
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    checkAdminAccess();
    loadMetrics();
  }, []);

  useEffect(() => {
    if (activeTab !== 'overview') {
      loadDetailedMetrics(activeTab);
    }
  }, [activeTab, selectedPeriod]);

  const checkAdminAccess = async () => {
    // Check if user is admin
    const token = localStorage.getItem('token');
    if (!token) {
      navigate('/login');
      return;
    }

    // Decode token to check admin status
    try {
      const user = JSON.parse(atob(token.split('.')[1]));
      // Check if is_admin flag is set in JWT token
      if (!user.is_admin) {
        toast.error('Admin access required');
        navigate('/');
      }
    } catch (error) {
      navigate('/login');
    }
  };

  const loadMetrics = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');

      const response = await fetch('/api/admin/metrics/summary', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        if (response.status === 403) {
          toast.error('Admin access required');
          navigate('/');
          return;
        }
        throw new Error('Failed to load metrics');
      }

      const data = await response.json();
      setSummary(data);
    } catch (error) {
      console.error('Failed to load metrics:', error);
      toast.error('Failed to load admin metrics');
    } finally {
      setLoading(false);
    }
  };

  const loadDetailedMetrics = async (metric: string) => {
    try {
      const token = localStorage.getItem('token');

      const response = await fetch(`/api/admin/metrics/${metric}?days=${selectedPeriod}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        throw new Error(`Failed to load ${metric} metrics`);
      }

      const data = await response.json();
      setDetailedMetrics(prev => ({
        ...prev,
        [metric]: data
      }));
    } catch (error) {
      console.error(`Failed to load ${metric} metrics:`, error);
      toast.error(`Failed to load ${metric} metrics`);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadMetrics();
    if (activeTab !== 'overview') {
      await loadDetailedMetrics(activeTab);
    }
    setRefreshing(false);
    toast.success('Metrics refreshed');
  };

  const formatNumber = (num: number) => {
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
  };

  const renderMetricCard = (title: string, value: any, change?: number, icon?: React.ReactNode, suffix?: string) => {
    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <span className="text-gray-400 text-sm font-medium">{title}</span>
          {icon && <div className="text-gray-500">{icon}</div>}
        </div>
        <div className="flex items-baseline justify-between">
          <h3 className="text-2xl font-bold text-white">
            {formatNumber(value)}{suffix}
          </h3>
          {change !== undefined && (
            <div className={`flex items-center text-sm ${change >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {change >= 0 ? <ArrowUp size={16} /> : <ArrowDown size={16} />}
              <span className="ml-1">{Math.abs(change)}%</span>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderUserChart = () => {
    if (!detailedMetrics.users?.daily_new_users) return null;

    const maxCount = Math.max(...detailedMetrics.users.daily_new_users.map((d: any) => d.count));

    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold text-white mb-4">User Growth</h3>
        <div className="h-64 flex items-end space-x-2">
          {detailedMetrics.users.daily_new_users.map((d: any, idx: number) => (
            <div key={idx} className="flex-1 flex flex-col items-center">
              <div
                className="w-full bg-green-500 rounded-t"
                style={{
                  height: `${maxCount > 0 ? (d.count / maxCount) * 100 : 0}%`,
                  minHeight: '2px'
                }}
              />
              <span className="text-xs text-gray-400 mt-2 rotate-45 origin-left">
                {new Date(d.date).toLocaleDateString('en', { month: 'short', day: 'numeric' })}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderTokenChart = () => {
    if (!detailedMetrics.tokens?.tokens_by_model) return null;

    const models = Object.keys(detailedMetrics.tokens.tokens_by_model);
    const tokens = models.map(m => detailedMetrics.tokens.tokens_by_model[m].tokens);
    const totalTokens = tokens.reduce((a, b) => a + b, 0);

    const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold text-white mb-4">Token Usage by Model</h3>
        <div className="space-y-3">
          {models.map((model, idx) => {
            const percentage = totalTokens > 0 ? (tokens[idx] / totalTokens * 100).toFixed(1) : 0;
            return (
              <div key={model} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-300">{model}</span>
                  <span className="text-gray-400">{formatNumber(tokens[idx])} ({percentage}%)</span>
                </div>
                <div className="w-full bg-gray-700 rounded-full h-2">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${percentage}%`,
                      backgroundColor: colors[idx % colors.length]
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <LoadingSpinner message="Loading admin dashboard..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Header */}
      <div className="bg-gray-800 border-b border-gray-700">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <BarChart3 className="text-blue-500" size={24} />
              <h1 className="text-xl font-bold text-white">Admin Dashboard</h1>
            </div>
            <div className="flex items-center space-x-4">
              <select
                value={selectedPeriod}
                onChange={(e) => setSelectedPeriod(Number(e.target.value))}
                className="bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600"
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
              </select>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="bg-gray-700 text-white rounded-lg px-4 py-2 text-sm hover:bg-gray-600 flex items-center space-x-2"
              >
                <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
                <span>Refresh</span>
              </button>
              <button
                onClick={() => navigate('/')}
                className="bg-gray-700 text-white rounded-lg px-4 py-2 text-sm hover:bg-gray-600"
              >
                Back to App
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-gray-800 border-b border-gray-700">
        <div className="container mx-auto px-4">
          <div className="flex space-x-8">
            {['overview', 'users', 'projects', 'sessions', 'tokens', 'marketplace'].map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`py-3 px-1 capitalize border-b-2 transition-colors ${
                  activeTab === tab
                    ? 'border-blue-500 text-blue-500'
                    : 'border-transparent text-gray-400 hover:text-white'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="container mx-auto px-4 py-8">
        {activeTab === 'overview' && summary && (
          <>
            {/* Key Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {renderMetricCard('Total Users', summary.users.total, summary.users.growth_rate, <Users size={20} />)}
              {renderMetricCard('DAU', summary.users.dau, undefined, <Activity size={20} />)}
              {renderMetricCard('MAU', summary.users.mau, undefined, <Calendar size={20} />)}
              {renderMetricCard('Total Projects', summary.projects.total, undefined, <Package size={20} />)}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {renderMetricCard('Sessions/User', summary.sessions.avg_per_user.toFixed(1), undefined, <Timer size={20} />)}
              {renderMetricCard('Avg Duration', summary.sessions.avg_duration.toFixed(0), undefined, <Timer size={20} />, ' min')}
              {renderMetricCard('Tokens Used', summary.tokens.total_this_week, undefined, <Zap size={20} />)}
              {renderMetricCard('Token Cost', summary.tokens.total_cost.toFixed(2), undefined, <Coins size={20} />, ' $')}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Marketplace Items', summary.marketplace.total_items, undefined, <ShoppingCart size={20} />)}
              {renderMetricCard('Agents', summary.marketplace.total_agents, undefined, <Users size={20} />)}
              {renderMetricCard('Bases', summary.marketplace.total_bases, undefined, <Database size={20} />)}
              {renderMetricCard('Recent Purchases', summary.marketplace.recent_purchases, undefined, <TrendingUp size={20} />)}
            </div>
          </>
        )}

        {activeTab === 'users' && detailedMetrics.users && (
          <div className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Total Users', detailedMetrics.users.total_users)}
              {renderMetricCard('New Users', detailedMetrics.users.new_users)}
              {renderMetricCard('Growth Rate', detailedMetrics.users.growth_rate, undefined, undefined, '%')}
              {renderMetricCard('Retention', detailedMetrics.users.retention_rate, undefined, undefined, '%')}
            </div>
            {renderUserChart()}
          </div>
        )}

        {activeTab === 'projects' && detailedMetrics.projects && (
          <div className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Total Projects', detailedMetrics.projects.total_projects)}
              {renderMetricCard('New Projects', detailedMetrics.projects.new_projects)}
              {renderMetricCard('Avg per User', detailedMetrics.projects.avg_projects_per_user.toFixed(1))}
              {renderMetricCard('Git Enabled', detailedMetrics.projects.git_enabled_projects)}
            </div>
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Project Creation Over Time</h3>
              <div className="h-64 flex items-end space-x-1">
                {detailedMetrics.projects.daily_projects?.map((d: any, idx: number) => {
                  const maxCount = Math.max(...detailedMetrics.projects.daily_projects.map((d: any) => d.count), 1);
                  return (
                    <div key={idx} className="flex-1 flex flex-col items-center group">
                      <div
                        className="w-full bg-blue-500 rounded-t transition-opacity hover:opacity-80"
                        style={{
                          height: `${(d.count / maxCount) * 100}%`,
                          minHeight: d.count > 0 ? '4px' : '2px'
                        }}
                        title={`${new Date(d.date).toLocaleDateString()}: ${d.count} projects`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'sessions' && detailedMetrics.sessions && (
          <div className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Total Sessions', detailedMetrics.sessions.total_sessions)}
              {renderMetricCard('Unique Users', detailedMetrics.sessions.unique_users)}
              {renderMetricCard('Avg per User', detailedMetrics.sessions.avg_sessions_per_user.toFixed(1))}
              {renderMetricCard('Avg Duration', detailedMetrics.sessions.avg_session_duration.toFixed(0), undefined, undefined, ' min')}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <h3 className="text-lg font-semibold text-white mb-4">Sessions Over Time</h3>
                <div className="h-64 flex items-end space-x-1">
                  {detailedMetrics.sessions.daily_sessions?.map((d: any, idx: number) => {
                    const maxCount = Math.max(...detailedMetrics.sessions.daily_sessions.map((d: any) => d.count), 1);
                    return (
                      <div key={idx} className="flex-1 flex flex-col items-center">
                        <div
                          className="w-full bg-purple-500 rounded-t"
                          style={{
                            height: `${(d.count / maxCount) * 100}%`,
                            minHeight: d.count > 0 ? '4px' : '2px'
                          }}
                          title={`${new Date(d.date).toLocaleDateString()}: ${d.count} sessions`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <h3 className="text-lg font-semibold text-white mb-4">Session Metrics</h3>
                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between mb-1">
                      <span className="text-gray-400">Avg Messages per Session</span>
                      <span className="text-white font-medium">{detailedMetrics.sessions.avg_messages_per_session?.toFixed(1) || 0}</span>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between mb-1">
                      <span className="text-gray-400">Avg Session Duration</span>
                      <span className="text-white font-medium">{detailedMetrics.sessions.avg_session_duration?.toFixed(0) || 0} min</span>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between mb-1">
                      <span className="text-gray-400">Total Sessions</span>
                      <span className="text-white font-medium">{detailedMetrics.sessions.total_sessions}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'tokens' && detailedMetrics.tokens && (
          <div className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Total Tokens', detailedMetrics.tokens.total_tokens)}
              {renderMetricCard('Total Cost', detailedMetrics.tokens.total_cost.toFixed(2), undefined, undefined, '$')}
              {renderMetricCard('Active Users', detailedMetrics.tokens.active_users)}
              {renderMetricCard('Avg/User', detailedMetrics.tokens.avg_tokens_per_user)}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {renderTokenChart()}
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <h3 className="text-lg font-semibold text-white mb-4">Top Users by Token Usage</h3>
                <div className="space-y-2">
                  {detailedMetrics.tokens.top_users?.slice(0, 5).map((user: any, idx: number) => (
                    <div key={idx} className="flex items-center justify-between">
                      <span className="text-gray-300">{user.user_id}</span>
                      <div className="text-right">
                        <div className="text-white font-medium">{formatNumber(user.total_tokens)}</div>
                        <div className="text-gray-500 text-sm">${user.total_cost.toFixed(2)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'marketplace' && detailedMetrics.marketplace && (
          <div className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {renderMetricCard('Total Items', detailedMetrics.marketplace.total_items)}
              {renderMetricCard('Total Purchases', detailedMetrics.marketplace.total_purchases)}
              {renderMetricCard('Recent Purchases', detailedMetrics.marketplace.recent_purchases)}
              {renderMetricCard('Total Revenue', detailedMetrics.marketplace.total_revenue.toFixed(2), undefined, undefined, '$')}
            </div>

            {/* Agents Section */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Agents Marketplace</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <div>
                  <div className="text-gray-400 text-sm">Total Agents</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.agents?.total || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm">Agent Purchases</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.agents?.total_purchases || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm">Adoption Rate</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.agents?.adoption_rate?.toFixed(1) || 0}%</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm">Recent Purchases</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.agents?.recent_purchases || 0}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                  <h4 className="text-md font-semibold text-white mb-3">Popular Agents (by purchases)</h4>
                  <div className="space-y-2">
                    {detailedMetrics.marketplace.agents?.popular?.map((agent: any, idx: number) => (
                      <div key={idx} className="flex items-center justify-between bg-gray-700/50 rounded p-3">
                        <div>
                          <div className="text-white font-medium">{agent.name}</div>
                          <div className="text-gray-400 text-sm">/{agent.slug}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-white font-medium">{agent.purchases} purchases</div>
                          <div className="text-gray-400 text-sm">{agent.usage_count} uses</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="text-md font-semibold text-white mb-3">Most Used Agents</h4>
                  <div className="space-y-2">
                    {detailedMetrics.marketplace.agents?.most_used && detailedMetrics.marketplace.agents.most_used.length > 0 ? (
                      detailedMetrics.marketplace.agents.most_used.map((agent: any, idx: number) => (
                        <div key={idx} className="flex items-center justify-between bg-gray-700/50 rounded p-3">
                          <div>
                            <div className="text-white font-medium">{agent.name}</div>
                            <div className="text-gray-400 text-sm">/{agent.slug}</div>
                          </div>
                          <div className="text-white font-medium">{agent.usage_count} uses</div>
                        </div>
                      ))
                    ) : (
                      <div className="text-gray-400 text-sm">No usage data yet</div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Bases Section */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Bases Marketplace</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                <div>
                  <div className="text-gray-400 text-sm">Total Bases</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.bases?.total || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm">Base Purchases</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.bases?.total_purchases || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm">Recent Purchases</div>
                  <div className="text-white text-2xl font-bold">{detailedMetrics.marketplace.bases?.recent_purchases || 0}</div>
                </div>
              </div>

              <div>
                <h4 className="text-md font-semibold text-white mb-3">Popular Bases</h4>
                <div className="space-y-2">
                  {detailedMetrics.marketplace.bases?.popular?.map((base: any, idx: number) => (
                    <div key={idx} className="flex items-center justify-between bg-gray-700/50 rounded p-3">
                      <div>
                        <div className="text-white font-medium">{base.name}</div>
                        <div className="text-gray-400 text-sm">/{base.slug}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-white font-medium">{base.purchases} purchases</div>
                        <div className="text-gray-400 text-sm">{base.downloads} downloads</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}