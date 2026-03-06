import { useTheme } from '../../theme/ThemeContext';

interface SkeletonCardProps {
  variant?: 'card' | 'featured';
}

export function SkeletonCard({ variant = 'card' }: SkeletonCardProps) {
  const { theme } = useTheme();

  const bgBase = theme === 'light' ? 'bg-black/5' : 'bg-white/5';
  const bgPulse = theme === 'light' ? 'bg-black/10' : 'bg-white/10';

  if (variant === 'featured') {
    return (
      <div
        className={`
          animate-pulse rounded-2xl border overflow-hidden p-4 md:p-6
          ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
        `}
      >
        <div className="flex flex-col md:flex-row gap-4 md:gap-6">
          {/* Icon */}
          <div className={`w-20 h-20 md:w-24 md:h-24 rounded-2xl flex-shrink-0 ${bgBase}`} />

          {/* Content */}
          <div className="flex-1 space-y-3">
            {/* Title */}
            <div className={`h-5 w-48 rounded ${bgPulse}`} />
            {/* Creator */}
            <div className={`h-3 w-24 rounded ${bgBase}`} />

            {/* Description lines */}
            <div className="space-y-2">
              <div className={`h-3.5 w-full rounded ${bgBase}`} />
              <div className={`h-3.5 w-3/4 rounded ${bgBase}`} />
            </div>

            {/* Metadata pills */}
            <div className="flex items-center gap-2 pt-1">
              <div className={`h-4 w-16 rounded ${bgBase}`} />
              <div className={`h-4 w-12 rounded ${bgBase}`} />
              <div className={`h-4 w-14 rounded ${bgBase}`} />
            </div>

            {/* Button */}
            <div className={`h-9 w-24 rounded-xl ${bgPulse}`} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`
        animate-pulse flex flex-col p-4 rounded-xl border
        ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
      `}
    >
      {/* Header: Icon + Name + Creator */}
      <div className="flex items-start gap-3 mb-2">
        <div className={`w-10 h-10 rounded-xl flex-shrink-0 ${bgBase}`} />
        <div className="flex-1 space-y-1.5">
          <div className={`h-4 w-3/4 rounded ${bgPulse}`} />
          <div className={`h-3 w-20 rounded ${bgBase}`} />
        </div>
      </div>

      {/* Description */}
      <div className="space-y-2 mb-3">
        <div className={`h-3 w-full rounded ${bgBase}`} />
        <div className={`h-3 w-2/3 rounded ${bgBase}`} />
      </div>

      {/* Metadata pills */}
      <div className="flex items-center gap-1.5 mb-3">
        <div className={`h-4 w-14 rounded ${bgBase}`} />
        <div className={`h-4 w-10 rounded ${bgBase}`} />
        <div className={`h-4 w-12 rounded ${bgBase}`} />
      </div>

      {/* Footer */}
      <div className="mt-auto pt-3 border-t border-white/5">
        <div className="flex items-center justify-end">
          <div className={`h-7 w-16 rounded-lg ${bgPulse}`} />
        </div>
      </div>
    </div>
  );
}

export default SkeletonCard;
