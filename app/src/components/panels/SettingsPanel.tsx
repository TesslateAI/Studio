import { useState } from 'react';
import { Lock, LockOpen } from 'lucide-react';
import { ToggleSwitch } from '../ui/ToggleSwitch';

interface SettingsPanelProps {
  projectId: number;
  onLockToggle?: (locked: boolean) => void;
}

export function SettingsPanel({ projectId, onLockToggle }: SettingsPanelProps) {
  const [projectName, setProjectName] = useState('My Awesome App');
  const [autoSave, setAutoSave] = useState(true);
  const [formatOnSave, setFormatOnSave] = useState(true);
  const [theme, setTheme] = useState('dark');
  const [fontSize, setFontSize] = useState(14);
  const [locked, setLocked] = useState(false);

  const handleLockToggle = () => {
    const newLocked = !locked;
    setLocked(newLocked);
    onLockToggle?.(newLocked);
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* General Settings */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">GENERAL</h3>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Project Name</span>
          <input
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1 text-sm outline-none focus:border-[var(--primary)] text-white"
          />
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Auto Save</span>
          <ToggleSwitch active={autoSave} onChange={setAutoSave} />
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Format on Save</span>
          <ToggleSwitch active={formatOnSave} onChange={setFormatOnSave} />
        </div>
      </div>

      {/* Appearance Settings */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">APPEARANCE</h3>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Theme</span>
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1 text-sm outline-none text-white"
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="auto">Auto</option>
          </select>
        </div>
        <div className="setting-item flex justify-between items-center py-3 text-gray-200">
          <span>Font Size</span>
          <input
            type="range"
            min="12"
            max="20"
            value={fontSize}
            onChange={(e) => setFontSize(parseInt(e.target.value))}
            className="w-32"
          />
          <span className="text-sm text-gray-500">{fontSize}px</span>
        </div>
      </div>

      {/* Panel Lock */}
      <div className="panel-section p-6">
        <button
          onClick={handleLockToggle}
          className="w-full py-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          {locked ? <Lock className="w-4 h-4" /> : <LockOpen className="w-4 h-4" />}
          {locked ? 'Panel Locked' : 'Lock Panel'}
        </button>
      </div>
    </div>
  );
}
