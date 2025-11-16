import { Check, AlertTriangle, Eye } from 'lucide-react';

export type EditMode = 'allow' | 'ask' | 'plan';

interface EditModeStatusProps {
  mode: EditMode;
  onModeChange: (mode: EditMode) => void;
  className?: string;
}

const modeConfig = {
  ask: {
    label: 'Ask Before Edit',
    icon: AlertTriangle,
    color: 'text-gray-400',
    bgColor: 'bg-gray-400/10',
    borderColor: 'border-gray-400/30',
    hoverBg: 'hover:bg-gray-400/20',
  },
  allow: {
    label: 'Allow All Edits',
    icon: Check,
    color: 'text-orange-400',
    bgColor: 'bg-orange-400/10',
    borderColor: 'border-orange-400/30',
    hoverBg: 'hover:bg-orange-400/20',
  },
  plan: {
    label: 'Plan Mode',
    icon: Eye,
    color: 'text-green-400',
    bgColor: 'bg-green-400/10',
    borderColor: 'border-green-400/30',
    hoverBg: 'hover:bg-green-400/20',
  },
} as const;

export function EditModeStatus({ mode, onModeChange, className = '' }: EditModeStatusProps) {
  const config = modeConfig[mode];
  const Icon = config.icon;

  const cycleMode = () => {
    const modes: EditMode[] = ['ask', 'allow', 'plan'];
    const currentIndex = modes.indexOf(mode);
    const nextIndex = (currentIndex + 1) % modes.length;
    onModeChange(modes[nextIndex]);
  };

  return (
    <div className={`flex items-center justify-center ${className}`}>
      <button
        onClick={cycleMode}
        className={`
          flex items-center gap-2 px-3 py-1.5 rounded-full
          border transition-all duration-200
          ${config.bgColor} ${config.borderColor} ${config.hoverBg}
          text-sm font-medium
        `}
        title="Click to cycle edit mode"
      >
        <Icon className={`w-4 h-4 ${config.color}`} />
        <span className={config.color}>{config.label}</span>
      </button>
    </div>
  );
}
