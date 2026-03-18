import type { ComputeTier } from '../../types/project';

export type EnvironmentStatus =
  | 'running'
  | 'agent_active'
  | 'files_ready'
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

/** Derive environment status from compute tier + optional transient flags. */
export function getEnvironmentStatus(
  computeTier: ComputeTier,
  options?: { stopping?: boolean; starting?: boolean }
): EnvironmentStatus | null {
  // Transient WS/UI-driven states (highest priority)
  if (options?.stopping) return 'stopping';
  if (options?.starting) return 'starting';

  // Compute tier based
  if (computeTier === 'environment') return 'running';
  if (computeTier === 'ephemeral') return 'agent_active';

  // computeTier === 'none'
  return 'files_ready';
}
