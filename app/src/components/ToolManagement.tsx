import { useState, useEffect, useRef } from 'react';
import { Check, X, Pencil, ChevronDown, ChevronUp, Plus } from 'lucide-react';
import toast from 'react-hot-toast';

export interface Tool {
  name: string;
  description: string;
  category: string;
  parameters: any;
  examples: string[];
  system_prompt?: string;
}

export interface ToolConfig {
  description?: string;
  examples?: string[];
  system_prompt?: string;
}

interface ToolManagementProps {
  selectedTools: string[];
  toolConfigs: Record<string, ToolConfig>;
  onToolsChange: (tools: string[], configs: Record<string, ToolConfig>) => void;
  availableModels?: string[];
}

export function ToolManagement({
  selectedTools,
  toolConfigs,
  onToolsChange,
}: ToolManagementProps) {
  const [availableTools, setAvailableTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingTool, setEditingTool] = useState<string | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['file_operations', 'shell_commands'])
  );
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    loadAvailableTools();
  }, []);

  const loadAvailableTools = async () => {
    try {
      const response = await fetch('/api/agents/tools/available', {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to load available tools');
      }

      const tools = await response.json();
      setAvailableTools(tools);
    } catch (error) {
      console.error('Error loading tools:', error);
      toast.error('Failed to load available tools');
    } finally {
      setLoading(false);
    }
  };

  const toggleTool = (toolName: string) => {
    const newSelectedTools = selectedTools.includes(toolName)
      ? selectedTools.filter((t) => t !== toolName)
      : [...selectedTools, toolName];

    // Remove config if tool is deselected
    const newToolConfigs = { ...toolConfigs };
    if (!newSelectedTools.includes(toolName)) {
      delete newToolConfigs[toolName];
    }

    onToolsChange(newSelectedTools, newToolConfigs);
  };

  const toggleCategory = (category: string) => {
    const newExpanded = new Set(expandedCategories);
    if (newExpanded.has(category)) {
      newExpanded.delete(category);
    } else {
      newExpanded.add(category);
    }
    setExpandedCategories(newExpanded);
  };

  const updateToolConfig = (
    toolName: string,
    config: Partial<ToolConfig>
  ) => {
    const newToolConfigs = {
      ...toolConfigs,
      [toolName]: {
        ...toolConfigs[toolName],
        ...config,
      },
    };
    onToolsChange(selectedTools, newToolConfigs);
    toast.success(`Updated ${toolName} configuration`);
  };

  const resetToolConfig = (toolName: string) => {
    const newToolConfigs = { ...toolConfigs };
    delete newToolConfigs[toolName];
    onToolsChange(selectedTools, newToolConfigs);
    toast.success(`Reset ${toolName} to default configuration`);
    setEditingTool(null);
  };

  const selectAllInCategory = (category: string) => {
    const toolsInCategory = availableTools
      .filter((t) => t.category === category)
      .map((t) => t.name);

    const newSelectedTools = [
      ...new Set([...selectedTools, ...toolsInCategory]),
    ];
    onToolsChange(newSelectedTools, toolConfigs);
    toast.success(
      `Selected all ${toolsInCategory.length} tools in ${category.replace(
        '_',
        ' '
      )}`
    );
  };

  const deselectAllInCategory = (category: string) => {
    const toolsInCategory = availableTools
      .filter((t) => t.category === category)
      .map((t) => t.name);

    const newSelectedTools = selectedTools.filter(
      (t) => !toolsInCategory.includes(t)
    );

    // Remove configs for deselected tools
    const newToolConfigs = { ...toolConfigs };
    toolsInCategory.forEach((toolName) => {
      delete newToolConfigs[toolName];
    });

    onToolsChange(newSelectedTools, newToolConfigs);
    toast.success(
      `Deselected all tools in ${category.replace('_', ' ')}`
    );
  };

  const groupedTools = availableTools.reduce((acc, tool) => {
    if (!acc[tool.category]) {
      acc[tool.category] = [];
    }
    acc[tool.category].push(tool);
    return acc;
  }, {} as Record<string, Tool[]>);

  const filteredTools = searchQuery
    ? availableTools.filter(
        (tool) =>
          tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          tool.description.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="text-[var(--text)]/60">Loading tools...</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--text)]">
          Tool Configuration
        </h3>
        <div className="text-xs text-[var(--text)]/60">
          {selectedTools.length} tool{selectedTools.length !== 1 ? 's' : ''}{' '}
          selected
        </div>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search tools..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        className="w-full px-3 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] text-sm focus:outline-none focus:border-orange-500/50"
      />

      {/* Tool List */}
      <div className="space-y-2 max-h-[500px] overflow-y-auto">
        {filteredTools ? (
          // Search results
          <div className="space-y-1">
            {filteredTools.map((tool) => (
              <ToolItem
                key={tool.name}
                tool={tool}
                isSelected={selectedTools.includes(tool.name)}
                config={toolConfigs[tool.name]}
                isEditing={editingTool === tool.name}
                onToggle={() => toggleTool(tool.name)}
                onEdit={() => setEditingTool(tool.name)}
                onSaveConfig={(config) => {
                  updateToolConfig(tool.name, config);
                  setEditingTool(null);
                }}
                onResetConfig={() => resetToolConfig(tool.name)}
                onCancelEdit={() => setEditingTool(null)}
              />
            ))}
            {filteredTools.length === 0 && (
              <div className="text-center py-4 text-[var(--text)]/40 text-sm">
                No tools found matching "{searchQuery}"
              </div>
            )}
          </div>
        ) : (
          // Grouped by category
          Object.entries(groupedTools).map(([category, tools]) => (
            <div
              key={category}
              className="border border-[var(--text)]/10 rounded-lg overflow-hidden"
            >
              {/* Category Header */}
              <div
                className="flex items-center justify-between px-3 py-2 bg-[var(--text)]/5 cursor-pointer hover:bg-[var(--text)]/10 transition-colors"
                onClick={() => toggleCategory(category)}
              >
                <div className="flex items-center gap-2">
                  {expandedCategories.has(category) ? (
                    <ChevronDown size={16} className="text-[var(--text)]" />
                  ) : (
                    <ChevronUp size={16} className="text-[var(--text)]" />
                  )}
                  <span className="text-sm font-medium text-[var(--text)]">
                    {category.replace('_', ' ').replace(/\b\w/g, (l) =>
                      l.toUpperCase()
                    )}
                  </span>
                  <span className="text-xs text-[var(--text)]/60">
                    ({tools.filter((t) => selectedTools.includes(t.name)).length}
                    /{tools.length})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      selectAllInCategory(category);
                    }}
                    className="px-2 py-1 text-xs text-green-400 hover:bg-green-500/10 rounded transition-colors"
                  >
                    Select All
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      deselectAllInCategory(category);
                    }}
                    className="px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 rounded transition-colors"
                  >
                    Deselect All
                  </button>
                </div>
              </div>

              {/* Category Tools */}
              {expandedCategories.has(category) && (
                <div className="divide-y divide-[var(--text)]/10">
                  {tools.map((tool) => (
                    <ToolItem
                      key={tool.name}
                      tool={tool}
                      isSelected={selectedTools.includes(tool.name)}
                      config={toolConfigs[tool.name]}
                      isEditing={editingTool === tool.name}
                      onToggle={() => toggleTool(tool.name)}
                      onEdit={() => setEditingTool(tool.name)}
                      onSaveConfig={(config) => {
                        updateToolConfig(tool.name, config);
                        setEditingTool(null);
                      }}
                      onResetConfig={() => resetToolConfig(tool.name)}
                      onCancelEdit={() => setEditingTool(null)}
                    />
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

interface ToolItemProps {
  tool: Tool;
  isSelected: boolean;
  config?: ToolConfig;
  isEditing: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onSaveConfig: (config: ToolConfig) => void;
  onResetConfig: () => void;
  onCancelEdit: () => void;
}

function ToolItem({
  tool,
  isSelected,
  config,
  isEditing,
  onToggle,
  onEdit,
  onSaveConfig,
  onResetConfig,
  onCancelEdit,
}: ToolItemProps) {
  const [editDescription, setEditDescription] = useState(
    config?.description || tool.description
  );
  const [editExamples, setEditExamples] = useState(
    config?.examples || tool.examples || []
  );
  const [editSystemPrompt, setEditSystemPrompt] = useState(
    config?.system_prompt || tool.system_prompt || ''
  );
  const [newExample, setNewExample] = useState('');

  const hasCustomConfig = !!config;

  const addExample = () => {
    if (!newExample.trim()) return;
    setEditExamples([...editExamples, newExample.trim()]);
    setNewExample('');
  };

  const removeExample = (index: number) => {
    setEditExamples(editExamples.filter((_, i) => i !== index));
  };

  const handleSave = () => {
    onSaveConfig({
      description: editDescription !== tool.description ? editDescription : undefined,
      examples: JSON.stringify(editExamples) !== JSON.stringify(tool.examples) ? editExamples : undefined,
      system_prompt: editSystemPrompt !== (tool.system_prompt || '') ? editSystemPrompt : undefined,
    });
  };

  return (
    <div className={`px-3 py-2 ${isSelected ? 'bg-orange-500/5' : ''}`}>
      {!isEditing ? (
        <div className="flex items-start gap-3">
          {/* Checkbox */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onToggle();
            }}
            className={`mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
              isSelected
                ? 'bg-orange-500 border-orange-500'
                : 'border-[var(--text)]/30 hover:border-orange-500/50'
            }`}
          >
            {isSelected && <Check size={14} className="text-white" />}
          </button>

          {/* Tool Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[var(--text)] font-mono">
                {tool.name}
              </span>
              {hasCustomConfig && (
                <span className="text-xs px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                  Custom
                </span>
              )}
            </div>
            <p className="text-xs text-[var(--text)]/60 mt-0.5 line-clamp-2">
              {config?.description || tool.description}
            </p>
            {(config?.examples || tool.examples)?.length > 0 && (
              <div className="mt-1 flex items-center gap-1 flex-wrap">
                {(config?.examples || tool.examples).slice(0, 2).map((example, i) => (
                  <span
                    key={i}
                    className="text-xs px-1.5 py-0.5 bg-[var(--text)]/5 text-[var(--text)]/50 rounded font-mono"
                  >
                    {example}
                  </span>
                ))}
                {(config?.examples || tool.examples).length > 2 && (
                  <span className="text-xs text-[var(--text)]/40">
                    +{(config?.examples || tool.examples).length - 2} more
                  </span>
                )}
              </div>
            )}
            {(config?.system_prompt || tool.system_prompt) && (
              <div className="mt-1 text-[10px] text-purple-400/70 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-purple-400/50 rounded-full"></span>
                Has custom instructions
              </div>
            )}
          </div>

          {/* Edit Button */}
          {isSelected && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                onEdit();
              }}
              className="p-1.5 text-[var(--text)]/60 hover:text-orange-400 hover:bg-orange-500/10 rounded transition-colors"
              title="Customize tool"
            >
              <Pencil size={14} />
            </button>
          )}
        </div>
      ) : (
        // Edit Mode
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-[var(--text)] font-mono">
              {tool.name}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                onCancelEdit();
              }}
              className="p-1 text-[var(--text)]/60 hover:text-red-400 rounded"
            >
              <X size={16} />
            </button>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs text-[var(--text)]/60 mb-1">
              Description
            </label>
            <textarea
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              rows={3}
              className="w-full px-2 py-1.5 bg-white/5 border border-[var(--text)]/15 rounded text-[var(--text)] text-xs focus:outline-none focus:border-orange-500/50 resize-none"
            />
          </div>

          {/* Examples */}
          <div>
            <label className="block text-xs text-[var(--text)]/60 mb-1">
              Examples
            </label>
            <div className="space-y-1">
              {editExamples.map((example, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={example}
                    onChange={(e) => {
                      const newExamples = [...editExamples];
                      newExamples[i] = e.target.value;
                      setEditExamples(newExamples);
                    }}
                    className="flex-1 px-2 py-1 bg-white/5 border border-[var(--text)]/15 rounded text-[var(--text)] text-xs focus:outline-none focus:border-orange-500/50 font-mono"
                  />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      removeExample(i);
                    }}
                    className="p-1 text-red-400 hover:bg-red-500/10 rounded"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <div className="flex items-center gap-2">
                <input
                  value={newExample}
                  onChange={(e) => setNewExample(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addExample();
                    }
                  }}
                  placeholder="Add example..."
                  className="flex-1 px-2 py-1 bg-white/5 border border-[var(--text)]/15 rounded text-[var(--text)] text-xs focus:outline-none focus:border-orange-500/50 font-mono"
                />
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    addExample();
                  }}
                  className="p-1 text-green-400 hover:bg-green-500/10 rounded"
                >
                  <Plus size={14} />
                </button>
              </div>
            </div>
          </div>

          {/* System Prompt */}
          <div>
            <label className="block text-xs text-[var(--text)]/60 mb-1">
              System Prompt <span className="text-[var(--text)]/40">(optional - additional instructions for this tool)</span>
            </label>
            <textarea
              value={editSystemPrompt}
              onChange={(e) => setEditSystemPrompt(e.target.value)}
              rows={4}
              placeholder="Add specific instructions for how this tool should behave..."
              className="w-full px-2 py-1.5 bg-white/5 border border-[var(--text)]/15 rounded text-[var(--text)] text-xs focus:outline-none focus:border-orange-500/50 resize-none font-mono"
            />
            <p className="mt-1 text-[10px] text-[var(--text)]/40">
              This prompt will be included when the agent uses this tool. Use it to customize tool behavior.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                handleSave();
              }}
              className="flex-1 px-3 py-1.5 bg-green-500/20 hover:bg-green-500/30 border border-green-500/40 text-green-400 text-xs rounded transition-colors"
            >
              Save Changes
            </button>
            {hasCustomConfig && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  onResetConfig();
                }}
                className="px-3 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 text-blue-400 text-xs rounded transition-colors"
              >
                Reset to Default
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
