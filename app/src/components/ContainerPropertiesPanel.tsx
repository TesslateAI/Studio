import { useState, useEffect } from 'react';
import { X, Play, Square, ArrowClockwise, Plus, Trash, PencilSimple, Check } from '@phosphor-icons/react';
import api from '../lib/api';
import { toast } from 'react-hot-toast';

interface EnvironmentVariable {
  key: string;
  value: string;
}

interface ContainerPropertiesPanelProps {
  containerId: string;
  containerName: string;
  containerStatus: string;
  projectSlug: string;
  onClose: () => void;
  onStatusChange?: (newStatus: string) => void;
  onNameChange?: (newName: string) => void;
  port?: number;
}

export const ContainerPropertiesPanel = ({
  containerId,
  containerName,
  containerStatus,
  projectSlug,
  onClose,
  onStatusChange,
  onNameChange,
  port,
}: ContainerPropertiesPanelProps) => {
  const [envVars, setEnvVars] = useState<EnvironmentVariable[]>([]);
  const [newEnvKey, setNewEnvKey] = useState('');
  const [newEnvValue, setNewEnvValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [editedName, setEditedName] = useState(containerName);
  const [isRenamingContainer, setIsRenamingContainer] = useState(false);

  useEffect(() => {
    fetchContainerDetails();
  }, [containerId]);

  // Reset edited name when container changes
  useEffect(() => {
    setEditedName(containerName);
    setIsEditingName(false);
  }, [containerName]);

  const handleRenameContainer = async () => {
    if (!editedName.trim() || editedName === containerName) {
      setIsEditingName(false);
      setEditedName(containerName);
      return;
    }

    try {
      setIsRenamingContainer(true);
      await api.post(`/api/projects/${projectSlug}/containers/${containerId}/rename`, {
        new_name: editedName.trim(),
      });

      toast.success('Container renamed successfully');
      onNameChange?.(editedName.trim());
      setIsEditingName(false);
    } catch (error: any) {
      console.error('Failed to rename container:', error);
      const errorMessage = error.response?.data?.detail || 'Failed to rename container';
      toast.error(errorMessage);
      setEditedName(containerName); // Reset on error
    } finally {
      setIsRenamingContainer(false);
    }
  };

  const fetchContainerDetails = async () => {
    try {
      setIsLoading(true);
      const response = await api.get(`/api/projects/${projectSlug}/containers/${containerId}`);
      const envVarsObj = response.data.environment_vars || {};

      // Convert object to array of key-value pairs
      const envVarsArray = Object.entries(envVarsObj).map(([key, value]) => ({
        key,
        value: String(value),
      }));

      setEnvVars(envVarsArray);
    } catch (error: any) {
      console.error('Failed to fetch container details:', error);

      // Handle 404 - container was deleted or doesn't exist
      if (error.response?.status === 404) {
        toast.error('Container not found. Please refresh the page to sync with the latest data.');
        onClose(); // Close the panel since container doesn't exist
      } else {
        toast.error('Failed to load container details');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddEnvVar = () => {
    if (!newEnvKey.trim()) {
      toast.error('Environment variable key cannot be empty');
      return;
    }

    // Check for duplicate keys
    if (envVars.some(env => env.key === newEnvKey)) {
      toast.error('Environment variable key already exists');
      return;
    }

    setEnvVars([...envVars, { key: newEnvKey, value: newEnvValue }]);
    setNewEnvKey('');
    setNewEnvValue('');
  };

  const handleRemoveEnvVar = (index: number) => {
    setEnvVars(envVars.filter((_, i) => i !== index));
  };

  const handleUpdateEnvVar = (index: number, field: 'key' | 'value', newValue: string) => {
    const updated = [...envVars];
    updated[index][field] = newValue;
    setEnvVars(updated);
  };

  const handleSaveEnvVars = async () => {
    try {
      setIsSaving(true);

      // Convert array back to object
      const envVarsObj: Record<string, string> = {};
      envVars.forEach(({ key, value }) => {
        if (key.trim()) {
          envVarsObj[key] = value;
        }
      });

      await api.patch(`/api/projects/${projectSlug}/containers/${containerId}`, {
        environment_vars: envVarsObj,
      });

      toast.success('Environment variables saved');
    } catch (error) {
      console.error('Failed to save environment variables:', error);
      toast.error('Failed to save environment variables');
    } finally {
      setIsSaving(false);
    }
  };

  const handleContainerAction = async (action: 'start' | 'stop' | 'restart') => {
    try {
      setIsLoading(true);

      // For start and restart, the backend returns a task_id for async processing
      // Set status to 'starting' immediately and let polling update to 'running'
      if (action === 'start' || action === 'restart') {
        onStatusChange?.('starting');
        toast.success(action === 'start' ? 'Starting container...' : 'Restarting container...');
      }

      const response = await api.post(`/api/projects/${projectSlug}/containers/${containerId}/${action}`);

      if (action === 'stop') {
        // Stop is synchronous, update status immediately
        onStatusChange?.('stopped');
        toast.success('Container stopped');
      } else {
        // For start/restart, the polling will update the status when container is running
        // Show task info in console for debugging
        console.log(`Container ${action} task started:`, response.data);
      }
    } catch (error: any) {
      console.error(`Failed to ${action} container:`, error);
      const errorMessage = error.response?.data?.detail || `Failed to ${action} container`;
      toast.error(errorMessage);
      // Reset to stopped on error if we were trying to start
      if (action === 'start' || action === 'restart') {
        onStatusChange?.('stopped');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className="md:hidden fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed md:absolute inset-y-4 md:inset-y-auto md:top-4 md:bottom-4 right-4 w-[calc(100%-2rem)] max-w-sm md:w-80 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] flex flex-col overflow-hidden z-50 shadow-2xl">
        {/* Header */}
        <div className="px-4 py-3 border-b border-[#2a2a2a] flex items-center justify-between flex-shrink-0">
        <div className="min-w-0 flex-1">
          {isEditingName ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={editedName}
                onChange={(e) => setEditedName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRenameContainer();
                  if (e.key === 'Escape') {
                    setEditedName(containerName);
                    setIsEditingName(false);
                  }
                }}
                className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--primary)] text-[var(--text)] rounded text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                autoFocus
                disabled={isRenamingContainer}
              />
              <button
                onClick={handleRenameContainer}
                disabled={isRenamingContainer}
                className="p-1 hover:bg-green-500/20 rounded transition-colors"
                title="Save name"
              >
                <Check size={16} className="text-green-400" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-[var(--text)] truncate">{containerName}</h2>
              <button
                onClick={() => setIsEditingName(true)}
                className="p-1 hover:bg-[var(--sidebar-hover)] rounded transition-colors flex-shrink-0"
                title="Rename container"
              >
                <PencilSimple size={14} className="text-[var(--text)]/60" />
              </button>
            </div>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${
              containerStatus === 'running'
                ? 'bg-green-500/20 text-green-400'
                : containerStatus === 'starting'
                ? 'bg-yellow-500/20 text-yellow-400'
                : containerStatus === 'stopped'
                ? 'bg-gray-500/20 text-gray-400'
                : containerStatus === 'failed'
                ? 'bg-red-500/20 text-red-400'
                : containerStatus === 'connected'
                ? 'bg-purple-500/20 text-purple-400'
                : 'bg-gray-500/20 text-gray-400'
            }`}>
              {containerStatus}
            </span>
            {port && (
              <span className="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400 flex-shrink-0">
                Port: {port}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-[var(--sidebar-hover)] rounded-lg transition-colors flex-shrink-0 ml-2"
        >
          <X size={16} className="text-[var(--text)]" />
        </button>
      </div>

      {/* Container Controls */}
      <div className="px-3 py-2 border-b border-[var(--border-color)] flex-shrink-0">
        <p className="text-xs font-medium text-[var(--text)] mb-2">Container Controls</p>
        <div className="flex gap-1.5">
          <button
            onClick={() => handleContainerAction('start')}
            disabled={isLoading || containerStatus === 'running' || containerStatus === 'starting'}
            className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
          >
            <Play size={12} weight="fill" />
            {containerStatus === 'starting' ? 'Starting...' : 'Start'}
          </button>
          <button
            onClick={() => handleContainerAction('stop')}
            disabled={isLoading || containerStatus === 'stopped' || containerStatus === 'connected'}
            className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
          >
            <Square size={12} weight="fill" />
            Stop
          </button>
          <button
            onClick={() => handleContainerAction('restart')}
            disabled={isLoading || containerStatus === 'starting' || containerStatus === 'connected'}
            className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
          >
            <ArrowClockwise size={12} />
            Restart
          </button>
        </div>
      </div>

      {/* Environment Variables */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-medium text-[var(--text)]">Environment Variables</p>
          <button
            onClick={handleSaveEnvVars}
            disabled={isSaving}
            className="px-2 py-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:opacity-50 text-white rounded text-xs font-medium transition-colors flex-shrink-0"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[var(--primary)]"></div>
          </div>
        ) : (
          <div className="space-y-2">
            {/* Existing environment variables */}
            {envVars.map((envVar, index) => (
              <div key={index} className="flex gap-1.5 items-start min-w-0">
                <div className="flex-1 space-y-1 min-w-0">
                  <input
                    type="text"
                    value={envVar.key}
                    onChange={(e) => handleUpdateEnvVar(index, 'key', e.target.value)}
                    placeholder="KEY"
                    className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <input
                    type="text"
                    value={envVar.value}
                    onChange={(e) => handleUpdateEnvVar(index, 'value', e.target.value)}
                    placeholder="value"
                    className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                </div>
                <button
                  onClick={() => handleRemoveEnvVar(index)}
                  className="p-1 hover:bg-red-500/20 rounded transition-colors mt-1 flex-shrink-0"
                >
                  <Trash size={12} className="text-red-400" />
                </button>
              </div>
            ))}

            {/* Add new environment variable */}
            <div className="pt-2 border-t border-[var(--border-color)]">
              <p className="text-xs font-medium text-[var(--text)]/60 mb-2">Add New Variable</p>
              <div className="space-y-1.5">
                <input
                  type="text"
                  value={newEnvKey}
                  onChange={(e) => setNewEnvKey(e.target.value)}
                  placeholder="KEY"
                  className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                <input
                  type="text"
                  value={newEnvValue}
                  onChange={(e) => setNewEnvValue(e.target.value)}
                  placeholder="value"
                  className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                <button
                  onClick={handleAddEnvVar}
                  className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-[var(--sidebar-hover)] hover:bg-[var(--border-color)] text-[var(--text)] rounded text-xs font-medium transition-colors"
                >
                  <Plus size={12} />
                  Add Variable
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      </div>
    </>
  );
};
