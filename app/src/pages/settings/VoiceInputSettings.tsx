import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import {
  ASR_MODELS,
  clearModelCache,
  getCleanupModel,
  getModelId,
  hasConsent,
  setCleanupModel,
  setModelId,
  subscribe,
  type AsrModelId,
} from '../../lib/asr-prefs';

export default function VoiceInputSettings() {
  const [model, setModel] = useState<AsrModelId>(() => getModelId());
  const [cleanupModel, setCleanupModelState] = useState<string>(() => getCleanupModel() ?? '');
  const [cleanupDraft, setCleanupDraft] = useState<string>(() => getCleanupModel() ?? '');
  const [consent, setConsent] = useState<boolean>(() => hasConsent());
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    return subscribe(() => {
      setModel(getModelId());
      const next = getCleanupModel() ?? '';
      setCleanupModelState(next);
      setCleanupDraft(next);
      setConsent(hasConsent());
    });
  }, []);

  const handleModelChange = (id: AsrModelId) => {
    setModelId(id);
    toast.success(`Voice model set to ${ASR_MODELS.find((m) => m.id === id)?.label ?? id}`);
  };

  const handleCleanupSave = () => {
    const next = cleanupDraft.trim();
    setCleanupModel(next);
    if (next) {
      toast.success(`Cleanup pass enabled with "${next}"`);
    } else {
      toast.success('Cleanup pass disabled — raw transcripts will land in the chat input');
    }
  };

  const handleCleanupClear = () => {
    setCleanupModel('');
    setCleanupDraft('');
  };

  const handleClearCache = async () => {
    setClearing(true);
    try {
      await clearModelCache();
      toast.success('Downloaded voice models cleared. They will re-download on next use.');
    } catch (err) {
      toast.error(`Failed to clear: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setClearing(false);
    }
  };

  const selectedModel = ASR_MODELS.find((m) => m.id === model) ?? ASR_MODELS[0];
  const cleanupActive = Boolean(cleanupModel);
  const draftDirty = cleanupDraft.trim() !== cleanupModel;

  return (
    <SettingsSection
      title="Voice input"
      description="Dictate chat messages with on-device speech recognition. Audio never leaves your computer."
    >
      <SettingsGroup title="Privacy">
        <SettingsItem
          label="On-device transcription"
          description="The speech model runs entirely in your browser using WebGPU (or WebAssembly fallback). Microphone audio is never uploaded."
          control={
            <span className="text-[11px] text-[var(--text-subtle)]">
              {consent ? 'Enabled' : 'Will prompt on first use'}
            </span>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Speech model">
        <SettingsItem
          label="Speech model"
          description={selectedModel.description + ` Approximate download: ${selectedModel.sizeMb} MB.`}
          control={
            <select
              value={model}
              onChange={(e) => handleModelChange(e.target.value as AsrModelId)}
              className="bg-[var(--surface)] border border-[var(--border)] rounded-md px-3 py-1.5 text-xs text-[var(--text)] focus:outline-none focus:border-[var(--primary)] min-w-[180px]"
            >
              {ASR_MODELS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} (~{m.sizeMb} MB)
                </option>
              ))}
            </select>
          }
        />
        <SettingsItem
          label="Clear downloaded models"
          description="Removes cached model weights from your browser. Re-downloads on next mic click."
          control={
            <button
              type="button"
              onClick={handleClearCache}
              disabled={clearing}
              className="bg-white/5 border border-white/10 text-[var(--text)] px-3 py-1.5 rounded-md text-xs hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {clearing ? 'Clearing…' : 'Clear cache'}
            </button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Transcript cleanup (optional)">
        <SettingsItem
          label="Cleanup model"
          description="Optional. Pick an LLM your account can call (e.g. claude-haiku-4-5) to fix punctuation, casing, and remove filler words after dictation. Leave blank to send the raw transcript to the chat input. Only the transcript text is forwarded — never audio."
          control={
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={cleanupDraft}
                onChange={(e) => setCleanupDraft(e.target.value)}
                placeholder="model id (blank = off)"
                className="bg-[var(--surface)] border border-[var(--border)] rounded-md px-3 py-1.5 text-xs text-[var(--text)] focus:outline-none focus:border-[var(--primary)] min-w-[200px]"
                spellCheck={false}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={handleCleanupSave}
                disabled={!draftDirty}
                className="bg-[var(--primary)] disabled:bg-white/5 disabled:text-[var(--text-subtle)] text-white px-3 py-1.5 rounded-md text-xs font-medium transition-all disabled:cursor-not-allowed"
              >
                Save
              </button>
              {cleanupActive && (
                <button
                  type="button"
                  onClick={handleCleanupClear}
                  className="bg-white/5 border border-white/10 text-[var(--text)] px-3 py-1.5 rounded-md text-xs hover:bg-white/10 transition-all"
                >
                  Disable
                </button>
              )}
            </div>
          }
        />
        <SettingsItem
          label="Status"
          description={
            cleanupActive
              ? `Active — using "${cleanupModel}" for cleanup. Raw text falls through if the call fails or times out.`
              : 'Disabled — no cleanup pass runs. Raw transcripts are written straight into the chat input.'
          }
          control={
            <span
              className={`text-[11px] font-medium ${
                cleanupActive ? 'text-emerald-400' : 'text-[var(--text-subtle)]'
              }`}
            >
              {cleanupActive ? 'On' : 'Off'}
            </span>
          }
        />
      </SettingsGroup>
    </SettingsSection>
  );
}
