import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  X,
  Rocket,
  CloudArrowUp,
  Warning,
  Plus,
  Trash,
  Gear,
  Info,
  CaretDown
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
  const navigate = useNavigate();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('');
  const [deploymentMode, setDeploymentMode] = useState<'source' | 'pre-built'>('pre-built');
  const [envVars, setEnvVars] = useState<Array<{ key: string; value: string }>>([]);
  const [customDomain, setCustomDomain] = useState('');
  const [isDeploying, setIsDeploying] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  // Auto-select appropriate deployment mode when provider changes
  useEffect(() => {
    if (!selectedProvider) return;

    // Default deployment modes per provider
    const providerDefaults: Record<string, 'source' | 'pre-built'> = {
      vercel: 'source',
      netlify: 'pre-built',
      cloudflare: 'pre-built',
    };

    const defaultMode = providerDefaults[selectedProvider.toLowerCase()] || 'pre-built';
    setDeploymentMode(defaultMode);
  }, [selectedProvider]);

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

      console.log('Deployment result:', result);

      if (result.status === 'success' && result.deployment_url) {
        // Try to open in new tab
        try {
          const newWindow = window.open(result.deployment_url, '_blank', 'noopener,noreferrer');
          if (!newWindow || newWindow.closed || typeof newWindow.closed === 'undefined') {
            // Popup was blocked
            throw new Error('Popup blocked');
          }
          toast.success('Deployment successful! Opening in new tab...');
        } catch (e) {
          // Fallback: Copy to clipboard and show clickable link
          navigator.clipboard.writeText(result.deployment_url).catch(() => {});
          toast.success(
            (t) => (
              <div>
                <div className="font-semibold mb-1">Deployment successful!</div>
                <a
                  href={result.deployment_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:text-blue-300 underline text-sm break-all"
                  onClick={() => toast.dismiss(t.id)}
                >
                  Click to open: {result.deployment_url}
                </a>
                <div className="text-xs text-gray-400 mt-1">URL copied to clipboard</div>
              </div>
            ),
            { duration: 10000 }
          );
        }
        onSuccess();
      } else if (result.status === 'success') {
        toast.success('Deployment completed successfully!');
        onSuccess();
      } else if (result.status === 'building' || result.status === 'deploying') {
        toast.success('Deployment started! This may take a few minutes...');
        onSuccess();
      } else {
        toast.error(result.error || 'Deployment failed');
      }
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
        className="bg-[var(--surface)] rounded-3xl w-full max-w-3xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
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
                onClick={() => {
                  onClose();
                  navigate('/settings');
                }}
                className="flex items-center gap-2 px-6 py-3 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-semibold transition-all"
              >
                <Gear size={18} weight="bold" />
                Go to Settings
              </button>
            </div>
          ) : (
            <>
              {/* Provider Selection */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <label className="block text-sm font-semibold text-[var(--text)]">
                    Deployment Provider
                  </label>
                  <div className="group relative">
                    <Info
                      size={16}
                      className="text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors cursor-help"
                      weight="fill"
                    />
                    <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-80 p-4 bg-[var(--surface)] border border-white/20 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                      <div className="text-xs text-[var(--text)]/80 space-y-2">
                        <p className="font-semibold text-[var(--text)]">Select deployment provider</p>
                        <p>Choose which hosting provider to deploy your project to. You can connect additional providers in Settings.</p>
                      </div>
                      <div className="absolute left-1/2 -translate-x-1/2 bottom-full w-0 h-0 border-l-8 border-r-8 border-b-8 border-l-transparent border-r-transparent border-b-white/20"></div>
                    </div>
                  </div>
                </div>
                <div className="relative">
                  <select
                    value={selectedProvider}
                    onChange={(e) => {
                      if (e.target.value === 'add-more') {
                        onClose();
                        navigate('/settings');
                      } else {
                        setSelectedProvider(e.target.value);
                      }
                    }}
                    className="w-full px-4 py-3 pr-10 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-orange-500 appearance-none cursor-pointer"
                  >
                    {connectedProviders.map((provider) => {
                      const credential = credentials.find(c => c.provider === provider);
                      const accountInfo = credential?.metadata?.account_name;
                      const displayText = accountInfo
                        ? `${getProviderDisplay(provider)} - ${accountInfo}`
                        : getProviderDisplay(provider);
                      return (
                        <option key={provider} value={provider} className="bg-[var(--surface)] text-[var(--text)]">
                          {displayText}
                        </option>
                      );
                    })}
                    <option value="add-more" className="bg-[var(--surface)] text-purple-400">
                      + Connect More Providers...
                    </option>
                  </select>
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
                    <CaretDown size={20} className="text-[var(--text)]/60" weight="bold" />
                  </div>
                </div>
              </div>

              {/* Deployment Mode */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <label className="block text-sm font-semibold text-[var(--text)]">
                    Deployment Mode
                  </label>
                  <div className="group relative">
                    <Info
                      size={16}
                      className="text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors cursor-help"
                      weight="fill"
                    />
                    <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-80 p-4 bg-[var(--surface)] border border-white/20 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                      <div className="text-xs text-[var(--text)]/80 space-y-2">
                        <p className="font-semibold text-[var(--text)]">About deployment modes</p>
                        <ul className="space-y-1.5 list-disc list-inside">
                          <li><strong>Pre-built:</strong> Build locally and upload only the production files. Faster deployment, consistent with local builds.</li>
                          <li><strong>Source Build:</strong> Upload source code and let the provider build your project remotely. Only supported by some providers (Vercel).</li>
                        </ul>
                      </div>
                      <div className="absolute left-1/2 -translate-x-1/2 bottom-full w-0 h-0 border-l-8 border-r-8 border-b-8 border-l-transparent border-r-transparent border-b-white/20"></div>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setDeploymentMode('pre-built')}
                    className={`
                      p-4 rounded-lg border-2 transition-all text-left
                      ${deploymentMode === 'pre-built'
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                      }
                    `}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                        deploymentMode === 'pre-built' ? 'border-purple-500' : 'border-[var(--text)]/30'
                      }`}>
                        {deploymentMode === 'pre-built' && (
                          <div className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                        )}
                      </div>
                      <div className="font-semibold text-[var(--text)]">Pre-built</div>
                    </div>
                  </button>

                  <button
                    onClick={() => setDeploymentMode('source')}
                    className={`
                      p-4 rounded-lg border-2 transition-all text-left
                      ${deploymentMode === 'source'
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                      }
                    `}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                        deploymentMode === 'source' ? 'border-purple-500' : 'border-[var(--text)]/30'
                      }`}>
                        {deploymentMode === 'source' && (
                          <div className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                        )}
                      </div>
                      <div className="font-semibold text-[var(--text)]">Source Build</div>
                    </div>
                  </button>
                </div>
              </div>

              {/* Custom Domain */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <label htmlFor="customDomain" className="block text-sm font-semibold text-[var(--text)]">
                    Custom Domain (Optional)
                  </label>
                  <div className="group relative">
                    <Info
                      size={16}
                      className="text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors cursor-help"
                      weight="fill"
                    />
                    <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-80 p-4 bg-[var(--surface)] border border-white/20 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                      <div className="text-xs text-[var(--text)]/80 space-y-2">
                        <p className="font-semibold text-[var(--text)]">Custom domain</p>
                        <p>Enter a custom domain name for your deployment. You'll need to configure DNS settings to point to your deployment after it's created.</p>
                      </div>
                      <div className="absolute left-1/2 -translate-x-1/2 bottom-full w-0 h-0 border-l-8 border-r-8 border-b-8 border-l-transparent border-r-transparent border-b-white/20"></div>
                    </div>
                  </div>
                </div>
                <input
                  id="customDomain"
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="example.com"
                  className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>

              {/* Environment Variables */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <label className="block text-sm font-semibold text-[var(--text)]">
                      Environment Variables
                    </label>
                    <div className="group relative">
                      <Info
                        size={16}
                        className="text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors cursor-help"
                        weight="fill"
                      />
                      <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-80 p-4 bg-[var(--surface)] border border-white/20 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                        <div className="text-xs text-[var(--text)]/80 space-y-2">
                          <p className="font-semibold text-[var(--text)]">About environment variables</p>
                          <ul className="space-y-1.5 list-disc list-inside">
                            <li>Environment variables are securely passed to your deployment</li>
                            <li>Use them for API keys, secrets, and configuration values</li>
                            <li>Values are encrypted in transit and at rest on the provider's platform</li>
                          </ul>
                        </div>
                        <div className="absolute left-1/2 -translate-x-1/2 bottom-full w-0 h-0 border-l-8 border-r-8 border-b-8 border-l-transparent border-r-transparent border-b-white/20"></div>
                      </div>
                    </div>
                  </div>
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
