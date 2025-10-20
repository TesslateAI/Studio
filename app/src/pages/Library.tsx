import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Package,
  Pencil,
  Power,
  Cpu,
  GitFork,
  LockSimpleOpen,
  LockKey,
  Sparkle,
  ArrowLeft,
  Check,
  XCircle,
  Rocket
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';

interface LibraryAgent {
  id: number;
  name: string;
  slug: string;
  description: string;
  category: string;
  mode: string;
  agent_type: string;
  model: string;
  source_type: 'open' | 'closed';
  is_forkable: boolean;
  icon: string;
  pricing_type: string;
  features: string[];
  purchase_date: string;
  purchase_type: string;
  expires_at: string | null;
  is_custom: boolean;
  parent_agent_id: number | null;
  system_prompt?: string;
  is_enabled?: boolean;
  is_published?: boolean;
  usage_count?: number;
}

export default function Library() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<LibraryAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingAgent, setEditingAgent] = useState<LibraryAgent | null>(null);

  useEffect(() => {
    loadLibraryAgents();
  }, []);

  const loadLibraryAgents = async () => {
    try {
      const data = await marketplaceApi.getMyAgents();
      setAgents(data.agents || []);
    } catch (error) {
      console.error('Failed to load library:', error);
      toast.error('Failed to load library');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleEnable = async (agent: LibraryAgent) => {
    try {
      const newState = !agent.is_enabled;
      await marketplaceApi.toggleAgent(agent.id, newState);
      toast.success(`Agent ${newState ? 'enabled' : 'disabled'}`);
      loadLibraryAgents(); // Reload to update state
    } catch (error) {
      console.error('Toggle failed:', error);
      toast.error('Failed to toggle agent');
    }
  };

  const handleEditAgent = (agent: LibraryAgent) => {
    setEditingAgent(agent);
  };

  const handleTogglePublish = async (agent: LibraryAgent) => {
    try {
      if (agent.is_published) {
        await marketplaceApi.unpublishAgent(agent.id);
        toast.success('Agent unpublished from marketplace');
      } else {
        await marketplaceApi.publishAgent(agent.id);
        toast.success('Agent published to community marketplace! 🎉');
      }
      loadLibraryAgents(); // Reload to update state
    } catch (error: any) {
      console.error('Publish toggle failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to toggle publish status');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <LoadingSpinner message="Loading library..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Header */}
      <div className="border-b border-white/10 bg-[var(--surface)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-3xl font-bold text-[var(--text)] mb-2">My Library</h1>
              <p className="text-[var(--text)]/60">Manage your agents and customize them for your projects</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate('/marketplace')}
                className="px-4 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
              >
                <Sparkle size={18} />
                Browse Marketplace
              </button>
              <button
                onClick={() => navigate('/dashboard')}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors flex items-center gap-2"
              >
                <ArrowLeft size={18} />
                Back to Dashboard
              </button>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4">
            <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
              <div className="text-2xl font-bold text-[var(--text)] mb-1">{agents.length}</div>
              <div className="text-sm text-[var(--text)]/60">Total Agents</div>
            </div>
            <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
              <div className="text-2xl font-bold text-green-400 mb-1">
                {agents.filter(a => a.is_enabled).length}
              </div>
              <div className="text-sm text-[var(--text)]/60">Enabled</div>
            </div>
            <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
              <div className="text-2xl font-bold text-orange-400 mb-1">
                {agents.filter(a => a.is_custom).length}
              </div>
              <div className="text-sm text-[var(--text)]/60">Custom Agents</div>
            </div>
          </div>
        </div>
      </div>

      {/* Agents Grid */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {agents.map(agent => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onToggleEnable={() => handleToggleEnable(agent)}
              onEdit={() => handleEditAgent(agent)}
              onTogglePublish={() => handleTogglePublish(agent)}
            />
          ))}
        </div>

        {agents.length === 0 && (
          <div className="text-center py-16">
            <Package size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
            <p className="text-[var(--text)]/60 mb-4">Your library is empty</p>
            <button
              onClick={() => navigate('/marketplace')}
              className="px-6 py-3 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors"
            >
              Browse Marketplace
            </button>
          </div>
        )}
      </div>

      {/* Edit Agent Modal */}
      {editingAgent && (
        <EditAgentModal
          agent={editingAgent}
          onClose={() => setEditingAgent(null)}
          onSave={async (updatedData) => {
            try {
              const response = await marketplaceApi.updateAgent(editingAgent.id, updatedData);
              if (response.forked) {
                toast.success('Created a custom fork with your changes!');
              } else {
                toast.success('Agent updated successfully');
              }
              setEditingAgent(null);
              loadLibraryAgents();
            } catch (error: any) {
              console.error('Update failed:', error);
              toast.error(error.response?.data?.detail || 'Failed to update agent');
            }
          }}
        />
      )}
    </div>
  );
}

// Agent Card Component
function AgentCard({
  agent,
  onToggleEnable,
  onEdit,
  onTogglePublish
}: {
  agent: LibraryAgent;
  onToggleEnable: () => void;
  onEdit: () => void;
  onTogglePublish: () => void;
}) {
  const canEdit = agent.source_type === 'open' || agent.is_custom;

  return (
    <div className="bg-[var(--surface)] border border-white/10 rounded-xl p-6 hover:border-orange-500/30 transition-all">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="text-3xl">{agent.icon}</div>
          <div>
            <h3 className="font-semibold text-[var(--text)] text-lg">{agent.name}</h3>
            <div className="flex items-center gap-2 mt-1">
              {agent.source_type === 'open' ? (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">
                  <LockSimpleOpen size={10} />
                  Open
                </span>
              ) : (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">
                  <LockKey size={10} />
                  Pro
                </span>
              )}
              {agent.is_custom && (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-orange-500/20 text-orange-400 text-xs rounded">
                  <GitFork size={10} />
                  Custom
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Enable/Disable Toggle */}
        <button
          onClick={onToggleEnable}
          className={`p-2 rounded-lg transition-colors ${
            agent.is_enabled
              ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
              : 'bg-white/5 text-[var(--text)]/40 hover:bg-white/10'
          }`}
          title={agent.is_enabled ? 'Disable agent' : 'Enable agent'}
        >
          {agent.is_enabled ? <Power size={20} weight="fill" /> : <Power size={20} />}
        </button>
      </div>

      {/* Description */}
      <p className="text-[var(--text)]/60 text-sm mb-4 line-clamp-2">{agent.description}</p>

      {/* Model Badge */}
      <div className="mb-4">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 border border-blue-500/20 rounded-lg w-fit">
          <Cpu size={14} className="text-blue-400" />
          <span className="text-xs text-blue-400 font-medium">{agent.model}</span>
        </div>
      </div>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mb-4">
        {agent.features.slice(0, 3).map((feature, idx) => (
          <span
            key={idx}
            className="px-2 py-1 bg-white/5 text-[var(--text)]/60 text-xs rounded"
          >
            {feature}
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-4 border-t border-white/10">
        {canEdit && (
          <button
            onClick={onEdit}
            className="flex-1 py-2 px-3 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <Pencil size={16} />
            Edit
          </button>
        )}
        {agent.is_custom && (
          <button
            onClick={onTogglePublish}
            className={`flex-1 py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-2 ${
              agent.is_published
                ? 'bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400'
                : 'bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 text-purple-400'
            }`}
          >
            {agent.is_published ? (
              <>
                <Check size={16} />
                Published
              </>
            ) : (
              <>
                <Rocket size={16} />
                Publish
              </>
            )}
          </button>
        )}
        <button
          onClick={onToggleEnable}
          className={`flex-1 py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-2 ${
            agent.is_enabled
              ? 'bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400'
              : 'bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400'
          }`}
        >
          {agent.is_enabled ? (
            <>
              <XCircle size={16} />
              Disable
            </>
          ) : (
            <>
              <Power size={16} />
              Enable
            </>
          )}
        </button>
      </div>

      {/* Purchase Date */}
      <div className="mt-4 text-xs text-[var(--text)]/40">
        Added {new Date(agent.purchase_date).toLocaleDateString()}
      </div>
    </div>
  );
}

// Edit Agent Modal Component
function EditAgentModal({
  agent,
  onClose,
  onSave
}: {
  agent: LibraryAgent;
  onClose: () => void;
  onSave: (data: { name?: string; description?: string; system_prompt?: string; model?: string }) => void;
}) {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt || '');
  const [model, setModel] = useState(agent.model);
  const [originalPrompt, setOriginalPrompt] = useState(agent.system_prompt || '');
  const [loading, setLoading] = useState(false);

  // Load parent agent's system prompt if this is a forked agent
  useEffect(() => {
    const loadOriginal = async () => {
      if (agent.parent_agent_id) {
        setLoading(true);
        try {
          // Fetch parent agent details to get original system prompt
          // For now, we'll use the current prompt as original
          // TODO: Implement parent agent fetch if needed
          setOriginalPrompt(agent.system_prompt || '');
        } catch (error) {
          console.error('Failed to load original prompt:', error);
        } finally {
          setLoading(false);
        }
      }
    };
    loadOriginal();
  }, [agent.parent_agent_id, agent.system_prompt]);

  const handleReset = () => {
    setSystemPrompt(originalPrompt);
    toast.success('Reset to original system prompt');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      name,
      description,
      system_prompt: systemPrompt,
      model
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Pencil size={24} />
            Edit Agent
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Agent Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              disabled={agent.source_type !== 'open' && !agent.is_custom}
            >
              <option value="cerebras/qwen-3-coder-480b">Cerebras Qwen 3 Coder (480B)</option>
            </select>
            {agent.source_type !== 'open' && !agent.is_custom && (
              <p className="mt-1 text-xs text-[var(--text)]/40">
                Model can only be changed for open source agents
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-[var(--text)]">
                System Prompt
              </label>
              {systemPrompt !== originalPrompt && (
                <button
                  type="button"
                  onClick={handleReset}
                  className="px-3 py-1 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 text-xs rounded transition-colors"
                >
                  Reset to Default
                </button>
              )}
            </div>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={10}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm resize-y"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              {systemPrompt.length} characters
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
            >
              <Check size={18} />
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
