export type VolumeState = 'legacy' | 'provisioning' | 'local' | 'remote_only' | 'restoring';
export type ComputeTier = 'none' | 'ephemeral' | 'environment';

export function getFeatures(volumeState: VolumeState, computeTier: ComputeTier) {
  return {
    fileBrowser:   volumeState === 'local',
    editor:        volumeState === 'local',
    agentChat:     volumeState === 'local',
    terminal:      computeTier === 'environment',
    preview:       computeTier === 'environment',
    startButton:   (volumeState === 'local' || volumeState === 'remote_only') && computeTier === 'none',
    stopButton:    computeTier === 'environment',
    restoreNotice: volumeState === 'remote_only' || volumeState === 'restoring',
  };
}
