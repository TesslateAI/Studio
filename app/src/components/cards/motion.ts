import type { Variants, Transition } from 'framer-motion';

export const cardSpring: Transition = {
  type: 'spring',
  stiffness: 400,
  damping: 30,
};

export const cardEntrance: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: cardSpring },
};

export const featuredEntrance: Variants = {
  initial: { opacity: 0, y: 16, scale: 0.98 },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 300, damping: 28 },
  },
};

export const hoverLift = {
  whileHover: { y: -3, transition: cardSpring },
};

export const staggerContainer: Variants = {
  animate: {
    transition: {
      staggerChildren: 0.05,
    },
  },
};

export const staggerItem: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: cardSpring },
};
