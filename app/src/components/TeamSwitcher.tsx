import { useState, useRef, useEffect } from 'react';
import { useTeam } from '../contexts/TeamContext';
import { CaretDown } from '@phosphor-icons/react';

export function TeamSwitcher() {
  const { activeTeam, teams, switchTeam } = useTeam();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!activeTeam) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md hover:bg-white/5 transition-colors text-sm w-full"
      >
        <div className="w-5 h-5 rounded bg-white/10 flex items-center justify-center text-[10px] font-semibold">
          {activeTeam.name.charAt(0).toUpperCase()}
        </div>
        <span className="truncate flex-1 text-left text-[var(--text)]">{activeTeam.name}</span>
        <CaretDown size={12} className="opacity-40 flex-shrink-0" />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 w-full bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg shadow-xl z-50 py-1 min-w-[200px]">
          {teams.map((team) => (
            <button
              key={team.id}
              onClick={() => {
                switchTeam(team.slug);
                setOpen(false);
              }}
              className={`flex items-center gap-2 px-3 py-2 w-full text-left text-sm hover:bg-white/5 transition-colors ${
                team.slug === activeTeam.slug ? 'text-[var(--accent)] bg-white/5' : 'text-[var(--text)]'
              }`}
            >
              <div className="w-5 h-5 rounded bg-white/10 flex items-center justify-center text-[10px] font-semibold flex-shrink-0">
                {team.name.charAt(0).toUpperCase()}
              </div>
              <span className="truncate">{team.name}</span>
              {team.is_personal && (
                <span className="text-[10px] opacity-40 ml-auto flex-shrink-0">Personal</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
