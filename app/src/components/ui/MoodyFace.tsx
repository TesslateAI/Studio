import { useEffect, useRef, useState, type CSSProperties } from 'react';

export type MoodyMood =
  | 'neutral'
  | 'happy'
  | 'sad'
  | 'angry'
  | 'worried'
  | 'surprised'
  | 'sleepy'
  | 'suspicious'
  | 'skeptical'
  | 'smug'
  | 'wink'
  | 'dead'
  | 'confused'
  | 'thinking';

interface EyeShape {
  w: number; // percent of face width
  h: number; // percent of face height
  rot: number; // degrees
  dy: number; // vertical offset as percent of face height
  side: number; // horizontal bias as percent of face width
}

interface MoodShape {
  left: EyeShape;
  right: EyeShape;
}

const BASE: EyeShape = { w: 18, h: 32, rot: 0, dy: 0, side: 0 };
const mk = (o: Partial<EyeShape> = {}): EyeShape => ({ ...BASE, ...o });

// Percentages are derived from the 280px reference face in the original mock
// (e.g. w:50 → 50/280 ≈ 18%). This keeps every eye scale-independent.
const MOODS: Record<MoodyMood, MoodShape> = {
  neutral: { left: mk(), right: mk() },
  happy: { left: mk({ w: 21, h: 12, dy: -1 }), right: mk({ w: 21, h: 12, dy: -1 }) },
  sad: { left: mk({ w: 14, h: 34, rot: -16, dy: 2 }), right: mk({ w: 14, h: 34, rot: -16, dy: 2 }) },
  angry: { left: mk({ w: 27, h: 10, rot: 22 }), right: mk({ w: 27, h: 10, rot: 22 }) },
  worried: { left: mk({ w: 16, h: 25, rot: -12 }), right: mk({ w: 16, h: 25, rot: -12 }) },
  surprised: { left: mk({ w: 30, h: 41, dy: -2 }), right: mk({ w: 30, h: 41, dy: -2 }) },
  sleepy: { left: mk({ w: 25, h: 4, dy: 4 }), right: mk({ w: 25, h: 4, dy: 4 }) },
  suspicious: { left: mk({ w: 16, h: 7, side: 6 }), right: mk({ w: 16, h: 7, side: 6 }) },
  skeptical: { left: mk({ w: 17, h: 30 }), right: mk({ w: 20, h: 6 }) },
  smug: { left: mk({ w: 20, h: 8, rot: 14, dy: -1 }), right: mk({ w: 20, h: 8, rot: 14, dy: -1 }) },
  wink: { left: mk({ w: 20, h: 30 }), right: mk({ w: 21, h: 2 }) },
  dead: { left: mk({ w: 32, h: 32 }), right: mk({ w: 32, h: 32 }) },
  confused: { left: mk({ w: 14, h: 25 }), right: mk({ w: 25, h: 11, rot: -10 }) },
  thinking: { left: mk({ w: 20, h: 20 }), right: mk({ w: 20, h: 20 }) },
};

const DEAD_MOOD: MoodyMood = 'dead';

interface MoodyFaceProps {
  size?: number;
  mood?: MoodyMood;
  /** Rounded corner radius as fraction of size (0–0.5). */
  radius?: number;
  /** Blink periodically. Disabled automatically on `prefers-reduced-motion`. */
  animate?: boolean;
  /** Nudge eyes toward pointer on desktop hover. Ignored on touch. */
  trackPointer?: boolean;
  className?: string;
  /** Overrides the eye color. Defaults to var(--sidebar-bg) for a cutout look. */
  eyeColor?: string;
}

/**
 * Tiny two-eye face icon distilled from the larger interactive mock.
 * Face body uses `currentColor`, so wrap it in a span with the desired
 * `text-[var(--…)]` class and it tracks your theme exactly.
 */
export function MoodyFace({
  size = 16,
  mood = 'neutral',
  radius = 0.14,
  animate = false,
  trackPointer = false,
  className = '',
  eyeColor = 'var(--text)',
}: MoodyFaceProps) {
  const faceRef = useRef<HTMLSpanElement>(null);
  const [blink, setBlink] = useState(false);
  const [pointerOffset, setPointerOffset] = useState({ x: 0, y: 0 });

  // Periodic blink — respects prefers-reduced-motion
  useEffect(() => {
    if (!animate) return;
    if (typeof window === 'undefined') return;
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq.matches) return;
    if (mood === DEAD_MOOD || mood === 'sleepy' || mood === 'wink') return;

    let mounted = true;
    const scheduleBlink = () => {
      if (!mounted) return;
      const wait = 2200 + Math.random() * 3200;
      const t = setTimeout(async () => {
        if (!mounted) return;
        setBlink(true);
        setTimeout(() => {
          if (!mounted) return;
          setBlink(false);
          scheduleBlink();
        }, 110);
      }, wait);
      return () => clearTimeout(t);
    };
    const cleanup = scheduleBlink();
    return () => {
      mounted = false;
      if (typeof cleanup === 'function') cleanup();
    };
  }, [animate, mood]);

  // Pointer tracking — desktop only, skipped on touch devices
  useEffect(() => {
    if (!trackPointer) return;
    if (typeof window === 'undefined') return;
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
    if (!fine.matches) return;

    const onMove = (e: PointerEvent) => {
      const el = faceRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      // Normalize against a soft 400px radius, cap to ±12% of face size
      const norm = (v: number) => Math.max(-1, Math.min(1, v / 400));
      setPointerOffset({ x: norm(dx) * 12, y: norm(dy) * 16 });
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [trackPointer]);

  const shape = MOODS[mood];

  const renderEye = (eye: EyeShape, which: 'left' | 'right') => {
    const w = (eye.w / 100) * size;
    const h = (eye.h / 100) * size;
    const baseGap = 0.18 * size; // horizontal gap from center
    const side = (eye.side / 100) * size;
    const dy = (eye.dy / 100) * size;
    const rotSign = which === 'left' ? 1 : -1;
    const cxBase = which === 'left' ? -baseGap : baseGap;
    const cx = cxBase + side + (pointerOffset.x * (which === 'left' ? 1 : 1)) / 2;
    const cy = dy + pointerOffset.y / 2;
    const blinkScale = blink ? 0.06 : 1;
    const transform = `translate(calc(-50% + ${cx}px), calc(-50% + ${cy}px)) rotate(${eye.rot * rotSign}deg) scaleY(${blinkScale})`;
    const style: CSSProperties = {
      position: 'absolute',
      top: '50%',
      left: '50%',
      width: `${w}px`,
      height: `${h}px`,
      background: eyeColor,
      transform,
      transformOrigin: 'center center',
      transition:
        'transform 160ms cubic-bezier(0.22, 1, 0.36, 1), width 200ms ease, height 200ms ease',
      borderRadius: '1px',
      pointerEvents: 'none',
    };
    return <span key={which} style={style} aria-hidden="true" />;
  };

  return (
    <span
      ref={faceRef}
      role="img"
      aria-label="Agent"
      className={`relative inline-block bg-current align-middle ${className}`}
      style={{
        width: `${size}px`,
        height: `${size}px`,
        borderRadius: `${radius * size}px`,
      }}
    >
      {renderEye(shape.left, 'left')}
      {renderEye(shape.right, 'right')}
    </span>
  );
}
