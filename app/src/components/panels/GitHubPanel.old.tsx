import { useState } from 'react';
import { GitBranch, Download, FileCode, PlusCircle, Trash } from 'lucide-react';
import { ToggleSwitch } from '../ui/ToggleSwitch';

interface GitHubPanelProps {
  projectId: number;
}

interface Secret {
  key: string;
  value: string;
}

export function GitHubPanel({ projectId }: GitHubPanelProps) {
  const [repository, setRepository] = useState('user/my-app');
  const [branch, setBranch] = useState('main');
  const [twoWaySync, setTwoWaySync] = useState(true);
  const [autoCommit, setAutoCommit] = useState(true);
  const [secrets, setSecrets] = useState<Secret[]>([
    { key: 'OPENAI_API_KEY', value: '••••••••••••••••' },
    { key: 'DATABASE_URL', value: '••••••••••••••••' }
  ]);

  const initGithub = (mode: 'import' | 'template' | 'new') => {
    if (mode === 'import') {
      const url = prompt('Enter GitHub repository URL:');
      if (url) alert(`Importing from ${url}...`);
    } else if (mode === 'template') {
      alert('Opening marketplace templates...');
    } else if (mode === 'new') {
      const name = prompt('Enter new repository name:');
      if (name) alert(`Creating new repository: ${name}`);
    }
  };

  const addSecret = () => {
    const key = prompt('Enter secret key:');
    if (key) {
      const value = prompt('Enter secret value:');
      if (value) {
        setSecrets([...secrets, { key, value: '••••••••••••••••' }]);
      }
    }
  };

  const removeSecret = (key: string) => {
    setSecrets(secrets.filter(s => s.key !== key));
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* Project Source */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">PROJECT SOURCE</h3>
        <div className="space-y-2">
          <button
            onClick={() => initGithub('import')}
            className="w-full p-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-left transition-all"
          >
            <div className="flex items-center gap-3">
              <Download className="w-5 h-5" />
              <div>
                <div className="text-sm font-semibold text-white">Import from GitHub</div>
                <div className="text-xs text-gray-500">Clone existing repository</div>
              </div>
            </div>
          </button>
          <button
            onClick={() => initGithub('template')}
            className="w-full p-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-left transition-all"
          >
            <div className="flex items-center gap-3">
              <FileCode className="w-5 h-5" />
              <div>
                <div className="text-sm font-semibold text-white">Use Template</div>
                <div className="text-xs text-gray-500">Start from marketplace base</div>
              </div>
            </div>
          </button>
          <button
            onClick={() => initGithub('new')}
            className="w-full p-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-left transition-all"
          >
            <div className="flex items-center gap-3">
              <PlusCircle className="w-5 h-5" />
              <div>
                <div className="text-sm font-semibold text-white">Initialize New Repo</div>
                <div className="text-xs text-gray-500">Create and push to GitHub</div>
              </div>
            </div>
          </button>
        </div>
      </div>

      {/* Connected Repository */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">CONNECTED REPOSITORY</h3>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Repository</span>
          <span className="text-sm text-gray-500">{repository}</span>
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Branch</span>
          <select
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1 text-sm outline-none text-white"
          >
            <option value="main">main</option>
            <option value="develop">develop</option>
            <option value="feature/new-ui">feature/new-ui</option>
          </select>
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Two-Way Sync</span>
          <ToggleSwitch active={twoWaySync} onChange={setTwoWaySync} />
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Auto Commit</span>
          <ToggleSwitch active={autoCommit} onChange={setAutoCommit} />
        </div>
      </div>

      {/* Secrets Management */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">SECRETS MANAGEMENT</h3>
        <div className="space-y-2 mb-3">
          {secrets.map((secret) => (
            <div key={secret.key} className="p-3 bg-white/5 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-white">{secret.key}</span>
                <button
                  onClick={() => removeSecret(secret.key)}
                  className="text-xs text-red-400 hover:text-red-300 p-1"
                >
                  <Trash className="w-4 h-4" />
                </button>
              </div>
              <div className="text-xs text-gray-500">{secret.value}</div>
            </div>
          ))}
        </div>
        <button
          onClick={addSecret}
          className="w-full py-2 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-sm font-medium transition-all"
        >
          <PlusCircle className="inline w-4 h-4 mr-2" />
          Add Secret
        </button>
        <div className="mt-3 text-xs text-gray-500">
          <i className="inline-block mr-1">ℹ️</i>
          Secrets are encrypted and synced to your account
        </div>
      </div>

      {/* Recent Commits */}
      <div className="panel-section p-6">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">RECENT COMMITS</h3>
        <div className="space-y-3">
          <div className="p-3 bg-white/5 rounded-lg">
            <div className="text-sm text-white mb-1">Updated hero component</div>
            <div className="text-xs text-gray-500">2 minutes ago</div>
          </div>
          <div className="p-3 bg-white/5 rounded-lg">
            <div className="text-sm text-white mb-1">Fixed responsive layout</div>
            <div className="text-xs text-gray-500">1 hour ago</div>
          </div>
        </div>
      </div>
    </div>
  );
}
