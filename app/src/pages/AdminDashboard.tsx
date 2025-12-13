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
import { getAuthHeaders } from '../lib/api';
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
    loadMetrics();
  }, []);

  useEffect(() => {
    if (activeTab !== 'overview' && activeTab !== 'agents') {
      loadDetailedMetrics(activeTab);
    }
  }, [activeTab, selectedPeriod]);

  const loadMetrics = async () => {
    try {
      setLoading(true);

      const response = await fetch('/api/admin/metrics/summary', {
        headers: getAuthHeaders(),
        credentials: 'include'
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
      const response = await fetch(`/api/admin/metrics/${metric}?days=${selectedPeriod}`, {
        headers: getAuthHeaders(),
        credentials: 'include'
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
      <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
      <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
      <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
      <div className="bg-gray-800 border-b border-[var(--text)]/15">
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
                className="bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
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
      <div className="bg-gray-800 border-b border-[var(--text)]/15">
        <div className="container mx-auto px-4">
          <div className="flex space-x-8">
            {['overview', 'users', 'projects', 'sessions', 'tokens', 'marketplace', 'agents'].map(tab => (
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
            <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
              <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
              <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
              <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
            <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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
            <div className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15">
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

        {activeTab === 'agents' && (
          <AgentManagement />
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Agent Management Component
// ============================================================================

interface Agent {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  mode: string;
  agent_type: string;
  model: string;
  icon: string;
  pricing_type: string;
  price: number;
  api_pricing_input: number;
  api_pricing_output: number;
  source_type: string;
  is_forkable: boolean;
  requires_user_keys: boolean;
  is_featured: boolean;
  is_active: boolean;
  usage_count: number;
  created_at: string;
  created_by_tesslate: boolean;
  created_by_username: string | null;
  forked_by_username: string | null;
  can_edit: boolean;
}

interface AgentDetailed extends Agent {
  long_description: string;
  system_prompt: string;
  features: string[];
  required_models: string[];
  tags: string[];
  is_published: boolean;
  updated_at: string | null;
}

function AgentManagement() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentDetailed | null>(null);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [filter, setFilter] = useState({
    source_type: '',
    pricing_type: '',
    is_active: ''
  });

  useEffect(() => {
    loadAgents();
    loadAvailableModels();
  }, [filter]);

  const loadAgents = async () => {
    try {
      setLoading(true);

      // Build query params
      const params = new URLSearchParams();
      if (filter.source_type) params.append('source_type', filter.source_type);
      if (filter.pricing_type) params.append('pricing_type', filter.pricing_type);
      if (filter.is_active) params.append('is_active', filter.is_active);

      const response = await fetch(`/api/admin/agents?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to load agents');

      const data = await response.json();
      setAgents(data.agents || []);
    } catch (error) {
      console.error('Failed to load agents:', error);
      toast.error('Failed to load agents');
    } finally {
      setLoading(false);
    }
  };

  const loadAvailableModels = async () => {
    try {
      const response = await fetch('/api/admin/models', {
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to load models');

      const data = await response.json();
      setAvailableModels(data.models || []);
    } catch (error) {
      console.error('Failed to load models:', error);
    }
  };

  const loadAgentDetails = async (agentId: number) => {
    try {
      const response = await fetch(`/api/admin/agents/${agentId}`, {
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to load agent details');

      const data = await response.json();
      setSelectedAgent(data);
      setShowEditModal(true);
    } catch (error) {
      console.error('Failed to load agent details:', error);
      toast.error('Failed to load agent details');
    }
  };

  const handleDelete = async (agent: Agent) => {
    if (!agent.can_edit) {
      toast.error('Cannot delete user-created agents');
      return;
    }

    if (!confirm(`Are you sure you want to delete "${agent.name}"? This cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`/api/admin/agents/${agent.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete agent');
      }

      toast.success('Agent deleted successfully');
      loadAgents();
    } catch (error: any) {
      console.error('Failed to delete agent:', error);
      toast.error(error.message || 'Failed to delete agent');
    }
  };

  const handleRemoveFromMarketplace = async (agent: Agent) => {
    if (!confirm(`Remove "${agent.name}" from the marketplace?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/admin/agents/${agent.id}/remove-from-marketplace`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to remove agent');

      toast.success('Agent removed from marketplace');
      loadAgents();
    } catch (error) {
      console.error('Failed to remove agent:', error);
      toast.error('Failed to remove agent');
    }
  };

  const handleToggleFeatured = async (agent: Agent) => {
    try {
      const response = await fetch(`/api/admin/agents/${agent.id}/feature?is_featured=${!agent.is_featured}`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to toggle featured');

      toast.success(`Agent ${!agent.is_featured ? 'featured' : 'unfeatured'}`);
      loadAgents();
    } catch (error) {
      console.error('Failed to toggle featured:', error);
      toast.error('Failed to toggle featured status');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner message="Loading agents..." size={60} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white">Agent Management</h2>
        <button
          onClick={() => setShowCreateModal(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center space-x-2"
        >
          <span>+ Create Agent</span>
        </button>
      </div>

      {/* Filters */}
      <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <select
            value={filter.source_type}
            onChange={(e) => setFilter({...filter, source_type: e.target.value})}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Source Types</option>
            <option value="open">Open Source</option>
            <option value="closed">Closed Source</option>
          </select>

          <select
            value={filter.pricing_type}
            onChange={(e) => setFilter({...filter, pricing_type: e.target.value})}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Pricing Types</option>
            <option value="free">Free</option>
            <option value="monthly">Monthly</option>
            <option value="api">API Pricing</option>
            <option value="one_time">One Time</option>
          </select>

          <select
            value={filter.is_active}
            onChange={(e) => setFilter({...filter, is_active: e.target.value})}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </div>
      </div>

      {/* Agents List */}
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-750 border-b border-[var(--text)]/15">
            <tr>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Agent</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Category</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Model</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Pricing</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Source</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Usage</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Status</th>
              <th className="text-right px-6 py-3 text-gray-400 font-medium text-sm">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {agents.map((agent) => (
              <tr key={agent.id} className="hover:bg-gray-700/50 transition-colors">
                <td className="px-6 py-4">
                  <div className="flex items-center space-x-3">
                    <span className="text-2xl">{agent.icon}</span>
                    <div>
                      <div className="text-white font-medium">{agent.name}</div>
                      <div className="text-gray-400 text-sm">/{agent.slug}</div>
                      {!agent.can_edit && (
                        <div className="text-yellow-500 text-xs mt-1">
                          {agent.created_by_username ? `By ${agent.created_by_username}` : agent.forked_by_username ? `Forked by ${agent.forked_by_username}` : 'User-created'}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-gray-300 capitalize">{agent.category}</span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-gray-300 text-sm font-mono">{agent.model}</span>
                </td>
                <td className="px-6 py-4">
                  <div>
                    <span className="text-gray-300 capitalize">{agent.pricing_type}</span>
                    {agent.pricing_type === 'monthly' && (
                      <div className="text-gray-400 text-sm">${(agent.price / 100).toFixed(2)}/mo</div>
                    )}
                    {agent.pricing_type === 'api' && (
                      <div className="text-gray-400 text-xs">
                        <div>In: ${agent.api_pricing_input}/M</div>
                        <div>Out: ${agent.api_pricing_output}/M</div>
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs ${agent.source_type === 'open' ? 'bg-green-500/20 text-green-400' : 'bg-blue-500/20 text-blue-400'}`}>
                    {agent.source_type}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-gray-300">{agent.usage_count}</span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-col space-y-1">
                    <span className={`px-2 py-1 rounded text-xs w-fit ${agent.is_active ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                      {agent.is_active ? 'Active' : 'Inactive'}
                    </span>
                    {agent.is_featured && (
                      <span className="px-2 py-1 rounded text-xs w-fit bg-yellow-500/20 text-yellow-400">
                        Featured
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center justify-end space-x-2">
                    <button
                      onClick={() => loadAgentDetails(agent.id)}
                      className="text-blue-400 hover:text-blue-300 text-sm"
                      title={agent.can_edit ? "Edit agent" : "View agent"}
                    >
                      {agent.can_edit ? 'Edit' : 'View'}
                    </button>
                    <button
                      onClick={() => handleToggleFeatured(agent)}
                      className="text-yellow-400 hover:text-yellow-300 text-sm"
                      title={agent.is_featured ? "Unfeature" : "Feature"}
                    >
                      {agent.is_featured ? '★' : '☆'}
                    </button>
                    {agent.is_active && (
                      <button
                        onClick={() => handleRemoveFromMarketplace(agent)}
                        className="text-[var(--primary)] hover:text-[var(--primary-hover)] text-sm"
                        title="Remove from marketplace"
                      >
                        Hide
                      </button>
                    )}
                    {agent.can_edit && (
                      <button
                        onClick={() => handleDelete(agent)}
                        className="text-red-400 hover:text-red-300 text-sm"
                        title="Delete agent"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {agents.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            No agents found
          </div>
        )}
      </div>

      {/* Create/Edit Modals */}
      {showCreateModal && (
        <AgentFormModal
          availableModels={availableModels}
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            loadAgents();
          }}
        />
      )}

      {showEditModal && selectedAgent && (
        <AgentFormModal
          agent={selectedAgent}
          availableModels={availableModels}
          onClose={() => {
            setShowEditModal(false);
            setSelectedAgent(null);
          }}
          onSuccess={() => {
            setShowEditModal(false);
            setSelectedAgent(null);
            loadAgents();
          }}
        />
      )}
    </div>
  );
}

// ============================================================================
// Agent Form Modal Component
// ============================================================================

interface AgentFormModalProps {
  agent?: AgentDetailed;
  availableModels: string[];
  onClose: () => void;
  onSuccess: () => void;
}

function AgentFormModal({ agent, availableModels, onClose, onSuccess }: AgentFormModalProps) {
  const isEdit = !!agent;
  const canEdit = !agent || agent.can_edit;

  // Agent type to mode mapping
  const agentTypeToMode: Record<string, string> = {
    'StreamAgent': 'stream',
    'IterativeAgent': 'agent'
  };

  const [formData, setFormData] = useState({
    name: agent?.name || '',
    description: agent?.description || '',
    long_description: agent?.long_description || '',
    category: agent?.category || 'builder',
    system_prompt: agent?.system_prompt || '',
    agent_type: agent?.agent_type || 'StreamAgent',
    model: agent?.model || (availableModels[0] || ''),
    icon: agent?.icon || '🤖',
    pricing_type: agent?.pricing_type || 'free',
    price: agent?.price ? (agent.price / 100) : 0,
    api_pricing_input: agent?.api_pricing_input || 0,
    api_pricing_output: agent?.api_pricing_output || 0,
    source_type: agent?.source_type || 'closed',
    is_forkable: agent?.is_forkable || false,
    requires_user_keys: agent?.requires_user_keys || false,
    features: agent?.features?.join(', ') || '',
    tags: agent?.tags?.join(', ') || '',
    is_featured: agent?.is_featured || false,
    is_active: agent?.is_active !== undefined ? agent.is_active : true
  });

  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!canEdit) {
      toast.error('Cannot edit this agent');
      return;
    }

    setSaving(true);

    try {
      // Prepare payload
      const payload = {
        ...formData,
        mode: agentTypeToMode[formData.agent_type] || 'stream', // Infer mode from agent type
        price: formData.pricing_type === 'monthly' || formData.pricing_type === 'one_time' ? Math.round(formData.price * 100) : 0,
        api_pricing_input: formData.pricing_type === 'api' ? parseFloat(formData.api_pricing_input.toString()) : 0,
        api_pricing_output: formData.pricing_type === 'api' ? parseFloat(formData.api_pricing_output.toString()) : 0,
        features: formData.features.split(',').map(f => f.trim()).filter(f => f),
        required_models: [], // Empty array - not used
        tags: formData.tags.split(',').map(t => t.trim()).filter(t => t)
      };

      const url = isEdit ? `/api/admin/agents/${agent.id}` : '/api/admin/agents';
      const method = isEdit ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save agent');
      }

      toast.success(`Agent ${isEdit ? 'updated' : 'created'} successfully`);
      onSuccess();
    } catch (error: any) {
      console.error('Failed to save agent:', error);
      toast.error(error.message || 'Failed to save agent');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-4xl w-full my-8">
        <div className="p-6 border-b border-[var(--text)]/15">
          <h2 className="text-2xl font-bold text-white">
            {isEdit ? (canEdit ? 'Edit Agent' : 'View Agent') : 'Create New Agent'}
          </h2>
          {isEdit && !canEdit && (
            <p className="text-yellow-500 text-sm mt-2">
              This is a user-created agent. You can only view it, not edit it.
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Basic Info */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Name *</label>
              <input
                type="text"
                required
                disabled={!canEdit}
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Icon</label>
              <input
                type="text"
                disabled={!canEdit}
                value={formData.icon}
                onChange={(e) => setFormData({...formData, icon: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                placeholder="🤖"
              />
            </div>
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Description *</label>
            <input
              type="text"
              required
              disabled={!canEdit}
              value={formData.description}
              onChange={(e) => setFormData({...formData, description: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              maxLength={500}
            />
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Long Description *</label>
            <textarea
              required
              disabled={!canEdit}
              value={formData.long_description}
              onChange={(e) => setFormData({...formData, long_description: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              rows={3}
            />
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">System Prompt *</label>
            <textarea
              required
              disabled={!canEdit}
              value={formData.system_prompt}
              onChange={(e) => setFormData({...formData, system_prompt: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 font-mono text-sm disabled:opacity-50"
              rows={6}
            />
          </div>

          {/* Configuration */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">
                Category *
                <span className="text-gray-500 font-normal text-xs ml-2">(e.g., builder, fullstack, data)</span>
              </label>
              <input
                type="text"
                required
                disabled={!canEdit}
                value={formData.category}
                onChange={(e) => setFormData({...formData, category: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                placeholder="builder"
              />
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">
                Agent Type *
                <span className="text-gray-500 font-normal text-xs ml-2">(determines mode automatically)</span>
              </label>
              <select
                required
                disabled={!canEdit}
                value={formData.agent_type}
                onChange={(e) => setFormData({...formData, agent_type: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                <option value="StreamAgent">StreamAgent (streaming mode)</option>
                <option value="IterativeAgent">IterativeAgent (agent mode)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">
                Model *
                <span className="text-gray-500 font-normal text-xs ml-2">(LiteLLM model - fixed for closed source, suggestion for open source)</span>
              </label>
              <select
                required
                disabled={!canEdit}
                value={formData.model}
                onChange={(e) => setFormData({...formData, model: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                {availableModels.map(model => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Source Type *</label>
              <select
                required
                disabled={!canEdit}
                value={formData.source_type}
                onChange={(e) => setFormData({...formData, source_type: e.target.value})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                <option value="closed">Closed Source</option>
                <option value="open">Open Source</option>
              </select>
            </div>
          </div>

          {/* Pricing */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Pricing Type *</label>
            <select
              required
              disabled={!canEdit}
              value={formData.pricing_type}
              onChange={(e) => setFormData({...formData, pricing_type: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
            >
              <option value="free">Free</option>
              <option value="monthly">Monthly Subscription</option>
              <option value="api">API Pricing (per token)</option>
              <option value="one_time">One-Time Purchase</option>
            </select>
          </div>

          {(formData.pricing_type === 'monthly' || formData.pricing_type === 'one_time') && (
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">
                Price ($) {formData.pricing_type === 'monthly' ? '/ month' : ''}
              </label>
              <input
                type="number"
                step="0.01"
                disabled={!canEdit}
                value={formData.price}
                onChange={(e) => setFormData({...formData, price: parseFloat(e.target.value) || 0})}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                min="0"
                placeholder="e.g., 9.99"
              />
            </div>
          )}

          {formData.pricing_type === 'api' && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-gray-300 text-sm font-medium mb-2">
                  Input Pricing ($/M tokens)
                </label>
                <input
                  type="number"
                  step="0.01"
                  disabled={!canEdit}
                  value={formData.api_pricing_input}
                  onChange={(e) => setFormData({...formData, api_pricing_input: parseFloat(e.target.value) || 0})}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                  min="0"
                  placeholder="e.g., 0.50"
                />
              </div>
              <div>
                <label className="block text-gray-300 text-sm font-medium mb-2">
                  Output Pricing ($/M tokens)
                </label>
                <input
                  type="number"
                  step="0.01"
                  disabled={!canEdit}
                  value={formData.api_pricing_output}
                  onChange={(e) => setFormData({...formData, api_pricing_output: parseFloat(e.target.value) || 0})}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                  min="0"
                  placeholder="e.g., 1.50"
                />
              </div>
            </div>
          )}

          {/* Lists */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">
              Features (comma-separated)
            </label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.features}
              onChange={(e) => setFormData({...formData, features: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="Real-time streaming, Code generation"
            />
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">
              Tags (comma-separated)
            </label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.tags}
              onChange={(e) => setFormData({...formData, tags: e.target.value})}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="react, typescript, streaming"
            />
          </div>

          {/* Flags */}
          <div className="grid grid-cols-2 gap-4">
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.is_forkable}
                onChange={(e) => setFormData({...formData, is_forkable: e.target.checked})}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">Is Forkable (open source only)</span>
            </label>

            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.requires_user_keys}
                onChange={(e) => setFormData({...formData, requires_user_keys: e.target.checked})}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">
                Requires User Keys
                <span className="text-gray-500 font-normal text-xs ml-2">(user must provide their own API keys)</span>
              </span>
            </label>

            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.is_featured}
                onChange={(e) => setFormData({...formData, is_featured: e.target.checked})}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">Featured</span>
            </label>

            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.is_active}
                onChange={(e) => setFormData({...formData, is_active: e.target.checked})}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">Active</span>
            </label>
          </div>
        </form>

        <div className="p-6 border-t border-[var(--text)]/15 flex items-center justify-end space-x-4">
          <button
            type="button"
            onClick={onClose}
            className="px-6 py-2 rounded-lg bg-gray-700 text-white hover:bg-gray-600"
          >
            {canEdit ? 'Cancel' : 'Close'}
          </button>
          {canEdit && (
            <button
              type="submit"
              disabled={saving}
              onClick={handleSubmit}
              className="px-6 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center space-x-2"
            >
              {saving ? (
                <>
                  <RefreshCw size={16} className="animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <span>{isEdit ? 'Update Agent' : 'Create Agent'}</span>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}