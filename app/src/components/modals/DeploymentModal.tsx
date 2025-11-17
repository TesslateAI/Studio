import { useState, useEffect } from 'react';
import {
  X,
  Rocket,
  CloudArrowUp,
  Warning,
  Plus,
  Trash,
  Gear
} from '@phosphor-icons/react';
import { deploymentsApi, deploymentCredentialsApi } from '../../lib/api';
import toast from 'react-hot-toast';

interface DeploymentModalProps {
  projectSlug: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

interface Provider {
  name: string;
  display_name: string;
  auth_type: string;
  required_fields: string[];
}

interface DeploymentCredential {
  id: string;
  provider: string;
  metadata: Record<string, any>;
}

export function DeploymentModal({
  projectSlug,
  isOpen,
  onClose,
  onSuccess
}: DeploymentModalProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('');
  const [deploymentMode, setDeploymentMode] = useState<'source' | 'pre-built'>('source');
  const [envVars, setEnvVars] = useState<Array<{ key: string; value: string }>>([]);
  const [customDomain, setCustomDomain] = useState('');
  const [isDeploying, setIsDeploying] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  const loadData = async () => {
    try {
      const [providersData, credentialsData] = await Promise.all([
        deploymentCredentialsApi.getProviders(),
        deploymentCredentialsApi.list(),
      ]);
      setProviders(providersData.providers || []);
      setCredentials(credentialsData.credentials || []);

      // Auto-select first connected provider
      if (credentialsData.credentials && credentialsData.credentials.length > 0) {
        setSelectedProvider(credentialsData.credentials[0].provider);
      }
    } catch (error: any) {
      console.error('Failed to load deployment data:', error);
      toast.error(error.response?.data?.detail || 'Failed to load deployment options');
    } finally {
      setLoading(false);
    }
  };

  const handleDeploy = async () => {
    if (!selectedProvider) {
      toast.error('Please select a deployment provider');
      return;
    }

    // Validate env vars
    const env_vars: Record<string, string> = {};
    for (const { key, value } of envVars) {
      if (key.trim()) {
        env_vars[key.trim()] = value;
      }
    }

    setIsDeploying(true);
    try {
      const result = await deploymentsApi.deploy(projectSlug, {
        provider: selectedProvider,
        deployment_mode: deploymentMode,
        custom_domain: customDomain.trim() || undefined,
        env_vars: Object.keys(env_vars).length > 0 ? env_vars : undefined,
      });

      toast.success('Deployment started successfully!');
      onSuccess();
    } catch (error: any) {
      console.error('Deployment failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to start deployment');
    } finally {
      setIsDeploying(false);
    }
  };

  const addEnvVar = () => {
    setEnvVars([...envVars, { key: '', value: '' }]);
  };

  const removeEnvVar = (index: number) => {
    setEnvVars(envVars.filter((_, i) => i !== index));
  };

  const updateEnvVar = (index: number, field: 'key' | 'value', value: string) => {
    const updated = [...envVars];
    updated[index][field] = value;
    setEnvVars(updated);
  };

  const getProviderDisplay = (providerName: string) => {
    const provider = providers.find(p => p.name === providerName);
    return provider?.display_name || providerName.charAt(0).toUpperCase() + providerName.slice(1);
  };

  const getProviderColor = (providerName: string) => {
    switch (providerName.toLowerCase()) {
      case 'cloudflare':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'vercel':
        return 'bg-white/20 text-white border-white/30';
      case 'netlify':
        return 'bg-teal-500/20 text-teal-400 border-teal-500/30';
      default:
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
    }
  };

  const connectedProviders = credentials.map(c => c.provider);
  const hasConnectedProviders = connectedProviders.length > 0;

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-[var(--surface)] rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <Rocket size={24} className="text-purple-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-[var(--text)]">Deploy Project</h2>
                <p className="text-sm text-[var(--text)]/60 mt-1">
                  Deploy your project to a hosting provider
                </p>
              </div>
            </div>
            {!isDeploying && (
              <button
                onClick={onClose}
                className="text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
              >
                <X size={24} />
              </button>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-[var(--text)]/60">Loading...</div>
            </div>
          ) : !hasConnectedProviders ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="p-4 bg-yellow-500/10 rounded-full mb-4">
                <Warning size={40} className="text-yellow-400" />
              </div>
              <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
                No providers connected
              </h3>
              <p className="text-sm text-[var(--text)]/60 mb-4">
                You need to connect at least one deployment provider before you can deploy.
                <br />
                Go to Account Settings to connect Cloudflare, Vercel, or Netlify.
              </p>
              <button
                onClick={onClose}
                className="px-6 py-3 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-semibold transition-all"
              >
                Go to Settings
              </button>
            </div>
          ) : (
            <>
              {/* Provider Selection */}
              <div>
                <label className="block text-sm font-semibold text-[var(--text)] mb-3">
                  Deployment Provider
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {connectedProviders.map((provider) => (
                    <button
                      key={provider}
                      onClick={() => setSelectedProvider(provider)}
                      className={`
                        p-4 rounded-lg border-2 transition-all text-left
                        ${selectedProvider === provider
                          ? `${getProviderColor(provider)} border-2`
                          : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                        }
                      `}
                    >
                      <div className="flex items-center gap-3">
                        <CloudArrowUp size={24} className={selectedProvider === provider ? '' : 'text-[var(--text)]/60'} />
                        <div>
                          <div className="font-semibold text-[var(--text)]">
                            {getProviderDisplay(provider)}
                          </div>
                          <div className="text-xs text-[var(--text)]/60 mt-1">
                            {credentials.find(c => c.provider === provider)?.metadata?.account_name || 'Connected'}
                          </div>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Deployment Mode */}
              <div>
                <label className="block text-sm font-semibold text-[var(--text)] mb-3">
                  Deployment Mode
                </label>
                <div className="space-y-3">
                  <button
                    onClick={() => setDeploymentMode('source')}
                    className={`
                      w-full p-4 rounded-lg border-2 transition-all text-left
                      ${deploymentMode === 'source'
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                      }
                    `}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 ${
                        deploymentMode === 'source' ? 'border-purple-500' : 'border-[var(--text)]/30'
                      }`}>
                        {deploymentMode === 'source' && (
                          <div className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                        )}
                      </div>
                      <div className="flex-1">
                        <div className="font-semibold text-[var(--text)]">Source Build (Recommended)</div>
                        <div className="text-xs text-[var(--text)]/60 mt-1">
                          Upload source code and let {getProviderDisplay(selectedProvider)} build your project.
                          Standard workflow with automatic framework detection.
                        </div>
                      </div>
                    </div>
                  </button>

                  <button
                    onClick={() => setDeploymentMode('pre-built')}
                    className={`
                      w-full p-4 rounded-lg border-2 transition-all text-left
                      ${deploymentMode === 'pre-built'
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                      }
                    `}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 ${
                        deploymentMode === 'pre-built' ? 'border-purple-500' : 'border-[var(--text)]/30'
                      }`}>
                        {deploymentMode === 'pre-built' && (
                          <div className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                        )}
                      </div>
                      <div className="flex-1">
                        <div className="font-semibold text-[var(--text)]">Pre-built</div>
                        <div className="text-xs text-[var(--text)]/60 mt-1">
                          Build locally and upload only the built files. Faster deployment, consistent with local builds.
                        </div>
                      </div>
                    </div>
                  </button>
                </div>
              </div>

              {/* Custom Domain */}
              <div>
                <label htmlFor="customDomain" className="block text-sm font-semibold text-[var(--text)] mb-2">
                  Custom Domain (Optional)
                </label>
                <input
                  id="customDomain"
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="example.com"
                  className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
                <p className="text-xs text-[var(--text)]/60 mt-2">
                  Enter a custom domain name for your deployment (requires DNS configuration)
                </p>
              </div>

              {/* Environment Variables */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="block text-sm font-semibold text-[var(--text)]">
                    Environment Variables
                  </label>
                  <button
                    onClick={addEnvVar}
                    className="flex items-center gap-1 text-sm text-purple-400 hover:text-purple-300 transition-colors"
                  >
                    <Plus size={16} />
                    Add Variable
                  </button>
                </div>

                {envVars.length === 0 ? (
                  <div className="p-4 bg-white/5 border border-white/10 rounded-lg text-center">
                    <p className="text-sm text-[var(--text)]/60">
                      No environment variables added yet
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {envVars.map((envVar, index) => (
                      <div key={index} className="flex gap-2">
                        <input
                          type="text"
                          value={envVar.key}
                          onChange={(e) => updateEnvVar(index, 'key', e.target.value)}
                          placeholder="KEY"
                          className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-orange-500 text-sm font-mono"
                        />
                        <input
                          type="text"
                          value={envVar.value}
                          onChange={(e) => updateEnvVar(index, 'value', e.target.value)}
                          placeholder="value"
                          className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-orange-500 text-sm font-mono"
                        />
                        <button
                          onClick={() => removeEnvVar(index)}
                          className="p-2 text-red-400 hover:text-red-300 transition-colors"
                        >
                          <Trash size={18} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-xs text-[var(--text)]/60 mt-2">
                  Add environment variables that your application needs at runtime
                </p>
              </div>

              {/* Pre-deployment Info */}
              <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                <div className="flex items-start gap-3">
                  <Gear size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
                  <div className="text-sm text-blue-400">
                    <p className="font-semibold mb-1">Before deployment:</p>
                    <ul className="list-disc list-inside space-y-1 text-xs">
                      {deploymentMode === 'source' ? (
                        <>
                          <li>Your source code will be uploaded to {getProviderDisplay(selectedProvider)}</li>
                          <li>{getProviderDisplay(selectedProvider)} will build your project remotely</li>
                          <li>You'll receive a live URL when deployment completes</li>
                        </>
                      ) : (
                        <>
                          <li>Your project will be built locally</li>
                          <li>Built files will be uploaded to {getProviderDisplay(selectedProvider)}</li>
                          <li>You'll receive a live URL when deployment completes</li>
                        </>
                      )}
                    </ul>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {hasConnectedProviders && (
          <div className="p-6 border-t border-white/10 flex justify-end gap-3">
            <button
              onClick={onClose}
              disabled={isDeploying}
              className="px-6 py-3 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleDeploy}
              disabled={isDeploying || !selectedProvider}
              className="px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2"
            >
              {isDeploying ? (
                <>
                  <svg
                    className="w-4 h-4 animate-spin"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Deploying...
                </>
              ) : (
                <>
                  <Rocket size={18} weight="bold" />
                  Deploy Project
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
