export type VolumeState = 'legacy' | 'provisioning' | 'local' | 'remote_only' | 'restoring';
export type ComputeTier = 'none' | 'ephemeral' | 'environment';

export function isV2Project(volumeState: string | undefined): boolean {
  return volumeState !== undefined && volumeState !== 'legacy';
}

export function getV2Features(volumeState: VolumeState, computeTier: ComputeTier) {
  return {
    fileBrowser:   volumeState === 'local',
    editor:        volumeState === 'local',
    agentChat:     volumeState === 'local',
    terminal:      computeTier === 'environment',
    preview:       computeTier === 'environment',
    startButton:   volumeState === 'local' && computeTier === 'none',
    stopButton:    computeTier === 'environment',
    restoreNotice: volumeState === 'remote_only' || volumeState === 'restoring',
  };
}
