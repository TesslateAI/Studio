import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Robot, Wrench, ArrowRight, ArrowLeft, SpinnerGap } from '@phosphor-icons/react';
import { setupApi } from '../lib/api';
import { ServiceConfigForm } from '../components/ServiceConfigForm';
import { ModelSelector } from '../components/chat/ModelSelector';
import type { TesslateConfig } from '../types/tesslateConfig';

type Tab = 'agent' | 'manual';

const DEFAULT_CONFIG: TesslateConfig = {
  apps: {
    app: {
      directory: '.',
      port: 3000,
      start: '',
      env: {},
    },
  },
  infrastructure: {},
  primaryApp: 'app',
};

export default function ProjectSetup() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<Tab>('agent');
  const [config, setConfig] = useState<TesslateConfig>(DEFAULT_CONFIG);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisDone, setAnalysisDone] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [existingConfig, setExistingConfig] = useState(false);
  const [analyzeModel, setAnalyzeModel] = useState('glm-5');

  // Load existing config on mount
  useEffect(() => {
    if (!slug) return;
    setupApi.getConfig(slug).then(res => {
      if (res.exists) {
        setConfig({ apps: res.apps, infrastructure: res.infrastructure, primaryApp: res.primaryApp });
        setExistingConfig(true);
        setAnalysisDone(true);
      }
    }).catch(() => {});
  }, [slug]);

  const handleAnalyze = useCallback(async () => {
    if (!slug || isAnalyzing) return;
    setIsAnalyzing(true);
    setAnalysisDone(false);

    try {
      const result = await setupApi.analyzeProject(slug, analyzeModel);
      if (result.apps && Object.keys(result.apps).length > 0) {
        setConfig({
          apps: result.apps,
          infrastructure: result.infrastructure || {},
          primaryApp: result.primaryApp || Object.keys(result.apps)[0],
        });
        setAnalysisDone(true);
        toast.success('Project analyzed successfully');
      } else {
        toast.error('Could not detect project structure. Try manual setup.');
        setActiveTab('manual');
      }
    } catch (error) {
      console.error('Analysis failed:', error);
      const msg = error instanceof Error ? error.message : 'Analysis failed';
      toast.error(msg);
    } finally {
      setIsAnalyzing(false);
    }
  }, [slug, isAnalyzing, analyzeModel]);

  const handleSave = async () => {
    if (!slug || isSaving) return;

    // Validate at least one app with a start command
    const appEntries = Object.entries(config.apps);
    if (appEntries.length === 0) {
      toast.error('Add at least one app');
      return;
    }

    const hasStart = appEntries.some(([, app]) => app.start.trim());
    if (!hasStart) {
      toast.error('At least one app needs a start command');
      return;
    }

    setIsSaving(true);
    try {
      const result = await setupApi.saveConfig(slug, config);
      toast.success('Configuration saved!');

      // Navigate to builder with the primary container
      if (result.primary_container_id) {
        navigate(`/project/${slug}/builder?container=${result.primary_container_id}`);
      } else if (result.container_ids.length > 0) {
        navigate(`/project/${slug}/builder?container=${result.container_ids[0]}`);
      } else {
        navigate(`/project/${slug}/builder`);
      }
    } catch (error) {
      console.error('Save failed:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err?.response?.data?.detail || 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSkip = async () => {
    if (!slug) return;
    // Save default config and navigate
    setIsSaving(true);
    try {
      const defaultConfig: TesslateConfig = {
        apps: { workspace: { directory: '.', port: null, start: 'sleep infinity', env: {} } },
        infrastructure: {},
        primaryApp: 'workspace',
      };
      await setupApi.saveConfig(slug, defaultConfig);
      navigate(`/project/${slug}/builder`);
    } catch {
      navigate(`/project/${slug}/builder`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--background)] flex flex-col">
      {/* Header */}
      <div className="border-b border-white/5 bg-[var(--surface)]/50 backdrop-blur-xl">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/dashboard')}
              className="p-2 text-[var(--text)]/40 hover:text-[var(--text)] transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
            <div>
              <h1 className="text-lg font-bold text-[var(--text)]">Project Setup</h1>
              <p className="text-xs text-[var(--text)]/40">{slug}</p>
            </div>
          </div>
          {existingConfig && (
            <span className="text-xs text-emerald-400 bg-emerald-400/10 px-2.5 py-1 rounded-full">
              Config detected
            </span>
          )}
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 pt-6">
        <div className="flex bg-[var(--surface)] rounded-xl p-1 border border-white/5">
          <button
            onClick={() => setActiveTab('agent')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'agent'
                ? 'bg-[rgba(var(--primary-rgb),0.15)] text-[var(--primary)]'
                : 'text-[var(--text)]/50 hover:text-[var(--text)]/70'
            }`}
          >
            <Robot size={16} /> Agent Setup
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'manual'
                ? 'bg-[rgba(var(--primary-rgb),0.15)] text-[var(--primary)]'
                : 'text-[var(--text)]/50 hover:text-[var(--text)]/70'
            }`}
          >
            <Wrench size={16} /> Manual Setup
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 max-w-3xl mx-auto w-full px-4 sm:px-6 py-6">
        {activeTab === 'agent' ? (
          <div className="space-y-6">
            {/* Analysis Section */}
            {!analysisDone && (
              <div className="bg-[var(--surface)] border border-white/5 rounded-2xl p-6 text-center">
                <Robot size={48} className="text-[var(--primary)] mx-auto mb-4" />
                <h2 className="text-lg font-bold text-[var(--text)] mb-2">
                  Analyze Your Project
                </h2>
                <p className="text-sm text-[var(--text)]/50 mb-6 max-w-md mx-auto">
                  Our AI will scan your project files to detect frameworks, ports, and startup commands automatically.
                </p>
                <div className="flex items-center gap-3 justify-center">
                  <ModelSelector
                    value={analyzeModel}
                    onModelChange={setAnalyzeModel}
                    dropUp={false}
                  />
                  <button
                    onClick={handleAnalyze}
                    disabled={isAnalyzing}
                    className="px-6 py-3 bg-[var(--primary)] text-white rounded-xl font-medium hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
                  >
                    {isAnalyzing ? (
                      <>
                        <SpinnerGap size={18} className="animate-spin" />
                        Analyzing...
                      </>
                    ) : (
                      'Analyze Project'
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Config Form (after analysis) */}
            {analysisDone && (
              <div>
                <p className="text-sm text-[var(--text)]/50 mb-4">
                  Review and adjust the detected configuration:
                </p>
                <ServiceConfigForm config={config} onChange={setConfig} />
              </div>
            )}
          </div>
        ) : (
          /* Manual Tab */
          <div>
            <p className="text-sm text-[var(--text)]/50 mb-4">
              Configure your project services manually:
            </p>
            <ServiceConfigForm config={config} onChange={setConfig} />
          </div>
        )}
      </div>

      {/* Bottom Bar */}
      <div className="border-t border-white/5 bg-[var(--surface)]/50 backdrop-blur-xl">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
          <button
            onClick={handleSkip}
            className="text-sm text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors"
          >
            Skip setup
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || Object.keys(config.apps).length === 0}
            className="px-6 py-2.5 bg-[var(--primary)] text-white rounded-xl font-medium hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
          >
            {isSaving ? (
              <>
                <SpinnerGap size={16} className="animate-spin" />
                Saving...
              </>
            ) : (
              <>
                Next <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
