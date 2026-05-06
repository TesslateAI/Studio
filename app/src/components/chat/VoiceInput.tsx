import { useCallback, useEffect, useState } from 'react';
import { useAsr } from '../../hooks/useAsr';
import { findModel, getModelId, grantConsent, hasConsent } from '../../lib/asr-prefs';
import { AsrSetupModal } from './AsrSetupModal';
import { MicButton } from './MicButton';
import { RecordingPanel } from './RecordingPanel';

interface VoiceInputProps {
  /** Called with the cleaned (or raw, if cleanup off/failed) transcript on stop. */
  onTranscript: (text: string) => void;
  /** Disable the mic (e.g., during agent execution). */
  disabled?: boolean;
}

export function VoiceInput({ onTranscript, disabled = false }: VoiceInputProps) {
  const [showSetup, setShowSetup] = useState(false);
  const [modelEntry, setModelEntry] = useState(() => findModel(getModelId()));

  const asr = useAsr({ onTranscript });

  // Refresh the displayed model when the user changes their selection in
  // Settings (only when not actively in a setup flow).
  useEffect(() => {
    if (!showSetup && asr.status === 'idle') {
      setModelEntry(findModel(getModelId()));
    }
  }, [showSetup, asr.status]);

  // Auto-close the setup modal once the model is loaded and recording starts.
  // We never close it manually right after consent — the user must see the
  // download progress bar fill in for big first-run downloads.
  useEffect(() => {
    if (showSetup && (asr.status === 'recording' || asr.status === 'ready')) {
      setShowSetup(false);
    }
  }, [showSetup, asr.status]);

  const handleClick = useCallback(() => {
    if (disabled) return;
    if (asr.status === 'recording') {
      asr.stop();
      return;
    }
    if (asr.status === 'finalizing' || asr.status === 'loading') return;
    if (!hasConsent()) {
      setModelEntry(findModel(getModelId()));
      setShowSetup(true);
      return;
    }
    void asr.start();
  }, [asr, disabled]);

  const handleConfirmSetup = useCallback(() => {
    grantConsent();
    void asr.start();
    // Modal stays open until status flips to 'recording' (see effect above).
  }, [asr]);

  const handleCancelRecording = useCallback(() => {
    asr.cancel();
  }, [asr]);

  const isLoading = asr.status === 'loading';
  const isRecording = asr.status === 'recording';
  const isFinalizing = asr.status === 'finalizing';
  const showPanel = isRecording || isFinalizing;

  return (
    <>
      <MicButton
        onClick={handleClick}
        isRecording={isRecording}
        isFinalizing={isFinalizing}
        isLoading={isLoading}
        disabled={disabled || isLoading}
      />
      <AsrSetupModal
        isOpen={showSetup}
        model={modelEntry}
        progress={asr.progress}
        isLoading={isLoading}
        error={asr.error}
        onConfirm={handleConfirmSetup}
        onClose={() => setShowSetup(false)}
      />
      <RecordingPanel
        isOpen={showPanel}
        isFinalizing={isFinalizing}
        partialTranscript={asr.partialTranscript}
        level={asr.level}
        elapsedMs={asr.elapsedMs}
        device={asr.device}
        onStop={asr.stop}
        onCancel={handleCancelRecording}
      />
    </>
  );
}
