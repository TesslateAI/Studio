import { motion, type HTMLMotionProps } from 'framer-motion';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import { forwardRef, type ReactNode } from 'react';
import { cardEntrance, featuredEntrance, cardSpring } from './motion';

const surfaceVariants = cva(
  'group relative flex flex-col cursor-pointer transition-colors duration-200 ease-out',
  {
    variants: {
      variant: {
        standard:
          'bg-[var(--surface-hover)] border border-[var(--border)] rounded-2xl p-4 sm:p-5 hover:border-[rgba(var(--primary-rgb),0.25)] hover:shadow-[0_8px_30px_rgba(0,0,0,0.12)]',
        featured:
          'bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-4 sm:p-6 hover:border-[rgba(var(--primary-rgb),0.25)] hover:shadow-[0_8px_30px_rgba(0,0,0,0.12)]',
        stat:
          'bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-4 sm:p-5 overflow-hidden',
      },
    },
    defaultVariants: {
      variant: 'standard',
    },
  }
);

export interface CardSurfaceProps
  extends VariantProps<typeof surfaceVariants>,
    Omit<HTMLMotionProps<'div'>, 'children'> {
  children: ReactNode;
  isActive?: boolean;
  isDisabled?: boolean;
  disableHoverLift?: boolean;
  className?: string;
}

export const CardSurface = forwardRef<HTMLDivElement, CardSurfaceProps>(
  function CardSurface(
    { variant, isActive, isDisabled, disableHoverLift, children, className, ...props },
    ref
  ) {
    const entrance = variant === 'featured' ? featuredEntrance : cardEntrance;

    return (
      <motion.div
        ref={ref}
        variants={entrance}
        initial="initial"
        animate="animate"
        whileHover={disableHoverLift ? undefined : { y: -3, transition: cardSpring }}
        whileTap={{ scale: 0.98 }}
        className={clsx(
          surfaceVariants({ variant }),
          isActive && 'border-[var(--primary)] ring-1 ring-[var(--primary)]/20',
          isDisabled && 'opacity-50 pointer-events-none',
          className
        )}
        {...props}
      >
        {children}
      </motion.div>
    );
  }
);
