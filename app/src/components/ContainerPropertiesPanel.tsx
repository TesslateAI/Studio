import { useState, useEffect } from 'react';
import { X, Play, Square, ArrowClockwise, Plus, Trash } from '@phosphor-icons/react';
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
  port?: number;
}

export const ContainerPropertiesPanel = ({
  containerId,
  containerName,
  containerStatus,
  projectSlug,
  onClose,
  onStatusChange,
  port,
}: ContainerPropertiesPanelProps) => {
  const [envVars, setEnvVars] = useState<EnvironmentVariable[]>([]);
  const [newEnvKey, setNewEnvKey] = useState('');
  const [newEnvValue, setNewEnvValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    fetchContainerDetails();
  }, [containerId]);

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
    } catch (error) {
      console.error('Failed to fetch container details:', error);
      toast.error('Failed to load container details');
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
      await api.post(`/api/projects/${projectSlug}/containers/${containerId}/${action}`);

      let newStatus = containerStatus;
      if (action === 'start') {
        newStatus = 'running';
        toast.success('Container starting...');
      } else if (action === 'stop') {
        newStatus = 'stopped';
        toast.success('Container stopped');
      } else if (action === 'restart') {
        newStatus = 'running';
        toast.success('Container restarting...');
      }

      onStatusChange?.(newStatus);
    } catch (error) {
      console.error(`Failed to ${action} container:`, error);
      toast.error(`Failed to ${action} container`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed right-0 top-0 h-full w-full md:w-96 bg-[var(--surface)] border-l border-[var(--border-color)] shadow-lg flex flex-col z-50 overflow-hidden">
      {/* Header */}
      <div className="px-3 md:px-4 py-3 md:py-4 border-b border-[var(--border-color)] flex items-center justify-between flex-shrink-0">
        <div className="min-w-0 flex-1">
          <h2 className="text-base md:text-lg font-semibold text-[var(--text)] truncate">{containerName}</h2>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${
              containerStatus === 'running'
                ? 'bg-green-500/20 text-green-400'
                : containerStatus === 'stopped'
                ? 'bg-gray-500/20 text-gray-400'
                : 'bg-yellow-500/20 text-yellow-400'
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
          className="p-2 hover:bg-[var(--sidebar-hover)] rounded-lg transition-colors flex-shrink-0 ml-2"
        >
          <X size={18} className="text-[var(--text)]" />
        </button>
      </div>

      {/* Container Controls */}
      <div className="px-3 md:px-4 py-2 md:py-3 border-b border-[var(--border-color)] flex-shrink-0">
        <p className="text-xs md:text-sm font-medium text-[var(--text)] mb-2">Container Controls</p>
        <div className="flex gap-1.5 md:gap-2">
          <button
            onClick={() => handleContainerAction('start')}
            disabled={isLoading || containerStatus === 'running'}
            className="flex-1 flex items-center justify-center gap-1 md:gap-2 px-2 md:px-3 py-1.5 md:py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs md:text-sm font-medium"
          >
            <Play size={14} weight="fill" />
            <span className="hidden sm:inline">Start</span>
          </button>
          <button
            onClick={() => handleContainerAction('stop')}
            disabled={isLoading || containerStatus === 'stopped'}
            className="flex-1 flex items-center justify-center gap-1 md:gap-2 px-2 md:px-3 py-1.5 md:py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs md:text-sm font-medium"
          >
            <Square size={14} weight="fill" />
            <span className="hidden sm:inline">Stop</span>
          </button>
          <button
            onClick={() => handleContainerAction('restart')}
            disabled={isLoading}
            className="flex-1 flex items-center justify-center gap-1 md:gap-2 px-2 md:px-3 py-1.5 md:py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs md:text-sm font-medium"
          >
            <ArrowClockwise size={14} />
            <span className="hidden sm:inline">Restart</span>
          </button>
        </div>
      </div>

      {/* Environment Variables */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 md:px-4 py-2 md:py-3">
        <div className="flex items-center justify-between mb-2 md:mb-3">
          <p className="text-xs md:text-sm font-medium text-[var(--text)]">Environment Variables</p>
          <button
            onClick={handleSaveEnvVars}
            disabled={isSaving}
            className="px-2 md:px-3 py-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:opacity-50 text-white rounded text-xs md:text-sm font-medium transition-colors flex-shrink-0"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[var(--primary)]"></div>
          </div>
        ) : (
          <div className="space-y-2">
            {/* Existing environment variables */}
            {envVars.map((envVar, index) => (
              <div key={index} className="flex gap-1.5 md:gap-2 items-start min-w-0">
                <div className="flex-1 space-y-1 min-w-0">
                  <input
                    type="text"
                    value={envVar.key}
                    onChange={(e) => handleUpdateEnvVar(index, 'key', e.target.value)}
                    placeholder="KEY"
                    className="w-full px-2 py-1 md:py-1.5 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs md:text-sm focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <input
                    type="text"
                    value={envVar.value}
                    onChange={(e) => handleUpdateEnvVar(index, 'value', e.target.value)}
                    placeholder="value"
                    className="w-full px-2 py-1 md:py-1.5 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs md:text-sm focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                </div>
                <button
                  onClick={() => handleRemoveEnvVar(index)}
                  className="p-1 md:p-1.5 hover:bg-red-500/20 rounded transition-colors mt-1 flex-shrink-0"
                >
                  <Trash size={14} className="text-red-400" />
                </button>
              </div>
            ))}

            {/* Add new environment variable */}
            <div className="pt-2 border-t border-[var(--border-color)]">
              <p className="text-xs font-medium text-[var(--text)]/60 mb-2">Add New Variable</p>
              <div className="space-y-2">
                <input
                  type="text"
                  value={newEnvKey}
                  onChange={(e) => setNewEnvKey(e.target.value)}
                  placeholder="KEY"
                  className="w-full px-2 py-1 md:py-1.5 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs md:text-sm focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                <input
                  type="text"
                  value={newEnvValue}
                  onChange={(e) => setNewEnvValue(e.target.value)}
                  placeholder="value"
                  className="w-full px-2 py-1 md:py-1.5 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs md:text-sm focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                />
                <button
                  onClick={handleAddEnvVar}
                  className="w-full flex items-center justify-center gap-1.5 md:gap-2 px-2 md:px-3 py-1.5 bg-[var(--sidebar-hover)] hover:bg-[var(--border-color)] text-[var(--text)] rounded text-xs md:text-sm font-medium transition-colors"
                >
                  <Plus size={14} />
                  Add Variable
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
