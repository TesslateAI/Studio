import { useState } from 'react';
import { Plus, Trash, CaretDown, CaretUp } from '@phosphor-icons/react';
import type { TesslateConfig, AppConfig, InfraConfig } from '../types/tesslateConfig';

interface ServiceConfigFormProps {
  config: TesslateConfig;
  onChange: (config: TesslateConfig) => void;
  readOnly?: boolean;
}

const INFRA_CATALOG: Record<string, { image: string; port: number }> = {
  postgres: { image: 'postgres:16', port: 5432 },
  redis: { image: 'redis:7-alpine', port: 6379 },
  mysql: { image: 'mysql:8', port: 3306 },
  mongo: { image: 'mongo:7', port: 27017 },
  minio: { image: 'minio/minio:latest', port: 9000 },
};

export function ServiceConfigForm({ config, onChange, readOnly = false }: ServiceConfigFormProps) {
  const [expandedApps, setExpandedApps] = useState<Set<string>>(new Set());
  const [newAppName, setNewAppName] = useState('');
  const [showAddInfra, setShowAddInfra] = useState(false);

  const toggleExpand = (name: string) => {
    setExpandedApps(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const updateApp = (name: string, field: keyof AppConfig, value: unknown) => {
    const updated = { ...config };
    updated.apps = { ...updated.apps };
    updated.apps[name] = { ...updated.apps[name], [field]: value };
    onChange(updated);
  };

  const updateEnvVar = (appName: string, key: string, value: string) => {
    const updated = { ...config };
    updated.apps = { ...updated.apps };
    updated.apps[appName] = {
      ...updated.apps[appName],
      env: { ...updated.apps[appName].env, [key]: value },
    };
    onChange(updated);
  };

  const removeEnvVar = (appName: string, key: string) => {
    const updated = { ...config };
    updated.apps = { ...updated.apps };
    const newEnv = { ...updated.apps[appName].env };
    delete newEnv[key];
    updated.apps[appName] = { ...updated.apps[appName], env: newEnv };
    onChange(updated);
  };

  const addApp = () => {
    const name = newAppName.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-') || 'new-app';
    if (config.apps[name]) return;
    const updated = { ...config };
    updated.apps = {
      ...updated.apps,
      [name]: { directory: '.', port: 3000, start: '', env: {} },
    };
    if (!updated.primaryApp) updated.primaryApp = name;
    onChange(updated);
    setNewAppName('');
    setExpandedApps(prev => new Set(prev).add(name));
  };

  const removeApp = (name: string) => {
    const updated = { ...config };
    const newApps = { ...updated.apps };
    delete newApps[name];
    updated.apps = newApps;
    if (updated.primaryApp === name) {
      updated.primaryApp = Object.keys(newApps)[0] || '';
    }
    onChange(updated);
  };

  const addInfra = (slug: string) => {
    if (config.infrastructure[slug]) return;
    const catalog = INFRA_CATALOG[slug];
    if (!catalog) return;
    const updated = { ...config };
    updated.infrastructure = {
      ...updated.infrastructure,
      [slug]: { image: catalog.image, port: catalog.port },
    };
    onChange(updated);
    setShowAddInfra(false);
  };

  const removeInfra = (name: string) => {
    const updated = { ...config };
    const newInfra = { ...updated.infrastructure };
    delete newInfra[name];
    updated.infrastructure = newInfra;
    onChange(updated);
  };

  const appNames = Object.keys(config.apps);

  return (
    <div className="space-y-6">
      {/* Apps Section */}
      <div>
        <h3 className="text-sm font-semibold text-[var(--text)] mb-3 uppercase tracking-wider">
          Apps
        </h3>
        <div className="space-y-3">
          {appNames.map(name => {
            const app = config.apps[name];
            const isExpanded = expandedApps.has(name);
            const isPrimary = config.primaryApp === name;

            return (
              <div
                key={name}
                className="bg-[var(--surface)] border border-white/5 rounded-xl overflow-hidden"
              >
                {/* Card Header */}
                <div
                  className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
                  onClick={() => toggleExpand(name)}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${isPrimary ? 'bg-[var(--primary)]' : 'bg-white/20'}`} />
                    <span className="font-medium text-[var(--text)]">{name}</span>
                    {app.port && (
                      <span className="text-xs text-[var(--text)]/40 bg-white/5 px-2 py-0.5 rounded">
                        :{app.port}
                      </span>
                    )}
                    {isPrimary && (
                      <span className="text-[10px] text-[var(--primary)] bg-[rgba(var(--primary-rgb),0.1)] px-2 py-0.5 rounded-full font-medium">
                        PRIMARY
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!readOnly && !isPrimary && appNames.length > 1 && (
                      <button
                        onClick={(e) => { e.stopPropagation(); removeApp(name); }}
                        className="p-1 text-red-400/60 hover:text-red-400 transition-colors"
                      >
                        <Trash size={14} />
                      </button>
                    )}
                    {isExpanded ? <CaretUp size={14} className="text-[var(--text)]/40" /> : <CaretDown size={14} className="text-[var(--text)]/40" />}
                  </div>
                </div>

                {/* Card Body */}
                {isExpanded && (
                  <div className="px-4 pb-4 pt-1 border-t border-white/5 space-y-3">
                    {/* Primary selector */}
                    {!readOnly && !isPrimary && (
                      <button
                        onClick={() => onChange({ ...config, primaryApp: name })}
                        className="text-xs text-[var(--primary)]/70 hover:text-[var(--primary)] transition-colors"
                      >
                        Set as primary app
                      </button>
                    )}

                    {/* Directory */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Directory</label>
                      <input
                        type="text"
                        value={app.directory}
                        onChange={(e) => updateApp(name, 'directory', e.target.value)}
                        disabled={readOnly}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                        placeholder="."
                      />
                    </div>

                    {/* Port */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Port</label>
                      <input
                        type="number"
                        value={app.port ?? ''}
                        onChange={(e) => updateApp(name, 'port', e.target.value ? parseInt(e.target.value) : null)}
                        disabled={readOnly}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                        placeholder="3000"
                      />
                    </div>

                    {/* Start Command */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Start Command</label>
                      <textarea
                        value={app.start}
                        onChange={(e) => updateApp(name, 'start', e.target.value)}
                        disabled={readOnly}
                        rows={2}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50 resize-none"
                        placeholder="npm install && npm run dev -- --host 0.0.0.0"
                      />
                    </div>

                    {/* Build Command */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Build Command</label>
                      <input
                        type="text"
                        value={app.build ?? ''}
                        onChange={(e) => updateApp(name, 'build', e.target.value || undefined)}
                        disabled={readOnly}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                        placeholder="npm run build"
                      />
                    </div>

                    {/* Output Directory */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Output Directory</label>
                      <input
                        type="text"
                        value={app.output ?? ''}
                        onChange={(e) => updateApp(name, 'output', e.target.value || undefined)}
                        disabled={readOnly}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                        placeholder="dist"
                      />
                    </div>

                    {/* Framework */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Framework</label>
                      <input
                        type="text"
                        value={app.framework ?? ''}
                        onChange={(e) => updateApp(name, 'framework', e.target.value || undefined)}
                        disabled={readOnly}
                        className="w-full bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                        placeholder="nextjs, vite, react, etc."
                      />
                    </div>

                    {/* Env Vars */}
                    <div>
                      <label className="text-xs text-[var(--text)]/50 block mb-1">Environment Variables</label>
                      <div className="space-y-2">
                        {Object.entries(app.env || {}).map(([key, value]) => (
                          <div key={key} className="flex gap-2">
                            <input
                              type="text"
                              value={key}
                              disabled
                              className="w-1/3 bg-[var(--background)] border border-white/10 rounded-lg px-3 py-1.5 text-xs text-[var(--text)] font-mono disabled:opacity-70"
                            />
                            <input
                              type="text"
                              value={value}
                              onChange={(e) => updateEnvVar(name, key, e.target.value)}
                              disabled={readOnly}
                              className="flex-1 bg-[var(--background)] border border-white/10 rounded-lg px-3 py-1.5 text-xs text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none disabled:opacity-50"
                            />
                            {!readOnly && (
                              <button
                                onClick={() => removeEnvVar(name, key)}
                                className="p-1 text-red-400/60 hover:text-red-400"
                              >
                                <Trash size={12} />
                              </button>
                            )}
                          </div>
                        ))}
                        {!readOnly && (
                          <EnvVarAdder onAdd={(k, v) => updateEnvVar(name, k, v)} />
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {/* Add App */}
          {!readOnly && (
            <div className="flex gap-2">
              <input
                type="text"
                value={newAppName}
                onChange={(e) => setNewAppName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addApp()}
                placeholder="App name (e.g., backend)"
                className="flex-1 bg-[var(--background)] border border-white/10 rounded-lg px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)]/50 focus:outline-none"
              />
              <button
                onClick={addApp}
                className="px-3 py-2 bg-[rgba(var(--primary-rgb),0.15)] text-[var(--primary)] rounded-lg text-sm font-medium hover:bg-[rgba(var(--primary-rgb),0.25)] transition-colors flex items-center gap-1"
              >
                <Plus size={14} /> Add
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Infrastructure Section */}
      <div>
        <h3 className="text-sm font-semibold text-[var(--text)] mb-3 uppercase tracking-wider">
          Infrastructure
        </h3>
        <div className="space-y-2">
          {Object.entries(config.infrastructure).map(([name, infra]) => (
            <div
              key={name}
              className="flex items-center justify-between bg-[var(--surface)] border border-white/5 rounded-xl px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-blue-500/10 rounded-lg flex items-center justify-center text-blue-400 text-xs font-bold uppercase">
                  {name.slice(0, 2)}
                </div>
                <div>
                  <span className="font-medium text-[var(--text)] text-sm">{name}</span>
                  <span className="text-xs text-[var(--text)]/40 ml-2">{infra.image}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--text)]/40">:{infra.port}</span>
                {!readOnly && (
                  <button
                    onClick={() => removeInfra(name)}
                    className="p-1 text-red-400/60 hover:text-red-400 transition-colors"
                  >
                    <Trash size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Add Infrastructure */}
          {!readOnly && (
            <div>
              {showAddInfra ? (
                <div className="bg-[var(--surface)] border border-white/5 rounded-xl p-3 space-y-2">
                  <p className="text-xs text-[var(--text)]/50 mb-2">Select a service:</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {Object.entries(INFRA_CATALOG)
                      .filter(([slug]) => !config.infrastructure[slug])
                      .map(([slug, info]) => (
                        <button
                          key={slug}
                          onClick={() => addInfra(slug)}
                          className="text-left px-3 py-2 bg-[var(--background)] border border-white/5 rounded-lg hover:border-[var(--primary)]/30 transition-colors"
                        >
                          <span className="text-sm font-medium text-[var(--text)] capitalize">{slug}</span>
                          <span className="text-[10px] text-[var(--text)]/40 block">{info.image}</span>
                        </button>
                      ))}
                  </div>
                  <button
                    onClick={() => setShowAddInfra(false)}
                    className="text-xs text-[var(--text)]/40 hover:text-[var(--text)]/60"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowAddInfra(true)}
                  className="w-full px-3 py-2 border border-dashed border-white/10 rounded-xl text-sm text-[var(--text)]/50 hover:border-white/20 hover:text-[var(--text)]/70 transition-colors flex items-center justify-center gap-1"
                >
                  <Plus size={14} /> Add Infrastructure
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Inline component for adding a new env var */
function EnvVarAdder({ onAdd }: { onAdd: (key: string, value: string) => void }) {
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');

  const handleAdd = () => {
    if (!key.trim()) return;
    onAdd(key.trim(), value);
    setKey('');
    setValue('');
  };

  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        placeholder="KEY"
        className="w-1/3 bg-[var(--background)] border border-dashed border-white/10 rounded-lg px-3 py-1.5 text-xs text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none"
      />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
        placeholder="value"
        className="flex-1 bg-[var(--background)] border border-dashed border-white/10 rounded-lg px-3 py-1.5 text-xs text-[var(--text)] font-mono focus:border-[var(--primary)]/50 focus:outline-none"
      />
      <button
        onClick={handleAdd}
        disabled={!key.trim()}
        className="px-2 py-1 text-[var(--primary)] text-xs hover:bg-[rgba(var(--primary-rgb),0.1)] rounded disabled:opacity-30"
      >
        <Plus size={12} />
      </button>
    </div>
  );
}
