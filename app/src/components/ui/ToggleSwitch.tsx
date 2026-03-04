interface ToggleSwitchProps {
  active: boolean;
  onChange: (active: boolean) => void;
  disabled?: boolean;
}

export function ToggleSwitch({ active, onChange, disabled = false }: ToggleSwitchProps) {
  return (
    <button
      onClick={() => !disabled && onChange(!active)}
      disabled={disabled}
      className={`
        toggle-switch relative
        w-12 h-6 rounded-full
        transition-all duration-300
        ${active ? 'bg-[var(--primary)]' : 'bg-white/10'}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      <div
        className={`
          absolute top-0.5 w-5 h-5
          bg-white rounded-full
          transition-all duration-300
          ${active ? 'left-[26px]' : 'left-0.5'}
        `}
      />
    </button>
  );
}
