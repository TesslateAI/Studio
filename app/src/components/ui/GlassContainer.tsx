import { type ReactNode } from 'react';

interface GlassContainerProps {
  children: ReactNode;
  className?: string;
  blur?: 'light' | 'medium' | 'heavy';
}

const blurLevels = {
  light: 'backdrop-blur-sm',
  medium: 'backdrop-blur-md',
  heavy: 'backdrop-blur-xl',
};

export function GlassContainer({
  children,
  className = '',
  blur = 'medium'
}: GlassContainerProps) {
  return (
    <div
      className={`
        bg-gradient-to-br from-[hsl(var(--hue1)_30%_10%_/_0.7)] to-[hsl(var(--hue2)_30%_10%_/_0.7)]
        ${blurLevels[blur]}
        saturate-180
        border border-white/12
        shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(255,255,255,0.1)]
        rounded-3xl
        ${className}
      `.trim()}
    >
      {children}
    </div>
  );
}
