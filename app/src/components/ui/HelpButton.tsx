import { useState } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { useTheme } from '../../theme/ThemeContext';
import { KeyboardShortcutsModal } from '../KeyboardShortcutsModal';

interface HelpButtonProps {
  className?: string;
}

export function HelpButton({ className = '' }: HelpButtonProps) {
  const [showShortcuts, setShowShortcuts] = useState(false);
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // Trigger with "?" key (shift+/)
  useHotkeys(
    'shift+/',
    (e) => {
      // Don't trigger when typing in inputs
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }
      e.preventDefault();
      setShowShortcuts(true);
    },
    {
      preventDefault: false,
      enableOnFormTags: false,
    }
  );

  return (
    <>
      <button
        onClick={() => setShowShortcuts(true)}
        className={`
          p-2 rounded-lg transition-colors
          ${isDark ? 'bg-white/10 hover:bg-white/15 text-white/60 hover:text-white/80' : 'bg-black/5 hover:bg-black/10 text-black/60 hover:text-black/80'}
          ${className}
        `}
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
      >
        <span className="font-mono text-sm font-medium">?</span>
      </button>

      <KeyboardShortcutsModal open={showShortcuts} onClose={() => setShowShortcuts(false)} />
    </>
  );
}

export default HelpButton;
