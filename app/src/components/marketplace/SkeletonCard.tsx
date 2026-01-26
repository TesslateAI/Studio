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
          animate-pulse rounded-xl border overflow-hidden
          ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
        `}
      >
        <div className="flex flex-col md:flex-row">
          {/* Image placeholder */}
          <div className={`w-full md:w-72 h-48 md:h-auto ${bgBase}`} />

          {/* Content */}
          <div className="flex-1 p-6 space-y-4">
            {/* Title */}
            <div className={`h-6 w-48 rounded ${bgPulse}`} />

            {/* Description lines */}
            <div className="space-y-2">
              <div className={`h-4 w-full rounded ${bgBase}`} />
              <div className={`h-4 w-3/4 rounded ${bgBase}`} />
            </div>

            {/* Footer */}
            <div className="flex items-center gap-4 pt-2">
              <div className={`h-4 w-24 rounded ${bgBase}`} />
              <div className={`h-4 w-16 rounded ${bgBase}`} />
              <div className={`h-4 w-20 rounded ${bgBase}`} />
            </div>
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
      {/* Icon */}
      <div className="mb-3">
        <div className={`w-12 h-12 rounded-xl ${bgBase}`} />
      </div>

      {/* Title */}
      <div className={`h-5 w-3/4 rounded mb-2 ${bgPulse}`} />

      {/* Description */}
      <div className="space-y-2 mb-3 min-h-[40px]">
        <div className={`h-3 w-full rounded ${bgBase}`} />
        <div className={`h-3 w-2/3 rounded ${bgBase}`} />
      </div>

      {/* Footer */}
      <div className="mt-auto pt-3 border-t border-white/5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Avatar */}
            <div className={`w-5 h-5 rounded-full ${bgBase}`} />
            {/* Name */}
            <div className={`h-3 w-16 rounded ${bgBase}`} />
            {/* Stats */}
            <div className={`h-3 w-12 rounded ${bgBase}`} />
          </div>
          {/* Button */}
          <div className={`h-7 w-16 rounded-lg ${bgPulse}`} />
        </div>
      </div>
    </div>
  );
}

export default SkeletonCard;
