import type { VolumeState, ComputeTier } from '../../types/project';

export type EnvironmentStatus =
  | 'running'
  | 'agent_active'
  | 'files_ready'
  | 'provisioning'
  | 'restoring'
  | 'hibernated'
  | 'stopping'
  | 'starting';

export interface StatusConfig {
  label: string;
  tooltip: string;
  className: string;
  textColor: string;
  dotColor?: string;
  spin?: boolean;
}

export const STATUS_MAP: Record<EnvironmentStatus, StatusConfig> = {
  running: {
    label: 'Running',
    tooltip: 'Environment is active and serving requests',
    className: 'bg-emerald-500/10 border-emerald-500/20',
    textColor: 'text-emerald-400',
    dotColor: 'bg-emerald-400',
  },
  agent_active: {
    label: 'Agent active',
    tooltip: 'An agent is running commands in this project.',
    className: 'bg-yellow-500/10 border-yellow-500/20',
    textColor: 'text-yellow-400',
    spin: true,
  },
  files_ready: {
    label: 'Files ready',
    tooltip: 'Files are ready. Start the environment for preview and terminal.',
    className: 'bg-cyan-500/10 border-cyan-500/20',
    textColor: 'text-cyan-400',
    dotColor: 'bg-cyan-400',
  },
  provisioning: {
    label: 'Provisioning...',
    tooltip: 'Project storage is being set up.',
    className: 'bg-purple-500/10 border-purple-500/20',
    textColor: 'text-purple-400',
    spin: true,
  },
  restoring: {
    label: 'Restoring...',
    tooltip: 'Project files are being restored from storage.',
    className: 'bg-cyan-500/10 border-cyan-500/20',
    textColor: 'text-cyan-400',
    spin: true,
  },
  hibernated: {
    label: 'Hibernated',
    tooltip: 'Environment is hibernated. Start it to access preview and terminal.',
    className: 'bg-blue-500/10 border-blue-500/20',
    textColor: 'text-blue-400',
    dotColor: 'bg-blue-400',
  },
  stopping: {
    label: 'Hibernating',
    tooltip: 'Environment is shutting down. Preview may show errors until hibernation completes.',
    className: 'bg-amber-500/10 border-amber-500/30',
    textColor: 'text-amber-400',
    spin: true,
  },
  starting: {
    label: 'Starting',
    tooltip: 'Environment is starting up. Preview will be available shortly.',
    className: 'bg-yellow-500/10 border-yellow-500/20',
    textColor: 'text-yellow-400',
    spin: true,
  },
};

/** Derive environment status from the two-axis model + optional transient flags. */
export function getEnvironmentStatus(
  volumeState: VolumeState,
  computeTier: ComputeTier,
  options?: { stopping?: boolean; starting?: boolean }
): EnvironmentStatus | null {
  // Transient WS/UI-driven states (highest priority)
  if (options?.stopping) return 'stopping';
  if (options?.starting) return 'starting';

  // Two-axis model
  if (computeTier === 'environment') return 'running';
  if (computeTier === 'ephemeral') return 'agent_active';

  // computeTier === 'none'
  switch (volumeState) {
    case 'restoring':
      return 'restoring';
    case 'provisioning':
      return 'provisioning';
    case 'remote_only':
      return 'hibernated';
    case 'local':
      return 'files_ready';
    default:
      return null; // 'legacy' — no badge
  }
}
