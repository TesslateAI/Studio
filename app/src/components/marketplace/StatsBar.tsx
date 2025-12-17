import React from 'react';
import { Lightning, Tag } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { formatInstalls } from './AgentCard';

interface StatsBarProps {
  usageCount: number;
  category?: string;
}

export function StatsBar({ usageCount, category }: StatsBarProps) {
  const { theme } = useTheme();

  return (
    <div className={`
      flex flex-wrap items-center gap-6 py-4 px-6 rounded-xl
      ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
    `}>
      {/* Uses Count */}
      <div className="flex items-center gap-2">
        <Lightning size={18} weight="fill" className="text-[var(--primary)]" />
        <div>
          <div className={`text-lg font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}>
            {formatInstalls(usageCount)}
          </div>
          <div className={`text-xs ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
            Uses
          </div>
        </div>
      </div>

      {/* Category */}
      {category && (
        <>
          <div className={`w-px h-10 ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'}`} />
          <div className="flex items-center gap-2">
            <Tag size={18} weight="bold" className={theme === 'light' ? 'text-black/40' : 'text-white/40'} />
            <div>
              <div className={`text-lg font-bold capitalize ${theme === 'light' ? 'text-black' : 'text-white'}`}>
                {category}
              </div>
              <div className={`text-xs ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                Category
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default StatsBar;
