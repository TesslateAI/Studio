import { Microphone, MicrophoneSlash } from '@phosphor-icons/react';

interface MicButtonProps {
  onClick: () => void;
  isRecording: boolean;
  isFinalizing: boolean;
  isLoading: boolean;
  disabled: boolean;
  title?: string;
}

export function MicButton({
  onClick,
  isRecording,
  isFinalizing,
  isLoading,
  disabled,
  title,
}: MicButtonProps) {
  const active = isRecording || isFinalizing;
  const tooltip =
    title ??
    (active
      ? 'Stop recording'
      : isLoading
        ? 'Loading speech model…'
        : 'Voice input — runs on your device');

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`btn btn-icon btn-sm ${active ? 'btn-active text-red-400' : ''}`}
      title={tooltip}
      aria-pressed={active}
      aria-label={tooltip}
    >
      {disabled && !active ? (
        <MicrophoneSlash size={14} weight="bold" />
      ) : (
        <Microphone size={14} weight={active ? 'fill' : 'bold'} />
      )}
    </button>
  );
}
