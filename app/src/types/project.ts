export type ComputeTier = 'none' | 'ephemeral' | 'environment';

export function getFeatures(computeTier: ComputeTier) {
  return {
    fileBrowser: true,
    editor: true,
    agentChat: true,
    terminal: computeTier === 'environment',
    preview: computeTier === 'environment',
    startButton: computeTier === 'none',
    stopButton: computeTier === 'environment',
    restoreNotice: false,
  };
}
